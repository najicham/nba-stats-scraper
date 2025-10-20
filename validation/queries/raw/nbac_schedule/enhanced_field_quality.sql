-- ============================================================================
-- File: validation/queries/raw/nbac_schedule/enhanced_field_quality.sql
-- Purpose: Validate 18 enhanced analytical fields are populated correctly
-- Status: FIXED - Corrected variable name inconsistencies
-- ============================================================================

WITH
-- Get all games in date range (excluding special event games)
all_games AS (
  SELECT
    game_date,
    game_id,
    home_team_tricode,
    away_team_tricode,
    is_regular_season,
    is_playoffs,
    -- Broadcaster Context (5 fields)
    is_primetime,
    has_national_tv,
    primary_network,
    traditional_networks,
    streaming_platforms,
    -- Game Classification (7 fields)
    playoff_round,
    is_all_star,
    is_emirates_cup,
    is_christmas,
    is_mlk_day,
    -- Scheduling Context (3 fields)
    day_of_week,
    is_weekend,
    time_slot,
    -- Venue Context (3 fields)
    neutral_site_flag,
    international_game,
    arena_timezone
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_date BETWEEN '2024-10-22' AND '2025-06-20'  -- UPDATE: Current season
    AND game_date >= '2024-10-22'  -- Partition filter
    -- Exclude special event games (All-Star, exhibitions)
    AND home_team_tricode NOT IN ('BAR', 'DRT', 'IAH', 'LBN', 'PAY', 'WOR', 
                                   'DRN', 'GNS', 'JAS', 'JKM', 'PAU', 
                                   'DLF', 'EST')
    AND away_team_tricode NOT IN ('BAR', 'DRT', 'IAH', 'LBN', 'PAY', 'WOR',
                                   'DRN', 'GNS', 'JAS', 'JKM', 'PAU',
                                   'DLF', 'EST')
),

-- Calculate NULL counts for each enhanced field
null_analysis AS (
  SELECT
    COUNT(*) as total_games,
    -- Broadcaster Context
    COUNT(CASE WHEN is_primetime IS NULL THEN 1 END) as null_primetime,
    COUNT(CASE WHEN has_national_tv IS NULL THEN 1 END) as null_national_tv,
    COUNT(CASE WHEN primary_network IS NULL THEN 1 END) as null_primary_network,
    COUNT(CASE WHEN traditional_networks IS NULL THEN 1 END) as null_traditional_networks,
    COUNT(CASE WHEN streaming_platforms IS NULL THEN 1 END) as null_streaming_platforms,
    -- Game Classification
    COUNT(CASE WHEN is_regular_season IS NULL THEN 1 END) as null_regular_season,
    COUNT(CASE WHEN is_playoffs IS NULL THEN 1 END) as null_playoffs,
    COUNT(CASE WHEN is_playoffs = TRUE AND playoff_round IS NULL THEN 1 END) as null_playoff_round,
    COUNT(CASE WHEN is_all_star IS NULL THEN 1 END) as null_all_star,
    COUNT(CASE WHEN is_emirates_cup IS NULL THEN 1 END) as null_emirates_cup,
    COUNT(CASE WHEN is_christmas IS NULL THEN 1 END) as null_christmas,
    COUNT(CASE WHEN is_mlk_day IS NULL THEN 1 END) as null_mlk_day,
    -- Scheduling Context
    COUNT(CASE WHEN day_of_week IS NULL THEN 1 END) as null_day_of_week,
    COUNT(CASE WHEN is_weekend IS NULL THEN 1 END) as null_weekend,
    COUNT(CASE WHEN time_slot IS NULL THEN 1 END) as null_time_slot,
    -- Venue Context
    COUNT(CASE WHEN neutral_site_flag IS NULL THEN 1 END) as null_neutral_site,
    COUNT(CASE WHEN international_game IS NULL THEN 1 END) as null_international_game,
    COUNT(CASE WHEN arena_timezone IS NULL THEN 1 END) as null_arena_timezone
  FROM all_games
),

