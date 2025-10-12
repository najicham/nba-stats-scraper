-- ============================================================================
-- File: validation/queries/raw/nbac_gamebook/name_resolution_problem_cases.sql
-- Purpose: Detailed list of name resolution problem cases for investigation
-- Usage: Run to see specific players that failed resolution
-- ============================================================================
-- Expected Results:
--   - List of inactive players with resolution issues
--   - Ordered by confidence score (lowest first)
--   - Use this to identify patterns and manual fixes needed
-- ============================================================================

SELECT
  game_date,
  game_id,
  player_name_original,
  player_name as resolved_name,
  team_abbr,
  name_resolution_status,
  name_resolution_confidence,
  name_resolution_method,
  br_team_abbr_used,
  dnp_reason,
  CASE
    WHEN name_resolution_status = 'not_found' THEN 'Player not in roster databases'
    WHEN name_resolution_status = 'multiple_matches' THEN 'Multiple players with same last name'
    WHEN name_resolution_confidence < 0.7 THEN 'Low confidence match'
    WHEN requires_manual_review = TRUE THEN 'Flagged for manual review'
    ELSE 'Other issue'
  END as issue_description,
  -- Context for investigation
  CONCAT(
    'Game: ', 
    CAST(game_date AS STRING), 
    ' | Team: ', 
    team_abbr,
    ' | DNP Reason: ',
    COALESCE(dnp_reason, 'None')
  ) as investigation_context
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE player_status = 'inactive'
  AND (
    name_resolution_status IN ('not_found', 'multiple_matches')
    OR name_resolution_confidence < 0.7
    OR requires_manual_review = TRUE
  )
  AND game_date BETWEEN '2021-10-19' AND '2025-06-20'
ORDER BY 
  name_resolution_confidence ASC NULLS FIRST,
  game_date DESC
LIMIT 200;