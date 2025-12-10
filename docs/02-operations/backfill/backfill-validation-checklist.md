# Backfill Validation Checklist

**Version:** 1.0
**Last Updated:** 2025-12-10
**Purpose:** Comprehensive checklist for validating backfill data quality after running any Phase 4 or Phase 5 backfill.

---

## Quick Reference - Critical Checks

Run these immediately after any backfill:

```bash
# 1. Run validation script
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date START --end-date END --details

# 2. Check for duplicates
bq query --use_legacy_sql=false "SELECT 'Predictions' as t, COUNT(*) as total, COUNT(DISTINCT CONCAT(game_date,'|',player_lookup,'|',system_id)) as uniq FROM nba_predictions.player_prop_predictions"

# 3. Check for NULL critical fields
bq query --use_legacy_sql=false "SELECT COUNTIF(game_id IS NULL) as null_game_id, COUNTIF(player_lookup IS NULL) as null_player FROM nba_predictions.player_prop_predictions"
```

---

## Part 1: Pre-Backfill Checks

### 1.1 Verify Upstream Data Exists
Before running any processor, verify its dependencies:

| Processor | Dependencies | Check Query |
|-----------|--------------|-------------|
| TDZA | player_game_summary | `SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = 'YYYY-MM-DD'` |
| PSZA | player_game_summary | Same as TDZA |
| PCF | TDZA, PSZA | Check both tables have records for date |
| PDC | player_game_summary | Same as TDZA |
| MLFS | PCF, PDC | Check both tables have records for date |
| Phase 5 | MLFS (50+ records) | `SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = 'YYYY-MM-DD'` |

### 1.2 Verify Season Bootstrap Period
For early season dates, check if date is in bootstrap:

```bash
python3 -c "
from datetime import date
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
d = date(2021, 11, 1)  # Change this
season = get_season_year_from_date(d)
print(f'{d}: early_season={is_early_season(d, season)}')"
```

**Bootstrap periods by season:**
- 2021-22: Oct 19 - Nov 1 (days 0-13)
- 2022-23: Oct 18 - Oct 31 (days 0-13)
- 2023-24: Oct 24 - Nov 6 (days 0-13)
- 2024-25: Oct 22 - Nov 4 (days 0-13)

### 1.3 Check Idempotency
Verify the backfill script has idempotency (pre-delete or MERGE):

- **Phase 4 processors**: Use MERGE pattern (check `_save_results()` method)
- **Phase 5 predictions**: Should have pre-delete (check `write_predictions_to_bq()`)

---

## Part 2: Post-Backfill Validation

### 2.1 Coverage Validation

#### Run the Validation Script
```bash
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date START --end-date END --details
```

**Status Codes to Watch:**
| Status | Meaning | Action Required |
|--------|---------|-----------------|
| OK | Records present | None |
| Skipped | Expected failures (bootstrap, insufficient data) | None - expected |
| DepsMiss | Upstream missing | Run upstream processor first |
| **Untracked** | No records AND no failure records | **INVESTIGATE** |
| **Investigate** | Processing errors | **FIX AND RERUN** |

#### Check Row Counts by Date
```sql
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as players
FROM [processor_table]
WHERE game_date >= 'START' AND game_date <= 'END'
GROUP BY game_date
ORDER BY game_date;
```

Expected player counts per date (rough guidelines):
- Low game days (1-3 games): 20-60 players
- Medium (4-7 games): 80-150 players
- High (8-12 games): 150-250 players
- Full slate (12+ games): 250-400+ players

### 2.2 Data Integrity Checks

#### Check for Duplicates
```sql
-- Phase 4 processors (example for PCF)
SELECT game_date, player_lookup, COUNT(*) as dup_count
FROM nba_precompute.player_composite_factors
WHERE game_date >= 'START' AND game_date <= 'END'
GROUP BY game_date, player_lookup
HAVING COUNT(*) > 1;

-- Phase 5 predictions
SELECT game_date, player_lookup, system_id, COUNT(*) as dup_count
FROM nba_predictions.player_prop_predictions
WHERE game_date >= 'START' AND game_date <= 'END'
GROUP BY game_date, player_lookup, system_id
HAVING COUNT(*) > 1;
```