-- Calculate TRUE counts for special events
special_events AS (
  SELECT
    COUNT(CASE WHEN is_primetime = TRUE THEN 1 END) as primetime_games,
    COUNT(CASE WHEN has_national_tv = TRUE THEN 1 END) as national_tv_games,
    COUNT(CASE WHEN is_christmas = TRUE THEN 1 END) as christmas_games,
    COUNT(CASE WHEN is_mlk_day = TRUE THEN 1 END) as mlk_games,
    COUNT(CASE WHEN is_all_star = TRUE THEN 1 END) as all_star_games,
    COUNT(CASE WHEN is_emirates_cup = TRUE THEN 1 END) as emirates_cup_games,
    COUNT(CASE WHEN is_weekend = TRUE THEN 1 END) as weekend_games,
    COUNT(CASE WHEN neutral_site_flag = TRUE THEN 1 END) as neutral_site_games,
    COUNT(CASE WHEN international_game = TRUE THEN 1 END) as international_games
  FROM all_games
),

-- Analyze network distribution
network_distribution AS (
  SELECT
    primary_network,
    COUNT(*) as games,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) as percentage
  FROM all_games
  WHERE primary_network IS NOT NULL
    AND is_regular_season = TRUE
  GROUP BY primary_network
  ORDER BY games DESC
  LIMIT 10
),

-- Validate data quality (FIXED: corrected variable names)
quality_check AS (
  SELECT
    -- Critical fields should have 0 NULLs
    CASE
      WHEN null_primetime = 0 AND null_regular_season = 0 AND null_playoffs = 0
      THEN '✅ All critical fields populated'
      ELSE '🔴 CRITICAL: Missing required fields'
    END as critical_status,
    -- Network fields should be mostly populated
    CASE
      WHEN null_primary_network < total_games * 0.1 THEN '✅ Network data good'
      WHEN null_primary_network < total_games * 0.3 THEN '🟡 Network data incomplete'
      ELSE '🔴 Network data mostly missing'
    END as network_status,
    -- Special events should have reasonable counts
    CASE
      WHEN (SELECT christmas_games FROM special_events) >= 5 THEN '✅ Christmas games found'
      WHEN (SELECT christmas_games FROM special_events) = 0 THEN '🟡 No Christmas games (check date range)'
      ELSE '🟡 Fewer Christmas games than expected'
    END as christmas_status
  FROM null_analysis
)

-- Output 1: NULL count summary
SELECT
  '=== NULL COUNT ANALYSIS ===' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  'Total Games (NBA only)' as section,
  CAST(total_games AS STRING) as field_name,
  '' as null_count,
  '' as percentage,
  '' as status
FROM null_analysis

UNION ALL

SELECT
  '' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  'BROADCASTER CONTEXT' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  '  is_primetime' as section,
  '' as field_name,
  CAST(null_primetime AS STRING) as null_count,
  CONCAT(CAST(ROUND(null_primetime * 100.0 / total_games, 1) AS STRING), '%') as percentage,
  CASE WHEN null_primetime = 0 THEN '✅' ELSE '🔴' END as status
FROM null_analysis

UNION ALL

SELECT
  '  has_national_tv' as section,
  '' as field_name,
  CAST(null_national_tv AS STRING) as null_count,
  CONCAT(CAST(ROUND(null_national_tv * 100.0 / total_games, 1) AS STRING), '%') as percentage,
  CASE WHEN null_national_tv = 0 THEN '✅' ELSE '🔴' END as status
FROM null_analysis

UNION ALL

SELECT
  '  primary_network' as section,
  '' as field_name,
  CAST(null_primary_network AS STRING) as null_count,
  CONCAT(CAST(ROUND(null_primary_network * 100.0 / total_games, 1) AS STRING), '%') as percentage,
  CASE
    WHEN null_primary_network = 0 THEN '✅'
    WHEN null_primary_network < total_games * 0.1 THEN '🟡'
    ELSE '🔴'
  END as status
FROM null_analysis

UNION ALL

SELECT
  '  traditional_networks' as section,
  '' as field_name,
  CAST(null_traditional_networks AS STRING) as null_count,
  CONCAT(CAST(ROUND(null_traditional_networks * 100.0 / total_games, 1) AS STRING), '%') as percentage,
  CASE
    WHEN null_traditional_networks = 0 THEN '✅'
    WHEN null_traditional_networks < total_games * 0.2 THEN '🟡'
    ELSE '🔴'
  END as status
