# Trajectory Lookback Window — Research Report

**Date:** 2026-05-15
**Source:** `analysis/trajectory_lookback_sweep.py`
**Raw output:** `analysis/trajectory_lookback_sweep_results.txt`
**Data window:** 2010-07-17 → 2025-11-18 (5,604 daily rows from `data/BTC.csv`)

---

## TL;DR

| Candidate | When to pick | Edge (1Y) | Edge (3M) | Mid-DD regime |
|-----------|--------------|-----------|-----------|---------------|
| **L = 21** | Strict reading of the spec's decision rule | +318% (t=+2.28) | **−22%** (t=−1.18) | **fails** (t=−0.50) |
| **L = 90** | Recommended in practice (matches weekly rebalance horizon) | +264% (t=+5.75) | +76% (t=+4.27) | borderline (t=+1.81) |
| **L = 120** | Maximum regime robustness | +342% (t=+7.16) | +65% (t=+3.48) | passes (t=+2.93) |

**Recommendation: `DEFAULT_TRAJECTORY_LOOKBACK_DAYS = 90`.**

The spec's decision rule, applied verbatim to the main 1Y sweep, selects
**L = 21**. However, L = 21 fails two of the three robustness checks: the
trajectory edge flips sign at the 3-month forward horizon (the horizon
most relevant for a weekly-rebalanced strategy), and the falling/
recovering separation disappears in the mid-DD regime (-50% to -30%).
L = 90 is the smallest window that passes all three checks
(main, 3M-horizon, shallow+deep regimes) with t-statistics > 4.

---

## 1. Main sweep — pooled buckets [-80%, -10%], threshold = 0.03, 1Y horizon

```
  L | n_fall | n_rec | n_flat | mean_1Y_fall | mean_1Y_rec |   edge | t-stat | p-value
----+--------+-------+--------+--------------+-------------+--------+--------+--------
  7 |   367  |  289  |  421   |    +584.7%   |   +853.7%   | +269%  | +1.21  | 0.2271
 14 |   454  |  318  |  300   |    +423.3%   |   +724.4%   | +301%  | +1.87  | 0.0626
 21 |   478  |  334  |  256   |    +395.0%   |   +712.8%   | +318%  | +2.28  | 0.0228   <-- strict winner
 30 |   500  |  350  |  212   |    +317.1%   |   +575.6%   | +259%  | +2.45  | 0.0147
 45 |   527  |  399  |  130   |    +206.6%   |   +500.9%   | +294%  | +4.33  | 0.0000
 60 |   508  |  425  |  121   |    +185.2%   |   +440.7%   | +256%  | +4.66  | 0.0000
 90 |   465  |  479  |  107   |    +150.6%   |   +414.2%   | +264%  | +5.75  | 0.0000
120 |   483  |  481  |   80   |    +117.0%   |   +459.1%   | +342%  | +7.16  | 0.0000
180 |   426  |  514  |   80   |     +74.2%   |   +426.0%   | +352%  | +7.97  | 0.0000
```

Smallest L that clears edge>20%, |t|>2.0, n_fall+n_rec ≥ 15 each:
**L = 21**. Edge +317.7%, t = +2.28, p = 0.023, n_fall = 478, n_rec = 334.

The edge stays in a wide +250–350% band across the whole sweep — the
signal exists, but the **t-stat climbs monotonically with L** (1.21 → 7.97),
meaning longer windows produce a much higher-confidence read of the same
underlying separation.

## 2. Robustness check A — bucket subsets

### Shallow drawdowns (-30% to -10%)
Short windows work great here: L = 7–21 all pass with t > 2 and edges
> 900%. Wide separation between sharp dip-buyers (recovering) and
slow-grinders-down (falling).

### Mid drawdowns (-50% to -30%)
**This is where short L fails.** No L below 90 separates the two
distributions:
```
  7: edge -657%  t=-1.38   <-- sign FLIPPED
 14: edge  -41%  t=-0.19
 21: edge  -84%  t=-0.50   <-- spec winner fails here
 30: edge  +64%  t=+0.67
 45: edge  +55%  t=+0.52
 60: edge  +64%  t=+0.76
 90: edge +124%  t=+1.81   <-- borderline
120: edge +191%  t=+2.93   <-- first significant
180: edge +317%  t=+5.58
```

This is the regime that hurts: mid drawdowns include the noisy chop in
2014, 2018, 2022, and short-window classification is dominated by
local oscillations rather than regime direction. The trajectory signal
in this bucket needs L ≥ 120 to be statistically real.

