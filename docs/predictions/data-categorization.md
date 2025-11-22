# NBA Predictions - Data Categorization Framework

**Created:** 2025-11-21 17:45:00 PST
**Last Updated:** 2025-11-21 17:45:00 PST

Quick reference for the four-category data framework used in similarity-based predictions.

## Overview

**Purpose:** Organize data by when it becomes available and how it's used

**Categories:**
1. **Pre-Game Context** - Static before tipoff (similarity matching)
2. **Real-Time Context** - Updates until game time (adjustments)
3. **Game Results** - Actual outcomes (training data)
4. **ML Predictions** - Model outputs (feedback loop)

## The Four Categories

### 1. Pre-Game Context

**Definition:** Static data available before tipoff

**Purpose:** Pattern matching to find historically similar games

**Update Timing:** Overnight (11 PM - 6 AM)

**Key Fields:**

```
Player Situation:
- days_rest
- back_to_back
- star_teammates_out
- usage_rate_projection
- season_phase

Recent Performance:
- points_avg_last_5
- points_avg_last_10
- prop_over_streak
- prop_under_streak

Matchup Context:
- home_game
- opponent_def_rating_last_10
- team_win_streak_entering
- games_vs_opponent_career
- points_avg_vs_opponent_career

Initial Market:
- opening_line
- line_movement (initial)
```

**Usage Example:**

```sql
-- Find similar historical situations
SELECT AVG(points) as avg_points_similar,
       COUNT(*) as similar_games
FROM player_game_summary
WHERE player_lookup = 'lebronjames'
  AND days_rest BETWEEN 1 AND 2
  AND opponent_def_rating_last_10 BETWEEN 105 AND 115
  AND home_game = TRUE
  AND season_phase = 'mid'
  AND prop_over_streak <= 1
```

### 2. Real-Time Context

**Definition:** Updates between line opening and game time

**Purpose:** Last-minute prediction adjustments

**Update Timing:** Hourly (6 AM - game time)

**Key Fields:**

```
Player Availability:
- player_status (probable/questionable/doubtful/out)
- injury_report
- star_teammates_out (updated)

Market Movement:
- current_points_line
- line_movement (total)
- public_betting_pct

Game Context:
- game_spread
- team_implied_points
- usage_rate_projection (updated)
```

**Risk Management:**

```python
# Pull prop if significant context change
if context_changed_significantly(old, new):
    if new.star_teammates_out > old.star_teammates_out:
        logger.warning("Star teammate ruled out - pull prop")
        return PULL_FROM_OFFERING
```

### 3. Game Results

**Definition:** Actual performance (post-game only)

**Purpose:** Training data for similarity analysis

**Update Timing:** Nightly (11 PM - 2 AM)

**Key Fields:**

```
Performance Stats:
- points
- minutes_played
- assists, rebounds
- fg_attempts
- usage_rate (actual)

Prop Outcomes:
- over_under_result (OVER/UNDER)
- margin (points - line)
- points_line (actual)

Game Context:
- win_flag
- overtime_periods
- margin_of_victory
- plus_minus
```

**Training Logic:**

```sql
-- Analyze outcomes in similar situations
SELECT
  AVG(points) as avg_points,
  AVG(CASE WHEN over_under_result = 'OVER' THEN 1.0 ELSE 0.0 END) as over_rate,
  COUNT(*) as sample_size
FROM player_game_summary
WHERE <similar_pre_game_context>
  AND game_date < CURRENT_DATE()  -- Historical only
```

### 4. ML Predictions

**Definition:** Model-generated forecasts

**Purpose:** Today's output → tomorrow's historical context

**Update Timing:** Morning (6-8 AM)

**Key Fields:**

```
Core Predictions:
- ml_points_prediction
- ml_over_probability
- ml_prediction_confidence
- recommendation (OVER/UNDER/PASS)
- model_version

Future Enhancements:
- ml_historical_accuracy (model's past performance)
- avg_confidence_when_correct
- prediction_vs_actual_margin
```

**Feedback Loop:**

```sql
-- Model performance becomes context
SELECT
  player_lookup,
  AVG(ml_prediction_confidence) as avg_confidence,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM prediction_accuracy
WHERE model_version = 'similarity_v1'
  AND <similar_context>
GROUP BY player_lookup
```

## How Similarity Matching Works

### Step 1: Collect Context for Today's Games

```python
# Pre-Game Context (overnight)
context = {
    'player_lookup': 'lebronjames',
    'days_rest': 2,
    'opponent_def_rating_last_10': 110.5,
    'home_game': True,
    'points_avg_last_5': 27.2,
    'season_phase': 'mid'
}
```

### Step 2: Find Similar Historical Games

```python
# Query historical games with similar Pre-Game Context
similar_games = find_similar_situations(
    player='lebronjames',
    days_rest_range=(1, 2),
    opponent_def_rating_range=(105, 115),
    home_game=True,
    season_phase='mid'
)
```

### Step 3: Analyze Historical Game Results

