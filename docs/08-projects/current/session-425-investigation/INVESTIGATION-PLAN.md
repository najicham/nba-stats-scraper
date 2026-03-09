# Session 425+ Investigation Plan: UNDER Signal Pipeline + Cross-Season Signal Analysis

**Created:** 2026-03-06 (Session 425)
**Status:** Ready for investigation
**Priority:** HIGH — UNDER is weakest link (59.6% vs OVER 71.3%)

## System Context (as of Mar 6)

- **BB HR:** 62.8% 7d (54-32), 64.2% 14d (106-59)
- **OVER 14d:** 71.3% (67-27) — excellent
- **UNDER 14d:** 59.6% (34-23) — weak link, signal vacuum
- **Market compression:** GREEN (0.62-0.65 ratio)
- **Algorithm:** v423_blowout_obs
- **Observation columns:** Fixed in code, deployed 23:19 UTC Mar 6. First production test will be Mar 7 export (~11 AM UTC). Verify after that run.

---

## Investigation 1: Shadow UNDER Signals Not Firing in BB (HIGH PRIORITY)

### Problem

4 shadow UNDER signals deployed in Sessions 422c/423 show **ZERO fires** in `signal_best_bets_picks` across all dates since Feb 25:

| Signal | Model-level HR | Model-level N | BB fires |
|--------|----------------|---------------|----------|
| `volatile_starter_under` | 65.5% | 637 | 0 |
| `downtrend_under` | 63.9% | 1,654 | 0 |
| `star_favorite_under` | ~73% | 88 | 0 |
| `starter_away_overtrend_under` | 68.1% | 213 | 0 |

These signals ARE:
- Registered in `ml/signals/registry.py` (lines 287-297)
- In `UNDER_SIGNAL_WEIGHTS` in `ml/signals/aggregator.py` (lines 78-82) at weight 1.5
- In `ACTIVE_SIGNALS` in `ml/signals/signal_health.py` (lines 111-114)
- BUT NOT appearing in `signal_health_daily` BQ table (confirmed gap)

### What to Investigate

**Step 1: Are the signals evaluating at all?**

The signals are registered via `registry.register()`. But are they being called during the export pipeline? Check:

```python
# In the aggregator's aggregate() method, signals are evaluated via:
signal_results = {}  # This comes from the caller (exporter)
# The exporter calls: signal_results = evaluate_signals(predictions)
```

Find where `evaluate_signals` or equivalent is called in the export pipeline. Check if these 4 signals' `evaluate()` methods are actually being invoked.

**Step 2: If evaluating, do they qualify?**

Each signal has specific conditions:

- **`volatile_starter_under`** (`ml/signals/volatile_starter_under.py`): UNDER + line 18-25 + std > 8 + edge >= 5. **LIKELY ISSUE: edge >= 5 threshold when over_edge_floor dropped to 3.0 means fewer high-edge UNDER picks exist.**

- **`downtrend_under`** (`ml/signals/downtrend_under.py`): UNDER + trend_slope <= -1.0 + pts_avg_last3 < line - 1.0. Check if `trend_slope` and `pts_avg_last3` are populated on pred dict.

- **`star_favorite_under`** (`ml/signals/star_favorite_under.py`): UNDER + line >= 25 + is_home + favorite. Check if `is_home` and favorite status fields are available.

- **`starter_away_overtrend_under`** (`ml/signals/starter_away_overtrend_under.py`): UNDER + NOT is_home + line 18-25 + `over_rate_last_10` > 0.50. The `over_rate_last_10` comes from feature 55. Check if this field is populated on pred dict.

- **`mean_reversion_under`** (`ml/signals/mean_reversion_under.py`): UNDER + line >= 12 + trend_slope >= 1.5 + pts_avg_last3 - line >= 1.5. Relaxed from 2.0 in Session 422.

**Step 3: Signal evaluation timing**

Signals are evaluated BEFORE the edge floor filter. But they only appear in `signal_tags` if the pick survives all filters. Check: are these signals qualifying at model level but then the PICKS they're on get filtered out before reaching BB?

Useful diagnostic query:
```sql
-- Check signal fire rates at MODEL level (before BB filtering)
-- Need to look at the signal evaluation results, not just BB picks
-- Check Cloud Function logs for signal evaluation output
```

