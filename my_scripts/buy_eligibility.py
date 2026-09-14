"""买入资格过滤（可开关的策略级条件层）。

四个实验开关的载体（默认全关，向后兼容）：
- ST 禁买：候选股命中静态黑名单（train_wiring.EXCLUDE_STOCKS_DEFAULT + 可选补充文件）→ 剔除；
  若提供 st_daily.parquet，则按交易日查 PIT 名单，静态名单仅作未覆盖/unknown_end 的 fallback
- 上市年龄：数据起始日起算不足 age_days 个交易日 → 剔除（all.txt 的 per-stock start）
- 买入状态（两条路径 OR，满足其一即可买）：
  1) 价格同时在 MA20 与 MA60 之下，且盈筹率<10%；
  2) 价格站上 MA20，且 5 日线斜率 ≥ -30°。
  盈筹率优先用外部 parquet（与 ST 的 --st-daily-file 同级，本仓 CYQ
  产物；不进 qlib bins——券商 winratio 若启用是独立的 bin 字段，与本文件无关）；
  经 winner_ratio_map 注入，对 QMT Spearman 0.92 / 召回 0.95。未命中回退：
  $close < Quantile($close, 250, 0.10)（与 COST-KDJ 的 Quantile 口径一致）
- 回补：由 TopkDropoutStrategyWithFilter 既有的「过滤后从后排得分回补」流程承担，
  本模块通过覆写其 _filter_stocks_by_return_threshold 钩子前置资格过滤，不复制其逻辑。

表达约定：QLib 代码形如 SH600000/SZ000001。
"""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import date
from pathlib import Path

import pandas as pd

from qlib.data import D

from custom_strategy import TopkDropoutStrategyWithFilter
from harvest_st_from_wind import load_st_daily_index  # noqa: E402

# 通达信口径：ATAN((MA5/REF(MA5,1)-1)*100)*180/PI；「不低于 -30°」含等于。
MA5_SLOPE_MIN_DEG = -30.0

# 买入状态表达式（诊断/文档用；MA5 斜率在 Python 侧判定，qlib 无 Atan 算子）
BUY_STATE_EXPR = (
    "(($close > Mean($close, 20)) | "
    "(($close < Mean($close, 20)) & ($close < Mean($close, 60)) & ($close < Quantile($close, 250, 0.10))))"
)
# 列序：close, MA20, MA60, Q10, MA5, 昨日 MA5
BUY_STATE_FIELDS = [
    "$close",
    "Mean($close, 20)",
    "Mean($close, 60)",
    "Quantile($close, 250, 0.10)",
    "Mean($close, 5)",
    "Ref(Mean($close, 5), 1)",
]


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return True


def ma5_slope_deg(ma5, ma5_prev) -> float:
    """5 日线斜率（度）：通达信 ATAN((MA5/REF(MA5,1)-1)*100)*180/PI。"""
    if _is_missing(ma5) or _is_missing(ma5_prev):
        return float("nan")
    prev = float(ma5_prev)
    if prev == 0.0:
        return float("nan")
    return math.degrees(math.atan((float(ma5) / prev - 1.0) * 100.0))


def ma20_stand_ok(close, ma20, ma5, ma5_prev) -> bool:
    """站上 MA20 且 5 日线斜率 >= -30°。任一输入 NaN → 不可买。"""
    if _is_missing(close) or _is_missing(ma20):
        return False
    if not (close > ma20):
        return False
    slope = ma5_slope_deg(ma5, ma5_prev)
    if pd.isna(slope):
        return False
    return bool(slope >= MA5_SLOPE_MIN_DEG)


def buy_state_ok(close, ma20, ma60, q10, ma5, ma5_prev) -> bool:
    """买入状态：条件1 或 条件2（纯函数，供单测）。

    1) 同时深于 MA20、MA60，且 close 低于过去 250 日收盘 10% 分位（盈筹率<10% 近似）；
    2) 站上 MA20，且 5 日线斜率 >= -30°。
    对应分支所需输入任一 NaN → 该分支不成立。
    """
    cond1 = (
        not _is_missing(close)
        and not _is_missing(ma20)
        and not _is_missing(ma60)
        and not _is_missing(q10)
        and close < ma20
        and close < ma60
        and close < q10
    )
    cond2 = ma20_stand_ok(close, ma20, ma5, ma5_prev)
    return bool(cond1 or cond2)


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
        return False  # 精确版只判条件1；条件2 由调用方 OR 进来
    return bool(close < ma20 and close < ma60 and winner_ratio < 0.10)


def load_winner_ratio_map(parquet_path: str | Path) -> dict:
    """本仓 CYQ 外部 parquet → {(code_upper, date): winner_ratio}。

    与 ST 的 st_daily.parquet 同级：湖上文件、按日查表。列：stock_code / date /
    winner_ratio。不读 bins；券商 winratio 不走这条加载器。
    """
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
        self._feature_cache: dict[str, pd.DataFrame] = {}  # code → date 索引的 6 列特征（preload 填充）
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
        """按预取缓存查 T 日特征，条件1 或 条件2 可买（纯查表，O(候选数)）。

        条件2：站上 MA20 且 5 日线斜率 >= -30°。
        条件1：同时在 MA20/MA60 之下且盈筹率<10%；精确盈筹率命中用 CYQ，
        未命中回退 Quantile 代理。
        """
        td = pd.Timestamp(trade_date)
        td_date = td.date()
        keep = []
        for code in stocks:
            frame = self._feature_cache.get(str(code))
            if frame is None or td not in frame.index:
                continue  # 无特征（停牌/未知）→ 不买
            row = frame.loc[td]
            close, ma20, ma60, q10 = row.iloc[0], row.iloc[1], row.iloc[2], row.iloc[3]
            ma5, ma5_prev = (row.iloc[4], row.iloc[5]) if len(row) > 5 else (float("nan"), float("nan"))
            cond2 = ma20_stand_ok(close, ma20, ma5, ma5_prev)
            wr = self.winner_ratio_map.get((str(code).upper(), td_date))
            if wr is not None:
                if cond2 or deep_washout_ok(close, ma20, ma60, wr):
                    keep.append(code)
            elif buy_state_ok(close, ma20, ma60, q10, ma5, ma5_prev):
                keep.append(code)
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
