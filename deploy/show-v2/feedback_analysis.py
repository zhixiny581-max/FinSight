"""Python port of FinSight's feedback analysis workflow at 960b08e.

Provider callbacks own HTTP, authentication and response limits. They receive
a timeout in seconds; late callback results never become model evidence.
"""

import hashlib
import json
import math
import os
import queue
import re
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4


COMMIT = "960b08eaf48e030244b6ba8f56aa3fee1ffd0676"
SHANGHAI = timezone(timedelta(hours=8))
DEFAULTS = dict(rounds=2, tools=6, tool_seconds=15, evidence_seconds=45,
                model_seconds=45, total_seconds=240, models=6)
TOOL_KEYS = {
    "ifind_news_search": ("query", "time_start", "time_end"),
    "public_web_search": ("query",),
    "read_webpage": ("url",),
}
_RUNNERS = threading.BoundedSemaphore(16)
_COMMENTARY = re.compile(r"(^|\.)(toutiao\.com|xueqiu\.com|guba\.eastmoney\.com|guba\.10jqka\.com\.cn|baijiahao\.baidu\.com|zhihu\.com|weibo\.com)$")
_MEDIA = re.compile(r"(^|\.)(tmtpost\.com|stcn\.com|cnstock\.com|yicai\.com|cls\.cn|xinhuanet\.com|cctv\.com|people\.com\.cn|10jqka\.com\.cn|eastmoney\.com|sina\.com\.cn)$")
_CIRCULAR = re.compile(r"候选.{0,12}为空|未提供.{0,6}候选|尚无.{0,6}候选|候选股票池为空")
_REAL = re.compile(r"企业成本|投入成本|运输成本|能源成本|原料成本|收入|订单|生产|消费|投资|就业|进出口|CPI|PPI|实际物价|终端价格")
_POLICY = re.compile(r"通胀预期|增长预期|政策预期|政策反应|利率路径|加息预期|降息预期|货币政策|财政政策|金融条件|信用条件|流动性预期")
_MARKET = re.compile(r"风险偏好|估值|折现率|宽基|股市|A股|港股|美股|市场风格|资产价格|成长股|价值股|大类资产")


class AnalysisError(Exception):
    """Stable public error code without provider payloads or credentials."""


def _dict(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _text(value):
    return str(value).strip() if value is not None else ""


def _hash(value):
    data = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8", errors="replace")).hexdigest()


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value, *, date_end=False):
    """Unknown news time is Shanghai midnight; date-only evidence ends that day."""
    raw = _text(value)
    match = re.fullmatch(
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?"
        r"(?:[T\s]+(\d{1,2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?"
        r"\s*([zZ]|[+-]\d\d:?\d\d)?)?", raw)
    if not match:
        return None
    y, m, d, hour, minute, second, frac, zone = match.groups()
    try:
        offset = SHANGHAI
        if zone:
            if zone.upper() == "Z":
                offset = timezone.utc
            else:
                z = zone[1:].replace(":", "")
                delta = timedelta(hours=int(z[:2]), minutes=int(z[2:]))
                offset = timezone(delta if zone[0] == "+" else -delta)
        if hour is None and date_end:
            hour, minute, second = "23", "59", "59"
        return datetime(int(y), int(m), int(d), int(hour or 0), int(minute or 0),
                        int(second or 0), int((frac or "").ljust(6, "0")), tzinfo=offset)
    except ValueError:
        return None


def eligible(item, as_of, tool, *, now=None):
    if as_of is None:
        return False, "as_of_unknown"
    published = timestamp(item.get("published_at") or item.get("time"), date_end=True)
    updated = timestamp(item.get("updated_at"), date_end=True)
    if published is None:
        return False, "publication_unknown"
    if published > as_of:
        return False, "after_as_of"
    if updated and updated > as_of:
        return False, "updated_after_as_of"
    if tool == "read_webpage" and (now or datetime.now(timezone.utc)) - as_of > timedelta(days=1) \
            and item.get("historical_snapshot") is not True:
        return False, "current_page_historical_content_unverified"
    return True, "published_before_as_of"


def _safe_url(value):
    value = _text(value)
    try:
        url = urlsplit(value)
        if url.scheme in ("http", "https") and url.hostname and not url.username and not url.password:
            return value
    except ValueError:
        pass
    return ""


