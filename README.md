# FinSight / 财讯智析

FinSight 是一个财经新闻分析平台。本仓库按四人协作边界组织代码，包含产品 UI 原型、新闻功能原型和行情模块。

## 分工

| 负责人 | 目录 | 职责 |
| --- | --- | --- |
| A | `frontend/` | 产品与前端；维护主界面并完成最终集成 |
| B | `modules/news/` | 快讯流与新闻导入 |
| C | `modules/analysis/` | 智能分析与面向用户的复盘校验 |
| D | `modules/market/` | 开市日历、日 K 数据与行情能力 |
| D | `eval/` | 离线评测、测试用例与评测结果 |

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

当前集成新闻导入、快讯流和智能分析的可运行前端为 [`modules/news/prototype/index.html`](modules/news/prototype/index.html)，需要通过其本地 Node 服务打开，不能直接使用 `file://`。启动与配置方式见 [`modules/news/README.md`](modules/news/README.md)。

`frontend/index.html` 与工作区外层的旧版 `财讯智析-UI原型.html` 作为早期静态原型保留，不是当前新闻功能的运行入口。

新闻模块按北京时间读取最近3个自然日，每天最多展示10条，三天合计最多30条。自动新闻必须先完成DeepSeek事实摘要和结构化质量判断，再进行事件级去重和信息重要度计算；页面分类统一为宏观级、行业级、公司级、混合级。

## 协作约定

- A 维护唯一的主前端；B、C、D 优先在各自目录中开发，避免相互覆盖。
- 各模块应提供清晰的调用说明、输入输出示例和所需环境变量说明。
- Prompt 建议放在各模块自己的 `prompts/` 目录中，不要写死在业务代码里。
- 真实 API Key、Token、密码和本地 `.env` 文件不得提交到仓库。
