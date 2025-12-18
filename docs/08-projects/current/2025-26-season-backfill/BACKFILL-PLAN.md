# 2025-26 Season Backfill Plan

**Created:** 2025-12-17
**Status:** Ready for Execution

---

## Executive Summary

The 2025-26 NBA season started on **October 21, 2025**, but our pipeline has significant data gaps. This document outlines the safe backfill strategy with proper dependency ordering to avoid **cascade contamination**.

---

## Current Data State Analysis

### Data Coverage by Phase

```
Phase 1/2 (Raw)    │ Oct 21 ────────────────────────────────── Dec 16
                   │     ❌ MISSING          ✅ HAVE (Nov 13+)
                   │     Oct 21 - Nov 12     Nov 13 - Dec 15

Phase 3 Analytics  │ Oct 21 ────────────────────────────────── Dec 16
  player_game_sum  │     ❌ MISSING          ✅ HAVE (Nov 13+)
  team_defense     │     ❌❌❌ COMPLETELY MISSING ❌❌❌
  team_offense     │     ❌❌❌ COMPLETELY MISSING ❌❌❌

Phase 4 Precompute │ Oct 21 ────────────────────────────────── Dec 16
  ALL TABLES       │     ❌❌❌ COMPLETELY MISSING ❌❌❌
```

### GCS Scraped Data Status

| Date Range | GCS Status | BigQuery Status |
|------------|------------|-----------------|
| Oct 21 - Nov 12 | **NO FILES** | No data |
| Nov 13 - Dec 15 | Has files | Has data |
| Dec 16 | Missing (today) | No data |

---

## 🚨 CRITICAL: Cascade Contamination Risk

### The Dangerous Scenario

If we run Phase 4 backfill **before** Phase 3 `team_defense_game_summary` is populated:

```
Phase 3: team_defense_game_summary = EMPTY
           ↓
Phase 4: TDZA runs → produces 0 records (no upstream data)
           ↓
Phase 4: PCF runs → opponent_strength_score = 0 for ALL records
           ↓
Phase 4: ML runs → bad features built on corrupted PCF
           ↓
Phase 5: Predictions → completely wrong predictions
```

**Result:** Records EXIST but contain INVALID VALUES. This is worse than missing data because:
1. Records pass existence checks ✓
2. Records have timestamps/IDs ✓
3. **Values are zeros/NULLs** ✗
4. Downstream consumers silently use bad data ✗

### Detection Query for Contamination

```sql
-- Run this AFTER any Phase 4 backfill to detect contamination
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(opponent_strength_score = 0) as zero_opponent,
  COUNTIF(opponent_strength_score > 0) as valid_opponent
FROM `nba_precompute.player_composite_factors`
WHERE game_date >= '2025-10-21'
GROUP BY game_date
HAVING COUNTIF(opponent_strength_score = 0) > 0
ORDER BY game_date;
```

---

## Dependency Chain (MUST Follow This Order)

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: RAW DATA (Scrape + Process)                            │
│  ══════════════════════════════════════                         │
│  BDL Scraper → GCS → BDL Processor → bdl_player_boxscores       │
│                                                                 │
│  ⚠️  Must complete BEFORE any downstream steps                   │
│  📅 Target: Oct 21 - Nov 12 (23 missing dates)                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: PHASE 3 ANALYTICS                                      │
│  ══════════════════════════════════════                         │
│  bdl_player_boxscores → player_game_summary                     │
│  bdl_player_boxscores → team_defense_game_summary  ← CRITICAL   │
│  bdl_player_boxscores → team_offense_game_summary  ← CRITICAL   │
│                                                                 │
│  ⚠️  team_defense_game_summary MUST have data before Phase 4    │
│  📅 Target: Oct 21 - Dec 16                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: PHASE 4 PRECOMPUTE (Strict Order!)                     │
│  ══════════════════════════════════════                         │
│                                                                 │
│  3a. TDZA + PSZA ─────────────► Run in PARALLEL                 │
│         │                       (no Phase 4 deps)               │
│         ▼                                                       │
│  3b. PCF ─────────────────────► SEQUENTIAL (needs TDZA)         │
│         │                                                       │
│         ▼                                                       │
│  3c. PDC ─────────────────────► SEQUENTIAL (needs PCF)          │
│         │                                                       │
│         ▼                                                       │
│  3d. ML Feature Store ────────► SEQUENTIAL (needs ALL)          │
│                                                                 │
│  📅 Target: Nov 5+ (bootstrap period ends ~Nov 3)               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: PHASE 5 PREDICTIONS (Optional)                         │
│  ══════════════════════════════════════                         │
│  ml_feature_store_v2 → player_prop_predictions                  │
│                                                                 │
│  ⚠️  Only run if ML has 50+ records per date                    │
│  📅 Target: Nov 5+ (after bootstrap)                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Bootstrap Period for 2025-26 Season

**Season Start:** October 21, 2025
**Bootstrap Window:** Days 0-13 (Oct 21 - Nov 3)

