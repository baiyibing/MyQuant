<!-- seat=kimi via=cursor-agent model=kimi-k2.7-code -->

以下按 Ask 模式仅出想法卡，**不写盘、不改代码、不跑实验**；你可将全文落盘到 `r2-live/kimi.md`。

---

# kimi R2-live · 缓存层（b）+ 内存/OOM（e）

> 锚定 HOST §2（#43 handler-cache / expr·dataset-cache / 禁 fetch→parquet）与仓内 `qlib_scripts/task_utils.py::replace_task_handler_with_cache`、`my_scripts/custom_train_backtest.py` handler_init/fetch 热点、`qlib_scripts/custom_handler.py::Alpha158CostKDJ` 自定义表达式。

---

## 卡 1 · handler-cache HIT/MISS 审计进 run-manifest，并加磁盘 TTL/配额

**本仓锚点**

```295:310:qlib_scripts/task_utils.py
def replace_task_handler_with_cache(task: dict, cache_dir: Union[str, Path] = ".") -> dict:
    ...
    hash = hash_args(handler)
    h_path = cache_dir / f"{handler['class']}.{hash[:10]}.pkl"
    if not h_path.exists():
        h = init_instance_by_config(handler)
        h.to_pickle(h_path, dump_all=True)
    task["dataset"]["kwargs"]["handler"] = f"file://{h_path}"
    return task
```

```310:330:my_scripts/run_manifest.py
def write_train_manifest(
    *,
    manifests_dir: Path | str,
    config: Mapping[str, Any],
    pred_path: Path | str | None = None,
    timer_recorder: Any = None,
    ...
):
```

```220:230:my_scripts/custom_train_backtest.py
print("[debug] before handler_init(filtered)", flush=True)
with t_rec.timer("handler_init"):
    handler = Alpha158CostKDJ(**data_handler_config)
print("[debug] after handler_init(filtered)", flush=True)
```

现状一句：`task_utils` 已能生成/复用 handler pickle，但没有一行可机读的 HIT/MISS 日志，也没有把命中情况写进 run-manifest，导致“同配置是否真命中”需要人工对时间。

**提案（缓存级 + 纪律级）**

1. `replace_task_handler_with_cache` 在命中/未命中时各打印一行结构化日志：
   `HANDLER_CACHE HIT key=<full_hash> path=... size_mb=...`
   `HANDLER_CACHE MISS reason=no_file|key_changed|corrupt size_mb=...`
2. `write_train_manifest` 扩展 `data` 或 `config` 字段：`handler_cache_hit`（bool）、`handler_cache_key`、`handler_cache_size_mb`、`handler_cache_miss_reason`。
3. 给缓存目录加 TTL/大小配额策略：超过 N GB 或 M 天未访问的 `.pkl` 自动归档或删除；Win 宿主文件枚举拖慢时尤其有用。

**收益**

- 把“同配置二次跑是否真省 15–18 min”变成 manifest 可审计的事实，排查 miss 不再靠猜。
- 避免缓存无限膨胀导致 Win 文件系统变慢/盘满。

**成本与风险**

- manifest schema 加字段是向后兼容的，但旧 manifest 解析器需忽略未知字段。
- TTL 可能误删近期实验仍需要的缓存；配额阈值拍脑袋会误杀大窗合法缓存。
- `hash[:10]` 文件名冲突风险仍在，建议日志/ manifest 用全长 hex。

**冻结检查**

- 同 `argv` 二次跑：manifest 中 `handler_cache_hit=true`，且 `handler_init` 墙钟秒级。
- 仅改 `--float-cap` / 回测窗 / gate：必须 `handler_cache_hit=false`。
- 磁盘配额触发前，小窗回归的缓存不得被清理。

**对抗预填**

- “HIT 日志可以伪造”→ 同时记录 `size_mb` 与 pickle 文件 md5，和 manifest artifact 指纹对得上才算真命中。
- “直接取消 handler-cache 靠 expr-cache 更快”→ 否决；HOST 已锁定 gate/窗 变优先 handler-cache。

**建议裁决**：裁剪后采纳（先落地 HIT/MISS 日志 + manifest 字段；TTL/配额作为可配置警告，暂不强制删除）。

**重提条件**：连续两次同配置 miss 或缓存目录 >宿主剩余磁盘 30% 时，把配额策略升级为强制。

---

## 卡 2 · 缓存 digest 键纳入自定义算子/数据 schema 指纹

**本仓锚点**

```299:302:qlib_scripts/task_utils.py
hash = hash_args(handler)
h_path = cache_dir / f"{handler['class']}.{hash[:10]}.pkl"
```

