# Session 113 Handoff: Phase 6 Subset Exporter

## Overview

Build a Phase 6 exporter that publishes optimal subset picks to GCS for website consumption. The subset/scenario system was implemented in Sessions 111-113 and identifies high-value betting opportunities.

## Critical: Data Quality Issue Discovered

**Before building the exporter, you may need to fix a feature calculation bug.**

Session 113 discovered that `points_avg_last_5` in the feature store is wrong for ~26% of records:

| Accuracy | % of Records |
|----------|--------------|
| Accurate (<1 pt off) | 51.5% |
| Close (1-3 pts off) | 22.5% |
| Off (3-5 pts) | 10.3% |
| **Wrong (>5 pts)** | **15.7%** |

**Examples of the bug:**
- Nikola Jokic: Feature shows 6.2, actual L5 is 31.0 (25 pts off!)
- Lauri Markkanen: Feature shows 3.8, actual L5 is 26.6 (23 pts off!)
- Luka Doncic: Feature shows 18.4, actual L5 is 33.4 (15 pts off!)

**Validation query:**
```sql
WITH manual_calc AS (
  SELECT
    player_lookup,
    game_date,
    ROUND(AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ), 1) as manual_l5
  FROM nba_analytics.player_game_summary
  WHERE game_date >= '2025-12-01'
    AND points IS NOT NULL
),
feature_values AS (
  SELECT player_lookup, game_date, points_avg_last_5
  FROM nba_analytics.upcoming_player_game_context
  WHERE game_date >= '2026-01-01'
)
SELECT
  f.player_lookup,
  f.game_date,
  f.points_avg_last_5 as feature_l5,
  m.manual_l5,
  ROUND(ABS(f.points_avg_last_5 - m.manual_l5), 1) as difference
FROM feature_values f
JOIN manual_calc m ON f.player_lookup = m.player_lookup AND f.game_date = m.game_date
WHERE ABS(f.points_avg_last_5 - m.manual_l5) > 5
ORDER BY difference DESC
LIMIT 20;
```

**Decision needed:** Fix the feature calculation first, or proceed with exporter knowing data has issues?

---

## Scenario/Subset System (Sessions 111-113)

### What We Built

A classification system that tags each prediction with a `scenario_category` at generation time. This identifies optimal betting opportunities.

### Scenario Categories

| Scenario | Filters | Hit Rate | ROI | Action |
|----------|---------|----------|-----|--------|
| `optimal_over` | OVER + Line <12 + Edge ≥5 | **87.3%** | +66.8% | BET |
| `ultra_high_edge_over` | OVER + Edge ≥7 | **88.5%** | +69.0% | BET |
| `optimal_under` | UNDER + Line ≥25 + Edge ≥3 + Not blacklisted | **70.7%** | +35.0% | BET |
| `under_safe` | UNDER + Line ≥20 + Not blacklisted/risky | **65.0%** | +24.0% | BET |
| `high_edge_over` | OVER + Edge ≥5 | ~75% | ~30% | SELECTIVE |
| `standard_over` | OVER + Edge 3-5 | ~58% | ~5% | CAUTION |
| `standard_under` | UNDER + Edge 3-5 | ~58% | ~5% | CAUTION |
| `anti_under_low_line` | UNDER + Line <15 | 53.8% | -5% | **AVOID** |
| `under_risky` | UNDER + Blacklisted/Risky opponent | ~45% | -15% | **AVOID** |
| `low_edge` | Edge <3 | 51.5% | -2% | **SKIP** |

### Player Blacklist (UNDER bets only)

These players have <50% UNDER hit rate - never bet UNDER on them:

| Player | player_lookup | UNDER HR |
|--------|---------------|----------|
| Luka Doncic | lukadoncic | 45.5% |
| Julius Randle | juliusrandle | 42.9% |
| Jaren Jackson Jr | jarenjacksonjr | 28.6% |
| LaMelo Ball | lameloball | 44.4% |
| Dillon Brooks | dillonbrooks | 40.0% |
| Michael Porter Jr | michaelporterjr | 40.0% |

### Opponent Risk List (UNDER bets only)

UNDER bets vs these teams have <40% hit rate:

| Team | Tricode | UNDER HR |
|------|---------|----------|
| Philadelphia | PHI | 36.4% |
| Minnesota | MIN | 37.5% |
| Detroit | DET | 37.5% |
| Miami | MIA | 38.5% |
| Denver | DEN | 40.0% |

### Key Finding: V8 vs V9

| Pattern | V8 HR | V9 HR | Model-Agnostic? |
|---------|-------|-------|-----------------|
| optimal_over | 82.2% | 87.3% | ✅ Yes |
| optimal_under | 67.2% | 70.7% | ✅ Yes |
| ultra_high_edge_over | 67.5% | 88.5% | ❌ V9 only |

`optimal_over` and `optimal_under` work for both V8 and V9. High-edge OVER patterns are V9-specific.

---

## Database Schema

### player_prop_predictions (New Columns - Session 112)

```sql
scenario_category STRING  -- optimal_over, optimal_under, low_edge, etc.
scenario_flags STRING     -- JSON: {"edge": 5.2, "line_value": 10.5, "blacklisted_player": false}
```

### daily_prediction_signals (New Columns - Session 112)

```sql
optimal_over_count INT64
optimal_under_count INT64
ultra_high_edge_count INT64
anti_pattern_count INT64
```

