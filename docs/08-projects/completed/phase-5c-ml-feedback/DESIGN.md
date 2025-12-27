# Phase 5C: ML Feedback Loop - Design Document

**Status:** Implementation Phase (Scoring Tier Integration)
**Created:** 2025-12-10
**Updated:** 2025-12-10
**Purpose:** Data structures that help ML systems learn from prediction errors

---

## 1. Executive Summary

Phase 5C creates feedback tables that allow prediction systems to learn from their mistakes. Unlike Phase 6 (website publishing), this data is consumed by the ML pipeline to improve future predictions.

### Key Insight from Investigation

Our bias analysis revealed severe under-prediction of high scorers:

| Scoring Tier | Avg Bias | Avg Predicted | Avg Actual |
|--------------|----------|---------------|------------|
| 30+ (stars)  | -12.64   | 21.2          | 33.8       |
| 20-29        | -7.17    | 16.4          | 23.5       |
| 10-19        | -3.10    | 10.8          | 13.9       |
| 0-9 (bench)  | +1.63    | 5.7           | 4.1        |

**Root Cause:** Excessive regression to mean. The ML system needs feedback to correct this.

---

## 2. Data Flow

```
Phase 5A: Predictions generated
    ↓
Phase 5B: Predictions graded (prediction_accuracy)
    ↓
Phase 5C: ML feedback tables computed ← YOU ARE HERE
    ↓
Phase 5A (next day): Predictions use feedback adjustments
```

---

## 3. Proposed Tables

### 3.1 Player Prediction Bias (`player_prediction_bias`)

**Purpose:** Track per-player bias so predictions can be adjusted.

**Use Case:** "We under-predict LeBron by 4.2 points on average. Add +4.2 to his prediction."

**Schema:**
```sql
CREATE TABLE player_prediction_bias (
  -- Keys
  player_lookup STRING NOT NULL,
  system_id STRING NOT NULL,
  as_of_date DATE NOT NULL,  -- When this was computed

  -- Sample
  sample_size INTEGER,        -- Games with graded predictions
  games_last_30d INTEGER,     -- Recent sample for weighting

  -- Bias Metrics
  avg_signed_error NUMERIC(5,2),      -- Positive = over-predict, Negative = under-predict
  avg_absolute_error NUMERIC(5,2),    -- MAE for this player
  bias_stddev NUMERIC(5,2),           -- Consistency of bias

  -- Recommended Adjustment
  recommended_adjustment NUMERIC(5,2), -- Add this to prediction (opposite of bias)
  adjustment_confidence NUMERIC(4,3),  -- How confident (based on sample size)

  -- Context
  avg_actual_points NUMERIC(5,1),     -- Player's scoring average
  scoring_tier STRING,                 -- 'STAR', 'STARTER', 'ROTATION', 'BENCH'

  -- Metadata
  computed_at TIMESTAMP
)
PARTITION BY as_of_date
CLUSTER BY player_lookup, system_id;
```

**Computation Logic:**
```python
def compute_player_bias(player_lookup, system_id, as_of_date):
    # Get last 30 games of graded predictions
    games = query("""
        SELECT signed_error, absolute_error, actual_points
        FROM prediction_accuracy
        WHERE player_lookup = @player AND system_id = @system
          AND game_date < @as_of_date
        ORDER BY game_date DESC LIMIT 30
    """)

    if len(games) < 5:
        return None  # Not enough data

    avg_bias = mean(games.signed_error)

    # Adjustment is opposite of bias
    # If we under-predict by 4 (bias = -4), adjustment = +4
    recommended_adjustment = -avg_bias

    # Confidence based on sample size and consistency
    confidence = min(1.0, len(games) / 20) * (1 - stddev(games.signed_error) / 10)

    return {
        'recommended_adjustment': recommended_adjustment,
        'adjustment_confidence': confidence
    }
```

**How Predictions Use This:**
```python
def predict_with_bias_correction(player_lookup, base_prediction):
    bias = get_player_bias(player_lookup, system_id='ensemble_v1')

    if bias and bias.adjustment_confidence > 0.5:
        adjustment = bias.recommended_adjustment * bias.adjustment_confidence
        return base_prediction + adjustment

    return base_prediction
```

---

### 3.2 Confidence Calibration (`confidence_calibration`)

**Purpose:** Track whether confidence scores are well-calibrated.

**Use Case:** "When we say 70% confident, we're actually right 85% of the time. Recalibrate."

