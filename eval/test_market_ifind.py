"""Synthetic fixtures modeled on verified MCP schemas; no credentials or live data."""

from copy import deepcopy
from datetime import date
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from modules.market.app import app
from modules.market.calendar_service import TradingCalendar
from modules.market.errors import MarketError
from modules.market.ifind_mcp import IFindMCP, SERVER_NAME, SERVER_URL, decode_tool_result, load_settings
from modules.market.ifind_parser import number, parse_history, parse_quotes
from modules.market.market_service import MarketService
from modules.market.symbols import normalize_code


@pytest.fixture
def history():
    return {
        "answer": "|证券代码|证券简称|日期|开盘价（单位：元）|最高价|最低价|收盘价|成交量|\\n"
                  "|---|---|---|---|---|---|---|---|\\n"
                  "|300750.SZ|测试证券|20260918|10|12|9|11|1.25万|\\n"
                  "|300750.SZ|测试证券|20260917|9|11|8|10|2万|",
        "indicators_params": {
            **{field: {"复权方式": "前复权"} for field in ("开盘价", "最高价", "最低价", "收盘价")},
            "成交量": {"单位": "股"},
        },
    }


@pytest.fixture
def snapshot():
    return {"tables": [["证券代码", "证券简称", "time", "最新价", "涨跌幅"],
                       ["300750.SZ", "测试证券", "2026-09-23 15:00:00", "11.5", "1.85"]]}


def parse(data):
    return parse_history(data, normalize_code("300750"), date(2026, 9, 1), date(2026, 9, 18), TradingCalendar())


def test_real_shape_history_mapping_sort_and_units(history):
    result = parse(history)
    assert result["DATES"] == ["2026-09-17", "2026-09-18"]
    assert result["candles"][-1] == {"o": 10, "h": 12, "l": 9, "c": 11, "v": 12500}


@pytest.mark.parametrize("value,unit,expected", [
    ("1.2万股", "volume", 12000), ("1.2万手", "volume", 1200000),
    ("0.2亿股", "volume", 20000000), ("100手", "volume", 10000),
    ("1,234.5", "", 1234.5), ("-1.85%", "", -1.85),
])
def test_numeric_units(value, unit, expected):
    assert number(value, unit) == expected


@pytest.mark.parametrize("value", [None, True, "--", "NaN", "inf", "", "约100", "1e9999"])
def test_invalid_numbers_rejected(value):
    with pytest.raises(MarketError):
        number(value)


@pytest.mark.parametrize("field", ["开盘价", "最高价", "最低价", "收盘价"])
def test_every_price_requires_explicit_forward_adjustment(history, field):
    history["indicators_params"][field]["复权方式"] = "不复权"
    with pytest.raises(MarketError, match="前复权"):
        parse(history)


def test_missing_volume_unit_rejected(history):
    del history["indicators_params"]["成交量"]["单位"]
    with pytest.raises(MarketError, match="单位"):
        parse(history)


@pytest.mark.parametrize("before,after", [
    ("300750.SZ", "600519.SH"), ("20260918", "20260920"),
    ("20260918", "20260831"), ("20260918", "20260917"),
    ("|10|12|9|11|", "|10|8|9|11|"), ("1.25万", "-1万"),
    ("1.25万", "未知"),
])
def test_corrupt_or_unrelated_history_is_not_silently_used(history, before, after):
    history["answer"] = history["answer"].replace(before, after)
    with pytest.raises(MarketError):
        parse(history)


def test_zero_volume_rows_are_not_filled(history):
    history["answer"] = history["answer"].replace("1.25万", "0")
    result = parse(history)
    assert result["DATES"] == ["2026-09-17"]
    assert result["skippedZeroVolume"] == 1


def test_verified_closed_day_fill_is_skipped(history):
    history["answer"] += "\\n|300750.SZ|测试证券|20260913||||11||"
    result = parse(history)
    assert len(result["candles"]) == 2
    assert result["skippedNonTrading"] == 1


def test_missing_trading_day_values_are_marked(history):
    history["answer"] += "\\n|300750.SZ|测试证券|20260916||||11||"
    result = parse(history)
    assert result["missingPriceDates"] == ["2026-09-16"]
    assert len(result["candles"]) == 2


def test_quote_fields_percent_and_exchange_timestamp(snapshot):
    result = parse_quotes(snapshot, [normalize_code("300750")])[0]
    assert result["px"] == 11.5
    assert result["chg"] == 1.85  # Already a percentage, not multiplied by 100.
    assert result["asOf"] == "2026-09-23T15:00:00+08:00"


