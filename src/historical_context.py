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

# Trajectory-awareness defaults. The lookback window is best chosen
# empirically (see docs/trajectory_lookback_sweep_prompt.md). 30d is a
# starting gut-feel value; change here to update both stats generation
# and the live signal call site.
DEFAULT_TRAJECTORY_LOOKBACK_DAYS = 30
DEFAULT_TRAJECTORY_THRESHOLD = 0.03


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


def classify_trajectory(
    current_dd: float,
    prior_dd: float,
    threshold: float = DEFAULT_TRAJECTORY_THRESHOLD,
) -> str:
    """
    Classify whether we are falling, recovering, or flat relative to
    a prior reference drawdown.

    Drawdowns are negative numbers (e.g. -0.40 means -40% from ATH).
    current_dd more negative than prior_dd => falling (deepening DD).
    current_dd less negative than prior_dd => recovering (shallower DD).
    """
    change = current_dd - prior_dd
    if change < -threshold:
        return 'falling'
    if change > threshold:
        return 'recovering'
    return 'flat'


def _empty_traj_stats() -> dict:
    return {
        'sample_size': 0,
        'avg_1m_return': None,
        'avg_3m_return': None,
        'avg_1y_return': None,
        'avg_2y_return': None,
        'median_1y_return': None,
        'avg_1y_max_dd': None,
        'worst_1y_max_dd': None,
        'win_rate_1m': None,
        'win_rate_3m': None,
        'win_rate_1y': None,
        'returns_1y': [],
        'max_dd_list': [],
    }


def _compute_traj_stats(df: pd.DataFrame, indices: list) -> dict:
    if not indices:
        return _empty_traj_stats()

    r1m, r3m, r1y, r2y, max_dd = [], [], [], [], []
    for idx in indices:
        entry_price = df.loc[idx, 'close']
        if idx + 30 < len(df):
            r1m.append(df.loc[idx + 30, 'close'] / entry_price - 1)
        if idx + 91 < len(df):
            r3m.append(df.loc[idx + 91, 'close'] / entry_price - 1)
        if idx + 365 < len(df):
            r1y.append(df.loc[idx + 365, 'close'] / entry_price - 1)
            forward_prices = df.loc[idx:idx + 365, 'close']
            max_dd.append(forward_prices.min() / entry_price - 1)
        if idx + 730 < len(df):
            r2y.append(df.loc[idx + 730, 'close'] / entry_price - 1)

    return {
        'sample_size': len(r1y) if r1y else len(r1m),
        'avg_1m_return': float(np.mean(r1m)) if r1m else None,
        'avg_3m_return': float(np.mean(r3m)) if r3m else None,
        'avg_1y_return': float(np.mean(r1y)) if r1y else None,
        'avg_2y_return': float(np.mean(r2y)) if r2y else None,
        'median_1y_return': float(np.median(r1y)) if r1y else None,
        'avg_1y_max_dd': float(np.mean(max_dd)) if max_dd else None,
        'worst_1y_max_dd': float(np.min(max_dd)) if max_dd else None,
        'win_rate_1m': float(np.mean([r > 0 for r in r1m])) if r1m else None,
        'win_rate_3m': float(np.mean([r > 0 for r in r3m])) if r3m else None,
        'win_rate_1y': float(np.mean([r > 0 for r in r1y])) if r1y else None,
        'returns_1y': r1y,
        'max_dd_list': max_dd,
    }


