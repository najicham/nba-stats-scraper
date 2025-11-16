# Phase 4→5 Mapping: ML Feature Consumption

**File:** `docs/data-flow/13-phase4-to-phase5-feature-consumption.md`
**Created:** 2025-11-15
**Last Updated:** 2025-11-15
**Purpose:** Data mapping from Phase 4 ML Feature Store to Phase 5 prediction systems
**Audience:** Engineers implementing Phase 5 prediction systems and debugging feature dependencies
**Status:** ⚠️ Blocked - Source table missing, contract defined

---

## 🚧 Current Deployment Status

**Implementation:** ⚠️ **BLOCKED**
- Phase 4 Source: `nba_predictions.ml_feature_store_v2` (**MISSING** - critical blocker)
- Phase 5 Consumers: 5 prediction systems (Moving Average, Zone Matchup, Similarity, XGBoost, Ensemble)
- Phase 5 Output: `nba_predictions.player_prop_predictions` (**MISSING** - not verified)
- Schema Definitions: Both schemas exist in `schemas/bigquery/predictions/`

**Blocker:** ❌ **ml_feature_store_v2 table does not exist**
- ✅ Schema file exists: `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`
- ❌ **Table not created in BigQuery**
- ❌ Phase 5 workers cannot run without this table (CRITICAL dependency)
- ❌ Output table `player_prop_predictions` also missing

**Processing Strategy:**
- **Phase 4 contract:** Deliver 25 features as ARRAY<FLOAT64> with quality score ≥85 for 85%+ of players
- **Phase 5 contract:** Extract features by index, validate quality, skip players with early_season_flag
- **Feature consumption:** Each system uses subset of 25 features (10-25 features depending on system)
- **Graceful degradation:** Systems skip players if features missing or quality <70

**Consumers:**
- Moving Average: Uses 10 of 25 features
- Zone Matchup V1: Uses 14 of 25 features
- Similarity: Uses 15 of 25 features + historical games
- XGBoost: Uses ALL 25 features
- Ensemble: Uses ALL 25 features (passes to component systems)

**See:** `docs/processors/` for Phase 5 deployment procedures

---

## 📊 Executive Summary

This document defines the **contract** between Phase 4 (ML Feature Store) and Phase 5 (Prediction Systems). It specifies how the 25-feature array is consumed, which systems use which features, and what guarantees each phase must provide.

**Contract Definition:** Phase 4→5 Feature Consumption
**Input Table:** `nba_predictions.ml_feature_store_v2` (Phase 4 output)
**Output Table:** `nba_predictions.player_prop_predictions` (Phase 5 output)
**Feature Count:** 25 features (v1_baseline_25)
**Granularity:** 1 feature row per player per game_date → 5 predictions per player

**Key Features:**
- **Feature array extraction** - Systems extract features by index from ARRAY<FLOAT64>
- **Partial feature usage** - Different systems use different subsets (10-25 features)
- **Quality validation** - Systems check `feature_quality_score` ≥70 before using
- **Early season handling** - Systems skip players with `early_season_flag = TRUE`
- **Feature versioning** - Systems verify `feature_version = 'v1_baseline_25'`
- **Source tracking** - Systems can inspect which Phase 4 sources contributed

**Data Quality Contract:**
- **Phase 4 guarantees:** ≥85% of players with quality score ≥85
- **Phase 5 requirements:** Minimum quality score 70 to generate prediction
- **Fallback behavior:** Skip player if features missing or quality too low

**Innovation:** Array-based extraction allows Phase 4 to add features (26-47) without breaking Phase 5 systems that only use first 25.

---

## 🗂️ Phase 4 Source (Precompute)

### Source: ML Feature Store V2 (CRITICAL - ONLY SOURCE)

**Table:** `nba_predictions.ml_feature_store_v2`
**Status:** ❌ **MISSING**
**Update Frequency:** Nightly at 12:00 AM (after all Phase 4 processors)
**Dependency:** CRITICAL - Phase 5 cannot run without this table
**Granularity:** One row per player per game_date (~450 rows/day)

**Purpose:**
- Unified feature store for all prediction systems
- Pre-computed 25 features from Phase 3 + Phase 4 sources
- Quality scored with source tracking
- Early season handling with placeholder rows

**Key Fields Used:**

