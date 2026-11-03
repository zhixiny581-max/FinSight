"""iFinD-backed market routes for the feedback version (960b08e)."""

from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


SH = timezone(timedelta(hours=8))
ALL_A = {"code": "700001.TI", "name": "同花顺全A（加权）"}
DATE = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:[T\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?")
CODE_KEYS = ("ticker", "symbol", "code", "stock_code", "thscode", "证券代码", "股票代码", "代码")
NAME_KEYS = ("name", "stock_name", "security_name", "证券简称", "股票简称", "简称", "名称")
INDUSTRY_KEYS = ("所属板块", "industry", "行业", "行业简称", "所属行业", "所属同花顺行业")
DATE_KEYS = ("日期", "交易日期", "时间", "date", "time", "datetime")


def text(value):
    return str(value).strip() if isinstance(value, (str, int, float)) else ""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean(value, length=40):
    return re.sub(r"[\x00-\x1f\x7f]", " ", text(value))[:length]


def first(query, key, default=""):
    value = (query or {}).get(key, default)
    return value[0] if isinstance(value, (tuple, list)) and value else value


def pick(row, keys, loose=()):
    for key in keys:
        if key in row and text(row[key]):
            return row[key]
    for key, value in row.items():
        if text(value) and any(piece in str(key) for piece in loose):
            return value
    return None


def cutoff(news):
    raw = text(news.get("published_at") or news.get("time"))
    match = DATE.search(raw)
    invalid = {"event_published_at": raw, "requested_cutoff": "", "rule": "missing_time", "precision": "unknown"}
    if not match:
        return invalid
    try:
        y, m, d = map(int, match.groups()[:3])
        hour, minute, second = (int(part or 0) for part in match.groups()[3:])
        exact = match[4] is not None and news.get("published_precision") not in ("date", "imported")
        if exact and re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", raw, re.I):
            stamp = datetime.fromisoformat(re.sub(r"z$", "+00:00", raw, flags=re.I)).astimezone(SH)
        else:
            stamp = datetime(y, m, d, hour, minute, second, tzinfo=SH)
        after = exact and (stamp.hour * 60 + stamp.minute >= 905)
        end = stamp.date() if after else stamp.date() - timedelta(days=1)
        return {
            "event_published_at": raw, "normalized_at": stamp.astimezone(timezone.utc).isoformat(),
            "requested_cutoff": end.isoformat(), "timezone": "Asia/Shanghai",
            "rule": "after_1505_provider_completion_convention" if after else "previous_completed_daily_bar",
            "precision": "minute" if exact else "date",
        }
    except (ValueError, OverflowError):
        return {**invalid, "rule": "invalid_time"}


def number(value):
    raw = text(value).replace(",", "").replace("，", "").replace("−", "-")
    # Match a numeric value and an optional unit, not an arbitrary number embedded in text.
    match = re.fullmatch(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([万亿]?)\s*(股|手|元|点|%)?", raw)
    if not match:
        return None
    val = float(match[1]) * {"": 1, "万": 10000, "亿": 100000000}[match[2]]
    return val if math.isfinite(val) else None


def walk(value, depth=0):
    if depth > 16:
        return
    if isinstance(value, str):
        stripped = value.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if stripped.startswith(("{", "[")):
            try:
                obj = json.loads(stripped)
            except (ValueError, RecursionError):
                obj = None
            if isinstance(obj, (list, dict)):
                yield from walk(obj, depth + 1)
                return
    yield value
    if isinstance(value, (dict, list)):
        for child in value.values() if isinstance(value, dict) else value:
            yield from walk(child, depth + 1)


def records(value):
    for obj in walk(value):
        if isinstance(obj, dict):
            yield obj
        elif isinstance(obj, list) and len(obj) > 1 and isinstance(obj[0], list) and all(isinstance(h, str) for h in obj[0]):
            for row in obj[1:]:
                if isinstance(row, list):
                    yield dict(zip((h.strip() for h in obj[0]), row))
        elif isinstance(obj, str) and "|" in obj:
            headers = None
            for line in obj.replace("\\r\\n", "\n").replace("\\n", "\n").splitlines():
                if "|" not in line:
                    headers = None
                    continue
                cells = [x.strip() for x in line.strip().strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", x) for x in cells):
                    continue
                is_header = (any("收盘" in c or c in ("close", "close_price") for c in cells) and
                             any("日期" in c or "时间" in c or c in DATE_KEYS for c in cells)) or (
                    any(c in CODE_KEYS for c in cells) and any(c in NAME_KEYS for c in cells))
                if is_header:
                    headers = cells
                elif headers and len(cells) >= 2:
                    yield dict(zip(headers, cells))


def provider_issue(value):
    if not isinstance(value, dict) or value.get("ok") is False or value.get("error"):
        return "request_failed"
    result = value.get("result")
    if isinstance(result, dict) and result.get("isError"):
        return "provider_error"
    for obj in walk(value):
        if not isinstance(obj, str):
            continue
        if re.search(r"达到.*工具.*次数上限|选购/升级权益", obj):
            return "tool_limit"
        if re.search(r"无权限|没有权限|未开通|权限不足", obj):
            return "permission_denied"
        if re.search(r"请求失败|查询失败|服务异常|系统繁忙", obj):
            return "provider_error"
    return ""


def normalize_bars(value, end, close_only=False, expected_code=""):
    by_date = {}
    for row in records(value):
        returned_code = text(pick(row, CODE_KEYS)).upper().split(".")[0]
        if expected_code and returned_code and returned_code != expected_code.upper().split(".")[0]:
            continue
        raw_day = text(pick(row, DATE_KEYS, ("日期", "时间", "date", "time")))
        if re.fullmatch(r"\d{8}", raw_day):
            raw_day = f"{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:]}"
        try:
            day = date.fromisoformat(raw_day[:10]).isoformat()
        except ValueError:
            continue
        if day > end:
            continue
        o = number(pick(row, ("开盘价", "开盘", "open", "open_price"), ("开盘", "open")))
        h = number(pick(row, ("最高价", "最高", "high", "high_price"), ("最高", "high")))
        l = number(pick(row, ("最低价", "最低", "low", "low_price"), ("最低", "low")))
        c = number(pick(row, ("收盘价", "收盘", "close", "close_price", "最新价"), ("收盘", "close", "最新价")))
        raw_volume = pick(row, ("成交量", "成交量(股)", "volume", "vol"), ("成交量", "volume"))
        volume = number(raw_volume)
        if volume is not None and text(raw_volume).endswith("手"):
            volume *= 100
        change = number(pick(row, ("涨跌幅", "涨跌幅(%)", "change_pct", "pct_chg"), ("涨跌幅", "change_pct", "pct_chg")))
        if c is None or c <= 0 or (volume is not None and volume < 0):
            continue
        if close_only:
            o = h = l = c
        if any(x is None or x <= 0 for x in (o, h, l)) or l > min(o, c) or h < max(o, c):
            continue
        row_out = dict(date=day, open=o, high=h, low=l, close=c, volume=volume, change_pct=change)
        if close_only:
            row_out["close_only_benchmark"] = True
        by_date[day] = row_out
    return [by_date[k] for k in sorted(by_date)[-60:]]


def metrics(bars):
    rows = [b for b in bars if b["close"] > 0][-60:]
    if not rows:
        return {"observations": 0}
    last = rows[-1]["close"]
    high = max(b["close"] for b in rows)
    low = min(b["close"] for b in rows)

    def ret(n):
        return round((last / rows[-1-n]["close"] - 1) * 100, 2) if len(rows) > n else None

    volumes = [b.get("volume") for b in rows[-25:]]
    ratio = None
    if len(volumes) == 25 and all(v is not None and v >= 0 for v in volumes) and sum(volumes[:20]) > 0:
        ratio = round((sum(volumes[-5:]) / 5) / (sum(volumes[:20]) / 20), 2)
    return {
        "observations": len(rows), "window_start": rows[0]["date"], "window_end": rows[-1]["date"],
        "return_5d_pct": ret(5), "return_20d_pct": ret(20), "return_60d_pct": ret(59),
        "return_60d_definition": "最近60条有效日线首尾涨跌幅（59个间隔）",
        "volume_ratio_5d_to_prior20d": ratio,
        "position_in_60d_range_pct": round((last-low)/(high-low)*100, 2) if high != low else None,
        "drawdown_from_60d_high_pct": round((last/high - 1)*100, 2), "range_basis": "收盘价",
        "price_adjustment": "供应方返回口径，未提供时不得假定复权一致",
    }


def excess(a, b):
    a, b = a[-21:], b[-21:]
    if len(a) != 21 or [x["date"] for x in a] != [x["date"] for x in b]:
        return None
    return round(metrics(a)["return_20d_pct"] - metrics(b)["return_20d_pct"], 2)


def stock_rows(value):
    by_code = {}
    for row in records(value):
        code = text(pick(row, CODE_KEYS)).upper()
        name = clean(pick(row, NAME_KEYS), 60)
        if not name or not re.fullmatch(r"(?:[036]\d{5}(?:\.(?:SH|SZ))?|[489]\d{5}(?:\.BJ)?)", code):
            continue
        by_code.setdefault(code.split(".")[0], {
            "code": code, "name": name, "industry": clean(pick(row, INDUSTRY_KEYS), 70) or "行业未提供",
        })
    return list(by_code.values())


def company_key(value):
    name = re.sub(r"[\s·・]|[（(].*?[）)]", "", text(value))
    name = re.sub(r"^\*?ST", "", name, flags=re.I)
    return re.sub(r"股份有限公司$|有限责任公司$|有限公司$|股份$|[ab]$", "", name, flags=re.I).lower()


def direct_match(a, b):
    a, b = company_key(a), company_key(b)
    return bool(a and b and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a))))


