# January 2022 Test Backfill Plan

**Created:** 2025-12-10
**Purpose:** Test complete pipeline backfill before running all 4 seasons
**Target Period:** 2022-01-01 to 2022-01-31

---

## Executive Summary

January 2022 will serve as a test case for the full backfill pipeline. This month has:
- **15 game dates**
- **157 games**
- **488 unique players**

This is a good test because it's after the bootstrap period (Nov-Dec 2021) so all players should have sufficient history for predictions.

---

## Current State (Pre-Backfill)

### Phase 3 Analytics Tables

| Table | Jan 2022 Status | Expected |
|-------|-----------------|----------|
| `nba_analytics.player_game_summary` | HAS DATA (15 dates, 488 players) | Already complete |
| `nba_analytics.team_defense_game_summary` | HAS DATA | Already complete |
| `nba_analytics.team_offense_game_summary` | HAS DATA | Already complete |
| `nba_analytics.upcoming_player_game_context` | MISSING | Needs backfill |
| `nba_analytics.upcoming_team_game_context` | MISSING | Needs backfill |

### Phase 4 Precompute Tables

| Table | Jan 2022 Status | Expected After |
|-------|-----------------|----------------|
| `nba_precompute.team_defense_zone_analysis` | MISSING | 15 dates |
| `nba_precompute.player_shot_zone_analysis` | MISSING | ~488 players/date |
| `nba_precompute.player_composite_factors` | MISSING | ~488 players/date |
| `nba_precompute.player_daily_cache` | MISSING | ~488 players/date |

### Phase 4+ ML Feature Store

| Table | Jan 2022 Status | Expected After |
|-------|-----------------|----------------|
| `nba_predictions.ml_feature_store_v2` | MISSING | ~488 players/date |

### Phase 5 Predictions

| Table | Jan 2022 Status | Expected After |
|-------|-----------------|----------------|
| `nba_predictions.player_prop_predictions` | MISSING | ~488 players/date |

---

## Backfill Execution Order

### STEP 0: Pre-Backfill Validation

Run these queries to establish baseline:

```bash
# Check January 2022 has base data
bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as table_name,
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT player_lookup) as players
FROM nba_analytics.player_game_summary
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'
UNION ALL
SELECT 'team_defense_game_summary', COUNT(DISTINCT game_date), COUNT(DISTINCT defending_team_abbr)
FROM nba_analytics.team_defense_game_summary
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'
UNION ALL
SELECT 'team_offense_game_summary', COUNT(DISTINCT game_date), COUNT(DISTINCT team_abbr)
FROM nba_analytics.team_offense_game_summary
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'"
```

**Expected Output:**
- player_game_summary: 15 dates, ~488 players
- team_defense_game_summary: 15 dates, 30 teams
- team_offense_game_summary: 15 dates, 30 teams

---

### STEP 1: Phase 3 Analytics Backfill (Optional Re-run)

Phase 3 tables already have data for January 2022. Only re-run if you want to refresh:

#### 1.1 Player Game Summary (skip if already complete)
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_analytics.player_game_summary`
**Expected Duration:** ~5-10 minutes
**Success Criteria:** 15 dates with ~488 players each

#### 1.2 Team Defense Game Summary (skip if already complete)
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/team_defense_game_summary/team_defense_game_summary_analytics_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_analytics.team_defense_game_summary`
**Expected Duration:** ~5-10 minutes
**Success Criteria:** 15 dates with 30 teams each

#### 1.3 Team Offense Game Summary (skip if already complete)
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/team_offense_game_summary/team_offense_game_summary_analytics_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_analytics.team_offense_game_summary`
**Expected Duration:** ~5-10 minutes
**Success Criteria:** 15 dates with 30 teams each

#### 1.4 Upcoming Player Game Context (REQUIRED for predictions)
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_analytics.upcoming_player_game_context`
**Expected Duration:** ~10-15 minutes
**Success Criteria:** 15 dates with player context records

#### 1.5 Upcoming Team Game Context (REQUIRED for predictions)
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_analytics.upcoming_team_game_context`
**Expected Duration:** ~5-10 minutes
**Success Criteria:** 15 dates with team context records

#### Step 1 Validation Query
```bash
bq query --use_legacy_sql=false "
SELECT
  'upcoming_player_game_context' as table_name,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as records
FROM nba_analytics.upcoming_player_game_context
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'
UNION ALL
SELECT 'upcoming_team_game_context', COUNT(DISTINCT game_date), COUNT(*)
FROM nba_analytics.upcoming_team_game_context
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'"
```

---

### STEP 2: Phase 4 Precompute Backfill

**IMPORTANT:** These must run in order due to dependencies!

```
TDZA (no dependencies)     ─┬─► PSZA (no dependencies) ─┬─► PCF (needs PSZA + TDZA)
                            │                           │
                            └───────────────────────────┴─► PDC (needs PSZA)