**Schema:**
```sql
CREATE TABLE confidence_calibration (
  -- Keys
  system_id STRING NOT NULL,
  confidence_bucket INTEGER NOT NULL,  -- 1-10 (decile)
  as_of_date DATE NOT NULL,

  -- Sample
  sample_size INTEGER,

  -- Calibration Metrics
  bucket_midpoint NUMERIC(4,3),        -- 0.05, 0.15, ..., 0.95
  actual_win_rate NUMERIC(4,3),        -- What actually happened
  calibration_error NUMERIC(4,3),      -- |actual - expected|

  -- For Recalibration
  recommended_multiplier NUMERIC(4,3), -- Multiply confidence by this

  -- Metadata
  computed_at TIMESTAMP
)
PARTITION BY as_of_date
CLUSTER BY system_id;
```

**Example Data:**
| system_id | bucket | midpoint | actual_win_rate | calibration_error |
|-----------|--------|----------|-----------------|-------------------|
| ensemble  | 5      | 0.50     | 0.62            | 0.12 (under-confident) |
| ensemble  | 7      | 0.70     | 0.85            | 0.15 (under-confident) |
| ensemble  | 9      | 0.90     | 0.88            | 0.02 (well-calibrated) |

**How Predictions Use This:**
```python
def recalibrate_confidence(raw_confidence, system_id):
    bucket = int(raw_confidence * 10)
    calibration = get_calibration(system_id, bucket)

    if calibration:
        # If actual > expected, we're under-confident, boost it
        return raw_confidence * calibration.recommended_multiplier

    return raw_confidence
```

---

### 3.3 Scoring Tier Adjustments (`scoring_tier_adjustments`)

**Purpose:** Systematic corrections by scoring tier (addresses the -12.6 bias for stars).

**Use Case:** "All systems under-predict 30+ scorers by ~12 points. Apply tier adjustment."

**Schema:**
```sql
CREATE TABLE scoring_tier_adjustments (
  -- Keys
  system_id STRING NOT NULL,
  scoring_tier STRING NOT NULL,  -- 'STAR_30PLUS', 'STARTER_20_29', 'ROTATION_10_19', 'BENCH_0_9'
  as_of_date DATE NOT NULL,

  -- Sample
  sample_size INTEGER,

  -- Tier Bias
  avg_signed_error NUMERIC(5,2),
  avg_absolute_error NUMERIC(5,2),

  -- Tier-Specific Adjustment
  recommended_adjustment NUMERIC(5,2),
  adjustment_confidence NUMERIC(4,3),

  -- Tier Bounds (for classification)
  tier_min_points NUMERIC(5,1),
  tier_max_points NUMERIC(5,1),

  -- Metadata
  computed_at TIMESTAMP
)
PARTITION BY as_of_date
CLUSTER BY system_id, scoring_tier;
```

**Current Data (from investigation):**
| scoring_tier | avg_bias | recommended_adjustment |
|--------------|----------|------------------------|
| STAR_30PLUS  | -12.64   | +12.64                 |
| STARTER_20_29| -7.17    | +7.17                  |
| ROTATION_10_19| -3.10   | +3.10                  |
| BENCH_0_9    | +1.63    | -1.63                  |

---

### 3.4 Context Error Correlations (`context_error_correlations`)

**Purpose:** Identify which game contexts correlate with prediction errors.

**Use Case:** "We're 3 points worse on back-to-backs. Adjust for fatigue context."

**Schema:**
```sql
CREATE TABLE context_error_correlations (
  -- Keys
  system_id STRING NOT NULL,
  context_feature STRING NOT NULL,  -- 'back_to_back', 'home_game', 'high_pace', etc.
  as_of_date DATE NOT NULL,

  -- Sample
  sample_size_with_context INTEGER,
  sample_size_without_context INTEGER,

  -- Error Comparison
  mae_with_context NUMERIC(5,2),
  mae_without_context NUMERIC(5,2),
  mae_difference NUMERIC(5,2),       -- Positive = worse with context

  bias_with_context NUMERIC(5,2),
  bias_without_context NUMERIC(5,2),

  -- Statistical Significance
  is_significant BOOLEAN,            -- p < 0.05

  -- Recommended Action
  recommended_adjustment NUMERIC(5,2),

  -- Metadata
  computed_at TIMESTAMP
)
PARTITION BY as_of_date
CLUSTER BY system_id;
```

**Example Contexts to Track:**
- `back_to_back` - Second game in 2 days
- `3_games_in_4_nights` - Heavy schedule
- `home_game` - Home vs away
- `high_pace_matchup` - Opponent pace > 102
- `blowout_risk` - Large spread games
- `primetime_game` - National TV games

