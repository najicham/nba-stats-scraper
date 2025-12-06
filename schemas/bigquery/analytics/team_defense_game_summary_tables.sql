-- ============================================================================
-- NBA Props Platform - Team Defense Game Summary Analytics Table
-- Path: schemas/bigquery/analytics/team_defense_game_summary_v2.sql
-- Team defensive performance results aggregated from Phase 2 raw data
-- Version: 2.0 (Phase 2 architecture with dependency tracking v4.0)
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.team_defense_game_summary` (
  -- ============================================================================
  -- CORE IDENTIFIERS (5 fields)
  -- ============================================================================
  game_id STRING NOT NULL,                          -- Standardized game ID: YYYYMMDD_AWAY_HOME
  game_date DATE NOT NULL,                          -- Game date for partitioning
  defending_team_abbr STRING NOT NULL,              -- Team playing defense
  opponent_team_abbr STRING NOT NULL,               -- Opposing offensive team
  season_year INT64 NOT NULL,                       -- Season year
  
  -- ============================================================================
  -- DEFENSIVE STATS - Opponent Performance Allowed (11 fields)
  -- Derived from opponent's offensive stats in Phase 2 team boxscore
  -- ============================================================================
  points_allowed INT64,                             -- Total points allowed to opponent
  opp_fg_attempts INT64,                            -- Field goal attempts allowed
  opp_fg_makes INT64,                               -- Field goal makes allowed
  opp_three_pt_attempts INT64,                      -- Three-point attempts allowed
  opp_three_pt_makes INT64,                         -- Three-point makes allowed
  opp_ft_attempts INT64,                            -- Free throw attempts allowed
  opp_ft_makes INT64,                               -- Free throw makes allowed
  opp_rebounds INT64,                               -- Rebounds allowed to opponent
  opp_assists INT64,                                -- Assists allowed to opponent
  turnovers_forced INT64,                           -- Turnovers forced by defense
  fouls_committed INT64,                            -- Fouls committed by defending team
  
  -- ============================================================================
  -- DEFENSIVE SHOT ZONE PERFORMANCE (9 fields)
  -- Currently NULL - requires play-by-play data (Phase 2 enhancement)
  -- ============================================================================
  opp_paint_attempts INT64,                         -- Paint shot attempts allowed
  opp_paint_makes INT64,                            -- Paint shot makes allowed
  opp_mid_range_attempts INT64,                     -- Mid-range attempts allowed
  opp_mid_range_makes INT64,                        -- Mid-range makes allowed
  
  -- Points allowed by zone (calculated from makes when available)
  points_in_paint_allowed INT64,                    -- Points from paint shots (2 × makes)
  mid_range_points_allowed INT64,                   -- Points from mid-range (2 × makes)
  three_pt_points_allowed INT64,                    -- Points from three-pointers (3 × makes)
  
  -- Special situations (Phase 2 enhancement)
  second_chance_points_allowed INT64,               -- Points from offensive rebounds
  fast_break_points_allowed INT64,                  -- Points from fast breaks
  
  -- ============================================================================
  -- DEFENSIVE ACTIONS (5 fields)
  -- Aggregated from Phase 2 player boxscores
  -- ============================================================================
  blocks_paint INT64,                               -- Blocks on paint shots (need play-by-play)
  blocks_mid_range INT64,                           -- Blocks on mid-range (need play-by-play)
  blocks_three_pt INT64,                            -- Blocks on three-pointers (need play-by-play)
  steals INT64,                                     -- Total steals by defending team
  defensive_rebounds INT64,                         -- Defensive rebounds secured
  
  -- ============================================================================
  -- ADVANCED DEFENSIVE METRICS (3 fields)
  -- Calculated from opponent offensive efficiency
  -- ============================================================================
  defensive_rating NUMERIC(6,2),                    -- Points allowed per 100 possessions
  opponent_pace NUMERIC(5,1),                       -- Pace allowed to opponent
  opponent_ts_pct NUMERIC(5,3),                     -- True shooting percentage allowed
  
  -- ============================================================================
  -- GAME CONTEXT (4 fields)
  -- ============================================================================
  home_game BOOLEAN NOT NULL,                       -- Whether defending team was at home
  win_flag BOOLEAN,                                 -- Whether defending team won
  margin_of_victory INT64,                          -- Point margin (positive = won)
  overtime_periods INT64,                           -- Number of overtime periods
  
  -- ============================================================================
  -- TEAM SITUATION CONTEXT (2 fields)
  -- Currently NULL - requires injury/roster data (Phase 2 enhancement)
  -- ============================================================================
  players_inactive INT64,                           -- Number of defensive players inactive
  starters_inactive INT64,                          -- Number of starting defenders inactive
  
  -- ============================================================================
  -- REFEREE INTEGRATION (1 field)
  -- Currently NULL - requires referee data (Phase 2 enhancement)
  -- ============================================================================
  referee_crew_id STRING,                           -- Links to game_referees table
  
  -- ============================================================================
  -- DATA QUALITY TRACKING (3 fields)
  -- Tracks which Phase 2 sources were used
  -- ============================================================================
  data_quality_tier STRING,                         -- 'high', 'medium', 'low'
  primary_source_used STRING,                       -- e.g., "nbac_team_boxscore+nbac_gamebook"
  processed_with_issues BOOLEAN,                    -- TRUE if defensive actions missing
  
  -- ============================================================================
  -- DEPENDENCY TRACKING v4.0 - PHASE 2 SOURCES (12 fields = 3 sources × 4 fields)
  -- Tracks which Phase 2 raw tables were used and their quality + Smart Idempotency (Pattern #14)
  -- ============================================================================

  -- Source 1: nbac_team_boxscore (opponent's offensive stats) - CRITICAL
  source_team_boxscore_last_updated TIMESTAMP,      -- When team boxscore was processed
  source_team_boxscore_rows_found INT64,            -- How many team boxscore records found
  source_team_boxscore_completeness_pct NUMERIC(5,2), -- % of expected data found
  source_team_boxscore_hash STRING,                 -- Smart Idempotency: data_hash from nbac_team_boxscore

  -- Source 2: nbac_gamebook_player_stats (defensive actions) - PRIMARY
  source_gamebook_players_last_updated TIMESTAMP,   -- When gamebook was processed
  source_gamebook_players_rows_found INT64,         -- How many player records found
  source_gamebook_players_completeness_pct NUMERIC(5,2), -- % of expected players found
  source_gamebook_players_hash STRING,              -- Smart Idempotency: data_hash from nbac_gamebook_player_stats

  -- Source 3: bdl_player_boxscores (defensive actions fallback) - OPTIONAL
  source_bdl_players_last_updated TIMESTAMP,        -- When BDL data was processed
  source_bdl_players_rows_found INT64,              -- How many BDL player records used
  source_bdl_players_completeness_pct NUMERIC(5,2), -- % of expected players found
  source_bdl_players_hash STRING,                   -- Smart Idempotency: data_hash from bdl_player_boxscores
  
  -- ============================================================================
  -- SMART REPROCESSING (1 field)
  -- Pattern #3: Phase 4 processors compare this hash to detect meaningful changes
  -- ============================================================================
  data_hash STRING,                                 -- SHA256 hash (16 chars) of meaningful analytics output fields

  -- ============================================================================
  -- PROCESSING METADATA (2 fields)
  -- ============================================================================
  processed_at TIMESTAMP NOT NULL,                  -- When this defensive record was created
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()  -- Row creation timestamp
)
PARTITION BY game_date
CLUSTER BY defending_team_abbr, game_date, data_quality_tier
OPTIONS(
  description="Team defensive performance aggregated from Phase 2 raw data (v2.0). Reads: nbac_team_boxscore (opponent offense), nbac_gamebook_player_stats (defensive actions), bdl_player_boxscores (fallback). Feeds into: Phase 4 precompute processors. Smart idempotency tracks upstream Phase 2 data_hash values to skip reprocessing when source data unchanged."
);

-- ============================================================================
-- VIEWS FOR MONITORING & ANALYSIS
-- ============================================================================

-- View: Recent high-quality defensive stats
CREATE OR REPLACE VIEW `nba_analytics.team_defense_recent_quality` AS
SELECT 
  game_date,
  defending_team_abbr,
  opponent_team_abbr,
  points_allowed,
  defensive_rating,
  steals,
  turnovers_forced,
  data_quality_tier,
  primary_source_used
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  AND data_quality_tier IN ('high', 'medium')
ORDER BY game_date DESC, defending_team_abbr;

-- View: Data quality monitoring
CREATE OR REPLACE VIEW `nba_analytics.team_defense_quality_check` AS
SELECT 
  game_date,
  COUNT(*) as total_records,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT defending_team_abbr) as unique_teams,
  
  -- Quality distribution
  COUNT(CASE WHEN data_quality_tier = 'high' THEN 1 END) as high_quality,
  COUNT(CASE WHEN data_quality_tier = 'medium' THEN 1 END) as medium_quality,
  COUNT(CASE WHEN data_quality_tier = 'low' THEN 1 END) as low_quality,
  
  -- Source usage
  COUNT(CASE WHEN primary_source_used LIKE '%nbac_gamebook%' THEN 1 END) as using_gamebook,
  COUNT(CASE WHEN primary_source_used LIKE '%bdl_player%' THEN 1 END) as using_bdl_fallback,
  
  -- Completeness
  AVG(source_team_boxscore_completeness_pct) as avg_team_boxscore_completeness,
  AVG(source_gamebook_players_completeness_pct) as avg_gamebook_completeness,
  
  -- Data availability
  COUNT(CASE WHEN steals IS NOT NULL AND steals > 0 THEN 1 END) as has_steals_data,
  COUNT(CASE WHEN defensive_rating IS NOT NULL THEN 1 END) as has_defensive_rating
  
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- View: Source freshness monitoring
CREATE OR REPLACE VIEW `nba_analytics.team_defense_source_freshness` AS
SELECT 
  game_date,
  defending_team_abbr,
  
  -- Calculate age of each source
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_boxscore_last_updated, HOUR) as team_boxscore_age_hours,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_gamebook_players_last_updated, HOUR) as gamebook_age_hours,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_bdl_players_last_updated, HOUR) as bdl_age_hours,
  
  -- Completeness
  source_team_boxscore_completeness_pct,
  source_gamebook_players_completeness_pct,
  source_bdl_players_completeness_pct,
  
  -- Overall quality
  data_quality_tier,
  processed_at
  
FROM `nba_analytics.team_defense_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
  AND (
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_team_boxscore_last_updated, HOUR) > 72
    OR source_team_boxscore_completeness_pct < 90
  )
