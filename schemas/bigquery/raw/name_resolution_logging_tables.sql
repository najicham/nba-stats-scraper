-- File: schemas/bigquery/name_resolution_logging_tables.sql
-- Enhanced logging tables for NBA.com gamebook name resolution tracking

-- Name resolution detailed log
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.name_resolution_log` (
  -- Processing context
  processing_run_id STRING NOT NULL,
  processing_timestamp TIMESTAMP NOT NULL,
  
  -- Player context
  original_name STRING NOT NULL,
  team_abbr STRING NOT NULL,
  season_year INT64 NOT NULL,
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,
  player_status STRING NOT NULL,        -- 'inactive', 'dnp' - helps filter to injured players
  
  -- Resolution results
  resolution_status STRING NOT NULL,     -- 'resolved', 'not_found', 'multiple_matches', 'original', 'error'
  resolution_method STRING,              -- 'direct_lookup', 'team_mapped', 'suffix_handled', 'team_mapped_suffix_handled'
  confidence_score FLOAT64,
  
  -- Resolution details
  resolved_name STRING,
  resolved_lookup STRING,
  br_team_abbr_used STRING,              -- Which BR team code was used for lookup
  roster_matches_found INT64,
  potential_matches STRING,              -- JSON string of potential matches
  error_details STRING,
  
  -- Traceability
  source_file_path STRING,               -- GCS path for debugging
  
  -- Metadata
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY resolution_status, player_status, team_abbr, season_year
OPTIONS (
  description = "Detailed log of every name resolution attempt for inactive NBA players",
  require_partition_filter = false
);

-- Processing performance summary
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_processing.resolution_performance` (
  -- Run identification
  processing_run_id STRING NOT NULL,
  processing_timestamp TIMESTAMP NOT NULL,
  
  -- Volume metrics
  total_inactive_players INT64,
  total_dnp_players INT64,               -- Separate tracking for DNP vs inactive
  files_processed INT64,
  processing_duration_minutes FLOAT64,
  
  -- Resolution metrics
  resolved_count INT64,
  not_found_count INT64,
  multiple_matches_count INT64,
  original_count INT64,
  error_count INT64,
  
  -- Method effectiveness
  team_mapping_fixes INT64,
  suffix_handling_fixes INT64,
  direct_lookup_successes INT64,
  
  -- Performance indicators
  resolution_rate FLOAT64,               -- resolved / total
  improvement_from_baseline FLOAT64,     -- Can be calculated later
  
  -- Processing scope
  date_range_start DATE,
  date_range_end DATE,
  
  -- Metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
OPTIONS (
  description = "Summary performance metrics for name resolution processing runs"
);

-- Views for injured player monitoring
CREATE OR REPLACE VIEW `nba_processing.injured_player_failures` AS
SELECT 
  original_name,
  team_abbr,
  br_team_abbr_used,
  season_year,
  resolution_status,
  COUNT(*) as failure_count,
  COUNT(DISTINCT game_id) as games_affected,
  MAX(error_details) as latest_error,
  MAX(potential_matches) as potential_solutions,
  MAX(game_date) as last_seen_date,
  -- Sample games for investigation
  STRING_AGG(DISTINCT game_id ORDER BY game_id LIMIT 3) as sample_games
FROM `nba_processing.name_resolution_log`
WHERE player_status = 'inactive'  -- Focus on injured players
  AND resolution_status IN ('not_found', 'error', 'multiple_matches')
GROUP BY original_name, team_abbr, br_team_abbr_used, season_year, resolution_status
ORDER BY failure_count DESC;

CREATE OR REPLACE VIEW `nba_processing.team_mapping_issues` AS
SELECT 
  team_abbr as original_team,
  br_team_abbr_used as mapped_team,
  COUNT(*) as failed_attempts,
  COUNT(DISTINCT original_name) as unique_players,
  COUNT(DISTINCT game_id) as games_affected,
  ARRAY_AGG(DISTINCT original_name ORDER BY original_name LIMIT 10) as sample_players
FROM `nba_processing.name_resolution_log`
WHERE resolution_status = 'not_found'
  AND team_abbr != br_team_abbr_used  -- Team mapping was attempted
GROUP BY team_abbr, br_team_abbr_used
ORDER BY failed_attempts DESC;

CREATE OR REPLACE VIEW `nba_processing.resolution_quality_by_team` AS
SELECT 
  team_abbr,
  br_team_abbr_used,
  season_year,
  COUNT(*) as total_attempts,
  COUNT(CASE WHEN resolution_status = 'resolved' THEN 1 END) as resolved,
  COUNT(CASE WHEN resolution_status = 'not_found' THEN 1 END) as not_found,
  COUNT(CASE WHEN resolution_status = 'multiple_matches' THEN 1 END) as multiple_matches,
  ROUND(COUNT(CASE WHEN resolution_status = 'resolved' THEN 1 END) * 100.0 / COUNT(*), 1) as success_rate
FROM `nba_processing.name_resolution_log`
WHERE player_status = 'inactive'  -- Focus on injured players
GROUP BY team_abbr, br_team_abbr_used, season_year
HAVING COUNT(*) >= 5  -- Only teams with meaningful sample size
ORDER BY success_rate ASC, total_attempts DESC;

-- Correction helper view
CREATE OR REPLACE VIEW `nba_processing.fixable_resolutions` AS
WITH failed_resolutions AS (
  SELECT DISTINCT
    original_name, 
    team_abbr, 
    br_team_abbr_used,
    season_year,
    COUNT(DISTINCT game_id) as games_affected
  FROM `nba_processing.name_resolution_log`
  WHERE resolution_status = 'not_found'
    AND player_status = 'inactive'
  GROUP BY original_name, team_abbr, br_team_abbr_used, season_year
),
roster_matches AS (
  SELECT DISTINCT
    player_last_name, 
    player_full_name, 
    player_lookup, 
    team_abbrev, 
    season_year
  FROM `nba_raw.br_rosters_current`
)
SELECT 
  f.original_name,
  f.team_abbr,
  f.br_team_abbr_used,
  f.season_year,
  f.games_affected,
  r.player_full_name as suggested_resolution,
  r.player_lookup as suggested_lookup,
  'HIGH' as fix_confidence
FROM failed_resolutions f
JOIN roster_matches r ON (
  LOWER(f.original_name) = LOWER(r.player_last_name)
  AND f.br_team_abbr_used = r.team_abbrev
  AND f.season_year = r.season_year
)
ORDER BY f.games_affected DESC;