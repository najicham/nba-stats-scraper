-- ============================================================================
-- File: validation/queries/raw/nbac_gamebook/name_resolution_quality.sql
-- Purpose: Analyze name resolution system performance and identify issues
-- Usage: Run after backfills or to monitor resolution quality
-- ============================================================================
-- Expected Results:
--   - Overall resolution rate ≥98.5% (target: 98.92%)
--   - Resolution rates consistent across seasons
--   - Few games requiring manual review
--   - Low confidence scores flagged for review
-- ============================================================================

WITH
resolution_by_season AS (
  SELECT
    CASE
      WHEN game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season,
    COUNT(*) as total_inactive,
    COUNT(CASE WHEN name_resolution_status = 'resolved' THEN 1 END) as resolved,
    COUNT(CASE WHEN name_resolution_status = 'not_found' THEN 1 END) as not_found,
    COUNT(CASE WHEN name_resolution_status = 'multiple_matches' THEN 1 END) as multiple_matches,
    COUNT(CASE WHEN name_resolution_confidence < 0.8 THEN 1 END) as low_confidence,
    COUNT(CASE WHEN requires_manual_review = TRUE THEN 1 END) as needs_review,
    ROUND(SAFE_DIVIDE(
      COUNT(CASE WHEN name_resolution_status = 'resolved' THEN 1 END),
      COUNT(*)
    ) * 100, 2) as resolution_rate_pct
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE player_status = 'inactive'
    AND game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY season
),

resolution_by_method AS (
  SELECT
    name_resolution_method,
    COUNT(*) as usage_count,
    ROUND(SAFE_DIVIDE(COUNT(*), (
      SELECT COUNT(*) 
      FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
      WHERE player_status = 'inactive'
        AND name_resolution_status = 'resolved'
        AND game_date BETWEEN '2021-10-19' AND '2025-06-20'
    )) * 100, 2) as percentage,
    AVG(name_resolution_confidence) as avg_confidence
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE player_status = 'inactive'
    AND name_resolution_status = 'resolved'
    AND game_date BETWEEN '2021-10-19' AND '2025-06-20'
  GROUP BY name_resolution_method
  ORDER BY usage_count DESC
),

problem_cases AS (
  SELECT
    game_date,
    game_id,
    player_name_original,
    team_abbr,
    name_resolution_status,
    name_resolution_confidence,
    name_resolution_method,
    dnp_reason
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE player_status = 'inactive'
    AND (
      name_resolution_status IN ('not_found', 'multiple_matches')
      OR name_resolution_confidence < 0.7
      OR requires_manual_review = TRUE
    )
    AND game_date BETWEEN '2021-10-19' AND '2025-06-20'
  ORDER BY game_date DESC, name_resolution_confidence ASC
  LIMIT 100
)

-- Season-by-season resolution rates
SELECT
  'SEASON RESOLUTION' as report_type,
  season,
  CAST(total_inactive AS STRING) as total_inactive,
  CAST(resolved AS STRING) as resolved,
  CAST(not_found AS STRING) as not_found,
  CAST(multiple_matches AS STRING) as multiple_matches,
  CAST(low_confidence AS STRING) as low_confidence,
  CONCAT(CAST(resolution_rate_pct AS STRING), '%') as resolution_rate,
  CASE
    WHEN resolution_rate_pct >= 98.9 THEN '✅ Excellent'
    WHEN resolution_rate_pct >= 98.5 THEN '✅ Good'
    WHEN resolution_rate_pct >= 98.0 THEN '⚠️ Acceptable'
    ELSE '🔴 Below Target'
  END as status
FROM resolution_by_season

UNION ALL

-- Resolution method breakdown
SELECT
  'RESOLUTION METHOD' as report_type,
  name_resolution_method as season,
  CAST(usage_count AS STRING) as total_inactive,
  CONCAT(CAST(percentage AS STRING), '%') as resolved,
  CONCAT(CAST(ROUND(avg_confidence * 100, 1) AS STRING), '%') as not_found,
  '' as multiple_matches,
  '' as low_confidence,
  '' as resolution_rate,
  '' as status
FROM resolution_by_method

UNION ALL

-- Problem cases summary
SELECT
  'PROBLEM CASES' as report_type,
  CAST(COUNT(*) AS STRING) as season,
  'See detailed list below' as total_inactive,
  '' as resolved,
  '' as not_found,
  '' as multiple_matches,
  '' as low_confidence,
  '' as resolution_rate,
  '' as status
FROM problem_cases

ORDER BY report_type DESC, season;

-- Optional: To see detailed problem cases, uncomment and run separately:
-- SELECT
--   game_date,
--   player_name_original,
--   team_abbr,
--   name_resolution_status,
--   CONCAT(CAST(ROUND(name_resolution_confidence * 100, 1) AS STRING), '%') as confidence,
--   name_resolution_method,
--   dnp_reason
-- FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
-- WHERE player_status = 'inactive'
--   AND (
--     name_resolution_status IN ('not_found', 'multiple_matches')
--     OR name_resolution_confidence < 0.7
--     OR requires_manual_review = TRUE
--   )
--   AND game_date BETWEEN '2021-10-19' AND '2025-06-20'
-- ORDER BY game_date DESC, name_resolution_confidence ASC
-- LIMIT 100;