### Deep drawdowns (-80% to -50%)
L = 21 onwards passes (t ≥ 3.0). Long windows show very large edges
(L = 120: +520%, L = 180: +541%). Deep DDs are bear-market territory
where the recovering/falling distinction maps to "post-capitulation
rally" vs "still grinding down" — well-separated regardless of L.

## 3. Robustness check B — threshold sensitivity

The optimal L is stable across thresholds 0.02–0.07. L = 21 is the
smallest L clearing the strict bar at every threshold:

| threshold | smallest qualifying L | t-stat |
|-----------|----------------------|--------|
| 0.02      | 21                   | +2.64  |
| 0.03      | 21                   | +2.28  |
| 0.05      | 21                   | +2.35  |
| 0.07      | 21                   | +2.08  |

Threshold sensitivity is **not** the binding constraint. Window length is.

## 4. Robustness check C — 3-month forward horizon

This is the most important check, because the live strategy rebalances
weekly and a 1Y forward return is far longer than any decision horizon.

```
  L | n_fall | n_rec | mean_3M_fall | mean_3M_rec |   edge | t-stat | p-value
----+--------+-------+--------------+-------------+--------+--------+--------
  7 |   380  |  293  |     +79.5%   |   +113.8%   |  +34%  | +1.51  | 0.130
 14 |   473  |  321  |     +90.6%   |    +75.2%   |  -15%  | -0.85  | 0.395
 21 |   496  |  336  |    +100.0%   |    +78.3%   |  -22%  | -1.18  | 0.238   <-- spec winner FAILS
 30 |   522  |  354  |    +100.7%   |    +70.3%   |  -30%  | -1.72  | 0.086
 45 |   552  |  401  |     +90.0%   |    +78.6%   |  -11%  | -0.64  | 0.519
 60 |   533  |  426  |     +74.1%   |    +92.6%   |  +19%  | +1.09  | 0.278
 90 |   492  |  481  |     +42.3%   |   +118.3%   |  +76%  | +4.27  | 0.0000  <-- first robust qualifier
120 |   508  |  483  |     +52.1%   |   +116.9%   |  +65%  | +3.48  | 0.0005
180 |   441  |  522  |     +55.1%   |    +89.6%   |  +34%  | +1.95  | 0.052
```

**At L = 21, the 3M-forward edge is negative.** I.e. on the timescale
that actually matters for a weekly-rebalanced bot, classifying as
"recovering" at L = 21 historically meant *lower* near-term returns.
This is a deal-breaker for using L = 21 in production.

The 3M edge only turns clearly positive and significant from **L = 90**.

## 5. Recommendation

### Headline

```python
# src/historical_context.py
DEFAULT_TRAJECTORY_LOOKBACK_DAYS = 90
```

### Why not L = 21 (strict spec winner)
- 3M-horizon edge is negative (and the bot rebalances weekly).
- Mid-DD regime separation is statistically null (t = −0.50).
- The t-stat in the main sweep is barely above the bar (2.28 vs cutoff 2.0).

### Why L = 90
- 1Y edge: +263.7% (t = +5.75, p < 1e-4, n_fall = 465, n_rec = 479)
- 3M edge: +76.0% (t = +4.27, p < 1e-4)
- Shallow regime: passes (t = +3.37)
- Deep regime: passes (t = +4.56)
- Mid regime: borderline (t = +1.81)
- Threshold-stable.

### When to consider L = 120 instead
If you want the trajectory split to be statistically valid in every
regime including mid-DDs (-50% to -30%), use 120. Cost: the lookback
covers a full quarter of price action, so the "Prior → Now" header
in the Telegram alert refers to a fairly stale starting point.

### Caveats
1. **Look-ahead is in the sampling, not the signal**: first-entry days
   are sampled non-overlappingly, but forward 1Y windows for adjacent
   entries do overlap. The t-test treats observations as IID; the true
   confidence interval is wider than the reported p-values. This is
   another reason to prefer larger-t winners (L = 90 / 120) over
   marginal ones (L = 21).
2. **2010–2025 has only ~2 full cycles.** Two bear bottoms (2015, 2019,
   2022 — three if you stretch) drive most of the deep-DD samples.
   The signal is real but the regime count is small.
3. **Recovering > falling is the BTC mean-reversion effect.** This
   sweep doesn't tell us whether the recovering bucket would have
   outperformed buy-and-hold on a leveraged basis; it only says
   recovering > falling. That comparison belongs in a separate
   backtest.

## 6. Next step

Change `DEFAULT_TRAJECTORY_LOOKBACK_DAYS` in `src/historical_context.py`
from `30` to `90` (or `120` if the regime caveat is a concern). That
single edit propagates to both
`get_historical_context_by_trajectory()` and the live signal call site
in `run_bot.py::_compute_prior_drawdown()`.
