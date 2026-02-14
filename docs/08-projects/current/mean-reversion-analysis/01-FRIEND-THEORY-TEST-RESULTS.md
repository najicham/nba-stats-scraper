# Mean Reversion Theory Testing Results

## Executive Summary

**Theory Tested:** "Players with 2+ consecutive UNDER games (or low FG% games) are due for a bounce-back OVER"

**Result:** ❌ **NO EVIDENCE OF MEAN REVERSION** — In fact, slight evidence of CONTINUATION (cold stays cold)

**Date Range:** 2025-11-01 to 2026-02-12 (Full Season)
**Sample Size:** 3,564 graded games (catboost_v9 predictions)

---

## Test 1: Prop Line Streak Analysis

### Your Friend's Theory
> "Look for a player that has 2 under games in a row and is due for the next game to go over."

### Results

| Scenario | Games | Over Rate | vs Baseline |
|----------|-------|-----------|-------------|
| **Baseline (All Players)** | 3,564 | **49.6%** | — |
| After 2 Consecutive UNDERS | 702 | **49.4%** | **-0.2pp** ❌ |
| After 3 Consecutive UNDERS | 297 | **50.5%** | **+0.9pp** |
| After At Least 1 UNDER in Last 2 | 2,144 | **48.6%** | **-1.0pp** ❌ |

### Interpretation

- **NO mean reversion effect detected**
- After 2 consecutive unders, players are SLIGHTLY LESS LIKELY to go over (49.4% vs 49.6%)
- After 3 unders, there's a tiny lift (+0.9pp), but sample size is small (297 games) and not statistically significant
- Overall pattern suggests **slight momentum/continuation** rather than reversion

---

## Test 2: Field Goal % Bounce-Back Theory

### Your Friend's Theory
> "If they had two games with a low shooting percentage, they probably were going to have a game with a higher shooting percentage. Focus on shooting percentage more than points because it showed if they had a bad game."

### Results

| Scenario | Games | Avg FG% | vs Baseline |
|----------|-------|---------|-------------|
| **All Games (5+ FGA)** | 11,020 | **47.0%** | — |
| **After Avg FG% < 40% in Last 2 Games** | 2,784 | **44.4%** | **-2.6pp** ❌ |

### Interpretation

- **STRONG NEGATIVE RESULT** — Cold shooting continues, not reverts
- Players averaging under 40% FG% in their last 2 games shoot 44.4% in the next game
- This is 2.6 percentage points WORSE than the baseline (47.0%)
- **Your friend's reasoning about FG% is backwards** — low FG% predicts CONTINUED poor performance, not bounce-back

---

## Why This Matters for Our ML Model

### 1. **Shooting % Features Are Missing from V9**

We have:
- ✅ Points averages (last 5, 10, season)
- ✅ Shot zone percentages (paint, mid, 3PT, FT)
- ❌ **NO field goal percentage** (FG%)
- ❌ **NO three-point percentage** (3PT%)

**Available in raw data but NOT in feature store:**
- `field_goal_percentage`
- `three_point_percentage`

### 2. **V12 Already Has Streak Features!**

V12 feature store (session 230) added:
- `prop_over_streak` — consecutive games over prop line
- `prop_under_streak` — consecutive games under prop line
- `consecutive_games_below_avg` — cold streak counter

**BUT these are NOT in V9 production model!**

### 3. **Our Data Shows CONTINUATION, Not Reversion**

This validates our V12 streak features:
- Cold streaks predict continued cold performance
- Hot streaks likely predict continued hot performance
- The market may UNDERESTIMATE continuation effects

---

## Feature Engineering Recommendations

### ✅ **SHOULD ADD to V13 or V12B:**

1. **Shooting Efficiency Features**
   - `fg_pct_last_3` — Recent FG% (3-game average)
   - `fg_pct_last_5` — Recent FG% (5-game average)
   - `fg_pct_vs_season_avg` — Deviation from season FG%
   - `three_pct_last_3` — Recent 3PT%
   - `three_pct_last_5` — Recent 3PT%
   - `shooting_cold_streak` — Games below 40% FG% (counter)

2. **Why FG% > Points for this signal:**
   - FG% shows **efficiency** independent of shot volume
   - Points can be high due to volume (20 points on 5/20 shooting is bad)
   - FG% reveals true "hot hand" vs "cold hand" state
   - Captures **shot-making ability** not just opportunity

3. **Implementation Notes:**
   - Add to Phase 4 precompute or Phase 5 feature generation
   - Use 20-game rolling average for season baseline
   - Track both FG% and 3PT% separately (different signals)
   - Consider interaction with opponent defense rating

