# Phase 5 Prediction Tables - Schema Reference

**Dataset:** `nba-props-platform.nba_predictions`  
**Purpose:** Multi-system prediction framework with ML integration  
**Update Schedule:** Daily (6-8 AM) + real-time when lines change

---

## 📋 Table Organization

### Input Data (Written by Phase 4, Read by Phase 5)
- `04_ml_feature_store_v2.sql` - **⚠️ WRITTEN BY PHASE 4** - Cached 25-feature vectors
- `05_feature_versions.sql` - Feature definitions and metadata

### Core Prediction Tables (Written by Phase 5)
- `00_prediction_systems.sql` - Registry of all prediction systems
- `01_player_prop_predictions.sql` - All predictions ⭐ CRITICAL TABLE
- `02_prediction_results.sql` - Actual outcomes vs predictions
- `03_system_daily_performance.sql` - Daily performance metrics

### Quality & Monitoring (Written by Phase 5)
- `06_prediction_quality_log.sql` - Data quality tracking

### ML Model Management (Written by Phase 5 ML Training)
- `07_ml_models.sql` - Trained ML model registry
- `08_ml_training_runs.sql` - Training history
- `09_ml_prediction_metadata.sql` - ML prediction details

### Configuration Management (Written by Phase 5)
- `10_weight_adjustment_log.sql` - Configuration change history

### Views (Read-Only)
- `views/` directory - Helper views for analysis and monitoring

---

## ⚠️ CRITICAL: ml_feature_store_v2 Ownership

**Table:** `nba_predictions.ml_feature_store_v2`  
**Schema File:** `04_ml_feature_store_v2.sql` (in this directory)  
**Written By:** **Phase 4 Precompute Processor** (5th processor, runs 12:00 AM)  
**Read By:** **Phase 5 Prediction Systems** (all 5 systems, 6:00 AM+)

### Why It's in This Dataset

Although `ml_feature_store_v2` is **written by Phase 4**, it's stored in the **predictions dataset** because:

1. ✅ **Tightly coupled with Phase 5** - Exclusively used by prediction systems
2. ✅ **Works with feature_versions** - Also in predictions dataset
3. ✅ **Dataset location clarity** - Schema file matches physical table location
4. ✅ **No other use cases** - Not used by other precompute operations

### Data Flow

```
Phase 4 (12:00 AM Nightly)
├─ team_defense_zone_analysis
├─ player_shot_zone_analysis
├─ player_composite_factors
├─ player_daily_cache
└─ ml_feature_store_v2  ← WRITES HERE (stored in nba_predictions)
          ↓
Phase 5 (6:00 AM Daily + Real-time Updates)
├─ Moving Average System  ← READS cached features
├─ Zone Matchup System    ← READS cached features
├─ Similarity System      ← READS cached features
├─ XGBoost ML System      ← READS cached features
└─ Ensemble System        ← READS cached features
```

### Key Concept: Compute Once, Use Many Times

**Without Feature Cache (Inefficient):**
- 450 players × 5 systems = 2,250 feature computations per day
- Each computation: ~25 expensive BigQuery queries
- Total: ~56,250 queries per day

**With Feature Cache (Efficient):**
- Phase 4 computes features once: 450 players × 25 features = 11,250 values
- Phase 5 reads cached features: 2,250 fast reads
- **Savings:** 50,000+ queries per day, 10x faster predictions

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

## 🚀 Quick Start

### Create All Tables
```bash
cd schemas/bigquery/predictions

# Deploy all tables in order
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
# - ...and others
```

---

## 🎯 Implementation Priority

### Session 2 Critical Tables (Must Create First)

**Phase 4 Writes These:**
1. `04_ml_feature_store_v2.sql` ⭐ (Phase 4 processor generates)
2. `05_feature_versions.sql` (Phase 4 populates on first run)

**Phase 5 Writes These:**
3. `00_prediction_systems.sql` ⭐ (register systems)
4. `01_player_prop_predictions.sql` ⭐ (all predictions go here)

### Can Defer to Production
- `02_prediction_results.sql` - Post-game analysis
- `03_system_daily_performance.sql` - Daily metrics
- `06_prediction_quality_log.sql` - Quality tracking
- `07-10_*.sql` - ML training and config management
- `views/*` - Nice to have, not critical

---

## 📊 Table Details

### ml_feature_store_v2 ⚠️ Written by Phase 4

**Purpose:** Cache 25-feature vectors for fast prediction generation  
**Written By:** Phase 4 Precompute Processor (5th processor)  
**Read By:** All Phase 5 prediction systems