def sector_match(a, b):
    a, b = [re.sub(r"行业|板块|产业", "", v) for v in (a, b)]
    if not a or not b or b == "未提供" or a in b or b in a:
        return True
    aliases = [
        ("石油天然气开采|石油开采|油气开采", "石油|天然气|油气开采"),
        ("油服工程|油气服务", "油服|油气开采|工程服务"), ("航空运输", "航空运输|机场航运"),
        ("物流运输|运输物流", "物流|运输"), ("油品运输|油运|油轮运输", "航运|港口|运输"),
        ("航运港口", "航运|港口"), ("化工", "化工|化学|石化"), ("证券", "证券|券商"),
    ]
    if any(re.search(x, a) and re.search(y, b) for x, y in aliases):
        return True
    grams = lambda s: {s[i:i+2] for i in range(len(s)-1)}
    x, y = grams(a), grams(b)
    return bool(x and y and len(x & y) / len(x) >= 0.45)


class MarketAdapter:
    def __init__(self, call, audit_dir=None):
        self.call = call
        self.audit_dir = Path(audit_dir) if audit_dir else None
        self.cache = OrderedDict()
        self.pending = {}
        self.lock = threading.Lock()

    def _request(self, server, tool, query, deadline):
        remaining = deadline - time.monotonic()
        if remaining < 1:
            raise TimeoutError("market request budget exhausted")
        return self.call(server, tool, {"query": query}, timeout=min(30, remaining))

    def _daily(self, server, tool, subject, end, deadline, close_only=False, latest=False):
        source = "iFinD " + tool
        if close_only:
            source += "（板块成分股算术平均）"
        key = (server, tool, subject, end, close_only, latest)
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < (60 if latest else 900):
                self.cache.move_to_end(key)
                return cached[1]
            event = self.pending.get(key)
            if not event:
                self.pending[key] = threading.Event()
        if event:
            event.wait(max(0, deadline - time.monotonic()))
            with self.lock:
                cached = self.cache.get(key)
            if cached and time.monotonic() - cached[0] < (60 if latest else 900):
                return cached[1]
            raise TimeoutError("coalesced market request failed")
        try:
            bars = {}
            fields = "每日交易日期、收盘价（算术平均）和成交量（合计）" if close_only else "日线交易日期、开盘价、最高价、最低价、收盘价、涨跌幅和成交量"
            compact = end.replace("-", "")
            symbol = re.match(r"^\d{6}(?:\.[A-Z]{2})?(?=\s|$)", subject, re.I)
            expected_code = symbol[0] if symbol else ""
            requests = []
            for attempt, days in enumerate((0, 105, 180)):
                start = (date.fromisoformat(end) - timedelta(days=days)).strftime("%Y%m%d")
                prefix = f"{subject}截至{compact}最近60个有效交易日的" if attempt == 0 else f"{subject}从{start}到{compact}的"
                query = prefix + fields + "，按交易日期逐日返回，只返回实际有交易的数据，不抽样或聚合"
                try:
                    raw = self._request(server, tool, query, deadline)
                    issue = provider_issue(raw)
                except Exception:
                    issue = "request_failed"
                requests.append({"query": query, "error": issue, "fetched_at": now()})
                if issue:
                    if not bars:
                        raise RuntimeError(issue)
                    break
                attempt_rows = normalize_bars(raw, end, close_only, expected_code)
                if len(attempt_rows) >= len(bars):
                    # Prefer one internally consistent upstream series; do not splice attempts
                    # whose adjustment metadata may differ.
                    bars = {bar["date"]: bar for bar in attempt_rows}
                if len(bars) >= 60:
                    break
            if latest and end not in bars and date.fromisoformat(end).weekday() < 5:
                query = f"{subject}在{compact}当天的日线交易日期、开盘价、最高价、最低价、收盘价和成交量，只返回这一天实际有交易的日线，不以前一日代替"
                try:
                    raw = self._request(server, tool, query, deadline)
                    issue = provider_issue(raw)
                    if not issue:
                        bars.update((bar["date"], bar) for bar in normalize_bars(raw, end, expected_code=expected_code) if bar["date"] == end)
                except Exception:
                    issue = "request_failed"
                requests.append({"query": query, "error": issue, "fetched_at": now()})
            rows = [bars[k] for k in sorted(bars)[-60:]]
            data = {
                "bars": rows, "requested_cutoff": end, "market_data_cutoff": rows[-1]["date"] if rows else "",
                "window_start": rows[0]["date"] if rows else "", "window_size": len(rows),
                "source": source, "fetched_at": now(), "metrics": metrics(rows),
            }
            if not rows:
                raise RuntimeError("empty_result")
            if self.audit_dir and server == "index" and tool == "index_data":
                try:
                    self.audit_dir.mkdir(parents=True, exist_ok=True)
                    # Never store raw upstream bodies or request authentication.
                    record_id = uuid.uuid4().hex
                    if sum(1 for _ in self.audit_dir.glob("market-*.json")) < 1000:
                        record = {**data, "record_id": record_id, "tool": tool, "provider_requests": requests}
                        (self.audit_dir / ("market-" + record_id + ".json")).write_text(
                            json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
                        data["source_record_id"] = record_id
                except OSError:
                    pass
            with self.lock:
                self.cache[key] = (time.monotonic(), data)
                self.cache.move_to_end(key)
                while len(self.cache) > 100:
                    self.cache.popitem(last=False)
            return data
        finally:
            with self.lock:
                self.pending.pop(key).set()

    def _all_a(self, timing, deadline, latest=False):
        day = timing["requested_cutoff"]
        if not day:
            raise ValueError("missing event date")
        today = datetime.now(SH)
        data = self._daily("index", "index_data", ALL_A["code"] + " " + ALL_A["name"],
                           min(day, today.date().isoformat()), deadline, latest=latest)
        return {
            **data, "benchmark": dict(ALL_A), "event_published_at": timing["event_published_at"],
            "cutoff_rule": timing["rule"], "analysis_mode": "market_observation" if latest else "ex_ante",
        }

    def market_context(self, news, *, timeout=32):
        try:
            return self._all_a(cutoff(news), time.monotonic() + max(0, timeout))
        except Exception:
            return None

    def market_kline(self, query, *, timeout=45):
        mode = first(query, "mode", "latest")
        published = clean(first(query, "published_at"))
        if mode not in ("latest", "pre_event"):
            return 400, {"ok": False, "error": "行情视图不正确"}
        today = datetime.now(SH)
        timing = (cutoff({"published_at": published}) if mode == "pre_event" else
                  {"event_published_at": published, "requested_cutoff": today.date().isoformat(), "rule": "latest_shanghai_date"})
        if not timing["requested_cutoff"]:
            return 400, {"ok": False, "error": "缺少有效新闻发布时间"}
        try:
            data = self._all_a(timing, time.monotonic() + max(0, timeout), latest=mode == "latest")
        except Exception:
            return 200, {"ok": False, "reason": "request_failed", "error": "全A行情读取失败，请点击刷新重试。"}
        data["view_mode"] = mode
        data["current_day_bar"] = "not_returned"
        if mode == "latest" and data["market_data_cutoff"] == today.date().isoformat():
            data["current_day_bar"] = "in_progress" if today.hour*60 + today.minute < 905 else "daily_returned"
        return 200, {"ok": True, "item": data}

    def stock_kline(self, query, *, timeout=55):
        code = re.sub(r"[^0-9A-Za-z.]", "", clean(first(query, "code"), 16))
        name = clean(first(query, "name"))
        industry = clean(first(query, "industry"))
        direction = clean(first(query, "expected_direction"), 12) or "不确定"
        timing = cutoff({"published_at": clean(first(query, "published_at"))})
        if not code and not name:
            return 400, {"ok": False, "error": "缺少股票代码或名称"}
        if not timing["requested_cutoff"]:
            return 400, {"ok": False, "error": "缺少有效新闻发布时间，不能建立事前行情截止点"}
        end = min(timing["requested_cutoff"], datetime.now(SH).date().isoformat())
        deadline = time.monotonic() + max(0, timeout)
        try:
            data = self._daily("stock", "get_stock_performance", " ".join(x for x in (code, name) if x), end,
                               min(deadline, time.monotonic() + timeout * 0.55))
        except Exception:
            return 200, {"ok": False, "mode": "unavailable", "reason": "request_failed", "item": {
                "code": code, "name": name, "status": "unavailable", "bars": [],
                "source": "iFinD get_stock_performance", "fetched_at": now(),
                "reason": "iFinD 未返回可用事前日线，可能与权限、时间或字段有关。",
            }}
        bench = sector = None
        try:
            bench = self._all_a(timing, min(deadline, time.monotonic() + max(0, deadline-time.monotonic()) * (0.6 if industry else 1)))
        except Exception:
            pass
        if industry:
            try:
                sector = {"name": industry, **self._daily("index", "sector_data", industry + "板块", end, deadline, True)}
            except Exception:
                pass
        mb, sb = (bench or {}).get("bars", []), (sector or {}).get("bars", [])
        pricing = {
            "state": "无法判断", "confidence": 0, "expected_direction": direction,
            "basis": ["价格和成交量仅描述事前市场状态，不能据此确认这条事件已被提前定价。"],
            "metrics": {"stock": metrics(data["bars"]), "market": metrics(mb), "industry": metrics(sb),
                        "excess_return_20d_pct": excess(data["bars"], mb), "excess_industry_return_20d_pct": excess(data["bars"], sb)},
            "caveat": "事件定价还需当时公开的预期与事件关联证据。",
        }
        return 200, {"ok": True, "mode": "live", "item": {
            **data, "code": code, "name": name, "status": "available", "unit": "元", "as_of": data["market_data_cutoff"],
            "event_published_at": timing["event_published_at"], "cutoff_rule": timing["rule"], "analysis_mode": "ex_ante",
            "reason": "来自 iFinD 股票日频行情，仅展示新闻时点以前最近60个有效交易日。",
            "market_benchmark": bench, "industry_benchmark": sector, "pricing_assessment": pricing,
        }}

    def _stocks(self, tool, query, deadline):
        try:
            raw = self._request("stock", tool, query, deadline)
            issue = provider_issue(raw)
            return ([], raw, issue) if issue else (stock_rows(raw), raw, "")
        except Exception:
            return [], {}, "request_failed"

    def related_stocks(self, query, *, timeout=30):
        title = clean(first(query, "title"), 100)
        if not title:
            return 400, {"ok": False, "error": "缺少新闻标题"}
        rows, _, issue = self._stocks("search_stocks", "请列出与以下新闻主题直接相关的A股上市公司，返回股票代码、简称和行业，不给投资建议。新闻主题：" + title,
                                      time.monotonic() + max(0, timeout))
        return 200, {"ok": not bool(issue), "mode": "unavailable" if issue else "live", "items": rows, "reason": issue}

    def attach_stocks(self, analysis, news, *, timeout=48):
        deadline = time.monotonic() + max(0, timeout)
        verdict = analysis.get("verdict") or {}
        impacts = {}
        for impact in analysis.get("direct_impacts") or []:
            if isinstance(impact, dict) and impact.get("entity_type") in ("上市公司", "非上市公司", "其他") and len(company_key(impact.get("name"))) >= 2:
                impacts.setdefault(company_key(impact["name"]), impact)
        direct_coverage = []
        sector_coverage = []
        found = {}
        issues = []
        if impacts:
            names = "、".join(clean(i["name"], 60) for i in impacts.values())
            suffix = f"逐一核验以下事件直接参与方哪些是A股上市公司，只返回精确对应证券代码、简称和所属同花顺行业，不扩展同行或概念股：{names}"
            rows, _, issue = self._stocks("search_stocks", suffix, deadline)
            tool = "search_stocks"
            if issue or not rows:
                rows, _, issue = self._stocks("get_stock_info", suffix, deadline)
                tool = "get_stock_info"
            source = f"iFinD {tool}（事件直接参与方核验）"
            if issue:
                issues.append(issue)
            exact_by_impact = [[s for s in rows if direct_match(impact["name"], s["name"])] for impact in impacts.values()]
            exact_codes = {s["code"] for group in exact_by_impact for s in group}
            for impact, matched in zip(impacts.values(), exact_by_impact):
                relation = "same_entity"
                if not matched:
                    brands = set(re.findall("[a-z0-9]{3,}", company_key(impact["name"])))
                    parents = [s for s in rows if s["code"] not in exact_codes and brands.intersection(re.findall("[a-z0-9]{3,}", company_key(s["name"])))]
                    if len(parents) == 1:
                        matched, relation = parents, "listed_parent"
                direct_coverage.append({
                    "direct_impact_id": impact.get("id"), "entity_name": impact["name"], "relation": impact.get("relation", ""),
                    "returned": len(matched), "matched": bool(matched), "match_type": relation if matched else "unmatched",
                    "listed_security": f"{matched[0]['name']} {matched[0]['code']}" if matched else "", "source": source, "error": issue,
                })
                if matched:
                    s = matched[0]
                    parent = relation == "listed_parent"
                    impact.update(ticker="" if parent else s["code"], entity_type="非上市公司" if parent else "上市公司",
                                  listed_status="未独立上市" if parent else "已上市", stock_lookup_allowed=True,
                                  listed_proxy_name=s["name"] if parent else "", listed_proxy_ticker=s["code"] if parent else "",
                                  listed_proxy_relation="上市母公司" if parent else "", listing_verification_source=source,
                                  listing_verified_at=now())
                for s in matched:
                    found.setdefault(s["code"].split(".")[0], self._candidate(s, verdict, source, direct=impact, relation=relation))
        sectors = {}
        for industry in analysis.get("industries") or []:
            if not isinstance(industry, dict) or industry.get("stock_expansion_allowed") is not True:
                continue
            basis = " ".join(text(industry.get(k)) for k in ("stock_expansion_basis", "reason", "role"))
            if not re.search(r"收入|成本|供给|供应|需求|供需|订单|产能|资本开支|监管|价格|库存|销量|出口|进口", basis):
                continue
            name = clean(industry.get("name"), 60)
            parts = [p.strip() for p in re.split(r"[/、,，和及]", name) if len(p.strip()) >= 2 and not re.search(r"A股|市场|新股|上市|资本", p)]
            for part in parts or ([name] if name else []):
                sectors.setdefault(part, industry)
        for i, (name, industry) in enumerate(sectors.items()):
            source = "iFinD search_stocks"
            if i >= 6 or deadline - time.monotonic() < 1:
                rows, raw, issue = [], {}, "request_budget"
            else:
                rows, raw, issue = self._stocks("search_stocks", f"请逐只返回{name}行业的全部A股上市公司，字段仅股票代码、股票简称和所属同花顺行业，不设其他筛选条件，不给投资建议", deadline)
                rows = [s for s in rows if sector_match(name, s["industry"])]
                if not rows:
                    alias = "油气开采及服务" if re.search(r"石油开采|油气开采|石油天然气开采", name) else "航运" if re.search(r"油品运输|油运|油轮运输", name) else "基础化工" if name == "化工" else name
                    rows, raw, issue = self._stocks("get_stock_info", f"{alias}板块成分证券的证券代码、证券简称和所属同花顺行业，逐只列出", deadline)
                    rows = [s for s in rows if sector_match(name, s["industry"])]
                    source = "iFinD get_stock_info（板块成分证券）"
                    if not rows and not issue:
                        issue = "empty_result"
            if issue:
                issues.append(issue)
            total = selected = None
            truncated = False
            for obj in walk(raw):
                if isinstance(obj, dict):
                    total = total or number(obj.get("dataTotalVolume"))
                    selected = selected or number(obj.get("selectedSecuritiesCount"))
                elif isinstance(obj, str):
                    count = re.search(r"为您找到\s*(\d+)\s*条数据", obj)
                    total = total or (int(count[1]) if count else None)
                    truncated |= bool(re.search(r"数据被截断|仅返回部分|以下为部分数据", obj))
            sector_coverage.append({
                "industry_id": industry.get("id"), "industry_name": name, "returned": len(rows),
                "provider_selected": selected, "provider_total": total, "source": source, "error": issue,
                "complete": bool(not issue and not truncated and (total or selected) and len(rows) >= (total or selected)),
            })
            for s in rows:
                stock_key = s["code"].split(".")[0]
                if stock_key in found:
                    seen = found[stock_key].setdefault("also_industry_ids", [])
                    if industry.get("id") and industry["id"] not in seen:
                        seen.append(industry["id"])
                    continue
                found[stock_key] = self._candidate(s, industry, source, sector=industry)
        stocks = list(found.values())
        partial = any(not v["matched"] for v in direct_coverage) or any(not v["complete"] for v in sector_coverage)
        if not (impacts or sectors):
            status, reason, message = "not_requested", "no_stock_expansion", "本次无满足经营变量门槛的板块或待核验公司。"
        elif not stocks:
            status, reason = ("unavailable", issues[0]) if issues else ("empty", "no_matching_records")
            message = "iFinD 本次未返回可解析的公司资料，不等同于没有受影响公司。"
        else:
            status, reason = ("partial", issues[0] if issues else "partial_match") if partial or issues else ("available", "")
            message = f"iFinD 返回 {len(stocks)} 家相关公司；{'部分核验未完成；' if status == 'partial' else ''}公司方向为板块或事件参考。"
        analysis.update(
            candidate_stocks=stocks, screened_stocks=stocks, stocks=stocks, kline=[],
            stock_coverage=sector_coverage, direct_stock_coverage=direct_coverage,
            stock_provider_status={"status": status, "reason_code": reason, "message": message,
                                   "source": "iFinD", "checked_at": now()},
            stock_selection_summary={"direct_count": sum(s["impact_type"] == "direct" for s in stocks),
                                     "industry_count": sum(s["impact_type"] == "industry" for s in stocks)},
            analysis_depth="sector_and_related_companies",
            company_listing={"direction_basis": "sector_or_event_reference", "company_analysis": False,
                             "note": "仅列相关公司及板块关联，方向和强度不是逐家公司研究结论。"},
        )
        return stocks

    @staticmethod
    def _candidate(stock, reference, source, direct=None, relation="", sector=None):
        scope = "event_reference" if direct else "industry_reference"
        label = "事件方向参考" if direct else "板块方向参考"
        sector_name = (sector or {}).get("name") or stock["industry"]
        message = "新闻中直接涉及的公司。表中方向仅参考事件整体判断。" if direct else f"iFinD 返回的{sector_name}板块相关公司。表中方向与强度引用该板块判断。"
        if direct and relation == "listed_parent":
            message = f"{stock['name']}为与{direct['name']}匹配的上市母公司候选；方向仅为事件参考。"
        return {
            **stock, "ticker": stock["code"], "impact_type": "direct" if direct else "industry",
            "impact_type_label": "事件相关" if direct else "板块相关", "direction_scope": scope,
            "impact_level_scope": scope, "reference_label": label, "industry_id": (sector or {}).get("id", ""),
            "industry_name": sector_name, "chain_stage": (sector or {}).get("chain_stage", 0),
            "stage": (direct or {}).get("relation") or sector_name, "direct_impact_id": (direct or {}).get("id", ""),
            "direct_entity_name": (direct or {}).get("name", ""), "direct_listing_relation": relation,
            "relation": (direct or {}).get("relation", ""), "data_source": source,
            "direction": reference.get("direction", "不确定"), "impact_level": reference.get("impact_level", "待评估"),
            "confidence": reference.get("confidence", 0), "role": message, "reason": message,
            "selection_basis": (sector or {}).get("stock_expansion_basis") or message,
            "conditions": reference.get("conditions") or [], "risks": [],
            "evidence_source_ids": (direct or {}).get("evidence_source_ids") or [],
        }
