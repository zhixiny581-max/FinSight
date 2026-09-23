# FinSight 沪深 A 股行情后端

范围：沪深 A 股。只在 `modules/market/`、`eval/` 下新增文件，不修改 `frontend/index.html`。

## 当前状态

- 已实现：沪深开市日历、上一/下一交易日、最近已收盘交易日、交易日序列、复盘时间窗口、标准 `.ics` 导出。
- 已实现：沪深 A 股代码格式校验；港股、北交所、指数和基金代码拒绝处理。
- 已实现：iFinD MCP 鉴权、前复权日 K、最新行情、分批取数与内存缓存，已用沪深各一只股票完成真实接口联调。
- 前端仍是原型，未自动连接后端；由 A 在最终集成时接入。仅新增后端不会改变原 HTML 的展示数据。

## 1. 安装与启动

在 FinSight 仓库根目录打开 PowerShell，使用 Python 3.10 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r modules/market/requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn modules.market.app:app --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000/docs`，点击任意接口的 Try it out → Execute 即可测试。
服务默认仅在本机运行，没有认证、公共部署或跨域集成配置。
仅测试日历无需授权。查询行情前，先在启动服务的 PowerShell 中设置本机配置路径：

```powershell
$env:IFIND_MCP_CONFIG = 'C:\你自己的目录\ifind-mcp.json'
```

文件内容就是包含 `hexin-ifind-ds-stock-mcp` 的完整 MCP 配置。实际配置文件保存在仓库外，不能上传。
设置后再启动服务；配置与工具详情见 [IFIND_MCP.md](IFIND_MCP.md)。

## 2. 调用接口

所有接口为 GET；`market` 可选 `SSE` 或 `SZSE`，默认 `SSE`。日期使用 `YYYY-MM-DD`。

| 路径 | 参数 | 用途 |
| --- | --- | --- |
| `/api/market/health` | 无 | 服务状态、支持年份、行情接入状态 |
| `/api/market/calendar` | `year=2026&month=9` | 月度日历、交易/休市日数、假期表 |
| `/api/market/calendar/day` | `date=2026-09-20` | `open/kind/label`；省略日期使用上海当天 |
| `/api/market/calendar/next` | `date=2026-09-20` | 严格晚于指定日期的下一交易日 |
| `/api/market/calendar/previous` | `date=2026-09-21` | 严格早于指定日期的上一交易日 |
| `/api/market/calendar/last-closed` | 无 | 按上海时间与 15:00 收盘边界计算 `LAST_TD` |
| `/api/market/calendar/trading-dates` | `end=2026-09-20&n=60` | 截至指定日期的升序交易日序列 `DATES` |
| `/api/market/calendar.ics` | `start=2026-09-01&end=2026-09-30` | 下载包含每日开/休市状态的日历 |
| `/api/market/review/window` | `date=2026-09-21` | 上一交易日 15:00 到当日 15:00，左开右闭 |
| `/api/market/stocks/{code}/quote` | 路径中 `code=300750` | 单只股票最新价、涨跌幅、供应商时间 |
| `/api/market/quotes` | `codes=300750,600519` | 1–10 只沪深 A 股快照，返回 `items` |
| `/api/market/stocks/{code}/kline` | `n=60&end=2026-09-22` | 最多 n 根前复权日 K，默认同时返回最新行情 |

日 K 的 `end` 可省略，使用最近已收盘交易日；`include_quote=false` 可仅取历史数据。
`n` 支持 1–120，默认 60；不会用未来日期或尚未收盘的当天数据作为完整日 K。

示例：`GET /api/market/calendar/day?date=2026-09-20`

```json
{"date":"2026-09-20","open":false,"kind":"makeup","label":"调休上班 · 仍休市"}
```

示例：`GET /api/market/review/window?date=2026-09-21`

```json
{
  "winFrom": "2026-09-18 15:00",
  "winTo": "2026-09-21 15:00",
  "start": "2026-09-18T15:00:00+08:00",
  "end": "2026-09-21T15:00:00+08:00",
  "startInclusive": false,
  "endInclusive": true,
  "timezone": "Asia/Shanghai"
}
```

业务错误返回 `{"error":{"code":"...","message":"..."}}`。输入错误为 HTTP 422，
无数据为 404，供应商/格式错误为 502，配置/权限/限流错误为 503，超时为 504。
参数类型、缺失参数或枚举错误使用 FastAPI 的 HTTP 422 `detail` 格式。

行情返回 `code/name/px/chg/asOf`。日 K 返回 `code/name/DATES/candles/px/chg/quoteAsOf`；
每根 candle 只有 HTML 已用的 `o/h/l/c/v`，与 `DATES` 严格一一对应，日期升序。
成交量统一为股，涨跌幅为百分数，时间带 `+08:00`。
`shortHistory` 标识根数不足；`missingTradingDates` 标识存在交易日缺数据，不能自动解释为停牌。
`historyBehindEnd` 标识最新有效 K 线早于请求截止日。
若日 K 成功但最新行情失败，保留日 K，`px/chg/quoteAsOf` 返回 null，并附 `quoteError`；前端应显示暂无行情。
`fetchedAt` 是取数时间，不能替代来自供应商的 `asOf` 或 `quoteAsOf`。

## 3. 日历口径与维护

`data/calendar.json` 包含 2025、2026 年交易所公布的休市安排及来源。2025 年用于跨年查询。
维护下一年时，核对交易所公告，新增该年的 `HOLIDAY_TABLE` 和 `source`，再重启服务。
不能只根据工作日推测尚未配置年份的交易日；查询超出覆盖年份会报错。
例如 2026-12-31 的下一交易日目前报 `CALENDAR_NOT_CONFIGURED`，不会猜测 2027 年安排。

`open` 表示当天是否为交易日，不表示当前时刻是否正在交易。午休、盘前、盘后不会改变当天 `open`。
`last-closed` 仅代表日历上已收盘，不能用来保证 iFinD 当天数据已经更新。
月度接口独立于今天，不会因为“下一年日历尚未发布”导致整个月不可读。
`calNextD` 中的“距今”以请求的 `date` 为基准；前端正常调用时省略 `date` 即以今天计算。

复盘窗口包含中间休市日的新闻：`start < published_at <= end`，比较前统一时区。
日历交易日序列不等于个股 K 线日期：停牌、上市时间和缺失数据必须在行情接入阶段单独处理。
`.ics` 事件为全天事件，`DTEND` 为下一日（不含）；UID 稳定，重复订阅可识别同一事件。

官方来源：

- [上交所 2025 年休市安排](https://www.sse.com.cn/disclosure/announcement/general/c/c_20241223_10767108.shtml)
- [上交所 2026 年休市安排](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)

## 4. iFinD 配置与权限

已使用用户提供的 MCP 配置完成接入，不需要另外提供传统 HTTP API Key 或 Python SDK。
服务读取 `IFIND_MCP_CONFIG` 指定的外部配置文件，或环境变量 `IFIND_MCP_AUTHORIZATION`。
完整说明见 [IFIND_MCP.md](IFIND_MCP.md)，无密钥模板见本目录 `.env.example`。
日历功能不需要 API Key；本模块不读取仓库根目录的 `MARKET_API_KEY`。
健康检查的 configured 只表示配置可读，授权有效性以在线行情请求结果为准。

## 5. 测试

```powershell
.\.venv\Scripts\python.exe -m pytest eval -q
```

101 项测试覆盖日历边界、ICS、沪深代码校验、MCP 协议、单位换算、复权校验、缺失行、分批取数与缓存。
默认测试使用合成数据，不触发付费/限额行情请求。真实接口联调记录见 IFIND_MCP.md。

## 6. GitHub 上传顺序

上传时保留 `modules/market/` 与 `eval/` 目录层级；不要上传 `.venv/`、`.env` 或 Token。
使用 Git 时只暂存负责目录，先检查差异，再提交到功能分支；不要覆盖前端。
交付包不含前端文件，需合并到现有 FinSight 仓库运行。详细步骤见交付文件《后端运行与上传说明.md》。
