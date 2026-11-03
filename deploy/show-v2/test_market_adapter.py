import json
import unittest
from datetime import date, datetime, timedelta

from market_adapter import MarketAdapter, SH, cutoff, excess, metrics, normalize_bars, stock_rows


def rpc(value):
    return {"jsonrpc": "2.0", "id": 7, "result": {"content": [
        {"type": "text", "text": json.dumps({"code": 1, "data": json.dumps(value, ensure_ascii=False)}, ensure_ascii=False)}
    ]}}


def bars_from(start=date(2026, 6, 1), size=80):
    return [{"date": (start + timedelta(days=i)).isoformat(), "open": 100+i,
             "high": 102+i, "low": 98+i, "close": 101+i, "volume": 1000}
            for i in range(size)]


class MarketTests(unittest.TestCase):
    def test_cutoff_respects_shanghai_date_precision_and_completion(self):
        self.assertEqual(cutoff({"published_at": "2026-07-10"})["requested_cutoff"], "2026-07-09")
        self.assertEqual(cutoff({"published_at": "2026-07-10T07:04:59Z"})["requested_cutoff"], "2026-07-09")
        self.assertEqual(cutoff({"published_at": "2026-07-10T07:05:00Z"})["requested_cutoff"], "2026-07-10")
        self.assertEqual(cutoff({"published_at": "2026-07-10T19:00+08:00", "published_precision": "date"})["requested_cutoff"], "2026-07-09")
        self.assertEqual(cutoff({"published_at": "2026-02-31"})["requested_cutoff"], "")

    def test_normalize_nested_markdown_caps_cutoff_and_rejects_invalid_bar(self):
        reply = rpc({"answer": """|交易日期|开盘价|最高价|最低价|收盘价|成交量|
|---|---|---|---|---|---|
|2026-07-08|10|12|9|11|3万股|
|2026-07-09|10|10|9|11|2万股|
|2026-07-10|10|12|9|11|2万股|
"""})
        got = normalize_bars(reply, "2026-07-09")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["date"], "2026-07-08")
        self.assertEqual(got[0]["volume"], 30000)
        one = normalize_bars(rpc({"rows": [{"date": "2026-07-08", "close": 3.2}]}), "2026-07-08", True)
        self.assertTrue(one[0]["close_only_benchmark"])

    def test_metrics_missing_and_excess_aligned(self):
        rows = bars_from(size=25)
        rows[0]["volume"] = None
        self.assertIsNone(metrics(rows)["volume_ratio_5d_to_prior20d"])
        self.assertIsNone(excess(rows, bars_from(date(2026, 6, 2), 25)))
        self.assertEqual(excess(rows, rows), 0)
        self.assertIsNone(metrics(rows)["return_60d_pct"])

    def test_provider_literal_escaped_linebreaks_and_symbol_verification(self):
        value = rpc({"answer": "|证券代码|日期|开盘价|最高价|最低价|收盘价|成交量|\\n"
                               "|---|---|---|---|---|---|---|\\n"
                               "|600519.SH|20260918|10|12|9|11|1.25万手|\\n"
                               "|000858.SZ|20260917|9|11|8|10|2万|"})
        bars = normalize_bars(value, "2026-09-18", expected_code="600519.SH")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["date"], "2026-09-18")
        self.assertEqual(bars[0]["volume"], 1250000)

    def test_live_routes_and_cache(self):
        calls = []

        def call(server, tool, args, timeout):
            self.assertGreater(timeout, 0)
            calls.append((server, tool))
            return rpc({"rows": bars_from()})

        service = MarketAdapter(call)
        news = {"published_at": "2026-08-08T10:00:00+08:00"}
        context = service.market_context(news)
        self.assertEqual(context["window_size"], 60)
        self.assertEqual(context["market_data_cutoff"], "2026-08-07")
        status, before = service.market_kline({"mode": ["pre_event"], "published_at": [news["published_at"]]})
        self.assertEqual(status, 200)
        self.assertEqual(before["item"]["analysis_mode"], "ex_ante")
        self.assertEqual(calls, [("index", "index_data")])
        _, latest = service.market_kline({"mode": "latest", **news})
        self.assertEqual(latest["item"]["analysis_mode"], "market_observation")
        self.assertGreater(latest["item"]["market_data_cutoff"], context["market_data_cutoff"])
        _, stock = service.stock_kline({"code": "600519.SH", **news, "industry": "食品饮料"})
        self.assertEqual(stock["item"]["market_data_cutoff"], "2026-08-07")
        self.assertEqual(stock["item"]["pricing_assessment"]["state"], "无法判断")
        self.assertEqual(stock["item"]["market_benchmark"]["market_data_cutoff"], "2026-08-07")
        self.assertTrue(stock["item"]["industry_benchmark"]["bars"][0]["close_only_benchmark"])

    def test_refuses_unknown_date_without_provider_calls(self):
        service = MarketAdapter(lambda *a, **k: self.fail("provider invoked without cutoff"))
        self.assertIsNone(service.market_context({"published_at": "?"}))
        self.assertEqual(service.market_kline({"mode": "pre_event"})[0], 400)
        self.assertEqual(service.stock_kline({"code": "600519.SH"})[0], 400)

    def test_direct_and_industry_references_without_kline_or_extra_model_calls(self):
        requests = []
        direct = [{"股票代码": "600519.SH", "股票简称": "贵州茅台", "所属同花顺行业": "食品饮料"},
                  {"股票代码": "000858.SZ", "股票简称": "五粮液", "所属同花顺行业": "食品饮料"}]

        def call(server, tool, args, timeout):
            requests.append(tool)
            return rpc({"rows": direct, "dataTotalVolume": 2})

        service = MarketAdapter(call)
        analysis = {
            "verdict": {"direction": "不确定", "impact_level": "待评估"},
            "direct_impacts": [{"id": "d1", "name": "贵州茅台股份有限公司", "entity_type": "其他", "relation": "发行人"}],
            "industries": [
                {"id": "i1", "name": "食品饮料", "stock_expansion_allowed": True, "reason": "供需发生变化", "direction": "利好"},
                {"id": "i2", "name": "地产", "stock_expansion_allowed": True, "reason": "仅为泛泛关联", "direction": "不确定"},
            ],
        }
        result = service.attach_stocks(analysis, {})
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["direction_scope"], "event_reference")
        self.assertEqual(result[1]["direction_scope"], "industry_reference")
        self.assertEqual(result[1]["direction"], "利好")
        self.assertEqual(result[0]["also_industry_ids"], ["i1"])
        self.assertEqual(analysis["direct_impacts"][0]["ticker"], "600519.SH")
        self.assertEqual(requests, ["search_stocks", "search_stocks"])
        self.assertFalse(analysis["company_listing"]["company_analysis"])

    def test_incomplete_provider_and_non_a_stock(self):
        one = {"股票代码": "600519.SH", "股票简称": "贵州茅台", "所属同花顺行业": "食品饮料"}
        hk = {"股票代码": "00700.HK", "股票简称": "腾讯"}
        value = rpc({"rows": [one, hk], "dataTotalVolume": 20, "answer": "以下为部分数据"})
        self.assertEqual(len(stock_rows(value)), 1)
        service = MarketAdapter(lambda *a, **k: value)
        analysis = {"industries": [{"id": "i1", "name": "食品饮料", "stock_expansion_allowed": True, "reason": "收入"}]}
        service.attach_stocks(analysis, {})
        self.assertEqual(analysis["stock_provider_status"]["status"], "partial")
        self.assertFalse(analysis["stock_coverage"][0]["complete"])


if __name__ == "__main__":
    unittest.main()
