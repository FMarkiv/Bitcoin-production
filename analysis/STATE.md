# BTC Tail Model v9 - Project State

**Last Updated:** 2026-01-21
**Status:** PRODUCTION READY - Holdout Validated

---

## Current Version: v9

### Configuration Summary

```python
STRATEGY_CONFIG = {
    # Core parameters (from v8)
    'danger_threshold': 0.20,
    'near_ath_threshold': -0.03,
    'near_ath_leverage': 3,
    'ath_breakout_leverage': 10,
    'ath_breakout_dd_requirement': -0.60,
    'graduated_dd_tiers': [(-0.60, -0.70, 2), (-0.70, -0.80, 3), (-0.80, -1.00, 5)],
    'dvol_z_threshold': 0.3,

    # New v9 additions
    'ma_filter_type': 'ema',
    'ma_filter_period': 200,
    'ma_filter_leverage_mult': 0.5,
    'mvrv_threshold': 3.0,
    'mvrv_boost_mult': 1.25,
}
```

### Performance Summary

| Metric | V8 Baseline | V9 Final | Improvement |
|--------|-------------|----------|-------------|
| IRR (Backtest) | 81.2% | 119.9% | +38.7% |
| Max Drawdown | -96.6% | -87.5% | +9.1% |
| Sharpe Ratio | ~0.9 | 1.27 | +41% |

---

## Validation Status

### Walk-Forward Validation (10 periods, 2016-2025)

| Metric | Value |
|--------|-------|
| Test Periods | 10 |
| Beat Buy-and-Hold | 60% |
| Avg OOS IRR | 326% |
| Best Year | 2017 (+1694%) |
| Worst Year | 2018 (-80%) |

**Warning:** Performance trend shows degradation:
- 2016-2020: 564% avg IRR
- 2021-2025: 88% avg IRR

### Holdout Validation (TRUE Out-of-Sample)

**Period:** 2025-09-21 to 2025-11-23 (10 weeks)

| Metric | V9 Strategy | Buy & Hold | V9 Edge |
|--------|-------------|------------|---------|
| Total Return | +0.5% | -19.5% | **+20.0%** |
| Max Drawdown | -20.1% | -24.8% | **+4.6%** |
| Annualized IRR | +2.6% | -67.6% | **+70.2%** |

**Result:** STRONG PASS
- Beat Buy & Hold: YES
- Lower Max DD: YES
- No catastrophic loss: YES
- Signal logic correct: YES

### V9 vs V8 on Holdout

| Metric | V9 | V8 | V9 Edge |
|--------|----|----|---------|
| Total Return | +0.5% | -4.7% | +5.2% |
| Max Drawdown | -20.1% | -24.8% | +4.6% |

**Conclusion:** V9 improvements (EMA 200 filter, MVRV boost) confirmed on holdout data.

---

## Key Decisions Made

### Implemented (v9)

1. **EMA 200 Filter** (+27.8% IRR)
   - Binary 100/50 scheme
   - Below EMA 200 → 50% leverage
   - Rationale: Reduces exposure in bearish regime

2. **MVRV Boost** (+10.9% IRR)
   - 1.25x multiplier when above EMA 200 AND MVRV < 3.0
   - Capped at 5x max (10x only for ATH breakout)
   - Rationale: Not overheated = safe for mild leverage increase

### Rejected (Tested, hurt performance)

| Feature | IRR Impact | Reason |
|---------|------------|--------|
| Ichimoku Risk-Off | -2.7% to -12% | Too conservative |
| Cloud Entry Boost | -1.7% to -30% | All DD levels hurt |
| RSI/Stochastic Oversold | -35% to -59% | Catches falling knives |
| Adaptive Vol Multiplier | -5.5% to -42% | Static 0.5 better |

---

## Files Reference

### Production Code
- `src/v9_production.py` - Signal generation
- `src/run_bot.py` - Main orchestrator
- `src/hyperliquid_executor.py` - Exchange integration
- `src/telegram_alerts.py` - Notifications

### Analysis Documents
- `analysis/FINAL_SUMMARY.md` - Complete testing record
- `analysis/HOLDOUT_VALIDATION.md` - Out-of-sample validation
- `analysis/STATE.md` - This file

### Generated Charts
- `analysis/holdout_performance.png` - Equity curves
- `analysis/holdout_signals.png` - Signal visualization

---

## Maintenance Schedule

| Frequency | Action |
|-----------|--------|
| Weekly | Monitor signals and execution |
| Monthly | Update MVRV data from CoinMetrics |
| Quarterly | Re-run correlation analysis |
| Annually | Full walk-forward re-validation |

**Review Trigger:** If strategy underperforms B&H for 3 consecutive years.

---

## Known Limitations

1. **Underperforms in grinding bulls** - Strategy excels in crash/recovery
2. **ATH breakout requires prior crash** - 10x only after >60% DD
3. **Performance degradation** - Recent years show lower alpha
4. **MVRV data dependency** - ~10% IRR edge lost if unavailable

---

## Deployment Checklist

- [x] Walk-forward validation (60% beat rate)
- [x] Parameter robustness (<15% IRR swing)
- [x] Holdout validation (STRONG PASS)
- [x] Signal logic tests passing
- [x] Documentation complete
- [ ] Production deployment
- [ ] Monitoring setup

---

*State Document - BTC Tail Model v9*
*Last Updated: 2026-01-21*