**Expected result:** 0 rows (no duplicates)

#### Check for NULL Critical Fields
```sql
-- Phase 5 predictions
SELECT
  COUNTIF(game_id IS NULL) as null_game_id,
  COUNTIF(player_lookup IS NULL OR player_lookup = '') as null_player,
  COUNTIF(system_id IS NULL OR system_id = '') as null_system,
  COUNTIF(predicted_points IS NULL) as null_predicted
FROM nba_predictions.player_prop_predictions
WHERE game_date >= 'START' AND game_date <= 'END';
```

**Expected result:** All zeros

### 2.3 Data Quality Checks

#### Value Range Validation
```sql
-- Prediction quality checks
SELECT
  COUNT(*) as total,
  COUNTIF(predicted_points < 0) as negative_points,
  COUNTIF(predicted_points > 60) as over_60_points,
  COUNTIF(confidence_score < 0 OR confidence_score > 1) as bad_confidence,
  MIN(predicted_points) as min_predicted,
  MAX(predicted_points) as max_predicted,
  AVG(predicted_points) as avg_predicted
FROM nba_predictions.player_prop_predictions
WHERE game_date >= 'START' AND game_date <= 'END';

-- PCF quality checks
SELECT
  COUNTIF(overall_composite < 0.1) as very_low_composite,
  COUNTIF(overall_composite > 2.0) as very_high_composite,
  AVG(overall_composite) as avg_composite
FROM nba_precompute.player_composite_factors
WHERE game_date >= 'START' AND game_date <= 'END';
```

#### Prediction Accuracy Check (for dates with actuals)
```sql
SELECT
  p.system_id,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(p.predicted_points - pgs.points)), 2) as mae,
  ROUND(AVG(p.predicted_points - pgs.points), 2) as mean_bias
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.game_date = pgs.game_date AND p.player_lookup = pgs.player_lookup
WHERE p.game_date >= 'START' AND p.game_date <= 'END'
GROUP BY p.system_id
ORDER BY mae;
```

**Expected MAE:** 4-6 points (anything over 8 needs investigation)

### 2.4 Gap Analysis

#### Find Missing Dates
```sql
WITH expected AS (
  SELECT DISTINCT game_date
  FROM nba_analytics.player_game_summary
  WHERE game_date >= 'START' AND game_date <= 'END'
),
actual AS (
  SELECT DISTINCT game_date
  FROM [processor_table]
  WHERE game_date >= 'START' AND game_date <= 'END'
)
SELECT e.game_date as missing_date
FROM expected e
LEFT JOIN actual a ON e.game_date = a.game_date
WHERE a.game_date IS NULL
ORDER BY missing_date;
```

#### Find Missing Players per Date
```sql
SELECT
  pgs.game_date,
  COUNT(DISTINCT pgs.player_lookup) as expected,
  COUNT(DISTINCT p.player_lookup) as actual,
  COUNT(DISTINCT pgs.player_lookup) - COUNT(DISTINCT p.player_lookup) as missing
FROM nba_analytics.player_game_summary pgs
LEFT JOIN [processor_table] p
  ON pgs.game_date = p.game_date AND pgs.player_lookup = p.player_lookup
WHERE pgs.game_date >= 'START' AND pgs.game_date <= 'END'
  AND pgs.minutes_played > 10  -- Only players who played significant minutes
GROUP BY pgs.game_date
HAVING COUNT(DISTINCT pgs.player_lookup) - COUNT(DISTINCT p.player_lookup) > 0
ORDER BY game_date;
```

---

## Part 3: Failure Record Analysis

