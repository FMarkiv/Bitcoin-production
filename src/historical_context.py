"""
Historical context module for BTC Tail Model v10

Provides historical return statistics from similar drawdown levels
to give psychological anchoring during drawdowns.
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pathlib import Path
import json


def get_historical_context(current_drawdown: float, price_data: pd.DataFrame) -> dict:
    """
    Given current drawdown, return historical average returns and drawdowns
    from similar drawdown levels.

    Args:
        current_drawdown: Current drawdown from ATH (e.g., -0.418 for -41.8%)
        price_data: DataFrame with 'close' and 'date' columns

    Returns:
        dict with historical statistics
    """
    # Define drawdown bucket (+/-5% range)
    bucket_size = 0.05
    dd_lower = (current_drawdown // bucket_size) * bucket_size
    dd_upper = dd_lower + bucket_size

    # Calculate drawdown series
    df = price_data.copy()
    df['ath'] = df['close'].cummax()
    df['drawdown'] = (df['close'] - df['ath']) / df['ath']
    df = df.reset_index(drop=True)

    # Find all historical instances in this bucket
    mask = (df['drawdown'] >= dd_lower) & (df['drawdown'] < dd_upper)
    instances = df[mask].index.tolist()

    # Calculate forward returns for each instance
    forward_returns = {
        '1m': [],   # 30 days
        '3m': [],   # 91 days
        '1y': [],   # 365 days
        '2y': [],   # 730 days
    }
    max_further_dd = []

    for idx in instances:
        entry_price = df.loc[idx, 'close']

        if idx + 30 < len(df):
            forward_returns['1m'].append(
                (df.loc[idx + 30, 'close'] / entry_price) - 1
            )
        if idx + 91 < len(df):
            forward_returns['3m'].append(
                (df.loc[idx + 91, 'close'] / entry_price) - 1
            )
        if idx + 365 < len(df):
            forward_returns['1y'].append(
                (df.loc[idx + 365, 'close'] / entry_price) - 1
            )
        if idx + 730 < len(df):
            forward_returns['2y'].append(
                (df.loc[idx + 730, 'close'] / entry_price) - 1
            )

        # Max further drawdown within 1 year
        if idx + 365 < len(df):
            forward_prices = df.loc[idx:idx+365, 'close']
            max_dd = (forward_prices.min() / entry_price) - 1
            max_further_dd.append(max_dd)

    result = {
        'dd_bucket': f"{dd_lower*100:.0f}% to {dd_upper*100:.0f}%",
        'dd_bucket_lower': dd_lower,
        'dd_bucket_upper': dd_upper,
        'sample_size': len(forward_returns['1m']),

        # 1 Month
        'avg_1m_return': np.mean(forward_returns['1m']) if forward_returns['1m'] else None,
        'median_1m_return': np.median(forward_returns['1m']) if forward_returns['1m'] else None,

        # 3 Month
        'avg_3m_return': np.mean(forward_returns['3m']) if forward_returns['3m'] else None,
        'median_3m_return': np.median(forward_returns['3m']) if forward_returns['3m'] else None,

        # 1 Year
        'avg_1y_return': np.mean(forward_returns['1y']) if forward_returns['1y'] else None,
        'median_1y_return': np.median(forward_returns['1y']) if forward_returns['1y'] else None,
        'returns_1y': forward_returns['1y'],

        # 2 Year
        'avg_2y_return': np.mean(forward_returns['2y']) if forward_returns['2y'] else None,

        # Risk metrics
        'avg_1y_max_dd': np.mean(max_further_dd) if max_further_dd else None,
        'worst_1y_max_dd': np.min(max_further_dd) if max_further_dd else None,
        'max_further_dd_list': max_further_dd,

        # Win rates
        'win_rate_1m': np.mean([r > 0 for r in forward_returns['1m']]) if forward_returns['1m'] else None,
        'win_rate_3m': np.mean([r > 0 for r in forward_returns['3m']]) if forward_returns['3m'] else None,
        'win_rate_1y': np.mean([r > 0 for r in forward_returns['1y']]) if forward_returns['1y'] else None,
    }

    return result


def generate_historical_chart(
    current_drawdown: float,
    historical_context: dict,
    output_path: str = 'historical_context.png'
) -> str:
    """
    Generate a chart showing historical return distribution from similar drawdown levels.

    Args:
        current_drawdown: Current drawdown (e.g., -0.418)
        historical_context: Output from get_historical_context()
        output_path: Where to save the chart

    Returns:
        Path to saved chart
    """
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle(
        f"Historical Returns from {historical_context['dd_bucket']} Drawdown\n"
        f"(n={historical_context['sample_size']} instances)",
        fontsize=14,
        fontweight='bold'
    )

    positive_color = '#2ecc71'
    negative_color = '#e74c3c'

    # --- Panel 1: 1-Year Return Distribution ---
    ax1 = axes[0, 0]
    returns_1y = historical_context.get('returns_1y', [])

    if returns_1y and len(returns_1y) >= 5:
        returns_pct = [r * 100 for r in returns_1y]

        n, bins, patches = ax1.hist(returns_pct, bins=20, edgecolor='white', alpha=0.7)
        for i, patch in enumerate(patches):
            if bins[i] >= 0:
                patch.set_facecolor(positive_color)
            else:
                patch.set_facecolor(negative_color)

        avg = historical_context['avg_1y_return'] * 100
        med = historical_context['median_1y_return'] * 100
        ax1.axvline(avg, color='black', linestyle='--', linewidth=2, label=f'Mean: {avg:.1f}%')
        ax1.axvline(med, color='orange', linestyle='-', linewidth=2, label=f'Median: {med:.1f}%')
        ax1.axvline(0, color='gray', linestyle='-', linewidth=1, alpha=0.5)

        ax1.set_xlabel('1-Year Forward Return (%)')
        ax1.set_ylabel('Frequency')
        ax1.set_title('1-Year Return Distribution')
        ax1.legend(loc='upper right')
    else:
        ax1.text(0.5, 0.5, 'Insufficient Data', ha='center', va='center', fontsize=14)
        ax1.set_title('1-Year Return Distribution')

    # --- Panel 2: Max Further Drawdown Distribution ---
    ax2 = axes[0, 1]
    max_dd_list = historical_context.get('max_further_dd_list', [])

    if max_dd_list and len(max_dd_list) >= 5:
        dd_pct = [d * 100 for d in max_dd_list]

        ax2.hist(dd_pct, bins=20, color=negative_color, edgecolor='white', alpha=0.7)

        avg_dd = historical_context['avg_1y_max_dd'] * 100
        worst_dd = historical_context['worst_1y_max_dd'] * 100
        ax2.axvline(avg_dd, color='black', linestyle='--', linewidth=2, label=f'Avg: {avg_dd:.1f}%')
        ax2.axvline(worst_dd, color='darkred', linestyle='-', linewidth=2, label=f'Worst: {worst_dd:.1f}%')

        ax2.set_xlabel('Max Further Drawdown Within 1 Year (%)')
        ax2.set_ylabel('Frequency')
        ax2.set_title('Downside Risk Distribution')
        ax2.legend(loc='upper left')
    else:
        ax2.text(0.5, 0.5, 'Insufficient Data', ha='center', va='center', fontsize=14)
        ax2.set_title('Downside Risk Distribution')

    # --- Panel 3: Average Returns by Horizon ---
    ax3 = axes[1, 0]

    horizons = ['1M', '3M', '1Y', '2Y']
    avg_returns = [
        historical_context.get('avg_1m_return', 0) or 0,
        historical_context.get('avg_3m_return', 0) or 0,
        historical_context.get('avg_1y_return', 0) or 0,
        historical_context.get('avg_2y_return', 0) or 0,
    ]
    avg_returns_pct = [r * 100 for r in avg_returns]

    colors = [positive_color if r >= 0 else negative_color for r in avg_returns_pct]
    bars = ax3.bar(horizons, avg_returns_pct, color=colors, edgecolor='white', alpha=0.8)

    for bar, val in zip(bars, avg_returns_pct):
        height = bar.get_height()
        ax3.annotate(f'{val:+.1f}%',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3 if height >= 0 else -12),
                    textcoords="offset points",
                    ha='center', va='bottom' if height >= 0 else 'top',
                    fontweight='bold')

    ax3.axhline(0, color='gray', linestyle='-', linewidth=1)
    ax3.set_xlabel('Time Horizon')
    ax3.set_ylabel('Average Return (%)')
    ax3.set_title('Average Returns by Horizon')

    # --- Panel 4: Win Rates by Horizon ---
    ax4 = axes[1, 1]

    win_rates = [
        (historical_context.get('win_rate_1m', 0) or 0) * 100,
        (historical_context.get('win_rate_3m', 0) or 0) * 100,
        (historical_context.get('win_rate_1y', 0) or 0) * 100,
    ]

    colors = [positive_color if w >= 50 else negative_color for w in win_rates]
    bars = ax4.bar(['1M', '3M', '1Y'], win_rates, color=colors, edgecolor='white', alpha=0.8)

    for bar, val in zip(bars, win_rates):
        height = bar.get_height()
        ax4.annotate(f'{val:.0f}%',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha='center', va='bottom',
                    fontweight='bold')

    ax4.axhline(50, color='gray', linestyle='--', linewidth=1, label='50% (coin flip)')
    ax4.set_xlabel('Time Horizon')
    ax4.set_ylabel('Win Rate (%)')
    ax4.set_title('Historical Win Rates (% Positive)')
    ax4.set_ylim(0, 100)
    ax4.legend(loc='lower right')

    # --- Footer ---
    fig.text(
        0.5, 0.02,
        f"Current Drawdown: {current_drawdown*100:.1f}% | "
        f"Historical 1Y Avg: {(historical_context.get('avg_1y_return', 0) or 0)*100:+.1f}% | "
        f"Win Rate: {(historical_context.get('win_rate_1y', 0) or 0)*100:.0f}% | "
        f"Avg Further DD: {(historical_context.get('avg_1y_max_dd', 0) or 0)*100:.1f}%",
        ha='center',
        fontsize=11,
        style='italic',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5)
    )

    plt.tight_layout(rect=[0, 0.05, 1, 0.95])
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    return output_path


def build_lookup_table(price_data: pd.DataFrame, output_path: str = 'data/historical_lookup.json') -> dict:
    """
    Pre-compute historical stats for all drawdown buckets.
    Run once and cache for faster lookups.
    """
    buckets = np.arange(-0.95, 0.05, 0.05)
    lookup = {}

    for dd_lower in buckets:
        bucket_key = f"{dd_lower:.2f}"
        context = get_historical_context(dd_lower + 0.025, price_data)

        # Remove raw lists to save space
        context_clean = {k: v for k, v in context.items()
                        if not isinstance(v, list)}
        lookup[bucket_key] = context_clean

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(lookup, f, indent=2)

    return lookup


if __name__ == '__main__':
    import sys

    df = pd.read_csv('data/BTC.csv', parse_dates=['date'])

    test_dd = float(sys.argv[1]) if len(sys.argv) > 1 else -0.42

    print(f"Testing historical context at {test_dd*100:.1f}% drawdown...")

    context = get_historical_context(test_dd, df)

    print(f"\nHistorical Context: {context['dd_bucket']}")
    print(f"   Sample Size: {context['sample_size']}")
    print(f"\n   Average Returns:")
    print(f"   - 1M:  {context['avg_1m_return']*100:+.1f}%" if context['avg_1m_return'] else "   - 1M:  N/A")
    print(f"   - 3M:  {context['avg_3m_return']*100:+.1f}%" if context['avg_3m_return'] else "   - 3M:  N/A")
    print(f"   - 1Y:  {context['avg_1y_return']*100:+.1f}%" if context['avg_1y_return'] else "   - 1Y:  N/A")
    print(f"   - 2Y:  {context['avg_2y_return']*100:+.1f}%" if context['avg_2y_return'] else "   - 2Y:  N/A")
    print(f"\n   Risk Metrics:")
    print(f"   - Avg 1Y Max DD:   {context['avg_1y_max_dd']*100:.1f}%" if context['avg_1y_max_dd'] else "   - Avg 1Y Max DD: N/A")
    print(f"   - Worst 1Y Max DD: {context['worst_1y_max_dd']*100:.1f}%" if context['worst_1y_max_dd'] else "   - Worst 1Y Max DD: N/A")
    print(f"\n   Win Rates:")
    print(f"   - 1Y: {context['win_rate_1y']*100:.0f}%" if context['win_rate_1y'] else "   - 1Y: N/A")

    chart_path = generate_historical_chart(test_dd, context, 'test_historical_chart.png')
    print(f"\nChart saved to: {chart_path}")
