# 任务书：sweep 窗口参数化（OOS 出窗复验的前置）

- 日期：2026-09-13
- 背景：路线图 §0.2 标注 M3-B 首张网格表是「16 日单窗线索，出窗复验待做（OOS 建议 2026-04~09、改参前）」。当前
  `sweep_live_adapter.py` 的 `SEGMENTS` 写死三月窗，无法跑 OOS。本任务参数化后由宿主执行 OOS。
- 约束沿用 `docs/plan-midterm-m1m4m2m3-2026-09-13.md` §0（全量测试门槛，当前基线 **95 passed + 18 subtests**）

---

## 任务：`--segments` 参数贯通 sweep → adapter

**现状**：`sweep_ranking.py` 只认网格参数；`sweep_live_adapter.SEGMENTS` 是模块常量（train 2026-01 /
valid 2026-02 / test 2026-03-01..03-23），`_predict_once()` 直接引用。

**接口设计**：
1. `sweep_ranking.py` 新增三参数（均可选，缺省=维持现状三月窗，**向后兼容是硬要求**）：
   `--train 2026-01-01:2026-01-31`、`--valid ...`、`--test ...`（`START:END` 格式，非法格式直接报错退出）
2. 装载 adapter 后、跑网格前，若用户给了任何一段，调用 adapter 暴露的 `set_segments(dict)`；
   未给则不调用（adapter 用默认）。**不要**把窗口塞进 SweepConfig——那是网格维度，窗口是运行维度
3. `sweep_live_adapter.py`：
   - `SEGMENTS` 常量保留为默认值；新增模块级 `set_segments(segments)`（校验三段齐全、起止合法、
     train.start <= valid.start <= test.start），`_predict_once` 改读当前生效段
   - handler 的 `start_time/end_time` = 三段的最小 start / 最大 end（label 用 `Ref($close,-2)`，
     末尾 1-2 天 label 为 NaN 会被 dropna——与三月窗现行为一致，注释说明即可）
   - **返回 payload 的 `config` 里带上生效 segments**（train/valid/test 三段），确保每个网格格子的
     manifest 可区分窗口——否则两张 sweep_summary 无从分辨是哪窗
4. 输出目录建议带窗口后缀由宿主自己传 `--out-dir`（如 `sweep_out_oos_202604_202608`），CLI 不强制

**验收**：
- 单测：`--train/--valid/--test` 解析与非法格式拒绝；缺省不调 `set_segments`（向后兼容）；
  `set_segments` 的段序校验；payload config 含生效 segments
- 冒烟：`--dry-run-fake` 路径不受影响（fake 不走 adapter，注意别把 set_segments 调用挂到 fake 分支）
- 全量 pytest 绿

## 宿主侧后续（非本任务，写明闭环）

Codex 合入后，本机执行 OOS（一次 handler_init ~18 分钟 + 网格轻计算）：

```bash
cd my_scripts && MLFLOW_DISABLE_AGENT_HINT=1 python sweep_ranking.py \
    --adapter sweep_live_adapter --topk 5,10,20 --n-drop 2,3 --hold 1 \
    --train 2026-01-01:2026-01-31 --valid 2026-02-01:2026-02-28 \
    --test 2026-04-01:2026-08-31 \
    --out-dir sweep_out_oos_202604_202608
```

判读纪律（预先写死，防事后挑窗口）：
- 三月窗结论只有**两窗同号/同排序**才 survives；topk5_ndrop2 若出窗翻车，三月表按窗口依赖处理
- 出窗表回写路线图 §0.2（含 hit/ir 两列与三月表并排）
- 无论结果如何，不改线上 topk 默认值——改参是 M3 之后、且要有第三个窗口佐证的事
