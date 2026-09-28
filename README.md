# FinSight / 财讯智析

## 最新更新：核心版前端（供组员同步）

更新时间：2026-09-28 23:37（北京时间，UTC+8）

新增核心版前端 [`modules/news/prototype/index-core.html`](modules/news/prototype/index-core.html)，保留新闻与智能分析等核心功能，移除导出今日清单、复盘跟踪、复盘校验及 `.ics` 下载入口；增加产业链传导路径放大查看，修复顶部栏固定问题。

同时更新页面路由和打包清单。核心版沿用现有后端接口与配置，原版 `index.html` 保留。组员同步最新代码后，可按[项目启动说明](modules/news/prototype/README.md)在本地运行。

FinSight 是一个财经新闻分析平台。本仓库按四人协作边界组织代码，包含产品 UI 原型、新闻功能原型和行情模块。

## 分工

| 负责人 | 目录 | 职责 |
| --- | --- | --- |
| A | `frontend/` | 产品与前端 |
| B | `modules/news/` | 快讯流与新闻导入 |
| C | `modules/analysis/` | 智能分析 |
| D | `modules/market/` | 开市日历、日 K 数据与行情能力 |
| D | `eval/` | 最终集成、离线评测、测试用例与评测结果 |

## 目录结构

```text
FinSight/
├── frontend/
│   └── index.html
├── modules/
│   ├── news/
│   │   └── prototype/
│   ├── analysis/
│   └── market/
├── eval/
├── .env.example
├── .gitignore
└── README.md
```

## 本地预览

当前核心版前端为 [`modules/news/prototype/index-core.html`](modules/news/prototype/index-core.html)，本地服务启动后通过 `/core` 访问。原版 [`modules/news/prototype/index.html`](modules/news/prototype/index.html) 仍通过 `/` 访问。两个页面都需要本地 Node 服务提供接口，不能直接双击 HTML 文件运行；启动与配置方式见 [原型启动说明](modules/news/prototype/README.md)。

`frontend/index.html` 与工作区外层的旧版 `财讯智析-UI原型.html` 作为早期静态原型保留，不是当前新闻功能的运行入口。

新闻模块按北京时间读取最近3个自然日，每天最多展示10条，三天合计最多30条。自动新闻必须先完成DeepSeek事实摘要和结构化质量判断，再进行事件级去重和信息重要度计算；页面分类统一为宏观级、行业级、公司级、混合级。

## 协作约定

- A 维护唯一的主前端；B、C、D 优先在各自目录中开发，避免相互覆盖。
- 各模块应提供清晰的调用说明、输入输出示例和所需环境变量说明。
- Prompt 建议放在各模块自己的 `prompts/` 目录中，不要写死在业务代码里。
- 真实 API Key、Token、密码和本地 `.env` 文件不得提交到仓库。