def _source_policy(item, url):
    host = urlsplit(url).hostname or ""
    authority = item.get("source_authority") or item.get("authority_level") or ""
    if _COMMENTARY.search(host):
        return False, "context_only", "commentary_or_aggregator_unverified"
    if authority == "other" and not _MEDIA.search(host):
        return False, "context_only", "publisher_not_verified"
    return (True, "primary_material" if authority in ("official", "company", "exchange")
            else "reported_material", authority or "provided_material")


def _source(item, source_id, method, content, available, reason):
    url = _safe_url(item.get("url") or item.get("link"))
    fact, use, reliability = (_source_policy(item, url) if method != "input"
                              else (True, "provided_material", "provided_material"))
    return {
        "id": source_id, "method": method, "url": url,
        "title": _text(item.get("title"))[:500],
        "publisher": _text(item.get("publisher") or item.get("source"))[:120],
        "published_at": _text(item.get("published_at") or item.get("time"))[:80],
        "updated_at": _text(item.get("updated_at"))[:80],
        "retrieved_at": _iso_now(), "eligible": available, "eligibility_reason": reason,
        "authority_level": _text(item.get("source_authority") or item.get("authority_level"))[:50],
        "fact_eligible": fact, "evidence_use": use, "reliability_reason": reliability,
        "evidence_level": _text(item.get("evidence_level")) or
                          ("page_body" if method == "read_webpage" else "news_excerpt"),
        "content": content[:18000 if method == "input" else 12000],
        "content_hash": _hash(content), "truncation": len(content) > (18000 if method == "input" else 12000),
    }


def _public_source(source):
    return {key: value for key, value in source.items() if key != "content"}


def _news_sources(news):
    rows = []
    for value in _list(news.get("sources"))[:16]:
        if isinstance(value, (tuple, list)):
            value = dict(zip(("title", "publisher", "published_at", "url"), value))
        if isinstance(value, dict):
            rows.append(value)
    if not rows:
        rows = [news]
    authority = {"official": 5, "exchange": 4, "company": 4, "major_media": 3}
    rows.sort(key=lambda s: (s.get("is_primary") is True,
                            authority.get(_text(s.get("authority_level")), 1)), reverse=True)
    result = []
    used = set()
    for index, row in enumerate(rows, start=1):
        source_id = _text(row.get("id"))
        if not re.fullmatch(r"news-[A-Za-z0-9_-]{1,50}", source_id) or source_id in used:
            source_id = f"news-{index}"
        if source_id in used:
            source_id = f"news-{index}-input"
        used.add(source_id)
        body = _text(row.get("content") or row.get("full_text") or
                     ((news.get("full_text") or news.get("content") or news.get("summary")) if index == 1 else ""))
        result.append(_source(row, source_id, "input", body, True, "provided_material"))
    return result


def _units(source):
    return [{"id": f"{source['id']}:p{i + 1}", "text": source["content"][start:start + 600]}
            for i, start in enumerate(range(0, len(source["content"]), 480))]


def _source_input(sources, limit=24000):
    output = []
    for source in sources:
        if limit <= 0:
            break
        if not source["eligible"]:
            continue
        selected = []
        budget = min(6000, limit)
        if source["fact_eligible"]:
            for unit in _units(source):
                length = len(unit["text"])
                if length <= budget:
                    selected.append(unit)
                    budget -= length
                    limit -= length
        output.append({**_public_source(source), "evidence_units": selected,
                       "content": "\n".join(u["text"] for u in selected)})
    return output


def _submit(callback, args, timeout):
    if timeout <= 0 or not _RUNNERS.acquire(blocking=False):
        raise AnalysisError("ANALYSIS_BUDGET_EXHAUSTED")
    result = queue.Queue(maxsize=1)
    deadline = time.monotonic() + timeout

    def run():
        try:
            value = callback(*args, timeout)
            result.put((True, value, time.monotonic()))
        except Exception as error:
            result.put((False, error, time.monotonic()))
        finally:
            _RUNNERS.release()

    try:
        threading.Thread(target=run, daemon=True).start()
    except RuntimeError:
        _RUNNERS.release()
        raise
    return result, deadline


