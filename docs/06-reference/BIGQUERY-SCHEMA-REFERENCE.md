# BigQuery Schema Reference

**Last Updated:** 2026-01-24
**Location:** `schemas/bigquery/`

---

## Overview

The NBA Props Platform uses 8 BigQuery datasets organized by pipeline phase:

| Dataset | Phase | Purpose | Tables |
|---------|-------|---------|--------|
| `nba_raw` | Phase 2 | Scraped data from external sources | ~40 |
| `nba_analytics` | Phase 3 | Calculated player/team metrics | 5 |
| `nba_precompute` | Phase 4 | Pre-computed aggregations | 4 |
| `nba_predictions` | Phase 5 | ML predictions and results | 8+ |
| `nba_reference` | - | Player identity registry | 3 |
| `nba_static` | - | Team locations, travel distances | 3 |
| `nba_processing` | - | Pipeline monitoring | 5+ |
| `nba_orchestration` | - | Workflow state | 3 |

MLB uses parallel datasets: `mlb_raw`, `mlb_analytics`, `mlb_predictions`, etc.

---

## Phase 2: Raw Data (`nba_raw`)

### NBA.com Tables

| Table | Description | Partition | Key Columns |
|-------|-------------|-----------|-------------|
| `nbac_player_boxscores` | Player game stats | game_date | game_id, nba_player_id, points, assists, rebounds, minutes |
| `nbac_team_boxscore` | Team game stats | game_date | game_id, team_abbr, points, rebounds |
| `nbac_gamebook_player_stats` | Official gamebook stats | game_date | game_id, player_id, plus_minus |
| `nbac_schedule` | Game schedule | game_date | game_id, home_team, away_team, game_status |
| `nbac_play_by_play` | Play-by-play events | game_date | game_id, event_id, action_type |
| `nbac_injury_report` | Injury reports | report_date | player_id, injury_status |
| `nbac_referee` | Referee assignments | game_date | game_id, referee_id |
| `nbac_player_list` | Active player roster | extraction_date | player_id, team_abbr |

### Ball Don't Lie Tables

| Table | Description | Partition | Key Columns |
|-------|-------------|-----------|-------------|
| `bdl_player_boxscores` | Player game stats | game_date | game_id, player_lookup, points, assists |
| `bdl_standings` | Team standings | date | team_abbr, wins, losses, pct |
| `bdl_active_players` | Active players | date | player_id, team_abbr |
| `bdl_injuries` | Injury tracking | date | player_id, injury_type |
| `bdl_odds` | Game odds | date | game_id, spread, total |

### Odds API Tables

| Table | Description | Partition | Key Columns |
|-------|-------------|-----------|-------------|
| `odds_api_game_lines` | Spread/total lines | game_date | game_id, bookmaker, spread, total |
| `odds_api_player_points_props` | Points props | date | player_lookup, line, over_odds, under_odds |
| `odds_api_player_assists_props` | Assists props | date | player_lookup, line |
| `odds_api_player_rebounds_props` | Rebounds props | date | player_lookup, line |

### BettingPros Tables

| Table | Description | Partition | Key Columns |
|-------|-------------|-----------|-------------|
| `bettingpros_player_points_props` | Points props | date | player_lookup, line, consensus_pick |
| `bettingpros_player_assists_props` | Assists props | date | player_lookup, line |
| `bettingpros_player_rebounds_props` | Rebounds props | date | player_lookup, line |

### ESPN Tables

| Table | Description | Partition | Key Columns |
|-------|-------------|-----------|-------------|
| `espn_scoreboard` | Scoreboard data | date | game_id, status, scores |
| `espn_boxscores` | Box scores | date | game_id, player_id, stats |
| `espn_team_rosters` | Team rosters | date | team_abbr, player_id, position |

---

## Phase 3: Analytics (`nba_analytics`)

### Core Tables

#### `player_game_summary`
Complete player performance per game with shot zones and prop results.

```sql
-- Key columns
player_lookup STRING,        -- Canonical player identifier
game_id STRING,
game_date DATE,

-- Basic stats
points INT64,
assists INT64,
rebounds INT64,
steals INT64,
blocks INT64,
turnovers INT64,
minutes FLOAT64,

-- Shot zones
paint_attempts INT64,
paint_makes INT64,
mid_range_attempts INT64,
mid_range_makes INT64,
three_pt_attempts INT64,
three_pt_makes INT64,

-- Advanced metrics
usage_rate FLOAT64,
ts_pct FLOAT64,              -- True Shooting %
efg_pct FLOAT64,             -- Effective FG %

-- Prop results
points_line FLOAT64,
over_under_result STRING,    -- 'OVER', 'UNDER', 'PUSH'

-- Source tracking
source_primary STRING,
source_fallback STRING,
source_completeness_pct FLOAT64
```

**Partitioning:** `BY game_date`
**Clustering:** `BY player_lookup, game_date`

