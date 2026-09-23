# 从现有 HTML 提取的字段与协作边界

读取基准：`frontend/index.html`，仓库提交 `7b447547affafa1b1983705e0f2c9dea3b3aa39a`。
这些名称来自实际 JavaScript 对象、变量或元素 ID；未凭空把字段改成 `openPrice`、`closePrice` 等名称。
HTTP 路径、响应外壳和元数据属于后端新增约定，不是已有前端接口。

## 已逐项阅读

| 文件/区域 | 结论 |
| --- | --- |
| 根 `README.md` | A 维护主前端；D 负责 `modules/market/` 及 `eval/`，各模块提供调用、输入输出和环境说明 |
| 根 `.env.example` | 只有三个空白 Key 占位，未指定行情供应商；本次用户指定 iFinD |
| 根 `.gitignore` | 已排除 `.env`、虚拟环境、Python 缓存和评测结果 |
| `frontend/index.html` | 当前完整 UI 原型；交接要求在文件内 `NOTES` 数组；尚无 fetch 行情请求 |
| 各模块与 `eval/` 中 `.gitkeep` | 空目录占位，没有既有后端逻辑或其他说明文档 |

## 开市日历（已实现）

| HTML 名称 | 含义 | 位置 |
| --- | --- | --- |
| `open` | 当天是否交易日，布尔值 | `mkt(ds)`，约 1019 行 |
| `kind` | `open/holiday/weekend/makeup` | `mkt(ds)` |
| `label` | 开市/休市的中文说明 | `mkt(ds)` |
| `calOpenN`、`calClosedN` | 当月交易日数、休市日数 | `renderMarketCal()`，约 1424 行 |
| `calTitle`、`calMonthLabel` | 月份标题和天数文案 | `renderMarketCal()` |
| `calNext`、`calNextD` | 下一交易日显示值、星期/距离说明 | `renderMarketCal()` |
| `HOLIDAY_TABLE` | `[名称,开始日,结束日,调休日期数组]` | 约 1000 行 |
| `DATES` | 日期字符串数组 | 约 1044 行及 K 线图 |
| `LAST_TD` | 最新已收盘交易日 | 约 1043 行 |
| `winFrom`、`winTo` | 复盘窗口显示文案 | `renderReview()`，约 1880 行 |

原 HTML 的 `state.cal.m` 是 JavaScript 的零基月份，HTTP 参数 `month` 为 1–12；最终集成时 A 需传 `m + 1`。
“有快讯”圆点来自 `NEWS`，属于新闻模块；休市状态不能代替是否有快讯。

## 日 K 与行情（已通过 iFinD MCP 实现）

| HTML 字段 | 含义 | 后端口径 |
| --- | --- | --- |
| `code` | 六位沪深股票代码，字符串 | 保留前导零；内部调用 iFinD 使用 `thscode`，如 `300750.SZ` |
| `name` | 股票名称 | 使用 iFinD 返回的证券简称 |
| `px` | 最新价 | 真实行情数值；标明供应商数据时间 |
| `chg` | 最新涨跌幅 | 百分数数值，如 `1.85` 表示 `1.85%`，不是预测值 |
| `candles` | 日 K 数组 | 默认最多 60 根有效日 K，按日期升序 |
| `o`、`h`、`l`、`c` | 开盘、最高、最低、收盘 | 前复权，所有价格使用同一复权基准 |
| `v` | 成交量 | 已核验 iFinD 元数据；统一换算为股，不沿用前端随机归一化数值 |
| `DATES` | 日 K 日期数组 | 与实际 `candles` 一一对应，不能将停牌日强行补成 K 线 |

证据：`openDrawer()` 约 1692 行；`genCandles()` 约 1725 行；`renderKline()` 约 1742 行；`NOTES` 的 `kline-drawer` 约 1995 行。
均线可继续由前端现有 `maLine(candles, n)` 计算。前端第一根 K 线以开盘计算涨跌幅是原型逻辑，正式接入应使用供应商上一收盘/涨跌幅口径；本次不修改 HTML。

`stage/note/role/dir/stars/conf` 来自分析模块，不应由行情模块伪造。
`seed` 只是前端随机行情生成种子，不是行情接口字段。
原型中的 `HK1177` 和 `HK3690` 按用户要求排除；保留 HTML 原文，后端拒绝港股请求。
后端代码格式校验不等于股票确实存在或仍上市；iFinD 空数据明确返回错误，缺失交易日和不足根数附带标识。

## 最终集成须知

当前 HTML 用固定的 `TODAY`、`LAST_TD`、同步日历函数与随机 K 线，没有网络调用。
在用户要求不修改 HTML 的阶段，后端可以单独运行和验证；不会自动让原网页显示真实行情。
A 最终需要把数据来源替换成 API，并处理加载、错误、无数据和港股不支持状态。
本次交付不负责新闻采集、模型推演或完整复盘评测；只为相关模块提供日历及后续行情事实。
