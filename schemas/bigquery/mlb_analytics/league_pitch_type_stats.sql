-- ============================================================================
-- MLB Props Platform - League Pitch-Type Baselines
-- League-wide whiff / CSW / velocity / spin by pitch type
-- File: schemas/bigquery/mlb_analytics/league_pitch_type_stats.sql
-- ============================================================================
--
-- Used by `pitcher_expected_arsenal_latest` to compute per-pitcher expected
-- whiff / CSW rates ("what would this arsenal produce against league-average
-- swings?"). Delta vs actual is a stuff-deception signal.
--
-- Source: `mlb_raw.mlb_game_feed_pitches` (per-pitch, Mar 2026 onward natively;
--   2025 season data via historical backfill, Session 531).
--
-- Contract:
--   pitch_type_code, pitch_type_desc,
--   league_pitches, league_swings, league_whiffs, league_called_strikes,
--   league_whiff_rate, league_csw_rate, league_called_strike_rate,
--   league_in_zone_rate, league_avg_velocity, league_avg_spin,
--   window_start, window_end, computed_at
--
-- Sample floor: 500 pitches per pitch type (excludes ultra-rare types like
--   eephus, gyro) so ratios are stable.
--
-- Window: all available per-pitch data from 2025-04-01 forward. Mature
--   backfill produces ~550K pitches; sufficient for stable per-type baselines.
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.league_pitch_type_stats` AS

WITH pitch_type_desc AS (
  SELECT code, description FROM UNNEST([
    STRUCT('FF' AS code, 'Four-Seam Fastball' AS description),
    STRUCT('SI', 'Sinker'),
    STRUCT('FA', 'Fastball'),
    STRUCT('SL', 'Slider'),
    STRUCT('CU', 'Curveball'),
    STRUCT('CH', 'Changeup'),
    STRUCT('KC', 'Knuckle-Curve'),
    STRUCT('ST', 'Sweeper'),
    STRUCT('FC', 'Cutter'),
    STRUCT('FS', 'Splitter'),
    STRUCT('CS', 'Slow Curve'),
    STRUCT('KN', 'Knuckleball'),
    STRUCT('EP', 'Eephus'),
    STRUCT('SC', 'Screwball'),
    STRUCT('FO', 'Forkball'),
    STRUCT('SV', 'Slurve'),
    STRUCT('GY', 'Gyroball')
  ])
),

agg AS (
  SELECT
    pitch_type_code,
    COUNT(*) AS league_pitches,
    COUNTIF(is_swing) AS league_swings,
    COUNTIF(is_whiff) AS league_whiffs,
    COUNTIF(is_called_strike) AS league_called_strikes,
    COUNTIF(is_in_zone) AS league_in_zone_pitches,
    AVG(velocity) AS league_avg_velocity_raw,
    AVG(spin_rate) AS league_avg_spin_raw,
    MIN(game_date) AS window_start,
    MAX(game_date) AS window_end
  FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches`
  WHERE game_date >= DATE('2025-04-01')
    AND pitch_type_code IS NOT NULL
  GROUP BY pitch_type_code
)

SELECT
  a.pitch_type_code,
  COALESCE(d.description, a.pitch_type_code) AS pitch_type_desc,
  a.league_pitches,
  a.league_swings,
  a.league_whiffs,
  a.league_called_strikes,
  ROUND(100.0 * a.league_whiffs / NULLIF(a.league_swings, 0), 2) AS league_whiff_rate,
  ROUND(
    100.0 * (a.league_whiffs + a.league_called_strikes) / NULLIF(a.league_pitches, 0),
    2
  ) AS league_csw_rate,
  ROUND(100.0 * a.league_called_strikes / NULLIF(a.league_pitches, 0), 2) AS league_called_strike_rate,
  ROUND(100.0 * a.league_in_zone_pitches / NULLIF(a.league_pitches, 0), 2) AS league_in_zone_rate,
  ROUND(a.league_avg_velocity_raw, 2) AS league_avg_velocity,
  ROUND(a.league_avg_spin_raw, 0) AS league_avg_spin,
  a.window_start,
  a.window_end,
  CURRENT_TIMESTAMP() AS computed_at
FROM agg a
LEFT JOIN pitch_type_desc d ON a.pitch_type_code = d.code
WHERE a.league_pitches >= 500  -- sample floor for stability
ORDER BY a.league_pitches DESC;
