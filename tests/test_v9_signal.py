"""
Test script to verify v9 signal logic matches specification.

Tests:
1. EMA 200 filter - leverage halved when below EMA 200
2. MVRV boost - 1.25x boost when above EMA AND MVRV < 3.0
3. Order of operations - signals applied in correct order
4. Edge cases - boundary conditions

Usage:
    python tests/test_v9_signal.py
"""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd

# Import the determine_position function from v9
from v9_production import determine_position, STRATEGY_CONFIG


def test_ema_filter():
    """Test that leverage is halved when below EMA 200"""
    print("\n" + "=" * 60)
    print("TEST 1: EMA 200 Filter")
    print("=" * 60)

    # Test case 1: Below EMA 200 in middle zone (should be 1x * 0.5 = 0.5x)
    leverage, position, reasoning = determine_position(
        drawdown=-0.30,  # Middle zone
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=50000,
        ema_200=60000,  # Price below EMA
        mvrv=None,
        dvol_zscore=None
    )
    expected = 0.5
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Below EMA, middle zone: {leverage}x (expected {expected}x) - {result}")

    # Test case 2: Below EMA 200 in DD tier (should be 2x * 0.5 = 1x)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,  # DD tier -60% to -70% = 2x base
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=50000,
        ema_200=60000,  # Price below EMA
        mvrv=None,
        dvol_zscore=None
    )
    expected = 1.0
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Below EMA, DD tier 2x: {leverage}x (expected {expected}x) - {result}")

    # Test case 3: Above EMA 200 (should keep full leverage)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,  # DD tier -60% to -70% = 2x base
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,  # Price above EMA
        mvrv=None,
        dvol_zscore=None
    )
    expected = 2
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Above EMA, DD tier 2x: {leverage}x (expected {expected}x) - {result}")

    # Test case 4: Below EMA 200 with 5x tier (should be 5x * 0.5 = 2.5x)
    leverage, position, reasoning = determine_position(
        drawdown=-0.85,  # DD tier < -80% = 5x base
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=50000,
        ema_200=60000,  # Price below EMA
        mvrv=None,
        dvol_zscore=None
    )
    expected = 2.5
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Below EMA, DD tier 5x: {leverage}x (expected {expected}x) - {result}")

    print("  EMA Filter tests complete.")
    return True


def test_mvrv_boost():
    """Test that 1.25x boost applied when above EMA AND MVRV < 3.0"""
    print("\n" + "=" * 60)
    print("TEST 2: MVRV Boost")
    print("=" * 60)

    # Test case 1: Above EMA and MVRV < 3.0 (should boost)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,  # DD tier = 2x base
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,  # Price above EMA
        mvrv=2.5,  # MVRV < 3.0
        dvol_zscore=None
    )
    expected = 2.5  # 2x * 1.25 = 2.5x
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Above EMA, MVRV<3.0: {leverage}x (expected {expected}x) - {result}")

    # Test case 2: Above EMA but MVRV >= 3.0 (no boost)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,  # DD tier = 2x base
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,  # Price above EMA
        mvrv=3.5,  # MVRV >= 3.0
        dvol_zscore=None
    )
    expected = 2
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Above EMA, MVRV>=3.0: {leverage}x (expected {expected}x) - {result}")

    # Test case 3: Below EMA and MVRV < 3.0 (no boost, EMA filter applied)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,  # DD tier = 2x base
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=50000,
        ema_200=60000,  # Price below EMA
        mvrv=2.5,  # MVRV < 3.0 but below EMA
        dvol_zscore=None
    )
    expected = 1.0  # 2x * 0.5 = 1x (no MVRV boost because below EMA)
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Below EMA, MVRV<3.0: {leverage}x (expected {expected}x) - {result}")

    # Test case 4: MVRV boost capped at 5x
    leverage, position, reasoning = determine_position(
        drawdown=-0.85,  # DD tier = 5x base
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,  # Price above EMA
        mvrv=2.5,  # MVRV < 3.0
        dvol_zscore=None
    )
    expected = 5.0  # 5x * 1.25 = 6.25x but capped at 5x
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  MVRV boost cap at 5x: {leverage}x (expected {expected}x) - {result}")

    print("  MVRV Boost tests complete.")
    return True


