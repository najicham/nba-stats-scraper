-- File: monitoring/queries/usage_rate_anomalies.sql
-- Description: Detect anomalous usage_rate values that indicate data quality issues
-- Added: 2026-01-27 as part of data quality investigation fixes
--
-- Usage: Run daily to detect usage_rate values > 50% (suspicious) or > 100% (invalid)
-- Invalid values typically indicate partial team data was processed as final
--
-- Expected: Zero rows for usage_rate > 100% after schema fix

-- Current day anomalies
SELECT
  game_date,
  game_id,
  player_lookup,
  team_abbr,
  opponent_team_abbr,
  usage_rate,
  usage_rate_valid,
  usage_rate_anomaly_reason,
  CASE
    WHEN usage_rate > 100 THEN 'INVALID - exceeds 100%'
    WHEN usage_rate > 50 THEN 'SUSPICIOUS - exceeds 50%'
    WHEN usage_rate > 40 THEN 'HIGH - check if correct'
    ELSE 'OK'
  END as anomaly_severity,
  -- Context for investigation
  minutes_played,
  fg_attempts,
  is_partial_game_data,
  game_status_at_processing,
  source_team_completeness_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND usage_rate > 40  -- Flag anything above typical max
ORDER BY usage_rate DESC, game_date DESC;

-- Summary by date
SELECT
  game_date,
  COUNT(*) as total_records,
  COUNTIF(usage_rate IS NOT NULL) as has_usage_rate,
  COUNTIF(usage_rate > 100) as invalid_over_100,
  COUNTIF(usage_rate > 50 AND usage_rate <= 100) as suspicious_50_to_100,
  COUNTIF(usage_rate > 40 AND usage_rate <= 50) as high_40_to_50,
  ROUND(COUNTIF(usage_rate > 50) * 100.0 / NULLIF(COUNTIF(usage_rate IS NOT NULL), 0), 2) as anomaly_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Historical trend for alerting thresholds
SELECT
  DATE_TRUNC(game_date, WEEK) as week_start,
  COUNT(*) as total_records,
  COUNTIF(usage_rate > 100) as invalid_count,
  COUNTIF(usage_rate > 50) as suspicious_count,
  MAX(usage_rate) as max_usage_rate
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY week_start
ORDER BY week_start DESC;
