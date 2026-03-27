-- ============================================================
-- Signal Drought Diagnosis Queries
-- Purpose: Understand BB output collapse since March 14, 2026
-- Generated: 2026-03-26
-- GCP Project: nba-props-platform
-- ============================================================


-- ============================================================
-- QUERY 1: Full signal health snapshot (last 7 days)
-- Shows all signals with regime, picks count, and HR.
-- signal_health_daily is NOT partitioned by game_date,
-- so no partition filter is required.
-- ============================================================

SELECT
    shd.signal_tag,
    shd.regime,
    shd.status,
    shd.picks_7d,
    ROUND(shd.hr_7d * 100, 1)    AS hr_7d_pct,
    shd.picks_14d,
    ROUND(shd.hr_14d * 100, 1)   AS hr_14d_pct,
    shd.picks_30d,
    ROUND(shd.hr_30d * 100, 1)   AS hr_30d_pct,
    shd.days_in_current_regime,
    shd.is_model_dependent,
    ROUND(shd.divergence_7d_vs_season * 100, 1) AS divergence_7d_vs_season_pp,
    -- Flag signals that are actively HOT
    CASE WHEN shd.regime = 'HOT' THEN 'HOT'
         WHEN shd.regime = 'COLD' THEN 'COLD'
         ELSE '' END              AS regime_flag,
    -- Highlight signals we expect to fire for UNDER picks
    CASE
        WHEN shd.signal_tag IN (
            'hot_3pt_under', 'line_drifted_down_under', 'bench_under',
            'extended_rest_under', 'volatile_starter_under',
            'sharp_line_drop_under', 'downtrend_under', 'home_under'
        ) THEN 'UNDER_FOCUS'
        ELSE ''
    END                          AS is_under_signal_of_interest,
    shd.game_date                AS snapshot_date
FROM `nba-props-platform.nba_predictions.signal_health_daily` shd
-- Get the most recent row per signal (one row per signal per day, take latest day)
WHERE shd.game_date = (
    SELECT MAX(game_date)
    FROM `nba-props-platform.nba_predictions.signal_health_daily`
)
ORDER BY
    is_under_signal_of_interest DESC,
    picks_7d DESC,
    hr_7d_pct DESC;


-- ============================================================
-- QUERY 2: BB picks drought analysis (March 5 – March 26)
-- Daily pick counts + real_sc distribution per day.
-- Highlights the collapse around March 14.
-- signal_best_bets_picks is partitioned by game_date.
-- ============================================================

WITH daily_picks AS (
    SELECT
        game_date,
        COUNT(*)                                             AS total_picks,
        COUNTIF(recommendation = 'OVER')                    AS over_picks,
        COUNTIF(recommendation = 'UNDER')                   AS under_picks,
        COUNTIF(signal_rescued = TRUE)                      AS rescued_picks,
        -- real_sc distribution buckets
        COUNTIF(real_signal_count = 0)                      AS rsc_0,
        COUNTIF(real_signal_count = 1)                      AS rsc_1,
        COUNTIF(real_signal_count = 2)                      AS rsc_2,
        COUNTIF(real_signal_count >= 3)                     AS rsc_3plus,
        ROUND(AVG(real_signal_count), 2)                    AS avg_real_sc,
        ROUND(AVG(CAST(edge AS FLOAT64)), 2)                AS avg_edge,
        -- HR for graded picks (where prediction_correct is known)
        COUNTIF(prediction_correct IS NOT NULL)              AS graded_n,
        ROUND(
            SAFE_DIVIDE(
                COUNTIF(prediction_correct = TRUE),
                NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0)
            ) * 100, 1
        )                                                    AS hr_pct
    FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
    WHERE game_date BETWEEN '2026-03-05' AND '2026-03-26'
    GROUP BY game_date
)
SELECT
    game_date,
    total_picks,
    over_picks,
    under_picks,
    rescued_picks,
    rsc_0,
    rsc_1,
    rsc_2,
    rsc_3plus,
    avg_real_sc,
    avg_edge,
    graded_n,
    hr_pct,
    -- Flag collapse days (< 3 picks)
    CASE WHEN total_picks < 3 THEN 'DROUGHT'
         WHEN total_picks < 6 THEN 'LOW'
         ELSE 'NORMAL'
    END                         AS pick_volume_flag,
    -- Mark the collapse boundary
    CASE WHEN game_date >= '2026-03-14' THEN 'POST_COLLAPSE' ELSE 'PRE_COLLAPSE' END AS period
FROM daily_picks
ORDER BY game_date DESC;


-- ============================================================
-- QUERY 3: BB candidate signal distribution (last 7 days)
-- Per-signal tag count for BLOCKED vs SELECTED candidates.
-- signal_tags is a REPEATED STRING column in model_bb_candidates.
-- model_bb_candidates is partitioned by game_date.
-- ============================================================