```14:34:qlib_scripts/custom_ops.py
class SMA(Rolling):
    ...
    def __init__(self, feature, N, M=1):
        ...
        super(SMA, self).__init__(feature, N, "sma")
```

```118:135:qlib_scripts/custom_handler.py
L1_expr = f"Quantile($low, {N}, 0.0001)"
L2_expr = f"Quantile($high, {N}, 0.9999)"
L3_expr = f"($close - {L1_expr}) / ({L2_expr} - {L1_expr} + 1e-6) * 100"
K_expr = f"SMA({L3_expr}, 3, 1)"
D_expr = f"SMA({K_expr}, 3, 1)"
J_expr = f"3*({K_expr}) - 2*({D_expr})"
```

现状一句：`hash_args(handler)` 主要基于 handler 配置字典，未必能感知 `custom_ops.py` 源码修改或数据 bin 里新增字段（如 `$volddx`、`$zhangting`、`$adfadfbasiccurhold`），存在“改了算子却仍 HIT”的脏读隐患。

**提案（缓存级 + 正确性级）**

1. 缓存键除 handler 配置外，追加：
   - 自定义算子模块源码 hash（如 `qlib_scripts/custom_ops.py`、`custom_handler.py` 中表达式生成逻辑）。
   - 数据 schema 版本：从 provider_uri 读取实际字段集合的 hash（或 bin 元数据 mtime/inode）。
   - `include_alpha158`、`include_cost_kdj`、`include_signal`、`include_lz`、`cost_window` 等显式开关（即使已落在 kwargs 内，也单独列进 digest 清单）。
2. 实现一个稳定的 `_handler_cache_key(handler, data_schema_hash, code_hashes)`，输出全长 sha256，截断仅用于文件名展示。
3. 将 digest 分量清单文档化，方便 frozen check。

**收益**

- 消除“改完 `SMA` 实现或加了一个新字段后，缓存仍命中”的正确性事故。
- 让 `handler-cache` 从“配置键”升级为“配置+代码+数据模式”键，敢在 sweep 里大规模依赖。

**成本与风险**

- 源码 hash 可能因注释/空白变化导致假 MISS；需做规范化（去注释、统一换行）后再 hash，或改用 AST 摘要。
- 数据 schema hash 若只看 mtime 会在 bin 刷新但字段未变时假 MISS；建议读取 qlib 字段元数据做内容 hash。
- Win/Linux 路径差异不影响源码 hash，但数据 schema hash 需用相对/规范路径。

**冻结检查**

- 修改 `custom_ops.py:SMA._load_internal` 任意一行 → 同配置必须 MISS。
- 还原修改 → 必须 HIT（若用源码 hash 则要求无脏文件）。
- 数据 bin 字段增删 → MISS；仅 bin 内部数据刷新但字段不变 → 可 HIT（按内容 hash 决定）。

**对抗预填**

- “直接以 git commit 做键就够了”→ 否决；dirty working tree 未提交也会改算子，而生产实验常在 dirty 状态跑。
- “hash 源码太贵”→ 只 hash 自定义模块（少量文件），并缓存源码 hash 到 `.cache_meta.json`，不必每次读盘重算。

**建议裁决**：采纳（裁剪：先落地自定义模块 + 数据字段 hash；AST 规范化登记远期）。

**重提条件**：若出现一次“改了表达式仍 HIT”或“bin 刷新后应 MISS 却 HIT”，立即升级为强制 digest 分量。

---

## 卡 3 · 峰值 RSS 与 handler pickle 体积护栏写入 manifest

**本仓锚点**

```17:50:my_scripts/custom_utils.py
class TimerRecorder:
    def __init__(self):
        self._t0 = timer()
        self.nodes = []
    ...
    def dump_json(self, path: str, extra: Optional[Dict] = None):
```

```290:310:my_scripts/run_manifest.py
def timings_from_recorder(timer_recorder: Any) -> dict[str, Any]:
    ...
    return {"total_seconds": total, "nodes": nodes}
```

```277:280:my_scripts/custom_train_backtest.py
with t_rec.timer("handler_fetch_feature"):
    data = handler.fetch(col_set="feature")
```

```700:710:my_scripts/custom_train_backtest.py
with t_rec.timer("dataset_prepare_test_feature_label"):
    data_df = dataset.prepare(segments='test', col_set=['feature', 'label'])
```

现状一句：`TimerRecorder` 只记墙钟节点，不记峰值内存；OOM 复盘时只能猜是哪一步撑爆 RAM。`handler.fetch(col_set="feature")` 与 `dataset.prepare` 会分别产生全量矩阵拷贝。