```

#### 2.1 Team Defense Zone Analysis (TDZA)
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_precompute.team_defense_zone_analysis`
**Input:** `nba_analytics.team_defense_game_summary`
**Expected Duration:** ~2-5 minutes
**Success Criteria:** 15 dates with 30 teams each

#### 2.2 Player Shot Zone Analysis (PSZA)
```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_precompute.player_shot_zone_analysis`
**Input:** `nba_analytics.player_game_summary`
**Expected Duration:** ~5-10 minutes
**Success Criteria:** 15 dates with ~450+ players each

#### 2.3 Player Composite Factors (PCF)
**Must run AFTER TDZA and PSZA complete!**

```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_precompute.player_composite_factors`
**Input:** `nba_precompute.player_shot_zone_analysis`, `nba_precompute.team_defense_zone_analysis`, `nba_analytics.upcoming_player_game_context`
**Expected Duration:** ~5-10 minutes
**Success Criteria:** 15 dates with ~450+ players each

#### 2.4 Player Daily Cache (PDC)
**Must run AFTER PSZA complete!**

```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31
```

**Output Table:** `nba_precompute.player_daily_cache`
**Input:** `nba_analytics.player_game_summary`, `nba_precompute.player_shot_zone_analysis`
**Expected Duration:** ~5-10 minutes
**Success Criteria:** 15 dates with ~450+ players each

#### Step 2 Validation Query
```bash
bq query --use_legacy_sql=false "
SELECT 'TDZA' as processor, COUNT(DISTINCT analysis_date) as dates, COUNT(*) as records
FROM nba_precompute.team_defense_zone_analysis
WHERE analysis_date >= '2022-01-01' AND analysis_date <= '2022-01-31'
UNION ALL
SELECT 'PSZA', COUNT(DISTINCT analysis_date), COUNT(*)
FROM nba_precompute.player_shot_zone_analysis
WHERE analysis_date >= '2022-01-01' AND analysis_date <= '2022-01-31'
UNION ALL
SELECT 'PCF', COUNT(DISTINCT game_date), COUNT(*)
FROM nba_precompute.player_composite_factors
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'
UNION ALL
SELECT 'PDC', COUNT(DISTINCT cache_date), COUNT(*)
FROM nba_precompute.player_daily_cache
WHERE cache_date >= '2022-01-01' AND cache_date <= '2022-01-31'
ORDER BY 1"
```

**Expected Results:**
- TDZA: 15 dates, ~450 records (30 teams * 15 dates)
- PSZA: 15 dates, ~6,750 records (~450 players * 15 dates)
- PCF: 15 dates, ~6,750 records
- PDC: 15 dates, ~6,750 records

---

### STEP 3: ML Feature Store (MLFS) Backfill

**Must run AFTER all Phase 4 precompute tables are populated!**

```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31 \
  --backfill-mode
```

**Output Table:** `nba_predictions.ml_feature_store_v2`
**Input:** All Phase 4 precompute tables + Phase 3 analytics tables
**Expected Duration:** ~15-30 minutes (depends on auto-retry for transient errors)
**Success Criteria:** 15 dates with ~488 players each

#### Step 3 Validation Query
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(*) as total_records,
  COUNT(*) - COUNT(DISTINCT player_lookup) as duplicates
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'"
```

**Expected Results:**
- 15 dates
- ~488 unique players
- 0 duplicates (per date)

---

### STEP 4: Predictions Backfill (Phase 5)

**Must run AFTER MLFS is complete!**

```bash
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py \
  --start-date 2022-01-01 \
  --end-date 2022-01-31 \
  --skip-preflight
```

**Output Table:** `nba_predictions.player_prop_predictions`
**Input:** `nba_predictions.ml_feature_store_v2`
**Expected Duration:** ~10-20 minutes
**Success Criteria:** 15 dates with ~488 players each, ~42 predictions per player

#### Step 4 Validation Query
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(*) as total_predictions,
  ROUND(AVG(confidence_score), 3) as avg_confidence,
  ROUND(MIN(confidence_score), 3) as min_confidence,
  ROUND(MAX(confidence_score), 3) as max_confidence
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'"
```

**Expected Results:**
- 15 dates
- ~488 unique players
- ~300,000+ total predictions (~42 prop types * ~488 players * 15 dates)
- Confidence scores in 0.4-1.0 range

---

## STEP 5: Final Coverage Validation

### 5.1 Full Coverage Check
```bash
bq query --use_legacy_sql=false "
-- January 2022 coverage: predictions vs actual players
SELECT
  pgs.game_date,
  COUNT(DISTINCT pgs.player_lookup) as players_who_played,
  COUNT(DISTINCT pred.player_lookup) as players_with_predictions,
  ROUND(COUNT(DISTINCT pred.player_lookup) * 100.0 / COUNT(DISTINCT pgs.player_lookup), 1) as coverage_pct
FROM nba_analytics.player_game_summary pgs
LEFT JOIN nba_predictions.player_prop_predictions pred
  ON pgs.game_date = pred.game_date AND pgs.player_lookup = pred.player_lookup
WHERE pgs.game_date >= '2022-01-01' AND pgs.game_date <= '2022-01-31'
GROUP BY 1
ORDER BY 1"
```

