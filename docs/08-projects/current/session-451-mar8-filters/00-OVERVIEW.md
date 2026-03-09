# Session 451 — Mar 8 Autopsy Filters

**Date:** 2026-03-09
**Algorithm:** `v451_session451_filters`
**Status:** DEPLOYED (pending push)

## What Was Implemented

5 changes from the Mar 8 (3-11) autopsy ranked action items:

### 1. Line Anomaly Extreme Drop (ACTIVE FILTER)
- **File:** `aggregator.py`
- **Logic:** Blocks OVER when line drops >= 40% OR >= 6pts from previous game
- **Trigger:** `prop_line_delta` derived (prev_line - current) / prev_line
- **Mar 8 counterfactual:** Would have blocked Derrick White ULTRA (line 16.5 -> 8.5, 48.5% drop)
- **Expected fire rate:** Very rare (1-2 per month). Safety net, not volume filter.

### 2. Player UNDER Suppression (OBSERVATION)
- **Files:** `player_blacklist.py` (new function), `per_model_pipeline.py`, `aggregator.py`
- **Logic:** Players with UNDER HR < 35% at N >= 20 across enabled models
- **Mar 8 counterfactual:** Nobody flagged yet — enabled models too new (Mar 2-4 start)
- **Expected activation:** ~late March when fleet has 4-6 weeks of history
- **Key candidates (all-model data):** Herro 22.5% (N=40), Jalen Duren 13.0% (N=23), GG Jackson 19.0% (N=21), Quickley 19.4% (N=31)
- **Promotion criteria:** CF HR >= 55% at N >= 20 for 7 consecutive days

### 3. UNDER Low Real SC (OBSERVATION)
- **File:** `aggregator.py`
- **Logic:** Tags UNDER picks with real_sc < 2 at edge < 7
- **Mar 8 counterfactual:** Would flag KAT (rsc=1), Thompson (rsc=1), Zion (rsc=1, WIN)
- **Risk if promoted:** Also blocks the only UNDER win (Zion rsc=1)
- **Promotion criteria:** Consistent < 50% HR at N >= 30

### 4. FT Variance UNDER (OBSERVATION)
- **Files:** `supplemental_data.py` (new CTE), `aggregator.py`
- **Logic:** Tags UNDER on high-FTA (>= 5) + high-CV (>= 0.5) players
- **Mar 8 counterfactual:** Flags Booker (fta=5.8, cv=0.634) — ULTRA UNDER loss
- **Discovery:** 47.8% UNDER HR vs 70.6% stable (22.8pp gap)
- **Promotion criteria:** CF HR >= 55% at N >= 20 for 7 consecutive days

### 5. Mean Reversion Under Guard
- **Files:** `mean_reversion_under.py`, `aggregator.py` SHADOW_SIGNALS
- **Two changes:**
  - Moved to SHADOW_SIGNALS → stops inflating real_sc
  - Added MAX_OVER_RATE = 0.60 guard → don't fire on structural high-scorers
- **Mar 8 counterfactual:** Thompson (rsc 1→0 → blocked by signal_density), Wemby/Herro (rsc reduced)
- **Signal HR:** 53.0% (below 54.3% baseline). Cross-season decay: 75.7% → 65.2% → 53.0%.

## Mar 8 Counterfactual Summary

| Pick | Outcome | Line Anomaly | UNDER Supp | Low RSC | FT Var | MR Guard |
|------|---------|-------------|------------|---------|--------|----------|
| D. White OVER | LOSS | **BLOCKED** | - | - | - | - |
| A. Thompson UNDER | LOSS | - | - | flagged | - | **rsc→0→BLOCKED** |
| KAT UNDER | LOSS | - | - | flagged | - | - |
| Castle UNDER | LOSS | - | - | - | - | - |
| Booker UNDER | LOSS | - | - | - | flagged | - |
| Herro UNDER | LOSS | - | - | - | - | rsc reduced |
| Wemby UNDER | LOSS | - | - | - | - | rsc reduced |
| Avdija OVER | LOSS | - | - | - | - | - |
| Yabusele OVER | LOSS | - | - | - | - | - |
| Okoro OVER | LOSS | - | - | - | - | - |
| Achiuwa OVER | LOSS | - | - | - | - | - |
| Zion UNDER | WIN | - | - | flagged | - | - |
| Tatum OVER | WIN | - | - | - | - | - |
| Riley OVER | WIN | - | - | - | - | - |

**Net: 3-11 → 3-9 (25.0%)** with confirmed blocks. Saves 2 units.

## Observation Promotion Schedule

Check these dates for promotion decisions:

| Observation | Check Date | Criteria | Query |
|-------------|-----------|----------|-------|
| `player_under_suppression_obs` | **2026-03-24** (Mon) | CF HR >= 55%, N >= 20 | `SELECT * FROM filter_counterfactual_daily WHERE filter_name = 'player_under_suppression_obs' ORDER BY game_date DESC LIMIT 7` |
| `under_low_rsc_obs` | **2026-03-24** (Mon) | CF HR >= 55%, N >= 20 | Same pattern with `under_low_rsc_obs` |
| `ft_variance_under_obs` | **2026-03-24** (Mon) | CF HR >= 55%, N >= 20 | Same pattern with `ft_variance_under_obs` |

Also check: existing observations from Sessions 439-442 that have been accumulating since Mar 3.

## Validation Queries

```sql
-- Check if line_anomaly_extreme_drop is firing
SELECT game_date, COUNT(*) AS blocked
FROM `nba-props-platform.nba_predictions.best_bets_filtered_picks`
WHERE filter_reason = 'line_anomaly_extreme_drop'
GROUP BY game_date ORDER BY game_date DESC;

-- Check player UNDER suppression list
-- (run compute_player_under_suppression manually or check logs)

-- Check FT variance observation fires
SELECT game_date, COUNT(*) AS tagged
FROM `nba-props-platform.nba_predictions.best_bets_filtered_picks`
WHERE filter_reason = 'ft_variance_under_obs'
GROUP BY game_date ORDER BY game_date DESC;

-- Check mean_reversion_under no longer in real_sc
-- Look at pick_signal_tags for mean_reversion_under — should still appear
-- but real_signal_count should be lower
SELECT game_date, player_lookup, real_signal_count, signal_tags
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date >= '2026-03-10'
  AND 'mean_reversion_under' IN UNNEST(signal_tags)
ORDER BY game_date DESC;
```

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Algorithm v451, 4 new filter counters, line anomaly active filter, 3 observations, player_under_suppression param |
| `ml/signals/mean_reversion_under.py` | MAX_OVER_RATE = 0.60 guard |
| `ml/signals/player_blacklist.py` | `compute_player_under_suppression()` function |
| `ml/signals/supplemental_data.py` | `fta_variance` CTE + SELECT columns + pred dict mapping |
| `ml/signals/per_model_pipeline.py` | SharedContext.player_under_suppression field + build_shared_context wiring |
| `ml/signals/pipeline_merger.py` | Algorithm version bump |
| `tests/unit/signals/test_aggregator.py` | 14 new tests (125 total) |
| `CLAUDE.md` | Algorithm version + signal count update |
