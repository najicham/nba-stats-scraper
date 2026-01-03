# Complete Backfill Execution Plan

**Date**: 2026-01-02
**Status**: 🎯 READY FOR EXECUTION
**Estimated Time**: 6-8 hours total
**Approach**: Validate → Backfill → Validate → Repeat

---

## 🎯 Executive Summary

**Goal**: Achieve 100% data completeness across all 5 seasons (2021-2026) and all 6 pipeline phases.

**Strategy**:
1. **Validate first** - Identify ALL gaps with comprehensive queries
2. **Backfill systematically** - Fill gaps in dependency order (Phase 2 → 3 → 4 → 5 → 6)
3. **Validate continuously** - Check completion after each phase
4. **Document thoroughly** - Record what was done and results

**Estimated Timeline**:
- Validation: 30 minutes
- Phase 3 backfill: 2-3 hours
- Phase 4 backfill: 1-2 hours
- Phase 5 backfill: 1 hour
- Phase 5B grading: 1-2 hours
- Final validation: 30 minutes
- **Total**: 6-8 hours

---

## 📊 Step 0: Comprehensive Validation (30 minutes)

**Goal**: Identify EVERY gap across all phases and seasons before starting backfill.

### Validation Queries

Save these to `validation_queries.sql`:

```sql
-- ============================================================
-- COMPREHENSIVE DATA COMPLETENESS VALIDATION
-- Project: nba-props-platform
-- Date: 2026-01-02
-- ============================================================

-- ------------------------------------------------------------
-- PHASE 2: Raw Data Validation
-- ------------------------------------------------------------

-- 2.1: BDL Boxscores by Season
SELECT
  season_year,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as player_records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
GROUP BY season_year
ORDER BY season_year;

-- 2.2: Gamebook Player Stats by Season
SELECT
  season_year,
  COUNT(DISTINCT game_code) as games,
  COUNT(*) as player_records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
GROUP BY season_year
ORDER BY season_year;

-- 2.3: Playoff Coverage in Phase 2 (BDL)
SELECT
  season_year,
  COUNT(DISTINCT game_id) as playoff_games,
  MIN(game_date) as playoff_start,
  MAX(game_date) as playoff_end
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE season_year IN (2021, 2022, 2023)
  AND game_date >= CASE
    WHEN season_year = 2021 THEN '2022-04-16'
    WHEN season_year = 2022 THEN '2023-04-15'
    WHEN season_year = 2023 THEN '2024-04-16'
  END
GROUP BY season_year
ORDER BY season_year;

-- ------------------------------------------------------------
-- PHASE 3: Analytics Validation
-- ------------------------------------------------------------

-- 3.1: Player Game Summary by Season
SELECT
  season_year,
  COUNT(DISTINCT game_code) as games,
  COUNT(*) as player_records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
GROUP BY season_year
ORDER BY season_year;

-- 3.2: Playoff Coverage in Phase 3 (THE KEY GAP)
SELECT
  season_year,
  COUNT(DISTINCT game_code) as playoff_games,
  MIN(game_date) as playoff_start,
  MAX(game_date) as playoff_end
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year IN (2021, 2022, 2023)
  AND game_date >= CASE
    WHEN season_year = 2021 THEN '2022-04-16'
    WHEN season_year = 2022 THEN '2023-04-15'
    WHEN season_year = 2023 THEN '2024-04-16'
  END
GROUP BY season_year
ORDER BY season_year;

-- 3.3: Phase 2 vs Phase 3 Gap Analysis (by season)
WITH phase2_dates AS (
  SELECT DISTINCT season_year, game_date
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
),
phase3_dates AS (
  SELECT DISTINCT season_year, game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
)
SELECT
  p2.season_year,
  COUNT(DISTINCT p2.game_date) as phase2_dates,
  COUNT(DISTINCT p3.game_date) as phase3_dates,
  COUNT(DISTINCT p2.game_date) - COUNT(DISTINCT p3.game_date) as missing_dates
FROM phase2_dates p2
LEFT JOIN phase3_dates p3 USING (season_year, game_date)
GROUP BY p2.season_year
ORDER BY p2.season_year;

-- ------------------------------------------------------------
-- PHASE 4: Precompute Validation
-- ------------------------------------------------------------

-- 4.1: Player Composite Factors by Season
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as player_records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2021-10-01' AND game_date < '2026-01-01'
GROUP BY year
ORDER BY year;

-- 4.2: ML Feature Store by Season
SELECT
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as feature_records,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM `nba-props-platform.nba_precompute.ml_feature_store`
WHERE game_date >= '2021-10-01' AND game_date < '2026-01-01'
GROUP BY year
ORDER BY year;

-- 4.3: Playoff Coverage in Phase 4
SELECT
  EXTRACT(YEAR FROM game_date) - 1 as season_year,
  COUNT(DISTINCT game_date) as playoff_dates,
  COUNT(*) as records
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE (
  (game_date >= '2022-04-16' AND game_date <= '2022-06-17') OR  -- 2021-22 playoffs
  (game_date >= '2023-04-15' AND game_date <= '2023-06-13') OR  -- 2022-23 playoffs
  (game_date >= '2024-04-16' AND game_date <= '2024-06-18')     -- 2023-24 playoffs
)
GROUP BY season_year
ORDER BY season_year;

-- 4.4: Phase 3 vs Phase 4 Gap Analysis
WITH phase3_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01' AND game_date < '2026-01-01'
),
phase4_dates AS (
  SELECT DISTINCT game_date
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= '2021-10-01' AND game_date < '2026-01-01'
)
SELECT
  COUNT(DISTINCT p3.game_date) as phase3_dates,
  COUNT(DISTINCT p4.game_date) as phase4_dates,
  COUNT(DISTINCT p3.game_date) - COUNT(DISTINCT p4.game_date) as missing_dates
FROM phase3_dates p3
LEFT JOIN phase4_dates p4 USING (game_date);

-- ------------------------------------------------------------
-- PHASE 5: Predictions Validation
-- ------------------------------------------------------------

-- 5.1: Player Prop Predictions by Season
SELECT
  season_year,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as predictions,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
GROUP BY season_year
ORDER BY season_year;

-- 5.2: Playoff Predictions Coverage
SELECT
  season_year,
  COUNT(DISTINCT game_id) as playoff_games,
  COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE season_year IN (2021, 2022, 2023)
  AND game_date >= CASE
    WHEN season_year = 2021 THEN '2022-04-16'
    WHEN season_year = 2022 THEN '2023-04-15'
    WHEN season_year = 2023 THEN '2024-04-16'
  END
GROUP BY season_year
ORDER BY season_year;

-- ------------------------------------------------------------
-- PHASE 5B: Grading Validation
-- ------------------------------------------------------------

-- 5B.1: Prediction Accuracy by Season
SELECT
  season_year,
  COUNT(DISTINCT game_id) as games,
  COUNT(*) as graded_predictions,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date,
  AVG(absolute_error) as avg_mae,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
GROUP BY season_year
ORDER BY season_year;

-- 5B.2: Grading Coverage by System
SELECT
  system_id,
  COUNT(DISTINCT season_year) as seasons,
  COUNT(*) as total_graded,
  AVG(absolute_error) as avg_mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
GROUP BY system_id
ORDER BY total_graded DESC;

-- ------------------------------------------------------------
-- SUMMARY: Complete Pipeline Health
-- ------------------------------------------------------------

-- Overall Completeness Matrix
WITH phase_counts AS (
  SELECT 'Phase 2: BDL Raw' as phase, season_year, COUNT(DISTINCT game_date) as dates
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
  GROUP BY season_year

  UNION ALL

  SELECT 'Phase 3: Analytics', season_year, COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
  GROUP BY season_year

  UNION ALL

  SELECT 'Phase 4: Precompute', EXTRACT(YEAR FROM game_date) - 1, COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= '2021-10-01' AND game_date < '2025-07-01'
  GROUP BY EXTRACT(YEAR FROM game_date)

  UNION ALL

  SELECT 'Phase 5: Predictions', season_year, COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
  GROUP BY season_year

  UNION ALL

  SELECT 'Phase 5B: Grading', season_year, COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE season_year IN (2021, 2022, 2023, 2024, 2025)
  GROUP BY season_year
)
SELECT
  season_year,
  SUM(CASE WHEN phase = 'Phase 2: BDL Raw' THEN dates ELSE 0 END) as phase2_dates,
  SUM(CASE WHEN phase = 'Phase 3: Analytics' THEN dates ELSE 0 END) as phase3_dates,
  SUM(CASE WHEN phase = 'Phase 4: Precompute' THEN dates ELSE 0 END) as phase4_dates,
  SUM(CASE WHEN phase = 'Phase 5: Predictions' THEN dates ELSE 0 END) as phase5_dates,
  SUM(CASE WHEN phase = 'Phase 5B: Grading' THEN dates ELSE 0 END) as phase5b_dates
FROM phase_counts
GROUP BY season_year
ORDER BY season_year;

-- ------------------------------------------------------------
-- SPECIFIC GAP IDENTIFICATION
-- ------------------------------------------------------------

-- Missing Playoff Dates in Phase 3
WITH phase2_playoff_dates AS (
  SELECT DISTINCT game_date, season_year
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE (
    (game_date >= '2022-04-16' AND game_date <= '2022-06-17') OR  -- 2021-22
    (game_date >= '2023-04-15' AND game_date <= '2023-06-13') OR  -- 2022-23
    (game_date >= '2024-04-16' AND game_date <= '2024-06-18')     -- 2023-24
  )
),
phase3_playoff_dates AS (
  SELECT DISTINCT game_date, season_year
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE (
    (game_date >= '2022-04-16' AND game_date <= '2022-06-17') OR
    (game_date >= '2023-04-15' AND game_date <= '2023-06-13') OR
    (game_date >= '2024-04-16' AND game_date <= '2024-06-18')
  )
)
SELECT
  p2.season_year,
  p2.game_date as missing_date,
  'Playoff date in Phase 2 but not Phase 3' as issue
FROM phase2_playoff_dates p2
LEFT JOIN phase3_playoff_dates p3 USING (game_date, season_year)
WHERE p3.game_date IS NULL
ORDER BY p2.game_date;
```

