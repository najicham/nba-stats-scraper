-- ============================================================================
-- PLAYER GAME SUMMARY TABLE (Enhanced with Blowout Analysis & Source Tracking)
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/analytics/player_game_summary_tables.sql
-- Purpose: Individual player performance data per game with comprehensive metrics

CREATE TABLE `nba-props-platform.nba_analytics.player_game_summary` (
  -- Core identifiers
  player_lookup STRING NOT NULL,                    -- Normalized player identifier (e.g., "lebronjames")
  player_full_name STRING,                          -- Display name (e.g., "LeBron James")
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date (partition key)
  team_abbr STRING,                                 -- Player's team abbreviation
  opponent_team_abbr STRING,                        -- Opposing team abbreviation
  season_year INT64,                                -- Season year (e.g., 2025 for 2024-25 season)
  
  -- Basic performance metrics
  points INT64,                                     -- Total points scored
  minutes_string STRING,                            -- Original minutes format ("32:45")
  minutes_played INT64,                             -- Minutes as integer (32)
  assists INT64,                                    -- Assists
  rebounds INT64,                                   -- Total rebounds
  offensive_rebounds INT64,                         -- Offensive rebounds
  defensive_rebounds INT64,                         -- Defensive rebounds
  steals INT64,                                     -- Steals
  blocks INT64,                                     -- Total blocks
  turnovers INT64,                                  -- Turnovers
  personal_fouls INT64,                             -- Personal fouls committed
  plus_minus INT64,                                 -- Plus/minus while on court
  
  -- Shot data by zone (Phase 1 enhancement)
  paint_attempts INT64,                             -- Field goal attempts in paint (≤8 feet)
  paint_makes INT64,                                -- Field goal makes in paint
  three_pt_attempts INT64,                          -- Three-point attempts
  three_pt_makes INT64,                             -- Three-point makes
  mid_range_attempts INT64,                         -- Mid-range attempts (9+ feet, 2PT)
  mid_range_makes INT64,                            -- Mid-range makes
  ft_attempts INT64,                                -- Free throw attempts
  ft_makes INT64,                                   -- Free throw makes
  
  -- Shot defense (blocks by zone)
  paint_blocks INT64,                               -- Blocks on paint shots
  mid_range_blocks INT64,                           -- Blocks on mid-range shots
  three_pt_blocks INT64,                            -- Blocks on three-point shots
  
  -- Shooting opportunities and efficiency
  and1_count INT64,                                 -- Made FG + shooting foul drawn
  
  -- Traditional shooting stats (for validation/cross-source compatibility)
  fg_attempts INT64,                                -- Total field goal attempts (validation only)
  fg_makes INT64,                                   -- Total field goal makes (validation only)
  fg_pct FLOAT64,                                   -- Field goal percentage
  
  -- Advanced efficiency metrics (calculated during processing)
  usage_rate FLOAT64,                               -- % of team plays ended by FGA, FTA, TO while on floor
  ts_pct FLOAT64,                                   -- True Shooting % = points / (2 * (FGA + 0.44 * FTA))
  efg_pct FLOAT64,                                  -- Effective FG % (accounts for 3-point value)
  ftr FLOAT64,                                      -- Free-throw rate = FTA / FGA
  
  -- Game context
  days_rest INT64,                                  -- Days since previous game (NULL for season opener)
  previous_game_minutes INT64,                      -- Minutes played in previous game
  home_game BOOLEAN,                                -- TRUE if playing at home
  starter_flag BOOLEAN,                             -- TRUE if started the game
  win_flag BOOLEAN,                                 -- TRUE if player's team won
  margin_of_victory INT64,                          -- Team points - Opponent points
  overtime_periods INT64,                           -- 0 for regulation, else number of OT periods
  
  -- Pace and possession context
  game_possessions INT64,                           -- Estimated team possessions this game
  pace FLOAT64,                                     -- Possessions per 48 minutes (game-level)
  
  -- Travel and fatigue factors
  travel_distance_km FLOAT64,                       -- Distance from previous game city (for fatigue analysis)
  
  -- Player status and injury tracking
  player_status STRING,                             -- 'active', 'injury', 'dnp'
  status_reason STRING,                             -- Reason for status (e.g., 'rest', 'knee soreness')
  is_active BOOLEAN,                                -- TRUE only when player_status = 'active'
  
  -- Prop betting data
  points_line FLOAT64,                              -- Betting line for player points (NULL if none)
  over_under_result STRING,                         -- 'OVER', 'UNDER', NULL
  margin FLOAT64,                                   -- Actual points - prop line
  
  -- Minutes analysis (BigDataBall enhanced)
  minutes_elapsed_when_over FLOAT64,                -- Game time when player crossed prop line
  projected_minutes_to_over FLOAT64,                -- Additional minutes needed if went under
  went_over_prop BOOLEAN,                           -- TRUE if exceeded prop line
  points_per_minute FLOAT64,                        -- Scoring rate
  
  -- Load management tracking
  back_to_back_flag BOOLEAN,                        -- TRUE if days_rest = 0
  high_load_back_to_back BOOLEAN,                   -- Back-to-back after 35+ minute game
  
  -- Simple blowout analysis (calculated post-game)
  blowout_level INT64,                              -- 1=Close Game, 2=Solid Win, 3=Comfortable, 4=Clear Blowout, 5=Massive (26+ pts)
  blowout_description STRING,                       -- "Close Game", "Solid Win", "Comfortable Win", "Clear Blowout", "Massive Blowout"
  
  -- Data source tracking with timestamps
  performance_source STRING,                        -- "bdl_boxscores", "nbac_gamebook", "bigdataball"
  performance_updated_at TIMESTAMP,                 -- When performance data was last updated
  injury_source STRING,                             -- "nbac_gamebook", "injury_report", "bdl_injury"
  injury_updated_at TIMESTAMP,                      -- When injury data was last updated
  prop_source STRING,                               -- "odds_api", "bettingpros_backup"
  prop_updated_at TIMESTAMP,                        -- When prop data was last updated
  timing_source STRING,                             -- "bigdataball"
  timing_updated_at TIMESTAMP,                      -- When timing data was last updated
  shot_zone_source STRING,                          -- "bigdataball", "bdl_backup"
  shot_zone_updated_at TIMESTAMP,                   -- When shot zone data was last updated
  
  -- Processing metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When record was first created
  processed_at TIMESTAMP                            -- When record was last processed
)
PARTITION BY game_date
CLUSTER BY player_lookup, team_abbr, player_status, performance_source
OPTIONS (
  description = "Individual player performance data per game with comprehensive metrics for prop betting analysis. Includes shot zones, efficiency metrics, prop outcomes, and source tracking.",
  partition_expiration_days = 1095  -- 3 years retention
);

-- ============================================================================
-- INDEXES AND VIEWS FOR COMMON QUERIES
-- ============================================================================

-- View for active players only (most common filter)
CREATE VIEW `nba-props-platform.nba_analytics.player_game_summary_active` AS
SELECT * FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE is_active = TRUE
AND player_status = 'active';

-- View for prop betting analysis (players with betting lines)
CREATE VIEW `nba-props-platform.nba_analytics.player_game_summary_props` AS
SELECT * FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE points_line IS NOT NULL
AND is_active = TRUE;