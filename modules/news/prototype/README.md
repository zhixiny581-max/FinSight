# 财讯智析新闻原型（独立运行）

这是 B 组新闻导入、快讯流的演示版本。支持从 iFinD 刷新新闻、粘贴链接导入、打标入库、保存导入记录；配好 DeepSeek 后可生成摘要并调用 `modules/analysis/` 的结构化推演服务。`index.html` 与 `server.js` 必须放在同一目录。

新闻摘要属于新闻模块，只在载入新新闻时生成或复用缓存；点击“开始 AI 分析”不会改写摘要。有全文时，推演会读取清洗后的全文。推演结论、宏观与市场判断、行业识别、行业传导图、股票关联和结果校验由 `modules/analysis/` 维护。宏观面使用同花顺全A作事前参照；股票详情打开时通过 iFinD `get_stock_performance` 按需获取新闻时点以前最近60个有效交易日日线，并与行业基准和同花顺全A对照。所有行情都以新闻时点为上限，不使用后续数据。

## Windows 双击启动

电脑需要安装 Node.js 18 或更高版本，无需安装额外 npm 依赖。双击 [`启动FinSight.cmd`](启动FinSight.cmd)：

1. 第一次启动会从 `.env.example` 创建本机 `.env` 并用记事本打开。
2. 在 `.env` 中填写自己的 `IFIND_MCP_AUTHORIZATION` 和 `DEEPSEEK_API_KEY`。iFinD 的值保持平台提供的 Authorization 原样，不要自行添加 Bearer 前缀。若已经安装并配置 `ifind-finance-data` Skill，也可以留空 `IFIND_MCP_AUTHORIZATION`；程序会使用该 Skill 的现有配置。
3. 保存 `.env` 后再次双击启动器。它会检查配置，在后台启动本地服务并打开 <http://127.0.0.1:3000>。

启动日志保存在被 Git 忽略的 `data/server.log` 和 `data/server-error.log`。如果服务已在运行，重复双击只会打开页面，不会重复启动。改动 `server.js` 或 `.env` 后，需要先结束旧的 Node 服务，再双击启动器让新配置生效。

不能直接双击 `index.html`。该页面依赖 `/api/news`、`/api/imports` 和 `/api/analyze` 等本地接口；通过 `file://` 打开时没有 Node 服务提供这些接口。

## 核心版界面

服务启动后可通过 <http://127.0.0.1:3000/core> 打开 `index-core.html`。核心版保留快讯流、新闻导入、智能分析、候选标的、按需日 K 和开市日历，移除了“导出今日清单”“加入复盘跟踪”、复盘校验页面以及页面内 `.ics` 下载入口。

核心版与原版共用现有 `/api/news`、`/api/imports`、`/api/analyze` 和 `/api/stock-kline`，不需要单独配置密钥、端口或业务接口。原来的 `/` 与 `/index.html` 继续返回完整原型页面；本机若使用其他端口，请将地址中的 `3000` 替换为实际端口。

## 命令行启动

也可以在本目录运行：

```bash
cp .env.example .env
npm start
```

复制命令只会在当前目录创建一个本地配置文件；在 `.env` 中填写自己的两个密钥。配置好后在浏览器打开 <http://127.0.0.1:3000>。

将原型发给其他 Windows 用户时，双击 [`打包分享.cmd`](打包分享.cmd) 生成 ZIP。ZIP 只包含运行所需文件，不包含 `.env`、`data/`、Git 文件或本机密钥。对方解压后安装 Node.js、在首次启动生成的 `.env` 中填写自己的 iFinD MCP 授权和 DeepSeek API Key，即可双击启动器运行。

未配置 iFinD 时，直接运行 `npm start` 的页面会使用示例新闻。未配置 DeepSeek 或DeepSeek调用失败时，自动候选采用保守策略，不会绕过质量判断进入页面；已有有效缓存仍可复用。双击启动器会提示先配置两项密钥。按手动刷新会重新读取新闻，导入记录保存在本机 `data/import-records.json`，摘要与质量判断缓存保存在 `data/news-summary-cache.json`。`data/` 已被忽略，不会随 Git 提交。

## 新闻刷新规则

- 每次刷新按 `Asia/Shanghai` 动态计算当天、昨天和前天。
- 每天完整执行3组国内固定检索和6组国际固定检索。每日候选不足12条时再执行3组补充检索。
- 每日最多保留20条候选供DeepSeek处理，每批最多12条；最终每日最多展示10条，三天合计最多30条。
- DeepSeek对每条候选同时返回事实摘要、`content_type`、`quality_score`、`a_share_relevance`、`factuality`、`materiality`、四级分类和淘汰原因。只有事实新闻且分数达到70、4、4、3门槛才进入后续去重。
- 摘要和质量结果按稳定新闻ID缓存。优先使用去除追踪参数后的原文链接；没有链接时组合标题、来源和发布日期。缓存版本失效才重新处理。
- 质量过滤后按核心事件、主体、事件日期、事件内容和影响对象去重，再按新鲜度15、来源权威性20、事件实质性25、A股传导直接性20、证据完整度10、多来源确认10计算信息重要度。
- 页面分类固定为宏观级、行业级、公司级、混合级。页面只显示iFinD提供的发布日期精度，不补造发布时间。

`GET /api/news` 会在 `processing_stats` 中保留候选数、缓存命中数、DeepSeek新处理数、质量淘汰数、失败数、去重数和最终展示数，并在 `query_log` 中记录实际检索日期、检索词和返回数量。这些字段用于开发追溯，页面不展示内部淘汰统计。

本目录的 `index.html` 是默认前端，`index-core.html` 是共用同一套接口的核心版前端，两者都已接入智能分析框架。旧的 `frontend/index.html` 和工作区外层 `财讯智析-UI原型.html` 不参与本次新闻功能修改。行情模块仍位于 `modules/market/`。
