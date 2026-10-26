"""Rebuild the synthetic parquet files beside this script; no external inputs."""

from pathlib import Path

import pandas as pd


def main() -> None:
    root = Path(__file__).resolve().parent
    start = pd.Timestamp("2020-01-02")
    end = pd.Timestamp("2026-10-13")
    calendar = pd.bdate_range(start, end)[::60].union(pd.DatetimeIndex([end]))
    symbols = ("510300_SH", "510050_SH", "159915_SZ", "518880_SH")
    for stride, symbol in enumerate(symbols, 1):
        dates = calendar[::stride].union(calendar[[0, -1]])
        close = pd.Series([4.0 + stride + i * 0.02 for i in range(len(dates))])
        volume = pd.Series([1000 + i * 10 for i in range(len(dates))])
        none = pd.DataFrame(
            {
                "time": [int(day.tz_localize("UTC").timestamp() * 1000) for day in dates],
                "open": close * 0.995,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": volume,
                "amount": close * volume * 100,
            }
        )
        # Only OHLC is adjusted; raw VWAP stays on the none basis.
        factor = 0.88 + 0.12 * ((dates - start) / (end - start))
        front = none.copy()
        for column in ("open", "high", "low", "close"):
            front[column] = front[column] * factor
        for basis, frame in (("front", front), ("none", none)):
            dest = root / f"dividend_type={basis}" / f"symbol={symbol}" / "data.parquet"
            dest.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(dest, engine="pyarrow", compression="snappy", index=False)
            print(f"{dest.relative_to(root)}: {len(frame)} synthetic rows")


if __name__ == "__main__":
    main()
