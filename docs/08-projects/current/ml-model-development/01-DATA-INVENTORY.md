# ML Data Inventory - What Exists and Where

**Updated**: 2026-01-02
**Purpose**: Complete catalog of available data for ML training and evaluation

---

## 📊 Summary Table

| Data Type | Table/Location | Games | Records | Date Range | Status |
|-----------|---------------|-------|---------|------------|--------|
| **Raw Box Scores** | `nba_raw.nbac_gamebook_player_stats` | 5,476 | ~180k | 2021-2024 | ✅ Complete |
| **Raw Box Scores** | `nba_raw.bdl_player_boxscores` | 5,274 | ~170k | 2021-2024 | ✅ Complete |
| **Analytics** | `nba_analytics.player_game_summary` | 4,725 | ~150k | 2021-2024 | ✅ Complete |
| **Features** | `nba_precompute.player_composite_factors` | 3,465 | ~101k | 2021-2024 | ✅ Complete |
| **Predictions** | `nba_predictions.player_prop_predictions` | 3,050 | ~315k | 2021-2024 | ✅ Complete |
| **Grading** | `nba_predictions.prediction_accuracy` | 3,050 | **328k** | 2021-2024 | ✅ **COMPLETE** |

---

## 🎯 Phase 5B Grading Data (CRITICAL FOR ML)

### Table: `nba_predictions.prediction_accuracy`

**Coverage**:
```
Season 2021-22: 146 dates, 1,104 games, 113,736 graded predictions
Season 2022-23: 137 dates, 1,020 games, 104,766 graded predictions
Season 2023-24: 120 dates,   926 games,  96,940 graded predictions
Season 2025-26:  12 dates,    69 games,  12,585 graded predictions
----------------------------------------
TOTAL:          403 dates, 3,119 games, 328,027 graded predictions
```

### What's In The Data

**Sample query**:
```sql
SELECT
  player_lookup,
  game_date,
  system_id,
  predicted_points,
  actual_points,
  absolute_error,
  signed_error,
  recommendation,
  was_correct,
  confidence_score
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date = '2022-01-15'
LIMIT 5;
```

**Fields Available**:
- `prediction_id` - Unique prediction ID
- `system_id` - Which prediction system generated this
- `player_lookup` - Player identifier
- `universal_player_id` - Unified player ID
- `game_date` - Game date
- `game_id` - Game identifier
- `predicted_points` - What the system predicted
- `actual_points` - What the player actually scored
- `absolute_error` - |predicted - actual|
- `signed_error` - predicted - actual (shows bias)
- `recommendation` - OVER/UNDER/SKIP
- `was_correct` - Boolean: was recommendation correct?
- `confidence_score` - System's confidence (0-1)
- `current_points_line` - Betting line at prediction time
- `line_margin` - How far prediction was from line

---

## 🔍 What You Can Query

### 1. System Performance Comparison

```sql
-- Which prediction system performs best?
SELECT
  system_id,
  COUNT(*) as total_predictions,
  AVG(absolute_error) as mae,
  AVG(signed_error) as bias,
  SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) / COUNT(*) as accuracy,
  AVG(confidence_score) as avg_confidence
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2021-11-01' AND game_date < '2024-05-01'
GROUP BY system_id
ORDER BY mae ASC;
```

**Expected Output**:
| system_id | predictions | mae | bias | accuracy | confidence |
|-----------|------------|-----|------|----------|-----------|
| system_a | 100,000 | 4.2 | -0.3 | 0.72 | 0.68 |
| system_b | 100,000 | 4.8 | +0.1 | 0.68 | 0.65 |

### 2. Player-Specific Performance

```sql
-- Which players are easiest/hardest to predict?
SELECT
  player_lookup,
  COUNT(*) as predictions,
  AVG(absolute_error) as mae,
  AVG(actual_points) as avg_points,
  STDDEV(actual_points) as point_volatility
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
GROUP BY player_lookup
HAVING predictions >= 50  -- Minimum sample size
ORDER BY mae ASC
LIMIT 20;
```

### 3. Temporal Patterns

```sql
-- Does accuracy vary by time of season?
SELECT
  EXTRACT(MONTH FROM game_date) as month,
  COUNT(*) as predictions,
  AVG(absolute_error) as mae,
  SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) / COUNT(*) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
GROUP BY month
ORDER BY month;
```

### 4. Situational Analysis

```sql
-- Home vs away performance
SELECT
  is_home_game,
  AVG(absolute_error) as mae,
  SUM(CASE WHEN was_correct THEN 1 ELSE 0 END) / COUNT(*) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
JOIN `nba-props-platform.nba_analytics.player_game_summary` pgs
  ON pa.game_id = pgs.game_id AND pa.player_lookup = pgs.player_lookup
GROUP BY is_home_game;
```

---

## 🧮 Feature Data (Phase 4)

### Table: `nba_precompute.player_composite_factors`

**What's Available**:
- Rolling averages (last 5, 10, 20 games)
- Matchup history vs opponent
- Shot zone analysis
- Pace adjustments
- Fatigue indicators
- Usage trends