### 3.1 Check Failure Categories
```sql
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count
FROM nba_processing.precompute_failures
WHERE analysis_date >= 'START' AND analysis_date <= 'END'
GROUP BY processor_name, failure_category
ORDER BY processor_name, count DESC;
```

### 3.2 Expected vs Unexpected Failures

**Expected (not errors):**
- `EXPECTED_INCOMPLETE` - Player hasn't played enough games (bootstrap)
- `INSUFFICIENT_DATA` - Not enough game history for lookback
- `MISSING_DEPENDENCIES` - Upstream not ready (date-level)
- `NO_SHOT_ZONE` - No shot data for player

**Needs Investigation:**
- `INCOMPLETE_UPSTREAM` - Player has games but missing upstream (needs backfill)
- `PROCESSING_ERROR` - Actual error during processing
- `calculation_error` - Code error (check if data exists despite error)

### 3.3 Check for Stale Failure Records
```sql
-- Failures where data actually exists (stale records)
SELECT
  f.analysis_date,
  f.failure_category,
  COUNT(f.entity_id) as failures,
  COUNT(p.player_lookup) as actual_records
FROM nba_processing.precompute_failures f
LEFT JOIN nba_precompute.player_composite_factors p
  ON f.analysis_date = p.game_date AND f.entity_id = p.player_lookup
WHERE f.processor_name = 'PlayerCompositeFactorsProcessor'
  AND f.analysis_date >= 'START' AND f.analysis_date <= 'END'
GROUP BY f.analysis_date, f.failure_category
HAVING COUNT(p.player_lookup) > 0;  -- Has records despite failures
```

---

## Part 4: Name Resolution Checks

### 4.1 Check Name Resolution Log
```sql
SELECT
  game_date,
  resolution_status,
  COUNT(*) as count
FROM nba_processing.name_resolution_log
WHERE game_date >= 'START' AND game_date <= 'END'
GROUP BY game_date, resolution_status
ORDER BY game_date;
```

### 4.2 Check Player Name Collisions
```sql
SELECT *
FROM nba_processing.player_name_collisions
WHERE detected_date >= 'START' AND detected_date <= 'END';
```

---

## Part 5: Performance Monitoring

### 5.1 Check Log Files
```bash
# Look at backfill logs
grep -E "(SUMMARY|Complete|error|failed|skip|duration)" /tmp/[processor]_*.log | tail -50

# Check for slow dates (took > 60 seconds)
grep -E "took [0-9]{2,}s" /tmp/[processor]_*.log
```

### 5.2 Check Processor Run Records
```sql
SELECT
  processor_name,
  run_date,
  success,
  TIMESTAMP_DIFF(completed_at, started_at, SECOND) as duration_seconds
FROM nba_processing.precompute_processor_runs
WHERE run_date >= 'START' AND run_date <= 'END'
ORDER BY run_date, processor_name;
```

---

## Part 6: Downstream Impact Analysis

### 6.1 Check if Gaps Affected Downstream
For Phase 4 gaps, check if they impacted Phase 5:

```sql
-- Dates with Phase 4 gaps but Phase 5 predictions exist
SELECT DISTINCT p.game_date
FROM nba_predictions.player_prop_predictions p
WHERE p.game_date >= 'START' AND p.game_date <= 'END'
  AND NOT EXISTS (
    SELECT 1 FROM nba_predictions.ml_feature_store_v2 m
    WHERE m.game_date = p.game_date
  );
```

### 6.2 Validate Prediction Dependencies Met
```sql
-- Check predictions were only generated when MLFS >= 50
SELECT
  p.game_date,
  COUNT(DISTINCT p.player_lookup) as predictions,
  m.mlfs_count
FROM nba_predictions.player_prop_predictions p
JOIN (
  SELECT game_date, COUNT(*) as mlfs_count
  FROM nba_predictions.ml_feature_store_v2
  GROUP BY game_date
) m ON p.game_date = m.game_date
WHERE p.game_date >= 'START' AND p.game_date <= 'END'
GROUP BY p.game_date, m.mlfs_count
HAVING m.mlfs_count < 50;  -- Should return 0 rows
```