@pytest.mark.parametrize("column,value", [(0,"600519.SH"),(2,"unknown"),(3,"0"),(4,"--")])
def test_bad_snapshot_is_rejected(snapshot, column, value):
    snapshot["tables"][1][column] = value
    with pytest.raises(MarketError):
        parse_quotes(snapshot, [normalize_code("300750")])


def test_missing_quote_row_is_explicit(snapshot):
    with pytest.raises(MarketError, match="部分股票"):
        parse_quotes(snapshot, [normalize_code("300750"), normalize_code("600519")])


def test_mcp_nested_json_envelope(snapshot):
    result = {"content": [{"type": "text", "text": json.dumps({"code": 1, "data": json.dumps(snapshot)})}]}
    assert decode_tool_result(result) == snapshot


@pytest.mark.parametrize("result", [
    {"isError": True}, {"content": []}, {"content": [{"type": "text", "text": "not json"}]},
    {"content": [{"type": "text", "text": '{"code":0,"msg":"secret must not echo"}'}]},
])
def test_mcp_errors_do_not_echo_upstream_details(result):
    with pytest.raises(MarketError) as error:
        decode_tool_result(result)
    assert "secret" not in error.value.message


@pytest.mark.parametrize("sse", [False, True])
def test_mcp_json_and_sse_matching_response(sse):
    payload = {"jsonrpc": "2.0", "id": 7, "result": {"hello": "world"}}
    body = json.dumps(payload)
    content_type = "application/json"
    if sse:
        body = 'data: {"method":"notifications/progress"}\n\ndata: ' + body + "\n\n"
        content_type = "text/event-stream"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=body, headers={"content-type": content_type}))
    with httpx.Client(transport=transport) as client:
        result, _ = IFindMCP()._post(client, SERVER_URL, {}, {"id": 7})
    assert result == {"hello": "world"}


@pytest.mark.parametrize("status,code", [(401,"IFIND_UNAUTHORIZED"),(403,"IFIND_UNAUTHORIZED"),(429,"IFIND_RATE_LIMITED")])
def test_mcp_http_failures_are_sanitized(status, code):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text="secret"))
    with httpx.Client(transport=transport) as client, pytest.raises(MarketError) as error:
        IFindMCP()._post(client, SERVER_URL, {}, {"id": 1})
    assert error.value.code == code
    assert "secret" not in error.value.message


def test_configuration_external_file_and_host_restriction(tmp_path, monkeypatch):
    config = tmp_path / "local.json"
    data = {"mcpServers": {SERVER_NAME: {"url": SERVER_URL, "headers": {"Authorization": "unit-test-only"}}}}
    config.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("IFIND_MCP_CONFIG", str(config))
    assert load_settings()[1]["Authorization"] == "unit-test-only"
    data["mcpServers"][SERVER_NAME]["url"] = "https://example.com/collect"
    config.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MarketError, match="官方地址"):
        load_settings()


def test_no_credentials_reports_unconfigured(monkeypatch):
    monkeypatch.delenv("IFIND_MCP_CONFIG", raising=False)
    monkeypatch.delenv("IFIND_MCP_AUTHORIZATION", raising=False)
    with pytest.raises(MarketError) as error:
        load_settings()
    assert error.value.code == "IFIND_NOT_CONFIGURED"


class Provider:
    def __init__(self, history, snapshot):
        self.history, self.snapshot = history, snapshot
        self.calls = []
        self.fail_quotes = False

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "stock_highfreq_quotes":
            if self.fail_quotes:
                raise MarketError("IFIND_UNAVAILABLE", "测试服务不可用", 502)
            return deepcopy(self.snapshot)
        data = deepcopy(self.history)
        import re
        start, end = re.search(r"在(\d{4}-\d{2}-\d{2})至(\d{4}-\d{2}-\d{2})", args["query"]).groups()
        lines = data["answer"].split("\\n")
        data["answer"] = "\\n".join(lines[:2] + [line for line in lines[2:]
            if start.replace("-", "") <= line.split("|")[3] <= end.replace("-", "")])
        return data


def service(history, snapshot):
    calendar = TradingCalendar()
    calendar.last_closed = lambda **kw: date(2026, 9, 23)
    provider = Provider(history, snapshot)
    return MarketService(provider, calendar), provider


