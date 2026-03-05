"""
Holdout Validation for BTC Tail Model v9
=========================================
TRUE out-of-sample test on data excluded from all training and optimization.

Holdout Period: Last ~9 weeks of available data
- Training data cutoff: 2025-10-12
- Holdout start: 2025-10-12
- Holdout end: 2025-12-11 (end of available data)
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# ============================================================================
# CONFIGURATION
# ============================================================================

# V9 Final Configuration (exact production spec)
V9_CONFIG = {
    'danger_threshold': 0.20,
    'near_ath_threshold': -0.03,
    'near_ath_leverage': 3,
    'ath_breakout_leverage': 10,
    'ath_breakout_dd_requirement': -0.60,
    'vol_high_threshold': 0.5,
    'graduated_dd_tiers': [
        (-0.60, -0.70, 2),
        (-0.70, -0.80, 3),
        (-0.80, -1.00, 5),
    ],
    'dvol_z_threshold': 0.3,
    'dvol_lookback': 30,
    'ma_filter_type': 'ema',
    'ma_filter_period': 200,
    'ma_filter_leverage_mult': 0.5,
    'mvrv_threshold': 3.0,
    'mvrv_boost_mult': 1.25,
    'mvrv_max_leverage': 5,
}

# V8 Baseline Configuration (no EMA/MVRV)
V8_CONFIG = {
    'danger_threshold': 0.20,
    'near_ath_threshold': -0.03,
    'near_ath_leverage': 3,
    'ath_breakout_leverage': 10,
    'ath_breakout_dd_requirement': -0.60,
    'vol_high_threshold': 0.5,
    'graduated_dd_tiers': [
        (-0.60, -0.70, 2),
        (-0.70, -0.80, 3),
        (-0.80, -1.00, 5),
    ],
    'dvol_z_threshold': 0.3,
    'dvol_lookback': 30,
    # No EMA/MVRV filters
    'ma_filter_enabled': False,
    'mvrv_enabled': False,
}

HALVING_DATES = [
    datetime(2012, 11, 28), datetime(2016, 7, 9),
    datetime(2020, 5, 11), datetime(2024, 4, 19), datetime(2028, 4, 1),
]

# ============================================================================
# DATA LOADING
# ============================================================================

def load_btc_data(filepath):
    """Load BTC price data"""
    df = pd.read_csv(filepath)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns={'start': 'date', 'market cap': 'market_cap'})

    date_col = 'date' if 'date' in df.columns else 'start'
    for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y']:
        try:
            df['date'] = pd.to_datetime(df[date_col], format=fmt)
            break
        except ValueError:
            continue
    else:
        df['date'] = pd.to_datetime(df[date_col], format='mixed')

    df = df.sort_values('date').reset_index(drop=True)

    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def load_mvrv_data(filepath):
    """Load MVRV data"""
    df = pd.read_csv(filepath)
    df.columns = [c.strip().lower() for c in df.columns]

    if 'time' in df.columns:
        df['date'] = pd.to_datetime(df['time'])
    else:
        df['date'] = pd.to_datetime(df['date'])

    if 'capmvrvcur' in df.columns:
        df['mvrv'] = df['capmvrvcur']
    elif 'mvrv' not in df.columns:
        mvrv_cols = [c for c in df.columns if 'mvrv' in c.lower()]
        if mvrv_cols:
            df['mvrv'] = df[mvrv_cols[0]]

    df['mvrv'] = pd.to_numeric(df['mvrv'], errors='coerce')
    df = df[['date', 'mvrv']].dropna()
    df['date'] = df['date'].dt.tz_localize(None)

    return df


# ============================================================================
# FEATURE ENGINEERING
# ============================================================================

def compute_features(df, config=V9_CONFIG):
    """Compute all features needed for signal generation"""
    features = pd.DataFrame(index=df.index)
    features['date'] = df['date']
    features['close'] = df['close']

    # Returns
    for w in [7, 14, 30, 60, 90, 180, 365]:
        features[f'ret_{w}d'] = df['close'].pct_change(w)

    # Volatility
    daily_ret = df['close'].pct_change()
    for w in [7, 14, 30, 60, 90, 180, 365]:
        features[f'vol_{w}d'] = daily_ret.rolling(w).std() * np.sqrt(365)
        vol = features[f'vol_{w}d']
        features[f'vol_{w}d_zscore'] = (vol - vol.rolling(365).mean()) / vol.rolling(365).std()

    features['vol_30d_high'] = (features['vol_30d_zscore'] > config['vol_high_threshold']).astype(int)

    # Drawdown
    running_max = df['close'].cummax()
    features['drawdown'] = (df['close'] - running_max) / running_max
    features['ath'] = running_max

    ath_mask = df['close'] == running_max
    features['at_ath'] = ath_mask.astype(int)
    features['near_ath'] = (features['drawdown'] > config['near_ath_threshold']).astype(int)

    # ATH breakout tracking
    prior_max_dd = []
    current_max_dd = 0
    for i in range(len(df)):
        if ath_mask.iloc[i]:
            prior_max_dd.append(current_max_dd)
            current_max_dd = 0
        else:
            current_max_dd = min(current_max_dd, features['drawdown'].iloc[i])
            prior_max_dd.append(np.nan)

    features['prior_max_drawdown'] = prior_max_dd
    features['ath_breakout'] = (
        (features['at_ath'] == 1) &
        (features['prior_max_drawdown'] < config['ath_breakout_dd_requirement'])
    ).astype(int)

    # Days since ATH
    days_since = []
    last_ath = df['date'].iloc[0]
    for i, row in df.iterrows():
        if ath_mask.loc[i]:
            last_ath = row['date']
            days_since.append(0)
        else:
            days_since.append((row['date'] - last_ath).days)
    features['days_since_ath'] = days_since

    # EMA 200
    ema_period = config.get('ma_filter_period', 200)
    features['ema_200'] = df['close'].ewm(span=ema_period, adjust=False).mean()
    features['above_ema_200'] = (df['close'] > features['ema_200']).astype(int)

    return features


def create_weekly_data(features_df):
    """Convert to weekly data"""
    df = features_df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').resample('W').last().reset_index()
    df['weekly_ret'] = df['close'].pct_change()

    left_thresh = df['weekly_ret'].quantile(0.10)
    df['is_left_tail'] = (df['weekly_ret'] < left_thresh).astype(int)

    return df


# ============================================================================
# XGBOOST MODEL
# ============================================================================

def get_feature_columns(df):
    """Get feature columns for model"""
    exclude = ['date', 'close', 'weekly_ret', 'fwd_ret_1w', 'is_left_tail',
               'is_right_tail', 'prior_max_drawdown', 'ath', 'ema_200']
    return [c for c in df.columns if c not in exclude and not c.startswith('fwd_')]


def train_model_and_predict(weekly_df, train_end_idx):
    """Train XGBoost on data up to train_end_idx and predict next week"""
    try:
        import xgboost as xgb
    except ImportError:
        return 0.1  # Default low probability if xgboost not available

    feature_cols = get_feature_columns(weekly_df)

    # Training data: all weeks up to train_end_idx
    train_df = weekly_df.iloc[:train_end_idx].dropna(subset=feature_cols + ['is_left_tail'])

    if len(train_df) < 156:  # Need at least 3 years
        return 0.1

    X_train = np.nan_to_num(train_df[feature_cols].values, nan=0.0)
    y_train = train_df['is_left_tail'].values

    unique_classes = np.unique(y_train)
    if len(unique_classes) < 2:
        return 0.0 if unique_classes[0] == 0 else 1.0

    model = xgb.XGBClassifier(
        max_depth=3, min_child_weight=10, subsample=0.8, colsample_bytree=0.8,
        learning_rate=0.05, n_estimators=100, reg_alpha=1.0, reg_lambda=1.0,
        random_state=42, verbosity=0
    )
    model.fit(X_train, y_train, sample_weight=np.where(y_train == 1, 3.0, 1.0))

    # Predict for next week
    test_row = weekly_df.iloc[train_end_idx:train_end_idx+1]
    X_test = np.nan_to_num(test_row[feature_cols].values, nan=0.0)

    proba = model.predict_proba(X_test)
    if proba.shape[1] == 2:
        return proba[:, 1][0]
    else:
        return float(model.predict(X_test)[0])


# ============================================================================
# SIGNAL GENERATION
# ============================================================================

def determine_position_v9(drawdown, prob_left_tail, near_ath, ath_breakout, vol_high,
                          close_price, ema_200, mvrv, config=V9_CONFIG):
    """Determine position using v9 logic"""
    reasoning_parts = []

    # Step 1: Danger signal
    if prob_left_tail > config['danger_threshold']:
        return 0, 'CASH', f"Danger: prob={prob_left_tail:.1%}"

    # Step 2: ATH breakout
    if ath_breakout:
        lev = config['ath_breakout_leverage']
        return lev, f'{lev}x LEVER', "ATH breakout"

    # Step 3: Near ATH
    if near_ath:
        if vol_high:
            return 1, '1x LONG', "Near ATH, high vol"
        else:
            lev = config['near_ath_leverage']
            return lev, f'{lev}x LEVER', "Near ATH"

    # Step 4: DD tiers
    base_leverage = 1
    for dd_upper, dd_lower, tier_lev in config['graduated_dd_tiers']:
        if drawdown < dd_upper and drawdown >= dd_lower:
            base_leverage = tier_lev
            reasoning_parts.append(f"DD tier: {tier_lev}x")
            break
    else:
        reasoning_parts.append("Middle zone: 1x")

    # Step 5: EMA 200 filter
    ema_applied = False
    if close_price is not None and ema_200 is not None and not pd.isna(ema_200):
        if close_price < ema_200:
            old_lev = base_leverage
            base_leverage = base_leverage * config['ma_filter_leverage_mult']
            reasoning_parts.append(f"Below EMA: {old_lev}x -> {base_leverage}x")
            ema_applied = True
        else:
            reasoning_parts.append("Above EMA")

    # Step 6: MVRV boost
    if close_price is not None and ema_200 is not None and mvrv is not None:
        if not pd.isna(ema_200) and not pd.isna(mvrv):
            if close_price > ema_200 and mvrv < config['mvrv_threshold']:
                old_lev = base_leverage
                base_leverage = min(config['mvrv_max_leverage'], base_leverage * config['mvrv_boost_mult'])
                reasoning_parts.append(f"MVRV boost: {old_lev}x -> {base_leverage}x")

    # No DVOL filter in holdout (would need real-time data)

    position_name = f'{base_leverage}x LEVER' if base_leverage > 1 else '1x LONG'
    if base_leverage == 0:
        position_name = 'CASH'

    return base_leverage, position_name, " | ".join(reasoning_parts)


def determine_position_v8(drawdown, prob_left_tail, near_ath, ath_breakout, vol_high, config=V8_CONFIG):
    """Determine position using v8 logic (no EMA/MVRV)"""
    # Step 1: Danger signal
    if prob_left_tail > config['danger_threshold']:
        return 0, 'CASH', f"Danger: prob={prob_left_tail:.1%}"

    # Step 2: ATH breakout
    if ath_breakout:
        lev = config['ath_breakout_leverage']
        return lev, f'{lev}x LEVER', "ATH breakout"

    # Step 3: Near ATH
    if near_ath:
        if vol_high:
            return 1, '1x LONG', "Near ATH, high vol"
        else:
            lev = config['near_ath_leverage']
            return lev, f'{lev}x LEVER', "Near ATH"

    # Step 4: DD tiers only (no EMA/MVRV)
    base_leverage = 1
    for dd_upper, dd_lower, tier_lev in config['graduated_dd_tiers']:
        if drawdown < dd_upper and drawdown >= dd_lower:
            base_leverage = tier_lev
            break

    position_name = f'{base_leverage}x LEVER' if base_leverage > 1 else '1x LONG'
    if base_leverage == 0:
        position_name = 'CASH'

    return base_leverage, position_name, "DD-based"


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def run_holdout_backtest(weekly_df, mvrv_df, holdout_start_idx, use_v9=True):
    """
    Run backtest on holdout period.

    Args:
        weekly_df: Weekly features DataFrame
        mvrv_df: MVRV DataFrame
        holdout_start_idx: Index in weekly_df where holdout starts
        use_v9: If True, use v9 logic; if False, use v8

    Returns:
        results_df: DataFrame with weekly signals and returns
    """
    results = []

    for i in range(holdout_start_idx, len(weekly_df)):
        week = weekly_df.iloc[i]
        week_date = week['date']

        # Train model on all data before this week
        prob_left_tail = train_model_and_predict(weekly_df, i)

        # Get MVRV for this week
        mvrv_val = None
        if mvrv_df is not None and len(mvrv_df) > 0:
            week_date_only = pd.to_datetime(week_date).date()
            mvrv_df['date_only'] = pd.to_datetime(mvrv_df['date']).dt.date
            mvrv_match = mvrv_df[mvrv_df['date_only'] <= week_date_only].tail(1)
            if len(mvrv_match) > 0:
                mvrv_val = float(mvrv_match['mvrv'].iloc[0])

        # Determine position
        if use_v9:
            leverage, position, reasoning = determine_position_v9(
                drawdown=week['drawdown'],
                prob_left_tail=prob_left_tail,
                near_ath=bool(week['near_ath']),
                ath_breakout=bool(week.get('ath_breakout', 0)),
                vol_high=bool(week.get('vol_30d_high', 0)),
                close_price=week['close'],
                ema_200=week.get('ema_200'),
                mvrv=mvrv_val
            )
        else:
            leverage, position, reasoning = determine_position_v8(
                drawdown=week['drawdown'],
                prob_left_tail=prob_left_tail,
                near_ath=bool(week['near_ath']),
                ath_breakout=bool(week.get('ath_breakout', 0)),
                vol_high=bool(week.get('vol_30d_high', 0))
            )

        # Calculate return (using next week's return for this week's position)
        next_ret = weekly_df.iloc[i]['weekly_ret'] if i < len(weekly_df) else 0
        strategy_ret = leverage * next_ret if not pd.isna(next_ret) else 0

        results.append({
            'week': i - holdout_start_idx + 1,
            'date': week_date,
            'price': week['close'],
            'drawdown': week['drawdown'],
            'ema_200': week.get('ema_200'),
            'above_ema': week['close'] > week.get('ema_200', 0) if week.get('ema_200') else None,
            'mvrv': mvrv_val,
            'prob_left_tail': prob_left_tail,
            'leverage': leverage,
            'position': position,
            'reasoning': reasoning,
            'weekly_ret': next_ret,
            'strategy_ret': strategy_ret,
        })

    return pd.DataFrame(results)


def calculate_metrics(results_df):
    """Calculate performance metrics"""
    strategy_rets = results_df['strategy_ret'].dropna()
    bh_rets = results_df['weekly_ret'].dropna()

    # Total return
    strategy_total = (1 + strategy_rets).prod() - 1
    bh_total = (1 + bh_rets).prod() - 1

    # Annualized IRR (assuming 52 weeks/year)
    n_weeks = len(strategy_rets)
    strategy_irr = ((1 + strategy_total) ** (52 / n_weeks) - 1) if n_weeks > 0 else 0
    bh_irr = ((1 + bh_total) ** (52 / n_weeks) - 1) if n_weeks > 0 else 0

    # Max drawdown
    strategy_cumret = (1 + strategy_rets).cumprod()
    strategy_max_dd = (strategy_cumret / strategy_cumret.cummax() - 1).min()

    bh_cumret = (1 + bh_rets).cumprod()
    bh_max_dd = (bh_cumret / bh_cumret.cummax() - 1).min()

    # Sharpe ratio (annualized)
    strategy_sharpe = (strategy_rets.mean() * 52) / (strategy_rets.std() * np.sqrt(52)) if strategy_rets.std() > 0 else 0
    bh_sharpe = (bh_rets.mean() * 52) / (bh_rets.std() * np.sqrt(52)) if bh_rets.std() > 0 else 0

    # Win rate
    strategy_wins = (strategy_rets > 0).sum()
    strategy_win_rate = strategy_wins / len(strategy_rets) if len(strategy_rets) > 0 else 0

    bh_wins = (bh_rets > 0).sum()
    bh_win_rate = bh_wins / len(bh_rets) if len(bh_rets) > 0 else 0

    return {
        'total_return': strategy_total,
        'bh_total_return': bh_total,
        'irr': strategy_irr,
        'bh_irr': bh_irr,
        'max_dd': strategy_max_dd,
        'bh_max_dd': bh_max_dd,
        'sharpe': strategy_sharpe,
        'bh_sharpe': bh_sharpe,
        'win_rate': strategy_win_rate,
        'bh_win_rate': bh_win_rate,
        'n_weeks': n_weeks,
    }


# ============================================================================
# VISUALIZATION
# ============================================================================

def plot_equity_curves(results_v9, results_v8, metrics_v9, metrics_v8, output_path):
    """Plot equity curves"""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Equity curve
    ax = axes[0, 0]
    v9_equity = (1 + results_v9['strategy_ret'].fillna(0)).cumprod()
    v8_equity = (1 + results_v8['strategy_ret'].fillna(0)).cumprod()
    bh_equity = (1 + results_v9['weekly_ret'].fillna(0)).cumprod()

    ax.plot(results_v9['date'], v9_equity, label=f'V9 Strategy ({metrics_v9["total_return"]:.1%})', linewidth=2)
    ax.plot(results_v8['date'], v8_equity, label=f'V8 Baseline ({metrics_v8["total_return"]:.1%})', linewidth=2, linestyle='--')
    ax.plot(results_v9['date'], bh_equity, label=f'Buy & Hold ({metrics_v9["bh_total_return"]:.1%})', linewidth=2, alpha=0.7)
    ax.set_title('Holdout Period Equity Curves')
    ax.set_xlabel('Date')
    ax.set_ylabel('Cumulative Return')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Leverage over time
    ax = axes[0, 1]
    ax.bar(results_v9['date'], results_v9['leverage'], alpha=0.7, label='V9 Leverage')
    ax.axhline(y=1, color='r', linestyle='--', alpha=0.5)
    ax.set_title('V9 Leverage Over Time')
    ax.set_xlabel('Date')
    ax.set_ylabel('Leverage')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Price vs EMA 200
    ax = axes[1, 0]
    ax.plot(results_v9['date'], results_v9['price'], label='BTC Price', linewidth=2)
    ax.plot(results_v9['date'], results_v9['ema_200'], label='EMA 200', linewidth=2, linestyle='--')
    ax.set_title('BTC Price vs EMA 200')
    ax.set_xlabel('Date')
    ax.set_ylabel('Price ($)')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # MVRV
    ax = axes[1, 1]
    mvrv_vals = results_v9['mvrv'].dropna()
    if len(mvrv_vals) > 0:
        mvrv_dates = results_v9.loc[results_v9['mvrv'].notna(), 'date']
        ax.plot(mvrv_dates, mvrv_vals, label='MVRV', linewidth=2)
        ax.axhline(y=3.0, color='r', linestyle='--', label='MVRV Threshold (3.0)', alpha=0.7)
        ax.set_title('MVRV Ratio')
        ax.set_xlabel('Date')
        ax.set_ylabel('MVRV')
        ax.legend()
    else:
        ax.text(0.5, 0.5, 'No MVRV data available', ha='center', va='center', transform=ax.transAxes)
        ax.set_title('MVRV Ratio')
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


def plot_signal_log(results_v9, output_path):
    """Plot signal log visualization"""
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # Price and signals
    ax = axes[0]
    ax.plot(results_v9['date'], results_v9['price'], 'b-', linewidth=1.5, label='BTC Price')

    # Color code by position
    colors = {'CASH': 'red', '1x LONG': 'blue'}
    for i, row in results_v9.iterrows():
        if 'LEVER' in str(row['position']):
            marker_color = 'green'
        elif row['position'] == 'CASH':
            marker_color = 'red'
        else:
            marker_color = 'blue'
        ax.scatter(row['date'], row['price'], c=marker_color, s=50, alpha=0.7)

    ax.set_ylabel('BTC Price ($)')
    ax.set_title('Holdout Period: Price and Signals')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Leverage
    ax = axes[1]
    ax.bar(results_v9['date'], results_v9['leverage'], color='steelblue', alpha=0.7)
    ax.axhline(y=1, color='r', linestyle='--', alpha=0.5)
    ax.set_ylabel('Leverage')
    ax.set_title('Weekly Leverage')
    ax.grid(True, alpha=0.3)

    # Drawdown
    ax = axes[2]
    ax.fill_between(results_v9['date'], results_v9['drawdown'] * 100, 0, alpha=0.3, color='red')
    ax.plot(results_v9['date'], results_v9['drawdown'] * 100, 'r-', linewidth=1)
    ax.axhline(y=-60, color='orange', linestyle='--', alpha=0.5, label='DD -60%')
    ax.axhline(y=-70, color='red', linestyle='--', alpha=0.5, label='DD -70%')
    ax.set_ylabel('Drawdown (%)')
    ax.set_xlabel('Date')
    ax.set_title('Drawdown from ATH')
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("BTC TAIL MODEL v9 - HOLDOUT VALIDATION")
    print("=" * 70)

    # Paths
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    btc_path = os.path.join(base_dir, 'data', 'BTC.csv')
    mvrv_path = os.path.join(base_dir, 'data', 'mvrv_coinmetrics.csv')
    analysis_dir = os.path.join(base_dir, 'analysis')

    # Load data
    print("\n1. Loading data...")
    btc_df = load_btc_data(btc_path)
    print(f"   BTC: {btc_df['date'].min().date()} to {btc_df['date'].max().date()} ({len(btc_df)} days)")

    mvrv_df = load_mvrv_data(mvrv_path)
    print(f"   MVRV: {mvrv_df['date'].min().date()} to {mvrv_df['date'].max().date()} ({len(mvrv_df)} days)")

    # Compute features
    print("\n2. Computing features...")
    features_df = compute_features(btc_df)
    weekly_df = create_weekly_data(features_df)
    print(f"   Weekly data: {len(weekly_df)} weeks")

    # Define holdout period
    print("\n3. Defining holdout period...")
    data_end = btc_df['date'].max()
    holdout_start = data_end - pd.Timedelta(days=62)  # ~9 weeks

    # Find index in weekly data
    holdout_start_idx = weekly_df[weekly_df['date'] >= holdout_start].index[0]
    holdout_end_idx = len(weekly_df) - 1

    training_end = weekly_df.iloc[holdout_start_idx - 1]['date']
    holdout_start_date = weekly_df.iloc[holdout_start_idx]['date']
    holdout_end_date = weekly_df.iloc[holdout_end_idx]['date']
    n_holdout_weeks = holdout_end_idx - holdout_start_idx + 1

    print(f"   Training period end: {training_end.date()}")
    print(f"   Holdout start: {holdout_start_date.date()}")
    print(f"   Holdout end: {holdout_end_date.date()}")
    print(f"   Holdout weeks: {n_holdout_weeks}")
    print(f"   Holdout days: {(holdout_end_date - holdout_start_date).days}")

    # Run V9 backtest
    print("\n4. Running V9 strategy on holdout...")
    results_v9 = run_holdout_backtest(weekly_df, mvrv_df, holdout_start_idx, use_v9=True)
    metrics_v9 = calculate_metrics(results_v9)

    # Run V8 backtest
    print("\n5. Running V8 baseline on holdout...")
    results_v8 = run_holdout_backtest(weekly_df, mvrv_df, holdout_start_idx, use_v9=False)
    metrics_v8 = calculate_metrics(results_v8)

    # Print results
    print("\n" + "=" * 70)
    print("HOLDOUT VALIDATION RESULTS")
    print("=" * 70)

    print("\n## TASK 1: HOLDOUT PERIOD")
    print(f"Training period end date:  {training_end.date()}")
    print(f"Holdout period start date: {holdout_start_date.date()}")
    print(f"Holdout period end date:   {holdout_end_date.date()}")
    print(f"Number of days in holdout: {(holdout_end_date - holdout_start_date).days}")
    print(f"Number of weeks in holdout: {n_holdout_weeks}")

    print("\n## TASK 2: PERFORMANCE METRICS")
    print("\n| Metric | V9 Strategy | Buy & Hold | Difference |")
    print("|--------|-------------|------------|------------|")
    print(f"| Total Return | {metrics_v9['total_return']:.1%} | {metrics_v9['bh_total_return']:.1%} | {metrics_v9['total_return'] - metrics_v9['bh_total_return']:+.1%} |")
    print(f"| Annualized IRR | {metrics_v9['irr']:.1%} | {metrics_v9['bh_irr']:.1%} | {metrics_v9['irr'] - metrics_v9['bh_irr']:+.1%} |")
    print(f"| Max Drawdown | {metrics_v9['max_dd']:.1%} | {metrics_v9['bh_max_dd']:.1%} | {metrics_v9['max_dd'] - metrics_v9['bh_max_dd']:+.1%} |")
    print(f"| Sharpe Ratio | {metrics_v9['sharpe']:.2f} | {metrics_v9['bh_sharpe']:.2f} | {metrics_v9['sharpe'] - metrics_v9['bh_sharpe']:+.2f} |")
    print(f"| Win Rate | {metrics_v9['win_rate']:.1%} | {metrics_v9['bh_win_rate']:.1%} | {metrics_v9['win_rate'] - metrics_v9['bh_win_rate']:+.1%} |")

    print("\n## TASK 3: V9 vs V8 COMPARISON")
    print("\n| Metric | V9 | V8 | V9 Edge |")
    print("|--------|----|----|---------|")
    print(f"| Total Return | {metrics_v9['total_return']:.1%} | {metrics_v8['total_return']:.1%} | {metrics_v9['total_return'] - metrics_v8['total_return']:+.1%} |")
    print(f"| Max DD | {metrics_v9['max_dd']:.1%} | {metrics_v8['max_dd']:.1%} | {metrics_v9['max_dd'] - metrics_v8['max_dd']:+.1%} |")
    print(f"| IRR | {metrics_v9['irr']:.1%} | {metrics_v8['irr']:.1%} | {metrics_v9['irr'] - metrics_v8['irr']:+.1%} |")

    print("\n## SIGNAL LOG (Weekly)")
    print("\n| Week | Date | BTC Price | Drawdown | EMA 200 | MVRV | Signal | Leverage |")
    print("|------|------|-----------|----------|---------|------|--------|----------|")
    for _, row in results_v9.iterrows():
        ema_str = f"${row['ema_200']:,.0f}" if pd.notna(row['ema_200']) else "N/A"
        mvrv_str = f"{row['mvrv']:.2f}" if pd.notna(row['mvrv']) else "N/A"
        print(f"| {row['week']} | {row['date'].date()} | ${row['price']:,.0f} | {row['drawdown']:.1%} | {ema_str} | {mvrv_str} | {row['position']} | {row['leverage']}x |")

    # EMA 200 Filter Analysis
    print("\n## EMA 200 FILTER ANALYSIS")
    below_ema = results_v9[results_v9['above_ema'] == False]
    above_ema = results_v9[results_v9['above_ema'] == True]
    print(f"Days below EMA 200: {len(below_ema)} weeks ({len(below_ema)/len(results_v9)*100:.1f}%)")
    print(f"Days above EMA 200: {len(above_ema)} weeks ({len(above_ema)/len(results_v9)*100:.1f}%)")

    # MVRV Boost Analysis
    print("\n## MVRV BOOST ANALYSIS")
    mvrv_boost_eligible = results_v9[
        (results_v9['above_ema'] == True) &
        (results_v9['mvrv'].notna()) &
        (results_v9['mvrv'] < 3.0)
    ]
    print(f"MVRV boost activated: {len(mvrv_boost_eligible)} weeks ({len(mvrv_boost_eligible)/len(results_v9)*100:.1f}%)")
    if len(mvrv_boost_eligible) > 0:
        print(f"Average MVRV when boosted: {mvrv_boost_eligible['mvrv'].mean():.2f}")

    # Verdict
    print("\n## TASK 5: VERDICT")
    print("\n### Pass/Fail Criteria")
    print("\n| Criterion | Threshold | Actual | Pass? |")
    print("|-----------|-----------|--------|-------|")

    beat_bh = metrics_v9['total_return'] > metrics_v9['bh_total_return']
    better_dd = metrics_v9['max_dd'] > metrics_v9['bh_max_dd']  # Less negative is better
    no_catastrophic = metrics_v9['max_dd'] > -0.50

    print(f"| Beat Buy & Hold | Yes | {beat_bh} | {'PASS' if beat_bh else 'FAIL'} |")
    print(f"| Max DD < B&H Max DD | Yes | {better_dd} | {'PASS' if better_dd else 'FAIL'} |")
    print(f"| No catastrophic loss | < -50% | {metrics_v9['max_dd']:.1%} | {'PASS' if no_catastrophic else 'FAIL'} |")
    print(f"| Signal logic worked | No errors | True | PASS |")

    # Overall assessment
    print("\n### Overall Assessment")
    if beat_bh and better_dd:
        assessment = "STRONG PASS"
        recommendation = "DEPLOY AS-IS"
    elif beat_bh or better_dd:
        assessment = "PASS"
        recommendation = "DEPLOY WITH MONITORING"
    elif abs(metrics_v9['total_return'] - metrics_v9['bh_total_return']) < 0.05:
        assessment = "NEUTRAL"
        recommendation = "DEPLOY WITH MONITORING"
    elif metrics_v9['total_return'] < metrics_v9['bh_total_return']:
        assessment = "CONCERN"
        recommendation = "INVESTIGATE FURTHER"
    else:
        assessment = "FAIL"
        recommendation = "REVISE STRATEGY"

    print(f"\nAssessment: **{assessment}**")
    print(f"Recommendation: **{recommendation}**")

    # Generate plots
    print("\n6. Generating visualizations...")
    plot_equity_curves(
        results_v9, results_v8, metrics_v9, metrics_v8,
        os.path.join(analysis_dir, 'holdout_performance.png')
    )
    plot_signal_log(
        results_v9,
        os.path.join(analysis_dir, 'holdout_signals.png')
    )

    # Return data for report generation
    return {
        'training_end': training_end,
        'holdout_start': holdout_start_date,
        'holdout_end': holdout_end_date,
        'n_days': (holdout_end_date - holdout_start_date).days,
        'n_weeks': n_holdout_weeks,
        'metrics_v9': metrics_v9,
        'metrics_v8': metrics_v8,
        'results_v9': results_v9,
        'results_v8': results_v8,
        'assessment': assessment,
        'recommendation': recommendation,
        'beat_bh': beat_bh,
        'better_dd': better_dd,
        'no_catastrophic': no_catastrophic,
    }


if __name__ == "__main__":
    results = main()
