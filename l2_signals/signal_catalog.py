"""信号代号目录（SSOT）——口头称呼与代码里的字符串应对齐这里。

命名约定
--------
- 规范名 = 英文 SNAKE_CASE（代码 / CSV / meta / CLI `--signal` 唯一键）
- 中文名 = 口头别名，可多词，不进文件名
- 不改已占用的代号（STAB_LOW_TREND、STEP_DIP_ACCUM 等），只增不改

两代信号
--------
- gen0：grok-bot-ops 六信号族（条件搜索时代，样本/可交易性未充分验收）
- gen1：Alpha158 × C1 联合搜索（本模块主线）
- gen2：净大单×MA20上穿 池 × Alpha158（用户两核心指标池，2026-11-05 起）

用法
----
    from signal_catalog import by_id, list_signals
    by_id("QUIET_DIP_ACCUM")["zh"]   # -> 缩量阴线吸筹
"""
from __future__ import annotations

from typing import Any

# status: active | candidate | archived | deprecated | rejected
# pool: 默认都在 C1（大单量≥2×前日）；另有说明写在 notes

CATALOG: list[dict[str, Any]] = [
    # ---------- gen0：六信号族 ----------
    {
        "id": "STEP_DIP_ACCUM",
        "zh": "阶跃回调吸筹",
        "gen": 0,
        "status": "archived",
        "conds_human": "C1 + ret_prev<0 + ret_1d<0 + bs<0.10",
        "card": "docs/l2_signals/2026-11-04-step-dip-accum-signal-card.md",
        "reproduce": "l2_signals/reproduce_gen0_signals.py --signal STEP_DIP_ACCUM",
        "notes": "六族最强主题种子（21/76.2%）；黄金 Exact。"
                 "注意：是收盘跌而非 KMID<0。样本极小，未跨年验收。",
    },
    {
        "id": "QUIET_DIP_TECH",
        "zh": "静阴技术",
        "gen": 0,
        "status": "rejected",
        "conds_human": "C1+C4（无大单；与 ACCUM 同口径的 C1/C4）",
        "card": "docs/l2_signals/2026-11-04-quiet-dip-tech-signal-card.md",
        "reproduce": "l2_signals/reproduce_quiet_dip_tech.py",
        "notes": "交接曾写 805/67.8%，可执行口径 2026≈4.1万/50.2%、2025≈5.3万/51.3%，"
                 "原数字无法复现。",
    },
    {
        "id": "QUIET_DIP_ACCUM",
        "zh": "缩量阴线吸筹",
        "gen": 0,
        "status": "archived",
        "conds_human": (
            "C1 阴线守MA5（开≤昨收×1.02∧高≤昨收×1.04∧收<昨收∧收<开∧收>MA5）"
            " + C2 净量/流通>2% + C3 T-1涨幅≤5% + C4 T-1阳线∧震幅/收<5%"
        ),
        "card": "docs/l2_signals/2026-11-04-quiet-dip-accum-signal-card.md",
        "reproduce": "l2_signals/reproduce_quiet_dip_accum.py",
        "notes": "2026 n=18 / 61.1%（Exact）。勿与 QUIET_LOW_TREND / QUIET_DIP_TECH 混称。",
    },
    {
        "id": "MEGA_ORDER_ACCUM",
        "zh": "极大单吸筹",
        "gen": 0,
        "status": "archived",
        "conds_human": "nfr_vol=(bov−sov)/ffv > 5%",
        "card": "docs/l2_signals/2026-11-04-mega-order-accum-signal-card.md",
        "reproduce": "l2_signals/reproduce_gen0_signals.py --signal MEGA_ORDER_ACCUM",
        "notes": "一日动量；黄金 Exact 1321。持有>2日失效。",
    },
    {
        "id": "VOL_SURGE_BUY",
        "zh": "放量买强",
        "gen": 0,
        "status": "rejected",
        "conds_human": "C1 + bov>sov + close>MA20 + close>MA100 + nbam>3000万",
        "card": "docs/l2_signals/2026-11-04-vol-surge-buy-signal-card.md",
        "reproduce": "l2_signals/reproduce_gen0_signals.py --signal VOL_SURGE_BUY",
        "notes": "命名卡定稿名；与 BIG_ORDER_STEP 同条件。反指 ~45%。"
                 "big_order_step_v2/v3 CSV 非本条件 Exact。",
    },
    {
        "id": "BIG_ORDER_STEP",
        "zh": "大单阶跃（原版）",
        "gen": 0,
        "status": "rejected",
        "conds_human": "同 VOL_SURGE_BUY（C1+C2+C3+C4）",
        "card": "docs/l2_signals/2026-11-04-vol-surge-buy-signal-card.md",
        "reproduce": "l2_signals/reproduce_gen0_signals.py --signal BIG_ORDER_STEP",
        "notes": "六族交接旧名；请优先用 VOL_SURGE_BUY。",
    },
    {
        "id": "DIP_CATCH_FALL",
        "zh": "接刀吸筹",
        "gen": 0,
        "status": "rejected",
        "conds_human": "close<昨收 + nfr_vol>2%",
        "card": "docs/l2_signals/2026-11-04-dip-catch-fall-signal-card.md",
        "reproduce": "l2_signals/reproduce_gen0_signals.py --signal DIP_CATCH_FALL",
        "notes": "反指 42.5%；黄金全覆盖。",
    },
    # ---------- gen1：Alpha158 主线 ----------
    {
        "id": "STAB_LOW_TREND",
        "zh": "低位企稳趋势",
        "gen": 1,
        "status": "candidate",
        "conds_human": "C1 + IMIN10≤q20 + QTLD30≥q80 + RSQR5≥q80（剔 KMID=0）；"
                       "阈值冻结自 2026-H1",
        "card": "docs/l2_signals/2026-11-04-stab-low-trend-signal-card.md",
        "reproduce": "l2_signals/export_signal.py --signal STAB_LOW_TREND",
        "notes": "当前主研究信号。跨年裸信号不稳定（regime 依赖），滚动门控亦非四年通吃。",
    },
    {
        "id": "QUIET_LOW_TREND",
        "zh": "安静低位趋势（废弃）",
        "gen": 1,
        "status": "deprecated",
        "conds_human": "LOW0≥q80 + QTLU5≤q20 + RSQR5≥q80",
        "card": "",
        "reproduce": "",
        "notes": "一字/T 字板污染（65% 买不进）。保留代号供对照，导出器拒绝无 H2 验证导出。"
                 "勿与 gen0 QUIET_DIP_ACCUM 混称。",
    },
    # ---------- gen2：净大单×MA20上穿 池 ----------
    {
        "id": "MEGA_MA20_BREAK",
        "zh": "大单破线确认",
        "gen": 2,
        "status": "candidate",
        "conds_human": "净大单量/流通>2% & MA20当日首站(cross_age=0) & MAX5<=1.0"
                       " & SUMP20>=q80 & VSUMP20=mid（剔 KMID=0）；阈值冻结自 2026-H1",
        "card": "docs/l2_signals/2026-11-05-mega-ma20-break-signal-card.md",
        "reproduce": "l2_signals/export_signal.py --signal MEGA_MA20_BREAK",
        "notes": "四年个体显著：62.3/74.5/62.5/71.2%（2023-2026，二项 p 全<0.05），"
                 "合计 243@67.1%。注意：A0 选择参考过跨年诊断，非严格样本外"
                 "（validate_ma20_mega_break.py 头部声明）。池为 gen2 池，非 C1。",
    },
]


def by_id(signal_id: str) -> dict[str, Any]:
    for row in CATALOG:
        if row["id"] == signal_id:
            return row
    raise KeyError(f"unknown signal id: {signal_id!r}; see signal_catalog.CATALOG")


def list_signals(*, gen: int | None = None, status: str | None = None) -> list[dict[str, Any]]:
    rows = CATALOG
    if gen is not None:
        rows = [r for r in rows if r["gen"] == gen]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return rows


def format_table() -> str:
    lines = [
        f"| {'代号':<22} | {'中文名':<16} | gen | status     |",
        f"|{'-'*24}|{'-'*18}|-----|------------|",
    ]
    for r in CATALOG:
        lines.append(
            f"| {r['id']:<22} | {r['zh']:<16} |  {r['gen']}  | {r['status']:<10} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):  # GBK 控制台遇 U+2212 等字符会崩，统一 utf-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(format_table())
    print()
    for r in CATALOG:
        print(f"[{r['id']}] {r['zh']}  — {r['conds_human']}")
        if r.get("card"):
            print(f"  card: {r['card']}")
        if r.get("reproduce"):
            print(f"  run:  {r['reproduce']}")