| Week | Dates | PSZA Expected Failures | Notes |
|------|-------|------------------------|-------|
| 1 | Oct 21-27 | **100%** | No player has 10 games |
| 2 | Oct 28 - Nov 3 | **90-100%** | Still bootstrap |
| 3 | Nov 4-10 | **60-75%** | Transitioning |
| 4 | Nov 11-17 | **40-50%** | Improving |
| 5+ | Nov 18+ | **25-30%** | Normal baseline |

**Implication:** Phase 4 processors will legitimately fail for many players in early November. This is EXPECTED.

---

## Safe Execution Plan

### STEP 1: Raw Data Backfill (Oct 21 - Nov 12)

```bash
# 1.1 Run BDL scraper for missing dates
# This needs to scrape from the BDL API first, then process
for date in $(seq -f "%02g" 21 31); do
  echo "Scraping 2025-10-$date"
  PYTHONPATH=. .venv/bin/python scrapers/balldontlie/bdl_box_scores.py \
    --gamedate 2025-10-$date --group cli
  sleep 2  # Be nice to API
done

for date in $(seq -f "%02g" 1 12); do
  echo "Scraping 2025-11-$date"
  PYTHONPATH=. .venv/bin/python scrapers/balldontlie/bdl_box_scores.py \
    --gamedate 2025-11-$date --group cli
  sleep 2
done

# 1.2 Verify GCS has the data
gsutil ls gs://nba-scraped-data/ball-dont-lie/boxscores/2025-10-*/ | wc -l
gsutil ls gs://nba-scraped-data/ball-dont-lie/boxscores/2025-11-*/ | wc -l

# 1.3 Process into BigQuery
PYTHONPATH=. .venv/bin/python backfill_jobs/raw/bdl_boxscores/bdl_boxscores_raw_backfill.py \
  --start-date 2025-10-21 --end-date 2025-11-12
```

### VALIDATION GATE 1: Verify Raw Data

```sql
-- Must see ~53 game dates (Oct 21 - Dec 15)
SELECT
  COUNT(DISTINCT game_date) as game_dates,
  MIN(game_date) as earliest,
  MAX(game_date) as latest,
  COUNT(*) as total_records
FROM `nba_raw.bdl_player_boxscores`
WHERE game_date >= '2025-10-21';

-- Expected: game_dates ≥ 50, earliest = 2025-10-21
```

### STEP 2: Phase 3 Analytics Backfill

```bash
# 2.1 Player Game Summary (may already run automatically)
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2025-10-21 --end-date 2025-12-16

# 2.2 CRITICAL: Team Defense Game Summary
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2025-10-21 --end-date 2025-12-16

# 2.3 Team Offense Game Summary
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2025-10-21 --end-date 2025-12-16
```

### VALIDATION GATE 2: Verify Phase 3 BEFORE Phase 4

```sql
-- CRITICAL: team_defense_game_summary MUST have data
SELECT
  'player_game_summary' as tbl,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as records
FROM `nba_analytics.player_game_summary`
WHERE game_date >= '2025-10-21'

UNION ALL

SELECT
  'team_defense_game_summary',
  COUNT(DISTINCT game_date),
  COUNT(*)
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date >= '2025-10-21'

UNION ALL

SELECT
  'team_offense_game_summary',
  COUNT(DISTINCT game_date),
  COUNT(*)
FROM `nba_analytics.team_offense_game_summary`
WHERE game_date >= '2025-10-21';

-- ALL THREE must have data. If team_defense_game_summary = 0, STOP.
```

```sql
-- Also verify critical fields are NOT NULL
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(opp_paint_attempts > 0) as valid_paint,
  COUNTIF(opp_mid_range_attempts > 0) as valid_mid
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date >= '2025-10-21'
GROUP BY game_date
HAVING COUNTIF(opp_paint_attempts > 0) = 0;

-- Should return 0 rows. If any rows, we have NULL field issues.
```

### STEP 3: Phase 4 Precompute Backfill

**ONLY proceed if VALIDATION GATE 2 passes!**

```bash
# 3.1 TDZA and PSZA (can run in parallel)
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2025-10-21 --end-date 2025-12-16 --skip-preflight &
TDZA_PID=$!

PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2025-10-21 --end-date 2025-12-16 --skip-preflight &
PSZA_PID=$!

# Wait for both
wait $TDZA_PID $PSZA_PID
echo "TDZA and PSZA complete"

# 3.2 PCF (depends on TDZA)
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2025-11-05 --end-date 2025-12-16 --skip-preflight

# 3.3 PDC (depends on PCF)
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2025-10-21 --end-date 2025-12-16 --skip-preflight

# 3.4 ML Feature Store (depends on ALL)
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2025-11-05 --end-date 2025-12-16 --skip-preflight
```

### VALIDATION GATE 3: Check for Cascade Contamination

