# MLB Pitcher Strikeouts - Phase Architecture Analysis

**Date**: 2026-01-07
**Purpose**: Compare NBA architecture with MLB to identify gaps and create implementation plan

---

## EXECUTIVE SUMMARY

### Current State Comparison

| Component | NBA | MLB | Gap |
|-----------|-----|-----|-----|
| **Scrapers** | 27 | 28 | MLB ahead |
| **Raw Tables** | 18 | 22 | MLB ahead |
| **Raw Processors** | 13+ | 8 | Missing 5+ |
| **Analytics Tables** | 6 | 2 | **Missing 4** |
| **Analytics Processors** | 5 | 2 | Missing 3 |
| **Precompute Tables** | 7 | 1 | **Missing 6** |
| **Precompute Processors** | 5 | 1 | Missing 4 |
| **ML Feature Store** | 25 features, production | 25 features, partial | Needs completion |
| **Prediction Systems** | 5 systems | 0 | **Not started** |
| **Grading System** | Complete | 0 | **Not started** |

### Priority Assessment

1. **HIGH**: Analytics tables (upcoming_player_game_context, team_game_summary)
2. **HIGH**: Precompute pipeline (daily cache, composite factors)
3. **MEDIUM**: ML training script
4. **MEDIUM**: Prediction worker/coordinator
5. **LOWER**: Grading pipeline

---

## PHASE 2: RAW DATA (Comparison)

### NBA Raw Tables (18 tables)

```
Ball Don't Lie:
├── bdl_active_players_current
├── bdl_injuries
├── bdl_live_boxscores
├── bdl_player_boxscores
├── bdl_standings

NBA.com:
├── nbac_gamebook_player_stats (PRIMARY)
├── nbac_injury_report
├── nbac_play_by_play (shot zones)
├── nbac_schedule
├── nbac_scoreboard

ESPN:
├── espn_boxscores
├── espn_scoreboard
├── espn_team_rosters

Basketball Ref:
├── br_roster_changes
├── br_rosters_current

Betting:
├── bettingpros_player_points_props
├── bigdataball_play_by_play
```

### MLB Raw Tables (22 tables) - COMPLETE

```
Ball Don't Lie:
├── bdl_active_players
├── bdl_batter_stats
├── bdl_box_scores
├── bdl_games
├── bdl_injuries
├── bdl_live_box_scores
├── bdl_pitcher_season_stats
├── bdl_pitcher_splits
├── bdl_pitcher_stats
├── bdl_player_versus
├── bdl_standings
├── bdl_team_season_stats

MLB Stats API:
├── mlb_game_feed (pitch-by-pitch)
├── mlb_game_lineups
├── mlb_lineup_batters
├── mlb_schedule

Odds API:
├── oddsa_batter_props
├── oddsa_events
├── oddsa_game_lines
├── oddsa_pitcher_props

External:
├── game_weather
├── statcast_pitcher_stats
```

### Gap: Raw Processors Needed

MLB is missing processors for these existing scrapers:

| Scraper | Has Table | Has Processor | Priority |
|---------|-----------|---------------|----------|
| MlbStandingsScraper | YES | NO | MEDIUM |
| MlbBoxScoresScraper | YES | NO | HIGH (grading) |
| MlbLiveBoxScoresScraper | YES | NO | LOW (live) |
| MlbTeamSeasonStatsScraper | YES | NO | HIGH (features) |
| MlbPlayerVersusScraper | YES | NO | MEDIUM |
| MlbGameFeedScraper | YES | NO | LOW |
| MlbStatcastPitcherScraper | YES | NO | MEDIUM |
| MlbWeatherScraper | YES | NO | LOW |

---

## PHASE 3: ANALYTICS (Critical Gaps)

### NBA Analytics Tables (6 tables)

| Table | Fields | Purpose |
|-------|--------|---------|
| `player_game_summary` | 79 | Player stats with 6-source fallback |
| `team_offense_game_summary` | 49 | Team offensive aggregates |
| `team_defense_game_summary` | 43 | Team defensive aggregates |
| `upcoming_player_game_context` | 48+ | Pre-game context for predictions |
| `upcoming_team_game_context` | 35+ | Pre-game team context |
| *(aggregate views)* | - | Various rollups |

**Total NBA Analytics Fields: 254+**

### MLB Analytics Tables (2 tables)

