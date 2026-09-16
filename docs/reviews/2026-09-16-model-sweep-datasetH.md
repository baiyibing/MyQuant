# 2026 窗 · DatasetH 多模型对照（50/5）

**日期**：2026-09-15 夜 → 2026-09-16 午前  
**窗**：train 2020-01-01:2024-12-31 / valid 2025 / test 2026-01-01:2026-09-14  
**策略**：TopkDropout 50/5，基准 SH000300，qlib 默认成本  
**特征**：`Alpha158CostKDJ` + DatasetH；handler-cache 钥匙 `9db25097…`（约 10.8 GB）  
**50/5 LGB 锚**：`8a061ea4`（handler 冷启动那趟，**pred.pkl 未覆盖**）  
**线上默认**：仍是 **10/3 LGB**（如 `907edbfb`）。本扫参是研究对照，**不改上线学习器、不改宽度**。  
**判优尺子**：线上仍只看 IC / Rank IC / 名单命中率。下表 PortAna 扣费超额只作学习器筛选，不上线。

扫参摘要：`manifests/model_sweep_20260915.txt`。YAML：`configs/models/*.yaml`（PR #69）。

---

## 1. 结论（先看这张）

同一套窗、同一套宇宙、同一把 handler 钥匙。树最好；线性与多数序列模型在本窗输掉基准。

| 模型 | 扣费超额 vs 300 | 拟合 | PortAna | 全程墙钟 | recorder |
|---|---:|---:|---:|---:|---|
| LGB | **+11.8%** | 117s | ~75s | ~4 min（HIT 后） | 既有 50/5 对照 |
| XGB CPU | **+11.8%** | 253s | 50s | 5.5 min | 既有 |
| CatBoost GPU | +11.2% | **26s** | ~50s | **1.6 min** | 既有 |
| DNN | +4.8% | 35s | 25s | 1.4 min | 既有 |
| LSTM | −1.3% | ~331s | ~47s | 6.7 min | `9de8e927` |
| TCN | −3.6% | 452s | 30s | 8.4 min | `00c103f9` |
| GRU | −4.1% | 364s | 47s | 7.3 min | `79265f85` |
| DoubleEnsemble | −13.3% | 1373s | 37s | 24 min | `61344198` |
| ALSTM | −15.7% | ~331s | ~47s | 6.7 min | `88dd0e6c` |
| TabNet | −18.9% | 1496s | 48s | 26 min | `970fdab6` |
| Lasso | −19.5% | 278s | 47s | 5.8 min | `d8770029` |
| Ridge | −24.3% | 83s | 25s | 2.1 min | `1e82e904` |

LGB 首跑填缓存：handler **866s**，全程 **18.6 min**。之后同一钥匙 HIT ≈ **5s**。

**读表**

1. 换学习器没有超过 LGB/XGB。Cat 几乎打平且最快；DNN 正但矮一截。  
2. 序列模型（LSTM/GRU/ALSTM/TCN）全部为负。**TCN 是 3×61 假序列**（`d_feat=3`），不能当成「真时序输给卷积」的结论。  
3. 线性（Ridge/Lasso）和 TabNet 更差，不是「再训久一点就会翻正」。  
4. 全程墙钟的大头在 **handler 冷启动** 和 **拟合**；PortAna 一律 25–75s，不是瓶颈。

---

## 2. 哪些要重做、哪些能复用

| 步骤 | 跨模型能否复用 | 这次实测 |
|---|---|---|
| `qlib.init` / 日历 / instruments | 是 | 秒级 |
| handler 物化（Alpha158CostKDJ 全窗 frame） | **是**（窗、宇宙、闸门、字段不变） | MISS 866s → HIT ~5s，同一钥匙 `9db25097…` |
| `dataset.prepare`（train/valid 切片） | 否，但很便宜 | 嵌在 `model_fit` 里；新埋点拆开后可见 |
| **拟合** | **否** | 26s（Cat）～ 25 min（TabNet） |
| 出分 `SignalRecord` | 否 | 分钟级 |
| 回测 `PortAna` | 否（分不同）；策略-only 可 replay 同一 `pred.pkl` | 25–75s |
| 分析包 / pred CSV | 否，必须带戳 | 已有 `预测结果_<UTC>_<rid>_50n5.csv` |

一句话：**特征不用每模型重算；权重必须各训一遍；回测也要各走一遍，但很便宜。**  
策略宽度/成本扫参应 replay 既有 pred，不要重训。学习器扫参必须重训。

---

## 3. 过程上踩过的坑

### 3.1 YAML 默认值不能直接搬到本机

| 学习器 | 第一次 | 原因 | 改法 |
|---|---|---|---|
| CatBoost | GPU 起不来 | `rsm` 与 GPU 冲突 | `cat.yaml` 去掉 `rsm` |
| TCN | `padded input size (0), kernel (1)` | 默认 `kernel_size=1` 且特征维对不上 | 重试 `d_feat=3` `kernel_size=5`（假序列，结论打折） |
| DoubleEnsemble | `NoneType ** int` | YAML `decay: null` | `decay: 0.9` |

教训：新 YAML **先短窗 / 少 round 冒烟**，再进过夜长窗。扫参脚本必须 **一个模型失败继续下一个**（见 `sweep_models.py`）。

### 3.2 埋点单次够、跨次不够

当时已经有：`qlib.init`、`handler_init`、`model_fit`、`SignalRecord`、`PortAna`、`export`、`D.features` 探针；manifest 也有 `timings.nodes` 和 `handler_cache_hit`。

缺的是对照层：

