# Session 45 Handoff - Feature Quality Investigation & Prevention

**Date:** 2026-01-30
**Duration:** ~1 hour (continuation of Session 44)
**Focus:** Deep root cause analysis, additional bug discovery, prevention mechanisms

---

## Executive Summary

Session 45 continued the fatigue bug investigation and discovered:

1. **worker.py was STILL BROKEN** - The processor was fixed but the multiprocessing worker module wasn't
2. **6 other features have issues** - team_win_pct, back_to_back, usage_spike_score, vegas lines, etc.
3. **Added pre-write validation** - New code will catch future bugs immediately
4. **Comprehensive documentation** - Full analysis of how to prevent this pattern

---

## Critical Discoveries

### Discovery 1: Worker Module Still Had Bug

The previous fix (commit cec08a99) only fixed `player_composite_factors_processor.py` but NOT `worker.py` which is used for multiprocessing.

**File:** `data_processors/precompute/player_composite_factors/worker.py`

```python
# BEFORE (still broken):
'fatigue_score': int(factor_scores['fatigue_score']),  # Returns -5 to 0!

# AFTER (fixed):
'fatigue_score': factor_contexts['fatigue_context_json']['final_score'],  # Returns 0-100
```

**Commit:** `c475cb9e`

### Discovery 2: Multiple Features Have Issues

Investigation of ml_feature_store_v2 found 6+ features with problems:

| Feature | Issue | Impact |
|---------|-------|--------|
| **fatigue_score** | 65% zeros since Jan 25 | CRITICAL |
| **vegas_opening_line** | 67-100% zeros Jan 30-31 | HIGH |
| **vegas_points_line** | 67-100% zeros Jan 30-31 | HIGH |
| **team_win_pct** | Always 0.5, no variance | MEDIUM |
| **back_to_back** | Always 0 | MEDIUM |
| **usage_spike_score** | Always 0 | LOW |
| **pace_score** | 100% zeros some days | MEDIUM |
| **shot_zone_mismatch_score** | 100% zeros some days | MEDIUM |

### Discovery 3: Validation Exists But Runs Too Late

The system has validation but it's POST-storage:
- Range validation in `data_loaders.py` - at prediction time
- Validators in `validation/validators/` - after data is in BigQuery
- No pre-write validation to reject bad data

---

## Fixes Applied This Session

### Fix 1: worker.py Fatigue Bug
```python
# Line 115 - Warning check fix
fatigue_score = factor_contexts['fatigue_context_json']['final_score']

# Line 139 - Record creation fix
'fatigue_score': factor_contexts['fatigue_context_json']['final_score'],
```

### Fix 2: Pre-Write Validation Added
```python
# New FEATURE_RANGES constant
FEATURE_RANGES = {
    'fatigue_score': (0, 100),
    'shot_zone_mismatch_score': (-15, 15),
    'pace_score': (-8, 8),
    'usage_spike_score': (-8, 8),
    ...
}

# New _validate_feature_ranges() function
def _validate_feature_ranges(record: dict) -> list:
    """Validate all features before writing to BigQuery."""
    violations = []
    for feature, (min_val, max_val) in FEATURE_RANGES.items():
        value = record.get(feature)
        if value is not None and (value < min_val or value > max_val):
            violations.append(f"CRITICAL:{feature}={value} outside [{min_val}, {max_val}]")
    return violations
```

This validation:
- Runs BEFORE every write
- Logs CRITICAL errors for violations
- Adds violations to `data_quality_issues` array
- Would have caught fatigue bug immediately

---

## Code Changes Made

| File | Change | Commit |
|------|--------|--------|
| `data_processors/precompute/player_composite_factors/worker.py` | Fix fatigue_score, add validation | `c475cb9e` |

---

## Deployments Needed

### Priority 1: Deploy Phase 4 (Required Before Next Game Day)

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

This deploys both the processor fix (cec08a99) AND the worker fix (c475cb9e).

### Priority 2: Backfill Affected Data

After deployment:

```bash
# Backfill player_composite_factors for Jan 25-30
PYTHONPATH=/home/naji/code/nba-stats-scraper python backfill_jobs/precompute/player_composite_factors/backfill.py --start-date 2026-01-25 --end-date 2026-01-30
```

### Verification Query

After backfill, verify fix worked:

