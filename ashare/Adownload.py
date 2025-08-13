from xtquant import xtdata
# 指定股票代码及时间范围（从上市日期至今）
xtdata.download_history_data("001872.SZ", period="1d", start_time="20170101")