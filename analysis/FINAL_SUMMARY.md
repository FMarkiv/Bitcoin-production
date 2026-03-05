# BTC Tail Model - Final Project Summary

**Generated:** 2026-01-20
**Status:** COMPLETE - Ready for Production

---

## Executive Summary

```
PROJECT:     BTC Tail Model Optimization
DURATION:    2026-01-18 to 2026-01-20
BASELINE:    81.2% IRR
FINAL:       119.9% IRR
IMPROVEMENT: +38.7%
STATUS:      Ready for Production (v9)
```

---

## 1. Performance Comparison

### 1.1 Key Metrics

| Metric | Baseline (v8) | Final Config (v9) | Change |
|--------|---------------|-------------------|--------|
| **IRR (Annualized)** | 81.2% | 119.9% | **+38.7%** |
| **Max Drawdown** | -96.6% | -87.5% | **+9.1%** |
| **Sharpe Ratio** | ~0.9 | 1.27 | **+41%** |
| Walk-Forward Beat Rate | N/A | 60% | New metric |
| Avg OOS IRR | N/A | 326.1% | New metric |

### 1.2 Component Contributions

| Feature | IRR Impact | Cumulative |
|---------|------------|------------|
| Baseline (v8 production) | 81.2% | 81.2% |
| + EMA 200 Filter (Binary 100/50) | +27.8% | 109.0% |
| + MVRV Boost (< 3.0, 1.25x) | +10.9% | 119.9% |

---

## 2. Final Configuration

### 2.1 Strategy Config

```python
STRATEGY_CONFIG = {
    # ============================================
    # EXISTING (Preserved from v8)
    # ============================================
    'danger_threshold': 0.20,           # XGBoost prob for cash
    'near_ath_threshold': -0.03,        # Within 3% of ATH
    'near_ath_leverage': 3,
    'ath_breakout_leverage': 10,
    'ath_breakout_dd_requirement': -0.60,
    'vol_high_threshold': 0.5,          # Vol z-score threshold
    'graduated_dd_tiers': [
        (-0.60, -0.70, 2),   # DD -60% to -70%: 2x
        (-0.70, -0.80, 3),   # DD -70% to -80%: 3x
        (-0.80, -1.00, 5),   # DD < -80%: 5x
    ],
    'dvol_z_threshold': 0.3,            # DVOL filter threshold
    'dvol_lookback': 30,                # DVOL rolling window

    # ============================================
    # NEW from Optimization (v9)
    # ============================================
    'ma_filter_type': 'ema',            # Use EMA not SMA
    'ma_filter_period': 200,            # EMA 200d
    'ma_filter_leverage_mult': 0.5,     # Binary 100/50 scheme
    'mvrv_threshold': 3.0,              # Boost when MVRV < 3.0
    'mvrv_boost_mult': 1.25,            # 25% boost multiplier
}
```

### 2.2 Signal Priority (Order of Operations)

```
1. XGBoost Danger (prob > 20%)     → CASH (0x)         [Highest priority]
2. ATH Breakout (after >60% DD)    → 10x LEVER
3. Near ATH (< 3% from ATH)        → 1x-3x (vol dependent)
4. DD Tiers (-60%/-70%/-80%)       → 2x/3x/5x
5. EMA 200 Filter (below EMA)      → 50% of base       [NEW]
6. MVRV Boost (>EMA & MVRV<3.0)    → 1.25x multiplier  [NEW]
7. DVOL Filter (z > 0.3)           → -1x reduction     [Last]
```

---

## 3. Complete Testing Record

### 3.1 Trend Following Indicators

| Indicator | Best Variant | IRR | vs Baseline | Implement? |
|-----------|--------------|-----|-------------|------------|
| **EMA** | **200** | **108.9%** | **+27.8%** | **YES** |
| SMA | 100 | 100.9% | +19.7% | NO (EMA better) |
| Golden Cross | 50/200 | 96.0% | +14.9% | NO |
| Ichimoku Cloud | Price Above | 98.8% | +17.6% | NO |
| Ichimoku Full Bullish | All signals | 97.9% | +16.7% | NO |

