# Backfill Failure Analysis - December 4, 2025

**Date:** 2025-12-04
**Author:** Claude Code Session 16
**Status:** Analysis Complete, Recommendations Pending Implementation

---

## Executive Summary

During the Phase 4 backfill for November 2021, multiple failures occurred due to:
1. **Missing Phase 3 data** - `player_game_summary` has gaps for 6 dates
2. **Continue-on-failure behavior** - Backfills proceed to next date after failures
3. **No pre-flight validation enforced** - Validation scripts exist but weren't used

**Impact:** Some Phase 4 data was generated with incomplete upstream data, and some dates have no data at all.

---

## Root Cause Analysis

### 1. The Gap Analysis (Current State)

```
| target_date | pgs | upgc | utgc | togs | tdgs | psza | tdza | pcf | pdc | mlfs |
|-------------|-----|------|------|------|------|------|------|-----|-----|------|
| 2021-11-15  | 241 |  389 |   22 |   88 |   88 |  272 |   30 | 389 | 202 |  389 | ✓ Complete
| 2021-11-16  |   0 |  105 |    6 |    0 |    0 |  272 |   30 |   0 |  54 |    0 | ✗ Phase 3 missing
| 2021-11-17  | 232 |  382 |   22 |    0 |    0 |  280 |   30 | 382 | 207 |  382 | ✓ Working
| 2021-11-18  |   0 |  212 |   12 |    0 |    0 |  280 |   30 | 212 | 110 |  212 | ✗ Phase 3 missing
| 2021-11-19  | 190 |  314 |   18 |    0 |    0 |  289 |   30 | 314 | 177 |  314 | ✓ Working
| 2021-11-20  | 203 |  312 |   18 |    0 |    0 |  294 |   30 | 312 | 181 |  312 | ✓ Working
| 2021-11-21  |   0 |  179 |   10 |    0 |    0 |  294 |   30 | 179 |  95 |    0 | ✗ Phase 3 missing
| 2021-11-22  | 225 |  346 |   20 |    0 |    0 |  303 |   30 | 346 | 207 |  346 | ✓ Working
| 2021-11-23  |   0 |  141 |    8 |    0 |    0 |  303 |   30 |   0 |  75 |    0 | ✗ Phase 3 missing
| 2021-11-24  | 276 |  450 |   26 |    0 |    0 |  313 |   30 | 450 | 276 |    0 | ⚠ MLFS pending
| 2021-11-25  |   0 |    0 |    0 |    0 |    0 |  313 |   30 |   0 |   0 |    0 | (No games - Thanksgiving)
| 2021-11-26  | 269 |  418 |   24 |    0 |    0 |  316 |   30 | 418 | 253 |    0 | ⚠ MLFS pending
| 2021-11-27  | 161 |  289 |   16 |    0 |    0 |  322 |   30 | 289 | 171 |    0 | ⚠ MLFS pending
| 2021-11-28  |   0 |  169 |   10 |    0 |    0 |  322 |   30 | 169 | 107 |    0 | ✗ Phase 3 missing
| 2021-11-29  | 201 |  325 |   18 |    0 |    0 |  325 |   29 |   0 |   0 |    0 | ✗ pcf/pdc missing
| 2021-11-30  |   0 |  179 |   10 |    0 |    0 |  325 |   29 |   0 |   0 |    0 | ✗ Phase 3 missing
```

**Legend:**
- `pgs` = player_game_summary (Phase 3)
- `upgc` = upcoming_player_game_context (Phase 3)
- `utgc` = upcoming_team_game_context (Phase 3)
- `togs` = team_offense_game_summary (Phase 3)
- `tdgs` = team_defense_game_summary (Phase 3)
- `psza` = player_shot_zone_analysis (Phase 4)
- `tdza` = team_defense_zone_analysis (Phase 4)
- `pcf` = player_composite_factors (Phase 4)
- `pdc` = player_daily_cache (Phase 4)
- `mlfs` = ml_feature_store_v2 (Phase 4)

### 2. Raw Data Verification

Phase 2 raw data is COMPLETE for all dates:

```
| game_date  | num_games | records |
|------------|-----------|---------|
| 2021-11-15 |        11 |      44 |
| 2021-11-16 |         3 |      12 |
| 2021-11-17 |        11 |      40 |
| 2021-11-18 |         6 |      22 |
| 2021-11-19 |         9 |      36 |
| 2021-11-20 |         9 |      36 |
| 2021-11-21 |         5 |      20 |
| 2021-11-22 |        10 |      40 |
| 2021-11-23 |         4 |      14 |
| 2021-11-24 |        13 |      52 |
| 2021-11-26 |        12 |      46 |
| 2021-11-27 |         8 |      32 |
| 2021-11-28 |         5 |      20 |
| 2021-11-29 |         9 |      36 |
| 2021-11-30 |         5 |      20 |
```

**Conclusion:** Raw data exists for all dates. The Phase 3 `player_game_summary` backfill failed to process certain dates.

### 3. Why Phase 3 Has Gaps

The `player_game_summary` backfill ran but failed on certain dates. Possible causes:
1. Transient errors (BigQuery quota, network issues)
2. Data quality issues on those specific dates
3. Unknown processor bugs

The backfill script continues to the next date on failure (see code analysis below).

### 4. team_offense_game_summary / team_defense_game_summary EMPTY

These tables have only Nov 15 data (88 rows each). This is a MAJOR gap - these Phase 3 tables were never properly backfilled.

---

## Code Analysis: Continue-on-Failure Behavior

### Current Backfill Script Behavior (player_composite_factors_precompute_backfill.py:214-226)