| Field | Type | Used By | Purpose |
|-------|------|---------|---------|
| player_lookup | STRING | All systems | Player identifier (join key) |
| universal_player_id | STRING | All systems | Output table population |
| game_date | DATE | All systems | Partition key, validation |
| game_id | STRING | All systems | Output table population |
| **features** | **ARRAY<FLOAT64>** | **All systems** | **25 feature values** |
| feature_names | ARRAY<STRING> | Validation | Feature labels (debug) |
| feature_count | INT64 | Validation | Must be 25 |
| feature_version | STRING | Validation | Must be "v1_baseline_25" |
| feature_quality_score | NUMERIC(5,2) | Validation | 0-100 score (≥70 required) |
| data_source | STRING | Monitoring | 'phase4'/'phase3'/'mixed'/'early_season' |
| opponent_team_abbr | STRING | Output | Metadata |
| is_home | BOOLEAN | Output | Metadata |
| days_rest | INT64 | Output | Metadata |
| early_season_flag | BOOLEAN | Filtering | Skip if TRUE |
| insufficient_data_reason | STRING | Logging | Why skipped |

**Data Quality Requirements:**
- ✅ ≥450 rows per game day (all players with games)
- ✅ feature_count = 25 exactly
- ✅ feature_version = "v1_baseline_25"
- ✅ ≥85% of rows with feature_quality_score ≥85
- ✅ early_season_flag = FALSE for ≥80% of rows (after Week 3)

**Query Pattern (Per Player):**
```sql
-- Phase 5 worker loads features for one player
SELECT
  features,                    -- ARRAY<FLOAT64> with 25 values
  feature_quality_score,
  early_season_flag,
  universal_player_id,
  opponent_team_abbr,
  is_home,
  data_source
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE player_lookup = @player_lookup
  AND game_date = @game_date
  AND feature_version = 'v1_baseline_25'
LIMIT 1
```

**Expected Response:**
```json
{
  "features": [25.2, 24.8, 24.5, 4.23, 3.0, 75.0, 3.5, 1.5, 0.8,
               0.0, 0.0, -2.0, 1.0, 110.5, 101.2, 0.0, 0.0, 0.0,
               0.35, 0.20, 0.45, 0.286, 99.8, 115.2, 0.700],
  "feature_quality_score": 97.0,
  "early_season_flag": false,
  "universal_player_id": "nba_player_2544",
  "opponent_team_abbr": "GSW",
  "is_home": false,
  "data_source": "phase4"
}
```

---

## 🔄 Data Flow

### Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 4: ML Feature Store V2 (Nightly 12:00 AM)                 │
│ Output: 450 rows with 25 features each                          │
│ Quality: ≥85% with score ≥85                                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Phase 5 Coordinator (6:15 AM)                           │
│ • Queries upcoming_player_game_context → 450 players            │
│ • Queries odds_player_props → betting lines                     │
│ • Publishes 450 Pub/Sub messages (one per player)               │
└─────────────────────────────────────────────────────────────────┘
                            ↓
                    Pub/Sub: prediction-request
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Phase 5 Worker Receives Message                         │
│ Message contains:                                                │
│ • player_lookup = "lebron-james"                                │
│ • game_date = "2025-11-15"                                      │
│ • line_values = [25.5]                                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Load Features from ml_feature_store_v2                  │
│ Query:                                                           │
│ SELECT features, feature_quality_score, early_season_flag       │
│ FROM ml_feature_store_v2                                        │
│ WHERE player_lookup = 'lebron-james'                            │
│   AND game_date = '2025-11-15'                                  │
│                                                                  │
│ Validation:                                                      │
│ ✅ early_season_flag = FALSE                                    │
│ ✅ feature_quality_score = 97.0 (≥70)                           │
│ ✅ LENGTH(features) = 25                                        │
│                                                                  │
│ Result: Load successful → Proceed to prediction                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Extract Features by System                              │
│                                                                  │
│ Moving Average (10 features):                                   │
│ • features[0] = 25.2  (points_avg_last_5)                      │
│ • features[1] = 24.8  (points_avg_last_10)                     │
│ • features[2] = 24.5  (points_avg_season)                      │
│ • features[3] = 4.23  (points_std_last_10)                     │
│ • features[13] = 110.5 (opponent_def_rating)                   │
│ • ... (5 more)                                                  │
│                                                                  │
│ Zone Matchup V1 (14 features):                                  │
│ • features[5] = 75.0  (fatigue_score)                          │
│ • features[6] = 3.5   (shot_zone_mismatch_score)               │
│ • features[18] = 0.35 (pct_paint)                              │
│ • features[19] = 0.20 (pct_mid_range)                          │
│ • features[20] = 0.45 (pct_three)                              │
│ • ... (9 more)                                                  │
│                                                                  │
│ XGBoost (ALL 25 features):                                      │
│ • features[0:25] → numpy array → model.predict()               │
│                                                                  │
│ Ensemble (ALL 25 features):                                     │
│ • Passes to all component systems                              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Generate Predictions (5 systems run in parallel)        │
│                                                                  │
│ Moving Average:                                                  │
│ • Baseline = weighted_avg(features[0:2], opponent_adjustment)  │
│ • predicted_points = 26.5, confidence = 68%                     │
│                                                                  │
│ Zone Matchup V1:                                                │
│ • Baseline = season_avg + shot_zone_adjustment                  │
│ • predicted_points = 26.8, confidence = 62%                     │
│                                                                  │
│ Similarity:                                                      │
│ • Find similar games (requires player_game_summary)             │
│ • predicted_points = 27.2, confidence = 75%                     │
│                                                                  │
│ XGBoost:                                                         │
│ • model.predict(features) → predicted_points = 26.3             │
│ • confidence = 72%                                              │
│                                                                  │
│ Ensemble:                                                        │
│ • Weighted combination of 4 systems                             │
│ • predicted_points = 26.7, confidence = 82%                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 6: Write to player_prop_predictions                        │
│ • 5 rows (one per system)                                       │
│ • Each includes: predicted_points, confidence, recommendation   │
│ • Streaming insert (immediate write)                            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Field Mappings

