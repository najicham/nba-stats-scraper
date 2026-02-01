# Dynamic Subset System Design

**Created**: Session 70 (2026-02-01)
**Status**: DESIGN - Ready for Review
**Builds On**: Session 75 Subset Architecture

---

## Problem Statement

The existing subset system uses **static filters** (confidence thresholds, edge, direction). But we've discovered **dynamic signals** (like pct_over) that vary daily and predict performance.

**Current gap**: No way to say "only bet today's picks IF the pre-game signal is favorable."

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
│  LAYER 4: PRESENTATION                              │
│  • /subset-picks skill                              │
│  • Daily dashboard with signal indicators           │
│  • Performance tracking per dynamic subset          │
└─────────────────────────────────────────────────────┘
```

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

## Changelog

| Date | Change |
|------|--------|
| 2026-02-01 | Initial design based on Session 70 findings |

---

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
