# Session 113 Handoff: L5 Feature Calculation Bug

## Priority: HIGH

The `points_avg_last_5` feature in the feature store is incorrect for ~26% of records. This is affecting prediction quality.

## The Problem

| Accuracy | % of Records |
|----------|--------------|
| Accurate (<1 pt off) | 51.5% |
| Close (1-3 pts off) | 22.5% |
| Off (3-5 pts) | 10.3% |
| **Wrong (>5 pts)** | **15.7%** |

### Examples

| Player | Feature L5 | Actual L5 | Difference |
|--------|-----------|-----------|------------|
| Nikola Jokic | 6.2 | 31.0 | 24.8 pts! |
| Lauri Markkanen | 3.8 | 26.6 | 22.8 pts! |
| Kawhi Leonard | 9.0 | 29.2 | 20.2 pts! |
| Luka Doncic | 18.4 | 33.4 | 15.0 pts! |
| Steph Curry | 13.2 | 21.4 | 8.2 pts! |

## Diagnostic Query

```sql
-- Find players with wrong L5 values
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

## Where to Investigate

### Feature Store Processing

The `upcoming_player_game_context` table is populated by Phase 4 precompute processors.

**Key files:**
- `data_processors/precompute/` - Phase 4 processors
- Look for where `points_avg_last_5` is calculated

### What to Check

1. **Date range bug?** - Is the L5 window calculated correctly?
2. **DNP handling?** - Are DNP games (NULL points) incorrectly included?
3. **Ordering issue?** - Is the ORDER BY game_date correct?
4. **Join issue?** - Is data being joined incorrectly across seasons?

### Quick Validation

```sql
-- Check Steph Curry specifically
-- Feature store value for 2026-01-30
SELECT game_date, points_avg_last_5, points_avg_last_10
FROM nba_analytics.upcoming_player_game_context
WHERE player_lookup = 'stephencurry' AND game_date = '2026-01-30';

-- Manual calculation (should match)
SELECT ROUND(AVG(points), 1) as correct_l5
FROM (
  SELECT points FROM nba_analytics.player_game_summary
  WHERE player_lookup = 'stephencurry'
    AND game_date < '2026-01-30'
    AND points IS NOT NULL
  ORDER BY game_date DESC
  LIMIT 5
);
```

## Impact

- **Predictions are less accurate** than they should be
- **Star players** seem most affected (Jokic, Luka, Kawhi, Curry)
- **~26% of predictions** made with bad feature data

## Fix Steps

1. Find the L5 calculation code in Phase 4 processors
2. Identify the bug (likely date window or DNP handling)
3. Fix the calculation
4. Reprocess recent data (at minimum Jan-Feb 2026)
5. Regenerate predictions with correct features
6. Verify fix with diagnostic query

## Related Tables

| Table | Purpose |
|-------|---------|
| `nba_analytics.upcoming_player_game_context` | Feature store (where bug manifests) |
| `nba_analytics.player_game_summary` | Source of truth for points |
| `nba_predictions.player_prop_predictions` | Uses features for predictions |

## Session 113 Findings

- 83% gold tier in feature store is CORRECT (17% are DNPs or early season)
- BUT the feature VALUES themselves have calculation errors
- The bug affects `points_avg_last_5` (and possibly `points_avg_last_10`)

---

**Created:** 2026-02-04 Session 113
