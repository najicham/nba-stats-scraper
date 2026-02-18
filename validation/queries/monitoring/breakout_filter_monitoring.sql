-- Breakout Filter Monitoring Queries
-- Created: Session 125 (2026-02-05)
-- Purpose: Track performance of role player UNDER filters and breakout patterns

-- =============================================================================
-- 1. DAILY FILTER PERFORMANCE
-- Run daily to see if filters are working
-- =============================================================================
WITH filtered_predictions AS (
  SELECT
    game_date,
    filter_reason,
    prediction_correct,
    predicted_points,
    line_value,
    actual_points
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = 'catboost_v9'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND filter_reason LIKE 'role_player_under%'
)
SELECT
  game_date,
  filter_reason,
  COUNT(*) as filtered_bets,
  -- Shadow tracking: would these have won if we bet them?
  COUNTIF(prediction_correct) as would_have_won,
  COUNTIF(NOT prediction_correct) as would_have_lost,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hypothetical_hit_rate,
  -- If hit rate < 50%, filter is SAVING us money
  CASE WHEN COUNTIF(prediction_correct) < COUNT(*) * 0.5
       THEN 'FILTER_WORKING' ELSE 'REVIEW_FILTER' END as status
FROM filtered_predictions
GROUP BY 1, 2
ORDER BY 1 DESC, 2;


-- =============================================================================
-- 2. BREAKOUT RATE BY OPPONENT
-- Identify which opponents allow more role player breakouts
-- =============================================================================
WITH role_player_games AS (
  SELECT
    pgs.opponent_team_abbr,
    pgs.points,
    -- Get season average from feature store
    fs.feature_2_value as season_avg,
    CASE WHEN pgs.points >= fs.feature_2_value * 1.5 THEN 1 ELSE 0 END as is_breakout
  FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
  JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
    ON pgs.player_lookup = fs.player_lookup
    AND pgs.game_date = fs.game_date
  WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND fs.feature_2_value BETWEEN 8 AND 16  -- Role players
    AND pgs.minutes_played >= 15
    AND fs.feature_2_value IS NOT NULL
)
SELECT
  opponent_team_abbr,
  COUNT(*) as games,
  SUM(is_breakout) as breakouts,
  ROUND(100.0 * SUM(is_breakout) / COUNT(*), 1) as breakout_rate_pct,
  CASE WHEN SUM(is_breakout) * 1.0 / COUNT(*) > 0.25
       THEN 'HIGH_RISK' ELSE 'NORMAL' END as risk_level
FROM role_player_games
GROUP BY 1
HAVING COUNT(*) >= 15
ORDER BY breakout_rate_pct DESC;


-- =============================================================================
-- 3. PLAYER BREAKOUT PROFILES
-- Identify high-volatility players who break out frequently
-- =============================================================================
WITH player_breakouts AS (
  SELECT
    pgs.player_lookup,
    pgs.team_abbr,
    COUNT(*) as total_games,
    COUNTIF(pgs.points >= fs.feature_2_value * 1.5) as breakout_games,
    AVG(fs.feature_2_value) as avg_season_ppg,
    AVG(fs.feature_3_value) as avg_std_dev,
    MAX(pgs.points) as max_points,
    AVG(pgs.points) as avg_points
  FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
  JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
    ON pgs.player_lookup = fs.player_lookup
    AND pgs.game_date = fs.game_date
  WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND fs.feature_2_value BETWEEN 8 AND 16  -- Role players
    AND pgs.minutes_played >= 15
    AND fs.feature_2_value IS NOT NULL
  GROUP BY 1, 2
  HAVING COUNT(*) >= 10
)
SELECT
  player_lookup,
  team_abbr,
  total_games,
  breakout_games,
  ROUND(100.0 * breakout_games / total_games, 1) as breakout_rate_pct,
  ROUND(avg_season_ppg, 1) as avg_ppg,
  ROUND(avg_std_dev, 1) as volatility,
  max_points,
  ROUND(max_points / avg_season_ppg, 2) as explosion_ratio,
  CASE
    WHEN breakout_games * 1.0 / total_games > 0.25 THEN 'HIGH_BREAKOUT_RISK'
    WHEN avg_std_dev > 7 THEN 'HIGH_VOLATILITY'
    ELSE 'NORMAL'
  END as player_risk_profile
FROM player_breakouts
ORDER BY breakout_rate_pct DESC
LIMIT 30;


