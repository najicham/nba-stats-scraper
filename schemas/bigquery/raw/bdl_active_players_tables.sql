-- Ball Don't Lie Active Players BigQuery Schema
-- File: schemas/bigquery/bdl_active_players_tables.sql

-- Create table for Ball Don't Lie Active Players with validation tracking
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_raw.bdl_active_players_current` (
  -- Primary identifiers
  player_lookup STRING NOT NULL OPTIONS(description="Normalized player name for cross-source matching (e.g., 'stephencurry')"),
  bdl_player_id INT64 NOT NULL OPTIONS(description="Ball Don't Lie unique player ID"),
  first_name STRING OPTIONS(description="Player first name from Ball Don't Lie"),
  last_name STRING OPTIONS(description="Player last name from Ball Don't Lie"),
  player_full_name STRING OPTIONS(description="Constructed full name 'First Last'"),

  -- Team assignment (critical for validation)
  bdl_team_id INT64 OPTIONS(description="Ball Don't Lie team ID"),
  team_abbr STRING OPTIONS(description="NBA standard three-letter team abbreviation (GSW, LAL, etc.)"),
  team_city STRING OPTIONS(description="Team city name from Ball Don't Lie"),
  team_name STRING OPTIONS(description="Team name from Ball Don't Lie (Warriors, Lakers, etc.)"),
  team_full_name STRING OPTIONS(description="Full team name from Ball Don't Lie"),
  team_conference STRING OPTIONS(description="Team conference (East/West)"),
  team_division STRING OPTIONS(description="Team division (Atlantic, Pacific, etc.)"),

  -- Player attributes
  position STRING OPTIONS(description="Player position code (G, F, C, etc.)"),
  height STRING OPTIONS(description="Player height in feet-inches format '6-2'"),
  weight STRING OPTIONS(description="Player weight in pounds as string"),
  jersey_number STRING OPTIONS(description="Current jersey number"),

  -- Career information
  college STRING OPTIONS(description="College attended or international origin"),
  country STRING OPTIONS(description="Country of origin"),
  draft_year INT64 OPTIONS(description="Year drafted into NBA"),
  draft_round INT64 OPTIONS(description="Draft round (1-2)"),
  draft_number INT64 OPTIONS(description="Draft pick number within round"),

  -- Cross-validation tracking
  has_validation_issues BOOLEAN NOT NULL OPTIONS(description="TRUE if any validation problems found against NBA.com data"),
  validation_status STRING NOT NULL OPTIONS(description="Validation result: 'validated', 'team_mismatch', 'missing_nba_com', 'data_quality_issue'"),
  validation_details STRING OPTIONS(description="JSON string with specific validation issues for analyst review"),
  nba_com_team_abbr STRING OPTIONS(description="Team abbreviation from NBA.com data for comparison"),
  validation_last_check TIMESTAMP OPTIONS(description="When validation was last performed against NBA.com data"),

  -- Processing metadata
  last_seen_date DATE OPTIONS(description="Date this player data was collected from Ball Don't Lie"),
  source_file_path STRING OPTIONS(description="GCS path of source JSON file"),
  processed_at TIMESTAMP NOT NULL OPTIONS(description="When this record was processed into BigQuery")
)
CLUSTER BY team_abbr, has_validation_issues, validation_status
OPTIONS(
  description="Ball Don't Lie active players with cross-validation against NBA.com data for prop betting player verification",
  labels=[("source", "ball_dont_lie"), ("data_type", "active_players"), ("business_purpose", "player_validation")]
);

-- Create indexes for common query patterns
-- Note: BigQuery doesn't support traditional indexes, clustering handles performance

-- Validation summary view for monitoring data quality
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.bdl_active_players_validation_summary` AS
SELECT 
  validation_status,
  COUNT(*) as player_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
FROM `nba-props-platform.nba_raw.bdl_active_players_current`
GROUP BY validation_status
ORDER BY player_count DESC;

-- Team comparison view for identifying discrepancies
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.bdl_nba_team_comparison` AS
SELECT 
  b.player_full_name,
  b.team_abbr as bdl_team,
  b.nba_com_team_abbr as nba_team,
  b.validation_status,
  b.validation_details,
  b.last_seen_date
FROM `nba-props-platform.nba_raw.bdl_active_players_current` b
WHERE b.has_validation_issues = TRUE
ORDER BY b.validation_status, b.player_full_name;

-- Props players validation view - critical for business operations
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.props_players_validation_status` AS
SELECT 
  o.player_name as props_player_name,
  o.game_date,
  b.player_full_name as bdl_player_name,
  b.team_abbr as bdl_team,
  b.nba_com_team_abbr as nba_team,
  b.has_validation_issues,
  b.validation_status,
  CASE 
    WHEN b.player_lookup IS NULL THEN 'MISSING_FROM_BDL'
    WHEN b.has_validation_issues THEN 'NEEDS_REVIEW'
    ELSE 'VALIDATED'
  END as props_validation_status
FROM `nba-props-platform.nba_raw.odds_api_player_points_props` o
LEFT JOIN `nba-props-platform.nba_raw.bdl_active_players_current` b 
  ON o.player_lookup = b.player_lookup
WHERE o.game_date >= CURRENT_DATE() - 7  -- Last 7 days of props
ORDER BY o.game_date DESC, props_validation_status DESC;

-- Add table comments for documentation
ALTER TABLE `nba-props-platform.nba_raw.bdl_active_players_current`
SET OPTIONS (
  description="""
Ball Don't Lie Active Players with NBA.com Cross-Validation

Purpose: Validate player-team assignments for prop betting operations
Strategy: MERGE_UPDATE (current-state data, replaces all records)
Validation: Cross-checks against nba_raw.nbac_player_list_current
Business Impact: CRITICAL - Ensures prop betting player data accuracy

Key Features:
- Real-time validation against NBA.com official data
- Confidence scoring for data quality monitoring  
- Team assignment verification for prop betting
- Issue tracking with detailed JSON for analyst review

Usage Examples:
1. Find validation issues: WHERE has_validation_issues = TRUE
2. Team mismatches: WHERE validation_status = 'team_mismatch' 
3. Props validation: JOIN with odds_api_player_points_props

Update Frequency: Daily + Real-time (every 2 hours during season)
Record Count: ~500 active NBA players
Validation Rate: Target >95% validated status
  """
);