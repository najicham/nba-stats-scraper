# Prioritization Framework

## Overview

Not all data gaps are equally important to fix. This document defines how to prioritize backfill work based on impact, recency, and business value.

## Priority Tiers

### P0: Critical (Fix Immediately)

**Criteria:**
- Recent gaps (< 14 days old)
- Phase 2 gaps (cascade to all downstream)
- Active prediction period affected
- Grading blocked for recent games

**Examples:**
- Missing boxscores for last week's games
- Phase 2 gap affecting today's predictions
- Grading incomplete for games with active bets

**SLA:** Fix within 24 hours

### P1: High (Fix This Week)

**Criteria:**
- Gaps 14-30 days old
- Phase 3-4 gaps with high cascade impact (>15 downstream dates)
- Quality degradation affecting recent predictions
- Multiple consecutive gap dates

**Examples:**
- Week-long Phase 3 gap from 3 weeks ago
- ML features showing all-bronze quality for recent period
- Prediction coverage dropped significantly

**SLA:** Fix within 7 days

### P2: Medium (Fix This Sprint)

**Criteria:**
- Gaps 30-60 days old
- Phase 4-5 gaps with moderate cascade impact
- Quality warnings (not failures)
- Non-consecutive isolated gaps

**Examples:**
- Single-day Phase 4 gap from 6 weeks ago
- Silver-tier quality (not bronze) for historical period
- Grading 50-80% complete for older games

**SLA:** Fix within 2 weeks

### P3: Low (Fix When Convenient)

**Criteria:**
- Gaps > 60 days old
- Phase 5-6 only gaps (no cascade impact)
- Bootstrap period exceptions
- Historical data with limited business value

**Examples:**
- Early season (Oct-Nov 2024) quality issues
- Grading incomplete for games > 90 days old
- Historical predictions that won't be graded

**SLA:** Fix within 30 days or defer

## Priority Score Calculation

### Formula

```
Priority Score = (Recency × 0.35) + (Cascade × 0.30) + (Phase × 0.20) + (Quality × 0.15)
```

### Component Scores

**Recency Score (0-1):**
| Days Old | Score |
|----------|-------|
| 0-7 | 1.0 |
| 8-14 | 0.9 |
| 15-30 | 0.7 |
| 31-60 | 0.4 |
| 61-90 | 0.2 |
| 90+ | 0.1 |

**Cascade Impact Score (0-1):**
| Downstream Dates Affected | Score |
|--------------------------|-------|
| 20+ | 1.0 |
| 15-19 | 0.8 |
| 10-14 | 0.6 |
| 5-9 | 0.4 |
| 1-4 | 0.2 |
| 0 | 0.0 |

**Phase Severity Score (0-1):**
| Phase | Score | Rationale |
|-------|-------|-----------|
| Phase 2 | 1.0 | Blocks everything downstream |
| Phase 3 | 0.8 | Blocks features and predictions |
| Phase 4 | 0.6 | Blocks predictions |
| Phase 5 | 0.3 | Affects grading only |
| Phase 6 | 0.1 | Terminal - no cascade |

**Quality Impact Score (0-1):**
| Issue Type | Score |
|-----------|-------|
| Complete failure (0 records) | 1.0 |
| Critical failure (< 50% expected) | 0.8 |
| Warning (50-80% expected) | 0.5 |
| Minor (80-95% expected) | 0.2 |
| Acceptable (> 95%) | 0.0 |

### Example Calculations

**Example 1: Recent Phase 2 Gap**
```
Gap: 2025-01-20 (5 days ago)
Phase: Phase 2
Cascade: 18 downstream dates
Quality: 0 records

Recency: 1.0 (5 days)
Cascade: 0.8 (18 dates)
Phase: 1.0 (Phase 2)
Quality: 1.0 (0 records)

Score = (1.0 × 0.35) + (0.8 × 0.30) + (1.0 × 0.20) + (1.0 × 0.15)
      = 0.35 + 0.24 + 0.20 + 0.15
      = 0.94 → P0
```

**Example 2: Old Phase 4 Gap**
```
Gap: 2024-11-15 (70+ days ago)
Phase: Phase 4
Cascade: 8 downstream dates
Quality: 30% of expected

Recency: 0.2 (70 days)
Cascade: 0.4 (8 dates)
Phase: 0.6 (Phase 4)
Quality: 0.8 (30%)

Score = (0.2 × 0.35) + (0.4 × 0.30) + (0.6 × 0.20) + (0.8 × 0.15)
      = 0.07 + 0.12 + 0.12 + 0.12
      = 0.43 → P2
```

**Example 3: Bootstrap Period**
```
Gap: 2024-10-25 (bootstrap period)
Phase: Phase 4
Cascade: 15 dates
Quality: 50% bronze tier

Special handling: Bootstrap period
Automatically downgrade to P3 regardless of score
```

## Priority Tier Mapping

| Score Range | Priority Tier |
|-------------|---------------|
| 0.80 - 1.00 | P0 (Critical) |
| 0.60 - 0.79 | P1 (High) |
| 0.40 - 0.59 | P2 (Medium) |
| 0.00 - 0.39 | P3 (Low) |

## Special Rules

### Automatic P0 Triggers

These conditions always result in P0 priority:
1. Phase 2 gap within last 7 days
2. Any gap affecting today's predictions
3. Cascade affecting > 25 dates
4. System-wide outage (multiple phases affected)

### Automatic Downgrade to P3

These conditions cap priority at P3:
1. Bootstrap period (Oct 22 - Nov 5, 2024)
2. All-Star break period (Feb 14-17, 2025)
3. Offseason dates
4. Gaps > 120 days old with < 5 cascade impact

