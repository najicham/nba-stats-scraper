-- ============================================================================
-- MLB Props Platform - Pitcher Expected Arsenal Metrics
-- Arsenal-weighted league expectations: "what would this pitcher produce
-- against league-average swings?" Delta vs actual = deception / stuff gap.
-- File: schemas/bigquery/mlb_analytics/pitcher_expected_arsenal.sql
-- ============================================================================
--
-- SOURCES:
--   1. `mlb_analytics.pitcher_pitch_arsenal_latest` — per-pitcher per-type
--      usage_pct and actual whiff_rate (last 5 starts).
--   2. `mlb_analytics.league_pitch_type_stats` — league baselines per type.
--
-- OUTPUT: one row per pitcher.
--
-- KEY METRICS:
--   expected_whiff_pct       Σ(usage_pct_i × league_whiff_rate_i) / 100
--   actual_whiff_pct         Σ(usage_pct_i × whiff_rate_i)        / 100
--   whiff_vs_expected_pp     actual - expected (positive = deception premium)
--   expected_csw_pct         Σ(usage_pct_i × league_csw_rate_i)   / 100
--   stuff_velocity_premium   Σ(usage_pct_i × (avg_velo - league_avg_velo_i)) / 100
--
-- GATES:
--   - Pitcher must have at least one arsenal row from the feed source
--     (statcast-fallback pitchers lack per-type whiff_rate so delta is noisy).
--   - Arsenal coverage (sum of usage_pct) ≥ 70% for metric to be trusted.
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.mlb_analytics.pitcher_expected_arsenal_latest` AS

WITH arsenal AS (
  SELECT
    player_lookup,
    pitch_type_code,
    usage_pct,
    whiff_rate,
    avg_velocity,
    source,
    last_seen_date,
    starts_sampled,
    total_pitch_count
  FROM `nba-props-platform.mlb_analytics.pitcher_pitch_arsenal_latest`
),

joined AS (
  SELECT
    a.player_lookup,
    a.pitch_type_code,
    a.usage_pct,
    a.whiff_rate AS pitcher_whiff_rate,
    a.avg_velocity AS pitcher_avg_velocity,
    a.source,
    a.last_seen_date,
    a.starts_sampled,
    a.total_pitch_count,
    l.league_whiff_rate,
    l.league_csw_rate,
    l.league_avg_velocity
  FROM arsenal a
  LEFT JOIN `nba-props-platform.mlb_analytics.league_pitch_type_stats` l
    ON a.pitch_type_code = l.pitch_type_code
),

agg AS (
  SELECT
    player_lookup,
    ANY_VALUE(source) AS source,
    MAX(last_seen_date) AS last_seen_date,
    MAX(starts_sampled) AS starts_sampled,
    SUM(total_pitch_count) AS total_pitches_sampled,
    SUM(usage_pct) AS arsenal_coverage_pct,
    COUNT(*) AS pitch_types_sampled,
    -- Arsenal-weighted expected metrics (usage_pct is 0-100, so divide by 100 to normalize)
    SUM(usage_pct * league_whiff_rate) / 100.0 AS expected_whiff_pct_raw,
    SUM(usage_pct * pitcher_whiff_rate) / 100.0 AS actual_whiff_pct_raw,
    SUM(usage_pct * league_csw_rate) / 100.0 AS expected_csw_pct_raw,
    SUM(usage_pct * (pitcher_avg_velocity - league_avg_velocity)) / 100.0 AS stuff_velocity_premium_raw
  FROM joined
  WHERE league_whiff_rate IS NOT NULL  -- skip pitch types with no league baseline
  GROUP BY player_lookup
)

SELECT
  player_lookup,
  source,
  last_seen_date,
  starts_sampled,
  total_pitches_sampled,
  pitch_types_sampled,
  ROUND(arsenal_coverage_pct, 1) AS arsenal_coverage_pct,
  ROUND(expected_whiff_pct_raw, 2) AS expected_whiff_pct,
  ROUND(actual_whiff_pct_raw, 2) AS actual_whiff_pct,
  ROUND(actual_whiff_pct_raw - expected_whiff_pct_raw, 2) AS whiff_vs_expected_pp,
  ROUND(expected_csw_pct_raw, 2) AS expected_csw_pct,
  ROUND(stuff_velocity_premium_raw, 2) AS stuff_velocity_premium,
  -- Trust flag: feed-sourced + ≥70% arsenal coverage + ≥300 pitches sampled
  -- (300 ≈ one full starter outing; excludes short-sample reliever noise).
  (
    source = 'game_feed_pitches'
    AND arsenal_coverage_pct >= 70.0
    AND total_pitches_sampled >= 300
  ) AS is_reliable,
  CURRENT_TIMESTAMP() AS computed_at
FROM agg
ORDER BY whiff_vs_expected_pp DESC;
