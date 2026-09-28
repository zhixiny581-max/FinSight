# 智能分析结果契约

新闻摘要与推演结论必须使用不同字段。`news.summary` 是新闻模块提供的只读事实摘要，`verdict` 是智能分析模块生成的条件性判断。

分析优先使用清洗后的 `news.full_text`，摘要只用于展示和定位。所有市场行情必须满足 `date <= analysis_timing.market_data_cutoff`，不得把新闻发生后的数据送入事前分析。

每次分析先输出 `analysis_scope`，用于决定页面布局。公司级与行业级事件不强制生成宏观图；宏观级与混合型事件只有在通过宏观重要性门槛后才展示宏观传导图。

```json
{
  "analysis_scope": {
    "level": "公司级 | 行业级 | 宏观级 | 混合型",
    "rationale": "影响范围判断依据",
    "direct_objects": [],
    "macro_gate": {"applicable": true, "materiality": "中", "reasons": []}
  },
  "news": {
    "canonical_title": "标题",
    "summary": "固定事实摘要",
    "full_text": "清洗后的新闻全文，可为空",
    "event_time": "发布时间",
    "sources": []
  },
  "verdict": {
    "headline": "不超过30字的核心判断",
    "conclusion": "触发条件→变量变化→行业影响→市场含义，仅写主情景；反向内容放在 counter_scenarios",
    "direction": "多空交织",
    "horizon": "短期",
    "confidence": 60,
    "causal_basis": [],
    "conditions": [],
    "counter_scenarios": [],
    "validation_metrics": []
  },
  "macro_analysis": {
    "applicable": true,
    "scope": "混合",
    "summary": "宏观与市场条件性判断",
    "channels": [],
    "market_impacts": [{
      "asset": "黄金",
      "direction": "多空交织",
      "positive_drivers": ["避险需求", "通胀预期"],
      "negative_drivers": ["实际利率上升", "美元走强"],
      "dominant_condition": ""
    }],
    "market_pricing": {
      "state": "部分提前定价",
      "confidence": 50,
      "basis": [],
      "caveat": "定性判断，不代表精确计价比例"
    },
    "macro_chain": {
      "nodes": [{
        "id": "shock-1",
        "type": "direct_shock",
        "stage": 1,
        "label": "直接冲击变量",
        "direction": "利空",
        "horizon": "短期",
        "impact_level": "中",
        "confidence": 60,
        "mechanism": "条件性传导机制",
        "conditions": [],
        "offsets": []
      }],
      "edges": [{"from":"macro-event","to":"shock-1","mechanism":"传导机制","direction":"利空","condition":""}],
      "validation_indicators": [{
        "id":"validation-1",
        "node_id":"shock-1",
        "indicator":"后续验证指标",
        "expected_direction":"上行压力",
        "observation_window":"后续1至3个月",
        "purpose":"验证对应传导是否发生",
        "status":"待验证"
      }]
    }
  },
  "macro_market": {
    "benchmark": {"code": "700001.TI", "name": "同花顺全A（加权）"},
    "analysis_mode": "ex_ante",
    "market_data_cutoff": "YYYY-MM-DD",
    "window_size": 60,
    "source": "iFinD index_data",
    "fetched_at": "ISO-8601",
    "bars": []
  },
  "event": {},
  "direct_impacts": [
    {
      "id": "direct-1",
      "name": "事件直接参与方",
      "ticker": "001399.SZ，模型不得编造，由iFinD核验后回填",
      "entity_type": "上市公司",
      "listed_status": "已上市",
      "stock_lookup_allowed": true,
      "relation": "收购方",
      "direction": "多空交织",
      "horizon": "中期",
      "confidence": 70,
      "impact_level": "中",
      "mechanism": "事件对该主体的直接经营、财务或治理影响",
      "conditions": [],
      "risks": [],
      "evidence": "新闻中的直接事实",
      "evidence_source_ids": ["news-1"]
    }
  ],
  "industries": [
    {
      "id": "industry-1",
      "name": "行业名称",
      "parent_id": "event",
      "chain_stage": 1,
      "role": "传导作用",
      "direction": "利好",
      "confidence": 60,
      "impact_level": "待评估",
      "stock_expansion_allowed": true,
      "stock_expansion_basis": "事件通过订单、成本、供需、产能或监管变量影响行业内一组公司的依据",
      "driver_node_id": "shock-1",
      "reason": "行业入选依据"
    }
  ],
  "industry_chain": {
    "nodes": [
      {"id": "event", "type": "event", "label": "事件"},
      {"id": "industry-1", "type": "industry", "label": "行业名称", "stage": 1}
    ],
    "edges": [
      {"from": "event", "to": "industry-1", "mechanism": "传导机制", "direction": "利好"}
    ]
  },
  "candidate_stocks": [
    {
      "code": "000000",
      "name": "公司名称",
      "industry_id": "industry-1",
      "industry_name": "行业名称",
      "chain_stage": 1,
      "direction": "利好",
      "confidence": 50,
      "impact_level": "待评估",
      "impact_type": "direct | industry",
      "direct_impact_id": "direct-1，直接影响股票填写",
      "role": "本次传导中的角色",
      "data_source": "iFinD search_stocks"
    }
  ],
  "stock_provider_status": {
    "status": "available | partial | empty | unavailable",
    "reason_code": "",
    "message": "不得把接口失败解释为没有受影响股票",
    "source": "iFinD search_stocks",
    "checked_at": "ISO-8601"
  },
  "uncertainties": [],
  "risk_notice": "本结果用于研究整理，不构成投资建议。"
}
```