**提案（内存级 + 纪律级）**

1. 在 `TimerRecorder` 节点中追加可选 `peak_rss_mb`：使用 `psutil.Process().memory_info().peak_wset`（Win）/ `resource.getrusage(RUSAGE_SELF).ru_maxrss`（Linux），在每个 `timer_context` 退出时采样。
2. `write_train_manifest` 把 `peak_rss_mb` 写进 `timings.nodes`，长期积累 OOM 前的 RSS 曲线。
3. `replace_task_handler_with_cache` 写 pickle 前检查估算大小：`handler` 对象序列化前若 >阈值（建议 4/8/16 GB 分档，默认警告），先提示缩窗/缩宇宙；写完后记录 `handler_cache_size_mb`。

**收益**

- OOM 从“跑到 40 min 炸”前移到“handler-cache 写入时 warned/rejected”。
- manifest 积累真实峰值数据，为卡 4/卡 5 的并行度预算提供输入。

**成本与风险**

- 新增 `psutil` 依赖；跨平台峰值语义不同（Win 是 peak working set，Linux 是 max RSS）。
- 阈值拍脑袋可能误杀长窗合法实验；建议默认仅 warn，可配置为 fatal。
- 采样时机若不放在 GC 后会有噪声，但用于趋势分析足够。

**冻结检查**

- 小窗跑完 manifest 中 `handler_init` 与 `handler_fetch_feature` 节点带 `peak_rss_mb>0`。
- 构造一个故意超大的 handler（如超长窗+全市场），写 cache 时阈值警告生效且不写坏半文件。
- 不改变 topk/过滤默认。

**对抗预填**

- “靠 `mem_cache_size=10` 就能解决”→ 否决盲开；`qlib_14.py` 中 `mem_cache_size` 已被注释且未验证，且与 OOM 无直接因果关系。
- “pickle 体积不重要，看 RSS 就行”→ 两者都要；pickle 体积是反序列化峰值的下界之一。

**建议裁决**：裁剪后采纳（先记 peak_rss_mb 与 size_mb，阈值默认 warn；fatal 模式待 Win 实测一档后再开）。

**重提条件**：记录满 1 周或再出现一次 OOM，根据峰值曲线把阈值改 fatal。

---

## 卡 4 · 训练入口禁用全量 `handler.fetch("feature")` 预览，防内存双峰

**本仓锚点**

```277:300:my_scripts/custom_train_backtest.py
with t_rec.timer("handler_fetch_feature"):
    data = handler.fetch(col_set="feature")
print(data.head(10))
print(f"所有feature列: {data.columns}")
...
print(data[available_cols].head(10))
```

```700:720:my_scripts/custom_train_backtest.py
with t_rec.timer("dataset_prepare_test_feature_label"):
    data_df = dataset.prepare(segments='test', col_set=['feature', 'label'])
print(data_df.head(10))
```

现状一句：`custom_train_backtest.py` 在 `handler_init` 之后立即做一次完整的 `handler.fetch(col_set="feature")` 打印头/列名，后续 `dataset.prepare` 还会再生成一份全量矩阵；大宇宙长窗时造成双峰内存。

**提案（IO级 + 内存级）**

1. 把 `handler.fetch(col_set="feature")` 全量预览改为默认关闭，新增 `--preview-rows N` 参数，默认 `0`。
2. 当 `N=0` 时，只通过 `handler.get_cols("feature")` 或读取 pickle 元数据打印列名，不物化 DataFrame。
3. 需要预览时限制 `N`（如最多 1000 行），用 `iloc[:N]` 或切片读，禁止把全市场×全窗矩阵拉进内存。
4. 生产/CI 跑法显式传 `--preview-rows=0`。

**收益**

- 消除一次与 handler 数据等大的内存峰值；对长窗大宇宙可让峰值 RSS 下降接近一半（视具体矩阵大小）。
- 同时减少一次不必要的全量 IO。

**成本与风险**

- 调试时列名预览信息减少；需要确认 `handler.get_cols("feature")` 在当前 handler 子类上可靠。
- 切片预览在大矩阵上可能仍慢，但受 `N` 上限约束。

**冻结检查**

- `--preview-rows=10` 输出头 10 行，与旧行为一致。
- `--preview-rows=0` 不触发 `handler_fetch_feature` 节点，或该节点 RSS 接近 0。
- 不改变训练产出（pred 字节一致）。

**对抗预填**

