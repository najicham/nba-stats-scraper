-- MLB Odds API Tables
-- Created: 2026-01-06
--
-- Tables for storing MLB betting odds from The Odds API.
-- Used for pitcher strikeout prediction model.

-- ============================================================================
-- ODDS API EVENTS
-- Maps game dates to Odds API event IDs
-- ============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.oddsa_events` (
  -- Identifiers
  event_id STRING NOT NULL,
  game_date DATE NOT NULL,

  -- Game Info
  commence_time TIMESTAMP,
  home_team STRING,
  away_team STRING,
  home_team_abbr STRING,
  away_team_abbr STRING,

  -- Metadata
  sport_key STRING DEFAULT 'baseball_mlb',
  snapshot_time TIMESTAMP NOT NULL,
  source_file_path STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr;


-- ============================================================================
-- ODDS API GAME LINES
-- Moneyline, spread (run line), and totals
-- ============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.oddsa_game_lines` (
  -- Identifiers
  game_id STRING,
  game_date DATE NOT NULL,
  event_id STRING NOT NULL,

  -- Teams
  home_team STRING,
  away_team STRING,
  home_team_abbr STRING NOT NULL,
  away_team_abbr STRING NOT NULL,

  -- Moneyline (h2h)
  home_ml INT64,                      -- e.g., -150
  away_ml INT64,                      -- e.g., +130
  home_ml_implied FLOAT64,            -- Implied win probability
  away_ml_implied FLOAT64,

  -- Spread (Run Line)
  home_spread FLOAT64,                -- e.g., -1.5
  home_spread_price INT64,            -- e.g., +140
  away_spread FLOAT64,                -- e.g., +1.5
  away_spread_price INT64,            -- e.g., -160

  -- Totals (Over/Under)
  total_runs FLOAT64,                 -- e.g., 8.5
  over_price INT64,                   -- e.g., -110
  under_price INT64,                  -- e.g., -110

  -- Metadata
  bookmaker STRING NOT NULL,
  last_update TIMESTAMP,
  snapshot_time TIMESTAMP NOT NULL,
  source_file_path STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY home_team_abbr, away_team_abbr, bookmaker;


-- ============================================================================
-- ODDS API PITCHER PROPS
-- Pitcher strikeouts and other props
-- PRIMARY TARGET: pitcher_strikeouts
-- ============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.oddsa_pitcher_props` (
  -- Identifiers
  game_id STRING,
  game_date DATE NOT NULL,
  event_id STRING NOT NULL,

  -- Pitcher
  player_name STRING NOT NULL,
  player_lookup STRING NOT NULL,      -- Normalized for joins (lowercase, no spaces)
  team_abbr STRING,

  -- Game Context
  home_team_abbr STRING,
  away_team_abbr STRING,

  -- Market
  market_key STRING NOT NULL,         -- pitcher_strikeouts, pitcher_outs, etc.
  bookmaker STRING NOT NULL,

  -- Line Details
  point FLOAT64,                      -- O/U line (e.g., 6.5)
  over_price INT64,                   -- American odds (e.g., -115)
  under_price INT64,                  -- American odds (e.g., -105)
  over_implied_prob FLOAT64,          -- Calculated probability
  under_implied_prob FLOAT64,

  -- Metadata
  last_update TIMESTAMP,
  snapshot_time TIMESTAMP NOT NULL,
  source_file_path STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, market_key, bookmaker;


-- ============================================================================
-- ODDS API BATTER PROPS
-- Batter strikeouts and other props
-- CRITICAL for bottom-up K prediction model
-- ============================================================================
CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.oddsa_batter_props` (
  -- Identifiers
  game_id STRING,
  game_date DATE NOT NULL,
  event_id STRING NOT NULL,

  -- Batter
  player_name STRING NOT NULL,
  player_lookup STRING NOT NULL,      -- Normalized for joins
  team_abbr STRING,

  -- Game Context
  home_team_abbr STRING,
  away_team_abbr STRING,
  opposing_team_abbr STRING,          -- Team the batter faces

  -- Market
  market_key STRING NOT NULL,         -- batter_strikeouts, batter_hits, etc.
  bookmaker STRING NOT NULL,

  -- Line Details
  point FLOAT64,                      -- O/U line (e.g., 0.5, 1.5)
  over_price INT64,
  under_price INT64,
  over_implied_prob FLOAT64,
  under_implied_prob FLOAT64,

  -- Derived (for model)
  expected_ks FLOAT64,                -- Expected K's based on line and implied prob

  -- Metadata
  last_update TIMESTAMP,
  snapshot_time TIMESTAMP NOT NULL,
  source_file_path STRING,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, market_key, bookmaker;


-- ============================================================================
-- VIEWS
-- ============================================================================

-- Active pitcher strikeout lines (latest snapshot per game)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.oddsa_pitcher_k_lines` AS
SELECT
  pp.*
FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props` pp
INNER JOIN (
  SELECT
    event_id,
    player_lookup,
    market_key,
    bookmaker,
    MAX(snapshot_time) as latest_snapshot
  FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props`
  WHERE market_key = 'pitcher_strikeouts'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY event_id, player_lookup, market_key, bookmaker
) latest ON pp.event_id = latest.event_id
  AND pp.player_lookup = latest.player_lookup
  AND pp.market_key = latest.market_key
  AND pp.bookmaker = latest.bookmaker
  AND pp.snapshot_time = latest.latest_snapshot
WHERE pp.market_key = 'pitcher_strikeouts';


-- Active batter strikeout lines (latest snapshot per game)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.oddsa_batter_k_lines` AS
SELECT
  bp.*
FROM `nba-props-platform.mlb_raw.oddsa_batter_props` bp
INNER JOIN (
  SELECT
    event_id,
    player_lookup,
    market_key,
    bookmaker,
    MAX(snapshot_time) as latest_snapshot
  FROM `nba-props-platform.mlb_raw.oddsa_batter_props`
  WHERE market_key = 'batter_strikeouts'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY event_id, player_lookup, market_key, bookmaker
) latest ON bp.event_id = latest.event_id
  AND bp.player_lookup = latest.player_lookup
  AND bp.market_key = latest.market_key
  AND bp.bookmaker = latest.bookmaker
  AND bp.snapshot_time = latest.latest_snapshot
WHERE bp.market_key = 'batter_strikeouts';


-- Lineup expected K's (sum of batter K lines per game)
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.oddsa_lineup_expected_ks` AS
SELECT
  game_date,
  event_id,
  home_team_abbr,
  away_team_abbr,
  team_abbr,
  bookmaker,
  COUNT(DISTINCT player_lookup) as batters_with_lines,
  SUM(point) as total_k_line_sum,
  SUM(expected_ks) as total_expected_ks,
  MAX(snapshot_time) as latest_snapshot
FROM `nba-props-platform.mlb_raw.oddsa_batter_k_lines`
GROUP BY game_date, event_id, home_team_abbr, away_team_abbr, team_abbr, bookmaker;


-- Today's games with odds
CREATE OR REPLACE VIEW `nba-props-platform.mlb_raw.oddsa_games_today` AS
SELECT
  e.event_id,
  e.game_date,
  e.commence_time,
  e.home_team,
  e.away_team,
  e.home_team_abbr,
  e.away_team_abbr,
  gl.total_runs,
  gl.home_ml,
  gl.away_ml,
  gl.home_spread
FROM `nba-props-platform.mlb_raw.oddsa_events` e
LEFT JOIN (
  SELECT
    event_id,
    total_runs,
    home_ml,
    away_ml,
    home_spread,
    ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY snapshot_time DESC) as rn
  FROM `nba-props-platform.mlb_raw.oddsa_game_lines`
  WHERE bookmaker = 'draftkings'
) gl ON e.event_id = gl.event_id AND gl.rn = 1
WHERE e.game_date = CURRENT_DATE('America/New_York');
