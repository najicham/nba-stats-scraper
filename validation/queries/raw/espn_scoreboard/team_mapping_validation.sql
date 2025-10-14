-- ============================================================================
-- File: validation/queries/raw/espn_scoreboard/team_mapping_validation.sql
-- Purpose: Validate ESPN team abbreviation mapping to NBA standard codes
-- Usage: Verify processor team mapping logic and detect unmapped codes
-- ============================================================================
-- Expected Results:
--   - All mappings: GS→GSW, NY→NYK, SA→SAS, NO→NOP, UTAH→UTA, WSH→WAS
--   - Flag unknown codes: CHK (2), SHQ (1) - investigation needed
--   - EAST (1) = All-Star game - should be filtered by processor
-- ============================================================================

WITH 
-- Home team mappings
home_mappings AS (
  SELECT 
    home_team_espn_abbr as espn_code,
    home_team_abbr as nba_code,
    COUNT(*) as occurrences,
    MIN(game_date) as first_seen,
    MAX(game_date) as last_seen
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= '2021-10-19'
  GROUP BY espn_code, nba_code
),

-- Away team mappings
away_mappings AS (
  SELECT 
    away_team_espn_abbr as espn_code,
    away_team_abbr as nba_code,
    COUNT(*) as occurrences,
    MIN(game_date) as first_seen,
    MAX(game_date) as last_seen
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= '2021-10-19'
  GROUP BY espn_code, nba_code
),

-- Combine both (total occurrences)
all_mappings AS (
  SELECT 
    espn_code,
    nba_code,
    SUM(occurrences) as total_occurrences,
    MIN(first_seen) as first_seen,
    MAX(last_seen) as last_seen
  FROM (
    SELECT * FROM home_mappings
    UNION ALL
    SELECT * FROM away_mappings
  )
  GROUP BY espn_code, nba_code
),

-- Classification
classified_mappings AS (
  SELECT 
    *,
    CASE
      -- Known standard mappings
      WHEN espn_code = nba_code THEN 'DIRECT'
      WHEN espn_code = 'GS' AND nba_code = 'GSW' THEN 'MAPPED'
      WHEN espn_code = 'NY' AND nba_code = 'NYK' THEN 'MAPPED'
      WHEN espn_code = 'SA' AND nba_code = 'SAS' THEN 'MAPPED'
      WHEN espn_code = 'NO' AND nba_code = 'NOP' THEN 'MAPPED'
      WHEN espn_code = 'UTAH' AND nba_code = 'UTA' THEN 'MAPPED'
      WHEN espn_code = 'WSH' AND nba_code = 'WAS' THEN 'MAPPED'
      
      -- Special events
      WHEN espn_code = 'EAST' OR espn_code = 'WEST' THEN 'ALL_STAR'
      
      -- Unknown/problematic codes
      WHEN espn_code IN ('CHK', 'SHQ') THEN 'UNKNOWN'
      
      -- Anything else is unexpected
      ELSE 'UNEXPECTED'
    END as mapping_type,
    CASE
      WHEN espn_code IN ('CHK', 'SHQ') THEN '🔴 Unknown code'
      WHEN espn_code IN ('EAST', 'WEST') THEN '⚪ All-Star event'
      WHEN espn_code = 'GS' AND nba_code != 'GSW' THEN '🔴 Wrong mapping'
      WHEN espn_code = 'NY' AND nba_code != 'NYK' THEN '🔴 Wrong mapping'
      WHEN espn_code = 'SA' AND nba_code != 'SAS' THEN '🔴 Wrong mapping'
      WHEN espn_code = 'NO' AND nba_code != 'NOP' THEN '🔴 Wrong mapping'
      WHEN espn_code = 'UTAH' AND nba_code != 'UTA' THEN '🔴 Wrong mapping'
      WHEN espn_code = 'WSH' AND nba_code != 'WAS' THEN '🔴 Wrong mapping'
      ELSE '✅ Valid'
    END as validation_status
  FROM all_mappings
)

-- Output: Combined results with proper BigQuery syntax
(
  SELECT 
    '📊 MAPPING SUMMARY' as section,
    mapping_type as col1,
    CAST(COUNT(*) AS STRING) as col2,
    CAST(SUM(total_occurrences) AS STRING) as col3,
    STRING_AGG(DISTINCT espn_code ORDER BY espn_code LIMIT 10) as col4,
    CASE
      WHEN mapping_type = 'UNKNOWN' THEN '🔴 Investigate'
      WHEN mapping_type = 'ALL_STAR' THEN '⚪ Filter in processor'
      WHEN mapping_type = 'UNEXPECTED' THEN '🔴 New pattern'
      ELSE '✅ Expected'
    END as status,
    CASE mapping_type
      WHEN 'UNKNOWN' THEN 1
      WHEN 'UNEXPECTED' THEN 2
      WHEN 'ALL_STAR' THEN 3
      WHEN 'MAPPED' THEN 4
      ELSE 5
    END as sort_order
  FROM classified_mappings
  GROUP BY mapping_type

  UNION ALL

  -- Output: Detailed mappings (all records)
  SELECT 
    '📋 ALL MAPPINGS' as section,
    espn_code as col1,
    nba_code as col2,
    CAST(total_occurrences AS STRING) as col3,
    CONCAT(first_seen, ' → ', last_seen) as col4,
    validation_status as status,
    CASE validation_status
      WHEN '🔴 Unknown code' THEN 10
      WHEN '🔴 Wrong mapping' THEN 11
      ELSE 12
    END as sort_order
  FROM classified_mappings

  UNION ALL

  -- Output: Problem cases (for investigation)
  SELECT 
    '🔴 INVESTIGATE THESE' as section,
    game_id as col1,
    CAST(game_date AS STRING) as col2,
    CONCAT(away_team_espn_abbr, ' @ ', home_team_espn_abbr) as col3,
    CONCAT(away_team_abbr, ' @ ', home_team_abbr) as col4,
    CONCAT(
      CASE WHEN home_team_espn_abbr IN ('CHK', 'SHQ', 'EAST', 'WEST') THEN '🔴 Home' ELSE '' END,
      ' ',
      CASE WHEN away_team_espn_abbr IN ('CHK', 'SHQ', 'EAST', 'WEST') THEN '🔴 Away' ELSE '' END
    ) as status,
    20 as sort_order
  FROM `nba-props-platform.nba_raw.espn_scoreboard`
  WHERE game_date >= '2021-10-19'  -- REQUIRED: Partition filter
    AND (home_team_espn_abbr IN ('CHK', 'SHQ', 'EAST', 'WEST')
         OR away_team_espn_abbr IN ('CHK', 'SHQ', 'EAST', 'WEST'))

  ORDER BY sort_order, section, col1
);