- “没有全量 fetch 就无法验证特征”→ 验证应走小样本 smoke 或切片，不应在生产入口全量复制。
- “dataset.prepare 反正也会拉全量，所以 fetch Preview 无所谓”→ 预览在 prepare 之前，形成双峰；减少一峰就是一峰。

**建议裁决**：采纳（默认关闭全量预览，加 `--preview-rows`；保留列名输出）。

**重提条件**：若 `handler.get_cols` 在某些自定义 handler 上信息不足，则改为仅预览“第一个交易日”的截面数据。

---

## 卡 5 · ranking sweep 一次 init 多臂：handler-cache 在 grid 间显式共享

**本仓锚点**

```150:210:my_scripts/sweep_ranking.py
def run_one(
    config: SweepConfig,
    *,
    train_predict_fn: TrainPredictFn,
    manifests_dir: Path | str | None = None,
    ...
) -> SweepResult:
    ...
    payload = dict(train_predict_fn(cfg))
```

```295:310:qlib_scripts/task_utils.py
def replace_task_handler_with_cache(task: dict, cache_dir: Union[str, Path] = ".") -> dict:
    ...
    task["dataset"]["kwargs"]["handler"] = f"file://{h_path}"
    return task
```

```220:230:my_scripts/custom_train_backtest.py
with t_rec.timer("handler_init"):
    handler = Alpha158CostKDJ(**data_handler_config)
```

现状一句：`sweep_ranking.py` 的 grid（topk / n_drop / hold_thresh）不改变 handler/特征/标签，但默认适配器可能让每臂都重新 init；结合 handler_init ~18 min，M 臂 sweep 会付 M×18 min。

**提案（缓存级 + 调度级）**

1. sweep 适配器在 grid 循环前调用 `replace_task_handler_with_cache` 一次，把 handler 固定为 `file://...pkl`。
2. 所有 `SweepConfig` 共享同一个 handler digest；grid 只修改 `port_analysis_config["strategy"]["kwargs"]` 中的 topk/n_drop/hold_thresh。
3. 在 `run_manifest` 中标注 `shared_handler_cache_key`，使事后能证明多臂只 init 一次。
4. 若某臂想改特征/窗/ gate，必须提升为新的 handler digest，不允许“为快而共享错误缓存”。

**收益**

- M 臂 ranking sweep 从 `M × ~18 min` 降到 `~18 min + M × ~5 s`（model_fit/回测）。这是 HOST 反复提到的“一次 init 多配置”最直接的落地。
- 与卡 1 的 HIT/MISS 审计配合，可量化节省。

**成本与风险**

- 适配器必须保证 grid 字段不触碰 handler；一旦某臂改了 handler 配置而仍用同一 file，会脏读。
- 多进程 sweep 时同时读同一个 pickle 是安全的，但同时写会冲突；需保证只写一次。
- Win 上多臂如果各自 spawn，传 `file://` 路径和 Linux 一致，但需避免绝对路径含空格/中文导致解析差异。

**冻结检查**

- 3 臂 sweep 的 manifest 中 `handler_init` 只出现一次且有 `shared_handler_cache_key`；其余臂的 `handler_init` 节点墙钟 <1 s 或被标记为 `cache_load`。
- 单独改某臂的 `fit_end_time` → 该臂必须 MISS 并重新 init。
- 各臂 `pred.pkl` 字节不同，证明策略参数确实生效。

**对抗预填**

- “不同 topk 需要不同特征”→ 否决；ranking 阶段的特征是同一套，topk 只在策略选择阶段截断。
- “共享 handler 会导致标签泄露”→ 否决；handler/segments/gates 不变就不存在额外泄露。

**建议裁决**：采纳（让 sweep 适配器优先使用 `replace_task_handler_with_cache`；多臂共享显式写进 manifest）。

**重提条件**：当 sweep  harness 正式跑真实 train/backtest 时，先验证此模式在三臂 grid 下只产生一次 handler_init。

---

## R2-live 小结（kimi）

| # | 标题 | 方向 | 建议裁决 |
|---|------|------|----------|
| 1 | handler-cache HIT/MISS 审计进 manifest + 磁盘 TTL/配额 | b | 裁剪后采纳 |
| 2 | 缓存 digest 键纳入自定义算子/数据 schema 指纹 | b | 采纳（裁剪版） |
| 3 | 峰值 RSS / handler pickle 体积护栏进 manifest | e | 裁剪后采纳 |
| 4 | 训练入口禁用全量 `handler.fetch("feature")` 预览 | e | 采纳 |
| 5 | ranking sweep 一次 init 多臂共享 handler-cache | b（兼 d） | 采纳 |
