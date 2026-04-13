-- ============================================================================
-- MLB Props Platform - Pitcher Advanced Arsenal
-- Derived metrics from per-pitch game feed data (Session 530)
-- File: schemas/bigquery/mlb_analytics/pitcher_advanced_arsenal_tables.sql
-- ============================================================================
--
-- Source: mlb_raw.mlb_game_feed_pitches
--
-- Produces one row per pitcher_lookup with three families of derived metrics:
--
--   1. Putaway pitch (last 3 starts, 2-strike counts only)
--      - Most-thrown pitch type on 2-strike counts
--      - Its whiff rate (whiffs / swings) when thrown on 2 strikes
--      - Its share of all 2-strike pitches
--
--   2. Velocity fade (last 5 starts, fastballs only: FF/SI/FC)
--      - Avg velocity in inning 1
--      - Avg velocity in innings 5+
--      - Fade (mph): velo_inning_1 - velo_inning_5_plus  (positive = fatigue)
--      - NULL for relievers / when fewer than 5 pitches in either bucket
--
--   3. Arsenal concentration (last 5 starts, all pitches)
--      - Herfindahl index of pitch type usage (0.15 = diverse, 1.0 = single pitch)
--      - Effective pitch count: 1 / herfindahl (e.g. 0.25 → "4 effective pitches")
--
-- Sample size floors (NULL below threshold, caller decides how to display):
--   - putaway_whiff_rate: ≥ 5 swings on 2-strike putaway pitch
--   - velo_fade_mph: ≥ 5 inning-1 fastballs AND ≥ 5 inning-5+ fastballs
--   - arsenal_concentration: ≥ 30 total pitches
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.pitcher_advanced_arsenal_latest` AS

WITH
-- Pitch-type descriptions for putaway_pitch_desc resolution
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

-- Rank each pitcher's distinct appearance dates
ranked_starts AS (
  SELECT pitcher_lookup, game_date,
    ROW_NUMBER() OVER (PARTITION BY pitcher_lookup ORDER BY game_date DESC) AS rn
  FROM (
    SELECT DISTINCT pitcher_lookup, game_date
    FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches`
    WHERE game_date >= DATE('2025-04-01')
  )
),
l3 AS (SELECT pitcher_lookup, game_date FROM ranked_starts WHERE rn <= 3),
l5 AS (SELECT pitcher_lookup, game_date FROM ranked_starts WHERE rn <= 5),

-- =============================================================================
-- 1. PUTAWAY PITCH (L3 starts, 2-strike counts)
-- =============================================================================

two_strike_pitches AS (
  SELECT
    p.pitcher_lookup,
    p.pitch_type_code,
    COUNT(*) AS pitch_count,
    COUNTIF(p.is_whiff) AS whiffs,
    COUNTIF(p.is_swing) AS swings
  FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches` p
  INNER JOIN l3 USING (pitcher_lookup, game_date)
  WHERE p.game_date >= DATE('2025-04-01')
    AND p.count_strikes = 2
    AND p.pitch_type_code IS NOT NULL
  GROUP BY 1, 2
),

two_strike_totals AS (
  SELECT pitcher_lookup, SUM(pitch_count) AS total_2k_pitches
  FROM two_strike_pitches GROUP BY 1
),

putaway_ranked AS (
  SELECT
    tsp.pitcher_lookup,
    tsp.pitch_type_code AS putaway_pitch_code,
    tsp.pitch_count AS putaway_2k_pitches,
    tsp.whiffs AS putaway_2k_whiffs,
    tsp.swings AS putaway_2k_swings,
    ROUND(100.0 * tsp.pitch_count / NULLIF(tst.total_2k_pitches, 0), 1) AS putaway_usage_pct_on_2k,
    ROW_NUMBER() OVER (
      PARTITION BY tsp.pitcher_lookup
      ORDER BY tsp.pitch_count DESC, tsp.pitch_type_code ASC
    ) AS rn
  FROM two_strike_pitches tsp
  JOIN two_strike_totals tst USING (pitcher_lookup)
),

putaway AS (
  SELECT
    pr.pitcher_lookup,
    pr.putaway_pitch_code,
    COALESCE(d.description, pr.putaway_pitch_code) AS putaway_pitch_desc,
    pr.putaway_2k_pitches,
    pr.putaway_usage_pct_on_2k,
    CASE
      WHEN pr.putaway_2k_swings >= 5
        THEN ROUND(100.0 * pr.putaway_2k_whiffs / pr.putaway_2k_swings, 1)
      ELSE NULL
    END AS putaway_whiff_rate
  FROM putaway_ranked pr
  LEFT JOIN pitch_type_desc d ON pr.putaway_pitch_code = d.code
  WHERE pr.rn = 1
),

-- =============================================================================
-- 2. VELOCITY FADE (L5 starts, fastballs only)
-- =============================================================================

fastball_velo AS (
  SELECT
    p.pitcher_lookup,
    p.inning,
    p.velocity
  FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches` p
  INNER JOIN l5 USING (pitcher_lookup, game_date)
  WHERE p.game_date >= DATE('2025-04-01')
    AND p.pitch_type_code IN ('FF', 'SI', 'FC')
    AND p.velocity IS NOT NULL
),

