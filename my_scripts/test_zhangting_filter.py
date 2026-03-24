import argparse
from typing import List

import pandas as pd
import qlib
from qlib.config import REG_CN
from qlib.data import D


def fetch_raw_rows(start_time: str, end_time: str, market: str) -> pd.DataFrame:
    instruments = D.instruments(
        market=market,
        start_time=start_time,
        end_time=end_time,
    )
    df = D.features(
        instruments=instruments,
        fields=["$close", "$change", "$zhangting"],
        start_time=start_time,
        end_time=end_time,
    )
    return df


def build_crosscheck_df(
    raw_df: pd.DataFrame,
    main_limit_pct: float,
    chinext_limit_pct: float,
    star_limit_pct: float,
    bj_limit_pct: float,
    eps: float,
) -> pd.DataFrame:
    if raw_df.empty:
        return raw_df

    df = raw_df.copy()
    # Method A: qlib label.
    df["is_limit_up_field"] = (df["$zhangting"] == 1)
    # Method B: price threshold by board-specific limit.
    inst = df.index.get_level_values("instrument").astype(str)
    is_bj = inst.str.startswith("BJ")
    is_chinext = inst.str.startswith("SZ30")
    is_star = inst.str.startswith(("SH688", "SH689"))

    df["limit_pct_used"] = main_limit_pct
    df.loc[is_chinext, "limit_pct_used"] = chinext_limit_pct
    df.loc[is_star, "limit_pct_used"] = star_limit_pct
    df.loc[is_bj, "limit_pct_used"] = bj_limit_pct
    df["is_limit_up_by_change"] = (df["$change"] >= (df["limit_pct_used"] - eps))
    # Useful to inspect edge cases around threshold.
    df["change_minus_limit"] = df["$change"] - df["limit_pct_used"]
    return df


def print_limit_up_summary(cross_df: pd.DataFrame, sample_dates: int, sample_stocks: int) -> None:
    limit_df = cross_df[cross_df["is_limit_up_field"]].copy()
    if limit_df.empty:
        print("未读取到 $zhangting == 1 的记录。")
        return

    by_date = limit_df.groupby(level="datetime").size().sort_index()
    print("=== $zhangting == 1 统计 ===")
    print(f"总记录数: {len(limit_df)}")
    print(f"涉及交易日数: {by_date.shape[0]}")
    print(f"涉及股票数: {limit_df.index.get_level_values('instrument').nunique()}")
    print()
    print("=== 每日涨停数量（前N日） ===")
    print(by_date.head(sample_dates))
    print()
    print("=== 每日涨停数量（后N日） ===")
    print(by_date.tail(sample_dates))
    print()

    unique_dates: List[pd.Timestamp] = list(by_date.index[:sample_dates])
    for dt in unique_dates:
        day_df = limit_df.xs(dt, level="datetime")
        print(f"=== {dt.date()} 样例（最多{sample_stocks}只） ===")
        print(day_df[["$close", "$change", "$zhangting"]].head(sample_stocks))
        print()


def print_consistency_summary(cross_df: pd.DataFrame, sample_mismatch: int) -> None:
    if cross_df.empty:
        print("无数据可用于一致性核验。")
        return

    total = len(cross_df)
    same = (cross_df["is_limit_up_field"] == cross_df["is_limit_up_by_change"]).sum()
    mismatch = total - same
    match_ratio = same / total if total else 0.0

    print("=== 一致性核验：$zhangting vs $change分市场阈值 ===")
    print(f"总样本: {total}")
    print(f"一致样本: {same}")
    print(f"不一致样本: {mismatch}")
    print(f"一致率: {match_ratio:.4%}")
    print()

    mismatch_df = cross_df[cross_df["is_limit_up_field"] != cross_df["is_limit_up_by_change"]].copy()
    if mismatch_df.empty:
        print("没有不一致样本。")
        return

    print(f"=== 不一致样本（最多{sample_mismatch}条） ===")
    cols = [
        "$close",
        "$change",
        "$zhangting",
        "limit_pct_used",
        "is_limit_up_field",
        "is_limit_up_by_change",
        "change_minus_limit",
    ]
    print(mismatch_df[cols].head(sample_mismatch))
    print()

    by_date = mismatch_df.groupby(level="datetime").size().sort_values(ascending=False)
    print("=== 不一致最多的交易日（前10） ===")
    print(by_date.head(10))
    print()