### Expected Results (Before Backfill)

Save these as baseline:

**Phase 2 (Raw)**:
- 2021-22: ~1,390 games ✅
- 2022-23: ~1,384 games ✅
- 2023-24: ~1,382 games ✅
- 2024-25: ~1,320 games ✅
- 2025-26: ~753 games ✅

**Phase 3 (Analytics)**:
- 2021-22: ~1,255 games (❌ missing ~135 playoff games)
- 2022-23: ~1,240 games (❌ missing ~144 playoff games)
- 2023-24: ~1,230 games (❌ missing ~152 playoff games)
- 2024-25: ~1,320 games ✅
- 2025-26: ~405 games ✅

**Phase 5B (Grading)**:
- 2021-22: ✅ ~113k graded
- 2022-23: ✅ ~104k graded
- 2023-24: ✅ ~96k graded
- 2024-25: ❌ only 1 record
- 2025-26: ⚪ current season

### Action: Run Validation

```bash
# Save queries to file
cat > /tmp/validation_queries.sql << 'EOF'
[paste all queries above]
EOF

# Run validation and save results
bq query --use_legacy_sql=false --format=pretty \
  < /tmp/validation_queries.sql \
  > /tmp/validation_results_before.txt 2>&1

# Review results
less /tmp/validation_results_before.txt
```