**Step 4: Check signal_health_daily pipeline**

The commit `633b8a06` added these to `ACTIVE_SIGNALS` in `signal_health.py` but is NOT deployed yet (phase6-export deployed at d6ecdd5, this commit is after). So signal_health_daily won't track them until this commit is deployed.

### Key Files

| File | Purpose |
|------|---------|
| `ml/signals/registry.py:284-297` | Signal registration |
| `ml/signals/aggregator.py:71-83` | UNDER_SIGNAL_WEIGHTS |
| `ml/signals/aggregator.py:335-430` | Edge floor + rescue logic |
| `ml/signals/aggregator.py:460-897` | Main scoring loop (signal_tags built here) |
| `ml/signals/signal_health.py:111-114` | ACTIVE_SIGNALS list |
| `ml/signals/volatile_starter_under.py` | Signal implementation |
| `ml/signals/downtrend_under.py` | Signal implementation |
| `ml/signals/star_favorite_under.py` | Signal implementation |
| `ml/signals/starter_away_overtrend_under.py` | Signal implementation |
| `ml/signals/mean_reversion_under.py` | Signal implementation |
| `data_processors/publishing/signal_best_bets_exporter.py:300-321` | Where signals are evaluated and aggregated |

### Hypothesis

The most likely cause is that these signals ARE evaluating and qualifying at model level, but the UNDER picks they qualify on don't survive to BB because:
1. UNDER picks need `real_sc >= 1` (at minimum) to pass the SC gate
2. These shadow signals ARE in UNDER_SIGNAL_WEIGHTS so they contribute to real_sc
3. BUT the picks may fail other filters (edge floor, blacklist, etc.) before signal evaluation

Or alternatively, the signal evaluation input data (`prediction` dict) is missing required fields like `is_home`, `over_rate_last_10`, `std`, etc.

**Quick validation approach:** Add temporary logging to one signal's `evaluate()` method to see how many predictions are checked and why they fail each condition.

---

## Investigation 2: mean_reversion_under Still Dead (MEDIUM PRIORITY)

### Problem

Despite relaxing thresholds from 2.0 → 1.5 (both trend_slope and above_line), mean_reversion_under has ZERO fires in BB picks.

### Current Thresholds (ml/signals/mean_reversion_under.py)

```python
MIN_SLOPE = 1.5       # trend_slope >= 1.5
MIN_ABOVE_LINE = 1.5  # pts_avg_last3 - line >= 1.5
MIN_LINE = 12.0       # line >= 12
```

### Diagnostic Queries

```sql
-- How many predictions would qualify for mean_reversion at model level?
SELECT game_date, COUNT(*) as n,
  COUNTIF(f.feature_44_value >= 1.5) as slope_ok,
  COUNTIF(f.feature_43_value - pa.line_value >= 1.5) as above_line_ok,
  COUNTIF(pa.recommendation = 'UNDER') as is_under,
  COUNTIF(
    pa.recommendation = 'UNDER'
    AND f.feature_44_value >= 1.5
    AND f.feature_43_value - pa.line_value >= 1.5
    AND pa.line_value >= 12
  ) as full_qualify
FROM nba_predictions.prediction_accuracy pa
JOIN nba_predictions.ml_feature_store_v2 f
  ON pa.player_lookup = f.player_lookup AND pa.game_date = f.game_date
WHERE pa.game_date >= '2026-03-01'
  AND pa.has_prop_line = TRUE
GROUP BY 1
ORDER BY 1 DESC
```

This will tell us if ANY predictions even meet the criteria at model level.

---

## Investigation 3: predicted_pace_over Promotion (QUICK WIN)

### Current Status

- **signal_health_daily:** 63.6% HR, N=22 (model level)
- **BB performance:** 78.6% HR (22-6), N=28
- **Promotion threshold:** HR >= 60% AND N >= 30

At N=28 BB fires, it's 2 picks away from N=30. With 8 OVER picks/day recently, it could hit 30 within 1-2 days.

### Action

If N reaches 30 and HR stays >= 60%, promote from shadow to active production signal. This means:
1. No code change needed for signal evaluation (already evaluating)
2. Could add to rescue_tags if BB HR stays above 65%
3. Monitor for 1-2 more days then promote

