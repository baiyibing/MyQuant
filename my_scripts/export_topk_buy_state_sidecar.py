"""Export joint-recipe buy-state sidecar for BT ``--buy-state-file``.

MyQuant is the qlib client. Fields:

    $close, Mean($close, 20), Mean($close, 60), $winratio

盈筹 = broker ``$winratio`` (Q4). No MA5 slope, no CYQ parquet, no Quantile
proxy. BT only looks up the table; do not ``import qlib`` on the simulate
hot path.

Default MQ ``--buy-state-filter`` (legacy MA5 + CYQ/Quantile) is unchanged.

Usage (repo root, vanna312)::

    python my_scripts/export_topk_buy_state_sidecar.py \\
      --qlib-dir ~/.qlib/qlib_data/my_data \\
      --start 2026-01-06 --end 2026-09-14 \\
      --out exports/buy_state_winratio.parquet
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import pandas as pd  # noqa: E402

from st_status import to_wind_code  # noqa: E402

BUY_STATE_FIELDS = (
    "$close",
    "Mean($close, 20)",
    "Mean($close, 60)",
    "$winratio",
)
OUT_COLUMNS = ("trade_date", "code", "close", "ma20", "ma60", "winratio")
_VALUE_ALIASES = {
    "close": ("$close", "close"),
    "ma20": ("mean($close, 20)", "mean($close,20)", "ma20"),
    "ma60": ("mean($close, 60)", "mean($close,60)", "ma60"),
    "winratio": ("$winratio", "winratio"),
}


def _col(frame: pd.DataFrame, *names: str):
    lower = {str(c).strip().lower(): c for c in frame.columns}
    for n in names:
        if n in lower:
            return lower[n]
    return None


def features_to_sidecar(frame: pd.DataFrame) -> pd.DataFrame:
    """Convert ``D.features`` output to BT lookup columns. No qlib import."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=list(OUT_COLUMNS))
    work = frame.reset_index() if isinstance(frame.index, pd.MultiIndex) else frame.copy()
    date_c = _col(work, "datetime", "date", "trade_date", "dt")
    code_c = _col(work, "instrument", "code", "stock_code", "symbol")
    if date_c is None or code_c is None:
        raise ValueError("features frame needs datetime + instrument")
    value_cols = {}
    for out_name, aliases in _VALUE_ALIASES.items():
        hit = _col(work, *aliases)
        if hit is None:
            raise ValueError(f"features frame missing {out_name} ({aliases})")
        value_cols[out_name] = hit
    close = pd.to_numeric(work[value_cols["close"]], errors="coerce")
    ma20 = pd.to_numeric(work[value_cols["ma20"]], errors="coerce")
    ma60 = pd.to_numeric(work[value_cols["ma60"]], errors="coerce")
    wr = pd.to_numeric(work[value_cols["winratio"]], errors="coerce")
    dates = pd.to_datetime(work[date_c], errors="coerce")
    ok = dates.notna() & close.notna() & ma20.notna() & ma60.notna() & wr.notna()
    rows = []
    for raw, ts, c, m20, m60, w, flag in zip(
        work[code_c], dates, close, ma20, ma60, wr, ok
    ):
        if not flag:
            continue
        wind = to_wind_code(str(raw))
        if not wind or "." not in str(wind):
            continue
        rows.append(
            {
                "trade_date": ts.strftime("%Y-%m-%d"),
                "code": str(wind).upper(),
                "close": float(c),
                "ma20": float(m20),
                "ma60": float(m60),
                "winratio": float(w),
            }
        )
    if not rows:
        return pd.DataFrame(columns=list(OUT_COLUMNS))
    return pd.DataFrame(rows, columns=list(OUT_COLUMNS))


def fetch_features(provider: Path, start: str, end: str) -> pd.DataFrame:
    import host_env  # noqa: F401
    import qlib
    from qlib.config import REG_CN
    from qlib.data import D

    qlib.init(provider_uri=str(provider), region=REG_CN, kernels=1)
    frame = D.features(
        D.instruments("all"),
        list(BUY_STATE_FIELDS),
        start_time=start,
        end_time=end,
    )
    if frame is None or frame.empty:
        raise SystemExit(f"D.features empty for {start}:{end} at {provider}")
    return frame


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Export close/MA20/MA60/$winratio sidecar for BT --buy-state-file. "
            "Does not change --buy-state-filter."
        )
    )
    p.add_argument(
        "--qlib-dir",
        type=Path,
        default=Path(os.path.expanduser("~/.qlib/qlib_data/my_data")),
        help="qlib provider (my_data day.bin, including $winratio)",
    )
    p.add_argument("--start", required=True, help="inclusive start YYYY-MM-DD")
    p.add_argument("--end", required=True, help="inclusive end YYYY-MM-DD")
    p.add_argument("--out", type=Path, required=True, help="parquet or csv path")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider = args.qlib_dir.expanduser().resolve()
    if not provider.is_dir():
        raise SystemExit(f"qlib-dir not found: {provider}")
    sidecar = features_to_sidecar(fetch_features(provider, args.start, args.end))
    out = args.out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in {".csv", ".txt"}:
        sidecar.to_csv(out, index=False, encoding="utf-8", lineterminator="\n")
    else:
        sidecar.to_parquet(out, index=False)
    print(f"wrote {len(sidecar)} rows -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