### dynamic_subset_definitions (Existing + New Columns)

```sql
subset_id STRING              -- e.g., 'optimal_over', 'v9_high_edge_top5'
subset_name STRING            -- Display name
system_id STRING              -- e.g., 'catboost_v9'
min_edge FLOAT64              -- Minimum edge filter
min_confidence FLOAT64        -- Minimum confidence filter
top_n INT64                   -- Limit to top N picks
recommendation_filter STRING  -- 'OVER', 'UNDER', or NULL for both
line_min FLOAT64              -- Minimum line value
line_max FLOAT64              -- Maximum line value
exclude_players STRING        -- JSON array of blacklisted player_lookups
exclude_opponents STRING      -- JSON array of risky opponent tricodes
scenario_category STRING      -- 'optimal', 'anti_pattern', 'signal_based'
expected_hit_rate FLOAT64     -- Historical hit rate
expected_roi FLOAT64          -- Historical ROI
```

---

## Query: Today's Optimal Picks

```sql
SELECT
  player_lookup,
  recommendation,
  current_points_line as line,
  ROUND(predicted_points, 1) as predicted,
  ROUND(ABS(predicted_points - current_points_line), 1) as edge,
  scenario_category,
  ROUND(confidence_score, 2) as confidence,
  game_id
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
  AND scenario_category IN ('optimal_over', 'optimal_under', 'ultra_high_edge_over')
ORDER BY
  CASE scenario_category
    WHEN 'ultra_high_edge_over' THEN 1
    WHEN 'optimal_over' THEN 2
    WHEN 'optimal_under' THEN 3
  END,
  edge DESC;
```

---

## Phase 6 Export Requirements

### What to Export

1. **Daily optimal picks** - Players with optimal scenarios
2. **Daily signal** - RED/YELLOW/GREEN market condition
3. **Historical performance** - Hit rates by scenario
4. **Subset definitions** - Filter criteria for each subset

### Suggested JSON Structure

```json
{
  "game_date": "2026-02-04",
  "generated_at": "2026-02-04T10:30:00Z",
  "signal": {
    "daily_signal": "GREEN",
    "pct_over": 58.3,
    "high_edge_picks": 12,
    "total_picks": 45
  },
  "optimal_picks": [
    {
      "player": "Trae Young",
      "player_lookup": "traeyoung",
      "team": "ATL",
      "opponent": "BOS",
      "recommendation": "OVER",
      "line": 10.5,
      "predicted": 16.2,
      "edge": 5.7,
      "scenario": "optimal_over",
      "confidence": 0.72,
      "expected_hit_rate": 87.3
    }
  ],
  "scenarios_summary": {
    "optimal_over": {"count": 3, "expected_hr": 87.3},
    "optimal_under": {"count": 2, "expected_hr": 70.7},
    "ultra_high_edge": {"count": 1, "expected_hr": 88.5}
  },
  "avoid_picks": [
    {
      "player": "Luka Doncic",
      "reason": "blacklisted_player",
      "scenario": "under_risky"
    }
  ]
}
```

### GCS Path Convention

```
gs://nba-props-platform-api/
  daily/
    2026-02-04/
      optimal-picks.json
      signal.json
  latest/
    optimal-picks.json  (symlink/copy of today's)
    signal.json
```

---

## Existing Code References

### Phase 6 Docs
- `docs/03-phases/` - Phase architecture documentation

### Subset Picks Notifier (Already Built)
- `shared/notifications/subset_picks_notifier.py` - Queries and formats picks
- Has working query logic for subsets, can be adapted for JSON export

### Signal Calculator
- `predictions/coordinator/signal_calculator.py` - Daily signal calculation
- Lines 228-270: Signal data structure

### Scenario Classification
- `predictions/worker/worker.py` lines 398-485: `_classify_scenario()` function
- Contains blacklist and risk opponent logic

### Schema Definitions
- `schemas/bigquery/predictions/04b_scenario_subset_extensions.sql`

---

## Verification Queries

### Check scenario_category is populated
```sql
SELECT scenario_category, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1 AND is_active = TRUE
GROUP BY 1;
```

### Check daily signals have scenario counts
```sql
SELECT game_date, daily_signal, optimal_over_count, optimal_under_count
FROM nba_predictions.daily_prediction_signals
WHERE game_date >= CURRENT_DATE() - 3
ORDER BY game_date DESC;
```

---

## Session 113 Deployments

These services were deployed with scenario classification:
- `prediction-worker` (commit c0c74715)
- `prediction-coordinator` (commit c0c74715)

Scenario backfill was run: 16,721 historical predictions now have `scenario_category` populated.

---

## Task Checklist

1. [ ] **Decide:** Fix L5 feature bug first, or proceed with exporter?
2. [ ] Review existing Phase 6 export code structure
3. [ ] Create export function for optimal picks JSON
4. [ ] Add daily signal to export
5. [ ] Set up GCS paths and permissions
6. [ ] Add to daily pipeline (after predictions complete)
7. [ ] Verify JSON structure works for website
8. [ ] Document the API endpoint

---

## Questions for User

Before starting, clarify:
1. What's the website expecting? (JSON structure, field names)
2. Should we include historical performance in daily export?
3. Should anti-patterns (picks to avoid) be included?
4. How often should exports refresh? (Once daily after predictions, or more?)

---

## Contact

Session 113 completed 2026-02-04. Questions about subset system → read Session 112 handoff.
