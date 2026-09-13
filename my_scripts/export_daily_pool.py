"""Export prediction TopN lists using the daily pool CSV contract.

``--asof pred_minus_one`` writes ``pred[D]`` to the next prediction date's
file; ``--asof identity`` writes it to D's file.  The default is
``pred_minus_one`` (locked 2026-09-12).

The output intentionally has no stock-name column.  Consequently unnamed ST
stocks are assigned a board limit by code prefix (10%/20%/30%), not the 5% ST
limit; this validation window is not E-R2.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

# 共享 mlflow 逃生口 / 静音（与其它工作流入口对齐；本脚本本身不 import qlib）
import host_env  # noqa: F401

import pandas as pd

from run_manifest import write_export_manifest


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
    dates = sorted(predictions["datetime"].drop_duplicates().tolist())
    written: list[Path] = []
    illegal_count = 0

    day_codes: dict[pd.Timestamp, list[str]] = {}
    for pred_date in dates:
        day = predictions.loc[predictions["datetime"] == pred_date].copy()
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
                "out_dir": str(Path(args.out_dir).expanduser()),
                "output_file_count": len(written),
            },
            pred_path=pred_path,
            out_dir=args.out_dir,
            output_file_count=len(written),
            pred_rows=int(len(predictions)),
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