## 枚举

- `direction`：`利好`、`利空`、`多空交织`、`不确定`
- `horizon`：`短期`、`中期`、`长期`、`不确定`
- `impact_level`：`高`、`中`、`低`、`待评估`
- `node.type`：`event`、`industry`
- `macro_chain.node.type`：`event`、`direct_shock`、`real_economy`、`policy_expectation`、`market`
- `market_pricing.state`：`未见明显提前定价`、`部分提前定价`、`提前定价较充分`、`可能过度交易`、`无法判断`、`不适用`

`confidence` 取值为 0 至 100，只表示证据和传导逻辑的可信程度，不是上涨概率。

`direct_impacts` 用于公司关系型事件的直接参与方。新闻明确点名的A股上市公司可以作为直接影响标的进入 `candidate_stocks`，不要求关联行业节点；普通同行不能仅凭行业归属进入。模型生成的 `listed_status` 只是初判，服务端应使用 iFinD 基本资料核验并回填 `ticker`、上市状态、核验来源和时间。`industries.stock_expansion_allowed` 只有在事件改变收入、成本、供需、订单、产能、资本开支或监管约束，并且影响适用于行业内一组公司时才能为 `true`。

`validation_indicators` 只表示新闻发生后需要继续观察的指标，生成分析时状态统一为“待验证”，不得写成宏观指标已经发生变化。`impact_level` 表示传导成立时的潜在影响强弱，与 `confidence` 分开。

`macro_chain` 的标准经济顺序为事件 → 直接冲击 → 一阶实体影响 → 二阶政策与预期反馈 → 市场影响。各类型含义固定如下：

- `direct_shock`：事件首先改变的供给、需求、价格风险溢价或制度约束。
- `real_economy`：成本、收入、订单、生产、消费、投资、就业、进出口以及已经实现的物价变化。
- `policy_expectation`：通胀或增长预期、利率路径预期、货币财政政策反应和金融信用条件变化。
- `market`：风险偏好、估值、折现率、资产价格和市场风格。

某层没有事实或逻辑依据时可以省略，但结论、宏观摘要或传导机制已经提及的层级必须生成独立节点。一个节点不得合并不同层级的概念，所有边必须由较早层级指向较晚层级。

行业层不展示预期差；宏观层只用事前宽基与宏观市场数据作定性判断；同花顺全A在分析完成后立即展示。个股层在用户点开标的时，才以同一新闻截止点读取个股、行业基准与全A最近60个有效交易日，再判断是否存在提前交易迹象。