**Key Fields:**
```sql
CREATE TABLE ml_feature_store_v2 (
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,
  game_id STRING NOT NULL,
  
  -- Feature data
  features ARRAY<FLOAT64> NOT NULL,        -- [f0, f1, ..., f24] (25 features)
  feature_names ARRAY<STRING> NOT NULL,    -- ['points_avg_last_5', ...]
  feature_count INT64 NOT NULL,            -- 25
  feature_version STRING NOT NULL,         -- 'v1_baseline_25'
  
  -- Quality tracking
  feature_quality_score NUMERIC(5,2),      -- 0-100 quality metric
  data_source STRING NOT NULL,             -- 'phase4' (confirms Phase 4 origin)
  
  -- Context
  opponent_team_abbr STRING,
  is_home BOOLEAN,
  days_rest INT64,
  
  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup, feature_version, game_date;
```

**Phase 5 Usage (READ ONLY):**
```python
# Phase 5 prediction system
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
    
    result = bq_client.query(query, params={...}).result()
    return next(result)
```

**Sample Query:**
```sql
-- Get today's cached features
SELECT 
  player_lookup,
  game_date,
  features[OFFSET(0)] as points_avg_last_5,
  features[OFFSET(5)] as fatigue_score,
  features[OFFSET(13)] as opponent_def_rating,
  feature_quality_score,
  data_source  -- Should always be 'phase4'
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
  AND feature_version = 'v1_baseline_25'
ORDER BY player_lookup;
```

---

### feature_versions

**Purpose:** Define feature sets and versions  
**Written By:** Phase 4 (populated on first run)  
**Read By:** Phase 4 (validation), Phase 5 (reference)

**Key Fields:**
- `feature_version` - 'v1_baseline_25'
- `feature_count` - 25
- `feature_names` - Array of feature names
- `feature_descriptions` - What each feature means
- `is_active` - Currently in use

---

### prediction_systems

**Purpose:** Registry of all prediction systems  
**Written By:** Phase 5 (during deployment)  
**Read By:** Phase 5 (routing predictions)

**Key Fields:**
- `system_id` - 'moving_average_baseline_v1'
- `system_type` - 'rule_based' or 'ml_model' or 'ensemble'
- `is_active` - Currently generating predictions
- `is_champion` - Primary system for recommendations
- `description` - What this system does

---

### player_prop_predictions ⭐ CRITICAL TABLE

**Purpose:** All predictions from all systems  
**Written By:** Phase 5 (all 5 systems write here)  
**Read By:** Phase 6 (publishing), Website (display)

**Key Fields:**
- `prediction_id` - Unique ID
- `system_id` - Which system made this prediction
- `player_lookup` - Who we're predicting for
- `game_date` - When they're playing
- `predicted_points` - System's prediction
- `prop_line` - Betting line (can change throughout day)
- `recommendation` - 'OVER' or 'UNDER'
- `confidence_score` - 0-100 confidence

**Multi-System Architecture:**
```sql
-- One player, one game, FIVE predictions
SELECT 
  player_lookup,
  system_id,
  predicted_points,
  confidence_score
FROM player_prop_predictions
WHERE player_lookup = 'lebron-james'
  AND game_date = '2025-01-27';

-- Results:
-- lebron-james, moving_average_baseline_v1, 28.5, 82
-- lebron-james, zone_matchup_v1, 27.3, 88
-- lebron-james, similarity_balanced_v1, 29.9, 85
-- lebron-james, xgboost_v1, 28.3, 75
-- lebron-james, meta_ensemble_v1, 28.6, 87
```

---

## ⚠️ Important Notes

### Feature Store Design (Array-Based)

**Why Arrays?**
- Start with 25 features (v1_baseline_25)
- Can expand to 47+ features WITHOUT schema changes
- Just update feature_version to 'v2_expanded_47'
- No ALTER TABLE needed

**Version Control:**
- All features tagged with `feature_version`
- Can run multiple versions simultaneously
- Easy rollback if new features don't work

### Multi-System Architecture

**How It Works:**
- 5 systems predict for SAME player/game
- Each writes to `player_prop_predictions` with different `system_id`
- ONE system designated as "champion" (primary recommendation)
- Other systems provide alternative viewpoints

**Benefits:**
- Compare system performance
- Identify system agreement (high confidence)
- Easy A/B testing
- Gradual rollout of new systems

---

## 🔍 Monitoring & Validation

### Check Feature Generation (Phase 4)
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

### Check Predictions (Phase 5)
```sql
-- Verify Phase 5 generated predictions for today
SELECT 
  system_id,
  COUNT(DISTINCT player_lookup) as players,
  AVG(confidence_score) as avg_confidence
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = CURRENT_DATE()
GROUP BY system_id;

-- Expected (5 rows):
-- moving_average_baseline_v1, 450, 75-80
-- zone_matchup_v1, 450, 80-85
-- similarity_balanced_v1, 450, 75-85
-- xgboost_v1, 450, 70-80
-- meta_ensemble_v1, 450, 80-90
```

