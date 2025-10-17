-- ============================================================================
-- Identify Exact Missing Playoff Games for Backfill
-- ============================================================================
-- Purpose: Get the exact dates and teams for missing playoff games
-- Output: CSV-ready list of dates to pass to backfill scripts
-- ============================================================================

WITH expected_playoff_games AS (
  SELECT DISTINCT
    s.game_date,
    s.game_id,
    s.home_team_tricode,
    s.away_team_tricode,
    s.home_team_name,
    s.away_team_name,
    s.playoff_round,
    CONCAT(s.away_team_tricode, ' @ ', s.home_team_tricode) as matchup
  FROM `nba-props-platform.nba_raw.nbac_schedule` s
  WHERE s.is_playoffs = TRUE
    AND s.game_date BETWEEN '2023-04-12' AND '2025-06-20'
),
actual_props AS (
  SELECT DISTINCT
    p.game_date,
    p.game_id,
    p.home_team_abbr,
    p.away_team_abbr,
    COUNT(DISTINCT p.player_name) as player_count,
    COUNT(DISTINCT p.bookmaker) as bookmaker_count
  FROM `nba-props-platform.nba_raw.odds_api_player_points_props` p
  WHERE p.game_date BETWEEN '2023-04-12' AND '2025-06-20'
  GROUP BY p.game_date, p.game_id, p.home_team_abbr, p.away_team_abbr
),
missing_games AS (
  SELECT
    e.game_date,
    e.game_id,
    e.home_team_tricode,
    e.away_team_tricode,
    e.home_team_name,
    e.away_team_name,
    e.matchup,
    e.playoff_round,
    CASE 
      WHEN e.game_date >= '2024-04-12' THEN '2023-24'
      WHEN e.game_date >= '2023-04-12' THEN '2022-23'
      ELSE '2024-25'
    END as season
  FROM expected_playoff_games e
  LEFT JOIN actual_props p
    ON e.game_date = p.game_date
    AND e.home_team_tricode = p.home_team_abbr
    AND e.away_team_tricode = p.away_team_abbr
  WHERE p.game_date IS NULL
)
SELECT
  season,
  playoff_round,
  game_date,
  matchup,
  home_team_name,
  away_team_name,
  game_id
FROM missing_games
ORDER BY game_date, playoff_round;

-- ============================================================================
-- Export to CSV for Backfill Script
-- ============================================================================
-- Run this separately to get comma-separated dates for backfill:
-- ============================================================================

-- Get unique dates as comma-separated list (for 2024-25 playoffs)
SELECT STRING_AGG(DISTINCT game_date, ',' ORDER BY game_date) as dates_to_backfill
FROM (
  SELECT DISTINCT e.game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule` e
  LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
    ON e.game_date = p.game_date
    AND e.home_team_tricode = p.home_team_abbr
    AND e.away_team_tricode = p.away_team_abbr
  WHERE e.is_playoffs = TRUE
    AND e.game_date BETWEEN '2025-04-12' AND '2025-06-20'  -- 2024-25 playoffs
    AND p.game_date IS NULL
);

-- Get unique dates as comma-separated list (for 2023-24 playoffs)
SELECT STRING_AGG(DISTINCT game_date, ',' ORDER BY game_date) as dates_to_backfill
FROM (
  SELECT DISTINCT e.game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule` e
  LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
    ON e.game_date = p.game_date
    AND e.home_team_tricode = p.home_team_abbr
    AND e.away_team_tricode = p.away_team_abbr
  WHERE e.is_playoffs = TRUE
    AND e.game_date BETWEEN '2024-04-12' AND '2024-06-20'  -- 2023-24 playoffs
    AND p.game_date IS NULL
);

-- Get unique dates as comma-separated list (for 2022-23 playoffs)
SELECT STRING_AGG(DISTINCT game_date, ',' ORDER BY game_date) as dates_to_backfill
FROM (
  SELECT DISTINCT e.game_date
  FROM `nba-props-platform.nba_raw.nbac_schedule` e
  LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
    ON e.game_date = p.game_date
    AND e.home_team_tricode = p.home_team_abbr
    AND e.away_team_tricode = p.away_team_abbr
  WHERE e.is_playoffs = TRUE
    AND e.game_date BETWEEN '2023-04-12' AND '2023-06-20'  -- 2022-23 playoffs
    AND p.game_date IS NULL
);

-- ============================================================================
-- Get Missing Games Grouped by Team (for investigation)
-- ============================================================================
SELECT
  CASE 
    WHEN e.home_team_tricode IN (
      SELECT home_team_tricode FROM (
        SELECT e2.home_team_tricode
        FROM `nba-props-platform.nba_raw.nbac_schedule` e2
        LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p2
          ON e2.game_date = p2.game_date
          AND e2.home_team_tricode = p2.home_team_abbr
          AND e2.away_team_tricode = p2.away_team_abbr
        WHERE e2.is_playoffs = TRUE
          AND e2.game_date BETWEEN '2023-04-12' AND '2025-06-20'
          AND p2.game_date IS NULL
        UNION ALL
        SELECT e2.away_team_tricode
        FROM `nba-props-platform.nba_raw.nbac_schedule` e2
        LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p2
          ON e2.game_date = p2.game_date
          AND e2.home_team_tricode = p2.home_team_abbr
          AND e2.away_team_tricode = p2.away_team_abbr
        WHERE e2.is_playoffs = TRUE
          AND e2.game_date BETWEEN '2023-04-12' AND '2025-06-20'
          AND p2.game_date IS NULL
      )
      GROUP BY home_team_tricode
      HAVING COUNT(*) >= 3
    ) THEN e.home_team_tricode
    WHEN e.away_team_tricode IN (
      SELECT away_team_tricode FROM (
        SELECT e2.away_team_tricode
        FROM `nba-props-platform.nba_raw.nbac_schedule` e2
        LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p2
          ON e2.game_date = p2.game_date
          AND e2.home_team_tricode = p2.home_team_abbr
          AND e2.away_team_tricode = p2.away_team_abbr
        WHERE e2.is_playoffs = TRUE
          AND e2.game_date BETWEEN '2023-04-12' AND '2025-06-20'
          AND p2.game_date IS NULL
      )
      GROUP BY away_team_tricode
      HAVING COUNT(*) >= 3
    ) THEN e.away_team_tricode
  END as affected_team,
  COUNT(*) as missing_games,
  STRING_AGG(DISTINCT game_date, ', ' ORDER BY game_date) as missing_dates,
  MIN(game_date) as first_missing,
  MAX(game_date) as last_missing
FROM `nba-props-platform.nba_raw.nbac_schedule` e
LEFT JOIN `nba-props-platform.nba_raw.odds_api_player_points_props` p
  ON e.game_date = p.game_date
  AND e.home_team_tricode = p.home_team_abbr
  AND e.away_team_tricode = p.away_team_abbr
WHERE e.is_playoffs = TRUE
  AND e.game_date BETWEEN '2023-04-12' AND '2025-06-20'
  AND p.game_date IS NULL
GROUP BY affected_team
HAVING affected_team IS NOT NULL
ORDER BY missing_games DESC;