**Sample**:
```sql
SELECT
  player_lookup,
  game_date,
  rolling_avg_points_5g,
  rolling_avg_points_10g,
  matchup_difficulty_score,
  expected_pace,
  fatigue_factor,
  shot_zone_mismatch_score
FROM `nba-props-platform.nba_precompute.player_composite_factors`
WHERE game_date = '2022-01-15'
LIMIT 5;
```

**Use For**: Training new ML models (inputs/features)

---

## 📈 Actual Results (Phase 2-3)

### For Training Labels

**Table**: `nba_analytics.player_game_summary`

```sql
SELECT
  player_lookup,
  game_date,
  points,
  minutes_played,
  field_goals_made,
  three_pointers_made,
  free_throws_made,
  rebounds_total,
  assists,
  is_home_game
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-01' AND game_date < '2024-06-01';
```

**Use For**: Training new models (labels/targets)

---

## 🎯 Historical Predictions (Phase 5A)

### Table: `nba_predictions.player_prop_predictions`

**What It Contains**:
- Predictions made by existing systems
- Multiple systems per game/player
- Confidence scores
- Recommendation (OVER/UNDER)
- Line values

**Use For**:
- Comparison baseline
- Ensemble input
- Understanding existing system logic

---

## 📊 Data Quality Checks

### Completeness by Season

```sql
-- Check data availability across phases
WITH phase2 AS (
  SELECT '2021-22' as season, COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE season_year = 2021
  UNION ALL
  SELECT '2022-23', COUNT(DISTINCT game_id)
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE season_year = 2022
  UNION ALL
  SELECT '2023-24', COUNT(DISTINCT game_id)
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE season_year = 2023
),
phase5b AS (
  SELECT '2021-22' as season, COUNT(DISTINCT game_id) as games
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2021-10-01' AND game_date < '2022-10-01'
  UNION ALL
  SELECT '2022-23', COUNT(DISTINCT game_id)
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2022-10-01' AND game_date < '2023-10-01'
  UNION ALL
  SELECT '2023-24', COUNT(DISTINCT game_id)
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE game_date >= '2023-10-01' AND game_date < '2024-10-01'
)
SELECT
  p2.season,
  p2.games as raw_games,
  p5.games as graded_games,
  ROUND(p5.games / p2.games * 100, 1) as pct_coverage
FROM phase2 p2
JOIN phase5b p5 ON p2.season = p5.season;
```

---

## 🎓 Data Usage Patterns

### For System Evaluation

**Use**: Phase 5B grading data
**Goal**: Understand current system performance
**Queries**: System comparison, temporal trends, player-specific analysis

### For New Model Training

**Inputs (X)**: Phase 4 features
- Rolling averages
- Matchup data
- Situational factors

**Labels (y)**: Phase 3 actual results
- Actual points scored
- Game outcome metrics

**Validation**: Phase 5B grading
- Compare new model to existing systems
- Use graded predictions as ground truth

### For Ensemble Models

**Inputs**: Phase 5A predictions (from all systems)
**Meta-features**: Phase 5B grading (which system when?)
**Output**: Weighted combination

---

## 💾 Data Access Examples

### Extract Training Dataset

```python
from google.cloud import bigquery

client = bigquery.Client(project='nba-props-platform')

query = """
SELECT
  f.player_lookup,
  f.game_date,
  f.game_id,
  -- Features (X)
  f.rolling_avg_points_5g,
  f.rolling_avg_points_10g,
  f.matchup_difficulty_score,
  f.fatigue_factor,
  f.shot_zone_mismatch_score,
  -- Label (y)
  a.points as actual_points
FROM `nba-props-platform.nba_precompute.player_composite_factors` f
JOIN `nba-props-platform.nba_analytics.player_game_summary` a
  ON f.game_id = a.game_id AND f.player_lookup = a.player_lookup
WHERE f.game_date >= '2021-11-01' AND f.game_date < '2024-04-15'
  AND a.minutes_played >= 10  -- Filter out garbage time
"""

df = client.query(query).to_dataframe()
print(f"Training samples: {len(df)}")
```

### Query Grading Results

```python
query = """
SELECT
  system_id,
  COUNT(*) as total,
  AVG(absolute_error) as mae,
  AVG(CASE WHEN was_correct THEN 1.0 ELSE 0.0 END) as accuracy
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2021-11-01' AND game_date < '2024-05-01'
GROUP BY system_id
ORDER BY mae ASC
"""

results = client.query(query).to_dataframe()
print(results)
```

---

## 🎯 Summary: What You Have

**For ML Evaluation**:
- ✅ 328k graded predictions
- ✅ Multiple systems to compare
- ✅ 3 complete seasons
- ✅ Performance metrics pre-calculated

**For ML Training**:
- ✅ 3,500+ games with features
- ✅ 5,400+ games with actual results
- ✅ Rich feature set (Phase 4)
- ✅ Multiple seasons for cross-validation

**For Ensemble**:
- ✅ Multiple system predictions (Phase 5A)
- ✅ System-specific performance (Phase 5B)
- ✅ Can train meta-learner

---

## ✅ Data Readiness: 100%

**No additional backfill needed for ML work**

All required data exists in BigQuery and is ready to query.

**Next**: See `02-EVALUATION-PLAN.md` to start analyzing system performance
