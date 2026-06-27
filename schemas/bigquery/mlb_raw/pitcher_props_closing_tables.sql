-- MLB Pitcher Props Closing Lines
-- Created: 2026-05-13 (Session 3 of MLB roadmap, A5 build)
--
-- One row per (game_pk, player_lookup, bookmaker) representing the closing line
-- captured before first pitch. Materialized daily by mlb-pitcher-props-closing-materialize
-- from the time-series snapshots in mlb_raw.oddsa_pitcher_props.
--
-- Goal: enable CLV (closing line value) computation in mlb_predictions.prediction_accuracy.

CREATE TABLE IF NOT EXISTS `nba-props-platform.mlb_raw.pitcher_props_closing` (
  game_date                  DATE      NOT NULL,
  game_pk                    INT64,                       -- nullable: joined from mlb_raw.mlb_schedule; not all events match
  game_start_time            TIMESTAMP NOT NULL,
  event_id                   STRING    NOT NULL,
  player_lookup              STRING    NOT NULL,
  player_name                STRING    NOT NULL,
  team_abbr                  STRING,
  home_team_abbr             STRING,
  away_team_abbr             STRING,
  bookmaker                  STRING    NOT NULL,
  market_key                 STRING    NOT NULL,          -- 'pitcher_strikeouts'
  closing_line               FLOAT64   NOT NULL,
  closing_over_price         INT64,
  closing_under_price        INT64,
  closing_over_implied       FLOAT64,
  closing_under_implied      FLOAT64,
  closing_snapshot_time      TIMESTAMP NOT NULL,
  minutes_before_first_pitch INT64     NOT NULL,          -- <= 30 → truly closing; > 30 → synthetic
  is_synthetic               BOOLEAN   NOT NULL,
  source_snapshot_path       STRING,                      -- mlb_raw.oddsa_pitcher_props.source_file_path forensic trail
  materialized_at            TIMESTAMP NOT NULL          -- default applied at insert by materializer
)
PARTITION BY game_date
CLUSTER BY player_lookup, bookmaker;
