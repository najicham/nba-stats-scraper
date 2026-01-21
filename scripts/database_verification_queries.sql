-- =============================================================================
-- DATABASE COMPLETENESS AND QUALITY VERIFICATION QUERIES
-- Project: nba-props-platform
-- Dates: Jan 19, 20, 21, 2026
-- =============================================================================

-- =============================================================================
-- SECTION 1: EXACT RECORD COUNTS BY DATE
-- =============================================================================

-- 1.1 - RAW PLAYER BOXSCORES BY DATE
SELECT
    game_date,
    COUNT(*) as record_count,
    COUNT(DISTINCT game_id) as unique_games,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT bdl_player_id) as unique_bdl_ids
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date
ORDER BY game_date;

-- 1.2 - RAW GAMES (ESPN SCOREBOARD)
SELECT
    game_date,
    COUNT(*) as record_count,
    COUNT(DISTINCT game_id) as unique_games,
    SUM(CASE WHEN game_status = 'Final' THEN 1 ELSE 0 END) as final_games,
    SUM(CASE WHEN game_status != 'Final' THEN 1 ELSE 0 END) as non_final_games
FROM `nba-props-platform.nba_raw.espn_scoreboard`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date
ORDER BY game_date;

-- 1.3 - ANALYTICS PLAYER GAME SUMMARY
SELECT
    game_date,
    COUNT(*) as record_count,
    COUNT(DISTINCT game_id) as unique_games,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT universal_player_id) as unique_universal_ids
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date
ORDER BY game_date;

-- 1.4 - PRECOMPUTE PLAYER DAILY CACHE
SELECT
    cache_date,
    COUNT(*) as record_count,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT universal_player_id) as unique_universal_ids
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY cache_date
ORDER BY cache_date;

-- 1.5 - PREDICTIONS (PLAYER PROP)
SELECT
    game_date,
    COUNT(*) as record_count,
    COUNT(DISTINCT game_id) as unique_games,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT prediction_id) as unique_predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date
ORDER BY game_date;

-- =============================================================================
-- SECTION 2: DATA QUALITY ISSUES
-- =============================================================================

-- 2.1 - NULL VALUES IN RAW PLAYER BOXSCORES
SELECT
    game_date,
    COUNT(*) as total_records,
    SUM(CASE WHEN player_lookup IS NULL THEN 1 ELSE 0 END) as null_player_lookup,
    SUM(CASE WHEN bdl_player_id IS NULL THEN 1 ELSE 0 END) as null_bdl_player_id,
    SUM(CASE WHEN game_id IS NULL THEN 1 ELSE 0 END) as null_game_id,
    SUM(CASE WHEN team_abbr IS NULL THEN 1 ELSE 0 END) as null_team_abbr,
    SUM(CASE WHEN minutes IS NULL OR minutes = '' THEN 1 ELSE 0 END) as null_or_empty_minutes,
    SUM(CASE WHEN points IS NULL THEN 1 ELSE 0 END) as null_points
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date
ORDER BY game_date;

-- 2.2 - DUPLICATE RECORDS CHECK (RAW PLAYER BOXSCORES)
SELECT
    game_date,
    game_id,
    player_lookup,
    COUNT(*) as duplicate_count
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date, game_id, player_lookup
HAVING COUNT(*) > 1
ORDER BY game_date, duplicate_count DESC
LIMIT 50;

-- 2.3 - PLAYERS WITH ZERO MINUTES (DNP/BENCH)
SELECT
    game_date,
    COUNT(*) as total_records,
    SUM(CASE WHEN minutes = '0:00' OR minutes IS NULL OR minutes = '' THEN 1 ELSE 0 END) as zero_or_null_minutes,
    SUM(CASE WHEN minutes != '0:00' AND minutes IS NOT NULL AND minutes != '' THEN 1 ELSE 0 END) as played_minutes
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date
ORDER BY game_date;

-- 2.4 - MISSING UNIVERSAL_PLAYER_ID IN ANALYTICS
SELECT
    game_date,
    COUNT(*) as total_records,
    SUM(CASE WHEN universal_player_id IS NULL THEN 1 ELSE 0 END) as missing_universal_id,
    SUM(CASE WHEN universal_player_id IS NOT NULL THEN 1 ELSE 0 END) as has_universal_id
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date
ORDER BY game_date;

-- =============================================================================
-- SECTION 3: DISCREPANCY ANALYSIS
-- =============================================================================