### Data Flow Validation
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

---

## 🚨 Troubleshooting

### Issue: No features for today (Phase 4 failed)
```sql
SELECT COUNT(*)
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE();
-- If 0: Phase 4 processor didn't run
```

**Impact:** Phase 5 CANNOT run without features  
**Severity:** 🔴 CRITICAL  
**Action:** Check Phase 4 processor logs, re-run manually

### Issue: Features exist but no predictions (Phase 5 failed)
```sql
-- Features present
SELECT COUNT(*) FROM ml_feature_store_v2 WHERE game_date = CURRENT_DATE();
-- Returns: 450

-- Predictions missing
SELECT COUNT(*) FROM player_prop_predictions WHERE game_date = CURRENT_DATE();
-- Returns: 0
```

**Impact:** Website has no predictions to show  
**Severity:** 🔴 CRITICAL  
**Action:** Check Phase 5 coordinator logs, re-run manually

### Issue: Only some systems have predictions
```sql
SELECT system_id, COUNT(*) as prediction_count
FROM player_prop_predictions
WHERE game_date = CURRENT_DATE()
GROUP BY system_id;

-- Expected: 5 systems × 450 players = 2,250 total
-- If less: Some systems failed
```

**Action:** Check individual system logs, may need to re-run specific systems

---

## 📚 Related Documentation

### Phase 4 Cross-Reference
- **Phase 4 Precompute README:** Details on ml_feature_store_v2 generation
- **Data Mapping Guide:** Phase 3→4→5 feature flow
- **Feature Store Architecture Decision:** Why ml_feature_store_v2 is written by Phase 4

### Phase 5 Implementation
- **Phase 5 Implementation Strategy:** 4-week rollout plan
- **Algorithm Specifications:** Formulas for each prediction system
- **Prediction Systems Tutorial:** Examples and testing
- **Infrastructure & Deployment Guide:** Cloud Run setup

### Operations
- **DEPLOYMENT_GUIDE.md:** Step-by-step deployment
- **Platform Architecture Overview:** Complete 6-phase pipeline
- **Monitoring Dashboard:** Grafana/Cloud Monitoring setup

---

## 🔧 Schema Updates

### Adding New Features (Expand from 25 to 47)

**No Schema Change Needed** (array-based design):
```sql
-- Phase 4 just needs to:
-- 1. Generate 47 features instead of 25
-- 2. Use new feature_version: 'v2_expanded_47'
-- 3. Write to same ml_feature_store_v2 table

INSERT INTO ml_feature_store_v2 (
  player_lookup,
  game_date,
  features,  -- Now 47 elements instead of 25
  feature_version  -- 'v2_expanded_47'
  -- ... other fields
)
```

**Phase 5 Updates:**
```python
# Read new feature version
features = read_from_feature_store(
    player_lookup, 
    game_date, 
    feature_version='v2_expanded_47'  # Changed
)

# Systems automatically use all 47 features
```

### Adding New System

1. Register in `prediction_systems`:
```sql
INSERT INTO prediction_systems (
  system_id, 
  system_type,
  is_active,
  description
) VALUES (
  'gradient_boost_v1',
  'ml_model',
  true,
  'Gradient boosting with engineered features'
);
```

2. Deploy new system code to Cloud Run

3. System reads from ml_feature_store_v2 and writes to player_prop_predictions

4. Monitor performance vs existing systems

---

## 📊 Performance Expectations

### Phase 4 Feature Generation
- **Runtime:** 10-15 minutes for 450 players
- **Trigger:** 12:00 AM nightly (after other Phase 4 processors)
- **Output:** 11,250 feature values (450 players × 25 features)

### Phase 5 Daily Predictions
- **Runtime:** 15-20 minutes for all systems
- **Trigger:** 6:00 AM daily
- **Input:** Read 450 cached feature vectors
- **Output:** 2,250 predictions (450 players × 5 systems)

### Phase 5 Real-Time Updates
- **Runtime:** 5-10 seconds per player
- **Trigger:** When prop line changes (9 AM - 7 PM)
- **Input:** Read 1 cached feature vector
- **Output:** 5 predictions (1 player × 5 systems)

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2025-01-27 | 1.0 | Initial Phase 5 schema documentation |
| 2025-11-05 | 1.1 | Clarified ml_feature_store_v2 ownership (Phase 4 writes, Phase 5 reads) |

---

## Questions or Issues?

- **Phase 4 Issues:** Check `data_processors/precompute/` logs
- **Phase 5 Issues:** Check `predictions/` service logs
- **Schema Questions:** Review DEPLOYMENT_GUIDE.md
- **Architecture Questions:** Review Platform Architecture Overview
- **Contact:** NBA Props Analytics Team