def get_historical_context_by_trajectory(
    current_drawdown: float,
    prior_drawdown: float,
    price_data: pd.DataFrame,
    lookback_days: int = DEFAULT_TRAJECTORY_LOOKBACK_DAYS,
    threshold: float = DEFAULT_TRAJECTORY_THRESHOLD,
) -> dict:
    """
    Trajectory-aware version of get_historical_context.

    Instead of pooling every historical day inside the drawdown bucket,
    this counts only first-entry days (days when drawdown crossed into
    the bucket from outside) so samples do not overlap. Each first-entry
    is classified as falling/recovering/flat by comparing its drawdown
    to the drawdown lookback_days earlier, and stats are computed per
    trajectory.
    """
    bucket_size = 0.05
    dd_lower = (current_drawdown // bucket_size) * bucket_size
    dd_upper = dd_lower + bucket_size

    df = price_data.copy()
    df['ath'] = df['close'].cummax()
    df['drawdown'] = (df['close'] - df['ath']) / df['ath']
    df = df.reset_index(drop=True)

    in_bucket = (df['drawdown'] >= dd_lower) & (df['drawdown'] < dd_upper)
    prev_in_bucket = in_bucket.shift(1, fill_value=False)
    first_entry_mask = in_bucket & ~prev_in_bucket

    first_entries = [i for i in df.index[first_entry_mask].tolist() if i >= lookback_days]

    by_traj = {'falling': [], 'recovering': [], 'flat': []}
    for idx in first_entries:
        entry_dd = float(df.loc[idx, 'drawdown'])
        prior_dd_at_idx = float(df.loc[idx - lookback_days, 'drawdown'])
        traj = classify_trajectory(entry_dd, prior_dd_at_idx, threshold)
        by_traj[traj].append(idx)

    current_trajectory = classify_trajectory(current_drawdown, prior_drawdown, threshold)
    combined_indices = by_traj['falling'] + by_traj['recovering'] + by_traj['flat']

    return {
        'dd_bucket': f"{dd_lower*100:.0f}% to {dd_upper*100:.0f}%",
        'dd_bucket_lower': float(dd_lower),
        'dd_bucket_upper': float(dd_upper),
        'current_drawdown': float(current_drawdown),
        'prior_drawdown': float(prior_drawdown),
        'current_trajectory': current_trajectory,
        'lookback_days': lookback_days,
        'threshold': threshold,
        'falling': _compute_traj_stats(df, by_traj['falling']),
        'recovering': _compute_traj_stats(df, by_traj['recovering']),
        'flat': _compute_traj_stats(df, by_traj['flat']),
        'combined': _compute_traj_stats(df, combined_indices),
    }


_TRAJ_EMOJI = {
    'falling': '\U0001f4c9',     # red chart down
    'recovering': '\U0001f4c8',  # green chart up
    'flat': '➡️',       # right arrow
}


def _fmt_pct(v, sign=True):
    if v is None:
        return 'N/A'
    return f"{v*100:+.1f}%" if sign else f"{v*100:.1f}%"


def _fmt_traj_line(label: str, traj: str, stats: dict, is_current: bool) -> str:
    emoji = _TRAJ_EMOJI[traj]
    n = stats.get('sample_size', 0) or 0
    if n < 5:
        return f"↳ {label} {emoji}: insufficient data (n={n})"

    parts = []
    if stats.get('avg_1m_return') is not None:
        parts.append(f"1M: {_fmt_pct(stats['avg_1m_return'])}")
    if stats.get('avg_3m_return') is not None:
        parts.append(f"3M: {_fmt_pct(stats['avg_3m_return'])}")
    if stats.get('avg_1y_return') is not None:
        parts.append(f"1Y: {_fmt_pct(stats['avg_1y_return'])}")
    if stats.get('win_rate_1y') is not None:
        parts.append(f"Win: {stats['win_rate_1y']*100:.0f}%")

    prefix = "<b>Your Path</b>" if is_current else label
    return f"↳ {prefix} ({traj.capitalize()}) {emoji} [n={n}]: " + ' | '.join(parts)


def format_telegram_context(context: dict) -> str:
    """
    Format trajectory-aware historical context for Telegram (HTML).

    Shows the current trajectory as "Your Path" plus the alternative
    trajectories for comparison. When current is flat, all three are
    shown; otherwise the current trajectory plus the opposite one.
    """
    if not context:
        return "↳ Historical context unavailable"

    bucket = context.get('dd_bucket', 'N/A')
    current_traj = context.get('current_trajectory', 'flat')
    cur_emoji = _TRAJ_EMOJI[current_traj]
    prior_dd = context.get('prior_drawdown')
    cur_dd = context.get('current_drawdown')

    header = (
        f"\U0001f4ca <b>Historical Context ({bucket})</b> - "
        f"{current_traj.upper()} {cur_emoji}"
    )
    sub = (
        f"↳ <i>Prior: {_fmt_pct(prior_dd, sign=False)} → "
        f"Now: {_fmt_pct(cur_dd, sign=False)} "
        f"(lookback {context.get('lookback_days', 0)}d)</i>"
    )

    if current_traj == 'flat':
        order = ['flat', 'falling', 'recovering']
    elif current_traj == 'falling':
        order = ['falling', 'recovering']
    else:
        order = ['recovering', 'falling']

    lines = [header, sub]
    for traj in order:
        is_cur = (traj == current_traj)
        lines.append(_fmt_traj_line(
            label='If ' + traj.capitalize() if not is_cur else 'Your Path',
            traj=traj,
            stats=context.get(traj, _empty_traj_stats()),
            is_current=is_cur,
        ))

    # Risk row from the current trajectory's stats (fallback to combined)
    risk_src = context.get(current_traj) or {}
    if (risk_src.get('sample_size') or 0) < 5:
        risk_src = context.get('combined') or {}
    avg_dd = risk_src.get('avg_1y_max_dd')
    worst_dd = risk_src.get('worst_1y_max_dd')
    risk_parts = []
    if avg_dd is not None:
        risk_parts.append(f"Avg Further DD: {_fmt_pct(avg_dd, sign=False)}")
    if worst_dd is not None:
        risk_parts.append(f"Worst: {_fmt_pct(worst_dd, sign=False)}")
    if risk_parts:
        lines.append("↳ <b>Risk:</b> " + ' | '.join(risk_parts))

    return '\n'.join(lines)


def generate_trajectory_chart(
    current_drawdown: float,
    prior_drawdown: float,
    context: dict,
    output_path: str = 'historical_trajectory_chart.png',
) -> str:
    """
    4-panel trajectory chart:
      TL: 1Y return distribution overlay (falling vs recovering)
      TR: Avg returns by horizon, falling vs recovering bars
      BL: Max further drawdown distribution overlay
      BR: Side-by-side summary stats table
    """
    falling = context.get('falling', _empty_traj_stats())
    recovering = context.get('recovering', _empty_traj_stats())
    flat = context.get('flat', _empty_traj_stats())
    current_traj = context.get('current_trajectory', 'flat')
    cur_emoji = {'falling': '↓', 'recovering': '↑', 'flat': '→'}[current_traj]

    fig, axes = plt.subplots(2, 2, figsize=(13, 10))
    fig.suptitle(
        f"Historical Returns from {context.get('dd_bucket', 'N/A')} Drawdown\n"
        f"Current Trajectory: {current_traj.upper()} {cur_emoji}  "
        f"(Prior: {prior_drawdown*100:.1f}% → Now: {current_drawdown*100:.1f}%)",
        fontsize=13,
        fontweight='bold',
    )

    fall_color = '#e74c3c'
    rec_color = '#2ecc71'
    flat_color = '#95a5a6'

    # --- TL: 1Y return distribution overlay ---
    ax1 = axes[0, 0]
    f_returns = [r * 100 for r in falling.get('returns_1y', [])]
    r_returns = [r * 100 for r in recovering.get('returns_1y', [])]
    plotted = False
    if len(f_returns) >= 3:
        ax1.hist(f_returns, bins=15, color=fall_color, alpha=0.55,
                 label=f"Falling (n={len(f_returns)})", edgecolor='white')
        if falling.get('avg_1y_return') is not None:
            ax1.axvline(falling['avg_1y_return'] * 100, color=fall_color,
                        linestyle='--', linewidth=2)
        plotted = True
    if len(r_returns) >= 3:
        ax1.hist(r_returns, bins=15, color=rec_color, alpha=0.55,
                 label=f"Recovering (n={len(r_returns)})", edgecolor='white')
        if recovering.get('avg_1y_return') is not None:
            ax1.axvline(recovering['avg_1y_return'] * 100, color=rec_color,
                        linestyle='--', linewidth=2)
        plotted = True
    if plotted:
        ax1.axvline(0, color='gray', linewidth=1, alpha=0.5)
        ax1.set_xlabel('1-Year Forward Return (%)')
        ax1.set_ylabel('Frequency')
        ax1.set_title('1Y Return Distribution: Falling vs Recovering')
        ax1.legend(loc='upper right')
    else:
        ax1.text(0.5, 0.5, 'Insufficient data', ha='center', va='center', fontsize=12)
        ax1.set_title('1Y Return Distribution')

    # --- TR: Avg returns by horizon ---
    ax2 = axes[0, 1]
    horizons = ['1M', '3M', '1Y', '2Y']
    keys = ['avg_1m_return', 'avg_3m_return', 'avg_1y_return', 'avg_2y_return']
    f_vals = [(falling.get(k) or 0) * 100 for k in keys]
    r_vals = [(recovering.get(k) or 0) * 100 for k in keys]
    x = np.arange(len(horizons))
    width = 0.38
    ax2.bar(x - width/2, f_vals, width, color=fall_color, alpha=0.85,
            label=f"Falling (n={falling.get('sample_size', 0)})")
    ax2.bar(x + width/2, r_vals, width, color=rec_color, alpha=0.85,
            label=f"Recovering (n={recovering.get('sample_size', 0)})")
    for i, (fv, rv) in enumerate(zip(f_vals, r_vals)):
        ax2.annotate(f'{fv:+.0f}%', xy=(i - width/2, fv),
                     xytext=(0, 3 if fv >= 0 else -12), textcoords='offset points',
                     ha='center', fontsize=9)
        ax2.annotate(f'{rv:+.0f}%', xy=(i + width/2, rv),
                     xytext=(0, 3 if rv >= 0 else -12), textcoords='offset points',
                     ha='center', fontsize=9)
    ax2.axhline(0, color='gray', linewidth=1)
    ax2.set_xticks(x)
    ax2.set_xticklabels(horizons)
    ax2.set_ylabel('Average Return (%)')
    ax2.set_title('Avg Returns by Horizon')
    ax2.legend(loc='upper left')

    # --- BL: Max further drawdown distribution overlay ---
    ax3 = axes[1, 0]
    f_dd = [d * 100 for d in falling.get('max_dd_list', [])]
    r_dd = [d * 100 for d in recovering.get('max_dd_list', [])]
    plotted = False
    if len(f_dd) >= 3:
        ax3.hist(f_dd, bins=15, color=fall_color, alpha=0.55,
                 label=f"Falling (n={len(f_dd)})", edgecolor='white')
        plotted = True
    if len(r_dd) >= 3:
        ax3.hist(r_dd, bins=15, color=rec_color, alpha=0.55,
                 label=f"Recovering (n={len(r_dd)})", edgecolor='white')
        plotted = True
    if plotted:
        ax3.set_xlabel('Max Further Drawdown Within 1Y (%)')
        ax3.set_ylabel('Frequency')
        ax3.set_title('Downside Risk by Trajectory')
        ax3.legend(loc='upper left')
    else:
        ax3.text(0.5, 0.5, 'Insufficient data', ha='center', va='center', fontsize=12)
        ax3.set_title('Downside Risk')

    # --- BR: Summary table ---
    ax4 = axes[1, 1]
    ax4.axis('off')
    rows = ['Sample (n)', '1M avg', '3M avg', '1Y avg', '2Y avg',
            '1Y win rate', 'Avg further DD', 'Worst further DD']

    def cells(stats):
        n = stats.get('sample_size', 0) or 0
        if n == 0:
            return ['0'] + ['-'] * (len(rows) - 1)
        return [
            f"{n}",
            _fmt_pct(stats.get('avg_1m_return')),
            _fmt_pct(stats.get('avg_3m_return')),
            _fmt_pct(stats.get('avg_1y_return')),
            _fmt_pct(stats.get('avg_2y_return')),
            f"{stats['win_rate_1y']*100:.0f}%" if stats.get('win_rate_1y') is not None else '-',
            _fmt_pct(stats.get('avg_1y_max_dd'), sign=False),
            _fmt_pct(stats.get('worst_1y_max_dd'), sign=False),
        ]

    cols = ['Falling', 'Recovering', 'Flat']
    table_data = list(zip(cells(falling), cells(recovering), cells(flat)))
    table = ax4.table(
        cellText=table_data,
        rowLabels=rows,
        colLabels=cols,
        loc='center',
        cellLoc='center',
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.0, 1.6)
    # Highlight the current-trajectory column header
    col_idx = {'falling': 0, 'recovering': 1, 'flat': 2}[current_traj]
    header_cell = table[0, col_idx]
    header_cell.set_facecolor('#f1c40f')
    header_cell.set_text_props(fontweight='bold')
    ax4.set_title('Summary by Trajectory')

    # Footer
    cur_n = (context.get(current_traj) or {}).get('sample_size', 0) or 0
    fig.text(
        0.5, 0.02,
        f"Current: {current_drawdown*100:.1f}% | Prior: {prior_drawdown*100:.1f}% | "
        f"Trajectory: {current_traj.upper()} | Relevant Sample: n={cur_n} | "
        f"Lookback: {context.get('lookback_days', 0)}d",
        ha='center', fontsize=10, style='italic',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5),
    )

    plt.tight_layout(rect=[0, 0.05, 1, 0.93])
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    return output_path


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

    # Optional: trajectory-aware context (pass prior_dd as 2nd arg).
    if len(sys.argv) > 2:
        test_prior = float(sys.argv[2])
        print(f"\n--- Trajectory-aware context (prior_dd={test_prior*100:.1f}%) ---")
        ctx = get_historical_context_by_trajectory(test_dd, test_prior, df)
        print(f"Current trajectory: {ctx['current_trajectory']}")
        for traj in ('falling', 'recovering', 'flat'):
            s = ctx[traj]
            n = s.get('sample_size', 0) or 0
            avg1y = s.get('avg_1y_return')
            avg1y_s = f"{avg1y*100:+.1f}%" if avg1y is not None else 'N/A'
            print(f"  {traj:>10}: n={n:>3}  avg 1Y={avg1y_s}")
        traj_chart = generate_trajectory_chart(
            test_dd, test_prior, ctx, 'test_trajectory_chart.png'
        )
        print(f"Trajectory chart saved to: {traj_chart}")
