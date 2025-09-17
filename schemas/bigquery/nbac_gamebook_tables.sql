-- File: schemas/bigquery/nbac_gamebook_tables.sql
-- Optimized NBA.com gamebook table with name resolution monitoring built-in

-- Main gamebook player stats table
CREATE TABLE `nba-props-platform.nba_raw.nbac_gamebook_player_stats` (
  -- Game identification
  game_id STRING NOT NULL,              -- Standardized format: "20240101_BKN_MIL" (YYYYMMDD_AWAY_HOME)
  game_code STRING,                     -- Original NBA.com game code from source data
  game_date DATE NOT NULL,              -- Game date in YYYY-MM-DD format
  season_year INT64 NOT NULL,           -- NBA season year (2024 = 2024-25 season, Oct-Sep)
  home_team_abbr STRING,               -- Home team 3-letter code (e.g., "MIL")
  away_team_abbr STRING,               -- Away team 3-letter code (e.g., "BKN")
  
  -- Player identification and resolution
  player_name STRING,                    -- Final resolved name or original
  player_name_original STRING NOT NULL,  -- Exactly as it appears in source
  player_lookup STRING,                  -- Normalized for matching
  team_abbr STRING,                      -- Player's team
  player_status STRING NOT NULL,         -- 'active', 'inactive', 'dnp'
  dnp_reason STRING,                     -- Reason for DNP/inactive
  
  -- Name resolution tracking
  name_resolution_status STRING,         -- 'resolved', 'not_found', 'multiple_matches', 'original'
  name_resolution_confidence FLOAT64,    -- 0.0-1.0 confidence score
  name_resolution_method STRING,         -- How it was resolved
  br_team_abbr_used STRING,             -- Which BR team code was used for lookup
  
  -- Basketball statistics
  minutes STRING,                        -- "MM:SS" format from source
  minutes_decimal FLOAT64,               -- Converted to decimal
  points INT64,
  field_goals_made INT64,
  field_goals_attempted INT64,
  field_goal_percentage FLOAT64,
  three_pointers_made INT64,
  three_pointers_attempted INT64,
  three_point_percentage FLOAT64,
  free_throws_made INT64,
  free_throws_attempted INT64,
  free_throw_percentage FLOAT64,
  offensive_rebounds INT64,
  defensive_rebounds INT64,
  total_rebounds INT64,
  assists INT64,
  steals INT64,
  blocks INT64,
  turnovers INT64,
  personal_fouls INT64,
  plus_minus INT64,
  
  -- Processing metadata and audit trail
  processed_by_run_id STRING,           -- Links to processing run
  source_file_path STRING,              -- GCS source file for debugging
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  
  -- Data quality indicators
  data_quality_flags ARRAY<STRING>,     -- ['team_mapped', 'suffix_handled'] etc.
  requires_manual_review BOOLEAN DEFAULT FALSE
)
PARTITION BY game_date
CLUSTER BY season_year, team_abbr, player_status, name_resolution_status
OPTIONS(
  description = "NBA.com gamebook player statistics with enhanced name resolution tracking",
  labels = [("source", "nba_com"), ("type", "player_stats"), ("domain", "basketball")]
);

-- Views for data quality monitoring
CREATE OR REPLACE VIEW `nba_raw.gamebook_data_quality_dashboard` AS
SELECT 
  season_year,
  team_abbr,
  br_team_abbr_used,
  player_status,
  name_resolution_status,
  COUNT(*) as player_records,
  COUNT(DISTINCT player_name_original) as unique_players,
  COUNT(DISTINCT game_id) as games_affected,
  ROUND(AVG(name_resolution_confidence), 3) as avg_confidence,
  COUNT(CASE WHEN requires_manual_review THEN 1 END) as manual_review_needed,
  
  -- Recent activity
  MAX(game_date) as latest_game_date,
  MAX(processed_at) as last_processed,
  
  -- Quality score
  ROUND(AVG(
    CASE 
      WHEN name_resolution_status = 'resolved' AND name_resolution_confidence = 1.0 THEN 1.0
      WHEN name_resolution_status = 'resolved' AND name_resolution_confidence >= 0.8 THEN 0.9
      WHEN name_resolution_status = 'multiple_matches' THEN 0.6
      WHEN name_resolution_status = 'not_found' AND player_status = 'inactive' THEN 0.2
      WHEN name_resolution_status = 'original' AND player_status != 'active' THEN 0.7
      ELSE 0.8
    END
  ), 3) as quality_score
FROM `nba_raw.nbac_gamebook_player_stats`
GROUP BY season_year, team_abbr, br_team_abbr_used, player_status, name_resolution_status
ORDER BY season_year DESC, quality_score ASC, player_records DESC;

