"""底层资产的行业集中度警示（issue 05）。"""

from app.advisory.concentration import CODE_INDUSTRY_CONCENTRATION, concentration_warnings

DIVERSIFIED = [
    {"industry": "科技", "market_value": "3000.00", "share": "0.30"},
    {"industry": "利率债", "market_value": "3500.00", "share": "0.35"},
    {"industry": "货币市场", "market_value": "3500.00", "share": "0.35"},
]

CONCENTRATED = [
    {"industry": "科技", "market_value": "5000.00", "share": "0.50"},
    {"industry": "利率债", "market_value": "5000.00", "share": "0.50"},
]

EXACTLY_AT_THRESHOLD = [{"industry": "科技", "market_value": "4000.00", "share": "0.40"}]


def test_no_industry_exceeds_the_threshold_produces_no_warning():
    assert concentration_warnings(DIVERSIFIED) == []


def test_an_industry_above_the_threshold_produces_a_warning_naming_it():
    warnings = concentration_warnings(CONCENTRATED)
    codes = {w["code"] for w in warnings}
    assert codes == {CODE_INDUSTRY_CONCENTRATION}
    assert "科技" in warnings[0]["message"]
    assert "50.0" in warnings[0]["message"]


def test_being_exactly_at_the_threshold_does_not_trigger_a_warning():
    assert concentration_warnings(EXACTLY_AT_THRESHOLD) == []


def test_multiple_industries_above_the_threshold_each_produce_their_own_warning():
    warnings = concentration_warnings(CONCENTRATED)
    industries = {w["message"].split("「")[1].split("」")[0] for w in warnings}
    assert industries == {"科技", "利率债"}


def test_no_exposure_data_produces_no_warning():
    assert concentration_warnings([]) == []
