"""
Trajectory Lookback Window — Empirical Sweep

Determines the optimal `lookback_days` value for the trajectory classifier
used in `get_historical_context_by_trajectory()` by sweeping
L in {7, 14, 21, 30, 45, 60, 90, 120, 180} and measuring how cleanly each
window separates falling vs recovering forward returns.

Decision rule:
  Pick the smallest L whose:
    * edge (mean_1Y[rec] - mean_1Y[fall]) > 0.20  (>20%)
    * |t-stat| > 2.0
    * min(n_fall, n_rec) >= 15
  If none qualify, report that the trajectory signal is too weak to deploy.

Run from repo root:
    python analysis/trajectory_lookback_sweep.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / 'src'))

from v9_production import load_btc_data  # noqa: E402

LOOKBACKS = [7, 14, 21, 30, 45, 60, 90, 120, 180]
DEFAULT_THRESHOLD = 0.03
DEFAULT_BUCKETS = (-0.80, -0.10)
BUCKET_SIZE = 0.05
FWD_HORIZONS = {'3m': 91, '1y': 365}


def build_drawdown_series(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().sort_values('date').reset_index(drop=True)
    df['ath'] = df['close'].cummax()
    df['drawdown'] = (df['close'] - df['ath']) / df['ath']
    return df


def collect_first_entries(df: pd.DataFrame, dd_low: float, dd_high: float) -> list[int]:
    """
    First-entry days: indices where drawdown is inside [dd_low, dd_high)
    bucket and was NOT inside the bucket the previous day. Buckets are
    iterated in 5% slices over [dd_low, dd_high).
    """
    entries: list[int] = []
    bucket_edges = np.round(np.arange(dd_low, dd_high, BUCKET_SIZE), 4)
    for edge in bucket_edges:
        lower = float(edge)
        upper = float(edge + BUCKET_SIZE)
        in_bucket = (df['drawdown'] >= lower) & (df['drawdown'] < upper)
        prev = in_bucket.shift(1, fill_value=False)
        first_entry = in_bucket & ~prev
        entries.extend(df.index[first_entry].tolist())
    return sorted(set(entries))


def classify(current: float, prior: float, threshold: float) -> str:
    diff = current - prior
    if diff < -threshold:
        return 'falling'
    if diff > threshold:
        return 'recovering'
    return 'flat'


def sweep(
    df: pd.DataFrame,
    dd_low: float = DEFAULT_BUCKETS[0],
    dd_high: float = DEFAULT_BUCKETS[1],
    threshold: float = DEFAULT_THRESHOLD,
    horizon_days: int = 365,
) -> pd.DataFrame:
    """
    For each L in LOOKBACKS, classify first-entries in the given bucket
    range and compute mean forward return / win rate / sample size per
    trajectory, plus separation edge and Welch t-test.
    """
    entries = collect_first_entries(df, dd_low, dd_high)
    rows = []
    for L in LOOKBACKS:
        usable = [i for i in entries if i >= L and i + horizon_days < len(df)]
        traj_returns: dict[str, list[float]] = {'falling': [], 'recovering': [], 'flat': []}
        for idx in usable:
            cur_dd = float(df.loc[idx, 'drawdown'])
            prior_dd = float(df.loc[idx - L, 'drawdown'])
            traj = classify(cur_dd, prior_dd, threshold)
            entry_price = df.loc[idx, 'close']
            exit_price = df.loc[idx + horizon_days, 'close']
            traj_returns[traj].append(exit_price / entry_price - 1)

        fall = traj_returns['falling']
        rec = traj_returns['recovering']
        flat = traj_returns['flat']

        def safe_mean(xs): return float(np.mean(xs)) if xs else np.nan
        def win_rate(xs): return float(np.mean([x > 0 for x in xs])) if xs else np.nan

        if len(fall) >= 2 and len(rec) >= 2:
            t_stat, p_val = stats.ttest_ind(rec, fall, equal_var=False)
        else:
            t_stat, p_val = np.nan, np.nan

        rows.append({
            'L': L,
            'n_fall': len(fall),
            'n_rec': len(rec),
            'n_flat': len(flat),
            'mean_fall': safe_mean(fall),
            'mean_rec': safe_mean(rec),
            'mean_flat': safe_mean(flat),
            'win_fall': win_rate(fall),
            'win_rec': win_rate(rec),
            'edge': safe_mean(rec) - safe_mean(fall),
            't_stat': float(t_stat) if not np.isnan(t_stat) else np.nan,
            'p_value': float(p_val) if not np.isnan(p_val) else np.nan,
        })
    return pd.DataFrame(rows)


def format_table(label: str, df_results: pd.DataFrame) -> str:
    lines = [f"\n=== {label} ==="]
    lines.append(
        f"{'L':>4} | {'n_fall':>6} | {'n_rec':>5} | {'n_flat':>6} | "
        f"{'mean_1Y_fall':>12} | {'mean_1Y_rec':>11} | {'edge':>7} | "
        f"{'t-stat':>6} | {'p-value':>7}"
    )
    lines.append('-' * 96)
    for _, r in df_results.iterrows():
        def pct(x):
            return f"{x*100:+7.1f}%" if pd.notna(x) else '    N/A'
        def num(x, fmt):
            return fmt.format(x) if pd.notna(x) else '   N/A'
        lines.append(
            f"{int(r['L']):>4} | "
            f"{int(r['n_fall']):>6} | {int(r['n_rec']):>5} | {int(r['n_flat']):>6} | "
            f"{pct(r['mean_fall']):>12} | {pct(r['mean_rec']):>11} | "
            f"{pct(r['edge']):>7} | "
            f"{num(r['t_stat'], '{:>+6.2f}'):>6} | "
            f"{num(r['p_value'], '{:>7.4f}'):>7}"
        )
    return '\n'.join(lines)


def pick_winner(df_results: pd.DataFrame, edge_min=0.20, t_min=2.0, n_min=15) -> dict:
    qualifying = df_results[
        (df_results['edge'] > edge_min)
        & (df_results['t_stat'].abs() > t_min)
        & (df_results['n_fall'] >= n_min)
        & (df_results['n_rec'] >= n_min)
    ].sort_values('L')
    if qualifying.empty:
        return {'qualifies': False, 'reason': 'no L met all three thresholds'}
    best = qualifying.iloc[0]
    return {
        'qualifies': True,
        'L': int(best['L']),
        'edge': float(best['edge']),
        't_stat': float(best['t_stat']),
        'p_value': float(best['p_value']),
        'n_fall': int(best['n_fall']),
        'n_rec': int(best['n_rec']),
    }


def main():
    df = load_btc_data(REPO_ROOT / 'data' / 'BTC.csv')
    df = build_drawdown_series(df[['date', 'close']])
    print(f"Loaded {len(df)} daily rows: {df['date'].iloc[0].date()} -> {df['date'].iloc[-1].date()}")

    # --- Main sweep: [-80%, -10%], threshold=0.03, 1Y horizon ---
    main_results = sweep(df)
    print(format_table('MAIN SWEEP (buckets -80% to -10%, threshold=0.03, 1Y forward)', main_results))
    main_pick = pick_winner(main_results)
    print(f"\nMain-sweep decision: {main_pick}")

    # --- Regime subsets ---
    print("\n\n" + '=' * 96)
    print("ROBUSTNESS: BUCKET SUBSETS (threshold=0.03, 1Y forward)")
    print('=' * 96)
    subsets = {
        'shallow (-30% to -10%)': (-0.30, -0.10),
        'mid (-50% to -30%)': (-0.50, -0.30),
        'deep (-80% to -50%)': (-0.80, -0.50),
    }
    subset_results = {}
    for label, (low, high) in subsets.items():
        res = sweep(df, dd_low=low, dd_high=high)
        subset_results[label] = res
        print(format_table(label, res))

    # --- Threshold sensitivity ---
    print("\n\n" + '=' * 96)
    print("ROBUSTNESS: THRESHOLD SENSITIVITY (buckets -80% to -10%, 1Y forward)")
    print('=' * 96)
    threshold_results = {}
    for th in (0.02, 0.03, 0.05, 0.07):
        res = sweep(df, threshold=th)
        threshold_results[th] = res
        print(format_table(f'threshold={th}', res))

    # --- 3-month horizon ---
    print("\n\n" + '=' * 96)
    print("ROBUSTNESS: 3-MONTH FORWARD HORIZON (buckets -80% to -10%, threshold=0.03)")
    print('=' * 96)
    res_3m = sweep(df, horizon_days=91)
    print(format_table('3M forward returns', res_3m))
    pick_3m = pick_winner(res_3m)
    print(f"\n3M-horizon decision: {pick_3m}")

    # --- Final summary ---
    print("\n\n" + '=' * 96)
    print("DECISION SUMMARY")
    print('=' * 96)
    if main_pick['qualifies']:
        print(f"Recommended lookback_days: {main_pick['L']}")
        print(f"  Expected 1Y edge (rec - fall): {main_pick['edge']*100:+.1f}%")
        print(f"  Welch t-stat: {main_pick['t_stat']:+.2f} (p={main_pick['p_value']:.4f})")
        print(f"  Sample sizes: n_fall={main_pick['n_fall']}, n_rec={main_pick['n_rec']}")
    else:
        print("No L qualified under decision rule (edge>20%, |t|>2.0, n>=15 both sides).")
        # Show whichever L has the highest edge for context.
        best = main_results.sort_values('edge', ascending=False).iloc[0]
        print(f"Best edge available: L={int(best['L'])} "
              f"edge={best['edge']*100:+.1f}% t={best['t_stat']:+.2f} "
              f"p={best['p_value']:.4f} n_fall={int(best['n_fall'])} n_rec={int(best['n_rec'])}")


if __name__ == '__main__':
    main()
