# Phase 5: Prediction Systems Tutorial - Worked Examples

**File:** `docs/predictions/tutorials/03-worked-prediction-examples.md`
**Created:** 2025-11-16
**Purpose:** Practical guide with worked examples and scenarios showing how each prediction system operates
**Audience:** Developers implementing or testing prediction systems
**Level:** Hands-on with step-by-step examples

---

## 📋 Table of Contents

1. [Document Purpose](#purpose)
2. [Example Scenario: All 5 Systems Compared](#all-systems-compared)
3. [System-Specific Walkthroughs](#system-walkthroughs)
4. [Edge Cases & Special Situations](#edge-cases)
5. [Testing Your Implementation](#testing)
6. [Debugging Guide](#debugging)
7. [Decision Framework](#decision-framework)
8. [Related Documentation](#related-docs)

---

## 🎯 Document Purpose {#purpose}

This tutorial complements the technical specifications with real-world examples and practical guidance. You'll learn:

✅ How each system makes predictions (with step-by-step examples)
✅ Why systems give different predictions for the same player
✅ How to test your implementation
✅ Common edge cases and how to handle them
✅ Debugging strategies when predictions seem wrong

**Use this when:** Building, testing, or debugging your prediction systems.

---

## 🏀 Example Scenario: All 5 Systems Compared {#all-systems-compared}

Let's predict the same game using all 5 systems and see how they differ.

### The Setup

**Player:** LeBron James (lebron-james)
**Game Date:** January 15, 2025
**Opponent:** Phoenix Suns (away game for LeBron)
**Betting Line:** 24.5 points (over/under)

**Context:**
- LeBron's last 10 games: 26.2 PPG average
- Season average: 25.0 PPG
- Days rest: 1 day (not back-to-back)
- Minutes per game: 35.2
- Primary scoring zone: Paint (42% of shots)
- Suns' paint defense: +3.8% worse than league average (WEAK)
- Expected game pace: 102.5 (fast)
- Home/away: Away

---

### System 1: Moving Average Baseline

**What it does:** Weighted average of recent performance + standard adjustments

**Step-by-step calculation:**

```python
# Step 1: Calculate baseline (weighted recent averages)
baseline = (
    26.5 * 0.40 +  # Last 5 games: 26.5 PPG
    26.2 * 0.35 +  # Last 10 games: 26.2 PPG
    25.0 * 0.25    # Season: 25.0 PPG
) = 26.05

# Step 2: Fatigue adjustment
fatigue_score = 78  # Good rest
fatigue_adjustment = (78 - 70) * 0.02 = +0.16

# Step 3: Shot zone mismatch adjustment
zone_mismatch_score = 5.5  # Favorable (paint vs weak paint defense)
zone_adjustment = 5.5 * 0.5 = +2.75

# Step 4: Pace adjustment
pace_score = 0.8  # Slightly faster than average
pace_adjustment = +0.8

# Step 5: Usage spike
usage_spike_score = 0.0  # No significant change
usage_adjustment = 0.0

# Step 6: Venue adjustment
venue_adjustment = -0.8  # Away game penalty

# Step 7: Back-to-back penalty
b2b_penalty = 0.0  # Not back-to-back

# Final prediction
predicted = 26.05 + 0.16 + 2.75 + 0.8 + 0.0 - 0.8 + 0.0
          = 28.96 points
```

**Result:**
- **Predicted Points:** 29.0
- **vs Line:** +4.5 (29.0 - 24.5)
- **Confidence:** 82% (high consistency, good data quality)
- **Recommendation:** OVER
- **Logic:** Strong recent performance + favorable matchup + fast pace

---

### System 2: Zone Matchup V1

**What it does:** Focuses heavily on shot zone matchup advantage

**Step-by-step calculation:**

```python
# Step 1: Identify primary zone
primary_zone = 'paint'  # 42% of shots in paint

# Step 2: Check opponent's paint defense
opponent_paint_defense = +3.8  # 3.8% worse than league (WEAK)

# Step 3: Calculate matchup factor
matchup_factor = 1.00 + (3.8 / 100) = 1.038  # 3.8% boost

# Step 4: Apply to recent average
base = 26.2  # Last 10 games
with_matchup = 26.2 * 1.038 = 27.2

# Step 5: Additional adjustments
pace_boost = 27.2 * 1.025 = 27.88  # Fast game (+2.5%)
away_penalty = 27.88 * 0.98 = 27.32  # Away game (-2%)

# Final prediction
predicted = 27.3
```

**Result:**
- **Predicted Points:** 27.3
- **vs Line:** +2.8
- **Confidence:** 88% (clear zone advantage, high sample quality)
- **Recommendation:** OVER
- **Logic:** Paint player vs weak paint defense = strong matchup

**Why different from Moving Average?**
- Zone Matchup is MORE confident because matchup is extremely favorable
- Applies matchup boost more aggressively (3.8% multiplier)
- Less influenced by fatigue/usage factors

---

### System 3: Similarity Balanced V1

**What it does:** Finds similar historical games and averages their outcomes

**Step-by-step calculation:**

```python
# Step 1: Find similar games
# Criteria: Away games, 1-day rest, vs elite/good defense, normal form
similar_games = [
    {'date': '2024-12-18', 'opponent': 'BOS', 'points': 28.0, 'similarity': 92},
    {'date': '2024-12-05', 'opponent': 'DEN', 'points': 26.0, 'similarity': 88},
    {'date': '2024-11-22', 'opponent': 'PHX', 'points': 31.0, 'similarity': 95},  # Same opponent!
    {'date': '2024-11-10', 'opponent': 'LAL', 'points': 27.0, 'similarity': 85},
    {'date': '2024-10-28', 'opponent': 'GSW', 'points': 25.0, 'similarity': 83},
    # ... total 18 similar games found with similarity >= 70
]

# Step 2: Calculate weighted baseline
total_weight = 0
weighted_sum = 0
for game in similar_games:
    weight = game['similarity'] / 100
    weighted_sum += game['points'] * weight
    total_weight += weight

baseline = weighted_sum / total_weight = 27.4

# Step 3: Apply reduced adjustments (similarity already captures context)
fatigue_adj = (78 - 70) * 0.015 = +0.12  # Reduced weight
zone_adj = 5.5 * 0.4 = +2.2              # Reduced weight
pace_adj = 0.8 * 0.8 = +0.64             # Reduced weight
venue_adj = -0.5                          # Away penalty

predicted = 27.4 + 0.12 + 2.2 + 0.64 - 0.5 = 29.86
```

**Result:**
- **Predicted Points:** 29.9
- **vs Line:** +5.4
- **Confidence:** 85% (18 similar games, avg similarity 87%)
- **Recommendation:** OVER
- **Logic:** Historical similar games averaged ~29 points

**Why different from others?**
- Found game vs Phoenix earlier this season (31 points, 95% similarity)
- Similar away games vs good teams averaged higher
- Less reliant on formulas, more on actual outcomes

---

### System 4: XGBoost V1

**What it does:** Machine learning model predicts based on learned patterns

**Step-by-step calculation:**

```python
# Step 1: Prepare feature vector (25 features)
features = [
    26.5,   # points_avg_last_5
    26.2,   # points_avg_last_10
    25.0,   # points_avg_season
    4.8,    # points_std_last_10
    35.2,   # minutes_avg_last_10
    78.0,   # fatigue_score
    5.5,    # shot_zone_mismatch_score
    0.8,    # pace_score
    0.0,    # usage_spike_score
    0.0,    # referee_favorability_score (deferred)
    0.0,    # look_ahead_pressure_score (deferred)
    0.0,    # matchup_history_score (deferred)
    0.0,    # momentum_score (deferred)
    112.5,  # opponent_def_rating_last_15
    102.5,  # opponent_pace_last_15
    0.0,    # is_home (0 = away)
    1.0,    # days_rest
    0.0,    # back_to_back
    0.42,   # paint_rate_last_10
    0.18,   # mid_range_rate_last_10
    0.28,   # three_pt_rate_last_10
    0.68,   # assisted_rate_last_10
    100.8,  # team_pace_last_10
    117.2,  # team_off_rating_last_10
    27.5    # usage_rate_last_10
]

# Step 2: Load model and predict
model = load_xgboost_model('v1')
predicted = model.predict(features)[0]
# Model output: 28.3
```

**Result:**
- **Predicted Points:** 28.3
- **vs Line:** +3.8
- **Confidence:** 75% (base ML confidence)
- **Recommendation:** OVER
- **Logic:** ML learned optimal feature weights from thousands of games

**Why different from others?**
- Learned from 36,000+ historical games
- Found non-linear patterns (e.g., paint rate + weak paint defense = bonus)
- More conservative than similarity (doesn't weight one 31-point game heavily)
- Feature importance: recent performance (14%), matchup (11%), pace (6%)

---

### System 5: Meta Ensemble V1

**What it does:** Intelligently combines predictions from Systems 1-4

**Step-by-step calculation:**

```python
# Step 1: Collect predictions from other systems
predictions = [
    {'system': 'moving_average_baseline', 'points': 29.0, 'confidence': 82},
    {'system': 'zone_matchup_v1', 'points': 27.3, 'confidence': 88},
    {'system': 'similarity_balanced_v1', 'points': 29.9, 'confidence': 85},
    {'system': 'xgboost_v1', 'points': 28.3, 'confidence': 75}
]

# Step 2: Get system weights (based on 30-day accuracy)
system_weights = {
    'moving_average_baseline': 0.22,  # 54% accuracy last 30 days
    'zone_matchup_v1': 0.26,          # 56% accuracy (best performer)
    'similarity_balanced_v1': 0.28,   # 57% accuracy (best on high conf)
    'xgboost_v1': 0.24                # 55% accuracy
}

# Step 3: Calculate weighted average (adjusted by confidence)
total_weight = 0
weighted_sum = 0

for pred in predictions:
    base_weight = system_weights[pred['system']]
    confidence_factor = pred['confidence'] / 100
    adjusted_weight = base_weight * confidence_factor

    weighted_sum += pred['points'] * adjusted_weight
    total_weight += adjusted_weight

predicted = weighted_sum / total_weight = 28.6

# Step 4: Calculate system agreement
variance = std_dev([29.0, 27.3, 29.9, 28.3]) = 1.1
agreement_score = 100 * (1 - 1.1/28.6) = 96.2%  # High agreement!
```

**Result:**
- **Predicted Points:** 28.6
- **vs Line:** +4.1
- **Confidence:** 87% (high agreement + high avg confidence)
- **Recommendation:** OVER
- **System Agreement:** 96% (all systems agree)
- **Logic:** All 4 systems predict OVER, ensemble weights them intelligently

**Why this is powerful:**
- All systems agree (range only 27.3 to 29.9)
- High confidence across the board
- Zone Matchup and Similarity are weighted highest (recent best performers)
- Reduces individual system biases

---

### Summary Table: All Systems Compared

| System | Predicted | vs Line | Confidence | Recommendation | Key Strength |
|--------|-----------|---------|------------|----------------|--------------|
| Moving Average | 29.0 | +4.5 | 82% | OVER | Captures recent hot streak |
| Zone Matchup | 27.3 | +2.8 | 88% | OVER | Identifies paint advantage |
| Similarity | 29.9 | +5.4 | 85% | OVER | Found high-scoring similar games |
| XGBoost | 28.3 | +3.8 | 75% | OVER | Learned optimal weights |
| **Ensemble** | **28.6** | **+4.1** | **87%** | **OVER** | **Combines all intelligently** |

**Champion Selection:** In production, you'd select ONE system as the "champion." Based on:
- Recent 30-day accuracy
- Confidence on this specific prediction
- System agreement

For this game: **Zone Matchup V1** would likely be champion (highest confidence, proven track record on matchup plays)

---

## 🔧 System-Specific Walkthroughs {#system-walkthroughs}

### Walkthrough A: Moving Average - When It Shines

**Scenario:** Consistent scorer, normal matchup, standard context

**Player:** Kevin Durant
**Context:**
- Home game, 2 days rest, balanced scoring (no zone preference)
- Recent: 28.5 PPG last 5, 27.8 PPG last 10, 27.2 season avg
- Opponent: Denver (average defense, all zones)
- Line: 28.5

**Why Moving Average is ideal:**
- No extreme matchup advantage → zone system neutral
- Consistent scorer (std dev: 3.8) → recent averages are reliable
- Normal context → no special adjustments needed

**Prediction:**
```python
baseline = 28.5*0.40 + 27.8*0.35 + 27.2*0.25 = 28.03
fatigue_adj = (85 - 70) * 0.02 = +0.30
zone_adj = 0.0  # Neutral matchup
pace_adj = 0.0  # Average pace
usage_adj = 0.0
venue_adj = +1.2  # Home
b2b = 0.0

predicted = 28.03 + 0.30 + 1.2 = 29.53 points
```

**Result:** 29.5 vs 28.5 line = +1.0 edge
**Confidence:** 84% (high consistency)
**Recommendation:** Borderline (edge too small for high confidence)

**Key Lesson:** Moving Average works best for consistent players in normal situations.

---

### Walkthrough B: Zone Matchup - Extreme Favorable

**Scenario:** Paint-dominant big man vs weak interior defense

**Player:** Joel Embiid
**Context:**
- Home game, fresh (3 days rest)
- **Shot Profile:**
  - Paint: 58% of shots, 64% FG% in paint
  - Primary zone: Paint (extreme)
  - Volume: 8.2 paint attempts per game

**Opponent:** Washington Wizards
**Defense:**
- Paint defense: +5.2% worse than league (WEAK)
- Weakest zone: Paint
- Paint FG% allowed: 68.3% (terrible)
- Defensive rating: 118.5 (bottom 5 in NBA)
- Line: 30.5

**Why Zone Matchup crushes this:**
- Clear zone dominance (58% paint) vs clear weakness (+5.2%)
- Multiplier effect: More shots + better efficiency

**Prediction:**
```python
base = 31.2  # Last 10 games
matchup_factor = 1.00 + (5.2 / 100) = 1.052  # 5.2% boost
with_matchup = 31.2 * 1.052 = 32.82

# Additional boosts
pace = 32.82 * 1.02 = 33.48  # Slightly fast
home = 33.48 * 1.02 = 34.15  # Home game

predicted = 34.2 points
```

**Result:** 34.2 vs 30.5 line = +3.7 edge
**Confidence:** 93% (extreme zone advantage)
**Recommendation:** STRONG OVER

**Key Lesson:** Zone Matchup excels when there's a clear mismatch (>5 percentage points).

---

## 🎪 Edge Cases & Special Situations {#edge-cases}

### Edge Case 1: Insufficient Data

**Problem:** Player has only 3 games this season (rookie or injury return)

**What happens:**
```python
# Moving Average
baseline = 3 games only (unreliable)
confidence = 30% (low sample size)
→ Likely PASS

# Zone Matchup
# Can still work if shot data available from college/previous games
confidence = 55% (moderate, if zone clear)

# Similarity
# Struggles to find similar games
min_threshold = 5 games → FAIL
→ Returns None

# XGBoost
# Can predict, but confidence is low
# Uses season features sparingly

# Ensemble
# Only 1-2 systems produce predictions
confidence = 40% (insufficient)
→ PASS
```

**Best strategy:** Use Zone Matchup if shot data exists, otherwise pass.

---

### Edge Case 2: Back-to-Back Games (2nd Night)

**Problem:** Player on 2nd night of back-to-back

**Detection:**
```python
back_to_back = True
days_rest = 0
```

**What systems do:**
```python
# Moving Average
# Applies B2B penalty: -1.5 points
# fatigue_score = low (45-55 range)
# fatigue_adjustment = -0.4 to -0.5
# Total penalty: ~2.0 points

# Zone Matchup
# B2B penalty: × 0.92 (8% reduction)
# If already fatigued: × 0.88 (12% reduction)

# Similarity
# Finds historical B2B games specifically
# B2B games typically score 1.8 less
# Baseline naturally lower

# XGBoost
# Has learned B2B patterns
# Typically predicts 2.5 points lower
# Also considers: minutes, opponent, position

# Ensemble
# All systems agree on penalty
# High confidence in the reduction
```

**Key insight:** Systems agree more on B2B games (fatigue is universal)

---

## 🧪 Testing Your Implementation {#testing}

### Test Suite 1: Unit Tests (Individual Systems)

Test each system with known inputs/outputs:

```python
def test_moving_average_baseline():
    """Test moving average calculation"""
    features = {
        'points_avg_last_5': 25.0,
        'points_avg_last_10': 24.0,
        'points_avg_season': 23.0,
        'fatigue_score': 70,
        'shot_zone_mismatch_score': 0,
        'pace_score': 0,
        'usage_spike_score': 0,
        'is_home': 1,
        'back_to_back': 0,
        'points_std_last_10': 5.0
    }

    result = moving_average_prediction(features)

    # Expected: (25*0.4 + 24*0.35 + 23*0.25) + 1.2 = 25.35
    assert abs(result['predicted_points'] - 25.35) < 0.1
    assert result['confidence_score'] > 60
    assert result['system_id'] == 'moving_average_baseline'

    print("✓ Moving Average test passed")


def test_zone_matchup():
    """Test zone matchup calculation"""
    features = {
        'points_avg_last_10': 26.0,
        'shot_zone_mismatch_score': 5.0,  # Strong favorable matchup
        'pace_score': 1.0,
        'is_home': 0,
        'back_to_back': 0
    }

    result = zone_matchup_prediction(features)

    # Expected: 26 * 1.05 (matchup) * 1.025 (pace) * 0.98 (away) ≈ 27.1
    assert result['predicted_points'] > 26.5
    assert result['confidence_score'] > 75  # High confidence on strong matchup

    print("✓ Zone Matchup test passed")
```

**Run tests:**
```bash
python -m pytest tests/test_prediction_systems.py -v
```

---

## 🐛 Debugging Guide {#debugging}

### Issue 1: System Returns None/Null

**Symptom:** Prediction is None or empty

**Possible causes:**
```python
# Check 1: Features missing?
if features is None or len(features) < 25:
    print("ERROR: Insufficient features")
    print(f"Expected 25, got {len(features) if features else 0}")
    # Solution: Check ml_feature_store_v2 population

# Check 2: Similar games not found?
if system == 'similarity_balanced_v1':
    similar_games = find_similar_games(...)
    if len(similar_games) < 5:
        print(f"WARNING: Only {len(similar_games)} similar games")
        # Solution: Lower similarity threshold

# Check 3: Model not loaded?
if system == 'xgboost_v1':
    if model is None:
        print("ERROR: XGBoost model not loaded")
        # Solution: Check GCS path, load_model()
```

---

### Issue 2: Predictions Way Off (>10 points)

**Symptom:** Predicted 35 points, actual was 18 points

**Debug steps:**
```python
# Step 1: Check recent averages
print(f"Last 5 avg: {features['points_avg_last_5']}")
print(f"Last 10 avg: {features['points_avg_last_10']}")
print(f"Season avg: {features['points_avg_season']}")
# If averages are correct, baseline should be close

# Step 2: Check adjustments
print(f"Fatigue adj: {fatigue_adjustment}")
print(f"Zone adj: {zone_adjustment}")
print(f"Pace adj: {pace_adjustment}")
# Are adjustments too large? (>±5 points is suspicious)

# Step 3: Check context
print(f"Minutes played: {actual_minutes}")
# Did player get DNP, injury, or garbage time?

# Step 4: Check outlier
if abs(predicted - actual) > 10:
    print("OUTLIER: Check game log")
    # Blowout? Early ejection? Injury mid-game?
```

---

## 🎯 Decision Framework: Which System to Trust {#decision-framework}

### Scenario-Based System Selection

When multiple systems give different recommendations, use this framework:

**Scenario 1: Clear Zone Advantage**
- Zone mismatch score > 6.0 (or < -6.0)
- **Trust:** Zone Matchup V1 (highest confidence on matchups)
- **Reasoning:** Specialized for this exact situation

**Scenario 2: Hot/Cold Streak**
- Recent form: "hot" or "cold" (>3 PPG diff from season)
- **Trust:** Similarity Balanced V1 (finds similar form games)
- **Reasoning:** Best at capturing momentum

**Scenario 3: Back-to-Back**
- days_rest = 0
- **Trust:** Moving Average (has explicit B2B penalty)
- **Reasoning:** Consistent fatigue modeling

**Scenario 4: Normal/Neutral Game**
- No extreme factors
- **Trust:** Meta Ensemble V1 (or highest confidence system)
- **Reasoning:** Ensemble reduces individual biases

**Scenario 5: High System Agreement**
- Agreement > 95%
- **Trust:** Meta Ensemble V1
- **Reasoning:** All systems agree, ensemble confidence highest

**Scenario 6: Low System Agreement**
- Agreement < 70%
- **Action:** PASS (regardless of edge)
- **Reasoning:** Uncertainty is high, avoid bet

---

## 🔗 Related Documentation {#related-docs}

### Tutorials
- **[Getting Started](./01-getting-started.md)** - Onboarding overview
- **[Understanding Prediction Systems](./02-understanding-prediction-systems.md)** - System concepts and types
- **[Operations Command Reference](./04-operations-command-reference.md)** - Quick commands

### Algorithms
- **[Composite Factor Calculations](../../algorithms/01-composite-factor-calculations.md)** - Mathematical specifications
- **[Confidence Scoring Framework](../../algorithms/02-confidence-scoring-framework.md)** - Confidence calculation details

### ML Training
- **[Initial Model Training](../../ml-training/01-initial-model-training.md)** - XGBoost training procedures
- **[Continuous Retraining](../../ml-training/02-continuous-retraining.md)** - Model improvement over time

### Operations
- **[Daily Operations](../../operations/05-daily-operations-checklist.md)** - Daily monitoring
- **[Performance Monitoring](../../operations/06-performance-monitoring.md)** - Tracking accuracy
- **[Emergency Procedures](../../operations/09-emergency-procedures.md)** - Troubleshooting

---

## 📝 Summary: Key Takeaways

### 1. Each System Has Strengths
- **Moving Average:** Reliable baseline for consistent players
- **Zone Matchup:** Best for clear zone advantages
- **Similarity:** Captures trends and recent form
- **XGBoost:** Learns complex patterns
- **Ensemble:** Combines intelligently, reduces risk

### 2. Disagreement is Information
- High agreement (>95%) = High confidence bet
- Low agreement (<70%) = Pass
- Medium agreement (70-95%) = Proceed with caution

### 3. Context Matters
- Back-to-back: Trust fatigue-aware systems
- Hot streaks: Trust similarity
- Role changes: Trust ML
- Normal games: Trust ensemble

### 4. Testing is Critical
- Unit tests catch bugs early
- Integration tests verify workflow
- Historical backtests validate accuracy
- Manual spot checks find edge cases

---

**Version:** 1.0
**Last Updated:** 2025-11-16
**Maintained By:** Documentation Team
