# 新闻模块

这里保存快讯流和新闻导入功能的可运行原型，供小组集成。它不会修改 `frontend/index.html`，也不会替代行情模块的接口。

原型代码在 [`prototype/`](prototype/README.md)。其中的 `index.html` 是配套页面，`server.js` 提供本地接口。`a-share-impact-analysis/` 是目前原型使用的分析规则参考，后续分析模块的正式规则由 C 组维护。

目前原型同时包含部分 AI 分析和股票展示逻辑，是为了演示完整流程；小组集成时建议按分工拆分，不要直接把整个页面覆盖到主前端。

供主前端对接的主要接口为 `GET /api/news`、`POST /api/imports`、`GET /api/imports`、`POST /api/imports/:id/prepare`、`POST /api/imports/:id/confirm`、`DELETE /api/imports/:id`。所有接口与页面同源运行，返回 JSON；具体调用方式可在原型页面脚本中查看。