-- =============================================================================
-- 4. HOT STREAK ANALYSIS
-- Track players on hot streaks (L5 >> season avg) and their breakout rates
-- =============================================================================
WITH hot_players AS (
  SELECT
    pgs.game_date,
    pgs.player_lookup,
    pgs.points as actual_points,
    fs.feature_0_value as l5_avg,
    fs.feature_2_value as season_avg,
    fs.feature_35_value as zscore,  -- pts_vs_season_zscore
    fs.feature_36_value as breakout_flag,
    CASE WHEN pgs.points >= fs.feature_2_value * 1.5 THEN 1 ELSE 0 END as had_breakout
  FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
  JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
    ON pgs.player_lookup = fs.player_lookup
    AND pgs.game_date = fs.game_date
  WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND fs.feature_2_value BETWEEN 8 AND 16  -- Role players
    AND pgs.minutes_played >= 15
    AND fs.feature_2_value IS NOT NULL
)
SELECT
  CASE
    WHEN zscore >= 2.0 THEN 'VERY_HOT (z>=2)'
    WHEN zscore >= 1.0 THEN 'HOT (z>=1)'
    WHEN zscore >= 0 THEN 'WARM (z>=0)'
    ELSE 'COLD (z<0)'
  END as streak_status,
  COUNT(*) as games,
  SUM(had_breakout) as breakouts,
  ROUND(100.0 * SUM(had_breakout) / COUNT(*), 1) as breakout_rate_pct,
  ROUND(AVG(actual_points), 1) as avg_actual_points
FROM hot_players
GROUP BY 1
ORDER BY breakout_rate_pct DESC;


-- =============================================================================
-- 5. WEEKLY SUMMARY - Filter Effectiveness
-- Run weekly to evaluate overall filter performance
-- =============================================================================
WITH weekly_summary AS (
  SELECT
    DATE_TRUNC(game_date, WEEK) as week_start,
    -- Actionable bets
    COUNTIF(is_actionable AND recommendation = 'UNDER') as under_bets_taken,
    COUNTIF(is_actionable AND recommendation = 'UNDER' AND prediction_correct) as under_wins,
    -- Filtered bets (shadow)
    COUNTIF(NOT is_actionable AND filter_reason LIKE 'role_player%') as role_player_filtered,
    COUNTIF(NOT is_actionable AND filter_reason LIKE 'role_player%' AND prediction_correct) as filtered_would_have_won
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = 'catboost_v9'
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 28 DAY)
  GROUP BY 1
)
SELECT
  week_start,
  under_bets_taken,
  under_wins,
  ROUND(100.0 * under_wins / NULLIF(under_bets_taken, 0), 1) as under_hit_rate,
  role_player_filtered,
  filtered_would_have_won,
  ROUND(100.0 * filtered_would_have_won / NULLIF(role_player_filtered, 0), 1) as filtered_hypothetical_rate,
  -- Calculate money saved by filtering
  CASE
    WHEN filtered_would_have_won < role_player_filtered * 0.5
    THEN CONCAT('+$', CAST(ROUND((role_player_filtered - 2*filtered_would_have_won) * 1.0, 2) AS STRING), ' saved per $1 bet')
    ELSE 'REVIEW: Filter may be too aggressive'
  END as filter_value
FROM weekly_summary
ORDER BY week_start DESC;


-- =============================================================================
-- 6. TEAMMATE INJURY IMPACT
-- Check if teammate injuries correlate with breakouts
-- =============================================================================
WITH games_with_injuries AS (
  SELECT
    pgs.game_date,
    pgs.player_lookup,
    pgs.points,
    fs.feature_2_value as season_avg,
    -- Check if teammate usage boost feature indicates injury opportunity
    COALESCE(pp.teammate_usage_boost, 0) as usage_boost,
    CASE WHEN pgs.points >= fs.feature_2_value * 1.5 THEN 1 ELSE 0 END as had_breakout
  FROM `nba-props-platform.nba_analytics.player_game_summary` pgs
  JOIN `nba-props-platform.nba_predictions.ml_feature_store_v2` fs
    ON pgs.player_lookup = fs.player_lookup
    AND pgs.game_date = fs.game_date
  LEFT JOIN `nba-props-platform.nba_predictions.player_prop_predictions` pp
    ON pgs.player_lookup = pp.player_lookup
    AND pgs.game_date = pp.game_date
    AND pp.system_id = 'catboost_v9'
    AND pp.is_active = true
  WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
    AND fs.feature_2_value BETWEEN 8 AND 16  -- Role players
    AND pgs.minutes_played >= 15
    AND fs.feature_2_value IS NOT NULL
)
SELECT
  CASE
    WHEN usage_boost >= 1.2 THEN 'HIGH_OPPORTUNITY (boost>=1.2)'
    WHEN usage_boost >= 1.1 THEN 'MODERATE_OPPORTUNITY (boost>=1.1)'
    ELSE 'NORMAL (no boost)'
  END as opportunity_level,
  COUNT(*) as games,
  SUM(had_breakout) as breakouts,
  ROUND(100.0 * SUM(had_breakout) / COUNT(*), 1) as breakout_rate_pct
FROM games_with_injuries
GROUP BY 1
ORDER BY breakout_rate_pct DESC;
