"""SW L1 Wind harvest moved to OSkhQuant1.3 (`oskh_data.vendor_wind_sw_l1`)."""

from __future__ import annotations

import sys

_MOVED = (
    "申万一级行业 Wind 采集已迁到 OSkhQuant1.3。本仓只消费。\n"
    "  D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_sw_l1 --generate-questions\n"
    "  D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_sw_l1 --merge --compare\n"
    "提示词：OSkhQuant1.3/docs/prompts/prompt-kimi-datasource-industry-harvest.md"
)


def main() -> int:
    print(_MOVED, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
