# 参考数据采集入口：MyQuant-infra

ST、SW-L1 与聚源原始响应加工均归 infra，本仓通过公共 API 消费成品，保留研究快照。
原 `qlib_scripts/list_st.py`、`checkcsv.py` 和 `exports/m3d_industry/_merge*.py` 已删除。
安装见[本仓 README](../README.md#环境搭建)。

```text
python -m myquant_infra.reference_data.st --help
python -m myquant_infra.reference_data.industry --help
python -m myquant_infra.data_validation.csv_float --csv-dir <本批CSV目录>
```

QMT 当日名称快照由 infra 接收调用方查询端口或当天导出的 JSON：

```text
python -m myquant_infra.reference_data.st snapshot-vendor-qmt-st-names --out-root <湖容器> --codes-file <代码文件> --names-json <当天名称JSON> --dry-run
```

需采集时由对应数据运行端配置查询端口，或传入真实的当天 JSON，并按 CLI 说明执行。
当日快照与历史 ST PIT 分开，不将当天名称填入历史。MyQuant 不保留券商 SDK 采集实现。

聚源 `table_markdown` 原始响应的离线加工：

```text
python -m myquant_infra.reference_data.industry --merge-gildata smart --raw-dir <原始响应目录> --output-dir <产物目录> --universe-file <all.txt> --metadata-json <本批证据JSON>
python -m myquant_infra.reference_data.industry --merge-gildata fin --raw-dir <fin响应目录> --output-dir <产物目录> --universe-file <all.txt> --metadata-json <fin批次证据JSON> --old-map <smart表> --base-report <原报告JSON>
```

所有路径与采集事实显式提供；批次日期和调用数取本批实际证据，不复制历史脚本的固定值。
MyQuant 的行业中性化仍只消费显式选定的单张表，缺映射时保持原分数并计数。
