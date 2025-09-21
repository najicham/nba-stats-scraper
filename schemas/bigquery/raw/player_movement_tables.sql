-- File: schemas/bigquery/player_movement_tables.sql
-- Description: BigQuery table schemas for NBA.com Player Movement data
-- NBA.com Player Movement Tables
-- Description: Complete NBA transaction history (trades, signings, waivers, G-League moves)

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_player_movement` (
  -- Core identifiers
  transaction_type STRING NOT NULL,
  transaction_date DATE NOT NULL,
  season_year INT64 NOT NULL,
  
  -- Player information
  player_id INT64 NOT NULL,
  player_slug STRING,
  player_full_name STRING,
  player_lookup STRING,
  is_player_transaction BOOLEAN NOT NULL,
  
  -- Team information
  team_id INT64 NOT NULL,
  team_slug STRING NOT NULL,
  team_abbr STRING NOT NULL,
  
  -- Transaction details
  transaction_description STRING NOT NULL,
  additional_sort INT64,
  group_sort STRING NOT NULL,
  
  -- Processing metadata
  source_file_path STRING NOT NULL,
  scrape_timestamp TIMESTAMP NOT NULL,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY RANGE_BUCKET(season_year, GENERATE_ARRAY(2021, 2030, 1))
CLUSTER BY player_lookup, team_abbr, transaction_type, transaction_date
OPTIONS (
  description = "NBA.com Player Movement: Complete transaction history (trades, signings, waivers, G-League moves) from 2021+. Critical for validating historical player-team assignments in prop betting analysis.",
  require_partition_filter = false
);

-- Helpful views for common queries
CREATE OR REPLACE VIEW `nba_raw.nbac_player_movement_recent` AS
SELECT *
FROM `nba_raw.nbac_player_movement`
WHERE transaction_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY transaction_date DESC, created_at DESC;

CREATE OR REPLACE VIEW `nba_raw.nbac_player_movement_players_only` AS
SELECT *
FROM `nba_raw.nbac_player_movement`
WHERE is_player_transaction = TRUE
ORDER BY transaction_date DESC, player_lookup;

CREATE OR REPLACE VIEW `nba_raw.nbac_player_movement_trades` AS  
SELECT 
  group_sort,
  transaction_date,
  COUNT(*) as transaction_parts,
  STRING_AGG(DISTINCT team_abbr ORDER BY team_abbr) as teams_involved,
  STRING_AGG(DISTINCT player_full_name ORDER BY player_full_name) as players_involved
FROM `nba_raw.nbac_player_movement`
WHERE transaction_type = 'Trade'
  AND player_full_name IS NOT NULL
  AND player_full_name != ''
GROUP BY group_sort, transaction_date
ORDER BY transaction_date DESC;