-- Injured players requiring attention
CREATE OR REPLACE VIEW `nba_raw.injured_players_attention_needed` AS
WITH injured_issues AS (
  SELECT 
    player_name_original,
    team_abbr,
    br_team_abbr_used,
    season_year,
    name_resolution_status,
    name_resolution_confidence,
    COUNT(*) as total_occurrences,
    COUNT(DISTINCT game_id) as games_affected,
    MAX(game_date) as last_seen,
    MIN(game_date) as first_seen,
    MAX(processed_by_run_id) as latest_processing_run,
    
    -- Categorize the issue
    CASE 
      WHEN name_resolution_status = 'not_found' AND team_abbr != br_team_abbr_used THEN 'TEAM_MAPPING_FAILED'
      WHEN name_resolution_status = 'not_found' AND player_name_original LIKE '% II' THEN 'SUFFIX_HANDLING_FAILED'
      WHEN name_resolution_status = 'not_found' THEN 'NO_ROSTER_MATCH'
      WHEN name_resolution_status = 'multiple_matches' THEN 'AMBIGUOUS_MATCH'
      WHEN requires_manual_review THEN 'MANUAL_REVIEW_FLAGGED'
      ELSE 'OTHER'
    END as issue_category,
    
    -- Sample games for investigation
    ARRAY_AGG(DISTINCT game_id LIMIT 3) as sample_games
  FROM `nba_raw.nbac_gamebook_player_stats`
  WHERE player_status = 'inactive'
    AND (name_resolution_status IN ('not_found', 'multiple_matches') 
         OR requires_manual_review = TRUE
         OR name_resolution_confidence < 0.8)
  GROUP BY player_name_original, team_abbr, br_team_abbr_used, season_year, 
           name_resolution_status, name_resolution_confidence, requires_manual_review
)
SELECT *,
  -- Priority scoring
  CASE 
    WHEN games_affected >= 20 THEN 'HIGH'
    WHEN games_affected >= 10 THEN 'MEDIUM' 
    WHEN games_affected >= 5 THEN 'LOW'
    ELSE 'MINIMAL'
  END as priority_level
FROM injured_issues
WHERE games_affected >= 3  -- Focus on recurring issues
ORDER BY 
  CASE priority_level WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END,
  games_affected DESC,
  last_seen DESC;

-- Team mapping effectiveness analysis
CREATE OR REPLACE VIEW `nba_raw.team_mapping_analysis` AS
SELECT 
  team_abbr as original_team_code,
  br_team_abbr_used as mapped_team_code,
  team_abbr != br_team_abbr_used as was_team_mapped,
  season_year,
  
  COUNT(*) as total_attempts,
  COUNT(CASE WHEN name_resolution_status = 'resolved' THEN 1 END) as successful_resolutions,
  COUNT(CASE WHEN name_resolution_status = 'not_found' THEN 1 END) as failed_resolutions,
  
  ROUND(
    COUNT(CASE WHEN name_resolution_status = 'resolved' THEN 1 END) * 100.0 / COUNT(*), 
    1
  ) as success_rate_pct,
  
  COUNT(DISTINCT player_name_original) as unique_players,
  COUNT(DISTINCT game_id) as games_affected,
  
  -- Focus on mapping effectiveness
  COUNT(CASE WHEN team_abbr != br_team_abbr_used AND name_resolution_status = 'resolved' THEN 1 END) as mapping_fixes_successful,
  COUNT(CASE WHEN team_abbr != br_team_abbr_used AND name_resolution_status = 'not_found' THEN 1 END) as mapping_fixes_failed
FROM `nba_raw.nbac_gamebook_player_stats`
WHERE player_status = 'inactive'
GROUP BY team_abbr, br_team_abbr_used, season_year
HAVING total_attempts >= 5  -- Meaningful sample size
ORDER BY success_rate_pct ASC, total_attempts DESC;

-- Processing run audit trail
CREATE OR REPLACE VIEW `nba_raw.processing_run_audit` AS
SELECT 
  g.processed_by_run_id,
  COUNT(DISTINCT g.game_id) as games_processed,
  COUNT(*) as total_player_records,
  COUNT(CASE WHEN g.player_status = 'inactive' THEN 1 END) as inactive_players_processed,
  COUNT(CASE WHEN g.name_resolution_status = 'resolved' AND g.player_status = 'inactive' THEN 1 END) as injured_players_resolved,
  
  MIN(g.game_date) as earliest_game,
  MAX(g.game_date) as latest_game,
  MIN(g.processed_at) as processing_started,
  MAX(g.processed_at) as processing_completed,
  
  -- Link to detailed performance logs
  p.processing_timestamp as logged_start_time,
  p.resolution_rate as logged_resolution_rate,
  p.team_mapping_fixes,
  p.suffix_handling_fixes,
  p.processing_duration_minutes
FROM `nba_raw.nbac_gamebook_player_stats` g
LEFT JOIN `nba_processing.resolution_performance` p 
  ON g.processed_by_run_id = p.processing_run_id
WHERE g.processed_by_run_id IS NOT NULL
GROUP BY g.processed_by_run_id, p.processing_timestamp, p.resolution_rate, 
         p.team_mapping_fixes, p.suffix_handling_fixes, p.processing_duration_minutes
ORDER BY processing_started DESC;

-- Quick health check view for monitoring
CREATE OR REPLACE VIEW `nba_raw.data_health_check` AS
SELECT 
  'Overall Resolution Rate' as metric,
  CONCAT(
    ROUND(COUNT(CASE WHEN name_resolution_status = 'resolved' AND player_status = 'inactive' THEN 1 END) * 100.0 / 
          NULLIF(COUNT(CASE WHEN player_status = 'inactive' THEN 1 END), 0), 1), 
    '%'
  ) as value,
  COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as total_inactive_players
FROM `nba_raw.nbac_gamebook_player_stats`

UNION ALL

SELECT 
  'Injured Players Needing Review' as metric,
  CAST(COUNT(*) AS STRING) as value,
  NULL as total_inactive_players
FROM `nba_raw.injured_players_attention_needed`
WHERE priority_level IN ('HIGH', 'MEDIUM')

UNION ALL

SELECT 
  'Team Mapping Success Rate' as metric,
  CONCAT(
    ROUND(AVG(success_rate_pct), 1), '%'
  ) as value,
  NULL as total_inactive_players
FROM `nba_raw.team_mapping_analysis`
WHERE was_team_mapped = TRUE

UNION ALL

SELECT 
  'Recent Processing Runs' as metric,
  CAST(COUNT(DISTINCT processed_by_run_id) AS STRING) as value,
  NULL as total_inactive_players
FROM `nba_raw.nbac_gamebook_player_stats`
WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY);