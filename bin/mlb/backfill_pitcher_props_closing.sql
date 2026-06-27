-- A5 backfill: replay materializer logic over the full oddsa_pitcher_props history.
-- Created: 2026-05-13 (Session 3 of MLB roadmap).
--
-- Differences from the daily materializer:
--   - Wider lookback (720 min vs 180 min) — captures morning snapshots as
--     "closing" rows. Per design Open Question #2, we keep these with
--     is_synthetic=TRUE so the post-A5 high-quality rows are distinguishable.
--   - Single SQL run over the full date range (2026-03-01 → yesterday).
--
-- Idempotent: DELETE any rows in the date range first, then INSERT. Safe to re-run.
--
-- To execute:
--   bq query --use_legacy_sql=false --project_id=nba-props-platform < bin/mlb/backfill_pitcher_props_closing.sql

DECLARE start_date DATE DEFAULT DATE '2026-03-01';
DECLARE end_date   DATE DEFAULT DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);

-- Drop any prior backfill rows in the range
DELETE FROM `nba-props-platform.mlb_raw.pitcher_props_closing`
WHERE game_date BETWEEN start_date AND end_date;

-- Insert one row per (player_lookup, bookmaker) per game_date
INSERT INTO `nba-props-platform.mlb_raw.pitcher_props_closing` (
  game_date, game_pk, game_start_time, event_id,
  player_lookup, player_name, team_abbr, home_team_abbr, away_team_abbr,
  bookmaker, market_key, closing_line,
  closing_over_price, closing_under_price,
  closing_over_implied, closing_under_implied,
  closing_snapshot_time, minutes_before_first_pitch, is_synthetic,
  source_snapshot_path, materialized_at
)
WITH oddsa AS (
  SELECT
    opp.game_date,
    opp.event_id,
    opp.player_name,
    opp.player_lookup,
    opp.team_abbr,
    opp.home_team_abbr,
    opp.away_team_abbr,
    opp.bookmaker,
    opp.market_key,
    opp.point AS closing_line,
    opp.over_price AS closing_over_price,
    opp.under_price AS closing_under_price,
    opp.over_implied_prob AS closing_over_implied,
    opp.under_implied_prob AS closing_under_implied,
    opp.snapshot_time AS closing_snapshot_time,
    opp.game_start_time,
    opp.source_file_path AS source_snapshot_path,
    TIMESTAMP_DIFF(opp.game_start_time, opp.snapshot_time, MINUTE)
      AS minutes_before_first_pitch,
    ROW_NUMBER() OVER (
      PARTITION BY opp.game_date, opp.player_lookup, opp.bookmaker
      ORDER BY opp.snapshot_time DESC
    ) AS rn
  FROM `nba-props-platform.mlb_raw.oddsa_pitcher_props` opp
  WHERE opp.game_date BETWEEN start_date AND end_date
    AND opp.market_key = 'pitcher_strikeouts'
    AND opp.point IS NOT NULL
    AND opp.snapshot_time IS NOT NULL
    AND opp.game_start_time IS NOT NULL
    AND opp.snapshot_time <= opp.game_start_time
    AND TIMESTAMP_DIFF(opp.game_start_time, opp.snapshot_time, MINUTE) <= 720
),
schedule AS (
  SELECT game_date, game_pk, home_team_abbr, away_team_abbr
  FROM `nba-props-platform.mlb_raw.mlb_schedule`
  WHERE game_date BETWEEN start_date AND end_date
)
SELECT
  o.game_date,
  s.game_pk,
  o.game_start_time,
  o.event_id,
  o.player_lookup,
  o.player_name,
  o.team_abbr,
  o.home_team_abbr,
  o.away_team_abbr,
  o.bookmaker,
  o.market_key,
  o.closing_line,
  o.closing_over_price,
  o.closing_under_price,
  o.closing_over_implied,
  o.closing_under_implied,
  o.closing_snapshot_time,
  o.minutes_before_first_pitch,
  o.minutes_before_first_pitch > 30 AS is_synthetic,
  o.source_snapshot_path,
  CURRENT_TIMESTAMP() AS materialized_at
FROM oddsa o
LEFT JOIN schedule s
  ON s.game_date = o.game_date
 AND s.home_team_abbr = o.home_team_abbr
 AND s.away_team_abbr = o.away_team_abbr
WHERE o.rn = 1;
