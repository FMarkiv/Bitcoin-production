"""
Bitcoin Tail Model v9 - PRODUCTION SIGNAL GENERATOR
====================================================
Upgraded from v8 with EMA 200 filter and MVRV boost.

Changes from v8:
- Added EMA 200 filter (Binary 100/50): 50% leverage when below EMA 200
- Added MVRV boost: 1.25x when above EMA 200 AND MVRV < 3.0
- Updated order of operations (7 steps)

Usage:
    python v9_production.py <btc_data.csv>

Output:
    - Current position recommendation
    - Leverage level
    - Reasoning

Dependencies:
    pip install pandas numpy xgboost
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone
import json
import sys
import requests
import os

# ============================================================================
# STRATEGY PARAMETERS (v9 - Updated 2026-01-20)
# ============================================================================

STRATEGY_CONFIG = {
    # ============================================
    # EXISTING (Preserved from v8)
    # ============================================
    'danger_threshold': 0.20,           # XGBoost prob threshold for cash
    'near_ath_threshold': -0.03,        # Within 3% of ATH
    'near_ath_leverage': 3,             # Leverage when near ATH
    'ath_breakout_leverage': 10,        # Leverage on ATH breakout after major DD
    'ath_breakout_dd_requirement': -0.60,  # DD required before ATH breakout signal
    'vol_high_threshold': 0.5,          # Vol z-score threshold for high vol
    'graduated_dd_tiers': [
        (-0.60, -0.70, 2),   # DD -60% to -70%: 2x
        (-0.70, -0.80, 3),   # DD -70% to -80%: 3x
        (-0.80, -1.00, 5),   # DD < -80%: 5x
    ],
    # DVOL regime-aware filter configuration
    'dvol_z_threshold': 0.3,            # Validated threshold from sensitivity analysis
    'dvol_lookback': 30,                # Rolling window for z-score calculation

    # ============================================
    # NEW v9 ADDITIONS
    # ============================================
    'ma_filter_type': 'ema',            # Use EMA not SMA
    'ma_filter_period': 200,            # EMA 200d
    'ma_filter_leverage_mult': 0.5,     # Binary 100/50 scheme
    'mvrv_threshold': 3.0,              # Boost when MVRV < 3.0
    'mvrv_boost_mult': 1.25,            # 25% boost multiplier
    'mvrv_max_leverage': 5,             # Cap for MVRV boost
}

HALVING_DATES = [
    datetime(2012, 11, 28), datetime(2016, 7, 9),
    datetime(2020, 5, 11), datetime(2024, 4, 19), datetime(2028, 4, 1),
]

# ============================================================================
# DATA LOADING
# ============================================================================

def load_btc_data(filepath):
    """Load and clean BTC price data"""
    df = pd.read_csv(filepath)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.rename(columns={'start': 'date', 'market cap': 'market_cap'})

    # Parse dates
    date_col = 'date' if 'date' in df.columns else 'start'
    for fmt in ['%d/%m/%Y', '%Y-%m-%d', '%m/%d/%Y']:
        try:
            df['date'] = pd.to_datetime(df[date_col], format=fmt)
            break
        except ValueError:
            continue
    else:
        # Fallback to pandas auto-detection
        df['date'] = pd.to_datetime(df[date_col], format='mixed')

    df = df.sort_values('date').reset_index(drop=True)

    for col in ['open', 'high', 'low', 'close', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


def load_mvrv_data(filepath='data/mvrv_coinmetrics.csv'):
    """
    Load MVRV data from CoinMetrics CSV.

    Args:
        filepath: Path to MVRV CSV file

    Returns:
        DataFrame with columns: [date, mvrv]
        Empty DataFrame if file not found
    """
    # Try multiple possible paths
    paths_to_try = [
        filepath,
        os.path.join(os.path.dirname(__file__), '..', 'data', 'mvrv_coinmetrics.csv'),
        os.path.join(os.path.dirname(__file__), 'data', 'mvrv_coinmetrics.csv'),
    ]

    for path in paths_to_try:
        try:
            df = pd.read_csv(path)
            df.columns = [c.strip().lower() for c in df.columns]

            # Handle various column names for date
            if 'date' in df.columns:
                date_col = 'date'
            elif 'time' in df.columns:
                date_col = 'time'
            else:
                date_col = df.columns[0]

            # Handle various column names for MVRV (CoinMetrics uses 'capmvrvcur')
            if 'mvrv' in df.columns:
                mvrv_col = 'mvrv'
            elif 'capmvrvcur' in df.columns:
                mvrv_col = 'capmvrvcur'
            elif 'mvrv_ratio' in df.columns:
                mvrv_col = 'mvrv_ratio'
            else:
                # Find column containing 'mvrv' in name
                mvrv_cols = [c for c in df.columns if 'mvrv' in c.lower()]
                mvrv_col = mvrv_cols[0] if mvrv_cols else df.columns[-1]

            df['date'] = pd.to_datetime(df[date_col])
            df['mvrv'] = pd.to_numeric(df[mvrv_col], errors='coerce')

            print(f"  Loaded MVRV data: {len(df)} rows from {path}")
            print(f"  Using columns: date='{date_col}', mvrv='{mvrv_col}'")
            return df[['date', 'mvrv']].dropna()
        except FileNotFoundError:
            continue
        except Exception as e:
            print(f"WARNING: Failed to load MVRV from {path}: {e}")
            continue

    print("WARNING: MVRV data not found. MVRV boost will be disabled.")
    return pd.DataFrame()


# ============================================================================
# DVOL REGIME-AWARE FILTER
# ============================================================================

def fetch_dvol_data(days: int = 90) -> pd.DataFrame:
    """
    Fetch DVOL (Deribit Volatility Index) data from Deribit API.

    Args:
        days: Number of days of history to fetch

    Returns:
        DataFrame with columns: [date, dvol]
        Empty DataFrame if fetch fails
    """
    end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = end_time - (days * 24 * 60 * 60 * 1000)

    url = "https://www.deribit.com/api/v2/public/get_volatility_index_data"
    params = {
        "currency": "BTC",
        "start_timestamp": start_time,
        "end_timestamp": end_time,
        "resolution": "1D"
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "result" in data and "data" in data["result"]:
            records = data["result"]["data"]
            df = pd.DataFrame(records, columns=["timestamp", "open", "high", "low", "close"])
            df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
            df["dvol"] = df["close"]
            return df[["date", "dvol"]]

        print("WARNING: No DVOL data in API response")
        return pd.DataFrame()

    except requests.RequestException as e:
        print(f"WARNING: Failed to fetch DVOL data: {e}")
        return pd.DataFrame()
    except (KeyError, ValueError) as e:
        print(f"WARNING: Failed to parse DVOL response: {e}")
        return pd.DataFrame()


def calculate_dvol_zscore(dvol_series: pd.Series, lookback: int = None) -> float:
    """
    Calculate rolling z-score of DVOL.

    Args:
        dvol_series: Historical DVOL values (daily)
        lookback: Rolling window for mean/std calculation (default from config)

    Returns:
        Current z-score, or np.nan if insufficient data
    """
    if lookback is None:
        lookback = STRATEGY_CONFIG['dvol_lookback']

    if len(dvol_series) < lookback:
        return np.nan

    rolling_mean = dvol_series.rolling(lookback).mean()
    rolling_std = dvol_series.rolling(lookback).std()

    current_dvol = dvol_series.iloc[-1]
    current_mean = rolling_mean.iloc[-1]
    current_std = rolling_std.iloc[-1]

    if current_std == 0 or pd.isna(current_std):
        return 0.0

    return (current_dvol - current_mean) / current_std


# ============================================================================
# FEATURE ENGINEERING
# ============================================================================

def compute_features(df):
    """Compute all features needed for signal generation"""
    features = pd.DataFrame(index=df.index)
    features['date'] = df['date']
    features['close'] = df['close']

    # Returns
    for w in [7, 14, 30, 60, 90, 180, 365]:
        features[f'ret_{w}d'] = df['close'].pct_change(w)
        features[f'log_ret_{w}d'] = np.log(df['close'] / df['close'].shift(w))

    # Volatility
    daily_ret = df['close'].pct_change()
    for w in [7, 14, 30, 60, 90, 180, 365]:
        features[f'vol_{w}d'] = daily_ret.rolling(w).std() * np.sqrt(365)
        vol = features[f'vol_{w}d']
        features[f'vol_{w}d_zscore'] = (vol - vol.rolling(365).mean()) / vol.rolling(365).std()

    features['vol_30d_high'] = (features['vol_30d_zscore'] > STRATEGY_CONFIG['vol_high_threshold']).astype(int)

    # Drawdown
    running_max = df['close'].cummax()
    features['drawdown'] = (df['close'] - running_max) / running_max
    features['ath'] = running_max

    ath_mask = df['close'] == running_max
    features['at_ath'] = ath_mask.astype(int)
    features['near_ath'] = (features['drawdown'] > STRATEGY_CONFIG['near_ath_threshold']).astype(int)

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
        (features['prior_max_drawdown'] < STRATEGY_CONFIG['ath_breakout_dd_requirement'])
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

    # Risk-adjusted metrics
    for w in [30, 60, 90, 180, 365]:
        rm = daily_ret.rolling(w).mean() * 365
        rs = daily_ret.rolling(w).std() * np.sqrt(365)
        features[f'sharpe_{w}d'] = rm / rs

        dr = daily_ret.copy()
        dr[dr > 0] = 0
        ds = dr.rolling(w).std() * np.sqrt(365)
        features[f'sortino_{w}d'] = rm / ds

    # Moving averages (SMA)
    for w in [50, 100, 200]:
        ma = df['close'].rolling(w).mean()
        features[f'price_vs_ma{w}'] = (df['close'] - ma) / ma
        features[f'above_ma{w}'] = (df['close'] > ma).astype(int)

    # EMA 200 for v9 filter
    ema_period = STRATEGY_CONFIG['ma_filter_period']
    features['ema_200'] = df['close'].ewm(span=ema_period, adjust=False).mean()
    features['above_ema_200'] = (df['close'] > features['ema_200']).astype(int)

    # Halving cycle
    def get_halving_info(date):
        date = pd.to_datetime(date)
        past = [h for h in HALVING_DATES if h <= date]
        future = [h for h in HALVING_DATES if h > date]
        days_since = (date - max(past)).days if past else np.nan
        days_until = (min(future) - date).days if future else np.nan
        return days_since, days_until, days_since / 1460 if not np.isnan(days_since) else np.nan

    halving_info = df['date'].apply(get_halving_info)
    features['days_since_halving'] = [x[0] for x in halving_info]
    features['days_until_halving'] = [x[1] for x in halving_info]
    features['halving_cycle_position'] = [x[2] for x in halving_info]

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


def train_model_and_predict(weekly_df, min_train_weeks=156):
    """Train XGBoost and get latest prediction"""
    try:
        import xgboost as xgb
    except ImportError:
        print("ERROR: XGBoost not installed. Run: pip install xgboost")
        return None

    feature_cols = get_feature_columns(weekly_df)

    # Use all data except last week for training
    train_df = weekly_df.iloc[:-1].dropna(subset=feature_cols + ['is_left_tail'])
    test_df = weekly_df.iloc[-1:]

    if len(train_df) < min_train_weeks:
        print(f"ERROR: Need at least {min_train_weeks} weeks of data")
        return None

    X_train = np.nan_to_num(train_df[feature_cols].values, nan=0.0)
    y_train = train_df['is_left_tail'].values

    # Check for degenerate case where only one class exists
    unique_classes = np.unique(y_train)
    if len(unique_classes) < 2:
        print(f"WARNING: Only one class in training data ({unique_classes})")
        # Return conservative estimate (no danger signal)
        return 0.0 if unique_classes[0] == 0 else 1.0

    model = xgb.XGBClassifier(
        max_depth=3, min_child_weight=10, subsample=0.8, colsample_bytree=0.8,
        learning_rate=0.05, n_estimators=100, reg_alpha=1.0, reg_lambda=1.0,
        random_state=42, verbosity=0
    )
    model.fit(X_train, y_train, sample_weight=np.where(y_train == 1, 3.0, 1.0))

    X_test = np.nan_to_num(test_df[feature_cols].values, nan=0.0)

    # Safely get probability for class 1 (left-tail)
    proba = model.predict_proba(X_test)
    if proba.shape[1] == 2:
        prob = proba[:, 1][0]
    else:
        # Single class prediction - use the prediction directly
        prob = float(model.predict(X_test)[0])

    return prob

# ============================================================================
# SIGNAL GENERATION (v9 - Updated Order of Operations)
# ============================================================================

def determine_position(drawdown, prob_left_tail, near_ath, ath_breakout, vol_high,
                       close_price=None, ema_200=None, mvrv=None, dvol_zscore=None):
    """
    Determine position based on strategy rules (v9).

    Order of operations:
    1. XGBoost danger (highest priority)
    2. ATH breakout
    3. Near ATH
    4. DD tiers (base leverage)
    5. EMA 200 filter (NEW v9)
    6. MVRV boost (NEW v9)
    7. DVOL filter (last)

    Returns: (leverage, position_name, reasoning)
    """
    config = STRATEGY_CONFIG
    reasoning_parts = []

    # Step 1: Danger signal (highest priority override)
    if prob_left_tail > config['danger_threshold']:
        return 0, 'CASH', f"Danger signal: prob={prob_left_tail:.1%} > {config['danger_threshold']:.0%}"

    # Step 2: ATH breakout after major drawdown
    if ath_breakout:
        lev = config['ath_breakout_leverage']
        return lev, f'{lev}x LEVER', f"ATH breakout after >{abs(config['ath_breakout_dd_requirement']):.0%} drawdown"

    # Step 3: Near ATH (with vol filter)
    if near_ath:
        if vol_high:
            return 1, '1x LONG', "Near ATH but high volatility - reducing leverage"
        else:
            lev = config['near_ath_leverage']
            return lev, f'{lev}x LEVER', f"Near ATH (DD > {config['near_ath_threshold']:.0%})"

    # Step 4: Base leverage from drawdown tiers
    base_leverage = 1
    for dd_upper, dd_lower, tier_lev in config['graduated_dd_tiers']:
        if drawdown < dd_upper and drawdown >= dd_lower:
            base_leverage = tier_lev
            reasoning_parts.append(f"DD tier ({dd_upper:.0%} to {dd_lower:.0%}) = {tier_lev}x")
            break
    else:
        reasoning_parts.append(f"Middle zone (DD={drawdown:.1%}) = 1x")

    # Step 5: Apply EMA 200 filter (NEW v9 - Binary 100/50)
    ema_applied = False
    if close_price is not None and ema_200 is not None and not pd.isna(ema_200):
        if close_price < ema_200:
            old_lev = base_leverage
            base_leverage = base_leverage * config['ma_filter_leverage_mult']
            reasoning_parts.append(f"Below EMA 200: {old_lev}x -> {base_leverage}x")
            ema_applied = True
        else:
            reasoning_parts.append("Above EMA 200: full leverage")

    # Step 6: Apply MVRV boost (NEW v9)
    mvrv_applied = False
    if close_price is not None and ema_200 is not None and mvrv is not None:
        if not pd.isna(ema_200) and not pd.isna(mvrv):
            if close_price > ema_200 and mvrv < config['mvrv_threshold']:
                old_lev = base_leverage
                base_leverage = min(config['mvrv_max_leverage'], base_leverage * config['mvrv_boost_mult'])
                reasoning_parts.append(f"MVRV boost (MVRV={mvrv:.2f} < {config['mvrv_threshold']}): {old_lev}x -> {base_leverage}x")
                mvrv_applied = True

    # Step 7: Apply DVOL filter (existing)
    dvol_applied = False
    if dvol_zscore is not None and pd.notna(dvol_zscore):
        if dvol_zscore > config['dvol_z_threshold'] and base_leverage > 1:
            old_lev = base_leverage
            base_leverage = max(1, base_leverage - 1)
            reasoning_parts.append(f"DVOL filter (z={dvol_zscore:.2f} > {config['dvol_z_threshold']}): {old_lev}x -> {base_leverage}x")
            dvol_applied = True

    # Determine position name
    if base_leverage == 0:
        position_name = 'CASH'
    elif base_leverage >= 1:
        position_name = f'{base_leverage}x LEVER' if base_leverage > 1 else '1x LONG'
    else:
        position_name = f'{base_leverage}x LONG'

    reasoning = " | ".join(reasoning_parts)
    return base_leverage, position_name, reasoning


def generate_signal(data_path, dvol_data: pd.DataFrame = None, mvrv_data: pd.DataFrame = None):
    """
    Main function to generate current trading signal (v9).

    Args:
        data_path: Path to BTC price data CSV
        dvol_data: Optional DataFrame with DVOL data (columns: date, dvol)
                   If None, will attempt to fetch from Deribit API
        mvrv_data: Optional DataFrame with MVRV data (columns: date, mvrv)
                   If None, will attempt to load from file

    Returns:
        Signal dict with position recommendation, or None if failed
    """

    # Load data
    print("Loading data...")
    df = load_btc_data(data_path)
    print(f"  Loaded {len(df)} days: {df['date'].min().date()} to {df['date'].max().date()}")

    # Compute features
    print("Computing features...")
    features = compute_features(df)

    # Create weekly data
    print("Creating weekly data...")
    weekly = create_weekly_data(features)

    # Get latest data point
    latest = weekly.iloc[-1]

    # Train model and get danger probability
    print("Training model...")
    prob_left_tail = train_model_and_predict(weekly)

    if prob_left_tail is None:
        return None

    # Extract current state
    current_state = {
        'date': str(latest['date'].date()),
        'price': float(latest['close']),
        'drawdown': float(latest['drawdown']),
        'ath': float(features['ath'].iloc[-1]),
        'prob_left_tail': float(prob_left_tail),
        'near_ath': bool(latest['near_ath']),
        'ath_breakout': bool(latest.get('ath_breakout', 0)),
        'vol_high': bool(latest.get('vol_30d_high', 0)),
        'days_since_ath': int(latest['days_since_ath']),
    }

    # Get EMA 200 value
    current_ema_200 = float(features['ema_200'].iloc[-1]) if 'ema_200' in features.columns else None
    current_state['ema_200'] = current_ema_200

    # Fetch DVOL data if not provided
    if dvol_data is None:
        print("Fetching DVOL data...")
        dvol_data = fetch_dvol_data()

    dvol_zscore = None
    if dvol_data is not None and len(dvol_data) > 0:
        dvol_zscore = calculate_dvol_zscore(dvol_data['dvol'])
        if pd.notna(dvol_zscore):
            print(f"  DVOL z-score: {dvol_zscore:.2f} (threshold: {STRATEGY_CONFIG['dvol_z_threshold']})")
        else:
            print("  DVOL z-score not available (insufficient data)")
    else:
        print("  DVOL data not available, continuing without filter")

    # Load MVRV data if not provided
    if mvrv_data is None:
        print("Loading MVRV data...")
        mvrv_data = load_mvrv_data()

    current_mvrv = None
    if mvrv_data is not None and len(mvrv_data) > 0:
        # Get MVRV for latest date (or closest available)
        latest_date = pd.to_datetime(latest['date']).date()
        mvrv_data['date_only'] = mvrv_data['date'].dt.date
        mvrv_match = mvrv_data[mvrv_data['date_only'] <= latest_date].tail(1)
        if len(mvrv_match) > 0:
            current_mvrv = float(mvrv_match['mvrv'].iloc[0])
            print(f"  MVRV: {current_mvrv:.2f} (threshold: {STRATEGY_CONFIG['mvrv_threshold']})")
        else:
            print("  MVRV data not available for current date")
    else:
        print("  MVRV data not loaded, MVRV boost disabled")

    current_state['mvrv'] = current_mvrv
    current_state['dvol_zscore'] = float(dvol_zscore) if pd.notna(dvol_zscore) else None

    # Determine position with all new filters
    leverage, position_name, reasoning = determine_position(
        drawdown=current_state['drawdown'],
        prob_left_tail=current_state['prob_left_tail'],
        near_ath=current_state['near_ath'],
        ath_breakout=current_state['ath_breakout'],
        vol_high=current_state['vol_high'],
        close_price=current_state['price'],
        ema_200=current_ema_200,
        mvrv=current_mvrv,
        dvol_zscore=dvol_zscore,
    )

    signal = {
        **current_state,
        'leverage': leverage,
        'position': position_name,
        'reasoning': reasoning,
        'above_ema_200': current_state['price'] > current_ema_200 if current_ema_200 else None,
        'mvrv_boost_eligible': (current_mvrv is not None and current_mvrv < STRATEGY_CONFIG['mvrv_threshold']
                                and current_state['price'] > current_ema_200 if current_ema_200 else False),
        'generated_at': datetime.now().isoformat(),
        'version': 'v9',
    }

    return signal


def print_signal(signal):
    """Pretty print the signal"""
    print("\n" + "=" * 70)
    print("BTC TAIL MODEL v9 - CURRENT SIGNAL")
    print("=" * 70)
    print(f"Date:           {signal['date']}")
    print(f"Price:          ${signal['price']:,.2f}")
    print(f"ATH:            ${signal['ath']:,.2f}")
    print(f"Drawdown:       {signal['drawdown']:.1%}")
    print(f"Days Since ATH: {signal['days_since_ath']}")
    print("-" * 70)
    print(f"Danger Prob:    {signal['prob_left_tail']:.1%}")
    print(f"Near ATH:       {'Yes' if signal['near_ath'] else 'No'}")
    print(f"ATH Breakout:   {'Yes' if signal['ath_breakout'] else 'No'}")
    print(f"Vol High:       {'Yes' if signal['vol_high'] else 'No'}")
    print("-" * 70)
    # v9 filters
    ema_200 = signal.get('ema_200')
    if ema_200 is not None:
        print(f"EMA 200:        ${ema_200:,.2f}")
        print(f"Above EMA 200:  {'Yes' if signal.get('above_ema_200') else 'No'}")
    else:
        print(f"EMA 200:        N/A")

    mvrv = signal.get('mvrv')
    if mvrv is not None:
        print(f"MVRV:           {mvrv:.2f} (threshold: {STRATEGY_CONFIG['mvrv_threshold']})")
        print(f"MVRV Boost:     {'Eligible' if signal.get('mvrv_boost_eligible') else 'Not eligible'}")
    else:
        print(f"MVRV:           N/A")

    dvol_z = signal.get('dvol_zscore')
    if dvol_z is not None:
        print(f"DVOL Z-Score:   {dvol_z:.2f} (threshold: {STRATEGY_CONFIG['dvol_z_threshold']})")
    else:
        print(f"DVOL Z-Score:   N/A")
    print("-" * 70)
    print(f"POSITION:       {signal['position']}")
    print(f"LEVERAGE:       {signal['leverage']}x")
    print(f"REASONING:      {signal['reasoning']}")
    print("=" * 70)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python v9_production.py <btc_data.csv>")
        print("  Optional: python v9_production.py <btc_data.csv> --json")
        sys.exit(1)

    data_path = sys.argv[1]
    output_json = '--json' in sys.argv

    signal = generate_signal(data_path)

    if signal:
        if output_json:
            print(json.dumps(signal, indent=2))
        else:
            print_signal(signal)
    else:
        print("ERROR: Failed to generate signal")
        sys.exit(1)
