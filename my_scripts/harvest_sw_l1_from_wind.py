"""SW L1 Wind harvest lives in OSkhQuant1.3; this repo only consumes the lake."""

from __future__ import annotations

import sys

_MOVED = (
    "申万一级行业 Wind 采集已迁到 OSkhQuant1.3。本仓只消费湖文件。\n"
    "  写湖：python -m oskh_data.vendor_wind_sw_l1 --generate-questions|--merge|--compare\n"
    "  读湖：{OSKH_SOURCE_PARQUET_ROOT}/vendor_wind_sw_l1/sw_l1_map.csv\n"
    "       （没有则 wind_l1_map.csv；未设 env 或文件不存在则报错，不猜 E:/F:）\n"
    "提示词：OSkhQuant1.3/docs/prompts/prompt-kimi-datasource-industry-harvest.md"
)


def main() -> int:
    print(_MOVED, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