---

### 3.5 System Agreement Patterns (`system_agreement_patterns`)

**Purpose:** Track accuracy when systems agree vs disagree.

**Use Case:** "When all 4 systems agree within 2 points, we're 95% accurate. Boost confidence."

**Schema:**
```sql
CREATE TABLE system_agreement_patterns (
  -- Keys
  agreement_level STRING NOT NULL,  -- 'HIGH', 'GOOD', 'MODERATE', 'LOW'
  as_of_date DATE NOT NULL,

  -- Definition
  max_variance NUMERIC(5,2),        -- Variance threshold for this level

  -- Sample
  sample_size INTEGER,

  -- Accuracy at This Agreement Level
  win_rate NUMERIC(4,3),
  avg_mae NUMERIC(5,2),

  -- Comparison to Overall
  win_rate_vs_overall NUMERIC(4,3),  -- Difference from overall win rate
  mae_vs_overall NUMERIC(5,2),       -- Difference from overall MAE

  -- Recommended Confidence Adjustment
  confidence_multiplier NUMERIC(4,3), -- Multiply ensemble confidence by this

  -- Metadata
  computed_at TIMESTAMP
)
PARTITION BY as_of_date;
```

**Expected Patterns:**
| agreement_level | variance | win_rate | confidence_multiplier |
|-----------------|----------|----------|----------------------|
| HIGH            | < 2.0    | 0.95     | 1.15 (boost)         |
| GOOD            | < 4.0    | 0.88     | 1.05                 |
| MODERATE        | < 6.0    | 0.82     | 0.95                 |
| LOW             | > 6.0    | 0.70     | 0.80 (reduce)        |

---

## 4. Refresh Schedule

| Table | Frequency | Trigger |
|-------|-----------|---------|
| `player_prediction_bias` | Daily | After Phase 5B grading |
| `confidence_calibration` | Weekly | Sunday night |
| `scoring_tier_adjustments` | Weekly | Sunday night |
| `context_error_correlations` | Weekly | Sunday night |
| `system_agreement_patterns` | Weekly | Sunday night |

---

## 5. Integration with Phase 5A

### Current Flow (No Feedback)
```python
def predict(player_lookup, features):
    return ensemble.predict(features)  # Raw prediction
```

### Future Flow (With Feedback)
```python
def predict_with_feedback(player_lookup, features, game_context):
    # 1. Get base prediction
    base_pred = ensemble.predict(features)

    # 2. Apply player-specific bias correction
    player_bias = get_player_bias(player_lookup)
    if player_bias and player_bias.confidence > 0.5:
        base_pred += player_bias.adjustment * player_bias.confidence

    # 3. Apply scoring tier adjustment
    tier = classify_scoring_tier(base_pred)
    tier_adj = get_tier_adjustment(tier)
    base_pred += tier_adj.adjustment * 0.5  # Partial application

    # 4. Apply context adjustments
    for context in game_context:
        ctx_adj = get_context_adjustment(context)
        if ctx_adj and ctx_adj.is_significant:
            base_pred += ctx_adj.adjustment

    # 5. Recalibrate confidence
    raw_confidence = ensemble.get_confidence()
    calibrated_confidence = recalibrate(raw_confidence)

    # 6. Adjust for system agreement
    agreement = get_system_agreement()
    final_confidence = calibrated_confidence * agreement.multiplier

    return base_pred, final_confidence
```

---

## 5A. Prediction Integration Design (Session 119 Decision)

### Decision: Add Columns to Predictions Table (Option B)

Two approaches were considered for integrating scoring tier adjustments:

| Criteria | Option A (Separate system_id) | Option B (Add columns) |
|----------|-------------------------------|------------------------|
| Query simplicity | Need JOIN or WHERE clause | Single SELECT |
| Storage | 2x rows for adjusted preds | Same row count |
| Comparison | Hard (different rows) | Easy (same row) |
| Schema change | None | 3 new columns |
| Backwards compatible | Yes | Yes (new cols nullable) |

**Selected: Option B** - Add columns to `player_prop_predictions` table.

### New Columns for `player_prop_predictions`

```sql
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN scoring_tier STRING,        -- STAR_30PLUS, STARTER_20_29, etc.
ADD COLUMN tier_adjustment FLOAT,      -- The scaled adjustment applied
ADD COLUMN adjusted_points FLOAT;      -- predicted_points + tier_adjustment
```

