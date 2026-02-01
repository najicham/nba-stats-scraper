# Dynamic Subset System Design

**Created**: Session 70 (2026-02-01)
**Updated**: Session 70 (2026-02-01) - Added pick ranking system
**Status**: DESIGN - Ready for Review
**Builds On**: Session 75 Subset Architecture

---

## Problem Statement

The existing subset system uses **static filters** (confidence thresholds, edge, direction). But we have two gaps:

1. **No dynamic signals**: No way to say "only bet today's picks IF the pre-game signal is favorable"
2. **No ranking**: When we have 10 high-edge picks, no way to select the "best" 5

This design addresses both problems.

---

## Proposed Solution: Dynamic Subsets

### Concept

Add a new layer to the subset system that evaluates **daily pre-game signals** before recommending picks.

```
┌─────────────────────────────────────────────────────┐
│  LAYER 1: FOUNDATION (unchanged)                     │
│  Base predictions from all models                    │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 2A: STATIC SUBSETS (existing)                │
│  • high_edge (5+ points)                            │
│  • premium (92+ conf, 3+ edge)                      │
│  • problem_tier (88-90% conf)                       │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 2B: DYNAMIC SIGNALS (NEW)                    │
│  Calculated daily before games:                     │
│  • pct_over: % of predictions recommending OVER     │
│  • pick_volume: # of high-edge picks                │
│  • model_agreement: % where V8 & V9 agree           │
│  • avg_edge: mean edge across picks                 │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 3: DYNAMIC SUBSETS (NEW)                     │
│  Combine static + dynamic:                          │
│  • high_edge_balanced: high edge + pct_over 25-40%  │
│  • high_edge_any: high edge regardless of signal    │
│  • premium_safe: premium + not under_heavy day      │
│  • consensus_balanced: V8+V9 agree + balanced day   │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 3B: PICK RANKING (NEW)                       │
│  Rank picks within each subset:                     │
│  • composite_score = (edge * 10) + (conf * 0.5)     │
│  • pick_rank = ROW_NUMBER by score                  │
│  • Enables "top 5" or "top 10" subsets              │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 4: PRESENTATION                              │
│  • /subset-picks skill                              │
│  • Daily dashboard with signal indicators           │
│  • Performance tracking per dynamic subset          │
└─────────────────────────────────────────────────────┘
```

---

## Pick Ranking System

### The Problem

Even with signal filtering, you might have 10 high-edge picks but only want to bet 5. How do you choose?

### Solution: Composite Score

Combine edge and confidence into a single ranking score:

```
composite_score = (edge * 10) + (confidence_score * 0.5)
```

**Why this formula?**
- **Edge is primary**: Bigger edge = more value (multiplied by 10)
- **Confidence is secondary**: Tiebreaker (multiplied by 0.5)
- **Edge dominates**: A 6-point edge always beats a 5-point edge, regardless of confidence

### Example Ranking

| Player | Edge | Confidence | Composite Score | Rank |
|--------|------|------------|-----------------|------|
| Player A | 7.2 | 87% | 72 + 43.5 = **115.5** | 1 |
| Player B | 6.5 | 91% | 65 + 45.5 = **110.5** | 2 |
| Player C | 6.4 | 88% | 64 + 44.0 = **108.0** | 3 |
| Player D | 5.8 | 92% | 58 + 46.0 = **104.0** | 4 |
| Player E | 5.1 | 89% | 51 + 44.5 = **95.5** | 5 |

Notice: Player A (7.2 edge, 87% conf) ranks higher than Player D (5.8 edge, 92% conf) because edge matters more.

### Ranked Subsets

These subsets use the composite score to limit picks:

| Subset | Base Filter | Ranking | Description |
|--------|-------------|---------|-------------|
| `v9_high_edge_top3` | edge ≥ 5 | Top 3 by score | Ultra-selective |
| `v9_high_edge_top5` | edge ≥ 5 | Top 5 by score | Recommended default |
| `v9_high_edge_top10` | edge ≥ 5 | Top 10 by score | More volume |
| `v9_high_edge_all` | edge ≥ 5 | All picks | No limit |

### Combining Ranking + Signals

The ranking system works **with or without** signal filtering:

**Option A: Signal + Ranking**
```
1. Check pct_over signal → GREEN? Continue
2. Filter to high-edge picks (edge ≥ 5)
3. Rank by composite_score
4. Take top 5
```

**Option B: Ranking Only (No Signal)**
```
1. Filter to high-edge picks (edge ≥ 5)
2. Rank by composite_score
3. Take top 5
```

Both are valid. The signal adds ~28% hit rate improvement, but ranking alone still gives you the best picks available.

---

## New Tables

### 1. daily_prediction_signals

Stores pre-game signals calculated each morning.

```sql
CREATE TABLE `nba-props-platform.nba_predictions.daily_prediction_signals` (
  -- Identity
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,  -- 'catboost_v9', 'catboost_v8', 'all'

  -- Calculated Signals
  total_picks INT64,
  high_edge_picks INT64,      -- edge >= 5
  premium_picks INT64,        -- conf >= 92 AND edge >= 3

  pct_over FLOAT64,           -- % recommending OVER
  pct_under FLOAT64,          -- % recommending UNDER

  avg_confidence FLOAT64,
  avg_edge FLOAT64,

  -- Signal Classifications
  skew_category STRING,       -- 'UNDER_HEAVY', 'BALANCED', 'OVER_HEAVY'
  volume_category STRING,     -- 'LOW', 'NORMAL', 'HIGH'

  -- Composite Signal
  daily_signal STRING,        -- 'GREEN', 'YELLOW', 'RED'
  signal_explanation STRING,  -- Human-readable explanation

  -- Metadata
  calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

  PRIMARY KEY (game_date, system_id) NOT ENFORCED
)
PARTITION BY game_date;
```

### 2. dynamic_subset_definitions

Extends pick_subset_definitions with signal conditions.