---

## 📋 Step 1: Phase 3 Analytics Backfill (2-3 hours)

**Goal**: Fill playoff gaps in analytics (2021-22, 2022-23, 2023-24 seasons)

### 1.1: Preparation

```bash
cd /home/naji/code/nba-stats-scraper

# Verify backfill script exists
ls -la backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py

# Check script help
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --help
```

### 1.2: Execute Phase 3 Backfill - 2021-22 Playoffs

```bash
# 2021-22 NBA Playoffs: April 16 - June 17, 2022
# Expected: ~135 playoff games

echo "=== Starting Phase 3 Backfill: 2021-22 Playoffs ==="
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-04-16 \
  --end-date 2022-06-17

# Expected output: Day-by-day processing with checkpoint saves
# Duration: ~45-60 minutes
```

**Validation Checkpoint**:
```sql
-- Should show ~135 playoff games
SELECT
  COUNT(DISTINCT game_code) as playoff_games,
  COUNT(*) as player_records
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year = 2021
  AND game_date >= '2022-04-16'
  AND game_date <= '2022-06-17';
```

### 1.3: Execute Phase 3 Backfill - 2022-23 Playoffs

```bash
# 2022-23 NBA Playoffs: April 15 - June 13, 2023
# Expected: ~144 playoff games

echo "=== Starting Phase 3 Backfill: 2022-23 Playoffs ==="
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2023-04-15 \
  --end-date 2023-06-13

# Duration: ~45-60 minutes
```

**Validation Checkpoint**:
```sql
SELECT
  COUNT(DISTINCT game_code) as playoff_games,
  COUNT(*) as player_records
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year = 2022
  AND game_date >= '2023-04-15'
  AND game_date <= '2023-06-13';
```

### 1.4: Execute Phase 3 Backfill - 2023-24 Playoffs

```bash
# 2023-24 NBA Playoffs: April 16 - June 18, 2024
# Expected: ~152 playoff games (longer playoffs)

echo "=== Starting Phase 3 Backfill: 2023-24 Playoffs ==="
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2024-04-16 \
  --end-date 2024-06-18

# Duration: ~45-60 minutes
```

**Validation Checkpoint**:
```sql
SELECT
  COUNT(DISTINCT game_code) as playoff_games,
  COUNT(*) as player_records
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year = 2023
  AND game_date >= '2024-04-16'
  AND game_date <= '2024-06-18';
```

### 1.5: Phase 3 Final Validation

```sql
-- All seasons should now be complete
SELECT
  season_year,
  COUNT(DISTINCT game_code) as total_games,
  COUNT(DISTINCT CASE
    WHEN game_date >= CASE
      WHEN season_year = 2021 THEN '2022-04-16'
      WHEN season_year = 2022 THEN '2023-04-15'
      WHEN season_year = 2023 THEN '2024-04-16'
    END
    THEN game_code
  END) as playoff_games
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year IN (2021, 2022, 2023)
GROUP BY season_year
ORDER BY season_year;

-- Expected:
-- 2021: ~1,390 total games, ~135 playoff games
-- 2022: ~1,384 total games, ~144 playoff games
-- 2023: ~1,382 total games, ~152 playoff games
```

---

## 📋 Step 2: Phase 4 Precompute Backfill (1-2 hours)

**Goal**: Generate ML features for playoff dates

### 2.1: Verify Phase 4 Script

```bash
# Check Phase 4 orchestrator script
ls -la bin/backfill/run_phase4_backfill.sh

# Review script to understand options
cat bin/backfill/run_phase4_backfill.sh | grep -A 10 "Usage"
```

### 2.2: Execute Phase 4 Backfill - 2021-22 Playoffs

```bash
echo "=== Starting Phase 4 Backfill: 2021-22 Playoffs ==="

# Run Phase 4 orchestrator for playoff dates
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2022-04-16 \
  --end-date 2022-06-17

# This will run 5 processors in dependency order:
# 1. team_defense_zone_analysis (parallel)
# 2. player_shot_zone_analysis (parallel)
# 3. player_composite_factors (sequential - depends on above)
# 4. player_daily_cache (sequential - depends on composite_factors)
# 5. ml_feature_store (sequential - depends on player_daily_cache)

# Duration: ~20-30 minutes
```

