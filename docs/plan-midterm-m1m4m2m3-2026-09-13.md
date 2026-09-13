# 中期落地计划：M1 全量 bin → M4 manifest → M2 筹码 parity → M3 ranking-only

- 日期：2026-09-13
- 状态：v1；M1 已合 #8；M4+M3-A 已合 #9；M2 已合 #10（不可比关门）；本波 `feat/m3-ranking-only` = M3-B→C 已交，M3-D **blocked**（无行业源）
- 上游：`docs/plan-three-repo-roadmap-2026-09-12.md` v1.3 §0/§4（本轮 = 中期项落地）；数据现状见 `docs/qlib-data-state-2026-09-13.md`
- 执行顺序：M1 → M4 → M2 → M3（M4 的 manifest 是 M3 sweep 的依赖）。L2 不在本计划

---

## §0 硬约束（Codex 必读，全部实踩验证过）

**数据管道**
1. `dump_all` 必须 `--max_workers 8`——16 在 Windows 进程池回收处死锁（2026-09-13 两次复现）
2. `dump_update` **禁用**：按个股自身日期 append，停牌一天整体错位一天
3. 指数绝不能留在 `instruments/all.txt`（`market="all"` 宇宙污染）；`patch_index_data.py` 第 4 步负责挪 `index.txt`
4. 湖 `time` 列是 UTC 毫秒，转 Asia/Shanghai 再取日期
5. 不能从 `cn_data` 拷 bin（日历不同，全错位）；湖股票日线只有 7 列，不能单独作训练源

**训练/运行**
6. `handler_init` ~18 分钟：涉及训练代码的片，验证合批跑，一片一跑会耗死
7. `MLFLOW_ALLOW_FILE_STORE` 已在脚本内设置，勿删；训练从 `my_scripts/` 目录跑（产物落 CWD）
8. as-of 契约已锁（`pred_minus_one`：file[T]=TopN(pred[prev(T)])），不重开
9. 池 CSV 字节契约：LF 无 BOM、裸 6 位码（`test_export_daily_pool` 锁着，别破）

**流程**
10. 从 master 切 `feat/fix` 分支；提交信息中文用 `git commit -F <文件>`（bash 内联 `-m` 中文会出转义事故）
11. 测试门槛 = 全量：`python -m pytest my_tests my_scripts/test_zhangting_filter.py`（当前基线 **25 passed + 18 subtests**），不是只跑新文件
12. 每片完成回写路线图 §0 进度（一行即可）
13. `~/.qlib` 数据只准通过 M1 的 orchestrator 动，动手前自动备份（命名 `my_data_backup_YYYYMMDD_pre_*`）
14. 补（2026-09-13 M3D-D 备料实踩）：**任何直接/间接触发 qlib joblib 多进程的入口脚本**（`D.features`、`DatasetH` 等）**必须 `if __name__ == "__main__":` + `multiprocessing.freeze_support()`**——Windows spawn 下 worker 会重执行主脚本，顶层裸跑 = 每个 worker 递归再拉数据、无限喷 `RuntimeError`。训练脚本历来带 guard 即此因；一次性备料/分析脚本同样适用。失控时按命令行特征定位进程树（`multiprocessing.spawn`/`loky`）定点 `taskkill /T`，勿盲杀全仓 python

**判优纪律**
14. 模型好坏只看 IC/IR/名单命中率；PortAna 净值、单窗 M5 NAV 都不是产品（首轮 M5 已证明三源名单几乎不重叠）

---

## §1 M1：刷新管道固化（当前手工流程 → 一条命令）

现状：刷新 = 手工串 `merge_archive_and_csv.py` → `dump_all(8)` → 换目录 → `patch_index_data.py` → 7z → F/G 副本。全跑通过一次（2026-09-13）。M1 把它变成可交给任何人/agent 的一条命令。

| 片 | 内容 | 验收 |
|---|---|---|
| M1-A | `qlib_scripts/refresh_mydata.py` 骨架 + `--dry-run`：编排现有三件套（子进程调用，不改它们接口），dry-run 打印完整计划（staging 路径、目标目录、宇宙变化预估） | dry-run 输出含每步命令与目标路径；参数校验单测 |
| M1-B | swap + 完整性门禁：原子 `mv`（失败自动回滚）；门禁四条——①新日历 vs 湖 `000001_SH` 逐日对齐 0 缺失 ②抽样双端值核对（首日/末日各 3 只 vs 源 CSV）③`all.txt` 无指数 ④新旧宇宙 diff 报告（新增/退市列表打印，退市数>预期要人工确认 `--force` 才过） | 门禁失败必须中止且不换目录；门禁逻辑单测（含构造失败用例） |
| M1-C | `--archive`：按惯例打 `my_data_YYYYMMDD_full.7z`（7-Zip 路径 `C:\Program Files\7-Zip\7z.exe`）+ `--offsite` 拷 F:/G: 并 MD5 三方校验 | 生成物与校验值打印；小目录 fixture 单测 |
| M1-D | 文档回写：`qlib-data-state` 文档加「标准刷新流程=orchestrator」一节；提示词的全量刷新段指向它 | review |

依赖：无。M1-B 依赖 M1-A；C 依赖 B；D 收尾。

## §2 M4：run manifest（结果可追溯）

