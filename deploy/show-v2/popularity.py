# -*- coding: utf-8 -*-
"""东方财富 A 股人气榜代理。

数据来源
  榜单：https://guba.eastmoney.com/rank/ 所使用的人气榜接口
        POST https://emappdata.eastmoney.com/stockrank/getAllCurrentList
        只返回证券代码(sc)与排名(rk)，不含名称与行情。
  行情：https://push2.eastmoney.com/api/qt/ulist.np/get
        按代码批量补齐名称、最新价、涨跌幅。

为什么必须走后端
  两个接口都不返回 Access-Control-Allow-Origin，浏览器从本站域名直接 fetch 会被
  CORS 拦截；POST 接口还需要 JSON 头。因此由本站服务端代理，前端只调用 /api/rank。

边界
  - 只做只读 GET，不缓存到磁盘，不写入任何用户数据。
  - 失败时返回结构化错误，前端明确显示"未获取到"，不伪造排名。
  - 网络不可用时区分 timeout / http / parse 三类原因。
"""

import json
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from threading import Lock
from time import monotonic, time
from urllib.parse import urlencode, urlsplit

from market_adapter import CODE_KEYS, NAME_KEYS, clean, number, pick, provider_issue, records
from news_provider import IFindError

SHANGHAI = timezone(timedelta(hours=8))

RANK_URL = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
QUOTE_URLS = (
    "https://push2.eastmoney.com/api/qt/ulist.np/get",
    "https://82.push2.eastmoney.com/api/qt/ulist.np/get",
    "https://push2his.eastmoney.com/api/qt/ulist.np/get",
)
RANK_PAYLOAD = {
    "appId": "appId01",
    "globalId": "786e4c21-70dc-435a-93bb-38",
    "marketType": "",
    "pageNo": 1,
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
SOURCE_LABEL = "东方财富 A 股人气榜"


class RankError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _fetch(request, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def _rank_raw(limit, timeout):
    payload = dict(RANK_PAYLOAD, pageSize=limit)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        RANK_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": UA,
                 "Accept": "application/json"},
    )
    try:
        raw = _fetch(request, timeout)
    except urllib.error.HTTPError as error:
        raise RankError("RANK_HTTP", str(error.code)) from None
    except (socket.timeout, TimeoutError):
        raise RankError("RANK_TIMEOUT") from None
    except urllib.error.URLError as error:
        reason = getattr(error, "reason", "")
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise RankError("RANK_TIMEOUT") from None
        raise RankError("RANK_UNREACHABLE", type(reason).__name__ or "URLError") from None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise RankError("RANK_PARSE") from None
    rows = data.get("data")
    if data.get("status") not in (0, None) or not isinstance(rows, list):
        raise RankError("RANK_REJECTED", str(data.get("message") or "")[:80])
    return rows


def _secid(code):
    """SH600519 -> 1.600519 ; SZ000001 -> 0.000001"""
    prefix, digits = code[:2].upper(), code[2:]
    return ("1." if prefix == "SH" else "0.") + digits


def _quotes(codes, timeout):
    if not codes:
        return {}
    params = urlencode({
        "fltt": 2, "np": 3, "invt": 2,
        "ut": "a79f54e3d4c8d44e494efb8f748db291",
        "secids": ",".join(_secid(code) for code in codes),
        "fields": "f12,f13,f14,f2,f3",
        "cb": "finSightQuote", "_": int(time() * 1000),
    }, safe=",")
    for url in QUOTE_URLS:
        req = urllib.request.Request(
            url + "?" + params, method="GET",
            headers={"User-Agent": UA, "Referer": "https://guba.eastmoney.com/",
                     "Accept": "*/*"},
        )
        host = urlsplit(url).hostname
        try:
            raw = _fetch(req, timeout / len(QUOTE_URLS)).decode("utf-8")
            wrapped = re.fullmatch(r"\s*finSightQuote\((.*)\)\s*;?\s*", raw, re.S)
            payload = json.loads(wrapped[1] if wrapped else raw)
            diff = (payload.get("data") or {}).get("diff")
        except (OSError, ValueError, AttributeError) as error:
            detail = getattr(error, "code", type(getattr(error, "reason", error)).__name__)
            print("FINSIGHT_RANK_QUOTE_UNAVAILABLE", host, detail, flush=True)
            continue
        if isinstance(diff, (list, dict)) and diff:
            break
        print("FINSIGHT_RANK_QUOTE_EMPTY", host, flush=True)
    else:
        return {}
    if isinstance(diff, dict):
        diff = list(diff.values())
    out = {}
    for row in diff:
        if not isinstance(row, dict):
            continue
        code = str(row.get("f12") or "")
        if not code:
            continue
        out[code] = {
            "name": str(row.get("f14") or ""),
            "price": row.get("f2"),
            "changePct": row.get("f3"),
        }
    return out


