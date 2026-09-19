# Prompt 已迁到 OSkhQuant1.3

申万一级 / ST 的 Kimi Wind 采集只住 1.3。本仓只消费湖，不猜 E:/F:。

- 行业：`OSkhQuant1.3/docs/prompts/prompt-kimi-datasource-industry-harvest.md`
- ST：`OSkhQuant1.3/docs/prompts/prompt-kimi-datasource-st-harvest.md`
- 本仓读：`{OSKH_SOURCE_PARQUET_ROOT}/vendor_wind_sw_l1/sw_l1_map.csv`（没有则报错，不改读 `wind_l1_map.csv`）

```text
D:\anaconda3\envs\vanna312\python.exe -m oskh_data.vendor_wind_sw_l1 --generate-questions
D:\anaconda3\envs\vanna312\python.exe -m oskh_data.vendor_wind_st pull-szse-namechange
```
