"""Run from repository root: python -m uvicorn modules.market.app:app."""

from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, Response

from .calendar_service import TradingCalendar, parse_date, today
from .errors import MarketError
from .ifind_mcp import configuration_status
from .market_service import MarketService

Market = Literal["SSE", "SZSE"]
calendar = TradingCalendar()
market_service = MarketService(calendar=calendar)
app = FastAPI(title="FinSight Market API", version="0.2.0",
              description="沪深开市日历、iFinD MCP 前复权日 K 和最新行情。")


@app.exception_handler(MarketError)
async def market_error_handler(request: Request, error: MarketError):
    return JSONResponse(status_code=error.status,
                        content={"error": {"code": error.code, "message": error.message}})


@app.get("/api/market/health")
def health():
    return {"status": "ok", "calendarYears": calendar.years,
            "quoteProvider": "ifind-mcp", "quoteStatus": configuration_status()}


@app.get("/api/market/calendar")
def month(year: int = Query(ge=1, le=9999), month: int = Query(ge=1, le=12), market: Market = "SSE"):
    return calendar.month(year, month, market)


@app.get("/api/market/calendar/day")
def day(date: str | None = None, market: Market = "SSE"):
    value = parse_date(date) if date is not None else today()
    return {"date": value.isoformat(), **calendar.state(value, market)}


@app.get("/api/market/calendar/next")
def next_day(date: str | None = None, market: Market = "SSE"):
    value = parse_date(date) if date is not None else today()
    following = calendar.adjacent(value, 1, market)
    weekday = "一二三四五六日"[following.weekday()]
    return {"date": following.isoformat(), "calNext": following.strftime("%m-%d"),
            "calNextD": f"周{weekday} · 距今 {(following-value).days} 天"}


@app.get("/api/market/calendar/previous")
def previous_day(date: str, market: Market = "SSE"):
    return {"date": calendar.adjacent(parse_date(date), -1, market).isoformat()}


@app.get("/api/market/calendar/last-closed")
def last_closed(market: Market = "SSE"):
    return {"LAST_TD": calendar.last_closed(market=market).isoformat(),
            "note": "按交易日与 15:00 收盘时间计算，不代表行情供应商已完成数据更新"}


@app.get("/api/market/calendar/trading-dates")
def trading_dates(end: str, n: int = Query(default=60, ge=1, le=250), market: Market = "SSE"):
    return {"DATES": calendar.trading_dates(n, parse_date(end), market)}


@app.get("/api/market/calendar.ics")
def calendar_export(start: str, end: str, market: Market = "SSE"):
    content = calendar.ics(parse_date(start), parse_date(end), market)
    return Response(content, media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="finsight-calendar.ics"'})


@app.get("/api/market/review/window")
def review_window(date: str, market: Market = "SSE"):
    return calendar.review_window(parse_date(date), market)


@app.get("/api/market/quotes")
def quotes(codes: str = Query(min_length=1, max_length=120)):
    return market_service.quotes(codes.split(","))


@app.get("/api/market/stocks/{code}/quote")
def quote(code: str):
    result = market_service.quotes([code])
    return {**result["items"][0], "fetchedAt": result["fetchedAt"], "cached": result["cached"]}


@app.get("/api/market/stocks/{code}/kline")
def kline(code: str, n: int = Query(default=60, ge=1, le=120),
          end: str | None = None, include_quote: bool = True):
    return market_service.kline(code, n, parse_date(end) if end is not None else None, include_quote)