```python
if result['status'] == 'success':
    successful_days += 1
    # ... mark checkpoint complete
elif result['status'] == 'skipped_bootstrap':
    skipped_days += 1
    # ... mark checkpoint skipped
else:
    failed_days.append(current_date)
    logger.error(f"  ✗ Failed: {result.get('error', 'Unknown')}")
    # ... mark checkpoint failed

processed_days += 1

# ALWAYS moves to next date regardless of failure!
current_date += timedelta(days=1)
```

**Key Issue:** There is no `--stop-on-failure` flag. Backfills always continue to the next date.

### Implications

1. **For Independent Data (Phase 3):** Continuing after failure is usually OK - each day is independent.
2. **For Dependent Data (Phase 4):** Continuing can produce:
   - **Hard failures:** When critical dependencies are missing (e.g., Nov 16 ml_feature_store)
   - **Degraded quality:** When historical data is incomplete (e.g., rolling averages based on partial data)

---

## Data Integrity Check: Dates After Failures

### Question: Do dates that ran after a failure have incomplete data?

**Analysis for Phase 4:**

| Date | Phase 3 Available? | Phase 4 Outcome |
|------|-------------------|-----------------|
| Nov 17 | Yes (232 pgs) | pcf=382, mlfs=382 ✓ Valid |
| Nov 18 | No (0 pgs) | pcf=212 from upgc only ⚠ Partial |
| Nov 19 | Yes (190 pgs) | pcf=314, mlfs=314 ✓ Valid |
| Nov 20 | Yes (203 pgs) | pcf=312, mlfs=312 ✓ Valid |
| Nov 21 | No (0 pgs) | pcf=179 from upgc only, mlfs=0 ⚠ Partial/Missing |
| Nov 22 | Yes (225 pgs) | pcf=346, mlfs=346 ✓ Valid |
| Nov 23 | No (0 pgs) | pcf=0, mlfs=0 ✗ Missing |

**Conclusion:** Some dates (Nov 18, 21) have **partial data** generated from `upcoming_player_game_context` alone, without historical `player_game_summary` data. This means:
- Features like rolling averages may be missing or incorrect
- The data exists but is DEGRADED quality

---

## Existing Validation Scripts

### bin/backfill/verify_phase3_for_phase4.py

Already exists and checks all 5 Phase 3 tables for coverage. Could be integrated as a pre-flight check.

```bash
# Example usage
python bin/backfill/verify_phase3_for_phase4.py --start-date 2021-11-15 --end-date 2021-11-30 --verbose
```

### bin/backfill/preflight_check.py

Comprehensive check of all phases (GCS, Phase 2, Phase 3, Phase 4). Shows coverage percentages.

### Integration Gap

These scripts exist but are **not enforced** before running backfills. They're manual tools.

---

## Recommendations

### Short-Term (Immediate)

1. **Re-run Phase 3 player_game_summary backfill for missing dates:**
   ```bash
   python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
     --dates 2021-11-16,2021-11-18,2021-11-21,2021-11-23,2021-11-28,2021-11-30
   ```

2. **Run team_offense_game_summary and team_defense_game_summary backfills:**
   ```bash
   python backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
     --start-date 2021-11-15 --end-date 2021-11-30

   python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
     --start-date 2021-11-15 --end-date 2021-11-30
   ```

3. **Re-run ml_feature_store for fixed Phase 3 dates:**
   ```bash
   python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
     --dates 2021-11-16,2021-11-18,2021-11-21,2021-11-23
   ```

### Medium-Term (This Week)

4. **Add `--stop-on-failure` flag to backfill scripts:**
   ```python
   parser.add_argument('--stop-on-failure', action='store_true',
                       help='Stop processing if any date fails')
   ```

5. **Add pre-flight validation to backfill scripts:**
   ```python
   if not args.skip_preflight:
       result = verify_phase3_for_phase4(start_date, end_date)
       if not result['all_ready']:
           logger.error("Phase 3 not ready. Use --skip-preflight to override.")
           sys.exit(1)
   ```

6. **Create unified gap detection script:**
   ```bash
   python bin/backfill/check_all_gaps.py --start-date 2021-11-15 --end-date 2021-11-30
   ```

### Long-Term (Future)

7. **Add backfill status tracking table:**
   ```sql
   CREATE TABLE nba_reference.backfill_status (
     processor STRING,
     target_date DATE,
     status STRING,  -- 'pending', 'running', 'success', 'failed', 'skipped'
     error_message STRING,
     started_at TIMESTAMP,
     completed_at TIMESTAMP,
     rows_written INT64
   );
   ```

8. **Orchestrated backfill runner** that enforces dependency order

---

## Commands for Verification

### Check current gaps
```bash
# Full gap analysis
bq query --use_legacy_sql=false "
WITH dates AS (
  SELECT DATE '2021-11-15' + INTERVAL d DAY as target_date
  FROM UNNEST(GENERATE_ARRAY(0, 15)) as d
)
SELECT
  d.target_date,
  (SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = d.target_date) as pgs,
  (SELECT COUNT(*) FROM nba_precompute.player_composite_factors WHERE game_date = d.target_date) as pcf,
  (SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = d.target_date) as mlfs
FROM dates d
ORDER BY d.target_date
"
```

### Run pre-flight check
```bash
python bin/backfill/verify_phase3_for_phase4.py \
  --start-date 2021-11-15 --end-date 2021-11-30 --verbose
```

---

## Appendix: File References

| File | Description |
|------|-------------|
| `bin/backfill/verify_phase3_for_phase4.py` | Phase 3 coverage checker |
| `bin/backfill/preflight_check.py` | Full phase coverage checker |
| `backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py` | Phase 3 backfill |
| `backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py` | Phase 4 backfill |
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | ML feature store backfill |