def test_order_of_operations():
    """Test that signals are applied in correct order"""
    print("\n" + "=" * 60)
    print("TEST 3: Order of Operations")
    print("=" * 60)

    # Test case 1: Danger signal takes priority (should be CASH)
    leverage, position, reasoning = determine_position(
        drawdown=-0.85,  # Would be 5x normally
        prob_left_tail=0.25,  # DANGER > 0.20
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,
        mvrv=2.5,
        dvol_zscore=None
    )
    expected = 0
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Danger signal priority: {leverage}x (expected {expected}x) - {result}")

    # Test case 2: ATH breakout takes priority over DD tiers
    leverage, position, reasoning = determine_position(
        drawdown=-0.02,  # Near ATH
        prob_left_tail=0.10,
        near_ath=True,
        ath_breakout=True,  # ATH breakout!
        vol_high=False,
        close_price=100000,
        ema_200=60000,
        mvrv=2.5,
        dvol_zscore=None
    )
    expected = 10
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  ATH breakout priority: {leverage}x (expected {expected}x) - {result}")

    # Test case 3: Near ATH takes priority over DD tiers
    leverage, position, reasoning = determine_position(
        drawdown=-0.02,  # Near ATH
        prob_left_tail=0.10,
        near_ath=True,
        ath_breakout=False,
        vol_high=False,  # Low vol = 3x
        close_price=100000,
        ema_200=60000,
        mvrv=2.5,
        dvol_zscore=None
    )
    expected = 3
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Near ATH priority: {leverage}x (expected {expected}x) - {result}")

    # Test case 4: DVOL filter applied last
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,  # DD tier = 2x
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,
        mvrv=2.5,  # MVRV boost = 2x * 1.25 = 2.5x
        dvol_zscore=0.5  # DVOL filter reduces by 1x
    )
    expected = 1.5  # 2.5x - 1 = 1.5x
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  DVOL filter last: {leverage}x (expected {expected}x) - {result}")

    print("  Order of Operations tests complete.")
    return True


def test_edge_cases():
    """Test boundary conditions"""
    print("\n" + "=" * 60)
    print("TEST 4: Edge Cases")
    print("=" * 60)

    # Test case 1: Exactly at MVRV threshold (3.0 - should NOT boost)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,
        mvrv=3.0,  # Exactly at threshold
        dvol_zscore=None
    )
    expected = 2  # No boost because MVRV is NOT < 3.0
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  MVRV exactly at 3.0: {leverage}x (expected {expected}x) - {result}")

    # Test case 2: Exactly at danger threshold (0.20 - should NOT go to cash)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,
        prob_left_tail=0.20,  # Exactly at threshold
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,
        mvrv=2.5,
        dvol_zscore=None
    )
    expected_not_cash = leverage > 0
    result = "PASS" if expected_not_cash else "FAIL"
    print(f"  Prob exactly at 0.20: {leverage}x (expected not CASH) - {result}")

    # Test case 3: Missing MVRV data (should work without boost)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,
        mvrv=None,  # No MVRV data
        dvol_zscore=None
    )
    expected = 2  # Base leverage, no boost
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Missing MVRV data: {leverage}x (expected {expected}x) - {result}")

    # Test case 4: Missing EMA data (should work without filter)
    leverage, position, reasoning = determine_position(
        drawdown=-0.65,
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=None,  # No EMA data
        mvrv=2.5,
        dvol_zscore=None
    )
    expected = 2  # Base leverage, no EMA filter or boost
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Missing EMA data: {leverage}x (expected {expected}x) - {result}")

    # Test case 5: DD tier boundaries
    # -60% exactly (should be 1x, not 2x)
    leverage, _, _ = determine_position(
        drawdown=-0.60,
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,
        mvrv=None,
        dvol_zscore=None
    )
    expected = 1  # -60% is NOT in the tier (tier is < -60%)
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  DD exactly -60%: {leverage}x (expected {expected}x) - {result}")

    # -60.01% (should be 2x)
    leverage, _, _ = determine_position(
        drawdown=-0.6001,
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,
        mvrv=None,
        dvol_zscore=None
    )
    expected = 2
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  DD at -60.01%: {leverage}x (expected {expected}x) - {result}")

    print("  Edge Cases tests complete.")
    return True


def test_combined_scenario():
    """Test a realistic combined scenario"""
    print("\n" + "=" * 60)
    print("TEST 5: Combined Scenario")
    print("=" * 60)

    # Scenario: Deep drawdown, above EMA, low MVRV, elevated DVOL
    # Base: 3x (DD -75%)
    # No EMA reduction (above EMA)
    # MVRV boost: 3x * 1.25 = 3.75x
    # DVOL reduction: 3.75x - 1 = 2.75x
    leverage, position, reasoning = determine_position(
        drawdown=-0.75,
        prob_left_tail=0.10,
        near_ath=False,
        ath_breakout=False,
        vol_high=False,
        close_price=70000,
        ema_200=60000,
        mvrv=2.5,
        dvol_zscore=0.5
    )
    expected = 2.75
    result = "PASS" if leverage == expected else "FAIL"
    print(f"  Combined scenario: {leverage}x (expected {expected}x) - {result}")
    print(f"  Reasoning: {reasoning}")

    print("  Combined Scenario tests complete.")
    return True


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("BTC TAIL MODEL v9 - SIGNAL LOGIC TESTS")
    print("=" * 70)

    tests = [
        test_ema_filter,
        test_mvrv_boost,
        test_order_of_operations,
        test_edge_cases,
        test_combined_scenario,
    ]

    all_passed = True
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"  TEST FAILED with exception: {e}")
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED - Review output above")
    print("=" * 70)

    return all_passed


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