| Table | Fields | Purpose |
|-------|--------|---------|
| `pitcher_game_summary` | ~40 | Pitcher rolling stats |
| `batter_game_summary` | ~40 | Batter rolling stats |

**Total MLB Analytics Fields: ~80**

### CRITICAL GAPS - MLB Needs These Tables

#### 1. `upcoming_pitcher_game_context` (NEW - CRITICAL)

**Purpose**: Pre-game context for pitchers starting today

**Fields (50+)**:
```sql
-- Identifiers
pitcher_lookup STRING,
game_date DATE,
game_id STRING,
team_abbr STRING,
opponent_team_abbr STRING,

-- Schedule Context
game_start_time TIMESTAMP,
is_home BOOLEAN,
is_day_game BOOLEAN,
venue STRING,

-- Pitcher State
days_rest INT64,
games_last_30_days INT64,
innings_last_30_days FLOAT64,
pitch_count_trend FLOAT64,
k_rate_trend FLOAT64,

-- Betting Lines
k_line FLOAT64,
k_line_opening FLOAT64,
k_line_movement FLOAT64,
over_odds INT64,
under_odds INT64,
line_source STRING,

-- Opponent Context
opponent_team_k_rate FLOAT64,
opponent_obp FLOAT64,
opponent_woba FLOAT64,
opponent_k_pct_vs_same_hand FLOAT64,

-- Ballpark/Weather
ballpark_k_factor FLOAT64,
temperature FLOAT64,
wind_mph FLOAT64,
is_dome BOOLEAN,

-- Fatigue Indicators
back_to_back_start BOOLEAN,
short_rest BOOLEAN,
season_pitch_count_total INT64,
season_innings_total FLOAT64,

-- Source Tracking (v4.0 pattern)
source_pitcher_stats_last_updated TIMESTAMP,
source_pitcher_stats_rows_found INT64,
source_schedule_last_updated TIMESTAMP,
source_odds_last_updated TIMESTAMP,

-- Quality Metrics
data_quality_score FLOAT64,
is_production_ready BOOLEAN,
created_at TIMESTAMP,
updated_at TIMESTAMP
```

**Data Sources**:
- mlb_raw.mlb_schedule (game context)
- mlb_raw.oddsa_pitcher_props (betting lines)
- mlb_raw.bdl_pitcher_stats (recent performance)
- mlb_raw.bdl_standings (playoff context)
- mlb_raw.game_weather (weather)
- mlb_analytics.pitcher_game_summary (rolling stats)
- mlb_analytics.batter_game_summary (opponent stats)

#### 2. `team_game_summary` (NEW - HIGH)

**Purpose**: Team-level game aggregates

**Fields (45+)**:
```sql
-- Identifiers
team_abbr STRING,
game_date DATE,
game_id STRING,
opponent_abbr STRING,
season_year INT64,

-- Game Context
is_home BOOLEAN,
win_flag BOOLEAN,
runs_scored INT64,
runs_allowed INT64,

-- Team Batting
team_hits INT64,
team_walks INT64,
team_strikeouts INT64,  -- CRITICAL for bottom-up model
team_home_runs INT64,
team_batting_avg FLOAT64,
team_obp FLOAT64,
team_slg FLOAT64,
team_k_rate FLOAT64,

-- Team Pitching
team_era FLOAT64,
team_whip FLOAT64,
team_k_rate_pitching FLOAT64,

-- Rolling Averages (last 10/30)
runs_avg_last_10 FLOAT64,
k_rate_avg_last_10 FLOAT64,
obp_avg_last_10 FLOAT64,

-- Source Tracking
source_batter_stats_last_updated TIMESTAMP,
source_pitcher_stats_last_updated TIMESTAMP,

-- Quality
created_at TIMESTAMP,
updated_at TIMESTAMP
```

#### 3. `upcoming_team_game_context` (NEW - MEDIUM)

**Purpose**: Pre-game team context

**Fields (30+)**:
```sql
-- Identifiers
team_abbr STRING,
game_date DATE,
game_id STRING,
opponent_abbr STRING,

-- Schedule
series_game_number INT64,
games_in_last_7 INT64,
travel_miles_last_3_days FLOAT64,

-- Team State
team_k_rate_last_10 FLOAT64,
team_obp_last_10 FLOAT64,
win_pct_last_10 FLOAT64,

-- Betting
run_line FLOAT64,
game_total FLOAT64,
implied_runs FLOAT64,

-- Playoff Context
games_back FLOAT64,
playoff_position STRING,

-- Source Tracking
created_at TIMESTAMP
```

