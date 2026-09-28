# 股票详情与K线数据要求

股票详情打开时，使用 iFinD 股票服务 `get_stock_performance` 按需查询最近5个交易日的日频数据，不在整条新闻分析时批量预取。

每根K线至少包含 `date`、`open`、`high`、`low`、`close`、`volume`。数据不足、权限不足或解析失败时返回 `unavailable`，前端不得补造行情。

每次返回需记录 `source`、`fetched_at` 和 `as_of`。K线仅展示历史数据，不据此自动生成方向、买卖信号或收益判断。

