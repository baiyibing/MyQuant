# Prompt 已迁到 OSkhQuant1.3

申万一级 / ST 的 Kimi Wind 采集只住 1.3。本仓只消费 F 湖。

- 行业：`E:/PycharmProjects/OSkhQuant1.3/docs/prompts/prompt-kimi-datasource-industry-harvest.md`
- ST：`E:/PycharmProjects/OSkhQuant1.3/docs/prompts/prompt-kimi-datasource-st-harvest.md`

```text
D:\anaconda3\envs\vanna312\python.exe -m oskh_data.vendor_wind_sw_l1 --generate-questions --map E:/PycharmProjects/MyQuant/exports/m3d_industry/sw_l1_map.csv
D:\anaconda3\envs\vanna312\python.exe -m oskh_data.vendor_wind_st pull-szse-namechange
```
