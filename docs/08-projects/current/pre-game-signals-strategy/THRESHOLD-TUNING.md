# Threshold Tuning for Pre-Game Signals

**Created**: Session 71 (2026-02-01)
**Status**: PENDING - Need 30+ days of validation data
**Purpose**: Optimize pct_over thresholds to maximize signal effectiveness

---

## What is Threshold Tuning?

Threshold tuning is the process of finding the optimal cutoff values that separate "good" betting days from "bad" betting days.

**Current thresholds** (based on 23 days of data):

| pct_over Range | Signal | Hit Rate | Days |
|----------------|--------|----------|------|
| < 25% | RED | 53.8% | 7 |
| 25-40% | GREEN | 82.0% | 15 |
| > 40% | YELLOW | 88.9% | 1 |

**The question**: Are 25% and 40% the best cutoffs, or would 22%, 28%, or 35% work better?

---

## Why It Matters

### The Problem with Arbitrary Thresholds

The current 25% threshold was chosen because:
1. It's a round number
2. It roughly matches where performance dropped in our data
3. It was "good enough" for initial implementation

But it might not be **optimal**. Consider:

| Scenario | Threshold | Result |
|----------|-----------|--------|
| Threshold too low (20%) | Fewer RED warnings | Miss some bad days, lower overall accuracy |
| Threshold too high (30%) | More RED warnings | Catch more bad days, but also flag good days |
| Optimal threshold (??%) | Best balance | Maximum separation between good and bad |

### The Goal

Find the threshold that **maximizes the hit rate difference** between categories while maintaining reasonable sample sizes in each category.

---

## Methods for Threshold Tuning

### Method 1: Grid Search (Simple)

Test multiple thresholds and compare results:

```
Threshold: 20%  → RED HR: 52%, GREEN HR: 78%, Diff: 26%
Threshold: 22%  → RED HR: 53%, GREEN HR: 80%, Diff: 27%
Threshold: 25%  → RED HR: 54%, GREEN HR: 82%, Diff: 28%  ← Current
Threshold: 28%  → RED HR: 56%, GREEN HR: 84%, Diff: 28%
Threshold: 30%  → RED HR: 58%, GREEN HR: 85%, Diff: 27%
```

Pick the threshold with the highest difference.

**Pros**: Simple, interpretable
**Cons**: Doesn't account for sample size imbalance

### Method 2: ROC Curve Analysis

Treat signal detection as a binary classification problem:
- Positive class: "Bad day" (hit rate < 60%)
- Negative class: "Good day" (hit rate >= 60%)
- Predictor: pct_over value

Plot ROC curve and find the threshold that maximizes:
- **Youden's J statistic**: Sensitivity + Specificity - 1
- **F1 score**: Balance of precision and recall

**Pros**: Statistically rigorous, accounts for class imbalance
**Cons**: More complex, requires defining "bad day" cutoff

### Method 3: Profit Maximization

Model expected profit at different thresholds:

```
Expected Profit = (Days_Bet × Avg_HR × Payout) - (Days_Bet × (1-Avg_HR) × Stake)
```

At -110 odds:
- Betting 100 days at 55% HR → +4.5% ROI
- Betting 80 days at 65% HR → +24% ROI (skipping 20 RED days)
- Betting 60 days at 75% HR → +43% ROI (skipping 40 days)

Find threshold that maximizes total profit, not just hit rate.

**Pros**: Directly optimizes what we care about (money)
**Cons**: Requires consistent bet sizing assumptions

---

## Data Requirements

### Minimum Sample Sizes

| Category | Minimum Days | Minimum Picks | Why |
|----------|--------------|---------------|-----|
| RED | 10 | 30 | Statistical significance |
| GREEN | 15 | 50 | Stable hit rate estimate |
| YELLOW | 5 | 15 | Directional understanding |

**Current data** (Jan 9-31, 2026):
- Total: 23 days
- RED: 7 days, 26 picks
- GREEN: 15 days, 61 picks
- YELLOW: 1 day, 54 picks

**Verdict**: Need more RED and YELLOW days before tuning.

### Target Data Collection

| Milestone | Date | Days | Action |
|-----------|------|------|--------|
| Minimum viable | Feb 15 | 38 | Initial tuning possible |
| Recommended | Mar 1 | 52 | More reliable estimates |
| Optimal | Mar 15 | 66 | Full seasonal patterns |

---

## SQL Queries for Threshold Analysis

### Query 1: Daily Signal Summary with Outcomes

