-- ============================================================================
-- COMPREHENSIVE DATA QUALITY INVESTIGATION
-- Purpose: Understand root causes of ML model failure
-- Date: 2026-01-02
-- ============================================================================

-- ============================================================================
-- INVESTIGATION 1: NULL PATTERN ANALYSIS FOR ALL 25 FEATURES
-- ============================================================================

-- 1A: Overall NULL rates across all features
CREATE TEMP TABLE null_analysis AS
WITH player_games AS (
  SELECT
    player_lookup,
    game_date,
    game_id,
    team_abbr,
    opponent_team_abbr,
    points,
    minutes_played,
    usage_rate,
    CAST(starter_flag AS INT64) as is_starter,
    -- Shot distribution
    SAFE_DIVIDE(paint_attempts, NULLIF(fg_attempts, 0)) * 100 as paint_rate,
    SAFE_DIVIDE(mid_range_attempts, NULLIF(fg_attempts, 0)) * 100 as mid_range_rate,
    SAFE_DIVIDE(three_pt_attempts, NULLIF(fg_attempts, 0)) * 100 as three_pt_rate,
    SAFE_DIVIDE(assisted_fg_makes, NULLIF(fg_makes, 0)) * 100 as assisted_rate,
    -- Game context
    CASE
      WHEN SPLIT(game_id, '_')[SAFE_OFFSET(2)] = team_abbr THEN TRUE
      ELSE FALSE
    END as is_home
  FROM `nba-props-platform.nba_analytics.player_game_summary`
  WHERE game_date >= '2021-10-01'
    AND game_date < '2024-05-01'
    AND points IS NOT NULL
),

