# NBA Player Breakout Detection - Design Document

**Created:** Session 125 (2026-02-05)
**Status:** Design Complete, Implementation Pending

## Executive Summary

This document proposes a comprehensive solution for detecting NBA player breakout games to improve UNDER bet performance. The current blunt filter (skip role player UNDER when edge is 2.5-4) improves hit rate from 35% to 55% but leaves value on the table. A probabilistic breakout model can achieve an estimated 60-65% hit rate by identifying which specific players in which specific situations are likely to break out.

---

## 1. Problem Analysis

### Current State

**The Breakout Problem:**
- Role players (8-16 PPG season average) have ~17% baseline breakout rate (scoring 1.5x+ their average)
- "Hot" players (L5 avg > season avg + 3 points) have ~24% breakout rate
- When UNDER misses on role players: model predicts 6.7, actual is 16.0 (typical miss magnitude)

**Current Mitigation (Session 125):**
```python
# Skip role player UNDER when:
#   - Season average: 8-16 PPG
#   - Edge: 2.5-4 points
#   - Result: Hit rate improves 35% -> 55%
```

**Why This Is Suboptimal:**
1. **Binary filter loses nuance** - A 14 PPG player with stable history is treated same as 10 PPG player on hot streak
2. **Edge threshold is arbitrary** - 2.4 edge vs 2.6 edge shouldn't flip recommendation
3. **No opponent context** - PHI and MIN allow more breakouts than BOS and CLE
4. **No recency weighting** - Yesterday's game matters more than 10 games ago

---

## 2. Recommended Approach: Breakout Probability Model

### Architecture: Two-Phase Implementation

#### Phase 1: Enhanced Feature Store (Immediate - 1 week)
Add breakout-predictive features to the existing feature store without requiring model retraining.

#### Phase 2: Dedicated Breakout Classifier (Medium-term - 2-4 weeks)
Train a binary classifier specifically for breakout detection.

---

## 3. Phase 1: Enhanced Features

### 3.1 New Features to Add to Feature Store

| Feature Name | Definition | Rationale |
|--------------|------------|-----------|
| `explosion_ratio` | max(L5_points) / season_avg | High ratio = volatile scorer |
| `days_since_breakout` | Days since last game >= 1.5x season avg | Recent breakout = higher probability of another |
| `hot_streak_intensity` | (L5_avg - season_avg) / season_std | Normalized hot streak measure |
| `opportunity_score` | Composite: teammate injuries + usage changes | More opportunity = higher breakout potential |
| `opponent_allows_breakouts` | Opponent's rate of allowing 1.5x games | Some defenses leak more |
| `matchup_favorability` | Player shot profile vs opponent defensive weaknesses | Exploitable matchup |
| `career_breakout_rate` | Historical % of games where player scored 1.5x avg | Some players have higher ceilings |

### 3.2 Feature Calculation Details

**explosion_ratio** (volatility indicator):
```python
def calculate_explosion_ratio(phase3_data: Dict) -> float:
    """
    Calculate explosion ratio: max(L5_points) / season_avg.

    Higher ratio = more volatile scorer = higher breakout risk.
    Typical values:
      - Steady scorers: 1.2-1.4
      - Volatile scorers: 1.6-2.0+
    """
    last_5_games = phase3_data.get('last_10_games', [])[:5]
    season_avg = phase3_data.get('points_avg_season', 0)

    if len(last_5_games) < 3 or season_avg <= 0:
        return 1.0  # Default: no elevated risk

    max_pts = max(g.get('points', 0) for g in last_5_games)
    return round(max_pts / season_avg, 3)
```

**days_since_breakout** (recency indicator):
```python
def calculate_days_since_breakout(phase3_data: Dict) -> int:
    """
    Days since player scored >= 1.5x their season average.

    Lower value = more recent breakout = higher probability of another.
    Returns 999 if no breakout in last 20 games.
    """
    last_20_games = phase3_data.get('last_20_games', [])
    season_avg = phase3_data.get('points_avg_season', 0)
    breakout_threshold = season_avg * 1.5

    for i, game in enumerate(last_20_games):
        if game.get('points', 0) >= breakout_threshold:
            return i  # Games ago (0 = most recent)

    return 999  # No recent breakout
```