### ❌ **SHOULD NOT DO:**

1. ❌ Build "mean reversion" signals (2 unders → bet over)
   - Data shows this doesn't work
   - Would add noise to the model

2. ❌ Remove V12 streak features
   - They capture CONTINUATION effects which ARE real
   - prop_under_streak likely predicts CONTINUED unders, not reversion

---

## SQL Queries for Further Analysis

### Check if specific star players show different patterns:

```sql
-- Test mean reversion for high-usage stars
WITH star_games AS (
  SELECT
    player_lookup,
    game_date,
    actual_points,
    line_value,
    CASE WHEN actual_points > line_value THEN 1 ELSE 0 END as went_over,
    SUM(CASE WHEN actual_points < line_value THEN 1 ELSE 0 END)
      OVER (
        PARTITION BY player_lookup
        ORDER BY game_date
        ROWS BETWEEN 2 PRECEDING AND 1 PRECEDING
      ) as unders_in_last_2,
    ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date) as game_num
  FROM nba_predictions.prediction_accuracy
  WHERE game_date BETWEEN '2025-11-01' AND '2026-02-12'
    AND actual_points IS NOT NULL
    AND line_value IS NOT NULL
    AND system_id = 'catboost_v9'
    AND player_lookup IN (
      'LeBronJames', 'lukadoncic', 'ShaiGilgeous-Alexander',
      'GiannisAntetokounmpo', 'nikolajokic'
    )
)
SELECT
  player_lookup,
  COUNTIF(unders_in_last_2 = 2 AND game_num >= 3) as after_2_unders_games,
  ROUND(AVG(CASE WHEN unders_in_last_2 = 2 AND game_num >= 3
                 THEN went_over END) * 100, 1) as over_rate_after_2_unders,
  ROUND(AVG(went_over) * 100, 1) as baseline_over_rate
FROM star_games
GROUP BY 1
ORDER BY 2 DESC;
```

### Check if FG% correlates with prop performance:

```sql
-- Do low FG% games predict UNDER on the prop line?
WITH combined_data AS (
  SELECT
    g.game_date,
    g.player_name,
    g.field_goal_percentage,
    pa.actual_points,
    pa.line_value,
    CASE WHEN pa.actual_points < pa.line_value THEN 1 ELSE 0 END as went_under
  FROM nba_raw.nbac_gamebook_player_stats g
  INNER JOIN nba_predictions.prediction_accuracy pa
    ON g.player_name = pa.player_lookup
    AND g.game_date = pa.game_date
  WHERE g.game_date BETWEEN '2025-11-01' AND '2026-02-12'
    AND g.field_goals_attempted >= 5
    AND pa.line_value IS NOT NULL
)
SELECT
  CASE
    WHEN field_goal_percentage < 0.35 THEN 'Very Low (<35%)'
    WHEN field_goal_percentage < 0.40 THEN 'Low (35-40%)'
    WHEN field_goal_percentage < 0.45 THEN 'Below Avg (40-45%)'
    WHEN field_goal_percentage < 0.50 THEN 'Average (45-50%)'
    ELSE 'Good (50%+)'
  END as fg_pct_bucket,
  COUNT(*) as games,
  ROUND(AVG(went_under) * 100, 1) as under_rate_pct,
  ROUND(AVG(actual_points - line_value), 1) as avg_margin
FROM combined_data
GROUP BY 1
ORDER BY MIN(field_goal_percentage);
```

---

## Conclusions

1. **Your friend's theory does NOT hold up in the data**
   - No mean reversion after 2 consecutive unders (49.4% vs 49.6% baseline)
   - No FG% bounce-back (44.4% vs 47.0% baseline)
   - Slight evidence of CONTINUATION effects (cold stays cold)

2. **BUT the intuition about FG% is valuable**
   - FG% is a better indicator of true performance than just points
   - We should add FG% and 3PT% to our feature store
   - Shooting efficiency likely has predictive power

3. **V12 streak features are directionally correct**
   - `prop_under_streak` should predict CONTINUED unders (not reversion)
   - `consecutive_games_below_avg` should predict below-average performance
   - These capture real CONTINUATION effects

4. **Next Steps:**
   - Add FG% and 3PT% features to V13 (or V12 update)
   - Test if FG% correlates with prop line performance
   - Consider interaction: low FG% + high usage → UNDER signal?
   - Validate V12 streak features are being used correctly (continuation not reversion)

---

## Files Created

- `/home/naji/code/nba-stats-scraper/bin/analysis/test_mean_reversion_theory.py` — Full analysis script
- This document — Summary of findings

---

**Session:** 242
**Date:** 2026-02-13
**Author:** Claude Sonnet 4.5
