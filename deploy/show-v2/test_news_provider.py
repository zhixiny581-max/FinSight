"""Offline fixtures for the feedback news port. No keys or network access."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

import news_provider as news


def test_data():
    # Keep atomic cache renames inside the writable workspace in local Windows checks.
    return tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)


class Response(io.BytesIO):
    def __init__(self, body=b"", headers=None):
        super().__init__(body)
        self.headers = headers or {}


class FakeMCP:
    def __init__(self):
        self.requests = []
        self.initialize_count = 0
        self.stale = True

    def open(self, request, timeout):
        body = json.loads(request.data)
        self.requests.append((request.full_url, request.headers, body, timeout))
        method = body["method"]
        if method == "initialize":
            self.initialize_count += 1
            return Response(json.dumps({"jsonrpc": "2.0", "id": body["id"],
                "result": {"protocolVersion": "2024-11-05"}}).encode(), {
                    "Mcp-Session-Id": "session-" + str(self.initialize_count),
                    "Content-Type": "application/json",
            })
        if method == "notifications/initialized":
            return Response()
        if self.stale:
            self.stale = False
            raise HTTPError(request.full_url, 404, "old session", {}, io.BytesIO())
        reply = {"jsonrpc": "2.0", "id": body["id"], "result": {"content": [{"text": "OK"}]}}
        return Response(("data: " + json.dumps(reply) + "\r\n\r\n").encode(),
                        {"Content-Type": "text/event-stream"})


class NewsTests(unittest.TestCase):
    def setUp(self):
        self.day = news.recent_dates()[0]
        self.calls = []
        self.models = []

    def ifind(self, server, tool, args, timeout):
        self.calls.append((server, tool, args, timeout))
        day = args["time_start"]
        rows = [
            {"标题": "能源主管部门公布新的原材料供需措施", "发布时间": day, "来源": "新华社",
             "正文": "主管部门公布原材料供需措施，具体执行需关注后续落实。", "原文链接": "https://news.example/item?utm_source=test"},
            {"标题": "能源主管部门公布新的原材料供需措施", "发布时间": day, "来源": "新华社",
             "正文": "重复记录。", "原文链接": "https://news.example/item"},
            {"标题": "开户推广扫码领券", "发布时间": day, "来源": "其他",
             "正文": "这是一份广告。", "原文链接": "https://news.example/ad"},
        ]
        result = {"code": 1, "data": json.dumps({"records": rows}, ensure_ascii=False)}
        return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"text": json.dumps(result, ensure_ascii=False)}]}}

    def model(self, messages, timeout):
        inputs = json.loads(messages[-1]["content"].split("\n", 1)[1])
        self.models.append((inputs, timeout))
        return json.dumps({"items": [{
            "id": item["id"], "summary": item["raw_summary"], "content_type": "事实新闻",
            "quality_score": 85, "a_share_relevance": 3, "factuality": 5, "materiality": 4,
            "category": "行业级", "reject_reason": "", "core_event": item["title"],
            "event_date": item["published_at"], "subjects": ["能源主管部门"], "impact_targets": ["原材料"],
        } for item in inputs]}, ensure_ascii=False)

    def test_mcp_json_sse_expiry_and_allowlist(self):
        client = news.IFindClient("fixture-auth")
        fake = FakeMCP()
        client._opener = fake
        result = client.call("stock", "get_stock_performance", {"query": "fixture"}, timeout=2)
        self.assertEqual(result["result"]["content"][0]["text"], "OK")
        self.assertEqual(fake.initialize_count, 2)
        self.assertTrue(all(url.startswith(news.ENDPOINT_ROOT) and 0 < t <= 2
                            for url, _, _, t in fake.requests))
        self.assertEqual(fake.requests[-1][1]["Mcp-session-id"], "session-2")
        with self.assertRaisesRegex(news.IFindError, "IFIND_TOOL_NOT_ALLOWED"):
            client.call("news", "unknown", {})

    def test_live_progressive_dedup_filter_and_cache(self):
        with test_data() as data:
            provider = news.NewsProvider(self.ifind, self.model, data)
            live = provider.fetch_news({"date": [self.day]})
            self.assertEqual(live["mode"], "live")
            self.assertEqual(live["date_range"]["dates"], [self.day])
            self.assertEqual(len(self.calls), 12)
            self.assertEqual(live["summary_stats"]["international_fixed_query_count"], 6)
            self.assertEqual(live["summary_stats"]["candidates"], 2)
            self.assertEqual(live["summary_stats"]["quality_rejected"], 1)
            self.assertEqual(len(live["items"]), 1)
            article = live["items"][0]
            self.assertEqual(article["published_precision"], "date")
            self.assertEqual(article["url"], "https://news.example/item")
            self.assertEqual(article["category"], "行业级")
            self.assertTrue(article["importance_breakdown"])
            self.assertEqual(len(self.models), 1)
            cached = provider.fetch_news({"date": self.day})
            self.assertEqual(cached["mode"], "cache")
            self.assertEqual(cached["retrieved_at"], live["retrieved_at"])
            self.assertEqual(len(self.calls), 12)
            refresh = provider.fetch_news({"date": self.day, "refresh_feed": "1"})
            self.assertEqual(refresh["mode"], "live")
            self.assertEqual(refresh["summary_stats"]["cache_hits"], 2)
            self.assertEqual(len(self.models), 1)

    def test_failed_provider_and_no_cache_not_live(self):
        def reject(*args, **kwargs):
            raise news.IFindError("IFIND_HTTP_403")
        with test_data() as data:
            provider = news.NewsProvider(reject, self.model, data)
            outcome = provider.fetch_news({"date": self.day})
            self.assertEqual(outcome["mode"], "mock")
            self.assertFalse(outcome["ok"])
            self.assertEqual(outcome["reason"], "ifind_http_403")
            self.assertFalse(self.models)

    def test_provider_failure_uses_previous_snapshot(self):
        def reject(*args, **kwargs):
            raise news.IFindError("IFIND_HTTP_429")
        with test_data() as data:
            provider = news.NewsProvider(self.ifind, self.model, data)
            self.assertEqual(provider.fetch_news({"date": self.day})["mode"], "live")
            provider.ifind_call = reject
            outcome = provider.fetch_news({"date": self.day, "refresh_feed": "1"})
            self.assertEqual(outcome["mode"], "cache")
            self.assertEqual(outcome["fallback_reason"], "ifind_http_429")

    def test_no_summary_never_leaks_unscreened_provider_records(self):
        with test_data() as data:
            provider = news.NewsProvider(self.ifind, None, data)
            outcome = provider.fetch_news({"date": self.day})
            self.assertFalse(outcome["ok"])
            self.assertEqual(outcome["items"], [])
            self.assertEqual(outcome["reason"], "not_configured")
            invalid = provider.fetch_news({"date": "2000-01-01"})
            self.assertEqual(invalid["http_status"], 400)

    def test_shanghai_date_rollover_without_inventing_time(self):
        self.assertEqual(news.normalize_published_at("2026-11-01T16:30:00Z"), "2026-11-02 00:30")
        self.assertEqual(news.normalize_published_at("2026年11月02日"), "2026-11-02")
        self.assertEqual(news.normalize_published_at("2026-11-31"), "")
        self.assertEqual(news.normalize_published_at("2026-11-02 25:15"), "")


if __name__ == "__main__":
    unittest.main()
