# -*- coding: utf-8 -*-
"""M3-D: cross-section industry / size neutralization on the ranking side.

The pipeline position is fixed: ``pred 打分 → 截面中性化 → TopN → 导出``.
This module owns the middle step and nothing else — it rewrites the ``score``
column the exporter ranks on and never touches labels, features, the infer
chain, fills, ``--asof`` or the topk default.

The industry map is a *current-snapshot* classification
(``exports/m3d_industry/sw_l1_map.csv``).  Applying it to past windows carries
survivorship / reclassification bias: acceptable for ranking experiments, but
every writeup has to carry that footnote.

Bypass discipline (never silently drop a name from the ranking universe):

* an instrument with no industry mapping keeps its raw score and is counted;
* a row with a missing / non-finite log float cap keeps its raw score and is
  counted;
* a day whose cross-section cannot support a regression (too few usable rows
  or a degenerate cap) keeps every raw score for that day and is counted.
"""

from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

SCORE_COLUMNS = ("datetime", "instrument", "score")
METHODS = ("industry", "size", "both")

#: A size regression needs at least this many usable rows in the cross-section.
MIN_REGRESSION_ROWS = 3

_QLIB_RE = re.compile(r"^(SH|SZ|BJ)(\d{6})$")
_DOT_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")
_BARE_RE = re.compile(r"^(\d{6})$")


def to_qlib_code(code: Any) -> str | None:
    """Normalize an instrument to the qlib dialect used by pred / the map.

    ``SZ300190`` (qlib, already normal), ``300190.SZ`` (gildata/wind) and the
    bare ``300190`` that the pool contract emits all map to ``SZ300190``.
    Bare codes get their exchange from the number range: ``6`` and ``90`` are
    Shanghai, ``0``/``2``/``3`` Shenzhen, ``4``/``8``/``92`` Beijing.  Anything
    unrecognized returns ``None`` so callers can bypass instead of guessing.
    """
    if code is None:
        return None
    text = str(code).strip().upper()
    if not text:
        return None
    match = _QLIB_RE.fullmatch(text)
    if match is not None:
        return f"{match.group(1)}{match.group(2)}"
    match = _DOT_RE.fullmatch(text)
    if match is not None:
        return f"{match.group(2)}{match.group(1)}"
    match = _BARE_RE.fullmatch(text)
    if match is None:
        return None
    digits = match.group(1)
    if digits[0] == "6" or digits.startswith("90"):
        return f"SH{digits}"
    if digits[0] in {"0", "2", "3"}:
        return f"SZ{digits}"
    if digits[0] in {"4", "8"} or digits.startswith("92"):
        return f"BJ{digits}"
    return None


def to_bare_code(code: Any) -> str | None:
    """Strip the exchange prefix: ``SZ300190`` / ``300190.SZ`` → ``300190``."""
    qlib = to_qlib_code(code)
    return None if qlib is None else qlib[2:]


@dataclass(frozen=True)
class NeutralizeReport:
    """Bypass accounting for one neutralization run."""

    method: str
    rows: int = 0
    days: int = 0
    industry_bypass_rows: int = 0
    industry_bypass_instruments: tuple[str, ...] = ()
    size_bypass_rows: int = 0
    size_skipped_days: int = 0

    def as_manifest_fields(self) -> dict[str, Any]:
        """Flat, JSON-safe summary for the export manifest config block."""
        return {
            "neutralize": self.method,
            "neutralize_rows": int(self.rows),
            "neutralize_days": int(self.days),
            "neutralize_industry_bypass_rows": int(self.industry_bypass_rows),
            "neutralize_industry_bypass_instruments": int(
                len(self.industry_bypass_instruments)
            ),
            "neutralize_size_bypass_rows": int(self.size_bypass_rows),
            "neutralize_size_skipped_days": int(self.size_skipped_days),
        }


