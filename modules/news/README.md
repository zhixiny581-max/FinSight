# 新闻模块

这里保存当前集成快讯流、新闻导入和智能分析框架的可运行页面。实际前端是 `prototype/index.html`；本模块不会修改旧的 `frontend/index.html` 或工作区外层的 `财讯智析-UI原型.html`，也不会替代行情模块接口。

原型代码在 [`prototype/`](prototype/README.md)。其中的 `index.html` 是配套页面，`server.js` 提供本地接口。新闻读取与摘要规则位于 `prototype/news-processing/`；正式推演规则、Prompt、结构契约和校验代码已迁入 `modules/analysis/`。

当前页面已经接入 `modules/analysis/` 的AI分析和股票展示逻辑。新闻相关改动应在现有页面上增量完成，不能用旧版静态原型覆盖该文件。

供主前端对接的主要接口为 `GET /api/news`、`POST /api/imports`、`GET /api/imports`、`POST /api/imports/:id/prepare`、`POST /api/imports/:id/confirm`、`DELETE /api/imports/:id`。所有接口与页面同源运行，返回 JSON；具体调用方式可在原型页面脚本中查看。

`GET /api/news` 动态查询北京时间最近3个自然日。每天固定执行国内3组、国际6组检索，国际检索不以国内候选不足为前提；每日候选不足12条时执行3组补充检索，每日最多处理20条候选、最多展示10条，三天合计最多30条。自动候选只有在DeepSeek摘要和质量判断同时完成并通过门槛后才进入快讯流，随后按事件去重并计算独立的信息重要度。

页面与接口只使用宏观级、行业级、公司级、混合级四个标签。旧缓存和人工导入记录中的五类旧标签会在读取时迁移。摘要和质量结果保存在 `prototype/data/news-summary-cache.json`，稳定标识优先使用规范化原文链接；没有链接时才使用标题、来源和日期生成。
