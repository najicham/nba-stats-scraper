-- File: schemas/bigquery/bettingpros_player_props_tables.sql
-- Description: BigQuery table schemas for BettingPros player props data
-- BettingPros Player Points Props Tables
-- Description: Alternative prop betting data source for line shopping and backup validation

CREATE TABLE IF NOT EXISTS `nba_raw.bettingpros_player_points_props` (
  -- Core identifiers (aligned with Odds API where possible)  
  game_date DATE NOT NULL,
  market_type STRING NOT NULL,  -- "points" (starting scope)
  market_id INT64 NOT NULL,     -- BettingPros market ID (156 for points)
  bp_event_id INT64 NOT NULL,   -- BettingPros event ID
  offer_id STRING NOT NULL,     -- Unique offer ID per player prop
  bet_side STRING NOT NULL,     -- "over" or "under" (clearer than selection_type)
  
  -- Player identification (aligned with Odds API)
  bp_player_id INT64 NOT NULL,  -- BettingPros player ID
  player_name STRING NOT NULL,  -- "Mitchell Robinson"
  player_lookup STRING NOT NULL, -- Normalized: "mitchellrobinson"
  player_team STRING NOT NULL,  -- Team from BettingPros (including "FA")
  player_position STRING,       -- Position code
  
  -- Team validation (comprehensive data quality framework)
  team_source STRING NOT NULL,           -- Always "bettingpros"
  has_team_issues BOOLEAN NOT NULL,      -- TRUE for ALL records initially
  validated_team STRING,                 -- Team from box score validation (when available)
  validation_confidence FLOAT64 NOT NULL, -- Time-based + validation scoring (never 1.0 initially)
  validation_method STRING NOT NULL,     -- How confidence was determined
  validation_notes STRING,               -- Validation details
  player_complications STRING,           -- "traded_gameday", "g_league_callup", "injury_after_lines", etc.
  
  -- Sportsbook details (aligned with Odds API)
  book_id INT64 NOT NULL,       -- Sportsbook ID
  bookmaker STRING NOT NULL,    -- "BetMGM", "BettingPros Consensus"
  line_id STRING,               -- Sportsbook line ID (helps with line tracking)
  points_line FLOAT64 NOT NULL, -- Points line (5.5, 10.5, etc.)
  odds_american INT64 NOT NULL, -- American odds (-143, +105)
  is_active BOOLEAN NOT NULL,   -- Line currently active
  is_best_line BOOLEAN NOT NULL, -- Flagged as best available
  bookmaker_last_update TIMESTAMP NOT NULL, -- When sportsbook updated line
  
  -- Opening line tracking (BettingPros-specific intelligence)
  opening_line FLOAT64,         -- Original opening line
  opening_odds INT64,           -- Original opening odds
  opening_book_id INT64,        -- Book that set opening
  opening_timestamp TIMESTAMP,  -- Opening line timestamp
  
  -- Processing metadata (standard processor pattern)
  source_file_path STRING NOT NULL,  -- GCS path
  created_at TIMESTAMP NOT NULL,     -- When record first created

  -- Smart Idempotency (Pattern #14)
  data_hash STRING,                  -- SHA256 hash of meaningful fields: player_lookup, game_date, market_type, bookmaker, bet_side, points_line, is_best_line

  processed_at TIMESTAMP NOT NULL    -- When record last processed
)
PARTITION BY game_date
CLUSTER BY player_lookup, bookmaker, has_team_issues, bet_side
OPTIONS (
  description = "BettingPros player prop betting lines for line shopping analysis and backup validation. Flattened structure with one record per player-sportsbook-bet_side combination. Comprehensive team validation framework tracks data quality issues. Uses smart idempotency to skip redundant writes when lines unchanged.",
  require_partition_filter = true
);

-- Helpful views for common business queries
CREATE OR REPLACE VIEW `nba_raw.bettingpros_props_recent` AS
SELECT *
FROM `nba_raw.bettingpros_player_points_props`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

CREATE OR REPLACE VIEW `nba_raw.bettingpros_props_validated` AS
SELECT *
FROM `nba_raw.bettingpros_player_points_props`
WHERE validation_confidence >= 0.8;

CREATE OR REPLACE VIEW `nba_raw.bettingpros_props_best_lines` AS
SELECT *
FROM `nba_raw.bettingpros_player_points_props`
WHERE is_best_line = TRUE
  AND is_active = TRUE
  AND game_date >= CURRENT_DATE();

-- Data quality monitoring view
CREATE OR REPLACE VIEW `nba_raw.bettingpros_validation_summary` AS
SELECT 
  game_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT player_lookup) as unique_players,
  COUNT(DISTINCT bookmaker) as unique_bookmakers,
  AVG(validation_confidence) as avg_confidence,
  COUNT(CASE WHEN has_team_issues = TRUE THEN 1 END) as records_needing_validation,
  COUNT(CASE WHEN player_team = 'FA' THEN 1 END) as free_agent_records,
  COUNT(CASE WHEN player_complications IS NOT NULL THEN 1 END) as records_with_complications
FROM `nba_raw.bettingpros_player_points_props`
GROUP BY game_date
ORDER BY game_date DESC;