---

## Part 7: Special Scenarios

### 7.1 COVID Protocol Dates (2021-22 Season)
Many games postponed Dec 2021 - Jan 2022. Expect:
- Fewer games per date
- Some dates with very few or no games
- Players on health protocols missing from data

### 7.2 Early Season Bootstrap
PSZA requires 10 games per player. Even after system bootstrap (day 14), individual players may not have 10 games yet.

**Expected pattern:**
- Day 14-17: ~0-50 PSZA records
- Day 18-21: ~50-100 PSZA records
- Day 22+: Normal coverage

### 7.3 Trade Deadline / All-Star Break
Players traded mid-season may have gaps. All-Star break (usually mid-February) has no games.

---

## Appendix: Known Issues and Workarounds

### Issue 1: Phase 5 Duplicates
**Symptom:** 49% duplicate predictions
**Cause:** Script used insert_rows_json() without pre-delete
**Fix:** Added idempotency (commit b7507cc)
**Prevention:** Always use pre-delete or MERGE pattern

### Issue 2: NULL game_id in Predictions
**Symptom:** All predictions missing game_id
**Cause:** game_id wasn't included in write function
**Fix:** Added game_id to query and write (commit b7507cc)
**Prevention:** Always include game_id in prediction writes

### Issue 3: Stale Failure Records
**Symptom:** "Investigate" status despite data existing
**Cause:** Initial failed run created failures, successful re-run didn't clean them
**Fix:** Manual DELETE of stale failures
**Prevention:** Add cleanup step after successful backfill

### Issue 4: PSZA UNTRACKED Nov 2-4
**Symptom:** PSZA shows UNTRACKED for Nov 2-4, 2021
**Cause:** PSZA requires 10 games per player; 0 players had 10 games by Nov 2
**Resolution:** Expected behavior - not a bug. Players accumulated games by Nov 5.

### Issue 5: Bad Confidence Scores
**Symptom:** 40 predictions with confidence > 1.0 (values like 52.0, 84.0)
**Cause:** Scale mismatch between daily worker and backfill:
- Daily worker uses `normalize_confidence()` which outputs 0-100 scale
- Backfill script stores raw confidence (0-1 scale) directly
- The 40 bad records are from 2025-11-25 daily run, NOT backfill
**Root Cause:** `predictions/worker/worker.py:872` calls `normalize_confidence()` which multiplies by 100
**Fix:** Need to decide on canonical scale:
- Option A: Fix daily worker to store 0-1 (match backfill)
- Option B: Fix backfill to normalize to 0-100 (match daily worker)
**Status:** NOT YET FIXED - need to align all writers on same scale

---

## Checklist Template

Copy this for each backfill run:

```
## Backfill Validation: [DATE_RANGE]

### Pre-Backfill
- [ ] Verified upstream data exists
- [ ] Checked bootstrap period
- [ ] Confirmed idempotency in script

### Coverage
- [ ] Ran validation script
- [ ] Checked status codes (no UNTRACKED/Investigate)
- [ ] Verified row counts reasonable

### Data Integrity
- [ ] No duplicates found
- [ ] No NULL critical fields
- [ ] Value ranges reasonable

### Quality
- [ ] Prediction accuracy acceptable (MAE < 6)
- [ ] No data anomalies

### Gaps
- [ ] No missing dates
- [ ] Missing players explained (bootstrap/failures)

### Failures
- [ ] Failure categories expected
- [ ] No stale failure records

### Downstream
- [ ] Phase 5 not impacted by Phase 4 gaps
- [ ] Dependency thresholds met

### Notes:
[Any special observations]
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-10 | Initial version based on Session 104 learnings |