**Validation Checkpoint**:
```sql
-- Check all 5 Phase 4 tables
SELECT 'player_composite_factors' as table_name, COUNT(DISTINCT game_date) as playoff_dates
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2022-04-16' AND game_date <= '2022-06-17'

UNION ALL

SELECT 'ml_feature_store', COUNT(DISTINCT game_date)
FROM `nba-props-platform.nba_precompute.ml_feature_store`
WHERE game_date >= '2022-04-16' AND game_date <= '2022-06-17'

UNION ALL

SELECT 'player_shot_zone_analysis', COUNT(DISTINCT game_date)
FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
WHERE game_date >= '2022-04-16' AND game_date <= '2022-06-17';

-- Expected: ~62 playoff dates for 2021-22
```

### 2.3: Execute Phase 4 Backfill - 2022-23 Playoffs

```bash
echo "=== Starting Phase 4 Backfill: 2022-23 Playoffs ==="

./bin/backfill/run_phase4_backfill.sh \
  --start-date 2023-04-15 \
  --end-date 2023-06-13

# Duration: ~20-30 minutes
```

**Validation Checkpoint**:
```sql
SELECT COUNT(DISTINCT game_date) as playoff_dates
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2023-04-15' AND game_date <= '2023-06-13';
-- Expected: ~60 dates
```

### 2.4: Execute Phase 4 Backfill - 2023-24 Playoffs

```bash
echo "=== Starting Phase 4 Backfill: 2023-24 Playoffs ==="

./bin/backfill/run_phase4_backfill.sh \
  --start-date 2024-04-16 \
  --end-date 2024-06-18

# Duration: ~20-30 minutes
```

**Validation Checkpoint**:
```sql
SELECT COUNT(DISTINCT game_date) as playoff_dates
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2024-04-16' AND game_date <= '2024-06-18';
-- Expected: ~64 dates
```

### 2.5: Phase 4 Final Validation

```sql
-- All playoff dates should be complete
WITH playoff_dates AS (
  SELECT '2021-22' as season, '2022-04-16' as start_date, '2022-06-17' as end_date
  UNION ALL
  SELECT '2022-23', '2023-04-15', '2023-06-13'
  UNION ALL
  SELECT '2023-24', '2024-04-16', '2024-06-18'
)
SELECT
  p.season,
  COUNT(DISTINCT f.game_date) as dates_with_features,
  DATE_DIFF(DATE(p.end_date), DATE(p.start_date), DAY) + 1 as total_days
FROM playoff_dates p
LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` f
  ON f.game_date >= DATE(p.start_date)
  AND f.game_date <= DATE(p.end_date)
GROUP BY p.season, p.start_date, p.end_date;

-- Expected: High coverage (not all days have games, so won't be 100% of days)
```

---

## 📋 Step 3: Phase 5 Predictions Backfill (1 hour)

**Goal**: Generate predictions for playoff games

### 3.1: Check Prediction Coordinator Status

```bash
# Get auth token
TOKEN=$(gcloud auth print-identity-token)

# Check coordinator health
curl -s -H "Authorization: Bearer $TOKEN" \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/health

# Check if there's a batch currently running
curl -s -H "Authorization: Bearer $TOKEN" \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status
```

### 3.2: Trigger Predictions - 2021-22 Playoffs

```bash
echo "=== Starting Phase 5 Predictions: 2021-22 Playoffs ==="

TOKEN=$(gcloud auth print-identity-token)

# Start prediction batch
RESPONSE=$(curl -s -X POST \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2022-04-16",
    "end_date": "2022-06-17",
    "force": false
  }')

echo "$RESPONSE"

# Extract batch_id from response
BATCH_ID=$(echo "$RESPONSE" | jq -r '.batch_id')
echo "Batch ID: $BATCH_ID"

# Monitor progress (run this periodically)
while true; do
  STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status?batch_id=$BATCH_ID")

  echo "$(date): $STATUS"

  IS_COMPLETE=$(echo "$STATUS" | jq -r '.progress.is_complete')
  if [ "$IS_COMPLETE" = "true" ]; then
    echo "✅ Predictions complete for 2021-22 playoffs"
    break
  fi

  sleep 30
done
```

**Validation Checkpoint**:
```sql
SELECT
  COUNT(DISTINCT game_id) as playoff_games,
  COUNT(*) as predictions,
  COUNT(DISTINCT player_id) as players
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE season_year = 2021
  AND game_date >= '2022-04-16'
  AND game_date <= '2022-06-17';
-- Expected: ~135 games, thousands of predictions
```

### 3.3: Trigger Predictions - 2022-23 Playoffs

```bash
echo "=== Starting Phase 5 Predictions: 2022-23 Playoffs ==="

TOKEN=$(gcloud auth print-identity-token)

curl -X POST \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2023-04-15",
    "end_date": "2023-06-13"
  }'

# Monitor with status endpoint
# Duration: ~15-20 minutes
```

**Validation Checkpoint**:
```sql
SELECT COUNT(DISTINCT game_id) as playoff_games, COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE season_year = 2022
  AND game_date >= '2023-04-15' AND game_date <= '2023-06-13';
