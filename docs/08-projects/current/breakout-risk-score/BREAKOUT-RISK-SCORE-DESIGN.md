# Breakout Risk Score Feature Design

**Created:** Session 125 (2026-02-04)
**Status:** Design Complete, Ready for Implementation
**Location:** Feature 37 in `ml_feature_store_v2`

---

## Executive Summary

The `breakout_risk_score` is a composite 0-100 feature that predicts the probability of a role player (8-16 PPG) scoring >= 1.5x their season average in a single game. This score will be used to filter UNDER bets and eventually train a dedicated breakout classifier.

**Problem:** Role player UNDER bets have 42-45% hit rate, losing money due to unexpected breakout games.

**Solution:** A multi-signal composite score combining hot streak, volatility, opponent defense leakiness, teammate injury opportunity, and historical breakout rate.

---

## 1. Feature Specification

### 1.1 Core Definition

```python
Feature Index: 37 (appended after breakout_flag at index 36)
Feature Name: breakout_risk_score
Data Type: FLOAT64
Range: 0.0 - 100.0
Default: 35.0 (neutral - league baseline breakout rate ~17%)
```

### 1.2 Score Interpretation

| Score Range | Risk Level | Recommendation |
|-------------|------------|----------------|
| 0-25 | Low | Safe for UNDER bet |
| 26-50 | Moderate | Proceed with caution |
| 51-75 | High | Consider skipping UNDER |
| 76-100 | Very High | Skip UNDER bet |

### 1.3 Component Weights

| Component | Weight | Source |
|-----------|--------|--------|
| Hot Streak | 30% | pts_vs_season_zscore (existing feature 35) |
| Volatility | 20% | points_std_last_10 + explosion_ratio (calculated) |
| Opponent Defense | 20% | opponent_def_rating (existing feature 13) |
| Opportunity | 15% | injured_teammates_ppg (new extraction needed) |
| Historical Rate | 15% | Calculated from last_10_games |

---

## 2. Component Calculation Details

### 2.1 Hot Streak Component (30%)

Uses existing `pts_vs_season_zscore` feature (index 35).

```python
def _calculate_hot_streak_component(z_score: float) -> float:
    """
    z-score -> 0-100 scale
    z = -1.5 -> 0 (very cold)
    z = 0 -> 50 (neutral)
    z = 1.5 -> 100 (very hot)
    """
    if z_score >= 1.5:
        return 100.0
    elif z_score <= -1.5:
        return 0.0
    else:
        # Linear: map [-1.5, 1.5] -> [0, 100]
        return ((z_score + 1.5) / 3.0) * 100.0
```

**Validation:** Players with z-score > 1.5 have ~24% breakout rate vs 17% baseline.

### 2.2 Volatility Component (20%)

Combines standard deviation and explosion ratio.

```python
def _calculate_volatility_component(std: float, last_10_games: list, season_avg: float) -> float:
    """
    Combines:
    - Standard deviation (60% weight): Higher std = more volatile
    - Explosion ratio (40% weight): max(L5)/season_avg
    """
    # Std score (0-50)
    if std >= 8.0:
        std_score = 50.0
    elif std >= 5.0:
        std_score = 35.0
    elif std >= 3.0:
        std_score = 20.0
    else:
        std_score = 10.0

    # Explosion ratio score (0-50)
    last_5_points = [g['points'] for g in last_10_games[:5]]
    explosion_ratio = max(last_5_points) / season_avg

    if explosion_ratio >= 1.8:
        explosion_score = 50.0
    elif explosion_ratio >= 1.5:
        explosion_score = 30.0
    else:
        explosion_score = 10.0

    return std_score * 0.6 + explosion_score * 0.4
```

**Rationale:** Players with high max games relative to their average are more likely to repeat those performances.

### 2.3 Opponent Defense Component (20%)

Uses existing `opponent_def_rating` feature (index 13).

```python
def _calculate_opponent_defense_component(def_rating: float) -> float:
    """
    Weaker defenses (higher rating) = higher breakout risk

    Thresholds calibrated from analysis:
    - def_rating < 110: Strong defense -> low risk
    - def_rating 110-113: Average -> moderate risk
    - def_rating 113-116: Weak -> elevated risk
    - def_rating > 116: Very weak -> high risk
    """
    if def_rating >= 116.0:
        return 90.0
    elif def_rating >= 113.0:
        return 70.0
    elif def_rating >= 110.0:
        return 50.0
    else:
        # Strong defense: linear from 10 to 50
        return max(10.0, 50.0 - (110.0 - def_rating) * 4.0)
```

**Data Source:** `nba_precompute.team_defense_zone_analysis.defensive_rating_last_15`

### 2.4 Opportunity Component (15%)

