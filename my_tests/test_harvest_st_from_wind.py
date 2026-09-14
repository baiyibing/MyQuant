"""Wind ST 后处理：合并、区间推断、稀疏 daily（不依赖 F 盘/MCP）。"""

from __future__ import annotations

import os
import sys

import pandas as pd

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MY_SCRIPTS = os.path.join(_ROOT, "my_scripts")
if _MY_SCRIPTS not in sys.path:
    sys.path.insert(0, _MY_SCRIPTS)

from harvest_st_from_wind import (  # noqa: E402
    build_daily_matrix,
    build_intervals,
    collect_harvest_status,
    coverage_fallback_qlib,
    infer_st_kind,
    is_st_risk_name,
    load_st_codes_asof,
    load_st_daily_index,
    merge_raw_to_parquet,
    normalize_implement,
    normalize_revoke,
    parse_codes_from_question,
    read_raw_csvs,
    to_qlib_code,
    to_wind_code,
)


def test_code_roundtrip():
    assert to_wind_code("SZ000504") == "000504.SZ"
    assert to_qlib_code("000504.SZ") == "SZ000504"
    assert to_qlib_code("600000.SH") == "SH600000"
    assert to_qlib_code("920305.BJ") == "BJ920305"


def test_is_st_risk_name():
    assert is_st_risk_name("*ST美谷") is True
    assert is_st_risk_name("＊ST生物") is True  # 全角星号
    assert is_st_risk_name("ST华闻") is True
    assert is_st_risk_name("退市岩石(退市)") is True
    assert is_st_risk_name("南华生物") is False
    assert is_st_risk_name("石药景峰") is False


def test_infer_st_kind():
    assert infer_st_kind("*ST景峰", "净资产为负") == "star_st"
    assert infer_st_kind("ST华闻", None) == "st"
    assert infer_st_kind("退市岩石", "退市") == "delist"


def test_read_raw_csvs_absolute_glob(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "st_implement_batch_0000.csv").write_text(
        "Wind代码,证券简称,实施ST后简称,实施ST前简称,股票种类,实施ST日期,实施ST原因\n"
        "000504.SZ,南华生物,*ST生物,南华生物,A股,2025-04-30,营收低于3亿\n",
        encoding="utf-8",
    )
    (raw / "st_implement_batch_0001.csv").write_text(
        "Wind代码,证券简称,实施ST后简称,实施ST前简称,股票种类,实施ST日期,实施ST原因\n"
        "000615.SZ,*ST美谷,*ST美谷,奥园美谷,A股,2023-05-05,净资产为负\n",
        encoding="utf-8",
    )
    df = read_raw_csvs(str(raw / "st_implement_batch_*.csv"))
    assert len(df) == 2
    impl = normalize_implement(df)
    assert set(impl["code"]) == {"000504.SZ", "000615.SZ"}


def test_intervals_without_revoke_open_vs_unknown():
    impl = normalize_implement(
        pd.DataFrame(
            [
                {
                    "Wind代码": "000615.SZ",
                    "证券简称": "*ST美谷",
                    "实施ST后简称": "*ST美谷",
                    "实施ST前简称": "奥园美谷",
                    "实施ST日期": "2023-05-05",
                    "实施ST原因": "净资产为负",
                },
                {
                    "Wind代码": "000615.SZ",
                    "证券简称": "*ST美谷",
                    "实施ST后简称": "*ST美谷",
                    "实施ST前简称": "ST美谷",
                    "实施ST日期": "2025-04-30",
                    "实施ST原因": "再戴帽",
                },
                {
                    "Wind代码": "000504.SZ",
                    "证券简称": "南华生物",
                    "实施ST后简称": "*ST生物",
                    "实施ST前简称": "南华生物",
                    "实施ST日期": "2025-04-30",
                    "实施ST原因": "营收低于3亿",
                },
            ]
        )
    )
    iv = build_intervals(impl, normalize_revoke(pd.DataFrame()))
    by = iv.set_index("code")
    assert by.loc["000615.SZ", "end_status"] == "open"
    assert by.loc["000615.SZ", "start_date"] == pd.Timestamp("2023-05-05").date()
    assert pd.isna(by.loc["000615.SZ", "end_date"]) or by.loc["000615.SZ", "end_date"] is None
    assert by.loc["000504.SZ", "end_status"] == "unknown_end"


def test_intervals_with_revoke_pair():
    impl = normalize_implement(
        pd.DataFrame(
            [
                {
                    "Wind代码": "000504.SZ",
                    "证券简称": "南华生物",
                    "实施ST后简称": "*ST生物",
                    "实施ST前简称": "南华生物",
                    "实施ST日期": "2025-04-30",
                    "实施ST原因": "营收低于3亿",
                }
            ]
        )
    )
    revoke = normalize_revoke(
        pd.DataFrame(
            [
                {
                    "股票编号": "000504.SZ",
                    "证券名称": "南华生物",
                    "撤销日期": "2026-06-12",
                    "撤销ST后简称": "南华生物",
                    "撤销ST前简称": "*ST生物",
                }
            ]
        )
    )
    iv = build_intervals(impl, revoke)
    assert len(iv) == 1
    assert iv.iloc[0]["end_status"] == "revoked"
    assert iv.iloc[0]["end_date"] == pd.Timestamp("2026-06-12").date()