def test_service_joins_history_and_quote_without_changing_ui_keys(history, snapshot):
    market, provider = service(history, snapshot)
    result = market.kline("300750", n=2, end=date(2026, 9, 18))
    assert result["px"] == 11.5 and result["candles"][-1]["c"] == 11
    assert result["chg"] == 1.85
    assert result["adjust"] == "qfq"
    assert result["volumeUnit"] == "股"
    assert result["shortHistory"] is False
    assert "2026-09-18" in provider.calls[0][1]["query"]
    assert "前复权" in provider.calls[0][1]["query"]


def test_quote_failure_preserves_history_and_does_not_invent_latest_price(history, snapshot):
    market, provider = service(history, snapshot)
    provider.fail_quotes = True
    result = market.kline("300750", n=60, end=date(2026, 9, 18))
    assert result["returnedCount"] == 2 and result["shortHistory"] is True
    assert result["px"] is None and result["chg"] is None
    assert result["quoteError"]["code"] == "IFIND_UNAVAILABLE"


def test_cached_history_does_not_keep_stale_quote_or_mutable_objects(history, snapshot):
    market, provider = service(history, snapshot)
    first = market.kline("300750", n=2, end=date(2026, 9, 18), include_quote=False)
    first["candles"][0]["c"] = 999
    second = market.kline("300750", n=2, end=date(2026, 9, 18), include_quote=False)
    assert len(provider.calls) == 1
    assert second["cached"] is True
    assert second["candles"][0]["c"] == 10


def test_invalid_symbols_do_not_call_provider(history, snapshot):
    market, provider = service(history, snapshot)
    with pytest.raises(MarketError):
        market.kline("HK1177")
    with pytest.raises(MarketError):
        market.quotes(["300750", "300750.SZ"])
    with pytest.raises(MarketError):
        market.kline("300750", end=date(2026, 9, 24))
    assert not provider.calls


def test_api_market_routes_with_injected_provider(history, snapshot, monkeypatch):
    import importlib
    module = importlib.import_module("modules.market.app")
    market, _ = service(history, snapshot)
    monkeypatch.setattr(module, "market_service", market)
    client = TestClient(app)
    assert client.get("/api/market/stocks/300750/quote").json()["code"] == "300750"
    response = client.get("/api/market/stocks/300750/kline?n=2&end=2026-09-18")
    assert response.status_code == 200 and response.json()["returnedCount"] == 2
    assert client.get("/api/market/stocks/HK1177/kline").status_code == 422
    assert client.get("/api/market/stocks/300750/kline?n=0").status_code == 422


def test_sixty_bars_use_short_complete_windows_and_aligned_dates(history):
    import re
    from datetime import timedelta
    calendar = TradingCalendar()
    calendar.last_closed = lambda **kw: date(2026, 9, 23)

    class WindowProvider:
        def __init__(self):
            self.windows = []

        def call(self, name, args):
            assert name == "get_stock_performance"
            a, b = re.search(r"在(\d{4}-\d{2}-\d{2})至(\d{4}-\d{2}-\d{2})", args["query"]).groups()
            start, end = date.fromisoformat(a), date.fromisoformat(b)
            assert (end-start).days <= 27
            self.windows.append((start, end))
            lines = history["answer"].split("\\n")[:2]
            cursor = end
            while cursor >= start:
                if calendar.state(cursor)["open"]:
                    lines.append(f"|300750.SZ|测试证券|{cursor:%Y%m%d}|10|12|9|11|100股|")
                else:
                    lines.append(f"|300750.SZ|测试证券|{cursor:%Y%m%d}||||11||")
                cursor -= timedelta(days=1)
            return {**history, "answer": "\\n".join(lines)}

    provider = WindowProvider()
    market = MarketService(provider, calendar)
    result = market.kline("300750", n=60, end=date(2026, 9, 22), include_quote=False)
    assert len(provider.windows) == 3
    assert result["returnedCount"] == 60
    assert result["DATES"] == calendar.trading_dates(60, date(2026, 9, 22))
    assert result["missingTradingDates"] == []
    assert result["shortHistory"] is False
    assert result["px"] is None


def test_upstream_timeout_is_safe(monkeypatch):
    monkeypatch.delenv("IFIND_MCP_CONFIG", raising=False)
    monkeypatch.setenv("IFIND_MCP_AUTHORIZATION", "unit-test-only")
    mcp = IFindMCP()
    def timeout(*args):
        raise httpx.ReadTimeout("secret response")
    monkeypatch.setattr(mcp, "_post", timeout)
    with pytest.raises(MarketError) as error:
        mcp.call("get_stock_performance", {"query": "test"})
    assert error.value.status == 504
    assert "secret" not in error.value.message
