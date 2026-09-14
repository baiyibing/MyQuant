"""SZSE / Eastmoney ST pull moved to OSkhQuant1.3 (`oskh_data.vendor_szse_st`)."""

from __future__ import annotations

import sys

_MOVED = (
    "深交所简称变更 / 东财风险警示板拉取已迁到 OSkhQuant1.3：\n"
    "  D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_st pull-szse-namechange"
)


def main() -> int:
    print(_MOVED, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
