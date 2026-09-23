"""Minimal read-only iFinD Streamable HTTP client, including JSON/SSE replies."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .errors import MarketError

SERVER_NAME = "hexin-ifind-ds-stock-mcp"
SERVER_URL = "https://api-mcp.51ifind.com:8643/ds-mcp-servers/" + SERVER_NAME
ALLOWED_TOOLS = {"get_stock_performance", "stock_highfreq_quotes"}


def load_settings() -> tuple[str, dict]:
    """Read secrets at runtime; never copy a user's configuration into the repo."""
    config_path = os.getenv("IFIND_MCP_CONFIG", "")
    if config_path:
        try:
            data = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
            server = data["mcpServers"][SERVER_NAME]
            url = server["url"]
            authorization = server["headers"]["Authorization"]
        except (OSError, ValueError, KeyError, TypeError):
            raise MarketError("IFIND_CONFIG_INVALID", "无法读取 iFinD 股票 MCP 配置", 503) from None
    else:
        url = SERVER_URL
        authorization = os.getenv("IFIND_MCP_AUTHORIZATION", "")
    try:
        if not isinstance(url, str):
            raise ValueError
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        raise MarketError("IFIND_CONFIG_INVALID", "iFinD 服务地址格式无效", 503) from None
    if (parsed.scheme != "https" or parsed.hostname != "api-mcp.51ifind.com"
            or port != 8643 or parsed.path != urlsplit(SERVER_URL).path
            or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise MarketError("IFIND_CONFIG_INVALID", "仅允许连接已核实的 iFinD 股票 MCP 官方地址", 503)
    if not isinstance(authorization, str) or not authorization.strip():
        raise MarketError("IFIND_NOT_CONFIGURED", "请设置 IFIND_MCP_CONFIG 指向本机 MCP 配置文件", 503)
    return url, {"Authorization": authorization, "Accept": "application/json, text/event-stream"}


def configuration_status() -> str:
    try:
        load_settings()
        return "configured"
    except MarketError:
        return "not_configured"


def decode_tool_result(result: dict) -> dict:
    if not isinstance(result, dict) or result.get("isError"):
        raise MarketError("IFIND_TOOL_ERROR", "iFinD 工具执行失败，请检查账号权限或稍后重试", 502)
    try:
        text_items = [item["text"] for item in result["content"] if item.get("type") == "text"]
        if len(text_items) != 1:
            raise ValueError
        envelope = json.loads(text_items[0])
        if not isinstance(envelope, dict):
            raise ValueError
        if envelope.get("code") != 1:
            raise MarketError("IFIND_TOOL_ERROR", "iFinD 未成功返回数据，请检查账号权限或稍后重试", 502)
        data = envelope["data"]
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, TypeError, KeyError):
        raise MarketError("IFIND_RESPONSE_INVALID", "iFinD 返回格式与已验证格式不一致", 502) from None


class IFindMCP:
    def _post(self, client, url, headers, message):
        # Do not follow redirects: credentials belong only to the verified origin.
        with client.stream("POST", url, headers=headers, json=message) as response:
            if response.status_code in (401, 403):
                raise MarketError("IFIND_UNAUTHORIZED", "iFinD 授权失效或无权限，请更新本机配置", 503)
            if response.status_code == 429:
                raise MarketError("IFIND_RATE_LIMITED", "iFinD 请求过于频繁，请稍后重试", 503)
            response.raise_for_status()
            session = response.headers.get("mcp-session-id")
            if "id" not in message:
                return None, session
            result = None
            size = 0
            if "text/event-stream" in response.headers.get("content-type", ""):
                event = []
                for line in response.iter_lines():
                    size += len(line.encode("utf-8"))
                    if size > 4_000_000:
                        raise ValueError("Oversized response")
                    if line.startswith("data:"):
                        event.append(line[5:].lstrip())
                    elif not line and event:
                        value = json.loads("\n".join(event))
                        event = []
                        if value.get("id") == message["id"]:
                            result = value
                            break
            else:
                chunks = []
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 4_000_000:
                        raise ValueError("Oversized response")
                    chunks.append(chunk)
                result = json.loads(b"".join(chunks))
            if not isinstance(result, dict) or result.get("id") != message["id"]:
                raise ValueError("Mismatched response")
            if "error" in result:
                raise MarketError("IFIND_PROTOCOL_ERROR", "iFinD MCP 请求失败", 502)
            return result["result"], session

    def call(self, name: str, arguments: dict) -> dict:
        if name not in ALLOWED_TOOLS:
            raise ValueError("Unsupported tool")
        url, headers = load_settings()
        trust_env = os.getenv("IFIND_TRUST_ENV", "false").lower() == "true"
        try:
            with httpx.Client(timeout=httpx.Timeout(90, connect=10), trust_env=trust_env,
                              follow_redirects=False) as client:
                init, session = self._post(client, url, headers, {
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "finsight-market", "version": "0.2.0"}},
                })
                if session:
                    headers["Mcp-Session-Id"] = session
                headers["MCP-Protocol-Version"] = init["protocolVersion"]
                try:
                    self._post(client, url, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"})
                    result, _ = self._post(client, url, headers, {
                        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    })
                    return decode_tool_result(result)
                finally:
                    if session:
                        try:
                            client.delete(url, headers=headers, timeout=5)
                        except httpx.HTTPError:
                            pass
        except httpx.TimeoutException:
            raise MarketError("IFIND_TIMEOUT", "iFinD 查询超时，请稍后重试", 504) from None
        except httpx.HTTPError:
            raise MarketError("IFIND_UNAVAILABLE", "无法连接 iFinD 服务", 502) from None
        except (KeyError, TypeError, ValueError):
            raise MarketError("IFIND_RESPONSE_INVALID", "iFinD 返回格式与已验证格式不一致", 502) from None
