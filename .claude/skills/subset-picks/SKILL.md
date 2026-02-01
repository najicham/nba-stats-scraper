---
name: subset-picks
description: Query picks from dynamic subsets with signal context
---

# /subset-picks - Query Picks from Dynamic Subsets

You are querying picks from the dynamic subset system. This system filters predictions based on both static criteria (edge, confidence) and dynamic daily signals (pct_over).

## Purpose

Query and display picks from any defined dynamic subset, with signal context and performance history.

## Usage

When the user invokes this skill:

```
/subset-picks                              # List available subsets
/subset-picks <subset_id>                  # Today's picks from subset
/subset-picks <subset_id> --history 7      # Last 7 days performance
```

## Workflow

### If no subset specified: List Available Subsets

Query all active subsets and display in a formatted table:

```sql
SELECT
  subset_id,
  subset_name,
  CASE WHEN use_ranking THEN CONCAT('Top ', CAST(top_n AS STRING)) ELSE 'All' END as selection,
  signal_condition,
  notes
FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
WHERE is_active = TRUE
ORDER BY subset_id;
```

**Output format:**

```
## Available Dynamic Subsets

| Subset ID | Name | Selection | Signal | Notes |
|-----------|------|-----------|--------|-------|
| v9_high_edge_top5 | V9 Top 5 | Top 5 | ANY | Recommended default |
| v9_high_edge_balanced | V9 High Edge Balanced | All | GREEN | Historical 82% HR |
...
```

### If subset specified: Get Today's Picks

First, determine if the subset uses ranking:

```sql
SELECT use_ranking, top_n, signal_condition, min_edge, min_confidence
FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
WHERE subset_id = '{SUBSET_ID}' AND is_active = TRUE;
```

Then use the appropriate query:

#### For UNRANKED subsets (use_ranking = FALSE):

```sql
WITH daily_signal AS (
  SELECT * FROM `nba-props-platform.nba_predictions.daily_prediction_signals`
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
),
subset_def AS (
  SELECT * FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
  WHERE subset_id = '{SUBSET_ID}'
)
SELECT
  p.player_lookup,
  ROUND(p.predicted_points, 1) as predicted,
  p.current_points_line as line,
  ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
  p.recommendation,
  ROUND(p.confidence_score, 2) as confidence,
  s.pct_over,
  s.daily_signal,
  CASE
    WHEN d.signal_condition = 'ANY' THEN '✅ INCLUDED'
    WHEN d.signal_condition = 'GREEN' AND s.daily_signal = 'GREEN' THEN '✅ INCLUDED'
    WHEN d.signal_condition = 'GREEN_OR_YELLOW' AND s.daily_signal IN ('GREEN', 'YELLOW') THEN '✅ INCLUDED'
    WHEN d.signal_condition = 'RED' AND s.daily_signal = 'RED' THEN '✅ INCLUDED'
    ELSE '❌ EXCLUDED (signal mismatch)'
  END as status
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
CROSS JOIN daily_signal s
CROSS JOIN subset_def d
WHERE p.game_date = CURRENT_DATE()
  AND p.system_id = d.system_id
  AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
  AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
  AND p.current_points_line IS NOT NULL
ORDER BY ABS(p.predicted_points - p.current_points_line) DESC;
```

#### For RANKED subsets (use_ranking = TRUE):

```sql
WITH daily_signal AS (
  SELECT * FROM `nba-props-platform.nba_predictions.daily_prediction_signals`
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
),
subset_def AS (
  SELECT * FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
  WHERE subset_id = '{SUBSET_ID}'
),
ranked_picks AS (
  SELECT
    p.player_lookup,
    ROUND(p.predicted_points, 1) as predicted,
    p.current_points_line as line,
    ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
    p.recommendation,
    ROUND(p.confidence_score, 2) as confidence,
    -- Composite score: edge * 10 + confidence * 0.5
    ROUND((ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5), 1) as composite_score,
    ROW_NUMBER() OVER (
      ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
    ) as pick_rank
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  CROSS JOIN subset_def d
  WHERE p.game_date = CURRENT_DATE()
    AND p.system_id = d.system_id
    AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
    AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
    AND p.current_points_line IS NOT NULL
)
SELECT
  r.pick_rank,
  r.player_lookup,
  r.predicted,
  r.line,
  r.edge,
  r.recommendation,
  r.confidence,
  r.composite_score,
  s.pct_over,
  s.daily_signal,
  CASE
    WHEN d.signal_condition = 'ANY' THEN '✅'
    WHEN d.signal_condition = 'GREEN' AND s.daily_signal = 'GREEN' THEN '✅'
    WHEN d.signal_condition = 'GREEN_OR_YELLOW' AND s.daily_signal IN ('GREEN', 'YELLOW') THEN '✅'
    ELSE '⚠️ Signal mismatch'
  END as signal_ok
FROM ranked_picks r
CROSS JOIN daily_signal s
CROSS JOIN subset_def d
WHERE r.pick_rank <= COALESCE(d.top_n, 999)
ORDER BY r.pick_rank;
```

