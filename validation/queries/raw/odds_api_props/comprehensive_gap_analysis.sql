-- ============================================================================
-- File: validation/queries/raw/odds_api_props/comprehensive_gap_analysis.sql
-- Purpose: Complete analysis of missing props data across 4 NBA seasons
-- Usage: Run once to get full picture of data gaps
-- ============================================================================
-- This query will show you:
--   1. Overall coverage summary by season
--   2. Missing games count (games in schedule but not in props)
--   3. Low coverage games (< 6 players)
--   4. Date ranges with gaps
-- ============================================================================

-- ============================================================================
-- PART 1: Overall Season Summary
-- ============================================================================
WITH season_summary AS (
  SELECT
    CASE
      WHEN s.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN s.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN s.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN s.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season,
    s.is_playoffs,
    COUNT(DISTINCT s.game_id) as scheduled_games,
    COUNT(DISTINCT p.game_id) as games_with_props,
    COUNT(DISTINCT s.game_id) - COUNT(DISTINCT p.game_id) as missing_games,
    ROUND(COUNT(DISTINCT p.game_id) * 100.0 / COUNT(DISTINCT s.game_id), 1) as coverage_pct
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
    ON s.game_date = p.game_date
    AND s.home_team_tricode = p.home_team_abbr
    AND s.away_team_tricode = p.away_team_abbr
  WHERE s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.is_all_star = FALSE  -- Exclude All-Star games
    AND (s.is_regular_season = TRUE OR s.is_playoffs = TRUE)  -- Only regular season and playoffs
  GROUP BY season, s.is_playoffs
),

-- ============================================================================
-- PART 2: Player Coverage Stats (for games that DO have props)
-- ============================================================================
player_coverage AS (
  SELECT
    CASE
      WHEN p.game_date BETWEEN '2021-10-19' AND '2022-06-20' THEN '2021-22'
      WHEN p.game_date BETWEEN '2022-10-18' AND '2023-06-20' THEN '2022-23'
      WHEN p.game_date BETWEEN '2023-10-24' AND '2024-06-20' THEN '2023-24'
      WHEN p.game_date BETWEEN '2024-10-22' AND '2025-06-20' THEN '2024-25'
    END as season,
    s.is_playoffs,
    ROUND(AVG(players_per_game), 1) as avg_players_per_game,
    MIN(players_per_game) as min_players,
    MAX(players_per_game) as max_players,
    COUNT(CASE WHEN players_per_game < 6 THEN 1 END) as low_coverage_games
  FROM (
    SELECT
      p.game_date,
      p.game_id,
      COUNT(DISTINCT p.player_lookup) as players_per_game
    FROM `nba-props-platform.nba_raw.odds_api_player_points_props` p
    WHERE p.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    GROUP BY p.game_date, p.game_id
  ) p
  LEFT JOIN `nba-props-platform.nba_raw.nbac_schedule` s
    ON p.game_date = s.game_date
  WHERE s.is_all_star = FALSE  -- Exclude All-Star games from player coverage stats
  GROUP BY season, s.is_playoffs
),

-- ============================================================================
-- PART 3: Combine Summary with Coverage
-- ============================================================================
combined_summary AS (
  SELECT
    s.season,
    CASE WHEN s.is_playoffs THEN 'Playoffs' ELSE 'Regular Season' END as game_type,
    s.scheduled_games,
    s.games_with_props,
    s.missing_games,
    s.coverage_pct,
    COALESCE(p.avg_players_per_game, 0) as avg_players,
    COALESCE(p.min_players, 0) as min_players,
    COALESCE(p.max_players, 0) as max_players,
    COALESCE(p.low_coverage_games, 0) as low_coverage_games,
    CASE
      WHEN s.missing_games = 0 AND COALESCE(p.low_coverage_games, 0) = 0 THEN '✅ Complete'
      WHEN s.missing_games > 0 AND s.games_with_props = 0 THEN '❌ No Data'
      WHEN s.missing_games > 0 THEN '🔴 Partial'
      WHEN COALESCE(p.low_coverage_games, 0) > 0 THEN '🟡 Low Coverage'
      ELSE '✅ Complete'
    END as status
  FROM season_summary s
  LEFT JOIN player_coverage p
    ON s.season = p.season
    AND s.is_playoffs = p.is_playoffs
  WHERE s.season IS NOT NULL
)

-- Output the summary
SELECT
  season,
  game_type,
  scheduled_games,
  games_with_props,
  missing_games,
  coverage_pct as coverage_percent,
  avg_players,
  min_players,
  max_players,
  low_coverage_games,
  status
FROM combined_summary
ORDER BY season, game_type DESC;

-- ============================================================================
-- PART 4: Date Ranges with Missing Data
-- ============================================================================
-- Run this separately to see specific date ranges with gaps
-- Uncomment the query below to see detailed gap analysis:
/*
WITH missing_game_dates AS (
  SELECT DISTINCT
    s.game_date,
    s.is_playoffs,
    COUNT(DISTINCT s.game_id) as games_on_date
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
    ON s.game_date = p.game_date
    AND s.home_team_tricode = p.home_team_abbr
    AND s.away_team_tricode = p.away_team_abbr
  WHERE s.game_date BETWEEN '2021-10-19' AND '2025-06-20'
    AND s.is_all_star = FALSE  -- Exclude All-Star games
    AND (s.is_regular_season = TRUE OR s.is_playoffs = TRUE)  -- Only regular season and playoffs
    AND p.game_date IS NULL
  GROUP BY s.game_date, s.is_playoffs
),

date_ranges AS (
  SELECT
    game_date,
    is_playoffs,
    games_on_date,
    LAG(game_date) OVER (ORDER BY game_date) as prev_date,
    DATE_DIFF(game_date, LAG(game_date) OVER (ORDER BY game_date), DAY) as days_since_prev
  FROM missing_game_dates
)

SELECT
  MIN(game_date) as range_start,
  MAX(game_date) as range_end,
  COUNT(*) as missing_dates,
  SUM(games_on_date) as total_missing_games,
  CASE WHEN MAX(is_playoffs) THEN 'Playoffs' ELSE 'Regular Season' END as game_type,
  CASE
    WHEN EXTRACT(MONTH FROM MIN(game_date)) = 10 THEN '🍂 Season Start'
    WHEN EXTRACT(MONTH FROM MIN(game_date)) IN (11,12) THEN '🏀 Early Season'
    WHEN EXTRACT(MONTH FROM MIN(game_date)) IN (1,2,3) THEN '❄️ Mid Season'
    WHEN EXTRACT(MONTH FROM MIN(game_date)) = 4 THEN '🌸 Late Regular'
    WHEN EXTRACT(MONTH FROM MIN(game_date)) IN (5,6) THEN '🏆 Playoffs'
    ELSE 'Other'
  END as period
FROM date_ranges
WHERE days_since_prev IS NULL OR days_since_prev <= 7
GROUP BY
  CASE
    WHEN days_since_prev IS NULL OR days_since_prev <= 7
    THEN DATE_DIFF(game_date, prev_date, DAY)
  END
ORDER BY range_start;
*/