**Success Criteria:** 100% coverage on all 15 dates

### 5.2 Data Quality Check
```bash
bq query --use_legacy_sql=false "
-- Check for NULL values and data quality issues
SELECT
  'MLFS NULL player_lookup' as issue,
  COUNT(*) as count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'
  AND player_lookup IS NULL
UNION ALL
SELECT 'MLFS NULL features', COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'
  AND features IS NULL
UNION ALL
SELECT 'Predictions NULL predicted_points', COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'
  AND predicted_points IS NULL
UNION ALL
SELECT 'Predictions NULL confidence', COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'
  AND confidence_score IS NULL"
```

**Success Criteria:** All counts should be 0

### 5.3 Comparison to Known Good Period (Dec 2021)
```bash
bq query --use_legacy_sql=false "
-- Compare Jan 2022 to Dec 2021 (known good)
SELECT
  FORMAT_DATE('%Y-%m', game_date) as month,
  COUNT(DISTINCT game_date) as dates,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(*) as total_predictions,
  ROUND(AVG(confidence_score), 3) as avg_confidence
FROM nba_predictions.player_prop_predictions
WHERE (game_date >= '2021-12-01' AND game_date <= '2021-12-31')
   OR (game_date >= '2022-01-01' AND game_date <= '2022-01-31')
GROUP BY 1
ORDER BY 1"
```

**Success Criteria:** Jan 2022 metrics should be similar to Dec 2021

---

## Troubleshooting

### Common Issues

#### 1. MLFS fails with "dependency not found"
- Ensure all Phase 4 precompute tables have data for the date range
- Check: `bq query "SELECT DISTINCT analysis_date FROM nba_precompute.player_shot_zone_analysis WHERE analysis_date >= '2022-01-01'"`

#### 2. Predictions fail with "MLFS coverage below threshold"
- Run with `--skip-mlfs-check` to bypass (not recommended)
- Better: Verify MLFS has data for all dates

#### 3. BQ timeout errors
- The MLFS backfill has auto-retry (3 attempts with 30/60/120s delays)
- If still failing, try single-date runs

#### 4. Zero predictions generated
- Check if MLFS has data: `bq query "SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = '2022-01-01'"`
- Verify player_lookup values match between MLFS and PGS

---

## Rollback Procedure

If backfill produces bad data, delete and re-run:

```bash
# Delete January 2022 data from specific table
bq query --use_legacy_sql=false "DELETE FROM nba_predictions.player_prop_predictions WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'"

bq query --use_legacy_sql=false "DELETE FROM nba_predictions.ml_feature_store_v2 WHERE game_date >= '2022-01-01' AND game_date <= '2022-01-31'"

bq query --use_legacy_sql=false "DELETE FROM nba_precompute.player_daily_cache WHERE cache_date >= '2022-01-01' AND cache_date <= '2022-01-31'"

# etc for other tables...
```

---

## Estimated Total Time

| Step | Duration |
|------|----------|
| Step 1: Phase 3 (if needed) | 30-45 min |
| Step 2: Phase 4 Precompute | 15-30 min |
| Step 3: MLFS | 15-30 min |
| Step 4: Predictions | 10-20 min |
| Step 5: Validation | 5-10 min |
| **Total** | **~1-2 hours** |

---

## Next Steps After Success

If January 2022 backfill succeeds with 100% coverage:
1. Proceed with February-April 2022 (rest of 2021-22 season)
2. Then backfill 2022-23 season
3. Then backfill 2023-24 season
4. Then backfill 2024-25 season (current)

---

## Quick Command Reference

```bash
# All commands assume you're in /home/naji/code/nba-stats-scraper

# Step 1.4-1.5 (Phase 3 context tables)
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/upcoming_player_game_context/upcoming_player_game_context_analytics_backfill.py --start-date 2022-01-01 --end-date 2022-01-31
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_analytics_backfill.py --start-date 2022-01-01 --end-date 2022-01-31

# Step 2 (Phase 4 Precompute - RUN IN ORDER)
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/team_defense_zone_analysis/team_defense_zone_analysis_precompute_backfill.py --start-date 2022-01-01 --end-date 2022-01-31
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_shot_zone_analysis/player_shot_zone_analysis_precompute_backfill.py --start-date 2022-01-01 --end-date 2022-01-31
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py --start-date 2022-01-01 --end-date 2022-01-31
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/player_daily_cache/player_daily_cache_precompute_backfill.py --start-date 2022-01-01 --end-date 2022-01-31

# Step 3 (MLFS)
PYTHONPATH=. .venv/bin/python backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py --start-date 2022-01-01 --end-date 2022-01-31 --backfill-mode

# Step 4 (Predictions)
PYTHONPATH=. .venv/bin/python backfill_jobs/prediction/player_prop_predictions_backfill.py --start-date 2022-01-01 --end-date 2022-01-31 --skip-preflight
```