def _merge_reports(method: str, first: NeutralizeReport, second: NeutralizeReport) -> NeutralizeReport:
    return NeutralizeReport(
        method=method,
        rows=first.rows,
        days=first.days,
        industry_bypass_rows=first.industry_bypass_rows + second.industry_bypass_rows,
        industry_bypass_instruments=tuple(
            sorted(set(first.industry_bypass_instruments) | set(second.industry_bypass_instruments))
        ),
        size_bypass_rows=first.size_bypass_rows + second.size_bypass_rows,
        size_skipped_days=first.size_skipped_days + second.size_skipped_days,
    )


def load_industry_map(path: Path | str) -> dict[str, str]:
    """Read ``sw_l1_map.csv`` into ``{qlib code: sw_l1}``.

    Rows whose code cannot be normalized, or whose industry cell is blank, are
    dropped — a missing mapping is a bypass downstream, never a fabricated one.
    """
    csv_path = Path(path)
    mapping: dict[str, str] = {}
    with csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "sw_l1" not in reader.fieldnames:
            raise ValueError(f"industry map missing 'sw_l1' column: {csv_path}")
        code_field = "code_qlib" if "code_qlib" in reader.fieldnames else None
        if code_field is None:
            raise ValueError(f"industry map missing 'code_qlib' column: {csv_path}")
        for row in reader:
            code = to_qlib_code(row.get(code_field))
            industry = (row.get("sw_l1") or "").strip()
            if code is None or not industry:
                continue
            mapping[code] = industry
    if not mapping:
        raise ValueError(f"industry map has no usable rows: {csv_path}")
    return mapping


def normalize_industry_map(sw_l1: Mapping[str, str] | pd.Series | pd.DataFrame) -> dict[str, str]:
    """Accept a mapping / Series / two-column frame and key it by qlib code."""
    if isinstance(sw_l1, pd.DataFrame):
        if "code_qlib" in sw_l1.columns and "sw_l1" in sw_l1.columns:
            pairs: Iterable[tuple[Any, Any]] = zip(sw_l1["code_qlib"], sw_l1["sw_l1"])
        elif sw_l1.shape[1] >= 2:
            pairs = zip(sw_l1.iloc[:, 0], sw_l1.iloc[:, 1])
        else:
            raise ValueError("industry frame needs code and sw_l1 columns")
    elif isinstance(sw_l1, pd.Series):
        pairs = zip(sw_l1.index, sw_l1.to_numpy())
    else:
        pairs = dict(sw_l1).items()

    mapping: dict[str, str] = {}
    for raw_code, raw_industry in pairs:
        code = to_qlib_code(raw_code)
        if code is None or raw_industry is None:
            continue
        industry = str(raw_industry).strip()
        if industry:
            mapping[code] = industry
    return mapping


def _as_score_frame(scores: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in SCORE_COLUMNS if column not in scores.columns]
    if missing:
        raise ValueError(f"scores missing column(s): {', '.join(missing)}")
    frame = scores.copy()
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise").dt.normalize()
    frame["score"] = pd.to_numeric(frame["score"], errors="raise").astype(float)
    return frame.reset_index(drop=True)


def _as_cap_series(log_float_cap: pd.DataFrame | pd.Series | Mapping[Any, Any]) -> pd.Series:
    """Normalize a cap source into ``Series[(datetime, qlib code)] -> float``."""
    if isinstance(log_float_cap, pd.DataFrame):
        frame = log_float_cap.copy()
        if isinstance(frame.index, pd.MultiIndex) and frame.shape[1] == 1:
            frame = frame.reset_index()
        value_columns = [c for c in frame.columns if c not in {"datetime", "instrument"}]
        if "datetime" not in frame.columns or "instrument" not in frame.columns:
            raise ValueError("log_float_cap frame needs datetime and instrument columns")
        if not value_columns:
            raise ValueError("log_float_cap frame has no value column")
        column = "log_float_cap" if "log_float_cap" in value_columns else value_columns[0]
        keys = list(zip(frame["datetime"], frame["instrument"]))
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy()
    elif isinstance(log_float_cap, pd.Series):
        if not isinstance(log_float_cap.index, pd.MultiIndex):
            raise ValueError("log_float_cap Series needs a (datetime, instrument) MultiIndex")
        keys = list(log_float_cap.index)
        values = pd.to_numeric(log_float_cap, errors="coerce").to_numpy()
    else:
        items = list(dict(log_float_cap).items())
        keys = [key for key, _ in items]
        values = pd.to_numeric(pd.Series([value for _, value in items], dtype="float64")).to_numpy()

    index_keys = []
    for key in keys:
        stamp, instrument = key
        code = to_qlib_code(instrument)
        index_keys.append((pd.Timestamp(stamp).normalize(), code if code else str(instrument)))
    index = pd.MultiIndex.from_tuples(index_keys, names=["datetime", "instrument"]) if index_keys else pd.MultiIndex.from_tuples([], names=["datetime", "instrument"])
    series = pd.Series(values, index=index, dtype="float64")
    return series[~series.index.duplicated(keep="last")]


