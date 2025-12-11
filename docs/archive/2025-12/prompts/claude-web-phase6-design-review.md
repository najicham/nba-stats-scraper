# NBA Props Platform - Phase 5B Grading & Phase 6 Publishing Design Review

**Purpose:** This document is for review by Claude (web) to validate our Phase 5B (Grading) implementation and help design Phase 6 (Publishing). Please provide detailed feedback and suggestions.

---

## 1. System Overview

We have an NBA player points prediction platform with the following pipeline:

```
Phase 1-2: Raw Data (NBA API) → BigQuery tables
Phase 3: Analytics (player_game_summary, team summaries)
Phase 4: Precompute (TDZA, PSZA, PCF, PDC, ML Feature Store)
Phase 5A: Predictions (5 systems generate points predictions before games)
Phase 5B: Grading (compare predictions to actual results - JUST IMPLEMENTED)
Phase 6: Publishing (prepare data for website consumption - TO DESIGN)
```

### Current Scale
- **Predictions:** 47,395 records across 62 game dates (Nov 2021 - Nov 2025)
- **Graded:** Currently backfilling all predictions (62 dates, ~10 seconds each)
- **Typical daily volume:** ~750 player-game predictions (150 players × 5 systems)

---

## 2. The 5 Prediction Systems

Each system uses different approaches to predict player points:

### 2.1 moving_average_baseline_v1
- **Approach:** Simple weighted moving average of recent scoring
- **Inputs:** Last 5/10/15 game averages, usage rate
- **Best for:** Stable scorers with consistent roles
- **MAE:** ~4.9 points

### 2.2 zone_matchup_v1
- **Approach:** Zone-based analysis (paint vs mid-range vs 3pt)
- **Inputs:** Player shot distribution, opponent zone defense ratings
- **Best for:** Players with distinct shot profiles
- **MAE:** ~6.2 points (worst performer)

### 2.3 similarity_balanced_v1
- **Approach:** Find similar historical player-games
- **Inputs:** 25 features from ML Feature Store, k-nearest neighbors
- **Best for:** Edge cases, role changes, unusual situations
- **MAE:** ~5.0 points

### 2.4 xgboost_v1
- **Approach:** Gradient boosted trees
- **Inputs:** Same 25 features as similarity
- **Best for:** Complex non-linear patterns
- **MAE:** ~4.75 points (best performer)

### 2.5 ensemble_v1
- **Approach:** Weighted combination of all 4 systems
- **Weights:** Based on recent accuracy, with confidence-based blending
- **MAE:** ~4.79 points (second best)

---

## 3. Phase 5B: Grading Implementation (Just Completed)

### 3.1 Schema (prediction_accuracy table)

```sql
CREATE TABLE prediction_accuracy (
  -- Primary Keys
  player_lookup STRING NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,

  -- Prediction Snapshot
  predicted_points NUMERIC(5, 1),
  confidence_score NUMERIC(4, 3),
  recommendation STRING,  -- OVER/UNDER/PASS
  line_value NUMERIC(5, 1),

  -- Feature Inputs (for ML analysis)
  referee_adjustment NUMERIC(5, 1),
  pace_adjustment NUMERIC(5, 1),
  similarity_sample_size INTEGER,

  -- Actual Result
  actual_points INTEGER,

  -- Core Accuracy Metrics
  absolute_error NUMERIC(5, 1),
  signed_error NUMERIC(5, 1),  -- positive = over-predicted
  prediction_correct BOOLEAN,  -- NULL for PASS recommendations

  -- Margin Analysis
  predicted_margin NUMERIC(5, 1),  -- predicted - line
  actual_margin NUMERIC(5, 1),     -- actual - line

  -- Threshold Accuracy
  within_3_points BOOLEAN,
  within_5_points BOOLEAN,

  -- Metadata
  model_version STRING,
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, player_lookup;
```

### 3.2 Grading Logic

```python
def grade_prediction(prediction, actual_points):
    # Core errors
    absolute_error = abs(predicted - actual)
    signed_error = predicted - actual  # positive = over-predicted

    # Recommendation correctness
    if recommendation == 'PASS':
        prediction_correct = None
    else:
        went_over = actual > line_value
        recommended_over = recommendation == 'OVER'
        prediction_correct = went_over == recommended_over

    # Thresholds
    within_3 = absolute_error <= 3.0
    within_5 = absolute_error <= 5.0

    # Margins
    predicted_margin = predicted - line
    actual_margin = actual - line
```

### 3.3 Initial Grading Results (Sample)

From first 13 dates graded (Nov 6-18, 2021):
```
Date        Graded   MAE    Bias
2021-11-06    578   5.15   -0.87
2021-11-07    816   4.76   -0.61
2021-11-08    817   4.43   -1.32
2021-11-09    297   4.74   -1.58
2021-11-10   1314   5.10   -1.24
2021-11-11    287   4.68   -1.01
2021-11-12   1132   4.34   -0.69
2021-11-13    672   4.77   -1.35
2021-11-14    731   4.30   -0.82
2021-11-15   1156   4.53   -0.82
```

**Observations:**
- MAE ranges from 4.3 to 5.2 points (reasonable for NBA points)
- Consistent negative bias (-0.2 to -1.6) = systems under-predict
- This bias could be corrected with a simple offset adjustment

---

## 4. Phase 5B Review Questions

Please evaluate our Phase 5B implementation:

### Q1: Is grading all 5 systems separately correct?
We grade each system independently (5 records per player-game). This enables:
- System comparison (which works best?)
- Weight optimization for ensemble
- Per-system bias detection

**Alternative:** Only grade ensemble (1 record per player-game), simpler but less insight.

**Question:** Is 5× the data worth the additional insight?

