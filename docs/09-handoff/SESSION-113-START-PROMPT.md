# Session 113: Review Scenario Filtering System + Answer Regeneration Question

## Context

Session 112 implemented a comprehensive **scenario filtering system** for optimal betting. This system classifies predictions into scenarios (optimal_over, optimal_under, etc.) at generation time.

**Your first task**: Review the implementation and answer the question below.

## Important Question to Answer

> "Sometimes predictions are changed or added to the DB. Will that affect our subsets? Will we regenerate them when predictions change, or create a new subset group? How will we handle that scenario?"

This question is about **prediction regeneration** - when Vegas lines change, predictions get regenerated. The concern is:
1. Does the `scenario_category` get recalculated when a prediction is regenerated?
2. If not, could we have stale scenario classifications?
3. Should scenario classification be stored at all, or computed at query time?

## Documents to Study (In Order)

### 1. Session 112 Handoff (What Was Done)
```
docs/09-handoff/2026-02-03-SESSION-112-HANDOFF.md
```

### 2. Scenario Filtering System Documentation
```
docs/08-projects/current/scenario-filtering-system/README.md
docs/08-projects/current/scenario-filtering-system/MONITORING-GUIDE.md
```

### 3. Key Code Changes
```
predictions/worker/worker.py           # Lines 395-480: _classify_scenario() function
predictions/coordinator/signal_calculator.py  # Scenario counts in daily signals
schemas/bigquery/predictions/04b_scenario_subset_extensions.sql  # Schema changes
```

### 4. Session 111 Original Findings
```
docs/09-handoff/2026-02-03-SESSION-111-HANDOFF.md
docs/08-projects/current/regression-to-mean-fix/SESSION-111-OPTIMAL-SCENARIOS.md
```

## What Session 112 Implemented

### Schema Changes

**player_prop_predictions** - New columns:
- `scenario_category` STRING - Classification: optimal_over, optimal_under, etc.
- `scenario_flags` STRING - JSON with edge, blacklist, opponent risk details

**daily_prediction_signals** - New columns:
- `optimal_over_count`, `optimal_under_count`, `ultra_high_edge_count`, `anti_pattern_count`

**dynamic_subset_definitions** - New columns:
- `recommendation_filter`, `line_min`, `line_max`
- `exclude_players`, `exclude_opponents` (JSON arrays)
- `scenario_category`, `expected_hit_rate`, `expected_roi`
- `sample_size_source`, `validation_period`, `last_validated_at`

**New tables**:
- `player_betting_risk` - 6 blacklisted players for UNDER bets
- `opponent_betting_risk` - 5 risky opponents for UNDER bets

### Code Changes

**Worker** (`predictions/worker/worker.py`):
- Added `_classify_scenario()` function (lines ~395-480)
- Added `UNDER_BLACKLIST_PLAYERS` and `UNDER_RISK_OPPONENTS` constants
- Scenario classification happens in `format_prediction_for_bigquery()`

**Signal Calculator** (`predictions/coordinator/signal_calculator.py`):
- Added scenario counts to daily signal calculation
- Logs optimal pick counts with daily signal

### Deployments
- `prediction-worker` - Deployed with scenario classification
- `prediction-coordinator` - Deployed with scenario counts

## Scenario Classification Reference

| Scenario | Filters | Hit Rate |
|----------|---------|----------|
| `optimal_over` | OVER + Line <12 + Edge ≥5 | 87.3% |
| `ultra_high_edge_over` | OVER + Edge ≥7 | 88.5% |
| `optimal_under` | UNDER + Line ≥25 + Edge ≥3 | 70.7% |
| `under_safe` | UNDER + Line ≥20 + No blacklist | 65% |
| `anti_under_low_line` | UNDER + Line <15 | 53.8% |
| `low_edge` | Edge <3 | 51.5% |

## The Regeneration Question

When predictions are regenerated (e.g., line changes from 10.5 to 12.5):

1. **Current behavior**: A new prediction record is created, `scenario_category` is calculated fresh
2. **Question**: Is the old prediction's `scenario_category` still valid? Does it matter?
3. **Consider**:
   - Predictions have `is_active` flag (only active predictions matter)
   - Old predictions are superseded (`superseded_by` column)
   - Daily signals are recalculated after prediction regeneration

### Files to Check for Regeneration Logic
```
predictions/worker/worker.py  # Search for "supersede" or "regenerat"
predictions/coordinator/coordinator.py  # Batch processing logic
```

## Your Tasks

1. **Study the implementation** - Read the docs and code listed above
2. **Answer the regeneration question** - How does prediction regeneration interact with scenario classification?
3. **Recommend any fixes** - If there's a gap, propose a solution
4. **Update documentation** - If you make changes or clarifications

## Verification Queries

```sql
-- Check if scenario_category is being populated (after next prediction run)
SELECT
  scenario_category,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1
  AND is_active = TRUE
GROUP BY scenario_category
ORDER BY count DESC;

-- Check daily signals have scenario counts
SELECT game_date, daily_signal, optimal_over_count, optimal_under_count, ultra_high_edge_count
FROM nba_predictions.daily_prediction_signals
WHERE game_date >= CURRENT_DATE() - 3
ORDER BY game_date DESC;

-- Check for regenerated predictions (multiple versions for same player/game)
SELECT
  player_lookup,
  game_date,
  COUNT(*) as versions,
  SUM(CASE WHEN is_active THEN 1 ELSE 0 END) as active_versions
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1
  AND system_id = 'catboost_v9'
GROUP BY player_lookup, game_date
HAVING COUNT(*) > 1
LIMIT 10;
```

## Quick Reference

| Resource | Location |
|----------|----------|
| Worker code | `predictions/worker/worker.py` |
| Signal calculator | `predictions/coordinator/signal_calculator.py` |
| Scenario docs | `docs/08-projects/current/scenario-filtering-system/` |
| Hit rate skill | `.claude/skills/hit-rate-analysis/SKILL.md` (queries 8-11) |
| Subset skill | `.claude/skills/subset-picks/SKILL.md` |

---

**Session 112 End** - 2026-02-03 ~7:00 PM PT
