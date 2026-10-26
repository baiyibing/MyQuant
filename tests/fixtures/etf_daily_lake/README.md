# Synthetic ETF daily lake

Offline synthetic fixtures for local smoke only. This is not a production lake
and contains no Wind samples. IDs such as SH510300 are real tickers, but every
bar here is synthetic.

The Hive-shaped `dividend_type=front` and `dividend_type=none` trees contain the
four symbols required by the existing VWAP gates: 510300_SH (31 rows), 510050_SH
(16), 159915_SZ (11), and 518880_SH (9). Both trees total 134 rows. The sparse
510300 calendar contains weekdays only, including 2020-01-02 and 2026-10-13;
other symbols use strict subsets with the same endpoints. These dates are not
an exchange calendar and are not suitable for training or backtesting.

Timestamps are UTC milliseconds. Amount and volume are identical across front
and none; the OHLC adjustment factor grows from 0.88 to 1.0. Thus raw VWAP is on
the none basis and staging must scale it to the front basis.

The committed parquet files need no generation during pytest. To rebuild them
deterministically from arithmetic, run `python tests/fixtures/etf_daily_lake/build_fixture.py`
from the repository root with pandas and pyarrow installed. The script writes
only beside itself and accepts no lake path or environment override.

See [the offline smoke note](../../../docs/etf-daily-qlib-offline-smoke.md)
for verification and the boundary with host E3/E4 acceptance.
