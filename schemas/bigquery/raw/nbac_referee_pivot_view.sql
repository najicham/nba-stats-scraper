-- ============================================================================
-- File: schemas/bigquery/raw/nbac_referee_pivot_view.sql
-- Description: Pivot view for game-level referee assignments
-- 
-- Purpose: Transform one-row-per-official into one-row-per-game format
-- Strategy: VIEW (not processor) - always up-to-date, no additional maintenance
-- ============================================================================

-- Main pivot view: One row per game with all officials
CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.nbac_referee_game_pivot` AS
SELECT 
  -- Core identifiers
  game_id,
  game_date,
  CAST(SUBSTR(season, 1, 4) AS INT64) as season_year,
  game_code,
  
  -- Team information
  home_team_id,
  home_team,
  home_team_abbr,
  away_team_id,
  away_team,
  away_team_abbr,
  
  -- Pivot officials by position
  MAX(CASE WHEN official_position = 1 THEN official_name END) as chief_referee,
  MAX(CASE WHEN official_position = 2 THEN official_name END) as crew_referee_1,
  MAX(CASE WHEN official_position = 3 THEN official_name END) as crew_referee_2,
  MAX(CASE WHEN official_position = 4 THEN official_name END) as crew_referee_3,
  
  -- Include official codes for potential lookups
  MAX(CASE WHEN official_position = 1 THEN official_code END) as chief_referee_code,
  MAX(CASE WHEN official_position = 2 THEN official_code END) as crew_referee_1_code,
  MAX(CASE WHEN official_position = 3 THEN official_code END) as crew_referee_2_code,
  MAX(CASE WHEN official_position = 4 THEN official_code END) as crew_referee_3_code,
  
  -- Metadata
  MAX(scrape_timestamp) as refs_announced_timestamp,
  MAX(source_file_path) as refs_source,
  COUNT(*) as total_officials
  
FROM `nba-props-platform.nba_raw.nbac_referee_game_assignments`
GROUP BY 
  game_id, 
  game_date, 
  season, 
  game_code,
  home_team_id,
  home_team,
  home_team_abbr,
  away_team_id,
  away_team,
  away_team_abbr;

-- ============================================================================
-- Helper view: Recent games with referee assignments
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.nbac_referee_game_pivot_recent` AS
SELECT 
  game_date,
  game_id,
  home_team_abbr,
  away_team_abbr,
  chief_referee,
  crew_referee_1,
  crew_referee_2,
  crew_referee_3,
  total_officials
FROM `nba-props-platform.nba_raw.nbac_referee_game_pivot`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY game_date DESC, game_id;

-- ============================================================================
-- Helper view: Chief referee summary (for quick lookups)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_raw.nbac_chief_referee_summary` AS
SELECT 
  chief_referee,
  chief_referee_code,
  COUNT(*) as games_worked,
  MIN(game_date) as first_game,
  MAX(game_date) as most_recent_game,
  COUNT(DISTINCT season_year) as seasons_worked
FROM `nba-props-platform.nba_raw.nbac_referee_game_pivot`
WHERE chief_referee IS NOT NULL
GROUP BY chief_referee, chief_referee_code
ORDER BY games_worked DESC;

-- ============================================================================
-- Documentation and Usage Examples
-- ============================================================================

/*
PURPOSE:
--------
Provides a game-level view of referee assignments without requiring a separate
analytics processor. Other processors can query this view directly.

USAGE EXAMPLES:
---------------

1. Get referees for a specific game:
   
   SELECT chief_referee, crew_referee_1, crew_referee_2
   FROM `nba-props-platform.nba_raw.nbac_referee_game_pivot`
   WHERE game_id = '0012400123';

2. Find all games worked by a specific referee:
   
   SELECT game_date, game_id, home_team_abbr, away_team_abbr
   FROM `nba-props-platform.nba_raw.nbac_referee_game_pivot`
   WHERE chief_referee = 'Scott Foster'
   ORDER BY game_date DESC;

3. Use in upcoming_team_game_context JOIN:
   
   SELECT 
     t.game_id,
     t.team_abbr,
     r.chief_referee,
     r.crew_referee_1
   FROM `nba_analytics.upcoming_team_game_context` t
   LEFT JOIN `nba_raw.nbac_referee_game_pivot` r
     ON t.game_id = r.game_id;

4. Get today's referee assignments:
   
   SELECT *
   FROM `nba-props-platform.nba_raw.nbac_referee_game_pivot`
   WHERE game_date = CURRENT_DATE();

PERFORMANCE:
------------
- View is computed on-demand (no storage cost)
- Underlying table is partitioned by game_date
- Use date filters for optimal query performance
- Consider materializing if queried frequently in production

MAINTENANCE:
------------
- No processor to deploy/monitor
- No backfill jobs needed
- Always reflects current raw data
- Update automatically when raw data updates

FUTURE ENHANCEMENTS:
--------------------
When referee tendencies are needed, create a separate processor:
- nba_analytics.referee_tendencies (calculated metrics)
- Joins this view with game summaries
- Calculates rolling averages (points, fouls, pace, etc.)
- Updates daily after games complete
*/