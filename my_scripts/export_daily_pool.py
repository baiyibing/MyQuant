"""Export prediction TopN lists using the daily pool CSV contract.

Stage machine (eng-perf P1-5): ``predict_extended|train → pred artifact → export / sweep --pred-from``. This entry reads ``--pred`` only — never handler_init.

``--asof pred_minus_one`` writes ``pred[D]`` to the next prediction date's
file; ``--asof identity`` writes it to D's file.  The default is
``pred_minus_one`` (locked 2026-09-12).

The output intentionally has no stock-name column.  Consequently unnamed ST
stocks are assigned a board limit by code prefix (10%/20%/30%), not the 5% ST
limit; this validation window is not E-R2.

``--neutralize`` (M3-D) cross-section neutralizes the pred scores *before* the
TopN truncation.  It is off by default: without the flag the exported bytes
are bit-for-bit what they were.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# 共享 mlflow 逃生口 / 静音（与其它工作流入口对齐；本脚本本身不 import qlib）
import host_env  # noqa: E402,F401

import pandas as pd  # noqa: E402

from float_cap_gate import (  # noqa: E402
    AMOUNT_COLUMN,
    CLOSE_COLUMN,
    FLOAT_SHARE_COLUMN,
    derive_log_float_cap,
    verify_float_cap,
)
from ranking_neutralize import METHODS, load_industry_map, neutralize  # noqa: E402
from run_manifest import md5_file, write_export_manifest  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = REPO_ROOT / "exports" / "r2_pred_topn_20260302_20260323"
INSTRUMENT_RE = re.compile(r"^(?:SH|SZ|BJ)?(\d{6})$", re.IGNORECASE)
REQUIRED_COLUMNS = {"datetime", "instrument", "score"}


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser, exposed separately to make defaults testable."""
    parser = argparse.ArgumentParser(
        description=(
            "Export daily TopN pool CSVs. pred_minus_one maps pred[D] to "
            "next(D); identity maps pred[D] to D."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--pred", required=True, help="CSV or pickle prediction file")
    parser.add_argument("--topk", type=int, default=10, help="codes per output day")
    parser.add_argument(
        "--asof",
        choices=("pred_minus_one", "identity"),
        default="pred_minus_one",
        help="prediction-date to buy-date mapping",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="output directory (the default is resolved from the repository root)",
    )
    parser.add_argument(
        "--neutralize",
        choices=METHODS,
        default=None,
        help="cross-section neutralize scores before TopN (default: off)",
    )
    parser.add_argument(
        "--industry-map",
        type=Path,
        default=None,
        help="SW L1 map CSV (code_qlib,sw_l1) for --neutralize industry/both",
    )
    parser.add_argument(
        "--float-cap",
        type=Path,
        default=None,
        help=(
            "float cap CSV for --neutralize size/both: either "
            f"datetime,instrument,log_float_cap or the raw {CLOSE_COLUMN}/"
            f"{FLOAT_SHARE_COLUMN} fields, plus {AMOUNT_COLUMN} for the gate"
        ),
    )
    return parser


def load_predictions(path: Path) -> pd.DataFrame:
    """Load and normalize a contract CSV or MultiIndex pickle."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        # Preserve leading zeroes and the exact string used for tie-breaking.
        frame = pd.read_csv(path, dtype={"instrument": str})
    elif suffix in {".pkl", ".pickle"}:
        frame = pd.read_pickle(path)
        if not isinstance(frame, pd.DataFrame):
            raise ValueError("pickle must contain a pandas DataFrame")
        if not isinstance(frame.index, pd.MultiIndex) or frame.index.nlevels != 2:
            raise ValueError("pickle must have a two-level (datetime, instrument) MultiIndex")
        frame = frame.reset_index()
        index_columns = list(frame.columns[:2])
        frame = frame.rename(columns={index_columns[0]: "datetime", index_columns[1]: "instrument"})
    else:
        raise ValueError("--pred must end in .csv, .pkl, or .pickle")

    missing = sorted(REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        raise ValueError(f"prediction input missing column(s): {', '.join(missing)}")

    result = frame.loc[:, ["datetime", "instrument", "score"]].copy()
    result["datetime"] = pd.to_datetime(result["datetime"], errors="raise").dt.normalize()
    result["instrument"] = result["instrument"].astype(str)
    result["score"] = pd.to_numeric(result["score"], errors="raise")
    return result


def load_float_cap(path: Path) -> pd.DataFrame:
    """Load a cap panel, deriving ``log_float_cap`` from bin-16 fields if given."""
    frame = pd.read_csv(path, dtype={"instrument": str})
    if CLOSE_COLUMN in frame.columns and FLOAT_SHARE_COLUMN in frame.columns:
        return derive_log_float_cap(frame)
    missing = sorted({"datetime", "instrument", "log_float_cap"}.difference(frame.columns))
    if missing:
        raise ValueError(
            f"float cap input needs {CLOSE_COLUMN}+{FLOAT_SHARE_COLUMN} or a "
            f"log_float_cap column; missing: {', '.join(missing)}"
        )
    return frame


def apply_neutralization(
    predictions: pd.DataFrame,
    *,
    method: str | None,
    industry_map: Path | None = None,
    float_cap: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Neutralize scores before ranking; returns the frame and manifest config.

    ``method=None`` is the default path and returns the input untouched.  For
    ``size``/``both`` the derived cap has to clear :func:`verify_float_cap`
    first — a failing gate raises instead of falling back to a fit nobody
    verified (``--neutralize industry`` stays available).
    """
    if method is None:
        return predictions, {"neutralize": "none"}

    sw_l1 = None
    config: dict[str, Any] = {}
    if method in {"industry", "both"}:
        if industry_map is None:
            raise ValueError(f"--neutralize {method} requires --industry-map")
        sw_l1 = load_industry_map(industry_map)
        config["neutralize_industry_map"] = str(industry_map)

    caps = None
    if method in {"size", "both"}:
        if float_cap is None:
            raise ValueError(f"--neutralize {method} requires --float-cap")
        caps = load_float_cap(float_cap)
        gate = verify_float_cap(caps)
        config.update(gate.as_manifest_fields())
        config["neutralize_float_cap"] = str(float_cap)
        if not gate.passed:
            raise ValueError(gate.blocked_message())

    frame, report = neutralize(predictions, method, sw_l1=sw_l1, log_float_cap=caps)
    config.update(report.as_manifest_fields())
    return frame, config


def _safe_output_dir(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if "stock_pool" in resolved.parts:
        raise ValueError("refusing to write under a stock_pool path")
    scripts_dir = (REPO_ROOT / "my_scripts").resolve()
    if resolved == scripts_dir or scripts_dir in resolved.parents:
        raise ValueError("refusing to write into my_scripts")
    return resolved


def export_daily_pool(
    predictions: pd.DataFrame,
    out_dir: Path,
    *,
    topk: int = 10,
    asof: str = "pred_minus_one",
) -> tuple[list[Path], int]:
    """Write daily contract files and return (written paths, illegal count)."""
    if topk <= 0:
        raise ValueError("topk must be greater than zero")
    if asof not in {"pred_minus_one", "identity"}:
        raise ValueError(f"unsupported asof: {asof}")

    output = _safe_output_dir(Path(out_dir))
    written: list[Path] = []
    illegal_count = 0

    # eng-perf P1-7: one groupby instead of per-day full-table boolean scan.
    # Neutralize (if any) already ran in main() before this call — do not cache
    # post-neutralize ranks across configs.
    day_codes: dict[pd.Timestamp, list[str]] = {}
    dates: list[pd.Timestamp] = []
    for pred_date, day in predictions.groupby("datetime", sort=True):
        dates.append(pred_date)
        day = day.sort_values(
            ["score", "instrument"], ascending=[False, True], kind="mergesort"
        )
        ranked_codes: list[str] = []
        seen: set[str] = set()
        for instrument in day["instrument"]:
            match = INSTRUMENT_RE.fullmatch(instrument)
            if match is None:
                illegal_count += 1
                continue
            code = match.group(1)
            if code not in seen:
                seen.add(code)
                ranked_codes.append(code)
        day_codes[pred_date] = ranked_codes[:topk]

    for index, pred_date in enumerate(dates):
        if asof == "pred_minus_one":
            if index + 1 == len(dates):
                continue
            buy_date = dates[index + 1]
        else:
            buy_date = pred_date
        codes = day_codes[pred_date]
        if not codes:
            continue
        output.mkdir(parents=True, exist_ok=True)
        destination = output / f"{buy_date:%Y%m%d}.csv"
        destination.write_text(
            "".join(f"{code}\n" for code in codes), encoding="utf-8", newline="\n"
        )
        written.append(destination)

    return written, illegal_count


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pred_path = Path(args.pred).expanduser()
    if not pred_path.is_file():
        parser.error(f"prediction file does not exist: {pred_path}")
    try:
        predictions = load_predictions(pred_path)
        pred_rows = int(len(predictions))
        # M3-D: 中性化只改排序用的 score，必须在 TopN 截取之前。
        predictions, neutralize_config = apply_neutralization(
            predictions,
            method=args.neutralize,
            industry_map=args.industry_map,
            float_cap=args.float_cap,
        )
        written, illegal_count = export_daily_pool(
            predictions, args.out_dir, topk=args.topk, asof=args.asof
        )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        parser.error(str(exc))
    if illegal_count:
        print(f"dropped {illegal_count} illegal instrument(s)", file=sys.stderr)
    # M4-C: export run-manifest（pred md5 / asof / topk / 输出文件数）
    try:
        manifests_dir = REPO_ROOT / "manifests"
        write_export_manifest(
            manifests_dir=manifests_dir,
            config={
                "asof": args.asof,
                "topk": args.topk,
                "pred": str(pred_path),
                "pred_md5": md5_file(pred_path),
                "out_dir": str(Path(args.out_dir).expanduser()),
                "output_file_count": len(written),
                **neutralize_config,
            },
            pred_path=pred_path,
            out_dir=args.out_dir,
            output_file_count=len(written),
            pred_rows=pred_rows,
            data={
                "calendar_first": str(predictions["datetime"].min().date())
                if len(predictions)
                else None,
                "calendar_last": str(predictions["datetime"].max().date())
                if len(predictions)
                else None,
                "calendar_days": int(predictions["datetime"].nunique())
                if len(predictions)
                else 0,
            },
            repo_root=REPO_ROOT,
        )
    except Exception as exc:  # noqa: BLE001 — export success must not fail on manifest
        print(f"Failed to write export manifest: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