player_performance AS (
  SELECT
    player_lookup,
    game_date,
    team_abbr,
    opponent_team_abbr,
    is_home,
    points as actual_points,

    -- Performance features (rolling averages)
    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
    ) as points_avg_last_5,

    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as points_avg_last_10,

    AVG(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    ) as points_avg_season,

    STDDEV(points) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as points_std_last_10,

    AVG(minutes_played) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as minutes_avg_last_10,

    -- Rest/fatigue features
    DATE_DIFF(
      game_date,
      LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY
    ) as days_rest,

    CASE WHEN DATE_DIFF(
      game_date,
      LAG(game_date) OVER (PARTITION BY player_lookup ORDER BY game_date),
      DAY
    ) = 1 THEN TRUE ELSE FALSE END as back_to_back,

    -- Shot distribution features
    AVG(paint_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as paint_rate_last_10,

    AVG(mid_range_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as mid_range_rate_last_10,

    AVG(three_pt_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as three_pt_rate_last_10,

    AVG(assisted_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as assisted_rate_last_10,

    AVG(usage_rate) OVER (
      PARTITION BY player_lookup
      ORDER BY game_date
      ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
    ) as usage_rate_last_10

  FROM player_games
),

feature_data AS (
  SELECT
    pp.*,

    -- Composite factors from precompute
    pcf.fatigue_score,
    pcf.shot_zone_mismatch_score,
    pcf.pace_score,
    pcf.usage_spike_score,

    -- Opponent defense metrics
    tdz.defensive_rating_last_15 as opponent_def_rating_last_15,
    tdz.opponent_pace as opponent_pace_last_15,

    -- Team metrics
    pdc.team_pace_last_10,
    pdc.team_off_rating_last_10

  FROM player_performance pp
  LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors` pcf
    ON pp.player_lookup = pcf.player_lookup
    AND pp.game_date = pcf.game_date
  LEFT JOIN `nba-props-platform.nba_precompute.team_defense_zone_analysis` tdz
    ON pp.opponent_team_abbr = tdz.team_abbr
    AND pp.game_date = tdz.analysis_date
  LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache` pdc
    ON pp.player_lookup = pdc.player_lookup
    AND pp.game_date = pdc.cache_date
  WHERE pp.points_avg_last_5 IS NOT NULL
    AND pp.points_avg_last_10 IS NOT NULL
)

SELECT
  COUNT(*) as total_rows,

  -- Performance features (5)
  COUNTIF(points_avg_last_5 IS NULL) as null_points_avg_last_5,
  COUNTIF(points_avg_last_10 IS NULL) as null_points_avg_last_10,
  COUNTIF(points_avg_season IS NULL) as null_points_avg_season,
  COUNTIF(points_std_last_10 IS NULL) as null_points_std_last_10,
  COUNTIF(minutes_avg_last_10 IS NULL) as null_minutes_avg_last_10,

  -- Composite factors (4)
  COUNTIF(fatigue_score IS NULL) as null_fatigue_score,
  COUNTIF(shot_zone_mismatch_score IS NULL) as null_shot_zone_mismatch_score,
  COUNTIF(pace_score IS NULL) as null_pace_score,
  COUNTIF(usage_spike_score IS NULL) as null_usage_spike_score,

  -- Opponent metrics (2)
  COUNTIF(opponent_def_rating_last_15 IS NULL) as null_opponent_def_rating_last_15,
  COUNTIF(opponent_pace_last_15 IS NULL) as null_opponent_pace_last_15,

  -- Game context (3)
  COUNTIF(is_home IS NULL) as null_is_home,
  COUNTIF(days_rest IS NULL) as null_days_rest,
  COUNTIF(back_to_back IS NULL) as null_back_to_back,

  -- Shot distribution (4)
  COUNTIF(paint_rate_last_10 IS NULL) as null_paint_rate_last_10,
  COUNTIF(mid_range_rate_last_10 IS NULL) as null_mid_range_rate_last_10,
  COUNTIF(three_pt_rate_last_10 IS NULL) as null_three_pt_rate_last_10,
  COUNTIF(assisted_rate_last_10 IS NULL) as null_assisted_rate_last_10,

  -- Team metrics (2)
  COUNTIF(team_pace_last_10 IS NULL) as null_team_pace_last_10,
  COUNTIF(team_off_rating_last_10 IS NULL) as null_team_off_rating_last_10,

  -- Usage (1)
  COUNTIF(usage_rate_last_10 IS NULL) as null_usage_rate_last_10,

  -- Target
  COUNTIF(actual_points IS NULL) as null_actual_points

FROM feature_data;

-- 1B: NULL rates by time period (check for temporal patterns)
SELECT
  'NULL Rates by Season' as analysis_type,
  EXTRACT(YEAR FROM game_date) as year,
  COUNT(*) as total_games,

  -- Sample high-impact features
  ROUND(COUNTIF(minutes_avg_last_10 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_minutes_avg_last_10,
  ROUND(COUNTIF(fatigue_score IS NULL) * 100.0 / COUNT(*), 2) as pct_null_fatigue_score,
  ROUND(COUNTIF(opponent_def_rating_last_15 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_opponent_def_rating,
  ROUND(COUNTIF(team_pace_last_10 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_team_pace_last_10,
  ROUND(COUNTIF(paint_rate_last_10 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_paint_rate_last_10

FROM feature_data
GROUP BY year
ORDER BY year;

-- 1C: NULL rates by team (check if specific teams have data issues)
SELECT
  'NULL Rates by Team' as analysis_type,
  team_abbr,
  COUNT(*) as total_games,

  ROUND(COUNTIF(minutes_avg_last_10 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_minutes_avg_last_10,
  ROUND(COUNTIF(fatigue_score IS NULL) * 100.0 / COUNT(*), 2) as pct_null_fatigue_score,
  ROUND(COUNTIF(opponent_def_rating_last_15 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_opponent_def_rating,
  ROUND(COUNTIF(team_pace_last_10 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_team_pace_last_10

FROM feature_data
GROUP BY team_abbr
HAVING COUNT(*) > 100
ORDER BY pct_null_team_pace_last_10 DESC
LIMIT 10;


-- ============================================================================
-- INVESTIGATION 2: DATA DISTRIBUTION ANALYSIS
-- ============================================================================

-- 2A: Feature statistics across entire dataset
SELECT
  'Overall Feature Statistics' as analysis_type,

  -- Performance features
  ROUND(AVG(points_avg_last_5), 2) as mean_points_avg_last_5,
  ROUND(STDDEV(points_avg_last_5), 2) as std_points_avg_last_5,
  ROUND(MIN(points_avg_last_5), 2) as min_points_avg_last_5,
  ROUND(MAX(points_avg_last_5), 2) as max_points_avg_last_5,

  ROUND(AVG(points_avg_last_10), 2) as mean_points_avg_last_10,
  ROUND(STDDEV(points_avg_last_10), 2) as std_points_avg_last_10,

  ROUND(AVG(COALESCE(minutes_avg_last_10, 0)), 2) as mean_minutes_avg_last_10,
  ROUND(STDDEV(COALESCE(minutes_avg_last_10, 0)), 2) as std_minutes_avg_last_10,

  -- Shot distribution
  ROUND(AVG(COALESCE(paint_rate_last_10, 0)), 2) as mean_paint_rate_last_10,
  ROUND(AVG(COALESCE(mid_range_rate_last_10, 0)), 2) as mean_mid_range_rate_last_10,
  ROUND(AVG(COALESCE(three_pt_rate_last_10, 0)), 2) as mean_three_pt_rate_last_10,

  -- Composite factors
  ROUND(AVG(COALESCE(fatigue_score, 0)), 2) as mean_fatigue_score,
  ROUND(STDDEV(COALESCE(fatigue_score, 0)), 2) as std_fatigue_score,

  -- Target variable
  ROUND(AVG(actual_points), 2) as mean_actual_points,
  ROUND(STDDEV(actual_points), 2) as std_actual_points,
  ROUND(MIN(actual_points), 2) as min_actual_points,
  ROUND(MAX(actual_points), 2) as max_actual_points

FROM feature_data;

-- 2B: Distribution comparison: Train vs Test periods
WITH splits AS (
  SELECT
    *,
    CASE
      WHEN game_date < '2023-04-01' THEN 'train'
      ELSE 'test'
    END as split
  FROM feature_data
)

SELECT
  split,
  COUNT(*) as samples,

  -- Performance features
  ROUND(AVG(points_avg_last_5), 2) as mean_points_avg_last_5,
  ROUND(STDDEV(points_avg_last_5), 2) as std_points_avg_last_5,

  ROUND(AVG(points_avg_last_10), 2) as mean_points_avg_last_10,
  ROUND(STDDEV(points_avg_last_10), 2) as std_points_avg_last_10,

  -- Shot distribution
  ROUND(AVG(COALESCE(paint_rate_last_10, 30)), 2) as mean_paint_rate_last_10,
  ROUND(AVG(COALESCE(three_pt_rate_last_10, 30)), 2) as mean_three_pt_rate_last_10,

  -- Composite factors
  ROUND(AVG(COALESCE(fatigue_score, 70)), 2) as mean_fatigue_score,

  -- Game context
  ROUND(AVG(CAST(is_home AS FLOAT64)), 2) as pct_home_games,
  ROUND(AVG(COALESCE(days_rest, 2)), 2) as mean_days_rest,
  ROUND(AVG(CAST(back_to_back AS FLOAT64)), 2) as pct_back_to_back,

  -- Target variable
  ROUND(AVG(actual_points), 2) as mean_actual_points,
  ROUND(STDDEV(actual_points), 2) as std_actual_points

FROM splits
GROUP BY split
ORDER BY split;

-- 2C: Check for extreme outliers
SELECT
  'Extreme Outliers' as analysis_type,
  COUNT(*) as total_outliers,

  -- Performance outliers
  COUNTIF(points_avg_last_10 > 50) as outliers_points_over_50,
  COUNTIF(points_avg_last_10 < 0) as outliers_points_negative,

  -- Shot rate outliers (should sum to ~100%)
  COUNTIF(
    COALESCE(paint_rate_last_10, 0) +
    COALESCE(mid_range_rate_last_10, 0) +
    COALESCE(three_pt_rate_last_10, 0) > 150
  ) as outliers_shot_rates_over_150,

  -- Fatigue outliers
  COUNTIF(fatigue_score < 0 OR fatigue_score > 100) as outliers_fatigue_invalid,

  -- Rest outliers
  COUNTIF(days_rest > 30) as outliers_days_rest_over_30,

  -- Target outliers
  COUNTIF(actual_points > 70) as outliers_actual_points_over_70,
  COUNTIF(actual_points < 0) as outliers_actual_points_negative

FROM feature_data;


-- ============================================================================
-- INVESTIGATION 3: FEATURE CORRELATION ANALYSIS
-- ============================================================================

-- 3A: Correlation between key features
SELECT
  'Feature Correlations' as analysis_type,

  -- Performance features correlation
  ROUND(CORR(points_avg_last_5, points_avg_last_10), 3) as corr_points_5_vs_10,
  ROUND(CORR(points_avg_last_10, points_avg_season), 3) as corr_points_10_vs_season,

  -- Shot distribution correlation
  ROUND(CORR(
    COALESCE(paint_rate_last_10, 30),
    COALESCE(three_pt_rate_last_10, 30)
  ), 3) as corr_paint_vs_3pt,

  -- Correlation with target
  ROUND(CORR(points_avg_last_5, actual_points), 3) as corr_points5_vs_target,
  ROUND(CORR(points_avg_last_10, actual_points), 3) as corr_points10_vs_target,
  ROUND(CORR(COALESCE(fatigue_score, 70), actual_points), 3) as corr_fatigue_vs_target,
  ROUND(CORR(CAST(is_home AS FLOAT64), actual_points), 3) as corr_home_vs_target,
  ROUND(CORR(COALESCE(days_rest, 2), actual_points), 3) as corr_rest_vs_target

FROM feature_data
WHERE points_avg_last_5 IS NOT NULL
  AND points_avg_last_10 IS NOT NULL;


-- ============================================================================
-- INVESTIGATION 4: SAMPLE SUFFICIENCY ANALYSIS
-- ============================================================================

-- 4A: Overall sample counts
SELECT
  'Sample Sufficiency' as analysis_type,
  COUNT(*) as total_samples,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(COUNT(*) / COUNT(DISTINCT player_lookup), 1) as avg_games_per_player,

  -- Samples with complete data (no NULLs in key features)
  COUNTIF(
    points_avg_last_5 IS NOT NULL AND
    points_avg_last_10 IS NOT NULL AND
    minutes_avg_last_10 IS NOT NULL AND
    fatigue_score IS NOT NULL AND
    team_pace_last_10 IS NOT NULL
  ) as samples_complete_data,

  ROUND(
    COUNTIF(
      points_avg_last_5 IS NOT NULL AND
      points_avg_last_10 IS NOT NULL AND
      minutes_avg_last_10 IS NOT NULL AND
      fatigue_score IS NOT NULL AND
      team_pace_last_10 IS NOT NULL
    ) * 100.0 / COUNT(*), 2
  ) as pct_complete_data

FROM feature_data;

-- 4B: Sample distribution by player type
SELECT
  'Sample Distribution by Player Type' as analysis_type,
  CASE
    WHEN points_avg_season >= 20 THEN 'Star (20+ ppg)'
    WHEN points_avg_season >= 12 THEN 'Starter (12-20 ppg)'
    WHEN points_avg_season >= 6 THEN 'Role Player (6-12 ppg)'
    ELSE 'Bench (<6 ppg)'
  END as player_type,

  COUNT(*) as samples,
  COUNT(DISTINCT player_lookup) as unique_players,
  ROUND(AVG(actual_points), 2) as mean_actual_points,
  ROUND(STDDEV(actual_points), 2) as std_actual_points,
  ROUND(MIN(actual_points), 2) as min_actual_points,
  ROUND(MAX(actual_points), 2) as max_actual_points

FROM feature_data
WHERE points_avg_season IS NOT NULL
GROUP BY player_type
ORDER BY MIN(points_avg_season) DESC;


-- ============================================================================
-- INVESTIGATION 5: TARGET VARIABLE ANALYSIS
-- ============================================================================

-- 5A: Target distribution analysis
SELECT
  'Target Variable Distribution' as analysis_type,
  COUNT(*) as total_samples,

  -- Central tendency
  ROUND(AVG(actual_points), 2) as mean_actual_points,
  ROUND(APPROX_QUANTILES(actual_points, 100)[OFFSET(50)], 2) as median_actual_points,

  -- Dispersion
  ROUND(STDDEV(actual_points), 2) as std_actual_points,
  ROUND(MIN(actual_points), 2) as min_actual_points,
  ROUND(MAX(actual_points), 2) as max_actual_points,

  -- Percentiles
  ROUND(APPROX_QUANTILES(actual_points, 100)[OFFSET(25)], 2) as p25_actual_points,
  ROUND(APPROX_QUANTILES(actual_points, 100)[OFFSET(75)], 2) as p75_actual_points,
  ROUND(APPROX_QUANTILES(actual_points, 100)[OFFSET(90)], 2) as p90_actual_points,

  -- Distribution bins
  COUNTIF(actual_points = 0) as count_0_points,
  COUNTIF(actual_points > 0 AND actual_points <= 5) as count_1_5_points,
  COUNTIF(actual_points > 5 AND actual_points <= 10) as count_6_10_points,
  COUNTIF(actual_points > 10 AND actual_points <= 20) as count_11_20_points,
  COUNTIF(actual_points > 20 AND actual_points <= 30) as count_21_30_points,
  COUNTIF(actual_points > 30) as count_over_30_points

FROM feature_data;

-- 5B: Compare starters vs bench players
SELECT
  'Starters vs Bench Analysis' as analysis_type,
  CASE
    WHEN points_avg_season >= 15 THEN 'Likely Starter'
    ELSE 'Likely Bench'
  END as player_category,

  COUNT(*) as samples,
  COUNT(DISTINCT player_lookup) as unique_players,

  -- Target statistics
  ROUND(AVG(actual_points), 2) as mean_actual_points,
  ROUND(STDDEV(actual_points), 2) as std_actual_points,
  ROUND(AVG(points_avg_last_10), 2) as mean_points_avg_last_10,

  -- Feature availability
  ROUND(COUNTIF(fatigue_score IS NOT NULL) * 100.0 / COUNT(*), 2) as pct_has_fatigue_score,
  ROUND(COUNTIF(team_pace_last_10 IS NOT NULL) * 100.0 / COUNT(*), 2) as pct_has_team_pace,

  -- Prediction difficulty (variance)
  ROUND(AVG(ABS(actual_points - points_avg_last_10)), 2) as mean_abs_deviation_from_avg

FROM feature_data
WHERE points_avg_season IS NOT NULL
GROUP BY player_category
ORDER BY MIN(points_avg_season) DESC;


-- ============================================================================
-- INVESTIGATION 6: DATA QUALITY ISSUES
-- ============================================================================

-- 6A: Impossible values detection
SELECT
  'Impossible Values Detection' as analysis_type,

  -- Negative values
  COUNTIF(points_avg_last_5 < 0) as negative_points_avg_last_5,
  COUNTIF(points_avg_last_10 < 0) as negative_points_avg_last_10,
  COUNTIF(actual_points < 0) as negative_actual_points,

  -- Unrealistic high values
  COUNTIF(points_avg_last_10 > 60) as unrealistic_points_avg_last_10,
  COUNTIF(actual_points > 80) as unrealistic_actual_points,

  -- Invalid percentages (should be 0-100)
  COUNTIF(paint_rate_last_10 < 0 OR paint_rate_last_10 > 100) as invalid_paint_rate,
  COUNTIF(three_pt_rate_last_10 < 0 OR three_pt_rate_last_10 > 100) as invalid_3pt_rate,
  COUNTIF(fatigue_score < 0 OR fatigue_score > 100) as invalid_fatigue_score,

  -- Invalid rest days
  COUNTIF(days_rest < 0) as negative_days_rest,
  COUNTIF(days_rest > 60) as unrealistic_days_rest

FROM feature_data;

-- 6B: Consistency checks
SELECT
  'Data Consistency Checks' as analysis_type,

  -- Check if recent average > season average (should be common due to trends)
  COUNTIF(points_avg_last_10 > points_avg_season * 2) as recent_2x_season_avg,

  -- Check if variance is too high (std dev > mean indicates high noise)
  COUNTIF(points_std_last_10 > points_avg_last_10) as high_variance_players,

  -- Shot distribution total (should be ~100%)
  AVG(
    COALESCE(paint_rate_last_10, 0) +
    COALESCE(mid_range_rate_last_10, 0) +
    COALESCE(three_pt_rate_last_10, 0)
  ) as avg_total_shot_rate,

  COUNTIF(
    ABS(
      COALESCE(paint_rate_last_10, 0) +
      COALESCE(mid_range_rate_last_10, 0) +
      COALESCE(three_pt_rate_last_10, 0) - 100
    ) > 20
  ) as shot_rate_sum_off_by_20pct

FROM feature_data
WHERE points_avg_last_10 IS NOT NULL
  AND points_avg_season IS NOT NULL;


-- ============================================================================
-- INVESTIGATION 7: MISSING DATA IMPACT ANALYSIS
-- ============================================================================

-- 7A: Compare prediction accuracy with/without complete data
WITH predictions AS (
  SELECT
    player_lookup,
    game_date,
    actual_points,
    points_avg_last_10,

    -- Completeness flag
    CASE
      WHEN fatigue_score IS NOT NULL
        AND team_pace_last_10 IS NOT NULL
        AND opponent_def_rating_last_15 IS NOT NULL
      THEN 'Complete'
      ELSE 'Incomplete'
    END as data_completeness,

    -- Simple baseline prediction
    ABS(actual_points - points_avg_last_10) as prediction_error

  FROM feature_data
  WHERE points_avg_last_10 IS NOT NULL
)

SELECT
  data_completeness,
  COUNT(*) as samples,
  ROUND(AVG(prediction_error), 2) as mean_baseline_error,
  ROUND(STDDEV(prediction_error), 2) as std_baseline_error

FROM predictions
GROUP BY data_completeness;


-- ============================================================================
-- SUMMARY: Key Metrics for Report
-- ============================================================================

SELECT
  'SUMMARY: Key Data Quality Metrics' as report_section,

  -- Sample size
  COUNT(*) as total_samples,
  COUNT(DISTINCT player_lookup) as unique_players,

  -- NULL rates for critical features
  ROUND(COUNTIF(minutes_avg_last_10 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_minutes,
  ROUND(COUNTIF(fatigue_score IS NULL) * 100.0 / COUNT(*), 2) as pct_null_fatigue,
  ROUND(COUNTIF(team_pace_last_10 IS NULL) * 100.0 / COUNT(*), 2) as pct_null_team_pace,

  -- Data quality
  COUNTIF(actual_points < 0 OR actual_points > 80) as impossible_target_values,
  ROUND(AVG(actual_points), 2) as mean_target,
  ROUND(STDDEV(actual_points), 2) as std_target,

  -- Correlation with target
  ROUND(CORR(points_avg_last_10, actual_points), 3) as corr_recent_avg_with_target

FROM feature_data;
