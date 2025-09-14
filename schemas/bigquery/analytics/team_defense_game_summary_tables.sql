-- ============================================================================
-- NBA Props Platform - Team Defense Game Summary Analytics Table
-- Team defensive performance results with shot zone tracking
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.team_defense_game_summary` (
  -- Core identifiers (5 fields)
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date for partitioning
  defending_team_abbr STRING NOT NULL,              -- Team playing defense
  opponent_team_abbr STRING NOT NULL,               -- Opposing offensive team
  season_year INT64 NOT NULL,                       -- Season year
  
  -- Defensive stats (opponent performance allowed) (11 fields)
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
  
  -- Defensive shot zone performance (6 fields)
  opp_paint_attempts INT64,                         -- Paint shot attempts allowed
  opp_paint_makes INT64,                            -- Paint shot makes allowed
  opp_mid_range_attempts INT64,                     -- Mid-range attempts allowed
  opp_mid_range_makes INT64,                        -- Mid-range makes allowed
  points_in_paint_allowed INT64,                    -- Points in paint allowed
  second_chance_points_allowed INT64,               -- Points from opponent offensive rebounds
  
  -- Defensive actions (5 fields)
  blocks_paint INT64,                               -- Blocks on paint shots
  blocks_mid_range INT64,                           -- Blocks on mid-range shots
  blocks_three_pt INT64,                            -- Blocks on three-point shots
  steals INT64,                                     -- Total steals by defending team
  defensive_rebounds INT64,                         -- Defensive rebounds secured
  
  -- Advanced defensive metrics (3 fields)
  defensive_rating NUMERIC(6,2),                    -- Points allowed per 100 possessions
  opponent_pace NUMERIC(5,1),                       -- Pace allowed to opponent
  opponent_ts_pct NUMERIC(5,3),                     -- True shooting percentage allowed
  
  -- Game context (4 fields)
  home_game BOOLEAN NOT NULL,                       -- Whether defending team was at home
  win_flag BOOLEAN NOT NULL,                        -- Whether defending team won
  margin_of_victory INT64,                          -- Point margin (positive = won)
  overtime_periods INT64,                           -- Number of overtime periods
  
  -- Team situation context (2 fields)
  players_inactive INT64,                           -- Number of defensive players inactive
  starters_inactive INT64,                          -- Number of starting defenders inactive
  
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
CLUSTER BY defending_team_abbr, game_date
OPTIONS(
  description="Team defensive performance results with shot zone tracking - context comes from upcoming_team_game_context"
);