### Complete Feature Consumption Matrix (25 Features)

**Feature Array Structure:**

| Index | Feature Name | Type | Range | Moving Avg | Zone Match | Similarity | XGBoost | Ensemble |
|-------|--------------|------|-------|------------|------------|------------|---------|----------|
| **Category 1: Recent Performance** | | | | | | | | |
| 0 | points_avg_last_5 | FLOAT | 0-50 | ✅ | ❌ | ✅ | ✅ | ✅ |
| 1 | points_avg_last_10 | FLOAT | 0-50 | ✅ | ❌ | ✅ | ✅ | ✅ |
| 2 | points_avg_season | FLOAT | 0-50 | ✅ | ❌ | ✅ | ✅ | ✅ |
| 3 | points_std_last_10 | FLOAT | 0-20 | ✅ | ❌ | ✅ | ✅ | ✅ |
| 4 | games_in_last_7_days | FLOAT | 0-7 | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Category 2: Composite Factors (Phase 4 Only)** | | | | | | | | |
| 5 | fatigue_score | FLOAT | 0-100 | ❌ | ✅ | ✅ | ✅ | ✅ |
| 6 | shot_zone_mismatch_score | FLOAT | -10 to +10 | ❌ | ✅ | ✅ | ✅ | ✅ |
| 7 | pace_score | FLOAT | -3 to +3 | ❌ | ✅ | ❌ | ✅ | ✅ |
| 8 | usage_spike_score | FLOAT | -3 to +3 | ❌ | ✅ | ❌ | ✅ | ✅ |
| **Category 3: Derived Factors** | | | | | | | | |
| 9 | rest_advantage | FLOAT | -2 to +2 | ❌ | ❌ | ✅ | ✅ | ✅ |
| 10 | injury_risk | FLOAT | 0-3 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 11 | recent_trend | FLOAT | -2 to +2 | ❌ | ❌ | ✅ | ✅ | ✅ |
| 12 | minutes_change | FLOAT | -10 to +10 | ❌ | ❌ | ✅ | ✅ | ✅ |
| **Category 4: Matchup Context** | | | | | | | | |
| 13 | opponent_def_rating | FLOAT | 100-130 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 14 | opponent_pace | FLOAT | 95-105 | ✅ | ✅ | ❌ | ✅ | ✅ |
| 15 | home_away | FLOAT | 0 or 1 | ✅ | ❌ | ✅ | ✅ | ✅ |
| 16 | back_to_back | FLOAT | 0 or 1 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 17 | playoff_game | FLOAT | 0 or 1 | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Category 5: Shot Zones** | | | | | | | | |
| 18 | pct_paint | FLOAT | 0-1 | ❌ | ✅ | ❌ | ✅ | ✅ |
| 19 | pct_mid_range | FLOAT | 0-1 | ❌ | ✅ | ❌ | ✅ | ✅ |
| 20 | pct_three | FLOAT | 0-1 | ❌ | ✅ | ❌ | ✅ | ✅ |
| 21 | pct_free_throw | FLOAT | 0-0.5 | ❌ | ❌ | ❌ | ✅ | ✅ |
| **Category 6: Team Context** | | | | | | | | |
| 22 | team_pace | FLOAT | 95-105 | ✅ | ✅ | ❌ | ✅ | ✅ |
| 23 | team_off_rating | FLOAT | 100-130 | ✅ | ✅ | ❌ | ✅ | ✅ |
| 24 | team_win_pct | FLOAT | 0-1 | ✅ | ❌ | ❌ | ✅ | ✅ |
| **TOTAL FEATURES USED** | | | | **10** | **14** | **15** | **25** | **25** |