1. **文件名写死**。`exp_name` 一律 `alpha158_cost_kdj_lgb`，根目录 `timing_custom_train_backtest_alpha158_cost_kdj_lgb.json` 每跑一个模型就盖掉上一个。磁盘上最后只剩 DoubleEnsemble。  
2. **扫参摘要只 grep `annualized_return`**。PortAna 表里同一字段出现多行（无成本 / 有成本 / 再打印一遍），容易抓错行。  
3. **`model_fit` 是一大块**。里面混着 `dataset.prepare`、真正拟合、valid 早停。看不出「切片 20s、boosting 15s」。

### 3.3 实验名共用的利弊

12 个学习器都进了同一个 MLflow 实验（默认 `alpha158_cost_kdj_lgb`）。好处：现役导出 / replay 脚本不用改 `--exp-name`。坏处：UI 里一堆 recorder 挤在一起。  
**保持默认实验名**，靠 `recorder_id` + 带戳 timing / pred 区分。只有在明确要隔离研究实验时才传 `--exp-name`。

### 3.4 窗口被关

TCN / DoubleEnsemble 第一次补跑死在 09-15 22:28 关窗。长拟合（TabNet 26 min、Ensemble 24 min）不适合挂在随时会关的会话里；用 `sweep_models.py` 顺序跑、日志落地 `manifests/sweep_<model>.log`。

---

## 4. 程序和埋点改了什么（2026-09-16）

| 点 | 改动 | 文件 |
|---|---|---|
| timing 不互盖 | `timing_<exp>_<model>_<UTC>.json`；分析包旁仍写一份 `timing.json` | `train_wiring.resolve_train_timing_path`、`custom_train_backtest` |
| 一行对照 | 退出时打印 `[timing] model=… handler=HIT/MISS fit=… prepare=… predict=… portana=… total=…` | `TimerRecorder.digest_line` |
| 拆 `model_fit` | `dataset.prepare.{seg}` 嵌套计时（fit 墙钟仍含 prepare） | `wrap_dataset_prepare` |
| PortAna 进 manifest | `data.excess_ann_with_cost` / IR / MDD（及 without-cost） | `extract_portana_metrics` → `_cal_data` |
| 扫参入口 | 一模型一进程，失败继续 | `my_scripts/sweep_models.py` |
| 对照表 | 读 `manifests/train_*.json`，不重训 | `my_scripts/summarize_model_runs.py` |
| 实验名可覆写 | `--exp-name`，默认仍 `alpha158_cost_kdj_lgb` | `parse_train_cli` |

历史 manifest（本扫参当时写下的）**没有** PortAna 单元格；速度表仍可从 `timings.nodes` 滚出来。新跑的才带超额数字。

**不改**：线上 10/3；`8a061ea4` pred.pkl；handler-cache 钥匙算法；run-manifest schema（只加可选 `data` 键）。

---

## 5. 以后怎么跑

同一窗换学习器（handler 已在）：

```text
python my_scripts/sweep_models.py --models ridge,lasso,gru --handler-cache
    --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31
    --test 2026-01-01:2026-09-14 --topk 50 --n-drop 5
```

跑完对照（不重训）：

```text
python my_scripts/summarize_model_runs.py --topk 50
```

单模型：

```text
python my_scripts/custom_train_backtest.py --model cat --handler-cache --topk 50 --n-drop 5
    --train 2020-01-01:2024-12-31 --valid 2025-01-01:2025-12-31 --test 2026-01-01:2026-09-14
```

新学习器：复制 `configs/models/<name>.yaml`，先短窗冒烟，再进 sweep。不要改 `custom_train_backtest.py`。

策略-only（成本 / topk / 闸门）继续用既有 pred replay，例如 `rebacktest_cost_tiers.py --recorder-id …`。

---

## 6. 还没做、建议下次补

1. **IC / Rank IC 进 manifest**。现在对照只落了 PortAna；和线上尺子不一致。`SigAnaRecord` 已经算过，写 `data.ic` / `data.rank_ic` 即可。  
2. **`model_fit` 再拆 boosting vs early-stop**。prepare 已拆；树模型的 `num_boost_round` 墙钟仍糊在 fit 里。  
3. **pred.pkl 级学习器对照**。若只想比策略，应禁止误触发重训；扫参入口可拒绝「无 `--model` 却改窗」的组合。  
4. **TCN / 序列模型的真输入**。要再比一次，先把 DatasetH 改成按票滚动窗，而不是 3×61 reshape。在那之前不要写「卷积不如树」。  
5. **Cat 打平 LGB 的复现窗**。只在 2026 50/5 见过一次；换 2024 窗或 10/3 再跑一趟再谈要不要进研究短名单。仍不进线上。  
6. **MLflow 实验拥挤**。若研究实验变多，用 `--exp-name` 另开，但导出脚本必须显式带同一个名字。

---

## 7. 经验教训（可执行）

1. **先 YAML、再冒烟、再过夜。** 默认超参会炸（rsm / decay / kernel）。  
2. **handler-cache 是扫参的前提。** 没 HIT 就不要开 12 模型。钥匙变了等于从头。  
3. **对照读命名单元格和 digest，不 grep 日志。**  
4. **timing / pred 必须带模型或 recorder 戳。** 共享文件名等于没记。  
5. **换学习器 ≠ 换策略。** 宽度、闸门、成本用 replay；学习器用重训。  
6. **单窗冠军不是上线理由。** 线上仍 10/3 LGB；本表树赢只说明「在这套 DatasetH + 2026 50/5 上不必换学习器」。  
7. **假序列不要写进架构结论。** TCN −3.6% 只能说明「当前 reshape 不行」。