```

### 3.4: Trigger Predictions - 2023-24 Playoffs

```bash
echo "=== Starting Phase 5 Predictions: 2023-24 Playoffs ==="

TOKEN=$(gcloud auth print-identity-token)

curl -X POST \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2024-04-16",
    "end_date": "2024-06-18"
  }'

# Monitor and wait for completion
```

**Validation Checkpoint**:
```sql
SELECT COUNT(DISTINCT game_id) as playoff_games, COUNT(*) as predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE season_year = 2023
  AND game_date >= '2024-04-16' AND game_date <= '2024-06-18';
```

### 3.5: Phase 5 Final Validation

```sql
-- All playoff predictions should exist
SELECT
  season_year,
  COUNT(DISTINCT game_id) as total_games,
  COUNT(DISTINCT CASE
    WHEN game_date >= CASE
      WHEN season_year = 2021 THEN '2022-04-16'
      WHEN season_year = 2022 THEN '2023-04-15'
      WHEN season_year = 2023 THEN '2024-04-16'
    END
    THEN game_id
  END) as playoff_games,
  COUNT(*) as total_predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE season_year IN (2021, 2022, 2023)
GROUP BY season_year
ORDER BY season_year;
```

---

## 📋 Step 4: Phase 5B Grading Backfill (1-2 hours)

**Goal**: Grade predictions for 2024-25 season

### 4.1: Explore Grading Scripts

```bash
# Find grading backfill script
ls -la backfill_jobs/prediction/

# Look for grading functionality
find . -name "*grade*" -o -name "*accuracy*" | grep -E "\.(py|sh)$"

# Check if player_prop_predictions_backfill has grading option
cat backfill_jobs/prediction/player_prop_predictions_backfill.py | grep -i grade
```

### 4.2: Investigate Grading Process

**Need to determine**:
1. Is there a separate grading backfill script?
2. Or is grading part of prediction generation?
3. What's the exact command to grade historical predictions?

```bash
# Search for how grading was done previously
grep -r "prediction_accuracy" --include="*.py" backfill_jobs/

# Look at Phase 5B processor
ls -la data_processors/prediction/

# Check if there's a grading processor
find data_processors/prediction -name "*grade*" -o -name "*accuracy*"
```

### 4.3: Execute Grading Backfill

**Option A: If separate grading script exists**:
```bash
# Example (exact command TBD based on exploration)
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/prediction/grade_predictions_backfill.py \
  --start-date 2024-10-22 \
  --end-date 2025-04-30
```

**Option B: If grading is part of prediction coordinator**:
```bash
TOKEN=$(gcloud auth print-identity-token)

# Trigger grading via coordinator
curl -X POST \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/grade \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2024-10-22",
    "end_date": "2025-04-30"
  }'
```

**Option C: If need to run grading processor directly**:
```bash
# Process grading for 2024-25 season
PYTHONPATH=. .venv/bin/python \
  data_processors/prediction/prediction_grading_processor.py \
  --start-date 2024-10-22 \
  --end-date 2025-04-30
```

### 4.4: Validation Checkpoint

```sql
-- Should see ~100k-110k graded predictions for 2024-25
SELECT
  COUNT(*) as graded_predictions,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_id) as players,
  AVG(absolute_error) as avg_mae,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE season_year = 2024;

-- Expected:
-- - graded_predictions: ~100,000-110,000 (vs current 1)
-- - games: ~1,300
-- - MAE: ~3-5 points
-- - accuracy: ~60-70%
```

### 4.5: Phase 5B Final Validation

```sql
-- All seasons should have grading
SELECT
  season_year,
  COUNT(*) as graded_predictions,
  COUNT(DISTINCT game_id) as games,
  MIN(game_date) as first_game,
  MAX(game_date) as last_game,
  AVG(absolute_error) as mae,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE season_year IN (2021, 2022, 2023, 2024)
GROUP BY season_year
ORDER BY season_year;

-- Expected:
-- 2021: ~113k graded ✅
-- 2022: ~104k graded ✅
-- 2023: ~96k graded ✅
-- 2024: ~100k-110k graded (NEW!)
```

---

## 📋 Step 5: Final Validation (30 minutes)

**Goal**: Confirm 100% data completeness across all phases

### 5.1: Run Complete Validation Suite

```bash
# Re-run all validation queries
bq query --use_legacy_sql=false --format=pretty \
  < /tmp/validation_queries.sql \
  > /tmp/validation_results_after.txt 2>&1