---

## Investigation 4: Cross-Season Signal Analysis (EXPERIMENT)

### Idea

Signals are currently evaluated only on current-season data. But we have 4+ seasons of feature store data (2021-2026, ~136K records). If signals hold up across seasons, we can:
1. Get much larger sample sizes for validation
2. Have higher confidence in signal reliability
3. Potentially discover signals that are structural (not seasonal noise)

### Data Availability

| Year | prediction_accuracy | ml_feature_store_v2 |
|------|--------------------|--------------------|
| 2021 | 9,924 | 12,569 |
| 2022 | 27,966 | 26,209 |
| 2023 | 26,645 | 24,265 |
| 2024 | 32,440 | 25,929 |
| 2025 | 35,654 | 32,002 |
| 2026 | 23,049 | 15,458 |

### Experiment Design

**Phase A: Validate existing signals across seasons**

For each active/shadow signal, compute HR per season using feature store + prediction_accuracy:

```sql
-- Template: Cross-season signal validation
-- Example: home_under (UNDER + is_home)
WITH predictions AS (
  SELECT pa.player_lookup, pa.game_date, pa.recommendation,
    pa.prediction_correct, pa.line_value,
    f.feature_44_value as trend_slope,
    f.feature_43_value as pts_avg_last3,
    -- Add other feature columns as needed for signal evaluation
    EXTRACT(YEAR FROM pa.game_date) as season_year
  FROM nba_predictions.prediction_accuracy pa
  JOIN nba_predictions.ml_feature_store_v2 f
    ON pa.player_lookup = f.player_lookup AND pa.game_date = f.game_date
  WHERE pa.has_prop_line = TRUE
    AND pa.recommendation IN ('OVER', 'UNDER')
    AND pa.prediction_correct IS NOT NULL
)
SELECT season_year,
  -- Apply signal conditions here
  COUNTIF(signal_qualifies AND prediction_correct) as wins,
  COUNTIF(signal_qualifies AND NOT prediction_correct) as losses,
  ROUND(SAFE_DIVIDE(
    COUNTIF(signal_qualifies AND prediction_correct),
    COUNTIF(signal_qualifies AND prediction_correct IS NOT NULL)
  ) * 100, 1) as hr_pct
FROM predictions
GROUP BY 1
ORDER BY 1
```

**Signals to test cross-season:**
1. `home_under` — is_home + UNDER. Feature: need `is_home` in feature store or join with schedule.
2. `mean_reversion_under` — trend_slope (f44) >= 1.5 AND pts_avg_last3 (f43) - line >= 1.5
3. `volatile_starter_under` — line 18-25, scoring std > 8. Need scoring_std feature.
4. `downtrend_under` — trend_slope (f44) <= -1.0 AND pts_avg_last3 (f43) < line - 1.0
5. `b2b_boost_over` — back-to-back games (rest_days <= 1) AND OVER. Need rest_days.
6. `scoring_cold_streak_over` — Check if bounce-back OVER holds across seasons.
7. `predicted_pace_over` — Uses pace features. Check if pace signal is structural.

**Phase B: Discover new cross-season signals**

Scan feature store features for consistent cross-season UNDER patterns:

```sql
-- Feature scan: which features predict UNDER across all seasons?
SELECT
  EXTRACT(YEAR FROM pa.game_date) as yr,
  -- Test each feature with a threshold
  CASE WHEN f.feature_N_value > X THEN 'high' ELSE 'low' END as bucket,
  pa.recommendation,
  COUNT(*) as n,
  COUNTIF(pa.prediction_correct) as wins,
  ROUND(SAFE_DIVIDE(COUNTIF(pa.prediction_correct), COUNT(*)) * 100, 1) as hr
FROM ...
```

Features most likely to yield structural UNDER signals:
- **f44 (trend_slope):** Positive slope + UNDER = mean reversion (already known)
- **f55 (over_rate_last_10):** High over rate + UNDER = streak regression
- **f43 (pts_avg_last3):** Hot 3-game stretch + UNDER = regression
- **f40 (minutes load):** High minutes + UNDER = fatigue?
- **f13 (defense vs position):** Good defense + UNDER
- **f7, f14, f22 (pace features):** Low pace + UNDER

