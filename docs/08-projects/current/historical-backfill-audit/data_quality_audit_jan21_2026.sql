-- Data Quality Audit for January 21, 2026
-- Comprehensive analysis of data quality issues and anomalies

-- ============================================================================
-- 1. DUPLICATE RECORDS IN RAW TABLES (PHASE 2)
-- ============================================================================

-- 1.1: Check for duplicate games in balldontlie_games
SELECT
  'balldontlie_games - Duplicate game_ids' as check_name,
  game_id,
  game_date,
  COUNT(*) as duplicate_count,
  STRING_AGG(DISTINCT CAST(id AS STRING) ORDER BY id) as record_ids
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`
GROUP BY game_id, game_date
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, game_date DESC
LIMIT 100;

-- 1.2: Check for duplicate box scores in balldontlie_box_scores
SELECT
  'balldontlie_box_scores - Duplicate player-game combinations' as check_name,
  game_id,
  player_id,
  COUNT(*) as duplicate_count,
  STRING_AGG(DISTINCT CAST(id AS STRING) ORDER BY id) as record_ids
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`
GROUP BY game_id, player_id
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 100;

-- 1.3: Check for duplicate player records
SELECT
  'balldontlie_players - Duplicate player_ids' as check_name,
  player_id,
  COUNT(*) as duplicate_count,
  STRING_AGG(DISTINCT first_name || ' ' || last_name ORDER BY id) as player_names,
  STRING_AGG(DISTINCT CAST(id AS STRING) ORDER BY id) as record_ids
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_players`
GROUP BY player_id
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 100;

-- 1.4: Check for duplicate team records
SELECT
  'balldontlie_teams - Duplicate team_ids' as check_name,
  team_id,
  COUNT(*) as duplicate_count,
  STRING_AGG(DISTINCT full_name ORDER BY id) as team_names,
  STRING_AGG(DISTINCT CAST(id AS STRING) ORDER BY id) as record_ids
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_teams`
GROUP BY team_id
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 100;

-- ============================================================================
-- 2. MISSING OR NULL CRITICAL FIELDS
-- ============================================================================

-- 2.1: Check for null critical fields in balldontlie_games
SELECT
  'balldontlie_games - Null Critical Fields' as check_name,
  COUNT(*) as total_records,
  COUNTIF(game_id IS NULL) as null_game_id,
  COUNTIF(game_date IS NULL) as null_game_date,
  COUNTIF(home_team_id IS NULL) as null_home_team_id,
  COUNTIF(visitor_team_id IS NULL) as null_visitor_team_id,
  COUNTIF(home_team_score IS NULL) as null_home_score,
  COUNTIF(visitor_team_score IS NULL) as null_visitor_score,
  COUNTIF(status IS NULL) as null_status
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`;

-- 2.2: Check for null critical fields in balldontlie_box_scores
SELECT
  'balldontlie_box_scores - Null Critical Fields' as check_name,
  COUNT(*) as total_records,
  COUNTIF(game_id IS NULL) as null_game_id,
  COUNTIF(player_id IS NULL) as null_player_id,
  COUNTIF(team_id IS NULL) as null_team_id,
  COUNTIF(min IS NULL) as null_minutes,
  COUNTIF(pts IS NULL) as null_points
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`;

-- 2.3: Check for games with all null stats (incomplete data)
SELECT
  'balldontlie_box_scores - Games with All Null Stats' as check_name,
  game_id,
  COUNT(*) as player_count,
  COUNTIF(pts IS NULL AND reb IS NULL AND ast IS NULL) as null_stat_count
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`
GROUP BY game_id
HAVING null_stat_count = player_count
ORDER BY game_id DESC
LIMIT 100;

-- 2.4: Check for null critical fields in analytics tables
SELECT
  'game_analytics - Null Critical Fields' as check_name,
  COUNT(*) as total_records,
  COUNTIF(game_id IS NULL) as null_game_id,
  COUNTIF(game_date IS NULL) as null_game_date,
  COUNTIF(season IS NULL) as null_season,
  COUNTIF(home_team_id IS NULL) as null_home_team_id,
  COUNTIF(away_team_id IS NULL) as null_away_team_id
FROM `nba_pipeline_prod.nba_analytics.game_analytics`;

-- ============================================================================
-- 3. ROW COUNT COMPARISONS BETWEEN RELATED TABLES
-- ============================================================================

-- 3.1: Compare game counts across phases
WITH phase_counts AS (
  SELECT
    'Phase 2: balldontlie_games' as table_name,
    COUNT(DISTINCT game_id) as game_count,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date
  FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`

  UNION ALL

  SELECT
    'Phase 3: game_analytics' as table_name,
    COUNT(DISTINCT game_id) as game_count,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date
  FROM `nba_pipeline_prod.nba_analytics.game_analytics`

  UNION ALL

  SELECT
    'Phase 4: precomputed_team_stats' as table_name,
    COUNT(DISTINCT game_id) as game_count,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date
  FROM `nba_pipeline_prod.nba_precompute.precomputed_team_stats`
)
SELECT
  table_name,
  game_count,
  earliest_date,
  latest_date,
  game_count - LAG(game_count) OVER (ORDER BY table_name) as diff_from_previous
