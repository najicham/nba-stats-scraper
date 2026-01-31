# Session 48 Handoff - Feature Quality Monitoring & Prevention

**Date:** 2026-01-31
**Focus:** Deploy fatigue fix, implement feature quality monitoring, add pre-write validation
**Status:** Major improvements completed, remaining tasks documented

---

## Executive Summary

Session 48 completed the fatigue_score fix deployment and backfill, then implemented comprehensive feature quality monitoring to prevent similar issues in the future. Key accomplishments:

1. **Deployed Phase 4** with fatigue_score fix and verified via backfill
2. **Fixed Vegas lines query bug** - missing `market_type = 'points'` filter
3. **Created feature health monitoring table** - detects issues within 24 hours
4. **Added pre-write validation** - catches critical bugs at write time
5. **Investigated all broken features** - root causes identified for 6+ features

---

## Fixes Applied

### Fix 1: Phase 4 Deployment & Backfill

**Action:** Deployed Phase 4 processor with fatigue_score fix (commits cec08a99, c475cb9e)

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
# Revision: nba-phase4-precompute-processors-00084-lqh
```

**Backfill:** Reprocessed Jan 25-30 data via Cloud Run endpoint

**Verification:**
```sql
SELECT game_date, ROUND(AVG(fatigue_score), 2) as avg_fatigue,
       COUNTIF(fatigue_score = 0) as zeros
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1;
```

| game_date | avg_fatigue | zeros |
|-----------|-------------|-------|
| 2026-01-25 | 92.66 | 0 |
| 2026-01-26 | 100.0 | 0 |
| 2026-01-27 | 94.4 | 0 |
| 2026-01-28 | 93.52 | 0 |
| 2026-01-29 | 90.61 | 0 |
| 2026-01-30 | 91.16 | 0 |

**Status:** ✅ Fixed and verified

---

### Fix 2: Vegas Lines Query Bug

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py:628`

**Problem:** Query was missing `market_type = 'points'` filter, causing 67-100% zeros for vegas_opening_line and vegas_points_line.

**Before:**
```sql
WHERE game_date = '{game_date}'
  AND bet_side = 'over'
  AND points_line IS NOT NULL
```

**After:**
```sql
WHERE game_date = '{game_date}'
  AND market_type = 'points'
  AND bet_side = 'over'
  AND points_line IS NOT NULL
```

**Context:** This same bug was fixed in Session 36 for other files but was missed in feature_extractor.py:
- `shared_ctes.py:212` - Fixed in Session 36
- `betting_data.py:185` - Fixed in Session 36
- `player_loader.py:710,940` - Fixed in Session 36
- `feature_extractor.py:628` - **Fixed in Session 48**

**Commit:** `0ea398bd`

**Status:** ✅ Fixed, needs deployment

---

### Fix 3: Feature Health Monitoring Table

**Table:** `nba_monitoring_west2.feature_health_daily`

**Purpose:** Track daily feature statistics to detect quality issues within 24 hours instead of 5+ days.

**Schema:**
```sql
CREATE TABLE nba_monitoring_west2.feature_health_daily (
  report_date DATE,
  feature_name STRING,
  source_table STRING,
  mean FLOAT64,
  stddev FLOAT64,
  min_value FLOAT64,
  max_value FLOAT64,
  p5, p25, p50, p75, p95 FLOAT64,
  total_records INT64,
  null_count INT64,
  zero_count INT64,
  negative_count INT64,
  out_of_range_count INT64,
  null_pct FLOAT64,
  zero_pct FLOAT64,
  health_status STRING,  -- 'healthy', 'warning', 'critical'
  alert_reasons ARRAY<STRING>,
  created_at TIMESTAMP
)
PARTITION BY report_date
CLUSTER BY feature_name, source_table
```

**Location:** `schemas/bigquery/monitoring/feature_health_daily.sql`

**Initial Data:** Populated with 7 days of data showing:
- `fatigue_score` - healthy (after backfill)
- `usage_spike_score` - warning (100% zeros - confirms bug)
- `pace_score` - healthy
- `shot_zone_mismatch_score` - healthy

**Query to check health:**
```sql
SELECT report_date, feature_name, ROUND(mean, 2) as mean,
       zero_count, ROUND(zero_pct, 1) as zero_pct, health_status
FROM nba_monitoring_west2.feature_health_daily
ORDER BY report_date DESC, feature_name;
```

