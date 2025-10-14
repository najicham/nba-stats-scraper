-- ============================================================================
-- File: validation/queries/raw/nbac_player_list/player_distribution_check.sql
-- Purpose: Analyze player distribution by position, status, and other dimensions
-- Usage: Run weekly to understand roster composition and detect anomalies
-- ============================================================================
-- Instructions:
--   1. Check position distribution is reasonable (not all PG, etc.)
--   2. Verify draft year distribution looks normal
--   3. Ensure roster_status categories are as expected
-- ============================================================================
-- Expected Results:
--   - Position distribution: Each position ~15-20% of roster
--   - Draft years: Spread across multiple years
--   - Roster status: Mostly "active", some "inactive"
-- ============================================================================

WITH
-- Position distribution
position_distribution AS (
  SELECT
    COALESCE(position, 'Unknown') as position,
    COUNT(*) as player_count,
    COUNT(CASE WHEN is_active = TRUE THEN 1 END) as active_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct_of_roster
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
  GROUP BY position
  ORDER BY player_count DESC
),

-- Roster status distribution
status_distribution AS (
  SELECT
    COALESCE(roster_status, 'Unknown') as roster_status,
    COUNT(*) as player_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct_of_roster
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
  GROUP BY roster_status
  ORDER BY player_count DESC
),

-- Draft year distribution (top 10)
draft_year_distribution AS (
  SELECT
    COALESCE(CAST(draft_year AS STRING), 'Undrafted') as draft_year,
    COUNT(*) as player_count,
    ROUND(AVG(years_pro), 1) as avg_years_pro
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
  GROUP BY draft_year
  ORDER BY player_count DESC
  LIMIT 10
),

-- Experience level distribution
experience_distribution AS (
  SELECT
    CASE
      WHEN years_pro = 0 THEN 'Rookies (0 years)'
      WHEN years_pro BETWEEN 1 AND 3 THEN 'Young (1-3 years)'
      WHEN years_pro BETWEEN 4 AND 7 THEN 'Mid (4-7 years)'
      WHEN years_pro BETWEEN 8 AND 12 THEN 'Veteran (8-12 years)'
      WHEN years_pro >= 13 THEN 'Senior (13+ years)'
      ELSE 'Unknown'
    END as experience_level,
    COUNT(*) as player_count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 1) as pct_of_roster
  FROM `nba-props-platform.nba_raw.nbac_player_list_current`
  WHERE season_year >= 2024
  GROUP BY experience_level
  ORDER BY 
    CASE experience_level
      WHEN 'Rookies (0 years)' THEN 1
      WHEN 'Young (1-3 years)' THEN 2
      WHEN 'Mid (4-7 years)' THEN 3
      WHEN 'Veteran (8-12 years)' THEN 4
      WHEN 'Senior (13+ years)' THEN 5
      ELSE 6
    END
)

-- Output: Distribution analysis
SELECT
  '=== POSITION DISTRIBUTION ===' as section,
  '' as category,
  '' as count,
  '' as percentage

UNION ALL

SELECT
  position as section,
  '' as category,
  CAST(player_count AS STRING) as count,
  CONCAT(CAST(pct_of_roster AS STRING), '%') as percentage
FROM position_distribution

UNION ALL

SELECT
  'Active Players' as section,
  position as category,
  CAST(active_count AS STRING) as count,
  '' as percentage
FROM position_distribution

UNION ALL

SELECT
  '' as section,
  '' as category,
  '' as count,
  '' as percentage

UNION ALL

SELECT
  '=== ROSTER STATUS ===' as section,
  '' as category,
  '' as count,
  '' as percentage

UNION ALL

SELECT
  roster_status as section,
  '' as category,
  CAST(player_count AS STRING) as count,
  CONCAT(CAST(pct_of_roster AS STRING), '%') as percentage
FROM status_distribution

UNION ALL

SELECT
  '' as section,
  '' as category,
  '' as count,
  '' as percentage

UNION ALL

SELECT
  '=== EXPERIENCE DISTRIBUTION ===' as section,
  '' as category,
  '' as count,
  '' as percentage

UNION ALL

SELECT
  experience_level as section,
  '' as category,
  CAST(player_count AS STRING) as count,
  CONCAT(CAST(pct_of_roster AS STRING), '%') as percentage
FROM experience_distribution

UNION ALL

SELECT
  '' as section,
  '' as category,
  '' as count,
  '' as percentage

UNION ALL

SELECT
  '=== TOP DRAFT YEARS ===' as section,
  '' as category,
  '' as count,
  '' as percentage

UNION ALL

SELECT
  draft_year as section,
  CONCAT('Avg exp: ', CAST(avg_years_pro AS STRING), ' yrs') as category,
  CAST(player_count AS STRING) as count,
  '' as percentage
FROM draft_year_distribution;