"""Normalize supported mainland equity codes without changing UI field names."""

import re
from dataclasses import dataclass

from .errors import MarketError


@dataclass(frozen=True)
class StockCode:
    code: str
    market: str
    thscode: str


def normalize_code(value: str) -> StockCode:
    text = value.strip().upper()
    if text.startswith("HK") or text.endswith((".HK", ".BJ")):
        raise MarketError("UNSUPPORTED_MARKET", "仅支持沪深 A 股，不支持港股或北交所股票")
    match = re.fullmatch(r"(\d{6})(?:\.(SH|SZ))?", text)
    if not match:
        raise MarketError("INVALID_CODE", "股票代码须为六位数字，可附 .SH 或 .SZ 后缀")
    code, suffix = match.groups()
    if code.startswith(("600", "601", "603", "605", "688")):
        expected, market = "SH", "SSE"
    elif code.startswith(("000", "001", "002", "003", "300", "301")):
        expected, market = "SZ", "SZSE"
    else:
        raise MarketError("UNSUPPORTED_SECURITY", "当前仅支持沪深 A 股代码，不支持指数、基金或其他市场")
    if suffix and suffix != expected:
        raise MarketError("CODE_MARKET_MISMATCH", "股票代码与交易所后缀不匹配")
    return StockCode(code=code, market=market, thscode=f"{code}.{expected}")
