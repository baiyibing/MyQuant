"""Migrated implementations stay in infra; MyQuant supplies research policy."""
import ast
from pathlib import Path

import pandas as pd
import pytest

from build_tradable_universe import build

ROOT = Path(__file__).resolve().parents[1]
MIGRATED = (
    *[f"qlib_scripts/{name}.py" for name in (
        "dump_bin", "dump_pit", "refresh_mydata", "merge_archive_and_csv",
        "patch_index_data", "refresh_mydata_1min", "stage_1min_from_lake",
        "build_mydata_1min", "stage_etf_daily_from_lake", "build_etf_qlib",
        "check_dump_bin", "check_data_health", "csv_float_scan",
    )],
    "my_scripts/build_winner_ratio.py", "my_scripts/st_status.py",
    "my_scripts/harvest_st_from_wind.py", "my_scripts/harvest_sw_l1_from_wind.py",
    "my_scripts/st_namechange.py", "myquant_contract/__init__.py",
    "myquant_contract/signal_bundle.py", "myquant_contract/schema/signal-bundle-1.schema.json",
    "qlib_scripts/list_st.py", "qlib_scripts/checkcsv.py",
    "exports/m3d_industry/_merge.py", "exports/m3d_industry/_merge_fin.py",
)


def test_no_migrated_implementations_or_imports():
    assert not [name for name in MIGRATED if (ROOT / name).is_file()]
    removed_modules = {Path(name).stem for name in MIGRATED if name.endswith(".py")}
    for directory in ("my_scripts", "qlib_scripts"):
        for path in (ROOT / directory).glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert node.module != "myquant_contract", path
                    assert not (node.module.split(".")[0] in removed_modules), path
                    assert not (node.module.startswith("qlib_scripts.") and node.module.split(".")[-1] in removed_modules), path
                elif isinstance(node, ast.Import):
                    assert not any(alias.name.split(".")[0] in removed_modules | {"myquant_contract"} for alias in node.names), path


def test_universe_wrapper_uses_explicit_snapshot_and_infra(tmp_path):
    (tmp_path / "calendars").mkdir()
    (tmp_path / "instruments").mkdir()
    (tmp_path / "calendars/day.txt").write_text("2026-01-05\n2026-01-06\n2026-01-07\n", encoding="utf-8")
    (tmp_path / "instruments/all.txt").write_text(
        "SZ000001\t2026-01-05\t2026-01-07\nSH600000\t2026-01-05\t2026-01-07\n", encoding="utf-8",
    )
    daily = tmp_path / "st.parquet"
    pd.DataFrame({
        "trade_date": pd.to_datetime(["2026-01-05", "2026-01-06"]),
        "code": ["000001.SZ", "000001.SZ"], "is_st": [True, False],
    }).to_parquet(daily, index=False)
    stats = build(tmp_path, age_days=1, extra_exclude_file=None,
                  st_daily_file=str(daily), st_asof="2026-01-05")
    assert stats["asof"] == "2026-01-05"
    assert stats["dropped_st"] == 1
    assert (tmp_path / "instruments/all_tradable.txt").read_text(encoding="utf-8") == "SH600000\t2026-01-06\t2026-01-07\n"
    stats = build(tmp_path, age_days=0, extra_exclude_file=None,
                  st_daily_file=str(daily), st_asof="2026-01-06")
    assert stats["kept"] == 2
    with pytest.raises(ValueError, match="--st-asof"):
        build(tmp_path, age_days=0, extra_exclude_file=None)
