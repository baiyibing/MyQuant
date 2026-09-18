# -*- coding: utf-8 -*-
"""Parquet lake resolvers: product key + derived trees; OSKH_DATA_ROOT ignored."""

from __future__ import annotations

import pytest

import data_root as dr


def test_source_env_wins_and_data_root_is_ignored(monkeypatch, tmp_path):
    lake = tmp_path / "lake"
    ci = tmp_path / "oskh_ci_data"
    lake.mkdir()
    ci.mkdir()
    st = lake / "vendor_wind_st_status"
    st.mkdir()
    (st / "st_daily.parquet").write_bytes(b"")
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(lake))
    monkeypatch.setenv("OSKH_DATA_ROOT", str(ci))

    assert dr.resolve_parquet_container() == lake
    assert dr.resolve_st_daily() == st / "st_daily.parquet"
    assert dr.resolve_stock_1min_none() == lake / "stock" / "period=1m" / "dividend_type=none"
    assert dr.resolve_index_1d_none() == lake / "index" / "period=1d" / "dividend_type=none"
    assert dr.resolve_index_1min_none() == lake / "index" / "period=1m" / "dividend_type=none"
    assert dr.resolve_etf_1d_none() == lake / "etf" / "period=1d" / "dividend_type=none"
    assert ci not in dr.resolve_parquet_container().parents
    assert dr.resolve_parquet_container() != ci / "stock_data"


def test_explicit_root_beats_env(monkeypatch, tmp_path):
    env_lake = tmp_path / "env"
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(env_lake))
    assert dr.resolve_parquet_container(explicit_root=explicit) == explicit
    assert dr.resolve_period_root("1m", explicit_root=explicit / "custom_1m") == explicit / "custom_1m"


def test_index_resolvers_never_read_stock_period_env(monkeypatch, tmp_path):
    lake = tmp_path / "lake"
    stock_1m = tmp_path / "stock_1m"
    index_1m = tmp_path / "index_1m"
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(lake))
    monkeypatch.setenv("OSKH_PERIOD_1M_ROOT", str(stock_1m))
    monkeypatch.setenv("OSKH_INDEX_1M_ROOT", str(index_1m))

    assert dr.resolve_period_root("1m") == stock_1m
    assert dr.resolve_index_minute_root() == index_1m
    assert dr.resolve_index_1min_none() == index_1m / "dividend_type=none"
    assert dr.resolve_index_daily_root() == lake / "index" / "period=1d"


def test_period_does_not_guess_legacy_container_layout(monkeypatch, tmp_path):
    lake = tmp_path / "lake"
    (lake / "period=1m").mkdir(parents=True)
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(lake))
    assert dr.resolve_period_root("1m") == lake / "stock" / "period=1m"


def test_unset_source_env_errors_instead_of_guessing_drive(monkeypatch):
    monkeypatch.delenv("OSKH_SOURCE_PARQUET_ROOT", raising=False)
    with pytest.raises(dr.DataRootError, match="OSKH_SOURCE_PARQUET_ROOT"):
        dr.resolve_parquet_container()
    with pytest.raises(dr.DataRootError, match="OSKH_SOURCE_PARQUET_ROOT"):
        dr.resolve_st_daily()


def test_sw_l1_map_only_sw_l1_map_csv(monkeypatch, tmp_path):
    lake = tmp_path / "lake"
    root = lake / "vendor_wind_sw_l1"
    root.mkdir(parents=True)
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(lake))
    assert dr.resolve_sw_l1_root() == root
    with pytest.raises(dr.DataRootError, match="行业映射"):
        dr.resolve_sw_l1_map()
    (root / "wind_l1_map.csv").write_text(
        "code_gildata,name,wind_sw_l1\n", encoding="utf-8"
    )
    with pytest.raises(dr.DataRootError, match="sw_l1_map.csv"):
        dr.resolve_sw_l1_map()
    preferred = root / "sw_l1_map.csv"
    preferred.write_text("code_qlib,sw_l1\n", encoding="utf-8")
    assert dr.resolve_sw_l1_map() == preferred
    explicit = tmp_path / "other.csv"
    explicit.write_text("code_qlib,sw_l1\n", encoding="utf-8")
    assert dr.resolve_sw_l1_map(explicit_root=explicit) == explicit


def test_st_and_cyq_and_qmt_missing_files_error(monkeypatch, tmp_path):
    lake = tmp_path / "lake"
    lake.mkdir()
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(lake))
    with pytest.raises(dr.DataRootError, match="ST 日表"):
        dr.resolve_st_daily()
    with pytest.raises(dr.DataRootError, match="CYQ"):
        dr.resolve_cyq_winner_ratio(must_exist=True)
    with pytest.raises(dr.DataRootError, match="QMT"):
        dr.resolve_qmt_winner_chips()
    cyq = lake / "cyq_winner_ratio" / "cyq_winner_ratio_daily_2026.parquet"
    assert dr.resolve_cyq_winner_ratio() == cyq
    (lake / "cyq_winner_ratio_daily_2026.parquet").write_bytes(b"")
    assert dr.resolve_cyq_winner_ratio() == cyq


def test_qlib_csv_env_or_explicit(monkeypatch, tmp_path):
    batch = tmp_path / "qlibdata20260918"
    monkeypatch.setenv("OSKH_QLIB_CSV_DIR", str(batch))
    assert dr.resolve_qlib_csv_dir() == batch
    other = tmp_path / "other"
    assert dr.resolve_qlib_csv_dir(explicit_root=other) == other
    monkeypatch.delenv("OSKH_QLIB_CSV_DIR", raising=False)
    with pytest.raises(dr.DataRootError, match="OSKH_QLIB_CSV_DIR"):
        dr.resolve_qlib_csv_dir()
