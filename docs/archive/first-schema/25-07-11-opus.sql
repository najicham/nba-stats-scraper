-- NBA Analytics Platform - Simplified BigQuery Schema
-- Focus: Raw scraped data storage only
-- All timestamps in UTC

-- Create dataset
CREATE SCHEMA IF NOT EXISTS `nba_raw`
OPTIONS(
  description="Raw scraped NBA data - Phase 1 Player Points Props",
  location="us-central1"
);

-- =====================================================
-- 1. GAMES TABLE - Schedule and results
-- =====================================================
CREATE OR REPLACE TABLE `nba_raw.games` (
  -- Identifiers
  game_id STRING NOT NULL,                    -- Format: "lakers_warriors_2025_01_08"
  external_game_ids JSON,                     -- {"odds_api": "abc123", "balldontlie": 456789}
  
  -- Game Details  
  game_date DATE NOT NULL,
  game_time TIMESTAMP,                        -- Tip-off time in UTC
  season STRING,                              -- "2024-25"
  game_type STRING,                           -- "regular", "playoffs", "preseason"
  
  -- Teams
  home_team STRING NOT NULL,                  -- "Lakers"
  away_team STRING NOT NULL,                  -- "Warriors"
  
  -- Status
  status STRING,                              -- "scheduled", "live", "final", "postponed"
  home_score INTEGER,                         -- NULL until game starts
  away_score INTEGER,
  
  -- Metadata
  last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  scraped_from STRING,                        -- "odds_api", "balldontlie", "espn"
  scraper_run_id STRING
)
PARTITION BY game_date
CLUSTER BY home_team, away_team, status
OPTIONS(
  description="NBA games schedule and results",
  partition_expiration_days=730  -- Keep 2 years
);