---

## PHASE 4: PRECOMPUTE (Critical Gaps)

### NBA Precompute Tables (7 tables)

| Table | Purpose | Dependencies |
|-------|---------|--------------|
| `team_defense_zone_analysis` | Team defense by zone | team_defense_game_summary |
| `player_shot_zone_analysis` | Player shooting by zone | player_game_summary |
| `player_daily_cache` | Fast lookup cache | All Phase 3 |
| `player_composite_factors` | 4 adjustment scores | Phase 3 + Zone analysis |
| `daily_game_context` | Game-level context | Schedule + odds |
| `daily_opponent_defense_zones` | Opponent defense | team_defense_zone_analysis |
| `ml_feature_store_v2` | 25-feature vectors | All Phase 4 |

### MLB Precompute Tables (1 table)

| Table | Purpose | Status |
|-------|---------|--------|
| `pitcher_ml_features` | 25-feature vectors | Partial (missing sources) |

### CRITICAL GAPS - MLB Needs These Tables

#### 1. `pitcher_daily_cache` (NEW - HIGH)

**Purpose**: Fast lookup cache for pitcher data (eliminates repeated queries)

**Fields (35+)**:
```sql
-- Identifiers
pitcher_lookup STRING,
cache_date DATE,
team_abbr STRING,

-- Recent Performance (cached)
k_avg_last_5 FLOAT64,
k_avg_last_10 FLOAT64,
k_avg_season FLOAT64,
k_std_last_10 FLOAT64,
ip_avg_last_5 FLOAT64,
era_last_10 FLOAT64,
whip_last_10 FLOAT64,

-- Workload
pitch_count_avg_last_5 INT64,
innings_season_total FLOAT64,
games_started INT64,
quality_starts INT64,

-- Fatigue Metrics
games_last_7_days INT64,
games_last_14_days INT64,
innings_last_7_days FLOAT64,
innings_last_14_days FLOAT64,

-- Split Performance
k_rate_home FLOAT64,
k_rate_away FLOAT64,
k_rate_day FLOAT64,
k_rate_night FLOAT64,

-- Source Tracking (v4.0 pattern)
source_pitcher_stats_last_updated TIMESTAMP,
source_pitcher_stats_rows_found INT64,
source_pitcher_stats_completeness_pct FLOAT64,
source_pitcher_stats_hash STRING,

-- Quality
data_quality_score FLOAT64,
is_production_ready BOOLEAN,
early_season_flag BOOLEAN,
created_at TIMESTAMP
```

**Cost Impact**: 79% reduction in BigQuery costs (same as NBA pattern)

#### 2. `pitcher_composite_factors` (NEW - HIGH)

**Purpose**: Calculate adjustment factors for predictions

**Fields (25+)**:
```sql
-- Identifiers
pitcher_lookup STRING,
game_date DATE,
game_id STRING,
opponent_abbr STRING,

-- The 4 Composite Factors (MLB version)
fatigue_score FLOAT64,          -- 0-100: Based on days rest, recent workload
matchup_mismatch_score FLOAT64, -- -10 to +10: Pitcher strength vs opponent weakness
ballpark_impact_score FLOAT64,  -- -5 to +5: Park K factor adjustment
recent_form_score FLOAT64,      -- -5 to +5: Hot/cold pitcher detection

-- Total Composite
total_composite_adjustment FLOAT64,  -- Sum of all factors

-- Factor Context (JSON for debugging)
fatigue_context STRING,
matchup_context STRING,
ballpark_context STRING,
form_context STRING,

-- Source Tracking
source_daily_cache_hash STRING,
source_opponent_stats_hash STRING,
source_ballpark_hash STRING,

-- Quality
created_at TIMESTAMP,
updated_at TIMESTAMP
```

**Fatigue Score Calculation**:
```
Base: 100
- Short rest (3 days): -15
- Back-to-back start: -25
- High workload (>95 pitches avg): -10
+ Extra rest (5+ days): +5
+ Low workload (<80 pitches avg): +5
```

**Matchup Mismatch Score**:
```
Compare: pitcher_k_rate vs opponent_k_rate
If pitcher K rate >> opponent K rate: Positive adjustment
If pitcher K rate << opponent K rate: Negative adjustment
Range: -10 to +10
```

#### 3. `opponent_lineup_analysis` (NEW - MEDIUM)