def _collect(task):
    result, deadline = task
    try:
        ok, value, finished = result.get(timeout=max(0, deadline - time.monotonic()))
    except queue.Empty:
        raise TimeoutError("callback exceeded its budget") from None
    if finished > deadline:
        raise TimeoutError("callback exceeded its budget")
    if not ok:
        raise value
    return value


def _direction_warnings(analysis, news):
    verdict = analysis["verdict"]
    conclusion = _text(verdict.get("conclusion"))
    macro = analysis["macro_analysis"]
    if len(conclusion) < 20 or "market_pricing" not in macro:
        raise AnalysisError("AI_INVALID_ANALYSIS")
    warnings = []
    if not 80 <= len(conclusion) <= 220:
        warnings.append("推演结论长度未达到建议范围")
    if not verdict.get("conditions"):
        warnings.append("未单列成立条件")
    if not verdict.get("counter_scenarios"):
        warnings.append("未单列反向情景")
    if len(_list(verdict.get("validation_metrics"))) < 2:
        warnings.append("验证指标少于两项")

    def bigrams(value):
        chars = "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", _text(value).lower()))
        return {chars[i:i + 2] for i in range(len(chars) - 1)}

    a, b = bigrams(conclusion), bigrams(news.get("summary"))
    overlap = len(a & b) / min(len(a), len(b)) if a and b else 0
    verdict["source_summary_overlap"] = round(overlap, 2)
    if overlap > 0.82:
        warnings.append("推演结论与新闻摘要重合度偏高")
    if macro.get("applicable"):
        chain = _dict(macro.get("macro_chain"))
        nodes = _list(chain.get("nodes"))
        types = {n.get("type") for n in nodes}
        if len(nodes) < 2 or not chain.get("edges") or not chain.get("validation_indicators"):
            warnings.append("宏观传导链不完整")
        if "direct_shock" not in types:
            warnings.append("宏观传导缺少直接冲击节点")
        description = " ".join([conclusion, _text(macro.get("summary"))] + [
            _text(n.get("label") or n.get("name")) + " " + _text(n.get("mechanism"))
            for n in nodes + _list(macro.get("channels"))
        ])
        if _REAL.search(description) and "real_economy" not in types:
            warnings.append("宏观传导缺少实体经济节点")
        if _POLICY.search(description) and "policy_expectation" not in types:
            warnings.append("宏观传导缺少政策或预期节点")
        if (macro.get("market_impacts") or _MARKET.search(description)) and "market" not in types:
            warnings.append("宏观传导缺少市场影响节点")
    for asset in _list(macro.get("market_impacts")):
        if re.search(r"黄金|金价|贵金属", _text(asset.get("asset"))) and (
            not asset.get("positive_drivers") or not asset.get("negative_drivers")
            or asset.get("direction") not in ("多空交织", "不确定")
        ):
            warnings.append("黄金影响未完整呈现双向驱动")
            break
    if not (analysis.get("direct_impacts") or macro.get("applicable")
            or analysis.get("industries") and _dict(analysis.get("industry_chain")).get("edges")):
        raise AnalysisError("AI_INVALID_ANALYSIS")
    analysis["validation_warnings"] = warnings
    return analysis


def _clean_graph(analysis, raw):
    """Discard edges and placeholder nodes fabricated by the older normalizer."""
    chain = analysis["macro_analysis"]["macro_chain"]
    original = _dict(_dict(raw.get("macro_analysis")).get("macro_chain"))
    explicit_nodes = [node for node in _list(original.get("nodes"))[:14]
                      if isinstance(node, dict) and node.get("type") != "event"]
    if not explicit_nodes:
        chain["nodes"] = [node for node in chain["nodes"] if node["id"] == "macro-event"]
    ids = {node["id"] for node in chain["nodes"]}
    explicit_edges = {(_text(edge.get("from")), _text(edge.get("to")))
                      for edge in _list(original.get("edges"))[:24] if isinstance(edge, dict)}
    chain["edges"] = [edge for edge in chain["edges"]
                      if (edge["from"], edge["to"]) in explicit_edges
                      and edge["from"] in ids and edge["to"] in ids]
    chain["validation_indicators"] = [item for item in chain["validation_indicators"]
                                      if item["node_id"] in ids]
    for edge in analysis.get("impact_chain", []):
        edge["evidence_source_ids"] = []
    direct_raw = _list(raw.get("direct_impacts") or raw.get("direct_entities") or raw.get("entity_impacts"))
    for direct in analysis.get("direct_impacts", []):
        match = next((r for r in direct_raw if isinstance(r, dict) and
                      (_text(r.get("id")) == direct["id"] or
                       _text(r.get("name") or r.get("entity") or r.get("company")) == direct["name"])), {})
        direct["evidence_source_ids"] = [_text(x) for x in _list(match.get("evidence_source_ids"))][:4]
    return analysis


