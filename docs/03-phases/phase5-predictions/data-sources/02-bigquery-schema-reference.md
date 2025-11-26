# BigQuery Schema Reference - Phase 5 Predictions

**File:** `docs/predictions/data-sources/02-bigquery-schema-reference.md`
**Created:** 2025-11-17
**Last Updated:** 2025-11-17
**Purpose:** Complete reference for all BigQuery tables in nba_predictions dataset
**Audience:** Engineers working with prediction data, queries, and data access

---

## 📋 Table of Contents

1. [Quick Reference](#quick-reference)
2. [Dataset Overview](#dataset-overview)
3. [Table Organization](#table-organization)
4. [Critical Concept: ml_feature_store_v2 Ownership](#feature-store-ownership)
5. [Table Schemas (11 Tables)](#table-schemas)
6. [Views (5 Views)](#views)
7. [Table Relationships](#table-relationships)
8. [Common Query Patterns](#common-queries)
9. [Deployment & Setup](#deployment)
10. [Monitoring & Health Checks](#monitoring)
11. [Troubleshooting](#troubleshooting)

---

## 🎯 Quick Reference {#quick-reference}

**Dataset:** `nba-props-platform.nba_predictions`
**Total Tables:** 11 tables + 5 views
**Update Schedule:** Daily (6-8 AM ET) + real-time when lines change
**Primary Owner:** Phase 5 Prediction System
**Critical Tables:** `ml_feature_store_v2`, `player_prop_predictions`

**Most Frequently Used Tables:**
| Table | Usage | Updated By | Update Frequency |
|-------|-------|------------|------------------|
| `ml_feature_store_v2` | ⭐⭐⭐ Very High | Phase 4 | Daily (12:00 AM) |
| `player_prop_predictions` | ⭐⭐⭐ Very High | Phase 5 | Daily (6:00 AM) + Real-time |
| `prediction_systems` | ⭐⭐ High | Manual/Deployment | On system changes |
| `feature_versions` | ⭐ Medium | Phase 4 | On feature updates |
| `system_daily_performance` | ⭐ Medium | Phase 5 | Daily (post-game) |

**Schema Files Location:** [`schemas/bigquery/predictions/`](../../../schemas/bigquery/predictions/)

---

## 🏗️ Dataset Overview {#dataset-overview}

### Purpose

The `nba_predictions` dataset stores all prediction-related data for the Phase 5 ML prediction system, including:
- **Features** - 25-feature vectors for ML models (written by Phase 4)
- **Predictions** - All predictions from 5 prediction systems (written by Phase 5)
- **Results** - Actual outcomes vs predictions
- **Performance** - System accuracy and metrics
- **Configuration** - System registry, feature versions, model metadata

### Design Philosophy

**Multi-System Architecture:**
- 5 prediction systems operate independently
- Each system predicts for the same players
- Results stored in single `player_prop_predictions` table with `system_id` field
- Enables system comparison, agreement scoring, ensemble logic

**Array-Based Features:**
- Features stored as `ARRAY<FLOAT64>` instead of individual columns
- Supports feature expansion from 25 → 47+ features WITHOUT schema changes
- Versioned with `feature_version` field

**Phase 4 Writes, Phase 5 Reads:**
- `ml_feature_store_v2` written by Phase 4 (12:00 AM)
- Phase 5 reads cached features (6:00 AM + real-time)
- "Compute once, use many times" optimization

---

## 📊 Table Organization {#table-organization}

### By Ownership

**Written by Phase 4 (Precompute):**
- `ml_feature_store_v2` - Feature vectors for predictions
- `feature_versions` - Feature definitions and metadata

**Written by Phase 5 (Predictions):**
- `prediction_systems` - Registry of prediction systems
- `player_prop_predictions` - All predictions (core table)
- `prediction_results` - Actual outcomes
- `system_daily_performance` - Daily metrics
- `prediction_quality_log` - Data quality tracking

**Written by Phase 5 ML Training:**
- `ml_models` - Trained model registry
- `ml_training_runs` - Training history
- `ml_prediction_metadata` - ML-specific details

**Written by Phase 5 Configuration:**
- `weight_adjustment_log` - Config change history

### By Update Frequency

**Daily (Scheduled):**
- `ml_feature_store_v2` - 12:00 AM (Phase 4)
- `player_prop_predictions` - 6:00 AM (Phase 5 coordinator)
- `system_daily_performance` - Post-game (after results known)

**Real-Time (Event-Driven):**
- `player_prop_predictions` - When prop lines change (9 AM - 7 PM)

**On-Demand:**
- `feature_versions` - When features updated
- `prediction_systems` - When systems added/modified
- `ml_models` - After model training
- `weight_adjustment_log` - When config changed

---

## ⚠️ Critical Concept: ml_feature_store_v2 Ownership {#feature-store-ownership}

### Key Facts

**Table:** `nba_predictions.ml_feature_store_v2`
**Schema File:** [`04_ml_feature_store_v2.sql`](../../../schemas/bigquery/predictions/04_ml_feature_store_v2.sql)
**Written By:** **Phase 4 Precompute Processor** (5th processor, runs 12:00 AM)
**Read By:** **Phase 5 Prediction Systems** (all 5 systems, 6:00 AM+)
**Storage Location:** `nba_predictions` dataset (NOT `nba_precompute`)

### Why It's in nba_predictions Dataset

Although `ml_feature_store_v2` is **written by Phase 4**, it's stored in the **nba_predictions dataset** because:

1. ✅ **Tightly coupled with Phase 5** - Exclusively used by prediction systems
2. ✅ **Works with feature_versions** - Also in predictions dataset
3. ✅ **Dataset location clarity** - Schema file matches physical table location
4. ✅ **No other use cases** - Not used by other precompute operations

### Data Flow Diagram

```
Phase 4 (12:00 AM Nightly)
├─ team_defense_zone_analysis     (nba_precompute)
├─ player_shot_zone_analysis      (nba_precompute)
├─ player_composite_factors       (nba_precompute)
├─ player_daily_cache             (nba_precompute)
└─ ml_feature_store_v2 ← WRITES   (nba_predictions) ⚠️
          ↓
Phase 5 (6:00 AM Daily + Real-time Updates)
├─ Moving Average System  ← READS cached features
├─ Zone Matchup System    ← READS cached features
├─ Similarity System      ← READS cached features
├─ XGBoost ML System      ← READS cached features
└─ Ensemble System        ← READS cached features
```

### Performance Optimization: Compute Once, Use Many

**Without Feature Cache (Inefficient):**
- 450 players × 5 systems = 2,250 feature computations per day
- Each computation: ~25 expensive BigQuery queries
- Total: ~56,250 queries per day
- Duration: ~75 minutes

**With Feature Cache (Efficient):**
- Phase 4 computes features once: 450 players × 25 features = 11,250 values
- Phase 5 reads cached features: 2,250 fast reads
- **Savings:** 50,000+ queries per day, 10x faster predictions
- Duration: ~7.5 minutes

### Feature Generation Schedule

```
12:00 AM - Phase 4 generates features for all 450 players
           • Reads Phase 3 analytics + Phase 4 precompute
           • Computes 25 features per player
           • Writes to ml_feature_store_v2
           • Takes ~10 minutes

6:00 AM  - Phase 5 daily predictions start
           • Reads cached features (instant)
           • Generates 2,250 predictions (450 × 5 systems)
           • Takes ~15 minutes

3:00 PM  - Prop line changes (LeBron: 25.5 → 26.5)
           • Phase 5 re-predicts using SAME cached features
           • Only prediction logic runs (not feature generation)
           • Takes ~10 seconds per player
```

**Important:** Features are generated ONCE per night and reused all day, even when prop lines change.

---

## 📚 Table Schemas (11 Tables) {#table-schemas}

### Table 00: prediction_systems

**Schema File:** [`00_prediction_systems.sql`](../../../schemas/bigquery/predictions/00_prediction_systems.sql)
**Purpose:** Registry of all prediction systems
**Written By:** Manual/Deployment scripts
**Read By:** Phase 5 (routing), Website (system info)

**Schema:**
```sql
CREATE TABLE prediction_systems (
  system_id STRING NOT NULL PRIMARY KEY,
  system_name STRING NOT NULL,
  system_type STRING NOT NULL,  -- 'rule_based', 'ml_model', 'ensemble'
  is_active BOOLEAN DEFAULT TRUE,
  is_champion BOOLEAN DEFAULT FALSE,
  description STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP
)
```

**Key Fields:**
- `system_id` - Unique identifier (e.g., `'moving_average_baseline_v1'`)
- `system_type` - Type of system: `'rule_based'`, `'ml_model'`, `'ensemble'`
- `is_active` - Whether system is currently generating predictions
- `is_champion` - Primary system for website display (only 1 can be TRUE)

**Sample Data:**
```sql
INSERT INTO prediction_systems VALUES
  ('moving_average_baseline_v1', 'Moving Average Baseline', 'rule_based', TRUE, FALSE, 'Simple average of recent games'),
  ('zone_matchup_v1', 'Zone Matchup', 'rule_based', TRUE, FALSE, 'Shot zone vs opponent defense'),
  ('similarity_balanced_v1', 'Similarity', 'rule_based', TRUE, FALSE, 'Pattern matching similar games'),
  ('xgboost_v1', 'XGBoost ML', 'ml_model', TRUE, FALSE, 'Gradient boosting ML model'),
  ('meta_ensemble_v1', 'Ensemble', 'ensemble', TRUE, TRUE, 'Confidence-weighted combination'); -- CHAMPION
```

**Usage:**
```sql
-- Get active systems
SELECT system_id, system_name, is_champion
FROM `nba-props-platform.nba_predictions.prediction_systems`
WHERE is_active = TRUE
ORDER BY is_champion DESC, system_id;
```

---

### Table 01: player_prop_predictions ⭐ CRITICAL TABLE

**Schema File:** [`01_player_prop_predictions.sql`](../../../schemas/bigquery/predictions/01_player_prop_predictions.sql)
**Purpose:** All predictions from all systems for all players
**Written By:** Phase 5 (all 5 systems)
**Read By:** Phase 6 (publishing), Website (display)

**Schema Overview:**
- **Total Fields:** ~35 fields across 7 categories
- **Partition:** `game_date` (365 days expiration)
- **Clustering:** `system_id`, `player_lookup`, `confidence_score DESC`, `game_date`

**Field Categories:**

**Identifiers (7 fields):**
```sql
prediction_id STRING NOT NULL,           -- UUID
system_id STRING NOT NULL,               -- Which system
player_lookup STRING NOT NULL,
universal_player_id STRING,
game_date DATE NOT NULL,
game_id STRING NOT NULL,
prediction_version INT64 DEFAULT 1,     -- Increments on updates
```

**Core Prediction (3 fields):**
```sql
predicted_points NUMERIC(5,1) NOT NULL,  -- Predicted points
confidence_score NUMERIC(5,2) NOT NULL,  -- 0-100 confidence
recommendation STRING NOT NULL,          -- 'OVER', 'UNDER', 'PASS'
```

**Prediction Components (9 fields):**
```sql
similarity_baseline NUMERIC(5,1),        -- Baseline from similar games
fatigue_adjustment NUMERIC(5,2),         -- Points adjustment from fatigue
shot_zone_adjustment NUMERIC(5,2),       -- Points adjustment from matchup
referee_adjustment NUMERIC(5,2),
look_ahead_adjustment NUMERIC(5,2),
pace_adjustment NUMERIC(5,2),
usage_spike_adjustment NUMERIC(5,2),
home_away_adjustment NUMERIC(5,2),
other_adjustments NUMERIC(5,2),          -- Sum of other factors
```

**Supporting Metadata (6 fields):**
```sql
similar_games_count INT64,               -- Sample size (rule-based)
avg_similarity_score NUMERIC(5,2),       -- Quality of matches
min_similarity_score NUMERIC(5,2),
current_points_line NUMERIC(4,1),        -- Line at time of prediction
line_margin NUMERIC(5,2),                -- predicted - line
ml_model_id STRING,                      -- Model used (ML systems)
```

**Multi-System Analysis (3 fields):**
```sql
prediction_variance NUMERIC(5,2),        -- Variance across systems
system_agreement_score NUMERIC(5,2),     -- 0-100 (100 = perfect agreement)
contributing_systems INT64,              -- Count of systems
```

**Key Factors & Warnings (2 JSON fields):**
```sql
key_factors JSON,                        -- {"extreme_fatigue": true, "paint_mismatch": +6.2}
warnings JSON,                           -- ["low_sample_size", "high_variance"]
```

**Status (2 fields):**
```sql
is_active BOOLEAN DEFAULT TRUE,          -- FALSE when superseded
superseded_by STRING,                    -- prediction_id that replaced this
```

**Timestamps (2 fields):**
```sql
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
updated_at TIMESTAMP
```

**Multi-System Architecture Example:**
```sql
-- One player, one game, FIVE predictions (one per system)
SELECT
  player_lookup,
  system_id,
  predicted_points,
  confidence_score,
  recommendation
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE player_lookup = 'lebron-james'
  AND game_date = '2025-11-17'
  AND is_active = TRUE;

-- Results:
-- lebron-james, moving_average_baseline_v1, 28.5, 82, OVER
-- lebron-james, zone_matchup_v1, 27.3, 88, OVER
-- lebron-james, similarity_balanced_v1, 29.9, 85, OVER
-- lebron-james, xgboost_v1, 28.3, 75, OVER
-- lebron-james, meta_ensemble_v1, 28.6, 87, OVER  ← CHAMPION
```

---

### Table 04: ml_feature_store_v2 ⚠️ Written by Phase 4

**Schema File:** [`04_ml_feature_store_v2.sql`](../../../schemas/bigquery/predictions/04_ml_feature_store_v2.sql)
**Purpose:** Flexible array-based feature storage for ML predictions
**Written By:** Phase 4 Precompute Processor (5th processor)
**Read By:** All Phase 5 prediction systems
**Version:** 2.0 (with v4.0 dependency tracking)

**Schema Overview:**
- **Total Fields:** 35 fields across 8 categories
- **Partition:** `game_date` (365 days expiration)
- **Clustering:** `player_lookup`, `feature_version`, `game_date`
- **Key Design:** Array-based features support expansion from 25 → 47+ without schema changes

**Field Categories:**

**Identifiers (4 fields):**
```sql
player_lookup STRING NOT NULL,
universal_player_id STRING,
game_date DATE NOT NULL,
game_id STRING NOT NULL,
```

**Flexible Features (4 fields - array-based design):**
```sql
features ARRAY<FLOAT64> NOT NULL,        -- [f0, f1, ..., f24] (25 initially)
feature_names ARRAY<STRING> NOT NULL,    -- ['points_avg_last_5', ...]
feature_count INT64 NOT NULL,            -- 25 (can expand to 47+)
feature_version STRING NOT NULL,         -- 'v1_baseline_25'
```

**Feature Metadata (2 fields):**
```sql
feature_generation_time_ms INT64,        -- Generation time
feature_quality_score NUMERIC(5,2),      -- 0-100 quality score
```

**Player Context (3 fields):**
```sql
opponent_team_abbr STRING,
is_home BOOLEAN,
days_rest INT64,
```

**Data Source (1 field):**
```sql
data_source STRING NOT NULL,             -- 'phase4', 'phase3', 'mixed', 'early_season'
```

**Source Tracking: Phase 4 Dependencies (12 fields - v4.0):**
```sql
-- Source 1: player_daily_cache (Features 0-4, 18-20, 22-23)
source_daily_cache_last_updated TIMESTAMP,
source_daily_cache_rows_found INT64,
source_daily_cache_completeness_pct NUMERIC(5,2),

-- Source 2: player_composite_factors (Features 5-8)
source_composite_last_updated TIMESTAMP,
source_composite_rows_found INT64,
source_composite_completeness_pct NUMERIC(5,2),

-- Source 3: player_shot_zone_analysis (Features 18-20)
source_shot_zones_last_updated TIMESTAMP,
source_shot_zones_rows_found INT64,
source_shot_zones_completeness_pct NUMERIC(5,2),

-- Source 4: team_defense_zone_analysis (Features 13-14)
source_team_defense_last_updated TIMESTAMP,
source_team_defense_rows_found INT64,
source_team_defense_completeness_pct NUMERIC(5,2),
```

**Early Season Handling (2 fields):**
```sql
early_season_flag BOOLEAN,               -- TRUE if insufficient historical data
insufficient_data_reason STRING,         -- Why data was insufficient
```

**Processing Metadata (2 fields):**
```sql
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
updated_at TIMESTAMP
```

**Array-Based Design Benefits:**
```sql
-- Start with 25 features (v1_baseline_25)
INSERT INTO ml_feature_store_v2 (player_lookup, game_date, features, feature_version)
VALUES ('lebron-james', '2025-11-17', [28.5, 32.1, ..., 0.85], 'v1_baseline_25');

-- Later expand to 47 features (v2_expanded_47) - NO SCHEMA CHANGE
INSERT INTO ml_feature_store_v2 (player_lookup, game_date, features, feature_version)
VALUES ('lebron-james', '2025-12-01', [28.5, 32.1, ..., 0.92], 'v2_expanded_47');

-- Both versions coexist in same table!
```

**Phase 5 Usage (READ ONLY):**
```python
def predict(player_lookup, game_date, prop_line):
    # Read cached features (NO generation)
    features = read_from_feature_store(player_lookup, game_date)

    # Use system-specific prediction logic
    prediction = self.calculate_prediction(features, prop_line)

    return prediction

def read_from_feature_store(player_lookup, game_date):
    """Read pre-computed features from Phase 4"""
    query = """
    SELECT
        features,  -- Already computed by Phase 4
        feature_names,
        opponent_team_abbr,
        is_home
    FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
    WHERE player_lookup = @player_lookup
      AND game_date = @game_date
      AND feature_version = 'v1_baseline_25'
    """
    return bq_client.query(query, params={...}).result()
```

**Sample Query:**
```sql
-- Get today's cached features
SELECT
  player_lookup,
  game_date,
  features[OFFSET(0)] as points_avg_last_5,       -- Feature 0
  features[OFFSET(5)] as fatigue_score,           -- Feature 5
  features[OFFSET(13)] as opponent_def_rating,    -- Feature 13
  feature_quality_score,
  data_source  -- Should always be 'phase4'
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
  AND feature_version = 'v1_baseline_25'
ORDER BY player_lookup;
```

---

### Table 05: feature_versions

**Schema File:** [`05_feature_versions.sql`](../../../schemas/bigquery/predictions/05_feature_versions.sql)
**Purpose:** Define feature sets and versions
**Written By:** Phase 4 (populated on first run)
**Read By:** Phase 4 (validation), Phase 5 (reference)

**Schema:**
```sql
CREATE TABLE feature_versions (
  feature_version STRING NOT NULL PRIMARY KEY,
  feature_count INT64 NOT NULL,
  feature_names ARRAY<STRING> NOT NULL,
  feature_descriptions ARRAY<STRING>,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP
)
```

**Key Fields:**
- `feature_version` - Version identifier (e.g., `'v1_baseline_25'`)
- `feature_count` - Number of features (25 initially)
- `feature_names` - Array of feature names
- `feature_descriptions` - What each feature means
- `is_active` - Currently in use

**Sample Data:**
```sql
INSERT INTO feature_versions VALUES (
  'v1_baseline_25',
  25,
  ['points_avg_last_5', 'points_avg_last_10', 'minutes_avg_last_5', ...],
  ['Average points in last 5 games', 'Average points in last 10 games', ...],
  TRUE,
  CURRENT_TIMESTAMP(),
  NULL
);
```

---

### Table 02: prediction_results

**Schema File:** [`02_prediction_results.sql`](../../../schemas/bigquery/predictions/02_prediction_results.sql)
**Purpose:** Actual outcomes vs predictions (post-game analysis)
**Written By:** Phase 5 (post-game processor)
**Read By:** Performance analysis, model training

**Key Fields:**
- `prediction_id` - Links to `player_prop_predictions`
- `actual_points` - What player actually scored
- `actual_outcome` - 'OVER', 'UNDER', or 'PUSH'
- `was_correct` - Boolean (did prediction match outcome)
- `points_error` - Absolute error (predicted - actual)
- `game_completed_at` - When game ended

---

### Table 03: system_daily_performance

**Schema File:** [`03_system_daily_performance.sql`](../../../schemas/bigquery/predictions/03_system_daily_performance.sql)
**Purpose:** Daily performance metrics by system
**Written By:** Phase 5 (daily aggregation after games)
**Read By:** Monitoring, dashboards

**Key Fields:**
- `system_id` - Which system
- `performance_date` - Date of games
- `total_predictions` - Count of predictions
- `correct_predictions` - Count that were correct
- `accuracy_pct` - Percentage correct
- `avg_confidence` - Average confidence score
- `avg_absolute_error` - Mean absolute error
- `calibration_score` - How well-calibrated (confidence vs accuracy)

---

### Table 06: prediction_quality_log

**Schema File:** [`06_prediction_quality_log.sql`](../../../schemas/bigquery/predictions/06_prediction_quality_log.sql)
**Purpose:** Data quality tracking
**Written By:** Phase 5 (during predictions)
**Read By:** Quality monitoring

**Key Fields:**
- `quality_check_id` - Unique ID
- `game_date` - Date checked
- `check_type` - Type of quality check
- `passed` - Boolean result
- `details` - JSON with specifics

---

### Table 07: ml_models

**Schema File:** [`07_ml_models.sql`](../../../schemas/bigquery/predictions/07_ml_models.sql)
**Purpose:** Trained ML model registry
**Written By:** Phase 5 ML Training
**Read By:** XGBoost system (model loading)

**Key Fields:**
- `model_id` - Unique identifier
- `model_version` - Version string
- `model_type` - 'xgboost', 'lightgbm', etc.
- `gcs_path` - Where model is stored
- `is_active` - Currently in use
- `performance_metrics` - JSON with accuracy, AUC, etc.

---

### Table 08: ml_training_runs

**Schema File:** [`08_ml_training_runs.sql`](../../../schemas/bigquery/predictions/08_ml_training_runs.sql)
**Purpose:** Training history and metrics
**Written By:** Phase 5 ML Training
**Read By:** Training analysis, debugging

**Key Fields:**
- `run_id` - Unique training run ID
- `model_id` - Model that was trained
- `training_start` - When training started
- `training_end` - When training completed
- `train_accuracy` - Training set accuracy
- `val_accuracy` - Validation set accuracy
- `hyperparameters` - JSON with config

---

### Table 09: ml_prediction_metadata

**Schema File:** [`09_ml_prediction_metadata.sql`](../../../schemas/bigquery/predictions/09_ml_prediction_metadata.sql)
**Purpose:** ML-specific prediction details
**Written By:** XGBoost system (Phase 5)
**Read By:** ML debugging, feature importance

**Key Fields:**
- `prediction_id` - Links to `player_prop_predictions`
- `feature_importance` - JSON array of importances
- `model_confidence_raw` - Raw model output
- `shap_values` - SHAP values for interpretability

---

### Table 10: weight_adjustment_log

**Schema File:** [`10_weight_adjustment_log.sql`](../../../schemas/bigquery/predictions/10_weight_adjustment_log.sql)
**Purpose:** Configuration change history
**Written By:** Admin/configuration updates
**Read By:** Audit logs, rollback

**Key Fields:**
- `adjustment_id` - Unique ID
- `system_id` - Which system was adjusted
- `parameter_name` - What was changed
- `old_value` - Previous value
- `new_value` - New value
- `changed_by` - Who made the change
- `change_reason` - Why it was changed

---

## 📊 Views (5 Views) {#views}

### View 1: todays_predictions_summary

**Schema File:** [`views/v_todays_predictions_summary.sql`](../../../schemas/bigquery/predictions/views/v_todays_predictions_summary.sql)
**Purpose:** Today's predictions with champion system highlighted

**Definition:**
```sql
CREATE OR REPLACE VIEW todays_predictions_summary AS
SELECT
  p.player_lookup,
  p.game_id,
  s.system_name,
  s.is_champion,
  p.predicted_points,
  p.confidence_score,
  p.recommendation,
  p.current_points_line,
  p.line_margin
FROM player_prop_predictions p
JOIN prediction_systems s ON p.system_id = s.system_id
WHERE p.game_date = CURRENT_DATE()
  AND p.is_active = TRUE
  AND s.active = TRUE
ORDER BY s.is_champion DESC, p.confidence_score DESC;
```

**Usage:**
```sql
-- Get today's predictions with champion first
SELECT * FROM `nba-props-platform.nba_predictions.todays_predictions_summary`
WHERE player_lookup = 'lebron-james';
```

---

### View 2: system_comparison_today

**Schema File:** [`views/v_system_comparison_today.sql`](../../../schemas/bigquery/predictions/views/v_system_comparison_today.sql)
**Purpose:** Compare all system predictions side-by-side for today

**Usage:** Quickly see how different systems predict for the same player
```sql
SELECT * FROM `nba-props-platform.nba_predictions.system_comparison_today`
WHERE player_lookup = 'stephen-curry';
```

---

### View 3: system_agreement

**Schema File:** [`views/v_system_agreement.sql`](../../../schemas/bigquery/predictions/views/v_system_agreement.sql)
**Purpose:** Identify players with high system agreement (high confidence bets)

**Usage:** Find consensus picks
```sql
SELECT * FROM `nba-props-platform.nba_predictions.system_agreement`
WHERE system_agreement_score >= 90
ORDER BY system_agreement_score DESC;
```

---

### View 4: system_accuracy_leaderboard

**Schema File:** [`views/v_system_accuracy_leaderboard.sql`](../../../schemas/bigquery/predictions/views/v_system_accuracy_leaderboard.sql)
**Purpose:** System performance leaderboard (last 30 days)

**Usage:** See which system is performing best
```sql
SELECT * FROM `nba-props-platform.nba_predictions.system_accuracy_leaderboard`;
```

---

### View 5: system_performance_comparison

**Schema File:** [`views/v_system_performance_comparison.sql`](../../../schemas/bigquery/predictions/views/v_system_performance_comparison.sql)
**Purpose:** Compare system performance across multiple metrics

**Usage:** Detailed system comparison
```sql
SELECT * FROM `nba-props-platform.nba_predictions.system_performance_comparison`
WHERE performance_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY);
```

---

## 🔗 Table Relationships {#table-relationships}

### Entity-Relationship Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     PHASE 4 WRITES                           │
└─────────────────────────────────────────────────────────────┘
                              ↓
          ┌───────────────────────────────────┐
          │   ml_feature_store_v2             │
          │   (25-feature vectors)            │
          └───────────────────────────────────┘
                  ↓ (read by Phase 5)
┌─────────────────────────────────────────────────────────────┐
│                     PHASE 5 READS & WRITES                   │
└─────────────────────────────────────────────────────────────┘

┌────────────────────┐
│ prediction_systems │ ──┐
│ (registry)         │   │
└────────────────────┘   │
                         │ JOIN
┌────────────────────┐   │
│ feature_versions   │   │
│ (metadata)         │   │
└────────────────────┘   ↓
                    ┌─────────────────────────┐
                    │ player_prop_predictions │ ⭐ CORE TABLE
                    │ (all predictions)       │
                    └─────────────────────────┘
                              ↓
                    ┌─────────────────────┐
                    │ prediction_results  │
                    │ (actual outcomes)   │
                    └─────────────────────┘
                              ↓
          ┌───────────────────┴────────────────────┐
          ↓                                        ↓
┌──────────────────────┐              ┌────────────────────────┐
│ system_daily_perf    │              │ prediction_quality_log │
│ (aggregated metrics) │              │ (quality checks)       │
└──────────────────────┘              └────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     ML TRAINING WRITES                       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────┐
│   ml_models     │ ──┐
│   (registry)    │   │
└─────────────────┘   │
                      │ FK: model_id
                      ↓
          ┌───────────────────────┐
          │  ml_training_runs     │
          │  (training history)   │
          └───────────────────────┘
                      ↓
          ┌───────────────────────────┐
          │ ml_prediction_metadata    │
          │ (SHAP values, importance) │
          └───────────────────────────┘
```

### Foreign Key Relationships

**player_prop_predictions:**
- `system_id` → `prediction_systems.system_id`
- `ml_model_id` → `ml_models.model_id` (for ML systems only)

**prediction_results:**
- `prediction_id` → `player_prop_predictions.prediction_id`

**ml_prediction_metadata:**
- `prediction_id` → `player_prop_predictions.prediction_id`
- `model_id` → `ml_models.model_id`

**ml_training_runs:**
- `model_id` → `ml_models.model_id`

**system_daily_performance:**
- `system_id` → `prediction_systems.system_id`

---

## 🔍 Common Query Patterns {#common-queries}

### 1. Get Today's Predictions for a Player (All Systems)

```sql
SELECT
  system_id,
  predicted_points,
  confidence_score,
  recommendation,
  current_points_line,
  line_margin
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND player_lookup = 'lebron-james'
  AND is_active = TRUE
ORDER BY confidence_score DESC;
```

### 2. Get Champion System Predictions Only

```sql
SELECT
  p.player_lookup,
  p.predicted_points,
  p.confidence_score,
  p.recommendation,
  s.system_name
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.prediction_systems` s
  ON p.system_id = s.system_id
WHERE p.game_date = CURRENT_DATE()
  AND p.is_active = TRUE
  AND s.is_champion = TRUE
ORDER BY p.confidence_score DESC;
```

### 3. Get High Confidence Predictions (≥85)

```sql
SELECT
  player_lookup,
  system_id,
  predicted_points,
  confidence_score,
  recommendation,
  current_points_line
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
  AND confidence_score >= 85
ORDER BY confidence_score DESC;
```

### 4. Compare System Predictions for One Player

```sql
SELECT
  system_id,
  predicted_points,
  confidence_score,
  fatigue_adjustment,
  pace_adjustment,
  shot_zone_adjustment
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2025-11-17'
  AND player_lookup = 'lebron-james'
  AND is_active = TRUE
ORDER BY system_id;
```

### 5. Get Predictions with High System Agreement

```sql
SELECT
  player_lookup,
  COUNT(DISTINCT system_id) as system_count,
  AVG(predicted_points) as avg_prediction,
  STDDEV(predicted_points) as prediction_std,
  AVG(system_agreement_score) as avg_agreement
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
GROUP BY player_lookup
HAVING system_count >= 4
  AND prediction_std <= 2.0  -- High agreement (low variance)
ORDER BY avg_agreement DESC;
```

### 6. Check Feature Quality for Today

```sql
SELECT
  COUNT(DISTINCT player_lookup) as players_with_features,
  AVG(feature_quality_score) as avg_quality,
  MIN(feature_quality_score) as min_quality,
  COUNTIF(feature_quality_score < 70) as low_quality_count
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
  AND feature_version = 'v1_baseline_25';

-- Expected: 450 players, avg 85+, min 70+, low_quality 0
```

### 7. Validate Complete Data Flow (Phase 4 → Phase 5)

```sql
-- Check complete data flow: Phase 4 → Phase 5
WITH feature_check AS (
  SELECT player_lookup
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date = CURRENT_DATE()
),
prediction_check AS (
  SELECT DISTINCT player_lookup
  FROM `nba-props-platform.nba_predictions.player_prop_predictions`
  WHERE game_date = CURRENT_DATE()
)
SELECT
  (SELECT COUNT(*) FROM feature_check) as players_with_features,
  (SELECT COUNT(*) FROM prediction_check) as players_with_predictions,
  -- Should be equal (both ~450)
  CASE
    WHEN (SELECT COUNT(*) FROM feature_check) = (SELECT COUNT(*) FROM prediction_check)
    THEN '✅ MATCH'
    ELSE '❌ MISMATCH'
  END as status;
```

### 8. Get System Performance (Last 30 Days)

```sql
SELECT
  s.system_name,
  COUNT(*) as total_predictions,
  SUM(CASE WHEN r.was_correct THEN 1 ELSE 0 END) as correct_predictions,
  ROUND(SUM(CASE WHEN r.was_correct THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as accuracy_pct,
  AVG(p.confidence_score) as avg_confidence,
  AVG(ABS(r.points_error)) as avg_abs_error
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.prediction_results` r
  ON p.prediction_id = r.prediction_id
JOIN `nba-props-platform.nba_predictions.prediction_systems` s
  ON p.system_id = s.system_id
WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND r.actual_points IS NOT NULL
GROUP BY s.system_name
ORDER BY accuracy_pct DESC;
```

### 9. Get Feature Source Health Check

```sql
-- Check source freshness and completeness
SELECT
  game_date,
  COUNT(*) as total_players,
  AVG(feature_quality_score) as avg_quality,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(source_daily_cache_last_updated), HOUR) as cache_age_hours,
  AVG(source_daily_cache_completeness_pct) as cache_completeness,
  AVG(source_composite_completeness_pct) as composite_completeness,
  AVG(source_shot_zones_completeness_pct) as shot_zones_completeness,
  AVG(source_team_defense_completeness_pct) as team_defense_completeness
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;
```

### 10. Find Players with Missing Features

```sql
-- Players with games today but no features (Phase 4 issue)
WITH todays_games AS (
  SELECT DISTINCT player_lookup
  FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
  WHERE game_date = CURRENT_DATE()
),
todays_features AS (
  SELECT player_lookup
  FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
  WHERE game_date = CURRENT_DATE()
)
SELECT g.player_lookup
FROM todays_games g
LEFT JOIN todays_features f ON g.player_lookup = f.player_lookup
WHERE f.player_lookup IS NULL;

-- If any results: Phase 4 failed to generate features for these players
```

---

## 🚀 Deployment & Setup {#deployment}

### Create All Tables

```bash
cd schemas/bigquery/predictions

# Deploy all tables in order (00-10)
for file in [0-1][0-9]*.sql; do
  echo "Creating $(basename $file)..."
  bq query --project_id=nba-props-platform \
           --use_legacy_sql=false \
           < "$file"
done

# Deploy views
for file in views/*.sql; do
  echo "Creating view $(basename $file)..."
  bq query --project_id=nba-props-platform \
           --use_legacy_sql=false \
           < "$file"
done
```

### Verify Tables Created

```bash
bq ls nba-props-platform:nba_predictions

# Should see:
# - ml_feature_store_v2 (written by Phase 4)
# - feature_versions
# - prediction_systems
# - player_prop_predictions
# - prediction_results
# - system_daily_performance
# - prediction_quality_log
# - ml_models
# - ml_training_runs
# - ml_prediction_metadata
# - weight_adjustment_log
# Plus 5 views
```

### Initialize Critical Tables

```sql
-- 1. Register prediction systems
INSERT INTO `nba-props-platform.nba_predictions.prediction_systems`
(system_id, system_name, system_type, is_active, is_champion, description)
VALUES
  ('moving_average_baseline_v1', 'Moving Average Baseline', 'rule_based', TRUE, FALSE,
   'Simple average of recent games'),
  ('zone_matchup_v1', 'Zone Matchup', 'rule_based', TRUE, FALSE,
   'Shot zone vs opponent defense'),
  ('similarity_balanced_v1', 'Similarity', 'rule_based', TRUE, FALSE,
   'Pattern matching similar games'),
  ('xgboost_v1', 'XGBoost ML', 'ml_model', TRUE, FALSE,
   'Gradient boosting ML model'),
  ('meta_ensemble_v1', 'Ensemble', 'ensemble', TRUE, TRUE,
   'Confidence-weighted combination');

-- 2. Register feature version
INSERT INTO `nba-props-platform.nba_predictions.feature_versions`
(feature_version, feature_count, feature_names, is_active)
VALUES
  ('v1_baseline_25', 25,
   ['points_avg_last_5', 'points_avg_last_10', 'minutes_avg_last_5', ...],
   TRUE);
```

---

## 📊 Monitoring & Health Checks {#monitoring}

### Daily Health Check (Run at 6:30 AM)

```sql
-- Verify Phase 4 generated features for today
SELECT
  COUNT(DISTINCT player_lookup) as players_with_features,
  AVG(feature_quality_score) as avg_quality,
  MIN(created_at) as first_generated,
  MAX(created_at) as last_generated
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
  AND feature_version = 'v1_baseline_25';

-- Expected:
-- players_with_features: ~450
-- avg_quality: 85-95
-- first_generated: ~12:00 AM
-- last_generated: ~12:15 AM
```

```sql
-- Verify Phase 5 generated predictions for today
SELECT
  system_id,
  COUNT(DISTINCT player_lookup) as players,
  AVG(confidence_score) as avg_confidence
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
GROUP BY system_id;

-- Expected (5 rows):
-- moving_average_baseline_v1, 450, 75-80
-- zone_matchup_v1, 450, 80-85
-- similarity_balanced_v1, 450, 75-85
-- xgboost_v1, 450, 70-80
-- meta_ensemble_v1, 450, 80-90
```

### Weekly Performance Review

```sql
-- System accuracy over last 7 days
SELECT
  s.system_name,
  COUNT(*) as predictions,
  SUM(CASE WHEN r.was_correct THEN 1 ELSE 0 END) as correct,
  ROUND(SUM(CASE WHEN r.was_correct THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as accuracy_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
JOIN `nba-props-platform.nba_predictions.prediction_results` r
  ON p.prediction_id = r.prediction_id
JOIN `nba-props-platform.nba_predictions.prediction_systems` s
  ON p.system_id = s.system_id
WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND r.actual_points IS NOT NULL
GROUP BY s.system_name
ORDER BY accuracy_pct DESC;
```

---

## 🚨 Troubleshooting {#troubleshooting}

### Issue 1: No features for today (Phase 4 failed)

**Symptom:**
```sql
SELECT COUNT(*)
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
-- Returns: 0 (should be ~450)
```

**Impact:** Phase 5 CANNOT run without features
**Severity:** 🔴 CRITICAL
**Action:**
1. Check Phase 4 ml_feature_store_v2 processor logs
2. Verify Phase 4 dependencies completed (player_daily_cache, player_composite_factors)
3. Re-run Phase 4 ml_feature_store_v2 processor manually
4. Once features exist, re-trigger Phase 5 coordinator

---

### Issue 2: Features exist but no predictions (Phase 5 failed)

**Symptom:**
```sql
-- Features present
SELECT COUNT(*) FROM ml_feature_store_v2 WHERE game_date = CURRENT_DATE();
-- Returns: 450 ✅

-- Predictions missing
SELECT COUNT(*) FROM player_prop_predictions WHERE game_date = CURRENT_DATE();
-- Returns: 0 ❌
```

**Impact:** Website has no predictions to show
**Severity:** 🔴 CRITICAL
**Action:**
1. Check Phase 5 coordinator logs: `gcloud run jobs executions list --job phase5-prediction-coordinator`
2. Check coordinator errors: `gcloud logging read "resource.labels.job_name=phase5-prediction-coordinator"`
3. Verify Pub/Sub messages published: Check `prediction-request` topic
4. Check worker logs: `gcloud run services logs read phase5-prediction-worker`
5. Re-run coordinator manually: `gcloud run jobs execute phase5-prediction-coordinator --region us-central1 --wait`

---

### Issue 3: Only some systems have predictions

**Symptom:**
```sql
SELECT system_id, COUNT(*) as prediction_count
FROM player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
GROUP BY system_id;

-- Expected: 5 systems × 450 players = 2,250 total
-- Actual: Only 3-4 systems, or < 450 players per system
```

**Action:**
1. Check which systems are missing:
   ```sql
   SELECT s.system_id, s.system_name
   FROM prediction_systems s
   LEFT JOIN (
     SELECT DISTINCT system_id
     FROM player_prop_predictions
     WHERE game_date = CURRENT_DATE()
   ) p ON s.system_id = p.system_id
   WHERE s.is_active = TRUE
     AND p.system_id IS NULL;
   ```
2. Check individual system logs (worker logs filtered by system_id)
3. May need to re-run specific worker instances

---

### Issue 4: Low feature quality scores

**Symptom:**
```sql
SELECT
  AVG(feature_quality_score) as avg_quality,
  MIN(feature_quality_score) as min_quality,
  COUNTIF(feature_quality_score < 70) as low_quality_count
FROM ml_feature_store_v2
WHERE game_date = CURRENT_DATE();

-- avg_quality: 55 (should be 85+)
-- min_quality: 30 (should be 70+)
-- low_quality_count: 250 (should be 0)
```

**Possible Causes:**
1. Early in season (< 10 games played)
2. Phase 4 dependencies incomplete
3. Data source staleness

**Action:**
```sql
-- Check source completeness
SELECT
  AVG(source_daily_cache_completeness_pct) as cache_completeness,
  AVG(source_composite_completeness_pct) as composite_completeness,
  AVG(source_shot_zones_completeness_pct) as shot_zones_completeness,
  AVG(source_team_defense_completeness_pct) as team_defense_completeness
FROM ml_feature_store_v2
WHERE game_date = CURRENT_DATE();

-- If any < 85%, check Phase 4 processor that writes that source
```

---

### Issue 5: Predictions not updating when lines change

**Symptom:**
- Prop line changes from 25.5 → 26.5 at 3:00 PM
- `player_prop_predictions` still shows `current_points_line = 25.5`
- No new predictions with updated line

**Action:**
1. Check real-time odds update processor (Phase 2)
2. Verify Pub/Sub `prediction-request` topic receiving line change events
3. Check worker logs for line update processing
4. Verify `prediction_version` is incrementing (older predictions should have `is_active = FALSE`)

---

## 📚 Related Documentation

**Schema Source Files:**
- [`schemas/bigquery/predictions/`](../../../schemas/bigquery/predictions/) - All schema .sql files
- [`schemas/bigquery/predictions/README.md`](../../../schemas/bigquery/predictions/README.md) - Original schema README

**Phase 4 Documentation:**
- `docs/processors/08-phase4-ml-feature-store-deepdive.md` - How features are generated
- `docs/data-flow/` - Phase 3 → 4 → 5 data flow

**Phase 5 Documentation:**
- [`tutorials/01-getting-started.md`](../tutorials/01-getting-started.md) - How to query predictions
- [`tutorials/02-understanding-prediction-systems.md`](../tutorials/02-understanding-prediction-systems.md) - How systems work
- [`operations/01-deployment-guide.md`](../operations/01-deployment-guide.md) - Deployment procedures
- [`algorithms/01-composite-factor-calculations.md`](../algorithms/01-composite-factor-calculations.md) - Algorithm specs

**Data Access:**
- [`data-sources/01-data-categorization.md`](01-data-categorization.md) - Data ownership and flow

---

## 📝 Version History

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-17 | 1.0 | Initial BigQuery schema reference documentation |

---

**Need Help?**
- **Schema Questions:** Review actual .sql files in `schemas/bigquery/predictions/`
- **Query Examples:** Check embedded queries in schema files
- **Phase 4 Issues:** Check Phase 4 processor logs
- **Phase 5 Issues:** Check Phase 5 coordinator/worker logs
- **Performance Questions:** Review monitoring queries in this doc
