# Codex R1 · d) 训练 / 导出 / sweep 调度

范围：墙钟调度——一次 init 多臂、manifest 计时节点、避免重复 Loading。不谈收益调参。

---

## 卡 1：统一「一次 handler_init → 多臂消费」调度面

**标题**：Train / Sweep / Export 共用「单次构建 + 多臂消费」契约

**本仓锚点**：`my_scripts/sweep_live_adapter.py` 已写明成本模型——pred/label 每进程只算一次（handler_init ~18min + fit ~5.6s），网格只做 TopN/指标；`predict_extended.py` 复用同一构建模式但独立入口；`sweep_ranking.py` 按格写 manifest、VM 故意不接 live。现状：一次 init 多配置只在 adapter 进程内成立，train→export 仍常另起进程再 Loading。

**提案**（调度级）：
1. 约定进程内「构建句柄」：`handler_span` 定界 → instruments → handler → dataset → model.fit → `pred/label`（或可选 dump model）只跑一次。
2. 臂类型拆开、禁止回灌构建：ranking 网格（topk/n_drop/hold）、export 池（asof/topk）、OOS 指标表——全部只读已缓存 pred/label。
3. CLI 合批：`--adapter` 路径下禁止「每格 subprocess 重训」；需要多窗时显式 `set_segments` + 清缓存，并在日志打 `INIT_ONCE` / `ARM_ONLY` 标记。
4. 合批验证片（HOST §1.5）挂同一调度面，禁止一片一跑重 init。

**收益**：N 格 sweep 墙钟从 ≈ N×(18min+) 压到 ≈ 1×init + N×秒级；与已测「整次真网格 ≈ 一次重训」对齐并可推广到 export 同进程附带。

**成本与风险**：切窗/改 gate/改 processors 若未清 `_STATE` → 脏 pred；Windows 多进程 spawn 会各自再 init（须单进程或显式共享产物）；臂逻辑误把 ranking 参数写进 handler 配置会假「多臂」。

**冻结检查**：同进程连续 2+ 臂日志仅一次 `handler_init`/`Loading`；改 segments 后必须出现二次 init；IC/IR 与单臂基线字节级可复现。

**对抗预填**：
- 「每臂独立进程更干净」→ 干净但白付 N×Loading；产物应用 pred CSV/manifest 溯源，而非重复构建。
- 「kernels>1 加速多臂」→ 与 #43 相反；调度优先省 init 次数，不拉高 kernels。

**建议裁决**：采纳（调度契约 + 日志断言；本轮不改产品代码，下轮实现）。

**重提条件**：若出现必须多进程的臂（真内存上限）——改为「一次 init 落 pred → 多进程只读 pred」，仍禁止每进程 Loading。

---

## 卡 2：Manifest 强制相位计时节点（可证伪调度）

**标题**：`timings.nodes` 标准化：Loading / handler_init / fit / predict / export / arms

**本仓锚点**：`docs/run-manifest-spec.md` 已有 `timings.nodes`（例 `handler_init`）；`custom_train_backtest.py` 用 `TimerRecorder` 包了 `handler_init`；但 `predict_extended.py` / `sweep_live_adapter.py` 路径常把空或缺失 timings 写入 `write_train_manifest`，sweep 多臂无法回答「时间花在哪」。mlflow 事故曾白付 ~17min init 后死——无相位则无法区分 init vs 逃生口失败。

**提案**（纪律级 + 调度级）：
1. 固定节点名（写入契约附录，不 bump schema 也可）：`qlib_init`、`Loading`（若可观测）、`handler_init`、`model_fit`、`predict`、`export`、`arm_grid`（整格合计）、可选 `mlflow_setup`。
2. 入口在 **任何 qlib import / handler 之前** 已 `import host_env`（逃生口）；计时从 `capture_git_provenance` 后起，收尾写 `total_seconds`。
3. sweep：仅第一臂填构建节点；后续臂只填 `arm_<id>` 秒级；summary 表加 `init_seconds` / `arms_seconds` 列。
4. CI/宿主读 manifest：若 `handler_init` 缺失或为 0 且 stage=train → 警告（防假成功）。

**收益**：砍掉「猜哪段慢」的整轮重跑；用节点对比 kernels=1 vs cache HIT（#43：16-kernel Loading ~52min miss vs ~405s）；一眼看出重复 Loading。

**成本与风险**：节点名漂移导致历史不可比；Timer 插桩过细干扰 Win 计时；把 arm 时间误记进 handler_init 会误导采纳缓存。

**冻结检查**：样例 manifest 含非空 `nodes` 且名在白名单；同配置二次跑 HIT 时 `handler_init` 应显著下降或出现 `handler_cache_hit` 节点；改 gate/窗必须 miss 且 init 回升。

**对抗预填**：
- 「只打 total 就够」→ total 无法指导调度（该合批还是该缓存）。
- 「用 mlflow 跑段计时」→ file-store 已事故；计时留在本仓 TimerRecorder/manifest。

