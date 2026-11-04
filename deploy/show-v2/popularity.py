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
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

SHANGHAI = timezone(timedelta(hours=8))

RANK_URL = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
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
    params = "fltt=2&secids=%s&fields=f12,f13,f14,f2,f3" % ",".join(_secid(c) for c in codes)
    request = urllib.request.Request(
        QUOTE_URL + "?" + params, method="GET",
        headers={"User-Agent": UA, "Referer": "https://quote.eastmoney.com/",
                 "Accept": "application/json"},
    )
    try:
        raw = _fetch(request, timeout)
    except Exception:  # 行情只是补充信息，失败不影响榜单本身
        return {}
    try:
        payload = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return {}
    diff = ((payload.get("data") or {}).get("diff")) or []
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


def fetch_rank(limit=20, timeout=8.0):
    """返回 {ok, items, updatedAt, source, ...}；失败抛 RankError。"""
    limit = max(1, min(int(limit or 20), 50))
    rows = _rank_raw(limit, timeout)
    codes = [str(r.get("sc") or "") for r in rows if isinstance(r, dict) and r.get("sc")]
    quotes = _quotes(codes, timeout)

    items = []
    for row in rows:
        code = str(row.get("sc") or "")
        if not code or len(code) < 4:
            continue
        digits = code[2:]
        quote = quotes.get(digits) or {}
        price = quote.get("price")
        change = quote.get("changePct")
        items.append({
            "rank": row.get("rk"),
            "code": digits,
            "market": "SH" if code[:2].upper() == "SH" else "SZ",
            "name": quote.get("name") or "",
            "price": price if isinstance(price, (int, float)) else None,
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
        "sourceUrl": "https://guba.eastmoney.com/rank/",
        "updatedAt": now.isoformat(timespec="seconds"),
        "updatedAtText": now.strftime("%Y-%m-%d %H:%M:%S"),
        "limit": limit,
        "items": items,
        "note": "排名来自东方财富人气榜，按股吧关注度排序，不代表涨跌或投资建议。",
    }