### Tier-Specific Adjustment Factors

Validated in Session 117 analysis:

| Tier | Bias | Raw Adjustment | Factor | Scaled Adjustment |
|------|------|----------------|--------|-------------------|
| STAR_30PLUS | -13.2 | +13.2 | 100% | +13.2 |
| STARTER_20_29 | -7.8 | +7.8 | 75% | +5.85 |
| ROTATION_10_19 | -3.6 | +3.6 | 50% | +1.8 |
| BENCH_0_9 | +1.6 | -1.6 | 50% | -0.8 |

**Rationale for factors:**
- Stars have extreme bias and need full correction
- Lower tiers have smaller biases where over-correction could hurt

### Implementation in Backfill

Only ensemble predictions get adjusted (individual systems remain unchanged):

```python
from data_processors.ml_feedback.scoring_tier_processor import ScoringTierAdjuster

# Initialize once per backfill
adjuster = ScoringTierAdjuster()

# For each prediction:
if system_name == 'ensemble':
    tier = adjuster.classify_tier(predicted_points)
    adjustment = adjuster.get_scaled_adjustment(predicted_points, as_of_date)
    adjusted_points = predicted_points + adjustment

    row['scoring_tier'] = tier
    row['tier_adjustment'] = adjustment
    row['adjusted_points'] = adjusted_points
```

### Validation Query

After re-backfill, validate improvement:

```sql
SELECT
  p.scoring_tier,
  COUNT(*) as predictions,
  AVG(ABS(a.actual_points - p.predicted_points)) as raw_mae,
  AVG(ABS(a.actual_points - p.adjusted_points)) as adjusted_mae,
  AVG(ABS(a.actual_points - p.predicted_points)) - AVG(ABS(a.actual_points - p.adjusted_points)) as improvement
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy a
  ON p.player_lookup = a.player_lookup
  AND p.game_date = a.game_date
  AND p.system_id = a.system_id
WHERE p.system_id = 'ensemble_v1'
  AND p.adjusted_points IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

### Files Created/Modified

**Created (Session 118):**
- `data_processors/ml_feedback/scoring_tier_processor.py` - ScoringTierAdjuster class
- `tests/processors/ml_feedback/test_scoring_tier.py` - 32 unit tests

**To Modify (Session 119):**
- `backfill_jobs/prediction/player_prop_predictions_backfill.py` - Add adjustment logic

---

## 6. Implementation Priority

### Phase 5C.1 (High Impact, Easy)
1. **`scoring_tier_adjustments`** - Addresses the -12.6 bias immediately
2. **`player_prediction_bias`** - Per-player corrections

### Phase 5C.2 (Medium Impact)
3. **`confidence_calibration`** - Better confidence scores
4. **`system_agreement_patterns`** - Leverage ensemble agreement

### Phase 5C.3 (Lower Priority)
5. **`context_error_correlations`** - Context-aware adjustments

---

## 7. Success Metrics

After implementing Phase 5C, we should see:

| Metric | Current | Target |
|--------|---------|--------|
| 30+ scorer bias | -12.6 | < -3.0 |
| Overall MAE | 4.5 | < 4.0 |
| Calibration error | Unknown | < 0.05 |
| High-agreement accuracy | Unknown | > 90% |

---

## 8. Open Questions

1. **How aggressively to apply adjustments?** Full adjustment vs partial (50%)?
2. **Minimum sample size?** 5 games? 10 games? 20 games?
3. **Decay rate?** Should recent games matter more than older games?
4. **Per-system or ensemble-only?** Apply corrections to each system or just ensemble?

---

## 9. Files to Create

```
data_processors/ml_feedback/
├── __init__.py
├── player_bias_processor.py
├── confidence_calibration_processor.py
├── scoring_tier_processor.py
├── context_correlation_processor.py
└── system_agreement_processor.py

backfill_jobs/ml_feedback/
├── __init__.py
└── ml_feedback_backfill.py

schemas/bigquery/nba_predictions/
├── player_prediction_bias.sql
├── confidence_calibration.sql
├── scoring_tier_adjustments.sql
├── context_error_correlations.sql
└── system_agreement_patterns.sql
```

---

## 10. Next Steps

1. [ ] Review this design
2. [ ] Decide on implementation priority (5C.1 first?)
3. [ ] Create schemas
4. [ ] Implement processors
5. [ ] Backfill historical data
6. [ ] Integrate with Phase 5A prediction pipeline
7. [ ] Measure improvement

---

**Document End**
