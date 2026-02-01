---
name: subset-performance
description: Compare performance across all defined dynamic subsets
---

# /subset-performance - Compare Subset Performance

You are comparing performance across all defined dynamic subsets to help users identify which betting strategies work best.

## Purpose

Compare hit rates, ROI, and signal effectiveness across all dynamic subsets over a specified time period.

## Usage

When the user invokes this skill:

```
/subset-performance                    # All subsets, last 7 days
/subset-performance --period 14        # Last 14 days
/subset-performance --period 30        # Last 30 days
/subset-performance --subset v9_high*  # Filter by pattern
```

## Workflow

### Step 1: Get Subset Definitions

First, query the active subsets:

```sql
SELECT
  subset_id,
  subset_name,
  system_id,
  min_edge,
  min_confidence,
  use_ranking,
  top_n,
  signal_condition,
  notes
FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
WHERE is_active = TRUE
ORDER BY subset_id;
```

### Step 2: Calculate Performance for Each Subset

Run this comprehensive query to get performance for all subsets:

```sql
WITH subset_defs AS (
  SELECT * FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
  WHERE is_active = TRUE
),
picks_with_results AS (
  SELECT
    p.game_date,
    p.player_lookup,
    p.system_id,
    ABS(p.predicted_points - p.current_points_line) as edge,
    p.confidence_score,
    p.recommendation,
    p.current_points_line,
    (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
    ROW_NUMBER() OVER (
      PARTITION BY p.game_date
      ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
    ) as daily_rank,
    pgs.points as actual_points,
    CASE
      WHEN pgs.points = p.current_points_line THEN NULL  -- Push
      WHEN (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
           (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
      THEN 1 ELSE 0
    END as is_correct,
    s.daily_signal,
    s.pct_over
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  LEFT JOIN `nba-props-platform.nba_predictions.daily_prediction_signals` s
    ON p.game_date = s.game_date AND p.system_id = s.system_id
  WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @period DAY)
    AND p.game_date < CURRENT_DATE()  -- Exclude today (no results yet)
    AND p.current_points_line IS NOT NULL
    AND pgs.points != p.current_points_line  -- Exclude pushes
)
SELECT
  d.subset_id,
  d.subset_name,
  d.signal_condition,
  d.use_ranking,
  d.top_n,
  COUNT(DISTINCT p.game_date) as days,
  COUNT(*) as total_picks,
  SUM(p.is_correct) as wins,
  ROUND(100.0 * SUM(p.is_correct) / NULLIF(COUNT(*), 0), 1) as hit_rate,
  -- Simplified ROI: (hit_rate - 52.38) / 52.38 * 100 (assuming -110 odds)
  ROUND((100.0 * SUM(p.is_correct) / NULLIF(COUNT(*), 0) - 52.38) / 52.38 * 100, 1) as approx_roi_pct
FROM picks_with_results p
CROSS JOIN subset_defs d
WHERE
  -- System filter
  (d.system_id IS NULL OR p.system_id = d.system_id)
  -- Edge filter
  AND p.edge >= COALESCE(d.min_edge, 0)
  -- Confidence filter
  AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
  -- Ranking filter
  AND (d.use_ranking = FALSE OR p.daily_rank <= COALESCE(d.top_n, 999))
  -- Signal filter
  AND (
    d.signal_condition = 'ANY'
    OR (d.signal_condition = 'GREEN' AND p.daily_signal = 'GREEN')
    OR (d.signal_condition = 'GREEN_OR_YELLOW' AND p.daily_signal IN ('GREEN', 'YELLOW'))
    OR (d.signal_condition = 'RED' AND p.daily_signal = 'RED')
  )
GROUP BY d.subset_id, d.subset_name, d.signal_condition, d.use_ranking, d.top_n
HAVING COUNT(*) >= 5  -- Minimum sample size
ORDER BY hit_rate DESC;
```

**Note**: Replace `@period` with the actual number of days (default: 7).

### Step 3: Calculate Signal Effectiveness

Compare performance on GREEN vs RED signal days:

