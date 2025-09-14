-- ============================================================================
-- NBA Props Platform - Cross-Table Views
-- Multi-table views for common analytics queries
-- ============================================================================

-- Today's betting opportunities with all context
CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.todays_opportunities` AS
SELECT 
  ml.player_lookup,
  ml.game_id,
  ml.game_date,
  ml.ml_points_prediction,
  ml.ml_over_probability,
  ml.ml_prediction_confidence,
  ml.recommendation,
  ml.data_quality_tier,
  u.team_abbr,
  u.opponent_team_abbr,
  u.current_points_line,
  u.prop_over_streak,
  u.prop_under_streak,
  u.points_avg_last_5,
  u.games_in_last_7_days,
  u.travel_miles,
  ABS(u.line_movement) as line_movement_magnitude
FROM `nba-props-platform.nba_analytics.current_ml_predictions` ml
JOIN `nba-props-platform.nba_analytics.upcoming_player_game_context` u
  ON ml.player_lookup = u.player_lookup 
  AND ml.game_date = u.game_date
WHERE ml.game_date = CURRENT_DATE()
  AND ml.ml_prediction_confidence > 60
  AND ml.recommendation != 'PASS'
  AND ml.data_quality_tier IN ('high', 'medium')
ORDER BY ml.ml_prediction_confidence DESC;

-- Data quality monitoring dashboard
CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.quality_monitoring` AS
SELECT 
  table_name,
  event_type,
  severity,
  COUNT(*) as issue_count,
  MAX(event_timestamp) as latest_occurrence,
  COUNT(CASE WHEN resolution_status = 'open' THEN 1 END) as open_issues
FROM `nba-props-platform.nba_analytics.data_quality_events`
WHERE event_timestamp >= TIMESTAMP(DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY))
GROUP BY table_name, event_type, severity
ORDER BY issue_count DESC;

-- Team context for player props
CREATE OR REPLACE VIEW `nba-props-platform.nba_analytics.team_context_for_props` AS
SELECT 
  tc.game_id,
  tc.team_abbr,
  tc.opponent_team_abbr,
  tc.team_days_rest,
  tc.starters_out_count,
  tc.star_players_out_count,
  tc.team_win_streak_entering,
  tc.team_loss_streak_entering,
  tc.last_game_margin,
  tc.ats_cover_streak,
  tc.over_streak,
  tc.referee_crew_id
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context` tc;