### System-Specific Extraction Code

**Moving Average System (10 features):**
```python
# Extract 10 features for weighted average calculation
points_last_5 = features[0]
points_last_10 = features[1]
points_season = features[2]
points_std = features[3]
opp_def_rating = features[13]
opp_pace = features[14]
is_home = features[15]
team_pace = features[22]
team_off_rating = features[23]
team_win_pct = features[24]

# Calculate baseline
baseline = (
    points_last_5 * 0.4 +
    points_last_10 * 0.4 +
    points_season * 0.2
)

# Opponent adjustment
opp_adjustment = (opp_def_rating - 112.0) * 0.05  # Scale to ±1 point

# Final prediction
predicted_points = baseline + opp_adjustment
```

**Zone Matchup V1 System (14 features):**
```python
# Extract composite factors + shot zones + matchup context
fatigue_score = features[5]
shot_zone_mismatch = features[6]
pace_score = features[7]
usage_spike = features[8]
opp_def_rating = features[13]
opp_pace = features[14]
pct_paint = features[18]
pct_mid_range = features[19]
pct_three = features[20]
team_pace = features[22]
team_off_rating = features[23]
points_season = features[2]  # Baseline

# Calculate adjustments
fatigue_adjustment = (fatigue_score - 100) * 0.05  # -5.0 to 0.0
pace_adjustment = pace_score
usage_adjustment = usage_spike

# Final prediction
predicted_points = (
    points_season +
    shot_zone_mismatch +
    fatigue_adjustment +
    pace_adjustment +
    usage_adjustment
)
```

**Similarity System (15 features):**
```python
# Extract features for similar game matching
points_last_5 = features[0]
points_last_10 = features[1]
points_season = features[2]
points_std = features[3]
fatigue_score = features[5]
shot_zone_mismatch = features[6]
rest_advantage = features[9]
recent_trend = features[11]
minutes_change = features[12]
opp_def_rating = features[13]
is_home = features[15]

# Calculate recent form for similarity matching
recent_form = points_last_5 - points_season

# Find similar games from player_game_summary
# (Also queries player_game_summary table - not just features)
similar_games = find_similar_games(
    recent_form=recent_form,
    opp_def_rating=opp_def_rating,
    is_home=is_home,
    rest_advantage=rest_advantage
)

# Average outcomes of similar games
baseline = avg([g.points for g in similar_games])

# Apply adjustments from features
predicted_points = baseline + shot_zone_mismatch + (recent_trend * 0.5)
```

**XGBoost System (ALL 25 features):**
```python
# Extract all 25 features as numpy array
import numpy as np

feature_array = np.array(features)  # All 25 features

# Load pre-trained model
model = load_xgboost_model('player_points_v1.model')

# Predict
predicted_points = model.predict(feature_array.reshape(1, -1))[0]

# Confidence from model uncertainty
confidence_score = calculate_confidence(
    model_variance=model.predict_variance(feature_array),
    feature_quality_score=feature_quality_score
)
```

**Ensemble System (ALL 25 features):**
```python
# Pass all 25 features to component systems
moving_avg_pred = moving_average_system.predict(features)
zone_match_pred = zone_matchup_system.predict(features)
similarity_pred = similarity_system.predict(features, historical_games)
xgboost_pred = xgboost_system.predict(features)

# Weighted combination (weights learned from historical accuracy)
weights = {
    'moving_avg': 0.15,
    'zone_match': 0.15,
    'similarity': 0.25,
    'xgboost': 0.45
}

predicted_points = (
    moving_avg_pred * weights['moving_avg'] +
    zone_match_pred * weights['zone_match'] +
    similarity_pred * weights['similarity'] +
    xgboost_pred * weights['xgboost']
)

# Agreement score (variance across systems)
system_agreement_score = calculate_agreement([
    moving_avg_pred, zone_match_pred, similarity_pred, xgboost_pred
])
```

---

## 📐 Calculation Examples

### Example 1: LeBron James - High Quality Features (All Systems Run)

