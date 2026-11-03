"""Synthetic regression tests; no real credentials or network calls."""

import json
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from base import normalize_analysis
from feedback_analysis import AnalysisError, analyze, eligible, finalize_candidates, timestamp


NEWS = {
    "title": "合成测试：板块供给变化",
    "summary": "开发合成情景，不是真实财经事件。",
    "full_text": "测试行业供给变化；尚未披露具体公司业务数据。",
    "published_at": "2026-10-20T12:00:00+08:00",
}
DRAFT = {
    "event": {"type": "供给变化"},
    "verdict": {
        "headline": "交付条件影响板块供给",
        "conclusion": "若供给变化持续，相关板块的交付与成本将受到影响，具体强弱取决于持续时间和替代能力。",
        "direction": "多空交织", "confidence": 60, "conditions": ["供给变化持续"],
    },
    "industries": [{
        "id": "up", "name": "合成供给板块", "direction": "利好", "impact_level": "中",
        "confidence": 65, "role": "收入与订单变量", "reason": "供给条件变化",
        "stock_expansion_allowed": True, "stock_expansion_basis": "订单变化",
    }],
    "direct_impacts": [], "macro_analysis": {"applicable": False}, "claims": [],
}


def tool_request(tool="ifind_news_search", scope="sector", **args):
    return {"tool": tool, "scope": scope, "arguments": args or {"query": "合成供给"}}


class FeedbackAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temp.cleanup)
        self.audit = Path(self.temp.name)
        self.stages = []
        on = patch.dict("os.environ", {"ANALYSIS_RETRIEVAL": "on"})
        on.start()
        self.addCleanup(on.stop)

    def run_analysis(self, callback=lambda _: deepcopy(DRAFT),
                     tool=lambda *_: {"items": []}, **kwargs):
        def model(messages, timeout):
            self.assertGreater(timeout, 0)
            self.assertEqual(messages[0]["content"],
                             Path(__file__).with_name("feedback.txt").read_bytes().decode("utf-8"))
            payload = json.loads(messages[1]["content"])
            self.stages.append(payload["stage"])
            self.assertEqual(payload["candidate_lookup_state"], "not_queried_yet")
            self.assertNotIn("stock_candidates", payload)
            return callback(payload)

        return analyze(deepcopy(NEWS), {"analysis_mode": "ex_ante"}, model_call=model,
                       tool_call=tool, tool_availability={
                           "ifind_news_search": True, "read_webpage": True,
                       }, audit_dir=self.audit, normalize=normalize_analysis, **kwargs)

    def test_two_rounds_actually_revise_and_attach_without_extra_model_call(self):
        queries = []

        def tool(name, args, timeout):
            queries.append(name)
            self.assertGreater(timeout, 0)
            return {"items": [{
                "title": name, "url": "https://example.com/evidence",
                "published_at": "2026-10-19", "historical_snapshot": True,
                "content": "合成行业供给变化资料。",
            }]}

        def model(data):
            result = deepcopy(DRAFT)
            if data["stage"] == "initial":
                result["tool_requests"] = [tool_request()]
            elif len(data["tool_results"]) == 1:
                self.assertTrue(data["sources"][1]["evidence_units"])
                result["tool_requests"] = [tool_request("read_webpage", url="https://example.com/evidence")]
            else:
                self.assertEqual(data["news"]["market_context"]["analysis_mode"], "ex_ante")
                self.assertEqual(len(data["sources"]), 3)
                result["industries"][0]["direction"] = "多空交织"
            return result

        analysis = self.run_analysis(model, tool)
        self.assertEqual(queries, ["ifind_news_search", "read_webpage"])
        self.assertEqual(analysis["industries"][0]["direction"], "多空交织")
        self.assertEqual(analysis["analysis_metadata"]["retrieval_rounds"], 2)
        analysis["stocks"] = [{"code": "TEST"}]
        finalize_candidates(analysis, self.audit)
        self.assertEqual(self.stages, ["initial", "revise_after_evidence", "revise_after_evidence"])
        self.assertEqual(analysis["analysis_metadata"]["candidate_count"], 1)
        audit = json.loads(next(self.audit.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(audit["candidate_count"], 1)
        self.assertEqual(len(audit["trace"]), 2)
        self.assertNotIn("合成行业供给变化资料", json.dumps(audit, ensure_ascii=False))

    def test_bad_initial_and_bad_revision_do_not_replace_valid_result(self):
        def model(data):
            result = deepcopy(DRAFT)
            if data["stage"] in ("initial", "revise_after_evidence"):
                result["industries"] = []
            else:
                result["tool_requests"] = [tool_request()]
            return result
        analysis = self.run_analysis(model)
        self.assertEqual(self.stages, ["initial", "initial_repair", "revise_after_evidence"])
        self.assertEqual(len(analysis["industries"]), 1)
        self.assertEqual(analysis["analysis_metadata"]["completion_status"], "partial")

    def test_one_json_repair(self):
        analysis = self.run_analysis(
            lambda data: '{invalid' if data["stage"] == "initial" else deepcopy(DRAFT))
        self.assertEqual(self.stages, ["initial", "initial_json_repair"])
        self.assertEqual(analysis["analysis_metadata"]["model_calls"], 2)

    def test_circular_candidate_review_precedes_stock_query(self):
        def model(data):
            result = deepcopy(DRAFT)
            if data["stage"] == "initial":
                result["industries"][0].update(stock_expansion_allowed=False,
                                              stock_expansion_basis="候选股票池为空，暂不展开")
            return result
        analysis = self.run_analysis(model)
        self.assertEqual(self.stages, ["initial", "initial_industry_query_review"])
        self.assertTrue(analysis["industries"][0]["stock_expansion_allowed"])

    def test_budget_duplicate_unavailable_out_of_scope_and_error_feedback(self):
        calls = []

        def tool(name, args, timeout):
            calls.append(name)
            raise ValueError("synthetic-provider-secret")

        def model(data):
            result = deepcopy(DRAFT)
            if data["stage"] == "initial":
                result["tool_requests"] = [
                    tool_request(scope="company"), tool_request(query="甲"),
                    tool_request(query="甲"), tool_request("public_web_search", query="乙"),
                ] + [tool_request(query=str(i)) for i in range(15)]
            else:
                statuses = {item["status"] for item in data["tool_results"]}
                self.assertEqual(statuses, {"out_of_scope", "failed", "duplicate", "unavailable"})
                self.assertNotIn("synthetic-provider-secret", json.dumps(data))
                result["tool_requests"] = [tool_request(query="不可进入第三轮")]
            return result
        analysis = self.run_analysis(model, tool)
        self.assertEqual(len(calls), 3)
        self.assertEqual(analysis["analysis_metadata"]["tool_calls"], 6)
        self.assertEqual(len(self.stages), 2)
        self.assertNotIn("synthetic-provider-secret", next(self.audit.glob("*.json")).read_text(encoding="utf-8"))

    def test_late_evidence_is_ignored_even_with_two_parallel_tools(self):
        def tool(name, args, timeout):
            time.sleep(timeout + 0.08)
            return {"items": [{"title": "迟到资料", "published_at": "2026-10-19",
                               "content": "不得进入证据"}]}

        def model(data):
            result = deepcopy(DRAFT)
            if data["stage"] == "initial":
                result["tool_requests"] = [tool_request(query="甲"), tool_request(query="乙")]
            else:
                self.assertEqual([t["error"] for t in data["tool_results"]], ["timeout", "timeout"])
                self.assertEqual(len(data["sources"]), 1)
            return result
        result = self.run_analysis(model, tool, budget={"tool_seconds": 0.02})
        self.assertEqual(len(result["sources"]), 1)

    def test_future_and_context_only_sources_not_used_as_factual_evidence(self):
        def tool(*_):
            return {"items": [
                {"title": "事后新闻", "published_at": "2026-10-21", "content": "禁止事后证据"},
                {"title": "评论", "url": "https://www.toutiao.com/a", "published_at": "2026-10-19",
                 "content": "未经核实的说法"},
            ]}

        def model(data):
            result = deepcopy(DRAFT)
            if data["stage"] == "initial":
                result["tool_requests"] = [tool_request()]
                return result
            self.assertEqual(data["excluded_sources"], [{"id": "evidence-2", "reason": "after_as_of"}])
            self.assertEqual(data["sources"][1]["evidence_use"], "context_only")
            self.assertEqual(data["sources"][1]["content"], "")
            result["verdict"]["conclusion"] += "事后实际利润翻倍。"
            result["claims"] = [{"id": "c1", "kind": "fact", "field_path": "verdict.conclusion",
                                 "text": "事后实际利润翻倍", "evidence": [
                                     {"source_id": "evidence-2", "unit_id": "evidence-2:p1"}]}]
            return result
        analysis = self.run_analysis(model, tool)
        self.assertNotIn("利润翻倍", analysis["verdict"]["conclusion"])
        self.assertIn("现有资料未能确认", analysis["verdict"]["conclusion"])
        self.assertEqual({i["reason"] for i in analysis["evidence_review"]["issues"]},
                         {"citation_not_supported", "unsupported_fact_withdrawn"})

    def test_supported_unit_remains_and_implicit_market_pricing_downgrades(self):
        def model(data):
            result = deepcopy(DRAFT)
            result["verdict"]["conclusion"] += "测试行业供给变化。"
            result["claims"] = [{"id": "c1", "kind": "fact", "field_path": "verdict.conclusion",
                                 "text": "测试行业供给变化", "evidence": [
                                     {"source_id": "news-1", "unit_id": "news-1:p1"}]}]
            result["macro_analysis"] = {
                "applicable": True,
                "macro_chain": {"nodes": [{"id": "shock", "type": "direct_shock", "label": "供给冲击"}],
                                "edges": []},
                "market_pricing": {"state": "已充分定价", "confidence": 90},
            }
            return result
        analysis = self.run_analysis(model)
        self.assertIn("测试行业供给变化", analysis["verdict"]["conclusion"])
        self.assertEqual(analysis["evidence_review"]["issues"], [])
        self.assertEqual(analysis["macro_analysis"]["market_pricing"]["state"], "无法判断")
        self.assertEqual(analysis["macro_analysis"]["macro_chain"]["edges"], [])
        self.assertIn("宏观传导链不完整", analysis["validation_warnings"])

    def test_date_only_unknown_or_updated_evidence(self):
        as_of = timestamp("2025-01-02T04:00:00Z")
        self.assertEqual(timestamp("2025-01-02 12:00"), as_of)
        self.assertEqual(eligible({"published_at": "2025-01-02"}, as_of, "ifind_news_search"),
                         (False, "after_as_of"))
        self.assertEqual(eligible({"published_at": "2025-01-01", "updated_at": "2025-01-03"},
                                  as_of, "read_webpage"), (False, "updated_after_as_of"))
        self.assertEqual(eligible({"published_at": "2025-01-01"}, as_of, "read_webpage"),
                         (False, "current_page_historical_content_unverified"))
        self.assertEqual(eligible({"published_at": "2025-01-01"}, None, "ifind_news_search"),
                         (False, "as_of_unknown"))

    def test_irrecoverable_failure_audited_without_provider_secret(self):
        def fail(_):
            raise ValueError("synthetic-provider-secret")
        with self.assertRaisesRegex(AnalysisError, "AI_PROVIDER_ERROR"):
            self.run_analysis(fail)
        self.assertNotIn("synthetic-provider-secret", next(self.audit.glob("*.json")).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