_QUOTE_LOCK = Lock()
_QUOTE_CACHE = {}
_QUOTE_TTL = 120
_QUOTE_RETRY = 15
_QUOTE_RETENTION = 3600


def _ifind_quotes(codes, quote_call, timeout):
    symbols = sorted({
        f"{code[2:]}.{code[:2]}" for code in codes
        if re.fullmatch(r"(?:SH|SZ|BJ)\d{6}", code)
    })
    if not symbols:
        return {}
    with _QUOTE_LOCK:
        now = monotonic()
        for code in list(_QUOTE_CACHE):
            if _QUOTE_CACHE[code][1] <= now:
                del _QUOTE_CACHE[code]
        missing = [code for code in symbols if code not in _QUOTE_CACHE or _QUOTE_CACHE[code][0] <= now]
        if missing:
            deadline = now + timeout
            quotes = {}
            retry = _QUOTE_RETRY
            for start in range(0, len(missing), 10):
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                batch = missing[start:start + 10]
                try:
                    data = quote_call("stock", "stock_highfreq_quotes", {
                        "symbols": ",".join(batch),
                        "indicators": "最新价,涨跌幅",
                        "data_mode": "real_time",
                    }, timeout=remaining)
                except IFindError as error:
                    issue = str(error)
                else:
                    issue = provider_issue(data)
                if issue:
                    print("FINSIGHT_RANK_IFIND_UNAVAILABLE", issue, flush=True)
                    if issue in {"tool_limit", "permission_denied", "IFIND_NOT_CONFIGURED",
                                 "IFIND_HTTP_401", "IFIND_HTTP_403", "IFIND_HTTP_429"}:
                        retry = _QUOTE_TTL
                        break
                    continue
                for row in records(data):
                    symbol = clean(pick(row, CODE_KEYS), 16).upper()
                    if symbol not in batch:
                        continue
                    name = clean(pick(row, NAME_KEYS), 40)
                    price = number(pick(row, ("最新价", "latest", "price")))
                    change = number(pick(row, ("涨跌幅", "涨跌幅(%)", "changeRatio", "changePct")))
                    if name or price is not None or change is not None:
                        quotes[symbol] = {
                            "name": name, "price": price, "changePct": change,
                            "asOf": clean(pick(row, ("time", "时间", "datetime")), 32),
                        }
            now = monotonic()
            for code in missing:
                quote = quotes.get(code)
                if quote and quote["price"] is not None and quote["changePct"] is not None:
                    _QUOTE_CACHE[code] = (now + _QUOTE_TTL, now + _QUOTE_RETENTION, quote)
                    continue
                previous = _QUOTE_CACHE.get(code)
                if previous and previous[1] > now and previous[2].get("price") is not None:
                    _QUOTE_CACHE[code] = (now + retry, previous[1], {**previous[2], "stale": True})
                else:
                    _QUOTE_CACHE[code] = (now + retry, now + retry, quote or {})
        return {code: _QUOTE_CACHE[code][2] for code in symbols}


def fetch_rank(limit=20, timeout=8.0, quote_call=None):
    """返回 {ok, items, updatedAt, source, ...}；失败抛 RankError。"""
    limit = max(1, min(int(limit or 20), 50))
    rows = _rank_raw(limit, timeout)
    codes = [str(r.get("sc") or "") for r in rows if isinstance(r, dict) and r.get("sc")]
    quotes = _ifind_quotes(codes, quote_call, timeout) if quote_call else _quotes(codes, timeout)

    items = []
    for row in rows:
        code = str(row.get("sc") or "")
        if not code or len(code) < 4:
            continue
        digits = code[2:]
        market = code[:2].upper()
        quote_key = f"{digits}.{market}" if quote_call else digits
        quote = quotes.get(quote_key) or {}
        price = quote.get("price")
        change = quote.get("changePct")
        items.append({
            "rank": row.get("rk"),
            "code": digits,
            "market": market,
            "name": quote.get("name") or "",
            "price": price if isinstance(price, (int, float)) else None,
            "quoteAsOf": quote.get("asOf") or None,
            "quoteStale": bool(quote.get("stale")),
            "changePct": change if isinstance(change, (int, float)) else None,
            # rc: 排名变化（正=上升），hisRc: 历史首次上榜时的名次，仅作参考
            "rankChange": row.get("rc") if isinstance(row.get("rc"), int) else None,
        })
    if not items:
        raise RankError("RANK_EMPTY")

    now = datetime.now(SHANGHAI)
    return {
        "ok": True,
        "source": SOURCE_LABEL,
        "quoteSource": "同花顺 iFinD" if quote_call else "东方财富",
        "sourceUrl": "https://guba.eastmoney.com/rank/",
        "updatedAt": now.isoformat(timespec="seconds"),
        "updatedAtText": now.strftime("%Y-%m-%d %H:%M:%S"),
        "limit": limit,
        "items": items,
        "note": "排名来自东方财富人气榜，按股吧关注度排序，不代表涨跌或投资建议。",
    }
