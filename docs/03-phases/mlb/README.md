# MLB Prediction Platform Documentation

## Overview

The MLB Prediction Platform is a comprehensive data pipeline and machine learning system for predicting pitcher strikeout totals. It shares infrastructure with the NBA platform but implements MLB-specific data sources, analytics processors, and prediction models.

**Primary Focus:** Pitcher Strikeouts Over/Under predictions

**Current Champion Model:** V1.6 Rolling (60% win rate in shadow testing, deployed 2026-01-15)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Data Sources](#data-sources)
3. [Data Pipeline](#data-pipeline)
4. [Prediction Models](#prediction-models)
5. [Shadow Mode Testing](#shadow-mode-testing)
6. [Red Flag System](#red-flag-system)
7. [Key Differences from NBA Platform](#key-differences-from-nba-platform)
8. [Configuration](#configuration)
9. [Deployment](#deployment)
10. [Directory Structure](#directory-structure)

---

## Architecture Overview

```
                                    MLB Platform Architecture

    +------------------+     +------------------+     +------------------+
    |   DATA SOURCES   |     |   RAW STORAGE    |     |    ANALYTICS     |
    +------------------+     +------------------+     +------------------+
    |                  |     |                  |     |                  |
    | Ball Don't Lie   |---->| mlb_raw.*        |---->| mlb_analytics.*  |
    | (Stats, Injuries)|     | bdl_pitcher_stats|     | pitcher_game_    |
    |                  |     | bdl_injuries     |     |   summary        |
    | MLB Stats API    |---->| mlb_schedule     |---->| pitcher_rolling_ |
    | (Schedule,       |     | mlb_lineups      |     |   statcast       |
    |  Lineups, Feed)  |     | mlb_game_feed    |     | batter_game_     |
    |                  |     |                  |     |   summary        |
    | The Odds API     |---->| oddsa_*          |     |                  |
    | (Props, Lines)   |     | pitcher_props    |     +--------+---------+
    |                  |     | batter_props     |              |
    | Baseball Savant  |---->| statcast_*       |              |
    | (Statcast)       |     |                  |              v
    |                  |     |                  |     +------------------+
    | FanGraphs        |---->| fangraphs_*      |     |   PREDICTIONS    |
    | (Season Stats)   |     |                  |     +------------------+
    |                  |     |                  |     |                  |
    | External Sources |---->| ballpark_factors |     | V1.4 Baseline    |
    | (Weather, Umpire)|     | umpire_stats     |     | V1.6 Rolling     |
    |                  |     | weather          |     | Ensemble V1      |
    +------------------+     +------------------+     +--------+---------+
                                                               |
                                                               v
                                                      +------------------+
                                                      |    OUTPUTS       |
                                                      +------------------+
                                                      | mlb_predictions. |
                                                      |   pitcher_       |
                                                      |   strikeouts     |
                                                      | shadow_mode_     |
                                                      |   predictions    |
                                                      +------------------+
```

---

## Data Sources

The platform collects data from 6 primary sources with 28+ individual scrapers.

### 1. Ball Don't Lie API (13 scrapers)

**Path:** `scrapers/mlb/balldontlie/`

Primary source for game statistics and player data.

| Scraper | Description | Key Fields |
|---------|-------------|------------|
| `mlb_pitcher_stats` | Per-game pitching stats | `strikeouts`, `innings_pitched`, `pitch_count`, `earned_runs` |
| `mlb_batter_stats` | Per-game batting stats | `strikeouts`, `hits`, `at_bats` |
| `mlb_games` | Game results | `home_score`, `away_score`, `status` |
| `mlb_box_scores` | Detailed box scores | Full game stats |
| `mlb_live_box_scores` | In-progress games | Real-time stats |
| `mlb_active_players` | Active roster | Player IDs, positions |
| `mlb_injuries` | Injury reports | IL status, injury type |
| `mlb_player_splits` | Platoon splits | vs LHP/RHP performance |
| `mlb_player_versus` | Head-to-head history | Pitcher vs batter matchups |
| `mlb_season_stats` | Season totals | Cumulative stats |
| `mlb_standings` | Team standings | W-L records |
| `mlb_team_season_stats` | Team aggregate stats | Team K rate |
| `mlb_teams` | Team information | Team metadata |

### 2. MLB Stats API (3 scrapers)

**Path:** `scrapers/mlb/mlbstatsapi/`

Official MLB API for schedule and lineup data.

| Scraper | Description | Key Fields |
|---------|-------------|------------|
| `mlb_schedule` | Daily game schedule | `game_date`, `game_time`, `venue` |
| `mlb_lineups` | Starting lineups | Starting pitchers, batting order |
| `mlb_game_feed` | Live game feed | Play-by-play, pitch data |

### 3. The Odds API (8 scrapers)

**Path:** `scrapers/mlb/oddsapi/`

Betting lines and props from multiple bookmakers.

| Scraper | Description | Key Fields |
|---------|-------------|------------|
| `mlb_events` | Today's events | Event IDs |
| `mlb_events_his` | Historical events | Past event data |
| `mlb_game_lines` | Moneyline/Spread/Total | Game odds |
| `mlb_game_lines_his` | Historical game lines | Past odds |
| `mlb_pitcher_props` | **Pitcher prop odds** | `strikeouts_line`, `over_price`, `under_price` |
| `mlb_pitcher_props_his` | Historical pitcher props | Past pitcher lines |
| `mlb_batter_props` | Batter prop odds | Hits, HRs, etc. |
| `mlb_batter_props_his` | Historical batter props | Past batter lines |

### 4. Baseball Savant / Statcast (1 scraper)

**Path:** `scrapers/mlb/statcast/`

Advanced pitch-level metrics via `pybaseball`.

| Scraper | Description | Key Fields |
|---------|-------------|------------|
| `mlb_statcast_pitcher` | Pitch-level data | `swstr_pct`, `velocity`, `spin_rate`, `chase_rate` |

**Critical Metrics for K Predictions:**
- `swstr_pct` (Swinging Strike %): Highly predictive of strikeout rate
- `chase_rate`: How often batters chase outside pitches
- `fb_velocity`: Fastball velocity trends

### 5. FanGraphs (via BettingPros)

**Path:** `scrapers/mlb/balldontlie/` (integrated)

Season-level advanced metrics.

| Metric | Description |
|--------|-------------|
| `swstr_pct` | Season swinging strike percentage |
| `csw_pct` | Called Strike + Whiff percentage |
| `o_swing_pct` | Chase rate (swings outside zone) |
| `k_pct` | Strikeout percentage |

### 6. External Data Sources (3 scrapers)

**Path:** `scrapers/mlb/external/`

Environmental and contextual factors.

| Scraper | Description | Key Fields |
|---------|-------------|------------|
| `mlb_ballpark_factors` | Park effects on K rate | `k_factor` (>100 = pitcher-friendly) |
| `mlb_umpire_stats` | Umpire tendencies | K zone size, call rates |
| `mlb_weather` | Game-day weather | Temperature, wind, humidity |

**High K Parks (k_factor > 105):**
- Petco Park (San Diego)
- Oracle Park (San Francisco)
- Citi Field (New York Mets)

**Low K Parks (k_factor < 95):**
- Coors Field (Colorado)
- Great American Ball Park (Cincinnati)

---

## Data Pipeline

### Phase 1: Data Collection (Scrapers)

```
scrapers/mlb/registry.py      # Central registry for all MLB scrapers
  |
  +-- get_scraper_instance()  # Dynamic scraper loading
  +-- PRIORITY_SCRAPERS       # Minimum viable pipeline scrapers
```

**Priority Scrapers for Daily Operations:**
1. `mlb_schedule` - Game schedule
2. `mlb_lineups` - Starting pitchers
3. `mlb_pitcher_props` - Betting lines
4. `mlb_game_feed` - Live data
5. `mlb_games` - Results

### Phase 2: Raw Data Storage

All scraped data lands in BigQuery dataset `mlb_raw`:
- `bdl_pitcher_stats`
- `oddsa_pitcher_props`
- `fangraphs_pitcher_season_stats`
- `bp_pitcher_props` (BettingPros)

### Phase 3: Analytics Processing

**Path:** `data_processors/analytics/mlb/`

**Main Service:** `main_mlb_analytics_service.py`

Endpoints:
- `POST /process` - Pub/Sub trigger
- `POST /process-date` - Process specific date
- `POST /process-date-range` - Backfill date range

**Processors:**

#### Pitcher Game Summary Processor

**File:** `pitcher_game_summary_processor.py`

Transforms raw stats into ML features with rolling averages.

**Key Features Generated:**
```
Rolling Stats:
  - k_avg_last_3, k_avg_last_5, k_avg_last_10
  - k_std_last_10 (strikeout volatility)
  - ip_avg_last_5, ip_avg_last_10
  - k_per_9_rolling_10
  - era_rolling_10, whip_rolling_10

Workload Features:
  - days_rest
  - games_last_30_days
  - pitch_count_avg_last_5

Season Features:
  - season_strikeouts, season_innings
  - season_k_per_9
  - season_games_started

Context Features:
  - is_home, is_postseason
  - opponent_team_k_rate
  - ballpark_k_factor
```

---

## Prediction Models

**Path:** `predictions/mlb/`

### Model Architecture

```
predictions/mlb/
  |
  +-- base_predictor.py               # Abstract base class
  +-- pitcher_strikeouts_predictor.py # Main predictor (legacy)
  +-- config.py                       # Configuration
  +-- worker.py                       # Flask service
  +-- shadow_mode_runner.py           # A/B testing
  |
  +-- prediction_systems/
        +-- v1_baseline_predictor.py  # V1.4 (25 features)
        +-- v1_6_rolling_predictor.py # V1.6 (35 features)
        +-- ensemble_v1.py            # Weighted ensemble
```

### V1.4 Baseline Model (25 features)

**File:** `prediction_systems/v1_baseline_predictor.py`

Core features for strikeout prediction:

```python
# Rolling Stats (f00-f04)
f00_k_avg_last_3, f01_k_avg_last_5, f02_k_avg_last_10,
f03_k_std_last_10, f04_ip_avg_last_5

# Season Stats (f05-f09)
f05_season_k_per_9, f06_season_era, f07_season_whip,
f08_season_games, f09_season_k_total

# Context (f10)
f10_is_home

# Opponent/Ballpark (f15-f18)
f15_opponent_team_k_rate, f16_ballpark_k_factor,
f17_month_of_season, f18_days_into_season

# Workload (f20-f24)
f20_days_rest, f21_games_last_30_days, f22_pitch_count_avg,
f23_season_ip_total, f24_is_postseason

# Bottom-up (f25-f28, f33)
f25_bottom_up_k_expected, f26_lineup_k_vs_hand,
f27_avg_k_vs_opponent, f28_games_vs_opponent,
f33_lineup_weak_spots
```

### V1.6 Rolling Model (35 features) - CHAMPION

**File:** `prediction_systems/v1_6_rolling_predictor.py`

Extends V1.4 with 10 additional features:

```python
# Season Swing Metrics (f19)
f19_season_swstr_pct, f19b_season_csw_pct, f19c_season_chase_pct

# Line-Relative Features (f30-f32)
f30_k_avg_vs_line    # Recent K avg minus betting line
f31_projected_vs_line # BettingPros projection minus line
f32_line_level        # The betting line itself

# BettingPros Features (f40-f44)
f40_bp_projection     # BettingPros K projection
f41_projection_diff   # Projection minus line
f42_perf_last_5_pct   # Last 5 games OVER %
f43_perf_last_10_pct  # Last 10 games OVER %
f44_over_implied_prob # Implied probability from odds

# Rolling Statcast (f50-f53)
f50_swstr_pct_last_3  # Per-game SwStr% (3-game avg)
f51_fb_velocity_last_3 # Fastball velocity trend
f52_swstr_trend       # Recent vs season SwStr%
f53_velocity_change   # Velocity change indicator
```

### Model Comparison

| Aspect | V1.4 Baseline | V1.6 Rolling |
|--------|---------------|--------------|
| Features | 25 | 35 |
| Data Sources | BDL, Odds API | + Statcast, BettingPros |
| Performance | ~55% | ~60% (shadow testing) |
| Model Type | XGBoost Regressor | XGBoost Regressor |
| Status | Challenger | **Champion** |

### Prediction Flow

```python
# 1. Load model from GCS
model_path = 'gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_*.json'

# 2. Load features from BigQuery
features = load_pitcher_features(pitcher_lookup, game_date)

# 3. Prepare feature vector
feature_vector = prepare_features(features)

# 4. Generate prediction
prediction = model.predict(feature_vector)

# 5. Apply red flags
red_flags = check_red_flags(features, recommendation)

# 6. Generate recommendation
recommendation = generate_recommendation(prediction, line, confidence)
```

### Recommendation Logic

```python
# Configuration (from config.py)
min_edge = 0.5       # Minimum edge to make a recommendation
min_confidence = 60.0 # Minimum confidence threshold

# Logic
if confidence < min_confidence:
    return 'PASS'

edge = predicted_strikeouts - betting_line

if edge >= min_edge:
    return 'OVER'
elif edge <= -min_edge:
    return 'UNDER'
else:
    return 'PASS'
```

---

## Shadow Mode Testing

**File:** `predictions/mlb/shadow_mode_runner.py`

Shadow mode enables champion-challenger testing by running multiple models in parallel.

### Purpose

- Compare model performance without affecting production
- Gather head-to-head statistics
- Validate new models before promotion

### How It Works

```python
# Run shadow mode for a date
python predictions/mlb/shadow_mode_runner.py --date 2025-06-15

# Or via API
POST /execute-shadow-mode
{"game_date": "2025-06-15", "dry_run": false}
```

### Output

Results are written to `mlb_predictions.shadow_mode_predictions`:

```sql
SELECT
    pitcher_lookup,
    v1_4_predicted, v1_4_recommendation,
    v1_6_predicted, v1_6_recommendation,
    recommendation_agrees,
    prediction_diff
FROM mlb_predictions.shadow_mode_predictions
WHERE game_date = '2025-06-15'
```

### Key Metrics Tracked

- **Prediction Difference:** V1.6 - V1.4 predictions
- **Recommendation Agreement:** When both recommend same direction
- **Edge Distribution:** Spread of edge values
- **Confidence Comparison:** Average confidence per model

---

## Red Flag System

The red flag system prevents betting on unreliable situations.

**File:** `predictions/mlb/config.py` (RedFlagConfig)

### Hard Skip Rules (No Bet)

| Rule | Threshold | Reason |
|------|-----------|--------|
| Currently on IL | - | Pitcher shouldn't have props |
| First start of season | `season_games = 0` | No historical data |
| Low IP average | `ip_avg < 4.0` | Likely bullpen/opener |
| MLB debut | `career_starts < 2` | Insufficient sample size |

### Soft Reduce Rules (Confidence Multiplier)

| Rule | Threshold | Multiplier | Applies To |
|------|-----------|------------|------------|
| Early season | `starts < 3` | 0.7x | All |
| High K variance | `k_std > 4` | 0.4x OVER / 1.1x UNDER | Directional |
| Short rest | `days < 4` | 0.7x | OVER only |
| High workload | `games_30d > 6` | 0.85x | OVER only |
| Elite SwStr% | `> 12%` | 1.1x OVER / 0.8x UNDER | Directional |
| Low SwStr% | `< 8%` | 0.85x OVER / 1.05x UNDER | Directional |
| Hot streak | `trend > +3%` | 1.08x OVER / 0.92x UNDER | Directional |
| Cold streak | `trend < -3%` | 0.92x OVER / 1.05x UNDER | Directional |

### Backtest Findings

- **High K variance (k_std > 4):** 34.4% OVER hit rate vs 62.5% UNDER
- **Elite SwStr% (> 12%):** 55.8% OVER vs 41.1% UNDER
- **Hot streak (+3% SwStr% trend):** 54.6% OVER hit rate

---

## Key Differences from NBA Platform

| Aspect | NBA Platform | MLB Platform |
|--------|--------------|--------------|
| Primary Prediction | Player Points/Rebounds/Assists | Pitcher Strikeouts |
| Game Frequency | Daily (Oct-Jun) | Daily (Apr-Oct) |
| Data Sources | NBA Stats API, ESPN | Ball Don't Lie, MLB Stats API, Statcast |
| Key Metrics | Usage%, Minutes, Pace | SwStr%, K/9, IP Average |
| Variance Factor | Minutes (DNP risk) | IP/Pitch Count (early hook) |
| Rest Days | Back-to-backs | 4-5 day rotation |
| Model Features | ~40 | 25-35 |
| Betting Lines | ESPN, DraftKings | The Odds API |
| Leading Indicators | Pace, Opponent DRTG | SwStr%, Velocity Trends |

### MLB-Specific Challenges

1. **Pitching Rotation:** Unlike NBA where all players can play, pitchers follow strict schedules
2. **Bullpen Risk:** Managers may pull starters early regardless of performance
3. **Weather Impact:** Outdoor games affected by temperature, wind, humidity
4. **Park Effects:** Significant variance in K rates by venue
5. **Platoon Splits:** LHP vs RHP significantly affects outcomes

---

## Configuration

### Environment Variables

```bash
# GCP Configuration
GCP_PROJECT_ID=nba-props-platform

# Model Paths
MLB_V1_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_4features_*.json
MLB_V1_6_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_*.json

# Active Systems (comma-separated)
MLB_ACTIVE_SYSTEMS=v1_baseline,v1_6_rolling  # or: ensemble_v1

# Prediction Thresholds
MLB_MIN_EDGE=0.5
MLB_MIN_CONFIDENCE=60.0

# Red Flag Thresholds
MLB_MIN_IP_AVG=4.0
MLB_MIN_CAREER_STARTS=2
MLB_HIGH_VARIANCE_K_STD=4.0
MLB_ELITE_SWSTR_PCT=0.12
MLB_LOW_SWSTR_PCT=0.08

# Cache Configuration
MLB_IL_CACHE_TTL_HOURS=3

# Alert Configuration
BACKFILL_MODE=false
```

### Configuration Classes

**File:** `predictions/mlb/config.py`

```python
from predictions.mlb.config import get_config

config = get_config()

# Access sub-configs
config.prediction.min_edge      # 0.5
config.red_flags.min_ip_avg     # 4.0
config.systems.active_systems   # 'v1_baseline'
config.cache.il_cache_ttl_hours # 3
```

---

## Deployment

### Cloud Run Services

| Service | Purpose | Trigger |
|---------|---------|---------|
| `mlb-prediction-worker` | Generate predictions | Pub/Sub, HTTP |
| `mlb-analytics-service` | Process raw data | Pub/Sub |
| `mlb-scraper-service` | Run scrapers | Cloud Scheduler |

### Docker Build

```bash
# Build from repository root
docker build -f predictions/mlb/Dockerfile -t mlb-prediction-worker .

# Deploy to Cloud Run
gcloud run deploy mlb-prediction-worker \
  --image gcr.io/nba-props-platform/mlb-prediction-worker \
  --platform managed \
  --region us-central1 \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform,MLB_ACTIVE_SYSTEMS=v1_6_rolling"
```

### Worker Endpoints

**File:** `predictions/mlb/worker.py`

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Service info |
| `/health` | GET | Liveness check |
| `/ready` | GET | Readiness check |
| `/health/deep` | GET | Deep health check |
| `/predict` | POST | Single pitcher prediction |
| `/predict-batch` | POST | All pitchers for date |
| `/execute-shadow-mode` | POST | Run shadow comparison |
| `/pubsub` | POST | Pub/Sub handler |

### Example API Calls

```bash
# Single prediction
curl -X POST http://localhost:8080/predict \
  -H "Content-Type: application/json" \
  -d '{"pitcher_lookup": "gerrit_cole", "game_date": "2025-06-15", "strikeouts_line": 6.5}'

# Batch prediction
curl -X POST http://localhost:8080/predict-batch \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-06-15", "write_to_bigquery": true}'

# Shadow mode
curl -X POST http://localhost:8080/execute-shadow-mode \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2025-06-15"}'
```

---

## Directory Structure

```
nba-stats-scraper/
|
+-- scrapers/mlb/
|     +-- __init__.py              # Package exports
|     +-- registry.py              # Scraper registry
|     +-- balldontlie/             # Ball Don't Lie scrapers (13)
|     +-- mlbstatsapi/             # MLB Stats API scrapers (3)
|     +-- oddsapi/                 # The Odds API scrapers (8)
|     +-- statcast/                # Baseball Savant scrapers (1)
|     +-- external/                # External data scrapers (3)
|
+-- data_processors/analytics/mlb/
|     +-- __init__.py
|     +-- main_mlb_analytics_service.py
|     +-- pitcher_game_summary_processor.py
|     +-- batter_game_summary_processor.py
|
+-- predictions/mlb/
|     +-- __init__.py
|     +-- base_predictor.py
|     +-- pitcher_strikeouts_predictor.py
|     +-- config.py
|     +-- worker.py
|     +-- shadow_mode_runner.py
|     +-- pitcher_loader.py
|     +-- Dockerfile
|     +-- requirements.txt
|     +-- prediction_systems/
|           +-- v1_baseline_predictor.py
|           +-- v1_6_rolling_predictor.py
|           +-- ensemble_v1.py
|
+-- scripts/mlb/
|     +-- training/
|     |     +-- train_pitcher_strikeouts_v1_5.py
|     |     +-- train_v1_6_rolling.py
|     |     +-- walk_forward_validation.py
|     +-- historical_odds_backfill/
|     |     +-- backfill_historical_betting_lines.py
|     |     +-- grade_historical_predictions.py
|     |     +-- calculate_hit_rate.py
|     +-- setup/
|     |     +-- create_mlb_registry_tables.py
|     |     +-- discover_mlb_market_ids.py
|     +-- simulate_game_day.py
|     +-- validate_current_predictions_v1.py
|
+-- deployment/dockerfiles/mlb/
      +-- Dockerfile.gap-detection
      +-- Dockerfile.freshness-checker
      +-- Dockerfile.prediction-coverage
```

---

## Training Scripts

**Path:** `scripts/mlb/training/`

### Train V1.6 Model

```bash
PYTHONPATH=. python scripts/mlb/training/train_v1_6_rolling.py
```

### Walk-Forward Validation

```bash
PYTHONPATH=. python scripts/mlb/training/walk_forward_validation.py
```

### Backtest Historical Predictions

```bash
# Backfill historical odds
PYTHONPATH=. python scripts/mlb/historical_odds_backfill/backfill_historical_betting_lines.py

# Grade predictions
PYTHONPATH=. python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py

# Calculate hit rate
PYTHONPATH=. python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py
```

---

## Future Enhancements

1. **Batter Strikeout Predictions:** Add batter K predictions
2. **Game Total Models:** Team-level run totals
3. **Real-time Adjustments:** Lineups announced → re-predict
4. **Velocity Tracking:** Per-game velocity drop detection
5. **Line Movement Signals:** Opening vs closing line analysis
6. **Weather Integration:** Temperature/wind impact modeling

---

## Support

- **Platform:** GCP (BigQuery, Cloud Run, Pub/Sub, GCS)
- **Models Stored:** `gs://nba-scraped-data/ml-models/mlb/`
- **Predictions Table:** `mlb_predictions.pitcher_strikeouts`
- **Shadow Results:** `mlb_predictions.shadow_mode_predictions`
