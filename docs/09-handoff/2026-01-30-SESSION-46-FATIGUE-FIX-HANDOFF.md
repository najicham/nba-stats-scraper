# Session 46 Handoff - Fatigue Score Fix & Feature Quality Monitoring

**Date:** 2026-01-30
**Duration:** ~60 minutes
**Focus:** Fix fatigue score backfill, investigate parallel processing bug, design feature quality monitoring

---

## Executive Summary

This session:
1. Ran daily validation - found model performance degradation (50% hit rate, -0.96 Vegas edge)
2. Fixed schedule table references (`nba_reference.nba_schedule` not `nba_schedule.nba_schedule`)
3. Attempted fatigue score backfill - **discovered ProcessPoolExecutor bug**
4. Successfully backfilled using serial processing
5. Launched investigation into feature quality monitoring

---

## Critical Finding: Parallel Processing Bug

### The Issue

The fatigue score backfill produced incorrect values (0) when using ProcessPoolExecutor, but correct values (100) when using serial processing.

**Evidence:**
- Parallel run: `fatigue_score = 0`, but `JSON_VALUE(fatigue_context_json, '$.final_score') = 100`
- Serial run: `fatigue_score = 100` (correct)

### Root Cause (Suspected)

ProcessPoolExecutor spawns new Python processes that may:
1. Load cached `.pyc` files with old code
2. Have module import issues in worker processes
3. Have a serialization/deserialization issue with the record dict

### Workaround Applied

Set environment variable to force serial processing:
```bash
ENABLE_PLAYER_PARALLELIZATION=false python backfill_jobs/...
```

### Backfill Status

| Date | Status | Method |
|------|--------|--------|
| 2026-01-30 | ✅ Done | Serial |
| 2026-01-25 | 🏃 Running | Serial (in background) |
| 2026-01-26 | 🏃 Running | Serial |
| 2026-01-27 | 🏃 Running | Serial |
| 2026-01-28 | 🏃 Running | Serial |

**Check progress:**
```bash
tail -f /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/bf4e4fd.output
```

**After composite factors complete, run ML feature store backfill:**
```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py --dates="2026-01-25,2026-01-26,2026-01-27,2026-01-28,2026-01-30"
```

---

## Schedule Table Fix

### Problem

Validation queries failed because of wrong table references.

### Fix Applied

| File | Change |
|------|--------|
| `backfill_jobs/scrapers/bp_props/deploy.sh` | `nba_raw.nba_schedule` → `nba_reference.nba_schedule` |
| `docs/08-projects/current/nba-backfill-2021-2026/CURRENT-STATUS.md` | `nba_orchestration.nba_schedule` → `nba_reference.nba_schedule` |
| `CLAUDE.md` | Added schedule data reference section |

### Correct Usage

```sql
-- Use this:
FROM nba_reference.nba_schedule
-- Columns: game_id, game_date, home_team_tricode, away_team_tricode, game_status
```

---

## Feature Quality Investigation Findings

Three exploration agents analyzed the codebase for similar bugs and improvement opportunities.

### Similar Bugs Found

| Feature | Issue | Severity | Status |
|---------|-------|----------|--------|
| `fatigue_score` | Stored adjustment instead of raw score | CRITICAL | FIXED (cec08a99, c475cb9e) |
| `shot_zone_mismatch_score` | Correct range but semantic mismatch | MEDIUM | N/A |
| `pace_score` | Already-scaled adjustment stored | MEDIUM | N/A |
| `usage_spike_score` | Already-scaled adjustment stored | MEDIUM | N/A |

### Existing Validation Patterns

The codebase has good validation infrastructure:
- `shared/utils/phase_validation.py` - Phase boundary validation
- `shared/validation/feature_drift_detector.py` - Drift detection (12 features monitored)
- `predictions/worker/data_loaders.py` - ML feature validation
- Pre-commit schema validation

### Critical Gaps

1. **No real-time feature range monitoring** - Would have caught fatigue bug immediately
2. **Only 12 of 37 features monitored for drift**
3. **No early warning for gradual quality degradation**
4. **Missing correlation checks between related features**

### Recommended Improvements

**P1: Add Feature Range Validation Before Write**
```python
# Add to worker.py (already added in c475cb9e)
FEATURE_RANGES = {
    'fatigue_score': (0, 100),
    'shot_zone_mismatch_score': (-15, 15),
    ...
}

def _validate_feature_ranges(record):
    for feature, (min_val, max_val) in FEATURE_RANGES.items():
        value = record.get(feature)
        if value < min_val or value > max_val:
            logger.error(f"FEATURE_RANGE_VIOLATION: {feature}={value}")
```