**建议裁决**：采纳（契约补节点表 + 入口补齐；优先于新缓存层）。

**重提条件**：若 qlib 内部 Loading 无法拆出——允许合并为 `handler_init` 单节点，但必须与 `model_fit`/`predict` 分离（fit~5.6s 已证可忽略）。

---

## 卡 3：跨阶段产物交接——禁止 train 后再 Loading 做 export/sweep

**标题**：Pred/Label 落盘交接：export 与二次 sweep 零二次 Loading

**本仓锚点**：`predict_extended.py` 一次 ~25min（8 个月窗）出 pred CSV + train manifest；`docs/m5r2-export-qlib-arm.md` 要求 live predict → 再 export；`export_daily_pool` 写 export manifest。风险：人为「再跑一遍 custom_train_backtest / adapter」做导出或复筛，重复 Loading（#43 量级数分钟～数十分钟）。

**提案**（IO/调度级）：
1. 阶段机：`refresh(可选) → train|predict_extended(一次构建) → 产物(pred CSV + manifest) → export_daily_pool / sweep_ranking(--pred-from)`，后两段默认只读产物。
2. `sweep_ranking` 增「离线臂模式」：输入对齐好的 pred/label（或 pred+label 路径），跳过 adapter 构建；live adapter 仅宿主显式 `--live-init`。
3. manifest `artifacts` 必含 pred md5；export/sweep manifest `config` 引用上游 `train_manifest` 路径或 config_hash，形成链。
4. 文档/脚本抬头断言：无上游 pred 不得启动 handler_init 做 export。

**收益**：导出/复筛整轮从「再付一次 init」→ 秒～分钟级 IO；与过滤回测侧 cache 收益正交，专砍调度重复。

**成本与风险**：pred 与 segments/gate 漂移 → 脏池；Windows 路径/锁文件；离线臂与 live 指标口径不一致（须同一 label 定义：Alpha158 Ref close -2/-1）。

**冻结检查**：同一 pred md5 两次 export 池字节一致；故意改 pred 一字节 → export 结果变且 manifest 链断裂可测；live 与 `--pred-from` 同配置指标差在浮点容差内。

**对抗预填**：
- 「export 重训更新鲜」→ 新鲜度应来自 refresh/asof 纪律，不是重复 Loading。
- 「fetch 大 parquet 交接」→ HOST 禁止；只用现有 pred CSV/pickle 契约，禁巨型 fetch。

**建议裁决**：裁剪后采纳（先做 `--pred-from` + manifest 链文档；不在本轮引入新二进制格式）。

**重提条件**：若 pred CSV 成为瓶颈（极大宇宙）——再议 handler-cache pickle 交接，仍禁 fetch→parquet。

---

## 卡 4：昂贵路径预检闸——Init 前失败快返回

**标题**：handler_init 前：host_env / 磁盘 / 段校验 / 单实例锁

**本仓锚点**：`docs/plan-followups-env-and-manifest-2026-09-13.md`——sweep 白付 ~17min init 后死于 mlflow file-store；已抽 `host_env.py` 逃生口。`set_segments` 已有窗校验，但其它入口仍可能「先 Loading 再爆」。合批验证若片片撞锁/撞 mlflow，会耗死。

**提案**（纪律级）：
1. 统一 `preflight()`：`import host_env` → 检查 `MLFLOW_ALLOW_FILE_STORE` → provider_uri 存在 → segments 合法 → 可选 port/文件锁防双开训练。
2. 失败 **exit≠0 且不写假成功 manifest**；成功才进入计时节点 `handler_init`。
3. 合批片共享同一预检；片失败跳过后续臂并汇总，避免串行白付。
4. 日志一行：`PREFLIGHT_OK` + git_commit 启动快照（与 manifest 一致）。

**收益**：避免整段 Loading 墙钟作废（一次事故 = ~17min+）；合批验证从「耗死」变为「快失败可重试」。

**成本与风险**：预检过严误杀（环境变量已人工设置）；锁文件残留挡后续跑；预检不能替代缓存正确性。

**冻结检查**：故意 unset 逃生口 → 立即失败且无长 Loading；正常路径 PREFLIGHT_OK 后出现 handler_init 节点；双开第二进程快失败。

**对抗预填**：
- 「mlflow 关了更快」→ 否决改产品默认；只保留 setdefault 逃生口。
- 「预检也 import qlib」→ 禁止；预检须在 qlib import 之前。

**建议裁决**：采纳（低成本纪律；与卡 2 计时节点互补）。

**重提条件**：若 mlflow 后端迁离 file-store——可收缩预检项，但 host_env 单一来源纪律保留。

---

## R1 小结（Codex）

| # | 标题 | 建议裁决 |
|---|------|----------|
| 1 | 统一一次 init 多臂消费契约 | 采纳 |
| 2 | Manifest 强制相位计时节点 | 采纳 |
| 3 | Pred 落盘交接禁二次 Loading | 裁剪后采纳 |
| 4 | Init 前预检闸（mlflow/段/锁） | 采纳 |