### Success Criteria

- Signal holds at >= 58% HR across ALL seasons (not just current)
- Minimum N >= 100 per season
- Monotonic or stable trend (not just one hot season)

### Key Consideration

Signals may work differently than model training across seasons because:
- Signals are **binary contextual evaluators** (qualifies/doesn't), not feature weights
- They capture **structural market inefficiencies** (e.g., "market overweights hot streaks") that may persist
- Models need precise point predictions, but signals just need directional bias
- Cross-season signal validation is fundamentally different from cross-season model training

---

## Investigation 5: Rescue Mechanism Review (LOW PRIORITY)

### Finding

Rescue is **structurally dead** since v422. `over_edge_floor` was lowered to 3.0, which equals `MIN_EDGE`. No pick can be below the edge floor, so rescue never triggers.

**Before v422:** rescue carried 87% of OVER picks (edge 3-5 range)
**After v422:** 0% rescue — all edge 3+ picks pass floor naturally

### Options

1. **Remove rescue code** — Clean up dead code path. Simplest.
2. **Repurpose rescue** — Use it for something else (e.g., rescue picks below SC gate instead of edge floor).
3. **Leave as-is** — Dead code is harmless, may be useful if we raise edge floor later.

Recommendation: Leave as-is for now. If we ever raise `over_edge_floor` above 3.0 again, rescue will re-activate.

---

## Quick Reference: Key Queries

### BB HR (rolling)
```sql
WITH bb AS (
  SELECT DISTINCT player_lookup, game_date
  FROM nba_predictions.signal_best_bets_picks
  WHERE game_date >= CURRENT_DATE() - 14
)
SELECT
  COUNTIF(pa.prediction_correct) as wins,
  COUNTIF(pa.prediction_correct = FALSE) as losses,
  ROUND(SAFE_DIVIDE(COUNTIF(pa.prediction_correct),
    COUNTIF(pa.prediction_correct IS NOT NULL)) * 100, 1) as hr
FROM bb
JOIN nba_predictions.prediction_accuracy pa
  ON bb.player_lookup = pa.player_lookup AND bb.game_date = pa.game_date
WHERE pa.has_prop_line = TRUE
  AND pa.recommendation IN ('OVER', 'UNDER')
  AND pa.prediction_correct IS NOT NULL
```

### Signal fire rates in BB
```sql
SELECT game_date,
  COUNTIF('volatile_starter_under' IN UNNEST(signal_tags)) as volatile_starter,
  COUNTIF('downtrend_under' IN UNNEST(signal_tags)) as downtrend,
  COUNTIF('star_favorite_under' IN UNNEST(signal_tags)) as star_fav,
  COUNTIF('starter_away_overtrend_under' IN UNNEST(signal_tags)) as starter_away_ot,
  COUNTIF('mean_reversion_under' IN UNNEST(signal_tags)) as mean_reversion,
  COUNT(*) as total_picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-01'
GROUP BY 1 ORDER BY 1 DESC
```

### Observation columns verification (run after Mar 7 export)
```sql
SELECT game_date, COUNT(*) as total_picks,
  COUNTIF(player_tier IS NOT NULL) as has_tier,
  COUNTIF(trend_slope IS NOT NULL) as has_trend_slope,
  COUNTIF(compression_ratio IS NOT NULL) as has_compression
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-07'
GROUP BY 1 ORDER BY 1 DESC
```

---

## Priority Order

1. **Shadow UNDER signal debugging** — Why aren't they firing? Likely wiring or data issue. Highest impact.
2. **Cross-season signal analysis** — Experiment to find structural signals with large N. Could unlock new UNDER signals.
3. **predicted_pace_over promotion** — Almost at threshold, monitor and promote when ready.
4. **mean_reversion_under deep dive** — Part of #1, trace why zero candidates qualify.
5. **Observation column verification** — Just check after Mar 7 export.

## Undeployed Commit

`633b8a06 fix: add 11 missing signals to signal_health_daily tracking` — needs to be deployed. It adds the 4 shadow UNDER signals to signal_health_daily tracking. Currently NOT deployed (phase6-export is at d6ecdd5). This commit auto-deploys on next push to main, or can be manually deployed.
