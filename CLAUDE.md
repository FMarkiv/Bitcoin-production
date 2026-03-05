# BTC Tail Model Trading Bot - v10 Production

**Version:** v10 (Released 2026-03-05)

## Overview

Automated Bitcoin tail-risk trading bot using XGBoost to predict left-tail events (significant price drops) and adjust position leverage accordingly. Designed to capture extreme market movements during crash recoveries.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      run_bot.py                             │
│                  (Main Orchestrator)                        │
│  - Fetches BTC data from CoinGecko/Hyperliquid             │
│  - Coordinates signal generation & execution                │
│  - Manages scheduling (rebalance on Sundays)               │
└─────────────┬───────────────┬───────────────┬──────────────┘
              │               │               │
              ▼               ▼               ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│v9_production.py │  │hyperliquid_     │  │telegram_alerts  │
│                 │  │executor.py      │  │.py              │
│ - Feature eng.  │  │                 │  │                 │
│ - XGBoost model │  │ - Exchange API  │  │ - Send signals  │
│ - Signal logic  │  │ - Position mgmt │  │ - Error alerts  │
│ - EMA 200 filter│  └─────────────────┘  └─────────────────┘
│ - MVRV boost    │
└─────────────────┘
```

## Strategy Logic

### Position Rules (Priority Order)

```
1. XGBoost Danger (prob > 20%)      → CASH (0x)          [Highest]
2. ATH Breakout (after >60% DD)     → 10x LEVER
3. Near ATH (< 3% from ATH)        → 1x-3x (vol dependent)
4. DD Tiers (-60%/-70%/-80%)        → 2x/3x/5x
5. EMA 200 Filter (below EMA)      → 50% of base
6. MVRV Boost (>EMA & MVRV<3.0)    → 1.25x multiplier (capped at 5x)
7. DVOL Filter (z > 0.3)           → -1x reduction      [Last]
```

### Configuration

```python
STRATEGY_CONFIG = {
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
```

## Data Sources

### Price Data (Priority Order)
1. **Hyperliquid API** (preferred) - Eliminates oracle mismatch
2. **CoinGecko API** (fallback) - Close prices only
3. **Local BTC.csv** (last resort) - Stale data fallback

### MVRV Data
- **Source:** CoinMetrics
- **File:** `data/mvrv_coinmetrics.csv`
- **Columns:** time, CapMVRVCur

## Running the Bot

```bash
# Production
python src/run_bot.py --once                   # Single run (for cron)
python src/run_bot.py --continuous             # Checks hourly, rebalances Sundays
python src/run_bot.py --force                  # Force rebalance regardless of schedule

# Testing
python src/run_bot.py --dry-run                # Signals only, no trades
python src/run_bot.py --mock                   # Mock everything
python src/run_bot.py --testnet                # Hyperliquid testnet

# Deployment mode (default: diversified)
python src/run_bot.py --deployment single      # Full position on Sunday
python src/run_bot.py --deployment diversified  # 1/7th daily (recommended)
```

## Testing

```bash
python tests/test_v9_signal.py
# Expected output: ALL TESTS PASSED
```

## Folder Structure

```
v10_production/
├── src/
│   ├── v9_production.py          # Signal generation (EMA 200 + MVRV boost)
│   ├── run_bot.py                # Main orchestrator
│   ├── hyperliquid_executor.py   # Hyperliquid API integration
│   ├── telegram_alerts.py        # Telegram notifications
│   └── logger.py                 # Logging configuration
├── data/
│   ├── BTC.csv                   # Historical BTC price data
│   ├── dvol_history.csv          # Deribit volatility index history
│   └── mvrv_coinmetrics.csv      # MVRV ratio data from CoinMetrics
├── tests/
│   └── test_v9_signal.py         # Signal logic tests
├── analysis/
│   ├── STATE.md                  # Current project state
│   ├── FINAL_SUMMARY.md          # Complete testing & optimization record
│   ├── IMPLEMENTATION_SPEC.md    # Production specification
│   └── HOLDOUT_VALIDATION.md     # Out-of-sample validation report
├── CLAUDE.md                     # This file
├── README.md                     # User documentation
└── requirements.txt              # Python dependencies
```

## Dependencies

```
pandas
numpy
xgboost
requests
hyperliquid-python-sdk
```

## Code Conventions

- **Exception handling**: Specific exceptions only, no bare `except`
- **Timezone**: All timestamps use `datetime.now(timezone.utc)`
- **Logging**: Use `logger` from logger.py, not `print()`
- **Configuration**: Constants in `STRATEGY_CONFIG` dict

## Performance

| Metric | Value |
|--------|-------|
| IRR (Annualized) | 119.9% |
| Max Drawdown | -87.5% |
| Sharpe Ratio | 1.27 |
| Walk-Forward Beat Rate | 60% (6/10 periods) |
| Avg OOS IRR | 326% |

**Regime performance**: Excels in bear markets (+208% edge over B&H), underperforms in grinding bulls.

**Performance trend**: First half (2016-2020) averaged 564% IRR, second half (2021-2025) averaged 88%. Monitor for continued alpha decay.

## Known Limitations

1. **Underperforms grinding bulls** - Strategy excels in crash/recovery, not steady uptrends
2. **ATH breakout requires prior crash** - 10x leverage only after >60% drawdown
3. **Performance degradation** - Recent years show lower alpha than historical
4. **MVRV dependency** - ~10% IRR edge lost if data unavailable

## Features Tested & Rejected

| Feature | IRR Impact |
|---------|------------|
| Ichimoku Risk-Off | -2.7% to -12% |
| Cloud Entry Boost | -1.7% to -30% |
| RSI/Stochastic Oversold | -35% to -59% |
| Adaptive Vol Multiplier | -5.5% to -42% |

## Changelog

### v10 (2026-03-05)
- Promoted to v10 production deployment folder
- Restructured project documentation

### v9 (2026-01-20)
- Added EMA 200 filter (Binary 100/50 leverage reduction, +27.8% IRR)
- Added MVRV boost (1.25x when conditions met, +10.9% IRR)
- Updated order of operations (7 steps)
- Performance: 81.2% → 119.9% IRR (+38.7%)

### v8.1
- DVOL Regime-Aware Filter (+16.4% IRR)
- Deployment Diversification (+19.9% IRR)
- Retry logic with exponential backoff
- Centralized logging framework

## Maintenance Schedule

| Frequency | Action |
|-----------|--------|
| Weekly | Monitor signals and execution |
| Monthly | Update MVRV data from CoinMetrics |
| Quarterly | Re-run correlation analysis, check regime changes |
| Annually | Full walk-forward re-validation |

**Review Trigger:** If strategy underperforms B&H for 3 consecutive years, consider full strategy review.
