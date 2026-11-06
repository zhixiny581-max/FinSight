# FinSight · 财经新闻事件分析

FinSight 将财经新闻整理为事件判断、宏观或行业传导、相关公司清单和行情观察。本仓库同时保留旧版 V1 与反馈修订版，便于演示、对照和回退。当前分析范围是**板块大致方向与相关公司名单**，不逐家公司开展财务研究，也不输出目标价或收益预测。

## 两个版本在哪里

| 版本 | 程序目录 | 根目录启动入口 | 默认地址 |
| --- | --- | --- | --- |
| 旧版 V1 | 原有 `modules/`、`frontend/`、`eval/` | `启动旧版.cmd` | http://127.0.0.1:3000/core |
| 新版反馈修订版 | `versions/feedback/` | `启动新版.cmd` | http://127.0.0.1:3003/core |

旧版程序、原提示词和原界面保留原位。本次只调整根目录 README、Git 忽略规则，并新增新版子目录、启动工具和说明材料。两个版本的 `.env`、新闻缓存、导入记录和分析审计各自独立；不会因启动新版而覆盖旧版数据。不要把整个新版目录覆盖到旧版 `modules/` 上。

`/core` 是核心界面，`/` 是完整原型页面；它们是界面入口，不是 V1/V2 的版本区分。版本由启动的程序目录决定。GitHub 只存储源文件，不直接运行这些本地 API；不能直接双击业务页面 HTML，也不能把本机地址当作在线部署地址。

## 课程展示与 Python 部署

