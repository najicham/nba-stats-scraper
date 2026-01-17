# MLB Prediction System - Complete Inventory & Backfill Plan

**Date:** 2026-01-16
**Purpose:** Document current state and create full 4-season (2022-2025) backfill plan
**Status:** Planning phase - ready to execute

---

## Table of Contents
1. [Current System Inventory](#current-system-inventory)
2. [Model Training Data](#model-training-data)
3. [Data Availability Matrix](#data-availability-matrix)
4. [Analytics Pipeline Dependencies](#analytics-pipeline-dependencies)
5. [Full Backfill Execution Plan](#full-backfill-execution-plan)
6. [Validation Checkpoints](#validation-checkpoints)

---

## 1. Current System Inventory

### Models in Production/Staging

| Model ID | Type | Version | Location | Status | Performance |
|----------|------|---------|----------|--------|-------------|
| `mlb_pitcher_strikeouts_v1_20260107` | Regressor | V1 | ✅ GCS + Database | 🟢 Production | 67.3% win rate, 1.46 MAE |
| `mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149` | Classifier | V1.6 | ⚠️ Local only | 🟡 Staged | 56.4% test hit rate |

### Current Predictions in Database

| Model | Seasons | Predictions | Pitchers | Date Range | Graded | Win Rate | MAE |
|-------|---------|-------------|----------|------------|--------|----------|-----|
| V1 | 2024-2025 | 8,130 | 340 | 2024-04-09 to 2025-09-28 | 88.5% | **67.3%** | **1.46** |
| V1.6 | None | 0 | 0 | N/A | N/A | N/A | N/A |

### Analytics Tables

| Table | Type | Seasons Available | Records | Purpose |
|-------|------|-------------------|---------|---------|
| `mlb_analytics.pitcher_game_summary` | TABLE | 2024-2025 | 9,247 | Core features (f00-f28) |
| `mlb_analytics.pitcher_rolling_statcast` | VIEW | 2024-2025 | 39,918 | V1.6 features (f50-f53) |
| `mlb_analytics.batter_game_summary` | TABLE | 2024-2025 | ? | Opponent analysis |
| `mlb_predictions.pitcher_strikeouts` | TABLE | 2024-2025 | 8,130 | Prediction storage |

**Source for pitcher_rolling_statcast:**
- ✅ VIEW based on `mlb_raw.statcast_pitcher_game_stats`
- ✅ Calculates rolling averages via SQL window functions
- ✅ No processor needed - automatically available when raw data exists

### Raw Data Tables

| Table | Purpose | Seasons Checked | Records (2024-2025) | Status |
|-------|---------|-----------------|---------------------|--------|
| `mlb_raw.mlb_pitcher_stats` | Game-level pitcher stats | ✅ | ? | ✅ Primary source |
| `mlb_raw.bdl_pitcher_stats` | Alternative pitcher stats | ✅ | ? | ✅ Backup source |
| `mlb_raw.statcast_pitcher_game_stats` | Statcast features | ⏸️ | 39,918 | ✅ For V1.6 |
| `mlb_raw.bp_pitcher_props` | BettingPros props | ✅ | 6,907 (2022-2025) | ✅ All 4 seasons! |
| `mlb_raw.mlb_game_lineups` | Lineup data | ✅ | ? | ✅ For lineup features |
| `mlb_raw.mlb_lineup_batters` | Batter lineups | ✅ | ? | ✅ For lineup features |

---

## 2. Model Training Data

### V1 Model (Current Production)
```
Model: mlb_pitcher_strikeouts_v1_20260107.json
Status: ✅ Deployed to GCS and production
```

**Training Data:**
- **Date Range:** Unknown (need to check model metadata)
- **Samples:** Unknown
- **Features:** 21 features (f00-f28, excluding V1.6 features)
- **Performance:**
  - **Production (2024-2025):** 67.3% win rate, 1.46 MAE ✅
  - Test metrics: Unknown (need metadata)

**Feature Sources:**
- Rolling stats: `pitcher_game_summary`
- Season aggregates: `pitcher_game_summary`
- Opponent context: `pitcher_game_summary`
- Workload: `pitcher_game_summary`
- Bottom-up: Lineup + batter analytics (f25-f28)

**Notes:**
- ✅ Performing excellently in production
- ✅ Stable and reliable
- ✅ No issues reported
- 📝 Need to extract training metadata

### V1.6 Model (Staged/Not Deployed)
```
Model: mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
Status: ⚠️ Local only, NOT in GCS
```

**Training Data:**
- **Date Range:** `2024-01-01` to `2025-12-31` ✅ Confirmed
- **Samples:** 6,112
- **Features:** 35 features (f00-f53, adds 4 V1.6 features)
- **Performance:**
  - Test accuracy: 63.2%
  - Test AUC: 0.682
  - Walk-forward hit rate: 56.4%
  - Very high OVER (>65%): 63.6% hit rate

**New Features (V1.6):**
- `f50_swstr_pct_last_3`: SwStr% last 3 starts
- `f51_fb_velocity_last_3`: FB velocity last 3 starts
- `f52_swstr_trend`: Recent SwStr% - season baseline
- `f53_velocity_change`: Velocity drop detection

**Feature Sources:**
- All V1 sources +
- **Rolling Statcast:** `pitcher_rolling_statcast` VIEW → `statcast_pitcher_game_stats` raw table
- **BettingPros:** `bp_pitcher_props` (f40-f44)

**Training Query:** `scripts/mlb/training/train_v1_6_rolling.py` lines 117-118:
```sql
WHERE game_date >= '2024-01-01'
  AND game_date <= '2025-12-31'
```

**Notes:**
- ⚠️ Test performance (56.4%) lower than V1 production (67.3%)
- ⚠️ May be classifier vs regressor comparison issue
- ⚠️ Needs real-world validation before replacing V1
- ✅ Model trained and ready for testing

---

## 3. Data Availability Matrix

### Raw Data Existence (2022-2025)

| Data Source | 2022 | 2023 | 2024 | 2025 | Required For | Priority |
|-------------|------|------|------|------|--------------|----------|
| **mlb_pitcher_stats** | ⏸️ | ⏸️ | ✅ | ✅ | Core pitcher stats | 🔴 P0 |
| **bdl_pitcher_stats** | ⏸️ | ⏸️ | ✅ | ✅ | Backup/validation | 🟡 P1 |
| **statcast_pitcher_game_stats** | ⏸️ | ⏸️ | ✅ | ✅ | V1.6 Statcast features | 🔴 P0 (V1.6) |
| **bp_pitcher_props** | ✅ 3,888 | ✅ 3,726 | ✅ 3,211 | ✅ 3,696 | V1.6 BettingPros features | 🟡 P1 (V1.6) |
| **mlb_game_lineups** | ⏸️ | ⏸️ | ✅ | ✅ | Lineup features (f25-f28) | 🟢 P2 |
| **mlb_lineup_batters** | ⏸️ | ⏸️ | ✅ | ✅ | Lineup features (f25-f28) | 🟢 P2 |
| **batter_game_summary** | ❌ | ❌ | ✅ | ✅ | Lineup features (f25-f28) | 🟢 P2 |

Legend:
- ✅ Confirmed exists
- ⏸️ Need to verify (likely exists)
- ❌ Does not exist

### Analytics Tables Status

| Analytics Table | 2022 | 2023 | 2024 | 2025 | Processor Exists | Can Rebuild |
|-----------------|------|------|------|------|------------------|-------------|
| **pitcher_game_summary** | ❌ | ❌ | ✅ 4,614 | ✅ 4,633 | ✅ Yes | ✅ Yes (if raw exists) |
| **pitcher_rolling_statcast** (VIEW) | ❌ | ❌ | ✅ Auto | ✅ Auto | N/A (VIEW) | ✅ Auto (if raw exists) |
| **batter_game_summary** | ❌ | ❌ | ✅ | ✅ | ✅ Yes | ✅ Yes (if raw exists) |

---

## 4. Analytics Pipeline Dependencies

### Dependency Graph

```
Raw Data Sources (mlb_raw)
│
├─── mlb_pitcher_stats (game-level) ──────┐
├─── bdl_pitcher_stats (game-level) ──────┤
│                                          ▼
│                        [pitcher_game_summary_processor]
│                                          │
│                                          ▼
│                            mlb_analytics.pitcher_game_summary
│                                      (TABLE)
│                                          │
│                                          ├─────► V1 Predictions (f00-f28)
│                                          │
│
├─── statcast_pitcher_game_stats ─────────┐
│                                          ▼
│                        mlb_analytics.pitcher_rolling_statcast
│                                       (VIEW - auto-calculated)
│                                          │
│                                          └─────► V1.6 Predictions (f50-f53)
│
├─── bp_pitcher_props ─────────────────────────► V1.6 Predictions (f40-f44)
│
├─── mlb_game_lineups ────────────────────┐
├─── mlb_lineup_batters ──────────────────┤
│                                          ▼
│                        [batter_game_summary_processor]
│                                          │
│                                          ▼
│                            mlb_analytics.batter_game_summary
│                                      (TABLE)
│                                          │
│                                          └─────► V1/V1.6 Predictions (f25-f28)
```

### Processor Details

#### MlbPitcherGameSummaryProcessor
**File:** `data_processors/analytics/mlb/pitcher_game_summary_processor.py`
**Source Table:** `mlb_raw.bdl_pitcher_stats` (primary)
**Target Table:** `mlb_analytics.pitcher_game_summary`
**Strategy:** `MERGE_UPDATE` (per date)

**Features Generated:**
- Rolling K averages (f00-f04): k_avg_last_3, k_avg_last_5, k_avg_last_10, k_std_last_10, ip_avg_last_5
- Season aggregates (f05-f09): season_k_per_9, era_rolling_10, whip_rolling_10, season_games, season_k_total
- Context (f10, f15-f18): is_home, opponent_team_k_rate, ballpark_k_factor, month_of_season, days_into_season
- Workload (f20-f24): days_rest, games_last_30_days, pitch_count_avg, season_ip_total, is_postseason
- Season swing metrics (f19): season_swstr_pct, season_csw_pct, season_chase_pct

**Backfill Support:** ✅ Yes - processes one date at a time

**Command:**
```bash
# Process single date
PYTHONPATH=. python -m data_processors.analytics.mlb.pitcher_game_summary_processor --date 2022-04-07

# Process date range
PYTHONPATH=. python scripts/run_analytics_backfill.py \
  --processor pitcher_game_summary \
  --start-date 2022-04-07 \
  --end-date 2023-10-01
```

#### MlbBatterGameSummaryProcessor
**File:** `data_processors/analytics/mlb/batter_game_summary_processor.py`
**Source Tables:** `mlb_raw.bdl_batter_stats`, lineup tables
**Target Table:** `mlb_analytics.batter_game_summary`
**Strategy:** `MERGE_UPDATE` (per date)

**Features Generated:**
- Batter K rates for lineup analysis
- Historical performance vs pitchers
- Used for bottom-up K calculation (f25-f28)

**Backfill Support:** ✅ Yes - processes one date at a time

#### pitcher_rolling_statcast (VIEW)
**Type:** BigQuery VIEW (auto-calculated)
**Source Table:** `mlb_raw.statcast_pitcher_game_stats`
**Target:** `mlb_analytics.pitcher_rolling_statcast`
**Strategy:** SQL window functions

**Features Generated:**
- Rolling SwStr% (f50): swstr_pct_last_3, swstr_pct_last_5, swstr_pct_last_10
- Rolling velocity (f51): fb_velocity_last_3, fb_velocity_last_5
- Baselines: swstr_pct_season_prior, fb_velocity_season_prior
- Trends (f52, f53): calculated in predictor from rolling stats

**Backfill Support:** ✅ Automatic - no action needed if raw data exists

---

## 5. Full Backfill Execution Plan

### Overview

**Goal:** Generate V1 AND V1.6 predictions for all 4 seasons (2022-2025)
**Total Expected Predictions:** ~17,000 (4,250 per season average)
**Estimated Total Time:** 15-25 hours
**Phases:** 5 phases with validation checkpoints

### Prerequisites Checklist

- [ ] **Verify raw data exists for 2022-2023**
  - [ ] `mlb_raw.mlb_pitcher_stats` or `bdl_pitcher_stats`
  - [ ] `mlb_raw.statcast_pitcher_game_stats` (for V1.6)
  - [ ] `mlb_raw.mlb_game_lineups` and `mlb_lineup_batters`
  - [ ] `mlb_raw.bdl_batter_stats`

- [ ] **Confirm processor functionality**
  - [ ] Test pitcher_game_summary_processor on single 2024 date
  - [ ] Test batter_game_summary_processor on single 2024 date
  - [ ] Verify pitcher_rolling_statcast VIEW works

- [ ] **Storage check**
  - [ ] BigQuery quota sufficient (~50GB analytics data)
  - [ ] GCS bucket has space for models

### Phase 1: Data Verification (2 hours)

**Objective:** Confirm all raw data exists for 2022-2023

#### Step 1.1: Check Raw Pitcher Stats
```sql
-- Check mlb_pitcher_stats
SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as games,
    COUNT(DISTINCT player_lookup) as pitchers,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
FROM `nba-props-platform.mlb_raw.mlb_pitcher_stats`
WHERE game_date >= '2022-01-01' AND game_date < '2024-01-01'
GROUP BY year
ORDER BY year;

-- If empty, check bdl_pitcher_stats
SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as games,
    COUNT(DISTINCT player_lookup) as pitchers,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
FROM `nba-props-platform.mlb_raw.bdl_pitcher_stats`
WHERE game_date >= '2022-01-01' AND game_date < '2024-01-01'
GROUP BY year
ORDER BY year;
```

**Expected Result:** 4,000-5,000 games per year, 200-300 pitchers

**If missing:** ❌ BLOCKER - Cannot proceed without base pitcher stats

#### Step 1.2: Check Statcast Data (for V1.6)
```sql
SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as games,
    COUNT(DISTINCT player_lookup) as pitchers,
    COUNTIF(swstr_pct IS NOT NULL) as has_swstr,
    COUNTIF(fb_velocity_avg IS NOT NULL) as has_velocity
FROM `nba-props-platform.mlb_raw.statcast_pitcher_game_stats`
WHERE game_date >= '2022-01-01' AND game_date < '2024-01-01'
GROUP BY year
ORDER BY year;
```

**Expected Result:** Similar volume to pitcher stats, >95% with SwStr% and velocity

**If missing:** ⚠️ Can still generate V1 predictions, but NOT V1.6

#### Step 1.3: Check Lineup/Batter Data
```sql
-- Check lineup data
SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(DISTINCT game_pk) as games,
    COUNT(*) as lineups
FROM `nba-props-platform.mlb_raw.mlb_game_lineups`
WHERE game_date >= '2022-01-01' AND game_date < '2024-01-01'
GROUP BY year
ORDER BY year;

-- Check batter stats
SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as batter_games,
    COUNT(DISTINCT player_lookup) as batters
FROM `nba-props-platform.mlb_raw.bdl_batter_stats`
WHERE game_date >= '2022-01-01' AND game_date < '2024-01-01'
GROUP BY year
ORDER BY year;
```

**Expected Result:** ~2,400 games per year, lineups for most games

**If missing:** ⚠️ Bottom-up features (f25-f28) will use defaults, still functional

**Validation Checkpoint 1:**
```bash
# Create data availability report
PYTHONPATH=. python scripts/mlb/check_2022_2023_data_availability.py > data_availability_report.txt
```

---

### Phase 2: Rebuild Analytics Tables (8-12 hours)

**Objective:** Populate `pitcher_game_summary` and `batter_game_summary` for 2022-2023

#### Step 2.1: Test Processor on Sample Date
```bash
# Test pitcher_game_summary processor on 2022-04-08 (opening day)
PYTHONPATH=. python -c "
from data_processors.analytics.mlb.pitcher_game_summary_processor import MlbPitcherGameSummaryProcessor
from datetime import date

processor = MlbPitcherGameSummaryProcessor()
result = processor.process_date(date(2022, 4, 8))
print(f'Test result: {result}')
"
```

**Expected:** 10-15 pitcher records for opening day

**If fails:** Debug processor, check raw data schema compatibility

#### Step 2.2: Backfill Pitcher Game Summary (2022)
```bash
# Backfill entire 2022 season
# Estimated time: 3-4 hours (182 dates @ 1 minute each)
PYTHONPATH=. python scripts/mlb/backfill_pitcher_game_summary.py \
  --start-date 2022-04-07 \
  --end-date 2022-10-05 \
  --batch-size 10
```

**Monitoring:**
- Check logs every hour
- Verify row counts match raw data
- Watch for errors/warnings

**Validation Checkpoint 2.1:**
```sql
-- Verify 2022 data
SELECT
    COUNT(*) as records,
    COUNT(DISTINCT player_lookup) as pitchers,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date,
    COUNTIF(k_avg_last_5 IS NOT NULL) as has_rolling_stats
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE season_year = 2022;
```

**Expected:** ~4,500 records, 250-300 pitchers, >90% with rolling stats

#### Step 2.3: Backfill Pitcher Game Summary (2023)
```bash
# Backfill 2023 season
# Estimated time: 3-4 hours
PYTHONPATH=. python scripts/mlb/backfill_pitcher_game_summary.py \
  --start-date 2023-03-30 \
  --end-date 2023-10-01 \
  --batch-size 10
```

**Validation Checkpoint 2.2:**
```sql
-- Verify 2023 data
SELECT
    COUNT(*) as records,
    COUNT(DISTINCT player_lookup) as pitchers,
    MIN(game_date) as first_date,
    MAX(game_date) as last_date
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE season_year = 2023;
```

#### Step 2.4: Backfill Batter Game Summary (Optional for better lineup features)
```bash
# Backfill batter analytics for 2022-2023
# Estimated time: 2-4 hours
# Note: Can skip if willing to use default values for f25-f28

PYTHONPATH=. python scripts/mlb/backfill_batter_game_summary.py \
  --start-date 2022-04-07 \
  --end-date 2023-10-01 \
  --batch-size 10
```

**Decision Point:**
- ✅ Include batter backfill → Better lineup features (f25-f28)
- ⚠️ Skip batter backfill → Faster, use defaults for lineup features

#### Step 2.5: Verify pitcher_rolling_statcast VIEW
```sql
-- Check that VIEW automatically works with new data
SELECT
    EXTRACT(YEAR FROM game_date) as year,
    COUNT(*) as records,
    COUNT(DISTINCT player_lookup) as pitchers,
    COUNTIF(swstr_pct_last_3 IS NOT NULL) as has_rolling_swstr,
    COUNTIF(fb_velocity_last_3 IS NOT NULL) as has_rolling_velocity
FROM `nba-props-platform.mlb_analytics.pitcher_rolling_statcast`
WHERE game_date >= '2022-01-01' AND game_date < '2024-01-01'
GROUP BY year
ORDER BY year;
```

**Expected:** If statcast raw data exists, VIEW should auto-populate

**Validation Checkpoint 2.3:**
```bash
# Comprehensive analytics validation
PYTHONPATH=. python scripts/mlb/validate_analytics_tables.py \
  --seasons 2022,2023 \
  --verbose
```

---

### Phase 3: Upload V1.6 Model & Generate Predictions (4-6 hours)

**Objective:** Deploy V1.6 and generate predictions for all 4 seasons

#### Step 3.1: Upload V1.6 Model to GCS
```bash
# Upload model files
gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
  gs://nba-scraped-data/ml-models/mlb/

gsutil cp models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json \
  gs://nba-scraped-data/ml-models/mlb/

# Verify upload
gsutil ls -lh gs://nba-scraped-data/ml-models/mlb/*v1_6*
```

**Validation:** Confirm both files uploaded (~513 KB + 2 KB)

#### Step 3.2: Test V1.6 Predictor on Sample Date
```bash
# Test V1.6 on a known 2024 date
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
from datetime import date

predictor = PitcherStrikeoutsPredictor(
    model_path='gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json'
)

# Test batch predict
preds = predictor.batch_predict(date(2024, 4, 10))
print(f'Generated {len(preds)} predictions')
print(f'Sample: {preds[0] if preds else None}')
"
```

**Expected:** 10-15 predictions with all 35 features

#### Step 3.3: Generate V1.6 Predictions for 2022
```bash
# Generate predictions for 2022 season
# Estimated time: 1-1.5 hours
PYTHONPATH=. python scripts/mlb/generate_historical_predictions_v16.py \
  --start-date 2022-04-07 \
  --end-date 2022-10-05 \
  --model-version v1.6 \
  --batch-size 30
```

**Expected Output:** ~4,500 predictions

#### Step 3.4: Generate V1.6 Predictions for 2023
```bash
# Generate predictions for 2023 season
# Estimated time: 1-1.5 hours
PYTHONPATH=. python scripts/mlb/generate_historical_predictions_v16.py \
  --start-date 2023-03-30 \
  --end-date 2023-10-01 \
  --model-version v1.6 \
  --batch-size 30
```

**Expected Output:** ~4,500 predictions

#### Step 3.5: Generate V1.6 Predictions for 2024
```bash
# Generate predictions for 2024 season
# Estimated time: 1 hour
PYTHONPATH=. python scripts/mlb/generate_historical_predictions_v16.py \
  --start-date 2024-03-20 \
  --end-date 2024-09-30 \
  --model-version v1.6 \
  --batch-size 30
```

**Expected Output:** ~4,000 predictions

#### Step 3.6: Generate V1.6 Predictions for 2025
```bash
# Generate predictions for 2025 season
# Estimated time: 1 hour
PYTHONPATH=. python scripts/mlb/generate_historical_predictions_v16.py \
  --start-date 2025-03-27 \
  --end-date 2025-09-30 \
  --model-version v1.6 \
  --batch-size 30
```

**Expected Output:** ~4,500 predictions

**Validation Checkpoint 3:**
```sql
-- Check V1.6 prediction counts
SELECT
    season_year,
    COUNT(*) as predictions,
    COUNT(DISTINCT pitcher_lookup) as pitchers,
    COUNT(DISTINCT game_date) as dates
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE model_version LIKE '%v1_6%'
GROUP BY season_year
ORDER BY season_year;
```

**Expected:**
- 2022: ~4,500 predictions
- 2023: ~4,500 predictions
- 2024: ~4,000 predictions
- 2025: ~4,500 predictions
- **Total: ~17,500 predictions**

---

### Phase 4: Grade All Predictions (2-4 hours)

**Objective:** Grade all V1.6 predictions against actual results

#### Step 4.1: Test Grading on Sample Date
```bash
# Test grading processor
PYTHONPATH=. python -c "
from data_processors.grading.mlb.mlb_prediction_grading_processor import MlbPredictionGradingProcessor
from datetime import date

processor = MlbPredictionGradingProcessor()
result = processor.run({'game_date': date(2022, 4, 8)})
print(f'Grading result: {result}')
print(f'Stats: {processor.get_grading_stats()}')
"
```

#### Step 4.2: Grade All V1.6 Predictions
```bash
# Grade all V1.6 predictions (2022-2025)
# Estimated time: 2-4 hours
PYTHONPATH=. python scripts/mlb/grade_all_v16_predictions.py \
  --start-date 2022-04-07 \
  --end-date 2025-09-30 \
  --model-filter v1_6
```

**Validation Checkpoint 4:**
```sql
-- Check grading completeness
SELECT
    season_year,
    COUNT(*) as total_predictions,
    COUNTIF(is_correct IS NOT NULL) as graded,
    COUNTIF(is_correct = TRUE) as wins,
    COUNTIF(is_correct = FALSE) as losses,
    ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate_pct
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE model_version LIKE '%v1_6%'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY season_year
ORDER BY season_year;
```

**Expected:** >95% graded for each season

---

### Phase 5: Comprehensive Validation (2-3 hours)

**Objective:** Validate full system from all angles

#### Step 5.1: Run All Validation Scripts
```bash
# 1. Comprehensive validation
PYTHONPATH=. python scripts/mlb/validate_v1_6_backfill_comprehensive.py \
  --seasons 2022,2023,2024,2025 \
  --verbose

# 2. Statistical analysis
PYTHONPATH=. python scripts/mlb/validate_v1_6_statistical_analysis.py \
  --export-csv

# 3. Compare V1 vs V1.6 (for 2024-2025)
PYTHONPATH=. python scripts/mlb/compare_v1_vs_v16.py \
  --seasons 2024,2025
```

#### Step 5.2: Performance Analysis by Season
```sql
-- V1.6 performance by season
WITH graded AS (
  SELECT
    season_year,
    COUNT(*) as total_bets,
    COUNTIF(is_correct = TRUE) as wins,
    COUNTIF(is_correct = FALSE) as losses,
    AVG(ABS(predicted_strikeouts - actual_strikeouts)) as mae,
    AVG(predicted_strikeouts - actual_strikeouts) as bias
  FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
  WHERE model_version LIKE '%v1_6%'
    AND is_correct IS NOT NULL
  GROUP BY season_year
)
SELECT
  season_year,
  total_bets,
  wins,
  losses,
  ROUND(wins * 100.0 / (wins + losses), 1) as win_rate_pct,
  ROUND(mae, 2) as mae,
  ROUND(bias, 2) as bias
FROM graded
ORDER BY season_year;
```

**Success Criteria:**
- ✅ Win rate >55% for each season
- ✅ MAE <2.0 for each season
- ✅ |Bias| <0.5 (well-calibrated)
- ✅ Coverage >90% for each season
- ✅ No data quality issues

#### Step 5.3: Compare to V1 Baseline (2024-2025 only)
```sql
-- V1 vs V1.6 comparison
SELECT
  CASE
    WHEN model_version LIKE '%v1_6%' THEN 'V1.6'
    ELSE 'V1'
  END as model,
  season_year,
  COUNT(*) as predictions,
  COUNTIF(is_correct = TRUE) as wins,
  ROUND(AVG(CAST(is_correct AS INT64)) * 100, 1) as win_rate,
  ROUND(AVG(ABS(predicted_strikeouts - actual_strikeouts)), 2) as mae
FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
WHERE season_year IN (2024, 2025)
  AND is_correct IS NOT NULL
GROUP BY model, season_year
ORDER BY season_year, model;
```

**Decision Matrix:**

| Scenario | V1.6 Win Rate | Action |
|----------|---------------|--------|
| V1.6 >= V1 | >=67% | ✅ Deploy V1.6 to production |
| V1.6 slightly lower | 60-66% | ⚠️ A/B test V1.6 in parallel |
| V1.6 significantly lower | <60% | ❌ Keep V1, investigate V1.6 issues |

---

## 6. Validation Checkpoints

### Summary of All Checkpoints

| Phase | Checkpoint | Validates | Pass Criteria |
|-------|-----------|-----------|---------------|
| 1 | Data availability | Raw data exists | All key tables have 2022-2023 data |
| 2.1 | 2022 analytics | pitcher_game_summary 2022 | ~4,500 records, >90% complete |
| 2.2 | 2023 analytics | pitcher_game_summary 2023 | ~4,500 records, >90% complete |
| 2.3 | Analytics tables | All analytics tables | Expected row counts, no gaps |
| 3 | V1.6 predictions | Prediction generation | ~17,500 predictions across 4 seasons |
| 4 | Grading | Grading completeness | >95% of predictions graded |
| 5.1 | Comprehensive | All validation scripts pass | No errors, all checks green |
| 5.2 | Performance | Model performance | Win rate >55%, MAE <2.0 |
| 5.3 | V1 comparison | V1.6 vs V1 | V1.6 competitive with V1 |

### Rollback Plan

If validation fails at any checkpoint:

**Checkpoint 1 fails (no raw data):**
- ❌ **STOP** - Cannot proceed without base data
- Action: Investigate raw data ingestion, historical data sources

**Checkpoint 2.x fails (analytics rebuild issues):**
- Rollback: No rollback needed (only adding data)
- Action: Debug processor, check schema compatibility, retry failed dates

**Checkpoint 3 fails (prediction generation issues):**
- Rollback: No rollback needed (V1 predictions unaffected)
- Action: Debug predictor, check feature availability, retry

**Checkpoint 4 fails (grading issues):**
- Rollback: Predictions remain but ungraded
- Action: Debug grading processor, verify mlb_raw.mlb_pitcher_stats

**Checkpoint 5 fails (performance issues):**
- Rollback: Keep V1 in production, flag V1.6 as experimental
- Action: Analyze performance gaps, iterate on model

---

## Quick Reference Commands

### Check Current Status
```bash
# Total predictions by model
bq query --use_legacy_sql=false "
SELECT
  model_version,
  COUNT(*) as predictions,
  MIN(game_date) as first_date,
  MAX(game_date) as last_date
FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\`
GROUP BY model_version
"

# Analytics table status
bq query --use_legacy_sql=false "
SELECT
  season_year,
  COUNT(*) as pitcher_records
FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\`
GROUP BY season_year
ORDER BY season_year
"
```

### Test Processors
```bash
# Test pitcher game summary
PYTHONPATH=. python -m data_processors.analytics.mlb.pitcher_game_summary_processor --date 2022-04-08

# Test prediction generation
PYTHONPATH=. python scripts/mlb/generate_historical_predictions_v16.py \
  --start-date 2022-04-08 \
  --end-date 2022-04-08 \
  --dry-run
```

### Monitor Progress
```bash
# Watch analytics backfill
watch -n 60 "bq query --use_legacy_sql=false 'SELECT season_year, COUNT(*) FROM \`nba-props-platform.mlb_analytics.pitcher_game_summary\` GROUP BY season_year ORDER BY season_year'"

# Watch prediction generation
watch -n 60 "bq query --use_legacy_sql=false 'SELECT DATE(game_date) as date, COUNT(*) as preds FROM \`nba-props-platform.mlb_predictions.pitcher_strikeouts\` WHERE model_version LIKE \"%v1_6%\" GROUP BY date ORDER BY date DESC LIMIT 10'"
```

---

## Files to Create for Execution

### Scripts Needed

1. ✅ `scripts/mlb/check_2022_2023_data_availability.py` - Data verification
2. ✅ `scripts/mlb/backfill_pitcher_game_summary.py` - Analytics backfill
3. ✅ `scripts/mlb/backfill_batter_game_summary.py` - Batter analytics backfill
4. ✅ `scripts/mlb/validate_analytics_tables.py` - Analytics validation
5. ✅ `scripts/mlb/generate_historical_predictions_v16.py` - V1.6 prediction generation
6. ✅ `scripts/mlb/grade_all_v16_predictions.py` - Bulk grading
7. ✅ `scripts/mlb/compare_v1_vs_v16.py` - Model comparison
8. ✅ `scripts/mlb/validate_v1_6_backfill_comprehensive.py` - Already exists
9. ✅ `scripts/mlb/validate_v1_6_statistical_analysis.py` - Already exists

### Documentation to Update

1. ✅ This inventory document (current file)
2. ⏸️ `docs/runbooks/mlb/analytics-backfill-runbook.md` - Step-by-step ops guide
3. ⏸️ `docs/runbooks/mlb/prediction-backfill-runbook.md` - Prediction generation guide
4. ⏸️ `CHANGELOG.md` - Document V1.6 deployment and backfill

---

## Timeline Estimate

| Phase | Activity | Estimated Time | Can Parallelize |
|-------|----------|----------------|-----------------|
| 1 | Data verification | 2 hours | No |
| 2 | Analytics rebuild | 8-12 hours | Partially (2022 & 2023 parallel) |
| 3 | Prediction generation | 4-6 hours | Yes (by season) |
| 4 | Grading | 2-4 hours | Yes (by season) |
| 5 | Validation | 2-3 hours | Partially |
| **Total (Sequential)** | | **18-27 hours** | |
| **Total (Parallelized)** | | **12-18 hours** | With multiple workers |

**Recommended Approach:**
- Run Phase 1 first (2 hours)
- Run Phase 2 with 2 parallel workers (2022 + 2023) - 6 hours
- Run Phase 3 with 4 parallel workers (all seasons) - 2 hours
- Run Phase 4 with 4 parallel workers - 1 hour
- Run Phase 5 sequentially - 3 hours

**Optimized Total: ~14 hours**

---

## Success Metrics

### Backfill Complete When:
- [ ] All raw data verified for 2022-2023
- [ ] pitcher_game_summary populated for 2022-2023 (~9,000 records)
- [ ] pitcher_rolling_statcast VIEW working for 2022-2023
- [ ] V1.6 model uploaded to GCS
- [ ] ~17,500 V1.6 predictions generated (2022-2025)
- [ ] >95% of predictions graded
- [ ] All validation scripts pass
- [ ] Performance metrics acceptable (win rate >55%, MAE <2.0)
- [ ] V1 vs V1.6 comparison complete
- [ ] Documentation updated

### Quality Thresholds:
- ✅ Win rate >55% (profitable)
- ✅ MAE <2.0 (accurate)
- ✅ Coverage >90% per season
- ✅ |Bias| <0.5 (calibrated)
- ✅ Grading >95% complete
- ✅ No data quality issues

---

## Contact & Support

**System Owner:** MLB Prediction Team
**Documentation:** This file + validation findings
**Last Updated:** 2026-01-16
**Status:** ✅ Ready to execute

For questions or issues during backfill:
1. Check validation scripts output
2. Review processor logs
3. Consult this inventory document
4. Check `FINAL_V16_VALIDATION_FINDINGS.md`