**Purpose**: Analyze today's opponent lineup for strikeout potential

**Fields (30+)**:
```sql
-- Identifiers
game_id STRING,
game_date DATE,
pitcher_lookup STRING,
opponent_team_abbr STRING,

-- Lineup Aggregates
lineup_avg_k_rate FLOAT64,
lineup_avg_obp FLOAT64,
lineup_avg_woba FLOAT64,

-- Per-Position Analysis (array)
lineup_batters ARRAY<STRUCT<
  batting_order INT64,
  batter_lookup STRING,
  k_rate_last_10 FLOAT64,
  k_rate_season FLOAT64,
  handedness STRING
>>,

-- Bottom-Up K Calculation
bottom_up_expected_k FLOAT64,  -- Sum of individual batter K probabilities
bottom_up_k_std FLOAT64,

-- Pitcher vs Lineup
pitcher_vs_team_k_rate FLOAT64,
pitcher_vs_team_ab INT64,

-- Source
created_at TIMESTAMP
```

#### 4. `ml_feature_store` (ENHANCE existing)

**Current**: `mlb_precompute.pitcher_ml_features` (basic)

**Needed Enhancements**:
- Add source tracking (4 fields per source)
- Add completeness checking (14 fields)
- Add data quality score
- Add early season handling
- Add smart idempotency (data_hash)

---

## PHASE 5: ML TRAINING & PREDICTIONS (Not Started)

### NBA Has (Complete)

1. **ML Training** (`ml/train_real_xgboost.py`)
   - 25 features, chronological split
   - XGBoost with early stopping
   - Model saved to GCS

2. **5 Prediction Systems**
   - Moving Average Baseline
   - Zone Matchup V1
   - Similarity Balanced V1
   - XGBoost V1
   - Ensemble V1 (combines all)

3. **Prediction Worker** (Cloud Run)
   - Receives Pub/Sub requests
   - Runs all 5 systems
   - Writes to staging table

4. **Prediction Coordinator** (Cloud Run)
   - Loads players with games
   - Pre-loads historical data
   - Publishes prediction requests
   - Consolidates staging tables

### MLB Needs

#### 1. Training Script: `ml/train_pitcher_strikeouts_xgboost.py`

**Template from NBA** but adapted for:
- Target: strikeouts (not points)
- Features: 25 pitcher-specific
- Data: 2-3 MLB seasons
- Splits: Chronological (train on 2023, validate 2024)

#### 2. Prediction Systems (Start with 3)

**System 1: Moving Average Baseline**
```python
# Weighted average of recent K performance
base_k = (
    0.5 * k_avg_last_5 +
    0.3 * k_avg_last_10 +
    0.2 * k_avg_season
)

# Adjustments
if fatigue_score < 70: base_k -= 1.0
if matchup_mismatch > 5: base_k += 0.5
if ballpark_k_factor > 1.1: base_k += 0.5
if is_day_game and day_k_rate > night_k_rate: base_k += 0.3
```

**System 2: XGBoost V1**
- Load trained model from GCS
- Pass 25-feature vector
- Return predicted_k, confidence

**System 3: Ensemble V1**
- Confidence-weighted average of all systems
- Variance-based agreement scoring

---

## PHASE 6: GRADING (Not Started)

### NBA Has

1. **Prediction Accuracy Processor**
   - Matches predictions with actuals
   - Computes error metrics
   - Writes to prediction_accuracy table

2. **Performance Summary**
   - Aggregates by system, player, situation
   - Rolling 7d, 30d, season views

### MLB Needs

#### 1. `prediction_accuracy` Table

```sql
CREATE TABLE mlb_predictions.prediction_accuracy (
  pitcher_lookup STRING,
  game_id STRING,
  game_date DATE,
  system_id STRING,

  -- Prediction Snapshot
  predicted_k FLOAT64,
  confidence_score FLOAT64,
  recommendation STRING,  -- OVER/UNDER/PASS
  k_line FLOAT64,

  -- Actual Result
  actual_k INT64,

  -- Accuracy Metrics
  absolute_error FLOAT64,
  signed_error FLOAT64,
  prediction_correct BOOLEAN,
  within_1_k BOOLEAN,
  within_2_k BOOLEAN,

  -- Margin
  predicted_margin FLOAT64,
  actual_margin FLOAT64,

  -- Metadata
  graded_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id, pitcher_lookup
```

---

## IMPLEMENTATION ROADMAP

### Phase 1: Analytics Foundation (Week 1-2)

