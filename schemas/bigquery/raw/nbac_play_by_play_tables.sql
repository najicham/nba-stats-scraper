-- File: schemas/bigquery/nbac_play_by_play_tables.sql
-- Description: BigQuery table schemas for NBA.com play-by-play data
-- NBA.com Play By Play Tables
-- Official NBA play-by-play events for advanced analytics and BigDataBall validation

CREATE TABLE IF NOT EXISTS `nba_raw.nbac_play_by_play` (
  -- Core Game Identifiers
  game_id              STRING NOT NULL,    -- Format: "20211019_BKN_MIL" (consistent with other processors)
  nba_game_id          STRING NOT NULL,    -- NBA.com game ID: "0022100001"
  game_date            DATE NOT NULL,      -- Game date
  season_year          INT64 NOT NULL,     -- Starting year (2021 for 2021-22 season)
  
  -- Team identifiers (may be NULL if cannot determine from play-by-play data)
  home_team_abbr       STRING,             -- Three-letter code (requires schedule cross-reference)
  away_team_abbr       STRING,             -- Three-letter code (requires schedule cross-reference)
  
  -- Event Identifiers
  event_id             STRING NOT NULL,    -- NBA.com action number as string
  event_sequence       INT64 NOT NULL,     -- Sequential order within game (actionNumber)
  period               INT64 NOT NULL,     -- Quarter/period number (1-4 regular, 5+ overtime)
  
  -- Game Clock
  game_clock           STRING,             -- Time remaining "11:47" (parsed from PT11M46.00S)
  game_clock_seconds   INT64,              -- Converted to seconds for analysis
  time_elapsed_seconds INT64,              -- Total seconds elapsed in game
  
  -- Event Details
  event_type           STRING,             -- "jumpball", "foul", "fieldgoal", etc. (actionType)
  event_action_type    STRING,             -- "personal", "made", "recovered", etc. (subType)
  event_description    STRING,             -- Full text description
  score_home           INT64,              -- Home team score after event
  score_away           INT64,              -- Away team score after event
  
  -- Primary Player (always from personId when available)
  player_1_id          INT64,              -- Primary player NBA ID
  player_1_lookup      STRING,             -- Normalized: "lebronjames"
  player_1_team_abbr   STRING,             -- Player's team (from teamTricode)
  
  -- Secondary Player (assists, blocks, fouls drawn, jump ball participants)
  player_2_id          INT64,              -- Secondary player NBA ID  
  player_2_lookup      STRING,             -- Normalized for cross-table joins
  player_2_team_abbr   STRING,             -- Team context (NULL if unknown)
  
  -- Tertiary Player (rare - technical fouls, ejections, 3-person jump balls)
  player_3_id          INT64,              -- Tertiary player NBA ID
  player_3_lookup      STRING,             -- Normalized for cross-table joins  
  player_3_team_abbr   STRING,             -- Team context (NULL if unknown)
  
  -- Shot Details (when applicable - only for field goals and free throws)
  shot_made            BOOLEAN,            -- TRUE if shot made, NULL if not a shot
  shot_type            STRING,             -- "2PT", "3PT", "FT", NULL if not a shot
  shot_x               FLOAT64,            -- Raw court X coordinate (may be NULL)
  shot_y               FLOAT64,            -- Raw court Y coordinate (may be NULL)
  shot_distance        FLOAT64,            -- Calculated distance in feet (0.0 if no coordinates)
  
  -- Video/Links (if available in source data)
  video_available      BOOLEAN DEFAULT FALSE, -- Has video replay
  video_url            STRING,             -- Link to video clip
  
  -- Processing Metadata (consistent with other processors)
  source_file_path     STRING NOT NULL,    -- GCS path
  processed_at         TIMESTAMP NOT NULL  -- Processing timestamp
)
PARTITION BY game_date
CLUSTER BY game_id, period, event_type
OPTIONS (
  description = "NBA.com play-by-play events - official source for detailed game analysis and BigDataBall validation",
  require_partition_filter = true
);

-- View for active game events (excluding period start/end administrative events)
CREATE OR REPLACE VIEW `nba_raw.nbac_play_by_play_active_events` AS
SELECT *
FROM `nba_raw.nbac_play_by_play`
WHERE event_type NOT IN ('period', 'timeout', 'substitution')
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- View for shot events only (field goals and free throws)
CREATE OR REPLACE VIEW `nba_raw.nbac_play_by_play_shots` AS  
SELECT 
  game_id,
  game_date,
  event_sequence,
  period,
  game_clock,
  player_1_lookup,
  player_1_team_abbr,
  shot_made,
  shot_type,
  shot_x,
  shot_y,
  shot_distance,
  event_description
FROM `nba_raw.nbac_play_by_play`
WHERE shot_made IS NOT NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);

-- View for recent games (last 30 days)
CREATE OR REPLACE VIEW `nba_raw.nbac_play_by_play_recent` AS
SELECT *
FROM `nba_raw.nbac_play_by_play`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY);