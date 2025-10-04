-- File: schemas/bigquery/nbac_player_list_tables.sql
-- NBA.com Player List - Current player-team assignments

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_player_list_current` (
  -- Player Identification
  player_lookup STRING NOT NULL,     -- Primary key: normalized name
  player_id INT64,                   -- NBA.com player ID
  player_full_name STRING,           -- Display name
  
  -- Team Assignment
  team_id INT64,                     -- NBA.com team ID
  team_abbr STRING,                  -- Three-letter code
  
  -- Player Details
  jersey_number STRING,
  position STRING,
  height STRING,
  weight STRING,
  birth_date DATE,
  age FLOAT64,
  draft_year INT64,
  draft_round INT64,
  draft_pick INT64,
  years_pro INT64,
  college STRING,
  country STRING,
  
  -- Status
  is_active BOOLEAN,
  roster_status STRING,              -- 'active', 'inactive', 'g-league'
  season_year INT64,
  
  -- Tracking
  source_file_date DATE,             -- Date from source file path (when roster was scraped)
  first_seen_date DATE,
  last_seen_date DATE,
  source_file_path STRING,
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY RANGE_BUCKET(season_year, GENERATE_ARRAY(2020, 2030, 1))
CLUSTER BY team_abbr, is_active
OPTIONS(
  description = "Current NBA player roster assignments from NBA.com Player List API",
  labels = [("source", "nba-com"), ("type", "roster"), ("update_frequency", "daily")]
);

-- Create monitoring view for duplicates
CREATE OR REPLACE VIEW `nba_processing.player_name_collisions` AS
SELECT 
    player_lookup,
    COUNT(*) as duplicate_count,
    STRING_AGG(CONCAT(player_full_name, ' (', team_abbr, ')'), ', ') as players
FROM `nba_raw.nbac_player_list_current`
GROUP BY player_lookup
HAVING COUNT(*) > 1;