[财讯智析课程展示站](https://mf12.show.lingnan.top/core) 使用 [Python 部署版](deploy/show-v2/README.md)。展示页保留快讯、智能分析、相关公司和行情，开发交接和标注入口已移除。复现线上版本时，按部署说明配置服务器环境变量。

### 展示版的密钥放哪

展示版（`deploy/show-v2`）不用 `.env`，改成两份可选文件，读到一个就停：

| 优先级 | 文件 | 场景 |
| --- | --- | --- |
| 1 | 系统环境变量 | 线上服务器注入 |
| 2 | `deploy/show-v2/api-config.json` | **展示机、同学本地部署**（项目内，随文件夹拷走） |
| 3 | `~/.finsight/config.json` | 跨项目复用（项目外，不会随仓库分发） |

课堂展示机：双击 `deploy/show-v2/打开配置文件.cmd` 填好 `api-config.json`，整个文件夹拷到展示电脑即可直接用。

同学本地部署：同样双击这个文件，从空模板 `api-config.example.json` 生成，按提示填写后重启服务，再进页面「工具 → 接口设置」点「全部检测」。

`api-config.json` 不进 Git、不进上传包（`.gitignore` 与打包脚本双重拦截，打包前还会扫描其中的真实值是否泄漏到其他文件）。只有空模板 `api-config.example.json` 会提交。完整步骤、字段表和排查方法见 [接口配置说明](docs/接口配置说明.md)。

## 环境与首次配置

双版本启动器及新版需要 **Node.js 22 或以上**。核心运行与基础测试只使用 Node.js 自带模块，不需要安装 npm 依赖，也不要求安装 Codex 或 iFinD Skill。

每版分别配置自己的文件：

| 版本 | 本机配置 | 可提交的空模板 |
| --- | --- | --- |
| 旧版 | `modules/news/prototype/.env` | 同目录 `.env.example` |
| 新版 | `versions/feedback/modules/news/prototype/.env` | 同目录 `.env.example` |

Windows 用户第一次双击对应启动入口，若配置不存在，程序会从空模板创建 `.env` 并打开记事本。填写后保存，再双击启动。也可手动复制模板：

```powershell
# 以下两条仅用于配置文件尚不存在的首次安装
Copy-Item modules/news/prototype/.env.example modules/news/prototype/.env
Copy-Item versions/feedback/modules/news/prototype/.env.example versions/feedback/modules/news/prototype/.env
```

请勿重新复制模板覆盖已经填写的配置。直接在各自 `.env` 中修改：

```dotenv
# 旧版默认3000，新版默认3003；同时运行时必须使用不同端口
PORT=3003
IFIND_MCP_AUTHORIZATION=
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
# 新版可选；不配置时仍可使用iFinD新闻检索和公开网页读取
TAVILY_API_KEY=
ANALYSIS_RETRIEVAL=on
```

- `IFIND_MCP_AUTHORIZATION` 填 iFinD MCP 提供的完整授权原值，不要自行添加 Bearer 前缀。两版都内置 iFinD 客户端；已有 Skill 配置也可作为备选。
- `DEEPSEEK_API_KEY` 填自己的模型密钥；`DEEPSEEK_MODEL` 使用所配置接口支持的模型名。项目模板沿用 `deepseek-flash`。
- `TAVILY_API_KEY` 是新版通用网页搜索的可选配置；为空时该工具会明确标为不可用，不假装已联网搜索。
- `ANALYSIS_RETRIEVAL=off` 可关闭新版额外补证，供开发对照；正常演示用 `on`。
- 两版可填写同一账号授权，但各自单独保存。实际 API 调用会消耗相应服务额度。

配置不完整或外部服务失败时，页面可能展示示例新闻、已有缓存或受限分析，不能把它们当作本次真实调用成功。`/api/status` 可检查当前服务配置与版本标识，不返回密钥。

## 启动、停止与回退

根目录双击 `启动新版.cmd` 或 `启动旧版.cmd`。服务在后台运行，重复启动同一版本只打开页面；遇到其他程序或不同实例占用端口时会提示，不会结束其他程序。

```powershell
node tools/launch.cjs feedback --check
node tools/launch.cjs legacy --check
node tools/launch.cjs feedback --no-open
node tools/launch.cjs legacy --no-open
```

修改配置或代码后，双击对应的 `停止新版.cmd` / `停止旧版.cmd`，再启动。停止工具只处理本工具记录且命令路径匹配的进程；无法核对身份时会拒绝停止。旧启动器创建的进程不一定有新工具的进程记录，这时需在原启动终端停止。

回退只需停止新版并启动旧版，打开旧版地址。程序和数据都保留在各自目录，无需覆盖文件、卸载或还原提交。

如需直接从命令行运行：

```powershell
# 旧版
node modules/news/prototype/server.js --port=3000
# 新版
node versions/feedback/modules/news/prototype/server.js --port=3003
```

后台启动日志及 PID 记录保存在各版本 `modules/news/prototype/data/`。本机原先在3003运行的其他副本，需要先停止后才能启动本目录新版。

## 新版分析过程

1. 以新闻摘要、可用全文、来源和发布时间为固定输入，分析不改写新闻摘要。
2. 取得新闻时点以前的全A行情；统一上海时区，检查缺失值、收益窗口及比较日期。
3. DeepSeek 判断公司、行业、宏观或混合范围，输出事件和板块的大致方向、机制、成立条件、相反路径与验证指标。
4. 如需额外依据，执行实际检索并回传资料或失败状态，让模型修订；最多2轮、6次工具调用，共享整个请求的240秒预算。
5. 检查输出结构、所声明事实的引用支持与资料时点。无效首稿有一次结构修复；无效的补证修订保留之前的有效结果，不自动补造宏观因果边。
6. 在分析完成后查询 iFinD 直接参与方和符合经营变量门槛的板块公司，核对关联；公司表方向和强度引用对应板块或事件，并明确标注口径。
7. 返回分析并保存本机运行记录。点击公司时才查询个股、行业基准与全A的事前日K。

全A市场图是独立观察入口：所有新闻层级都展示，可在最新行情与新闻前行情间切换并标记新闻日。最新数据不写回事前分析；后续市场涨跌不直接归因为这一条新闻。宏观级隐藏事件直接影响和产业链传导两块；混合型仍保留实质行业路径。

## 验证与边界

```powershell
npm --prefix modules/news/prototype test
npm --prefix versions/feedback/modules/news/prototype run check
npm --prefix versions/feedback/modules/news/prototype test
node tools/test-release.cjs
node tools/check-legacy.cjs
node tools/prepare-release.cjs --check
```

基础测试使用合成场景，不包含同学的16道独立评测题。通过测试表示相应机制和接口行为符合约定，不等于已经通过独立测评，也不保证每条财经新闻的因果判断正确。引用检查覆盖模型声明的 claims，仍需要人工判断引用是否真正支持经济解释。外部接口、网页访问和原始新闻质量仍会影响结果。

[交付复核记录](docs/review/交付复核.md)记录本次实际检查范围及结果；[分析模块说明](versions/feedback/modules/analysis/README.md)说明当前 prompt、编排和数据职责。

## 讲解材料

讲解顺序是先完整介绍新版，再说明旧版问题与修改理由。

- [新版核心流程图](docs/presentation/new-analysis/new-analysis.html)：课堂演示只展示新版；可全屏、缩放和导出。
- [新版流程 PNG](docs/presentation/new-analysis/new-analysis.png)：可直接放进课件。
- [讲解思路与讲解稿](docs/presentation/分析模块讲解稿.md)：包含操作顺序、可照读稿件、问题—修改—效果对照及常见提问。

旧版、新版的程序说明均保留，但课堂流程图不再并排讲两版。原始协作目录及分工可参见旧版各模块说明。

## 文档索引

| 文档 | 内容 | 给谁看 |
| --- | --- | --- |
| [交接与待办](docs/交接与待办-20261105.md) | 按人分派：同学要改什么、全组要定什么 | 全组 |
| [接口配置说明](docs/接口配置说明.md) | 密钥放哪、怎么填、报错怎么查 | 部署的人 |
| [UI优化说明](docs/UI优化说明.md) | 这轮界面改了什么、为什么改 | 全组 |
| [移动端适配说明](docs/移动端适配说明.md) | 手机端改了哪些、怎么复测 | 前端 |
| [Bug修复记录](docs/Bug修复记录-20261104.md) | 13 项前端缺陷的定位、修复与实测 | 前端 |
| [页面实测与优化清单](docs/页面实测与优化清单.md) | 每屏实测结果与优化建议 | 前端 |
| [前端控件实测与修改意见](docs/前端控件实测与修改意见.md) | 逐控件行为核对与修改意见 | 前端 |
| [数据接入诊断](docs/数据接入诊断-20261104.md) | iFinD 新闻量少的原因分析与改法 | 后端 |
| [GitHub协作指南](docs/GitHub协作指南.md) | 添加、合并、分支流程与安全红线 | 全组 |

## 安全上传 GitHub

**真实密钥只放本机 `.env` 和 `deploy/show-v2/api-config.json`，不要上传 `.env`、`api-config.json`、`mcp_config.json`、`data/`、日志、运行审计或个人导入记录。** `.env.example` 与 `api-config.example.json` 是空模板，可上传。

推荐双击根目录 `打包上传GitHub.cmd`，或运行：

```powershell
node tools/prepare-release.cjs
```

上传包输出为 `release/FinSight-GitHub.zip`。工具只打包 `tools/publish-files.json` 中明确列出的项目文件，并检查本机密钥值、敏感文件路径和现有 Git 历史；发现命中即停止。ZIP 包含两个版本、空配置模板、README、测试和讲解材料，不含 `.git` 和本机配置。解压后进入包内的 `FinSight` 文件夹上传，其他同学按本 README 配置自己的密钥。

使用 Git 提交时，在推送前运行 `node tools/prepare-release.cjs --check` 并查看暂存文件列表。Git 忽略规则不保护网页端手动拖入的文件，手动上传请使用上述清洁包的内容。

旧版原有的 `modules/news/prototype/打包分享.cmd` 为保持旧文件不变而保留；它只打包新闻原型，不能作为本次完整分析项目的交付入口。请统一使用根目录 `打包上传GitHub.cmd`。