**Phase 4 Input (ml_feature_store_v2):**
```json
{
  "player_lookup": "lebron-james",
  "game_date": "2025-11-15",
  "features": [25.2, 24.8, 24.5, 4.23, 3.0, 75.0, 3.5, 1.5, 0.8,
               0.0, 0.0, -2.0, 1.0, 110.5, 101.2, 0.0, 0.0, 0.0,
               0.35, 0.20, 0.45, 0.286, 99.8, 115.2, 0.700],
  "feature_quality_score": 97.0,
  "early_season_flag": false
}
```

**Validation:**
```python
# Phase 5 worker validates before using
assert early_season_flag == False  # ✅ Pass
assert feature_quality_score >= 70  # ✅ Pass (97.0)
assert len(features) == 25          # ✅ Pass
# Proceed to prediction
```

**System 1: Moving Average**
```python
# Extract 10 features
baseline = 25.2 * 0.4 + 24.8 * 0.4 + 24.5 * 0.2  # = 25.0
opp_adjustment = (110.5 - 112.0) * 0.05  # = -0.075
predicted_points = 25.0 + (-0.075) = 24.9

# Round to .5
predicted_points = 25.0
confidence_score = 68.0
recommendation = "UNDER" (25.0 < 25.5 line)
```

**System 2: Zone Matchup V1**
```python
# Extract 14 features
baseline = 24.5  # points_season
shot_zone_adjustment = 3.5  # Favorable paint matchup
fatigue_adjustment = (75.0 - 100) * 0.05 = -1.25
pace_adjustment = 1.5
usage_adjustment = 0.8

predicted_points = 24.5 + 3.5 + (-1.25) + 1.5 + 0.8 = 29.05
# Round to .5
predicted_points = 29.0
confidence_score = 62.0
recommendation = "OVER" (29.0 > 25.5 line)
```

**System 3: Similarity**
```python
# Extract 15 features + query historical games
recent_form = 25.2 - 24.5 = 0.7  # Hot
# Find 10 similar games (requires player_game_summary)
similar_games = [28, 26, 30, 27, 25, 29, 26, 28, 27, 26]
baseline = avg(similar_games) = 27.2

# Adjustments
shot_zone_adjustment = 3.5
trend_adjustment = -2.0 * 0.5 = -1.0

predicted_points = 27.2 + 3.5 + (-1.0) = 29.7
# Round to .5
predicted_points = 29.5
confidence_score = 75.0
recommendation = "OVER" (29.5 > 25.5 line)
```

**System 4: XGBoost**
```python
# Use all 25 features
import numpy as np
feature_array = np.array(features)
predicted_points = xgboost_model.predict(feature_array.reshape(1, -1))[0]
# Model output: 26.3

predicted_points = 26.5  # Rounded to .5
confidence_score = 72.0
recommendation = "OVER" (26.5 > 25.5 line)
```

**System 5: Ensemble**
```python
# Combine 4 predictions
predictions = {
    'moving_avg': 25.0,
    'zone_match': 29.0,
    'similarity': 29.5,
    'xgboost': 26.5
}

weights = {'moving_avg': 0.15, 'zone_match': 0.15, 'similarity': 0.25, 'xgboost': 0.45}

predicted_points = (
    25.0 * 0.15 +
    29.0 * 0.15 +
    29.5 * 0.25 +
    26.5 * 0.45
) = 27.475

# Round to .5
predicted_points = 27.5
confidence_score = 82.0
recommendation = "OVER" (27.5 > 25.5 line)

# Calculate agreement
prediction_variance = std([25.0, 29.0, 29.5, 26.5]) = 2.08
system_agreement_score = max(0, 100 - (variance * 10)) = 79.2
```

**Phase 5 Output (player_prop_predictions):**
```sql
INSERT INTO player_prop_predictions (
  system_id, player_lookup, game_date,
  predicted_points, confidence_score, recommendation,
  current_points_line, line_margin
) VALUES
  ('moving_average', 'lebron-james', '2025-11-15', 25.0, 68.0, 'UNDER', 25.5, -0.5),
  ('zone_matchup_v1', 'lebron-james', '2025-11-15', 29.0, 62.0, 'OVER', 25.5, 3.5),
  ('similarity', 'lebron-james', '2025-11-15', 29.5, 75.0, 'OVER', 25.5, 4.0),
  ('xgboost', 'lebron-james', '2025-11-15', 26.5, 72.0, 'OVER', 25.5, 1.0),
  ('ensemble', 'lebron-james', '2025-11-15', 27.5, 82.0, 'OVER', 25.5, 2.0);
```

---

