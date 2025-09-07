-- ============================================================================
-- TEAM DEFENSE GAME LOG (Enhanced with Blowout Analysis & Source Tracking)
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/analytics/team_defense_game_log_tables.sql
-- Purpose: Team defensive performance data per game with opponent shooting allowed and defensive metrics

CREATE TABLE `nba-props-platform.nba_analytics.team_defense_game_log` (
  -- Core identifiers
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date (partition key)
  defending_team_abbr STRING NOT NULL,              -- Team playing defense
  opponent_team_abbr STRING NOT NULL,               -- Opposing offensive team
  season_year INT64,                                -- Season year
  
  -- Basic opponent shooting allowed by zone
  opp_paint_attempts INT64,                         -- Paint shot attempts allowed
  opp_paint_makes INT64,                            -- Paint shot makes allowed
  opp_three_pt_attempts INT64,                      -- Three-point attempts allowed
  opp_three_pt_makes INT64,                         -- Three-point makes allowed
  opp_mid_range_attempts INT64,                     -- Mid-range attempts allowed
  opp_mid_range_makes INT64,                        -- Mid-range makes allowed
  
  -- Enhanced three-point zone breakdown
  opp_corner3_attempts INT64,                       -- Corner three-point attempts allowed
  opp_corner3_makes INT64,                          -- Corner three-point makes allowed
  opp_above_break3_attempts INT64,                  -- Above-the-break three-point attempts allowed
  opp_above_break3_makes INT64,                     -- Above-the-break three-point makes allowed
  
  -- Total field goals allowed
  opp_fg_attempts INT64,                            -- Total field goal attempts allowed
  opp_fg_makes INT64,                               -- Total field goal makes allowed
  
  -- Free throws and fouls
  opp_ft_attempts INT64,                            -- Free throw attempts allowed
  opp_ft_makes INT64,                               -- Free throw makes allowed
  shooting_fouls_committed INT64,                   -- Shooting fouls committed
  non_shooting_fouls_committed INT64,               -- Non-shooting defensive fouls
  offensive_fouls_drawn INT64,                      -- Charges/offensive fouls drawn
  
  -- Foul detail by zone
  paint_fouls_committed INT64,                      -- Shooting fouls on paint attempts
  three_pt_fouls_committed INT64,                   -- Shooting fouls on three-point attempts
  mid_range_fouls_committed INT64,                  -- Shooting fouls on mid-range attempts
  
  -- Defensive stats generated
  blocks_paint INT64,                               -- Blocks on paint shots
  blocks_mid_range INT64,                           -- Blocks on mid-range shots
  blocks_three_pt INT64,                            -- Blocks on three-point shots
  total_blocks INT64,                               -- Total blocks
  steals INT64,                                     -- Steals
  deflections INT64,                                -- Deflections (if available)
  
  -- Rebounding
  team_defensive_rebounds INT64,                    -- Team defensive rebounds
  opp_offensive_rebounds INT64,                     -- Offensive rebounds allowed to opponent
  
  -- Turnovers
  turnovers_forced INT64,                           -- Total turnovers forced
  
  -- Points allowed breakdown
  points_allowed INT64,                             -- Total points allowed
  points_in_paint_allowed INT64,                    -- Points in paint allowed
  second_chance_points_allowed INT64,               -- Points from opponent offensive rebounds
  
  -- Four Factors (defensive metrics)
  def_efg_allowed FLOAT64,                          -- Effective FG% allowed
  def_tov_rate FLOAT64,                             -- Turnover rate forced
  def_drb_pct FLOAT64,                              -- Defensive rebound %
  def_ft_rate_allowed FLOAT64,                      -- Free throw rate allowed
  
  -- Pace and possessions
  possessions_estimate INT64,                       -- Estimated possessions
  possessions_method STRING,                        -- Calculation method
  game_pace FLOAT64,                                -- Possessions per 48 minutes
  opponent_pace FLOAT64,                            -- Opponent's pace this game
  opponent_avg_pace_pre_game FLOAT64,               -- Opponent's season pace
  defensive_pace_impact FLOAT64,                    -- Pace change caused by defense
  defensive_rating FLOAT64,                         -- Points allowed per 100 possessions
  
  -- Game context
  home_game BOOLEAN,                                -- Home/away indicator
  win_flag BOOLEAN,                                 -- Win/loss result
  margin_of_victory INT64,                          -- Score differential
  overtime_periods INT64,                           -- Overtime periods
  final_score_defense INT64,                        -- Defending team score
  final_score_opponent INT64,                       -- Opponent score
  
  -- Market context
  closing_spread FLOAT64,                           -- Betting spread
  closing_total FLOAT64,                            -- Game total
  team_implied_total FLOAT64,                       -- Team implied points
  opp_implied_total FLOAT64,                        -- Opponent implied points
  
  -- Simple blowout analysis (calculated post-game)
  blowout_level INT64,                              -- 1=Close Game, 2=Solid Win, 3=Comfortable, 4=Clear Blowout, 5=Massive (26+ pts)
  blowout_description STRING,                       -- "Close Game", "Solid Win", "Comfortable Win", "Clear Blowout", "Massive Blowout"
  
  -- Data source tracking with timestamps
  shot_zone_source STRING,                          -- "bigdataball", "calculated_from_opponents"
  shot_zone_updated_at TIMESTAMP,                   -- When shot zone data was last updated
  defensive_stats_source STRING,                    -- "player_aggregation", "nbac_official_team_totals"
  defensive_stats_updated_at TIMESTAMP,             -- When defensive totals were calculated
  pace_source STRING,                               -- "bigdataball_possessions", "standard_formula"
  pace_updated_at TIMESTAMP,                        -- When pace calculations were updated
  
  -- Processing metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When record was created
  processed_at TIMESTAMP                            -- When record was last processed
)
PARTITION BY game_date
CLUSTER BY defending_team_abbr, opponent_team_abbr, season_year
OPTIONS (
  description = "Team defensive performance data per game with opponent shooting allowed and defensive metrics for strength-of-schedule analysis.",
  partition_expiration_days = 1095  -- 3 years retention
);

