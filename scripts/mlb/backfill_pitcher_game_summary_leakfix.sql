-- Backfill: de-leak FanGraphs-derived columns in mlb_analytics.pitcher_game_summary
--
-- Context (2026-05-20): mlb_raw.fangraphs_pitcher_season_stats holds only
-- post-season snapshots, so the processor's same-season join leaked completed-
-- season swstr/csw/chase/contact into mid-season game rows. The processor code
-- was fixed to a prior-season join (commit a490ddc2); this script repaired the
-- already-written historical rows the same way.
--
-- Idempotent — safe to re-run. Run once after a processor logic change if the
-- table is suspected stale. Both statements were executed 2026-05-20; verified
-- 0 mismatches afterward.
--
--   bq query --use_legacy_sql=false --project_id=nba-props-platform < this_file

-- 1. Matched rows: set the 4 FanGraphs columns from the prior season's final
--    snapshot (leak-free — the prior season is complete before any game).
UPDATE `nba-props-platform.mlb_analytics.pitcher_game_summary` t
SET
  season_swstr_pct   = CAST(ROUND(fg.swstr_pct, 4) AS NUMERIC),
  season_csw_pct     = CAST(ROUND(fg.csw_pct, 4) AS NUMERIC),
  season_chase_pct   = CAST(ROUND(fg.o_swing_pct, 4) AS NUMERIC),
  season_contact_pct = CAST(ROUND(fg.contact_pct, 4) AS NUMERIC)
FROM (
  SELECT player_lookup, season_year, swstr_pct, csw_pct, o_swing_pct, contact_pct
  FROM `mlb_raw.fangraphs_pitcher_season_stats`
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY player_lookup, season_year ORDER BY snapshot_date DESC) = 1
) fg
WHERE REPLACE(t.player_lookup, "_", "") = fg.player_lookup
  AND fg.season_year = EXTRACT(YEAR FROM t.game_date) - 1
  AND t.game_date >= "2022-01-01";

-- 2. Unmatched rows (no prior-season FanGraphs — e.g. 2022 games, rookies):
--    NULL the columns so no stale/leaked value remains. NaN-tolerant downstream.
UPDATE `nba-props-platform.mlb_analytics.pitcher_game_summary` t
SET season_swstr_pct = NULL, season_csw_pct = NULL,
    season_chase_pct = NULL, season_contact_pct = NULL
WHERE t.game_date >= "2022-01-01"
  AND NOT EXISTS (
    SELECT 1 FROM `mlb_raw.fangraphs_pitcher_season_stats` fg
    WHERE REPLACE(t.player_lookup, "_", "") = fg.player_lookup
      AND fg.season_year = EXTRACT(YEAR FROM t.game_date) - 1
  );
