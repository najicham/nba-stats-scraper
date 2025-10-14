-- File: validation/queries/raw/nbac_play_by_play/score_progression_validation.sql
-- ============================================================================
-- Score Progression Validation
-- Purpose: Detect score anomalies and validate final scores match box scores
-- Ensures scoring events are processed correctly
-- ============================================================================

WITH score_progression AS (
  SELECT 
    game_date,
    game_id,
    event_sequence,
    period,
    score_home,
    score_away,
    LAG(score_home) OVER (PARTITION BY game_id ORDER BY event_sequence) as prev_home_score,
    LAG(score_away) OVER (PARTITION BY game_id ORDER BY event_sequence) as prev_away_score
  FROM `nba-props-platform.nba_raw.nbac_play_by_play`
  WHERE game_date >= '2024-01-01'
),

score_issues AS (
  SELECT 
    game_date,
    game_id,
    event_sequence,
    period,
    score_home,
    score_away,
    prev_home_score,
    prev_away_score,
    CASE 
      WHEN score_home < prev_home_score THEN '🔴 Home score decreased'
      WHEN score_away < prev_away_score THEN '🔴 Away score decreased'
      WHEN (score_home - prev_home_score) > 3 THEN '⚠️ Home score jumped >3'
      WHEN (score_away - prev_away_score) > 3 THEN '⚠️ Away score jumped >3'
      ELSE NULL
    END as issue
  FROM score_progression
  WHERE prev_home_score IS NOT NULL
),

final_scores AS (
  SELECT 
    p.game_date,
    p.game_id,
    p.home_team_abbr,
    p.away_team_abbr,
    MAX(p.score_home) as pbp_final_home,
    MAX(p.score_away) as pbp_final_away,
    b.home_team_score as box_final_home,
    b.away_team_score as box_final_away
  FROM `nba-props-platform.nba_raw.nbac_play_by_play` p
  LEFT JOIN `nba-props-platform.nba_raw.bdl_player_boxscores` b
    ON p.game_id = b.game_id
    AND p.game_date = b.game_date
  WHERE p.game_date >= '2024-01-01'
  GROUP BY p.game_date, p.game_id, p.home_team_abbr, p.away_team_abbr, 
           b.home_team_score, b.away_team_score
)

-- Report score progression issues
SELECT 
  'SCORE ANOMALIES' as report_type,
  game_date,
  game_id,
  event_sequence,
  period,
  score_home,
  score_away,
  issue
FROM score_issues
WHERE issue IS NOT NULL

UNION ALL

-- Report final score mismatches
SELECT 
  'FINAL SCORE VALIDATION' as report_type,
  game_date,
  game_id,
  NULL as event_sequence,
  NULL as period,
  pbp_final_home as score_home,
  pbp_final_away as score_away,
  CASE 
    WHEN box_final_home IS NULL THEN '⚪ No box score to compare'
    WHEN pbp_final_home != box_final_home OR pbp_final_away != box_final_away 
    THEN '🔴 CRITICAL: Final scores do not match box scores'
    ELSE '✅ Final scores match'
  END as issue
FROM final_scores

ORDER BY report_type, game_date DESC, event_sequence;
