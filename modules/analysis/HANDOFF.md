# FinSight 智能分析模块交接文档

## 当前模块边界

智能分析的活动代码已经迁入本目录：

- `analysis_service.js` 负责 DeepSeek 请求、结果标准化、摘要重复度校验和兜底结果。
- `prompts/impact-analysis.txt` 规定限制性推演结构。
- `SKILL.md` 和 `references/` 记录职责与数据契约。
- 当前新闻原型仍提供 `/api/analyze` 和 `/api/stock-kline` 路由，但只负责调用本模块及适配 iFinD，以保持原有启动方式兼容。

新闻摘要是只读输入，有清洗后全文时以全文作为推演的主要事实依据。宏观与全市场影响、行业与产业链影响分开输出；产业链图只包含事件与行业节点，股票清单通过 `industry_id` 关联行业。宏观层使用同花顺全A事前行情作定性判断，股票详情通过 iFinD `get_stock_performance` 查询新闻时点以前最近60个有效交易日日线，并与行业基准、同花顺全A对照。新闻后的行情留给复盘模块，本阶段不得进入事前分析。

本文档用于记录 FinSight 智能分析模块的开发、配置和交接信息。当前先说明从 GitHub 获取项目后，如何配置 iFinD MCP 与 DeepSeek API，并双击启动现有网站。

## 1. 当前可运行范围

目前可通过双击启动的是新闻模块原型，目录为：

```text
FinSight/modules/news/prototype/
```

启动后打开的页面由该目录下的 `index.html` 提供，后端由 `server.js` 提供。仓库中的 `frontend/index.html` 是主前端 UI 原型，目前还没有与新闻模块后端完成集成，因此直接双击主前端只能查看静态界面。

## 2. 运行环境

队友需要准备：

- Windows 电脑
- Node.js 18 或更高版本
- 有效的 iFinD MCP Authorization
- 有效的 DeepSeek API Key
- 可访问 iFinD MCP 和 DeepSeek API 的网络

本项目当前没有第三方 npm 依赖，不需要执行 `npm install`。

可以在命令提示符或 PowerShell 中运行以下命令检查 Node.js：

```powershell
node --version
```

输出版本号为 `v18` 或更高版本即可。

## 3. 从 GitHub 获取项目

可以选择以下任一种方式：

1. 在 GitHub 项目页面下载 ZIP，然后完整解压。
2. 使用 Git 克隆仓库，并切换到包含当前功能的分支。

不要只下载单个 `index.html`。页面依赖同目录下的启动脚本、Node.js 服务和接口代码，缺少这些文件将无法使用新闻和 AI 分析功能。

## 4. 第一次双击启动和填写配置

进入以下目录：

```text
FinSight/modules/news/prototype/
```

双击：

```text
启动FinSight.cmd
```

第一次运行时，启动器会执行以下操作：

1. 检查 Node.js 版本。
2. 根据 `.env.example` 在当前目录生成本机配置文件 `.env`。
3. 使用记事本打开 `.env`。

在 `.env` 中填写：

```dotenv
PORT=3000
IFIND_MCP_AUTHORIZATION=填写自己的iFinD授权值
DEEPSEEK_API_KEY=填写自己的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

填写时注意：

- `IFIND_MCP_AUTHORIZATION` 填写平台提供的完整 Authorization 原值，不要自行添加 `Bearer` 前缀。
- 等号两侧不要添加多余空格。
- 不要使用中文引号包裹密钥。
- `.env` 包含个人凭据，不要上传到 GitHub，也不要发给其他人。

填写完成后保存并关闭记事本。

## 5. 第二次双击并打开网站

再次双击 `启动FinSight.cmd`。配置检查通过后，启动器会在后台运行本地服务，并自动在浏览器中打开：

```text
http://127.0.0.1:3000/
```

以后正常使用时，只需双击该启动文件。若服务已经运行，重复双击只会再次打开页面，不会重复启动服务。

不能直接双击 `index.html` 运行完整功能。直接双击会以 `file://` 方式打开静态页面，此时没有本地服务提供 `/api/news`、`/api/imports` 和 `/api/analyze` 等接口。

## 6. 是否必须安装 iFinD MCP Skill

不必须安装。

当前项目已经在 `ifind_client.js` 中内置了新闻和股票数据所需的 iFinD MCP 请求客户端。只要在 `.env` 中正确填写 `IFIND_MCP_AUTHORIZATION`，程序就会直接使用内置客户端连接 iFinD MCP。

`ifind-finance-data` Skill 只是兼容的备用连接方式。当电脑已经安装并配置该 Skill 时，项目可以读取其配置；对新队友而言，直接填写 `IFIND_MCP_AUTHORIZATION` 更简单。

## 7. 常见问题

### 双击后提示找不到 Node.js

安装 Node.js 18 或更高版本，安装完成后重新打开文件夹并双击启动器。必要时重启电脑，使 Node.js 加入系统 `PATH`。

### 双击后再次打开 `.env`

说明 `DEEPSEEK_API_KEY` 或 `IFIND_MCP_AUTHORIZATION` 仍为空，或者填写格式未通过检查。保存有效配置后再次双击。

### 3000 端口被其他程序占用

将 `.env` 中的端口改为其他未占用端口，例如：

```dotenv
PORT=3001
```

重新启动后访问对应地址，例如 `http://127.0.0.1:3001/`。

### 修改配置后没有生效

本地 Node.js 服务可能仍在使用旧配置。先结束原来的 Node.js 服务，再双击启动器。错误日志位于：

```text
FinSight/modules/news/prototype/data/server-error.log
```

## 8. 配置依据与核对记录

- 核对时间：2026-09-27，Asia/Shanghai
- 核对方式：读取当前分支中的 `start.ps1`、`.env.example`、`server.js` 和 `ifind_client.js`
- 当前分支：`feature/news-import-20260924`
- iFinD 接入方式：优先读取本机 `.env` 中的授权值并使用内置 MCP 客户端，已安装 Skill 时可作为备用方式
- DeepSeek 接入方式：读取本机 `.env`，请求地址默认为 `https://api.deepseek.com`

本文档不记录任何真实 API Key、Authorization 或密码。
