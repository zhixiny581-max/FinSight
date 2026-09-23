"""Calendar-aware daily bars and latest snapshots; no mock market data."""

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from time import monotonic

from .calendar_service import SHANGHAI, TradingCalendar
from .errors import MarketError
from .ifind_mcp import IFindMCP
from .ifind_parser import parse_history, parse_quotes
from .symbols import normalize_code

HISTORY_QUERY = (Path(__file__).with_name("prompts") / "daily_kline.txt").read_text(encoding="utf-8").strip()


class MarketService:
    def __init__(self, provider=None, calendar=None):
        self.provider = provider or IFindMCP()
        self.calendar = calendar or TradingCalendar()
        self.cache = {}
        self.lock = Lock()

    def _cached(self, key, ttl, operation):
        # Serialize cache misses to avoid accidental bursts against the account.
        with self.lock:
            current = monotonic()
            entry = self.cache.get(key)
            if entry and entry[0] > current:
                result = deepcopy(entry[1])
                result["cached"] = True
                return result
            result = operation()
            result["fetchedAt"] = datetime.now(SHANGHAI).isoformat()
            result["cached"] = False
            self.cache = {k: v for k, v in self.cache.items() if v[0] > current}
            if len(self.cache) >= 128:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = (monotonic() + ttl, deepcopy(result))
            return result

    def quotes(self, codes: list[str]) -> dict:
        if not 1 <= len(codes) <= 10:
            raise MarketError("INVALID_COUNT", "一次可查询 1 至 10 只沪深 A 股")
        symbols = [normalize_code(code) for code in codes]
        if len({s.code for s in symbols}) != len(symbols):
            raise MarketError("DUPLICATE_CODE", "股票代码不可重复")

        def fetch():
            data = self.provider.call("stock_highfreq_quotes", {
                "symbols": ",".join(s.thscode for s in symbols),
                "indicators": "最新价,涨跌幅", "data_mode": "real_time",
            })
            return {"items": parse_quotes(data, symbols)}

        return self._cached(("quotes", *(s.code for s in symbols)), 15, fetch)

    def kline(self, code: str, n: int = 60, end=None, include_quote: bool = True) -> dict:
        symbol = normalize_code(code)
        if not 1 <= n <= 120:
            raise MarketError("INVALID_COUNT", "日 K 数量须在 1 至 120 之间")
        closed = self.calendar.last_closed(market=symbol.market)
        end = end or closed
        self.calendar.check(end, symbol.market)
        if end > closed:
            raise MarketError("FUTURE_DATE", "结束日期不能晚于最近已收盘交易日")
        if not self.calendar.state(end, symbol.market)["open"]:
            end = self.calendar.adjacent(end, -1, symbol.market)
        # Extra calendar days allow holidays and suspensions without filling fake bars.
        start = max(end - timedelta(days=n * 2 + 30),
                    end.replace(year=min(self.calendar.years), month=1, day=1))

        def fetch():
            records = {}
            name = None
            skipped_zero = skipped_closed = calls = 0
            missing_prices = []
            chunk_end = end
            while chunk_end >= start and len(records) < n:
                chunk_start = max(start, chunk_end - timedelta(days=27))
                data = self.provider.call("get_stock_performance", {
                    "query": HISTORY_QUERY.format(code=symbol.thscode, start=chunk_start.isoformat(), end=chunk_end.isoformat()),
                })
                calls += 1
                history = parse_history(data, symbol, chunk_start, chunk_end, self.calendar)
                records.update(zip(history["DATES"], history["candles"]))
                name = name or history["name"]
                skipped_zero += history["skippedZeroVolume"]
                skipped_closed += history["skippedNonTrading"]
                missing_prices.extend(history["missingPriceDates"])
                chunk_end = chunk_start - timedelta(days=1)
            dates = sorted(records)[-n:]
            if not dates:
                raise MarketError("IFIND_NO_DATA", "查询范围内没有有效日 K，可能未上市或停牌", 404)
            candles = [records[d] for d in dates]
            missing = []
            cursor = datetime.fromisoformat(dates[0]).date()
            while cursor <= end:
                if self.calendar.state(cursor, symbol.market)["open"] and cursor.isoformat() not in records:
                    missing.append(cursor.isoformat())
                cursor += timedelta(days=1)
            return {"code": symbol.code, "name": name, "market": symbol.market,
                    "DATES": dates, "candles": candles, "adjust": "qfq",
                    "source": "iFinD MCP", "volumeUnit": "股", "priceUnit": "CNY",
                    "requestedCount": n, "returnedCount": len(dates), "shortHistory": len(dates) < n,
                    "requestedEnd": end.isoformat(), "lastDate": dates[-1],
                    "historyBehindEnd": dates[-1] < end.isoformat(),
                    "queryStart": chunk_start.isoformat(), "skippedZeroVolume": skipped_zero,
                    "skippedNonTrading": skipped_closed, "missingPriceDates": sorted(missing_prices),
                    "missingTradingDates": missing, "upstreamCalls": calls,
                    "adjustmentBasis": "iFinD 查询时的前复权口径；历史回测需另外保存当时快照"}

        result = self._cached(("kline", symbol.code, n, end.isoformat()), 300, fetch)
        result.update({"px": None, "chg": None, "quoteAsOf": None, "quoteError": None})
        if include_quote:
            try:
                quotes = self.quotes([symbol.code])
                quote = quotes["items"][0]
                result.update({"px": quote["px"], "chg": quote["chg"], "quoteAsOf": quote["asOf"]})
            except MarketError as error:
                result["quoteError"] = {"code": error.code, "message": error.message}
        return result