### Example 2: Rookie Player - Low Quality Features (Graceful Degradation)

**Phase 4 Input (ml_feature_store_v2):**
```json
{
  "player_lookup": "rookie-player",
  "game_date": "2025-11-15",
  "features": [12.5, 11.8, 11.2, 3.5, 3.0, 50.0, 0.0, 0.0, 0.0,
               0.0, 0.0, 0.0, 0.0, 112.0, 100.0, 0.5, 0.0, 0.0,
               0.30, 0.20, 0.35, 0.15, 100.0, 112.0, 0.500],
  "feature_quality_score": 65.0,
  "early_season_flag": false
}
```

**Validation:**
```python
# Phase 5 worker validates
assert early_season_flag == False  # ✅ Pass
assert feature_quality_score >= 70  # ❌ FAIL (65.0 < 70)

# Decision: Quality too low (65 < 70)
# Some systems may skip, others may proceed with warning
```

**System Behavior:**

**Moving Average:**
```python
if feature_quality_score < 70:
    # Skip player - insufficient quality
    log.warning(f"Skipping {player_lookup}: quality {feature_quality_score} < 70")
    return None
```

**Zone Matchup V1:**
```python
if feature_quality_score < 70:
    # Skip player
    return None
```

**Similarity:**
```python
# Check historical games
if historical_games_count < 5:
    # Skip - insufficient similar games (rookie has only 3 games)
    return None
```

**XGBoost:**
```python
# XGBoost is more tolerant of low-quality features
if feature_quality_score >= 60:  # Lower threshold
    predicted_points = xgboost_model.predict(features)
    confidence_score = feature_quality_score  # Lower confidence
    return (predicted_points, confidence_score)
else:
    return None
```

**Ensemble:**
```python
# Only XGBoost returned a prediction
# Cannot ensemble with 1 system - skip player
return None
```

**Phase 5 Output:**
```sql
-- Only 1 prediction (XGBoost only)
INSERT INTO player_prop_predictions (
  system_id, player_lookup, game_date,
  predicted_points, confidence_score, recommendation,
  current_points_line, line_margin,
  warnings
) VALUES
  ('xgboost', 'rookie-player', '2025-11-15', 11.5, 65.0, 'PASS', 11.5, 0.0,
   '["low_feature_quality", "insufficient_historical_data"]');
```

**Result:** Graceful degradation - 1 prediction instead of 5

---

### Example 3: Early Season - Skip Player

**Phase 4 Input (ml_feature_store_v2):**
```json
{
  "player_lookup": "rookie-player",
  "game_date": "2024-10-25",
  "features": [null, null, null, null, null, null, null, null, null,
               null, null, null, null, null, null, null, null, null,
               null, null, null, null, null, null, null],
  "feature_quality_score": 0.0,
  "early_season_flag": true,
  "insufficient_data_reason": "Early season: 280/450 players lack historical data"
}
```

**Validation:**
```python
# Phase 5 worker validates
assert early_season_flag == False  # ❌ FAIL (early_season_flag = TRUE)

# Decision: Skip player entirely (no predictions)
log.info(f"Skipping {player_lookup}: early season")
return None  # All 5 systems skip
```

**Phase 5 Output:** No predictions written

---

## ⚠️ Known Issues & Edge Cases

### Issue 1: Feature Array Length Changes (Future Evolution)
**Problem:** Phase 4 may add features (25→47) in future versions
**Contract:** Phase 5 systems must handle arrays of any length ≥25
**Solution:**
```python
# Safe extraction (works with 25, 47, or any length ≥25)
if len(features) < 25:
    raise ValueError(f"Feature array too short: {len(features)} < 25")

# Extract first 25 features (ignore any extras)
points_last_5 = features[0]
points_last_10 = features[1]
# ... up to features[24]
```
**Impact:** Future-proof - Phase 4 can add features without breaking Phase 5
**Status:** By design - array-based storage enables evolution

### Issue 2: Quality Score Threshold Disagreement
**Problem:** Different systems use different quality thresholds
**Current State:**
- Most systems: quality ≥70
- XGBoost: quality ≥60 (more tolerant)
- Moving Average: quality ≥70 (strict)
**Solution:** Accept variation - systems self-select quality tolerance
**Impact:** Some systems skip players that others process (acceptable)
**Status:** By design - each system defines its own risk tolerance