```sql
SELECT
  game_date,
  ROUND(AVG(fatigue_score), 2) as avg_fatigue,
  COUNTIF(fatigue_score = 0) as zeros,
  COUNTIF(fatigue_score < 0) as negatives
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1;
-- Expected: avg_fatigue ~90-100, zeros ~0, negatives = 0
```

---

## Documentation Created

| File | Description |
|------|-------------|
| `docs/08-projects/current/2026-01-30-session-44-maintenance/FEATURE-QUALITY-COMPREHENSIVE-ANALYSIS.md` | Full investigation report |
| `docs/09-handoff/2026-01-30-SESSION-45-FEATURE-QUALITY-HANDOFF.md` | This handoff |

---

## Prevention Mechanisms Implemented

### Implemented This Session

1. **Pre-Write Validation** in worker.py
   - Validates all features against expected ranges
   - Logs CRITICAL errors for violations
   - Adds violations to data_quality_issues

### Still Needed (Future Sessions)

2. **Daily Feature Health Table**
   - Create `nba_monitoring.feature_health_daily`
   - Scheduled query to populate daily
   - Track mean, zeros, negatives for each feature

3. **Enhanced /validate-daily Skill**
   - Add feature health section
   - Show zero counts and range violations
   - Alert on anomalies

4. **Pre-Commit Feature Tests**
   - Run processor on test data
   - Assert output ranges
   - Catch bugs before commit

---

## Root Cause Analysis: Why This Keeps Happening

### Pattern

1. Refactor changes return value semantics
2. Consumer code isn't updated
3. No range validation catches the bug
4. Goes unnoticed until predictions degrade
5. Hours of investigation to find

### Contributing Factors

1. **Two code paths** - processor.py AND worker.py both need updating
2. **No type enforcement** - Python doesn't enforce return types
3. **Silent failures** - Wrong values aren't errors
4. **Delayed detection** - Validation is post-storage

### Solution Layers

1. **Pre-write validation** (implemented) - Catch at write time
2. **Daily monitoring** (needed) - Catch within 24 hours
3. **Pre-commit tests** (needed) - Catch before commit
4. **Clear contracts** (needed) - Document expected ranges

---

## Next Session Checklist

### Immediate (Required)

- [ ] Deploy Phase 4 processor: `./bin/deploy-service.sh nba-phase4-precompute-processors`
- [ ] Run backfill for Jan 25-30
- [ ] Verify fatigue_score is now correct (avg ~90-100)

### Short Term (This Week)

- [ ] Investigate other broken features (team_win_pct, back_to_back, vegas lines)
- [ ] Create feature_health_daily table
- [ ] Add feature health to /validate-daily skill

### Medium Term

- [ ] Add pre-commit feature range tests
- [ ] Create alerting on feature anomalies
- [ ] Document expected ranges for all features

---

## Queries for Monitoring

### Quick Feature Health Check

```sql
SELECT
  'fatigue_score' as feature,
  ROUND(AVG(fatigue_score), 2) as mean,
  ROUND(100.0 * COUNTIF(fatigue_score = 0) / COUNT(*), 1) as pct_zeros,
  COUNTIF(fatigue_score < 0) as negatives
FROM nba_precompute.player_composite_factors
WHERE game_date >= CURRENT_DATE() - 7
UNION ALL
SELECT
  'team_win_pct',
  ROUND(AVG(team_win_pct), 2),
  ROUND(100.0 * COUNTIF(team_win_pct = 0.5) / COUNT(*), 1),
  0
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7;
```

### Predictions with Quality Issues

```sql
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNTIF(completeness_percentage < 90) as low_completeness,
  COUNTIF(ARRAY_LENGTH(data_quality_issues) > 0) as has_issues
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-01-25'
GROUP BY game_date
ORDER BY game_date;
```

---

## Key Learnings

1. **Multiprocessing adds complexity** - Worker module is separate from processor
2. **Refactors need full audit** - All consumers of changed code must be checked
3. **Validation before storage** - Pre-write validation is essential
4. **Monitor features, not just predictions** - Input quality drives output quality

---

## System Status at Session End

| Component | Status |
|-----------|--------|
| Pipeline | ✅ Healthy |
| Scrapers | ✅ Fixed & deployed |
| Phase 4 Processor | ⚠️ Fix committed (cec08a99 + c475cb9e), needs deployment |
| Feature Quality | ⚠️ Broken since Jan 25, fix pending deployment |
| Pre-write Validation | ✅ Implemented |

---

*Session 45 complete. Worker.py bug found and fixed. Pre-write validation added. Deploy and backfill required.*
