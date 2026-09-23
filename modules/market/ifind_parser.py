"""Strict parsing of the two response formats observed from iFinD stock MCP."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from .calendar_service import SHANGHAI, parse_date
from .errors import MarketError
from .symbols import StockCode


def invalid(message="iFinD 行情缺失字段或返回值异常"):
    return MarketError("IFIND_DATA_INVALID", message, 502)


def number(raw, unit="") -> float:
    if isinstance(raw, bool) or raw is None:
        raise invalid()
    text = str(raw).strip().replace(",", "").replace("，", "")
    multiplier = Decimal(1)
    # Units on the cell override a metadata base unit; magnitude is separate.
    cell_unit = next((u for u in ("股", "手", "元", "%") if text.endswith(u)), "")
    if cell_unit:
        text = text[:-len(cell_unit)]
    for suffix, scale in (("亿", 100_000_000), ("万", 10_000)):
        if text.endswith(suffix):
            multiplier *= scale
            text = text[:-len(suffix)]
            break
    if unit == "volume":
        if cell_unit not in ("股", "手"):
            raise invalid("成交量单位不明确")
        if cell_unit == "手":
            multiplier *= 100
    elif cell_unit not in ("", "元", "%"):
        raise invalid()
    try:
        value = Decimal(text) * multiplier
        if not value.is_finite():
            raise InvalidOperation
        result = float(value)
        if not Decimal(str(result)).is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, OverflowError):
        raise invalid() from None


def _rows(data: dict) -> list[dict]:
    table = data.get("tables")
    if table is None:
        answer = data.get("answer", "")
        if not isinstance(answer, str):
            raise invalid()
        table = []
        for line in answer.replace("\\n", "\n").splitlines():
            line = line.strip()
            if not line.startswith("|"):
                continue
            # Remove only the outer delimiters, preserving empty final cells.
            body = line[1:-1] if line.endswith("|") else line[1:]
            cells = [cell.strip() for cell in body.split("|")]
            if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                continue
            table.append(cells)
    if not isinstance(table, list) or not table or not isinstance(table[0], list):
        raise MarketError("IFIND_NO_DATA", "iFinD 未返回行情表格", 404)
    headers = [re.sub(r"[（(].*?[）)]", "", str(h)).strip() for h in table[0]]
    if len(set(headers)) != len(headers):
        raise invalid("行情表头重复")
    rows = []
    for row in table[1:]:
        if not isinstance(row, list) or len(row) != len(headers):
            raise invalid("行情表格列数不一致")
        rows.append(dict(zip(headers, row)))
    return rows


def parse_history(data: dict, symbol: StockCode, start, end, calendar) -> dict:
    params = data.get("indicators_params", {})
    if not isinstance(params, dict):
        raise invalid()
    for field in ("开盘价", "最高价", "最低价", "收盘价"):
        settings = params.get(field, {})
        if not isinstance(settings, dict) or settings.get("复权方式") != "前复权":
            raise invalid("未确认所有 OHLC 价格为前复权，拒绝混用复权口径")
    volume_settings = params.get("成交量", {})
    volume_unit = volume_settings.get("单位") if isinstance(volume_settings, dict) else None
    if volume_unit not in ("股", "手"):
        raise invalid("iFinD 未明确成交量单位")
    records = {}
    name = None
    skipped = 0
    closed_rows = 0
    missing_dates = []
    seen = set()
    for row in _rows(data):
        try:
            if row["证券代码"] != symbol.thscode:
                raise invalid("iFinD 返回的股票代码与请求不一致")
            raw_day = str(row["日期"])
            if re.fullmatch(r"\d{8}", raw_day):
                raw_day = f"{raw_day[:4]}-{raw_day[4:6]}-{raw_day[6:]}"
            try:
                day = parse_date(raw_day)
            except MarketError:
                raise invalid("iFinD 返回了无效日期") from None
            if not start <= day <= end:
                raise invalid("iFinD 返回了请求范围之外的日 K")
            if raw_day in seen:
                raise invalid("日 K 日期重复")
            seen.add(raw_day)
            empty = (None, "", "--", "-", "null")
            if not calendar.state(day, symbol.market)["open"]:
                # Observed MCP fill: previous close, blank O/H/L and volume.
                if not all(row.get(f) in empty for f in ("开盘价", "最高价", "最低价", "成交量")):
                    raise invalid("休市日出现了非空交易数据")
                closed_rows += 1
                continue
            if all(row.get(f) in empty for f in ("开盘价", "最高价", "最低价", "成交量")):
                missing_dates.append(raw_day)
                continue
            candle = {key: number(row[field]) for key, field in
                      (("o", "开盘价"), ("h", "最高价"), ("l", "最低价"), ("c", "收盘价"))}
            raw_volume = str(row["成交量"]).strip()
            if not raw_volume.endswith(("股", "手")):
                raw_volume += volume_unit
            candle["v"] = number(raw_volume, "volume")
            if candle["v"] < 0:
                raise invalid("成交量为负")
            # A zero-volume row is not fabricated into a trading candle.
            if candle["v"] == 0:
                skipped += 1
                continue
            if (min(candle[k] for k in ("o", "h", "l", "c")) <= 0
                    or candle["l"] > min(candle["o"], candle["c"])
                    or candle["h"] < max(candle["o"], candle["c"])):
                raise invalid("日 K 高低价关系异常")
            if raw_day in records:
                raise invalid("日 K 日期重复")
            records[raw_day] = candle
            if not isinstance(row["证券简称"], str) or not row["证券简称"].strip():
                raise invalid("证券简称缺失")
            name = row["证券简称"]
        except (KeyError, TypeError, AttributeError):
            raise invalid() from None
    dates = sorted(records)
    return {"name": name, "DATES": dates, "candles": [records[d] for d in dates],
            "skippedZeroVolume": skipped, "skippedNonTrading": closed_rows,
            "missingPriceDates": missing_dates}


def parse_quotes(data: dict, symbols: list[StockCode]) -> list[dict]:
    requested = {symbol.thscode: symbol for symbol in symbols}
    found = {}
    for row in _rows(data):
        try:
            code = row["证券代码"]
            if code not in requested or code in found:
                raise invalid("行情股票代码缺失、重复或与请求不一致")
            px = number(row["最新价"])
            chg = number(row["涨跌幅"])
            if px <= 0:
                raise invalid("最新价无效")
            stamp = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)
            symbol = requested[code]
            if not isinstance(row["证券简称"], str) or not row["证券简称"].strip():
                raise invalid("证券简称缺失")
            found[code] = {"code": symbol.code, "name": row["证券简称"], "px": px, "chg": chg,
                           "market": symbol.market, "asOf": stamp.isoformat(),
                           "source": "iFinD MCP", "priceUnit": "CNY", "chgUnit": "%"}
        except (KeyError, TypeError, ValueError):
            raise invalid() from None
    if set(found) != set(requested):
        raise MarketError("IFIND_NO_DATA", "部分股票没有最新行情，请单独查询或核实股票状态", 404)
    return [found[symbol.thscode] for symbol in symbols]
