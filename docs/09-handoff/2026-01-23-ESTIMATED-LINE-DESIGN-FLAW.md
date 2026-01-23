# The Estimated Line Design Flaw: A Case Study in Circular Reasoning

**Date:** 2026-01-23
**Author:** Session analysis
**Status:** Documented for posterity

---

## Executive Summary

The ESTIMATED_AVG betting line system had a **fundamental design flaw**: the estimated line and the prediction were both derived from the same data source (`points_avg_last_5`). This created a circular comparison where we were essentially comparing a number to itself with noise.

**Result:** 42.7% win rate (worse than a coin flip)

---

## How the Estimated Line Was Created

When a player had no real sportsbook betting line, the system created a fake "estimated" line.

**File:** `predictions/coordinator/player_loader.py` (lines 1041-1059)

```python
def _estimate_betting_line_with_method(self, player_lookup: str):
    # Query player's recent averages
    query = """
    SELECT
        points_avg_last_5,
        points_avg_last_10,
        l10_games_used as games_played
    FROM upcoming_player_game_context
    WHERE player_lookup = @player_lookup
    """

    # Use L5 average, rounded to nearest 0.5
    if row.points_avg_last_5 is not None:
        avg = float(row.points_avg_last_5)
        estimated_line = round(avg * 2) / 2.0  # Round to 0.5
        return estimated_line, 'points_avg_last_5'
```

**Example:**
- LeBron's `points_avg_last_5` = 26.3
- Estimated line = `round(26.3 * 2) / 2.0` = **26.5**

---

## How the Prediction Was Created

The prediction systems also heavily relied on `points_avg_last_5`.

### Moving Average Baseline

**File:** `predictions/worker/prediction_systems/moving_average_baseline.py` (lines 58-60, 105-108)

```python
# Weights
self.weight_last_5 = 0.50   # 50% weight on L5
self.weight_last_10 = 0.30  # 30% weight on L10
self.weight_season = 0.20   # 20% weight on season

# Prediction
base_prediction = (
    points_last_5 * 0.50 +
    points_last_10 * 0.30 +
    points_season * 0.20
)

# Then add adjustments
predicted_points = base_prediction + fatigue_adj + pace_adj + venue_adj + ...
```

### CatBoost V8 (ML Model)

**File:** `predictions/worker/prediction_systems/catboost_v8.py` (lines 39-40, 324-325)

```python
# First two features in the model:
V8_FEATURES = [
    "points_avg_last_5",    # Feature #1
    "points_avg_last_10",   # Feature #2
    "points_avg_season",    # Feature #3
    ...
]

# Feature vector construction:
vector = np.array([
    features.get('points_avg_last_5', season_avg),
    features.get('points_avg_last_10', season_avg),
    ...
])
```

### Similarity Balanced V1

**File:** `predictions/worker/prediction_systems/similarity_balanced_v1.py` (lines 140, 151)

```python
# Uses L5 for form calculation
last_5 = features.get('points_avg_last_5', 0)
season = features.get('points_avg_season', 0)
form = self._get_form_bucket(last_5, season)
```

---

## The Circular Comparison Problem

### The Math

```
Estimated Line = round(L5, 0.5)
Prediction     = 0.50 * L5 + 0.30 * L10 + 0.20 * season + adjustments

"Edge" = Prediction - Estimated Line
       = (0.50 * L5 + 0.30 * L10 + 0.20 * season + adj) - round(L5, 0.5)
```

### Simplified Example

Let's say a player has:
- `points_avg_last_5` = 24.0
- `points_avg_last_10` = 23.5
- `points_avg_season` = 24.2
- Adjustments = +0.8 (fatigue, pace, etc.)

**Estimated Line:**
```
round(24.0 * 2) / 2.0 = 24.0
```

**Prediction:**
```
0.50 * 24.0 + 0.30 * 23.5 + 0.20 * 24.2 + 0.8
= 12.0 + 7.05 + 4.84 + 0.8
= 24.69
```

**"Edge":**
```
24.69 - 24.0 = 0.69 points → Barely an edge, recommend OVER?
```

### What the "Edge" Actually Represents

The calculated edge is NOT a disagreement with market consensus. It's:

1. **The difference between L5 and the weighted average of L5/L10/season**
   - This is random noise (recent variance vs longer-term average)

2. **The adjustments (fatigue, pace, venue, etc.)**
   - These might be real, but they're calibrated assuming we're comparing to Vegas
   - Without a real market baseline, we don't know if +0.8 for "high pace" is accurate

---

## Why Vegas Lines Work Better

### Vegas Lines Are Efficient Markets