**Status:** ✅ Created and populated

---

### Fix 4: Pre-Write Validation

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

**Purpose:** Validate feature values against expected ranges BEFORE writing to BigQuery. This catches bugs at write time instead of waiting for model degradation.

**Implementation:**

1. **ML_FEATURE_RANGES constant** - Maps each of 37 features to (min, max, is_critical, name)
2. **validate_feature_ranges() function** - Checks values and returns warnings/errors
3. **Integration in _process_single_player()** - Blocks writes for critical violations

**Critical Features (block writes if invalid):**
- `fatigue_score` (index 5): Must be 0-100

**Example validation:**
```python
ML_FEATURE_RANGES = {
    5: (0, 100, True, 'fatigue_score'),   # CRITICAL
    6: (-15, 15, False, 'shot_zone_mismatch_score'),
    7: (-8, 8, False, 'pace_score'),
    # ... 37 features total
}
```

**Detection Speed:**
| Method | Detection Time |
|--------|---------------|
| Model degradation | 5-6 days |
| Daily health monitoring | <24 hours |
| Pre-write validation | <1 hour |

**Commit:** `0ea398bd`

**Status:** ✅ Implemented, needs deployment

---

## Root Causes Identified

### Investigation: Other Broken Features

Session 48 used parallel agents to investigate 6+ features with issues:

| Feature | Root Cause | File | Priority |
|---------|-----------|------|----------|
| **vegas_opening_line** | Missing `market_type='points'` filter | feature_extractor.py:628 | FIXED |
| **vegas_points_line** | Same as above | feature_extractor.py:628 | FIXED |
| **usage_spike_score** | `projected_usage_rate = None` (TODO) | context_builder.py:295 | HIGH |
| **team_win_pct** | Not passed to final record | context_builder.py | HIGH |
| **back_to_back** | Upstream data quality issue | TBD | MEDIUM |
| **pace_score** | Depends on team context data | pace_factor.py | MEDIUM |
| **shot_zone_mismatch** | Depends on Phase 4 shot zone data | shot_zone_mismatch.py | MEDIUM |

### Detailed Root Cause: usage_spike_score

**Location:** `data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py:295`

```python
'projected_usage_rate': None,  # TODO: future
```

The feature is hardcoded to None, so usage_spike_factor.py defaults to 25.0 for both projected and baseline, resulting in 0 difference.

### Detailed Root Cause: team_win_pct

The value is calculated in feature_calculator.py but never passed through to the final record in context_builder.py.

---

## Prevention Mechanisms

### Implemented This Session

1. **Pre-Write Validation** (ml_feature_store_processor.py)
   - Validates all 37 features against expected ranges
   - Critical violations block writes
   - Warnings logged but allowed
   - Would have caught fatigue bug in <1 hour

2. **Feature Health Monitoring Table** (nba_monitoring_west2.feature_health_daily)
   - Daily aggregation of feature statistics
   - Tracks zeros, out-of-range, mean drift
   - Health status classification (healthy/warning/critical)
   - Detects issues within 24 hours

3. **Bytecode Cache Validation** (from Session 47)
   - Clears stale .pyc files on import
   - Prevents ProcessPoolExecutor cache issues

### Already Existed (from previous sessions)

4. **Pre-commit schema validation** (.pre-commit-hooks/validate_schema_fields.py)
5. **Feature drift detector** (shared/validation/feature_drift_detector.py) - covers 12 of 37 features
6. **Quality columns** in all Phase 3+ tables

### Still Needed

7. **Scheduled query** for daily feature_health_daily population
8. **Expand drift detector** from 12 to 37 features
9. **Add feature health section** to /validate-daily skill
10. **Pre-commit feature range tests**

---

## Code Changes

| File | Change | Commit |
|------|--------|--------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Fix Vegas query - add market_type filter | 0ea398bd |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Add ML_FEATURE_RANGES and pre-write validation | 0ea398bd |
| `schemas/bigquery/monitoring/feature_health_daily.sql` | New monitoring table schema | 0ea398bd |

---

## Deployments Needed

### Priority 1: Deploy Phase 4 (picks up Vegas query fix)

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

This deploys:
- Vegas lines query fix (market_type filter)
- Pre-write validation for ML feature store