#### `team_offense_game_summary`
Team offensive performance aggregates.

```sql
team_abbr STRING,
game_date DATE,
game_id STRING,
points INT64,
pace FLOAT64,
offensive_rating FLOAT64,
fg_pct FLOAT64,
three_pt_pct FLOAT64,
ft_pct FLOAT64,
assists INT64,
turnovers INT64
```

#### `team_defense_game_summary`
Team defensive performance by zone.

```sql
team_abbr STRING,
game_date DATE,
opponent_points_allowed INT64,
opponent_paint_pct FLOAT64,
opponent_mid_range_pct FLOAT64,
opponent_three_pt_pct FLOAT64,
defensive_rating FLOAT64
```

#### `upcoming_player_game_context`
Pre-game context for predictions.

```sql
player_lookup STRING,
game_date DATE,
game_id STRING,
opponent_abbr STRING,
is_home BOOL,
rest_days INT64,
travel_distance_miles FLOAT64,
fatigue_score FLOAT64,
back_to_back BOOL
```

---

## Phase 4: Precompute (`nba_precompute`)

### `player_shot_zone_analysis`
Shot distribution and efficiency by zone (10 & 20-game windows).

```sql
player_lookup STRING,
analysis_date DATE,

-- 10-game window
paint_rate_last_10 FLOAT64,
paint_pct_last_10 FLOAT64,
mid_range_rate_last_10 FLOAT64,
mid_range_pct_last_10 FLOAT64,
three_pt_rate_last_10 FLOAT64,
three_pt_pct_last_10 FLOAT64,
games_in_sample_10 INT64,

-- 20-game window
paint_rate_last_20 FLOAT64,
games_in_sample_20 INT64,

-- Quality indicators
sample_quality_10 STRING,    -- 'HIGH', 'MEDIUM', 'LOW'
data_quality_tier STRING
```

**Schedule:** Nightly 11:15 PM ET

### `team_defense_zone_analysis`
Team defensive zone strengths (15-game window).

```sql
team_abbr STRING,
analysis_date DATE,
opponent_paint_pct_allowed FLOAT64,
opponent_mid_range_pct_allowed FLOAT64,
opponent_three_pt_pct_allowed FLOAT64,
games_in_sample INT64
```

**Schedule:** Nightly 11:00 PM ET

### `player_composite_factors`
Adjustment factors for predictions.

```sql
player_lookup STRING,
game_date DATE,
fatigue_adjustment FLOAT64,
matchup_adjustment FLOAT64,
pace_adjustment FLOAT64,
usage_adjustment FLOAT64,
home_away_adjustment FLOAT64
```

**Schedule:** Nightly 11:30 PM ET

---

## Phase 5: Predictions (`nba_predictions`)

### `prediction_systems`
Registry of all prediction systems.

```sql
system_id STRING,            -- 'catboost_v8', 'ensemble_v1', etc.
system_name STRING,
system_type STRING,          -- 'ml', 'ensemble', 'baseline', 'similarity_based'
version STRING,
active BOOL,
is_champion BOOL,            -- Primary production system
config JSON,                 -- Weights, thresholds
lifetime_predictions INT64,
lifetime_accuracy FLOAT64,
last_7_days_accuracy FLOAT64,
last_30_days_accuracy FLOAT64,
model_id STRING,             -- Reference to ml_models
model_file_path STRING
```

### `player_prop_predictions`
All predictions from all systems.

```sql
prediction_id STRING,
system_id STRING,
player_lookup STRING,
game_date DATE,
game_id STRING,

-- Core prediction
predicted_points FLOAT64,
confidence_score FLOAT64,    -- 0-100
recommendation STRING,       -- 'OVER', 'UNDER', 'PASS', 'NO_LINE'

-- Prediction components
similarity_baseline FLOAT64,
fatigue_adjustment FLOAT64,
shot_zone_adjustment FLOAT64,
pace_adjustment FLOAT64,
home_away_adjustment FLOAT64,

-- Line info
current_points_line FLOAT64,
line_source STRING,          -- 'odds_api', 'bettingpros', 'estimated'
sportsbook STRING,

-- Multi-system analysis
prediction_variance FLOAT64,
system_agreement_score FLOAT64,

-- Metadata
key_factors JSON,
warnings JSON,
is_production_ready BOOL,
created_at TIMESTAMP
```

**Partitioning:** `BY game_date`
**Clustering:** `BY system_id, player_lookup`

### `prediction_results`
Actual outcomes vs predictions.

```sql
prediction_id STRING,
system_id STRING,
player_lookup STRING,
game_date DATE,

-- Comparison
predicted_points FLOAT64,
actual_points FLOAT64,
prediction_line FLOAT64,
actual_result STRING,        -- 'OVER', 'UNDER', 'PUSH'

-- Accuracy metrics
prediction_error FLOAT64,
prediction_correct BOOL,
within_3_points BOOL,
within_5_points BOOL,

-- Calibration
confidence_score FLOAT64,
confidence_calibrated BOOL
```