### Issue 3: Missing Features in Array (NULL values)
**Problem:** Individual features may be NULL (early season, data issues)
**Detection:**
```python
# Check for NULLs in feature array
if any(f is None for f in features):
    null_indices = [i for i, f in enumerate(features) if f is None]
    log.warning(f"NULL features at indices: {null_indices}")
```
**Solution:** System-specific handling
- Moving Average: Use season average as fallback
- XGBoost: Impute with median or skip
- Zone Matchup: Skip if critical features NULL (e.g., shot zones)
**Impact:** Reduced prediction quality but graceful degradation
**Status:** Handled by each system individually

### Issue 4: early_season_flag Cascade
**Problem:** Phase 4 sets early_season_flag if >50% of players lack data
**Impact:** ALL players skipped during early season (first 2-3 weeks)
**Mitigation:** Phase 5 could use estimated features as fallback (future)
**Current State:** Acceptable - wait 2 weeks for sufficient data
**Status:** By design - quality over quantity

### Issue 5: Feature Version Mismatch
**Problem:** Phase 5 expects "v1_baseline_25", Phase 4 writes "v2_enhanced_47"
**Detection:**
```python
if feature_version != 'v1_baseline_25':
    log.error(f"Feature version mismatch: {feature_version} != v1_baseline_25")
    # Decision: Skip player or try to extract first 25 features?
```
**Solution:** Phase 5 systems must check `feature_count` and `feature_version`
**Impact:** Prevents using wrong feature set
**Status:** Critical validation check

---

## ✅ Validation Rules

### Phase 4 Output Validation (Contract Guarantees)

**Table-Level Validation:**
- ✅ **Row count:** ≥450 rows per game_date (normal season)
- ✅ **Partition coverage:** All dates with games must have data
- ✅ **Player coverage:** All players from upcoming_player_game_context present
- ✅ **Quality distribution:** ≥85% of rows with feature_quality_score ≥85

**Row-Level Validation:**
```sql
-- Validate Phase 4 output quality
SELECT
  game_date,
  COUNT(*) as total_players,
  SUM(CASE WHEN early_season_flag = TRUE THEN 1 ELSE 0 END) as early_season,
  SUM(CASE WHEN feature_count != 25 THEN 1 ELSE 0 END) as wrong_feature_count,
  SUM(CASE WHEN feature_version != 'v1_baseline_25' THEN 1 ELSE 0 END) as wrong_version,
  AVG(feature_quality_score) as avg_quality,
  MIN(feature_quality_score) as min_quality
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = CURRENT_DATE()
GROUP BY game_date;

-- Expected (normal season):
-- total_players: ~450
-- early_season: 0-20 (0-5%)
-- wrong_feature_count: 0
-- wrong_version: 0
-- avg_quality: 90-95
-- min_quality: 65-70
```

**Feature Array Validation:**
- ✅ **Array length:** LENGTH(features) = 25
- ✅ **No NULLs:** No NULL values in feature array (or early_season_flag = TRUE)
- ✅ **Value ranges:** All features within expected ranges (see mapping table)

### Phase 5 Input Validation (Worker Checks)

**Before Loading Features:**
```python
# 1. Check table exists
query = f"""
SELECT COUNT(*) FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date = '{game_date}'
"""
if result == 0:
    raise MissingDataError("ml_feature_store_v2 has no data for {game_date}")
```

**After Loading Features:**
```python
# 2. Validate feature row
if early_season_flag == True:
    log.info(f"Skipping {player_lookup}: early season")
    return None

if feature_quality_score < 70:
    log.warning(f"Low quality: {player_lookup} score={feature_quality_score}")
    # Decision: skip or proceed with warning (system-specific)

if len(features) != 25:
    raise ValueError(f"Expected 25 features, got {len(features)}")

if feature_version != 'v1_baseline_25':
    raise ValueError(f"Version mismatch: {feature_version}")

# 3. Validate feature values
for i, value in enumerate(features):
    if value is None:
        log.error(f"NULL feature at index {i} for {player_lookup}")
        # Handle system-specifically

    # Check range (example)
    if i == 0 and not (0 <= value <= 50):  # points_avg_last_5
        log.warning(f"Feature 0 out of range: {value}")
```

### Phase 5 Output Validation (Prediction Quality)

**After Generating Predictions:**
```python
# Validate prediction
if not (0 <= predicted_points <= 60):
    log.error(f"Prediction out of range: {predicted_points}")

if not (0 <= confidence_score <= 100):
    log.error(f"Confidence out of range: {confidence_score}")

if recommendation not in ['OVER', 'UNDER', 'PASS']:
    log.error(f"Invalid recommendation: {recommendation}")
```

---

## 📈 Success Criteria