velo_buckets AS (
  SELECT
    pitcher_lookup,
    COUNTIF(inning = 1) AS fb_n_inning_1,
    COUNTIF(inning >= 5) AS fb_n_inning_5_plus,
    ROUND(AVG(IF(inning = 1, velocity, NULL)), 1) AS velo_inning_1,
    ROUND(AVG(IF(inning >= 5, velocity, NULL)), 1) AS velo_inning_5_plus
  FROM fastball_velo
  GROUP BY 1
),

velo_fade AS (
  SELECT
    pitcher_lookup,
    velo_inning_1,
    velo_inning_5_plus,
    CASE
      WHEN fb_n_inning_1 >= 5 AND fb_n_inning_5_plus >= 5
        THEN ROUND(velo_inning_1 - velo_inning_5_plus, 1)
      ELSE NULL
    END AS velo_fade_mph,
    fb_n_inning_1,
    fb_n_inning_5_plus
  FROM velo_buckets
),

-- =============================================================================
-- 3. ARSENAL CONCENTRATION (L5 starts, Herfindahl index)
-- =============================================================================

arsenal_usage AS (
  SELECT
    p.pitcher_lookup,
    p.pitch_type_code,
    COUNT(*) AS pitches
  FROM `nba-props-platform.mlb_raw.mlb_game_feed_pitches` p
  INNER JOIN l5 USING (pitcher_lookup, game_date)
  WHERE p.game_date >= DATE('2025-04-01')
    AND p.pitch_type_code IS NOT NULL
  GROUP BY 1, 2
),

arsenal_totals AS (
  SELECT pitcher_lookup, SUM(pitches) AS total_pitches
  FROM arsenal_usage GROUP BY 1
),

herf AS (
  SELECT
    a.pitcher_lookup,
    ROUND(SUM(POW(a.pitches / t.total_pitches, 2)), 3) AS arsenal_concentration,
    t.total_pitches
  FROM arsenal_usage a JOIN arsenal_totals t USING (pitcher_lookup)
  GROUP BY a.pitcher_lookup, t.total_pitches
),

concentration AS (
  SELECT
    pitcher_lookup,
    CASE WHEN total_pitches >= 30 THEN arsenal_concentration ELSE NULL END AS arsenal_concentration,
    CASE
      WHEN total_pitches >= 30
        THEN ROUND(1.0 / NULLIF(arsenal_concentration, 0), 2)
      ELSE NULL
    END AS effective_pitch_count
  FROM herf
),

-- =============================================================================
-- START COUNTS + LAST SEEN
-- =============================================================================

start_counts AS (
  SELECT pitcher_lookup,
    COUNTIF(rn <= 3) AS starts_l3,
    COUNTIF(rn <= 5) AS starts_l5,
    MAX(game_date) AS last_seen_date
  FROM ranked_starts
  GROUP BY 1
)

-- =============================================================================
-- FINAL: one row per pitcher_lookup
-- =============================================================================

SELECT
  s.pitcher_lookup AS player_lookup,
  s.last_seen_date,
  s.starts_l3,
  s.starts_l5,

  -- Putaway pitch
  p.putaway_pitch_code,
  p.putaway_pitch_desc,
  p.putaway_whiff_rate,
  p.putaway_usage_pct_on_2k,
  p.putaway_2k_pitches,

  -- Velocity fade
  v.velo_inning_1,
  v.velo_inning_5_plus,
  v.velo_fade_mph,
  v.fb_n_inning_1,
  v.fb_n_inning_5_plus,

  -- Arsenal concentration
  c.arsenal_concentration,
  c.effective_pitch_count,

  CURRENT_TIMESTAMP() AS computed_at

FROM start_counts s
LEFT JOIN putaway p ON s.pitcher_lookup = p.pitcher_lookup
LEFT JOIN velo_fade v ON s.pitcher_lookup = v.pitcher_lookup
LEFT JOIN concentration c ON s.pitcher_lookup = c.pitcher_lookup
ORDER BY s.last_seen_date DESC, s.pitcher_lookup;
