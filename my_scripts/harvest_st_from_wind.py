"""ST harvest moved to OSkhQuant1.3. This module only re-exports lake readers.

    D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_st merge
"""

from __future__ import annotations

import sys

from st_status import (  # noqa: F401
    coverage_fallback_qlib,
    load_st_codes_asof,
    load_st_daily_index,
    to_qlib_code,
    to_wind_code,
)

_MOVED = (
    "ST / Wind / 深交所采集已迁到 OSkhQuant1.3。"
    "本仓只消费 F 湖。请在 1.3 运行：\n"
    "  D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_st generate-questions\n"
    "  D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_st pull-szse-namechange\n"
    "  D:/anaconda3/envs/vanna312/python.exe -m oskh_data.vendor_wind_st merge\n"
    "提示词：OSkhQuant1.3/docs/prompts/prompt-kimi-datasource-st-harvest.md"
)


def main() -> int:
    print(_MOVED, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