-- ============================================================================
-- VIEWS FOR COMMON TEAM DEFENSIVE ANALYSIS
-- ============================================================================

-- View for defensive efficiency and strength
CREATE VIEW `nba-props-platform.nba_analytics.team_defense_efficiency` AS
SELECT 
  defending_team_abbr,
  season_year,
  game_date,
  defensive_rating,
  def_efg_allowed,
  def_tov_rate,
  def_drb_pct,
  def_ft_rate_allowed,
  points_allowed,
  blowout_level,
  defensive_pace_impact
FROM `nba-props-platform.nba_analytics.team_defense_game_log`
WHERE defensive_stats_source IS NOT NULL;

-- View for opponent shooting allowed by zone
CREATE VIEW `nba-props-platform.nba_analytics.team_defense_shot_zones` AS
SELECT 
  defending_team_abbr,
  opponent_team_abbr,
  game_date,
  season_year,
  opp_paint_attempts,
  opp_paint_makes,
  SAFE_DIVIDE(opp_paint_makes, opp_paint_attempts) as paint_fg_pct_allowed,
  opp_three_pt_attempts,
  opp_three_pt_makes,
  SAFE_DIVIDE(opp_three_pt_makes, opp_three_pt_attempts) as three_pt_pct_allowed,
  opp_mid_range_attempts,
  opp_mid_range_makes,
  SAFE_DIVIDE(opp_mid_range_makes, opp_mid_range_attempts) as mid_range_pct_allowed,
  SAFE_DIVIDE(opp_three_pt_attempts, opp_fg_attempts) as three_pt_rate_allowed,
  total_blocks,
  blocks_paint,
  blocks_three_pt
FROM `nba-props-platform.nba_analytics.team_defense_game_log`
WHERE shot_zone_source IS NOT NULL;

-- View for defensive impact summary (useful for prop analysis)
CREATE VIEW `nba-props-platform.nba_analytics.team_defense_impact` AS
SELECT 
  defending_team_abbr,
  opponent_team_abbr,
  game_date,
  season_year,
  defensive_rating,
  points_allowed,
  turnovers_forced,
  total_blocks,
  steals,
  opp_offensive_rebounds,
  blowout_level,
  win_flag
FROM `nba-props-platform.nba_analytics.team_defense_game_log`;