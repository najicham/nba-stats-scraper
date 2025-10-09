-- ============================================================================
-- NBA Props Platform - Player Game Summary Analytics Table
-- Pure performance results with shot zone tracking - no context duplication
-- Updated: Added universal_player_id for stable player identification
-- ============================================================================

CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_analytics.player_game_summary` (
  -- Core identifiers (8 fields - UPDATED: added universal_player_id)
  player_lookup STRING NOT NULL,                    -- Normalized player identifier
  universal_player_id STRING,                       -- Universal player ID from registry (e.g., lebronjames_001)
  player_full_name STRING,                          -- Display name for reports
  game_id STRING NOT NULL,                          -- Unique game identifier
  game_date DATE NOT NULL,                          -- Game date for partitioning
  team_abbr STRING NOT NULL,                        -- Player's team abbreviation
  opponent_team_abbr STRING NOT NULL,               -- Opposing team abbreviation
  season_year INT64 NOT NULL,                       -- Season year (2024 for 2023-24 season)
  
  -- Basic performance stats (16 fields)
  points INT64,                                     -- Total points scored
  minutes_played INT64,                             -- Minutes played
  assists INT64,                                    -- Total assists
  offensive_rebounds INT64,                         -- Offensive rebounds
  defensive_rebounds INT64,                         -- Defensive rebounds
  steals INT64,                                     -- Total steals
  blocks INT64,                                     -- Total blocks
  turnovers INT64,                                  -- Total turnovers
  fg_attempts INT64,                                -- Total field goal attempts
  fg_makes INT64,                                   -- Total field goal makes
  three_pt_attempts INT64,                          -- Three-point attempts
  three_pt_makes INT64,                             -- Three-point makes
  ft_attempts INT64,                                -- Free throw attempts
  ft_makes INT64,                                   -- Free throw makes
  plus_minus INT64,                                 -- Plus/minus while on court
  personal_fouls INT64,                             -- Personal fouls committed
  
  -- Shot zone performance (8 fields)
  paint_attempts INT64,                             -- Field goal attempts in paint (≤8 feet)
  paint_makes INT64,                                -- Field goal makes in paint
  mid_range_attempts INT64,                         -- Mid-range attempts (9+ feet, 2PT)
  mid_range_makes INT64,                            -- Mid-range makes
  paint_blocks INT64,                               -- Blocks on paint shots
  mid_range_blocks INT64,                           -- Blocks on mid-range shots
  three_pt_blocks INT64,                            -- Blocks on three-point shots
  and1_count INT64,                                 -- Made FG + shooting foul drawn
  
  -- Shot creation analysis (2 fields)
  assisted_fg_makes INT64,                          -- Made FGs that were assisted
  unassisted_fg_makes INT64,                        -- Made FGs unassisted (shot creation)
  
  -- Advanced efficiency (5 fields)
  usage_rate NUMERIC(5,2),                          -- Percentage of team plays used
  ts_pct NUMERIC(5,3),                              -- True Shooting percentage
  efg_pct NUMERIC(5,3),                             -- Effective Field Goal percentage
  starter_flag BOOLEAN NOT NULL,                    -- Whether player started
  win_flag BOOLEAN NOT NULL,                        -- Whether player's team won
  
  -- Prop betting results (7 fields)
  points_line NUMERIC(4,1),                         -- Betting line for points prop
  over_under_result STRING,                         -- 'OVER', 'UNDER', or NULL
  margin NUMERIC(6,2),                              -- Actual points minus line
  opening_line NUMERIC(4,1),                        -- Opening betting line
  line_movement NUMERIC(4,1),                       -- Line movement from open to close
  points_line_source STRING,                        -- Source of closing line
  opening_line_source STRING,                       -- Source of opening line
  
  -- Player availability (2 fields)
  is_active BOOLEAN NOT NULL,                       -- Whether player played
  player_status STRING,                             -- 'active', 'injured', 'rest', 'dnp_coaches_decision', 'suspended', 'personal'
  
  -- Data quality (3 fields)
  data_quality_tier STRING,                        -- 'high', 'medium', 'low' 
  primary_source_used STRING,                       -- Data source used
  processed_with_issues BOOLEAN,                    -- Quality issues flag
  
  -- Processing metadata (2 fields)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY universal_player_id, player_lookup, team_abbr, game_date
OPTIONS(
  description="Pure player performance results with shot zone tracking - no context duplication. Updated with universal_player_id for stable player identification across seasons and teams."
);

-- ============================================================================
-- Migration Note: Adding universal_player_id to existing table
-- ============================================================================
-- If table already exists, add the column:
-- ALTER TABLE `nba-props-platform.nba_analytics.player_game_summary`
-- ADD COLUMN IF NOT EXISTS universal_player_id STRING;

-- Optional: Backfill existing records (run after adding column)
-- UPDATE `nba-props-platform.nba_analytics.player_game_summary` pgs
-- SET universal_player_id = (
--   SELECT DISTINCT universal_player_id
--   FROM `nba-props-platform.nba_reference.nba_players_registry` r
--   WHERE r.player_lookup = pgs.player_lookup
--     AND r.season = CONCAT(CAST(pgs.season_year AS STRING), '-', 
--                           LPAD(CAST(pgs.season_year + 1 - 2000 AS STRING), 2, '0'))
--   LIMIT 1
-- )
-- WHERE universal_player_id IS NULL;