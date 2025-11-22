-- File: schemas/bigquery/raw/nbac_schedule_tables.sql
-- Description: BigQuery table schemas for NBA.com schedule data
-- UPDATED: Added data_source and source_updated_at columns for scraper tracking

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_schedule` (
  -- Core identifiers
  game_id STRING NOT NULL,
  game_code STRING NOT NULL,
  season STRING NOT NULL,                    -- "2023" 
  season_nba_format STRING NOT NULL,         -- "2023-24"
  season_year INT64 NOT NULL,                -- 2023 for 2023-24 season
  
  -- Game details
  game_date DATE NOT NULL,
  game_date_est TIMESTAMP,                   -- Full timestamp with time
  game_status INT64,                         -- 1=scheduled, 2=in progress, 3=final
  game_status_text STRING,                   -- "Scheduled", "Final", etc.
  
  -- Teams
  home_team_id INT64 NOT NULL,
  home_team_tricode STRING NOT NULL,         -- "MIN", "DAL"  
  home_team_name STRING NOT NULL,            -- "Timberwolves"
  away_team_id INT64 NOT NULL,
  away_team_tricode STRING NOT NULL,         -- "DAL", "MIN"
  away_team_name STRING NOT NULL,            -- "Mavericks"
  
  -- Venue
  arena_name STRING,
  arena_city STRING,
  arena_state STRING,
  
  -- Broadcaster context (from scraper analysis)
  is_primetime BOOLEAN,                     -- ESPN/TNT/ABC variants
  has_national_tv BOOLEAN,                  -- Any national TV coverage
  primary_network STRING,                   -- Main national broadcaster
  traditional_networks STRING,              -- JSON array of traditional TV networks
  streaming_platforms STRING,               -- JSON array of streaming platforms
  
  -- Game type classification
  is_regular_season BOOLEAN,                -- Regular season game
  is_playoffs BOOLEAN,                      -- Any playoff game
  is_all_star BOOLEAN,                      -- All-Star weekend events
  is_emirates_cup BOOLEAN,                  -- NBA Cup/In-Season Tournament
  playoff_round STRING,                     -- Specific playoff round
  is_christmas BOOLEAN,                     -- Christmas Day game
  is_mlk_day BOOLEAN,                       -- Martin Luther King Jr. Day game
  
  -- Scheduling context
  day_of_week STRING,                       -- Day of week (lowercase)
  is_weekend BOOLEAN,                       -- Friday, Saturday, or Sunday
  time_slot STRING,                         -- Rough time classification
  
  -- Special venue context
  neutral_site_flag BOOLEAN,                -- Game at neutral venue (not home/away arena)
  international_game BOOLEAN,               -- Game outside US/Canada
  arena_timezone STRING,                    -- Arena timezone (e.g., "America/New_York")
  
  -- Game results (for completed games)
  home_team_score INT64,
  away_team_score INT64,
  winning_team_tricode STRING,
  
  -- =========================================================================
  -- NEW: Source tracking (added 2025-10-19)
  -- =========================================================================
  data_source STRING,                       -- "api_stats" or "cdn_static"
  source_updated_at TIMESTAMP,              -- When this source last updated the record
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  scrape_timestamp TIMESTAMP,
  created_at TIMESTAMP NOT NULL,

  -- Smart Idempotency (Pattern #14)
  data_hash STRING,  -- SHA256 hash of meaningful fields: game_id, game_date, game_time_utc, home_team_tricode, away_team_tricode, game_status

  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_date, data_source, home_team_tricode, away_team_tricode, season_year
OPTIONS (
  description = "NBA.com official game schedule with team, venue, and broadcast information. Source of truth for game timing and team matchups. Uses smart idempotency to skip redundant writes when schedule unchanged.",
  require_partition_filter = true
);

-- Create helpful views
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_current_season` AS
SELECT *
FROM `nba_raw.nbac_schedule`
WHERE season_year = (
  SELECT MAX(season_year) 
  FROM `nba_raw.nbac_schedule`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
);

CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_upcoming` AS
SELECT *
FROM `nba_raw.nbac_schedule`
WHERE game_date >= CURRENT_DATE()
  AND game_status = 1
ORDER BY game_date, game_date_est;

CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_recent` AS
SELECT *
FROM `nba_raw.nbac_schedule`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY game_date DESC;

-- Enhanced business analytics views
CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_primetime` AS
SELECT *
FROM `nba_raw.nbac_schedule`
WHERE is_primetime = TRUE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
ORDER BY game_date DESC;

CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_playoffs` AS
SELECT *
FROM `nba_raw.nbac_schedule`
WHERE is_playoffs = TRUE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
ORDER BY game_date, playoff_round;

CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_national_tv` AS
SELECT 
  game_date,
  home_team_tricode,
  away_team_tricode,
  primary_network,
  is_primetime,
  is_weekend,
  time_slot,
  game_status,
  data_source
FROM `nba_raw.nbac_schedule`
WHERE has_national_tv = TRUE
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
ORDER BY game_date DESC;

CREATE OR REPLACE VIEW `nba_raw.nbac_schedule_analytics` AS
SELECT 
  season_nba_format,
  data_source,
  COUNT(*) as total_games,
  COUNT(CASE WHEN is_primetime THEN 1 END) as primetime_games,
  COUNT(CASE WHEN has_national_tv THEN 1 END) as national_tv_games,
  COUNT(CASE WHEN is_weekend THEN 1 END) as weekend_games,
  COUNT(CASE WHEN is_christmas THEN 1 END) as christmas_games,
  COUNT(CASE WHEN is_playoffs THEN 1 END) as playoff_games,
  ROUND(COUNT(CASE WHEN is_primetime THEN 1 END) * 100.0 / COUNT(*), 1) as primetime_percentage
FROM `nba_raw.nbac_schedule`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 730 DAY)
GROUP BY season_nba_format, data_source
ORDER BY season_nba_format DESC, data_source;