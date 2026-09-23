import pytest

from modules.market.errors import MarketError
from modules.market.symbols import normalize_code


@pytest.mark.parametrize("raw,code,market,thscode", [
    ("300750", "300750", "SZSE", "300750.SZ"),
    ("600519", "600519", "SSE", "600519.SH"),
    (" 688981.sh ", "688981", "SSE", "688981.SH"),
    ("000001.SZ", "000001", "SZSE", "000001.SZ"),
])
def test_normalization(raw, code, market, thscode):
    result = normalize_code(raw)
    assert (result.code, result.market, result.thscode) == (code, market, thscode)


@pytest.mark.parametrize("raw", ["HK1177", "HK3690", "01177.HK", "920001.BJ", "510300", "399001", "000001.SH", "300750.SH", "600519.SZ", "bad", "1", ""])
def test_unsupported_or_invalid_codes_are_rejected(raw):
    with pytest.raises(MarketError):
        normalize_code(raw)
