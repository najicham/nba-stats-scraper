# MLB Pitcher Strikeouts - Complete System Handoff

**Date:** 2026-01-14
**Status:** V1 Validated (67.27%), V2 Infrastructure Ready
**Next Action:** Populate features → Train V2 → Compare to V1

---

## System Overview

### What This System Does

Predicts MLB pitcher strikeout totals and generates betting recommendations (OVER/UNDER) by comparing predictions to sportsbook lines.

### Current Performance (V1)

| Metric | Value | Interpretation |
|--------|-------|----------------|
| **Hit Rate** | 67.27% | +14.89% over breakeven |
| **Total Picks** | 7,196 | 2 seasons of data |
| **MAE** | 1.46 K | Average error |
| **Implied ROI** | ~28.5% | Highly profitable |
| **Edge Correlation** | Strong | Higher edge = higher win rate |

---

## Architecture

### Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                  │
├─────────────────────────────────────────────────────────────────────┤
│  Ball Don't Lie API    │  MLB Stats API    │  The Odds API          │
│  (Pitcher/Batter Stats)│  (Schedule/Lineup)│  (Betting Lines)       │
└───────────┬────────────┴────────┬──────────┴──────────┬─────────────┘
            │                     │                     │
            ▼                     ▼                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    BIGQUERY TABLES                                   │
├─────────────────────────────────────────────────────────────────────┤
│  mlb_raw.bdl_pitcher_stats     │  mlb_raw.mlb_schedule              │
│  mlb_raw.bdl_batter_stats      │  mlb_raw.mlb_lineup_batters        │
│  mlb_raw.oddsa_pitcher_props   │  mlb_raw.oddsa_game_lines          │
└───────────┬────────────────────┴────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 ANALYTICS (Phase 3)                                  │
├─────────────────────────────────────────────────────────────────────┤
│  mlb_analytics.pitcher_game_summary (9,793 rows)                    │
│  - Rolling K averages (last 3, 5, 10 games)                         │
│  - Season stats (K/9, ERA, WHIP)                                    │
│  - Workload metrics (days rest, games last 30)                      │
│  - Data quality scores                                               │
└───────────┬─────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 PREDICTION MODELS                                    │
├──────────────────────────────┬──────────────────────────────────────┤
│  V1 (Champion)               │  V2 (Challenger) - TO BE TRAINED     │
│  - XGBoost                   │  - CatBoost                          │
│  - 19 features               │  - 29 features                       │
│  - 67.27% hit rate           │  - Target: 70%+                      │
└──────────────────────────────┴──────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 PREDICTIONS TABLE                                    │
├─────────────────────────────────────────────────────────────────────┤
│  mlb_predictions.pitcher_strikeouts                                 │
│  - prediction_id, game_date, pitcher_lookup                         │
│  - predicted_strikeouts, confidence, recommendation                 │
│  - strikeouts_line, edge, model_version                             │
│  - actual_strikeouts, is_correct (for grading)                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `predictions/mlb/pitcher_strikeouts_predictor.py` | V1 predictor (XGBoost, 19 features) |
| `predictions/mlb/pitcher_strikeouts_predictor_v2.py` | V2 predictor skeleton (CatBoost, 29 features) |
| `scrapers/bettingpros/bp_mlb_player_props.py` | Live odds scraper (market_id=285) |
| `data_processors/analytics/mlb/pitcher_game_summary_processor.py` | Feature processor |
| `scripts/mlb/historical_odds_backfill/` | Historical backfill scripts |

---

## V1 vs V2 Feature Comparison

### V1 Features (19) - Currently Used

```python
FEATURE_ORDER = [
    # Rolling Performance (5)
    'f00_k_avg_last_3',
    'f01_k_avg_last_5',
    'f02_k_avg_last_10',
    'f03_k_std_last_10',
    'f04_ip_avg_last_5',

    # Season Stats (5)
    'f05_season_k_per_9',
    'f06_season_era',
    'f07_season_whip',
    'f08_season_games',
    'f09_season_k_total',

    # Game Context (1)
    'f10_is_home',

    # Workload (5)
    'f20_days_rest',
    'f21_games_last_30_days',
    'f22_pitch_count_avg',
    'f23_season_ip_total',
    'f24_is_postseason',

    # Bottom-Up Model (3)
    'f25_bottom_up_k_expected',
    'f26_lineup_k_vs_hand',
    'f33_lineup_weak_spots',
]
```

