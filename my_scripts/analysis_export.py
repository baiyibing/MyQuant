"""盘后分析包：从已落盘的 hist_positions / pred 展开 CSV，不重回测。

产物（稳定文件名，按 recorder 分目录）::

    positions_daily.csv   逐日持仓快照
    trades_daily.csv      相邻日 amount 差分得到的买卖
    ledger_by_stock.csv   每只股票流水账（买/持/卖 + 逐笔盈亏）
    pnl_by_stock.csv      按股汇总（从流水账归并，与 ledger 同源）
    daily_picks.csv       每日荐股（pred TopK）对照实持
    nav_daily.csv         组合日净值（有 report 才写）
    summary.json          行数 / 盈亏对账，给盘后提示词当索引

训练收尾和 ``export_positions_trades.py``（默认 --from-recorder）共用本模块。
换成本 / topk / 闸门才走 ``--replay`` 重跑 PortAna。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

_POSITION_SPECIAL_KEYS = {"cash", "now_account_value", "cash_delay"}

CloseLookup = Callable[[str, pd.Timestamp], float | None]


def _day_position_dict(day_pos: Any) -> dict:
    """Accept qlib Position, SimpleNamespace, or a raw dict."""
    if isinstance(day_pos, dict):
        return dict(day_pos)
    raw = getattr(day_pos, "position", None)
    if raw is None:
        return {}
    return dict(raw)


def _iso(day) -> str:
    return pd.Timestamp(day).date().isoformat()


def filter_positions_by_window(positions: Mapping, start: str, end: str) -> dict:
    """Keep hist_positions keys whose calendar date is inside [start, end]."""
    out = {}
    for day, pos in positions.items():
        d = _iso(day)
        if start <= d <= end:
            out[day] = pos
    return out


def positions_frame(positions: Mapping) -> tuple[pd.DataFrame, dict]:
    """hist_positions → 逐日持仓 DataFrame + {date: {inst: (amount, price, count)}}."""
    rows = []
    snapshots: dict = {}
    streak: dict[str, int] = {}
    for day in sorted(positions.keys()):
        pdict = _day_position_dict(positions[day])
        cash = float(pdict.get("cash", 0.0) or 0.0) + float(pdict.get("cash_delay", 0.0) or 0.0)
        stock_items = {k: v for k, v in pdict.items() if k not in _POSITION_SPECIAL_KEYS}
        total = float(pdict.get("now_account_value", 0.0) or 0.0)
        if total <= 0:
            total = cash + sum(
                float(item.get("amount", 0)) * float(item.get("price", 0.0) or 0.0)
                for item in stock_items.values()
                if isinstance(item, dict)
            )
        day_snap: dict[str, tuple[float, float, int]] = {}
        for inst in stock_items:
            streak[inst] = streak.get(inst, 0) + 1
        streak = {k: v for k, v in streak.items() if k in stock_items}
        for inst, item in stock_items.items():
            if not isinstance(item, dict):
                item = {"amount": item}
            amount = float(item.get("amount", 0))
            price = float(item.get("price", 0.0) or 0.0)
            value = amount * price
            day_snap[inst] = (amount, price, streak[inst])
            rows.append(
                {
                    "date": _iso(day),
                    "instrument": inst,
                    "holding_days": streak[inst],
                    "bought_today": streak[inst] == 1,
                    "amount": amount,
                    "price": price,
                    "value": value,
                    "weight": (value / total) if total > 0 else None,
                    "cash": cash,
                    "total_value": total,
                }
            )
        snapshots[pd.Timestamp(day)] = day_snap
    return pd.DataFrame(rows), snapshots


def _est_cost(value: float, rate: float, min_cost: float) -> float:
    if value <= 0:
        return 0.0
    return max(value * rate, min_cost)


def trades_frame(
    snapshots: dict,
    open_rate: float,
    close_rate: float,
    min_cost: float = 5.0,
    close_of: CloseLookup | None = None,
) -> pd.DataFrame:
    """相邻交易日 amount 差分 → 买卖记录。"""
    rows = []
    days = sorted(snapshots.keys())
    prev: dict = {}
    for day in days:
        cur = snapshots[day]
        for inst in sorted(set(prev) | set(cur)):
            cur_amt = cur.get(inst, (0.0,))[0]
            prev_amt = prev.get(inst, (0.0,))[0]
            delta = cur_amt - prev_amt
            if abs(delta) < 1e-9:
                continue
            side = "buy" if delta > 0 else "sell"
            if inst in cur:
                price = cur[inst][1]
            else:
                looked = close_of(inst, day) if close_of is not None else None
                price = looked if looked is not None else prev.get(inst, (0.0, 0.0, 0))[1]
            value = abs(delta) * price
            rate = open_rate if side == "buy" else close_rate
            held = prev.get(inst, (0.0, 0.0, 0))[2] if side == "sell" else 1
            rows.append(
                {
                    "date": _iso(day),
                    "instrument": inst,
                    "side": side,
                    "delta_amount": abs(delta),
                    "price": price,
                    "value": value,
                    "est_cost": _est_cost(value, rate, min_cost),
                    "held_days": held,
                }
            )
        prev = cur
    return pd.DataFrame(rows)


def ledger_frame(
    snapshots: dict,
    open_rate: float,
    close_rate: float,
    min_cost: float = 5.0,
    close_of: CloseLookup | None = None,
) -> pd.DataFrame:
    """每只股票流水账：买 / 持 / 卖，均价成本，逐笔已实现 + 当日浮动。

    买入成本记在买事件（est_cost），卖出只扣卖出费。浮动 = 余仓 × (现价-均价) − 按余仓摊销的买入费。
    """
    rows: list[dict[str, Any]] = []
    days = sorted(snapshots.keys())
    prev: dict = {}
    avg_entry: dict[str, float] = {}
    buy_cost_remain: dict[str, float] = {}
    cum_realized: dict[str, float] = {}
    first_date: dict[str, str] = {}

    for day in days:
        cur = snapshots[day]
        cash = None
        total = None
        # cash/total 不在 snapshot 元组里；留给 write 侧用 positions_daily 对齐。
        for inst in sorted(set(prev) | set(cur)):
            cur_amt = float(cur.get(inst, (0.0, 0.0, 0))[0])
            prev_amt = float(prev.get(inst, (0.0, 0.0, 0))[0])
            if cur_amt <= 1e-9 and prev_amt <= 1e-9:
                continue
            if inst in cur:
                price = float(cur[inst][1])
                held = int(cur[inst][2])
            else:
                looked = close_of(inst, day) if close_of is not None else None
                price = float(looked if looked is not None else prev[inst][1])
                held = int(prev[inst][2])
            delta = cur_amt - prev_amt
            entry = avg_entry.get(inst, price)
            realized = 0.0
            trade_value = 0.0
            cost = 0.0
            if abs(delta) < 1e-9:
                event = "hold"
            elif delta > 0:
                event = "buy"
                trade_value = delta * price
                cost = _est_cost(trade_value, open_rate, min_cost)
                old_cost = buy_cost_remain.get(inst, 0.0)
                if prev_amt <= 1e-9:
                    avg_entry[inst] = price
                    buy_cost_remain[inst] = cost
                    first_date.setdefault(inst, _iso(day))
                else:
                    avg_entry[inst] = (prev_amt * entry + delta * price) / cur_amt
                    buy_cost_remain[inst] = old_cost + cost
                entry = avg_entry[inst]
            else:
                event = "sell"
                sell_amt = -delta
                trade_value = sell_amt * price
                cost = _est_cost(trade_value, close_rate, min_cost)
                frac = sell_amt / prev_amt if prev_amt > 1e-9 else 1.0
                released_buy = buy_cost_remain.get(inst, 0.0) * frac
                buy_cost_remain[inst] = buy_cost_remain.get(inst, 0.0) - released_buy
                realized = sell_amt * (price - entry) - cost - released_buy
                if cur_amt <= 1e-9:
                    avg_entry.pop(inst, None)
                    buy_cost_remain.pop(inst, None)

            remain_amt = cur_amt
            remain_buy = buy_cost_remain.get(inst, 0.0)
            unrealized = remain_amt * (price - avg_entry.get(inst, entry)) - remain_buy if remain_amt > 1e-9 else 0.0
            cum_realized[inst] = cum_realized.get(inst, 0.0) + realized
            rows.append(
                {
                    "date": _iso(day),
                    "instrument": inst,
                    "event": event,
                    "delta_amount": abs(delta) if abs(delta) >= 1e-9 else 0.0,
                    "amount_after": remain_amt,
                    "price": price,
                    "entry_price": avg_entry.get(inst, entry),
                    "trade_value": trade_value,
                    "est_cost": cost,
                    "holding_days": held,
                    "realized_pnl": realized,
                    "unrealized_pnl": unrealized,
                    "cum_realized_pnl": cum_realized[inst],
                    "cash": cash,
                    "total_value": total,
                }
            )
        prev = cur

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["instrument", "date", "event"], ignore_index=True)


def attach_portfolio_context(ledger: pd.DataFrame, pos_df: pd.DataFrame) -> pd.DataFrame:
    """Copy cash / total_value / weight from the daily position snapshot onto ledger rows."""
    if ledger.empty or pos_df.empty:
        return ledger
    out = ledger.copy()
    ctx = pos_df.loc[:, ["date", "instrument", "cash", "total_value", "weight"]].drop_duplicates(
        ["date", "instrument"]
    )
    out = out.drop(columns=["cash", "total_value"], errors="ignore")
    out = out.merge(ctx, on=["date", "instrument"], how="left")
    day_cash = pos_df.loc[:, ["date", "cash", "total_value"]].drop_duplicates("date")
    missing = out["cash"].isna()
    if missing.any():
        out = out.drop(columns=["cash", "total_value"], errors="ignore")
        out = out.merge(day_cash, on="date", how="left")
    return out


def pnl_from_ledger(ledger: pd.DataFrame) -> pd.DataFrame:
    """按股汇总，与 ledger_frame 同源。"""
    if ledger.empty:
        return pd.DataFrame(
            columns=[
                "instrument",
                "round_trips",
                "wins",
                "losses",
                "realized_pnl",
                "unrealized_pnl",
                "est_costs",
                "total_entry_value",
                "held_days_sum",
                "first_date",
                "last_date",
                "still_held",
                "total_pnl",
                "return_on_cost",
            ]
        )
    rows = []
    for inst, g in ledger.groupby("instrument", sort=True):
        g = g.sort_values("date")
        sells_flat = g[(g["event"] == "sell") & (g["amount_after"] <= 1e-9)]
        round_trips = int(len(sells_flat))
        wins = int((sells_flat["realized_pnl"] > 0).sum())
        losses = int((sells_flat["realized_pnl"] <= 0).sum()) if round_trips else 0
        realized = float(g["realized_pnl"].sum())
        last = g.iloc[-1]
        still_held = float(last["amount_after"]) > 1e-9
        unrealized = float(last["unrealized_pnl"]) if still_held else 0.0
        buys = g[g["event"] == "buy"]
        total_entry = float(buys["trade_value"].sum()) if len(buys) else 0.0
        rows.append(
            {
                "instrument": inst,
                "round_trips": round_trips,
                "wins": wins,
                "losses": losses,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "est_costs": float(g["est_cost"].sum()),
                "total_entry_value": total_entry,
                "held_days_sum": int(g.loc[g["amount_after"] > 1e-9, "holding_days"].max() or 0)
                if still_held
                else int((g["event"] == "hold").sum() + (g["event"] == "buy").sum()),
                "first_date": g["date"].iloc[0],
                "last_date": g["date"].iloc[-1],
                "still_held": bool(still_held),
            }
        )
    df = pd.DataFrame(rows)
    df["total_pnl"] = df["realized_pnl"] + df["unrealized_pnl"]
    df["return_on_cost"] = df["total_pnl"] / df["total_entry_value"].replace(0, pd.NA)
    return df.sort_values("total_pnl", ascending=False, ignore_index=True)


def pred_score_frame(pred: Any) -> pd.DataFrame:
    """Normalize recorder pred.pkl / Series / DataFrame to datetime, instrument, score."""
    if pred is None:
        raise ValueError("pred is required")
    if isinstance(pred, pd.Series):
        frame = pred.rename("score").reset_index()
    elif isinstance(pred, pd.DataFrame):
        frame = pred.reset_index() if isinstance(pred.index, pd.MultiIndex) else pred.copy()
    else:
        raise TypeError(f"unsupported pred type: {type(pred)!r}")
    cols = list(frame.columns)
    if "score" not in frame.columns:
        raise ValueError("pred missing score column")
    if "datetime" not in frame.columns or "instrument" not in frame.columns:
        leftover = [c for c in cols if c != "score"]
        if len(leftover) < 2:
            raise ValueError("pred needs datetime, instrument, score")
        rename = {}
        if "datetime" not in frame.columns:
            rename[leftover[0]] = "datetime"
        if "instrument" not in frame.columns:
            inst_src = leftover[1] if leftover[0] in rename else leftover[0]
            rename[inst_src] = "instrument"
        frame = frame.rename(columns=rename)
    out = frame.loc[:, ["datetime", "instrument", "score"]].copy()
    out["datetime"] = pd.to_datetime(out["datetime"], errors="raise").dt.normalize()
    out["instrument"] = out["instrument"].astype(str)
    out["score"] = pd.to_numeric(out["score"], errors="raise")
    return out


def daily_picks_frame(
    pred: Any,
    snapshots: dict,
    *,
    topk: int = 10,
    asof: str = "pred_minus_one",
) -> pd.DataFrame:
    """每日荐股：pred TopK（asof=pred_minus_one → 交易日 T 用 T-1 分）对照当日实持。

    action:
      new_buy        TopK 且当日新开仓
      held           TopK 且已在仓
      missed         TopK 但未持有（涨停拒单 / 资格过滤 / n_drop 惯性）
      held_not_topk  在仓但不在当日 TopK（n_drop / hold_thresh 留仓）
    """
    if topk <= 0:
        raise ValueError("topk must be greater than zero")
    if asof not in {"pred_minus_one", "identity"}:
        raise ValueError(f"unsupported asof: {asof}")

    scores = pred_score_frame(pred)
    ranked_by_pred: dict[pd.Timestamp, pd.DataFrame] = {}
    pred_dates: list[pd.Timestamp] = []
    for pred_date, day in scores.groupby("datetime", sort=True):
        pred_dates.append(pred_date)
        ranked = day.sort_values(["score", "instrument"], ascending=[False, True], kind="mergesort")
        ranked = ranked.drop_duplicates("instrument", keep="first").reset_index(drop=True)
        ranked = ranked.assign(rank=ranked.index + 1)
        ranked_by_pred[pred_date] = ranked

    snap_days = sorted(snapshots.keys())
    rows: list[dict[str, Any]] = []

    def emit(trade_day: pd.Timestamp, pred_date: pd.Timestamp) -> None:
        ranked = ranked_by_pred.get(pred_date)
        if ranked is None or ranked.empty:
            return
        held = snapshots.get(trade_day, {})
        top_insts = set(ranked.loc[ranked["rank"] <= topk, "instrument"])
        extra_held = [i for i in held if i not in top_insts]
        watch = list(ranked.loc[ranked["rank"] <= topk, "instrument"]) + extra_held
        rank_map = dict(zip(ranked["instrument"], ranked["rank"]))
        score_map = dict(zip(ranked["instrument"], ranked["score"]))
        seen: set[str] = set()
        for inst in watch:
            if inst in seen:
                continue
            seen.add(inst)
            in_top = inst in top_insts
            in_port = inst in held
            streak = int(held[inst][2]) if in_port else 0
            if in_top and in_port and streak <= 1:
                action = "new_buy"
            elif in_top and in_port:
                action = "held"
            elif in_top:
                action = "missed"
            else:
                action = "held_not_topk"
            rows.append(
                {
                    "trade_date": _iso(trade_day),
                    "pred_date": _iso(pred_date),
                    "rank": int(rank_map[inst]) if inst in rank_map else None,
                    "instrument": inst,
                    "score": float(score_map[inst]) if inst in score_map else None,
                    "held": in_port,
                    "holding_days": streak,
                    "action": action,
                }
            )

    if asof == "identity":
        for pred_date in pred_dates:
            emit(pred_date, pred_date)
    else:
        for i, pred_date in enumerate(pred_dates):
            if i + 1 >= len(pred_dates):
                continue
            emit(pred_dates[i + 1], pred_date)
        # 回测首日可能早于 pred 的「下一交易日」映射；补上 snapshot 有、上面没 emit 的交易日
        emitted = {r["trade_date"] for r in rows}
        for trade_day in snap_days:
            if _iso(trade_day) in emitted:
                continue
            prev_preds = [d for d in pred_dates if d < trade_day]
            if not prev_preds:
                continue
            emit(trade_day, prev_preds[-1])

    return pd.DataFrame(rows)


def nav_from_report(report: pd.DataFrame) -> pd.DataFrame:
    """PortAna report_normal_1day → 日净值表。"""
    if report is None or len(report) == 0:
        return pd.DataFrame()
    frame = report.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        if "datetime" in frame.columns:
            frame = frame.set_index("datetime")
        else:
            frame.index = pd.to_datetime(frame.index)
    frame = frame.reset_index()
    date_col = frame.columns[0]
    frame = frame.rename(columns={date_col: "date"})
    frame["date"] = pd.to_datetime(frame["date"]).dt.date.map(lambda d: d.isoformat())
    return frame


def build_qlib_close_lookup(snapshots: dict) -> CloseLookup | None:
    """Batch $close for exit-day prices. None if empty or D.features fails."""
    days = sorted(snapshots.keys())
    insts = sorted({i for snap in snapshots.values() for i in snap})
    if not days or not insts:
        return None
    from qlib.data import D  # 调用方已 qlib.init

    close_df = D.features(insts, ["$close"], days[0], days[-1])["$close"]

    def close_of(inst: str, day: pd.Timestamp) -> float | None:
        try:
            v = close_df.loc[(inst, day)]
        except KeyError:
            return None
        return float(v) if v == v else None

    return close_of


def write_analysis_bundle(
    *,
    positions: Mapping,
    out_dir: str | Path,
    open_rate: float,
    close_rate: float,
    min_cost: float = 5.0,
    account: float = 1e8,
    pred: Any = None,
    report: pd.DataFrame | None = None,
    topk: int = 10,
    asof: str = "pred_minus_one",
    close_of: CloseLookup | None = None,
    use_qlib_close: bool = False,
    extra_summary: Mapping[str, Any] | None = None,
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Write the analysis CSV pack. Returns {paths, summary}."""
    from contextlib import nullcontext

    try:
        from custom_utils import maybe_timer as _span
    except Exception:  # pragma: no cover - recorder is optional
        def _span(_name: str):
            return nullcontext()

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with _span("analysis.positions_frame"):
        pos_df, snapshots = positions_frame(positions)
    if close_of is None and use_qlib_close:
        with _span("analysis.close_lookup"):
            try:
                close_of = build_qlib_close_lookup(snapshots)
            except Exception as exc:
                print(f"[export] close lookup skipped: {exc}", flush=True)
                close_of = None
    with _span("analysis.ledger"):
        trd_df = trades_frame(snapshots, open_rate, close_rate, min_cost=min_cost, close_of=close_of)
        led_df = attach_portfolio_context(
            ledger_frame(snapshots, open_rate, close_rate, min_cost=min_cost, close_of=close_of),
            pos_df,
        )
        pnl_df = pnl_from_ledger(led_df)
    with _span("analysis.daily_picks"):
        picks_df = daily_picks_frame(pred, snapshots, topk=topk, asof=asof) if pred is not None else pd.DataFrame()
        nav_df = nav_from_report(report) if report is not None else pd.DataFrame()

    names = {
        "positions_daily": pos_df,
        "trades_daily": trd_df,
        "ledger_by_stock": led_df,
        "pnl_by_stock": pnl_df,
        "daily_picks": picks_df,
        "nav_daily": nav_df,
    }
    paths: dict[str, str] = {}
    for name, frame in names.items():
        if name in {"daily_picks", "nav_daily"} and frame.empty and (
            (name == "daily_picks" and pred is None) or (name == "nav_daily" and report is None)
        ):
            continue
        dest = out / f"{name}.csv"
        frame.to_csv(dest, index=False, encoding=encoding)
        paths[name] = str(dest)

    last_total = None
    if len(pos_df):
        last_day = pos_df["date"].iloc[-1]
        last_total = float(pos_df.loc[pos_df["date"] == last_day, "total_value"].iloc[-1])
    sum_pnl = float(pnl_df["total_pnl"].sum()) if len(pnl_df) else 0.0
    nav_delta = float(last_total - account) if last_total is not None else None
    buys = int((trd_df["side"] == "buy").sum()) if len(trd_df) else 0
    sells = int((trd_df["side"] == "sell").sum()) if len(trd_df) else 0
    summary: dict[str, Any] = {
        "days": int(len(snapshots)),
        "position_rows": int(len(pos_df)),
        "trades_rows": int(len(trd_df)),
        "ledger_rows": int(len(led_df)),
        "pnl_rows": int(len(pnl_df)),
        "picks_rows": int(len(picks_df)),
        "nav_rows": int(len(nav_df)),
        "buys": buys,
        "sells": sells,
        "win": int((pnl_df["total_pnl"] > 0).sum()) if len(pnl_df) else 0,
        "loss": int((pnl_df["total_pnl"] <= 0).sum()) if len(pnl_df) else 0,
        "pnl_total": sum_pnl,
        "nav_delta": nav_delta,
        "pnl_nav_diff": (sum_pnl - nav_delta) if nav_delta is not None else None,
        "open_rate": open_rate,
        "close_rate": close_rate,
        "min_cost": min_cost,
        "account": account,
        "topk": topk,
        "asof": asof,
        "files": {k: Path(v).name for k, v in paths.items()},
    }
    if extra_summary:
        summary.update(dict(extra_summary))
    summary_path = out / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    paths["summary"] = str(summary_path)
    return {"paths": paths, "summary": summary, "out_dir": str(out)}


def print_bundle_summary(bundle: Mapping[str, Any]) -> None:
    s = bundle["summary"]
    nav_delta = s.get("nav_delta")
    diff = s.get("pnl_nav_diff")
    nav_txt = f"{nav_delta:,.0f}" if nav_delta is not None else "n/a"
    diff_txt = f"{diff:,.0f}" if diff is not None else "n/a"
    print(
        f"[pnl] stocks={s['pnl_rows']} win={s['win']} loss={s['loss']} "
        f"total_pnl={s['pnl_total']:,.0f} nav_delta={nav_txt} diff={diff_txt}",
        flush=True,
    )
    print(
        f"[export] days={s['days']} position_rows={s['position_rows']} "
        f"trades={s['trades_rows']} (buy={s['buys']} sell={s['sells']}) "
        f"ledger={s['ledger_rows']} picks={s['picks_rows']}",
        flush=True,
    )
    for key, path in bundle["paths"].items():
        print(f"=== {key}: {path} ===")