def industry_demean(
    scores: pd.DataFrame,
    sw_l1: Mapping[str, str] | pd.Series | pd.DataFrame,
) -> tuple[pd.DataFrame, NeutralizeReport]:
    """Per-day cross-section: subtract the mean score of each SW L1 industry.

    Unmapped instruments keep their raw score and are excluded from the group
    means (they would otherwise pull an industry toward an unrelated name).
    A singleton industry demeans to exactly 0 by construction — that is the
    honest answer for "this name carries no within-industry information", not
    a bug.
    """
    frame = _as_score_frame(scores)
    mapping = normalize_industry_map(sw_l1)
    industries = pd.Series(
        [mapping.get(to_qlib_code(code) or "") for code in frame["instrument"]],
        index=frame.index,
        dtype="object",
    )
    mapped = industries.notna() & (industries != "")
    bypass = frame.loc[~mapped, "instrument"].astype(str)

    if mapped.any():
        block = frame.loc[mapped]
        group_means = block.groupby([block["datetime"], industries[mapped]])["score"].transform("mean")
        frame.loc[mapped, "score"] = block["score"] - group_means

    report = NeutralizeReport(
        method="industry",
        rows=int(len(frame)),
        days=int(frame["datetime"].nunique()),
        industry_bypass_rows=int((~mapped).sum()),
        industry_bypass_instruments=tuple(sorted(set(bypass))),
    )
    return frame, report


def size_residual(
    scores: pd.DataFrame,
    log_float_cap: pd.DataFrame | pd.Series | Mapping[Any, Any],
) -> tuple[pd.DataFrame, NeutralizeReport]:
    """Per-day cross-section: replace the score with its OLS residual on size.

    ``score ~ a + b · log_float_cap`` fitted on the rows with a finite cap;
    those rows get ``score - (a + b · cap)``.  Rows with a missing cap keep the
    raw score, and a day that cannot support the fit (fewer than
    ``MIN_REGRESSION_ROWS`` usable rows, or zero cap variance) is left entirely
    untouched rather than fitted on noise.
    """
    frame = _as_score_frame(scores)
    caps = _as_cap_series(log_float_cap)

    lookup_keys = pd.MultiIndex.from_arrays(
        [
            frame["datetime"],
            [to_qlib_code(code) or str(code) for code in frame["instrument"]],
        ]
    )
    cap_values = caps.reindex(lookup_keys).to_numpy(dtype="float64")
    usable = np.isfinite(cap_values) & np.isfinite(frame["score"].to_numpy(dtype="float64"))

    bypass_rows = 0
    skipped_days = 0
    for _, positions in frame.groupby("datetime", sort=True).groups.items():
        index = frame.index.get_indexer(pd.Index(positions))
        day_usable = usable[index]
        x = cap_values[index][day_usable]
        if day_usable.sum() < MIN_REGRESSION_ROWS or not np.isfinite(x).all() or np.ptp(x) == 0.0:
            skipped_days += 1
            bypass_rows += int(len(index))
            continue
        y = frame["score"].to_numpy(dtype="float64")[index][day_usable]
        x_mean = x.mean()
        y_mean = y.mean()
        variance = float(((x - x_mean) ** 2).sum())
        if variance <= 0.0:
            skipped_days += 1
            bypass_rows += int(len(index))
            continue
        slope = float(((x - x_mean) * (y - y_mean)).sum() / variance)
        residual = y - (y_mean + slope * (x - x_mean))
        frame.iloc[index[day_usable], frame.columns.get_loc("score")] = residual
        bypass_rows += int((~day_usable).sum())

    report = NeutralizeReport(
        method="size",
        rows=int(len(frame)),
        days=int(frame["datetime"].nunique()),
        size_bypass_rows=int(bypass_rows),
        size_skipped_days=int(skipped_days),
    )
    return frame, report