ORDER BY game_date DESC, team_boxscore_age_hours DESC;

-- ============================================================================
-- USAGE NOTES
-- ============================================================================
--
-- ARCHITECTURE CHANGE (v2.0):
--   v1.0: Read from Phase 3 tables (team_offense_game_summary, player_game_summary)
--   v2.0: Read from Phase 2 raw tables (nbac_team_boxscore, nbac_gamebook_player_stats)
--   
--   This eliminates circular Phase 3 dependencies and properly follows
--   Phase 2 → Phase 3 → Phase 4 architecture.
--
-- DEPENDENCIES (Phase 2 Raw Tables):
--   CRITICAL: nba_raw.nbac_team_boxscore (opponent offensive stats)
--   PRIMARY:  nba_raw.nbac_gamebook_player_stats (defensive actions)
--   FALLBACK: nba_raw.bdl_player_boxscores (when gamebook incomplete)
--
-- DATA FLOW:
--   1. Extract opponent's offensive stats from nbac_team_boxscore
--   2. Flip perspective: opponent's offense = this team's defense
--   3. Aggregate defensive actions from gamebook player stats
--   4. Fall back to BDL if gamebook missing/incomplete
--   5. Combine into complete defensive summary
--
-- DATA QUALITY TIERS:
--   high:   Has defensive actions from nbac_gamebook
--   medium: Has defensive actions from bdl_player_boxscores fallback
--   low:    Missing defensive actions (opponent stats only)
--
-- MULTI-SOURCE STRATEGY:
--   Processor tries sources in priority order:
--   1. nbac_gamebook_player_stats (best quality, name resolution)
--   2. bdl_player_boxscores (good quality, fallback)
--   3. nbac_player_boxscores (last resort, rarely needed)
--
-- DEFERRED FIELDS (Need additional Phase 2 data):
--   Shot zones: Requires play-by-play data
--   Blocks by zone: Requires play-by-play data
--   Injury data: Requires roster/injury scraper
--   Referee data: Requires referee scraper
--
-- DOWNSTREAM USAGE (Phase 4):
--   - team_defense_zone_analysis (aggregates last 15 games)
--   - player_zone_matchup_matrix (opponent defense for matchups)
--   - player_composite_factors (defensive strength factor)
--
-- MONITORING ALERTS:
--   - Alert if source_team_boxscore_completeness_pct < 90%
--   - Alert if data_quality_tier = 'low' for >20% of records
--   - Alert if any source >72 hours old
--   - Alert if processed_with_issues = TRUE for >10% of records
--
-- ============================================================================
-- MIGRATION FROM v1.0
-- ============================================================================
--
-- To migrate from v1.0 schema (Phase 3 dependencies):
--
-- 1. Add new dependency tracking fields:
--    ALTER TABLE ... ADD COLUMN source_team_boxscore_last_updated TIMESTAMP;
--    (repeat for all 9 new fields)
--
-- 2. Deploy new processor (reads Phase 2 instead of Phase 3)
--
-- 3. Reprocess historical data if needed
--
-- 4. Verify Phase 4 processors still work (schema unchanged)
--
-- ============================================================================
-- END OF SCHEMA
-- ============================================================================