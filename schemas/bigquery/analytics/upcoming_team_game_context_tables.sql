-- ============================================================================
-- NBA Props Platform - Upcoming Team Game Context Analytics Table
-- Team-level context for upcoming games with fatigue, personnel, and betting intelligence
-- File: schemas/bigquery/analytics/upcoming_team_game_context_tables.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.upcoming_team_game_context` (
  -- Core identifiers (5 fields)
  team_abbr STRING NOT NULL,                        -- Team abbreviation
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date for partitioning
  opponent_team_abbr STRING NOT NULL,               -- Opposing team abbreviation
  season_year INT64 NOT NULL,                       -- Season year
  
  -- Game spread context (5 fields)
  game_spread NUMERIC(4,1),                         -- Current point spread
  opening_spread NUMERIC(4,1),                      -- Opening point spread
  spread_movement NUMERIC(4,1),                     -- Current - opening
  game_spread_source STRING,                        -- Source of current spread
  spread_public_betting_pct NUMERIC(5,2),           -- % of public bets on favorite
  
  -- Game total context (5 fields)
  game_total NUMERIC(5,1),                          -- Current over/under total
  opening_total NUMERIC(5,1),                       -- Opening total
  total_movement NUMERIC(4,1),                      -- Current - opening
  game_total_source STRING,                         -- Source of current total
  total_public_betting_pct NUMERIC(5,2),            -- % of public bets on OVER
  
  -- Core team fatigue (6 fields)
  team_days_rest INT64,                             -- Days since last game
  team_back_to_back BOOLEAN,                        -- Back-to-back flag
  games_in_last_7_days INT64,                       -- Weekly load
  games_in_last_14_days INT64,                      -- Bi-weekly load
  back_to_backs_last_14_days INT64,                 -- Recent compression
  consecutive_road_games INT64,                     -- Current road trip
  
  -- Personnel context (3 fields)
  starters_out_count INT64,                         -- Confirmed starters out
  star_players_out_count INT64,                     -- Top 3 overall impact players out
  questionable_players_count INT64,                 -- Injury report questionable
  
  -- Team momentum context (2 fields)
  team_win_streak_entering INT64,                   -- Current win streak (0 if none)
  team_loss_streak_entering INT64,                  -- Current loss streak (0 if none)
  
  -- Recent performance context (6 fields)
  -- TODO: ATS and over/under streaks return 0 until implemented
  last_game_margin INT64,                           -- Point margin last game (+ = won, - = lost)
  ats_cover_streak INT64,                           -- Covers streak (0 if none)
  ats_fail_streak INT64,                            -- ATS losing streak (0 if none)
  over_streak INT64,                                -- Team total overs streak (0 if none)
  under_streak INT64,                               -- Team total unders streak (0 if none)
  ats_record_last_10 STRING,                        -- "7-3" format for quick reference
  
  -- Basic game context (2 fields)
  home_game BOOLEAN NOT NULL,                       -- Home court advantage
  travel_miles INT64,                               -- Travel distance
  
  -- Team Forward-Looking Schedule Context (4 fields)
  -- TODO: Partially implemented, some fields return 0/NULL/FALSE
  team_next_game_days_rest INT64,                   -- Days until team's next game
  team_games_in_next_7_days INT64,                  -- Team's upcoming game density
  next_opponent_win_pct NUMERIC(5,3),               -- Win percentage of team's next opponent
  next_game_is_primetime BOOLEAN,                   -- Whether team's next game is nationally televised
  
  -- Opponent Asymmetry Context (3 fields)
  opponent_days_rest INT64,                         -- Current opponent's rest before this game
  opponent_games_in_next_7_days INT64,              -- Current opponent's upcoming schedule density
  opponent_next_game_days_rest INT64,               -- Current opponent's rest after this game
  
  -- Market context (4 fields)
  -- TODO: These are populated post-game, NULL for pre-game context
  closing_spread NUMERIC(4,1),                      -- Final betting spread
  closing_total NUMERIC(5,1),                       -- Final game total
  team_implied_total NUMERIC(5,1),                  -- Team's expected scoring
  opp_implied_total NUMERIC(5,1),                   -- Opponent's expected scoring
  
  -- Referee integration (1 field)
  referee_crew_id STRING,                           -- Links to nba_raw.nbac_referee_game_pivot view
  
  -- Data quality (3 fields)
  data_quality_tier STRING,                        -- 'high', 'medium', 'low'
  primary_source_used STRING,                       -- Primary data source
  processed_with_issues BOOLEAN,                    -- Issues flag
  
  -- Update tracking (3 fields) 
  context_version INT64,                            -- Update counter  
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY team_abbr, game_date
OPTIONS(
  description="Team-level context for upcoming games with fatigue, personnel, betting intelligence, and forward-looking schedule psychology. Deferred fields noted in comments."
);

-- ============================================================================
-- NOTES ON DEFERRED FIELDS
-- ============================================================================
-- The following fields are included in the schema but return default values
-- until their processing logic is fully implemented:
--
-- ATS Streaks (ats_cover_streak, ats_fail_streak, ats_record_last_10):
--   - Schema ready for future implementation
--   - Requires matching historical spreads with game results
--   - Currently returns 0 or "0-0"
--
-- Over/Under Streaks (over_streak, under_streak):
--   - Schema ready for future implementation  
--   - Requires matching historical totals with game results
--   - Currently returns 0
--
-- Forward Schedule Details (team_games_in_next_7_days, next_opponent_win_pct,
-- next_game_is_primetime):
--   - Partially implemented (team_next_game_days_rest works)
--   - Rest require additional schedule parsing logic
--   - Currently returns 0/NULL/FALSE
--
-- Market Closing Lines (closing_spread, closing_total, team_implied_total,
-- opp_implied_total):
--   - These are populated POST-GAME
--   - Always NULL for pre-game context records
--   - Updated after game completes for historical analysis
-- ============================================================================