```sql
-- Get daily signals with actual hit rates
WITH daily_outcomes AS (
  SELECT
    p.game_date,
    COUNT(*) as total_picks,
    COUNTIF(ABS(p.predicted_points - p.current_points_line) >= 5) as high_edge_picks,
    ROUND(100.0 * COUNTIF(p.recommendation = 'OVER') / COUNT(*), 1) as pct_over,
    -- Calculate actual hit rate
    ROUND(100.0 * COUNTIF(
      (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
      (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
    ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5  -- High edge only
    AND p.current_points_line IS NOT NULL
    AND p.game_date >= DATE('2026-01-09')
    AND p.game_date < CURRENT_DATE()
  GROUP BY p.game_date
  HAVING COUNT(*) >= 3  -- Minimum picks per day
)
SELECT
  game_date,
  pct_over,
  high_edge_picks,
  hit_rate,
  CASE
    WHEN pct_over < 25 THEN 'RED'
    WHEN pct_over > 40 THEN 'YELLOW'
    ELSE 'GREEN'
  END as current_signal
FROM daily_outcomes
ORDER BY game_date;
```

### Query 2: Grid Search for Optimal Threshold

```sql
-- Test different thresholds
WITH daily_outcomes AS (
  SELECT
    p.game_date,
    ROUND(100.0 * COUNTIF(p.recommendation = 'OVER') / COUNT(*), 1) as pct_over,
    ROUND(100.0 * COUNTIF(
      (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
      (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
    ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5
    AND p.current_points_line IS NOT NULL
    AND p.game_date >= DATE('2026-01-09')
    AND p.game_date < CURRENT_DATE()
  GROUP BY p.game_date
  HAVING COUNT(*) >= 3
),
thresholds AS (
  SELECT threshold FROM UNNEST([18, 20, 22, 24, 25, 26, 28, 30, 32, 35]) as threshold
)
SELECT
  t.threshold,
  -- Below threshold (RED)
  COUNTIF(d.pct_over < t.threshold) as red_days,
  ROUND(AVG(CASE WHEN d.pct_over < t.threshold THEN d.hit_rate END), 1) as red_hr,
  -- At or above threshold (GREEN)
  COUNTIF(d.pct_over >= t.threshold) as green_days,
  ROUND(AVG(CASE WHEN d.pct_over >= t.threshold THEN d.hit_rate END), 1) as green_hr,
  -- Difference
  ROUND(
    AVG(CASE WHEN d.pct_over >= t.threshold THEN d.hit_rate END) -
    AVG(CASE WHEN d.pct_over < t.threshold THEN d.hit_rate END), 1
  ) as hr_difference
FROM thresholds t
CROSS JOIN daily_outcomes d
GROUP BY t.threshold
ORDER BY hr_difference DESC;
```

### Query 3: Statistical Significance Test

```sql
-- Two-proportion z-test for threshold comparison
WITH daily_outcomes AS (
  SELECT
    p.game_date,
    ROUND(100.0 * COUNTIF(p.recommendation = 'OVER') / COUNT(*), 1) as pct_over,
    COUNTIF(pgs.points != p.current_points_line) as total_bets,
    COUNTIF(
      (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
      (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
    ) as wins
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5
    AND p.current_points_line IS NOT NULL
    AND p.game_date >= DATE('2026-01-09')
    AND p.game_date < CURRENT_DATE()
  GROUP BY p.game_date
  HAVING COUNT(*) >= 3
),
aggregated AS (
  SELECT
    -- RED category (pct_over < 25)
    SUM(CASE WHEN pct_over < 25 THEN total_bets ELSE 0 END) as n1,
    SUM(CASE WHEN pct_over < 25 THEN wins ELSE 0 END) as x1,
    -- GREEN category (pct_over >= 25)
    SUM(CASE WHEN pct_over >= 25 THEN total_bets ELSE 0 END) as n2,
    SUM(CASE WHEN pct_over >= 25 THEN wins ELSE 0 END) as x2
  FROM daily_outcomes
)
SELECT
  n1 as red_bets,
  x1 as red_wins,
  ROUND(100.0 * x1 / n1, 1) as red_hr,
  n2 as green_bets,
  x2 as green_wins,
  ROUND(100.0 * x2 / n2, 1) as green_hr,
  -- Pooled proportion
  ROUND((x1 + x2) / (n1 + n2), 4) as pooled_p,
  -- Z-statistic (approximate)
  ROUND(
    (x1/n1 - x2/n2) /
    SQRT(((x1+x2)/(n1+n2)) * (1 - (x1+x2)/(n1+n2)) * (1/n1 + 1/n2)),
    2
  ) as z_stat
FROM aggregated;
```

---

## Implementation Plan

### Phase 1: Data Collection (Now - Feb 15)

**Goal**: Accumulate 38+ days of signal data

