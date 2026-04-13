-- ============================================================================
-- MLB Props Platform - Pitcher Pitch Arsenal Analytics View
-- Per-pitcher, per-pitch-type rolling stats derived from Statcast daily data
-- File: schemas/bigquery/mlb_analytics/pitcher_pitch_arsenal_tables.sql
-- ============================================================================
--
-- SOURCE: mlb_raw.statcast_pitcher_daily (populated by mlb_statcast_daily scraper)
--
-- DATA MODEL:
--   statcast_pitcher_daily has one row per (pitcher_lookup, game_date)
--   with pitch_types as a JSON string: {"FF": 42, "SL": 28, "CH": 18}
--   and overall whiff_rate and avg_velocity per start.
--
-- OUTPUT: One row per (pitcher_lookup, pitch_type_code) —
--   aggregated over that pitcher's last 5 starts.
--
-- Pitch type codes (common):
--   FF = Four-Seam Fastball   SI = Sinker            SL = Slider
--   CU = Curveball            CH = Changeup           KC = Knuckle-Curve
--   ST = Sweeper              FC = Cutter             FS = Splitter
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.pitcher_pitch_arsenal_latest` AS

WITH

-- Human-readable names for common pitch type codes
pitch_type_desc AS (
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

-- Rank each pitcher's starts, most recent first
ranked_starts AS (
  SELECT
    player_lookup,
    game_date,
    total_pitches,
    whiff_rate,
    avg_velocity,
    pitch_types,
    ROW_NUMBER() OVER (
      PARTITION BY player_lookup
      ORDER BY game_date DESC
    ) AS start_rank
  FROM `nba-props-platform.mlb_raw.statcast_pitcher_daily`
  WHERE game_date >= DATE('2025-04-01')
    AND pitch_types IS NOT NULL
    AND pitch_types NOT IN ('{}', 'null', '')
    AND total_pitches > 0
),

-- Keep only last 5 starts per pitcher
last5_starts AS (
  SELECT *
  FROM ranked_starts
  WHERE start_rank <= 5
),

-- Expand pitch_types JSON to per-(pitcher, start, pitch_type) rows.
-- BigQuery JSON_EXTRACT_SCALAR requires a literal path, so we use
-- REGEXP_EXTRACT which accepts dynamic patterns.
pitch_type_rows AS (
  SELECT
    s.player_lookup,
    s.game_date,
    s.total_pitches  AS start_total_pitches,
    s.whiff_rate     AS start_whiff_rate,
    s.avg_velocity   AS start_avg_velocity,
    c.code           AS pitch_type_code,
    CAST(
      REGEXP_EXTRACT(
        s.pitch_types,
        CONCAT(r'"', c.code, r'":\s*(\d+)')
      ) AS INT64
    )                AS pitch_count
  FROM last5_starts s
  CROSS JOIN (
    SELECT code FROM UNNEST([
      'FF','FA','SI','SL','CU','CH','KC','ST','FC','FS','CS','KN','EP','SC','FO','SV','GY'
    ]) AS code
  ) c
  -- Only keep rows where this pitch type appears in the JSON
  WHERE REGEXP_CONTAINS(s.pitch_types, CONCAT(r'"', c.code, r'"'))
),

-- Aggregate per (pitcher, pitch_type) across last 5 starts
arsenal_rollup AS (
  SELECT
    player_lookup,
    pitch_type_code,
    MAX(game_date)                                               AS last_seen_date,
    SUM(pitch_count)                                             AS total_pitch_count,
    SUM(start_total_pitches)                                     AS total_pitches_across_starts,
    ROUND(
      SUM(start_avg_velocity * start_total_pitches)
      / NULLIF(SUM(start_total_pitches), 0),
      1
    )                                                            AS avg_velocity,
    ROUND(
      SUM(start_whiff_rate * start_total_pitches)
      / NULLIF(SUM(start_total_pitches), 0),
      1
    )                                                            AS avg_whiff_rate,
    COUNT(DISTINCT game_date)                                    AS starts_sampled
  FROM pitch_type_rows
  WHERE pitch_count > 0
  GROUP BY player_lookup, pitch_type_code
)

SELECT
  a.player_lookup,
  a.pitch_type_code,
  COALESCE(d.description, a.pitch_type_code) AS pitch_type_desc,
  a.last_seen_date,
  a.total_pitch_count,
  ROUND(
    a.total_pitch_count * 100.0
    / NULLIF(a.total_pitches_across_starts, 0),
    1
  )                                           AS usage_pct,
  a.avg_whiff_rate                            AS whiff_rate,
  a.avg_velocity,
  a.starts_sampled,
  CURRENT_TIMESTAMP()                         AS computed_at
FROM arsenal_rollup a
LEFT JOIN pitch_type_desc d ON a.pitch_type_code = d.code
WHERE a.total_pitch_count * 100.0
      / NULLIF(a.total_pitches_across_starts, 0) >= 5.0
ORDER BY a.player_lookup, usage_pct DESC;
