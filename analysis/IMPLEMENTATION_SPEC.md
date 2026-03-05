# BTC Tail Model v9 - Implementation Specification

**Version:** v9 Production
**Date:** 2026-01-21
**Status:** VALIDATED - Ready for Deployment

---

## 1. Strategy Overview

The BTC Tail Model is a tail-risk trading strategy that uses XGBoost machine learning to predict left-tail events and adjusts leverage based on market conditions.

### Core Thesis

1. During major crashes (>60% drawdown), increase leverage to capture recovery
2. During normal conditions, maintain modest exposure
3. Reduce exposure when danger signals appear or bearish regime detected

---

## 2. Signal Priority (Order of Operations)

```
Priority  Signal                      Action
========  ==========================  ================
1 (High)  XGBoost Danger (>20%)       → CASH (0x)
2         ATH Breakout (after >60%)   → 10x LEVER
3         Near ATH (<3% from ATH)     → 1x-3x (vol dependent)
4         DD Tiers                    → 2x/3x/5x (graduated)
5         EMA 200 Filter (below)      → 50% of base leverage
6         MVRV Boost (>EMA & <3.0)    → 1.25x multiplier (max 5x)
7 (Last)  DVOL Filter (z > 0.3)       → -1x reduction
```

---

## 3. Configuration Parameters

### 3.1 Core Parameters (Preserved from v8)

```python
STRATEGY_CONFIG = {
    # Danger threshold
    'danger_threshold': 0.20,           # XGBoost prob for cash signal

    # Near ATH
    'near_ath_threshold': -0.03,        # Within 3% of ATH
    'near_ath_leverage': 3,             # Leverage when near ATH (low vol)

    # ATH Breakout
    'ath_breakout_leverage': 10,        # Max leverage on breakout
    'ath_breakout_dd_requirement': -0.60,  # Min prior DD required

    # Volatility
    'vol_high_threshold': 0.5,          # Vol z-score for high vol flag

    # Graduated DD Tiers
    'graduated_dd_tiers': [
        (-0.60, -0.70, 2),   # DD -60% to -70%: 2x leverage
        (-0.70, -0.80, 3),   # DD -70% to -80%: 3x leverage
        (-0.80, -1.00, 5),   # DD < -80%: 5x leverage
    ],

    # DVOL Filter
    'dvol_z_threshold': 0.3,            # Z-score threshold
    'dvol_lookback': 30,                # Rolling window (days)
}
```

### 3.2 New v9 Parameters

```python
# EMA 200 Filter (Binary 100/50)
'ma_filter_type': 'ema',            # Use EMA (not SMA)
'ma_filter_period': 200,            # 200-day EMA
'ma_filter_leverage_mult': 0.5,     # 50% leverage when below EMA

# MVRV Boost
'mvrv_threshold': 3.0,              # Boost when MVRV < 3.0
'mvrv_boost_mult': 1.25,            # 25% leverage increase
'mvrv_max_leverage': 5,             # Cap for MVRV-boosted leverage
```

---

## 4. Signal Generation Logic

### 4.1 Pseudocode

```python
def determine_position(market_state):
    # Step 1: Danger override (highest priority)
    if xgboost_prob > 0.20:
        return CASH

    # Step 2: ATH breakout
    if at_ath AND prior_max_drawdown < -0.60:
        return 10x LEVER

    # Step 3: Near ATH
    if drawdown > -0.03:  # Within 3% of ATH
        if vol_high:
            return 1x LONG
        else:
            return 3x LEVER

    # Step 4: DD tiers (base leverage)
    if -0.70 <= drawdown < -0.60:
        base_leverage = 2
    elif -0.80 <= drawdown < -0.70:
        base_leverage = 3
    elif drawdown < -0.80:
        base_leverage = 5
    else:
        base_leverage = 1

    # Step 5: EMA 200 filter
    if price < ema_200:
        base_leverage *= 0.5

    # Step 6: MVRV boost
    if price > ema_200 AND mvrv < 3.0:
        base_leverage = min(5, base_leverage * 1.25)

    # Step 7: DVOL filter (last)
    if dvol_zscore > 0.3 AND base_leverage > 1:
        base_leverage -= 1

    return base_leverage
```

