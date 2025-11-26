# Understanding Rule-Based Prediction Systems

**File:** `docs/predictions/tutorials/02-understanding-prediction-systems.md`
**Created:** 2025-11-16
**Purpose:** Educational guide explaining different types of prediction systems and when to use each approach
**Audience:** Engineers learning prediction system concepts
**Level:** Conceptual explanation with examples

---

## 🎯 Quick Answer to a Common Question

**Question:** Are all rule-based systems based on similarity matching first?

**Answer:** No! Of your 5 systems:
- ❌ moving_average_baseline - **NO** similarity matching
- ❌ zone_matchup_v1 - **NO** similarity matching
- ✅ similarity_balanced_v1 - **YES**, uses similarity matching
- 🤖 xgboost_v1 - ML system (not rule-based)
- 🎯 meta_ensemble_v1 - Combines all the above

**Only 1 out of 3 rule-based systems uses similarity matching!**

---

## 📋 Table of Contents

1. [Types of Rule-Based Systems](#types)
2. [Statistical Aggregation (No Similarity)](#statistical-aggregation)
3. [Mathematical Models (No Similarity)](#mathematical-models)
4. [Case-Based Reasoning (Uses Similarity)](#case-based-reasoning)
5. [Understanding Adjustments](#adjustments)
6. [Real-World Example](#real-world-example)
7. [Key Takeaways](#takeaways)
8. [Related Documentation](#related-docs)

---

## 🔧 Types of Rule-Based Systems {#types}

### Type 1: Statistical Aggregation (No Similarity)

**Concept:** "Recent performance predicts future performance"

**How it works:**
1. Take player's last N games
2. Calculate average
3. Apply simple adjustments

**Example: moving_average_baseline**

```python
# Step 1: Get recent games (NO similarity checking)
last_10_games = get_last_n_games(player, n=10)

# Step 2: Simple average
baseline = sum([g.points for g in last_10_games]) / 10
# Example: [24, 27, 22, 25, 28, 23, 26, 25, 24, 26] → 25.0 avg

# Step 3: Apply adjustments (explicit rules)
if game.is_home:
    baseline += 1.2  # We decided home = +1.2 points

if game.rest_days == 0:
    baseline -= 2.5  # We decided back-to-back = -2.5 points

# Done! No similarity matching at all.
```

**Why use this approach:**
- ✅ Simple and transparent
- ✅ Fast (no similarity calculations)
- ✅ Works well for consistent players
- ✅ Hard to beat (good baseline)

**When it fails:**
- ❌ Doesn't account for opponent quality
- ❌ Doesn't account for unique situations
- ❌ Same prediction regardless of matchup

---

### Type 2: Mathematical Models (No Similarity)

**Concept:** "Model the underlying mechanics"

**How it works:**
1. Calculate expected value from first principles
2. Use basketball math/physics
3. Apply domain knowledge

**Example: zone_matchup_v1**

```python
# Step 1: Analyze player's shot distribution
player_shoots_paint = 0.45  # 45% of shots in paint
player_paint_accuracy = 0.65  # Makes 65% in paint
player_attempts_per_game = 16

# Step 2: Analyze opponent defense
opponent_allows_paint_pct = 0.60  # Allows 60% in paint
league_average_paint_pct = 0.56   # League average is 56%

# Step 3: Calculate expected points (MATH, not similarity)
expected_paint_attempts = player_shoots_paint * player_attempts_per_game
# = 0.45 × 16 = 7.2 attempts in paint

expected_paint_makes = expected_paint_attempts * player_paint_accuracy
# = 7.2 × 0.65 = 4.68 makes

expected_paint_points = expected_paint_makes * 2
# = 4.68 × 2 = 9.36 points from paint

# Step 4: Adjust for opponent quality
# Opponent allows 60% vs 56% league avg = +4 percentage points worse
matchup_factor = 1 + (0.60 - 0.56) * some_weight
paint_points_adjusted = expected_paint_points * matchup_factor

# Repeat for mid-range and three-point zones...
# Sum all zones = final prediction

# NO SIMILARITY MATCHING - pure math!
```

**Why use this approach:**
- ✅ Captures matchup advantages
- ✅ Based on basketball fundamentals
- ✅ Explainable (Giannis vs weak paint defense = good matchup)
- ✅ Adapts to opponent strengths/weaknesses

**When it fails:**
- ❌ Assumes player plays "normally" (doesn't account for hot/cold streaks)
- ❌ Requires good shot zone data
- ❌ More complex than simple average

---

### Type 3: Case-Based Reasoning (YES, Uses Similarity)

**Concept:** "Find similar past situations and predict based on those"

**How it works:**
1. Define what makes situations "similar"
2. Find historical games matching today's context
3. Predict based on what happened in those games

**Example: similarity_balanced_v1**

```python
# Step 1: Define today's context
today = {
    'opponent': 'Lakers',
    'opponent_defense': 'elite',
    'rest_days': 1,
    'venue': 'away',
    'recent_form': 'hot'
}

# Step 2: Find similar historical games
# THIS IS WHERE SIMILARITY MATCHING HAPPENS
historical_games = find_similar_games(player, today)

# Returns games like:
# Game 1: vs Celtics (elite), 1 day rest, away, hot → 27 pts (95% similar)
# Game 2: vs Bucks (elite), 1 day rest, away, normal → 24 pts (85% similar)
# Game 3: vs Heat (elite), 2 days rest, away, hot → 28 pts (80% similar)
# ...

# Step 3: Weighted average based on similarity
prediction = 0
total_weight = 0

for game in historical_games:
    weight = game.similarity_score / 100
    prediction += game.points * weight
    total_weight += weight

prediction = prediction / total_weight
# = (27×0.95 + 24×0.85 + 28×0.80 + ...) / (0.95 + 0.85 + 0.80 + ...)

# Step 4: Apply Phase 4 adjustments
prediction += fatigue_adjustment
prediction += pace_adjustment
# etc.
```

**Why use this approach:**
- ✅ Captures unique situations
- ✅ Works well for unusual contexts
- ✅ Adapts to player's actual history
- ✅ Handles multiple factors simultaneously

**When it fails:**
- ❌ Requires lots of historical data
- ❌ Doesn't work for rookies
- ❌ Similarity calculation can be complex
- ❌ Slower than other methods

---

## 🔑 The Key Differences {#key-differences}

| System | Question Asked | Method | Similarity? |
|--------|---------------|---------|-------------|
| **moving_average_baseline** | "What did this player do recently?" | Average last 10 games | ❌ NO |
| **zone_matchup_v1** | "What should happen based on basketball math?" | Calculate expected points by zone | ❌ NO |
| **similarity_balanced_v1** | "What happened in similar situations before?" | Find similar games, average outcomes | ✅ YES |

---

## ➕ Understanding "Additive" Adjustments {#adjustments}

You asked about additive rules. This is about how you **COMBINE** information, not the prediction method itself.

### Additive Approach (What We're Using)

**Formula:** `Final = Baseline + Adjustment₁ + Adjustment₂ + ...`

**Example:**
```python
baseline = 25.0  # From similarity, average, or math

# Apply adjustments (additive)
fatigue = -2.5      # Tired = -2.5 points
matchup = +3.0      # Good matchup = +3.0 points
pace = +1.2         # Fast game = +1.2 points
home = +1.2         # Home game = +1.2 points

final = baseline + fatigue + matchup + pace + home
final = 25.0 + (-2.5) + 3.0 + 1.2 + 1.2
final = 27.9 points
```

**Pros:**
- ✅ Intuitive (easier to understand)
- ✅ Independent adjustments (each factor adds/subtracts)
- ✅ Matches Phase 4 design (adjustments are in points)

**Cons:**
- ❌ Adjustments same magnitude regardless of baseline (tired LeBron vs tired bench player both -2.5)

---

### Multiplicative Approach (Alternative)

**Formula:** `Final = Baseline × Factor₁ × Factor₂ × ...`

**Example:**
```python
baseline = 25.0

# Apply factors (multiplicative)
fatigue_factor = 0.90      # Tired = 10% reduction
matchup_factor = 1.12      # Good matchup = 12% boost
pace_factor = 1.05         # Fast game = 5% boost
home_factor = 1.04         # Home game = 4% boost

final = baseline * fatigue_factor * matchup_factor * pace_factor * home_factor
final = 25.0 × 0.90 × 1.12 × 1.05 × 1.04
final = 27.4 points
```

**Pros:**
- ✅ Scales with player quality (10% of 30 pts ≠ 10% of 10 pts)
- ✅ Naturally bounds predictions (can't go negative)
- ✅ Percentage-based (some find this intuitive)

**Cons:**
- ❌ Less intuitive than additive
- ❌ Harder to tune factor ranges
- ❌ Doesn't match Phase 4 design

---

## 🏀 Real-World Example: LeBron James {#real-world-example}

**Scenario:** LeBron playing vs Celtics (elite defense), back-to-back, away

### System 1: moving_average_baseline

```
Recent 10 games: 26.8 ppg
Adjustments: -2.5 (back-to-back) + 0 (away)
Prediction: 24.3 points
Logic: Simple recent average with fatigue penalty
```

### System 2: zone_matchup_v1

```
LeBron attacks paint: 45% of shots
Celtics paint defense: Elite (allows 54%, league avg 56%)
Expected from paint: 10.5 points
Expected from other zones: 14.8 points
Adjustments: +1.2 (LeBron good vs Celtics paint)
Prediction: 26.5 points
Logic: Matchup actually favorable despite elite defense
```

### System 3: similarity_balanced_v1

```
Found 8 similar games:
- vs Heat (elite), back-to-back, away: 22 pts
- vs 76ers (elite), back-to-back, away: 24 pts
- vs Bucks (elite), back-to-back, away: 21 pts
- Average of similar: 22.7 pts
Adjustments: +0.5 (pace) - 1.0 (Celtics better than avg elite)
Prediction: 22.2 points
Logic: In similar situations, LeBron scores less
```

### System 4: xgboost_v1 (ML)

```
Features: [26.8, 0, 1, 112.1, ...]  # 25 features
Model learned patterns from 4 years
Prediction: 23.8 points
Logic: Model learned LeBron + back-to-back + elite D = lower
```

### System 5: meta_ensemble

```
Combine all:
- moving_average: 24.3 (weight: 1.04)
- zone_matchup: 26.5 (weight: 1.16)
- similarity: 22.2 (weight: 1.08)
- xgboost: 23.8 (weight: 1.12)

Weighted average: 24.1 points
Logic: Ensemble combines insights from all approaches
```

**Notice:** Different systems give different predictions (22.2 to 26.5)! That's good - diversity helps ensemble.

---

## 🎓 Key Takeaways {#takeaways}

### 1. Not all rule-based systems use similarity matching
- Only **similarity_balanced_v1** does
- Other systems use different logic

### 2. "Additive" refers to how you combine adjustments
- **Additive:** `baseline + adj1 + adj2`
- **Multiplicative:** `baseline × factor1 × factor2`
- We chose additive because it's intuitive

### 3. Different systems excel in different situations
- **Moving average:** Consistent players
- **Zone matchup:** Clear matchup advantages
- **Similarity:** Unusual situations
- **ML:** Complex patterns
- **Ensemble** combines all approaches

### 4. Ensemble combines all approaches
- Takes advantage of each system's strengths
- Often most accurate overall

---

## 🌡️ Analogy: Predicting Tomorrow's Temperature

**Simple Average (moving_average_baseline):**
"Last 7 days averaged 68°F, so tomorrow will be 68°F"
- Simple, fast, often good enough

**Physics Model (zone_matchup_v1):**
"Sun angle + humidity + pressure system = 72°F"
- Based on underlying mechanics

**Similar Days (similarity_balanced_v1):**
"Find days with similar pressure, humidity, wind → averaged 70°F on those days"
- Case-based reasoning

**Machine Learning (xgboost_v1):**
"Model learned from 10 years of data → predicts 71°F"
- Pattern recognition

**Ensemble (meta_ensemble):**
"Combine all predictions with weights → 70.5°F"
- Best of all worlds

---

## 📚 For Your Learning

Think of each system as a different "expert":
- Each expert has a different methodology
- The ensemble is the "committee decision"
- Diversity of approaches is more valuable than perfection of one

---

## 🔗 Related Documentation {#related-docs}

### Tutorials
- **[Getting Started](./01-getting-started.md)** - Onboarding overview
- **[Worked Prediction Examples](./03-worked-prediction-examples.md)** - Step-by-step prediction walkthroughs
- **[Operations Command Reference](./04-operations-command-reference.md)** - Quick commands

### Algorithms
- **[Composite Factor Calculations](../../algorithms/01-composite-factor-calculations.md)** - Mathematical specifications for all 5 systems
- **[Confidence Scoring Framework](../../algorithms/02-confidence-scoring-framework.md)** - How confidence scores are calculated

### ML Training
- **[Initial Model Training](../../ml-training/01-initial-model-training.md)** - XGBoost training procedures
- **[Continuous Retraining](../../ml-training/02-continuous-retraining.md)** - Model improvement over time

---

**Version:** 1.0
**Last Updated:** 2025-11-16
**Maintained By:** Documentation Team