def print_manual_check_samples(cross_df: pd.DataFrame, sample_dates: int, sample_stocks: int) -> None:
    # Manual check set 1: field says limit-up.
    field_limit = cross_df[cross_df["is_limit_up_field"]]
    if not field_limit.empty:
        print("=== 人工核验样本A：$zhangting==1 ===")
        by_date = field_limit.groupby(level="datetime").size().sort_index()
        for dt in list(by_date.index[:sample_dates]):
            day_df = field_limit.xs(dt, level="datetime")
            print(f"[A] {dt.date()} 最多{sample_stocks}只")
            print(day_df[["$close", "$change", "$zhangting"]].head(sample_stocks))
            print()

    # Manual check set 2: threshold says limit-up but field does not.
    hard_cases = cross_df[(cross_df["is_limit_up_by_change"]) & (~cross_df["is_limit_up_field"])]
    if not hard_cases.empty:
        print("=== 人工核验样本B：$change达分市场阈值但$zhangting!=1 ===")
        print(
            hard_cases[["$close", "$change", "$zhangting", "limit_pct_used", "change_minus_limit"]].head(
                sample_stocks
            )
        )
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="从 Qlib 数据中读取 $zhangting == 1 的股票用于人工核验")
    parser.add_argument("--provider-uri", default="~/.qlib/qlib_data/my_data", help="qlib provider_uri")
    parser.add_argument("--start-time", default="2026-01-01", help="起始日期")
    parser.add_argument("--end-time", default="2026-03-13", help="结束日期")
    parser.add_argument("--market", default="all", help="股票池，如 all/csi300")
    parser.add_argument("--main-limit-pct", type=float, default=0.10, help="主板涨停阈值（默认10%）")
    parser.add_argument("--chinext-limit-pct", type=float, default=0.20, help="创业板涨停阈值（默认20%）")
    parser.add_argument("--star-limit-pct", type=float, default=0.20, help="科创板涨停阈值（默认20%）")
    parser.add_argument("--bj-limit-pct", type=float, default=0.30, help="北交所涨停阈值（默认30%）")
    parser.add_argument("--eps", type=float, default=1e-6, help="阈值比较容差")
    parser.add_argument("--sample-dates", type=int, default=5, help="展示前后多少个交易日统计")
    parser.add_argument("--sample-stocks", type=int, default=10, help="每个样例交易日展示多少只股票")
    parser.add_argument("--sample-mismatch", type=int, default=20, help="最多展示多少条不一致样本")
    args = parser.parse_args()

    qlib.init(provider_uri=args.provider_uri, region=REG_CN)

    raw_df = fetch_raw_rows(
        start_time=args.start_time,
        end_time=args.end_time,
        market=args.market,
    )
    cross_df = build_crosscheck_df(
        raw_df=raw_df,
        main_limit_pct=args.main_limit_pct,
        chinext_limit_pct=args.chinext_limit_pct,
        star_limit_pct=args.star_limit_pct,
        bj_limit_pct=args.bj_limit_pct,
        eps=args.eps,
    )
    print_limit_up_summary(
        cross_df=cross_df,
        sample_dates=args.sample_dates,
        sample_stocks=args.sample_stocks,
    )
    print_consistency_summary(cross_df=cross_df, sample_mismatch=args.sample_mismatch)
    print_manual_check_samples(
        cross_df=cross_df,
        sample_dates=args.sample_dates,
        sample_stocks=args.sample_stocks,
    )


if __name__ == "__main__":
    main()