-- 3.1 - JAN 19: RAW VS ANALYTICS DISCREPANCY
WITH raw_players AS (
    SELECT DISTINCT game_id, player_lookup
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date = '2026-01-19'
),
analytics_players AS (
    SELECT DISTINCT game_id, player_lookup
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date = '2026-01-19'
)
SELECT
    'In Raw Only' as status,
    COUNT(*) as count
FROM raw_players r
LEFT JOIN analytics_players a
    ON r.game_id = a.game_id AND r.player_lookup = a.player_lookup
WHERE a.player_lookup IS NULL

UNION ALL

SELECT
    'In Analytics Only' as status,
    COUNT(*) as count
FROM analytics_players a
LEFT JOIN raw_players r
    ON a.game_id = r.game_id AND a.player_lookup = r.player_lookup
WHERE r.player_lookup IS NULL

UNION ALL

SELECT
    'In Both' as status,
    COUNT(*) as count
FROM raw_players r
INNER JOIN analytics_players a
    ON r.game_id = a.game_id AND r.player_lookup = a.player_lookup;

-- 3.2 - JAN 19: PLAYERS IN RAW BUT NOT IN ANALYTICS (WITH DETAILS)
SELECT
    r.game_id,
    r.player_lookup,
    r.player_full_name,
    r.team_abbr,
    r.minutes,
    r.points,
    r.rebounds,
    r.assists
FROM `nba-props-platform.nba_raw.bdl_player_boxscores` r
LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` a
    ON r.game_id = a.game_id
    AND r.player_lookup = a.player_lookup
    AND a.game_date = '2026-01-19'
WHERE r.game_date = '2026-01-19'
    AND a.player_lookup IS NULL
ORDER BY r.game_id, r.player_lookup
LIMIT 100;

-- 3.3 - JAN 20: PREDICTIONS BREAKDOWN BY GAME
SELECT
    game_id,
    COUNT(DISTINCT player_lookup) as unique_players,
    COUNT(DISTINCT prediction_id) as total_predictions
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date = '2026-01-20'
GROUP BY game_id
ORDER BY game_id;

-- 3.4 - JAN 20: CHECK IF THERE'S ANALYTICS DATA
SELECT
    COUNT(*) as record_count,
    COUNT(DISTINCT game_id) as unique_games,
    COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2026-01-20';

-- 3.5 - JAN 20: CHECK IF THERE'S PRECOMPUTE DATA
SELECT
    COUNT(*) as record_count,
    COUNT(DISTINCT player_lookup) as unique_players
FROM `nba-props-platform.nba_precompute.player_daily_cache`
WHERE cache_date = '2026-01-20';

-- =============================================================================
-- SECTION 4: HISTORICAL DATA RANGE
-- =============================================================================

-- 4.1 - DATE RANGE FOR EACH TABLE
SELECT
    'nba_raw.bdl_player_boxscores' as table_name,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date,
    COUNT(*) as total_records,
    COUNT(DISTINCT game_date) as unique_dates
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`

UNION ALL

SELECT
    'nba_raw.espn_scoreboard' as table_name,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date,
    COUNT(*) as total_records,
    COUNT(DISTINCT game_date) as unique_dates
FROM `nba-props-platform.nba_raw.espn_scoreboard`

UNION ALL

SELECT
    'nba_analytics.player_game_summary' as table_name,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date,
    COUNT(*) as total_records,
    COUNT(DISTINCT game_date) as unique_dates
FROM `nba-props-platform.nba_analytics.player_game_summary`

UNION ALL

SELECT
    'nba_precompute.player_daily_cache' as table_name,
    MIN(cache_date) as earliest_date,
    MAX(cache_date) as latest_date,
    COUNT(*) as total_records,
    COUNT(DISTINCT cache_date) as unique_dates
FROM `nba-props-platform.nba_precompute.player_daily_cache`

UNION ALL

SELECT
    'nba_predictions.player_prop_predictions' as table_name,
    MIN(game_date) as earliest_date,
    MAX(game_date) as latest_date,
    COUNT(*) as total_records,
    COUNT(DISTINCT game_date) as unique_dates
FROM `nba-props-platform.nba_predictions.player_prop_predictions`;

