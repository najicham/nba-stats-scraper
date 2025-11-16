# Phase 5 Data Categorization Framework

**File:** `docs/predictions/data-sources/01-data-categorization.md`
**Created:** 2025-11-15
**Last Updated:** 2025-11-15
**Purpose:** Categorize all Phase 5 data by availability timing and usage in prediction pipeline
**Status:** Current
**Source:** Wiki documentation (Data Categorization Framework)

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [The Four Categories](#four-categories)
3. [Category 1: Pre-Game Context](#pre-game-context)
4. [Category 2: Real-Time Context](#real-time-context)
5. [Category 3: Game Results](#game-results)
6. [Category 4: ML Predictions](#ml-predictions)
7. [Data Pipeline Integration](#data-pipeline)
8. [Business Applications](#business-applications)
9. [Technical Implementation](#technical-implementation)

---

## 🎯 Overview {#overview}

The NBA props prediction system organizes all data into **four distinct categories** based on when the data becomes available and how it's used in the prediction process. This framework ensures clear data pipeline timing, enables reliable similarity matching, and creates a feedback loop for continuous model improvement.

### How Historical Predictions Work

```
Step 1: Collect Pre-Game + Real-Time Context for today's games
Step 2: Find historically similar situations using Pre-Game Context
Step 3: Analyze Game Results from those similar historical games
Step 4: Generate ML Predictions for today, which become tomorrow's historical context
```

### The Feedback Loop

```
Today's Predictions
    ↓
Tomorrow's Historical Context
    ↓
Improved Pattern Matching
    ↓
Better Predictions
```

---

## 📊 The Four Categories {#four-categories}

| Category | Availability | Primary Purpose | Update Timing |
|----------|-------------|-----------------|---------------|
| **1. Pre-Game Context** | Before tipoff (static) | Pattern matching & similarity search | Overnight (11 PM - 6 AM) |
| **2. Real-Time Context** | Before tipoff (dynamic) | Last-minute adjustments & risk assessment | Hourly (6 AM - game time) |
| **3. Game Results** | After game complete | Training data & accuracy measurement | Nightly (11 PM - 2 AM) |
| **4. ML Predictions** | Morning (6-8 AM) | Today's output → Tomorrow's input | Daily (6 AM - 8 AM) |

---

## 1️⃣ Pre-Game Context {#pre-game-context}

### Definition

Information available before tipoff that remains static throughout the game.

### Primary Purpose

Pattern matching to find historically similar situations.

### Update Timing

Calculated overnight (11 PM - 6 AM) after previous day's games complete.

### Data Fields

**Player Situation Context:**

| Field | Description | Example |
|-------|-------------|---------|
| `days_rest` | Rest days since last game | 2 |
| `back_to_back` | Playing consecutive nights | true |
| `star_teammates_out` | Key players unavailable | ["Anthony Davis"] |
| `usage_rate_projection` | Expected role based on available players | 28.5% |
| `season_phase` | Early/mid/late season or playoffs | "mid" |

**Historical Performance Patterns:**

| Field | Description | Example |
|-------|-------------|---------|
| `points_avg_last_5` | Recent 5-game scoring average | 26.8 |
| `points_avg_last_10` | Broader 10-game trend | 25.3 |
| `prop_over_streak` | Consecutive games exceeding prop line | 3 |
| `prop_under_streak` | Consecutive games falling short | 0 |
| `games_vs_opponent_career` | Historical sample size vs this team | 47 |
| `points_avg_vs_opponent_career` | Career scoring vs this opponent | 28.1 |

**Matchup and Environmental Context:**

| Field | Description | Example |
|-------|-------------|---------|
| `home_game` | Playing at home venue | true |
| `opponent_def_rating_last_10` | Recent opponent defensive strength | 112.4 |
| `team_win_streak_entering` | Team momentum entering game | 3 |
| `team_loss_streak_entering` | Team struggles entering game | 0 |

**Initial Market Context:**

| Field | Description | Example |
|-------|-------------|---------|
| `opening_line` | First posted prop line | 25.5 |
| `line_movement` | Movement from opening to current | +1.0 |

### Similarity Matching Logic

Pre-Game Context creates the "search criteria" for finding historical games. The system looks for games where a player had similar rest, opponent strength, recent form, and situational factors.

**Example Query:**

```sql
SELECT
    game_date,
    points,
    over_under_result
FROM player_game_summary
WHERE player_lookup = 'lebron-james'
  AND days_rest BETWEEN 1 AND 2
  AND opponent_def_rating_last_10 BETWEEN 105 AND 115
  AND prop_over_streak <= 1
  AND season_phase = 'mid'
  AND home_game = TRUE
ORDER BY game_date DESC
LIMIT 30;
```

---

## 2️⃣ Real-Time Context {#real-time-context}

### Definition

Information that changes throughout the day before game time.

### Primary Purpose

Last-minute adjustments to predictions and risk assessment.

### Update Timing

Hourly updates from 6 AM until game time.

### Data Fields

**Player Availability:**

| Field | Description | Example |
|-------|-------------|---------|
| `player_status` | Injury report designation | "probable" |
| `injury_report` | Detailed injury description | "Right ankle soreness" |
| `star_teammates_out` | Updated based on latest injury reports | ["Anthony Davis"] |

**Market Movement:**

| Field | Description | Example |
|-------|-------------|---------|
| `current_points_line` | Most recent prop line | 26.5 |
| `line_movement` | Total movement from opening | +1.0 |
| `public_betting_pct` | Percentage of bets on over | 68% |

**Lineup Projections:**

| Field | Description | Example |
|-------|-------------|---------|
| `usage_rate_projection` | Updated based on final injury reports | 32.5% |
| `game_spread` | Point spread for the game | LAL -7.5 |
| `team_implied_points` | Team's expected scoring output | 115.5 |

### Business Logic

Real-Time Context allows the system to adjust predictions as new information becomes available. If a star teammate is ruled out 2 hours before tipoff, the system can update usage projections and re-calculate predictions.

**Risk Management:**

Props should be pulled from offering if key context changes dramatically:
- Player becomes questionable
- Star teammate ruled out
- Line moves significantly (>2.0 points)

**Example Adjustment:**

```python
# 2 PM: Anthony Davis ruled OUT
initial_prediction = {
    'predicted_points': 26.5,
    'confidence': 75,
    'usage_rate_projection': 28.5
}

# Re-calculate with updated context
updated_prediction = {
    'predicted_points': 29.2,  # Higher usage expected
    'confidence': 80,           # More confident with clarity
    'usage_rate_projection': 32.5
}
```

---

## 3️⃣ Game Results {#game-results}

### Definition

Actual performance statistics and outcomes, available only after game completion.

### Primary Purpose

Training data for similarity matching and measuring prediction accuracy.

### Update Timing

Processed nightly (11 PM - 2 AM) after games complete.

### Data Fields

**Performance Statistics:**

| Field | Description | Example |
|-------|-------------|---------|
| `points` | Total points scored | 31 |
| `minutes_played` | Playing time | 38.2 |
| `assists` | Assists recorded | 8 |
| `rebounds` | Total rebounds | 7 |
| `fg_attempts` | Shot attempts (volume indicator) | 22 |
| `usage_rate` | Actual usage percentage | 31.8% |

**Prop Outcomes:**

| Field | Description | Example |
|-------|-------------|---------|
| `over_under_result` | Whether player went OVER or UNDER | "OVER" |
| `margin` | Points scored minus prop line | +4.5 (31 - 26.5) |
| `points_line` | The actual line that was bet | 26.5 |

**Game Context Results:**

| Field | Description | Example |
|-------|-------------|---------|
| `win_flag` | Whether player's team won | true |
| `overtime_periods` | Extra playing time | 0 |
| `margin_of_victory` | Final game margin | +12 |
| `plus_minus` | Player's impact while on court | +15 |

### Training Data Logic

When the system finds historically similar Pre-Game Context situations, it analyzes the Game Results from those situations to predict today's outcome.

**Example Pattern Analysis:**

```sql
-- Find similar historical situations
SELECT
    AVG(points) as avg_points_in_similar_games,
    AVG(CASE WHEN over_under_result = 'OVER' THEN 1.0 ELSE 0.0 END) as over_rate,
    COUNT(*) as sample_size
FROM player_game_summary
WHERE player_lookup = 'lebron-james'
  AND days_rest BETWEEN 1 AND 2
  AND opponent_def_rating_last_10 BETWEEN 105 AND 115
  AND home_game = TRUE
  AND season_phase = 'mid';

-- Result:
-- avg_points_in_similar_games: 28.5
-- over_rate: 0.72 (72% hit rate)
-- sample_size: 18

-- Interpretation:
-- In 18 similar situations, LeBron averaged 28.5 points and went OVER 72% of the time.
-- If today's line is 25.5, that suggests strong OVER recommendation.
```

---

## 4️⃣ ML Predictions {#ml-predictions}

### Definition

Model-generated forecasts that become historical context for future predictions.

### Primary Purpose

Today's output becomes tomorrow's input for improved decision-making.

### Update Timing

Generated each morning (6-8 AM) after Pre-Game and Real-Time Context are ready.

### Data Fields

**Core Predictions:**

| Field | Description | Example |
|-------|-------------|---------|
| `ml_points_prediction` | Model's point forecast | 28.7 |
| `ml_over_probability` | Probability of exceeding the line | 76.5% |
| `ml_prediction_confidence` | Model's confidence level | 82 |
| `recommendation` | Final OVER/UNDER/PASS decision | "OVER" |
| `model_version` | Which model generated the prediction | "v2.1" |

**Historical ML Context (Future Enhancement):**

| Field | Description | Example |
|-------|-------------|---------|
| `model_historical_accuracy` | Model's accuracy on this player in similar situations | 67.5% |
| `avg_confidence_when_over` | Average confidence when player went OVER in past | 78.2 |
| `prediction_vs_actual_margin` | Recent prediction accuracy margin | -1.3 |

### Feedback Loop Logic

Today's ML predictions become part of tomorrow's Pre-Game Context. The system can learn patterns like:
- "When the model had 85% confidence on LeBron props, he hit 87% of the time"
- "Model tends to be overconfident on back-to-back games"

**Self-Improving Intelligence:**

```sql
-- Historical model performance becomes context
SELECT
    player_lookup,
    AVG(ml_prediction_confidence) as avg_model_confidence,
    AVG(CASE WHEN prediction_correct = TRUE THEN 1.0 ELSE 0.0 END) as accuracy,
    COUNT(*) as sample_size
FROM prediction_accuracy
WHERE model_version = 'v2.1'
  AND similar_context_situation = TRUE
GROUP BY player_lookup
HAVING sample_size >= 20
ORDER BY accuracy DESC;
```

**Example Insight:**

```
Player: lebron-james
Avg Confidence: 78.5
Accuracy: 72.3% (84/116 games)
Insight: Model is well-calibrated for LeBron (78% confidence → 72% accuracy)

Player: austin-reaves
Avg Confidence: 71.2
Accuracy: 58.1% (18/31 games)
Insight: Model overconfident on Reaves (71% confidence → 58% accuracy)
→ Adjust confidence downward by 10-15 points for role players
```

---

## 🔄 Data Pipeline Integration {#data-pipeline}

### Overnight Processing (11 PM - 6 AM)

```
┌────────────────────────────────────────┐
│ 1. Load Game Results                   │ (11 PM - 12 AM)
│    - Process completed games           │
│    - Calculate prop outcomes           │
│    - Update player_game_summary table  │
└────────────────────────────────────────┘
                ↓
┌────────────────────────────────────────┐
│ 2. Calculate Pre-Game Context          │ (12 AM - 4 AM)
│    - Historical patterns (last 5/10)   │
│    - Opponent matchups                 │
│    - Situational factors               │
└────────────────────────────────────────┘
                ↓
┌────────────────────────────────────────┐
│ 3. Update Similarity Databases         │ (4 AM - 6 AM)
│    - Index new game data               │
│    - Recalculate similarity scores     │
└────────────────────────────────────────┘
```

### Morning Preparation (6 AM - 8 AM)

```
┌────────────────────────────────────────┐
│ 1. Initialize Real-Time Context        │ (6 AM)
│    - Load initial injury reports       │
│    - Get opening betting lines         │
│    - Set baseline projections          │
└────────────────────────────────────────┘
                ↓
┌────────────────────────────────────────┐
│ 2. Generate ML Predictions             │ (6:15 AM - 6:30 AM)
│    - Use Pre-Game Context              │
│    - Apply initial Real-Time Context   │
│    - Create similarity matches         │
│    - Run prediction systems            │
└────────────────────────────────────────┘
```

### Intraday Updates (8 AM - Game Time)

```
Every Hour:
┌────────────────────────────────────────┐
│ 1. Update Real-Time Context            │
│    - Refresh injury reports            │
│    - Check line movement               │
│    - Update betting percentages        │
└────────────────────────────────────────┘
                ↓
┌────────────────────────────────────────┐
│ 2. Refresh ML Predictions              │ (if significant change)
│    - Re-run affected players           │
│    - Update confidence levels          │
│    - Trigger risk assessment           │
└────────────────────────────────────────┘
```

### Post-Game Analysis (Next Day)

```
┌────────────────────────────────────────┐
│ 1. Calculate Prediction Accuracy       │
│    - Compare ML Predictions vs Results │
│    - Update model performance metrics  │
└────────────────────────────────────────┘
                ↓
┌────────────────────────────────────────┐
│ 2. Identify Improvement Patterns       │
│    - System-specific performance       │
│    - Player-specific calibration       │
│    - Context-specific adjustments      │
└────────────────────────────────────────┘
```

---

## 💼 Business Applications {#business-applications}

### 1. Similarity Matching Engine

Uses Pre-Game Context to find historical games where similar conditions existed, then analyzes Game Results patterns from those situations.

**Value:** Enables data-driven predictions based on historical patterns, not just recent averages.

### 2. Risk Management

Real-Time Context changes trigger re-evaluation of prop offerings and confidence levels.

**Value:** Protects against offering bad lines when key information changes.

**Example Rules:**

```python
# Risk assessment thresholds
RISK_RULES = {
    'player_status_change': {
        'questionable': 'PULL_PROP',
        'doubtful': 'PULL_PROP',
        'out': 'PULL_PROP'
    },
    'star_teammate_ruled_out': 'REASSESS_CONFIDENCE',
    'line_movement_threshold': 2.0,  # Pull if line moves >2 points
    'public_betting_extreme': 85  # Pull if >85% on one side
}
```

### 3. Model Training

Game Results provide ground truth for improving ML Predictions accuracy and calibration.

**Value:** Continuous improvement through feedback loops.

### 4. Continuous Improvement

ML Predictions accuracy becomes part of Pre-Game Context for future decision-making, creating a self-improving system.

**Value:** System gets smarter over time without manual intervention.

---

## 🛠️ Technical Implementation {#technical-implementation}

### Database Design

**Historical Tables (Pre-Game Context + Game Results):**

```sql
-- Similarity matching queries
CREATE TABLE nba_analytics.player_game_summary (
  -- Pre-Game Context fields
  player_lookup STRING,
  game_date DATE,
  days_rest INT64,
  opponent_def_rating_last_10 FLOAT64,
  home_game BOOLEAN,
  -- ... other Pre-Game Context fields

  -- Game Results fields
  points INT64,
  over_under_result STRING,
  margin FLOAT64,
  -- ... other Game Results fields

  PRIMARY KEY (player_lookup, game_date)
)
PARTITION BY game_date
CLUSTER BY player_lookup, days_rest, opponent_def_rating_last_10;
```

**Current Tables (Real-Time Context + ML Predictions):**

```sql
-- Today's games and predictions
CREATE TABLE nba_predictions.player_prop_predictions (
  -- Real-Time Context
  player_lookup STRING,
  game_date DATE,
  current_points_line FLOAT64,
  player_status STRING,
  line_movement FLOAT64,

  -- ML Predictions
  ml_points_prediction FLOAT64,
  ml_over_probability FLOAT64,
  recommendation STRING,
  model_version STRING,

  PRIMARY KEY (player_lookup, game_date, model_version)
)
PARTITION BY game_date
CLUSTER BY player_lookup;
```

**Accuracy Tables (ML Predictions Performance):**

```sql
-- Track model performance over time
CREATE TABLE nba_analytics.prediction_accuracy (
  prediction_id STRING,
  player_lookup STRING,
  game_date DATE,

  -- Prediction details
  ml_points_prediction FLOAT64,
  ml_prediction_confidence INT64,
  points_line FLOAT64,

  -- Actual results
  actual_points INT64,
  prediction_correct BOOLEAN,
  margin_error FLOAT64,

  -- Context
  model_version STRING,
  similar_context_situation BOOLEAN,

  PRIMARY KEY (prediction_id)
)
PARTITION BY game_date
CLUSTER BY player_lookup, model_version, prediction_correct;
```

### Query Optimization

**Pre-Game Context Fields:**

Heavily indexed for similarity search performance:

```sql
-- Optimized similarity search
CREATE INDEX idx_similarity ON player_game_summary (
  player_lookup,
  days_rest,
  opponent_def_rating_last_10,
  home_game,
  season_phase
)
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 1095 DAY);  -- 3 years
```

**Real-Time Context:**

Optimized for frequent updates:

```sql
-- Partition by current date for fast updates
PARTITION BY DATE(last_updated)
CLUSTER BY player_lookup
```

**Game Results:**

Optimized for analytical queries:

```sql
-- Partition by game date for historical analysis
PARTITION BY game_date
CLUSTER BY player_lookup, over_under_result
```

### Data Quality Requirements

Each category has different quality requirements:

| Category | Quality Requirement | Validation |
|----------|-------------------|------------|
| **Pre-Game Context** | Must be stable and consistent | No changes after calculation |
| **Real-Time Context** | Must be current (< 1 hour old) | Timestamp checks |
| **Game Results** | Must be authoritative | Official NBA stats API |
| **ML Predictions** | Must be reproducible | Version tracking |

---

## 🔗 Related Documentation

**Phase 5 Operations:**
- **Deployment:** `docs/predictions/operations/01-deployment-guide.md` - How to deploy prediction services
- **Scheduling:** `docs/predictions/operations/02-scheduling-strategy.md` - When data updates run
- **Troubleshooting:** `docs/predictions/operations/03-troubleshooting.md` - How to debug data issues

**Data Flow:**
- **Phase 4→5:** `docs/data-flow/13-phase4-to-phase5-feature-consumption.md` - ML Feature Store consumption

**Architecture:**
- **Pipeline:** `docs/architecture/04-event-driven-pipeline-architecture.md` - Overall data flow

---

**Last Updated:** 2025-11-15
**Next Review:** After Phase 5 deployment
**Status:** Current - Comprehensive data categorization framework
