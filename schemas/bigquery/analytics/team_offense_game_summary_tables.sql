-- ============================================================================
-- NBA Props Platform - Team Offense Game Summary Analytics Table
-- Team offensive performance results with shot zone tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.team_offense_game_summary` (
  -- Core identifiers (5 fields)
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date for partitioning
  team_abbr STRING NOT NULL,                        -- Team playing offense
  opponent_team_abbr STRING NOT NULL,               -- Opposing defensive team
  season_year INT64 NOT NULL,                       -- Season year
  
  -- Basic offensive stats (11 fields)
  points_scored INT64,                              -- Total points scored by team
  fg_attempts INT64,                                -- Total field goal attempts
  fg_makes INT64,                                   -- Total field goal makes
  three_pt_attempts INT64,                          -- Three-point attempts
  three_pt_makes INT64,                             -- Three-point makes
  ft_attempts INT64,                                -- Free throw attempts
  ft_makes INT64,                                   -- Free throw makes
  rebounds INT64,                                   -- Total rebounds
  assists INT64,                                    -- Total assists
  turnovers INT64,                                  -- Total turnovers
  personal_fouls INT64,                             -- Personal fouls committed
  
  -- Team shot zone performance (6 fields)
  team_paint_attempts INT64,                        -- Paint shot attempts
  team_paint_makes INT64,                           -- Paint shot makes
  team_mid_range_attempts INT64,                    -- Mid-range attempts
  team_mid_range_makes INT64,                       -- Mid-range makes
  points_in_paint_scored INT64,                     -- Points from paint shots
  second_chance_points_scored INT64,                -- Points immediately after offensive rebounds
  
  -- Advanced offensive metrics (4 fields)
  offensive_rating NUMERIC(6,2),                    -- Points per 100 possessions
  pace NUMERIC(5,1),                                -- Possessions per 48 minutes
  possessions INT64,                                -- Estimated total possessions
  ts_pct NUMERIC(5,3),                              -- Team true shooting percentage
  
  -- Game context (4 fields)
  home_game BOOLEAN NOT NULL,                       -- Whether team was playing at home
  win_flag BOOLEAN NOT NULL,                        -- Whether team won
  margin_of_victory INT64,                          -- Point margin (positive = won)
  overtime_periods INT64,                           -- Number of overtime periods
  
  -- Team situation context (2 fields)
  players_inactive INT64,                           -- Number of players inactive/out
  starters_inactive INT64,                          -- Number of regular starters inactive
  
  -- Referee integration (1 field)
  referee_crew_id STRING,                           -- Links to game_referees table
  
  -- Data quality tracking (3 fields)
  data_quality_tier STRING,                        -- 'high', 'medium', 'low'
  primary_source_used STRING,                       -- Source: "bdl_boxscores", "nba_scoreboard", etc.
  processed_with_issues BOOLEAN,                    -- TRUE if quality events logged
  
  -- Processing metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY team_abbr, game_date
OPTIONS(
  description="Team offensive performance results with shot zone tracking - context comes from upcoming_team_game_context"
);