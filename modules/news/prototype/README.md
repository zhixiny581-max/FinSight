# 财讯智析新闻原型（独立运行）

这是 B 组新闻导入、快讯流的演示版本。支持从 iFinD 刷新新闻、粘贴链接导入、打标入库、保存导入记录；配好 DeepSeek 后可生成摘要和按需分析。`index.html` 与 `server.js` 必须放在同一目录。

在本目录运行，电脑需要已有 Node.js，无需额外安装 npm 依赖：

```bash
cp .env.example .env
npm start
```

复制命令只会在当前目录创建一个本地配置文件；在 `.env` 中填写自己的 `DEEPSEEK_API_KEY`。如 iFinD Skill 不在默认的 `~/.codex/skills/ifind-finance-data`，还要填写本机的 `IFIND_SKILL_DIR`。iFinD 的连接配置保存在各自安装的 Skill 目录，本仓库没有、也不应提交任何真实密钥。配置好后在浏览器打开 <http://127.0.0.1:3000>；不要直接双击 HTML 文件，否则接口无法工作。

未配置 iFinD 时，页面会使用示例新闻；未配置 DeepSeek 时，AI 摘要与分析不能保证真实生成。按手动刷新会重新读取新闻，导入记录保存在本机 `data/import-records.json`，摘要缓存保存在 `data/news-summary-cache.json`。`data/` 已被忽略，不会随 Git 提交。

这个目录是独立原型，不是小组最终前端。主页面仍在仓库的 `frontend/`，行情模块仍在 `modules/market/`；集成时需要由相关同学决定路由和页面合并方式。
