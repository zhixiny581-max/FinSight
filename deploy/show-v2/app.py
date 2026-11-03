"""Python deployment of FinSight feedback; source baseline 960b08e."""

import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import base
from feedback_analysis import analyze, finalize_candidates
from market_adapter import MarketAdapter
from news_provider import IFindClient, NewsProvider, normalize_news_response

ROOT = Path(__file__).resolve().parent
PORT = int(os.getenv("PORT", "8000"))
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
AUDIT_DIR = DATA_DIR / "feedback-audit"
BASELINE = "960b08e"
IFIND_AUTH = (os.getenv("IFIND_MCP_AUTHORIZATION") or "").strip()
IFIND = IFindClient(IFIND_AUTH)
MARKET = MarketAdapter(IFIND.call, audit_dir=AUDIT_DIR)
ANALYSIS_SLOTS = threading.BoundedSemaphore(1)
UPSTREAM_SLOTS = threading.BoundedSemaphore(4)
SSL = ssl.create_default_context()
URL_OPENER = build_opener(ProxyHandler({}), base._NoRedirectHandler())


def no_redirect_open(request, timeout=20):
    return URL_OPENER.open(request, timeout=timeout)


# Only fixed-host vendor requests use urllib. Untrusted news URLs use the
# DNS-pinned fetch below, which validates every redirect independently.
base._open_url = no_redirect_open


def model_call(messages, timeout):
    return base.deepseek_chat(messages, max_tokens=8000, temperature=0.15, timeout=timeout)


NEWS = NewsProvider(IFIND.call, model_call, DATA_DIR)


def public_ip(address):
    ip = ipaddress.ip_address(address)
    if ip.version == 6:
        if ip.ipv4_mapped:
            return public_ip(str(ip.ipv4_mapped))
        if ip.sixtofour or ip.teredo:
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def fetch_page(url, timeout):
    deadline = time.monotonic() + min(20, float(timeout))
    current = str(url or "").strip()
    for hop in range(5):
        if len(current) > 2048 or re.search(r"[\x00-\x20\x7f]", current):
            raise base.ApiError("IMPORT_INVALID_URL")
        try:
            parsed = urlsplit(current)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            host = (parsed.hostname or "").encode("idna").decode("ascii")
        except (ValueError, UnicodeError):
            raise base.ApiError("IMPORT_INVALID_URL")
        if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None or parsed.password is not None:
            raise base.ApiError("IMPORT_INVALID_URL")
        if port != (443 if parsed.scheme == "https" else 80):
            raise base.ApiError("IMPORT_URL_BLOCKED")
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addresses or any(not public_ip(a[4][0]) for a in addresses):
            raise base.ApiError("IMPORT_URL_BLOCKED")
        address = addresses[0]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        conn = (http.client.HTTPSConnection(host, port, timeout=remaining, context=SSL)
                if parsed.scheme == "https" else http.client.HTTPConnection(host, port, timeout=remaining))

        def connect_pinned(_addr, timeout, source_address=None):
            family, socktype, proto, _, sockaddr = address
            sock = socket.socket(family, socktype, proto)
            try:
                sock.settimeout(timeout)
                sock.connect(sockaddr)
                return sock
            except BaseException:
                sock.close()
                raise

        # Preserve the original hostname for the HTTP Host and TLS certificate,
        # while connecting to exactly the public address validated above.
        conn._create_connection = connect_pinned
        try:
            target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
            conn.request("GET", target, headers={
                "User-Agent": "FinSightEvidence/1.0",
                "Accept": "text/html,text/plain,application/xhtml+xml",
                "Accept-Encoding": "identity", "Connection": "close",
            })
            with conn.getresponse() as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location or hop == 4:
                        raise base.ApiError("IMPORT_FETCH_FAILED")
                    current = urljoin(current, location)
                    continue
                content_type = response.getheader("Content-Type", "").lower()
                if response.status != 200 or not re.search(r"text/(html|plain)|application/xhtml\+xml", content_type):
                    raise base.ApiError("IMPORT_UNSUPPORTED_CONTENT")
                if response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise base.ApiError("IMPORT_UNSUPPORTED_CONTENT")
                raw = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError()
                    if conn.sock:
                        conn.sock.settimeout(remaining)
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    raw.extend(chunk)
                    if len(raw) > 2_500_000:
                        raise base.ApiError("IMPORT_TOO_LARGE")
                charset = re.search(r"charset=[\"']?([\w-]+)", content_type)
                try:
                    source = raw.decode(charset.group(1) if charset else "utf-8", errors="replace")
                except LookupError:
                    source = raw.decode("utf-8", errors="replace")
                article = base.html_to_article(source, current)
                article["url"] = current
                article["published_at"] = base.meta_content(source, ["article:published_time", "datepublished", "pubdate"]) or article["published_at"]
                article["updated_at"] = base.meta_content(source, ["article:modified_time", "datemodified"])
                if len(article["content"]) < 20:
                    raise base.ApiError("IMPORT_CONTENT_EMPTY")
                return article
        finally:
            conn.close()
    raise base.ApiError("IMPORT_FETCH_FAILED")


