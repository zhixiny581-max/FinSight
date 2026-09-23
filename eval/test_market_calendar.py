from datetime import date, datetime, timezone
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient

from modules.market.app import app
from modules.market.calendar_service import SHANGHAI, TradingCalendar, parse_date
from modules.market.errors import MarketError

client = TestClient(app)
calendar = TradingCalendar()


@pytest.mark.parametrize("raw", ["2026-01-04", "2026-02-14", "2026-02-28", "2026-05-09", "2026-09-20", "2026-10-10"])
def test_makeup_weekends_are_closed(raw):
    assert calendar.state(parse_date(raw)) == {
        "open": False, "kind": "makeup", "label": "调休上班 · 仍休市"}


@pytest.mark.parametrize("raw,kind,opened", [
    ("2026-09-25", "holiday", False), ("2026-10-07", "holiday", False),
    ("2026-10-08", "open", True), ("2026-09-19", "weekend", False),
    ("2026-02-23", "holiday", False), ("2026-02-24", "open", True),
])
def test_exchange_schedule(raw, kind, opened):
    assert calendar.state(parse_date(raw))["kind"] == kind
    assert calendar.state(parse_date(raw))["open"] is opened


def test_adjacent_and_cross_year():
    assert calendar.adjacent(date(2026, 9, 20), 1) == date(2026, 9, 21)
    assert calendar.adjacent(date(2026, 10, 1), 1) == date(2026, 10, 8)
    assert calendar.adjacent(date(2026, 1, 5), -1) == date(2025, 12, 31)
    with pytest.raises(MarketError, match="2027"):
        calendar.adjacent(date(2026, 12, 31), 1)


def test_unknown_year_and_market_do_not_guess():
    with pytest.raises(MarketError, match="2027"):
        calendar.state(date(2027, 1, 4))
    with pytest.raises(MarketError, match="仅支持"):
        calendar.state(date(2026, 9, 21), "HK")


@pytest.mark.parametrize("raw", ["2026-02-30", "2026-9-2", "20260920", "garbage", ""])
def test_strict_date_validation(raw):
    with pytest.raises(MarketError):
        parse_date(raw)


def test_month_counts_and_next_day_api():
    result = client.get("/api/market/calendar?year=2026&month=9").json()
    assert result["calOpenN"] == 21
    assert result["calClosedN"] == 9
    assert len(result["days"]) == 30
    result = client.get("/api/market/calendar/next?date=2026-09-20").json()
    assert result == {"date": "2026-09-21", "calNext": "09-21", "calNextD": "周一 · 距今 1 天"}


def test_sixty_dates_are_sorted_unique_and_open():
    dates = calendar.trading_dates(60, date(2026, 9, 20))
    assert len(dates) == len(set(dates)) == 60
    assert dates == sorted(dates)
    assert dates[-1] == "2026-09-18"
    assert all(calendar.state(parse_date(day))["open"] for day in dates)


def test_last_closed_at_close_boundary_and_timezone():
    assert calendar.last_closed(datetime(2026, 9, 21, 14, 59, tzinfo=SHANGHAI)) == date(2026, 9, 18)
    assert calendar.last_closed(datetime(2026, 9, 21, 15, 0, tzinfo=SHANGHAI)) == date(2026, 9, 21)
    assert calendar.last_closed(datetime(2026, 9, 21, 7, 0, tzinfo=timezone.utc)) == date(2026, 9, 21)
    assert calendar.last_closed(datetime(2026, 9, 20, 16, 0, tzinfo=SHANGHAI)) == date(2026, 9, 18)


def test_review_window_spans_holidays_left_open_right_closed():
    result = calendar.review_window(date(2026, 10, 8))
    assert result["start"] == "2026-09-30T15:00:00+08:00"
    assert result["end"] == "2026-10-08T15:00:00+08:00"
    assert result["startInclusive"] is False
    assert result["endInclusive"] is True
    assert client.get("/api/market/review/window?date=2026-10-01").status_code == 422


def test_ics_format_inclusive_range_and_exclusive_event_end():
    response = client.get("/api/market/calendar.ics?start=2026-09-20&end=2026-09-21")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert response.content.endswith(b"END:VCALENDAR\r\n")
    assert response.text.count("BEGIN:VEVENT") == 2
    assert "DTSTART;VALUE=DATE:20260920\r\nDTEND;VALUE=DATE:20260921" in response.text
    assert "SUMMARY:调休上班 · 仍休市" in response.text
    assert all(len(line.encode("utf-8")) <= 75 for line in response.text.splitlines())
    assert client.get("/api/market/calendar.ics?start=2026-09-21&end=2026-09-20").status_code == 422


@pytest.mark.parametrize("url", [
    "/api/market/calendar?year=2026&month=13",
    "/api/market/calendar/day?date=2026-02-30",
    "/api/market/calendar/day?date=2027-01-04",
    "/api/market/calendar/day?date=2026-09-21&market=HK",
    "/api/market/calendar/trading-dates?end=2026-09-18&n=0",
])
def test_api_invalid_inputs(url):
    assert client.get(url).status_code == 422


def test_calendar_states_and_dates_match_original_html_contract():
    html = (Path(__file__).parents[1] / "frontend/index.html").read_text(encoding="utf-8")
    assert "out.push({o,h,l,c,v:" in html
    assert "return {open:true, kind:'open', label:'开市'}" in html
    section = html.split("const HOLIDAY_RANGES = [", 1)[1].split("];", 1)[0]
    ranges = re.findall(r"\['([^']+)','([^']+)','([^']+)'\]", section)
    assert ranges == [(r[1], r[2], r[0]) for r in calendar.data["years"]["2026"]["HOLIDAY_TABLE"]]
