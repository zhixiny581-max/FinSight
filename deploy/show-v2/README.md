# FinSight 反馈修订版 · Python 部署

迁移基准：GitHub main 960b08eaf48e030244b6ba8f56aa3fee1ffd0676。
此目录独立于原 Node.js 代码与旧 Python 展示包。前端和反馈提示词来自该基准，缓存状态提示为部署版适配。

- 启动：`python app.py`，读取 `PORT`，监听 `0.0.0.0`。
- 机密：服务器环境变量 `IFIND_MCP_AUTHORIZATION`、`DEEPSEEK_API_KEY`；可选 `TAVILY_API_KEY`。不要将实际值打包。
- 数据：`DATA_DIR`，按平台配置持久保存新闻缓存、导入记录和受限审计。
- API：新闻、导入、智能分析、相关公司和两类行情与新版页面同源提供。无可用新闻时明确回退为缓存或示例。
- 取证：iFinD 新闻和安全公开网页读取可用；未配置 Tavily 时不启用通用网页搜索。不提供事后资料作为事前证据。
- 验证：`python -B -m unittest discover -v`。测试不调用付费 API；上线后再分别验证实际提供商。

部署 ZIP 根目录包含 deploy.json、app.py、base.py、market_adapter.py、news_provider.py、feedback_analysis.py、index.html 和 feedback.txt。不要打包 .env、测试记录、缓存或原始源码快照。
