-- View: nba_raw.odds_api_game_lines_preferred
-- Description: Game lines with DraftKings preferred, FanDuel fallback
-- 
-- Coverage Stats (Oct 2021 → Mar 2025):
--   - Total games: 5,260
--   - DraftKings: 5,235 games (99.52%)
--   - FanDuel fallback: 25 games (0.48%)
--
-- Breakdown:
--   - 13 games missing DK entirely (0.25%)
--   - 15 games missing DK spreads (0.29%)
--   - 25 games missing DK totals (0.48%)

CREATE OR REPLACE VIEW `nba_raw.odds_api_game_lines_preferred` AS
WITH ranked_bookmakers AS (
  SELECT 
    *,
    -- Rank: DraftKings=1, FanDuel=2 (lower is better)
    ROW_NUMBER() OVER (
      PARTITION BY game_id, game_date, market_key, outcome_name
      ORDER BY 
        CASE bookmaker_key 
          WHEN 'draftkings' THEN 1 
          WHEN 'fanduel' THEN 2 
          ELSE 99 
        END,
        snapshot_timestamp DESC  -- If both exist, take latest
    ) as bookmaker_rank
  FROM `nba_raw.odds_api_game_lines`
)
SELECT 
  snapshot_timestamp,
  previous_snapshot_timestamp,
  next_snapshot_timestamp,
  game_id,
  sport_key,
  sport_title,
  commence_time,
  game_date,
  home_team,
  away_team,
  home_team_abbr,
  away_team_abbr,
  bookmaker_key,
  bookmaker_title,
  bookmaker_last_update,
  market_key,
  market_last_update,
  outcome_name,
  outcome_price,
  outcome_point,
  source_file_path,
  created_at,
  processed_at
FROM ranked_bookmakers
WHERE bookmaker_rank = 1;