FROM phase_counts
ORDER BY table_name;

-- 3.2: Compare box score counts between raw and analytics
SELECT
  'Box Score Count Comparison' as check_name,
  raw.total_raw_box_scores,
  analytics.total_analytics_box_scores,
  raw.total_raw_box_scores - analytics.total_analytics_box_scores as difference
FROM (
  SELECT COUNT(*) as total_raw_box_scores
  FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`
) raw
CROSS JOIN (
  SELECT COUNT(*) as total_analytics_box_scores
  FROM `nba_pipeline_prod.nba_analytics.player_game_stats`
) analytics;

-- 3.3: Games with mismatched player counts
WITH raw_counts AS (
  SELECT game_id, COUNT(*) as raw_player_count
  FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`
  GROUP BY game_id
),
analytics_counts AS (
  SELECT game_id, COUNT(*) as analytics_player_count
  FROM `nba_pipeline_prod.nba_analytics.player_game_stats`
  GROUP BY game_id
)
SELECT
  'Games with Mismatched Player Counts' as check_name,
  COALESCE(r.game_id, a.game_id) as game_id,
  COALESCE(r.raw_player_count, 0) as raw_player_count,
  COALESCE(a.analytics_player_count, 0) as analytics_player_count,
  COALESCE(r.raw_player_count, 0) - COALESCE(a.analytics_player_count, 0) as difference
FROM raw_counts r
FULL OUTER JOIN analytics_counts a ON r.game_id = a.game_id
WHERE COALESCE(r.raw_player_count, 0) != COALESCE(a.analytics_player_count, 0)
ORDER BY ABS(COALESCE(r.raw_player_count, 0) - COALESCE(a.analytics_player_count, 0)) DESC
LIMIT 100;

-- ============================================================================
-- 4. DATA FRESHNESS ISSUES
-- ============================================================================

-- 4.1: Check last update timestamps across all phases
SELECT
  'Data Freshness Summary' as check_name,
  'Phase 2: Raw Data' as phase,
  MAX(updated_at) as latest_update,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(updated_at), HOUR) as hours_since_update,
  MAX(game_date) as latest_game_date
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`

UNION ALL

SELECT
  'Data Freshness Summary',
  'Phase 3: Analytics',
  MAX(updated_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(updated_at), HOUR),
  MAX(game_date)
FROM `nba_pipeline_prod.nba_analytics.game_analytics`

UNION ALL

SELECT
  'Data Freshness Summary',
  'Phase 4: Precompute',
  MAX(updated_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(updated_at), HOUR),
  MAX(game_date)
FROM `nba_pipeline_prod.nba_precompute.precomputed_team_stats`

ORDER BY phase;

-- 4.2: Games in raw data but not in analytics (stale pipeline)
SELECT
  'Games in Raw but Not Analytics' as check_name,
  r.game_id,
  r.game_date,
  r.status,
  r.home_team_id,
  r.visitor_team_id,
  r.created_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), r.created_at, HOUR) as hours_in_raw
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games` r
LEFT JOIN `nba_pipeline_prod.nba_analytics.game_analytics` a
  ON r.game_id = a.game_id
WHERE a.game_id IS NULL
  AND r.status = 'Final'
ORDER BY r.game_date DESC, hours_in_raw DESC
LIMIT 100;

-- 4.3: Games in analytics but not in precompute
SELECT
  'Games in Analytics but Not Precompute' as check_name,
  a.game_id,
  a.game_date,
  a.home_team_id,
  a.away_team_id,
  a.updated_at,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), a.updated_at, HOUR) as hours_in_analytics
FROM `nba_pipeline_prod.nba_analytics.game_analytics` a
LEFT JOIN `nba_pipeline_prod.nba_precompute.precomputed_team_stats` p
  ON a.game_id = p.game_id
