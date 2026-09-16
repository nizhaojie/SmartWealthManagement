"""资产配置比例建议：以画像目标配置为基线，按生成侧重做结构化调整。"""

import pytest

from app.advisory.allocation import suggest_allocation
from app.advisory.scoring import TILT_BALANCED, TILT_LIQUIDITY, TILT_RETURN

TARGET_ALLOCATION = {"股票": 40, "债券": 35, "现金": 15, "另类": 10}


def test_balanced_tilt_leaves_the_target_allocation_unchanged():
    suggestion = suggest_allocation(TARGET_ALLOCATION, TILT_BALANCED)
    assert suggestion == {"股票": 40.0, "债券": 35.0, "现金": 15.0, "另类": 10.0}


def test_return_tilt_raises_the_equity_share():
    suggestion = suggest_allocation(TARGET_ALLOCATION, TILT_RETURN)
    assert suggestion["股票"] == pytest.approx(50.0, abs=0.02)
    assert suggestion["现金"] < 15.0


def test_liquidity_tilt_raises_the_cash_share():
    suggestion = suggest_allocation(TARGET_ALLOCATION, TILT_LIQUIDITY)
    assert suggestion["现金"] == pytest.approx(25.0, abs=0.02)
    assert suggestion["股票"] < 40.0


def test_every_tilt_still_sums_to_one_hundred():
    for tilt in (TILT_BALANCED, TILT_RETURN, TILT_LIQUIDITY):
        suggestion = suggest_allocation(TARGET_ALLOCATION, tilt)
        assert round(sum(suggestion.values()), 2) == 100.0


def test_category_order_is_preserved_for_comparison_with_the_target():
    suggestion = suggest_allocation(TARGET_ALLOCATION, TILT_RETURN)
    assert list(suggestion.keys()) == list(TARGET_ALLOCATION.keys())


def test_shift_is_capped_at_one_hundred_percent_when_already_dominant():
    dominant = {"股票": 95, "债券": 5, "现金": 0, "另类": 0}
    suggestion = suggest_allocation(dominant, TILT_RETURN)
    assert suggestion["股票"] == 100.0
    assert round(sum(suggestion.values()), 2) == 100.0