### V2 Features (29) - To Be Trained

```python
V2_FEATURE_ORDER = [
    # Rolling Performance (5) - Same as V1
    'f00_k_avg_last_3',
    'f01_k_avg_last_5',
    'f02_k_avg_last_10',
    'f03_k_std_last_10',
    'f04_ip_avg_last_5',

    # Season Stats (5) - Same as V1
    'f05_season_k_per_9',
    'f06_season_era',
    'f07_season_whip',
    'f08_season_games',
    'f09_season_k_total',

    # Game Context (5) - EXPANDED (+3)
    'f10_is_home',
    'f11_home_away_k_diff',      # NEW: Home K/9 - Away K/9
    'f12_is_day_game',           # NEW: 1 if day game
    'f13_day_night_k_diff',      # NEW: Day K/9 - Night K/9
    'f24_is_postseason',

    # Matchup Context (5) - NEW (+5)
    'f14_vs_opponent_k_rate',    # NEW: K rate vs this team
    'f15_opponent_team_k_rate',  # NEW: Team strikeout rate
    'f16_opponent_obp',          # NEW: Team OBP
    'f17_ballpark_k_factor',     # NEW: Park K factor
    'f18_game_total_line',       # NEW: Vegas game total

    # Workload (4) - Same as V1
    'f20_days_rest',
    'f21_games_last_30_days',
    'f22_pitch_count_avg',
    'f23_season_ip_total',

    # Bottom-Up Model (5) - EXPANDED (+2)
    'f25_bottom_up_k_expected',
    'f26_lineup_k_vs_hand',
    'f27_platoon_advantage',     # NEW: Platoon matchup score
    'f33_lineup_weak_spots',
    'f34_matchup_edge',          # NEW: Composite edge score
]
```

---

## Next Session Tasks

### Task 1: Populate Missing Features in Analytics Table

The columns exist in `mlb_analytics.pitcher_game_summary` but have 0% data:

```sql
-- Check current state
SELECT
    COUNT(*) as total_rows,
    COUNTIF(home_away_k_diff IS NOT NULL AND home_away_k_diff != 0) as home_away_populated,
    COUNTIF(opponent_team_k_rate IS NOT NULL AND opponent_team_k_rate != 0) as opp_k_populated,
    COUNTIF(ballpark_k_factor IS NOT NULL AND ballpark_k_factor != 0) as ballpark_populated
FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date >= '2024-01-01';
```

#### 1.1 Populate home_away_k_diff

```sql
-- Calculate from existing home_k_per_9 and away_k_per_9 columns
UPDATE `nba-props-platform.mlb_analytics.pitcher_game_summary`
SET home_away_k_diff = COALESCE(home_k_per_9, 0) - COALESCE(away_k_per_9, 0)
WHERE game_date >= '2024-01-01'
  AND (home_k_per_9 IS NOT NULL OR away_k_per_9 IS NOT NULL);
```

#### 1.2 Populate day_night_k_diff

```sql
UPDATE `nba-props-platform.mlb_analytics.pitcher_game_summary`
SET day_night_k_diff = COALESCE(day_k_per_9, 0) - COALESCE(night_k_per_9, 0)
WHERE game_date >= '2024-01-01'
  AND (day_k_per_9 IS NOT NULL OR night_k_per_9 IS NOT NULL);
```

#### 1.3 Populate opponent_team_k_rate (requires join)

```sql
-- First, create a team K rate reference
CREATE OR REPLACE TABLE `nba-props-platform.mlb_reference.team_k_rates` AS
SELECT
    team_abbr,
    season_year,
    AVG(k_rate) as team_k_rate,
    AVG(obp) as team_obp
FROM (
    SELECT
        team_abbr,
        EXTRACT(YEAR FROM game_date) as season_year,
        SAFE_DIVIDE(SUM(strikeouts), SUM(at_bats)) as k_rate,
        -- Calculate OBP if available
        0.320 as obp  -- Default, update with real data
    FROM `nba-props-platform.mlb_raw.bdl_batter_stats`
    GROUP BY team_abbr, EXTRACT(YEAR FROM game_date)
)
GROUP BY team_abbr, season_year;

-- Then update pitcher_game_summary
UPDATE `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
SET opponent_team_k_rate = tkr.team_k_rate,
    opponent_obp = tkr.team_obp