def industry_size_neutral(
    scores: pd.DataFrame,
    sw_l1: Mapping[str, str] | pd.Series | pd.DataFrame,
    log_float_cap: pd.DataFrame | pd.Series | Mapping[Any, Any],
) -> tuple[pd.DataFrame, NeutralizeReport]:
    """Industry demean first, then the size residual on the demeaned scores.

    Sequential rather than one joint OLS on ``[industry dummies | log cap]``.
    The joint fit would zero both exposures exactly, but it forces a single
    usable-row set: a name missing *either* the industry or the cap would have
    to drop out of the fit entirely, and the dummy block goes rank-deficient on
    thin days.  Sequential composition keeps each bypass rule local (unmapped
    names skip only the industry step, NaN-cap names skip only the size step),
    which is what the bypass accounting above has to stay honest about.  The
    cost is that the size step can re-introduce a small industry mean; the
    residual size exposure — the thing size neutralization is for — is still
    zeroed by the second step.
    """
    demeaned, industry_report = industry_demean(scores, sw_l1)
    residual, size_report = size_residual(demeaned, log_float_cap)
    return residual, _merge_reports("both", industry_report, size_report)


def neutralize(
    scores: pd.DataFrame,
    method: str,
    *,
    sw_l1: Mapping[str, str] | pd.Series | pd.DataFrame | None = None,
    log_float_cap: pd.DataFrame | pd.Series | Mapping[Any, Any] | None = None,
) -> tuple[pd.DataFrame, NeutralizeReport]:
    """Dispatch ``industry`` / ``size`` / ``both`` with argument checks."""
    if method not in METHODS:
        raise ValueError(f"unsupported neutralize method: {method!r}; expected one of {METHODS}")
    if method in {"industry", "both"} and sw_l1 is None:
        raise ValueError(f"method {method!r} needs an industry map")
    if method in {"size", "both"} and log_float_cap is None:
        raise ValueError(f"method {method!r} needs a log float cap source")
    if method == "industry":
        return industry_demean(scores, sw_l1)
    if method == "size":
        frame, report = size_residual(scores, log_float_cap)
        return frame, replace(report, method="size")
    return industry_size_neutral(scores, sw_l1, log_float_cap)


def _read_scores(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"instrument": str})
    return _as_score_frame(frame)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Cross-section neutralize a pred score table (ranking side only). "
            "Reads datetime,instrument,score and writes the same schema."
        )
    )
    parser.add_argument("--pred", required=True, type=Path, help="pred CSV (datetime,instrument,score)")
    parser.add_argument("--out", required=True, type=Path, help="destination CSV")
    parser.add_argument("--method", choices=METHODS, required=True, help="neutralization method")
    parser.add_argument("--industry-map", type=Path, default=None, help="sw_l1_map.csv path")
    parser.add_argument(
        "--float-cap",
        type=Path,
        default=None,
        help="cap CSV (datetime,instrument,log_float_cap) for size/both",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        scores = _read_scores(args.pred)
        sw_l1 = load_industry_map(args.industry_map) if args.industry_map else None
        caps = None
        if args.float_cap is not None:
            caps = pd.read_csv(args.float_cap, dtype={"instrument": str})
        frame, report = neutralize(scores, args.method, sw_l1=sw_l1, log_float_cap=caps)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        parser.error(str(exc))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False, lineterminator="\n")
    print(
        f"method={report.method} rows={report.rows} days={report.days} "
        f"industry_bypass={report.industry_bypass_rows} "
        f"size_bypass={report.size_bypass_rows} size_skipped_days={report.size_skipped_days}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
