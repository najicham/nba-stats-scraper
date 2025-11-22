-- File: schemas/bigquery/odds_game_lines_tables.sql
-- Description: BigQuery table schemas for Odds API game lines history data
-- Odds Game Lines History Tables
-- Description: Historical snapshots of game lines (spreads/totals) from various sportsbooks

CREATE TABLE IF NOT EXISTS `nba_raw.odds_api_game_lines` (
  -- Snapshot metadata
  snapshot_timestamp TIMESTAMP NOT NULL,
  previous_snapshot_timestamp TIMESTAMP,
  next_snapshot_timestamp TIMESTAMP,
  
  -- Game identifiers  
  game_id STRING NOT NULL,
  sport_key STRING NOT NULL,
  sport_title STRING NOT NULL,
  commence_time TIMESTAMP NOT NULL,
  game_date DATE NOT NULL,
  
  -- Teams
  home_team STRING NOT NULL,
  away_team STRING NOT NULL,
  home_team_abbr STRING,
  away_team_abbr STRING,
  
  -- Bookmaker info
  bookmaker_key STRING NOT NULL,
  bookmaker_title STRING NOT NULL,
  bookmaker_last_update TIMESTAMP NOT NULL,
  
  -- Market info
  market_key STRING NOT NULL,  -- 'spreads' or 'totals'
  market_last_update TIMESTAMP NOT NULL,
  
  -- Outcome info
  outcome_name STRING NOT NULL,  -- Team name or 'Over'/'Under'
  outcome_price FLOAT64 NOT NULL,  -- Decimal odds
  outcome_point FLOAT64,  -- Spread value or total value
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  data_source STRING,  -- 'current' | 'historical' | 'backfill' | 'manual' | NULL (legacy)
  created_at TIMESTAMP NOT NULL,

  -- Smart Idempotency (Pattern #14)
  data_hash STRING,  -- SHA256 hash of meaningful fields: game_id, game_date, bookmaker_key, market_key, outcome_name, outcome_point, snapshot_timestamp

  processed_at TIMESTAMP NOT NULL
)
PARTITION BY game_date
CLUSTER BY game_id, bookmaker_key, market_key, snapshot_timestamp
OPTIONS (
  description = "Historical snapshots of NBA game lines (spreads and totals) from various sportsbooks via Odds API. data_source indicates collection method: 'current' (live scraper), 'historical' (backfill endpoint), 'backfill' (manual), 'manual' (corrections), or NULL (legacy). Uses smart idempotency to skip redundant writes when lines unchanged.",
  require_partition_filter = true
);

-- Helpful views for common queries
CREATE OR REPLACE VIEW `nba_raw.odds_api_game_lines_recent` AS
SELECT *
FROM `nba_raw.odds_api_game_lines`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

CREATE OR REPLACE VIEW `nba_raw.odds_api_game_lines_latest_by_game` AS
WITH ranked_snapshots AS (
  SELECT *,
    ROW_NUMBER() OVER (
      PARTITION BY game_id, bookmaker_key, market_key, outcome_name 
      ORDER BY snapshot_timestamp DESC
    ) as rn
  FROM `nba_raw.odds_api_game_lines`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
)
SELECT * EXCEPT(rn)
FROM ranked_snapshots 
WHERE rn = 1;

-- View for data source analysis
CREATE OR REPLACE VIEW `nba_raw.odds_api_game_lines_source_stats` AS
SELECT 
  game_date,
  data_source,
  COUNT(*) as row_count,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT bookmaker_key) as unique_bookmakers,
  MIN(snapshot_timestamp) as earliest_snapshot,
  MAX(snapshot_timestamp) as latest_snapshot,
  COUNTIF(previous_snapshot_timestamp IS NOT NULL) as has_previous_link,
  COUNTIF(next_snapshot_timestamp IS NOT NULL) as has_next_link
FROM `nba_raw.odds_api_game_lines`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY game_date, data_source
ORDER BY game_date DESC, data_source;

-- View for live-only data (excluding historical backfills)
CREATE OR REPLACE VIEW `nba_raw.odds_api_game_lines_live_only` AS
SELECT *
FROM `nba_raw.odds_api_game_lines`
WHERE data_source = 'current' OR data_source IS NULL;