FROM `nba-props-platform.mlb_reference.team_k_rates` tkr
WHERE pgs.opponent_team_abbr = tkr.team_abbr
  AND EXTRACT(YEAR FROM pgs.game_date) = tkr.season_year;
```

#### 1.4 Populate ballpark_k_factor

```sql
-- Create ballpark factors reference (example values)
CREATE OR REPLACE TABLE `nba-props-platform.mlb_reference.ballpark_factors` AS
SELECT * FROM UNNEST([
    STRUCT('COL' as venue_abbr, 0.92 as k_factor),  -- Coors Field (pitcher friendly)
    STRUCT('SD' as venue_abbr, 1.08 as k_factor),   -- Petco Park (pitcher park)
    STRUCT('NYY' as venue_abbr, 1.02 as k_factor),  -- Yankee Stadium
    STRUCT('BOS' as venue_abbr, 0.98 as k_factor),  -- Fenway Park
    -- Add all 30 ballparks...
]);

-- Update with venue-based factors
UPDATE `nba-props-platform.mlb_analytics.pitcher_game_summary` pgs
SET ballpark_k_factor = COALESCE(bp.k_factor, 1.0)
FROM `nba-props-platform.mlb_reference.ballpark_factors` bp
WHERE pgs.venue = bp.venue_abbr;
```

---

### Task 2: Extract Training Data

#### Data Split Strategy

| Split | Date Range | Purpose | ~Records |
|-------|------------|---------|----------|
| **Train** | 2024-04-01 to 2025-05-31 | Model fitting | ~5,500 |
| **Validation** | 2025-06-01 to 2025-06-30 | Hyperparameter tuning | ~700 |
| **Test** | 2025-07-01 to 2025-09-28 | Final evaluation (hit rate) | ~2,000 |

**Important:** The test set (Jul-Sep 2025) showed performance decline (56-59% hit rate vs 70%+ earlier). V2 should specifically address this.

#### Extract Training Data Query

```sql
-- Export training data to CSV or direct to Python
SELECT
    player_lookup,
    game_date,

    -- Target variable
    strikeouts as actual_strikeouts,

    -- V1 Features (for comparison)
    k_avg_last_3 as f00_k_avg_last_3,
    k_avg_last_5 as f01_k_avg_last_5,
    k_avg_last_10 as f02_k_avg_last_10,
    k_std_last_10 as f03_k_std_last_10,
    ip_avg_last_5 as f04_ip_avg_last_5,

    season_k_per_9 as f05_season_k_per_9,
    COALESCE(era_rolling_10, season_era) as f06_season_era,
    COALESCE(whip_rolling_10, season_whip) as f07_season_whip,
    season_games_started as f08_season_games,
    season_strikeouts as f09_season_k_total,

    CASE WHEN is_home THEN 1.0 ELSE 0.0 END as f10_is_home,

    days_rest as f20_days_rest,
    games_last_30_days as f21_games_last_30_days,
    pitch_count_avg_last_5 as f22_pitch_count_avg,
    season_innings as f23_season_ip_total,
    CASE WHEN is_postseason THEN 1.0 ELSE 0.0 END as f24_is_postseason,

    -- V2 NEW Features
    home_away_k_diff as f11_home_away_k_diff,
    CASE WHEN is_day_game THEN 1.0 ELSE 0.0 END as f12_is_day_game,
    day_night_k_diff as f13_day_night_k_diff,
    vs_opponent_k_per_9 as f14_vs_opponent_k_rate,
    opponent_team_k_rate as f15_opponent_team_k_rate,
    opponent_obp as f16_opponent_obp,
    ballpark_k_factor as f17_ballpark_k_factor,
    game_total_line as f18_game_total_line,

    -- Bottom-up features (may need join with lineup_k_analysis)
    5.0 as f25_bottom_up_k_expected,  -- Default, update from lineup analysis
    0.22 as f26_lineup_k_vs_hand,      -- Default
    0.0 as f27_platoon_advantage,
    2 as f33_lineup_weak_spots,
    0.0 as f34_matchup_edge,

    -- Metadata
    data_completeness_score,
    rolling_stats_games

FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
WHERE game_date BETWEEN '2024-04-01' AND '2025-09-28'
  AND strikeouts IS NOT NULL
  AND rolling_stats_games >= 3
ORDER BY game_date;
```

---

### Task 3: Train V2 Model

#### Training Script Location

Create: `scripts/mlb/training/train_pitcher_strikeouts_v2.py`

#### Training Code

```python
#!/usr/bin/env python3
"""
Train MLB Pitcher Strikeouts V2 Model (CatBoost)

Usage:
    python scripts/mlb/training/train_pitcher_strikeouts_v2.py
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime
from catboost import CatBoostRegressor, Pool
from sklearn.metrics import mean_absolute_error
from google.cloud import bigquery, storage

# Feature configuration
V2_FEATURES = [
    'f00_k_avg_last_3', 'f01_k_avg_last_5', 'f02_k_avg_last_10',
    'f03_k_std_last_10', 'f04_ip_avg_last_5',
    'f05_season_k_per_9', 'f06_season_era', 'f07_season_whip',
    'f08_season_games', 'f09_season_k_total',
    'f10_is_home', 'f11_home_away_k_diff', 'f12_is_day_game',
    'f13_day_night_k_diff', 'f24_is_postseason',
    'f14_vs_opponent_k_rate', 'f15_opponent_team_k_rate',
    'f16_opponent_obp', 'f17_ballpark_k_factor', 'f18_game_total_line',
    'f20_days_rest', 'f21_games_last_30_days',
    'f22_pitch_count_avg', 'f23_season_ip_total',
    'f25_bottom_up_k_expected', 'f26_lineup_k_vs_hand',
    'f27_platoon_advantage', 'f33_lineup_weak_spots', 'f34_matchup_edge',
]

TARGET = 'actual_strikeouts'

def load_data():
    """Load training data from BigQuery"""
    client = bigquery.Client(project='nba-props-platform')

    query = """
    SELECT * FROM `nba-props-platform.mlb_analytics.pitcher_game_summary`
    WHERE game_date BETWEEN '2024-04-01' AND '2025-09-28'
      AND strikeouts IS NOT NULL
      AND rolling_stats_games >= 3
    """

    df = client.query(query).to_dataframe()
    print(f"Loaded {len(df)} rows")
    return df

def split_data(df):
    """Split into train/validation/test"""
    train = df[df['game_date'] < '2025-06-01']
    val = df[(df['game_date'] >= '2025-06-01') & (df['game_date'] < '2025-07-01')]
    test = df[df['game_date'] >= '2025-07-01']

    print(f"Train: {len(train)}, Val: {len(val)}, Test: {len(test)}")
    return train, val, test

def prepare_features(df):
    """Extract feature matrix and target"""
    # Map column names to feature names
    feature_mapping = {
        'k_avg_last_3': 'f00_k_avg_last_3',
        'k_avg_last_5': 'f01_k_avg_last_5',
        'k_avg_last_10': 'f02_k_avg_last_10',
        'k_std_last_10': 'f03_k_std_last_10',
        'ip_avg_last_5': 'f04_ip_avg_last_5',
        'season_k_per_9': 'f05_season_k_per_9',
        # ... add all mappings
    }

    X = df[V2_FEATURES].fillna(0)
    y = df['strikeouts']
    return X, y

def train_model(X_train, y_train, X_val, y_val):
    """Train CatBoost model"""
    model = CatBoostRegressor(
        iterations=1000,
        learning_rate=0.05,
        depth=6,
        l2_leaf_reg=3,
        early_stopping_rounds=50,
        random_seed=42,
        verbose=100,
    )

    model.fit(
        X_train, y_train,
        eval_set=(X_val, y_val),
        use_best_model=True,
    )

    return model

def evaluate_model(model, X_test, y_test):
    """Evaluate on test set"""
    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)

    print(f"\n=== Test Set Evaluation ===")
    print(f"MAE: {mae:.3f}")
    print(f"Test samples: {len(y_test)}")

    return mae, predictions

def calculate_hit_rate(predictions, actuals, lines):
    """Calculate hit rate against betting lines"""
    results = []
    for pred, actual, line in zip(predictions, actuals, lines):
        if line is None or pd.isna(line):
            continue

        edge = pred - line
        if abs(edge) < 0.5:  # PASS threshold
            continue

        recommended = 'OVER' if edge > 0 else 'UNDER'
        actual_result = 'OVER' if actual > line else 'UNDER' if actual < line else 'PUSH'

        if actual_result == 'PUSH':
            continue

        is_correct = recommended == actual_result
        results.append({
            'predicted': pred,
            'actual': actual,
            'line': line,
            'edge': edge,
            'recommended': recommended,
            'is_correct': is_correct
        })

    if not results:
        return 0.0, 0

    wins = sum(1 for r in results if r['is_correct'])
    total = len(results)
    hit_rate = wins / total * 100

    print(f"\n=== Hit Rate Analysis ===")
    print(f"Total picks: {total}")
    print(f"Wins: {wins}")
    print(f"Hit rate: {hit_rate:.2f}%")

    return hit_rate, total

def save_model(model, mae, hit_rate):
    """Save model to GCS"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    model_name = f'pitcher_strikeouts_v2_{timestamp}'

    # Save locally first
    local_path = f'/tmp/{model_name}.cbm'
    model.save_model(local_path)

    # Upload to GCS
    client = storage.Client()
    bucket = client.bucket('nba-scraped-data')
    blob = bucket.blob(f'ml-models/mlb/{model_name}.cbm')
    blob.upload_from_filename(local_path)

    # Save metadata
    metadata = {
        'model_id': model_name,
        'model_version': 'v2',
        'algorithm': 'catboost',
        'feature_count': len(V2_FEATURES),
        'features': V2_FEATURES,
        'test_mae': mae,
        'test_hit_rate': hit_rate,
        'trained_at': timestamp,
    }

    metadata_path = f'/tmp/{model_name}_metadata.json'
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    metadata_blob = bucket.blob(f'ml-models/mlb/{model_name}_metadata.json')
    metadata_blob.upload_from_filename(metadata_path)

    print(f"\nModel saved: gs://nba-scraped-data/ml-models/mlb/{model_name}.cbm")
    return model_name