```python
# What happened in those similar games?
avg_points = similar_games['points'].mean()  # 28.5
over_rate = (similar_games['over_under_result'] == 'OVER').mean()  # 0.72
```

### Step 4: Generate ML Prediction

```python
# Today's prediction (becomes tomorrow's historical context)
prediction = {
    'ml_points_prediction': 28.5,
    'ml_over_probability': 0.72,
    'ml_prediction_confidence': 0.85,
    'recommendation': 'OVER' if current_line < 25.5 else 'PASS'
}
```

## Data Pipeline Schedule

### Overnight (11 PM - 6 AM)

1. Load Game Results from completed games
2. Calculate Pre-Game Context for upcoming games
3. Update historical similarity databases

### Morning (6 AM - 8 AM)

1. Initialize Real-Time Context for today
2. Generate ML Predictions using Pre-Game + initial Real-Time Context
3. Create similarity matches

### Intraday (8 AM - Game Time)

1. Update Real-Time Context hourly
2. Refresh ML Predictions when context changes significantly
3. Risk assessment for prop offerings

### Post-Game (Next Day)

1. Calculate prediction accuracy
2. Update model performance metrics
3. Identify prediction improvements

## Database Design

### Historical Tables (Similarity Matching)

```sql
-- Pre-Game Context + Game Results for pattern analysis
CREATE TABLE player_game_summary (
    -- Pre-Game Context fields
    player_lookup STRING,
    days_rest INT64,
    opponent_def_rating_last_10 FLOAT64,
    home_game BOOLEAN,
    points_avg_last_5 FLOAT64,

    -- Game Results fields
    points INT64,
    over_under_result STRING,
    margin FLOAT64,

    -- Indexed for similarity search
    game_date DATE
)
PARTITION BY game_date
CLUSTER BY player_lookup, days_rest, home_game;
```

### Current Tables (Today's Games)

```sql
-- Real-Time Context + ML Predictions for today
CREATE TABLE upcoming_player_game_context (
    -- Real-Time Context
    player_lookup STRING,
    current_points_line FLOAT64,
    player_status STRING,

    -- ML Predictions
    ml_points_prediction FLOAT64,
    ml_over_probability FLOAT64,
    recommendation STRING,

    game_date DATE
)
PARTITION BY game_date;
```

### Accuracy Tables (Model Performance)

```sql
-- ML Predictions performance tracking
CREATE TABLE prediction_accuracy (
    player_lookup STRING,
    model_version STRING,
    ml_prediction_confidence FLOAT64,
    prediction_correct BOOLEAN,
    game_date DATE
)
PARTITION BY game_date;
```

## Query Optimization

**Pre-Game Context:**
- Heavily indexed for similarity search
- Cluster by most common search criteria
- Partition by game_date for time-based queries

**Real-Time Context:**
- Optimized for frequent updates
- Small working set (today's games only)

**Game Results:**
- Optimized for analytical queries
- Read-heavy, write-once pattern

## Business Applications

### Similarity Matching Engine

Uses Pre-Game Context to find historical games → analyzes Game Results patterns

### Risk Management

Real-Time Context changes → re-evaluate prop offerings

### Model Training

Game Results → improve ML Predictions accuracy

### Continuous Improvement

ML Predictions accuracy → becomes Pre-Game Context for future decisions

## Example: Complete Prediction Flow

```python
# 1. Pre-Game Context (calculated overnight)
pre_game = {
    'player': 'lebronjames',
    'days_rest': 2,
    'opponent_def_rating': 110.5,
    'home_game': True,
    'points_avg_last_5': 27.2
}

# 2. Find similar historical games
similar = query_similar_games(pre_game)
# Returns: 45 games with avg 28.5 points, 72% OVER rate

# 3. Real-Time Context (updated this morning)
real_time = {
    'current_line': 25.5,
    'player_status': 'probable',
    'star_teammates_out': 0
}

# 4. Generate ML Prediction
prediction = {
    'ml_points_prediction': 28.5,  # From similar games
    'ml_over_probability': 0.72,    # From similar games
    'ml_prediction_confidence': 0.85,
    'recommendation': 'OVER'  # 28.5 > 25.5
}

# 5. After game completes → Game Results
results = {
    'points': 31,  # Actual performance
    'over_under_result': 'OVER',
    'margin': 5.5  # 31 - 25.5
}

# 6. Accuracy tracking
accuracy = {
    'prediction_correct': True,  # Was OVER
    'confidence_was': 0.85,
    'margin_was': 5.5
}
# This becomes context for future predictions
```

## Implementation Files

**Prediction Systems:**
- `predictions/worker/prediction_systems/similarity_balanced_v1.py`

**Schemas:**
- `schemas/bigquery/predictions/01_player_prop_predictions.sql`
- `schemas/bigquery/predictions/02_prediction_results.sql`
- `schemas/bigquery/predictions/09_ml_prediction_metadata.sql`

**Tests:**
- `tests/predictions/test_similarity.py`

## See Also

- [Analytics Processors Reference](../reference/03-analytics-processors-reference.md)
- [Predictions Documentation](../predictions/)