### 3.2 Momentum Indicators

| Indicator | Best Variant | IRR | vs Baseline | Implement? |
|-----------|--------------|-----|-------------|------------|
| MACD | Above Zero | 94.1% | +12.9% | NO |
| ROC | 7d Positive | 91.0% | +9.8% | NO |
| RSI | 14 | 54.3% | -26.9% | **NO** |
| RSI Oversold | < 30 | 8.0% | -73.3% | **NO** |
| Stochastic | Oversold | 46.1% | -35.1% | **NO** |
| Williams %R | Oversold | 46.1% | -35.1% | **NO** |
| CCI | 20 | 41.4% | -39.8% | **NO** |

### 3.3 Volatility Indicators

| Indicator | Best Variant | IRR | vs Baseline | Implement? |
|-----------|--------------|-----|-------------|------------|
| DVOL Filter | z > 0.3 | 97.6% | +16.4% | YES (existing) |
| Bollinger Bands | Lower touch | 47.7% | -33.5% | **NO** |
| ATR | High vol | 75.2% | -6% | NO |
| Keltner Channels | 20,2 | 81.0% | ~0% | NO |
| Donchian | At High | 84.7% | +3.5% | NO |

### 3.4 Volume Indicators

| Indicator | Best Variant | IRR | vs Baseline | Implement? |
|-----------|--------------|-----|-------------|------------|
| OBV | Bullish | 73.2% | -8% | NO |
| MFI | Oversold | 84.7% | +3.5% | NO |
| Volume SMA | High Vol | 50.1% | -31.1% | **NO** |

### 3.5 On-Chain Indicators

| Indicator | Threshold | IRR | vs Baseline | Implement? |
|-----------|-----------|-----|-------------|------------|
| MVRV < 1.5 + EMA 200 | 1.5 | 114.6% | +33.5% | NO (use 3.0) |
| MVRV < 2.0 + EMA 200 | 2.0 | 115.6% | +34.5% | NO (use 3.0) |
| MVRV < 2.5 + EMA 200 | 2.5 | 118.9% | +37.7% | NO (use 3.0) |
| **MVRV < 3.0 + EMA 200** | **3.0** | **119.9%** | **+38.7%** | **YES** |
| MVRV < 3.5 + EMA 200 | 3.5 | 124.2% | +43.0% | NO (less robust) |

### 3.6 Leverage Schemes Tested

| Scheme | IRR | vs Baseline | Implement? |
|--------|-----|-------------|------------|
| **Binary 100/50** | **109.6%** | **+28.5%** | **YES** |
| Binary 100/25 | 106.7% | +25.6% | NO |
| Binary 100/0 | 94.3% | +13.2% | NO |
| Tiered 100/75/50/25 | 95.7% | +14.5% | NO |
| Linear (0% at -20%) | 80.3% | -0.8% | NO |

### 3.7 Adaptive Volatility Tested

| Config | Description | IRR | vs Static | Implement? |
|--------|-------------|-----|-----------|------------|
| Static 0.50 | Baseline | 87.4% | - | **YES** |
| Config A (Linear) | 0.80 → 0.20 | 71.0% | -16.5% | NO |
| Config B (Low Vol Boost) | 0.75 if < 25% | 64.3% | -23.1% | NO |
| Config C (High Vol Protect) | 0.25 if > 75% | 82.0% | -5.5% | NO |
| Config D (Aggressive) | 1.00 → 0.00 | 45.5% | -41.9% | NO |
| Config E (Continuous) | Linear interp | 71.1% | -16.3% | NO |

### 3.8 Combination Tests