FROM null_analysis

UNION ALL

SELECT
  '  streaming_platforms' as section,
  '' as field_name,
  CAST(null_streaming_platforms AS STRING) as null_count,
  CONCAT(CAST(ROUND(null_streaming_platforms * 100.0 / total_games, 1) AS STRING), '%') as percentage,
  CASE
    WHEN null_streaming_platforms = 0 THEN '✅'
    WHEN null_streaming_platforms < total_games * 0.2 THEN '🟡'
    ELSE '🔴'
  END as status
FROM null_analysis

UNION ALL

SELECT
  '' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  'GAME CLASSIFICATION' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  '  is_regular_season' as section,
  '' as field_name,
  CAST(null_regular_season AS STRING) as null_count,
  CONCAT(CAST(ROUND(null_regular_season * 100.0 / total_games, 1) AS STRING), '%') as percentage,
  CASE WHEN null_regular_season = 0 THEN '✅' ELSE '🔴' END as status
FROM null_analysis

UNION ALL

SELECT
  '  is_playoffs' as section,
  '' as field_name,
  CAST(null_playoffs AS STRING) as null_count,
  CONCAT(CAST(ROUND(null_playoffs * 100.0 / total_games, 1) AS STRING), '%') as percentage,
  CASE WHEN null_playoffs = 0 THEN '✅' ELSE '🔴' END as status
FROM null_analysis

UNION ALL

SELECT
  '' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

-- Output 2: Special events counts
SELECT
  '=== SPECIAL EVENTS ===' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  'Primetime Games' as section,
  CAST(primetime_games AS STRING) as field_name,
  CONCAT(CAST(ROUND(primetime_games * 100.0 / (SELECT total_games FROM null_analysis), 1) AS STRING), '%') as null_count,
  '' as percentage,
  '✅' as status
FROM special_events

UNION ALL

SELECT
  'National TV Games' as section,
  CAST(national_tv_games AS STRING) as field_name,
  CONCAT(CAST(ROUND(national_tv_games * 100.0 / (SELECT total_games FROM null_analysis), 1) AS STRING), '%') as null_count,
  '' as percentage,
  '✅' as status
FROM special_events

UNION ALL

SELECT
  'Christmas Games' as section,
  CAST(christmas_games AS STRING) as field_name,
  '' as null_count,
  '' as percentage,
  CASE WHEN christmas_games >= 5 THEN '✅' ELSE '🟡' END as status
FROM special_events

UNION ALL

SELECT
  'MLK Day Games' as section,
  CAST(mlk_games AS STRING) as field_name,
  '' as null_count,
  '' as percentage,
  CASE WHEN mlk_games >= 8 THEN '✅' ELSE '🟡' END as status
FROM special_events

UNION ALL

SELECT
  'Weekend Games' as section,
  CAST(weekend_games AS STRING) as field_name,
  CONCAT(CAST(ROUND(weekend_games * 100.0 / (SELECT total_games FROM null_analysis), 1) AS STRING), '%') as null_count,
  '' as percentage,
  '' as status
FROM special_events

UNION ALL

SELECT
  '' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

-- Output 3: Network distribution
SELECT
  '=== NETWORK DISTRIBUTION ===' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  primary_network as section,
  CAST(games AS STRING) as field_name,
  CONCAT(CAST(percentage AS STRING), '%') as null_count,
  '' as percentage,
  '' as status
FROM network_distribution

UNION ALL

SELECT
  '' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

-- Output 4: Overall status
SELECT
  '=== OVERALL STATUS ===' as section,
  '' as field_name,
  '' as null_count,
  '' as percentage,
  '' as status

UNION ALL

SELECT
  'Critical Fields' as section,
  critical_status as field_name,
  '' as null_count,
  '' as percentage,
  '' as status
FROM quality_check

UNION ALL

SELECT
  'Network Data' as section,
  network_status as field_name,
  '' as null_count,
  '' as percentage,
  '' as status
FROM quality_check

UNION ALL

SELECT
  'Christmas Games' as section,
  christmas_status as field_name,
  '' as null_count,
  '' as percentage,
  '' as status
FROM quality_check;
