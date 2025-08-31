-- File: schemas/bigquery/name_resolution_tables.sql
-- Name resolution management for data quality

-- Master resolution table - canonical mappings
CREATE TABLE IF NOT EXISTS `nba_raw.player_name_resolutions` (
  -- Resolution key (unique identifier for resolution cases)
  resolution_id        STRING NOT NULL,    -- Format: "ATL_Lundy_2024"
  
  -- Original data
  team_abbr            STRING NOT NULL,
  original_name        STRING NOT NULL,    -- "Lundy" from gamebook
  season_year          INT64 NOT NULL,
  
  -- Resolution results
  resolved_name        STRING,             -- "Luke Lundy" (manually corrected)
  resolved_lookup      STRING,             -- "lukelundy" (normalized)
  resolution_method    STRING NOT NULL,    -- "manual", "auto_exact", "auto_fuzzy", "auto_context"
  resolution_status    STRING NOT NULL,    -- "pending", "validated", "rejected", "uncertain"
  confidence_score     FLOAT64,           -- 0.0-1.0
  
  -- Resolution context
  possible_matches     JSON,               -- Store BR roster matches for reference
  context_notes        STRING,             -- "Traded mid-season", "Two-way contract"
  
  -- Audit fields
  created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  created_by           STRING DEFAULT 'system',  -- "system", "analyst@company.com"
  validated_at         TIMESTAMP,
  validated_by         STRING,
  last_updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  updated_by           STRING,
  
  -- Quality metrics
  games_affected       INT64,              -- How many games use this resolution
  first_seen_date      DATE,               -- When first encountered
  last_seen_date       DATE,               -- Most recent occurrence
  
  PRIMARY KEY (resolution_id)
)
PARTITION BY DATE(created_at)
CLUSTER BY team_abbr, season_year, resolution_status
OPTIONS(
  description = "Master table for player name resolution management and validation",
  labels = [("type", "data_quality"), ("domain", "player_names")]
);

-- Add fields to your existing gamebook table for linking
ALTER TABLE `nba_raw.nbac_gamebook_player_stats`
ADD COLUMN IF NOT EXISTS name_resolution_confidence FLOAT64,
ADD COLUMN IF NOT EXISTS name_resolution_method STRING,  -- How it was resolved
ADD COLUMN IF NOT EXISTS resolution_id STRING,           -- Link to resolutions table
ADD COLUMN IF NOT EXISTS name_last_validated TIMESTAMP;  -- When name was last validated

-- View for pending manual review
CREATE OR REPLACE VIEW `nba_raw.name_resolutions_pending` AS
SELECT 
  r.resolution_id,
  r.team_abbr,
  r.original_name,
  r.season_year,
  r.possible_matches,
  r.games_affected,
  r.context_notes,
  r.created_at,
  -- Sample games where this resolution appears
  ARRAY_AGG(g.game_id ORDER BY g.game_date DESC LIMIT 3) as sample_games
FROM `nba_raw.player_name_resolutions` r
LEFT JOIN `nba_raw.nbac_gamebook_player_stats` g 
  ON r.resolution_id = g.resolution_id
WHERE r.resolution_status = 'pending'
GROUP BY r.resolution_id, r.team_abbr, r.original_name, r.season_year, 
         r.possible_matches, r.games_affected, r.context_notes, r.created_at
ORDER BY r.games_affected DESC, r.created_at ASC;

-- View for data quality dashboard
CREATE OR REPLACE VIEW `nba_raw.name_resolution_metrics` AS
SELECT 
  season_year,
  team_abbr,
  resolution_status,
  resolution_method,
  COUNT(*) as resolution_count,
  AVG(confidence_score) as avg_confidence,
  SUM(games_affected) as total_games_affected,
  MIN(created_at) as first_resolution,
  MAX(last_updated_at) as last_activity
FROM `nba_raw.player_name_resolutions`
GROUP BY season_year, team_abbr, resolution_status, resolution_method
ORDER BY season_year DESC, total_games_affected DESC;

-- Stored procedure for bulk validation
CREATE OR REPLACE PROCEDURE `nba_raw.validate_name_resolution`(
  IN resolution_ids ARRAY<STRING>,
  IN validated_by STRING,
  IN batch_notes STRING
)
BEGIN
  -- Update resolution status to validated
  UPDATE `nba_raw.player_name_resolutions`
  SET 
    resolution_status = 'validated',
    validated_at = CURRENT_TIMESTAMP(),
    validated_by = validated_by,
    context_notes = CONCAT(IFNULL(context_notes, ''), ' | Batch validated: ', batch_notes),
    last_updated_at = CURRENT_TIMESTAMP(),
    updated_by = validated_by
  WHERE resolution_id IN UNNEST(resolution_ids);
  
  -- Update linked gamebook records
  UPDATE `nba_raw.nbac_gamebook_player_stats`
  SET 
    name_last_validated = CURRENT_TIMESTAMP(),
    name_resolution_confidence = (
      SELECT confidence_score 
      FROM `nba_raw.player_name_resolutions` r 
      WHERE r.resolution_id = nbac_gamebook_player_stats.resolution_id
    )
  WHERE resolution_id IN UNNEST(resolution_ids);
END;
