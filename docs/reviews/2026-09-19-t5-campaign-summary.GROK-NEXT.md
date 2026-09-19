# Grok 复核：T5 下一步补强（ecc40b7）

- **Verifier**: Grok 4.6（只读核对主文「下一步」节 + `git show ecc40b7`；未重算实验、未改事实包）
- **tip SHA**: `ecc40b7`（`docs: expand T5 summary next-steps (BT points 1–7)`）

**VERDICT: PASS**

相对 BT 要点 1–7：

1. COVERED — 停新刀；MAXRET/WRD1 A 有条件信息、进 LGB 未过 B；再加一列难抬净收益；主战场=组合/风险/成本/成交（净收益仅作资源安排，非已验证）。
2. COVERED — 定性「信息有、组合没」；MAXRET 伤头、WRD1 伤底（口径不混）；三条线并行。
3. COVERED — 组合与约束最优先；只读 pred `8a061ea4`；行业/市值中性、换手上限、禁止追近端大涨、尾部暴露。
4. COVERED — 成本与成交挂名 Mode B / MyQuant-backtrader；同信号对照不同成交假设。
5. COVERED — 信号作过滤/降权/否决；不新开 LGB；主模型不动。
6. COVERED — 不建议再扫刀、为过 B 扫 seed/窗、动线上 10/3、没过组合层就把 PortAna 当真钱。
7. COVERED — 若只选一步：冻结特征约一周；组合约束+分钟成交只读对照；输入 `8a061ea4`；验收换手/回撤/净超额不是 RankIC。

**FABRICATED_METRICS: NO** — 节首写明「研究顺序建议，非事实包已验证收益结论」；成交段明示不填成交率/滑点/净超额数字；未见编造数值。

**N1_OK: YES** — 主文无「经本地 HEAD 核验」；事实包 tip `ecde0f7` 与初次提交 `2d33d68` 仍区分；本 commit 未改该段。

**ONLINE_UNTOUCHED: YES** — `ecc40b7` 只改两份 docs（主文「下一步」节 + REVIEW 末尾 follow-up）；线上 pred `8a061ea4` / 10/3 未被本 commit 改动。

一句话结论：下一步节按 BT 1–7 写全且边界清楚，可按现状作为研究顺序交付。
