# 后续修复：共享 env 模块 + manifest 启动时取 commit（交 Codex）

- 日期：2026-09-13
- 来源：M3 宿主跑批当天实踩的三个教训（两个代码修 + 一个文档回写）
- 约束沿用中期计划 §0：全量测试门槛（当前基线 **90 passed + 18 subtests**）、每任务一分支一 PR、中文提交信息 `git commit -F`

---

## 任务 1：共享 env 模块（根治「每脚本一份逃生口」）

**事故**：sweep 进程白付 17 分钟 handler_init 后死于 mlflow file-store maintenance mode——逃生口
`os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")` 只写在 `custom_train_backtest.py` 里；
`sweep_live_adapter.py` 是事后补的又一份。同类问题会随入口脚本数量线性增长。

**做法**：
1. 新建 `my_scripts/host_env.py`（名字可议）：模块级 `setdefault`
   - `MLFLOW_ALLOW_FILE_STORE=true`（mlflow file-store 逃生口）
   - `MLFLOW_DISABLE_AGENT_HINT=1`（顺手静音刷屏，幂等）
2. 所有触碰 qlib 工作流的入口在 **任何 qlib import 之前** `import host_env`：
   `custom_train_backtest.py`、`sweep_live_adapter.py`、`feature_experiments.py`、
   `sweep_ranking.py`、`export_daily_pool.py`
3. 删掉 `custom_train_backtest.py` 与 `sweep_live_adapter.py` 里各自的 setdefault（单一来源）

**验收**：
- `grep -rn "MLFLOW_ALLOW_FILE_STORE" my_scripts/` 只命中 `host_env.py` 一处（及注释）
- 单测：子进程 `import host_env` 后 `os.environ["MLFLOW_ALLOW_FILE_STORE"]` 生效且不覆盖已有值（setdefault 语义）
- 全量 pytest 绿

## 任务 2：manifest 的 git_commit 改为启动时取

**事故**：run-5（2026-09-13 08:12）训练中途切了分支，manifest 收尾时才读 HEAD，记成了
`e587629`（适配器分支）而不是实际执行的 `80a2007`——产物溯源失真。

**做法**：
1. `custom_train_backtest.py` 入口（handler_init 之前）一次性取：
   `git rev-parse HEAD`（失败回退 `None`）、当前分支名、`git status --porcelain` 非空 → `git_dirty=true`
2. 传递到收尾的 `write_train_manifest`，schema 增加字段：`git_branch`、`git_dirty`
   （`git_commit` 语义改为「启动时 HEAD」，schema 版本是否 bump 由实现者判断——加字段不破坏旧读端则不 bump）
3. `sweep_live_adapter` 路径同样受益（handler 之前取）

**验收**：
- 单测：mock 两次不同的 `git rev-parse` 输出（启动真/收尾假），manifest 记录启动值 + branch + dirty
- 重训不必跑（单测覆盖即可），下次真跑顺带验证

## 任务 3：路线图 §0 回写（一行级）

把当天结果回写 `docs/plan-three-repo-roadmap-2026-09-12.md` §0：
- M3-A：IC 0.0183（持平）/ RankIC 0.0048（基线 3.4×）；首个真 train manifest
- M3-C：两窗真实筛**负结果**——turnover_resist_approx 三月 +0.138 → 六至八月 -0.069 符号翻转，四候选不入选
- M3-B：首张 6 格真网格表（topk5_ndrop2 双指标最佳，单窗线索，出窗复验待做）
- 事故两起（DropLimitUpLearn module_path / mlflow 逃生口）随任务 1/2 根治

**验收**：文档 review。

---

## 顺序与规模

任务 1、2 可并行（互不碰文件）；任务 3 收尾。预计各一个 PR、半天内完。
