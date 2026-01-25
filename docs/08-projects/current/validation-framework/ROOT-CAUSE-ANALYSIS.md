# Root Cause Analysis: Pipeline Issues Jan 23-25, 2026

**Date:** 2026-01-25
**Analyst:** Claude
**Status:** Complete

---

## Executive Summary

A **single Firestore permission failure** created a **cascading quality degradation** that affected all downstream predictions. The issue was hidden because existing validations only checked record counts, not data quality.

---

## Issue Chain

```
1. Firestore 403 Error
   └── Master Controller blocked for 45.2 hours
       └── No workflow decisions made
           └── No Phase 2 processors triggered
               └── No new boxscores collected (except bdl_live)
                   └── No Phase 3 analytics updated
                       └── Rolling window calculations become stale
                           └── Feature quality scores drop (75→64)
                               └── More players filtered out
                                   └── Prediction coverage drops (282→85)
                                       └── Grading has nothing to grade
```

---

## Detailed Findings

### 1. Workflow Decision Gap

| Metric | Value |
|--------|-------|
| Last decision before outage | Jan 23, 04:20 PST |
| First decision after fix | Jan 25, 01:35 PST |
| Total gap | **45.2 hours** |

**Impact:** Zero workflows ran for nearly 2 days.

### 2. Feature Quality Degradation

| Date | Avg Quality | Low Quality Count | Trend |
|------|-------------|-------------------|-------|
| Jan 20 | 78.96 | 4 | Baseline |
| Jan 21 | 76.71 | 1 | Good |
| Jan 22 | 75.49 | 25 | Slight drop |
| Jan 23 | **69.07** | **65** | Significant drop |
| Jan 24 | **64.43** | **135** | Major degradation |

**Root cause:** Rolling window calculations (L7D, L14D) became incomplete because no new game data was being processed.

### 3. Team Context Quality

Sample from Jan 24 team contexts:
```
quality_tier: poor
quality_score: 25.0
is_production_ready: false
l7d_completeness_pct: 25-50%
l14d_completeness_pct: 33-40%
data_quality_issues: ["l7d_incomplete:25%", "l14d_incomplete:33%"]
```

**Impact:** Teams with poor context quality cascade to poor player features.

### 4. Prediction Coverage Drop

| Date | BDL Players | Feature Players | Predicted Players | Coverage |
|------|-------------|-----------------|-------------------|----------|
| Jan 20 | 140 | 220 | 81 | 58% |
| Jan 21 | 247 | 224 | 52 | 21% |
| Jan 22 | 282 | 283 | 88 | 31% |
| Jan 23 | 281 | 281 | 85 | **30%** |
| Jan 24 | 209 | 181 | 65 | **31%** |

**Note:** Even before the outage, prediction coverage was only 30-58% of boxscore players. This is partly by design (feature quality threshold) but amplified by the outage.

### 5. Grading Lag

| Date | Predictions | Graded | Coverage |
|------|-------------|--------|----------|
| Jan 20 | 156 | 87 | 56% |
| Jan 21 | 52 | 42 | 81% |
| Jan 22 | 88 | 82 | 93% |
| Jan 23 | 85 | **4** | **5%** |
| Jan 24 | 65 | 0 | 0% |

**Root cause:** TWO issues compounding:
1. Phase 2 blocked → actuals weren't updated
2. **Data Bug:** `has_prop_line` flag incorrectly set

### 6. has_prop_line Data Bug (CRITICAL)

The grading processor filters on `has_prop_line = TRUE`, but most predictions have this flag incorrectly set:

```
| has_prop_line | line_source   | count |
|---------------|---------------|-------|
| false         | ACTUAL_PROP   |   218 |  <-- WRONG: should be TRUE
| false         | ESTIMATED_AVG |   369 |
| false         | NO_PROP_LINE  |    13 |
| true          | ACTUAL_PROP   |     4 |  <-- Only these get graded
```

**Impact:** 218 predictions with real prop lines are NOT being graded because `has_prop_line=false`.

**Fix options:**
1. Fix prediction generator to correctly set `has_prop_line` based on `line_source`
2. Update grading processor to grade all `ACTUAL_PROP` predictions regardless of flag
3. Backfill: Update historical `has_prop_line` flags where `line_source='ACTUAL_PROP'`

---

## Why Existing Validation Missed This

### Current Validation Gaps

| What We Check | What We Missed |
|---------------|----------------|
| Record counts | Quality scores |
| Table existence | Rolling window completeness |
| Game-level coverage | Player-level filtering |
| Final output | Intermediate quality degradation |

### The Hidden Failure Mode

The system continued producing *some* output during the outage:
- `bdl_live_boxscores` kept running (has dedicated scheduler)
- Old predictions remained in the database
- Feature store had entries (just poor quality)

So count-based validation showed "data exists" when the data was actually degraded.

---

## Recommendations

### 1. Quality-Based Validation (Not Just Counts)

```sql
-- Instead of: COUNT(*) > 0
-- Use: AVG(quality_score) > 70 AND COUNTIF(quality_score < 65) < 10%
```

### 2. Workflow Decision Monitoring

Alert if no decisions made in > 2 hours during business hours.

### 3. Rolling Window Completeness

Check that L7D and L14D completeness stays above 80%.

### 4. Prediction Funnel Monitoring

Track drop-off at each stage:
- Boxscore players → Feature players (should be ~100%)
- Feature players → High-quality features (should be >80%)
- High-quality → Predicted (should be >90% of those with props)

### 5. Cross-Phase Timing Validation

Alert if Phase N+1 doesn't start within X minutes of Phase N completion.

---

## Validation Improvements Needed

| Validation | Current | Improved |
|------------|---------|----------|
| Data completeness | Count > 0 | Count matches expected AND quality > threshold |
| Feature quality | Not checked | Avg > 70, low_quality < 10% |
| Prediction coverage | Count only | Funnel analysis with expected conversion rates |
| Grading lag | Count only | Compare to actionable predictions from 24h ago |
| Workflow health | Not checked | Decision gap monitoring |
| Rolling windows | Not checked | L7D/L14D completeness > 80% |

---

## Implementation Priority

1. **P0 (Immediate):** Workflow decision gap alert
2. **P0 (Immediate):** Feature quality monitoring
3. **P1 (This week):** Prediction funnel validation
4. **P1 (This week):** Rolling window completeness
5. **P2 (Next week):** Cross-phase timing validation
