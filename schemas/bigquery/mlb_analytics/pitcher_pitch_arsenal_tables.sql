-- ============================================================================
-- MLB Props Platform - Pitcher Pitch Arsenal Analytics View
-- Per-pitcher, per-pitch-type rolling stats from per-pitch game feed data
-- File: schemas/bigquery/mlb_analytics/pitcher_pitch_arsenal_tables.sql
-- ============================================================================
--
-- SOURCES (preferred → fallback):
--   1. mlb_raw.mlb_game_feed_pitches — per-pitch detail with true per-type
--      velocity and whiff rate. Populated daily (3 AM ET, Mar-Oct).
--   2. mlb_raw.statcast_pitcher_daily — per-pitcher aggregates with pitch_types
--      JSON (usage counts only). Used when per-pitch data is missing.
--
-- OUTPUT: One row per (pitcher_lookup, pitch_type_code), aggregated over that
--   pitcher's last 5 starts, filtered to pitch types ≥ 5% of arsenal.
--
-- Columns (stable contract used by mlb_pitcher_exporter.py):
--   player_lookup, pitch_type_code, pitch_type_desc, last_seen_date,
--   total_pitch_count, usage_pct, whiff_rate, avg_velocity, starts_sampled,
--   computed_at
--
-- Historical note: when Session 530 shipped, per-pitch data started Apr 2026.
--   For historical starts with no per-pitch data, the row falls back to
--   pitcher-level whiff/velocity from statcast_pitcher_daily.
--
-- Pitch type codes (common):
--   FF = Four-Seam Fastball   SI = Sinker            SL = Slider
--   CU = Curveball            CH = Changeup           KC = Knuckle-Curve
--   ST = Sweeper              FC = Cutter             FS = Splitter
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.pitcher_pitch_arsenal_latest` AS

WITH

-- Pitch type descriptions (used as fallback if feed data is missing)
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

-- =============================================================================
-- PATH 1: per-pitch source (preferred — true per-type velocity + whiff)
-- =============================================================================

-- Rank each pitcher's distinct starts (by game_date) in the per-pitch table
feed_starts_ranked AS (
  SELECT
    pitcher_lookup,
    game_date,
    ROW_NUMBER() OVER (
      PARTITION BY pitcher_lookup
      ORDER BY game_date DESC
    ) AS start_rank
  FROM (
    SELECT DISTINCT pitcher_lookup, game_date
    FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches`
    WHERE game_date >= DATE('2025-04-01')
  )
),

feed_last5 AS (
  SELECT pitcher_lookup, game_date
  FROM feed_starts_ranked
  WHERE start_rank <= 5
),

