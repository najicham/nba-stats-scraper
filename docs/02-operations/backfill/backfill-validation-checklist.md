# Backfill Validation Checklist

**Version:** 1.5
**Last Updated:** 2025-12-10
**Purpose:** Comprehensive checklist for validating backfill data quality **before, during, and after** running Phase 4 or Phase 5 backfills.

---

## Table of Contents

| Section | Description | When to Use |
|---------|-------------|-------------|
| [Quick Reference](#quick-reference---critical-checks) | Copy-paste commands | During & after backfill |
| [STOP Thresholds](#-stop-and-investigate-thresholds) | When to halt | During backfill |
| [Part 0: Real-Time Monitoring](#part-0-real-time-monitoring-during-backfill) | Live monitoring | During backfill |
| [Part 1: Pre-Backfill](#part-1-pre-backfill-checks) | Readiness checks | Before starting |
| [Part 2: Post-Backfill Validation](#part-2-post-backfill-validation) | Coverage & integrity | After Phase 4 |
| [Part 3: Failure Analysis](#part-3-failure-record-analysis) | Debug failures | After any issues |
| [Part 4: Name Resolution](#part-4-name-resolution-checks) | Player name issues | If missing players |
| [Part 5: Performance](#part-5-performance-monitoring) | Speed issues | If running slow |
| [Part 6: Downstream Impact](#part-6-downstream-impact-analysis) | Phase 4→5 cascade | After Phase 4 |
| **[Part 7: Phase 5 Predictions](#part-7-phase-5-predictions-validation)** | **Prediction checks** | **After Phase 5** |
| [Part 8: Special Scenarios](#part-8-special-scenarios) | Edge cases | Reference |
| [Part 9: Advanced Checks](#part-9-advanced-validation-checks) | Deep validation | Post-backfill |
| [Part 10: 2021-22 Season](#part-10-2021-22-season-backfill-reference) | Season-specific | 2021 backfill |
| [Appendix: Known Issues](#appendix-known-issues-and-workarounds) | Past problems | Reference |
| [Checklist Template](#checklist-template) | Copy for each run | Every backfill |

---

## Quick Reference - Critical Checks

### During Backfill (Run Every 10-15 Minutes)
```bash
# 1. Check progress - are dates being processed?
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as records
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY 1 ORDER BY 1 DESC LIMIT 5"

# 2. Check for errors accumulating (STOP if PROCESSING_ERROR > 0)
bq query --use_legacy_sql=false "
SELECT failure_category, COUNT(*) as cnt
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN 'START' AND 'END'
GROUP BY 1 ORDER BY 2 DESC"

# 3. Quick cascade contamination check
bq query --use_legacy_sql=false "
SELECT game_date, COUNTIF(opponent_strength_score = 0) as bad, COUNT(*) as total
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY 1 HAVING COUNTIF(opponent_strength_score = 0) > 0"
```

### After Phase 4 Backfill
```bash
# 1. Run validation script
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date START --end-date END --details

# 2. Run cascade contamination validation
PYTHONPATH=. .venv/bin/python scripts/validate_cascade_contamination.py \
  --start-date START --end-date END --strict
```

### After Phase 5 Backfill
```bash
# 1. Check all 5 systems generating predictions
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY 1 ORDER BY 2 DESC"

# 2. Check for duplicates (should be 0)
bq query --use_legacy_sql=false "
SELECT game_date, player_lookup, system_id, COUNT(*) as dup
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY 1,2,3 HAVING COUNT(*) > 1"

# 3. Check value ranges (should all be 0 except total)
bq query --use_legacy_sql=false "
SELECT COUNT(*) as total,
  COUNTIF(predicted_points < 0 OR predicted_points > 60) as bad_points,
  COUNTIF(confidence_score < 0 OR confidence_score > 1) as bad_conf
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'"

# 4. Check MAE by system (should be < 7.0)
bq query --use_legacy_sql=false "
SELECT p.system_id, ROUND(AVG(ABS(p.predicted_points - pgs.points)), 2) as mae
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.game_date = pgs.game_date AND p.player_lookup = pgs.player_lookup
WHERE p.game_date BETWEEN 'START' AND 'END'
GROUP BY 1 ORDER BY 2"
```

---

## 🚨 STOP AND INVESTIGATE Thresholds

| Condition | Threshold | Action |
|-----------|-----------|--------|
| `PROCESSING_ERROR` failures | > 0 | **STOP** - Code bug, fix before continuing |
| `UNTRACKED` dates | > 0 | **STOP** - Missing failure tracking, investigate |
| Zero-value `opponent_strength_score` | > 5% of records | **STOP** - Cascade contamination |
| Timeout errors | > 3 consecutive dates | **PAUSE** - Check BQ connectivity |
| No progress for 10+ minutes | - | **CHECK** - Is script hung? |

---

## Part 0: Real-Time Monitoring During Backfill

### 0.1 Log Monitoring (Watch in Separate Terminal)

```bash
# Watch the backfill output in real-time
# Replace with your actual log location
tail -f /tmp/phase4_backfill_*.log 2>/dev/null || tail -f /tmp/backfill.log

# Or watch stdout if running interactively
# Look for these patterns:
#   ✓ = Success
#   SKIP = Expected skip (bootstrap)
#   ERROR = Problem - investigate
#   took XXXs = Performance (normal: 30-60s per date)
```

### 0.2 Progress Tracking Query

Run every 10-15 minutes to verify dates are being processed:

```sql
-- Show most recent processed dates and record counts
SELECT
  'TDZA' as proc, MAX(DATE(analysis_date)) as latest, COUNT(DISTINCT DATE(analysis_date)) as dates
FROM nba_precompute.team_defense_zone_analysis WHERE DATE(analysis_date) BETWEEN 'START' AND 'END'
UNION ALL
SELECT 'PSZA', MAX(DATE(analysis_date)), COUNT(DISTINCT DATE(analysis_date))
FROM nba_precompute.player_shot_zone_analysis WHERE DATE(analysis_date) BETWEEN 'START' AND 'END'
UNION ALL
SELECT 'PCF', MAX(DATE(game_date)), COUNT(DISTINCT DATE(game_date))
FROM nba_precompute.player_composite_factors WHERE DATE(game_date) BETWEEN 'START' AND 'END'
UNION ALL
SELECT 'PDC', MAX(DATE(cache_date)), COUNT(DISTINCT DATE(cache_date))
FROM nba_precompute.player_daily_cache WHERE DATE(cache_date) BETWEEN 'START' AND 'END'
UNION ALL
SELECT 'MLFS', MAX(DATE(game_date)), COUNT(DISTINCT DATE(game_date))
FROM nba_predictions.ml_feature_store_v2 WHERE DATE(game_date) BETWEEN 'START' AND 'END';
```

**What to look for:**
- `latest` date should be advancing
- `dates` count should be increasing
- If stuck for >10 min, check if script is hung

### 0.3 Failure Accumulation Check

Run periodically to catch problems early:

```sql
-- Are failures accumulating? Check every 15 min
SELECT
  processor_name,
  failure_category,
  COUNT(*) as count,
  MIN(analysis_date) as first_date,
  MAX(analysis_date) as last_date
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN 'START' AND 'END'
  AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)  -- Recent failures
GROUP BY 1, 2
ORDER BY 3 DESC;
```

**Red flags to watch for:**
- `PROCESSING_ERROR` appearing = **STOP and investigate**
- `INCOMPLETE_UPSTREAM` growing rapidly = upstream issue
- Normal: `INSUFFICIENT_DATA` / `EXPECTED_INCOMPLETE` counts growing (expected)

### 0.4 Quick Health Check Script

Create a simple monitoring script you can run repeatedly:

```bash
#!/bin/bash
# Save as: monitor_backfill.sh
# Usage: ./monitor_backfill.sh 2021-11-01 2021-12-31

START=$1
END=$2

echo "=== BACKFILL HEALTH CHECK $(date) ==="
echo ""
echo "--- Progress (latest dates processed) ---"
bq query --use_legacy_sql=false --format=pretty "
SELECT 'PCF' as proc, MAX(DATE(game_date)) as latest, COUNT(DISTINCT DATE(game_date)) as dates
FROM nba_precompute.player_composite_factors WHERE DATE(game_date) BETWEEN '$START' AND '$END'
UNION ALL
SELECT 'MLFS', MAX(DATE(game_date)), COUNT(DISTINCT DATE(game_date))
FROM nba_predictions.ml_feature_store_v2 WHERE DATE(game_date) BETWEEN '$START' AND '$END'"

echo ""
echo "--- Failures (last 30 min) ---"
bq query --use_legacy_sql=false --format=pretty "
SELECT failure_category, COUNT(*) as cnt
FROM nba_processing.precompute_failures
WHERE analysis_date BETWEEN '$START' AND '$END'
  AND created_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 MINUTE)
GROUP BY 1 ORDER BY 2 DESC LIMIT 5"

echo ""
echo "--- Contamination Check (zero opponent_strength) ---"
bq query --use_legacy_sql=false --format=pretty "
SELECT COUNT(*) as bad_records
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN '$START' AND '$END'
  AND opponent_strength_score = 0"
```

### 0.5 Checkpoint Recovery

If backfill fails mid-way, use the checkpoint system:

```bash
# Check checkpoint status
cat /tmp/backfill_checkpoints/*.json 2>/dev/null | jq -r '.last_completed_date'

# Resume from checkpoint (built into run_phase4_backfill.sh)
./bin/backfill/run_phase4_backfill.sh --start-date START --end-date END
# It will auto-resume from last checkpoint

# Force restart (ignore checkpoints)
./bin/backfill/run_phase4_backfill.sh --start-date START --end-date END --no-resume
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

#### Source of Truth: Where Expected Players Come From

**`nba_analytics.player_game_summary`** is the authoritative source for which players played on each date. This is populated by Phase 3 from box score data.

```
Pipeline Flow:
  Phase 2 (Raw Box Scores)
    → Phase 3 (player_game_summary) ← SOURCE OF TRUTH for players
      → Phase 4 (Precompute processors)
        → Phase 5 (Predictions)
```

If a player is in `player_game_summary` but missing from Phase 4/5, that's a gap to investigate.

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

#### Find Specific Missing Players
```sql
-- Get the actual player names that are missing
SELECT
  pgs.game_date,
  pgs.player_lookup,
  pgs.player_name,
  pgs.team_abbr,
  pgs.minutes_played
FROM nba_analytics.player_game_summary pgs
LEFT JOIN nba_precompute.player_composite_factors pcf
  ON pgs.game_date = pcf.game_date AND pgs.player_lookup = pcf.player_lookup
WHERE pgs.game_date = 'YYYY-MM-DD'
  AND pcf.player_lookup IS NULL  -- Missing from Phase 4
  AND pgs.minutes_played > 10
ORDER BY pgs.minutes_played DESC;
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

Name resolution failures occur when a player name from raw data can't be matched to the registry. These players will be missing from downstream processors until fixed.

### 4.1 Check Registry Failures (Unresolved Players)

```sql
-- Players that failed name resolution and need fixing
SELECT
  player_lookup,
  game_date,
  team_abbr,
  season,
  status,
  created_at
FROM nba_processing.registry_failures
WHERE game_date >= 'START' AND game_date <= 'END'
  AND status = 'PENDING'  -- Not yet resolved
ORDER BY game_date, player_lookup;

-- Count by status
SELECT status, COUNT(*) as count
FROM nba_processing.registry_failures
WHERE game_date >= 'START' AND game_date <= 'END'
GROUP BY status;

-- Statuses:
-- PENDING: Needs manual resolution
-- RESOLVED: Fixed in registry, needs reprocessing
-- REPROCESSED: Fixed and reprocessed
```

### 4.2 Check Name Resolution Log
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

### 4.3 Check Player Name Collisions
```sql
SELECT *
FROM nba_processing.player_name_collisions
WHERE detected_date >= 'START' AND detected_date <= 'END';
```

### 4.4 Name Resolution Recovery Workflow

When a name resolution issue is fixed, you need to re-run affected processors:

```bash
# Step 1: Find which dates are affected by the fixed player
bq query --use_legacy_sql=false "
SELECT DISTINCT game_date
FROM nba_processing.registry_failures
WHERE player_lookup = 'FIXED_PLAYER_LOOKUP'
  AND status = 'RESOLVED'
ORDER BY game_date"

# Step 2: Re-run Phase 3 for affected dates (to pick up the player)
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date AFFECTED_START --end-date AFFECTED_END

# Step 3: Re-run Phase 4 for affected dates
# Order: TDZA+PSZA (parallel) → PCF → PDC → MLFS
./bin/backfill/run_phase4_backfill.sh --start-date AFFECTED_START --end-date AFFECTED_END

# Step 4: Re-run Phase 5 predictions
PYTHONPATH=. .venv/bin/python backfill_jobs/predictions/predictions_backfill.py \
  --start-date AFFECTED_START --end-date AFFECTED_END

# Step 5: Mark registry failure as REPROCESSED
bq query --use_legacy_sql=false "
UPDATE nba_processing.registry_failures
SET status = 'REPROCESSED', resolved_at = CURRENT_TIMESTAMP()
WHERE player_lookup = 'FIXED_PLAYER_LOOKUP'
  AND status = 'RESOLVED'"
```

### 4.5 Verify Player Now Appears in Pipeline

```sql
-- After reprocessing, verify player now has records
SELECT
  'Phase 3' as phase,
  COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE player_lookup = 'FIXED_PLAYER_LOOKUP'
  AND game_date >= 'AFFECTED_START'

UNION ALL

SELECT 'Phase 4 PCF', COUNT(*)
FROM nba_precompute.player_composite_factors
WHERE player_lookup = 'FIXED_PLAYER_LOOKUP'
  AND game_date >= 'AFFECTED_START'

UNION ALL

SELECT 'Phase 5 Predictions', COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE player_lookup = 'FIXED_PLAYER_LOOKUP'
  AND game_date >= 'AFFECTED_START';
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

This section covers detecting and recovering from cascade gaps - when upstream data issues affect downstream processors.

### 6.1 Cascade Gap Detection

**Question:** Did a downstream processor run with incomplete upstream data?

```sql
-- Check Phase 4 → Phase 5 cascade: Predictions made without MLFS
SELECT DISTINCT p.game_date
FROM nba_predictions.player_prop_predictions p
WHERE p.game_date >= 'START' AND p.game_date <= 'END'
  AND NOT EXISTS (
    SELECT 1 FROM nba_predictions.ml_feature_store_v2 m
    WHERE m.game_date = p.game_date
  );

-- Check Phase 3 → Phase 4 cascade: PCF made without Phase 3
SELECT DISTINCT pcf.game_date
FROM nba_precompute.player_composite_factors pcf
WHERE pcf.game_date >= 'START' AND pcf.game_date <= 'END'
  AND NOT EXISTS (
    SELECT 1 FROM nba_analytics.player_game_summary pgs
    WHERE pgs.game_date = pcf.game_date
  );
```

### 6.2 Find Players Affected by Upstream Gaps

```sql
-- Players in Phase 3 but missing from Phase 4 (due to upstream gaps)
WITH phase3_players AS (
  SELECT DISTINCT game_date, player_lookup
  FROM nba_analytics.player_game_summary
  WHERE game_date >= 'START' AND game_date <= 'END'
    AND minutes_played > 10
),
phase4_players AS (
  SELECT DISTINCT game_date, player_lookup
  FROM nba_precompute.player_composite_factors
  WHERE game_date >= 'START' AND game_date <= 'END'
)
SELECT
  p3.game_date,
  p3.player_lookup,
  'Missing from Phase 4' as issue
FROM phase3_players p3
LEFT JOIN phase4_players p4
  ON p3.game_date = p4.game_date AND p3.player_lookup = p4.player_lookup
WHERE p4.player_lookup IS NULL
ORDER BY p3.game_date, p3.player_lookup;
```

### 6.3 Validate Prediction Dependencies Met
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

### 6.4 Cascade Gap Recovery Workflow

When upstream gaps are fixed, re-run downstream in dependency order:

```
Cascade Flow (must re-run in this order):
  Phase 3 gap fixed
    → Re-run Phase 4: TDZA + PSZA (parallel)
      → Re-run Phase 4: PCF (needs TDZA)
        → Re-run Phase 4: PDC
          → Re-run Phase 4: MLFS (needs PCF, PDC)
            → Re-run Phase 5: Predictions
```

```bash
# Example: Phase 3 data was missing for Dec 1-5, now fixed

# Step 1: Verify Phase 3 is now complete
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as players
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2021-12-01' AND '2021-12-05'
GROUP BY 1 ORDER BY 1"

# Step 2: Delete potentially contaminated Phase 4 data for affected dates
# (Optional but recommended for clean re-run)
bq query --use_legacy_sql=false "
DELETE FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN '2021-12-01' AND '2021-12-05'"

# Step 3: Re-run Phase 4 in order
./bin/backfill/run_phase4_backfill.sh --start-date 2021-12-01 --end-date 2021-12-05

# Step 4: Verify Phase 4 coverage matches Phase 3
bq query --use_legacy_sql=false "
SELECT
  pgs.game_date,
  COUNT(DISTINCT pgs.player_lookup) as phase3,
  COUNT(DISTINCT pcf.player_lookup) as phase4,
  COUNT(DISTINCT pgs.player_lookup) - COUNT(DISTINCT pcf.player_lookup) as gap
FROM nba_analytics.player_game_summary pgs
LEFT JOIN nba_precompute.player_composite_factors pcf
  ON pgs.game_date = pcf.game_date AND pgs.player_lookup = pcf.player_lookup
WHERE pgs.game_date BETWEEN '2021-12-01' AND '2021-12-05'
  AND pgs.minutes_played > 10
GROUP BY 1 ORDER BY 1"

# Step 5: Re-run Phase 5 predictions
PYTHONPATH=. .venv/bin/python backfill_jobs/predictions/predictions_backfill.py \
  --start-date 2021-12-01 --end-date 2021-12-05
```

### 6.5 Identify All Dates Needing Re-run

```sql
-- Find all dates where downstream ran with incomplete upstream
-- These dates need re-processing after upstream is fixed

-- PCF records with bad upstream (opponent_strength_score = 0 indicates TDZA gap)
SELECT DISTINCT game_date
FROM nba_precompute.player_composite_factors
WHERE game_date >= 'START' AND game_date <= 'END'
  AND opponent_strength_score = 0
ORDER BY game_date;

-- MLFS records with incomplete upstreams
SELECT DISTINCT game_date
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= 'START' AND game_date <= 'END'
  AND all_upstreams_ready = FALSE
ORDER BY game_date;
```

---

## Part 7: Phase 5 Predictions Validation

Phase 5 generates predictions using 5 prediction systems. This section covers how to validate predictions are being generated correctly.

### 7.1 Prerequisites for Phase 5

Before running Phase 5 predictions backfill:

```bash
# 1. Verify MLFS has data for all dates (minimum 50 records per date)
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as mlfs_count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY 1
HAVING COUNT(*) < 50
ORDER BY 1"

# Expected: 0 rows (all dates have 50+ MLFS records)

# 2. Verify MLFS completeness flags
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNTIF(is_production_ready = TRUE) as ready,
  COUNTIF(is_production_ready = FALSE) as not_ready
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY 1
ORDER BY 1"
```

### 7.2 Running Phase 5 Predictions Backfill

```bash
# Run predictions backfill (after MLFS is complete)
PYTHONPATH=. .venv/bin/python backfill_jobs/predictions/predictions_backfill.py \
  --start-date START --end-date END

# With MLFS check override (use carefully!)
PYTHONPATH=. .venv/bin/python backfill_jobs/predictions/predictions_backfill.py \
  --start-date START --end-date END --skip-mlfs-check
```

### 7.3 Phase 5 Progress Monitoring

```sql
-- Check predictions progress
SELECT
  game_date,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT system_id) as systems
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY game_date
ORDER BY game_date DESC
LIMIT 10;

-- Expected per date (after bootstrap):
-- predictions: 500-2000 (5 systems × 100-400 players)
-- players: 100-400
-- systems: 5 (all systems running)
```

### 7.4 Prediction System Health

The 5 prediction systems should all be generating predictions:

```sql
-- Check predictions per system
SELECT
  system_id,
  COUNT(*) as predictions,
  COUNT(DISTINCT game_date) as dates,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(confidence_score), 3) as avg_confidence
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY system_id
ORDER BY predictions DESC;

-- Expected systems:
-- moving_average_baseline
-- zone_matchup_v1
-- similarity_balanced_v1
-- xgboost_v1
-- ensemble_v1

-- If any system is missing or has significantly fewer predictions,
-- check for circuit breaker trips or system-specific errors.
```

### 7.5 Prediction Quality Validation

```sql
-- Value range checks
SELECT
  'Range Check' as check_type,
  COUNT(*) as total,
  COUNTIF(predicted_points < 0) as negative_pts,
  COUNTIF(predicted_points > 60) as over_60_pts,
  COUNTIF(confidence_score < 0 OR confidence_score > 1) as bad_confidence,
  COUNTIF(recommendation NOT IN ('OVER', 'UNDER', 'PASS')) as bad_recommendation
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END';

-- Expected: All counts except 'total' should be 0

-- Confidence distribution (should be 0.2-0.8 range)
SELECT
  CASE
    WHEN confidence_score < 0.3 THEN 'low (<0.3)'
    WHEN confidence_score < 0.5 THEN 'medium (0.3-0.5)'
    WHEN confidence_score < 0.7 THEN 'good (0.5-0.7)'
    ELSE 'high (>0.7)'
  END as confidence_bucket,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY 1
ORDER BY 1;
```

### 7.6 Recommendation Distribution

```sql
-- Check recommendation distribution (should be balanced)
SELECT
  game_date,
  recommendation,
  COUNT(*) as count,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(PARTITION BY game_date), 1) as pct
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY game_date, recommendation
ORDER BY game_date, recommendation;

-- Expected distribution per date:
-- OVER: 30-40%
-- UNDER: 30-40%
-- PASS: 20-40%
-- If PASS is >60%, features may be low quality
```

### 7.7 Prediction Accuracy Check (Historical)

For backfill dates with actual game results:

```sql
-- MAE by system (lower is better)
SELECT
  p.system_id,
  COUNT(*) as predictions,
  ROUND(AVG(ABS(p.predicted_points - pgs.points)), 2) as mae,
  ROUND(AVG(p.predicted_points - pgs.points), 2) as bias,
  ROUND(STDDEV(p.predicted_points - pgs.points), 2) as std_dev
FROM nba_predictions.player_prop_predictions p
JOIN nba_analytics.player_game_summary pgs
  ON p.game_date = pgs.game_date AND p.player_lookup = pgs.player_lookup
WHERE p.game_date BETWEEN 'START' AND 'END'
GROUP BY p.system_id
ORDER BY mae;

-- Expected MAE:
-- < 5.0: Excellent
-- 5.0-6.0: Good
-- 6.0-7.0: Acceptable
-- > 7.0: Investigate
```

### 7.8 Phase 5 Duplicates Check

```sql
-- Check for duplicate predictions (same player/date/system)
SELECT
  game_date,
  player_lookup,
  system_id,
  COUNT(*) as dup_count
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY game_date, player_lookup, system_id
HAVING COUNT(*) > 1
LIMIT 20;

-- Expected: 0 rows
-- If duplicates exist, check idempotency (pre-delete before insert)
```

### 7.9 Phase 5 Completeness Fields

Predictions inherit completeness from MLFS:

```sql
-- Check predictions completeness metadata
SELECT
  game_date,
  COUNTIF(is_production_ready = TRUE) as prod_ready,
  COUNTIF(is_production_ready = FALSE) as not_ready,
  COUNTIF(backfill_bootstrap_mode = TRUE) as bootstrap_mode,
  AVG(completeness_percentage) as avg_completeness
FROM nba_predictions.player_prop_predictions
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY game_date
ORDER BY game_date;

-- Early season: expect lower prod_ready rates
-- After Nov 15+: expect >80% prod_ready
```

### 7.10 Phase 5 Skip Reasons

Check why players were skipped:

```sql
-- Check prediction worker skip reasons
SELECT
  skip_reason,
  COUNT(*) as count
FROM nba_predictions.prediction_worker_runs
WHERE DATE(created_at) BETWEEN 'START' AND 'END'
  AND skip_reason IS NOT NULL
GROUP BY skip_reason
ORDER BY count DESC;

-- Expected (normal):
-- 'no_features' - Player not in MLFS
-- 'features_not_production_ready' - Completeness < 90%

-- Investigate (problems):
-- 'invalid_features' - Quality score < 70
-- 'circuit_open_*' - System circuit breaker tripped
```

---

## Part 8: Special Scenarios

### 8.1 COVID Protocol Dates (2021-22 Season)
Many games postponed Dec 2021 - Jan 2022. Expect:
- Fewer games per date
- Some dates with very few or no games
- Players on health protocols missing from data

### 8.2 Early Season Bootstrap
PSZA requires 10 games per player. Even after system bootstrap (day 14), individual players may not have 10 games yet.

**Expected pattern:**
- Day 14-17: ~0-50 PSZA records
- Day 18-21: ~50-100 PSZA records
- Day 22+: Normal coverage

### 8.3 Trade Deadline / All-Star Break
Players traded mid-season may have gaps. All-Star break (usually mid-February) has no games.

---

## Part 9: Advanced Validation Checks

These checks go deeper into the processor internals based on how the code actually works.

### 9.1 Circuit Breaker State Monitoring

Circuit breakers trip after 5 consecutive failures and block processing for 30 minutes.

```sql
-- Check for tripped circuit breakers
SELECT
  processor_name,
  entity_id,
  analysis_date,
  attempt_number,
  completeness_pct,
  skip_reason,
  circuit_breaker_until,
  TIMESTAMP_DIFF(circuit_breaker_until, CURRENT_TIMESTAMP(), MINUTE) as minutes_remaining
FROM nba_orchestration.reprocess_attempts
WHERE analysis_date BETWEEN 'START' AND 'END'
  AND circuit_breaker_tripped = TRUE
  AND circuit_breaker_until > CURRENT_TIMESTAMP()
ORDER BY analysis_date DESC
LIMIT 20;
```

**Expected:** 0 rows during active backfill (circuit breakers shouldn't trip if upstream is healthy)

### 9.2 is_production_ready Distribution

This is THE key field that determines data quality. Records with `is_production_ready=FALSE` have <90% completeness.

```sql
-- Check production readiness distribution by processor
SELECT
  'PCF' as proc,
  game_date,
  COUNTIF(is_production_ready = TRUE) as ready,
  COUNTIF(is_production_ready = FALSE) as not_ready,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(is_production_ready = TRUE) / COUNT(*), 1) as ready_pct
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY game_date
HAVING COUNTIF(is_production_ready = FALSE) > 0
ORDER BY game_date;
```

**Expected for normal dates:** >80% production ready
**Expected for early season (Nov 1-15):** Lower rates acceptable (bootstrap)

### 9.3 Quality Tier Distribution

Processors assign quality tiers based on sample size.

```sql
-- Check quality tier distribution
SELECT
  game_date,
  data_quality_tier,
  COUNT(*) as count
FROM nba_precompute.player_shot_zone_analysis
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY game_date, data_quality_tier
ORDER BY game_date, data_quality_tier;

-- Expected distribution (after bootstrap):
-- high: 60-70% (>=10 games)
-- medium: 20-30% (7-9 games)
-- low: 10-20% (<7 games, rookies, limited players)
```

### 9.4 Data Quality Issues Field

The `data_quality_issues` array tracks specific problems.

```sql
-- Find records with quality issues
SELECT
  game_date,
  data_quality_issues,
  COUNT(*) as count
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN 'START' AND 'END'
  AND ARRAY_LENGTH(data_quality_issues) > 0
GROUP BY game_date, data_quality_issues
ORDER BY count DESC
LIMIT 20;

-- Common issues (expected):
-- 'upstream_player_shot_zone_incomplete' - early season
-- 'early_season' - bootstrap period
-- 'thin_sample' - limited data

-- Issues to investigate:
-- 'all_sources_failed' - BAD
-- 'missing_required' - BAD
```

### 9.5 Phase 5 Feature Validation Failures

Predictions skip players when features don't meet quality thresholds.

```sql
-- Check prediction skip reasons
SELECT
  DATE(created_at) as run_date,
  skip_reason,
  COUNT(*) as count
FROM nba_predictions.prediction_worker_runs
WHERE DATE(created_at) BETWEEN 'START' AND 'END'
  AND skip_reason IS NOT NULL
GROUP BY run_date, skip_reason
ORDER BY run_date, count DESC;

-- Expected skip reasons:
-- 'no_features' - No MLFS data for player (early season)
-- 'features_not_production_ready' - Completeness < 90%

-- Bad skip reasons (investigate):
-- 'invalid_features' - Quality score < 70
-- 'circuit_open_*' - System circuit breaker tripped
```

### 9.6 MLFS Upstream Completeness

MLFS checks all Phase 4 upstreams before processing.

```sql
-- Check MLFS upstream status flags
SELECT
  game_date,
  COUNTIF(upstream_pdc_ready = FALSE) as pdc_not_ready,
  COUNTIF(upstream_pcf_ready = FALSE) as pcf_not_ready,
  COUNTIF(upstream_psza_ready = FALSE) as psza_not_ready,
  COUNTIF(upstream_tdza_ready = FALSE) as tdza_not_ready,
  COUNTIF(all_upstreams_ready = FALSE) as any_upstream_missing,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY game_date
HAVING COUNTIF(all_upstreams_ready = FALSE) > 0
ORDER BY game_date;
```

### 9.7 Backfill Mode Blindspot Check

**CRITICAL:** In backfill mode, defensive checks are SKIPPED. This means:
- Upstream processor status is NOT verified
- Gap detection in lookback window is NOT performed
- You must manually validate data integrity

```bash
# After backfill, run these to compensate for skipped defensive checks:

# 1. Verify no cascade contamination (defensive check substitute)
PYTHONPATH=. .venv/bin/python scripts/validate_cascade_contamination.py \
  --start-date START --end-date END --strict

# 2. Check for gaps in lookback window (gap detection substitute)
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as players
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN DATE_SUB(DATE('START'), INTERVAL 30 DAY) AND 'END'
GROUP BY game_date
ORDER BY game_date"

# 3. Verify source metadata was captured
bq query --use_legacy_sql=false "
SELECT game_date,
  COUNTIF(source_pgs_last_updated IS NULL) as missing_pgs_meta,
  COUNTIF(source_tdgs_last_updated IS NULL) as missing_tdgs_meta
FROM nba_precompute.player_composite_factors
WHERE game_date BETWEEN 'START' AND 'END'
GROUP BY 1 HAVING COUNTIF(source_pgs_last_updated IS NULL) > 0"
```

### 9.8 Multi-Window Completeness (PDC Specific)

Player Daily Cache checks 4 windows - all must pass for production ready.

```sql
-- Check PDC multi-window completeness
SELECT
  cache_date,
  COUNTIF(l5_completeness_pct < 90) as l5_incomplete,
  COUNTIF(l10_completeness_pct < 90) as l10_incomplete,
  COUNTIF(l7d_completeness_pct < 90) as l7d_incomplete,
  COUNTIF(l14d_completeness_pct < 90) as l14d_incomplete,
  COUNT(*) as total
FROM nba_precompute.player_daily_cache
WHERE cache_date BETWEEN 'START' AND 'END'
GROUP BY cache_date
HAVING COUNTIF(l5_completeness_pct < 90) > 0
   OR COUNTIF(l10_completeness_pct < 90) > 0
ORDER BY cache_date;
```

---

## Part 10: 2021-22 Season Backfill Reference

### 10.1 Season Timeline

| Period | Dates | Notes |
|--------|-------|-------|
| Season Start | Oct 19, 2021 | First game day |
| Bootstrap Window | Oct 19 - Nov 1 | Days 0-13, expect 90%+ failures |
| Early Season | Nov 2 - Nov 18 | Failures decrease from 75% to 30% |
| Normal Operations | Nov 19+ | Expect ~25% baseline failures |
| COVID Surge | Dec 17 - Jan 15 | Many postponements, lower player counts |
| All-Star Break | Feb 18-23, 2022 | No games |
| Trade Deadline | Feb 10, 2022 | Player movements |
| Season End | Apr 10, 2022 | Regular season ends |

### 10.2 Expected Failure Rates by Month (2021-22)

| Month | PSZA Failure Rate | Notes |
|-------|-------------------|-------|
| Oct 2021 | 90-100% | Bootstrap period |
| Nov 2021 (1-5) | 80-90% | Transitioning out of bootstrap |
| Nov 2021 (6-15) | 40-60% | Players accumulating games |
| Nov 2021 (16-30) | 25-35% | Normal baseline |
| Dec 2021 | 25-35% | Normal, some COVID impact |
| Jan 2022 | 25-30% | COVID surge impact |
| Feb 2022 | 20-25% | All-Star break gap |
| Mar-Apr 2022 | 15-20% | Stable baseline |

### 10.3 Key Dates to Watch

```sql
-- Check these specific dates for 2021-22
-- Oct 19: First game day (expect all failures)
-- Nov 2: First day with potential PSZA records
-- Nov 5: First day with meaningful PSZA coverage
-- Dec 23: COVID surge begins (expect fewer players)
-- Feb 18-23: All-Star break (no games)
SELECT game_date, COUNT(*) as players
FROM nba_analytics.player_game_summary
WHERE game_date IN ('2021-10-19', '2021-11-02', '2021-11-05', '2021-12-23', '2022-02-18')
GROUP BY 1 ORDER BY 1;
```

### 10.4 Quick Validation for 2021-22 Backfill

Run this after completing each month:

```bash
# November 2021 validation
PYTHONPATH=. .venv/bin/python scripts/validate_backfill_coverage.py \
  --start-date 2021-11-01 --end-date 2021-11-30 --details

# Check cascade contamination
PYTHONPATH=. .venv/bin/python scripts/validate_cascade_contamination.py \
  --start-date 2021-11-01 --end-date 2021-11-30

# Verify no unexpected gaps
bq query --use_legacy_sql=false "
SELECT
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(DISTINCT game_date) as game_days,
  SUM(CASE WHEN pcf.game_date IS NULL THEN 1 ELSE 0 END) as missing_pcf_days
FROM nba_analytics.player_game_summary pgs
LEFT JOIN (SELECT DISTINCT game_date FROM nba_precompute.player_composite_factors) pcf
  ON pgs.game_date = pcf.game_date
WHERE pgs.game_date BETWEEN '2021-10-19' AND '2022-04-10'
GROUP BY 1 ORDER BY 1"
```

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
**Status:** FIXED - normalized to 0-1 scale (commit 6bccfdd)

### Issue 6: Stale Data from Failed Backfills
**Symptom:** Failed backfill dates still have old/incomplete data from previous runs
**Example (Session 106):**
- Dec 7 backfill failed with BQ timeout
- Old MLFS data (59 players) remained from previous incorrect run
- Predictions backfill would have used this incomplete data
**Root Cause:** MERGE pattern updates/inserts but doesn't remove players that shouldn't exist
**Fix applied:**
1. Manual DELETE of stale data before retry
2. Added MLFS completeness check to predictions backfill (prevents running on incomplete data)
**Prevention:**
- Always verify MLFS coverage before running predictions
- Use `--skip-mlfs-check` only if you understand the implications
```bash
# Check MLFS coverage before predictions
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as mlfs,
  (SELECT COUNT(*) FROM nba_analytics.player_game_summary WHERE game_date = m.game_date) as expected
FROM nba_predictions.ml_feature_store_v2 m
WHERE game_date = 'YYYY-MM-DD'
GROUP BY game_date"
```

### Issue 7: Transient BigQuery Timeouts
**Symptom:** Random dates fail with 600s timeout on batch extraction
**Example:** Dec 7/9 2021 failed while Dec 8 (larger date) succeeded
**Root Cause:** Network/BigQuery connection instability (NOT data volume related)
**Indicators:**
- Failed dates have FEWER players than successful dates
- Failures occur consecutively
- Dates immediately before/after succeed normally
**Fix:** Added auto-retry logic to `feature_extractor.py`:
- 3 retries with 30s, 60s, 120s delays
- Only retries transient errors (timeout, connection, reset)
- Clears batch cache between attempts
**Status:** FIXED (Session 106)

---

## Checklist Template

Copy this for each backfill run:

```
## Backfill Validation: [DATE_RANGE]

### Pre-Backfill
- [ ] Verified upstream data exists (Phase 3 has records for all dates)
- [ ] Checked bootstrap period (know which dates expect 90%+ failures)
- [ ] Confirmed idempotency in script
- [ ] For predictions: Verified MLFS has complete coverage (or using `--skip-mlfs-check`)

### During Backfill (check every 15 min)
- [ ] Progress advancing (dates increasing in BQ tables)
- [ ] No PROCESSING_ERROR failures appearing
- [ ] No cascade contamination (opponent_strength_score = 0)
- [ ] Script not hung (activity in logs)

### Post-Backfill Coverage
- [ ] Ran validation script (`validate_backfill_coverage.py`)
- [ ] Checked status codes (no UNTRACKED/Investigate)
- [ ] Verified row counts reasonable for each date

### Data Integrity
- [ ] No duplicates found
- [ ] No NULL critical fields
- [ ] Value ranges reasonable
- [ ] Ran cascade contamination check (`validate_cascade_contamination.py`)

### Quality
- [ ] Prediction accuracy acceptable (MAE < 6)
- [ ] No data anomalies

### Gaps
- [ ] No missing dates (all game days have records)
- [ ] Missing players explained (bootstrap/failures)

### Failures
- [ ] Failure categories are expected types only
- [ ] No stale failure records (data exists but failures remain)
- [ ] Failure rates match expected for season period

### Downstream
- [ ] Phase 5 not impacted by Phase 4 gaps
- [ ] Dependency thresholds met (MLFS >= 50 for predictions)

### Phase 5 Predictions (if running predictions backfill)
- [ ] MLFS has 50+ records per date before predictions run
- [ ] All 5 prediction systems generating predictions
- [ ] No duplicates (player/date/system unique)
- [ ] Prediction ranges valid (0-60 points, confidence 0-1)
- [ ] Recommendation distribution balanced (OVER/UNDER/PASS ~30-40% each)
- [ ] MAE < 7.0 across all systems

### Stop Conditions Monitored
- [ ] Did NOT see PROCESSING_ERROR > 0
- [ ] Did NOT see UNTRACKED status
- [ ] Did NOT see cascade contamination > 5%
- [ ] Did NOT see script hung > 10 min

### Advanced Checks (Post-Backfill)
- [ ] Circuit breakers not tripped (reprocess_attempts table)
- [ ] is_production_ready distribution reasonable (>80% after bootstrap)
- [ ] Quality tier distribution normal (high: 60-70%, medium: 20-30%)
- [ ] No bad data_quality_issues (all_sources_failed, missing_required)
- [ ] Backfill blindspot compensated (ran cascade contamination check)
- [ ] MLFS upstream flags all TRUE (all_upstreams_ready)

### Notes:
[Any special observations, unexpected failures, or issues encountered]
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-10 | Initial version based on Session 104 learnings |
| 1.1 | 2025-12-10 | Added Issues 6 (stale data), 7 (BQ timeouts) from Session 106. Added MLFS check to template. |
| 1.2 | 2025-12-10 | Added Part 0 (Real-Time Monitoring), Part 8 (2021-22 Season Reference), STOP thresholds table, health check script, checkpoint recovery, and expanded checklist template. |
| 1.3 | 2025-12-10 | Added Part 7B (Advanced Validation Checks) based on deep code review: circuit breaker monitoring, is_production_ready checks, quality tier distribution, data_quality_issues field, Phase 5 skip reasons, MLFS upstream completeness, backfill mode blindspot warning, and PDC multi-window checks. |
| 1.4 | 2025-12-10 | Reorganized document: Added Table of Contents, dedicated Part 7 for Phase 5 Predictions Validation (10 subsections covering prerequisites, progress monitoring, system health, quality validation, accuracy checks), renumbered sections for logical flow, added Phase 5 items to checklist template. |
| 1.5 | 2025-12-10 | Enhanced gap detection: Added "Source of Truth" explanation for player_game_summary, registry_failures table checks, name resolution recovery workflow, cascade gap detection queries, cascade recovery workflow with dependency order, find players affected by upstream gaps. |
