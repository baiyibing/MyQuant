"""买入资格过滤（可开关的策略级条件层）。

四个实验开关的载体（默认全关，向后兼容）：
- ST 禁买：候选股命中静态黑名单（train_wiring.EXCLUDE_STOCKS_DEFAULT + 可选补充文件）→ 剔除；
  若提供 st_daily.parquet，则按交易日查 PIT 名单，静态名单仅作未覆盖/unknown_end 的 fallback
- 上市年龄：数据起始日起算不足 age_days 个交易日 → 剔除（all.txt 的 per-stock start）
- 买入状态：站上 MA20 可买；或价格在 MA20 与 MA60 之下且 盈筹率<10% 可买。
  盈筹率优先用精确 CYQ 值（build_winner_ratio.py 产物经 winner_ratio_map 注入，
  对 QMT 真值 Spearman 0.92/召回率 0.95）；未命中时回退时间无权近似：
  $close < Quantile($close, 250, 0.10)（与 COST-KDJ 的 Quantile 口径一致）
- 回补：由 TopkDropoutStrategyWithFilter 既有的「过滤后从后排得分回补」流程承担，
  本模块通过覆写其 _filter_stocks_by_return_threshold 钩子前置资格过滤，不复制其逻辑。

表达约定：QLib 代码形如 SH600000/SZ000001。
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import date
from pathlib import Path

import pandas as pd

from qlib.data import D

from custom_strategy import TopkDropoutStrategyWithFilter
from harvest_st_from_wind import load_st_daily_index  # noqa: E402

# 买入状态表达式（诊断/文档用；策略内经 D.features 批量取数后用 buy_state_ok 判定）
BUY_STATE_EXPR = "(($close > Mean($close, 20)) | (($close < Mean($close, 20)) & ($close < Mean($close, 60)) & ($close < Quantile($close, 250, 0.10))))"
BUY_STATE_FIELDS = ["$close", "Mean($close, 20)", "Mean($close, 60)", "Quantile($close, 250, 0.10)"]


def buy_state_ok(close, ma20, ma60, q10) -> bool:
    """单一买入状态判定（纯函数，供单测）。

    站上 MA20 → 可买；否则需同时 深于 MA20、深于 MA60 且 close 低于过去 250 日
    收盘价的 10% 分位（盈筹率<10% 的时间无权近似）。任一输入 NaN → 不可买。
    """
    if close is None or ma20 is None or ma60 is None or q10 is None:
        return False
    try:
        if pd.isna(close) or pd.isna(ma20) or pd.isna(ma60) or pd.isna(q10):
            return False
    except TypeError:
        return False
    if close > ma20:
        return True
    return bool(close < ma20 and close < ma60 and close < q10)


def deep_washout_ok(close, ma20, ma60, winner_ratio) -> bool:
    """精确盈筹率版深洗判定（纯函数，供单测）。

    close < MA20 且 < MA60 且 CYQ winner_ratio < 0.10。任一输入 NaN → 不可买。
    """
    if close is None or ma20 is None or ma60 is None or winner_ratio is None:
        return False
    try:
        if pd.isna(close) or pd.isna(ma20) or pd.isna(ma60) or pd.isna(winner_ratio):
            return False
    except TypeError:
        return False
    if close > ma20:
        return False  # 精确版只判分支二；分支一（站上 MA20）由调用方先行判定
    return bool(close < ma20 and close < ma60 and winner_ratio < 0.10)


def load_winner_ratio_map(parquet_path: str | Path) -> dict:
    """build_winner_ratio.py 产物 parquet → {(code_upper, date): winner_ratio}。"""
    p = Path(parquet_path)
    if not p.is_file():
        return {}
    df = pd.read_parquet(p)
    out: dict = {}
    for code, d, wr in zip(df["stock_code"], df["date"], df["winner_ratio"]):
        if pd.isna(wr):
            continue
        out[(str(code).upper(), pd.Timestamp(d).date())] = float(wr)
    return out


def load_age_map(qlib_dir: Path) -> dict[str, pd.Timestamp]:
    """all.txt → {code: 数据起始日}（上市年龄的可用近似，见模块 docstring 局限）。"""
    all_path = Path(qlib_dir) / "instruments" / "all.txt"
    age_map: dict[str, pd.Timestamp] = {}
    for line in all_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        age_map[parts[0].strip().upper()] = pd.Timestamp(parts[1].strip())
    return age_map


def load_extra_exclude(path: str | Path | None) -> set[str]:
    """每行一个 QLib 代码的补充黑名单文件 → 集合（文件可不存在，返回空集）。"""
    if path is None:
        return set()
    p = Path(path)
    if not p.is_file():
        return set()
    return {ln.strip().upper() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}


def _as_date(value) -> date:
    ts = pd.Timestamp(value)
    return ts.date()


class BuyEligibilityFilter:
    """策略级买入资格过滤：ST / 上市年龄 / 买入状态，全部可独立开关。"""

    def __init__(
        self,
        st_codes: set[str] | None = None,
        age_map: dict[str, pd.Timestamp] | None = None,
        age_days: int = 60,
        check_buy_state: bool = False,
        calendar: list | None = None,
        features_fn=None,
        st_daily_file: str | Path | None = None,
        st_coverage_file: str | Path | None = None,
        st_daily_lookup: dict[date, set[str]] | None = None,
        st_fallback: set[str] | None = None,
        winner_ratio_map: dict | None = None,
    ):
        self.st_codes = {c.upper() for c in st_codes} if st_codes else set()
        self.age_map = age_map or {}
        self.age_days = age_days
        self.check_buy_state = check_buy_state
        self.features_fn = features_fn  # 可注入；缺省用 D.features
        # 精确盈筹率 {(CODE, date): ratio}（build_winner_ratio.py 产物）；命中替代 Quantile 代理
        self.winner_ratio_map = {k: v for k, v in (winner_ratio_map or {}).items()}
        self._feature_cache: dict[str, pd.DataFrame] = {}  # code → date 索引的 4 列特征（preload 填充）
        self._st_by_date: dict[date, set[str]] | None = None
        self._st_dates: list[date] = []
        self.st_fallback: set[str] = set()
        if st_daily_lookup is not None:
            self._st_by_date = {d: {c.upper() for c in s} for d, s in st_daily_lookup.items()}
            self._st_dates = sorted(self._st_by_date)
            self.st_fallback = {c.upper() for c in (st_fallback or set())}
        elif st_daily_file:
            by_date, fallback = load_st_daily_index(
                st_daily_file, st_coverage_file, fallback_static=self.st_codes
            )
            self._st_by_date = by_date
            self._st_dates = sorted(by_date)
            self.st_fallback = fallback if st_fallback is None else {c.upper() for c in st_fallback}
        elif st_fallback:
            self.st_fallback = {c.upper() for c in st_fallback}
        # 每只股票的最早可买日 = 日历上(数据起始 + age_days)那天的日期；日历外的起始日不设限
        self.min_trade_date: dict[str, pd.Timestamp] = {}
        if age_map and calendar:
            cal = pd.DatetimeIndex(calendar)
            pos = {d: i for i, d in enumerate(cal)}
            for code, start in age_map.items():
                idx = pos.get(start)
                if idx is not None and idx + age_days < len(cal):
                    self.min_trade_date[code] = cal[idx + age_days]

    def preload(self, codes, start_time, end_time) -> None:
        """整窗批量预取买入状态特征（逐日单日取数在长回测下慢两个数量级，禁止走那条路）。"""
        if not self.check_buy_state:
            return
        codes = list(dict.fromkeys(str(c) for c in codes))
        fetch = self.features_fn or self._bulk_fetch
        print(f"[buy_eligibility] preload buy-state features: {len(codes)} codes {start_time}..{end_time}", flush=True)
        df = fetch(codes, start_time, end_time)
        for code, sub in df.groupby(level="instrument"):
            self._feature_cache[str(code)] = sub.droplevel("instrument")
        print(f"[buy_eligibility] preload done: {len(self._feature_cache)} codes cached", flush=True)

    @staticmethod
    def _bulk_fetch(codes, start_time, end_time) -> pd.DataFrame:
        return D.features(codes, BUY_STATE_FIELDS, start_time=start_time, end_time=end_time)

    def st_codes_of_date(self, trade_date) -> set[str]:
        """T 日禁买 ST 集合（QLib 形）。有 daily 则 as-of 最近交易日 + fallback，否则退回静态名单。"""
        if self._st_by_date is None:
            return set(self.st_codes)
        target = _as_date(trade_date)
        if target in self._st_by_date:
            pit = self._st_by_date[target]
        elif self._st_dates:
            idx = bisect_right(self._st_dates, target) - 1
            pit = self._st_by_date[self._st_dates[idx]] if idx >= 0 else set()
        else:
            pit = set()
        return set(pit) | set(self.st_fallback)

    def eligible(self, stocks, trade_date) -> list[str]:
        """按 ST → 年龄 → 买入状态 依次过滤，保持原顺序。"""
        out: list[str] = []
        td = pd.Timestamp(trade_date)
        banned = self.st_codes_of_date(td)
        for code in stocks:
            c = code.upper() if isinstance(code, str) else code
            if c in banned:
                continue
            min_d = self.min_trade_date.get(c)
            if min_d is not None and td < min_d:
                continue
            out.append(code)
        if self.check_buy_state and out:
            out = self._filter_buy_state(out, td)
        return out

    def _filter_buy_state(self, stocks: list, trade_date: pd.Timestamp) -> list:
        """按预取缓存查 T 日 close/MA20/MA60/Q10，buy_state_ok 过滤（纯查表，O(候选数)）。

        精确盈筹率（winner_ratio_map）命中时，深洗分支改用 CYQ winner_ratio<0.10 判定，
        Quantile 代理仅作未命中回退。
        """
        td = pd.Timestamp(trade_date)
        td_date = td.date()
        keep = []
        for code in stocks:
            frame = self._feature_cache.get(str(code))
            if frame is None or td not in frame.index:
                continue  # 无特征（停牌/未知）→ 不买
            row = frame.loc[td]
            if row.iloc[0] > row.iloc[1]:
                keep.append(code)  # 分支一：站上 MA20，精确无近似
                continue
            wr = self.winner_ratio_map.get((str(code).upper(), td_date))
            if wr is not None:
                if deep_washout_ok(row.iloc[0], row.iloc[1], row.iloc[2], wr):
                    keep.append(code)
                continue
            if buy_state_ok(row.iloc[0], row.iloc[1], row.iloc[2], row.iloc[3]):
                keep.append(code)  # 回退：Quantile 代理
        return keep


class TopkDropoutStrategyWithBuyEligibility(TopkDropoutStrategyWithFilter):
    """在既有过滤策略的涨幅过滤前，前置买入资格过滤（复用其过滤+回补流程）。

    用法（经 init_instance_by_config / strategy dict）::

        {
            "class": "TopkDropoutStrategyWithBuyEligibility",
            "module_path": "buy_eligibility",
            "kwargs": {"signal": pred, "topk": 50, "n_drop": 5,
                       "eligibility": <BuyEligibilityFilter>},
        }
    """

    def __init__(self, *args, eligibility: BuyEligibilityFilter | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.eligibility = eligibility

    def _filter_stocks_by_return_threshold(self, stocks, trade_start_time, initial_required_count):
        if self.eligibility is not None and stocks:
            stocks = self.eligibility.eligible(list(stocks), trade_start_time)
            if not stocks:
                return []
        return super()._filter_stocks_by_return_threshold(stocks, trade_start_time, initial_required_count)