### 4.2 Important Notes

1. **EMA 200 filter is BINARY:** Either full leverage (above) or 50% (below)
2. **MVRV boost requires BOTH conditions:** Above EMA 200 AND MVRV < 3.0
3. **MVRV boost capped at 5x:** Only ATH breakout can reach 10x
4. **Order matters:** Apply filters in exact sequence specified

---

## 5. Data Requirements

### 5.1 Price Data

| Source | Priority | Notes |
|--------|----------|-------|
| Hyperliquid API | 1 | Preferred (eliminates oracle mismatch) |
| CoinGecko API | 2 | Fallback (close prices only) |
| Local BTC.csv | 3 | Emergency fallback |

**Minimum history:** 200 days for EMA 200 calculation

### 5.2 MVRV Data

- **Source:** CoinMetrics
- **File:** `data/mvrv_coinmetrics.csv`
- **Columns:** `time`, `CapMVRVCur`
- **Update Frequency:** Monthly

**Degradation:** If MVRV unavailable, strategy works but loses ~10% IRR edge

### 5.3 DVOL Data

- **Source:** Deribit API
- **Endpoint:** `/api/v2/public/get_volatility_index_data`
- **Update Frequency:** Daily
- **Lookback:** 30 days for z-score

---

## 6. Performance Expectations

### 6.1 Backtest Results

| Metric | Value |
|--------|-------|
| IRR (2013-2025) | 119.9% |
| Max Drawdown | -87.5% |
| Sharpe Ratio | 1.27 |
| Walk-Forward Beat Rate | 60% |

### 6.2 Regime Performance

| Regime | Strategy IRR | B&H IRR | Edge |
|--------|--------------|---------|------|
| Bull (>50% trailing) | 129.8% | 113.1% | +16.8% |
| Bear (<-30% trailing) | 290.8% | 82.6% | +208.2% |
| Sideways | 274.6% | 229.2% | +45.4% |

### 6.3 Holdout Validation (2025-09 to 2025-11)

| Metric | V9 | B&H | Edge |
|--------|----|----|------|
| Return | +0.5% | -19.5% | +20.0% |
| Max DD | -20.1% | -24.8% | +4.6% |

---

## 7. Risk Management

### 7.1 Leverage Limits

| Condition | Max Leverage |
|-----------|--------------|
| Normal operations | 5x |
| MVRV boost | 5x (capped) |
| ATH breakout | 10x |
| Below EMA 200 | 2.5x (5x * 0.5) |

### 7.2 Position Sizing

- Weekly rebalancing (default: Sundays)
- Diversified deployment: 1/7th position daily (recommended)
- Single deployment: Full position on rebalance day

### 7.3 Stop Loss

No explicit stop loss - strategy uses:
- XGBoost danger signal to exit to cash
- Graduated leverage reduction via filters

---

## 8. Deployment

### 8.1 Command Line

```bash
# Dry run (signals only)
python src/run_bot.py --dry-run

# Production (single run)
python src/run_bot.py --once

# Continuous mode
python src/run_bot.py --continuous

# Testnet
python src/run_bot.py --testnet
```

### 8.2 Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `HL_PRIVATE_KEY` | For trading | Hyperliquid wallet key |
| `TELEGRAM_BOT_TOKEN` | For alerts | Telegram bot token |
| `TELEGRAM_CHAT_ID` | For alerts | Chat ID for notifications |

---

## 9. Monitoring

### 9.1 Key Metrics to Track

- Weekly signal accuracy
- Leverage utilization
- Drawdown vs benchmark
- EMA filter activation rate
- MVRV boost activation rate

### 9.2 Alert Conditions

- Danger signal activated (CASH position)
- ATH breakout signal
- Max leverage reached (5x or 10x)
- Execution failures

---

## 10. Version History

| Version | Date | Changes |
|---------|------|---------|
| v9 | 2026-01-20 | Added EMA 200 filter, MVRV boost |
| v8.1 | Previous | DVOL filter, diversified deployment |
| v8 | Previous | Graduated DD tiers, XGBoost danger |

---

*Implementation Specification - BTC Tail Model v9*
*Generated: 2026-01-21*
