-- ============================================================================
-- TEAM OFFENSE GAME LOG (Enhanced with Blowout Analysis & Source Tracking)
-- ============================================================================
-- Location: nba-stats-scraper/schemas/bigquery/analytics/team_offense_game_log_tables.sql
-- Purpose: Team offensive performance data per game with detailed shot zones and efficiency metrics

CREATE TABLE `nba-props-platform.nba_analytics.team_offense_game_log` (
  -- Core identifiers
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date (partition key)
  team_abbr STRING NOT NULL,                        -- Team playing offense
  opponent_team_abbr STRING NOT NULL,               -- Opposing defensive team
  season_year INT64,                                -- Season year
  
  -- Team shot distribution by zone
  team_paint_attempts INT64,                        -- Paint shot attempts
  team_paint_makes INT64,                           -- Paint shot makes
  team_three_pt_attempts INT64,                     -- Three-point attempts
  team_three_pt_makes INT64,                        -- Three-point makes
  team_mid_range_attempts INT64,                    -- Mid-range attempts
  team_mid_range_makes INT64,                       -- Mid-range makes
  
  -- Enhanced three-point zone breakdown
  team_corner3_attempts INT64,                      -- Corner three-point attempts
  team_corner3_makes INT64,                         -- Corner three-point makes
  team_above_break3_attempts INT64,                 -- Above-the-break three-point attempts
  team_above_break3_makes INT64,                    -- Above-the-break three-point makes
  
  -- Total field goals
  team_fg_attempts INT64,                           -- Total field goal attempts
  team_fg_makes INT64,                              -- Total field goal makes
  
  -- Free throws
  team_ft_attempts INT64,                           -- Free throw attempts
  team_ft_makes INT64,                              -- Free throw makes
  shooting_fouls_drawn INT64,                       -- Shooting fouls drawn from opponent
  
  -- Offensive stats generated
  offensive_rebounds INT64,                         -- Offensive rebounds
  assists INT64,                                    -- Total assists
  turnovers INT64,                                  -- Turnovers committed
  
  -- Assist detail by zone
  paint_assists INT64,                              -- Assists leading to paint scores
  three_pt_assists INT64,                           -- Assists leading to three-pointers
  mid_range_assists INT64,                          -- Assists leading to mid-range scores
  
  -- Shot creation detail
  assisted_fg_makes INT64,                          -- Made FGs that were assisted
  unassisted_fg_makes INT64,                        -- Made FGs unassisted (shows shot creation)
  and1_count INT64,                                 -- Made FG + shooting foul drawn
  
  -- Four Factors (offensive metrics)
  off_efg_pct FLOAT64,                              -- Effective FG% = (FGM + 0.5*3PM) / FGA
  off_tov_rate FLOAT64,                             -- Turnover rate = TOV / possessions
  off_orb_pct FLOAT64,                              -- Offensive rebound % = ORB / (ORB + opp DRB)
  off_ft_rate FLOAT64,                              -- Free throw rate = FTA / FGA
  
  -- Helper field for calculations
  opponent_defensive_rebounds INT64,                -- Opponent defensive rebounds (for ORB% calc)
  
  -- Shooting efficiency and distribution
  ts_pct FLOAT64,                                   -- True Shooting % = Points / (2 * (FGA + 0.44*FTA))
  three_point_rate FLOAT64,                         -- Three-point rate = 3PA / FGA
  mid_range_rate FLOAT64,                           -- Mid-range rate = Mid-range attempts / FGA
  
  -- Points breakdown
  points_scored INT64,                              -- Total points scored (validation field)
  points_in_paint_scored INT64,                     -- Points from paint shots
  second_chance_points_scored INT64,                -- Points immediately after offensive rebounds
  
  -- Pace and possessions (standardized naming)
  possessions_estimate INT64,                       -- Estimated possessions used
  possessions_method STRING,                        -- Method used for possession calculation
  pace FLOAT64,                                     -- Possessions per 48 minutes
  seconds_per_possession FLOAT64,                   -- Average possession length
  offensive_rating FLOAT64,                         -- Points scored per 100 possessions
  
  -- Game context
  home_game BOOLEAN,                                -- TRUE if team was home
  win_flag BOOLEAN,                                 -- TRUE if team won
  margin_of_victory INT64,                          -- Team score - opponent score
  overtime_periods INT64,                           -- 0 for regulation, else number of OT periods
  final_score_team INT64,                           -- Team's final score
  final_score_opponent INT64,                       -- Opponent's final score
  
  -- Market context
  closing_spread FLOAT64,                           -- Team spread at close
  closing_total FLOAT64,                            -- Game O/U total
  team_implied_total FLOAT64,                       -- Team's implied point total
  opp_implied_total FLOAT64,                        -- Opponent's implied total
  
  -- Simple blowout analysis (calculated post-game)
  blowout_level INT64,                              -- 1=Close Game, 2=Solid Win, 3=Comfortable, 4=Clear Blowout, 5=Massive (26+ pts)
  blowout_description STRING,                       -- "Close Game", "Solid Win", "Comfortable Win", "Clear Blowout", "Massive Blowout"
  
  -- Data source tracking with timestamps
  shot_zone_source STRING,                          -- "bigdataball", "calculated_from_players"
  shot_zone_updated_at TIMESTAMP,                   -- When shot zone data was last updated
  team_stats_source STRING,                         -- "player_aggregation", "nbac_official_team_totals"
  team_stats_updated_at TIMESTAMP,                  -- When team totals were calculated
  pace_source STRING,                               -- "bigdataball_possessions", "standard_formula"
  pace_updated_at TIMESTAMP,                        -- When pace calculations were updated
  
  -- Processing metadata
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(), -- When record was created
  processed_at TIMESTAMP                            -- When record was last processed
)
PARTITION BY game_date
CLUSTER BY team_abbr, opponent_team_abbr, season_year
OPTIONS (
  description = "Team offensive performance data per game with detailed shot zones and efficiency metrics for opponent analysis.",
  partition_expiration_days = 1095  -- 3 years retention
);

-- ============================================================================
-- VIEWS FOR COMMON TEAM OFFENSIVE ANALYSIS
-- ============================================================================

-- View for team offensive ratings and efficiency
CREATE VIEW `nba-props-platform.nba_analytics.team_offense_efficiency` AS
SELECT 
  team_abbr,
  season_year,
  game_date,
  offensive_rating,
  off_efg_pct,
  off_tov_rate,
  off_orb_pct,
  off_ft_rate,
  pace,
  three_point_rate,
  points_scored,
  blowout_level
FROM `nba-props-platform.nba_analytics.team_offense_game_log`
WHERE team_stats_source IS NOT NULL;

-- View for shot zone analysis
CREATE VIEW `nba-props-platform.nba_analytics.team_offense_shot_zones` AS
SELECT 
  team_abbr,
  opponent_team_abbr,
  game_date,
  season_year,
  team_paint_attempts,
  team_paint_makes,
  SAFE_DIVIDE(team_paint_makes, team_paint_attempts) as paint_fg_pct,
  team_three_pt_attempts,
  team_three_pt_makes,
  SAFE_DIVIDE(team_three_pt_makes, team_three_pt_attempts) as three_pt_pct,
  team_mid_range_attempts,
  team_mid_range_makes,
  SAFE_DIVIDE(team_mid_range_makes, team_mid_range_attempts) as mid_range_pct,
  three_point_rate,
  mid_range_rate
FROM `nba-props-platform.nba_analytics.team_offense_game_log`
WHERE shot_zone_source IS NOT NULL;