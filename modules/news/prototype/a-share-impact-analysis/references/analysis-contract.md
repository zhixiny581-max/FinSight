# 分析结果契约

网站后端返回一个 JSON 对象。字段名保持稳定，空数组比省略字段更好。

```json
{
  "news": {
    "canonical_title": "规范化标题",
    "summary": "经过压缩和专业化处理的摘要",
    "event_time": "2026-09-20T10:00:00+08:00",
    "sources": [
      {
        "title": "原文标题",
        "publisher": "来源名称",
        "published_at": "2026-09-20T09:30:00+08:00",
        "url": "https://example.com/article",
        "authority_level": "official",
        "is_primary": true
      }
    ]
  },
  "event": {
    "type": "政策支持",
    "direction": "利好",
    "horizon": "中期",
    "confidence": 0.72,
    "key_variables": ["订单", "产品价格"]
  },
  "impact_chain": [
    {
      "step": 1,
      "title": "政策或事件",
      "detail": "发生了什么",
      "direction": "利好",
      "evidence": ["news-1"]
    },
    {
      "step": 2,
      "title": "行业传导",
      "detail": "如何影响供需、价格、成本或竞争",
      "direction": "利好",
      "evidence": []
    },
    {
      "step": 3,
      "title": "公司影响",
      "detail": "公司需要验证什么",
      "direction": "不确定",
      "evidence": []
    }
  ],
  "industries": [
    {
      "name": "行业名称",
      "direction": "利好",
      "reason": "入选原因",
      "confidence": 0.65
    }
  ],
  "candidate_stocks": [
    {
      "code": "000000",
      "name": "公司名称",
      "industry": "行业名称",
      "stage": "直接影响",
      "direction": "利好",
      "reason": "与影响链的关联",
      "evidence": ["stock-1"],
      "data_as_of": "2026-09-20"
    }
  ],
  "screened_stocks": [
    {
      "code": "000000",
      "name": "公司名称",
      "score": 7.5,
      "tier": "重点观察",
      "screening_reasons": ["事件传导直接", "数据较新"],
      "risks": ["估值较高"]
    }
  ],
  "summary": "一段给网页顶部展示的综合总结",
  "uncertainties": ["需要等待后续公告验证"],
  "risk_notice": "本结果用于研究整理，不构成投资建议。",
  "kline": [
    {
      "code": "000000",
      "name": "公司名称",
      "as_of": "2026-09-20",
      "status": "available",
      "unit": "元",
      "bars": [
        {"date": "2026-09-19", "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000000}
      ]
    }
  ]
}
```

## 枚举

- `authority_level`: `official`、`exchange`、`company`、`major_media`、`other`
- `direction`: `利好`、`利空`、`多空交织`、`不确定`
- `horizon`: `短期`、`中期`、`长期`、`不确定`
- `tier`: `重点观察`、`一般观察`、`暂不纳入`
- `stage`: `上游`、`直接影响`、`下游`
- K线 `status`: `available`、`unavailable`、`stale`

`confidence` 和 `score` 只能表达分析排序，不能被网页解释为收益概率或上涨幅度。