**Output format for picks:**

```
## {Subset Name} - {Date}

### Signal Status
| Metric | Value | Status |
|--------|-------|--------|
| pct_over | X% | {GREEN/YELLOW/RED} |
| Daily Signal | {signal} | {interpretation} |
| Signal Match | ✅/❌ | {reason} |

{If signal mismatch and subset requires specific signal, show warning:}
⚠️ SIGNAL MISMATCH
This subset requires {signal_condition} signal, but today is {daily_signal}.
No picks recommended today based on historical performance.

### Today's Picks
| Rank | Player | Line | Predicted | Edge | Direction | Confidence | Composite Score |
|------|--------|------|-----------|------|-----------|------------|-----------------|
| 1 | Player A | 22.5 | 28.1 | +5.6 | OVER | 0.89 | 100.5 |
...
```

### If --history flag specified: Show Historical Performance

**Query pattern for historical performance:**

```sql
WITH subset_def AS (
  SELECT * FROM `nba-props-platform.nba_predictions.dynamic_subset_definitions`
  WHERE subset_id = '{SUBSET_ID}'
),
picks_with_results AS (
  SELECT
    p.game_date,
    p.player_lookup,
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
  CROSS JOIN subset_def d
  WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {DAYS} DAY)
    AND p.game_date < CURRENT_DATE()  -- Exclude today (no results yet)
    AND p.system_id = d.system_id
    AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
    AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
    AND p.current_points_line IS NOT NULL
    AND pgs.points != p.current_points_line  -- Exclude pushes
)
SELECT
  COUNT(*) as total_picks,
  SUM(is_correct) as wins,
  ROUND(100.0 * SUM(is_correct) / NULLIF(COUNT(*), 0), 1) as hit_rate,
  COUNT(DISTINCT game_date) as days
FROM picks_with_results
CROSS JOIN subset_def d
WHERE (d.use_ranking = FALSE OR daily_rank <= d.top_n)
  AND (
    d.signal_condition = 'ANY'
    OR (d.signal_condition = 'GREEN' AND daily_signal = 'GREEN')
    OR (d.signal_condition = 'GREEN_OR_YELLOW' AND daily_signal IN ('GREEN', 'YELLOW'))
    OR (d.signal_condition = 'RED' AND daily_signal = 'RED')
  );
```

**Output format for history:**

```
## {Subset Name} - Last {N} Days Performance

| Metric | Value |
|--------|-------|
| Days | X |
| Total Picks | Y |
| Wins | Z |
| Hit Rate | W% |

### Interpretation
{Compare to baseline and provide context}
```

## Important Signal Logic

**Signal Condition Matching:**

| Condition | Matches When |
|-----------|-------------|
| `ANY` | Always included, no signal filter |
| `GREEN` | daily_signal = 'GREEN' (pct_over 25-40%) |
| `GREEN_OR_YELLOW` | daily_signal IN ('GREEN', 'YELLOW') |
| `RED` | daily_signal = 'RED' (pct_over <25%) |

**Composite Score Formula:**
```
composite_score = (edge * 10) + (confidence * 0.5)
```

- Edge dominates: 1 point edge difference = 10 score points
- Confidence is tiebreaker: 20% confidence difference = 10 score points
- A 7.2 edge + 87% conf (115.5) beats 5.8 edge + 92% conf (104.0)

## Example Usage

**List all subsets:**
```
User: /subset-picks
→ Display table of all 9 active subsets
```

**Get today's top 5:**
```
User: /subset-picks v9_high_edge_top5
→ Query ranked picks, show top 5 with signal context
```

**Check balanced subset on RED day:**
```
User: /subset-picks v9_high_edge_balanced
→ Show warning that signal is RED, subset requires GREEN
→ Still show picks but with EXCLUDED status
```

**Historical performance:**
```
User: /subset-picks v9_high_edge_top5 --history 14
→ Show last 14 days hit rate for top 5 subset
```

## Notes

1. **Always check signal first** - Show signal status before picks
2. **Warn on mismatches** - If subset requires GREEN but today is RED, warn user
3. **Exclude pushes** - In historical queries, filter `actual_points != line` to exclude pushes
4. **Use composite score for ranking** - Edge * 10 + Confidence * 0.5
5. **Today has no results yet** - Historical queries should exclude CURRENT_DATE()

## Related Tables

- `nba_predictions.dynamic_subset_definitions` - Subset configurations
- `nba_predictions.daily_prediction_signals` - Daily signal metrics
- `nba_predictions.player_prop_predictions` - Base predictions
- `nba_analytics.player_game_summary` - Actual results for grading

## Related Documentation

- Design: `docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md`
- Session findings: `docs/09-handoff/2026-02-01-SESSION-70-V9-PERFORMANCE-ANALYSIS.md`