-- =====================================================
-- 2. TEAM_ROSTERS TABLE - Player to team mapping
-- =====================================================
CREATE OR REPLACE TABLE `nba_raw.team_rosters` (
  -- Core fields
  player_name_normalized STRING NOT NULL,     -- "lebron_james"
  team_name STRING NOT NULL,                  -- "Lakers"
  roster_date DATE NOT NULL,                  -- Date this roster is valid for
  
  -- Change tracking
  effective_timestamp TIMESTAMP NOT NULL,     -- UTC time this became effective
  end_timestamp TIMESTAMP,                    -- NULL if current, set when player moves
  
  -- Deduplication
  roster_hash STRING,                         -- MD5 of player+team+jersey+position
  last_confirmed_timestamp TIMESTAMP,         -- Last scrape that confirmed this
  
  -- Optional details
  jersey_number STRING,
  position STRING,
  status STRING,                              -- "active", "inactive", "g-league"
  
  -- Metadata
  scraped_from STRING,                        -- "espn", "nba_com"
  scraper_run_id STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY roster_date
CLUSTER BY player_name_normalized, team_name
OPTIONS(
  description="Player-team relationships - handles trades mid-day",
  partition_expiration_days=365
);

-- =====================================================
-- 3. PLAYER_PROPS TABLE - Prop bet lines with movement
-- =====================================================
CREATE OR REPLACE TABLE `nba_raw.player_props` (
  -- Identifiers  
  prop_line_id STRING NOT NULL,               -- Auto-generated unique ID
  game_id STRING NOT NULL,                    -- Links to games table
  player_name_normalized STRING NOT NULL,     -- "lebron_james"
  
  -- Prop details
  prop_type STRING NOT NULL,                  -- "points" (future: "rebounds", "assists")
  prop_line FLOAT64 NOT NULL,                 -- 25.5
  
  -- Odds (American format)
  over_american INTEGER,                      -- -110
  under_american INTEGER,                     -- -110
  
  -- Bookmaker
  bookmaker_key STRING NOT NULL,              -- "draftkings"
  bookmaker_title STRING,                     -- "DraftKings"
  
  -- Line movement tracking
  line_timestamp TIMESTAMP NOT NULL,          -- UTC when this line was observed
  previous_line FLOAT64,                      -- NULL if first observation
  line_change FLOAT64,                        -- prop_line - previous_line
  
  -- Status flags
  is_current BOOLEAN DEFAULT TRUE,            -- FALSE when newer line exists
  is_closing_line BOOLEAN DEFAULT FALSE,      -- TRUE for final pre-game line
  
  -- Metadata
  scraper_run_id STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(line_timestamp)
CLUSTER BY game_id, player_name_normalized, bookmaker_key
OPTIONS(
  description="Prop lines with full movement history",
  partition_expiration_days=365
);

-- =====================================================
-- 4. PLAYER_PROP_RESULTS TABLE - Graded props
-- =====================================================
CREATE OR REPLACE TABLE `nba_raw.player_prop_results` (
  -- Identifiers
  prop_result_id STRING NOT NULL,             -- Auto-generated unique ID
  game_id STRING NOT NULL,
  player_name_normalized STRING NOT NULL,
  
  -- Prop snapshot
  prop_type STRING NOT NULL,                  -- "points"
  closing_line FLOAT64 NOT NULL,              -- 25.5
  
  -- Best available closing odds
  best_over_american INTEGER,                 -- -105 (best across all books)
  best_under_american INTEGER,                -- -115
  best_over_bookmaker STRING,                 -- Which book had best over
  best_under_bookmaker STRING,                -- Which book had best under
  
  -- Result
  actual_result FLOAT64,                      -- 28 points scored
  over_hit BOOLEAN,                           -- TRUE (28 > 25.5)
  under_hit BOOLEAN,                          -- FALSE
  push BOOLEAN,                               -- TRUE if exactly on line
  
  -- Context
  game_date DATE,
  player_team STRING,                         -- From roster lookup
  opponent_team STRING,
  home_away STRING,                           -- "home" or "away"
  
  -- Metadata
  graded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  actual_result_source STRING,                -- "balldontlie_boxscore"
  scraper_run_id STRING
)
PARTITION BY game_date
CLUSTER BY player_name_normalized, prop_type
OPTIONS(
  description="Historical graded props for analysis",
  partition_expiration_days=1095  -- Keep 3 years
);

-- =====================================================
-- 5. PLAYER_INJURIES TABLE - Daily injury status
-- =====================================================
CREATE OR REPLACE TABLE `nba_raw.player_injuries` (
  -- Core fields (one row per player per day)
  player_name_normalized STRING NOT NULL,
  injury_date DATE NOT NULL,
  
  -- Status
  injury_status STRING NOT NULL,              -- "out", "questionable", "probable", "available"
  injury_description STRING,                  -- "knee soreness", "rest"
  
  -- Intraday updates
  status_timestamp TIMESTAMP NOT NULL,        -- UTC when this status was scraped
  previous_status STRING,                     -- If status changed during day
  is_current_status BOOLEAN DEFAULT TRUE,     -- FALSE if superseded by later update
  
  -- Optional
  expected_return STRING,                     -- "2-3 weeks", "day-to-day"
  game_id STRING,                             -- If injury report is game-specific
  
  -- Metadata
  scraped_from STRING,                        -- "nba_injury_report"
  scraper_run_id STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY injury_date
CLUSTER BY player_name_normalized, injury_status
OPTIONS(
  description="Daily injury status - one row per player per day minimum",
  partition_expiration_days=365
);

-- =====================================================
-- 6. PLAYER_BOXSCORES TABLE - Game performance stats
-- =====================================================
CREATE OR REPLACE TABLE `nba_raw.player_boxscores` (
  -- Identifiers
  boxscore_id STRING NOT NULL,                -- Auto-generated unique ID
  game_id STRING NOT NULL,
  player_name_normalized STRING NOT NULL,
  
  -- Game context
  game_date DATE NOT NULL,
  team STRING NOT NULL,
  opponent STRING NOT NULL,
  home_away STRING,
  
  -- Core stats (nullable for DNP/missing data)
  minutes_played STRING,                      -- "36:24" or NULL if DNP
  points INTEGER,
  rebounds INTEGER,
  assists INTEGER,
  
  -- Shooting (all nullable)
  field_goals_made INTEGER,
  field_goals_attempted INTEGER,
  three_pointers_made INTEGER,
  three_pointers_attempted INTEGER,
  free_throws_made INTEGER,
  free_throws_attempted INTEGER,
  
  -- Other stats (all nullable)
  steals INTEGER,
  blocks INTEGER,
  turnovers INTEGER,
  personal_fouls INTEGER,
  plus_minus INTEGER,
  
  -- Status
  dnp_reason STRING,                          -- "coach's decision", "injury", NULL if played
  
  -- Game result
  team_score INTEGER,
  opponent_score INTEGER,
  
  -- Metadata
  scraped_from STRING,                        -- "balldontlie", "espn"
  scraper_run_id STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_name_normalized, team
OPTIONS(
  description="Player game performance - handles DNP and missing stats",
  partition_expiration_days=1095  -- Keep 3 years
);

-- =====================================================
-- NOTES ON IMPLEMENTATION
-- =====================================================

-- 1. Player Name Normalization Function (Python):
-- def normalize_player_name(name):
--     # Remove Jr., Sr., III, etc.
--     name = re.sub(r'\s+(Jr\.?|Sr\.?|III|II|IV)$', '', name, flags=re.I)
--     # Lowercase and underscore
--     return name.lower().strip().replace(' ', '_')

-- 2. Game ID Generation:
-- f"{home_team.lower()}_{away_team.lower()}_{game_date.strftime('%Y_%m_%d')}"
-- For rescheduled games, could append "_v2" if collision detected

-- 3. Missing Data Handling:
-- - No props available: Normal, just no rows in player_props
-- - No injury status: Assume healthy (no row = healthy)
-- - DNP in boxscore: Set stats to NULL, populate dnp_reason

-- 4. UTC Conversion:
-- All timestamps stored as UTC
-- Convert LA time to UTC: datetime.now(tz=LA_TZ).astimezone(pytz.UTC)

-- 5. Roster Change Detection:
-- Only insert new roster row if roster_hash changes
-- Update last_confirmed_timestamp if data unchanged
