-- File: schemas/bigquery/nbac_gamebook_tables.sql
-- NBA.com Gamebook Player Stats table schema

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_gamebook_player_stats` (
  -- Game identifiers
  game_id              STRING NOT NULL,    -- Format: "20211019_BKN_MIL"
  game_code            STRING,              -- Original: "20211019/BKNMIL"
  game_date            DATE NOT NULL,       -- 2021-10-19
  season_year          INT64,               -- 2021 for 2021-22 season
  
  -- Teams
  home_team_abbr       STRING,              -- Three-letter code
  away_team_abbr       STRING,              -- Three-letter code
  
  -- Player identifiers
  player_name          STRING,              -- Full name (resolved for inactive)
  player_name_original STRING,              -- As appears in source
  player_lookup        STRING,              -- Normalized: "kevindurant"
  team_abbr            STRING,              -- Three-letter code for player's team
  
  -- Player status
  player_status        STRING,              -- "active", "dnp", "inactive"
  dnp_reason           STRING,              -- Full DNP or injury reason text
  name_resolution_status STRING,            -- "resolved", "multiple_matches", "not_found", "original"
  
  -- Stats (NULL for non-active players)
  minutes              STRING,              -- "30:15" format
  minutes_decimal      FLOAT64,             -- 30.25
  points               INT64,
  field_goals_made     INT64,
  field_goals_attempted INT64,
  field_goal_percentage FLOAT64,
  three_pointers_made  INT64,
  three_pointers_attempted INT64,
  three_point_percentage FLOAT64,
  free_throws_made     INT64,
  free_throws_attempted INT64,
  free_throw_percentage FLOAT64,
  offensive_rebounds   INT64,
  defensive_rebounds   INT64,
  total_rebounds       INT64,
  assists              INT64,
  steals               INT64,
  blocks               INT64,
  turnovers            INT64,
  personal_fouls       INT64,
  plus_minus           INT64,
  
  -- Processing metadata
  source_file_path     STRING,
  processed_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, game_date, player_status
OPTIONS(
  description = "NBA.com gamebook data with player stats and availability status",
  labels = [("source", "nbacom"), ("type", "gamebooks")]
);

-- View for active players only (commonly used for prop validation)
CREATE OR REPLACE VIEW `nba_raw.nbac_gamebook_active_players` AS
SELECT 
  game_id,
  game_date,
  season_year,
  home_team_abbr,
  away_team_abbr,
  player_name,
  player_lookup,
  team_abbr,
  minutes_decimal,
  points,
  field_goals_made,
  field_goals_attempted,
  three_pointers_made,
  three_pointers_attempted,
  free_throws_made,
  free_throws_attempted,
  total_rebounds,
  assists,
  steals,
  blocks,
  turnovers,
  personal_fouls,
  plus_minus
FROM `nba_raw.nbac_gamebook_player_stats`
WHERE player_status = 'active';

-- View for name resolution issues (for data quality monitoring)
CREATE OR REPLACE VIEW `nba_raw.nbac_gamebook_name_issues` AS
SELECT 
  player_name_original,
  team_abbr,
  name_resolution_status,
  COUNT(*) as occurrences,
  MAX(game_date) as most_recent_game,
  MIN(game_date) as first_game,
  STRING_AGG(DISTINCT dnp_reason LIMIT 3) as sample_reasons
FROM `nba_raw.nbac_gamebook_player_stats`
WHERE player_status = 'inactive'
  AND name_resolution_status IN ('multiple_matches', 'not_found')
GROUP BY player_name_original, team_abbr, name_resolution_status
ORDER BY occurrences DESC;

-- Example query: Validate prop outcomes
-- This shows how to join with Odds API data
/*
SELECT 
  p.game_date,
  p.player_name,
  p.player_lookup,
  p.points_line,
  p.bookmaker,
  g.points as actual_points,
  g.player_status,
  g.dnp_reason,
  CASE 
    WHEN g.player_status != 'active' THEN 'NO_ACTION'
    WHEN g.points > p.points_line THEN 'OVER'
    WHEN g.points < p.points_line THEN 'UNDER'
    ELSE 'PUSH'
  END as result
FROM `nba_raw.odds_api_player_points_props` p
LEFT JOIN `nba_raw.nbac_gamebook_player_stats` g 
  ON p.game_id = g.game_id 
  AND p.player_lookup = g.player_lookup
WHERE p.game_date = '2024-02-14'
ORDER BY p.player_name, p.bookmaker;
*/