| Factor | Vegas Incorporates | Estimated Line Incorporates |
|--------|-------------------|----------------------------|
| Player's recent scoring | ✅ Yes | ✅ Yes (it's ALL it uses) |
| Opponent's defense rating | ✅ Yes | ❌ No |
| Back-to-back fatigue | ✅ Yes | ❌ No |
| Home/away splits | ✅ Yes | ❌ No |
| Injury news (theirs + opponent) | ✅ Yes | ❌ No |
| Lineup changes | ✅ Yes | ❌ No |
| Sharp bettor information | ✅ Yes | ❌ No |
| Minutes projection | ✅ Yes | ❌ No |
| Blowout risk | ✅ Yes | ❌ No |

### When We Disagree with Vegas

```
Vegas says:     26.5 (incorporates ALL information)
We predict:     28.2 (found fatigue + pace matchup)
Edge:           1.7 points

If we're right about fatigue/pace → We win
If Vegas already priced it in → We might still win (noise)
```

### When We Disagree with Estimated Line

```
Estimated says: 26.5 (just L5 average, nothing else)
We predict:     28.2 (same L5 average + adjustments)
Edge:           1.7 points

But wait... we're comparing:
- Our model (uses L5 as primary input)
- To L5 rounded

This is like grading your own homework.
```

---

## The Statistical Evidence

### Win Rates by Line Source

| Line Source | Win Rate | MAE | Picks |
|-------------|----------|-----|-------|
| ACTUAL_PROP | **80.4%** | 6.36 | 8,236 |
| VEGAS_BACKFILL | 75.0% | 4.05 | 4 |
| ESTIMATED_AVG | **42.7%** | 8.63 | 124 |

### Why 42.7% (Worse Than Random)?

A coin flip would give 50%. We did **worse** because:

1. **Systematic bias in adjustments**: Our adjustments (fatigue, pace, etc.) might be calibrated for Vegas lines, not raw averages

2. **Confidence calibration is wrong**: The confidence score assumes we're finding edge vs. the market. With no market, high confidence = overconfidence

3. **The rounding creates fake edges**: `round(L5, 0.5)` can create artificial 0.5-point differences that look like edge but aren't

4. **Regression to the mean**: Players who score above their average tend to regress. Our adjustments might push in the wrong direction.

---

## Visual Representation

```
┌─────────────────────────────────────────────────────────────┐
│                    VEGAS LINE FLOW                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Sharp Bettors ─────┐                                       │
│  Injury News ───────┼──→ Vegas Line (26.5) ←── Real Market  │
│  Matchup Analysis ──┤         │                             │
│  Public Betting ────┘         │                             │
│                               ▼                             │
│                    Our Model Predicts (28.2)                │
│                               │                             │
│                               ▼                             │
│                    Edge = 1.7 (REAL disagreement)           │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  ESTIMATED LINE FLOW                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  points_avg_last_5 ─────→ Estimated Line (24.5)             │
│         │                        │                          │
│         │    (same data!)        │                          │
│         ▼                        ▼                          │
│  Our Model Uses L5 ────→ Prediction (25.2)                  │
│         │                        │                          │
│         └────────────────────────┘                          │
│                    │                                        │
│                    ▼                                        │
│         Edge = 0.7 (CIRCULAR - comparing to ourselves)      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Lessons Learned

### 1. Never Compare a Prediction to Its Own Input
If your prediction uses X as a primary feature, don't create a baseline from X. You'll just be measuring noise.

### 2. Market Efficiency Matters
Vegas lines represent real information from millions of dollars of bets. A season average represents nothing but historical data we already have.

### 3. Calibration Requires the Right Baseline
Confidence scores, edge thresholds, and recommendation logic were all calibrated assuming we're disagreeing with an efficient market. They don't work when comparing to a naive baseline.

### 4. Worse Than Random is a Red Flag
42.7% win rate means our system was **systematically wrong**, not just noisy. This indicates a fundamental flaw, not bad luck.

---

## The Fix (Implemented 2026-01-23)

1. **Stop generating estimated lines** - `disable_estimated_lines=True`
2. **Still predict points** for players without lines (for learning)
3. **Mark as NO_PROP_LINE** - No OVER/UNDER recommendation
4. **Only grade real lines** - Win rate metrics only for actual sportsbook lines

See: [No Estimated Lines Implementation](./2026-01-23-NO-ESTIMATED-LINES-IMPLEMENTATION.md)

---

## Related Files

| File | Purpose |
|------|---------|
| `predictions/coordinator/player_loader.py` | Where estimated lines were created |
| `predictions/worker/prediction_systems/moving_average_baseline.py` | Uses L5 with 50% weight |
| `predictions/worker/prediction_systems/catboost_v8.py` | Uses L5 as first feature |
| `predictions/worker/prediction_systems/similarity_balanced_v1.py` | Uses L5 for form buckets |