| Combination | IRR | vs Baseline | Implement? |
|-------------|-----|-------------|------------|
| EMA 200 only | 108.9% | +27.8% | PARTIAL |
| SMA 100 + MVRV<1.5 | 104.6% | +23.4% | NO |
| EMA 200 + MVRV<1.5 | 114.6% | +33.5% | NO |
| EMA 200 + MVRV<2.0 | 115.6% | +34.5% | NO |
| EMA 200 + MVRV<2.5 | 118.9% | +37.7% | NO |
| **EMA 200 + MVRV<3.0** | **119.9%** | **+38.7%** | **YES** |
| + Ichimoku Risk-Off | 102.7%-111.9% | Worse | NO |
| + Cloud Entry Boost | 108.8% | -5.9% | NO |

### 3.9 Cloud Entry Tests (All DD Levels)

| DD Level | 52W Return | Win Rate | As Boost IRR | Implement? |
|----------|------------|----------|--------------|------------|
| Any DD | +420.8% | 82% | 106.1% | NO |
| > 20% DD | +462.2% | 80% | 107.3% | NO |
| > 30% DD | +303.4% | 79% | 108.8% | NO |
| > 40% DD | +318.4% | 83% | 105.2% | NO |
| > 50% DD | +322.0% | 89% | 103.9% | NO |
| > 60% DD | +359.9% | 93% | 102.1% | NO |

**Conclusion:** Great analytics, but all implementation methods hurt IRR.

### 3.10 Capitulation Signals (52-Week Forward Returns)

| Signal | 52W Return | Win Rate | Max Further DD | Use? |
|--------|------------|----------|----------------|------|
| Below BB + >30% DD | +312.2% | 66% | -85% | INFO ONLY |
| Williams Oversold + >50% DD | +231.9% | 81% | -85% | INFO ONLY |
| Stochastic Oversold + >40% DD | +224.0% | 75% | -88% | INFO ONLY |
| RSI 14 < 25 | +188.7% | 72% | -87% | INFO ONLY |
| Cloud Entry + >60% DD | +359.9% | 93% | -84% | INFO ONLY |

**Note:** These signals are useful for conviction during drawdowns but should NOT be used for leverage adjustments.

---

## 4. Walk-Forward Validation

### 4.1 Methodology

- Training window: 3 years
- Test window: 1 year
- Step forward: 1 year
- Total test periods: 10

### 4.2 Results by Period

| Train Period | Test Period | Strategy IRR | B&H IRR | Beat B&H | Max DD |
|--------------|-------------|--------------|---------|----------|--------|
| 2013-2015 | 2016 | 156.1% | 121.6% | YES | -34.9% |
| 2014-2016 | 2017 | 1694.4% | 1306.5% | YES | -40.6% |
| 2015-2017 | 2018 | -79.8% | -72.4% | NO | -85.3% |
| 2016-2018 | 2019 | 517.3% | 87.0% | YES | -54.3% |
| 2017-2019 | 2020 | 531.4% | 300.2% | YES | -37.7% |
| 2018-2020 | 2021 | 40.3% | 58.0% | NO | -49.9% |
| 2019-2021 | 2022 | -60.8% | -65.2% | YES | -62.3% |
| 2020-2022 | 2023 | 376.3% | 154.3% | YES | -23.3% |
| 2021-2023 | 2024 | 105.8% | 111.8% | NO | -32.8% |
| 2022-2024 | 2025 | -19.6% | -2.1% | NO | -29.3% |

### 4.3 Summary Statistics

| Metric | Value |
|--------|-------|
| Total Test Periods | 10 |
| Periods Beating B&H | **6 (60%)** |
| Average OOS IRR | **326.1%** |
| Average B&H IRR | 200.0% |
| Best Period | 2017 (1694.4%) |
| Worst Period | 2018 (-79.8%) |

### 4.4 Performance Trend Warning

| Period | Avg OOS IRR |
|--------|-------------|
| First Half (2016-2020) | **563.9%** |
| Second Half (2021-2025) | **88.4%** |

**Trend: DEGRADING** - Strategy alpha appears to be decaying in recent years.

---

## 5. Parameter Robustness

