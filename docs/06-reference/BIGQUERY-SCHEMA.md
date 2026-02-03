# BigQuery Schema Reference

This document provides comprehensive documentation of all BigQuery datasets and tables used in the NBA Props Platform.

**Project:** `nba-props-platform`
**Location:** US (primary), us-west2 (some datasets)

---

## Table of Contents

1. [Dataset Overview](#dataset-overview)
2. [NBA Datasets](#nba-datasets)
   - [nba_raw](#nba_raw---phase-2-raw-data)
   - [nba_analytics](#nba_analytics---phase-3-analytics)
   - [nba_precompute](#nba_precompute---phase-4-precompute)
   - [nba_predictions](#nba_predictions---phase-5-predictions)
   - [nba_reference](#nba_reference---player-identity)
   - [nba_static](#nba_static---static-reference-data)
   - [nba_processing](#nba_processing---processing-monitoring)
   - [nba_orchestration](#nba_orchestration---pipeline-orchestration)
3. [MLB Datasets](#mlb-datasets)
4. [Key Relationships](#key-relationships)
5. [Common Patterns](#common-patterns)

---

## Dataset Overview

The platform uses a 6-phase data pipeline architecture:

| Phase | Dataset | Description |
|-------|---------|-------------|
| 2 | `nba_raw` | Scraped data from external sources (APIs, websites) |
| 3 | `nba_analytics` | Historical player/team performance with calculated metrics |
| 4 | `nba_precompute` | Pre-computed aggregations and cached calculations |
| 5 | `nba_predictions` | ML model predictions and accuracy tracking |
| - | `nba_reference` | Player identity registry with universal IDs |
| - | `nba_static` | Team locations, travel distances, league patterns |
| - | `nba_processing` | Pipeline execution logs, data quality tracking |
| - | `nba_orchestration` | Scraper scheduling and workflow coordination |

---

## NBA Datasets

### nba_raw - Phase 2 Raw Data

**Purpose:** Scraped and normalized data from external sources (APIs, websites). Minimally processed, close to original format.

#### Core Tables

##### `bdl_player_boxscores`
Player box score statistics from Ball Don't Lie API.

| Column | Type | Description |
|--------|------|-------------|
| `game_id` | STRING | Unique game ID: "YYYYMMDD_AWAY_HOME" |
| `game_date` | DATE | Game date (partition key) |
| `season_year` | INT64 | NBA season year |
| `player_lookup` | STRING | Normalized player identifier |
| `player_full_name` | STRING | Full player name |
| `team_abbr` | STRING | Player's team abbreviation |
| `points` | INT64 | Points scored |
| `assists` | INT64 | Assists |
| `rebounds` | INT64 | Total rebounds |
| `offensive_rebounds` | INT64 | Offensive rebounds |
| `defensive_rebounds` | INT64 | Defensive rebounds |
| `steals` | INT64 | Steals |
| `blocks` | INT64 | Blocks |
| `turnovers` | INT64 | Turnovers |
| `minutes` | STRING | Minutes played (MM:SS format) |
| `field_goals_made` | INT64 | Field goals made |
| `field_goals_attempted` | INT64 | Field goals attempted |
| `three_pointers_made` | INT64 | Three-pointers made |
| `three_pointers_attempted` | INT64 | Three-pointers attempted |
| `free_throws_made` | INT64 | Free throws made |
| `free_throws_attempted` | INT64 | Free throws attempted |
| `data_hash` | STRING | SHA256 hash for idempotency |
| `processed_at` | TIMESTAMP | When record was processed |

**Partitioned by:** `game_date`
**Clustered by:** `player_lookup`, `team_abbr`, `game_date`

---

##### `nbac_gamebook_player_stats`
NBA.com gamebook player statistics with name resolution tracking.

| Column | Type | Description |
|--------|------|-------------|
| `game_id` | STRING | Standardized format: "YYYYMMDD_AWAY_HOME" |
| `game_code` | STRING | Original NBA.com game code |
| `game_date` | DATE | Game date (partition key) |
| `season_year` | INT64 | NBA season year |
| `player_name` | STRING | Final resolved name |
| `player_name_original` | STRING | Name as it appears in source |
| `player_lookup` | STRING | Normalized for matching |
| `team_abbr` | STRING | Player's team |
| `player_status` | STRING | 'active', 'inactive', 'dnp' |
| `name_resolution_status` | STRING | 'resolved', 'not_found', 'multiple_matches' |
| `name_resolution_confidence` | FLOAT64 | 0.0-1.0 confidence score |
| `minutes` | STRING | "MM:SS" format |
| `minutes_decimal` | FLOAT64 | Converted to decimal |
| `points` | INT64 | Points scored |
| `field_goals_made` | INT64 | Field goals made |
| `field_goals_attempted` | INT64 | Field goals attempted |
| `assists` | INT64 | Assists |
| `total_rebounds` | INT64 | Total rebounds |
| `steals` | INT64 | Steals |
| `blocks` | INT64 | Blocks |
| `turnovers` | INT64 | Turnovers |
| `plus_minus` | INT64 | Plus/minus (NBA.com only) |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `season_year`, `team_abbr`, `player_status`, `name_resolution_status`

---

##### `nbac_team_boxscore`
NBA.com team-level box score statistics.

| Column | Type | Description |
|--------|------|-------------|
| `game_id` | STRING | System format: "YYYYMMDD_AWAY_HOME" |
| `nba_game_id` | STRING | NBA.com game ID |
| `game_date` | DATE | Game date (partition key) |
| `season_year` | INT64 | NBA season year |
| `team_id` | INT64 | NBA.com team ID |
| `team_abbr` | STRING | Team abbreviation |
| `is_home` | BOOLEAN | TRUE if home team |
| `fg_made` | INT64 | Field goals made |
| `fg_attempted` | INT64 | Field goals attempted |
| `three_pt_made` | INT64 | Three-pointers made |
| `three_pt_attempted` | INT64 | Three-pointers attempted |
| `ft_made` | INT64 | Free throws made |
| `ft_attempted` | INT64 | Free throws attempted |
| `total_rebounds` | INT64 | Total rebounds |
| `assists` | INT64 | Assists |
| `steals` | INT64 | Steals |
| `blocks` | INT64 | Blocks |
| `turnovers` | INT64 | Turnovers |
| `points` | INT64 | Total points |
| `plus_minus` | INT64 | Plus/minus |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `game_id`, `team_abbr`, `season_year`, `is_home`

---

##### `nbac_schedule`
NBA.com official game schedule.

| Column | Type | Description |
|--------|------|-------------|
| `game_id` | STRING | Unique game ID |
| `game_code` | STRING | NBA.com game code |
| `game_date` | DATE | Game date (partition key) |
| `season_year` | INT64 | Season year |
| `game_status` | INT64 | 1=scheduled, 2=in progress, 3=final |
| `game_status_text` | STRING | "Scheduled", "Final", etc. |
| `home_team_id` | INT64 | Home team NBA.com ID |
| `home_team_tricode` | STRING | Home team abbreviation |
| `away_team_id` | INT64 | Away team NBA.com ID |
| `away_team_tricode` | STRING | Away team abbreviation |
| `arena_name` | STRING | Venue name |
| `is_primetime` | BOOLEAN | ESPN/TNT/ABC game |
| `is_playoffs` | BOOLEAN | Playoff game |
| `is_christmas` | BOOLEAN | Christmas Day game |
| `home_team_score` | INT64 | Home team final score |
| `away_team_score` | INT64 | Away team final score |
| `data_source` | STRING | "api_stats" or "cdn_static" |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `game_date`, `data_source`, `home_team_tricode`, `away_team_tricode`, `season_year`

---

##### `odds_api_player_points_props`
Player points prop odds from The Odds API with historical snapshots.

| Column | Type | Description |
|--------|------|-------------|
| `game_id` | STRING | Game identifier |
| `odds_api_event_id` | STRING | Odds API event ID |
| `game_date` | DATE | Game date (partition key) |
| `snapshot_timestamp` | TIMESTAMP | When odds were captured |
| `player_name` | STRING | Player name from bookmaker |
| `player_lookup` | STRING | Normalized player identifier |
| `bookmaker` | STRING | Bookmaker name |
| `points_line` | FLOAT64 | Points prop line |
| `over_price` | FLOAT64 | Decimal odds for over |
| `under_price` | FLOAT64 | Decimal odds for under |
| `over_price_american` | INT64 | American odds for over |
| `under_price_american` | INT64 | American odds for under |
| `minutes_before_tipoff` | INT64 | Minutes until game start |
| `data_source` | STRING | 'current', 'historical', 'backfill' |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `player_lookup`, `game_date`, `bookmaker`

---

#### Additional Raw Tables

| Table | Description |
|-------|-------------|
| `bdl_standings` | Team standings from Ball Don't Lie |
| `bdl_active_players` | Active player list from Ball Don't Lie |
| `bdl_injuries` | Injury reports from Ball Don't Lie |
| `nbac_play_by_play` | NBA.com play-by-play events |
| `nbac_injury_report` | NBA.com official injury report |
| `nbac_player_list` | NBA.com player roster |
| `nbac_referee` | Game referee assignments |
| `espn_boxscore` | ESPN box score data |
| `espn_team_roster` | ESPN team rosters |
| `bettingpros_player_points_props` | BettingPros prop data |
| `odds_api_game_lines` | Game spread/total lines |
| `bigdataball_play_by_play` | Big Ball Data play-by-play |

---

### nba_analytics - Phase 3 Analytics

**Purpose:** Historical player and team performance with calculated metrics. Enriched data ready for predictions.

#### `player_game_summary`
Complete player performance with shot zone tracking and multi-source fallback.

| Column | Type | Description |
|--------|------|-------------|
| `player_lookup` | STRING | Normalized player identifier |
| `universal_player_id` | STRING | Universal ID from registry |
| `player_full_name` | STRING | Display name |
| `game_id` | STRING | Unique game identifier |
| `game_date` | DATE | Game date (partition key) |
| `team_abbr` | STRING | Player's team |
| `opponent_team_abbr` | STRING | Opposing team |
| `season_year` | INT64 | Season year |
| `points` | INT64 | Total points |
| `minutes_played` | NUMERIC(5,1) | Minutes played |
| `assists` | INT64 | Assists |
| `offensive_rebounds` | INT64 | Offensive rebounds |
| `defensive_rebounds` | INT64 | Defensive rebounds |
| `steals` | INT64 | Steals |
| `blocks` | INT64 | Blocks |
| `turnovers` | INT64 | Turnovers |
| `fg_attempts` | INT64 | Field goal attempts |
| `fg_makes` | INT64 | Field goal makes |
| `three_pt_attempts` | INT64 | Three-point attempts |
| `three_pt_makes` | INT64 | Three-point makes |
| `paint_attempts` | INT64 | Paint shot attempts |
| `paint_makes` | INT64 | Paint shot makes |
| `mid_range_attempts` | INT64 | Mid-range attempts |
| `mid_range_makes` | INT64 | Mid-range makes |
| `usage_rate` | NUMERIC(6,2) | Percentage of team plays used |
| `ts_pct` | NUMERIC(5,3) | True shooting percentage |
| `efg_pct` | NUMERIC(5,3) | Effective FG percentage |
| `points_line` | NUMERIC(4,1) | Betting line for points |
| `over_under_result` | STRING | 'OVER', 'UNDER', or NULL |
| `margin` | NUMERIC(6,2) | Actual points minus line |
| `data_quality_tier` | STRING | 'high', 'medium', 'low' |
| `primary_source_used` | STRING | Data source used |
| `shot_zones_estimated` | BOOLEAN | TRUE if estimated |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `universal_player_id`, `player_lookup`, `team_abbr`, `game_date`

---

#### `team_offense_game_summary`
Team offensive performance with shot zone tracking.

| Column | Type | Description |
|--------|------|-------------|
| `game_id` | STRING | Unique game identifier |
| `game_date` | DATE | Game date (partition key) |
| `team_abbr` | STRING | Team abbreviation |
| `opponent_team_abbr` | STRING | Opposing team |
| `season_year` | INT64 | Season year |
| `points_scored` | INT64 | Total points scored |
| `fg_attempts` | INT64 | Field goal attempts |
| `fg_makes` | INT64 | Field goal makes |
| `three_pt_attempts` | INT64 | Three-point attempts |
| `three_pt_makes` | INT64 | Three-point makes |
| `ft_attempts` | INT64 | Free throw attempts |
| `ft_makes` | INT64 | Free throw makes |
| `rebounds` | INT64 | Total rebounds |
| `assists` | INT64 | Assists |
| `turnovers` | INT64 | Turnovers |
| `offensive_rating` | NUMERIC(6,2) | Points per 100 possessions |
| `pace` | NUMERIC(5,1) | Possessions per 48 minutes |
| `ts_pct` | NUMERIC(5,3) | Team true shooting % |
| `home_game` | BOOLEAN | Home team flag |
| `win_flag` | BOOLEAN | Team won flag |
| `margin_of_victory` | INT64 | Point margin |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `team_abbr`, `game_date`, `home_game`

---

#### `team_defense_game_summary`
Team defensive performance aggregated from opponent stats.

| Column | Type | Description |
|--------|------|-------------|
| `game_id` | STRING | Unique game identifier |
| `game_date` | DATE | Game date (partition key) |
| `defending_team_abbr` | STRING | Team playing defense |
| `opponent_team_abbr` | STRING | Offensive team |
| `season_year` | INT64 | Season year |
| `points_allowed` | INT64 | Points allowed |
| `opp_fg_attempts` | INT64 | FG attempts allowed |
| `opp_fg_makes` | INT64 | FG makes allowed |
| `opp_three_pt_attempts` | INT64 | 3PT attempts allowed |
| `opp_three_pt_makes` | INT64 | 3PT makes allowed |
| `turnovers_forced` | INT64 | Turnovers forced |
| `steals` | INT64 | Steals |
| `defensive_rebounds` | INT64 | Defensive rebounds |
| `defensive_rating` | NUMERIC(6,2) | Points allowed per 100 poss |
| `data_quality_tier` | STRING | 'high', 'medium', 'low' |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `defending_team_abbr`, `game_date`, `data_quality_tier`

---

#### `upcoming_player_game_context`
Pre-game context for player predictions.

| Column | Type | Description |
|--------|------|-------------|
| `player_lookup` | STRING | Normalized player identifier |
| `universal_player_id` | STRING | Universal ID from registry |
| `game_id` | STRING | Upcoming game identifier |
| `game_date` | DATE | Game date (partition key) |
| `team_abbr` | STRING | Player's team |
| `opponent_team_abbr` | STRING | Opposing team |
| `has_prop_line` | BOOLEAN | Has betting prop line |
| `current_points_line` | NUMERIC(4,1) | Current prop line |
| `opening_points_line` | NUMERIC(4,1) | Opening prop line |
| `line_movement` | NUMERIC(4,1) | Current - opening |
| `game_spread` | NUMERIC(4,1) | Current point spread |
| `game_total` | NUMERIC(5,1) | Over/under total |
| `days_rest` | INT64 | Rest days since last game |
| `back_to_back` | BOOLEAN | Back-to-back game |
| `games_in_last_7_days` | INT64 | Weekly game count |
| `minutes_in_last_7_days` | INT64 | Weekly minutes |
| `points_avg_last_5` | NUMERIC(5,1) | Recent scoring average |
| `points_avg_last_10` | NUMERIC(5,1) | Broader scoring trend |
| `prop_over_streak` | INT64 | Current over streak |
| `prop_under_streak` | INT64 | Current under streak |
| `home_game` | BOOLEAN | Home vs away |
| `player_status` | STRING | Injury status |
| `data_quality_tier` | STRING | 'high', 'medium', 'low' |
| `is_production_ready` | BOOLEAN | All windows complete |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `player_lookup`, `universal_player_id`, `game_date`

---

### nba_precompute - Phase 4 Precompute

**Purpose:** Pre-computed aggregations and cached calculations shared across player reports. Disposable performance optimization layer.

#### `team_defense_zone_analysis`
Team defensive performance by shot zone (last 15 games rolling).

| Column | Type | Description |
|--------|------|-------------|
| `team_abbr` | STRING | Team abbreviation |
| `analysis_date` | DATE | Analysis date (partition key) |
| `paint_pct_allowed_last_15` | NUMERIC(5,3) | Paint FG% allowed |
| `paint_attempts_allowed_per_game` | NUMERIC(5,1) | Paint attempts/game |
| `paint_defense_vs_league_avg` | NUMERIC(5,2) | vs league average |
| `mid_range_pct_allowed_last_15` | NUMERIC(5,3) | Mid-range FG% allowed |
| `mid_range_defense_vs_league_avg` | NUMERIC(5,2) | vs league average |
| `three_pt_pct_allowed_last_15` | NUMERIC(5,3) | 3PT% allowed |
| `three_pt_defense_vs_league_avg` | NUMERIC(5,2) | vs league average |
| `defensive_rating_last_15` | NUMERIC(6,2) | Points per 100 poss |
| `games_in_sample` | INT64 | Games in calculation |
| `strongest_zone` | STRING | Best defensive zone |
| `weakest_zone` | STRING | Worst defensive zone |
| `data_quality_tier` | STRING | 'high', 'medium', 'low' |
| `early_season_flag` | BOOLEAN | Insufficient data |

**Partitioned by:** `analysis_date`
**Clustered by:** `team_abbr`, `analysis_date`
**Retention:** 90 days

---

#### `player_composite_factors`
Pre-calculated composite adjustment factors for predictions.

| Column | Type | Description |
|--------|------|-------------|
| `player_lookup` | STRING | Normalized player identifier |
| `universal_player_id` | STRING | Universal ID from registry |
| `game_date` | DATE | Game date (partition key) |
| `game_id` | STRING | Game identifier |
| `fatigue_score` | INT64 | 0-100 (100 = fresh) |
| `shot_zone_mismatch_score` | NUMERIC(4,1) | -10.0 to +10.0 |
| `pace_score` | NUMERIC(3,1) | -3.0 to +3.0 |
| `usage_spike_score` | NUMERIC(3,1) | -3.0 to +3.0 |
| `total_composite_adjustment` | NUMERIC(5,2) | Sum of all factors |
| `fatigue_context_json` | STRING | JSON with fatigue details |
| `shot_zone_context_json` | STRING | JSON with zone matchup |
| `data_completeness_pct` | NUMERIC(5,2) | % data available |
| `has_warnings` | BOOLEAN | Calculation warnings |
| `is_production_ready` | BOOLEAN | Ready for production |
| `data_hash` | STRING | SHA256 hash for idempotency |

**Partitioned by:** `game_date`
**Clustered by:** `player_lookup`, `universal_player_id`, `game_date`

---

#### Additional Precompute Tables

| Table | Description |
|-------|-------------|
| `player_shot_zone_analysis` | Player shot distribution by zone |
| `player_daily_cache` | Daily player metrics cache |
| `daily_game_context` | Game-level context data |
| `daily_opponent_defense_zones` | Opponent defensive profiles |

---

### nba_predictions - Phase 5 Predictions

**Purpose:** ML model predictions and accuracy tracking. The core product output.

#### `prediction_systems`
Registry of all prediction systems.

| Column | Type | Description |
|--------|------|-------------|
| `system_id` | STRING | Unique system ID |
| `system_name` | STRING | Human-readable name |
| `system_type` | STRING | 'baseline', 'rule_based', 'ml', 'ensemble' |
| `version` | STRING | Semantic version |
| `active` | BOOLEAN | Running in production |
| `is_champion` | BOOLEAN | Primary recommendation system |
| `config` | JSON | System configuration |
| `lifetime_accuracy` | NUMERIC(5,3) | Overall accuracy |
| `system_category` | STRING | Category classification |
| `requires_ml_model` | BOOLEAN | Needs ML model |

**Systems:**
- `moving_average_baseline` - Weighted recent averages
- `zone_matchup_v1` - Shot zone matchup rules
- `similarity_balanced_v1` - Similar game matching
- `xgboost_v1` - XGBoost ML model
- `meta_ensemble_v1` - Ensemble of all systems (champion)

---

#### `player_prop_predictions`
All predictions from all systems.

| Column | Type | Description |
|--------|------|-------------|
| `prediction_id` | STRING | Unique prediction ID |
| `system_id` | STRING | Which system made prediction |
| `player_lookup` | STRING | Player identifier |
| `game_id` | STRING | Game identifier |
| `game_date` | DATE | Game date (partition key) |
| `predicted_points` | NUMERIC(5,1) | System's prediction |
| `prop_line` | NUMERIC(4,1) | Betting line |
| `recommendation` | STRING | 'OVER', 'UNDER', 'PASS' |
| `confidence_score` | NUMERIC(5,2) | 0-100 confidence |
| `feature_version` | STRING | Feature set version |
| `created_at` | TIMESTAMP | Prediction creation time |

**Partitioned by:** `game_date`
**Clustered by:** `player_lookup`, `system_id`, `game_date`

---

#### `prediction_grades`
Grades predictions against actual results.

| Column | Type | Description |
|--------|------|-------------|
| `prediction_id` | STRING | FK to player_prop_predictions |
| `player_lookup` | STRING | Player identifier |
| `game_id` | STRING | Game identifier |
| `game_date` | DATE | Game date (partition key) |
| `system_id` | STRING | Prediction system |
| `predicted_points` | NUMERIC(5,1) | What was predicted |
| `confidence_score` | NUMERIC(5,2) | Confidence (0-1) |
| `recommendation` | STRING | OVER, UNDER, PASS |
| `points_line` | NUMERIC(4,1) | Betting line used |
| `actual_points` | INT64 | Actual result |
| `actual_vs_line` | STRING | OVER, UNDER, PUSH |
| `prediction_correct` | BOOLEAN | TRUE if correct |
| `margin_of_error` | NUMERIC(5,2) | |predicted - actual| |
| `line_margin` | NUMERIC(5,2) | actual - line |
| `graded_at` | TIMESTAMP | When graded |
| `player_dnp` | BOOLEAN | Player did not play |

**Partitioned by:** `game_date`
**Clustered by:** `player_lookup`, `prediction_correct`, `confidence_score`

---

#### `ml_feature_store_v2`
Cached 25-feature vectors for fast prediction (written by Phase 4).

| Column | Type | Description |
|--------|------|-------------|
| `player_lookup` | STRING | Player identifier |
| `game_date` | DATE | Game date (partition key) |
| `game_id` | STRING | Game identifier |
| `features` | ARRAY<FLOAT64> | [f0, f1, ..., f24] |
| `feature_names` | ARRAY<STRING> | Feature name array |
| `feature_count` | INT64 | 25 |
| `feature_version` | STRING | 'v1_baseline_25' |
| `feature_quality_score` | NUMERIC(5,2) | 0-100 quality metric |
| `opponent_team_abbr` | STRING | Opponent team |
| `is_home` | BOOLEAN | Home game flag |
| `days_rest` | INT64 | Days of rest |

**Partitioned by:** `game_date`
**Clustered by:** `player_lookup`, `feature_version`, `game_date`

---

### nba_reference - Player Identity

**Purpose:** Player identity registry with universal player IDs. Continuously updated.

#### `nba_players_registry`
Authoritative registry of valid NBA players.

| Column | Type | Description |
|--------|------|-------------|
| `universal_player_id` | STRING | Universal ID (e.g., "kjmartin_001") |
| `player_name` | STRING | Official NBA.com name |
| `player_lookup` | STRING | Normalized lookup key |
| `team_abbr` | STRING | Team affiliation |
| `season` | STRING | "2023-24" format |
| `first_game_date` | DATE | First game this season |
| `last_game_date` | DATE | Most recent game |
| `games_played` | INT64 | Total games |
| `jersey_number` | INT64 | Current jersey number |
| `position` | STRING | Listed position |
| `source_priority` | STRING | Data source priority |
| `confidence_score` | FLOAT64 | 0.0-1.0 confidence |
| `last_processor` | STRING | 'gamebook' or 'roster' |
| `last_gamebook_activity_date` | DATE | Last game processed |
| `last_roster_activity_date` | DATE | Last roster update |

**Clustered by:** `universal_player_id`, `player_lookup`, `season`, `team_abbr`

---

### nba_static - Static Reference Data

**Purpose:** Team locations, travel distances, and league patterns. Rarely updated.

| Table | Description |
|-------|-------------|
| `team_locations` | Team city/state/timezone |
| `travel_distances` | Distance between arenas |
| `league_pattern_effects` | Seasonal patterns |

---

### nba_processing - Processing Monitoring

**Purpose:** Pipeline execution logs, data quality tracking, and monitoring.

| Table | Description |
|-------|-------------|
| `processing_log` | Processor execution logs |
| `precompute_data_issues` | Data quality issues |
| `precompute_failures` | Failed processing runs |
| `registry_failures` | Player registry failures |
| `reprocessing_runs` | Reprocessing history |

---

### nba_orchestration - Pipeline Orchestration

**Purpose:** Scraper scheduling and workflow coordination.

#### `workflow_executions`
Tracks workflow execution attempts.

| Column | Type | Description |
|--------|------|-------------|
| `execution_id` | STRING | Unique execution ID (UUID) |
| `execution_time` | TIMESTAMP | When started (partition key) |
| `workflow_name` | STRING | Workflow being executed |
| `decision_id` | STRING | Links to workflow_decisions |
| `scrapers_requested` | ARRAY<STRING> | Scrapers to execute |
| `scrapers_triggered` | INT64 | Scrapers actually called |
| `scrapers_succeeded` | INT64 | Successful completions |
| `scrapers_failed` | INT64 | Failed scrapers |
| `status` | STRING | 'started', 'completed', 'failed' |
| `duration_seconds` | FLOAT64 | Total duration |
| `error_message` | STRING | Error if failed |

**Partitioned by:** `DATE(execution_time)`
**Clustered by:** `workflow_name`, `status`
**Retention:** 90 days

---

#### Additional Orchestration Tables

| Table | Description |
|-------|-------------|
| `workflow_decisions` | Workflow run/skip decisions |
| `scraper_execution_log` | Individual scraper executions |
| `daily_expected_schedule` | Expected daily game schedule |
| `circuit_breaker_state` | Circuit breaker status |
| `cleanup_operations` | Data cleanup tracking |

---

## MLB Datasets

The platform also supports MLB pitcher strikeout predictions using a parallel dataset structure.

### mlb_raw - Phase 2 Raw Data

#### `bdl_pitcher_stats`
MLB pitcher per-game statistics.

| Column | Type | Description |
|--------|------|-------------|
| `game_id` | STRING | BDL game ID |
| `game_date` | DATE | Game date (partition key) |
| `season_year` | INT64 | Season year |
| `bdl_player_id` | INT64 | Ball Don't Lie player ID |
| `player_full_name` | STRING | Full player name |
| `player_lookup` | STRING | Normalized lookup key |
| `team_abbr` | STRING | Pitcher's team |
| `strikeouts` | INT64 | **TARGET VARIABLE** |
| `innings_pitched` | NUMERIC(4,1) | Innings pitched |
| `pitch_count` | INT64 | Total pitches |
| `strikes` | INT64 | Total strikes |
| `walks_allowed` | INT64 | Walks |
| `hits_allowed` | INT64 | Hits allowed |
| `earned_runs` | INT64 | Earned runs |
| `era` | NUMERIC(5,2) | Earned run average |
| `win` | BOOLEAN | Got the win |
| `loss` | BOOLEAN | Got the loss |
| `save` | BOOLEAN | Got the save |

**Partitioned by:** `game_date`
**Clustered by:** `player_lookup`, `team_abbr`, `game_date`

---

#### Additional MLB Tables

| Dataset | Tables |
|---------|--------|
| `mlb_raw` | `bdl_games`, `bdl_active_players`, `bdl_injuries`, `bdl_batter_stats`, `bdl_season_stats`, `bdl_player_splits`, `mlb_schedule`, `mlb_lineups`, `bp_props`, `fangraphs_pitcher_season_stats` |
| `mlb_analytics` | `batter_game_summary` |
| `mlb_precompute` | `ml_feature_store` |
| `mlb_predictions` | (to be implemented) |
| `mlb_reference` | `mlb_players_registry` |

---

## Key Relationships

### Player Identification Flow

```
nba_raw.nbac_gamebook_player_stats
         |
         | player_lookup
         v
nba_reference.nba_players_registry -----> universal_player_id
         |
         | player_lookup, universal_player_id
         v
nba_analytics.player_game_summary
         |
         v
nba_precompute.player_composite_factors
         |
         v
nba_predictions.player_prop_predictions
```

### Data Pipeline Flow

```
Phase 2 (nba_raw)
    |
    | Multiple raw sources per entity
    v
Phase 3 (nba_analytics)
    |
    | Unified, enriched records
    v
Phase 4 (nba_precompute)
    |
    | Aggregated, cached calculations
    v
Phase 5 (nba_predictions)
    |
    | Predictions + grading
    v
Output (Recommendations)
```

### Join Keys

| From Table | To Table | Join Key(s) |
|------------|----------|-------------|
| Any raw table | player_game_summary | `player_lookup`, `game_id` |
| player_game_summary | composite_factors | `player_lookup`, `game_date` |
| player_prop_predictions | prediction_grades | `prediction_id` |
| workflow_executions | scraper_execution_log | `scraper_execution_ids` |
| workflow_executions | workflow_decisions | `decision_id` |

---

## Common Patterns

### Smart Idempotency (Pattern #14)

All tables include a `data_hash` column containing a SHA256 hash of meaningful fields. This enables:
- Skipping redundant writes when data unchanged
- Detecting meaningful changes for reprocessing
- Efficient incremental updates

```sql
-- Hash typically excludes: processed_at, created_at, source tracking fields
-- Hash includes: all business/measurement fields
```

### Partition Requirements

All date-partitioned tables require partition filters:

```sql
-- CORRECT
SELECT * FROM player_game_summary
WHERE player_lookup = 'lebronjames'
  AND game_date >= '2024-01-01';

-- INCORRECT (will fail or scan all data)
SELECT * FROM player_game_summary
WHERE player_lookup = 'lebronjames';
```

### Source Tracking Fields

Phase 3/4 tables include source tracking (per v4.0 dependency tracking):

```sql
-- For each upstream source:
source_{prefix}_last_updated TIMESTAMP      -- When source was processed
source_{prefix}_rows_found INT64            -- Rows found in query
source_{prefix}_completeness_pct NUMERIC    -- % of expected data
source_{prefix}_hash STRING                 -- Hash for smart reprocessing
```

### Data Quality Tiers

Most analytics tables include `data_quality_tier`:
- **high**: All critical sources present, 10+ games sample
- **medium**: Critical sources present with minor gaps, 5-9 games
- **low**: Missing sources or <5 games sample

### Early Season Handling

Tables may include early season placeholders:
- `early_season_flag` = TRUE when insufficient historical data
- Business metrics set to NULL
- Downstream should filter: `WHERE early_season_flag IS NULL OR early_season_flag = FALSE`

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-23 | 1.0 | Initial comprehensive schema documentation |

---

## Questions or Issues?

- **Schema Questions:** Review individual `.sql` files in `schemas/bigquery/`
- **Data Flow:** See `docs/06-grading/NBA-GRADING-SYSTEM.md`
- **Pipeline Architecture:** See `docs/` for phase-specific documentation