WITH candidates AS (
    SELECT
        game_date,
        player_lookup,
        player_name,
        recommendation,
        real_signal_count,
        signal_tag,
        was_selected,
        filters_failed,
        edge
    FROM `nba-props-platform.nba_predictions.model_bb_candidates`,
        UNNEST(signal_tags) AS signal_tag
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
),
signal_summary AS (
    SELECT
        signal_tag,
        was_selected,
        COUNT(*)                        AS appearances,
        -- Count distinct candidate rows (player × game × model)
        COUNT(DISTINCT CONCAT(player_lookup, '|', CAST(game_date AS STRING))) AS distinct_candidates
    FROM candidates
    GROUP BY signal_tag, was_selected
),
pivoted AS (
    SELECT
        signal_tag,
        SUM(CASE WHEN was_selected = TRUE  THEN appearances ELSE 0 END) AS selected_appearances,
        SUM(CASE WHEN was_selected = FALSE THEN appearances ELSE 0 END) AS blocked_appearances,
        SUM(CASE WHEN was_selected = TRUE  THEN distinct_candidates ELSE 0 END) AS selected_candidates,
        SUM(CASE WHEN was_selected = FALSE THEN distinct_candidates ELSE 0 END) AS blocked_candidates
    FROM signal_summary
    GROUP BY signal_tag
)
SELECT
    signal_tag,
    selected_appearances,
    blocked_appearances,
    selected_candidates,
    blocked_candidates,
    selected_appearances + blocked_appearances         AS total_appearances,
    ROUND(
        SAFE_DIVIDE(selected_appearances,
                    selected_appearances + blocked_appearances) * 100, 1
    )                                                  AS selection_rate_pct,
    -- Flag signals that appear only in blocked candidates (never making final cuts)
    CASE
        WHEN selected_appearances = 0 AND blocked_appearances > 0 THEN 'ONLY_IN_BLOCKED'
        WHEN blocked_appearances = 0 AND selected_appearances > 0 THEN 'ONLY_IN_SELECTED'
        ELSE 'MIXED'
    END                                                AS signal_fate,
    -- Mark signals of interest
    CASE
        WHEN signal_tag IN (
            'hot_3pt_under', 'line_drifted_down_under', 'bench_under',
            'extended_rest_under', 'volatile_starter_under',
            'sharp_line_drop_under', 'downtrend_under', 'home_under'
        ) THEN 'UNDER_FOCUS'
        ELSE ''
    END                                                AS is_under_signal_of_interest
FROM pivoted
ORDER BY
    is_under_signal_of_interest DESC,
    total_appearances DESC;


-- ============================================================
-- QUERY 3b (companion): Most common filters_failed for blocked
-- candidates — what is actually blocking picks?
-- ============================================================

SELECT
    filters_failed,
    COUNT(*)    AS blocked_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct_of_blocked
FROM `nba-props-platform.nba_predictions.model_bb_candidates`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND was_selected = FALSE
  AND filters_failed IS NOT NULL
  AND filters_failed != ''
GROUP BY filters_failed
ORDER BY blocked_count DESC
LIMIT 30;


-- ============================================================
-- QUERY 4: hot_3pt_under data check
-- Verifies that the 3PT shooting supplemental data actually
-- exists in player_game_summary for recent games.
-- player_game_summary is partitioned by game_date.
--
-- hot_3pt_under needs:
--   three_pct_last_3  (window avg of three_pt_makes/three_pt_attempts, last 3 games)
--   three_pct_season  (window avg of same, season)
--   three_pa_per_game (window avg of three_pt_attempts, season)
-- These are computed live in supplemental_data.py from player_game_summary.
-- Signal fires only when:
--   (three_pct_last_3 - three_pct_season) >= 0.10  AND  three_pa_per_game >= 3.0
-- ============================================================

-- 4a: Check raw 3PT data availability for recent completed games
SELECT
    game_date,
    COUNT(*)                                           AS player_games,
    COUNTIF(three_pt_attempts > 0)                     AS with_3pt_attempts,
    COUNTIF(three_pt_attempts IS NULL)                 AS null_3pt_attempts,
    COUNTIF(three_pt_makes IS NULL)                    AS null_3pt_makes,
    ROUND(AVG(NULLIF(three_pt_attempts, 0)), 2)        AS avg_3pa_when_nonzero,
    ROUND(
        SAFE_DIVIDE(
            COUNTIF(three_pt_attempts > 0),
            COUNT(*)
        ) * 100, 1
    )                                                  AS pct_players_with_3pt_data
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND (is_dnp IS NULL OR is_dnp = FALSE)
GROUP BY game_date
ORDER BY game_date DESC;