```sql
CREATE TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions` (
  -- Identity
  subset_id STRING NOT NULL,
  subset_name STRING NOT NULL,
  subset_description STRING NOT NULL,

  -- Base Filter (static, like existing subsets)
  system_id STRING,           -- 'catboost_v9' or NULL for any
  base_filter_sql STRING,     -- WHERE clause for picks

  -- Signal Conditions (dynamic, evaluated daily)
  signal_conditions ARRAY<STRUCT<
    signal_name STRING,       -- 'pct_over', 'high_edge_picks', etc.
    operator STRING,          -- '>=', '<=', 'IN', 'BETWEEN'
    value STRING              -- '25', '25,40' for BETWEEN
  >>,

  -- When signals don't match
  fallback_behavior STRING,   -- 'EXCLUDE_ALL', 'REDUCE_CONFIDENCE', 'FLAG_ONLY'

  -- Metadata
  is_active BOOL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

  PRIMARY KEY (subset_id) NOT ENFORCED
);
```

---

## Proposed Dynamic Subsets

### Subset 1: `v9_high_edge_balanced`

**Description**: V9 high-edge picks, but only on days with balanced pct_over.

**Static Filter**:
```sql
system_id = 'catboost_v9'
AND ABS(predicted_points - current_points_line) >= 5
```

**Signal Conditions**:
- pct_over BETWEEN 25 AND 40

**Historical Performance**:
- With signal: 82% hit rate (61 picks)
- Without signal: 54% hit rate (26 picks)

---

### Subset 2: `v9_high_edge_any`

**Description**: V9 high-edge picks regardless of daily signal (control group).

**Static Filter**:
```sql
system_id = 'catboost_v9'
AND ABS(predicted_points - current_points_line) >= 5
```

**Signal Conditions**: None

**Purpose**: Baseline to compare against signal-filtered subsets.

---

### Subset 3: `v9_premium_safe`

**Description**: V9 premium picks (92+ conf, 3+ edge) on non-warning days.

**Static Filter**:
```sql
system_id = 'catboost_v9'
AND confidence_score >= 0.92
AND ABS(predicted_points - current_points_line) >= 3
```

**Signal Conditions**:
- daily_signal IN ('GREEN', 'YELLOW')  -- Not RED

---

### Subset 4: `consensus_balanced`

**Description**: Picks where V8 and V9 agree, on balanced days.

**Static Filter**:
```sql
-- Picks where both models recommend same direction
EXISTS (
  SELECT 1 FROM predictions v8
  WHERE v8.system_id = 'catboost_v8'
    AND v8.player_lookup = p.player_lookup
    AND v8.game_date = p.game_date
    AND v8.recommendation = p.recommendation
)
```

**Signal Conditions**:
- pct_over BETWEEN 20 AND 45

---

### Subset 5: `v9_high_edge_warning`

**Description**: V9 high-edge on WARNING days (for tracking only).

**Static Filter**:
```sql
system_id = 'catboost_v9'
AND ABS(predicted_points - current_points_line) >= 5
```

**Signal Conditions**:
- pct_over < 25 OR pct_over > 45

**Purpose**: Shadow tracking - see if warning days really underperform.

---

### Subset 6: `v9_high_edge_top5`

**Description**: Top 5 high-edge picks by composite score (regardless of signal).

**Static Filter**:
```sql
system_id = 'catboost_v9'
AND ABS(predicted_points - current_points_line) >= 5
```

**Ranking**:
```sql
ROW_NUMBER() OVER (
  ORDER BY (ABS(predicted_points - current_points_line) * 10) + (confidence_score * 0.5) DESC
) <= 5
```

**Signal Conditions**: None (works any day)

**Purpose**: Always get the best 5 picks, even on RED signal days.

---

### Subset 7: `v9_high_edge_top5_balanced`

**Description**: Top 5 high-edge picks, but only on balanced signal days.

**Static Filter**:
```sql
system_id = 'catboost_v9'
AND ABS(predicted_points - current_points_line) >= 5
```

**Ranking**: Top 5 by composite score

**Signal Conditions**:
- pct_over BETWEEN 25 AND 40

**Purpose**: Best of both worlds - ranking + signal filtering.

---

### Subset 8: `v9_high_edge_top10`

**Description**: Top 10 high-edge picks by composite score.

**Static Filter**:
```sql
system_id = 'catboost_v9'
AND ABS(predicted_points - current_points_line) >= 5
```

**Ranking**: Top 10 by composite score

**Signal Conditions**: None

**Purpose**: More volume while still prioritizing best picks.

---

### Subset 9: `v9_best_of_day`

**Description**: Single best pick of the day (highest composite score).

**Static Filter**:
```sql
system_id = 'catboost_v9'
AND ABS(predicted_points - current_points_line) >= 5
```

**Ranking**: Top 1 by composite score

**Signal Conditions**: None

**Purpose**: "Lock of the day" - one high-conviction pick.

---

## Skill Design: `/subset-picks`

### Purpose

Query and display picks from any defined subset with performance context.

### Usage

```
/subset-picks                           # Show available subsets
/subset-picks v9_high_edge_balanced     # Today's picks from this subset
/subset-picks v9_high_edge_balanced --history 7  # Last 7 days performance
```

### Output Example

```
## V9 High Edge Balanced - Today (Feb 1, 2026)

### Pre-Game Signal Check
| Signal | Value | Status |
|--------|-------|--------|
| pct_over | 10.6% | ⚠️ UNDER_HEAVY |
| high_edge_picks | 4 | ⚠️ LOW |
| Daily Signal | RED | Not recommended |

⚠️ **WARNING**: Today's signal is RED. This subset recommends
   SKIPPING today's picks based on historical performance.

### Picks (showing for reference only)
| Player | Line | Prediction | Edge | Recommendation |
|--------|------|------------|------|----------------|
| Player A | 22.5 | 28.1 | +5.6 | OVER |
| Player B | 18.5 | 12.8 | -5.7 | UNDER |
| Player C | 25.5 | 31.2 | +5.7 | OVER |
| Player D | 19.5 | 13.1 | -6.4 | UNDER |

### Historical Performance (Last 14 Days)
| Category | Days | Picks | Hit Rate |
|----------|------|-------|----------|
| GREEN (Balanced) | 10 | 52 | 81.2% |
| RED (Warning) | 4 | 18 | 55.6% |
| Overall | 14 | 70 | 73.6% |
```

---

## Skill Design: `/subset-performance`

### Purpose

Compare performance across all defined subsets.

### Usage

```
/subset-performance                     # All subsets, last 7 days
/subset-performance --period 30         # Last 30 days
/subset-performance --subset v9_high*   # Filter by pattern
```

### Output Example

```
## Subset Performance Report (Jan 25 - Feb 1, 2026)

