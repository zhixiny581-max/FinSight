"""Exchange calendar; never infer an unpublished year's holiday schedule."""

import calendar
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .errors import MarketError

# Fixed UTC+08:00 avoids requiring a system IANA database on Windows.
SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
DATA_PATH = Path(__file__).with_name("data") / "calendar.json"


def parse_date(value: str) -> date:
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise MarketError("INVALID_DATE", "日期必须为有效的 YYYY-MM-DD 格式") from None


def today() -> date:
    return datetime.now(SHANGHAI).date()


class TradingCalendar:
    def __init__(self, path: Path = DATA_PATH):
        self.data = json.loads(path.read_text(encoding="utf-8"))
        self.years = sorted(int(y) for y in self.data["years"])
        self.holidays: dict[date, str] = {}
        self.makeup: set[date] = set()
        for year, config in self.data["years"].items():
            for name, start, end, makeup in config["HOLIDAY_TABLE"]:
                first, last = parse_date(start), parse_date(end)
                if first.year != int(year) or last.year != int(year) or first > last:
                    raise ValueError("Invalid holiday range in calendar.json")
                current = first
                while current <= last:
                    if current in self.holidays:
                        raise ValueError("Overlapping holiday ranges in calendar.json")
                    self.holidays[current] = name
                    current += timedelta(days=1)
                for raw in makeup:
                    day = parse_date(raw)
                    if day.year != int(year) or day.weekday() < 5:
                        raise ValueError("Makeup days must be weekends in the configured year")
                    self.makeup.add(day)

    def check(self, day: date, market: str = "SSE") -> None:
        if market not in self.data["markets"]:
            raise MarketError("UNSUPPORTED_MARKET", "日历仅支持 SSE（沪市）和 SZSE（深市）")
        if day.year not in self.years:
            raise MarketError("CALENDAR_NOT_CONFIGURED", f"尚未配置 {day.year} 年交易所日历")

    def state(self, day: date, market: str = "SSE") -> dict:
        self.check(day, market)
        if day in self.holidays:
            return {"open": False, "kind": "holiday", "label": self.holidays[day] + "休市"}
        if day.weekday() >= 5:
            if day in self.makeup:
                return {"open": False, "kind": "makeup", "label": "调休上班 · 仍休市"}
            return {"open": False, "kind": "weekend", "label": "周末休市"}
        return {"open": True, "kind": "open", "label": "开市"}

    def adjacent(self, day: date, step: int, market: str = "SSE") -> date:
        self.check(day, market)
        if step not in (-1, 1):
            raise ValueError("step must be -1 or 1")
        # state() stops at the first unconfigured year; no endless searches.
        while True:
            day += timedelta(days=step)
            if self.state(day, market)["open"]:
                return day

    def last_closed(self, now: datetime | None = None, market: str = "SSE") -> date:
        now = now or datetime.now(SHANGHAI)
        if now.tzinfo is None:
            raise ValueError("now must include a timezone")
        local = now.astimezone(SHANGHAI)
        day = local.date()
        if self.state(day, market)["open"] and local.time() >= time(15):
            return day
        return self.adjacent(day, -1, market)

    def trading_dates(self, n: int, end: date, market: str = "SSE") -> list[str]:
        if not 1 <= n <= 250:
            raise MarketError("INVALID_COUNT", "n 必须在 1 至 250 之间")
        result = []
        current = end
        while len(result) < n:
            if self.state(current, market)["open"]:
                result.append(current.isoformat())
            current -= timedelta(days=1)
        return list(reversed(result))

    def month(self, year: int, month: int, market: str = "SSE") -> dict:
        try:
            first = date(year, month, 1)
        except ValueError:
            raise MarketError("INVALID_MONTH", "年份或月份无效") from None
        self.check(first, market)
        days = [
            {"date": date(year, month, d).isoformat(), **self.state(date(year, month, d), market)}
            for d in range(1, calendar.monthrange(year, month)[1] + 1)
        ]
        opened = sum(d["open"] for d in days)
        return {
            "market": market, "timezone": "Asia/Shanghai", "days": days,
            "calOpenN": opened, "calClosedN": len(days) - opened,
            "calTitle": f"{year} 年 {month} 月",
            "calMonthLabel": f"{year} 年 {month} 月 · 共 {len(days)} 天",
            "HOLIDAY_TABLE": self.data["years"][str(year)]["HOLIDAY_TABLE"],
            "source": self.data["years"][str(year)]["source"],
        }

    def review_window(self, day: date, market: str = "SSE") -> dict:
        if not self.state(day, market)["open"]:
            raise MarketError("NOT_TRADING_DAY", "复盘日期必须为交易日")
        previous = self.adjacent(day, -1, market)
        return {
            "winFrom": f"{previous.isoformat()} 15:00",
            "winTo": f"{day.isoformat()} 15:00",
            "start": datetime.combine(previous, time(15), SHANGHAI).isoformat(),
            "end": datetime.combine(day, time(15), SHANGHAI).isoformat(),
            "startInclusive": False, "endInclusive": True, "timezone": "Asia/Shanghai",
        }

    def ics(self, start: date, end: date, market: str = "SSE") -> str:
        if start > end or (end - start).days > 365:
            raise MarketError("INVALID_RANGE", "开始日期不能晚于结束日期，最多导出 366 天")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//FinSight//Market Calendar//ZH",
                 "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
        day = start
        while day <= end:
            state = self.state(day, market)
            lines.extend([
                "BEGIN:VEVENT", f"UID:{market}-{day:%Y%m%d}@calendar.finsight",
                f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
                f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                f"SUMMARY:{'交易日' if state['open'] else state['label']}",
                "TRANSP:TRANSPARENT", "END:VEVENT",
            ])
            day += timedelta(days=1)
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"
