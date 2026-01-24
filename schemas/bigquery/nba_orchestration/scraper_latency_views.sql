-- File: schemas/bigquery/nba_orchestration/scraper_latency_views.sql
-- ============================================================================
-- NBA Orchestration - Scraper Latency & Game Data Timeline Views
-- ============================================================================
-- Purpose: Create views for monitoring scraper data availability and latency
-- Dataset: nba_orchestration
-- Created: January 24, 2026
--
-- Views:
--   1. v_scraper_latency_daily - Daily scraper latency and coverage metrics
--   2. v_game_data_timeline - Game-level data availability across sources
-- ============================================================================


-- ============================================================================
-- VIEW 1: v_scraper_latency_daily
-- ============================================================================
-- Purpose: Aggregate scraper execution metrics by game date
-- Usage: SELECT * FROM `nba-props-platform.nba_orchestration.v_scraper_latency_daily`
--        WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
--
-- Metrics:
--   - total_games: Number of games scheduled for that date
--   - games_with_data: Games that have data in the raw table
--   - coverage_pct: Percentage of games with data
--   - latency_p50_hours: Median time from game end to data availability
--   - latency_p90_hours: 90th percentile latency
--   - never_available_count: Games that never got data
--   - health_score: Overall health metric (0-100)
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_scraper_latency_daily` AS
WITH
-- Get all completed games from schedule
games AS (
  SELECT
    game_id,
    game_date,
    home_team_tricode,
    away_team_tricode,
    TIMESTAMP(game_datetime_et) as game_start_time,
    -- Estimate game end time (game start + 2.5 hours average)
    TIMESTAMP_ADD(TIMESTAMP(game_datetime_et), INTERVAL 150 MINUTE) as estimated_game_end
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3  -- Completed games only
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
),

-- NBAC Gamebook availability (first successful data for each game)
nbac_gamebook_availability AS (
  SELECT
    game_id,
    game_date,
    MIN(processed_at) as first_data_at,
    'nbac_gamebook' as scraper_name
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    AND player_status = 'active'  -- Only count games with actual player data
  GROUP BY game_id, game_date
  HAVING COUNT(*) >= 10  -- At least 10 active players
),

-- BDL Box Scores availability
bdl_boxscores_availability AS (
  SELECT
    game_id,
    game_date,
    MIN(processed_at) as first_data_at,
    'bdl_box_scores' as scraper_name
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_id, game_date
  HAVING COUNT(*) >= 10  -- At least 10 players
),

-- NBAC Player Boxscore availability
nbac_player_boxscore_availability AS (
  SELECT
    game_id,
    game_date,
    MIN(processed_at) as first_data_at,
    'nbac_player_boxscore' as scraper_name
  FROM `nba-props-platform.nba_raw.nbac_player_boxscore`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_id, game_date
  HAVING COUNT(*) >= 10
),

-- Odds API Props availability (check for game date, not game_id since props are pre-game)
oddsa_props_availability AS (
  SELECT
    game_id,
    game_date,
    MIN(processing_timestamp) as first_data_at,
    'oddsa_player_props' as scraper_name
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
  GROUP BY game_id, game_date
  HAVING COUNT(DISTINCT player_lookup) >= 5  -- At least 5 players with props
),

-- Combine all scrapers
all_scraper_availability AS (
  SELECT * FROM nbac_gamebook_availability
  UNION ALL
  SELECT * FROM bdl_boxscores_availability
  UNION ALL
  SELECT * FROM nbac_player_boxscore_availability
  UNION ALL
  SELECT * FROM oddsa_props_availability
),

-- Join with games to calculate latency
game_scraper_latency AS (
  SELECT
    g.game_id,
    g.game_date,
    a.scraper_name,
    a.first_data_at,
    g.estimated_game_end,
    TIMESTAMP_DIFF(a.first_data_at, g.estimated_game_end, MINUTE) / 60.0 as latency_hours
  FROM games g
  LEFT JOIN all_scraper_availability a
    ON g.game_id = a.game_id AND g.game_date = a.game_date
),

-- Aggregate by scraper and date
scraper_daily_stats AS (
  SELECT
    game_date,
    scraper_name,
    COUNT(DISTINCT game_id) as total_games,
    COUNT(DISTINCT CASE WHEN first_data_at IS NOT NULL THEN game_id END) as games_with_data,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN first_data_at IS NOT NULL THEN game_id END) /
          NULLIF(COUNT(DISTINCT game_id), 0), 2) as coverage_pct,
    ROUND(APPROX_QUANTILES(latency_hours, 100)[OFFSET(50)], 2) as latency_p50_hours,
    ROUND(APPROX_QUANTILES(latency_hours, 100)[OFFSET(90)], 2) as latency_p90_hours,
    COUNT(DISTINCT CASE WHEN first_data_at IS NULL THEN game_id END) as never_available_count
  FROM game_scraper_latency
  WHERE scraper_name IS NOT NULL
  GROUP BY game_date, scraper_name
)

SELECT
  game_date,
  scraper_name,
  total_games,
  games_with_data,
  coverage_pct,
  latency_p50_hours,
  latency_p90_hours,
  never_available_count,
  -- Health score: weighted combination of coverage and latency
  -- 100 = perfect (100% coverage, <1h latency)
  -- Deductions: -20 per 10% missing coverage, -10 per hour of P90 latency
  GREATEST(0, LEAST(100,
    ROUND(
      (coverage_pct)
      - GREATEST(0, (100 - coverage_pct) * 2)  -- Penalty for missing coverage
      - GREATEST(0, (COALESCE(latency_p90_hours, 0) - 1) * 5)  -- Penalty for latency >1h
    , 0)
  )) as health_score
FROM scraper_daily_stats
ORDER BY game_date DESC, scraper_name;


-- ============================================================================
-- VIEW 2: v_game_data_timeline
-- ============================================================================
-- Purpose: Track data availability status for each game across all sources
-- Usage: SELECT * FROM `nba-props-platform.nba_orchestration.v_game_data_timeline`
--        WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
--        AND availability_status != 'OK'
--
-- Status values:
--   - AVAILABLE: Data exists
--   - NEVER_AVAILABLE: No data found
--   - LATE: Data arrived >6h after game
-- ============================================================================

CREATE OR REPLACE VIEW `nba-props-platform.nba_orchestration.v_game_data_timeline` AS
WITH
-- Get all completed games
games AS (
  SELECT
    game_id,
    game_date,
    home_team_tricode,
    away_team_tricode,
    CONCAT(away_team_tricode, ' @ ', home_team_tricode) as matchup,
    TIMESTAMP(game_datetime_et) as game_start_time,
    TIMESTAMP_ADD(TIMESTAMP(game_datetime_et), INTERVAL 150 MINUTE) as estimated_game_end,
    -- West coast games (PHX, LAL, LAC, GSW, SAC, POR, DEN, UTA, MIN, OKC)
    CASE
      WHEN home_team_tricode IN ('PHX', 'LAL', 'LAC', 'GSW', 'SAC', 'POR', 'DEN', 'UTA', 'MIN', 'OKC')
      THEN TRUE
      ELSE FALSE
    END as is_west_coast
  FROM `nba-props-platform.nba_raw.nbac_schedule`
  WHERE game_status = 3
    AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),

-- NBAC data
nbac_data AS (
  SELECT
    game_id,
    MIN(processed_at) as nbac_first_at,
    COUNT(*) as nbac_record_count
  FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    AND player_status = 'active'
  GROUP BY game_id
),

-- BDL data
bdl_data AS (
  SELECT
    game_id,
    MIN(processed_at) as bdl_first_at,
    COUNT(*) as bdl_record_count
  FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_id
),

-- Odds data (pre-game, so we just check existence)
odds_data AS (
  SELECT
    game_id,
    MIN(processing_timestamp) as odds_first_at,
    COUNT(DISTINCT player_lookup) as odds_player_count
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
  WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  GROUP BY game_id
)

SELECT
  g.game_date,
  g.game_id,
  g.matchup,
  g.home_team_tricode,
  g.away_team_tricode,
  g.is_west_coast,
  g.estimated_game_end,

  -- NBAC status
  CASE
    WHEN n.game_id IS NULL THEN 'NEVER_AVAILABLE'
    WHEN TIMESTAMP_DIFF(n.nbac_first_at, g.estimated_game_end, HOUR) > 6 THEN 'LATE'
    ELSE 'AVAILABLE'
  END as nbac_status,
  TIMESTAMP_DIFF(n.nbac_first_at, g.estimated_game_end, MINUTE) as nbac_latency_minutes,

  -- BDL status
  CASE
    WHEN b.game_id IS NULL THEN 'NEVER_AVAILABLE'
    WHEN TIMESTAMP_DIFF(b.bdl_first_at, g.estimated_game_end, HOUR) > 12 THEN 'LATE'
    ELSE 'AVAILABLE'
  END as bdl_status,
  TIMESTAMP_DIFF(b.bdl_first_at, g.estimated_game_end, MINUTE) as bdl_latency_minutes,

  -- Odds status (pre-game so different logic)
  CASE
    WHEN o.game_id IS NULL THEN 'NEVER_AVAILABLE'
    WHEN o.odds_player_count < 10 THEN 'PARTIAL'
    ELSE 'AVAILABLE'
  END as odds_status,
  o.odds_player_count,

  -- Overall availability
  CASE
    WHEN n.game_id IS NULL THEN 'CRITICAL - NO NBAC'
    WHEN b.game_id IS NULL AND g.game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) THEN 'WARNING - NO BDL'
    WHEN o.game_id IS NULL THEN 'INFO - NO ODDS'
    ELSE 'OK'
  END as availability_status

FROM games g
LEFT JOIN nbac_data n ON g.game_id = n.game_id
LEFT JOIN bdl_data b ON g.game_id = b.game_id
LEFT JOIN odds_data o ON g.game_id = o.game_id
ORDER BY g.game_date DESC, g.game_id;


-- ============================================================================
-- DEPLOYMENT NOTES
-- ============================================================================
-- To deploy these views:
--
-- 1. Run this SQL file against BigQuery:
--    bq query --use_legacy_sql=false < scraper_latency_views.sql
--
-- 2. Verify views work:
--    SELECT * FROM `nba-props-platform.nba_orchestration.v_scraper_latency_daily`
--    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY);
--
--    SELECT * FROM `nba-props-platform.nba_orchestration.v_game_data_timeline`
--    WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
--    AND availability_status != 'OK';
--
-- 3. Update daily_scraper_health.sql to uncomment the queries that use these views
-- ============================================================================