-- 4b: Check how many players would QUALIFY for hot_3pt_under
-- (i.e., have sufficient 3PA and a hot streak)
-- This computes the same rolling window logic as supplemental_data.py
WITH recent_games AS (
    SELECT
        player_lookup,
        player_full_name,
        game_date,
        three_pt_attempts,
        three_pt_makes,
        SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)) AS three_pct_game,
        AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
            OVER (PARTITION BY player_lookup ORDER BY game_date
                  ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS three_pct_last_3,
        AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
            OVER (PARTITION BY player_lookup ORDER BY game_date
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_season,
        AVG(CAST(three_pt_attempts AS FLOAT64))
            OVER (PARTITION BY player_lookup ORDER BY game_date
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pa_per_game
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)  -- window for rolling calcs
      AND season_year = 2026
      AND (is_dnp IS NULL OR is_dnp = FALSE)
),
-- Isolate rows for "today's upcoming game" window (last 7 days of completed games
-- that would be used as the lookback for upcoming game predictions)
qualifying_check AS (
    SELECT
        player_lookup,
        player_full_name,
        game_date,
        ROUND(three_pct_last_3, 3)                        AS three_pct_last_3,
        ROUND(three_pct_season, 3)                        AS three_pct_season,
        ROUND(three_pct_last_3 - three_pct_season, 3)     AS three_pt_diff,
        ROUND(three_pa_per_game, 1)                       AS three_pa_per_game,
        -- hot_3pt_under qualification gates
        CASE WHEN three_pct_last_3 IS NOT NULL
              AND three_pct_season IS NOT NULL
              AND three_pa_per_game >= 3.0
              AND (three_pct_last_3 - three_pct_season) >= 0.10
             THEN TRUE ELSE FALSE END                     AS would_qualify_hot_3pt_under
    FROM recent_games
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
)
SELECT
    game_date,
    COUNT(*)                                   AS total_players,
    COUNTIF(three_pct_last_3 IS NOT NULL)      AS has_last_3_data,
    COUNTIF(three_pa_per_game >= 3.0)          AS has_sufficient_volume,
    COUNTIF(would_qualify_hot_3pt_under)       AS would_qualify_signal,
    -- Sample of qualifying players (for spot checking)
    STRING_AGG(
        CASE WHEN would_qualify_hot_3pt_under
             THEN CONCAT(player_full_name, '(diff=', CAST(three_pt_diff AS STRING), ')')
             ELSE NULL END,
        ', '
        ORDER BY three_pt_diff DESC
        LIMIT 5
    )                                          AS sample_qualifying_players
FROM qualifying_check
GROUP BY game_date
ORDER BY game_date DESC;


-- ============================================================
-- QUERY 5: League macro — market regime (last 14 days)
-- Confirms TIGHT vs LOOSE and BB HR trend.
-- league_macro_daily is NOT partitioned.
-- ============================================================

SELECT
    game_date,
    market_regime,
    ROUND(vegas_mae_7d, 3)                       AS vegas_mae_7d,
    ROUND(model_mae_7d, 3)                       AS model_mae_7d,
    ROUND(mae_gap_7d, 3)                         AS mae_gap_7d,
    ROUND(league_avg_ppg_7d, 1)                  AS league_avg_ppg_7d,
    ROUND(avg_edge_7d, 2)                        AS avg_edge_7d,
    ROUND(pct_edge_3plus * 100, 1)               AS pct_edge_3plus_pct,
    -- BB hit rate with N
    bb_n_7d                                      AS bb_picks_7d,
    ROUND(bb_hr_7d * 100, 1)                     AS bb_hr_7d_pct,
    bb_n_14d                                     AS bb_picks_14d,
    ROUND(bb_hr_14d * 100, 1)                    AS bb_hr_14d_pct,
    total_predictions,
    -- Regime interpretation annotations
    CASE
        WHEN market_regime = 'TIGHT' THEN 'TIGHT — OVER floor auto-raised to 6.0, edge collapses'
        WHEN market_regime = 'LOOSE' THEN 'LOOSE — normal operation, OVER floor 5.0'
        ELSE market_regime
    END                                          AS regime_note,
    -- Flag if vegas MAE is below the TIGHT threshold (4.5)
    CASE WHEN vegas_mae_7d < 4.5 THEN 'TIGHT_THRESHOLD_BREACH' ELSE '' END AS tight_flag,
    -- Flag if edge availability looks collapsed
    CASE WHEN avg_edge_7d < 3.0 THEN 'EDGE_COLLAPSED'
         WHEN avg_edge_7d < 4.0 THEN 'EDGE_LOW'
         ELSE '' END                             AS edge_flag
FROM `nba-props-platform.nba_predictions.league_macro_daily`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
ORDER BY game_date DESC;
