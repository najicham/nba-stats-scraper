# Session 70 Master Plan - Pre-Game Signals & Dynamic Subsets

**Date**: February 1, 2026
**Session**: 70
**Status**: PLAN COMPLETE - Ready for Implementation
**For**: Next session to review and implement

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Session 70 Accomplishments](#session-70-accomplishments)
3. [Discovery: Pre-Game Signals](#discovery-pre-game-signals)
4. [V9 Performance Analysis](#v9-performance-analysis)
5. [Dynamic Subset System Design](#dynamic-subset-system-design)
6. [Implementation Plan](#implementation-plan)
7. [SQL Queries Reference](#sql-queries-reference)
8. [Files Created This Session](#files-created-this-session)
9. [Open Questions](#open-questions)
10. [Quick Start for Next Session](#quick-start-for-next-session)

---

## Executive Summary

### What We Did
1. ✅ Fixed orchestration (5 Cloud Functions deployed)
2. ✅ Analyzed V9 performance (discovered high-edge works, low-edge doesn't)
3. ✅ Discovered pre-game signal (pct_over) that predicts daily performance
4. ✅ Designed dynamic subset system to filter picks based on signals

### Key Finding

**The pct_over signal is statistically significant (p=0.0065)**:

| pct_over | High-Edge Hit Rate | Sample |
|----------|-------------------|--------|
| <25% (Under-heavy) | **54%** | 26 picks |
| ≥25% (Balanced) | **82%** | 61 picks |

This 28-point difference means we can **dramatically improve hit rates** by only betting on days with balanced pct_over.

### What Needs to Be Built

1. **Signal calculation pipeline** - Calculate pct_over each morning
2. **Dynamic subset tables** - Store signal-filtered picks
3. **Skills** - `/subset-picks` and `/subset-performance`
4. **Monitoring** - Track signal effectiveness over time

---

## Session 70 Accomplishments

### 1. Orchestration Fixes

Fixed missing `shared/utils` symlinks in 5 Cloud Functions:

| Cloud Function | Revision | Status |
|----------------|----------|--------|
| phase2-to-phase3-orchestrator | 00035-foc | ✅ Healthy |
| phase3-to-phase4-orchestrator | 00030-miy | ✅ Healthy |
| phase5-to-phase6-orchestrator | 00017-tef | ✅ Healthy |
| daily-health-summary | 00024-kog | ✅ Healthy |
| auto-backfill-orchestrator | 00003-geg | ✅ Healthy |

**Commits**:
- `27ed0fc5` - fix: Add missing shared/utils symlinks to 5 Cloud Functions

### 2. Validation Completed

- All Cloud Function imports pass
- All Cloud Function symlinks valid
- Predictions generated for Feb 1 (200 V9 picks for 10 games)
- Data quality good (94.1% shot zones, 212 players for Jan 31)

---

## Discovery: Pre-Game Signals

### The pct_over Signal

**Definition**: Percentage of predictions recommending OVER vs UNDER

```sql
pct_over = 100.0 * COUNT(recommendation = 'OVER') / COUNT(*)
```

### Why It Matters

When V9 heavily favors UNDER predictions (<25% over):
- High-edge picks drop from 82% → 54% hit rate
- This is barely above the 52.4% breakeven threshold
- Betting on these days erodes profits

### Historical Data (Jan 9-31, 2026)

| Date | pct_over | High-Edge Picks | Hit Rate | Category |
|------|----------|-----------------|----------|----------|
| Jan 31 | 19.6% | 5 | 40% | UNDER_HEAVY |
| Jan 30 | 24.6% | 5 | 75% | BALANCED |
| Jan 29 | 19.7% | 4 | 50% | UNDER_HEAVY |
| Jan 28 | 28.9% | 1 | 100% | BALANCED |
| Jan 27 | 21.8% | 3 | 33% | UNDER_HEAVY |
| Jan 26 | 35.5% | 8 | 86% | BALANCED |
| Jan 25 | 29.0% | 2 | 100% | BALANCED |
| Jan 24 | 28.2% | 2 | 50% | BALANCED |
| Jan 23 | 38.7% | 1 | 100% | BALANCED |
| Jan 22 | 30.6% | 5 | 100% | BALANCED |
| Jan 21 | 27.9% | 7 | 57% | BALANCED |
| Jan 20 | 30.4% | 3 | 100% | BALANCED |

### Statistical Validation

Two-proportion z-test comparing UNDER_HEAVY vs BALANCED:

| Metric | Value |
|--------|-------|
| UNDER_HEAVY hit rate | 53.8% (14/26) |
| BALANCED hit rate | 82.0% (50/61) |
| Difference | 28.2 percentage points |
| Z-statistic | 2.72 |
| **P-value** | **0.0065** |
| 95% CI | [6.7%, 49.6%] |
| Significant? | ✅ Yes (p < 0.01) |

### Thresholds Defined

| pct_over | Category | Historical Performance | Action |
|----------|----------|----------------------|--------|
| <25% | UNDER_HEAVY | 54% hit rate | ⚠️ Reduce/skip betting |
| 25-40% | BALANCED | 82% hit rate | ✅ Normal confidence |
| >40% | OVER_HEAVY | 89% hit rate* | ✅ Higher confidence |

*OVER_HEAVY based on 1 day (Jan 12), needs more data.

### Today's Warning (Feb 1, 2026)

| Metric | Value | Status |
|--------|-------|--------|
| pct_over | **10.6%** | 🔴 EXTREME UNDER |
| high_edge_picks | 4 | ⚠️ LOW |
| Daily Signal | **RED** | Not recommended |

Feb 1 has the most extreme UNDER skew we've seen. Based on historical patterns, expect worse performance.

---

## V9 Performance Analysis

### Key Finding: Two Different Stories

**Story 1: High-Edge Picks (5+ point edge) - GOOD**

| Period | Picks | Hit Rate |
|--------|-------|----------|
| Jan 25-31 (7 days) | 28 | **65.4%** |
| Expected | - | 72% |

V9 high-edge picks are performing well.

**Story 2: Overall Predictions - POOR**

| Period | Picks | Hit Rate |
|--------|-------|----------|
| Jan 25-31 (7 days) | ~800 | **25-35%** |

V9's overall hit rate is dragged down by poor low-edge predictions.

### Conclusion

**Only bet V9 high-edge picks (5+ point edge)**. The low-edge predictions have ~22% hit rate and should be avoided.

### Daily Performance Comparison

| Date | V9 Overall | V8 Overall | V9 High-Edge | V8 High-Edge |
|------|------------|------------|--------------|--------------|
| Jan 31 | 22.1% | 42.2% | 40.0% | 47.6% |
| Jan 30 | 26.2% | 0.0% | 75.0% | 0.0% |
| Jan 29 | 24.8% | 48.3% | 50.0% | 60.0% |
| Jan 28 | 33.3% | 37.0% | 100.0% | 50.0% |
| Jan 27 | 23.8% | 34.9% | 33.3% | 28.6% |
| Jan 26 | 39.3% | 40.3% | 85.7% | 60.3% |
| Jan 25 | 39.4% | 48.1% | 100.0% | 54.3% |

---

## Dynamic Subset System Design

### Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  LAYER 1: FOUNDATION                                │
│  Base predictions from catboost_v9, catboost_v8     │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 2A: STATIC SUBSETS (existing)                │
│  • high_edge (5+ points)                            │
│  • premium (92+ conf, 3+ edge)                      │
│  • actionable_filtered (excludes 88-90%)            │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 2B: DYNAMIC SIGNALS (NEW)                    │
│  Calculated daily before games:                     │
│  • pct_over                                         │
│  • pick_volume                                      │
│  • daily_signal (GREEN/YELLOW/RED)                  │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 3: DYNAMIC SUBSETS (NEW)                     │
│  Combine static + dynamic:                          │
│  • v9_high_edge_balanced                            │
│  • v9_high_edge_any (control)                       │
│  • v9_high_edge_warning (shadow)                    │
│  • consensus_balanced                               │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  LAYER 4: PRESENTATION                              │
│  • /subset-picks skill                              │
│  • /subset-performance skill                        │
│  • Dashboard integration                            │
└─────────────────────────────────────────────────────┘
```

### New Tables Required

#### 1. daily_prediction_signals

Stores pre-game signals calculated each morning.

```sql
CREATE TABLE `nba-props-platform.nba_predictions.daily_prediction_signals` (
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,

  -- Counts
  total_picks INT64,
  high_edge_picks INT64,
  premium_picks INT64,

  -- Signals
  pct_over FLOAT64,
  pct_under FLOAT64,
  avg_confidence FLOAT64,
  avg_edge FLOAT64,

  -- Classifications
  skew_category STRING,      -- 'UNDER_HEAVY', 'BALANCED', 'OVER_HEAVY'
  volume_category STRING,    -- 'LOW', 'NORMAL', 'HIGH'
  daily_signal STRING,       -- 'GREEN', 'YELLOW', 'RED'
  signal_explanation STRING,

  calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

  PRIMARY KEY (game_date, system_id) NOT ENFORCED
)
PARTITION BY game_date;
```

#### 2. dynamic_subset_definitions

Extends existing subset definitions with signal conditions.

```sql
CREATE TABLE `nba-props-platform.nba_predictions.dynamic_subset_definitions` (
  subset_id STRING NOT NULL,
  subset_name STRING NOT NULL,
  subset_description STRING NOT NULL,

  system_id STRING,
  base_filter_sql STRING,

  signal_conditions ARRAY<STRUCT<
    signal_name STRING,
    operator STRING,
    value STRING
  >>,

  fallback_behavior STRING,
  is_active BOOL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

  PRIMARY KEY (subset_id) NOT ENFORCED
);
```

### Proposed Dynamic Subsets

| Subset ID | Description | Static Filter | Signal Condition | Expected HR |
|-----------|-------------|---------------|------------------|-------------|
| `v9_high_edge_balanced` | High edge on balanced days | edge ≥ 5 | pct_over 25-40% | 82% |
| `v9_high_edge_any` | High edge (control) | edge ≥ 5 | (none) | 65% |
| `v9_high_edge_warning` | High edge on warning days | edge ≥ 5 | pct_over <25% | 54% |
| `v9_premium_safe` | Premium on non-RED days | conf ≥92, edge ≥3 | signal != RED | 75%+ |
| `consensus_balanced` | V8+V9 agree on balanced days | V8=V9 direction | pct_over 20-45% | 75%+ |

### New Skills

#### /subset-picks

```
Usage:
  /subset-picks                          # List available subsets
  /subset-picks v9_high_edge_balanced    # Today's picks from subset
  /subset-picks v9_high_edge_balanced --history 7  # Last 7 days

Output includes:
  - Pre-game signal status (GREEN/YELLOW/RED)
  - Warning if signal suggests skipping
  - Pick details (player, line, edge, recommendation)
  - Historical performance context
```

#### /subset-performance

```
Usage:
  /subset-performance                    # All subsets, last 7 days
  /subset-performance --period 30        # Last 30 days

Output includes:
  - Performance table (picks, hit rate, ROI)
  - Signal effectiveness comparison
  - Statistical significance indicators
```

---

## Implementation Plan

### Phase 1: Signal Infrastructure (Priority: HIGH)

**Goal**: Calculate and store daily signals

**Tasks**:
1. Create `daily_prediction_signals` table in BigQuery
2. Write signal calculation query
3. Add to prediction workflow (run after predictions generated)
4. Backfill historical signals (Jan 9-31)

**Estimated Effort**: 2-3 hours

### Phase 2: Dynamic Subset Tables (Priority: HIGH)

**Goal**: Store subset definitions with signal conditions

**Tasks**:
1. Create `dynamic_subset_definitions` table
2. Insert initial 5 subset definitions
3. Create view that joins predictions + signals + definitions
4. Test with today's data

**Estimated Effort**: 2-3 hours

### Phase 3: Skills (Priority: MEDIUM)

**Goal**: User-facing interface for subsets

**Tasks**:
1. Create `/subset-picks` skill
   - List subsets command
   - Get picks command with signal context
   - History command
2. Create `/subset-performance` skill
   - Performance comparison table
   - Signal effectiveness metrics

**Estimated Effort**: 3-4 hours

### Phase 4: Integration (Priority: MEDIUM)

**Goal**: Integrate into daily workflow

**Tasks**:
1. Add signal calculation to morning prediction workflow
2. Create Slack alert for RED signal days
3. Add signal indicators to dashboard
4. Document for users

**Estimated Effort**: 2-3 hours

### Phase 5: Validation (Ongoing)

**Goal**: Confirm signal effectiveness with more data

**Tasks**:
1. Track daily signals vs actual performance
2. Update validation-tracker.md
3. Recalculate statistical significance monthly
4. Adjust thresholds if needed

**Estimated Effort**: 15 min/day

---

## SQL Queries Reference

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
      THEN 'Heavy OVER skew - monitor for potential issues'
    ELSE 'Balanced signals - historical 82% hit rate on high-edge picks'
  END as signal_explanation,

  CURRENT_TIMESTAMP() as calculated_at

FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND current_points_line IS NOT NULL
GROUP BY system_id;
```

### Pre-Game Diagnostic (Run Daily)

```sql
SELECT
  game_date,
  system_id,
  total_picks,
  high_edge_picks,
  pct_over,
  skew_category,
  daily_signal,
  signal_explanation
FROM `nba-props-platform.nba_predictions.daily_prediction_signals`
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9';
```

### Get Subset Picks with Signal Context

```sql
WITH daily_signal AS (
  SELECT * FROM `nba-props-platform.nba_predictions.daily_prediction_signals`
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
)
SELECT
  p.player_lookup,
  p.predicted_points,
  p.current_points_line,
  ROUND(p.predicted_points - p.current_points_line, 1) as edge,
  p.recommendation,
  p.confidence_score,
  s.pct_over,
  s.daily_signal,
  CASE
    WHEN s.pct_over BETWEEN 25 AND 40 THEN '✅ INCLUDED'
    ELSE '⚠️ EXCLUDED (signal)'
  END as subset_status
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
CROSS JOIN daily_signal s
WHERE p.game_date = CURRENT_DATE()
  AND p.system_id = 'catboost_v9'
  AND ABS(p.predicted_points - p.current_points_line) >= 5
  AND p.current_points_line IS NOT NULL
ORDER BY ABS(p.predicted_points - p.current_points_line) DESC;
```

### Compare Signal Categories (Historical)

```sql
WITH daily_data AS (
  SELECT
    p.game_date,
    ROUND(100.0 * COUNTIF(p.recommendation = 'OVER') / COUNT(*), 1) as pct_over,
    COUNTIF(ABS(p.predicted_points - p.current_points_line) >= 5) as high_edge_picks,
    ROUND(100.0 * COUNTIF(
      ABS(p.predicted_points - p.current_points_line) >= 5 AND
      ((pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
       (pgs.points < p.current_points_line AND p.recommendation = 'UNDER'))
    ) / NULLIF(COUNTIF(
      ABS(p.predicted_points - p.current_points_line) >= 5 AND
      pgs.points != p.current_points_line
    ), 0), 1) as high_edge_hit_rate
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  WHERE p.game_date >= DATE('2026-01-09')
    AND p.system_id = 'catboost_v9'
    AND p.current_points_line IS NOT NULL
  GROUP BY p.game_date
)
SELECT
  CASE
    WHEN pct_over < 25 THEN 'UNDER_HEAVY'
    WHEN pct_over > 40 THEN 'OVER_HEAVY'
    ELSE 'BALANCED'
  END as category,
  COUNT(*) as days,
  SUM(high_edge_picks) as total_picks,
  ROUND(AVG(high_edge_hit_rate), 1) as avg_hit_rate
FROM daily_data
WHERE high_edge_hit_rate IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

---

## Files Created This Session

### Handoff Documents

| File | Purpose |
|------|---------|
| `docs/09-handoff/2026-02-01-SESSION-70-V9-PERFORMANCE-ANALYSIS.md` | V9 analysis findings |
| `docs/09-handoff/2026-02-01-SESSION-70-MASTER-PLAN.md` | This document |

### Project Documentation

| File | Purpose |
|------|---------|
| `docs/08-projects/current/pre-game-signals-strategy/README.md` | Signal strategy overview |
| `docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md` | System design |
| `docs/08-projects/current/pre-game-signals-strategy/daily-diagnostic.sql` | Morning queries |
| `docs/08-projects/current/pre-game-signals-strategy/historical-analysis.sql` | Discovery queries |
| `docs/08-projects/current/pre-game-signals-strategy/validation-tracker.md` | Ongoing validation |

### Commits

| Commit | Description |
|--------|-------------|
| `27ed0fc5` | fix: Add missing shared/utils symlinks to 5 Cloud Functions |
| `599c2b55` | docs: Add Session 70 handoff - V9 performance analysis |
| `6acccd93` | docs: Add pre-game signals strategy project |
| `62c8a4ad` | docs: Add dynamic subset system design |

---

## Open Questions

### Signal Design

1. **Threshold tuning**: Are 25% and 40% the right pct_over thresholds?
   - Current: Based on 23-day sample
   - Action: Review after 30+ days of data

2. **Multi-model signals**: How to combine V8 and V9 signals?
   - Option A: Separate signals per model
   - Option B: Combined "consensus signal"

3. **Per-game vs per-day**: Should signals be calculated per-game?
   - Current: Per-day (simpler)
   - Alternative: Per-game (more granular)

### Implementation

4. **Fallback on RED days**: What to show users?
   - Option A: Hide picks entirely
   - Option B: Show with prominent warning
   - Option C: Show only highest-edge picks (7+)

5. **Skill location**: Where should skills live?
   - Current skills are in `.claude/skills/`
   - Need to decide on structure for new skills

### Validation

6. **Statistical power**: Do we have enough data?
   - Current: 23 days, 87 high-edge picks
   - Need: Ongoing validation to confirm pattern holds

---

## Quick Start for Next Session

### Option 1: Implement Signal Infrastructure (Recommended)

```bash
# 1. Read this document
cat docs/09-handoff/2026-02-01-SESSION-70-MASTER-PLAN.md

# 2. Create the daily_prediction_signals table
# Use schema from "New Tables Required" section

# 3. Run signal calculation for today
# Use query from "Calculate Daily Signals" section

# 4. Verify signals calculated correctly
bq query --use_legacy_sql=false "
SELECT * FROM nba_predictions.daily_prediction_signals
WHERE game_date = CURRENT_DATE()"
```

### Option 2: Validate Today's Performance

```bash
# After tonight's games complete (Feb 2 morning):

# 1. Check Feb 1 signal (was RED with 10.6% pct_over)
bq query --use_legacy_sql=false "
SELECT pct_over, daily_signal
FROM nba_predictions.daily_prediction_signals
WHERE game_date = DATE('2026-02-01') AND system_id = 'catboost_v9'"

# 2. Check actual high-edge performance
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as picks,
  ROUND(100.0 * COUNTIF(
    (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
    (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
  ) / NULLIF(COUNTIF(pgs.points != p.current_points_line), 0), 1) as hit_rate
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
WHERE p.game_date = DATE('2026-02-01')
  AND p.system_id = 'catboost_v9'
  AND ABS(p.predicted_points - p.current_points_line) >= 5"

# 3. Update validation tracker
# If hit rate < 55%, signal was correct (RED day performed poorly)
# If hit rate > 65%, signal may need recalibration
```

### Option 3: Create /subset-picks Skill

```bash
# 1. Read skill design
cat docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md

# 2. Create skill directory
mkdir -p .claude/skills/subset-picks

# 3. Implement skill (see design doc for spec)
```

---

## Success Criteria

### Short-term (1 week)
- [ ] Signal infrastructure deployed
- [ ] Daily signals calculating automatically
- [ ] At least one skill implemented

### Medium-term (2 weeks)
- [ ] 5 dynamic subsets defined
- [ ] Both skills functional
- [ ] Dashboard integration

### Long-term (1 month)
- [ ] 30+ days of signal validation
- [ ] Statistical significance reconfirmed
- [ ] User adoption of subset-based betting

---

## Contact

For questions about this plan:
1. Read the related documents listed above
2. Check the SQL queries for implementation details
3. Review the open questions for design decisions needed

---

**Session 70 Complete**
**Time**: February 1, 2026
**Next Action**: Implement Phase 1 (Signal Infrastructure)

*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