All parameters showed **<15% IRR swing** = NOT OVERFIT

| Parameter | Test Range | IRR Min | IRR Max | Swing | Status |
|-----------|------------|---------|---------|-------|--------|
| EMA Period | 150-250 | 114.9% | 121.6% | 6.7% | ROBUST |
| MVRV Threshold | 2.5-3.5 | 118.9% | 124.2% | 5.3% | ROBUST |
| Below-MA Mult | 0.3-0.7 | 114.6% | 119.9% | 5.3% | ROBUST |
| MVRV Boost | 1.1-1.4 | 113.6% | 125.1% | 11.5% | ROBUST |

---

## 6. Regime Analysis

| Regime | % of Time | Strategy IRR | B&H IRR | Outperformance |
|--------|-----------|--------------|---------|----------------|
| Bull (>50% trailing 12m) | 60% | 129.8% | 113.1% | **+16.8%** |
| Bear (<-30% trailing 12m) | 16% | 290.8% | 82.6% | **+208.2%** |
| Sideways | 23% | 274.6% | 229.2% | **+45.4%** |

**Key Finding:** Strategy outperforms in ALL market regimes, with largest edge in bear markets.

---

## 7. Key Discoveries

### 7.1 MVRV: Filter, Not Trigger

- MVRV alone fails as a signal because it fires 50-100+ days before actual bottoms
- Combined with trend confirmation (EMA 200), it becomes effective
- MVRV < 3.0 outperformed < 1.5 because it captures more of the bull run
- **Implementation:** Only boost when ABOVE EMA AND MVRV < 3.0

### 7.2 The RSI Paradox

- RSI has highest raw correlation with forward returns (0.246)
- But using RSI oversold as a trading signal produces worst IRR (-73%)
- **Lesson:** Correlation is descriptive, not prescriptive

### 7.3 Longer MAs Win

- 200-period MAs consistently outperform 50 and 100
- Aligns with strategy thesis (capturing tail events, not day trading)
- EMA 200 maintains positive correlation even at 52-week horizon

### 7.4 EMA > SMA at Long Horizons

- SMA 200 correlation goes negative at 52W (-0.067)
- EMA 200 stays positive (0.124)
- EMA's faster response prevents "stale" signals
- **Implementation:** Use EMA, not SMA

### 7.5 Adaptive Volatility Fails

- Low volatility does NOT equal low risk
- 14.7% crash probability even in "very low vol" regimes
- 544 events where low vol was followed by >30% drawdowns
- Static protection (0.50 multiplier) beats all dynamic adjustments
- **Implementation:** Keep static 0.50 below-MA multiplier

### 7.6 Cloud Entry: Great Analytics, Bad Signal

- Cloud entry at 60% DD shows 93% win rate, +360% 52W return
- But every implementation method hurt strategy IRR
- **Use:** For conviction during drawdowns, NOT for position sizing

### 7.7 Performance Degradation

- First half (2016-2020): 564% avg OOS IRR
- Second half (2021-2025): 88% avg OOS IRR
- Strategy edge concentrated in crash/recovery periods
- **Expectation:** Underperformance in grinding bull markets without major corrections

---

## 8. What NOT to Implement

Based on extensive testing, these features are explicitly rejected:

| Feature | IRR Impact | Reason |
|---------|------------|--------|
| Ichimoku Risk-Off | -2.7% to -12% | Tested, hurts more than helps |
| Cloud Entry Boost | -1.7% to -30% | All DD levels tested, all hurt |
| RSI/Stochastic Oversold | -35% to -59% | Catches falling knives |
| Bollinger Band Oversold | -27% to -33% | Same issue |
| Adaptive Vol Multiplier | -5.5% to -42% | All configs underperformed static |
| SMA (instead of EMA) | -1% to -5% | EMA has better long-horizon correlation |
| MVRV < 1.5 (instead of 3.0) | -5.3% | Less signal, less boost opportunity |

---

## 9. Known Limitations

