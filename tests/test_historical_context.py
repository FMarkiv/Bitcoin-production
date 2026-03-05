"""
Test script for historical context module.
Run with: python tests/test_historical_context.py
"""

import sys
sys.path.insert(0, 'src')

import pandas as pd
import numpy as np
from historical_context import get_historical_context, generate_historical_chart


def test_basic_functionality():
    """Test that historical context returns expected structure"""
    dates = pd.date_range('2015-01-01', '2025-01-01', freq='D')
    np.random.seed(42)

    returns = np.random.normal(0.001, 0.03, len(dates))
    prices = 1000 * np.exp(np.cumsum(returns))

    df = pd.DataFrame({
        'date': dates,
        'close': prices
    })

    result = get_historical_context(-0.40, df)

    assert 'dd_bucket' in result
    assert 'sample_size' in result
    assert 'avg_1y_return' in result
    assert 'win_rate_1y' in result

    print(f"  Basic functionality test passed")
    print(f"  Bucket: {result['dd_bucket']}")
    print(f"  Sample size: {result['sample_size']}")

    return result


def test_chart_generation():
    """Test that chart generates without errors"""
    dates = pd.date_range('2015-01-01', '2025-01-01', freq='D')
    np.random.seed(42)
    returns = np.random.normal(0.001, 0.03, len(dates))
    prices = 1000 * np.exp(np.cumsum(returns))

    df = pd.DataFrame({
        'date': dates,
        'close': prices
    })

    context = get_historical_context(-0.40, df)
    chart_path = generate_historical_chart(-0.40, context, 'test_chart.png')

    import os
    assert os.path.exists(chart_path)
    print(f"  Chart generation test passed")
    print(f"  Chart saved to: {chart_path}")

    os.remove(chart_path)


def test_edge_cases():
    """Test edge cases"""
    dates = pd.date_range('2020-01-01', '2025-01-01', freq='D')
    prices = np.linspace(10000, 50000, len(dates))  # Steady uptrend

    df = pd.DataFrame({
        'date': dates,
        'close': prices
    })

    # Test near ATH (should have limited data)
    result = get_historical_context(-0.02, df)
    print(f"  Edge case test passed (near ATH)")
    print(f"  Sample size at -2% DD: {result['sample_size']}")

    # Test extreme drawdown
    result = get_historical_context(-0.85, df)
    print(f"  Edge case test passed (extreme DD)")
    print(f"  Sample size at -85% DD: {result['sample_size']}")


def test_with_real_data():
    """Test with actual BTC data if available"""
    try:
        df = pd.read_csv('data/BTC.csv')
        # Handle different column naming conventions
        if 'Start' in df.columns:
            df = df.rename(columns={'Start': 'date', 'Close': 'close'})
        df['date'] = pd.to_datetime(df['date'], dayfirst=True)
        df = df.sort_values('date').reset_index(drop=True)

        result = get_historical_context(-0.42, df)

        print(f"\n  Real BTC Data Test:")
        print(f"   Bucket: {result['dd_bucket']}")
        print(f"   Sample: {result['sample_size']} instances")

        if result['avg_1y_return']:
            print(f"\n   Forward Returns:")
            print(f"   - 1M:  {result['avg_1m_return']*100:+.1f}%")
            print(f"   - 3M:  {result['avg_3m_return']*100:+.1f}%")
            print(f"   - 1Y:  {result['avg_1y_return']*100:+.1f}%")
            print(f"\n   Risk:")
            print(f"   - Avg 1Y DD: {result['avg_1y_max_dd']*100:.1f}%")
            print(f"   - Win Rate:  {result['win_rate_1y']*100:.0f}%")

        chart_path = generate_historical_chart(-0.42, result, 'test_btc_chart.png')
        print(f"\n   Chart saved: {chart_path}")

    except FileNotFoundError:
        print("  Real data test skipped (BTC.csv not found)")


if __name__ == '__main__':
    print("Testing Historical Context Module\n")
    print("=" * 50)

    test_basic_functionality()
    print()
    test_chart_generation()
    print()
    test_edge_cases()
    print()
    test_with_real_data()

    print("\n" + "=" * 50)
    print("All tests passed!")