def main():
    # Load and split data
    df = load_data()
    train, val, test = split_data(df)

    # Prepare features
    X_train, y_train = prepare_features(train)
    X_val, y_val = prepare_features(val)
    X_test, y_test = prepare_features(test)

    # Train model
    print("\n=== Training CatBoost V2 ===")
    model = train_model(X_train, y_train, X_val, y_val)

    # Evaluate
    mae, predictions = evaluate_model(model, X_test, y_test)

    # Calculate hit rate against lines
    lines = test['strikeouts_line'].values
    hit_rate, total_picks = calculate_hit_rate(predictions, y_test.values, lines)

    # Save model
    model_name = save_model(model, mae, hit_rate)

    print(f"\n=== Summary ===")
    print(f"V2 Model: {model_name}")
    print(f"MAE: {mae:.3f} (V1 was 1.46)")
    print(f"Hit Rate: {hit_rate:.2f}% (V1 was 67.27%)")

if __name__ == '__main__':
    main()
```

---

### Task 4: Measure Hit Rate on Historical Data

#### Method 1: Backfill V2 Predictions to BigQuery

```python
# After training, generate predictions for all historical data
# and compare to V1

def backfill_v2_predictions(model, df):
    """Generate V2 predictions for all historical games"""
    X, _ = prepare_features(df)
    predictions = model.predict(X)

    results = []
    for i, row in df.iterrows():
        line = row.get('strikeouts_line')
        actual = row.get('strikeouts')
        pred = predictions[i]

        if line is None or pd.isna(line):
            continue

        edge = pred - line
        if abs(edge) < 1.0:  # V2 uses 1.0 threshold
            recommendation = 'PASS'
        elif edge > 0:
            recommendation = 'OVER'
        else:
            recommendation = 'UNDER'

        # Determine correctness
        if actual > line:
            actual_result = 'OVER'
        elif actual < line:
            actual_result = 'UNDER'
        else:
            actual_result = 'PUSH'

        is_correct = (recommendation == actual_result) if recommendation != 'PASS' else None

        results.append({
            'game_date': row['game_date'],
            'player_lookup': row['player_lookup'],
            'predicted_strikeouts': round(pred, 2),
            'actual_strikeouts': actual,
            'strikeouts_line': line,
            'edge': round(edge, 2),
            'recommendation': recommendation,
            'is_correct': is_correct,
            'model_version': 'v2',
        })

    return pd.DataFrame(results)
