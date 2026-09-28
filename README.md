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

直接使用浏览器打开 `frontend/index.html` 即可查看当前 UI 原型。

新闻导入与快讯流的独立演示及配置方式见 [`modules/news/README.md`](modules/news/README.md)。

## 协作约定

- A 维护唯一的主前端；B、C、D 优先在各自目录中开发，避免相互覆盖。
- 各模块应提供清晰的调用说明、输入输出示例和所需环境变量说明。
- Prompt 建议放在各模块自己的 `prompts/` 目录中，不要写死在业务代码里。
- 真实 API Key、Token、密码和本地 `.env` 文件不得提交到仓库。