# Compare before vs after
diff /tmp/validation_results_before.txt /tmp/validation_results_after.txt
```

### 5.2: Completeness Matrix

```sql
-- Final completeness check
WITH phase_counts AS (
  SELECT 'Phase 2: BDL Raw' as phase, season_year, COUNT(DISTINCT game_date) as dates
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE season_year IN (2021, 2022, 2023, 2024)
  GROUP BY season_year

  UNION ALL

  SELECT 'Phase 3: Analytics', season_year, COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE season_year IN (2021, 2022, 2023, 2024)
  GROUP BY season_year

  UNION ALL

  SELECT 'Phase 4: Precompute', EXTRACT(YEAR FROM game_date) - 1, COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE EXTRACT(YEAR FROM game_date) BETWEEN 2022 AND 2025
  GROUP BY EXTRACT(YEAR FROM game_date)

  UNION ALL

  SELECT 'Phase 5: Predictions', season_year, COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE season_year IN (2021, 2022, 2023, 2024)
  GROUP BY season_year

  UNION ALL

  SELECT 'Phase 5B: Grading', season_year, COUNT(DISTINCT game_date)
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE season_year IN (2021, 2022, 2023, 2024)
  GROUP BY season_year
)
SELECT
  season_year,
  SUM(CASE WHEN phase = 'Phase 2: BDL Raw' THEN dates ELSE 0 END) as phase2,
  SUM(CASE WHEN phase = 'Phase 3: Analytics' THEN dates ELSE 0 END) as phase3,
  SUM(CASE WHEN phase = 'Phase 4: Precompute' THEN dates ELSE 0 END) as phase4,
  SUM(CASE WHEN phase = 'Phase 5: Predictions' THEN dates ELSE 0 END) as phase5,
  SUM(CASE WHEN phase = 'Phase 5B: Grading' THEN dates ELSE 0 END) as phase5b,
  -- Check completeness
  CASE
    WHEN SUM(CASE WHEN phase = 'Phase 2: BDL Raw' THEN dates ELSE 0 END) =
         SUM(CASE WHEN phase = 'Phase 3: Analytics' THEN dates ELSE 0 END)
    THEN '✅ Complete'
    ELSE '❌ Gap exists'
  END as status
FROM phase_counts
GROUP BY season_year
ORDER BY season_year;

-- Expected: All seasons show "✅ Complete"
```

### 5.3: Playoff-Specific Validation

```sql
-- Verify all playoff games are in all phases
WITH playoff_ranges AS (
  SELECT 2021 as season_year, DATE('2022-04-16') as start_date, DATE('2022-06-17') as end_date
  UNION ALL SELECT 2022, DATE('2023-04-15'), DATE('2023-06-13')
  UNION ALL SELECT 2023, DATE('2024-04-16'), DATE('2024-06-18')
),
phase_counts AS (
  SELECT
    pr.season_year,
    'Phase 2' as phase,
    COUNT(DISTINCT p2.game_date) as dates
  FROM playoff_ranges pr
  LEFT JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` p2
    ON p2.game_date BETWEEN pr.start_date AND pr.end_date
    AND p2.season_year = pr.season_year
  GROUP BY pr.season_year

  UNION ALL

  SELECT
    pr.season_year,
    'Phase 3',
    COUNT(DISTINCT p3.game_date)
  FROM playoff_ranges pr
  LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` p3
    ON p3.game_date BETWEEN pr.start_date AND pr.end_date
    AND p3.season_year = pr.season_year
  GROUP BY pr.season_year

  UNION ALL

  SELECT
    pr.season_year,
    'Phase 4',
    COUNT(DISTINCT p4.game_date)
  FROM playoff_ranges pr
  LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` p4
    ON p4.game_date BETWEEN pr.start_date AND pr.end_date
  GROUP BY pr.season_year

  UNION ALL

  SELECT
    pr.season_year,
    'Phase 5',
    COUNT(DISTINCT p5.game_date)
  FROM playoff_ranges pr
  LEFT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` p5
    ON p5.game_date BETWEEN pr.start_date AND pr.end_date
    AND p5.season_year = pr.season_year
  GROUP BY pr.season_year
)
SELECT
  season_year,
  SUM(CASE WHEN phase = 'Phase 2' THEN dates ELSE 0 END) as phase2,
  SUM(CASE WHEN phase = 'Phase 3' THEN dates ELSE 0 END) as phase3,
  SUM(CASE WHEN phase = 'Phase 4' THEN dates ELSE 0 END) as phase4,
  SUM(CASE WHEN phase = 'Phase 5' THEN dates ELSE 0 END) as phase5
FROM phase_counts
GROUP BY season_year
ORDER BY season_year;

-- Expected: All phases should have same number of dates per season
```

### 5.4: Record Counts Validation

```sql
-- Ensure reasonable record counts (sanity check)
SELECT
  'Phase 2: BDL Raw' as phase,
  COUNT(*) as total_records,
  COUNT(*) / COUNT(DISTINCT game_id) as avg_players_per_game
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE season_year IN (2021, 2022, 2023, 2024)

UNION ALL

SELECT
  'Phase 3: Analytics',
  COUNT(*),
  COUNT(*) / COUNT(DISTINCT game_code)
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year IN (2021, 2022, 2023, 2024)

UNION ALL

SELECT
  'Phase 4: Precompute',
  COUNT(*),
  NULL
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date >= '2021-10-01' AND game_date < '2025-07-01'

UNION ALL

SELECT
  'Phase 5: Predictions',
  COUNT(*),
  COUNT(*) / COUNT(DISTINCT game_id)
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE season_year IN (2021, 2022, 2023, 2024)

UNION ALL

SELECT
  'Phase 5B: Grading',
  COUNT(*),
  COUNT(*) / COUNT(DISTINCT game_id)
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE season_year IN (2021, 2022, 2023, 2024);

