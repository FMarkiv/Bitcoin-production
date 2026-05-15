# Trajectory Lookback Window — Research Prompt

The trajectory-aware historical context (`get_historical_context_by_trajectory`)
classifies historical first-entries into a drawdown bucket as falling /
recovering / flat based on the drawdown observed `lookback_days` earlier.

The default is **30 days**, picked by gut. The "right" answer depends on
what window gives the cleanest separation between falling vs recovering
forward returns. The prompt below is intended to be handed to a separate
research session (Claude, ChatGPT, a notebook, whatever) to find the best
window empirically.

---

## RESEARCH PROMPT (copy-paste into a new session)

I need you to determine the optimal `lookback_days` value for a trajectory
classifier used on Bitcoin drawdowns.

### Setup

I have daily BTC close prices (`data/BTC.csv`, columns: `date`, `close`).
For each day I compute:

- `ath_t = max(close[0..t])`
- `drawdown_t = (close_t - ath_t) / ath_t`  (e.g. -0.42 for -42%)

A "drawdown bucket" is a 5% slice of drawdown space, e.g. -45% to -40%.
A "first entry" is a day `t` where `drawdown_t` is inside the bucket but
`drawdown_{t-1}` is not. (Non-overlapping samples.)

For each first-entry day `t` and a candidate lookback `L`, classify the
trajectory by comparing `drawdown_t` to `drawdown_{t-L}`:

- `falling`     if `drawdown_t - drawdown_{t-L} < -0.03`
- `recovering`  if `drawdown_t - drawdown_{t-L} >  0.03`
- `flat`        otherwise

For each first-entry day I have a forward 1-year return `r_t = close_{t+365}/close_t - 1`.

### Task

Sweep `L ∈ {7, 14, 21, 30, 45, 60, 90, 120, 180}` days. For each `L`:

1. Pool first-entries across all drawdown buckets in [-80%, -10%] (i.e.
   exclude very shallow and very extreme buckets).
2. Classify each first-entry as falling / recovering / flat using lookback `L`.
3. Compute, for each trajectory, the **mean 1-year forward return** and
   **win rate** (% of forward returns > 0). Also report **sample size**.
4. Compute the **separation metric**: `mean_1Y[recovering] - mean_1Y[falling]`.
   This is the "trajectory edge" — bigger is better.
5. Also compute the **t-statistic** (Welch's t-test) between the two
   distributions' 1Y returns — this tells us if the separation is statistically
   significant given the (small) sample sizes.

### Output

Produce a table:

```
L   | n_fall | n_rec | n_flat | mean_1Y_fall | mean_1Y_rec | edge   | t-stat | p-value
----+--------+-------+--------+--------------+-------------+--------+--------+--------
  7 |   ...  |  ...  |  ...   |     ...      |    ...      |  ...   |  ...   |  ...
 14 |   ...  |  ...  |  ...   |     ...      |    ...      |  ...   |  ...   |  ...
 ...
180 |   ...  |  ...  |  ...   |     ...      |    ...      |  ...   |  ...   |  ...
```

### Decision rule

Pick the smallest `L` whose edge is meaningfully positive (>20%) AND whose
t-statistic is significant (|t| > 2.0) AND whose sample sizes (`n_fall` and
`n_rec`) are both >= 15. If no `L` clears all three bars, the trajectory
signal is too weak to deploy and we should report that explicitly.

### Robustness checks

- Repeat the sweep on bucket subsets: shallow DDs (-30% to -10%),
  mid DDs (-50% to -30%), deep DDs (-80% to -50%). The optimal `L`
  may differ by regime.
- Repeat with `threshold ∈ {0.02, 0.03, 0.05, 0.07}` to confirm the
  conclusion is not threshold-sensitive.
- Look at 3-month forward returns as well as 1-year, since the strategy
  rebalances weekly and a shorter horizon may be more decision-relevant.

### Deliverable

A short report stating:

1. Recommended `lookback_days` value.
2. Expected edge (mean 1Y separation) at that value.
3. Confidence (t-stat, p-value, sample size).
4. Any caveats about regime sensitivity or threshold sensitivity.

---

## How to apply the result

Once you have a recommended `L`, change one constant in
`src/historical_context.py`:

```python
DEFAULT_TRAJECTORY_LOOKBACK_DAYS = <L>
```

That value is consumed by both `get_historical_context_by_trajectory()`
and `_compute_prior_drawdown()` in `run_bot.py`, so the live bot and the
historical computation stay in sync automatically.
