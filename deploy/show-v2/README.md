# FinSight 反馈修订版 · Python 部署

迁移基准：GitHub main 960b08eaf48e030244b6ba8f56aa3fee1ffd0676。
此目录独立于原 Node.js 代码与旧 Python 展示包。反馈提示词沿用迁移基准，前端和部署逻辑包含 2026-11-07 的线上更新。

- 启动：`python app.py`，读取 `PORT`，监听 `0.0.0.0`。
- 机密：按 **环境变量 > 本目录 `api-config.json` > `~/.finsight/config.json`** 三层读取，哪层有值就用哪层，只覆盖填写过的项。首次使用双击 `打开配置文件.cmd`，从 `api-config.example.json` 生成并填写。不要将实际值打包或提交。
- 配置项：`ifind`（iFinD 授权串）、`deepseek`（模型密钥）、可选 `tavily`；另有可选 `deepseek_base_url`、`deepseek_model`（留空用代码默认）。「接口设置」只显示配置状态，`GET /api/health` 返回各服务是否配置。
- 数据：`DATA_DIR`，按平台配置持久保存新闻缓存、导入记录和受限审计。
- 快讯：`GET /api/news?snapshot=1` 只读取持久化的日快照，并合并已确认的导入新闻。手动刷新重查快照的最后一天和之后的日期，以最近 7 个自然日为限。
- 人气榜：`GET /api/rank` 返回东方财富排名，使用同花顺 iFinD 批量补齐行情。每批最多 10 只，行情缓存 2 分钟。遇到临时失败时保留并标注已有行情。
- 新闻导入、智能分析、相关公司和两类行情与看板同源提供。
- 取证：iFinD 新闻和安全公开网页读取可用；未配置 Tavily 时不启用通用网页搜索。不提供事后资料作为事前证据。
- 验证：`python -B -m unittest discover -v`。测试不调用付费 API；上线后再分别验证实际提供商。配置排查见 `docs/接口配置说明.md`。

部署 ZIP 根目录包含 `deploy.json`、`app.py`、`base.py`、`config_store.py`、`market_adapter.py`、`news_provider.py`、`feedback_analysis.py`、`popularity.py`、`index.html` 和 `feedback.txt`。不要打包 `api-config.json`、`.env`、测试记录、缓存或原始源码快照。