```sql
WITH picks_with_results AS (
  SELECT
    p.game_date,
    ABS(p.predicted_points - p.current_points_line) as edge,
    p.recommendation,
    p.current_points_line,
    pgs.points as actual_points,
    CASE
      WHEN pgs.points = p.current_points_line THEN NULL
      WHEN (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
           (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
      THEN 1 ELSE 0
    END as is_correct,
    s.daily_signal
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  LEFT JOIN `nba-props-platform.nba_predictions.daily_prediction_signals` s
    ON p.game_date = s.game_date AND p.system_id = s.system_id
  WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @period DAY)
    AND p.game_date < CURRENT_DATE()
    AND p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5  -- High edge only
    AND p.current_points_line IS NOT NULL
    AND pgs.points != p.current_points_line
)
SELECT
  daily_signal,
  COUNT(*) as picks,
  SUM(is_correct) as wins,
  ROUND(100.0 * SUM(is_correct) / COUNT(*), 1) as hit_rate
FROM picks_with_results
WHERE daily_signal IS NOT NULL
GROUP BY daily_signal
ORDER BY daily_signal;
```

## Output Format

Present results in clear markdown tables:

```
## Subset Performance Report (Last {N} Days)

### Performance by Subset

| Subset | Picks | Hit Rate | ROI | Signal Filter | Ranking |
|--------|-------|----------|-----|---------------|---------|
| v9_high_edge_balanced | 52 | 81.2% | +55% | GREEN | All |
| v9_high_edge_top5 | 35 | 77.1% | +47% | ANY | Top 5 |
| v9_premium_safe | 38 | 76.3% | +46% | GREEN_OR_YELLOW | All |
| consensus_balanced | 31 | 74.2% | +42% | GREEN | All |
| v9_high_edge_any | 70 | 65.4% | +25% | ANY | All |
| v9_high_edge_warning | 18 | 55.6% | +6% | RED | All |

### Signal Effectiveness (V9 High Edge)

| Signal | Picks | Hit Rate | Interpretation |
|--------|-------|----------|----------------|
| GREEN | 52 | 82% | Bet confidently |
| YELLOW | 18 | 68% | Proceed with caution |
| RED | 26 | 54% | Consider skipping |

### Key Insights

1. **Signal filter impact**: GREEN signal days show +{X}% higher hit rate
2. **Best performing subset**: {subset_name} with {hit_rate}% hit rate
3. **Ranking impact**: Top 5 picks vs all picks difference: {diff}%

### Recommendations

Based on the data:
- **High confidence days (GREEN signal)**: Use {best_green_subset}
- **Low confidence days (RED signal)**: Consider using {best_red_subset} or skipping
- **Volume vs accuracy trade-off**: {insight}
```

## Key Metrics

| Metric | Formula | Good Value |
|--------|---------|------------|
| **Hit Rate** | wins / total_picks * 100 | >= 52.4% (break-even at -110) |
| **Approx ROI** | (hit_rate - 52.38) / 52.38 * 100 | > 0% |
| **Signal Lift** | hit_rate_green - hit_rate_red | > 15% |

## Breakeven Reference

At standard -110 odds:
- **Breakeven hit rate**: 52.38%
- **55% hit rate**: ~5% ROI
- **60% hit rate**: ~15% ROI
- **65% hit rate**: ~24% ROI
- **70% hit rate**: ~34% ROI
- **75% hit rate**: ~43% ROI
- **80% hit rate**: ~53% ROI

## Notes

1. **Exclude today's games** - They haven't been graded yet
2. **Exclude pushes** - Where actual == line
3. **Minimum sample size** - At least 5 picks to show a subset
4. **Signal data dependency** - Signals must exist in `daily_prediction_signals` table
5. **Default period** - 7 days if not specified

## Related Tables

- `nba_predictions.dynamic_subset_definitions` - Subset configurations
- `nba_predictions.daily_prediction_signals` - Daily signal metrics
- `nba_predictions.player_prop_predictions` - Base predictions
- `nba_analytics.player_game_summary` - Actual results for grading

## Related Skills

- `/subset-picks` - Get today's picks from a specific subset
- `/hit-rate-analysis` - Detailed hit rate analysis with groupings
- `/validate-daily` - Daily pipeline validation

## Related Documentation

- Design: `docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md`