def _project(normalize, raw, news):
    if not isinstance(raw, dict) or not _text(_dict(raw.get("verdict")).get("conclusion")) \
            or not isinstance(raw.get("industries"), list):
        raise AnalysisError("AI_INVALID_ANALYSIS")
    try:
        return _direction_warnings(_clean_graph(normalize(raw, news), raw), news)
    except (KeyError, IndexError, TypeError, ValueError, OverflowError) as error:
        raise AnalysisError("AI_INVALID_ANALYSIS") from error


def _withdraw(raw, claim):
    parts = re.sub(r"^analysis\.", "", _text(claim.get("field_path"))).split(".")
    if parts[0] not in ("verdict", "macro_analysis", "direct_impacts", "industries") or len(parts) > 10:
        return False
    target = raw
    for part in parts[:-1]:
        if isinstance(target, dict):
            target = target.get(part)
        elif isinstance(target, list) and re.fullmatch(r"\d{1,4}", part) and int(part) < len(target):
            target = target[int(part)]
        else:
            return False
    key = parts[-1]
    if isinstance(target, list):
        if not re.fullmatch(r"\d{1,4}", key) or int(key) >= len(target):
            return False
        key = int(key)
    elif not isinstance(target, dict) or key not in target:
        return False
    value = target[key]
    excerpt = _text(claim.get("text"))
    if not isinstance(value, str) or not excerpt or excerpt not in value:
        return False
    target[key] = value.replace(excerpt, "现有资料未能确认该对象的这项事实")
    return True


def _write_audit(path, payload):
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def finalize_candidates(analysis, audit_dir):
    """Record stock attachment without a further model call or logging payloads."""
    metadata = _dict(analysis.get("analysis_metadata"))
    if not metadata:
        return
    metadata["candidate_count"] = len(_list(analysis.get("stocks")))
    if audit_dir is None:
        return
    run_id = str(UUID(metadata["run_id"]))
    path = Path(audit_dir) / f"{run_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["candidate_count"] = metadata["candidate_count"]
        data["analysis_hash"] = _hash(analysis)
        _write_audit(path, data)
    except (OSError, ValueError):
        metadata["audit_status"] = "unavailable"