### Q2: Are these metrics sufficient for ML training?

We capture:
- absolute_error (for loss function)
- signed_error (for bias correction)
- prediction_correct (for classification metrics)
- within_3/5 points (for practical accuracy)
- predicted/actual margins (for betting analysis)

**Missing:**
- Percentile accuracy (was prediction in top 25% of outcomes?)
- Context (was game close? player in foul trouble? blowout?)

**Question:** What additional fields would improve ML training?

### Q3: Confidence calibration support?

We store `confidence_score` (0.0-1.0) and can analyze:
- "When system says 80% confident, is it right 80% of the time?"

Current schema doesn't have binned confidence analysis.

**Question:** Should we add a `confidence_bucket` field (e.g., 'HIGH', 'MEDIUM', 'LOW')?

### Q4: Handling PASS recommendations?

Currently: `prediction_correct = NULL` for PASS recommendations (can't grade)

**Alternative options:**
1. Exclude PASS from grading entirely (don't write record)
2. Write record with NULL, include for points accuracy but exclude from win rate
3. Grade PASS as "correct" if margin was small (push territory)

**Question:** Which approach is best for ML training?

---

## 5. Phase 6: Publishing Design

Phase 6 prepares data for website consumption. Help us design this phase.

### 5.1 Existing Schema Infrastructure (Empty)

These tables exist but are unpopulated:

```sql
-- Detailed results per prediction
prediction_results (
  prediction_id, game_date, player_lookup,
  predicted_recommendation, actual_result,
  within_3_points, within_5_points,
  line_margin, actual_margin,
  key_factors JSON
)

-- Daily aggregated performance
system_daily_performance (
  game_date, system_id,
  overall_accuracy, avg_prediction_error, rmse,
  over_accuracy, under_accuracy,
  high_conf_predictions, high_conf_accuracy,
  confidence_calibration_score
)
```

### 5.2 Website Needs (Assumed)

What data does a betting/prediction website need?

1. **Today's Predictions Page**
   - List of player predictions with confidence
   - Recommendations (OVER/UNDER)
   - Key factors driving prediction

2. **System Leaderboard**
   - Which system is hottest?
   - 7-day, 30-day, season accuracy

3. **Player History Page**
   - How accurate are predictions for LeBron?
   - Trend over time

4. **Confidence Analysis**
   - High confidence picks today
   - High confidence accuracy history

### 5.3 Design Questions for Phase 6

**Q5: What should Phase 6 actually do?**

Options:
A) Materialize views for website performance (pre-compute aggregations)
B) Transform data format (JSON for API consumption)
C) Filter/curate (only publish high-confidence predictions)
D) All of the above

**Q6: Update frequency?**

Options:
- Real-time: Update as each game completes
- Batch: Update once daily after all games
- Incremental: Update every hour during game windows

**Q7: Relationship to Phase 5B?**

Should Phase 6 run:
- Sequentially after Phase 5B (grading complete → publish)
- In parallel (publish predictions immediately, grade later)
- Independently (scheduled job regardless of grading status)

**Q8: What aggregations are needed?**

Please suggest the key aggregations/views for website consumption:
- Rolling accuracy (7/30/season)
- By-system comparison
- By-player accuracy
- By-confidence-level accuracy
- By-point-total-bucket accuracy (high scorers vs role players)

---

## 6. Technical Context

### 6.1 Current Stack
- **Data:** Google BigQuery
- **Processing:** Python processors with daily scheduling
- **Tables:** Partitioned by game_date, clustered by relevant keys
- **Backfill:** Idempotent (pre-delete before insert)

### 6.2 Data Volume Estimates

Per season (~1,230 game dates):
- `player_prop_predictions`: ~250k records (5 systems × 50k player-games)
- `prediction_accuracy`: ~250k records (1:1 with predictions)
- `system_daily_performance`: ~6k records (5 systems × 1,230 days)

### 6.3 Performance Considerations

Current query patterns:
- "Get all predictions for today" (partition scan)
- "Get system accuracy over 30 days" (moderate scan)
- "Get player historical accuracy" (requires clustering)

---

## 7. Summary of Questions

1. **Q1:** Is grading all 5 systems separately correct?
2. **Q2:** What additional fields would improve ML training?
3. **Q3:** Should we add confidence buckets for calibration?
4. **Q4:** How should PASS recommendations be handled?
5. **Q5:** What should Phase 6 actually do?
6. **Q6:** What update frequency is appropriate?
7. **Q7:** How should Phase 6 relate to Phase 5B?
8. **Q8:** What aggregations are needed for the website?

---

## 8. Additional Context

### Key Files in Codebase
```
predictions/worker/prediction_systems/
  - base_predictor.py (abstract class)
  - moving_average_baseline.py
  - zone_matchup_v1.py
  - similarity_balanced_v1.py
  - xgboost_v1.py
  - ensemble_v1.py

data_processors/grading/prediction_accuracy/
  - prediction_accuracy_processor.py

backfill_jobs/grading/prediction_accuracy/
  - prediction_accuracy_grading_backfill.py

schemas/bigquery/nba_predictions/
  - prediction_accuracy.sql
  - player_prop_predictions.sql (not committed)
```

### Related Tables
- `nba_predictions.player_prop_predictions` - Phase 5A output
- `nba_predictions.prediction_accuracy` - Phase 5B output
- `nba_predictions.prediction_results` - Phase 6 (empty)
- `nba_predictions.system_daily_performance` - Phase 6 (empty)
- `nba_analytics.player_game_summary` - Actual points scored

---

**Please provide comprehensive feedback on:**
1. Validation of Phase 5B implementation
2. Design recommendations for Phase 6
3. Any concerns or alternative approaches we should consider