| Subset | Picks | Hit Rate | ROI | Signal Filter |
|--------|-------|----------|-----|---------------|
| v9_high_edge_balanced | 52 | 81.2% | +42% | pct_over 25-40% |
| v9_premium_safe | 38 | 76.3% | +31% | daily_signal != RED |
| consensus_balanced | 31 | 74.2% | +27% | pct_over 20-45% |
| v9_high_edge_any | 70 | 65.4% | +12% | (none) |
| v9_high_edge_warning | 18 | 55.6% | -8% | pct_over <25 or >45 |

### Signal Effectiveness
The pct_over signal adds +15.8% hit rate when filtering for balanced days.
Statistical significance: p=0.0065 ✅
```

---

## Implementation Plan

### Phase 1: Signal Infrastructure (This Week)

1. **Create daily_prediction_signals table**
   - Run signal calculation query each morning
   - Store results for historical analysis

2. **Add signal calculation to prediction workflow**
   - After predictions generated, calculate signals
   - Store in BigQuery
   - Log to monitoring

### Phase 2: Dynamic Subsets (Next Week)

1. **Create dynamic_subset_definitions table**
   - Add initial 5 subsets defined above

2. **Create materialized view for dynamic subsets**
   - Join predictions + signals + subset definitions
   - Filter picks based on both static and dynamic criteria

### Phase 3: Skills (Week After)

1. **Create /subset-picks skill**
   - Query picks from any subset
   - Show signal context
   - Display warnings when signal is RED

2. **Create /subset-performance skill**
   - Compare subset performance
   - Calculate signal effectiveness
   - Show statistical significance

### Phase 4: Integration (Ongoing)

1. **Add to daily workflow**
   - Morning: Calculate signals
   - Morning: Flag if RED signal day
   - Evening: Track actual performance

2. **Dashboard integration**
   - Add signal indicators to unified dashboard
   - Show subset performance trends

---

## SQL Queries

### Calculate Daily Signals

```sql
-- Run each morning after predictions are generated
INSERT INTO `nba-props-platform.nba_predictions.daily_prediction_signals`
SELECT
  CURRENT_DATE() as game_date,
  system_id,

  COUNT(*) as total_picks,
  COUNTIF(ABS(predicted_points - current_points_line) >= 5) as high_edge_picks,
  COUNTIF(confidence_score >= 0.92 AND ABS(predicted_points - current_points_line) >= 3) as premium_picks,

  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as pct_under,

  ROUND(AVG(confidence_score), 2) as avg_confidence,
  ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,

  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 THEN 'UNDER_HEAVY'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 40 THEN 'OVER_HEAVY'
    ELSE 'BALANCED'
  END as skew_category,

  CASE
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3 THEN 'LOW'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) > 8 THEN 'HIGH'
    ELSE 'NORMAL'
  END as volume_category,

  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25 THEN 'RED'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3 THEN 'YELLOW'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45 THEN 'YELLOW'
    ELSE 'GREEN'
  END as daily_signal,

  CASE
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) < 25
      THEN 'Heavy UNDER skew - historically 54% hit rate vs 82% on balanced days'
    WHEN COUNTIF(ABS(predicted_points - current_points_line) >= 5) < 3
      THEN 'Low pick volume - high variance expected'
    WHEN ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) > 45
      THEN 'Heavy OVER skew - monitor for potential underperformance'
    ELSE 'Balanced signals - historical 82% hit rate on high-edge picks'
  END as signal_explanation,

  CURRENT_TIMESTAMP() as calculated_at

FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND current_points_line IS NOT NULL
GROUP BY system_id;
```

### Get Subset Picks with Signal Context

```sql
-- Get v9_high_edge_balanced picks for today
WITH daily_signal AS (
  SELECT * FROM `nba-props-platform.nba_predictions.daily_prediction_signals`
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
)
SELECT
  p.player_lookup,
  p.predicted_points,
  p.current_points_line,
  p.predicted_points - p.current_points_line as edge,
  p.recommendation,
  p.confidence_score,
  s.pct_over,
  s.daily_signal,
  CASE
    WHEN s.pct_over BETWEEN 25 AND 40 THEN 'INCLUDED'
    ELSE 'EXCLUDED (signal mismatch)'
  END as subset_status
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
CROSS JOIN daily_signal s
WHERE p.game_date = CURRENT_DATE()
  AND p.system_id = 'catboost_v9'
  AND ABS(p.predicted_points - p.current_points_line) >= 5
  AND p.current_points_line IS NOT NULL
ORDER BY ABS(p.predicted_points - p.current_points_line) DESC;
```

### Get Ranked Picks (Top N)

```sql
-- Get top 5 high-edge picks by composite score
WITH ranked_picks AS (
  SELECT
    p.player_lookup,
    p.predicted_points,
    p.current_points_line,
    ABS(p.predicted_points - p.current_points_line) as edge,
    p.recommendation,
    p.confidence_score,
    -- Composite score: edge * 10 + confidence * 0.5
    (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
    ROW_NUMBER() OVER (
      ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
    ) as pick_rank
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  WHERE p.game_date = CURRENT_DATE()
    AND p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5
    AND p.current_points_line IS NOT NULL
)
SELECT * FROM ranked_picks
WHERE pick_rank <= 5  -- Change to 10 for top10, 3 for top3, etc.
ORDER BY pick_rank;
```

### Get Ranked Picks with Signal Context

```sql
-- Combine ranking + signal for full context
WITH daily_signal AS (
  SELECT * FROM `nba-props-platform.nba_predictions.daily_prediction_signals`
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
),
ranked_picks AS (
  SELECT
    p.*,
    ABS(p.predicted_points - p.current_points_line) as edge,
    (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
    ROW_NUMBER() OVER (
      ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
    ) as pick_rank
  FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
  WHERE p.game_date = CURRENT_DATE()
    AND p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5
    AND p.current_points_line IS NOT NULL
)
SELECT
  r.pick_rank,
  r.player_lookup,
  ROUND(r.edge, 1) as edge,
  r.confidence_score,
  ROUND(r.composite_score, 1) as composite_score,
  r.recommendation,
  s.pct_over,
  s.daily_signal,
  -- Subset membership
  CASE WHEN r.pick_rank <= 3 THEN '✅' ELSE '' END as in_top3,
  CASE WHEN r.pick_rank <= 5 THEN '✅' ELSE '' END as in_top5,
  CASE WHEN r.pick_rank <= 10 THEN '✅' ELSE '' END as in_top10,
  CASE WHEN s.pct_over BETWEEN 25 AND 40 THEN '✅' ELSE '⚠️' END as signal_ok
FROM ranked_picks r
CROSS JOIN daily_signal s
ORDER BY r.pick_rank;
```

### Compare Subset Performance (Historical)

```sql
-- Compare performance across different subset strategies
WITH picks_with_results AS (
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
      WHEN (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
           (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
      THEN 1 ELSE 0
    END as is_correct
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
    AND p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5
    AND p.current_points_line IS NOT NULL
    AND pgs.points != p.current_points_line  -- Exclude pushes
)
SELECT
  'v9_high_edge_top3' as subset,
  COUNT(*) as picks,
  SUM(is_correct) as wins,
  ROUND(100.0 * SUM(is_correct) / COUNT(*), 1) as hit_rate
FROM picks_with_results WHERE daily_rank <= 3

UNION ALL

SELECT
  'v9_high_edge_top5' as subset,
  COUNT(*) as picks,
  SUM(is_correct) as wins,
  ROUND(100.0 * SUM(is_correct) / COUNT(*), 1) as hit_rate
FROM picks_with_results WHERE daily_rank <= 5

UNION ALL

SELECT
  'v9_high_edge_top10' as subset,
  COUNT(*) as picks,
  SUM(is_correct) as wins,
  ROUND(100.0 * SUM(is_correct) / COUNT(*), 1) as hit_rate
FROM picks_with_results WHERE daily_rank <= 10

UNION ALL

SELECT
  'v9_high_edge_all' as subset,
  COUNT(*) as picks,
  SUM(is_correct) as wins,
  ROUND(100.0 * SUM(is_correct) / COUNT(*), 1) as hit_rate
FROM picks_with_results

ORDER BY subset;
```

---

## Success Metrics

### Signal Effectiveness
- **Goal**: Signal-filtered subsets outperform unfiltered by 10%+
- **Current**: 82% vs 54% = +28% difference on high-edge picks

### Skill Adoption
- **Goal**: Users run /subset-picks daily
- **Measure**: Skill invocation count

### Betting Performance
- **Goal**: Users who follow signal recommendations profit more
- **Measure**: ROI per subset, tracked daily

---

## Open Questions

1. **Signal granularity**: Should we calculate signals per-game or per-day?
   - Per-day is simpler and matches current analysis
   - Per-game could catch game-specific issues

2. **Multi-model signals**: How to combine V8 and V9 signals?
   - Currently analyzed separately
   - Could create "consensus signal" based on both

3. **Threshold tuning**: Are 25% and 40% the right pct_over thresholds?
   - Based on 23-day sample
   - May need adjustment with more data

4. **Fallback behavior**: What to show users on RED signal days?
   - Option A: Hide picks entirely
   - Option B: Show with prominent warning
   - Option C: Show reduced list (highest edge only)

---

## Related Documents

- `docs/08-projects/current/subset-pick-system/SUBSET_SYSTEM_ARCHITECTURE.md` - Base architecture
- `docs/08-projects/current/pre-game-signals-strategy/README.md` - Signal discovery
- `schemas/bigquery/predictions/04_pick_subset_definitions.sql` - Static subsets

---

## A/B Testing Strategy: Track All Subsets

### Approach

Create **all** subset variations and track performance of each. This lets us discover which combinations work best without guessing.

### Subsets to Track

**By Ranking (no signal filter):**
| Subset | Filter | Expected Volume |
|--------|--------|-----------------|
| `v9_high_edge_top1` | Best single pick | 1/day |
| `v9_high_edge_top3` | Top 3 by score | 3/day |
| `v9_high_edge_top5` | Top 5 by score | 5/day |
| `v9_high_edge_top10` | Top 10 by score | 5-10/day |
| `v9_high_edge_all` | All high-edge | 3-15/day |

**By Signal (no ranking):**
| Subset | Signal Condition | Expected Volume |
|--------|------------------|-----------------|
| `v9_high_edge_balanced` | pct_over 25-40% | 0-15/day |
| `v9_high_edge_warning` | pct_over <25% or >45% | 0-15/day |

**Combined (ranking + signal):**
| Subset | Ranking + Signal | Expected Volume |
|--------|------------------|-----------------|
| `v9_high_edge_top5_balanced` | Top 5 + balanced day | 0-5/day |
| `v9_high_edge_top5_any` | Top 5 regardless | 3-5/day |

### What We'll Learn

After 2-4 weeks of tracking:

1. **Does ranking improve hit rate?**
   - Compare top3 vs top10 vs all
   - Hypothesis: top3 > top5 > top10 > all

2. **Does the signal filter add value on top of ranking?**
   - Compare `top5_balanced` vs `top5_any`
   - If similar, signal may be redundant with ranking

3. **What's the optimal subset?**
   - May find `top5_balanced` is best overall
   - Or may find `top3_any` is simpler and just as good

### Daily Tracking Query

```sql
-- Run daily to track all subset performance
INSERT INTO `nba-props-platform.nba_predictions.subset_daily_performance`
WITH base_data AS (
  -- ... (full query from Compare Subset Performance section)
)
SELECT
  CURRENT_DATE() as report_date,
  subset,
  picks,
  wins,
  hit_rate,
  CURRENT_TIMESTAMP() as calculated_at
FROM (
  -- All subset calculations
);
```

---

## Changelog

| Date | Change |
|------|--------|
| 2026-02-01 | Initial design based on Session 70 findings |
| 2026-02-01 | Added pick ranking system with composite score |
| 2026-02-01 | Added ranked subsets (top3, top5, top10) |
| 2026-02-01 | Added A/B testing strategy for all subsets |

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