### Priority 2: Set up scheduled query for feature health

Create Cloud Scheduler job to run daily at 6 AM ET:
```sql
-- See schemas/bigquery/monitoring/feature_health_daily.sql for full query
INSERT INTO nba_monitoring_west2.feature_health_daily
SELECT ... FROM nba_precompute.player_composite_factors
WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
```

---

## Known Issues Still to Address

### High Priority

1. **usage_spike_score always 0**
   - Root cause: `projected_usage_rate = None` hardcoded
   - Fix: Implement usage rate calculation in context_builder.py
   - Impact: 1 of 37 features is useless

2. **team_win_pct always 0.5**
   - Root cause: Value not passed to final record
   - Fix: Add to context_builder.py output
   - Impact: 1 of 37 features is useless

### Medium Priority

3. **schedule_context_calculator not integrated**
   - File exists but not called
   - Features like `next_game_days_rest` are hardcoded to 0

4. **Expand drift detector to 37 features**
   - Currently only monitors 12 features
   - Miss coverage for Vegas lines, trajectory features

---

## Queries for Monitoring

### Quick Feature Health Check

```sql
SELECT
  report_date,
  feature_name,
  ROUND(mean, 2) as mean,
  zero_count,
  ROUND(zero_pct, 1) as zero_pct,
  health_status,
  alert_reasons
FROM nba_monitoring_west2.feature_health_daily
WHERE report_date >= CURRENT_DATE() - 3
ORDER BY report_date DESC, feature_name;
```

### Check Vegas Lines After Fix

```sql
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(features[OFFSET(25)] > 0) as has_vegas_line,
  ROUND(100.0 * COUNTIF(features[OFFSET(25)] > 0) / COUNT(*), 1) as pct_with_lines
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1;
```

### Validation Error Tracking

```sql
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(ARRAY_LENGTH(data_quality_issues) > 0) as has_issues,
  COUNTIF(ARRAY_TO_STRING(data_quality_issues, ',') LIKE '%range_warning%') as range_warnings
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1 ORDER BY 1;
```

---

## Next Session Checklist

### Immediate (Required)

- [ ] Deploy Phase 4 to pick up Vegas query fix and pre-write validation
- [ ] Verify Vegas lines are now populated (should be >50% coverage)
- [ ] Set up scheduled query for feature_health_daily

### Short Term

- [ ] Fix usage_spike_score (implement projected_usage_rate)
- [ ] Fix team_win_pct (pass through to final record)
- [ ] Add feature health section to /validate-daily skill

### Medium Term

- [ ] Expand drift detector from 12 to 37 features
- [ ] Create alerting on feature health critical status
- [ ] Integrate schedule_context_calculator

---

## Key Learnings

1. **Query bugs can hide in multiple files** - The market_type filter was fixed in 4 files in Session 36 but missed in feature_extractor.py

2. **Pre-write validation is essential** - Catching bugs at write time (minutes) vs model degradation (days) is a 100x improvement

3. **Monitoring tables enable proactive detection** - The feature_health_daily table immediately showed usage_spike_score is 100% zeros

4. **Hardcoded TODOs are bugs** - `projected_usage_rate = None # TODO: future` has been broken since implementation

5. **Use agents for parallel investigation** - 3 agents simultaneously analyzed ML feature structure, quality patterns, and broken features

---

## Files Reference

| Purpose | Location |
|---------|----------|
| Feature health schema | `schemas/bigquery/monitoring/feature_health_daily.sql` |
| Pre-write validation | `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` |
| Vegas query fix | `data_processors/precompute/ml_feature_store/feature_extractor.py:628` |
| Usage spike TODO | `data_processors/analytics/upcoming_player_game_context/calculators/context_builder.py:295` |
| Drift detector | `shared/validation/feature_drift_detector.py` |

---

## Session Statistics

- **Duration:** ~1 hour
- **Commits:** 1 (0ea398bd)
- **Files Changed:** 3
- **Lines Added:** 324
- **Tables Created:** 1 (feature_health_daily)
- **Bugs Fixed:** 2 (fatigue backfill, Vegas query)
- **Bugs Identified:** 3 more (usage_spike, team_win_pct, schedule_context)

---

*Session 48 complete. Feature quality monitoring infrastructure in place. Deploy Phase 4 to activate pre-write validation.*