def analyze(news, market_context, *, model_call, tool_call, tool_availability,
            audit_dir, normalize, prompt_path=None, model="", budget=None, deadline=None):
    """Return a normalized V2 analysis before candidate attachment.

    `model_call(messages, timeout)` returns model text or a parsed object.
    `tool_call(name, arguments, timeout)` returns an object with an items list.
    Optional deadline is a monotonic timestamp shared with the HTTP handler.
    """
    limits = {**DEFAULTS, **(budget or {})}
    started = time.monotonic()
    limit_at = min(started + limits["total_seconds"], deadline or math.inf)
    run_id = str(uuid4())
    prompt_file = Path(prompt_path) if prompt_path else Path(__file__).with_name("feedback.txt")
    prompt = prompt_file.read_bytes().decode("utf-8")
    prompt_hash = _hash(prompt)
    as_of = timestamp(news.get("published_at") or news.get("time"))
    as_of_text = as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if as_of else ""
    sources = _news_sources(news)
    sent_units = {}
    issues = []
    model_trace = []
    trace = []
    seen_requests = set()
    round_count = 0
    tool_elapsed = 0.0
    repaired_json = False
    availability = {name: bool(tool_availability.get(name)) for name in TOOL_KEYS}

    def remaining():
        return max(0, limit_at - time.monotonic())

    def call_model(stage, previous=None):
        nonlocal repaired_json
        if len(model_trace) >= limits["models"] or remaining() < 0.05:
            raise AnalysisError("ANALYSIS_BUDGET_EXHAUSTED")
        consumed = _source_input(sources)
        for source in consumed:
            for unit in source["evidence_units"]:
                sent_units[(source["id"], unit["id"])] = unit["text"]
        data = {
            "stage": stage, "output_required": ["verdict", "industries", "claims", "semantic_review"],
            "news": {**{key: news.get(key) for key in ("title", "summary", "source", "url")},
                     "full_text": _text(news.get("full_text") or news.get("content"))[:18000],
                     "published_at": news.get("published_at") or news.get("time"),
                     "market_context": market_context},
            "as_of": as_of_text, "sources": consumed, "previous": previous,
            "excluded_sources": [{"id": s["id"], "reason": s["eligibility_reason"]} for s in sources
                                 if not s["eligible"]],
            "analysis_depth": "sector_and_related_companies",
            "candidate_lookup_state": "not_queried_yet",
            "stock_expansion_contract": "stock_expansion_allowed仅决定是否查询行业候选，不代表确认公司受益。初稿没有候选是因为尚未查询，禁止用候选池为空或公司暴露未核实否定行业查询。无经营变量变化的宏观或公司事件仍不扩展。",
            "review_instructions": "只分析事件及板块的大致方向、机制、条件、反向路径。不要逐家公司分析业务、财务或方向，不为候选名单查询公司资料。公司名单由后台iFinD取得。板块判断不能写成对全部成分公司的独立结论。",
            "tool_availability": availability,
            "tool_results": [{"request": t["request"], "status": t["status"], "error": t.get("error"),
                              "source_ids": t.get("source_ids", [])} for t in trace],
            "remaining": {"rounds": limits["rounds"] - round_count,
                          "tool_calls": limits["tools"] - len(trace),
                          "model_calls": limits["models"] - len(model_trace) - 1,
                          "time_ms": round(remaining() * 1000)},
        }
        record = {"stage": stage, "input_hash": _hash(data), "started_at": _iso_now()}
        model_trace.append(record)
        value = None
        try:
            messages = [{"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(data, ensure_ascii=False, allow_nan=False)}]
            value = _collect(_submit(model_call, (messages,), min(limits["model_seconds"], remaining())))
            record["output_hash"] = _hash(value)
            if isinstance(value, str):
                value = json.loads(re.sub(r"\s*```$", "", re.sub(r"^```(?:json)?\s*", "", value.strip())))
            return value
        except (json.JSONDecodeError, SyntaxError):
            record["error"] = "invalid_json"
            if not repaired_json and len(model_trace) < limits["models"] and remaining() >= 0.05:
                repaired_json = True
                issues.append({"stage": stage, "reason": "bounded_json_repair"})
                return call_model(stage + "_json_repair", {
                    "invalid_json": _text(value)[:20000],
                    "repair_instruction": "上次JSON语法错误。仅修正JSON语法，保留内容和完整结构，禁止未转义引号。"})
            raise AnalysisError("AI_INVALID_ANALYSIS") from None
        except TimeoutError:
            record["error"] = "timeout"
            raise AnalysisError("AI_TIMEOUT") from None
        except Exception:
            record["error"] = "provider_error"
            raise AnalysisError("AI_PROVIDER_ERROR") from None
        finally:
            record["finished_at"] = _iso_now()

    def accept_sources(record, result):
        items = _list(_dict(result).get("items"))[:8]
        record["status"] = "ok" if items else "empty"
        record["source_ids"] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            content = _text(item.get("content") or item.get("full_text") or item.get("summary"))
            available, reason = eligible(item, as_of, record["request"]["tool"])
            source = _source(item, f"evidence-{len(sources) + 1}", record["request"]["tool"],
                             content, available, reason)
            duplicate = next((s for s in sources if
                (s["url"], s["title"], s["content_hash"], s["eligible"], s["fact_eligible"]) ==
                (source["url"], source["title"], source["content_hash"], source["eligible"], source["fact_eligible"])), None)
            if duplicate is None:
                sources.append(source)
            record["source_ids"].append((duplicate or source)["id"])

    def retrieve(raw):
        nonlocal round_count, tool_elapsed
        requests = _list(raw.get("tool_requests"))
        if not requests or round_count >= limits["rounds"] or len(trace) >= limits["tools"] \
                or tool_elapsed >= limits["evidence_seconds"] or remaining() < 0.05 \
                or os.getenv("ANALYSIS_RETRIEVAL", "on").lower() == "off":
            return False
        round_count += 1
        beginning = time.monotonic()
        index = 0
        while index < len(requests) and len(trace) < limits["tools"]:
            pending = []
            for _ in range(2):
                timeout = min(limits["tool_seconds"], remaining(),
                              limits["evidence_seconds"] - tool_elapsed - (time.monotonic() - beginning))
                if timeout <= 0 or index >= len(requests) or len(trace) >= limits["tools"]:
                    break
                req = _dict(requests[index])
                index += 1
                name = _text(req.get("tool"))
                args = {k: _text(_dict(req.get("arguments")).get(k))[:(2000 if k == "url" else 500)]
                        for k in TOOL_KEYS.get(name, ()) if k in _dict(req.get("arguments"))}
                scope = _text(req.get("scope"))
                request = {"tool": name, "scope": scope, "arguments": args}
                record = {"round": round_count, "request": request, "started_at": _iso_now()}
                trace.append(record)
                signature = _hash([name, args])
                duplicate = signature in seen_requests
                seen_requests.add(signature)
                if scope not in ("event", "sector"):
                    record["status"] = "out_of_scope"
                elif duplicate:
                    record["status"] = "duplicate"
                elif not availability.get(name):
                    record["status"] = "unavailable"
                elif not (args.get("query") or args.get("url")):
                    record["status"] = "failed"
                    record["error"] = "invalid_arguments"
                else:
                    try:
                        pending.append((record, _submit(tool_call, (name, args), timeout)))
                    except Exception:
                        record["status"] = "failed"
                        record["error"] = "provider_busy"
                if record.get("status"):
                    record["finished_at"] = _iso_now()
            for record, task in pending:
                try:
                    accept_sources(record, _collect(task))
                except Exception as error:
                    record["status"] = "failed"
                    record["error"] = "timeout" if isinstance(error, TimeoutError) else "provider_error"
                record["finished_at"] = _iso_now()
            if remaining() <= 0 or tool_elapsed + time.monotonic() - beginning >= limits["evidence_seconds"]:
                break
        tool_elapsed += time.monotonic() - beginning
        return True

    def inspect_and_withdraw(raw):
        available = {s["id"] for s in sources if s["eligible"] and s["fact_eligible"]}
        pricing_supported = False
        claims = _list(raw.get("claims"))
        for entry in claims:
            claim = _dict(entry)
            good = False
            evidence = _list(claim.get("evidence"))
            for link in evidence:
                cite = _dict(link)
                source_id = _text(cite.get("source_id"))
                excerpt = _text(cite.get("excerpt"))
                unit_id = _text(cite.get("unit_id"))
                unit = sent_units.get((source_id, unit_id))
                valid = source_id in available and (
                    bool(unit) and (not excerpt or excerpt in unit) if unit_id else
                    bool(excerpt) and any(sid == source_id and excerpt in body
                                          for (sid, _), body in sent_units.items()))
                if not valid:
                    issues.append({"claim": claim.get("id"), "field": claim.get("field_path"),
                                   "reason": "citation_not_supported", "source_id": source_id})
                good |= valid
                if valid and excerpt and "market_pricing" in _text(claim.get("field_path")):
                    pricing_supported = True
            if claim.get("kind") == "fact" and not good:
                if not evidence:
                    issues.append({"claim": claim.get("id"), "reason": "fact_without_evidence"})
                if _withdraw(raw, claim):
                    issues.append({"claim": claim.get("id"), "reason": "unsupported_fact_withdrawn"})
        return available, pricing_supported

    audit_path = Path(audit_dir) / f"{run_id}.json" if audit_dir is not None else None

    def audit(analysis=None, status="failed"):
        # No raw provider responses, query arguments, article bodies, URLs or
        # model payloads. Fingerprints permit correlating offline fixtures.
        _write_audit(audit_path, {
            "run_id": run_id, "version": "feedback", "code_commit": COMMIT,
            "prompt_hash": prompt_hash, "input_hash": _hash(news),
            "market_context_hash": _hash(market_context), "as_of": as_of_text,
            "completion_status": status, "finished_at": _iso_now(),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "model_trace": model_trace,
            "trace": [{**{k: v for k, v in t.items() if k != "request"},
                       "tool": t["request"]["tool"] if t["request"]["tool"] in TOOL_KEYS else "unknown",
                       "request_hash": _hash(t["request"])} for t in trace],
            "sources": [{k: s[k] for k in ("id", "method", "eligible", "eligibility_reason",
                                          "fact_eligible", "content_hash")} for s in sources],
            "sent_units": [{"source_id": sid, "unit_id": uid, "hash": _hash(body)}
                           for (sid, uid), body in sent_units.items()],
            "issue_reasons": [issue["reason"] for issue in issues],
            "analysis_hash": _hash(analysis) if analysis is not None else None,
            "candidate_count": len(_list(_dict(analysis).get("stocks"))),
        })

    try:
        raw = None
        try:
            raw = call_model("initial")
            _project(normalize, raw, news)
        except AnalysisError as error:
            if str(error) != "AI_INVALID_ANALYSIS":
                raise
            issues.append({"stage": "initial", "reason": "bounded_structure_repair"})
            raw = call_model("initial_repair", {"error": str(error), "previous": raw})
            _project(normalize, raw, news)
        while len(model_trace) < limits["models"] - 1 and retrieve(raw):
            try:
                revised = call_model("revise_after_evidence", raw)
                _project(normalize, revised, news)
                raw = revised
            except AnalysisError as error:
                issues.append({"stage": "sector_evidence", "reason": str(error)})
                break
        circular = [_dict(i).get("id") for i in raw["industries"] if
                    _dict(i).get("stock_expansion_allowed") is False
                    and _CIRCULAR.search(_text(_dict(i).get("stock_expansion_basis")))]
        if circular and len(model_trace) < limits["models"] - 1:
            issues.append({"stage": "industry_query_gate", "reason": "circular_candidate_requirement",
                           "industry_ids": circular})
            try:
                corrected = call_model("initial_industry_query_review", {
                    "analysis": raw, "correction": "尚未查询候选，因此候选为空不是拒绝查询的理由。仅按行业经营变量及适用一组公司判断是否查询，保留具体因果条件，不必确认个股受益。返回完整分析结构。"})
                _project(normalize, corrected, news)
                raw = corrected
            except AnalysisError:
                issues.append({"stage": "industry_query_gate", "reason": "invalid_correction_kept_previous"})
        raw = deepcopy(raw)
        available, pricing_supported = inspect_and_withdraw(raw)
        analysis = _project(normalize, raw, news)
        for impact in analysis.get("direct_impacts", []):
            impact["evidence_source_ids"] = [x for x in impact["evidence_source_ids"] if x in available]
        analysis["sources"] = [_public_source(s) for s in sources if s["eligible"]]
        analysis["news"]["sources"] = analysis["sources"]
        pricing = analysis["macro_analysis"]["market_pricing"]
        if pricing.get("applicable") and not pricing_supported:
            pricing.update(state="无法判断", confidence=0,
                           basis=["现有资料未提供这条事件的事前预期与定价关联证据。"])
        analysis["analysis_version"] = "feedback"
        analysis["analysis_depth"] = "sector_and_related_companies"
        analysis["evidence_review"] = {"issues": issues, "claim_count": len(_list(raw.get("claims")))}
        status = "partial" if issues or any(t["status"] in ("failed", "unavailable") for t in trace) else "complete"
        analysis["analysis_metadata"] = {
            "version": "feedback", "analysis_depth": analysis["analysis_depth"],
            "company_analysis": False, "run_id": run_id, "model": model,
            "prompt_hash": prompt_hash, "model_calls": len(model_trace), "tool_calls": len(trace),
            "retrieval_rounds": round_count, "elapsed_ms": round((time.monotonic() - started) * 1000),
            "candidate_count": 0, "sector_count": len(analysis["industries"]),
            "evidence_snapshot_hash": _hash(sources), "completion_status": status,
        }
        try:
            audit(analysis, status)
        except OSError:
            analysis["analysis_metadata"]["audit_status"] = "unavailable"
        return analysis
    except Exception:
        try:
            audit()
        except OSError:
            pass
        raise