**Actions**:
1. Signals auto-calculate daily (already implemented)
2. Monitor daily outcomes via `/validate-daily`
3. Track in `daily_prediction_signals` table

**No code changes needed** - just wait for data.

### Phase 2: Initial Analysis (Feb 15)

**Goal**: Run grid search to identify candidate thresholds

**Actions**:
1. Run Query 2 (grid search)
2. Identify top 3 candidate thresholds
3. Run Query 3 for statistical significance
4. Document findings

### Phase 3: Threshold Update (Feb 20+)

**Goal**: Update production thresholds if better values found

**Actions**:
1. Update `signal_calculator.py` with new thresholds
2. Update signal explanation messages
3. Backfill signals with new thresholds (optional)
4. Monitor for 1 week before declaring success

---

## Decision Framework

### When to Change Thresholds

Change thresholds if ALL of these are true:

| Criteria | Requirement |
|----------|-------------|
| Sample size | >= 10 days in each category |
| Hit rate difference | >= 15 percentage points |
| Statistical significance | p-value < 0.05 |
| Improvement | New threshold is >= 3% better than current |

### When NOT to Change

Keep current thresholds if:
- Sample size is too small (< 10 days per category)
- Difference is not significant (p > 0.10)
- Improvement is marginal (< 3% better)
- High variance in daily outcomes

---

## Current Data Status

### As of Feb 1, 2026

**Important**: pct_over is calculated from ALL predictions, but hit rate is measured on HIGH-EDGE picks only (edge >= 5).

```
Total days: 23
RED days (< 25%): 8 days, 32 bets
GREEN days (>= 25%): 15 days, 109 bets

RED hit rate: 62.5%
GREEN hit rate: 84.4%

Difference: 21.9 percentage points
```

### Grid Search Results (Feb 1, 2026)

| Threshold | RED Days | RED HR | GREEN Days | GREEN HR | Diff |
|-----------|----------|--------|------------|----------|------|
| 20% | 2 | 44.4% | 21 | 81.8% | 37.4% |
| 22% | 4 | 50.0% | 19 | 82.7% | 32.7% |
| 24% | 6 | 58.3% | 17 | 83.8% | 25.4% |
| **25%** | **8** | **62.5%** | **15** | **84.4%** | **21.9%** |
| 26% | 9 | 64.7% | 14 | 84.1% | 19.4% |
| 28% | 14 | 66.1% | 9 | 88.2% | 22.2% |
| 30% | 15 | 66.7% | 8 | 88.1% | 21.4% |

**Current recommendation**: Keep 25% threshold
- Lower thresholds (20-22%) have higher differences but too few RED days
- 28% is interesting but GREEN sample becomes small (9 days)
- Need 10+ days per category before confident tuning

### Data Gaps

1. **Sample size**: 8 RED days is borderline - need 10+ for confidence
2. **Upper threshold**: Not enough data to tune the 40% YELLOW threshold
3. **Seasonal variation**: All data from Jan - may differ in Feb/Mar

---

## Monitoring Dashboard Query

Run this weekly to track readiness for threshold tuning:

```sql
-- Weekly threshold tuning readiness check
WITH daily_outcomes AS (
  SELECT
    p.game_date,
    ROUND(100.0 * COUNTIF(p.recommendation = 'OVER') / COUNT(*), 1) as pct_over,
    COUNTIF(pgs.points != p.current_points_line) as bets,
    COUNTIF(
      (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
      (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
    ) as wins
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5
    AND p.current_points_line IS NOT NULL
    AND p.game_date >= DATE('2026-01-09')
    AND p.game_date < CURRENT_DATE()
  GROUP BY p.game_date
  HAVING COUNT(*) >= 3
)
SELECT
  'Summary' as metric,
  COUNT(*) as total_days,
  COUNTIF(pct_over < 25) as red_days,
  COUNTIF(pct_over >= 25 AND pct_over <= 40) as green_days,
  COUNTIF(pct_over > 40) as yellow_days,
  SUM(bets) as total_bets,
  SUM(wins) as total_wins,
  ROUND(100.0 * SUM(wins) / SUM(bets), 1) as overall_hr,
  CASE
    WHEN COUNTIF(pct_over < 25) >= 10 AND COUNTIF(pct_over >= 25) >= 15
    THEN 'READY for tuning'
    ELSE CONCAT('WAIT - need ',
      GREATEST(0, 10 - COUNTIF(pct_over < 25)), ' more RED days, ',
      GREATEST(0, 15 - COUNTIF(pct_over >= 25)), ' more GREEN days')
  END as tuning_status
FROM daily_outcomes;
```

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-01 | Created document (Session 71) |

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
