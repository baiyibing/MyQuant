# -*- coding: utf-8 -*-
"""Parquet lake resolvers: product key + derived trees; OSKH_DATA_ROOT ignored."""

from __future__ import annotations

from pathlib import Path

import data_root as dr


def test_source_env_wins_and_data_root_is_ignored(monkeypatch, tmp_path):
    lake = tmp_path / "lake"
    ci = tmp_path / "oskh_ci_data"
    lake.mkdir()
    ci.mkdir()
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(lake))
    monkeypatch.setenv("OSKH_DATA_ROOT", str(ci))

    assert dr.resolve_parquet_container() == lake
    assert dr.resolve_st_daily() == lake / "vendor_wind_st_status" / "st_daily.parquet"
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


def test_period_legacy_container_fallback(monkeypatch, tmp_path):
    lake = tmp_path / "lake"
    legacy = lake / "period=1m"
    legacy.mkdir(parents=True)
    monkeypatch.setenv("OSKH_SOURCE_PARQUET_ROOT", str(lake))
    assert dr.resolve_period_root("1m") == legacy


def test_fallback_prefers_f_when_present(monkeypatch, tmp_path):
    f_root = tmp_path / "F" / "stock_data"
    e_root = tmp_path / "E" / "stock_data"
    f_root.mkdir(parents=True)
    e_root.mkdir(parents=True)
    monkeypatch.delenv("OSKH_SOURCE_PARQUET_ROOT", raising=False)
    monkeypatch.setattr(dr, "_FALLBACKS", (f_root, e_root))
    assert dr.resolve_parquet_container() == f_root


def test_fallback_e_when_f_missing(monkeypatch, tmp_path):
    f_root = tmp_path / "F" / "stock_data"
    e_root = tmp_path / "E" / "stock_data"
    e_root.mkdir(parents=True)
    monkeypatch.delenv("OSKH_SOURCE_PARQUET_ROOT", raising=False)
    monkeypatch.setattr(dr, "_FALLBACKS", (f_root, e_root))
    assert dr.resolve_parquet_container() == e_root


def test_fallback_e_literal_when_neither_exists(monkeypatch, tmp_path):
    f_root = tmp_path / "F" / "stock_data"
    e_root = tmp_path / "E" / "stock_data"
    monkeypatch.delenv("OSKH_SOURCE_PARQUET_ROOT", raising=False)
    monkeypatch.setattr(dr, "_FALLBACKS", (f_root, e_root))
    assert dr.resolve_parquet_container() == e_root
