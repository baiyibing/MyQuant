# Prompt：用 Kimi datasource 批量复核 A 股申万一级行业

> 适用场景：已有 gildata/聚源/其他来源的行业映射表，需要以万得（Wind）为权威源做全量独立复核；或反过来用 Wind 首次采集申万一级行业。
> 前置依赖：Kimi Code 已安装并启用 `kimi-datasource` 插件（≥3.4.0），且当前会话已 `/login`。
> 配套脚本：`my_scripts/harvest_sw_l1_from_wind.py`（生成问题文件、合并、比对）。

## 目标

以 `wind_get_financial_data` API 批量获取 A 股全市场的「申万一级行业」，与参考表（如 `exports/m3d_industry/sw_l1_map.csv`）按 `code_gildata`（600000.SH 格式）对齐，输出冲突清单和一致性报告。

## 关键坑点（必须先读）

1. **不要调 `get_data_source_desc`**：3.4.0 插件对新增源路由错位（如 gildata 返回 stock_finance_data 的文档、wind 返回 yahoo_finance 的文档）。直接调接口，若 API 名错了报错信息会列出真实可用 API。
2. **Wind 的正确入口是 `wind_get_financial_data`**，参数是 NLU 问题串：`"code1、code2…codeN的申万一级行业"`。
3. **批量大小**：100 个 code/问题最稳；发现某批返回 canned 演示数据/空码/空行业，立即将该文件重命名为 `*.bogus.csv` 隔离，改用 20 或 50 码子块重试。
4. **问题串构造**：代码用 `600000.SH` 格式，用中文顿号 `、` 连接，后缀固定为 `的申万一级行业`。必须用 Python 生成 UTF-8 文件，**禁止**在 Git Bash 里用 `paste -sd "、"`（多字节分隔符会被 locale 破坏）。
5. **每批校验**：以落盘的 CSV 文件为准（markdown 预览会截断）。期望列：`Wind代码,证券简称,申万一级行业,申万一级行业.行业级别`。用 `wc -l` 检查行数是否等于该批代码数+1。
6. **断点续采**：每个 `batch_NNNN.csv` 都是检查点。中断后只补缺失批次，不要重采已存在的有效文件。
7. **额度控制**：每次调用都消耗 Kimi Code 账户额度。若返回 403/额度/auth 错误，立即停止并汇报断点，等待用户通知后再续。
8. **行业名归一化**：比对前去掉空格、全半角统一、去掉 `(申万)`/`（申万）` 等括号后缀。

## 执行步骤

### 阶段一：本机生成问题文件（无额度消耗）

```bash
cd E:\PycharmProjects\MyQuant
D:\anaconda3\envs\vanna312\python.exe my_scripts/harvest_sw_l1_from_wind.py --generate-questions --map exports/m3d_industry/sw_l1_map.csv --wind-dir exports/m3d_industry/wind_raw
```

这会生成 `wind_raw/q0000.txt` 等问题串文件。

### 阶段二：Kimi agent 采集（消耗额度）

把以下指令交给 Kimi agent：

```text
使用 wind 数据源批量复核申万一级行业。

- 问题文件目录：exports/m3d_industry/wind_raw/q*.txt
- 每个 q 文件内容是一个问题串，例如：600000.SH、600004.SH、…的申万一级行业
- 对第 i 个问题文件（q{i:04d}.txt），调用 mcp__plugin-kimi-datasource_data__call_data_source_tool：
  data_source_name="wind"
  api_name="wind_get_financial_data"
  params={"question": "<q 文件完整内容>", "file_path": "E:/PycharmProjects/MyQuant/exports/m3d_industry/wind_raw/batch_{i:04d}.csv"}
- 如果某 batch 文件行数明显少于 q 文件代码数+1，或出现大量空 Wind代码/空申万一级行业，将该文件重命名为 batch_{i:04d}.bogus.csv，并把该 q 文件中的代码拆成 20 个一批，生成 retry_{i:04d}_a.csv .. retry_{i:04d}_e.csv（file_path 形如 wind_raw/retry_0041_a.csv）。
- 每个 retry 子块的问题串同样以「的申万一级行业」结尾，用顿号连接代码。
- 全部 q 文件处理完后，运行 my_scripts/harvest_sw_l1_from_wind.py --all 合并并比对。
- 若遇到 403/额度/auth 错误立即停止并报告断点（已完成到第几批）。
- 不要调用 get_data_source_desc；不要修改仓库其他文件；不要执行 git 操作。
```

### 阶段三：本机合并与比对（无额度消耗）

采集完成后：

```bash
D:\anaconda3\envs\vanna312\python.exe my_scripts/harvest_sw_l1_from_wind.py --all --map exports/m3d_industry/sw_l1_map.csv --wind-dir exports/m3d_industry/wind_raw
```

产物：
- `exports/m3d_industry/wind_l1_map.csv`：Wind 口径全量行业表
- `exports/m3d_industry/wind_conflicts.csv`：冲突清单
- `exports/m3d_industry/wind_crosscheck.json`：覆盖率 / 一致率 / progress_note

## 验收标准

- `wind_missing` 应接近 0（少量退市/风险股可接受）。
- `agreement_rate_normalized` ≥ 0.98；若目标是权威复核，争取 1.0。
- `wind_conflicts.csv` 行数应能被人工快速审完；若大于 50 行，检查是否归一化规则不够或某批 bogus 未重采。

## 历史经验值（本次 M3-D）

- 5210 只 SH/SZ，54 个问题文件（52×100 + 10 + 30）。
- 其中 10 个百码问题串触发了 Wind 后端的 canned 演示数据返回，拆成 20/50 码子块后成功。
- 最终 overlap=5210，wind_missing=0，raw/normalized 冲突均为 0，一致率 1.0。
- 全程约 50+ 次 MCP 调用，建议分批次提交 git，防止额度窗口耗尽丢失进度。