### Priority Escalation

Gaps escalate priority if:
1. Unfixed after SLA (P2 → P1 after 2 weeks)
2. Multiple related gaps compound
3. Business-critical period (playoffs, finals)

## Backfill Order Within Priority

Within each priority tier, order backfills by:

1. **Oldest first within phase** - Clear cascade debt
2. **Phase 2 before Phase 3** - Fix root causes
3. **Consecutive dates together** - Efficient batching
4. **High cascade first** - Maximum impact

### Optimal Backfill Sequence

```
P0 Gaps:
  1. All Phase 2 gaps (oldest → newest)
  2. All Phase 3 gaps (oldest → newest)
  3. All Phase 4 gaps (dependency order)
  4. Phase 5-6 gaps

P1 Gaps:
  [Same pattern]

P2 Gaps:
  [Same pattern]

P3 Gaps:
  [Batch by month, run during off-peak]
```

## Cost-Benefit Considerations

### Backfill Cost Factors

| Factor | Impact |
|--------|--------|
| BigQuery processing | ~$0.05-0.20 per date per phase |
| Compute time | ~5-15 minutes per date per phase |
| API calls (if re-scraping) | Rate limits apply |
| Human attention | Monitoring, verification |

### Value Factors

| Factor | Value Signal |
|--------|--------------|
| Prediction grading possible | High (model improvement) |
| Recent predictions affected | High (user trust) |
| Historical analysis value | Medium |
| Completeness for reporting | Low-Medium |

### Skip Criteria

Consider NOT backfilling if:
1. Gap > 180 days AND cascade impact = 0
2. No predictions exist for grading
3. Cost exceeds value (very old historical data)
4. Data source no longer available

## Decision Matrix

| Scenario | Priority | Action |
|----------|----------|--------|
| Recent Phase 2 gap | P0 | Immediate backfill |
| Recent Phase 3-4 quality warning | P1 | Schedule this week |
| Old Phase 2 gap with high cascade | P1 | Schedule this week |
| Old Phase 4 gap, low cascade | P2-P3 | Batch with similar |
| Bootstrap period gaps | P3 | Accept or batch |
| Phase 6 only gaps | P2-P3 | Low priority |
| Playoff period gaps | P0-P1 | Escalate |

## Implementation

### SQL Query for Priority Assignment

```sql
-- Assign priority scores and tiers
SELECT
  game_date,
  phase,
  days_old,
  cascade_impact_count,
  quality_status,
  -- Calculate component scores
  CASE
    WHEN days_old <= 7 THEN 1.0
    WHEN days_old <= 14 THEN 0.9
    WHEN days_old <= 30 THEN 0.7
    WHEN days_old <= 60 THEN 0.4
    WHEN days_old <= 90 THEN 0.2
    ELSE 0.1
  END as recency_score,
  CASE
    WHEN cascade_impact_count >= 20 THEN 1.0
    WHEN cascade_impact_count >= 15 THEN 0.8
    WHEN cascade_impact_count >= 10 THEN 0.6
    WHEN cascade_impact_count >= 5 THEN 0.4
    ELSE 0.2
  END as cascade_score,
  CASE phase
    WHEN 'phase2' THEN 1.0
    WHEN 'phase3' THEN 0.8
    WHEN 'phase4' THEN 0.6
    WHEN 'phase5' THEN 0.3
    ELSE 0.1
  END as phase_score,
  CASE quality_status
    WHEN 'FAIL' THEN 1.0
    WHEN 'CRITICAL' THEN 0.8
    WHEN 'WARN' THEN 0.5
    ELSE 0.2
  END as quality_score,
  -- Calculate total and assign tier
  (recency_score * 0.35 + cascade_score * 0.30 + phase_score * 0.20 + quality_score * 0.15) as priority_score,
  CASE
    WHEN (recency_score * 0.35 + cascade_score * 0.30 + phase_score * 0.20 + quality_score * 0.15) >= 0.80 THEN 'P0'
    WHEN (recency_score * 0.35 + cascade_score * 0.30 + phase_score * 0.20 + quality_score * 0.15) >= 0.60 THEN 'P1'
    WHEN (recency_score * 0.35 + cascade_score * 0.30 + phase_score * 0.20 + quality_score * 0.15) >= 0.40 THEN 'P2'
    ELSE 'P3'
  END as priority_tier
FROM gap_analysis
-- Apply special rules
WHERE NOT (
  -- Bootstrap period
  game_date BETWEEN '2024-10-22' AND '2024-11-05'
  -- All-Star break
  OR game_date BETWEEN '2025-02-14' AND '2025-02-17'
)
ORDER BY priority_score DESC, game_date;
```

## Reporting

### Weekly Priority Report

Generate weekly to track backfill progress:

```
=== Weekly Backfill Priority Report ===
Week of: 2026-01-20

P0 (Critical): 2 dates
  - 2026-01-18 (Phase 2, 18 cascade)
  - 2026-01-19 (Phase 2, 16 cascade)

P1 (High): 8 dates
  - 2025-12-28 to 2025-12-31 (Phase 3, 12 cascade avg)
  - 2026-01-05 (Phase 4, quality warning)
  [...]

P2 (Medium): 15 dates
  [...]

P3 (Low): 42 dates
  [...]

Completed This Week: 12 dates
Remaining: 67 dates
Estimated Completion: 2-3 weeks
```

## Summary

The prioritization framework ensures:
1. **Critical gaps fixed first** - Recent, high-cascade issues
2. **Efficient resource use** - Batch similar work
3. **Business value focus** - Prioritize actionable data
4. **Clear SLAs** - Accountability for resolution
5. **Flexibility** - Escalation and special rules
