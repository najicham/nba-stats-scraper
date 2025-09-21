-- File: schemas/bigquery/odds_api_props_tables.sql
--
-- BigQuery schema for Odds API player props data
-- Tracks player prop lines and odds over time with snapshots

-- Create the main props table
CREATE TABLE IF NOT EXISTS `nba_raw.odds_api_player_points_props` (
  -- Game identifiers
  game_id STRING NOT NULL,           -- "20231024_LAL_DEN"
  odds_api_event_id STRING NOT NULL,
  game_date DATE NOT NULL,
  game_start_time TIMESTAMP,         
  
  -- Teams (abbreviated only)
  home_team_abbr STRING NOT NULL,
  away_team_abbr STRING NOT NULL,
  
  -- Snapshot tracking
  snapshot_timestamp TIMESTAMP NOT NULL,  -- From filename
  snapshot_tag STRING,                    -- "snap-2130"
  capture_timestamp TIMESTAMP,            -- When scraper ran
  minutes_before_tipoff INT64,            -- Calculated: (game_start_time - snapshot_timestamp) in minutes
  
  -- Prop details
  bookmaker STRING NOT NULL,
  player_name STRING NOT NULL,            -- "LeBron James"
  player_lookup STRING,                   -- "lebronjames"
  
  -- Points line
  points_line FLOAT64 NOT NULL,
  over_price FLOAT64,
  over_price_american INT64,
  under_price FLOAT64,
  under_price_american INT64,
  
  -- Metadata
  bookmaker_last_update TIMESTAMP,        -- From API response
  source_file_path STRING,                -- Full GCS path
  processing_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, game_date, bookmaker
OPTIONS(
  description = "Player points prop odds from The Odds API with historical snapshots",
  labels = [("source", "odds_api"), ("type", "props"), ("sport", "nba")]
);

-- Create view for latest props per game
CREATE OR REPLACE VIEW `nba_raw.odds_api_latest_props` AS
WITH latest_snapshots AS (
  SELECT 
    game_id,
    player_name,
    bookmaker,
    MAX(snapshot_timestamp) as latest_snapshot
  FROM `nba_raw.odds_api_player_points_props`
  GROUP BY game_id, player_name, bookmaker
)
SELECT 
  p.*,
  RANK() OVER (
    PARTITION BY p.game_id, p.player_name 
    ORDER BY p.snapshot_timestamp DESC
  ) as snapshot_rank
FROM `nba_raw.odds_api_player_points_props` p
INNER JOIN latest_snapshots l
  ON p.game_id = l.game_id 
  AND p.player_name = l.player_name 
  AND p.bookmaker = l.bookmaker
  AND p.snapshot_timestamp = l.latest_snapshot;

-- Create view for line movement analysis
CREATE OR REPLACE VIEW `nba_raw.odds_api_line_movements` AS
WITH prop_changes AS (
  SELECT 
    game_id,
    player_name,
    bookmaker,
    points_line,
    over_price,
    under_price,
    minutes_before_tipoff,
    snapshot_timestamp,
    LAG(points_line) OVER (
      PARTITION BY game_id, player_name, bookmaker 
      ORDER BY snapshot_timestamp
    ) as prev_line,
    LAG(over_price) OVER (
      PARTITION BY game_id, player_name, bookmaker 
      ORDER BY snapshot_timestamp
    ) as prev_over_price,
    LAG(under_price) OVER (
      PARTITION BY game_id, player_name, bookmaker 
      ORDER BY snapshot_timestamp
    ) as prev_under_price
  FROM `nba_raw.odds_api_player_points_props`
)
SELECT 
  *,
  points_line - prev_line as line_change,
  over_price - prev_over_price as over_price_change,
  under_price - prev_under_price as under_price_change,
  CASE 
    WHEN points_line != prev_line THEN 'LINE_MOVED'
    WHEN over_price != prev_over_price OR under_price != prev_under_price THEN 'ODDS_CHANGED'
    ELSE 'NO_CHANGE'
  END as movement_type
FROM prop_changes
WHERE prev_line IS NOT NULL;

-- Sample queries for analysis
/*
-- Get all props for a specific game
SELECT * 
FROM `nba_raw.odds_api_player_points_props`
WHERE game_id = '20231024_LAL_DEN'
ORDER BY player_name, bookmaker, snapshot_timestamp;

-- Track line movements for a player
SELECT 
  player_name,
  bookmaker,
  points_line,
  over_price_american,
  under_price_american,
  minutes_before_tipoff,
  snapshot_timestamp
FROM `nba_raw.odds_api_player_points_props`
WHERE game_id = '20231024_LAL_DEN'
  AND player_name = 'LeBron James'
ORDER BY snapshot_timestamp;

-- Find biggest line moves
SELECT 
  game_id,
  player_name,
  bookmaker,
  line_change,
  minutes_before_tipoff,
  snapshot_timestamp
FROM `nba_raw.odds_api_line_movements`
WHERE ABS(line_change) >= 1
ORDER BY ABS(line_change) DESC
LIMIT 100;

-- Player props summary by game
SELECT 
  game_date,
  COUNT(DISTINCT game_id) as games,
  COUNT(DISTINCT player_name) as players,
  COUNT(DISTINCT bookmaker) as bookmakers,
  COUNT(*) as total_records,
  AVG(points_line) as avg_line,
  MIN(minutes_before_tipoff) as closest_to_tipoff
FROM `nba_raw.odds_api_player_points_props`
GROUP BY game_date
ORDER BY game_date DESC;
*/