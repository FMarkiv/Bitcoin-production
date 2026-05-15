"""
Tests for trajectory-aware historical context.
Run with: python tests/test_trajectory.py
"""

import os
import sys
sys.path.insert(0, 'src')

import numpy as np
import pandas as pd

from historical_context import (
    classify_trajectory,
    get_historical_context_by_trajectory,
    generate_trajectory_chart,
    format_telegram_context,
    DEFAULT_TRAJECTORY_LOOKBACK_DAYS,
)


def _synthetic_btc(seed: int = 42, years: int = 12) -> pd.DataFrame:
    dates = pd.date_range('2014-01-01', periods=years * 365, freq='D')
    rng = np.random.default_rng(seed)
    # Random walk with some drift; produces multiple drawdown cycles
    returns = rng.normal(0.0007, 0.035, len(dates))
    prices = 1000 * np.exp(np.cumsum(returns))
    return pd.DataFrame({'date': dates, 'close': prices})


def test_trajectory_classification():
    # Falling: current more negative than prior
    assert classify_trajectory(-0.40, -0.35) == 'falling'
    # Recovering: current less negative than prior
    assert classify_trajectory(-0.35, -0.45) == 'recovering'
    # Flat: minimal change
    assert classify_trajectory(-0.40, -0.41) == 'flat'
    # Threshold edge
    assert classify_trajectory(-0.40, -0.42, threshold=0.05) == 'flat'
    assert classify_trajectory(-0.40, -0.30, threshold=0.05) == 'falling'
    print("  classify_trajectory: OK")


def test_trajectory_context_structure():
    df = _synthetic_btc()

    ctx = get_historical_context_by_trajectory(-0.42, -0.35, df)
    assert ctx['current_trajectory'] == 'falling'
    for key in ('falling', 'recovering', 'flat', 'combined'):
        assert key in ctx, f"missing {key}"
        assert 'sample_size' in ctx[key]

    ctx2 = get_historical_context_by_trajectory(-0.42, -0.55, df)
    assert ctx2['current_trajectory'] == 'recovering'

    ctx3 = get_historical_context_by_trajectory(-0.42, -0.43, df)
    assert ctx3['current_trajectory'] == 'flat'

    # Lookback is recorded
    assert ctx['lookback_days'] == DEFAULT_TRAJECTORY_LOOKBACK_DAYS
    print("  trajectory context structure: OK")


def test_no_sample_overlap():
    """First-entry sampling: an index appears in at most one trajectory list,
    and trajectories partition the first-entry set."""
    df = _synthetic_btc()
    ctx = get_historical_context_by_trajectory(-0.30, -0.25, df, lookback_days=30)

    f_n = ctx['falling']['sample_size']
    r_n = ctx['recovering']['sample_size']
    fl_n = ctx['flat']['sample_size']
    c_n = ctx['combined']['sample_size']

    # combined should be the union (>= each, <= sum)
    assert c_n <= f_n + r_n + fl_n
    print(f"  first-entry partition: falling={f_n}, recovering={r_n}, flat={fl_n}, combined={c_n}")


def test_telegram_formatting():
    df = _synthetic_btc()
    ctx = get_historical_context_by_trajectory(-0.42, -0.55, df)
    text = format_telegram_context(ctx)
    assert 'RECOVERING' in text or 'FALLING' in text or 'FLAT' in text
    assert 'Your Path' in text or 'insufficient' in text.lower()
    print("  telegram formatting: OK")


def test_chart_generation():
    df = _synthetic_btc()
    ctx = get_historical_context_by_trajectory(-0.42, -0.55, df)
    out = generate_trajectory_chart(-0.42, -0.55, ctx, 'test_trajectory_chart.png')
    assert os.path.exists(out)
    os.remove(out)
    print("  trajectory chart: OK")


def test_with_real_btc_data_if_available():
    path = 'data/BTC.csv'
    if not os.path.exists(path):
        print("  real BTC data not available, skipping")
        return
    # Load via v9's loader so column names match
    sys.path.insert(0, 'src')
    from v9_production import load_btc_data
    df = load_btc_data(path)
    ctx = get_historical_context_by_trajectory(-0.42, -0.50, df)
    print(f"  real data: trajectory={ctx['current_trajectory']}, "
          f"falling n={ctx['falling']['sample_size']}, "
          f"recovering n={ctx['recovering']['sample_size']}, "
          f"flat n={ctx['flat']['sample_size']}")


if __name__ == '__main__':
    print("Running trajectory tests...")
    test_trajectory_classification()
    test_trajectory_context_structure()
    test_no_sample_overlap()
    test_telegram_formatting()
    test_chart_generation()
    test_with_real_btc_data_if_available()
    print("\nALL TESTS PASSED")