def public_article(url):
    try:
        article = fetch_page(url, 18)
        article["published_at"] = base.normalize_imported_date(article["published_at"])
        return article
    except base.ApiError:
        raise
    except (TimeoutError, socket.timeout):
        raise base.ApiError("IMPORT_FETCH_TIMEOUT") from None
    except (OSError, ValueError, http.client.HTTPException):
        raise base.ApiError("IMPORT_FETCH_FAILED") from None


base.fetch_public_article = public_article


def availability():
    enabled = os.getenv("ANALYSIS_RETRIEVAL", "on").lower() != "off"
    return {
        "ifind_news_search": enabled and bool(IFIND_AUTH),
        "public_web_search": enabled and bool(os.getenv("TAVILY_API_KEY")),
        "read_webpage": enabled,
    }


def evidence_tool(name, args, timeout):
    if not availability().get(name):
        raise ValueError("TOOL_UNAVAILABLE")
    if name == "ifind_news_search":
        query = str(args.get("query") or "").strip()[:500]
        start, end = args.get("time_start"), args.get("time_end")
        if not query or not all(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in (start, end)):
            raise ValueError("TOOL_ARGS_INVALID")
        raw = IFIND.call("news", "search_news", {
            "query": query, "time_start": start, "time_end": end, "size": 8,
        }, timeout=timeout)
        return {"items": normalize_news_response(raw)[:8]}
    if name == "read_webpage":
        return {"items": [fetch_page(args.get("url"), timeout)]}
    request = Request("https://api.tavily.com/search", method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + os.environ["TAVILY_API_KEY"],
    }, data=json.dumps({
        "query": str(args.get("query") or "")[:500], "max_results": 5, "include_raw_content": False,
    }).encode())
    with no_redirect_open(request, timeout=timeout) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("SEARCH_RESPONSE_LIMIT")
    return {"items": [{**item, "published_at": item.get("published_date", ""), "evidence_level": "search_snippet"}
                      for item in json.loads(raw).get("results", [])[:5] if isinstance(item, dict)]}