```

#### Method 2: Compare V1 vs V2 Hit Rates

```sql
-- After backfilling V2 predictions, compare to V1
WITH v1_stats AS (
    SELECT
        'v1' as model_version,
        COUNT(*) as total_picks,
        COUNTIF(is_correct = TRUE) as wins,
        ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE model_version = 'v1' OR model_version IS NULL
      AND is_correct IS NOT NULL
),
v2_stats AS (
    SELECT
        'v2' as model_version,
        COUNT(*) as total_picks,
        COUNTIF(is_correct = TRUE) as wins,
        ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate
    FROM `nba-props-platform.mlb_predictions.pitcher_strikeouts`
    WHERE model_version = 'v2'
      AND is_correct IS NOT NULL
)
SELECT * FROM v1_stats
UNION ALL
SELECT * FROM v2_stats;
```

---

## Hit Rate Analysis by Period

### Performance Breakdown (V1)

| Period | Picks | Win Rate | Notes |
|--------|-------|----------|-------|
| 2024-04 to 2024-09 | ~3,000 | 70-73% | Strong performance |
| 2025-03 to 2025-05 | ~1,500 | 70-75% | Strong performance |
| **2025-06 to 2025-08** | ~2,000 | **56-59%** | **Performance decline** |
| 2025-09 | ~600 | 63% | Partial recovery |

**Key Insight:** V2 should specifically address the Jul-Aug 2025 decline. The additional features (opponent K rate, ballpark factors) may help.

### Edge Analysis (V1)

| Edge Bucket | Picks | Win Rate |
|-------------|-------|----------|
| 2.5+ | 129 | 92.2% |
| 2.0-2.5 | 247 | 89.9% |
| 1.5-2.0 | 253 | 81.4% |
| 1.0-1.5 | 558 | 79.2% |
| 0.5-1.0 | 977 | 68.2% |
| <0.5 | 1,357 | 52.5% |

**V2 Strategy:** Use 1.0 edge minimum (vs 0.5 for V1) to filter out lower-confidence picks.

---

## Champion-Challenger Promotion Criteria

V2 becomes champion if (after 100+ picks over 7+ days):

| Metric | V1 Baseline | V2 Threshold |
|--------|-------------|--------------|
| Hit Rate | 67.27% | >= 67.27% |
| MAE | 1.46 | <= 1.46 |
| High Edge Win Rate | 85% (edge > 1.5) | >= 85% |
| Sample Size | - | >= 100 picks |

---

## Quick Reference Commands

### Check Feature Population
```bash
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT
    COUNT(*) as total,
    COUNTIF(home_away_k_diff != 0) as home_away,
    COUNTIF(opponent_team_k_rate != 0) as opp_k,
    COUNTIF(ballpark_k_factor != 0) as ballpark
FROM mlb_analytics.pitcher_game_summary
WHERE game_date >= \"2024-01-01\"
'''
for row in client.query(query):
    print(f'Total: {row.total}, Home/Away: {row.home_away}, Opp K: {row.opp_k}, Ballpark: {row.ballpark}')
"
```

### Train V2 Model
```bash
python scripts/mlb/training/train_pitcher_strikeouts_v2.py
```

### Compare V1 vs V2
```bash
python3 -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
query = '''
SELECT
    COALESCE(model_version, \"v1\") as version,
    COUNT(*) as picks,
    COUNTIF(is_correct = TRUE) as wins,
    ROUND(SAFE_DIVIDE(COUNTIF(is_correct = TRUE), COUNT(*)) * 100, 2) as hit_rate
FROM mlb_predictions.pitcher_strikeouts
WHERE is_correct IS NOT NULL
GROUP BY 1
'''
for row in client.query(query):
    print(f'{row.version}: {row.hit_rate}% ({row.wins}/{row.picks})')
"
```

### Test V2 Predictor
```bash
python predictions/mlb/pitcher_strikeouts_predictor_v2.py --debug
```

---

## Summary

### Current Status
- **V1:** Validated at 67.27% hit rate, profitable
- **V2:** Infrastructure ready, needs features populated and model trained

### Next Session Priorities

1. **Populate missing features** (SQL updates for ~6 columns)
2. **Export training data** (train: 2024-04 to 2025-05, test: 2025-07+)
3. **Train CatBoost V2** with 29 features
4. **Backfill V2 predictions** for historical comparison
5. **Compare V1 vs V2** hit rates

### Files to Reference
- `predictions/mlb/pitcher_strikeouts_predictor_v2.py` - V2 skeleton
- `docs/.../PROJECT-ROADMAP.md` - Full roadmap
- `docs/.../MODEL-UPGRADE-STRATEGY.md` - Strategy details