**NEW DATA EXTRACTION REQUIRED**

This component requires querying injured teammates' PPG, which is not currently available in the feature extractor.

```python
def _calculate_opportunity_component(injured_teammates_ppg: float) -> float:
    """
    More injured PPG = more opportunity = higher breakout risk

    Thresholds:
    - 30+ PPG injured: Multiple starters out (100 score)
    - 20+ PPG: Star player out (80 score)
    - 12+ PPG: Starter out (50 score)
    - 5+ PPG: Role player out (30 score)
    - <5 PPG: Team healthy (10 score)
    """
    if injured_teammates_ppg >= 30.0:
        return 100.0
    elif injured_teammates_ppg >= 20.0:
        return 80.0
    elif injured_teammates_ppg >= 12.0:
        return 50.0
    elif injured_teammates_ppg >= 5.0:
        return 30.0
    else:
        return 10.0
```

**Data Source (to be added):**
```sql
-- Query for injured_teammates_ppg
SELECT
    ir.game_date,
    ir.team_abbr,
    SUM(COALESCE(ps.season_avg_points, 10.0)) as injured_teammates_ppg
FROM nba_raw.nbac_injury_report ir
JOIN player_season_stats ps ON ir.player_lookup = ps.player_lookup
WHERE ir.status IN ('Out', 'Doubtful')
  AND ir.game_date = '{game_date}'
GROUP BY ir.game_date, ir.team_abbr
```

**Workaround (Phase 1):** Until this data is extracted, default to 20.0 (moderate opportunity).

### 2.5 Historical Breakout Rate Component (15%)

Calculated from `last_10_games` in phase3_data.

```python
def _calculate_historical_breakout_component(last_10_games: list, season_avg: float) -> float:
    """
    What % of recent games did player score >= 1.5x season avg?

    Scale: 0% -> 10, 17% (baseline) -> 50, 35%+ -> 100
    """
    breakout_threshold = season_avg * 1.5
    breakout_count = sum(1 for g in last_10_games if g['points'] >= breakout_threshold)
    breakout_rate = breakout_count / len(last_10_games)

    if breakout_rate >= 0.35:
        return 100.0
    elif breakout_rate <= 0.0:
        return 10.0
    else:
        # Linear: map [0, 0.35] -> [10, 100]
        return 10.0 + (breakout_rate / 0.35) * 90.0
```

---

## 3. Integration Points

### 3.1 Feature Store Pipeline

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
# Line ~50 - Add import
from .breakout_risk_calculator import BreakoutRiskCalculator

# Line ~411 - Initialize in __init__
self.breakout_risk_calculator = BreakoutRiskCalculator()

# Line ~1680 - After breakout_flag calculation
# Feature 37: Breakout Risk Score (composite prediction feature)
breakout_risk_score, _ = self.breakout_risk_calculator.calculate_breakout_risk_score(
    phase4_data, phase3_data, team_context=None  # TODO: Add team_context when available
)
features.append(breakout_risk_score)
feature_sources[37] = 'calculated'
```

### 3.2 Feature Contract Update

**File:** `shared/ml/feature_contract.py`

```python
# Update version
CURRENT_FEATURE_STORE_VERSION = "v2_38features"
FEATURE_STORE_FEATURE_COUNT = 38

# Add to FEATURE_STORE_NAMES list (line ~88)
    # 37: Breakout Risk (added Session 125)
    "breakout_risk_score",

# Update V10_FEATURE_NAMES
V10_FEATURE_NAMES: List[str] = V9_FEATURE_NAMES + [
    "dnp_rate",
    "pts_slope_10g",
    "pts_vs_season_zscore",
    "breakout_flag",
    "breakout_risk_score",  # NEW
]

# Add to FEATURE_DEFAULTS
    "breakout_risk_score": 35.0,  # League baseline
```

### 3.3 Processor Updates

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
# Update constants (line ~85)
FEATURE_VERSION = 'v2_38features'
FEATURE_COUNT = 38

# Update FEATURE_NAMES list (line ~124)
    # Breakout Risk Score (37) - Session 125 composite breakout prediction
    'breakout_risk_score',

# Add validation range (line ~192)
    37: (0, 100, False, 'breakout_risk_score'),
```

### 3.4 Prediction Worker Integration

**File:** `predictions/worker/worker.py`

For immediate use without model retraining, add rule-based filtering:

```python
def should_skip_role_player_under(features: Dict, edge: float) -> Tuple[bool, str]:
    """
    Use breakout_risk_score to filter role player UNDER bets.

    Args:
        features: Dict with season_avg, breakout_risk_score
        edge: Predicted edge (negative for UNDER)

    Returns:
        (should_skip, reason)
    """
    season_avg = features.get('points_avg_season', 0)

    # Only applies to role players (8-16 PPG)
    if not (8 <= season_avg <= 16):
        return False, None

    breakout_risk = features.get('breakout_risk_score', 35.0)
    abs_edge = abs(edge)

    # Sliding threshold based on edge
    if abs_edge >= 5.0:
        threshold = 70  # High edge allows more risk
    elif abs_edge >= 3.0:
        threshold = 55
    else:
        threshold = 40  # Low edge = be conservative

    if breakout_risk >= threshold:
        return True, f"breakout_risk_{breakout_risk:.0f}"

    return False, None
```

---

## 4. Implementation Plan

### Phase 1: Core Feature (Week 1)

1. **Add breakout_risk_calculator.py** (DONE - created)
2. Update feature_contract.py with new feature
3. Update ml_feature_store_processor.py:
   - Import calculator
   - Add to __init__
   - Add feature calculation after breakout_flag
   - Update FEATURE_VERSION, FEATURE_COUNT, FEATURE_NAMES
   - Add validation range
4. Deploy and validate feature generation

### Phase 2: Opportunity Component (Week 2)

1. Add `_batch_extract_team_injuries` to feature_extractor.py
2. Pass team_context to breakout_risk_calculator
3. Backfill with corrected opportunity scores

### Phase 3: Prediction Integration (Week 2-3)

1. Add `should_skip_role_player_under` to prediction worker
2. Store skip reasons for monitoring
3. Track shadow performance (would skipped bets have won?)

### Phase 4: Classifier Training (Week 3-4)

1. Generate training data with breakout_risk_score
2. Train dedicated CatBoost breakout classifier
3. A/B test classifier vs rule-based filter

---

## 5. Expected Impact

### Current State (Session 125 simple filter)
- Role player UNDER hit rate: 35% -> 55% with filter
- Bets skipped: ~30%
- Filter is binary (skip all role players with low edge)

### With breakout_risk_score
- Role player UNDER hit rate: **58-62%** (targeted filtering)
- Bets skipped: **~20%** (more targeted)
- Precision: **~75%** (skip the right bets)

### ROI Impact Estimate

| Scenario | Hit Rate | ROI |
|----------|----------|-----|
| No filter | 42% | -15% |
| Simple filter (current) | 55% | +5% |
| breakout_risk_score filter | 60% | +12% |
| With trained classifier | 65% | +18% |

---

## 6. Monitoring Queries

### Feature Distribution Check

```sql
-- Check breakout_risk_score distribution
SELECT
  CASE
    WHEN features[OFFSET(37)] < 25 THEN 'Low (0-25)'
    WHEN features[OFFSET(37)] < 50 THEN 'Moderate (25-50)'
    WHEN features[OFFSET(37)] < 75 THEN 'High (50-75)'
    ELSE 'Very High (75-100)'
  END as risk_category,
  COUNT(*) as records,
  ROUND(AVG(features[OFFSET(2)]), 1) as avg_season_ppg
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND features[OFFSET(2)] BETWEEN 8 AND 16  -- Role players
GROUP BY 1
ORDER BY 1
```

### Filter Performance Tracking

```sql
-- Track breakout_risk filter effectiveness
SELECT
  game_date,
  COUNT(*) as role_player_unders,
  COUNTIF(filter_reason LIKE 'breakout_risk%') as skipped,
  -- For non-skipped bets
  COUNTIF(filter_reason IS NULL AND prediction_correct) as wins,
  COUNTIF(filter_reason IS NULL AND NOT prediction_correct) as losses,
  -- Shadow: would skipped bets have won?
  COUNTIF(filter_reason LIKE 'breakout_risk%' AND actual_points >= line_value) as correct_skips,
  COUNTIF(filter_reason LIKE 'breakout_risk%' AND actual_points < line_value) as incorrect_skips
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND season_avg_points BETWEEN 8 AND 16
  AND bet_type = 'UNDER'
GROUP BY 1
ORDER BY 1 DESC
```

---

## 7. Files Created/Modified

### Created
- `/data_processors/precompute/ml_feature_store/breakout_risk_calculator.py`
- `/docs/08-projects/current/breakout-risk-score/BREAKOUT-RISK-SCORE-DESIGN.md`

### To Be Modified
- `/shared/ml/feature_contract.py` - Add feature 37
- `/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` - Integration
- `/predictions/worker/worker.py` - Filtering logic

---

## 8. Testing Checklist

- [ ] Unit tests for BreakoutRiskCalculator
- [ ] Integration test: feature generates for all players
- [ ] Validation: score distribution matches expected (mean ~35-40)
- [ ] Backfill test: regenerate features for 7 days
- [ ] Shadow tracking: compare filter decisions to actual outcomes

---

*Document created by Claude, Session 125*