-- Sanity checks:
-- - Phase 2: ~25-30 players per game
-- - Phase 3: ~25-30 players per game
-- - Phase 5: ~200-300 predictions per game (multiple prop types)
-- - Phase 5B: ~200-300 graded per game
```

---

## 📋 Step 6: Documentation (30 minutes)

### 6.1: Create Completion Report

```bash
cat > /home/naji/code/nba-stats-scraper/docs/08-projects/current/backfill-system-analysis/BACKFILL-COMPLETION-REPORT.md << 'EOF'
# Backfill Completion Report

**Date**: 2026-01-02
**Executor**: [Your name]
**Status**: ✅ COMPLETE
**Duration**: [X hours]

## Summary

Successfully backfilled all missing data across 4 historical seasons (2021-2025):
- Phase 3 Analytics: 430 playoff games added
- Phase 4 Precompute: 186 playoff dates processed
- Phase 5 Predictions: Playoff predictions generated
- Phase 5B Grading: 2024-25 season graded (~100k predictions)

## Before vs After

### Phase 3 Analytics (2021-24 Playoffs)
- Before: 0 playoff games
- After: ~430 playoff games
- Status: ✅ 100% complete

### Phase 4 Precompute (2021-24 Playoffs)
- Before: 0 playoff dates
- After: ~186 playoff dates
- Status: ✅ 100% complete

### Phase 5B Grading (2024-25 Season)
- Before: 1 test record
- After: ~100,000-110,000 graded predictions
- Status: ✅ 100% complete

## Validation Results

[Paste final validation query results here]

## Issues Encountered

[Document any issues and how they were resolved]

## Next Steps

1. ✅ All historical data backfill complete
2. ⏭️ Ready for ML model training (see ml-model-development/)
3. ⏭️ Consider P1-P3 backfill system improvements

## References

- Root cause analysis: `ROOT-CAUSE-ANALYSIS.md`
- Execution plan: `COMPLETE-BACKFILL-EXECUTION-PLAN.md`
- Validation queries: `/tmp/validation_queries.sql`

EOF
```

### 6.2: Update ML Project Docs

```bash
# Update ML project README with new data availability
cat >> /home/naji/code/nba-stats-scraper/docs/08-projects/current/ml-model-development/README.md << 'EOF'

---

## 🎉 UPDATE: Historical Data Backfill Complete (2026-01-02)

**All gaps filled!**
- ✅ 2021-24 playoff data now in Phase 3-5 (430 games added)
- ✅ 2024-25 grading complete (~100k predictions graded)
- ✅ 4 complete seasons ready for ML training (2021-2024)
- ✅ Total: ~425k graded predictions available

**Impact on ML work**:
- Can now train on playoff data if desired
- 30% more training data available
- Better model generalization (includes high-stakes games)

See: `docs/08-projects/current/backfill-system-analysis/BACKFILL-COMPLETION-REPORT.md`

EOF
```

### 6.3: Update Session Handoff

Create a new handoff document:

```bash
cat > /home/naji/code/nba-stats-scraper/docs/09-handoff/2026-01-02-BACKFILL-COMPLETE.md << 'EOF'
# Session Handoff: Complete Historical Backfill Executed

**Date**: 2026-01-02
**Duration**: ~[X hours]
**Status**: ✅ ALL GAPS FILLED

## What Was Done

1. **Root Cause Analysis** - Identified 5 systematic backfill problems
2. **Comprehensive Validation** - Validated all 5 seasons across all 6 phases
3. **Systematic Backfill** - Filled all identified gaps:
   - Phase 3: 430 playoff games
   - Phase 4: 186 playoff dates
   - Phase 5: Playoff predictions
   - Phase 5B: 2024-25 season grading

## Key Outcomes

✅ **Zero data gaps** - All 4 historical seasons (2021-2024) now complete
✅ **ML ready** - 425k graded predictions available for training
✅ **System understood** - Documented why gaps existed and how to prevent
✅ **Process documented** - Future backfills can follow same pattern

## Documents Created

1. `ROOT-CAUSE-ANALYSIS.md` - Why gaps existed (11k words)
2. `GAMEPLAN.md` - P0-P3 improvement roadmap
3. `COMPLETE-BACKFILL-EXECUTION-PLAN.md` - Step-by-step execution guide
4. `BACKFILL-COMPLETION-REPORT.md` - What was backfilled

## Next Session Focus

**Recommended**: Start ML work (evaluation or training)

All data is now complete and validated. No backfill blockers remain.

See: `ml-model-development/README.md` for ML quick start.

EOF
```

---

## ✅ Success Criteria

Backfill is **COMPLETE** when ALL of these pass:

### ✅ Phase 3 Criteria
```sql
-- All seasons should match Phase 2 counts (within 1-2% for data quality)
SELECT season_year,
  COUNT(DISTINCT game_code) >= 1380 as is_complete
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE season_year IN (2021, 2022, 2023)
GROUP BY season_year;
-- All should be TRUE
```

### ✅ Phase 4 Criteria
```sql
-- Phase 4 should have ~same dates as Phase 3
WITH p3_dates AS (
  SELECT COUNT(DISTINCT game_date) as cnt
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE season_year IN (2021, 2022, 2023)
),
p4_dates AS (
  SELECT COUNT(DISTINCT game_date) as cnt
  FROM `nba-props-platform.nba_precompute.player_composite_factors`
  WHERE game_date >= '2021-10-01' AND game_date < '2024-07-01'
)
SELECT
  p3.cnt as phase3_dates,
  p4.cnt as phase4_dates,
  ABS(p3.cnt - p4.cnt) <= 10 as is_complete  -- Allow small variance