**opportunity_score** (situation indicator):
```python
def calculate_opportunity_score(phase3_data: Dict, team_context: Dict) -> float:
    """
    Composite opportunity score based on:
    - Teammate injuries (star out = more shots)
    - Recent usage trend (getting more touches)
    - Starting lineup changes

    Scale: 0-10, higher = more opportunity
    """
    score = 0.0

    # Teammate injury impact
    injured_teammates_ppg = team_context.get('injured_teammates_ppg', 0)
    if injured_teammates_ppg >= 20:
        score += 4.0  # Star out
    elif injured_teammates_ppg >= 12:
        score += 2.0  # Starter out

    # Usage trend (are they getting more shots?)
    usage_l5 = phase3_data.get('usage_rate_l5', 0)
    usage_season = phase3_data.get('usage_rate_season', 0)
    if usage_l5 > usage_season * 1.15:
        score += 3.0  # Usage up 15%+

    # Starting lineup changes
    if phase3_data.get('started_recent_game') and not phase3_data.get('started_season'):
        score += 2.0  # New starter

    return min(10.0, score)
```

---

## 4. Phase 2: Dedicated Breakout Classifier

### 4.1 Model Architecture

**Type:** Binary classifier (CatBoost or XGBoost)

**Target Variable:**
```python
is_breakout = 1 if actual_points >= season_avg * 1.5 else 0
```

**Output:** `P(breakout | features)` - probability between 0 and 1

**Decision Rule:**
```python
if breakout_probability > 0.25:  # ~24% baseline for hot players
    skip_under_bet = True
```

### 4.2 Training Data Requirements

```sql
-- Generate training data
WITH player_games AS (
  SELECT
    pgs.player_lookup,
    pgs.game_date,
    pgs.points as actual_points,
    pgs.season_avg_points,
    -- Breakout label
    CASE WHEN pgs.points >= pgs.season_avg_points * 1.5 THEN 1 ELSE 0 END as is_breakout,
    -- Features
    f.explosion_ratio,
    f.days_since_breakout,
    f.opportunity_score,
    f.breakout_flag,
    f.pts_vs_season_zscore,
    f.pts_slope_10g,
    f.home_away,
    f.back_to_back,
    f.opponent_def_rating
  FROM nba_analytics.player_game_summary pgs
  JOIN nba_predictions.ml_feature_store_v2 f
    ON pgs.player_lookup = f.player_lookup
    AND pgs.game_date = f.game_date
  WHERE pgs.game_date >= '2025-11-01'
    AND pgs.season_avg_points BETWEEN 8 AND 16  -- Role players only
    AND pgs.minutes_played >= 15
)
SELECT * FROM player_games
```

**Expected training set:** ~5,000-8,000 role player games
**Class balance:** ~17% positive (breakouts), ~83% negative

### 4.3 Feature Importance (Expected)

| Feature | Expected Importance | Rationale |
|---------|---------------------|-----------|
| `pts_vs_season_zscore` | High | Hot players break out more |
| `explosion_ratio` | High | Volatile scorers have higher ceilings |
| `opportunity_score` | High | More opportunity = more breakouts |
| `days_since_breakout` | Medium | Recent breakout = pattern |
| `opponent_breakout_rate` | Medium | Some defenses leak |

---

## 5. Integration Options

### Option A: Pre-Filter (Recommended for Phase 1)

```python
def should_skip_under_bet(features: Dict, breakout_classifier) -> Tuple[bool, str]:
    """Skip UNDER bet if breakout probability is high."""
    season_avg = features.get('points_avg_season', 0)

    if not (8 <= season_avg <= 16):
        return False, None

    breakout_prob = breakout_classifier.predict_proba(features)[1]

    if breakout_prob > 0.25:
        return True, f"breakout_risk_{breakout_prob:.2f}"

    return False, None
```

