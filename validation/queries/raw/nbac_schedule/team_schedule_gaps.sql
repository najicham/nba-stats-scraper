-- ============================================================================
-- File: validation/queries/raw/nbac_schedule/team_schedule_gaps.sql
-- Purpose: Detect suspicious gaps in team schedules (missing games detection)
-- Usage: Run when anomalies suspected or as part of weekly validation
-- Status: FIXED - Corrected GROUP BY aggregation error
-- ============================================================================

WITH
-- Get all regular season games (playoff scheduling is naturally uneven)
regular_season_games AS (
  SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    home_team_name,
    away_team_name
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-04-13'  -- UPDATE: Regular season only
    AND is_regular_season = TRUE
    AND is_playoffs = FALSE
    AND game_date >= '2024-10-22'  -- Partition filter
),

-- Expand to team-game combinations
team_games AS (
  SELECT
    game_date,
    home_team_tricode as team,
    home_team_name as team_name,
    game_id,
    CONCAT(away_team_tricode, ' vs ', home_team_tricode, ' (home)') as game_description
  FROM regular_season_games
  
  UNION ALL
  
  SELECT
    game_date,
    away_team_tricode as team,
    away_team_name as team_name,
    game_id,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode, ' (away)') as game_description
  FROM regular_season_games
),

-- Calculate gaps between games for each team
team_gaps AS (
  SELECT
    team,
    team_name,  -- Keep this here for later use
    game_date,
    game_description,
    LAG(game_date) OVER (PARTITION BY team ORDER BY game_date) as previous_game_date,
    DATE_DIFF(
      game_date, 
      LAG(game_date) OVER (PARTITION BY team ORDER BY game_date), 
      DAY
    ) as days_since_last_game
  FROM team_games
),

-- Categorize gaps by severity
gap_analysis AS (
  SELECT
    team,
    team_name,
    game_date,
    previous_game_date,
    days_since_last_game,
    game_description,
    CASE
      WHEN days_since_last_game IS NULL THEN '⚪ First game of season'
      WHEN days_since_last_game <= 2 THEN '✅ Normal (1-2 days)'
      WHEN days_since_last_game = 3 THEN '✅ Acceptable (3 days)'
      WHEN days_since_last_game BETWEEN 4 AND 6 THEN '🟡 Longer than usual (4-6 days)'
      WHEN days_since_last_game BETWEEN 7 AND 10 THEN '🟠 Suspicious gap (7-10 days)'
      ELSE '🔴 CRITICAL: Very long gap (>10 days)'
    END as gap_status
  FROM team_gaps
  WHERE days_since_last_game IS NOT NULL
),

-- Find teams with most concerning gaps - FIXED aggregation
team_gap_summary AS (
  SELECT
    team,
    ANY_VALUE(team_name) as team_name,  -- FIXED: Use ANY_VALUE for non-grouped column
    COUNT(*) as total_games,
    COUNTIF(days_since_last_game > 6) as suspicious_gaps,
    COUNTIF(days_since_last_game > 10) as critical_gaps,
    MAX(days_since_last_game) as longest_gap,
    ROUND(AVG(days_since_last_game), 1) as avg_gap_days
  FROM gap_analysis
  GROUP BY team
),

-- Add overall status calculation
team_status AS (
  SELECT
    *,
    CASE
      WHEN critical_gaps > 0 THEN '🔴 CRITICAL: Has 10+ day gaps'
      WHEN suspicious_gaps > 2 THEN '🟠 WARNING: Multiple 7+ day gaps'
      WHEN longest_gap > 6 THEN '🟡 INFO: One 7+ day gap'
      ELSE '✅ Normal'
    END as overall_status
  FROM team_gap_summary
),

-- Known acceptable gaps (All-Star break, etc.)
known_breaks AS (
  SELECT date FROM UNNEST([
    -- All-Star Break 2025 (teams' last game Feb 12-13, resume Feb 19-21)
    DATE('2025-02-12'),
    DATE('2025-02-13'),
    DATE('2025-02-14'),
    DATE('2025-02-15'),
    DATE('2025-02-16'),
    DATE('2025-02-17'),
    DATE('2025-02-18'),
    DATE('2025-02-19'),
    DATE('2025-02-20'),
    DATE('2025-02-21')
  ]) AS date
)

-- Output 1: Team summary (teams with issues)
SELECT
  '=== TEAMS WITH SUSPICIOUS GAPS ===' as section,
  '' as team,
  '' as total_games,
  '' as suspicious_gaps,
  '' as longest_gap,
  '' as status,
  0 as sort_order,
  0 as sub_sort

UNION ALL

SELECT
  team as section,
  team_name as team,
  CAST(total_games AS STRING) as total_games,
  CAST(suspicious_gaps AS STRING) as suspicious_gaps,
  CONCAT(CAST(longest_gap AS STRING), ' days') as longest_gap,
  overall_status as status,
  CASE overall_status
    WHEN '🔴 CRITICAL: Has 10+ day gaps' THEN 1
    WHEN '🟠 WARNING: Multiple 7+ day gaps' THEN 2
    WHEN '🟡 INFO: One 7+ day gap' THEN 3
    ELSE 4
  END as sort_order,
  longest_gap as sub_sort
FROM team_status
WHERE overall_status != '✅ Normal'

UNION ALL

SELECT
  '' as section,
  '' as team,
  '' as total_games,
  '' as suspicious_gaps,
  '' as longest_gap,
  '' as status,
  100 as sort_order,
  0 as sub_sort

UNION ALL

-- Output 2: Specific gap details (only suspicious gaps)
SELECT
  '=== SPECIFIC GAPS (7+ DAYS) ===' as section,
  '' as team,
  '' as total_games,
  '' as suspicious_gaps,
  '' as longest_gap,
  '' as status,
  200 as sort_order,
  0 as sub_sort

UNION ALL

SELECT
  CONCAT(team, ' - ', team_name) as section,
  CONCAT(CAST(previous_game_date AS STRING), ' → ', CAST(game_date AS STRING)) as team,
  CONCAT(CAST(days_since_last_game AS STRING), ' days') as total_games,
  game_description as suspicious_gaps,
  '' as longest_gap,
  gap_status as status,
  300 as sort_order,
  days_since_last_game as sub_sort
FROM gap_analysis
WHERE days_since_last_game >= 7
  -- Exclude known breaks
  AND game_date NOT IN (SELECT date FROM known_breaks)
  AND previous_game_date NOT IN (SELECT date FROM known_breaks)

UNION ALL

SELECT
  '' as section,
  '' as team,
  '' as total_games,
  '' as suspicious_gaps,
  '' as longest_gap,
  '' as status,
  400 as sort_order,
  0 as sub_sort

UNION ALL

-- Output 3: All-Star break detection
SELECT
  '=== KNOWN BREAKS ===' as section,
  '' as team,
  '' as total_games,
  '' as suspicious_gaps,
  '' as longest_gap,
  '' as status,
  500 as sort_order,
  0 as sub_sort

UNION ALL

SELECT
  'All-Star Break 2025' as section,
  'Feb 14-17' as team,
  CAST(COUNT(DISTINCT ga.team) AS STRING) as total_games,
  'teams affected' as suspicious_gaps,
  '' as longest_gap,
  '✅ Expected gap' as status,
  600 as sort_order,
  0 as sub_sort
FROM gap_analysis ga
WHERE game_date IN (SELECT date FROM known_breaks)
   OR previous_game_date IN (SELECT date FROM known_breaks)
   
ORDER BY sort_order, sub_sort DESC;