-- Path: schemas/bigquery/raw/nbac_team_boxscore_tables.sql
-- Description: BigQuery table schema for NBA.com team box score data (v2.0)
--
-- NBA.com Team Box Score Statistics
-- Complete team-level statistics for each NBA game
-- Data Source: stats.nba.com/stats/boxscoretraditionalv2
-- Processing: NbacTeamBoxscoreProcessor (MERGE_UPDATE strategy)
--
-- Version 2.0 Changes:
-- - Added is_home boolean to distinguish home/away teams
-- - Added nba_game_id for NBA.com API traceability
-- - Standardized game_id format: YYYYMMDD_AWAY_HOME
-- - Updated clustering to include is_home

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_team_boxscore` (
  -- Core Game Identifiers
  game_id              STRING NOT NULL,    -- System format: "20250115_LAL_PHI" (date_away_home)
  nba_game_id          STRING NOT NULL,    -- NBA.com game ID: "0022400561"
  game_date            DATE NOT NULL,      -- Game date (partition key)
  season_year          INT64 NOT NULL,     -- NBA season starting year (2024 for 2024-25 season)
  
  -- Team Identifiers
  team_id              INT64 NOT NULL,     -- NBA.com team ID (e.g., 1610612755 for 76ers)
  team_abbr            STRING NOT NULL,    -- Normalized team abbreviation: LAL, BOS, GSW, PHI, etc.
  team_name            STRING,             -- Team name: Lakers, Celtics, Warriors, 76ers, etc.
  team_city            STRING,             -- Team city: Los Angeles, Boston, Golden State, Philadelphia, etc.
  is_home              BOOLEAN NOT NULL,   -- TRUE if home team, FALSE if away team
  
  -- Game Time
  minutes              STRING,             -- Total minutes played: "240:00" for regulation, "265:00" for OT
  
  -- Field Goals
  fg_made              INT64,              -- Field goals made (includes 2PT and 3PT)
  fg_attempted         INT64,              -- Field goals attempted (includes 2PT and 3PT)
  fg_percentage        FLOAT64,            -- Field goal percentage (0.0-1.0, NULL if attempted=0)
  
  -- Three Pointers
  three_pt_made        INT64,              -- Three-pointers made
  three_pt_attempted   INT64,              -- Three-pointers attempted
  three_pt_percentage  FLOAT64,            -- Three-point percentage (0.0-1.0, NULL if attempted=0)
  
  -- Free Throws
  ft_made              INT64,              -- Free throws made
  ft_attempted         INT64,              -- Free throws attempted
  ft_percentage        FLOAT64,            -- Free throw percentage (0.0-1.0, NULL if attempted=0)
  
  -- Rebounds
  offensive_rebounds   INT64,              -- Offensive rebounds
  defensive_rebounds   INT64,              -- Defensive rebounds
  total_rebounds       INT64,              -- Total rebounds (offensive + defensive)
  
  -- Other Statistics
  assists              INT64,              -- Assists
  steals               INT64,              -- Steals
  blocks               INT64,              -- Blocks
  turnovers            INT64,              -- Turnovers
  personal_fouls       INT64,              -- Personal fouls
  points               INT64,              -- Total points scored
  plus_minus           INT64,              -- Plus/minus (+/-) - sum of both teams always equals 0
  
  -- Processing Metadata
  source_file_path     STRING,             -- GCS path of source JSON file
  created_at           TIMESTAMP,          -- When record was first created (UTC)
  processed_at         TIMESTAMP NOT NULL  -- When record was last processed (UTC)
)
PARTITION BY game_date
CLUSTER BY game_id, team_abbr, season_year, is_home
OPTIONS (
  description = "NBA.com team box score statistics - complete team-level performance data per game. Each game produces exactly 2 rows (one per team). Updated via MERGE_UPDATE strategy. v2.0 includes home/away indicator and dual game ID system.",
  require_partition_filter = true
);

-- ================================================================
-- USAGE NOTES
-- ================================================================
-- 
-- Game ID System (v2.0):
--   game_id:     Standardized system format "YYYYMMDD_AWAY_HOME" (e.g., "20250115_LAL_PHI")
--   nba_game_id: NBA.com source format (e.g., "0022400561")
--   Use game_id for joins across your system tables
--   Use nba_game_id for NBA.com API lookups and debugging
--
-- Home/Away Indicator:
--   is_home = TRUE:  This team is the home team
--   is_home = FALSE: This team is the away team
--   Each game has exactly 2 rows: one with is_home=TRUE, one with is_home=FALSE
--
-- Partition Requirement: ALL queries MUST include game_date filter
--   ❌ WRONG: SELECT * FROM nbac_team_boxscore WHERE team_abbr = 'LAL'
--   ✅ RIGHT: SELECT * FROM nbac_team_boxscore WHERE team_abbr = 'LAL' AND game_date >= '2024-10-01'
--
-- Clustering: Optimized for queries filtering/joining on:
--   1. game_id (most common - get both teams for a game)
--   2. team_abbr (team-specific queries)  
--   3. season_year (season-level analysis)
--   4. is_home (home vs away analysis)
--
-- Data Validation: Each game should have exactly 2 rows (one per team)
--   Points should equal: (FG2 * 2) + (3PT * 3) + FT
--   Total rebounds should equal: offensive_rebounds + defensive_rebounds
--   Plus/minus should sum to 0 across both teams
--   Exactly one row should have is_home=TRUE and one is_home=FALSE per game_id
--
-- Related Tables:
--   - nba_raw.bdl_player_boxscores (player-level stats for validation)
--   - nba_raw.nbac_schedule (game schedule and status)
--   - nba_raw.odds_api_player_points_props (prop betting data)

-- ================================================================
-- EXAMPLE QUERIES
-- ================================================================

-- Get team stats for a specific game (returns 2 rows)
-- SELECT *
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_id = '20250115_LAL_PHI'
--   AND game_date = '2025-01-15';

-- Get only home team stats for a game
-- SELECT *
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_id = '20250115_LAL_PHI'
--   AND is_home = TRUE
--   AND game_date = '2025-01-15';
-- -- Returns: PHI (76ers)

-- Get only away team stats for a game
-- SELECT *
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_id = '20250115_LAL_PHI'
--   AND is_home = FALSE
--   AND game_date = '2025-01-15';
-- -- Returns: LAL (Lakers)

-- Lookup by NBA.com game ID
-- SELECT *
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE nba_game_id = '0022400561'
--   AND game_date = '2025-01-15';

-- Team's recent shooting performance (last 30 days)
-- SELECT 
--   game_date,
--   game_id,
--   CASE WHEN is_home THEN 'vs' ELSE '@' END as location,
--   fg_made,
--   fg_attempted,
--   ROUND(fg_percentage * 100, 1) as fg_pct,
--   three_pt_made,
--   three_pt_attempted,
--   points
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE team_abbr = 'LAL'
--   AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
-- ORDER BY game_date DESC;

-- Home vs Away performance comparison
-- SELECT 
--   is_home,
--   COUNT(*) as games,
--   ROUND(AVG(points), 1) as avg_points,
--   ROUND(AVG(fg_percentage) * 100, 1) as avg_fg_pct,
--   ROUND(AVG(three_pt_percentage) * 100, 1) as avg_3pt_pct,
--   ROUND(AVG(CAST(assists AS FLOAT64)), 1) as avg_assists
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE season_year = 2024
--   AND game_date >= '2024-10-01'
-- GROUP BY is_home
-- ORDER BY is_home DESC;

-- Season averages for all teams with home/away splits
-- SELECT 
--   team_abbr,
--   is_home,
--   COUNT(*) as games_played,
--   ROUND(AVG(points), 1) as avg_points,
--   ROUND(AVG(fg_percentage) * 100, 1) as avg_fg_pct,
--   ROUND(AVG(three_pt_percentage) * 100, 1) as avg_3pt_pct,
--   ROUND(AVG(CAST(assists AS FLOAT64)), 1) as avg_assists,
--   ROUND(AVG(CAST(total_rebounds AS FLOAT64)), 1) as avg_rebounds
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE season_year = 2024
--   AND game_date >= '2024-10-01'
-- GROUP BY team_abbr, is_home
-- ORDER BY team_abbr, is_home DESC;

-- Cross-validation with player box scores (verify team totals match)
-- SELECT 
--   t.game_date,
--   t.game_id,
--   t.team_abbr,
--   CASE WHEN t.is_home THEN 'HOME' ELSE 'AWAY' END as location,
--   t.points as team_total,
--   SUM(p.points) as player_sum,
--   t.points - SUM(p.points) as diff
-- FROM `nba_raw.nbac_team_boxscore` t
-- JOIN `nba_raw.bdl_player_boxscores` p
--   ON t.game_id = p.game_id AND t.team_abbr = p.team_abbr
-- WHERE t.game_date >= '2025-01-01'
-- GROUP BY t.game_date, t.game_id, t.team_abbr, t.is_home, t.points
-- HAVING ABS(t.points - SUM(p.points)) > 1
-- ORDER BY t.game_date DESC;

-- ================================================================
-- DATA QUALITY CHECKS
-- ================================================================

-- Check 1: Verify all games have exactly 2 teams
-- SELECT game_id, game_date, COUNT(*) as team_count
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_date >= '2025-01-01'
-- GROUP BY game_id, game_date
-- HAVING COUNT(*) != 2;

-- Check 2: Verify each game has exactly 1 home and 1 away team
-- SELECT game_id, game_date, 
--        SUM(CASE WHEN is_home THEN 1 ELSE 0 END) as home_count,
--        SUM(CASE WHEN NOT is_home THEN 1 ELSE 0 END) as away_count
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_date >= '2025-01-01'
-- GROUP BY game_id, game_date
-- HAVING home_count != 1 OR away_count != 1;

-- Check 3: Verify game_id format matches YYYYMMDD_AWAY_HOME pattern
-- SELECT game_id, game_date, team_abbr, is_home
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_date >= '2025-01-01'
--   AND NOT REGEXP_CONTAINS(game_id, r'^\d{8}_[A-Z]{2,3}_[A-Z]{2,3}$')
-- ORDER BY game_date DESC;

-- Check 4: Verify away team matches first part of game_id and home team matches second part
-- SELECT game_id, game_date, team_abbr, is_home,
--        SPLIT(game_id, '_')[OFFSET(1)] as expected_away,
--        SPLIT(game_id, '_')[OFFSET(2)] as expected_home
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_date >= '2025-01-01'
--   AND (
--     (NOT is_home AND team_abbr != SPLIT(game_id, '_')[OFFSET(1)])
--     OR
--     (is_home AND team_abbr != SPLIT(game_id, '_')[OFFSET(2)])
--   );

-- Check 5: Verify FG math (made ≤ attempted)
-- SELECT game_id, game_date, team_abbr, is_home, fg_made, fg_attempted
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE fg_made > fg_attempted
--   AND game_date >= '2025-01-01';

-- Check 6: Verify 3PT math (3PT made ≤ FG made)
-- SELECT game_id, game_date, team_abbr, is_home, three_pt_made, fg_made
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE three_pt_made > fg_made
--   AND game_date >= '2025-01-01';

-- Check 7: Verify rebound math (offensive + defensive = total)
-- SELECT game_id, game_date, team_abbr, is_home,
--        offensive_rebounds, defensive_rebounds, total_rebounds
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE total_rebounds != offensive_rebounds + defensive_rebounds
--   AND game_date >= '2025-01-01';

-- Check 8: Verify points calculation
-- SELECT game_id, game_date, team_abbr, is_home, points,
--        ((fg_made - three_pt_made) * 2) + (three_pt_made * 3) + ft_made as calculated_points
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE points != ((fg_made - three_pt_made) * 2) + (three_pt_made * 3) + ft_made
--   AND game_date >= '2025-01-01';

-- Check 9: Verify plus/minus sums to zero per game
-- SELECT game_id, game_date, SUM(plus_minus) as plus_minus_sum
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_date >= '2025-01-01'
-- GROUP BY game_id, game_date
-- HAVING SUM(plus_minus) != 0;

-- ================================================================
-- MAINTENANCE QUERIES
-- ================================================================

-- Get table statistics
-- SELECT 
--   COUNT(*) as total_rows,
--   COUNT(DISTINCT game_id) as unique_games,
--   COUNT(DISTINCT nba_game_id) as unique_nba_game_ids,
--   COUNT(DISTINCT team_abbr) as unique_teams,
--   SUM(CASE WHEN is_home THEN 1 ELSE 0 END) as home_records,
--   SUM(CASE WHEN NOT is_home THEN 1 ELSE 0 END) as away_records,
--   MIN(game_date) as earliest_game,
--   MAX(game_date) as latest_game,
--   MAX(processed_at) as last_processed
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE game_date >= '2024-10-01';

-- Get processing status by date
-- SELECT 
--   DATE(processed_at) as process_date,
--   COUNT(*) as records_processed,
--   COUNT(DISTINCT game_id) as unique_games,
--   COUNT(DISTINCT nba_game_id) as unique_nba_game_ids
-- FROM `nba_raw.nbac_team_boxscore`
-- WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
-- GROUP BY process_date
-- ORDER BY process_date DESC;

-- ================================================================
-- MIGRATION FROM V1 TO V2
-- ================================================================
-- If you have existing data without is_home and standardized game_id:
--
-- Step 1: Add new columns (NULL allowed temporarily)
-- ALTER TABLE `nba_raw.nbac_team_boxscore`
-- ADD COLUMN IF NOT EXISTS nba_game_id STRING,
-- ADD COLUMN IF NOT EXISTS is_home BOOLEAN;
--
-- Step 2: Backfill nba_game_id from old game_id
-- UPDATE `nba_raw.nbac_team_boxscore`
-- SET nba_game_id = game_id
-- WHERE nba_game_id IS NULL AND game_date >= '2024-10-01';
--
-- Step 3: Determine home/away and update game_id format
-- -- This requires joining with schedule data or re-processing source files
-- -- Contact your data engineering team for migration script
--
-- Step 4: Make columns NOT NULL after backfill
-- -- (Requires table recreation or careful ALTER TABLE operations)