```sql
-- CRITICAL: Check for opponent_strength_score = 0 (indicates missing TDZA)
SELECT
  game_date,
  COUNT(*) as total,
  COUNTIF(opponent_strength_score = 0) as zero_opponent,
  COUNTIF(opponent_strength_score > 0) as valid_opponent,
  ROUND(100.0 * COUNTIF(opponent_strength_score > 0) / COUNT(*), 1) as valid_pct
FROM `nba_precompute.player_composite_factors`
WHERE game_date >= '2025-10-21'
GROUP BY game_date
HAVING COUNTIF(opponent_strength_score = 0) = COUNT(*)
ORDER BY game_date;

-- Should return 0 rows. Any rows = CASCADE CONTAMINATION.
```

---

## What If I Run Out of Order?

### Scenario 1: Run Phase 4 before Phase 3 team summaries

**Result:** All PCF records will have `opponent_strength_score = 0`

**Recovery:**
1. DELETE the contaminated Phase 4 data
2. Run Phase 3 team summaries first
3. Re-run Phase 4 in correct order

```sql
-- Delete contaminated PCF data
DELETE FROM `nba_precompute.player_composite_factors`
WHERE game_date >= '2025-10-21'
  AND opponent_strength_score = 0;
```

### Scenario 2: Run PCF before TDZA

**Result:** Same as above - `opponent_strength_score = 0`

**Recovery:** Same as Scenario 1

### Scenario 3: Run ML before PCF completes

**Result:** ML features will have missing/default values

**Recovery:**
1. DELETE ML records for affected dates
2. Re-run PCF, then ML

### Scenario 4: Run Phase 5 predictions before ML has 50+ records

**Result:** Predictions will skip dates with <50 MLFS records (built-in safety)

**Recovery:** Just re-run predictions after ML is complete

---

## Estimated Timeline

| Step | Duration | Notes |
|------|----------|-------|
| Step 1: Raw scraper | 30-60 min | API rate limits, 23 dates |
| Step 1: Raw processor | 15 min | Fast BQ processing |
| Step 2: Phase 3 | 30-60 min | 3 analytics tables |
| Step 3: TDZA + PSZA | 30-60 min | Parallel |
| Step 3: PCF | 30 min | Sequential |
| Step 3: PDC | 20 min | Sequential |
| Step 3: ML | 30-60 min | Sequential |
| **Total** | **3-5 hours** | |

---

## Monitoring During Backfill

```bash
# Watch progress every 15 minutes
./bin/backfill/monitor_backfill.sh 2025-10-21 2025-12-16

# Or manually:
bq query --use_legacy_sql=false "
SELECT
  'TDZA' as proc, MAX(DATE(analysis_date)) as latest, COUNT(DISTINCT DATE(analysis_date)) as dates
FROM nba_precompute.team_defense_zone_analysis WHERE DATE(analysis_date) >= '2025-10-21'
UNION ALL
SELECT 'PSZA', MAX(DATE(analysis_date)), COUNT(DISTINCT DATE(analysis_date))
FROM nba_precompute.player_shot_zone_analysis WHERE DATE(analysis_date) >= '2025-10-21'
UNION ALL
SELECT 'PCF', MAX(DATE(game_date)), COUNT(DISTINCT DATE(game_date))
FROM nba_precompute.player_composite_factors WHERE DATE(game_date) >= '2025-10-21'
UNION ALL
SELECT 'ML', MAX(DATE(game_date)), COUNT(DISTINCT DATE(game_date))
FROM nba_predictions.ml_feature_store_v2 WHERE DATE(game_date) >= '2025-10-21'"
```

---

## Checklist

### Pre-Backfill
- [ ] Verified raw data exists or scraped for target dates
- [ ] Verified no existing contaminated data
- [ ] Cleared any partial/failed previous backfill attempts

### Step 1: Raw Data
- [ ] BDL scraper ran for Oct 21 - Nov 12
- [ ] GCS has files for all dates
- [ ] BQ bdl_player_boxscores has Oct 21 - Dec 15 data
- [ ] **VALIDATION GATE 1 passed**

### Step 2: Phase 3 Analytics
- [ ] player_game_summary backfilled
- [ ] team_defense_game_summary backfilled
- [ ] team_offense_game_summary backfilled
- [ ] opp_paint_attempts NOT NULL verified
- [ ] **VALIDATION GATE 2 passed**

### Step 3: Phase 4 Precompute
- [ ] TDZA + PSZA completed (parallel)
- [ ] PCF completed (after TDZA)
- [ ] PDC completed (after PCF)
- [ ] ML completed (after all)
- [ ] opponent_strength_score > 0 verified
- [ ] **VALIDATION GATE 3 passed** (no cascade contamination)

### Post-Backfill
- [ ] Ran full validation script
- [ ] Verified failure rates match expected bootstrap pattern
- [ ] No PROCESSING_ERROR failures
- [ ] No UNTRACKED dates

---

## Related Documentation

- [Backfill Validation Checklist](../../02-operations/backfill/backfill-validation-checklist.md)
- [Data Integrity Guide](../../02-operations/backfill/data-integrity-guide.md)
- [Phase 4 Dependencies](../../02-operations/backfill/runbooks/phase4-dependencies.md)
- [Phase 4 Precompute Backfill Runbook](../../02-operations/backfill/runbooks/phase4-precompute-backfill.md)