1. **Underperforms in grinding bulls**: 2021, 2024, 2025 all underperformed B&H
2. **ATH breakout requires prior crash**: 10x leverage only triggers after >60% DD
3. **Performance degradation**: Recent years show lower alpha vs historical
4. **Edge concentrated in crashes**: Strategy shines during crisis, not normal markets
5. **Max drawdown still high**: -87.5% DD possible even with optimizations

---

## 10. Baseline Reconciliation

Two baseline IRRs appeared in analysis documents:

| Source | IRR | Leverage Tiers | Status |
|--------|-----|----------------|--------|
| Legacy test | 114.9% | 2x at -40%, 3x at -60% | **DEPRECATED** |
| Production-aligned | 81.2% | 2x at -60%, 3x at -70%, 5x at -80% | **AUTHORITATIVE** |

**AUTHORITATIVE BASELINE: 81.2%**
- Matches production code in v8_production.py
- All improvements measured against this baseline

---

## 11. Maintenance Schedule

| Frequency | Action |
|-----------|--------|
| Weekly | Monitor signals and execution |
| Monthly | Update MVRV data from CoinMetrics |
| Quarterly | Re-run correlation analysis, check regime |
| Annually | Full walk-forward re-validation |

---

## 12. Future Considerations (Not Implemented)

Flagged for potential future investigation:

1. **Time-based ATH boost**: If at ATH >90 days without correction
2. **Cross-asset signals**: SPX tail events as BTC correlation trigger
3. **Options overlay**: Buy cheap OTM calls during low vol periods
4. **Yield overlay**: Deploy idle capital to staking/lending when below EMA

---

## 13. Files Generated

### Analysis Documents
- `STATE.md` - Project state and context
- `IMPLEMENTATION_SPEC.md` - Production specification
- `IMPLEMENTATION_VERIFICATION.md` - Gap analysis
- `WALK_FORWARD_VALIDATION.md` - OOS validation results
- `ADAPTIVE_VOL_ANALYSIS.md` - Adaptive vol testing
- `BASELINE_RECONCILIATION.md` - Baseline IRR clarification
- `FINAL_SUMMARY.md` - This document

### Charts
- `correlation_heatmap_52w.png` - 6 horizons including 52W
- `capitulation_52w_analysis.png` - Capitulation 52W returns
- `mvrv_threshold_comparison.png` - MVRV sensitivity
- `ichimoku_riskoff_test.png` - Ichimoku test results
- `cloud_entry_signal.png` - Cloud entry test
- `cloud_entry_dd_analysis.png` - Cloud entry by DD level
- `walk_forward_results.png` - Walk-forward IRR by year
- `parameter_sensitivity.png` - Parameter robustness
- `regime_analysis.png` - Performance by regime
- `adaptive_vol_analysis.png` - Adaptive vol multiplier test

### Test Scripts
- `test_final_config.py` - Final configuration testing
- `test_cloud_dd_walkforward.py` - Walk-forward validation
- `test_adaptive_vol_regime.py` - Adaptive vol testing
- `test_comprehensive_indicators.py` - All indicator testing

---

## 14. Conclusion

The BTC Tail Model optimization project successfully improved IRR from 81.2% to 119.9% (+38.7%) through the addition of:

1. **EMA 200 Filter** (+27.8% IRR): Binary 100/50 leverage reduction below EMA 200
2. **MVRV Boost** (+10.9% IRR): 1.25x multiplier when above EMA AND MVRV < 3.0

The strategy has been validated through:
- Walk-forward testing (60% OOS beat rate)
- Parameter sensitivity analysis (<15% IRR swing)
- Regime analysis (outperforms in all market conditions)

Key decisions were made to NOT implement features that tested poorly, including Ichimoku signals, cloud entry boosts, RSI/Stochastic oversold, and adaptive volatility multipliers.

The strategy is ready for production deployment as v9.

---

*BTC Tail Model - Final Project Summary*
*Generated: 2026-01-20*
*Status: COMPLETE*
