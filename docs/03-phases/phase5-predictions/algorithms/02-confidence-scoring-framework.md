# Phase 5 Confidence Scoring Framework

**File:** `docs/predictions/algorithms/02-confidence-scoring-framework.md`
**Created:** 2025-11-16
**Purpose:** Six-factor confidence scoring system for evaluating prediction quality and reliability
**Status:** ✅ Current

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Confidence Calculation Framework](#confidence-framework)
3. [Factor 1: Similarity Match Quality](#similarity-quality)
4. [Factor 2: Data Completeness](#data-completeness)
5. [Factor 3: Signal Consistency](#signal-consistency)
6. [Factor 4: Historical Variance](#historical-variance)
7. [Factor 5: Prediction Margin](#prediction-margin)
8. [Factor 6: Contextual Red Flags](#red-flags)
9. [Complete Calculation Example](#calculation-example)
10. [Confidence Tiers & Recommendations](#confidence-tiers)
11. [Special Situations](#special-situations)
12. [Implementation](#implementation)
13. [Related Documentation](#related-docs)

---

## 🎯 Executive Summary {#executive-summary}

Confidence scoring evaluates the quality and reliability of each prediction, producing a 0-100 score that indicates how much we trust the prediction. High confidence predictions receive stronger recommendations, while low confidence predictions may be passed on entirely.

### Core Principle

Not all predictions are created equal. Confidence scoring helps us identify which predictions are backed by strong data, consistent signals, and favorable circumstances, enabling risk-appropriate betting decisions.

### Confidence Score Impact

| Range | Confidence Level | Action |
|-------|------------------|--------|
| **85-100** | High confidence | Recommend with higher stake |
| **70-84** | Medium-high confidence | Standard recommendation |
| **55-69** | Medium confidence | Small stake or track only |
| **40-54** | Low confidence | Track only, no recommendation |
| **0-39** | Very low confidence | Do not use |

---

## 🔢 Confidence Calculation Framework {#confidence-framework}

### Six-Factor Scoring System

```python
def calculate_confidence_score(prediction_inputs):
    """
    Calculate 0-100 confidence score based on 6 factors

    Returns: int (0-100)
    """
    score = 50  # Start at neutral baseline

    # Factor 1: Similarity Match Quality (max +25 points)
    score += calculate_similarity_quality_score(prediction_inputs)

    # Factor 2: Data Completeness (max +15 points)
    score += calculate_data_completeness_score(prediction_inputs)

    # Factor 3: Signal Consistency (max +15 points)
    score += calculate_signal_consistency_score(prediction_inputs)

    # Factor 4: Historical Variance (max +10 points)
    score += calculate_variance_score(prediction_inputs)

    # Factor 5: Prediction Margin (max +10 points)
    score += calculate_margin_score(prediction_inputs)

    # Factor 6: Contextual Red Flags (penalties)
    score += calculate_red_flags_penalty(prediction_inputs)

    # Clamp to valid range
    return max(0, min(100, int(score)))
```

---

## 📊 Factor 1: Similarity Match Quality (Max +25 Points) {#similarity-quality}

### Overview

Measures the quality and quantity of similar historical games found. More similar games with higher match scores = higher confidence.

### Calculation

```python
def calculate_similarity_quality_score(prediction_inputs):
    """
    Score similarity match quality
    Returns: 0 to +25 points
    """
    score = 0

    # Sub-factor A: Sample Size (max +15 points)
    sample_size = prediction_inputs.similar_games_count

    if sample_size >= 40:
        score += 15  # Exceptional sample
    elif sample_size >= 25:
        score += 12  # Excellent sample
    elif sample_size >= 15:
        score += 10  # Good sample
    elif sample_size >= 10:
        score += 5   # Adequate sample
    else:
        score -= 10  # Insufficient sample (penalty)

    # Sub-factor B: Average Similarity Score (max +10 points)
    avg_similarity = prediction_inputs.avg_similarity_score

    if avg_similarity >= 80:
        score += 10  # Excellent matches
    elif avg_similarity >= 70:
        score += 8   # Very good matches
    elif avg_similarity >= 60:
        score += 5   # Good matches
    elif avg_similarity >= 50:
        score += 2   # Acceptable matches
    else:
        score -= 5   # Poor matches (penalty)

    return score
```

### Examples

**High Quality (Score: +23):**
- Sample Size: 32 games → +12 points
- Avg Similarity: 76 → +8 points
- Minimum Similarity: 68 → +3 bonus points
- **Total: +23 points**

**Low Quality (Score: -8):**
- Sample Size: 8 games → -10 points (insufficient)
- Avg Similarity: 52 → +2 points
- **Total: -8 points**

---

## 📋 Factor 2: Data Completeness (Max +15 Points) {#data-completeness}

### Overview

Checks what percentage of expected data fields are populated and high quality. Missing data reduces confidence.

### Calculation

```python
def calculate_data_completeness_score(prediction_inputs):
    """
    Score data quality and completeness
    Returns: 0 to +15 points
    """
    # Check critical fields
    required_fields = [
        'fatigue_score',
        'shot_zone_mismatch_score',
        'referee_favorability_score',
        'opponent_def_rating_last_10',
        'days_rest',
        'points_avg_last_5',
        'current_points_line',
        'composite_factors_calculated'
    ]

    # Count populated fields
    populated = sum(
        1 for field in required_fields
        if getattr(prediction_inputs, field) is not None
    )

    completeness_pct = (populated / len(required_fields)) * 100

    # Score based on completeness
    if completeness_pct >= 95:
        score = 15  # Complete data
    elif completeness_pct >= 85:
        score = 10  # Mostly complete
    elif completeness_pct >= 75:
        score = 5   # Acceptable
    else:
        score = -5  # Significant gaps (penalty)

    # Bonus for high data quality tier
    if prediction_inputs.data_quality_tier == 'high':
        score += 3
    elif prediction_inputs.data_quality_tier == 'low':
        score -= 3

    return score
```

### Examples

**Complete Data (Score: +18 → capped at +15):**
- 8 of 8 required fields populated → +15 points
- Data quality tier: high → +3 points
- **Total: +18 points (capped at +15)**

**Incomplete Data (Score: -5):**
- 5 of 8 required fields populated → -5 points
- Data quality tier: medium → 0 points
- **Total: -5 points**

---

## 🎯 Factor 3: Signal Consistency (Max +15 Points) {#signal-consistency}

### Overview

Checks if multiple prediction factors agree on direction (all pointing OVER or all pointing UNDER). Agreement = higher confidence.

### Calculation

```python
def calculate_signal_consistency_score(prediction_inputs):
    """
    Check if adjustment factors agree or conflict
    Returns: 0 to +15 points
    """
    # Get adjustment directions
    adjustments = {
        'fatigue': prediction_inputs.fatigue_adjustment,
        'shot_zone': prediction_inputs.shot_zone_adjustment,
        'referee': prediction_inputs.referee_adjustment,
        'look_ahead': prediction_inputs.look_ahead_adjustment,
        'pace': prediction_inputs.pace_adjustment,
        'usage_spike': prediction_inputs.usage_spike_adjustment
    }

    # Count positive vs negative adjustments
    positive = sum(1 for v in adjustments.values() if v > 0.5)
    negative = sum(1 for v in adjustments.values() if v < -0.5)
    neutral = sum(1 for v in adjustments.values() if abs(v) <= 0.5)

    total_signals = positive + negative + neutral

    # Perfect agreement (all same direction)
    if positive >= 5 and negative == 0:
        return 15  # Strong bullish consensus
    elif negative >= 5 and positive == 0:
        return 15  # Strong bearish consensus

    # Strong majority agreement
    elif positive >= 4 and negative <= 1:
        return 12  # Mostly bullish
    elif negative >= 4 and positive <= 1:
        return 12  # Mostly bearish

    # Moderate agreement
    elif positive >= 3 and negative <= 1:
        return 8   # Lean bullish
    elif negative >= 3 and positive <= 1:
        return 8   # Lean bearish

    # Mixed signals (conflict)
    elif abs(positive - negative) <= 1:
        return 0   # No clear consensus

    # Mostly neutral signals
    elif neutral >= 4:
        return 3   # Weak signals overall

    else:
        return 5   # Some agreement
```

### Examples

**Strong Agreement (Score: +15):**
- Fatigue: +0.8 (positive)
- Shot Zone: +1.2 (positive)
- Referee: +0.3 (positive)
- Look-Ahead: -0.2 (neutral)
- Pace: +0.6 (positive)
- Usage: +0.9 (positive)
- **Result: 5 positive, 0 negative → +15 points**

**Conflicting Signals (Score: 0):**
- Fatigue: -3.2 (negative)
- Shot Zone: +1.8 (positive)
- Referee: -0.4 (negative)
- Look-Ahead: +0.6 (positive)
- Pace: -0.3 (neutral)
- Usage: +0.7 (positive)
- **Result: 3 positive, 2 negative → 0 points (mixed)**

---

## 📉 Factor 4: Historical Variance (Max +10 Points) {#historical-variance}

### Overview

Low variance in similar historical games indicates consistent performance in this situation. High variance = unpredictable = lower confidence.

### Calculation

```python
def calculate_variance_score(prediction_inputs):
    """
    Reward consistent historical performance
    Returns: 0 to +10 points
    """
    std_dev = prediction_inputs.points_std_dev

    # Lower standard deviation = more consistent = higher confidence
    if std_dev <= 3.5:
        return 10  # Very consistent
    elif std_dev <= 5.0:
        return 7   # Consistent
    elif std_dev <= 6.5:
        return 4   # Moderate consistency
    elif std_dev <= 8.0:
        return 1   # Some variance
    else:
        return -5  # High variance (penalty)
```

### Examples

**Consistent Performance (Score: +10):**
- Similar games: [27, 29, 28, 26, 30, 28, 27, 29]
- Standard deviation: 1.4 points
- **Score: +10 points**

**Volatile Performance (Score: -5):**
- Similar games: [18, 32, 22, 38, 19, 35, 21, 36]
- Standard deviation: 8.7 points
- **Score: -5 points**

---

## 🎲 Factor 5: Prediction Margin (Max +10 Points) {#prediction-margin}

### Overview

How far is the prediction from the betting line? Larger margins suggest clearer edge opportunities and justify higher confidence.

### Calculation

```python
def calculate_margin_score(prediction_inputs):
    """
    Reward predictions with clear separation from line
    Returns: 0 to +10 points
    """
    predicted = prediction_inputs.predicted_points
    line = prediction_inputs.current_points_line
    margin = abs(predicted - line)

    # Larger margin = clearer signal
    if margin >= 4.0:
        return 10  # Very clear edge
    elif margin >= 3.0:
        return 8   # Clear edge
    elif margin >= 2.0:
        return 5   # Moderate edge
    elif margin >= 1.0:
        return 2   # Small edge
    else:
        return -5  # Too close to line (penalty)
```

### Examples

**Strong Conviction (Score: +10):**
- Predicted: 31.5 points
- Line: 27.0 points
- Margin: 4.5 points
- **Score: +10 points**

**Weak Conviction (Score: -5):**
- Predicted: 27.3 points
- Line: 27.0 points
- Margin: 0.3 points
- **Score: -5 points**

---

## 🚩 Factor 6: Contextual Red Flags (Penalties Only) {#red-flags}

### Overview

Specific circumstances that reduce confidence in predictions. These are penalties that subtract from the score.

### Calculation

```python
def calculate_red_flags_penalty(prediction_inputs):
    """
    Identify warning signs that reduce confidence
    Returns: 0 to -30 points (penalties only)
    """
    penalty = 0

    # Red Flag 1: Player Status Uncertain
    if prediction_inputs.player_status == 'questionable':
        penalty -= 10  # May not play or limited minutes
    elif prediction_inputs.player_status == 'doubtful':
        penalty -= 20  # Significant uncertainty

    # Red Flag 2: Late Line Movement
    if abs(prediction_inputs.line_movement) >= 2.0:
        penalty -= 5   # Sharp money moving away
    elif abs(prediction_inputs.line_movement) >= 3.0:
        penalty -= 10  # Major line movement

    # Red Flag 3: Missing Opponent Defense Data
    if prediction_inputs.opponent_defense_incomplete:
        penalty -= 5   # Can't properly assess matchup

    # Red Flag 4: Extreme Fatigue
    if prediction_inputs.fatigue_score < 35:
        penalty -= 8   # Player in danger zone

    # Red Flag 5: Back-to-Back + Travel
    if prediction_inputs.back_to_back and prediction_inputs.time_zones_crossed >= 2:
        penalty -= 5   # Brutal schedule situation

    # Red Flag 6: New/Changed Context
    if prediction_inputs.context_recently_changed:
        penalty -= 5   # Prediction may be stale

    # Red Flag 7: Rookie or Limited History
    if prediction_inputs.player_games_played < 30:
        penalty -= 10  # Insufficient track record

    # Red Flag 8: Playoff Implications
    if prediction_inputs.playoff_implications:
        penalty -= 3   # Unpredictable motivation

    return penalty
```

### Example

**Multiple Red Flags (Score: -28):**
- Player Status: questionable → -10 points
- Line Movement: -2.5 points → -5 points
- Extreme Fatigue: score 32 → -8 points
- Back-to-back + 3 time zones → -5 points
- **Total Penalty: -28 points**

---

## 💡 Complete Calculation Example {#calculation-example}

### Scenario: LeBron James vs Phoenix Suns

**Input Data:**

```python
prediction_inputs = {
    # Similarity quality
    'similar_games_count': 28,
    'avg_similarity_score': 75,

    # Data completeness
    'all_fields_populated': True,
    'data_quality_tier': 'high',

    # Adjustments (signal consistency)
    'fatigue_adjustment': -3.5,      # Negative
    'shot_zone_adjustment': +1.2,    # Positive
    'referee_adjustment': +0.3,      # Positive
    'look_ahead_adjustment': -0.4,   # Negative
    'pace_adjustment': +0.1,         # Neutral
    'usage_spike_adjustment': +0.7,  # Positive

    # Variance
    'points_std_dev': 5.2,

    # Prediction margin
    'predicted_points': 28.7,
    'current_points_line': 27.5,

    # Red flags
    'player_status': 'active',
    'line_movement': -0.5,
    'fatigue_score': 42,
    'back_to_back': False
}
```

### Step-by-Step Calculation

```python
# Start at baseline
confidence_score = 50

# Factor 1: Similarity Quality
# - 28 games → +12 points
# - Avg 75 similarity → +8 points
confidence_score += 20  # Now 70

# Factor 2: Data Completeness
# - All fields populated (100%) → +15 points
# - High quality tier → +3 points (capped at +15 total)
confidence_score += 15  # Now 85

# Factor 3: Signal Consistency
# - 3 positive, 2 negative, 1 neutral → Moderate conflict
confidence_score += 5  # Now 90

# Factor 4: Variance
# - Std dev 5.2 → Moderate consistency
confidence_score += 4  # Now 94

# Factor 5: Prediction Margin
# - Margin: 1.2 points → Small edge
confidence_score += 2  # Now 96

# Factor 6: Red Flags
# - Extreme fatigue (score 42) → -8 points
# - No other red flags
confidence_score -= 8  # Now 88

# Final Score
final_confidence = max(0, min(100, 88))
# Result: 88 (High Confidence)
```

### Interpretation

**88 = High Confidence**

- Strong sample size and data quality
- Clear prediction edge (1.2 points above line)
- Main concern: extreme fatigue
- **Recommendation:** OVER with high confidence, but note fatigue risk

---

## 🎚️ Confidence Tiers & Recommendations {#confidence-tiers}

### Tier Definitions

```python
def get_confidence_tier(confidence_score):
    """Map confidence score to tier"""
    if confidence_score >= 85:
        return "VERY_HIGH"
    elif confidence_score >= 70:
        return "HIGH"
    elif confidence_score >= 55:
        return "MEDIUM"
    elif confidence_score >= 40:
        return "LOW"
    else:
        return "VERY_LOW"
```

### Recommendation Rules by Tier

```python
def generate_recommendation(predicted_points, line, confidence_score, min_margin=0.75):
    """
    Generate betting recommendation based on confidence
    """
    margin = predicted_points - line
    tier = get_confidence_tier(confidence_score)

    # Confidence-based margin requirements
    if tier == "VERY_HIGH":
        required_margin = 0.5  # Can recommend on smaller edges
    elif tier == "HIGH":
        required_margin = 0.75
    elif tier == "MEDIUM":
        required_margin = 1.25
    elif tier == "LOW":
        required_margin = 2.0
    else:
        return "PASS"  # Don't recommend very low confidence

    # Make recommendation
    if margin >= required_margin:
        return "OVER"
    elif margin <= -required_margin:
        return "UNDER"
    else:
        return "PASS"  # In no-man's land
```

### Tier Characteristics

| Tier | Range | Characteristics | Action |
|------|-------|----------------|--------|
| **Very High** | 85-100 | Strong data, clear signals, large sample | Recommend with higher stake |
| **High** | 70-84 | Good data, mostly agreeing signals | Standard recommendation |
| **Medium** | 55-69 | Acceptable data, mixed signals or small sample | Small stake or track only |
| **Low** | 40-54 | Significant gaps, conflicting signals | Track only, no recommendation |
| **Very Low** | 0-39 | Major issues, insufficient data | Do not use |

---

## 🔬 Special Situations {#special-situations}

### Handling ML System Confidence

ML systems calculate confidence differently but map to same scale:

```python
def calculate_ml_confidence(ml_prediction_inputs):
    """
    Calculate confidence for ML predictions
    Different factors but same 0-100 scale
    """
    score = 50  # Baseline

    # Factor 1: Model training performance
    if ml_prediction_inputs.model_validation_mae <= 3.5:
        score += 15
    elif ml_prediction_inputs.model_validation_mae <= 4.5:
        score += 10
    else:
        score += 5

    # Factor 2: Feature availability
    feature_completeness = ml_prediction_inputs.features_populated_pct
    if feature_completeness >= 95:
        score += 12
    elif feature_completeness >= 85:
        score += 8
    else:
        score += 3

    # Factor 3: Prediction uncertainty
    if ml_prediction_inputs.prediction_std_dev:
        if ml_prediction_inputs.prediction_std_dev <= 2.5:
            score += 10
        elif ml_prediction_inputs.prediction_std_dev <= 4.0:
            score += 5
        else:
            score -= 5

    # Factor 4: Out of distribution check
    if ml_prediction_inputs.out_of_distribution_flag:
        score -= 15  # Inputs very different from training data

    # Factor 5: Feature agreement
    if ml_prediction_inputs.feature_agreement_score > 0.7:
        score += 8

    # Factor 6: Recent model performance
    if ml_prediction_inputs.model_recent_accuracy >= 0.65:
        score += 10
    elif ml_prediction_inputs.model_recent_accuracy >= 0.55:
        score += 5
    else:
        score -= 5

    # Red flags (same as rule-based)
    score += calculate_red_flags_penalty(ml_prediction_inputs)

    return max(0, min(100, int(score)))
```

### Ensemble System Confidence

When combining multiple systems:

```python
def calculate_ensemble_confidence(system_predictions):
    """
    Confidence for ensemble that combines multiple systems
    """
    # Start with average of component confidences
    avg_confidence = np.mean([p.confidence_score for p in system_predictions])

    # Boost for agreement
    std_dev = np.std([p.predicted_points for p in system_predictions])
    if std_dev < 1.0:
        agreement_bonus = 15  # Strong agreement
    elif std_dev < 2.0:
        agreement_bonus = 8
    elif std_dev < 3.0:
        agreement_bonus = 3
    else:
        agreement_bonus = -5  # Disagreement penalty

    # Boost if champion system has high confidence
    champion_pred = [p for p in system_predictions if p.is_champion][0]
    if champion_pred.confidence_score >= 80:
        champion_bonus = 5
    else:
        champion_bonus = 0

    ensemble_confidence = avg_confidence + agreement_bonus + champion_bonus

    return max(0, min(100, int(ensemble_confidence)))
```

---

## 🛠️ Implementation {#implementation}

### Database Storage

```sql
-- Add confidence details to predictions table
ALTER TABLE player_prop_predictions ADD COLUMN IF NOT EXISTS
  confidence_breakdown JSON;  -- Store factor-by-factor scores for analysis

-- Example JSON structure:
{
  "similarity_quality": 20,
  "data_completeness": 15,
  "signal_consistency": 5,
  "variance": 4,
  "margin": 2,
  "red_flags": -8,
  "final_score": 88,
  "tier": "VERY_HIGH"
}
```

### Configuration

**File:** `config/confidence_scoring.yaml`

```yaml
similarity_quality:
  max_points: 25
  excellent_sample_size: 25
  minimum_sample_size: 10
  excellent_avg_score: 70

data_completeness:
  max_points: 15
  required_fields:
    - fatigue_score
    - shot_zone_mismatch_score
    - referee_favorability_score
    - opponent_def_rating_last_10

signal_consistency:
  max_points: 15
  strong_agreement_threshold: 5

variance:
  max_points: 10
  excellent_std_dev: 3.5
  acceptable_std_dev: 6.5

margin:
  max_points: 10
  strong_edge: 4.0
  moderate_edge: 2.0

red_flags:
  player_questionable: -10
  extreme_fatigue: -8
  major_line_movement: -10

tiers:
  very_high: 85
  high: 70
  medium: 55
  low: 40
```

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 Algorithm Documentation:**

- **Composite Factors:** `01-composite-factor-calculations.md` - How prediction adjustments are calculated
- **Architectural Decisions:** `../design/01-architectural-decisions.md` - Why we use confidence scoring

**Phase 5 Operations:**

- **Worker Deep-Dive:** `../operations/04-worker-deepdive.md` - How confidence affects predictions in production
- **Troubleshooting:** `../operations/03-troubleshooting.md` - When confidence scores are off

**Implementation:**

- **Source Code:** `predictions/shared/confidence/` - Confidence scoring implementation
- **Prediction Systems:** `predictions/worker/prediction_systems/` - System-specific confidence calculations

---

**Last Updated:** 2025-11-16
**Next Steps:** Review composite factor calculations to understand prediction adjustments
**Status:** ✅ Current

---

## Quick Reference

**6 Factors Summary:**

| Factor | Max Points | Purpose |
|--------|------------|---------|
| Similarity Quality | +25 | Sample size and match quality |
| Data Completeness | +15 | Feature availability and quality |
| Signal Consistency | +15 | Factor agreement (bullish/bearish) |
| Historical Variance | +10 | Performance consistency |
| Prediction Margin | +10 | Edge size vs betting line |
| Red Flags | -30 | Warning signs and uncertainties |

**Total Range:** 0-100 points (starting from 50 baseline)
