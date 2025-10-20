-- ============================================================================
-- NBA Props Platform - Upcoming Player Game Context Analytics Table
-- Complete pre-game context for player similarity matching
-- File: schemas/bigquery/analytics/upcoming_player_game_context_tables.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.upcoming_player_game_context` (
  -- Core identifiers (6 fields - UPDATED: added universal_player_id)
  player_lookup STRING NOT NULL,                    -- Normalized player identifier
  universal_player_id STRING,                       -- Universal player ID from registry (e.g., lebronjames_001)
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date for partitioning
  team_abbr STRING NOT NULL,                        -- Player's team abbreviation
  opponent_team_abbr STRING NOT NULL,               -- Opposing team abbreviation
  
  -- Player prop betting context (5 fields)
  current_points_line NUMERIC(4,1),                 -- Most recent player points line
  opening_points_line NUMERIC(4,1),                 -- Opening player points line
  line_movement NUMERIC(4,1),                       -- Current line - opening line
  current_points_line_source STRING,                -- Source of current line
  opening_points_line_source STRING,                -- Source of opening line
  
  -- Game spread context (5 fields)
  game_spread NUMERIC(4,1),                         -- Current point spread
  opening_spread NUMERIC(4,1),                      -- Opening point spread
  spread_movement NUMERIC(4,1),                     -- Current spread - opening spread
  game_spread_source STRING,                        -- Source of current spread
  spread_public_betting_pct NUMERIC(5,2),           -- % of public bets on favorite
  
  -- Game total context (5 fields)
  game_total NUMERIC(5,1),                          -- Current over/under total points
  opening_total NUMERIC(5,1),                       -- Opening total
  total_movement NUMERIC(4,1),                      -- Current total - opening total
  game_total_source STRING,                         -- Source of current total
  total_public_betting_pct NUMERIC(5,2),            -- % of public bets on OVER
  
  -- Pre-game context (8 fields)
  pace_differential NUMERIC(5,1),                   -- Team vs opponent pace
  opponent_pace_last_10 NUMERIC(5,1),               -- Opponent recent pace
  game_start_time_local TIME,                       -- Start time impact
  opponent_ft_rate_allowed NUMERIC(5,3),            -- FT opportunities
  home_game BOOLEAN,                                -- Home vs away
  back_to_back BOOLEAN,                             -- Back-to-back flag
  season_phase STRING,                              -- 'early', 'mid', 'late', 'playoffs'
  projected_usage_rate NUMERIC(5,2),                -- Expected usage based on available players
  
  -- Player fatigue analysis (12 fields)
  days_rest INT64,                                  -- Rest days
  days_rest_before_last_game INT64,                 -- Previous rest
  days_since_2_plus_days_rest INT64,                -- Time since real rest
  games_in_last_7_days INT64,                       -- Weekly load
  games_in_last_14_days INT64,                      -- Bi-weekly load
  minutes_in_last_7_days INT64,                     -- Weekly minutes
  minutes_in_last_14_days INT64,                    -- Bi-weekly minutes
  avg_minutes_per_game_last_7 NUMERIC(5,1),         -- Recent intensity
  back_to_backs_last_14_days INT64,                 -- Recent compression
  avg_usage_rate_last_7_games NUMERIC(5,2),         -- Usage intensity
  fourth_quarter_minutes_last_7 INT64,              -- Crunch time load
  clutch_minutes_last_7_games INT64,                -- High-stress minutes
  
  -- Travel context (5 fields)
  travel_miles INT64,                               -- Travel distance
  time_zone_changes INT64,                          -- Time zones crossed
  consecutive_road_games INT64,                     -- Road trip length
  miles_traveled_last_14_days INT64,                -- Cumulative travel
  time_zones_crossed_last_14_days INT64,            -- Jet lag factor
  
  -- Player characteristics (1 field)
  player_age INT64,                                 -- Current age for fatigue analysis
  
  -- Recent performance context (8 fields)
  points_avg_last_5 NUMERIC(5,1),                   -- Recent form
  points_avg_last_10 NUMERIC(5,1),                  -- Broader trend
  prop_over_streak INT64,                           -- Current over streak
  prop_under_streak INT64,                          -- Current under streak
  star_teammates_out INT64,                         -- Key players out
  opponent_def_rating_last_10 NUMERIC(6,2),         -- Opponent defense
  shooting_pct_decline_last_5 NUMERIC(5,3),         -- Performance decline signal
  fourth_quarter_production_last_7 NUMERIC(5,1),    -- Late-game energy
  
  -- Forward-Looking Schedule Context (4 fields)
  -- TODO: Returns 0/NULL for now, implement in future iteration
  next_game_days_rest INT64,                        -- Days until player's next game
  games_in_next_7_days INT64,                       -- Player's upcoming game density
  next_opponent_win_pct NUMERIC(5,3),               -- Win percentage of player's next opponent
  next_game_is_primetime BOOLEAN,                   -- Whether player's next game is nationally televised
  
  -- Opponent Asymmetry Context (3 fields)
  -- TODO: Implement fully after team context processor is stable
  opponent_days_rest INT64,                         -- Current opponent's rest before this game
  opponent_games_in_next_7_days INT64,              -- Current opponent's upcoming schedule density
  opponent_next_game_days_rest INT64,               -- Current opponent's rest after this game
  
  -- Real-time updates (4 fields)
  player_status STRING,                             -- Injury report status
  injury_report STRING,                             -- Detailed injury info
  questionable_teammates INT64,                     -- Questionable players
  probable_teammates INT64,                         -- Probable players
  
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
CLUSTER BY player_lookup, universal_player_id, game_date
OPTIONS(
  description="Complete pre-game context for player predictions with universal player identification. Forward-looking schedule fields and opponent asymmetry fields are placeholders for future implementation."
);

-- ============================================================================
-- NOTES ON DEFERRED FIELDS
-- ============================================================================
-- The following fields are included in the schema but return default values
-- until their processing logic is fully implemented:
--
-- Forward-Looking Schedule (next_game_days_rest, games_in_next_7_days, 
-- next_opponent_win_pct, next_game_is_primetime):
--   - Schema ready for future implementation
--   - Currently returns 0/NULL/FALSE
--   - Requires forward schedule analysis from team context
--
-- Opponent Asymmetry (opponent_days_rest, opponent_games_in_next_7_days,
-- opponent_next_game_days_rest):
--   - Partially implemented in team context processor
--   - Can be fully calculated once team context is stable
--   - Currently returns values from opponent's team context where available
-- ============================================================================
