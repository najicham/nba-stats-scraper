# Pipeline Resilience Improvements - January 25, 2026

**Created:** 2026-01-25
**Status:** Implementation in Progress
**Priority:** P0 - Critical Infrastructure

---

## Executive Summary

Deep investigation of the NBA pipeline identified **systemic issues** that caused:
- 45-hour master controller outage (undetected)
- 98% of predictions skipped from grading (has_prop_line bug)
- 9 players/day with props missing predictions (is_production_ready filter)
- Silent failures throughout the pipeline

This document captures root causes, fixes applied, and new resilience patterns.

---

## Root Cause Analysis

### The Pattern: Shortcuts That Become Technical Debt

| Bug | Shortcut Taken | Cost |
|-----|----------------|------|
| `has_prop_line` bug | Derived flag instead of using `line_source` directly | 98% data loss in grading |
| 9 players missing | Binary `is_production_ready` gate | Lost betting opportunities |
| 45-hour outage | "We'll add monitoring later" | Undetected pipeline failure |

### Systemic Issues Identified

1. **Velocity over correctness culture** - Features shipped without validation
2. **Missing design review** - Critical decisions not documented or reviewed
3. **Count-based validation only** - Checked "data exists" not "data is correct"
4. **Monitoring built after critical systems** - No health checks on dependencies
5. **Silent failure patterns** - 7,061 bare `except: pass` statements in codebase

---

## Fixes Applied (This Session)

### 1. has_prop_line Filter Fix

**Files Changed:**
- `bin/validation/comprehensive_health_check.py:418`
- `bin/validation/multi_angle_validator.py:169`

**Change:** Replace `has_prop_line = TRUE` with `line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')`

**Why:** The `has_prop_line` field has data inconsistencies - can be FALSE even when actual prop line exists. Using `line_source` as the authoritative source.

### 2. Players with Props Missing Predictions Fix

**File Changed:** `predictions/coordinator/player_loader.py:307`

**Change:**
```python
# OLD:
AND is_production_ready = TRUE

# NEW:
AND (is_production_ready = TRUE OR has_prop_line = TRUE)
```

**Why:** Players with betting props should get predictions even if historical data is incomplete. Sportsbooks have validated they'll play.

### 3. Schedule Table Reference Fix

**File Changed:** `bin/validation/comprehensive_health_check.py:601`

**Change:** Use `v_nbac_schedule_latest` instead of `nbac_schedule`

**Why:** The view deduplicates and shows current game status accurately.

### 4. Error Handling for Missing Views

**File Changed:** `bin/validation/check_prediction_coverage.py:31-37`

**Change:** Added try-catch with helpful error message if view doesn't exist.

### 5. Phase Transition Monitor (NEW)

**File Created:** `bin/monitoring/phase_transition_monitor.py`

**Purpose:** Real-time monitoring that would have caught the 45-hour outage in <30 minutes.

**Checks:**
- Workflow decision gaps (>2 hours = CRITICAL)
- Phase transition delays (>1 hour = CRITICAL)
- Stuck processors (>4 hours = WARNING)
- Data completeness issues

**Usage:**
```bash
# Single run
python bin/monitoring/phase_transition_monitor.py

# With Slack alerts
python bin/monitoring/phase_transition_monitor.py --alert

# Continuous mode (every 10 min)
python bin/monitoring/phase_transition_monitor.py --continuous --alert
```

---

## New Validation Angles (15 Discovered)

### Critical Priority (Implement First)

#### 1. Late Predictions Detection
Predictions made AFTER game start = invalid betting edge.
```sql
SELECT p.game_date, p.player_lookup,
  TIMESTAMP_DIFF(p.prediction_time, s.game_date_est, MINUTE) as minutes_after_start
FROM nba_predictions.player_prop_predictions p
JOIN nba_raw.v_nbac_schedule_latest s ON p.game_id = s.game_id
WHERE TIMESTAMP_DIFF(p.prediction_time, s.game_date_est, MINUTE) >= 0
```

#### 2. Critical NULL Fields
Fields that should never be NULL but might be due to ETL breaks.
```sql
SELECT game_date, COUNT(*) as null_points
FROM nba_analytics.player_game_summary
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND is_active = TRUE AND points IS NULL
GROUP BY game_date
```

#### 3. Grading Lag Bottleneck
Identify which phase is causing grading delays.
```sql
-- Track timing through Phase 2→3→4→5
-- See which transition takes longest
```

### High Priority (Implement This Week)

#### 4. Source Data Hash Drift
Phase 3 analytics have data_hash fields - detect when source changed but analytics not reprocessed.

#### 5. Void Rate Anomaly
Sudden spike in voided predictions = injury detection breaking.

#### 6. Prediction System Consistency
If xgboost predicts 500 players but catboost predicts 100, something broke.

#### 7. Source Completeness Regression
Track when data sources drop in quality over time.

#### 8. Denormalized Field Drift
Team/opponent in analytics should match schedule - detect mismatches.

### Medium Priority (Implement This Month)

#### 9. Multi-Pass Processing Incompleteness
player_game_summary uses 3-pass processing - detect games stuck in Pass 1 or 2.

#### 10. Cardinality Mismatch Across Tables
Games in schedule should = games in boxscores should = games in analytics.

#### 11. Precompute Cache Staleness
Detect when cache is used after games finish (stale data in predictions).

#### 12. Registry Stale Mappings
Players in predictions not found in registry = outdated player data.

#### 13. Line Movement Sanity
Extreme unexplained line movements = sportsbook data quality issues.

#### 14. Coverage Gaps by Archetype
Certain player types (bench, rotation) might be systematically excluded.

#### 15. Feature Quality Regression
Sudden drop in feature_quality_score = data pipeline issue.