**Priority 1.1: Create upcoming_pitcher_game_context**
- Schema design (50+ fields)
- Processor implementation
- Source tracking v4.0 pattern
- Backfill job

**Priority 1.2: Create team_game_summary**
- Aggregate batter/pitcher stats to team level
- Rolling averages
- Quality tracking

### Phase 2: Precompute Pipeline (Week 2-3)

**Priority 2.1: Create pitcher_daily_cache**
- Fast lookup cache
- Source tracking
- Completeness checking

**Priority 2.2: Create pitcher_composite_factors**
- Fatigue score
- Matchup mismatch
- Ballpark impact
- Recent form

**Priority 2.3: Create opponent_lineup_analysis**
- Bottom-up K calculation
- Per-batter analysis
- Lineup aggregates

**Priority 2.4: Enhance ml_feature_store**
- Add 14-field completeness checking
- Add source tracking
- Add smart idempotency

### Phase 3: ML Training (Week 3-4)

**Priority 3.1: Historical backfill**
- Run scrapers for 2023-2024 seasons
- Process raw data
- Populate analytics tables
- Populate precompute tables

**Priority 3.2: Create training script**
- Adapt NBA template
- 25 pitcher-specific features
- XGBoost with early stopping

**Priority 3.3: Train initial model**
- Chronological split
- Evaluate vs baseline
- Save to GCS

### Phase 4: Prediction System (Week 4-5)

**Priority 4.1: Create prediction systems**
- Moving Average Baseline
- XGBoost V1
- Ensemble V1

**Priority 4.2: Create prediction worker**
- Cloud Run service
- Pub/Sub integration
- Staging table writes

**Priority 4.3: Create prediction coordinator**
- Player loading
- Request publishing
- Batch consolidation

### Phase 5: Grading & Evaluation (Week 5-6)

**Priority 5.1: Create grading processor**
- Match predictions with actuals
- Compute accuracy metrics
- Write to prediction_accuracy

**Priority 5.2: Create performance summary**
- Aggregation by system
- Rolling windows
- Calibration analysis

---

## SCHEMA FILES NEEDED

### New SQL Files to Create

1. `schemas/bigquery/mlb_analytics/upcoming_pitcher_game_context_tables.sql`
2. `schemas/bigquery/mlb_analytics/team_game_summary_tables.sql`
3. `schemas/bigquery/mlb_analytics/upcoming_team_game_context_tables.sql`
4. `schemas/bigquery/mlb_precompute/pitcher_daily_cache_tables.sql`
5. `schemas/bigquery/mlb_precompute/pitcher_composite_factors_tables.sql`
6. `schemas/bigquery/mlb_precompute/opponent_lineup_analysis_tables.sql`
7. `schemas/bigquery/mlb_predictions/pitcher_k_predictions_tables.sql`
8. `schemas/bigquery/mlb_predictions/prediction_accuracy_tables.sql`
9. `schemas/bigquery/mlb_predictions/prediction_performance_summary_tables.sql`

### New Processor Files to Create

1. `data_processors/analytics/mlb/upcoming_pitcher_game_context_processor.py`
2. `data_processors/analytics/mlb/team_game_summary_processor.py`
3. `data_processors/precompute/mlb/pitcher_daily_cache_processor.py`
4. `data_processors/precompute/mlb/pitcher_composite_factors_processor.py`
5. `data_processors/precompute/mlb/opponent_lineup_analysis_processor.py`
6. `predictions/mlb/worker/worker.py`
7. `predictions/mlb/coordinator/coordinator.py`
8. `data_processors/grading/mlb/pitcher_k_accuracy_processor.py`

---

## SUMMARY

### What MLB Has (Complete)
- 28 scrapers (ahead of NBA)
- 22 raw tables (ahead of NBA)
- 8 raw processors
- 2 analytics tables (basic)
- 1 precompute table (partial)

### What MLB Needs (Critical)
- 4 new analytics tables (~175 fields)
- 4 new precompute tables (~120 fields)
- 1 enhanced ML feature store
- 3 prediction systems
- 1 grading pipeline

### Estimated Effort
- **Total New Fields**: ~295 fields across 8 tables
- **Total New Processors**: 8 processors + 2 Cloud Run services
- **Timeline**: 5-6 weeks to match NBA maturity

The MLB infrastructure is solid at the scraper/raw level, but needs significant work on analytics and precompute to support production ML predictions.