def test_daily_sparse_skips_unknown_end():
    cal = pd.DatetimeIndex(pd.to_datetime(["2025-04-29", "2025-04-30", "2025-05-06"]))
    iv = pd.DataFrame(
        [
            {
                "code": "000615.SZ",
                "name": "*ST美谷",
                "st_kind": "star_st",
                "start_date": pd.Timestamp("2025-04-30").date(),
                "end_date": None,
                "reason": "x",
                "end_status": "open",
            },
            {
                "code": "000504.SZ",
                "name": "南华生物",
                "st_kind": "star_st",
                "start_date": pd.Timestamp("2025-04-30").date(),
                "end_date": None,
                "reason": "x",
                "end_status": "unknown_end",
            },
        ]
    )
    daily = build_daily_matrix(iv, cal)
    assert set(daily["code"]) == {"000615.SZ"}
    assert daily["is_st"].all()
    assert pd.Timestamp("2025-04-29") not in set(daily["trade_date"])
    assert pd.Timestamp("2025-04-30") in set(daily["trade_date"])


def test_parse_question_and_status(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "q_st_implement_0000.txt").write_text(
        "000001.SZ、000002.SZ的ST状态和历史戴帽摘帽时间", encoding="utf-8"
    )
    (raw / "q_st_implement_0001.txt").write_text(
        "000004.SZ的ST状态和历史戴帽摘帽时间", encoding="utf-8"
    )
    (raw / "q_st_revoke_0000.txt").write_text(
        "000001.SZ、000002.SZ的撤销风险警示和摘帽日期", encoding="utf-8"
    )
    (raw / "q_st_revoke_0001.txt").write_text(
        "000004.SZ的撤销风险警示和摘帽日期", encoding="utf-8"
    )
    (raw / "st_implement_batch_0000.csv").write_text(
        "Wind代码,证券简称,实施ST后简称,实施ST前简称,股票种类,实施ST日期,实施ST原因\n"
        "000001.SZ,平安银行,ST平安,平安银行,A股,2020-01-02,测试\n",
        encoding="utf-8",
    )
    codes = parse_codes_from_question((raw / "q_st_implement_0000.txt").read_text(encoding="utf-8"))
    assert codes == ["000001.SZ", "000002.SZ"]
    st = collect_harvest_status(tmp_path)
    assert st["implement"]["have"] == ["0000"]
    assert st["implement"]["missing"] == ["0001"]
    assert st["revoke"]["n_have"] == 0
    assert st["harvested_wind_codes"] == ["000001.SZ", "000002.SZ"]


def test_merge_raw_to_parquet_partial(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "q_st_implement_0000.txt").write_text(
        "000615.SZ的ST状态和历史戴帽摘帽时间", encoding="utf-8"
    )
    (raw / "st_implement_batch_0000.csv").write_text(
        "Wind代码,证券简称,实施ST后简称,实施ST前简称,股票种类,实施ST日期,实施ST原因\n"
        "000615.SZ,*ST美谷,*ST美谷,奥园美谷,A股,2023-05-05,净资产为负\n",
        encoding="utf-8",
    )
    cal = pd.DatetimeIndex(pd.to_datetime(["2023-05-04", "2023-05-05", "2023-05-08"]))
    stats = merge_raw_to_parquet(tmp_path, calendar=cal, dense=False)
    assert stats["impl_rows"] == 1
    assert stats["revoke_rows"] == 0
    assert stats["open_st"] == 1
    daily = pd.read_parquet(stats["daily"])
    assert set(daily["code"]) == {"000615.SZ"}
    assert (tmp_path / "st_coverage.json").is_file()
    assert (tmp_path / "harvest_status.json").is_file()


def test_coverage_fallback_and_asof(tmp_path):
    daily = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(["2026-01-07", "2026-01-08"]),
            "code": ["000615.SZ", "000615.SZ"],
            "is_st": [True, True],
            "st_kind": ["star_st", "star_st"],
            "name": ["*ST美谷", "*ST美谷"],
        }
    )
    daily_path = tmp_path / "st_daily.parquet"
    daily.to_parquet(daily_path, index=False)
    (tmp_path / "st_coverage.json").write_text(
        '{"harvested_wind_codes": ["000615.SZ", "000504.SZ"], '
        '"unknown_end_wind_codes": ["000504.SZ"]}',
        encoding="utf-8",
    )
    static = {"SZ000615", "SZ000504", "SH688999"}
    fallback = coverage_fallback_qlib(
        {"harvested_wind_codes": ["000615.SZ", "000504.SZ"], "unknown_end_wind_codes": ["000504.SZ"]},
        static,
    )
    assert "SZ000504" in fallback
    assert "SH688999" in fallback
    assert "SZ000615" not in fallback
    by_date, fb = load_st_daily_index(daily_path, fallback_static=static)
    assert by_date[pd.Timestamp("2026-01-07").date()] == {"SZ000615"}
    assert fb == fallback
    asof = load_st_codes_asof(daily_path, asof="2026-01-07", fallback_static=static)
    assert asof == {"SZ000615", "SZ000504", "SH688999"}