WHERE p.game_id IS NULL
ORDER BY a.game_date DESC, hours_in_analytics DESC
LIMIT 100;

-- ============================================================================
-- 5. GAMES WITH PARTIAL DATA (IN SOME TABLES BUT NOT OTHERS)
-- ============================================================================

-- 5.1: Games with game data but no box scores
SELECT
  'Games with No Box Scores' as check_name,
  g.game_id,
  g.game_date,
  g.status,
  g.home_team_id,
  g.visitor_team_id,
  g.home_team_score,
  g.visitor_team_score
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games` g
LEFT JOIN (
  SELECT DISTINCT game_id
  FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`
) b ON g.game_id = b.game_id
WHERE b.game_id IS NULL
  AND g.status = 'Final'
ORDER BY g.game_date DESC
LIMIT 100;

-- 5.2: Games with box scores but no game record
SELECT
  'Box Scores with No Game Record' as check_name,
  b.game_id,
  COUNT(DISTINCT b.player_id) as player_count,
  MIN(b.created_at) as earliest_box_score
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores` b
LEFT JOIN `nba_pipeline_prod.nba_raw_data.balldontlie_games` g
  ON b.game_id = g.game_id
WHERE g.game_id IS NULL
GROUP BY b.game_id
ORDER BY player_count DESC
LIMIT 100;

-- 5.3: Games with analytics but missing player stats
SELECT
  'Games with Analytics but No Player Stats' as check_name,
  g.game_id,
  g.game_date,
  g.home_team_id,
  g.away_team_id
FROM `nba_pipeline_prod.nba_analytics.game_analytics` g
LEFT JOIN (
  SELECT DISTINCT game_id
  FROM `nba_pipeline_prod.nba_analytics.player_game_stats`
) p ON g.game_id = p.game_id
WHERE p.game_id IS NULL
ORDER BY g.game_date DESC
LIMIT 100;

-- 5.4: Complete data availability check for recent games
WITH game_presence AS (
  SELECT
    g.game_id,
    g.game_date,
    g.status,
    CASE WHEN g.game_id IS NOT NULL THEN 1 ELSE 0 END as has_game,
    CASE WHEN b.game_id IS NOT NULL THEN 1 ELSE 0 END as has_box_scores,
    CASE WHEN a.game_id IS NOT NULL THEN 1 ELSE 0 END as has_analytics,
    CASE WHEN p.game_id IS NOT NULL THEN 1 ELSE 0 END as has_precompute
  FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games` g
  LEFT JOIN (SELECT DISTINCT game_id FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`) b
    ON g.game_id = b.game_id
  LEFT JOIN (SELECT DISTINCT game_id FROM `nba_pipeline_prod.nba_analytics.game_analytics`) a
    ON g.game_id = a.game_id
  LEFT JOIN (SELECT DISTINCT game_id FROM `nba_pipeline_prod.nba_precompute.precomputed_team_stats`) p
    ON g.game_id = p.game_id
  WHERE g.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAYS)
)
SELECT
  'Data Completeness for Last 7 Days' as check_name,
  game_id,
  game_date,
  status,
  CASE
    WHEN has_game = 1 AND has_box_scores = 1 AND has_analytics = 1 AND has_precompute = 1 THEN 'COMPLETE'
    WHEN has_game = 1 AND has_box_scores = 1 AND has_analytics = 1 THEN 'MISSING_PRECOMPUTE'
    WHEN has_game = 1 AND has_box_scores = 1 THEN 'MISSING_ANALYTICS_AND_PRECOMPUTE'
    WHEN has_game = 1 THEN 'MISSING_BOX_SCORES_AND_DOWNSTREAM'
    ELSE 'UNKNOWN'
  END as completeness_status
FROM game_presence
WHERE NOT (has_game = 1 AND has_box_scores = 1 AND has_analytics = 1 AND has_precompute = 1)
ORDER BY game_date DESC, game_id;

-- ============================================================================
-- 6. UNUSUAL TIMESTAMP PATTERNS
-- ============================================================================

-- 6.1: Records with future timestamps
SELECT
  'Records with Future Timestamps' as check_name,
  'balldontlie_games' as table_name,
  game_id,
  game_date,
  created_at,
  updated_at,
  TIMESTAMP_DIFF(created_at, CURRENT_TIMESTAMP(), HOUR) as hours_in_future
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`
WHERE created_at > CURRENT_TIMESTAMP()
   OR updated_at > CURRENT_TIMESTAMP()
ORDER BY created_at DESC
LIMIT 50;

-- 6.2: Records with created_at after updated_at (impossible)
SELECT
  'Records with created_at > updated_at' as check_name,
  'balldontlie_games' as table_name,
  game_id,
  game_date,
  created_at,
  updated_at,
  TIMESTAMP_DIFF(created_at, updated_at, MINUTE) as minutes_difference
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`
WHERE created_at > updated_at
ORDER BY minutes_difference DESC
LIMIT 100;

-- 6.3: Games with very old updated_at but recent game_date (stale data)
SELECT
  'Recent Games with Stale Timestamps' as check_name,
  game_id,
  game_date,
  status,
  updated_at,
  DATE_DIFF(CURRENT_DATE(), game_date, DAY) as days_since_game,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), updated_at, DAY) as days_since_update
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAYS)
  AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), updated_at, DAY) > 7
  AND status = 'Final'
ORDER BY days_since_update DESC
LIMIT 100;

-- 6.4: Bulk insert detection (many records with identical timestamps)
SELECT
  'Potential Bulk Inserts' as check_name,
  created_at,
  COUNT(*) as record_count,
  COUNT(DISTINCT game_date) as distinct_dates,
  MIN(game_date) as earliest_game,
  MAX(game_date) as latest_game
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`
GROUP BY created_at
HAVING COUNT(*) > 100
ORDER BY record_count DESC
LIMIT 50;

-- 6.5: Records updated today grouped by hour
SELECT
  'Updates Today by Hour' as check_name,
  EXTRACT(HOUR FROM updated_at) as update_hour,
  COUNT(*) as update_count,
  COUNT(DISTINCT game_id) as distinct_games
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`
WHERE DATE(updated_at) = CURRENT_DATE()
GROUP BY update_hour
ORDER BY update_hour;

-- ============================================================================
-- 7. ADDITIONAL ANOMALY CHECKS
-- ============================================================================

-- 7.1: Games with impossible scores (negative or extremely high)
SELECT
  'Games with Anomalous Scores' as check_name,
  game_id,
  game_date,
  home_team_id,
  visitor_team_id,
  home_team_score,
  visitor_team_score,
  status
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`
WHERE home_team_score < 0
   OR visitor_team_score < 0
   OR home_team_score > 200
   OR visitor_team_score > 200
   OR (status = 'Final' AND home_team_score = visitor_team_score)
ORDER BY game_date DESC
LIMIT 100;

-- 7.2: Players with anomalous stats
SELECT
  'Players with Anomalous Stats' as check_name,
  game_id,
  player_id,
  pts,
  reb,
  ast,
  min
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`
WHERE pts > 100
   OR reb > 50
   OR ast > 50
   OR pts < 0
   OR reb < 0
   OR ast < 0
ORDER BY pts DESC, reb DESC
LIMIT 100;

-- 7.3: Games with zero players
SELECT
  'Games with No Players' as check_name,
  g.game_id,
  g.game_date,
  g.status,
  COALESCE(player_count, 0) as player_count
FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games` g
LEFT JOIN (
  SELECT game_id, COUNT(*) as player_count
  FROM `nba_pipeline_prod.nba_raw_data.balldontlie_box_scores`
  GROUP BY game_id
) b ON g.game_id = b.game_id
WHERE COALESCE(player_count, 0) = 0
  AND g.status = 'Final'
ORDER BY g.game_date DESC
LIMIT 100;

-- 7.4: Check for data gaps by date range
WITH date_series AS (
  SELECT DATE_ADD(DATE('2024-10-01'), INTERVAL day_offset DAY) as check_date
  FROM UNNEST(GENERATE_ARRAY(0, DATE_DIFF(CURRENT_DATE(), DATE('2024-10-01'), DAY))) as day_offset
),
games_by_date AS (
  SELECT
    game_date,
    COUNT(*) as game_count
  FROM `nba_pipeline_prod.nba_raw_data.balldontlie_games`
  WHERE game_date >= DATE('2024-10-01')
  GROUP BY game_date
)
SELECT
  'Date Ranges with No Games' as check_name,
  ds.check_date,
  COALESCE(g.game_count, 0) as game_count
FROM date_series ds
LEFT JOIN games_by_date g ON ds.check_date = g.game_date
WHERE COALESCE(g.game_count, 0) = 0
  AND EXTRACT(DAYOFWEEK FROM ds.check_date) NOT IN (1, 7) -- Exclude Sundays and Saturdays typically
ORDER BY ds.check_date DESC
LIMIT 100;
