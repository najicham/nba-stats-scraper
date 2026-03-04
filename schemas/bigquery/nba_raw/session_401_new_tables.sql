-- Session 401: New data source tables for signals pipeline
-- All tables partitioned by game_date (except covers_referee_stats by season)
-- Run with: bq query --use_legacy_sql=false < schemas/bigquery/nba_raw/session_401_new_tables.sql

-- 1. NumberFire Projections
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.numberfire_projections` (
  game_date DATE NOT NULL,
  player_name STRING,
  player_lookup STRING,
  team STRING,
  position STRING,
  projected_points FLOAT64,
  projected_minutes FLOAT64,
  projected_rebounds FLOAT64,
  projected_assists FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup
OPTIONS (
  description='NumberFire daily fantasy basketball projections for consensus signal'
);

-- 2. FantasyPros Projections
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.fantasypros_projections` (
  game_date DATE NOT NULL,
  player_name STRING,
  player_lookup STRING,
  team STRING,
  position STRING,
  projected_points FLOAT64,
  projected_minutes FLOAT64,
  projected_rebounds FLOAT64,
  projected_assists FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup
OPTIONS (
  description='FantasyPros consensus projections for consensus signal'
);

-- 3. TeamRankings Team Stats
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.teamrankings_team_stats` (
  game_date DATE NOT NULL,
  team STRING,
  pace FLOAT64,
  offensive_efficiency FLOAT64,
  defensive_efficiency FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY team
OPTIONS (
  description='TeamRankings team pace and efficiency stats for predicted pace signal'
);

-- 4. Hashtag Basketball Defense vs Position
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.hashtagbasketball_dvp` (
  game_date DATE NOT NULL,
  team STRING,
  position STRING,
  points_allowed FLOAT64,
  rebounds_allowed FLOAT64,
  assists_allowed FLOAT64,
  rank INT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY team, position
OPTIONS (
  description='Hashtag Basketball defense vs position stats for DvP signal'
);

-- 5. RotoWire Lineups
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.rotowire_lineups` (
  game_date DATE NOT NULL,
  game_time STRING,
  away_team STRING,
  home_team STRING,
  player_name STRING,
  player_lookup STRING,
  team STRING,
  position STRING,
  lineup_position INT64,
  is_starter BOOL,
  injury_status STRING,
  projected_minutes FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY team
OPTIONS (
  description='RotoWire projected starting lineups for minutes projection signal'
);

-- 6. Covers Referee Stats
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.covers_referee_stats` (
  season STRING NOT NULL,
  game_date DATE,
  referee_name STRING,
  games_officiated INT64,
  over_record STRING,
  under_record STRING,
  over_percentage FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY referee_name
OPTIONS (
  description='Covers.com referee O/U tendency stats for referee signal'
);

-- 7. DailyFantasyFuel Projections
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.dailyfantasyfuel_projections` (
  game_date DATE NOT NULL,
  player_name STRING,
  player_lookup STRING,
  team STRING,
  position STRING,
  projected_points FLOAT64,
  projected_minutes FLOAT64,
  salary FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup
OPTIONS (
  description='DailyFantasyFuel projections for consensus signal'
);

-- 8. Dimers Projections
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.dimers_projections` (
  game_date DATE NOT NULL,
  player_name STRING,
  player_lookup STRING,
  team STRING,
  position STRING,
  projected_points FLOAT64,
  projected_minutes FLOAT64,
  salary FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup
OPTIONS (
  description='Dimers projections for consensus signal'
);

-- 9. NBA Tracking Stats
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.nba_tracking_stats` (
  game_date DATE NOT NULL,
  player_name STRING,
  player_lookup STRING,
  team STRING,
  touches FLOAT64,
  drives FLOAT64,
  catch_shoot_fga FLOAT64,
  catch_shoot_fg_pct FLOAT64,
  pull_up_fga FLOAT64,
  pull_up_fg_pct FLOAT64,
  paint_touches FLOAT64,
  minutes FLOAT64,
  usage_pct FLOAT64,
  pace FLOAT64,
  poss FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY player_lookup
OPTIONS (
  description='NBA.com player tracking stats for usage and pace signals'
);

-- 10. VSiN Betting Splits
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.vsin_betting_splits` (
  game_date DATE NOT NULL,
  away_team STRING,
  home_team STRING,
  total_line FLOAT64,
  over_ticket_pct FLOAT64,
  under_ticket_pct FLOAT64,
  over_money_pct FLOAT64,
  under_money_pct FLOAT64,
  spread FLOAT64,
  home_spread_pct FLOAT64,
  away_spread_pct FLOAT64,
  source_file_path STRING,
  scraped_at TIMESTAMP,
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY home_team
OPTIONS (
  description='VSiN public betting percentage splits for sharp money signal'
);