class Handler(base.Handler):
    server_version = "FinSightFeedback/1.0"

    def log_message(self, _format, *_args):
        # Never log input URLs, headers, query strings or body.
        pass

    def send_json(self, status, body):
        data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_json(405, {"ok": False, "error": "只支持同源访问"})

    def route(self, method):
        path = urlsplit(self.path).path
        if method in {"POST", "DELETE"} and self.headers.get("Sec-Fetch-Site") in {"cross-site", "same-site"}:
            return self.send_json(403, {"ok": False, "error": "请从本站页面操作"})
        if method == "POST" and self.headers.get_content_type() != "application/json":
            return self.send_json(415, {"ok": False, "error": "请求须使用 JSON 格式"})
        costly = path in {"/api/news", "/api/analyze", "/api/market-kline", "/api/stock-kline", "/api/related-stocks"} or (
            method == "POST" and path.startswith("/api/imports"))
        if costly and not UPSTREAM_SLOTS.acquire(blocking=False):
            return self.send_json(429, {"ok": False, "error": "请求较多，请稍后重试"})
        try:
            query = parse_qs(urlsplit(self.path).query)
            if method == "GET" and path == "/api/market-kline":
                return self.send_json(*MARKET.market_kline(query))
            if method == "GET" and path == "/api/related-stocks":
                return self.send_json(*MARKET.related_stocks(query))
            return super().route(method)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            print("FINSIGHT_ROUTE_ERROR", type(exc).__name__, flush=True)
            return self.send_json(500, {"ok": False, "error": "服务器发生意外错误"})
        finally:
            if costly:
                UPSTREAM_SLOTS.release()

    def api_status(self):
        self.send_json(200, {
            "app": "finsight-show-v2", "edition": "feedback", "source_commit": BASELINE,
            "runtime": "python", "ok": True, "analysisSchemaVersion": 6,
            "mode": "live_ready" if IFIND_AUTH else "mock_only",
            "ifindClient": "built_in" if IFIND_AUTH else "not_configured",
            "deepseek": {"configured": base.has_deepseek(), "model": base.DEEPSEEK_MODEL},
            "tool_availability": availability(),
        })

    def api_news(self, query):
        include = query.get("include_imports", ["1"])[0] == "1"
        payload = NEWS.fetch_news(query, imported=base.confirmed_imported_news() if include else ())
        self.send_json(payload.pop("http_status", 200), payload)

    def api_stock_kline(self, query):
        self.send_json(*MARKET.stock_kline(query))

    def api_analyze(self):
        if not base.has_deepseek():
            return self.send_json(400, {"ok": False, "reason": "not_configured", "error": "还没有配置 DeepSeek 密钥"})
        try:
            payload = self.read_json_body()
        except base.ApiError:
            return self.send_json(400, {"ok": False, "error": "分析请求格式不正确"})
        news = payload.get("news", payload) if isinstance(payload, dict) else None
        if not isinstance(news, dict) or not base.text(news.get("title")):
            return self.send_json(400, {"ok": False, "error": "缺少新闻标题"})
        if not ANALYSIS_SLOTS.acquire(blocking=False):
            return self.send_json(429, {"ok": False, "error": "正在处理另一条分析，请稍后再试"})
        try:
            return self.analyze_one(news)
        finally:
            ANALYSIS_SLOTS.release()

    def analyze_one(self, news):
        deadline = time.monotonic() + 238

        def bounded(fn, *args, timeout):
            remaining = deadline - time.monotonic()
            if remaining < 1:
                raise TimeoutError("REQUEST_BUDGET")
            return fn(*args, timeout=min(float(timeout), remaining))

        try:
            market = bounded(MARKET.market_context, news, timeout=35)
        except Exception as exc:
            print("FINSIGHT_MARKET_UNAVAILABLE", type(exc).__name__, flush=True)
            market = None
        fields = ("benchmark", "event_published_at", "market_data_cutoff", "cutoff_rule",
                  "analysis_mode", "metrics", "source", "fetched_at")
        context = ({k: market.get(k) for k in fields} | {"observations": market.get("window_size")}
                   if market and market.get("status") != "unavailable" else {"status": "unavailable", "analysis_mode": "ex_ante"})
        try:
            analysis = analyze(
                news, context,
                model_call=lambda messages, timeout: bounded(model_call, messages, timeout=timeout),
                tool_call=lambda name, args, timeout: bounded(evidence_tool, name, args, timeout=timeout),
                tool_availability=availability(), audit_dir=AUDIT_DIR,
                normalize=base.normalize_analysis, prompt_path=ROOT / "feedback.txt", model=base.DEEPSEEK_MODEL,
                deadline=deadline,
            )
        except Exception as exc:
            print("FINSIGHT_ANALYSIS_FAILED", type(exc).__name__, flush=True)
            return self.send_json(502, {"ok": False, "error": "未取得通过校验的分析结果，请稍后重试"})
        analysis["macro_market"] = market or {"status": "unavailable", "analysis_mode": "ex_ante"}
        analysis["analysis_timing"] = {
            "event_published_at": base.text(news.get("published_at") or news.get("time")),
            "market_data_cutoff": context.get("market_data_cutoff", ""),
            "analysis_mode": "ex_ante", "analyzed_at": base.now_iso(),
        }
        try:
            candidates = bounded(MARKET.attach_stocks, analysis, news, timeout=40)
        except Exception as exc:
            print("FINSIGHT_STOCKS_UNAVAILABLE", type(exc).__name__, flush=True)
            candidates = []
            for key in ("candidate_stocks", "screened_stocks", "stocks"):
                analysis[key] = []
            analysis["stock_provider_status"] = {"status": "unavailable", "message": "标的查询未完成，不能据此判断没有相关股票"}
        try:
            finalize_candidates(analysis, AUDIT_DIR)
            base.mark_import_analyzed(news.get("id"))
        except Exception as exc:
            print("FINSIGHT_AUDIT_OR_IMPORT_UPDATE_FAILED", type(exc).__name__, flush=True)
        self.send_json(200, {
            "ok": True, "mode": "live", "analysisSchemaVersion": 6,
            "analysis": analysis, "candidates": candidates,
        })


class LimitedServer(ThreadingHTTPServer):
    connection_slots = threading.BoundedSemaphore(20)

    def process_request(self, request, address):
        if not self.connection_slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            request.settimeout(20)
            super().process_request(request, address)
        except BaseException:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.connection_slots.release()


if __name__ == "__main__":
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = LimitedServer(("0.0.0.0", PORT), Handler)
    print(f"FinSight feedback Python {BASELINE} listening on {PORT}", flush=True)
    server.serve_forever()