### Option B: Store Probability for Analysis

```python
prediction_record = {
    'player_lookup': player_lookup,
    'predicted_points': predicted_points,
    'breakout_probability': breakout_prob,  # NEW
    'recommendation': recommendation,
}
```

### Option C: Adjust Prediction (Most Sophisticated)

```python
def adjust_prediction_for_breakout(base_prediction: float,
                                   breakout_prob: float,
                                   season_avg: float) -> float:
    """Adjust prediction upward when breakout is likely."""
    if breakout_prob < 0.15:
        return base_prediction

    expected_breakout_pts = season_avg * 1.6
    breakout_adjustment = (expected_breakout_pts - base_prediction) * breakout_prob

    return round(base_prediction + breakout_adjustment, 1)
```

---

## 6. Implementation Plan

### Week 1: Feature Store Enhancement
- Add `explosion_ratio` to feature_calculator.py
- Add `days_since_breakout` to feature_calculator.py
- Add `opportunity_score` calculation
- Create `opponent_breakout_rates` reference table
- Update feature_contract.py with V11 features

### Week 2: Rule-Based Filter (Interim)
```python
def should_skip_under_bet_heuristic(features: Dict) -> bool:
    """Rule-based breakout detection until ML model is trained."""

    if features.get('pts_vs_season_zscore', 0) > 1.5:
        return True  # Hot streak

    if features.get('days_since_breakout', 999) <= 3:
        return True  # Recent breakout

    if features.get('explosion_ratio', 1.0) > 1.8:
        return True  # High volatility

    if features.get('opportunity_score', 0) >= 5:
        return True  # Opportunity spike

    return False
```

### Weeks 3-4: ML Model Training
- Generate training dataset
- Train and validate breakout classifier
- Feature importance analysis
- A/B test against rule-based filter

---

## 7. Expected Impact

| Metric | Current (Session 125) | With Breakout Model |
|--------|----------------------|---------------------|
| Role UNDER Hit Rate | 55% | **60-65%** |
| Bets Skipped | ~30% | ~20% (more targeted) |
| Precision | ~65% | ~75% |

---

## 8. Alternative Approaches Considered

### 1. Train Model Only on Role Players
**Status:** Worth exploring
- Train separate CatBoost model on only role player data
- Would learn role-player-specific patterns
- Risk: smaller training set

### 2. Analyze Breakout Causes
**Status:** Worth exploring
- Query: When do breakouts happen? (teammate injuries, specific opponents)
- Could identify predictable situations vs random variance

### 3. Simple Blacklist
**Rejected:** Static, doesn't capture situation-specific risk

---

## 9. Success Criteria

### Phase 1 (Week 2)
- [ ] Role player UNDER hit rate >= 58%
- [ ] Breakout filter catches >= 60% of actual breakouts
- [ ] Filter skips <= 25% of bets

### Phase 2 (Week 4)
- [ ] Role player UNDER hit rate >= 62%
- [ ] Breakout probability AUC >= 0.70
- [ ] Calibrated probabilities

---

## 10. Monitoring Queries

```sql
-- Breakout filter performance
SELECT
  game_date,
  COUNT(*) as total_role_player_unders,
  COUNTIF(filter_reason LIKE 'breakout%') as skipped_for_breakout,
  COUNTIF(filter_reason IS NULL AND prediction_correct) as wins,
  COUNTIF(filter_reason IS NULL AND NOT prediction_correct) as losses,
  -- Shadow tracking: would skipped bets have won?
  COUNTIF(filter_reason LIKE 'breakout%' AND actual_points >= line_value) as correct_skips,
  COUNTIF(filter_reason LIKE 'breakout%' AND actual_points < line_value) as incorrect_skips
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC
```

---

*Document created by Opus agent, Session 125*