---

## Resilience Patterns: What Exists vs What's Missing

### Strong Patterns (Already Implemented)

| Pattern | Location | Status |
|---------|----------|--------|
| Retry with jitter | `shared/utils/retry_with_jitter.py` | Excellent |
| BigQuery retries | `shared/utils/bigquery_retry.py` | Excellent |
| Circuit breakers | `shared/utils/external_service_circuit_breaker.py` | Good |
| Fallback chains | `FallbackSourceMixin` | Good |
| Error classification | `shared/utils/result.py` | Good |

### Critical Gaps (Need Implementation)

| Gap | Impact | Priority |
|-----|--------|----------|
| 7,061 bare `except: pass` | Silent failures | P0 |
| No idempotency keys | Duplicate processing | P1 |
| No dead-letter queue | Failed jobs disappear | P1 |
| Phase 4→5 has no data validation | Predictions on bad data | P0 |
| Batch processors not in Sentry | Errors not captured | P0 |
| No phase transition alerts | 45-hour outage undetected | P0 (FIXED) |

---

## Observability Gaps

### What Would Have Caught the 45-Hour Outage

| Check | Status Before | Status After |
|-------|--------------|--------------|
| Workflow decision gap alert | Missing | **ADDED** (phase_transition_monitor.py) |
| Phase transition deadline alert | Missing | **ADDED** |
| Real-time completeness monitoring | Missing | Partial |
| Batch processor Sentry | Missing | TODO |
| Pipeline health dashboard | Missing | TODO |

### Recommended Monitoring Stack

1. **Every 10 minutes:** `phase_transition_monitor.py --alert`
2. **Every hour:** `comprehensive_health_check.py --alert`
3. **Every day:** `daily_summary/main.py` (existing)
4. **On-demand:** `multi_angle_validator.py`

---

## Phase Transition Failure Modes

### Phase 2→3: HIGHEST RISK

**Problem:** No blocking validation. Proceeds after 30-min deadline even with partial data.

**Current Behavior:**
- Phase 2 completes with 3/6 processors
- 30-minute deadline hits
- Phase 3 triggers with incomplete upstream data
- Analytics compute with 0 box scores → NULL results
- Cascades to Phases 4, 5, 6

**Fix Needed:** Require critical processors (bdl_box_scores, schedule, gamebook) before proceeding.

### Phase 4→5: HIGH RISK

**Problem:** No data validation at all.

**Current Behavior:**
- Uses tiered timeout (triggers eventually)
- No check if ml_feature_store exists
- No check if feature counts match expectations
- Predictions may run with NULL features

**Fix Needed:** Add R-008 equivalent validation before triggering predictions.

---

## Data Quality Gaps

### Missing Checks

1. **Per-field null rate monitoring** - Currently only checks average
2. **Statistical outlier detection** - No Z-score, IQR, MAD
3. **Cross-field validation** - FG_MAKES should be <= FG_ATTEMPTS
4. **Data age per entity** - No per-player staleness tracking
5. **Schema change detection** - No structural validation
6. **Duplicate detection** - No check for duplicate game+player rows

---

## Implementation Priority

### Immediate (This Week)

1. ✅ Fix has_prop_line filters in validation scripts
2. ✅ Fix player_loader to include players with props
3. ✅ Create phase transition monitor
4. ⬜ Deploy phase_transition_monitor to Cloud Scheduler (every 10 min)
5. ⬜ Add Sentry to batch processors

### Short-term (Next 2 Weeks)

6. ⬜ Add R-008 validation to Phase 4→5 transition
7. ⬜ Implement late predictions detection
8. ⬜ Implement critical NULL field checks
9. ⬜ Add cross-field validation rules
10. ⬜ Audit and fix bare `except: pass` statements

### Medium-term (Next Month)

11. ⬜ Implement idempotency keys
12. ⬜ Add dead-letter queue for failed processors
13. ⬜ Build pipeline health dashboard
14. ⬜ Add all 15 new validation angles
15. ⬜ Implement statistical outlier detection

---

## Key Design Principles Going Forward

1. **Use authoritative sources** - Never derive flags when source field exists
2. **Validate before proceeding** - Every phase transition needs data quality gate
3. **Monitor first, feature second** - Add health checks before deploying
4. **Fail loudly** - Remove silent exception handlers
5. **Degrade gracefully** - Use partial data with quality flags, don't block entirely
6. **Multiple validation angles** - Each angle catches different failures

---

## Files Changed This Session

| File | Change |
|------|--------|
| `bin/validation/comprehensive_health_check.py` | Fixed has_prop_line filter, schedule table reference |
| `bin/validation/multi_angle_validator.py` | Fixed has_prop_line filter |
| `predictions/coordinator/player_loader.py` | Allow players with props to bypass production_ready |
| `bin/validation/check_prediction_coverage.py` | Added error handling |
| `bin/monitoring/phase_transition_monitor.py` | NEW - Real-time phase transition alerting |
| `docs/08-projects/current/pipeline-resilience-improvements/RESILIENCE-IMPROVEMENTS-JAN25.md` | This document |

---

## Quick Commands Reference

```bash
# Phase transition monitoring (would have caught 45h outage)
python bin/monitoring/phase_transition_monitor.py --alert

# Comprehensive health check
python bin/validation/comprehensive_health_check.py --date 2026-01-24

# Multi-angle validation
python bin/validation/multi_angle_validator.py --days 7

# Data completeness
python bin/validation/daily_data_completeness.py --days 7

# Prediction coverage
python bin/validation/check_prediction_coverage.py --weeks 12

# Orchestration state check
python bin/monitoring/check_orchestration_state.py 2026-01-24
```

---

**End of Document**