**P2: Build Feature Quality Dashboard**
- Track distribution stats over time
- Alert on 2-sigma deviations from baseline
- Monitor all 37 ML features

**P3: Add Correlation Validation**
- `minutes_avg` should correlate with `games_played`
- `fatigue_score` should correlate with `days_rest`

---

## Model Performance Status

**CRITICAL:** Model performance degraded significantly.

| Week | Hit Rate | Vegas Edge | Status |
|------|----------|------------|--------|
| Jan 25 | 50.6% | -0.23 | 🔴 |
| Jan 18 | 51.6% | +0.72 | 🔴 |
| Jan 11 | 51.1% | -0.53 | 🔴 |
| Jan 04 | 62.7% | -0.08 | ✅ |

**Tier Breakdown (Last 2 Weeks):**
| Tier | Hit Rate | Bias |
|------|----------|------|
| Stars (25+) | 36.4% | -10.05 (under-predicting) |
| Starters (15-25) | 51.7% | -2.11 |
| Rotation (5-15) | 55.2% | +1.27 |
| Bench (<5) | 49.4% | +6.20 (over-predicting) |

**Vegas Edge: -0.96** (Vegas is now more accurate than our model)

---

## Next Session Checklist

### Immediate

1. **Verify backfill completed:**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT game_date, AVG(fatigue_score) as avg, COUNTIF(fatigue_score > 0) as correct
   FROM nba_precompute.player_composite_factors
   WHERE game_date >= '2026-01-25'
   GROUP BY 1 ORDER BY 1"
   ```

2. **Run ML feature store backfill** (if composite factors done):
   ```bash
   PYTHONPATH=/home/naji/code/nba-stats-scraper python \
     backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
     --dates="2026-01-25,2026-01-26,2026-01-27,2026-01-28,2026-01-30"
   ```

3. **Verify ML feature store has correct fatigue:**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT game_date, AVG(fatigue_score) as avg
   FROM nba_predictions.ml_feature_store_v2
   WHERE game_date >= '2026-01-25'
   GROUP BY 1 ORDER BY 1"
   ```

### Short-Term

4. **Investigate parallel processing bug:**
   - Check if `.pyc` caching is the issue
   - Verify worker imports correctly in subprocess
   - Consider switching to ThreadPoolExecutor

5. **Deploy Phase 4 with parallelization fix or disabled:**
   ```bash
   # Option 1: Disable parallelization in production
   # Set ENABLE_PLAYER_PARALLELIZATION=false in Cloud Run env vars

   # Option 2: Fix the bug and redeploy
   ./bin/deploy-service.sh nba-phase4-precompute-processors
   ```

### Medium-Term

6. **Implement feature quality monitoring:**
   - Add real-time range validation alerts
   - Build feature quality dashboard
   - Expand drift monitoring to all 37 features

7. **Address model degradation:**
   - Review CatBoost V11 experiment results
   - Consider recency weighting in training
   - Add player trajectory features

---

## Files Modified This Session

| File | Change |
|------|--------|
| `CLAUDE.md` | Added Schedule Data Reference section |
| `backfill_jobs/scrapers/bp_props/deploy.sh` | Fixed schedule table reference |
| `docs/08-projects/current/nba-backfill-2021-2026/CURRENT-STATUS.md` | Fixed schedule table reference |

---

## Key Commands

```bash
# Check fatigue score status
bq query --use_legacy_sql=false "
SELECT game_date, AVG(fatigue_score) as avg_fatigue
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2026-01-25'
GROUP BY 1 ORDER BY 1"

# Run serial backfill (workaround for parallel bug)
ENABLE_PLAYER_PARALLELIZATION=false PYTHONPATH=/home/naji/code/nba-stats-scraper python \
  backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --dates="2026-01-30"

# Check backfill progress
tail -f /tmp/claude-1000/-home-naji-code-nba-stats-scraper/tasks/bf4e4fd.output

# Schedule table queries
bq query --use_legacy_sql=false "
SELECT game_id, game_date, home_team_tricode, away_team_tricode
FROM nba_reference.nba_schedule
WHERE game_date = CURRENT_DATE()"
```

---

## Lessons Learned

1. **ProcessPoolExecutor can have code caching issues** - Always verify worker code matches main process
2. **Pre-write validation catches bugs early** - The FEATURE_RANGES validation added in c475cb9e would have caught this
3. **JSON storage provides debugging trail** - `fatigue_context_json` showed correct value even when column was wrong
4. **Serial fallback is valuable** - Having `ENABLE_PLAYER_PARALLELIZATION=false` option saved the backfill

---

*Session 46 Handoff - 2026-01-30*
*Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>*