-- 4.2 - DATE GAPS IN LAST 30 DAYS (GAMES)
WITH date_series AS (
    SELECT DATE_SUB(CURRENT_DATE(), INTERVAL day DAY) as check_date
    FROM UNNEST(GENERATE_ARRAY(0, 30)) as day
),
games_by_date AS (
    SELECT
        game_date,
        COUNT(*) as game_count
    FROM `nba-props-platform.nba_raw.espn_scoreboard`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    GROUP BY game_date
)
SELECT
    ds.check_date,
    COALESCE(gbd.game_count, 0) as games_scheduled,
    CASE
        WHEN COALESCE(gbd.game_count, 0) = 0 THEN 'NO GAMES'
        ELSE 'HAS GAMES'
    END as status
FROM date_series ds
LEFT JOIN games_by_date gbd ON ds.check_date = gbd.game_date
ORDER BY ds.check_date DESC;

-- =============================================================================
-- SECTION 5: GAME SCHEDULE VERIFICATION
-- =============================================================================

-- 5.1 - GAMES ON JAN 20, 2026
SELECT
    game_id,
    game_date,
    home_team_abbr,
    away_team_abbr,
    game_status,
    home_team_score,
    away_team_score
FROM `nba-props-platform.nba_raw.espn_scoreboard`
WHERE game_date = '2026-01-20'
ORDER BY game_id;

-- 5.2 - GAME STATUSES FOR TARGET DATES
SELECT
    game_date,
    game_status,
    COUNT(*) as game_count
FROM `nba-props-platform.nba_raw.espn_scoreboard`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
GROUP BY game_date, game_status
ORDER BY game_date, game_status;

-- 5.3 - ALL GAMES FOR TARGET DATES (FULL DETAIL)
SELECT
    game_date,
    game_id,
    home_team_abbr,
    away_team_abbr,
    game_status,
    home_team_score,
    away_team_score
FROM `nba-props-platform.nba_raw.espn_scoreboard`
WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
ORDER BY game_date, game_id;

-- =============================================================================
-- SECTION 6: COMPREHENSIVE SUMMARY BY DATE
-- =============================================================================

-- 6.1 - SUMMARY COMPARISON TABLE
WITH raw_counts AS (
    SELECT
        game_date,
        COUNT(*) as raw_player_records,
        COUNT(DISTINCT game_id) as raw_games
    FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
    WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
    GROUP BY game_date
),
analytics_counts AS (
    SELECT
        game_date,
        COUNT(*) as analytics_player_records,
        COUNT(DISTINCT game_id) as analytics_games
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
    GROUP BY game_date
),
precompute_counts AS (
    SELECT
        cache_date as game_date,
        COUNT(*) as precompute_records
    FROM `nba-props-platform.nba_precompute.player_daily_cache`
    WHERE cache_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
    GROUP BY cache_date
),
prediction_counts AS (
    SELECT
        game_date,
        COUNT(*) as prediction_records,
        COUNT(DISTINCT game_id) as prediction_games
    FROM `nba-props-platform.nba_predictions.player_prop_predictions`
    WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
    GROUP BY game_date
),
game_counts AS (
    SELECT
        game_date,
        COUNT(*) as scheduled_games
    FROM `nba-props-platform.nba_raw.espn_scoreboard`
    WHERE game_date IN ('2026-01-19', '2026-01-20', '2026-01-21')
    GROUP BY game_date
)
SELECT
    COALESCE(r.game_date, a.game_date, pc.game_date, pr.game_date, g.game_date) as game_date,
    COALESCE(g.scheduled_games, 0) as scheduled_games,
    COALESCE(r.raw_player_records, 0) as raw_player_records,
    COALESCE(r.raw_games, 0) as raw_games,
    COALESCE(a.analytics_player_records, 0) as analytics_player_records,
    COALESCE(a.analytics_games, 0) as analytics_games,
    COALESCE(pc.precompute_records, 0) as precompute_records,
    COALESCE(pr.prediction_records, 0) as prediction_records,
    COALESCE(pr.prediction_games, 0) as prediction_games,
    COALESCE(r.raw_player_records, 0) - COALESCE(a.analytics_player_records, 0) as raw_analytics_diff
FROM raw_counts r
FULL OUTER JOIN analytics_counts a ON r.game_date = a.game_date
FULL OUTER JOIN precompute_counts pc ON COALESCE(r.game_date, a.game_date) = pc.game_date
FULL OUTER JOIN prediction_counts pr ON COALESCE(r.game_date, a.game_date, pc.game_date) = pr.game_date
FULL OUTER JOIN game_counts g ON COALESCE(r.game_date, a.game_date, pc.game_date, pr.game_date) = g.game_date
ORDER BY game_date;