**Partitioning:** `BY game_date`

### `system_daily_performance`
Daily accuracy metrics per system.

```sql
system_id STRING,
date DATE,
total_predictions INT64,
correct_predictions INT64,
accuracy_pct FLOAT64,
mae FLOAT64,                 -- Mean Absolute Error
rmse FLOAT64,                -- Root Mean Square Error
over_accuracy_pct FLOAT64,
under_accuracy_pct FLOAT64
```

### `ml_models`
Registry of trained ML models.

```sql
model_id STRING,
model_name STRING,
model_type STRING,           -- 'xgboost', 'catboost', 'lightgbm'
version STRING,
model_file_path STRING,      -- GCS path
model_size_bytes INT64,

-- Performance
training_mae FLOAT64,
validation_mae FLOAT64,
test_mae FLOAT64,
training_samples INT64,

-- Features
features_used JSON,
feature_importance JSON,
hyperparameters JSON,

-- Status
active BOOL,
production_ready BOOL,
trained_on_date DATE
```

---

## Reference Tables (`nba_reference`)

### `nba_players_registry`
Authoritative player validation.

```sql
universal_player_id STRING,  -- UUID
player_name STRING,          -- Canonical name
player_lookup STRING,        -- Lowercase normalized
team_abbr STRING,
season STRING,
first_game_date DATE,
last_game_date DATE,
games_played INT64,
jersey_number STRING,
position STRING,
confidence_score FLOAT64     -- Match confidence
```

### `player_aliases`
Name variation mappings.

```sql
alias STRING,                -- Variant name
canonical_name STRING,       -- Correct name
player_lookup STRING,
source STRING,               -- Where alias was found
created_at TIMESTAMP
```

---

## Static Tables (`nba_static`)

### `team_locations`
Geographic reference data.

```sql
team_abbr STRING,            -- PRIMARY KEY
city STRING,
state STRING,
arena_name STRING,
latitude FLOAT64,
longitude FLOAT64,
timezone STRING,
airport_code STRING
```

### `travel_distances`
Pre-computed travel distances.

```sql
from_team STRING,
to_team STRING,
distance_miles FLOAT64,
flight_hours FLOAT64,
timezone_change INT64
```

---

## Common Patterns

### Smart Idempotency
All raw tables include:
```sql
data_hash STRING  -- SHA256 hash of meaningful fields
```
Prevents redundant writes when data is unchanged.

### Standard Metadata
All tables include:
```sql
created_at TIMESTAMP,
processed_at TIMESTAMP,
source_file_path STRING,
scrape_timestamp TIMESTAMP
```

### Partitioning
- All tables with date dimension: `PARTITION BY game_date`
- All partitions require filter: `require_partition_filter = true`

### Clustering
- Player tables: `CLUSTER BY player_lookup, game_date`
- Game tables: `CLUSTER BY game_id`
- Prediction tables: `CLUSTER BY system_id`

---

## Retention Policies

| Data Type | Retention | Reason |
|-----------|-----------|--------|
| Raw data | 180-365 days | Source for reprocessing |
| Analytics | 90-180 days | Historical analysis |
| Precompute | 90 days | Regenerable |
| Predictions | 3 years | Long-term analysis |
| Processing logs | 60-180 days | Debugging |

---

## Schema Files

```
schemas/bigquery/
├── datasets.sql                    # Dataset definitions
├── raw/                            # Phase 2 tables
│   ├── nbac_*.sql                  # NBA.com tables
│   ├── bdl_*.sql                   # Ball Don't Lie tables
│   ├── odds_*.sql                  # Odds API tables
│   └── bettingpros_*.sql           # BettingPros tables
├── analytics/                      # Phase 3 tables
│   ├── player_game_summary_tables.sql
│   ├── team_offense_game_summary_tables.sql
│   └── team_defense_game_summary_tables.sql
├── precompute/                     # Phase 4 tables
│   ├── player_shot_zone_analysis.sql
│   └── team_defense_zone_analysis.sql
├── predictions/                    # Phase 5 tables
│   ├── 00_prediction_systems.sql
│   ├── 01_player_prop_predictions.sql
│   └── 02_prediction_results.sql
├── nba_reference/                  # Player registry
│   └── nba_players_registry_table.sql
├── static/                         # Static reference
│   ├── team_locations_table.sql
│   └── travel_distances_table.sql
└── processing/                     # Monitoring
    └── processing_tables.sql
```

---

## Related Documentation

- [Pipeline Architecture](../01-architecture/quick-reference.md)
- [MLB Platform](./MLB-PLATFORM.md)
- [Validation Framework](../08-projects/current/comprehensive-improvements-jan-2026/VALIDATION-FRAMEWORK-GUIDE.md)