**Phase 4 Contract Success:**
- ✅ ≥450 rows per game_date (normal season)
- ✅ ≥85% of rows with feature_quality_score ≥85
- ✅ <5% of rows with early_season_flag = TRUE (after Week 3)
- ✅ 100% of rows with feature_count = 25
- ✅ 100% of rows with feature_version = "v1_baseline_25"
- ✅ 0 NULL values in feature arrays (except early season)

**Phase 5 Processing Success:**
- ✅ ≥400 players processed per game_date (90% of 450)
- ✅ ≥5 predictions per processed player (all 5 systems run)
- ✅ Total predictions: ≥2,000 rows per game_date (400 players × 5 systems)
- ✅ Average confidence: ≥70 across all systems
- ✅ <10% of players skipped due to low quality

**System-Specific Success:**

| System | Min Players | Avg Confidence | Quality Threshold |
|--------|-------------|----------------|-------------------|
| Moving Average | ≥400 | ≥65 | 70 |
| Zone Matchup V1 | ≥400 | ≥60 | 70 |
| Similarity | ≥350 | ≥70 | 70 + historical games |
| XGBoost | ≥420 | ≥70 | 60 |
| Ensemble | ≥380 | ≥80 | 70 (4-system) |

**Data Quality Success:**
- ✅ Feature loading latency: <20ms per player
- ✅ Feature extraction errors: <1% of players
- ✅ Version mismatches: 0
- ✅ Early season skips: <5% (after Week 3)

**Cost Success:**
- ✅ Daily queries: 450 (one per player)
- ✅ Data scanned: <1 MB per game_date
- ✅ Cost per day: <$0.001

---

## 🔗 Related Documentation

**Phase 4 Source:**
- Schema: `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`
- Processor: `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- Data mapping: `docs/data-flow/12-phase3-to-phase4-ml-feature-store-v2.md`

**Phase 5 Consumers:**
- Data flow: `docs/data-mapping/phase5_data_flow_mapping.md`
- System algorithms: `docs/prediction-systems/` (if exists)

**Phase 5 Output:**
- Schema: `schemas/bigquery/predictions/01_player_prop_predictions.sql`
- Run `bq show nba_predictions.player_prop_predictions` (when created)

**Cross-Phase Dependencies:**
- Phase 3→4: `docs/data-flow/10-phase3-to-phase4-player-daily-cache.md`
- Phase 3→4: `docs/data-flow/11-phase3-to-phase4-player-composite-factors.md`
- Phase 3→4: `docs/data-flow/09-phase3-to-phase4-player-shot-zone-analysis.md`
- Phase 3→4: `docs/data-flow/08-phase3-to-phase4-team-defense-zone-analysis.md`

**Monitoring:**
- `docs/monitoring/` - Data quality metrics

---

## 📅 Processing Schedule

**Daily Pipeline Timing:**
```
12:00 AM - Phase 4 ML Feature Store V2 completes
           Output: 450 rows with 25 features each
           Quality: ≥85% with score ≥85

6:00 AM  - Phase 5 Coordinator starts
           Query: ml_feature_store_v2 to validate data exists
           Output: 450 Pub/Sub messages

6:15 AM  - Phase 5 Workers start (20 instances × 5 threads)
           Load: ml_feature_store_v2 features (450 queries)
           Process: 5 systems per player
           Write: 2,250 predictions to player_prop_predictions

7:00 AM  - Phase 5 Workers complete
           Result: 2,250 predictions ready for Phase 6
```

**Data Lag:**
- Phase 4 → Phase 5: 6 hours (12:00 AM → 6:00 AM)
- Feature generation → Predictions: ~6 hours
- **Total Lag:** Games end at ~10:00 PM → Predictions ready by 7:00 AM next day

**Dependency Chain:**
1. Phase 3 (10:30 PM): Analytics complete
2. Phase 4 (12:00 AM): ML Feature Store completes ← **Phase 4→5 boundary**
3. **Phase 5 Coordinator (6:00 AM):** Validates features exist
4. **Phase 5 Workers (6:15 AM):** Load features, generate predictions
5. Phase 6 (7:00 AM): Publish predictions

**Critical Timing:**
- Phase 4 MUST complete by 6:00 AM
- If Phase 4 late → Phase 5 delayed or fails
- SLA: Predictions ready by 7:00 AM for morning bettors

---

**Document Version:** 1.0
**Status:** ⚠️ Blocked - Source table missing, contract fully defined
**Next Steps:** Create `nba_predictions.ml_feature_store_v2` table to enable Phase 5 processing