-- Aggregate per (pitcher, pitch_type) over last 5 starts using per-pitch rows
feed_arsenal AS (
  SELECT
    p.pitcher_lookup AS player_lookup,
    p.pitch_type_code,
    ANY_VALUE(p.pitch_type_desc) AS feed_pitch_type_desc,
    MAX(p.game_date) AS last_seen_date,
    COUNT(*) AS total_pitch_count,
    ROUND(AVG(p.velocity), 1) AS avg_velocity,
    ROUND(
      100.0 * COUNTIF(p.is_whiff) / NULLIF(COUNTIF(p.is_swing), 0),
      1
    ) AS whiff_rate,
    COUNT(DISTINCT p.game_date) AS starts_sampled
  FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches` p
  INNER JOIN feed_last5 f
    ON p.pitcher_lookup = f.pitcher_lookup AND p.game_date = f.game_date
  WHERE p.game_date >= DATE('2025-04-01')
    AND p.pitch_type_code IS NOT NULL
  GROUP BY p.pitcher_lookup, p.pitch_type_code
),

feed_totals AS (
  SELECT player_lookup, SUM(total_pitch_count) AS arsenal_total
  FROM feed_arsenal
  GROUP BY player_lookup
),

feed_arsenal_with_usage AS (
  SELECT
    a.player_lookup,
    a.pitch_type_code,
    COALESCE(d.description, a.feed_pitch_type_desc, a.pitch_type_code) AS pitch_type_desc,
    a.last_seen_date,
    a.total_pitch_count,
    ROUND(100.0 * a.total_pitch_count / NULLIF(t.arsenal_total, 0), 1) AS usage_pct,
    a.whiff_rate,
    a.avg_velocity,
    a.starts_sampled,
    'game_feed_pitches' AS source
  FROM feed_arsenal a
  JOIN feed_totals t ON a.player_lookup = t.player_lookup
  LEFT JOIN pitch_type_desc d ON a.pitch_type_code = d.code
),

-- =============================================================================
-- PATH 2: statcast fallback (pitcher-level whiff/velo applied to each pitch type)
-- Only used for pitchers NOT present in the feed path.
-- =============================================================================

statcast_ranked_starts AS (
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

statcast_last5 AS (
  SELECT * FROM statcast_ranked_starts WHERE start_rank <= 5
),

statcast_pitch_rows AS (
  SELECT
    s.player_lookup,
    s.game_date,
    s.total_pitches AS start_total_pitches,
    s.whiff_rate AS start_whiff_rate,
    s.avg_velocity AS start_avg_velocity,
    c.code AS pitch_type_code,
    CAST(
      REGEXP_EXTRACT(
        s.pitch_types,
        CONCAT(r'"', c.code, r'":\s*(\d+)')
      ) AS INT64
    ) AS pitch_count
  FROM statcast_last5 s
  CROSS JOIN (
    SELECT code FROM UNNEST([
      'FF','FA','SI','SL','CU','CH','KC','ST','FC','FS','CS','KN','EP','SC','FO','SV','GY'
    ]) AS code
  ) c
  WHERE REGEXP_CONTAINS(s.pitch_types, CONCAT(r'"', c.code, r'"'))
),

statcast_arsenal AS (
  SELECT
    player_lookup,
    pitch_type_code,
    MAX(game_date) AS last_seen_date,
    SUM(pitch_count) AS total_pitch_count,
    SUM(start_total_pitches) AS total_pitches_across_starts,
    ROUND(
      SUM(start_avg_velocity * start_total_pitches)
      / NULLIF(SUM(start_total_pitches), 0),
      1
    ) AS avg_velocity,
    ROUND(
      SUM(start_whiff_rate * start_total_pitches)
      / NULLIF(SUM(start_total_pitches), 0),
      1
    ) AS whiff_rate,
    COUNT(DISTINCT game_date) AS starts_sampled
  FROM statcast_pitch_rows
  WHERE pitch_count > 0
  GROUP BY player_lookup, pitch_type_code
),

statcast_arsenal_with_usage AS (
  SELECT
    a.player_lookup,
    a.pitch_type_code,
    COALESCE(d.description, a.pitch_type_code) AS pitch_type_desc,
    a.last_seen_date,
    a.total_pitch_count,
    ROUND(
      a.total_pitch_count * 100.0 / NULLIF(a.total_pitches_across_starts, 0),
      1
    ) AS usage_pct,
    a.whiff_rate,
    a.avg_velocity,
    a.starts_sampled,
    'statcast_pitcher_daily' AS source
  FROM statcast_arsenal a
  LEFT JOIN pitch_type_desc d ON a.pitch_type_code = d.code
),

-- =============================================================================
-- UNION: prefer feed path; statcast fills in pitchers missing from feed
-- =============================================================================

feed_players AS (
  SELECT DISTINCT player_lookup FROM feed_arsenal_with_usage
),

combined AS (
  SELECT * FROM feed_arsenal_with_usage
  UNION ALL
  SELECT s.*
  FROM statcast_arsenal_with_usage s
  WHERE s.player_lookup NOT IN (SELECT player_lookup FROM feed_players)
)

SELECT
  player_lookup,
  pitch_type_code,
  pitch_type_desc,
  last_seen_date,
  total_pitch_count,
  usage_pct,
  whiff_rate,
  avg_velocity,
  starts_sampled,
  source,
  CURRENT_TIMESTAMP() AS computed_at
FROM combined
WHERE usage_pct >= 5.0
ORDER BY player_lookup, usage_pct DESC;