现状：`timing_*.json` 只有耗时。M4 定一个三仓同格式的 manifest 契约并接入两处。

schema（`myquant.run-manifest/1`，JSON，UTF-8 无 BOM）：

```json
{
  "schema": "myquant.run-manifest/1",
  "stage": "train | export | refresh",
  "git_commit": "<HEAD>",
  "created_utc": "...",
  "config": {"key": "value", "config_hash": "sha256(canonical json)"},
  "data": {"calendar_first": "...", "calendar_last": "...", "calendar_days": 1621, "calendar_md5": "..."},
  "artifacts": [{"path": "...", "md5": "...", "rows": 0}],
  "timings": {"total_seconds": 0, "nodes": []}
}
```

| 片 | 内容 | 验收 |
|---|---|---|
| M4-A | `my_scripts/run_manifest.py` 纯模块：构建/校验/写盘（`manifests/<stage>_<UTC>.json`，随产物同目录放一份）；schema 版本化 | 单测：确定性（同输入同 hash）、artifacts 指纹、坏 schema 拒收 |
| M4-B | 接入训练：`custom_train_backtest.py` 收尾时产出 train manifest（含 segments/topk/n_drop、pred.csv 指纹、TimerRecorder 节点） | 重训一次（合批验证）出合法 manifest |
| M4-C | 接入导出：`export_daily_pool.py` 产 export manifest（pred 文件 md5、asof、topk、输出目录文件数）；`docs/run-manifest-spec.md` 落 schema 契约（backtrader 仓后续对齐用，本仓不改它） | 导出一窗出 manifest；spec 文档 review |

依赖：M4-A 独立；B 依赖 A（且尽量与 M3-A 合批重训）；C 依赖 A。

## §3 M2：筹码 parity（晋升门，不是日常 CI）

前提认知：本仓筹码量（bin 的 `netcsfree/basiccurhold/...` + COST 特征）与 backtrader 仓 `qlib_cost/cyq` 是两套实现。M2 先回答「可比吗」，再回答「数值一致吗」。**映射结论为不可比是合法终点，记录后关门。**

| 片 | 内容 | 验收 |
|---|---|---|
| M2-A | 概念映射表 `docs/chip-parity-map.md`：本仓字段/特征 ↔ backtrader 仓函数（逐量：定义、单位、复权口径、窗口）；明确哪些可比哪些不可比 | 映射表 review；若「无比对对象」→ 记录并终结 M2 |
| M2-B | golden 导出 + 比较器：固定窗口 2026-03-02~03-23、固定 8 只（600000/300190/920014 等，含北交所）；`my_scripts/chip_parity_check.py --bt-repo E:\PycharmProjects\MyQuant-backtrader`：调对方实现算同输入，容差（默认相对差 1e-4，可配）逐量报告，不一致 exit 1 | 构造两侧一致/不一致用例的单测（用 fake bt 模块注入） |
| M2-C | 晋升门文档：什么事件触发（策略要用筹码量晋升 Paper 前）、通过标准、结果归档 `docs/chip-parity-report-<date>.md` | review |

依赖：M2-A 独立先行；B 依赖 A 的映射结论。

## §4 M3：ranking-only 模型迭代（只动排序，不动成交）

| 片 | 内容 | 验收 |
|---|---|---|
| M3-A | 涨停剔除训练集：learn 阶段丢 `$zhangting==1` 样本（processor 实现，勿动 infer/导出池）；与基线同窗重训对比 IC/IR | 单测（样本数变化断言）+ 合批重训的对比表；manifest 留档（依赖 M4-B） |
| M3-B | sweep harness：配置（topk/n_drop/持有期网格）→ 逐配置训练/预测 → IC/IR 汇总表 + 每配置 manifest；`--limit 2` 调试档 | **已交** `sweep_ranking.py`（注入/fake；宿主 live 待跑） |
| M3-C | 特征实验：仅限 bin 16 字段可算的新特征（如换手阻力近似）；逐特征 NaN 率检查 + 单窗 IC 增量 | **已交** `feature_experiments.py`（合成窗；宿主真 bin 待跑） |
| M3-D | 行业/市值中性化（**条件片**）：先盘点行业分类数据源（F:\disclosure_data、湖内有无 industry 表）；有则实现截面中性化后取 TopN，无源则记录 blocked 跳过 | **blocked** 见 `docs/m3d-industry-source-inventory.md` |

依赖：M3-A/B 依赖 M4-B（合批重训时顺带产出 manifest）；M3-B 先行于 C/D。

---

## §5 里程碑与顺序

```
M1-A → M1-B → M1-C → M1-D        （刷新管道，~1-2 天）
M4-A → (M4-B + M3-A 合批重训) → M4-C   （manifest，~1 天 + 一次 18 分钟重训）
M2-A → M2-B → M2-C               （parity，~1 天，可能提前关门）
M3-B → M3-C → M3-D               （ranking-only，重训量大，合批）
```

## §6 明确不做

- L2（名单 → trade_decision → LEBS）——以后单独出计划
- 不动 backtrader 仓 / 1.3 仓的任何代码（M2 只读对方实现）
- 不用 PortAna 净值 / 单窗 M5 NAV 判优（首轮 M5 已证名单三源几乎不重叠）
- 不重开 as-of 语义；不改池 CSV 字节契约
- 不造第四套引擎；成交仿真一律不出本仓