FROM p3_dates p3, p4_dates p4;
-- is_complete should be TRUE
```

### ✅ Phase 5B Criteria
```sql
-- 2024-25 should have ~100k graded predictions
SELECT
  season_year,
  COUNT(*) >= 100000 as is_complete
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE season_year = 2024
GROUP BY season_year;
-- is_complete should be TRUE
```

### ✅ Playoff Criteria
```sql
-- Each playoff season should have ~130-150 games across all phases
WITH playoff_games AS (
  SELECT
    season_year,
    COUNT(DISTINCT game_code) as analytics_games
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE season_year IN (2021, 2022, 2023)
    AND game_date >= CASE
      WHEN season_year = 2021 THEN '2022-04-16'
      WHEN season_year = 2022 THEN '2023-04-15'
      WHEN season_year = 2023 THEN '2024-04-16'
    END
  GROUP BY season_year
)
SELECT
  season_year,
  analytics_games,
  analytics_games >= 130 as is_complete
FROM playoff_games;
-- All is_complete should be TRUE
```

---

## 🚨 Troubleshooting

### Issue: Phase 3 Backfill Script Fails

**Symptoms**: Script crashes with BigQuery 413 error or timeout

**Solution**:
```bash
# Use smaller date ranges
# Instead of full playoff range, do 1-2 weeks at a time

# Example: Break 2021-22 playoffs into smaller chunks
PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-04-16 --end-date 2022-04-30

PYTHONPATH=. .venv/bin/python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-05-01 --end-date 2022-05-15

# Continue in chunks...
```

### Issue: Phase 4 Script Times Out

**Symptoms**: run_phase4_backfill.sh exceeds 6-hour timeout

**Solution**:
```bash
# Use --start-from flag to resume from specific processor
./bin/backfill/run_phase4_backfill.sh \
  --start-date 2022-04-16 --end-date 2022-06-17 \
  --start-from 3  # Start from processor #3 (player_composite_factors)
```

### Issue: Prediction Coordinator Returns 409 Conflict

**Symptoms**: "Batch already in progress" error

**Solution**:
```bash
# Check current batch status
TOKEN=$(gcloud auth print-identity-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/status

# Wait for current batch to complete, or use force flag
curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"start_date": "2022-04-16", "end_date": "2022-06-17", "force": true}'
```

### Issue: Grading Script Not Found

**Symptoms**: Can't find Phase 5B grading backfill script

**Investigation**:
```bash
# Search for grading functionality
grep -r "prediction_accuracy" --include="*.py" .

# Check if grading is part of prediction generation
cat services/prediction_coordinator/main.py | grep -i grade

# Look for grading processor
find data_processors -name "*grade*" -o -name "*accuracy*"
```

**Escalation**: If grading script truly doesn't exist, may need to:
1. Run predictions first, then manually grade
2. Or write a new grading script based on existing processor logic

---

## 📊 Estimated Timeline

| Phase | Task | Duration | Dependencies |
|-------|------|----------|--------------|
| 0 | Initial validation | 30 min | None |
| 1 | Phase 3: 2021-22 playoffs | 45-60 min | Phase 2 complete |
| 1 | Phase 3: 2022-23 playoffs | 45-60 min | Phase 2 complete |
| 1 | Phase 3: 2023-24 playoffs | 45-60 min | Phase 2 complete |
| 2 | Phase 4: 2021-22 playoffs | 20-30 min | Phase 3 complete |
| 2 | Phase 4: 2022-23 playoffs | 20-30 min | Phase 3 complete |
| 2 | Phase 4: 2023-24 playoffs | 20-30 min | Phase 3 complete |
| 3 | Phase 5: All playoffs | 45-60 min | Phase 4 complete |
| 4 | Phase 5B: 2024-25 grading | 1-2 hours | Phase 5 complete |
| 5 | Final validation | 30 min | All complete |
| 6 | Documentation | 30 min | All complete |
| **TOTAL** | **Full backfill** | **6-8 hours** | |

---

## 🎯 Quick Start

**Ready to execute? Run these commands:**

```bash
# Step 1: Navigate to project
cd /home/naji/code/nba-stats-scraper

# Step 2: Run initial validation (save results)
bq query --use_legacy_sql=false --format=pretty \
  "SELECT season_year, COUNT(DISTINCT game_code) as games
   FROM \`nba-props-platform.nba_analytics.player_game_summary\`
   WHERE season_year IN (2021, 2022, 2023)
   GROUP BY season_year" \
  > /tmp/validation_before.txt

# Step 3: Start Phase 3 backfill (first playoff period)
PYTHONPATH=. .venv/bin/python \
  backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py \
  --start-date 2022-04-16 --end-date 2022-06-17

# Step 4: Continue with remaining steps from this plan...
```

**OR use the master backfill script** (after creating it in P1):
```bash
./bin/backfill/run_full_backfill.sh \
  --start-date 2022-04-16 --end-date 2024-06-18 \
  --phases 3,4,5
```

---

**Ready to backfill? Let's fill those gaps! 🚀**
