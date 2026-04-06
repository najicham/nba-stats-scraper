"""Shared supplemental data queries for signal evaluation.

Provides the BigQuery queries and row-parsing logic needed to build
the supplemental dicts that signals require (3PT stats, minutes stats,
model health, games_vs_opponent). Used by both SignalBestBetsExporter
and SignalAnnotator to avoid duplicating SQL.

Session 314: Added query_games_vs_opponent() with module-level cache.
    Previously a private method on SignalBestBetsExporter — extracted here
    so both exporters can call it without duplicate BQ scans.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery

from shared.config.cross_model_subsets import build_system_id_sql_filter, build_noveg_mae_sql_filter, classify_system_id
from shared.config.model_selection import get_best_bets_model_id

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


def query_model_health(
    bq_client: bigquery.Client,
    system_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Query rolling 7-day hit rate for edge 3+ picks.

    Args:
        bq_client: BigQuery client.
        system_id: Model to check health for. Defaults to best bets model.

    Returns:
        Dict with hit_rate_7d_edge3 (float or None), graded_count (int).
    """
    model_id = system_id or get_best_bets_model_id()
    query = f"""
    SELECT
      COUNTIF(prediction_correct) as wins,
      COUNT(*) as graded_count,
      ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1)
        AS hit_rate_7d_edge3
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND system_id = '{model_id}'
      AND ABS(predicted_points - line_value) >= 3.0
      AND prediction_correct IS NOT NULL
      AND is_voided IS NOT TRUE
    """

    try:
        result = bq_client.query(query).result(timeout=30)
        row = next(result, None)
        if row and (row.graded_count or 0) > 0:
            return dict(row)
    except Exception as e:
        logger.error(f"Model health query failed: {e}", exc_info=True)

    return {'hit_rate_7d_edge3': None, 'graded_count': 0}


def query_predictions_with_supplements(
    bq_client: bigquery.Client,
    target_date: str,
    system_id: Optional[str] = None,
    multi_model: bool = False,
    skip_disabled_filter: bool = False,
) -> Tuple[List[Dict], Dict[str, Dict]]:
    """Query active predictions with supplemental signal data.

    Args:
        bq_client: BigQuery client.
        target_date: Date string in YYYY-MM-DD format.
        system_id: Model to query predictions for. Defaults to best bets model.
        multi_model: If True, query all CatBoost families and pick highest-edge
            prediction per player. Adds source_model_id, n_models_eligible,
            champion_edge, direction_conflict to each prediction dict.
        skip_disabled_filter: If True, include predictions from disabled/blocked
            models. Used by simulation tools to evaluate historical periods
            where models were active but are now disabled.

    Returns:
        Tuple of (predictions list, supplemental_map keyed by player_lookup).
    """
    model_id = system_id or get_best_bets_model_id()

    if multi_model:
        system_filter = build_system_id_sql_filter('p')
        # Session 395: skip_disabled_filter for historical simulation.
        # When evaluating historical periods, models that were active then
        # may be disabled now. The simulator needs to bypass this filter.
        if skip_disabled_filter:
            disabled_models_cte = """
    -- Session 395: Disabled model filter SKIPPED (historical simulation mode)
    WITH disabled_models AS (
      SELECT CAST(NULL AS STRING) AS model_id FROM UNNEST(ARRAY<STRING>[]) AS model_id
    ),"""
        else:
            disabled_models_cte = f"""
    -- Session 366: Model HR weight with post-filter fallback chain.
    -- Priority: best-bets HR (21d, N>=8) → raw HR (14d, N>=10) → 50% default.
    -- Self-bootstrapping: new models use raw HR until they accumulate 8+ best-bets picks.
    -- Session 378c: Registry cascade — disabled/blocked models auto-excluded from best bets.
    -- Safe degradation: if registry query returns empty, NOT IN (empty) excludes nothing.
    -- Session 391: Defense-in-depth — hardcoded legacy models that bypass registry
    -- (loaded directly by worker.py) are explicitly excluded here to prevent them
    -- from winning per-player selection then being blocked by LEGACY_MODEL_BLOCKLIST.
    -- Root cause: catboost_v12/v9 won selection for 47/61 players → all blocked → 0 best bets.
    WITH disabled_models AS (
      SELECT model_id
      FROM `{PROJECT_ID}.nba_predictions.model_registry`
      WHERE enabled = FALSE OR status IN ('blocked', 'disabled')
         OR model_id IN ('catboost_v12', 'catboost_v9')
    ),"""
        preds_cte = f"""{disabled_models_cte}

    -- Session 378c warmup REMOVED: created_at reflects registry insertion date,
    -- not actual model deployment date. Re-registering models resets created_at,
    -- blocking established models. The model HR weight system (Session 365) and
    -- model sanity guard (Session 378c) provide sufficient protection for new models.

    model_hr AS (
      SELECT
        model_id,
        rolling_hr_14d AS hr_14d,
        rolling_n_14d AS n_14d,
        best_bets_hr_21d AS bb_hr_21d,
        best_bets_n_21d AS bb_n_21d
      FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
      WHERE game_date = (
        SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_predictions.model_performance_daily`
        WHERE game_date < @target_date
      )
    ),

    all_model_preds AS (
      SELECT
        p.player_lookup,
        p.game_id,
        p.game_date,
        p.system_id,
        CAST(p.predicted_points AS FLOAT64) AS predicted_points,
        CAST(p.current_points_line AS FLOAT64) AS line_value,
        p.recommendation,
        CAST(p.predicted_points - p.current_points_line AS FLOAT64) AS edge,
        CAST(p.confidence_score AS FLOAT64) AS confidence_score,
        COALESCE(p.feature_quality_score, 0) AS feature_quality_score,
        -- Session 366: Post-filter HR fallback chain for model weight.
        -- best-bets HR (21d, N>=8) → raw HR (14d, N>=10) → 50% default
        LEAST(1.0, COALESCE(
          CASE WHEN mh.bb_n_21d >= 8 THEN mh.bb_hr_21d ELSE NULL END,
          CASE WHEN mh.n_14d >= 10 THEN mh.hr_14d ELSE NULL END,
          50.0
        ) / 55.0) AS model_hr_weight
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` p
      LEFT JOIN model_hr mh ON mh.model_id = p.system_id
      LEFT JOIN disabled_models dm ON p.system_id = dm.model_id
      WHERE p.game_date = @target_date
        AND {system_filter}
        AND p.is_active = TRUE
        AND p.is_actionable = TRUE  -- Session 414: exclude worker-filtered predictions
        AND p.recommendation IN ('OVER', 'UNDER')
        AND p.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
        AND dm.model_id IS NULL  -- Exclude disabled/blocked models
        -- warmup_models filter removed (see comment above)
    ),

    -- Per-player model counts: how many models have edge 5+ for this player
    model_counts AS (
      SELECT
        player_lookup,
        game_id,
        COUNT(*) AS n_models_eligible,
        MAX(CASE WHEN system_id = '{model_id}' THEN edge END) AS champion_edge,
        COUNTIF(recommendation = 'OVER' AND ABS(edge) >= 5.0) AS n_over,
        COUNTIF(recommendation = 'UNDER' AND ABS(edge) >= 5.0) AS n_under
      FROM all_model_preds
      WHERE ABS(edge) >= 5.0
      GROUP BY player_lookup, game_id
    ),

    preds AS (
      SELECT
        amp.*,
        mc.n_models_eligible,
        mc.champion_edge,
        CASE
          WHEN mc.n_over > 0 AND mc.n_under > 0 THEN TRUE
          ELSE FALSE
        END AS direction_conflict
      FROM all_model_preds amp
      LEFT JOIN model_counts mc
        ON mc.player_lookup = amp.player_lookup AND mc.game_id = amp.game_id
      -- Session 365: Rank by HR-weighted edge so better-performing models
      -- win per-player selection over poorly-performing ones
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY amp.player_lookup, amp.game_id
        ORDER BY ABS(amp.edge) * amp.model_hr_weight DESC, amp.system_id DESC
      ) = 1
    ),"""
    else:
        if skip_disabled_filter:
            single_disabled_cte = """
    -- Session 395: Disabled model filter SKIPPED (historical simulation mode)
    WITH disabled_models AS (
      SELECT CAST(NULL AS STRING) AS model_id FROM UNNEST(ARRAY<STRING>[]) AS model_id
    ),"""
        else:
            single_disabled_cte = f"""
    -- Session 378c: Registry cascade for single-model path (warmup removed)
    -- Session 391: Defense-in-depth — include hardcoded legacy models
    WITH disabled_models AS (
      SELECT model_id
      FROM `{PROJECT_ID}.nba_predictions.model_registry`
      WHERE enabled = FALSE OR status IN ('blocked', 'disabled')
         OR model_id IN ('catboost_v12', 'catboost_v9')
    ),"""
        preds_cte = f"""{single_disabled_cte}
    preds AS (
      SELECT
        p.player_lookup,
        p.game_id,
        p.game_date,
        p.system_id,
        CAST(p.predicted_points AS FLOAT64) AS predicted_points,
        CAST(p.current_points_line AS FLOAT64) AS line_value,
        p.recommendation,
        CAST(p.predicted_points - p.current_points_line AS FLOAT64) AS edge,
        CAST(p.confidence_score AS FLOAT64) AS confidence_score,
        COALESCE(p.feature_quality_score, 0) AS feature_quality_score
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` p
      LEFT JOIN disabled_models dm ON p.system_id = dm.model_id
      WHERE p.game_date = @target_date
        AND p.system_id = '{model_id}'
        AND p.is_active = TRUE
        AND p.is_actionable = TRUE  -- Session 414: exclude worker-filtered predictions
        AND p.recommendation IN ('OVER', 'UNDER')
        AND p.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
        AND dm.model_id IS NULL  -- Exclude disabled/blocked models
        -- warmup_models filter removed (see comment above)
    ),"""

    query = f"""{preds_cte}

    -- Rolling stats for 3PT and minutes signals
    game_stats AS (
      SELECT
        player_lookup,
        game_date,
        minutes_played,
        player_full_name,
        team_abbr,
        opponent_team_abbr,
        AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS three_pct_last_3,
        AVG(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_season,
        STDDEV(SAFE_DIVIDE(three_pt_makes, NULLIF(three_pt_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pct_std,
        AVG(CAST(three_pt_attempts AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS three_pa_per_game,
        AVG(minutes_played)
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS minutes_avg_last_3,
        AVG(minutes_played)
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season,
        -- FG% rolling stats (for fg_cold_continuation signal)
        SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)) AS fg_pct,
        AVG(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) AS fg_pct_last_3,
        AVG(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fg_pct_season,
        STDDEV(SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fg_pct_std,
        -- Player profile stats (for market-pattern UNDER signals, Session 274)
        starter_flag,
        AVG(CAST(points AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS points_avg_season,
        AVG(usage_rate)
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS usage_avg_season,
        AVG(CAST(ft_attempts AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS fta_season,
        AVG(CAST(unassisted_fg_makes AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS unassisted_fg_season,
        STDDEV(CAST(points AS FLOAT64))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) AS points_std_last_5,
        -- FT rate and starter rate (Session 336 — player profile signals)
        SAFE_DIVIDE(
          SUM(ft_attempts) OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),
          SUM(fg_attempts) OVER (PARTITION BY player_lookup ORDER BY game_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)
        ) AS ft_rate_season,
        AVG(CAST(starter_flag AS INT64)) OVER (PARTITION BY player_lookup ORDER BY game_date
          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS starter_rate_season,
        -- Self-creation rate: rolling 10-game unassisted FG ratio (Session 380)
        AVG(SAFE_DIVIDE(unassisted_fg_makes, NULLIF(fg_makes, 0)))
          OVER (PARTITION BY player_lookup ORDER BY game_date
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING) AS self_creation_rate_last_10,
        -- Plus/minus streak (Session 294 — neg_pm_under anti-pattern)
        plus_minus,
        LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 1)
          OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_1,
        LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 2)
          OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_2,
        LAG(CASE WHEN plus_minus < 0 THEN 1 ELSE 0 END, 3)
          OVER (PARTITION BY player_lookup ORDER BY game_date) AS neg_pm_3
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date >= '2025-10-22'
        AND minutes_played > 0
    ),

    latest_stats AS (
      SELECT gs.*
      FROM game_stats gs
      INNER JOIN preds p ON gs.player_lookup = p.player_lookup
      WHERE gs.game_date < @target_date
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY gs.player_lookup ORDER BY gs.game_date DESC
      ) = 1
    ),

    -- Streak data: prior actual over/under outcomes + prediction correctness
    streak_data AS (
      SELECT
        player_lookup,
        game_date,
        LAG(CAST(prediction_correct AS INT64), 1) OVER w AS prev_correct_1,
        LAG(CAST(prediction_correct AS INT64), 2) OVER w AS prev_correct_2,
        LAG(CAST(prediction_correct AS INT64), 3) OVER w AS prev_correct_3,
        LAG(CAST(prediction_correct AS INT64), 4) OVER w AS prev_correct_4,
        LAG(CAST(prediction_correct AS INT64), 5) OVER w AS prev_correct_5,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 1) OVER w AS prev_over_1,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 2) OVER w AS prev_over_2,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 3) OVER w AS prev_over_3,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 4) OVER w AS prev_over_4,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 5) OVER w AS prev_over_5
      FROM (
        SELECT *
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '2025-10-22'
          AND system_id = '{model_id}'
          AND prediction_correct IS NOT NULL
          AND is_voided IS NOT TRUE
          AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
        QUALIFY ROW_NUMBER() OVER (
          PARTITION BY player_lookup, game_id ORDER BY graded_at DESC
        ) = 1
      )
      WINDOW w AS (PARTITION BY player_lookup ORDER BY game_date)
    ),

    latest_streak AS (
      SELECT sd.*
      FROM streak_data sd
      INNER JOIN preds p ON sd.player_lookup = p.player_lookup
      WHERE sd.game_date < @target_date
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY sd.player_lookup ORDER BY sd.game_date DESC
      ) = 1
    ),

    -- V12 predictions for cross-model consensus scoring
    -- Dedup: if multiple V12 MAE models exist, pick the one with latest system_id
    -- Session 335: Uses build_noveg_mae_sql_filter() instead of hardcoded pattern
    v12_preds AS (
      SELECT
        p2.player_lookup,
        p2.game_id,
        p2.recommendation AS v12_recommendation,
        CAST(p2.predicted_points - p2.current_points_line AS FLOAT64) AS v12_edge,
        CAST(p2.predicted_points AS FLOAT64) AS v12_predicted_points,
        CAST(p2.confidence_score AS FLOAT64) AS v12_confidence
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` p2
      WHERE p2.game_date = @target_date
        AND {build_noveg_mae_sql_filter('p2')}
        AND p2.is_active = TRUE
        AND p2.is_actionable = TRUE  -- Session 414: exclude worker-filtered predictions
        AND p2.recommendation IN ('OVER', 'UNDER')
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY p2.player_lookup, p2.game_id ORDER BY p2.system_id DESC
      ) = 1
    ),

    -- Multi-book line std, teammate_usage, star_teammates_out, prop_under_streak for signals (Session 303, 355, 367, 371, 374)
    book_stats AS (
      SELECT
        player_lookup,
        game_date,
        feature_50_value AS multi_book_line_std,
        feature_50_source AS book_std_source,
        feature_47_value AS teammate_usage_available,
        feature_37_value AS star_teammates_out,
        feature_52_value AS prop_under_streak,
        feature_42_value AS implied_team_total,
        feature_18_value AS opponent_pace,
        feature_3_value AS points_std_last_10,
        feature_0_value AS points_avg_last_5,
        feature_1_value AS points_avg_last_10,
        feature_29_value AS avg_pts_vs_opp,
        feature_30_value AS games_vs_opp,
        feature_40_value AS minutes_load_7d,
        feature_43_value AS pts_avg_last3,
        feature_44_value AS trend_slope,
        feature_48_value AS usage_rate_l5,
        feature_57_value AS blowout_risk,
        feature_41_value AS spread_magnitude,
        feature_53_value AS prop_over_streak,
        feature_55_value AS over_rate_last_10
      FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
      WHERE game_date = @target_date
    ),

    -- Previous game prop line for line delta signal (Session 294)
    -- Gets the most recent previous line for each player across ANY model
    -- Fixed Session 387: was model-specific (dead champion = always NULL)
    prev_prop_lines AS (
      SELECT
        pp.player_lookup,
        CAST(pp.current_points_line AS FLOAT64) AS prev_line_value,
        pp.game_date AS prev_line_date
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` pp
      WHERE pp.game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
        AND pp.game_date < @target_date
        AND pp.is_active = TRUE
        AND pp.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY pp.player_lookup ORDER BY pp.game_date DESC
      ) = 1
    ),

    -- DraftKings intra-day line movement: opening vs closing line (Session 380)
    -- Line up 2.0+ on OVER = 67.8% HR (69% Feb-resilient)
    dk_line_movement AS (
      SELECT
        player_lookup,
        closing_line - opening_line AS dk_line_move_direction
      FROM (
        SELECT
          player_lookup,
          MIN(CASE WHEN rn_asc = 1 THEN points_line END) AS opening_line,
          MIN(CASE WHEN rn_desc = 1 THEN points_line END) AS closing_line
        FROM (
          SELECT
            player_lookup,
            points_line,
            ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY snapshot_timestamp ASC) AS rn_asc,
            ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY snapshot_timestamp DESC) AS rn_desc
          FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
          WHERE game_date = @target_date
            AND LOWER(bookmaker) = 'draftkings'
            AND player_lookup IS NOT NULL
        )
        WHERE rn_asc = 1 OR rn_desc = 1
        GROUP BY player_lookup
      )
      WHERE opening_line IS NOT NULL AND closing_line IS NOT NULL
    ),

    -- Session 418: Previous game context for bounce-back and streak signals.
    -- Fetches each player's most recent game stats to detect bad misses, shooting slumps, etc.
    prev_game_context AS (
      SELECT
        player_lookup,
        points AS prev_game_points,
        points_line AS prev_game_line,
        SAFE_DIVIDE(points, NULLIF(points_line, 0)) AS prev_game_ratio,
        SAFE_DIVIDE(fg_makes, NULLIF(fg_attempts, 0)) AS prev_game_fg_pct,
        minutes_played AS prev_game_minutes,
        game_date AS prev_game_date
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
        AND game_date < @target_date
        AND points IS NOT NULL AND points > 0
        AND (is_dnp IS NULL OR is_dnp = FALSE)
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY player_lookup ORDER BY game_date DESC
      ) = 1
    ),

    -- Session 451: FTA variance for ft_variance_under observation.
    -- Players with high FTA avg (>=5) + high CV (>=0.5) = 47.8% UNDER HR vs 70.6% stable (22.8pp gap).
    fta_variance AS (
      SELECT
        player_lookup,
        AVG(CAST(ft_attempts AS FLOAT64)) AS fta_avg_last_10,
        STDDEV(CAST(ft_attempts AS FLOAT64)) AS fta_std_last_10,
        SAFE_DIVIDE(
          STDDEV(CAST(ft_attempts AS FLOAT64)),
          NULLIF(AVG(CAST(ft_attempts AS FLOAT64)), 0)
        ) AS fta_cv_last_10
      FROM (
        SELECT player_lookup, ft_attempts,
          ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) AS rn
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date >= '2025-10-22'
          AND game_date < @target_date
          AND minutes_played > 0
          AND (is_dnp IS NULL OR is_dnp = FALSE)
      )
      WHERE rn <= 10
      GROUP BY player_lookup
      HAVING COUNT(*) >= 5
    )

    SELECT
      p.*,
      ls.player_full_name,
      ls.team_abbr,
      ls.opponent_team_abbr,
      ls.three_pct_last_3,
      ls.three_pct_season,
      ls.three_pct_std,
      ls.three_pa_per_game,
      ls.minutes_avg_last_3,
      ls.minutes_avg_season,
      ls.minutes_played AS prev_minutes,
      ls.fg_pct_last_3,
      ls.fg_pct_season,
      ls.fg_pct_std,
      ls.neg_pm_1,
      ls.neg_pm_2,
      ls.neg_pm_3,
      ls.starter_flag,
      ls.points_avg_season,
      ls.usage_avg_season,
      ls.fta_season,
      ls.unassisted_fg_season,
      ls.points_std_last_5,
      ls.ft_rate_season,
      ls.starter_rate_season,
      ls.self_creation_rate_last_10,
      DATE_DIFF(@target_date, ls.game_date, DAY) AS rest_days,
      lsk.prev_correct_1, lsk.prev_correct_2, lsk.prev_correct_3,
      lsk.prev_correct_4, lsk.prev_correct_5,
      lsk.prev_over_1, lsk.prev_over_2, lsk.prev_over_3,
      lsk.prev_over_4, lsk.prev_over_5,
      v12.v12_recommendation,
      v12.v12_edge,
      v12.v12_predicted_points,
      v12.v12_confidence,
      ppl.prev_line_value,
      ppl.prev_line_date,
      bs.multi_book_line_std,
      bs.book_std_source,
      bs.teammate_usage_available,
      bs.star_teammates_out,
      bs.prop_under_streak,
      bs.implied_team_total,
      bs.opponent_pace,
      bs.points_std_last_10,
      bs.points_avg_last_5,
      bs.points_avg_last_10,
      bs.avg_pts_vs_opp,
      bs.games_vs_opp,
      bs.minutes_load_7d,
      bs.pts_avg_last3,
      bs.trend_slope,
      bs.usage_rate_l5,
      bs.blowout_risk,
      bs.spread_magnitude,
      bs.prop_over_streak,
      bs.over_rate_last_10,
      dlm.dk_line_move_direction,
      pgc.prev_game_points,
      pgc.prev_game_line,
      pgc.prev_game_ratio,
      pgc.prev_game_fg_pct,
      pgc.prev_game_minutes,
      fv.fta_avg_last_10,
      fv.fta_std_last_10,
      fv.fta_cv_last_10
    FROM preds p
    LEFT JOIN latest_stats ls ON ls.player_lookup = p.player_lookup
    LEFT JOIN latest_streak lsk ON lsk.player_lookup = p.player_lookup
    LEFT JOIN v12_preds v12 ON v12.player_lookup = p.player_lookup AND v12.game_id = p.game_id
    LEFT JOIN prev_prop_lines ppl ON ppl.player_lookup = p.player_lookup
    LEFT JOIN book_stats bs ON bs.player_lookup = p.player_lookup AND bs.game_date = p.game_date
    LEFT JOIN dk_line_movement dlm ON dlm.player_lookup = p.player_lookup
    LEFT JOIN prev_game_context pgc ON pgc.player_lookup = p.player_lookup
    LEFT JOIN fta_variance fv ON fv.player_lookup = p.player_lookup
    ORDER BY p.player_lookup
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    rows = bq_client.query(query, job_config=job_config).result(timeout=60)

    # Session 374b: Query opponent stars out separately (team_abbr derived in Python)
    opp_stars_query = f"""
    SELECT
      ir.team AS team_abbr,
      COUNT(DISTINCT ir.player_lookup) AS stars_out
    FROM `{PROJECT_ID}.nba_raw.nbac_injury_report` ir
    INNER JOIN (
      SELECT player_lookup, team_abbr
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date >= '2025-10-22' AND game_date < @target_date
      GROUP BY player_lookup, team_abbr
      HAVING AVG(points) >= 18 OR AVG(minutes_played) >= 28
    ) stars ON ir.player_lookup = stars.player_lookup AND ir.team = stars.team_abbr
    WHERE ir.game_date = @target_date
      AND ir.injury_status IN ('out', 'doubtful', 'Out', 'Doubtful')
    GROUP BY ir.team
    """
    try:
        opp_stars_rows = bq_client.query(opp_stars_query, job_config=job_config).result(timeout=30)
        team_stars_out = {row['team_abbr']: row['stars_out'] for row in opp_stars_rows}
    except Exception as e:
        logger.warning(f"Failed to query opponent stars out: {e}")
        team_stars_out = {}

    # Session 399: Mean-median gap for high_skew_over_block filter.
    # Players with right-skewed scoring (mean >> median) have inflated OVER
    # predictions because the model predicts mean but books set lines at median.
    # mean_median_gap > 2.0 = 49.1% OVER HR — below breakeven.
    skew_query = f"""
    WITH player_last_10 AS (
      SELECT
        player_lookup,
        points,
        ROW_NUMBER() OVER (
          PARTITION BY player_lookup ORDER BY game_date DESC
        ) AS rn
      FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
      WHERE game_date >= '2025-10-22'
        AND game_date < @target_date
        AND minutes_played > 0
    )
    SELECT
      player_lookup,
      AVG(points) - APPROX_QUANTILES(points, 100)[OFFSET(50)] AS mean_median_gap
    FROM player_last_10
    WHERE rn <= 10
    GROUP BY player_lookup
    HAVING COUNT(*) >= 5
    """
    try:
        skew_rows = bq_client.query(skew_query, job_config=job_config).result(timeout=30)
        skew_map = {row['player_lookup']: float(row['mean_median_gap']) for row in skew_rows}
        logger.info(f"Loaded mean-median gap for {len(skew_map)} players")
    except Exception as e:
        logger.warning(f"Failed to query mean-median gap: {e}")
        skew_map = {}

    # Session 397: Q4 scoring ratio from BDL play-by-play.
    # Players with high Q4 scoring ratio (35%+) have 34.0% UNDER HR (N=359) —
    # the model undershoots them because Q4 scoring isn't captured in averages.
    q4_ratio_query = f"""
    WITH player_game_q4 AS (
      SELECT
        REGEXP_REPLACE(player_1_lookup, r'^[0-9]+', '') as player_lookup,
        game_date,
        SAFE_DIVIDE(
          SUM(CASE WHEN period = 4 THEN points_scored ELSE 0 END),
          SUM(points_scored)
        ) as q4_ratio
      FROM `{PROJECT_ID}.nba_raw.bigdataball_play_by_play`
      WHERE game_date >= '2025-10-01'
        AND game_date < @target_date
        AND event_type IN ('shot', 'free throw') AND points_scored > 0
      GROUP BY 1, 2
      HAVING SUM(points_scored) >= 5
    ),
    ranked AS (
      SELECT player_lookup, q4_ratio,
        ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY game_date DESC) as rn
      FROM player_game_q4
    )
    SELECT
      player_lookup,
      AVG(q4_ratio) as q4_scoring_ratio
    FROM ranked
    WHERE rn <= 5
    GROUP BY 1
    """
    try:
        q4_rows = bq_client.query(q4_ratio_query, job_config=job_config).result(timeout=30)
        q4_ratio_map = {row['player_lookup']: float(row['q4_scoring_ratio']) for row in q4_rows}
        logger.info(f"Loaded Q4 scoring ratios for {len(q4_ratio_map)} players")
    except Exception as e:
        logger.warning(f"Failed to query Q4 scoring ratios: {e}")
        q4_ratio_map = {}

    # Session 401/403/407: Projection alignment from external sources.
    # Compare external projected_points to prop line to count how many sources
    # agree with each direction. 1+ source above line + OVER = aligned signal.
    # Session 407: Switched to single-source mode (NumberFire only).
    # Session 434: Added ESPN Fantasy projections as second source (shadow validation).
    # - FantasyPros EXCLUDED: Dead (Playwright timeout, wrong data type — DFS season totals)
    # - Dimers EXCLUDED: Page shows generic projections, NOT game-date-specific
    # - DFF EXCLUDED: Only provides DraftKings fantasy points (FPTS)
    # NumberFire (via FanDuel Research GraphQL) provides 120+ valid per-game projections.
    # ESPN Fantasy provides season-average per-game projections for ~500 players.
    projection_query = f"""
    WITH nf AS (
      SELECT REPLACE(player_lookup, '-', '') AS player_lookup, projected_points,
        ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY scraped_at DESC) AS rn
      FROM `{PROJECT_ID}.nba_raw.numberfire_projections`
      WHERE game_date = @target_date AND projected_points IS NOT NULL
        AND projected_points BETWEEN 5 AND 60
    ),
    espn AS (
      SELECT REPLACE(player_lookup, '-', '') AS player_lookup, projected_points,
        ROW_NUMBER() OVER (PARTITION BY player_lookup ORDER BY scraped_at DESC) AS rn
      FROM `{PROJECT_ID}.nba_raw.espn_projections`
      WHERE game_date = @target_date AND projected_points IS NOT NULL
        AND projected_points BETWEEN 5 AND 60
    )
    SELECT
      COALESCE(nf.player_lookup, espn.player_lookup) AS player_lookup,
      nf.projected_points AS nf_projected_points,
      CAST(NULL AS FLOAT64) AS fp_projected_points,
      CAST(NULL AS FLOAT64) AS dm_projected_points,
      espn.projected_points AS espn_projected_points
    FROM nf
    FULL OUTER JOIN espn ON nf.player_lookup = espn.player_lookup AND espn.rn = 1
    WHERE nf.rn = 1 OR (nf.player_lookup IS NULL AND espn.rn = 1)
    """
    projection_map = {}
    try:
        proj_rows = bq_client.query(projection_query, job_config=job_config).result(timeout=30)
        for row in proj_rows:
            projection_map[row['player_lookup']] = {
                'numberfire': float(row['nf_projected_points']) if row['nf_projected_points'] is not None else None,
                'fantasypros': float(row['fp_projected_points']) if row['fp_projected_points'] is not None else None,
                # DFF excluded: only has DFS fantasy points, not real NBA points
                'dailyfantasyfuel': None,
                'dimers': float(row['dm_projected_points']) if row['dm_projected_points'] is not None else None,
                'espn': float(row['espn_projected_points']) if row['espn_projected_points'] is not None else None,
            }
        logger.info(f"Loaded projection data for {len(projection_map)} players from NumberFire + ESPN")
    except Exception as e:
        logger.warning(f"Failed to query projection consensus data: {e}")

    # Session 401: TeamRankings predicted pace for predicted_pace_over signal.
    pace_query = f"""
    SELECT team, pace
    FROM `{PROJECT_ID}.nba_raw.teamrankings_team_stats`
    WHERE game_date = (
      SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_raw.teamrankings_team_stats`
      WHERE game_date <= @target_date
    )
    AND pace IS NOT NULL
    """
    team_pace_map = {}
    try:
        pace_rows = bq_client.query(pace_query, job_config=job_config).result(timeout=30)
        team_pace_map = {row['team']: float(row['pace']) for row in pace_rows}
        logger.info(f"Loaded TeamRankings pace for {len(team_pace_map)} teams")
    except Exception as e:
        logger.warning(f"Failed to query TeamRankings pace: {e}")

    # Session 401/406: DvP data for dvp_favorable_over signal.
    # Session 406: rank column is NULL in BQ — compute from points_allowed.
    # Rank 1 = most points allowed (worst defender). Deduplicate scraper rows.
    # Session 433: Fallback to gamebook self-computation when Hashtag unavailable.
    dvp_query = f"""
    WITH deduped AS (
      SELECT DISTINCT team, position, points_allowed
      FROM `{PROJECT_ID}.nba_raw.hashtagbasketball_dvp`
      WHERE game_date = (
        SELECT MAX(game_date) FROM `{PROJECT_ID}.nba_raw.hashtagbasketball_dvp`
        WHERE game_date <= @target_date
      )
      AND points_allowed IS NOT NULL
      AND position = 'ALL'
      AND team NOT IN ('PG', 'SG', 'SF', 'PF', 'C')
    )
    SELECT team, position, points_allowed,
      RANK() OVER (ORDER BY points_allowed DESC) AS rank
    FROM deduped
    """
    dvp_map = {}  # {team: {position: {points_allowed, rank}}}
    try:
        dvp_rows = bq_client.query(dvp_query, job_config=job_config).result(timeout=30)
        for row in dvp_rows:
            team = row['team']
            if team not in dvp_map:
                dvp_map[team] = {}
            dvp_map[team][row['position']] = {
                'points_allowed': float(row['points_allowed']),
                'rank': int(row['rank']) if row['rank'] is not None else None,
            }
        logger.info(f"Loaded DvP data for {len(dvp_map)} teams")
    except Exception as e:
        logger.warning(f"Failed to query DvP data: {e}")

    # Session 433: Fallback — self-compute DvP from gamebook when Hashtag
    # is unavailable (SPOF mitigation). Uses last 30 days of opponent scoring.
    # Only fires when primary Hashtag source returned 0 teams.
    if len(dvp_map) == 0:
        logger.warning("Hashtag DvP unavailable — falling back to gamebook self-computation")
        dvp_fallback_query = f"""
        WITH opponent_scoring AS (
          SELECT
            g.opponent_team_abbr AS defending_team,
            g.points,
          FROM `{PROJECT_ID}.nba_analytics.player_game_summary` g
          WHERE g.game_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
            AND g.game_date < @target_date
            AND g.minutes > 0
            AND g.points IS NOT NULL
            AND (g.is_dnp IS NULL OR g.is_dnp = FALSE)
        ),
        team_defense AS (
          SELECT
            defending_team AS team,
            'ALL' AS position,
            ROUND(AVG(points), 1) AS points_allowed
          FROM opponent_scoring
          GROUP BY defending_team
          HAVING COUNT(*) >= 30
        )
        SELECT team, position, points_allowed,
          RANK() OVER (ORDER BY points_allowed DESC) AS rank
        FROM team_defense
        """
        try:
            fb_rows = bq_client.query(dvp_fallback_query, job_config=job_config).result(timeout=30)
            for row in fb_rows:
                team = row['team']
                if team not in dvp_map:
                    dvp_map[team] = {}
                dvp_map[team][row['position']] = {
                    'points_allowed': float(row['points_allowed']),
                    'rank': int(row['rank']) if row['rank'] is not None else None,
                }
            logger.info(f"DvP fallback loaded for {len(dvp_map)} teams (from gamebook)")
        except Exception as e:
            logger.warning(f"DvP fallback query also failed: {e}")

    # Session 401: CLV tracking — opening vs closing line comparison.
    # Session 408: snapshot_type='closing' never populated.
    # Session 427: Fixed snapshot selection — was using MIN/MAX on string
    # snapshot_tag, picking snap-0006 (midnight) and snap-2201 (sparse late).
    # Now uses first snapshot >= 0600 (morning market open) and last <= 2200
    # (evening pre-game). Produces 5x more CLV-qualified players (10 vs 2).
    clv_query = f"""
    WITH tagged AS (
      SELECT player_lookup, points_line, snapshot_tag,
        CAST(SUBSTR(snapshot_tag, 6) AS INT64) AS snap_time
      FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
      WHERE game_date = @target_date
        AND player_lookup IS NOT NULL
        AND snapshot_tag IS NOT NULL
        AND points_line IS NOT NULL
    ),
    snap_bounds AS (
      SELECT
        MIN(CASE WHEN snap_time >= 600 THEN snapshot_tag END) as earliest_snap,
        MAX(CASE WHEN snap_time <= 2200 THEN snapshot_tag END) as latest_snap
      FROM tagged
    ),
    opening AS (
      SELECT t.player_lookup, AVG(t.points_line) as opening_line
      FROM tagged t, snap_bounds sb
      WHERE t.snapshot_tag = sb.earliest_snap
      GROUP BY 1
    ),
    closing AS (
      SELECT t.player_lookup, AVG(t.points_line) as closing_line
      FROM tagged t, snap_bounds sb
      WHERE t.snapshot_tag = sb.latest_snap
      GROUP BY 1
    )
    SELECT
      o.player_lookup,
      o.opening_line,
      c.closing_line,
      o.opening_line - c.closing_line AS clv
    FROM opening o
    JOIN closing c ON o.player_lookup = c.player_lookup
    WHERE ABS(o.opening_line - c.closing_line) > 0
    """
    clv_map = {}
    try:
        clv_rows = bq_client.query(clv_query, job_config=job_config).result(timeout=30)
        for row in clv_rows:
            clv_map[row['player_lookup']] = {
                'opening_line': float(row['opening_line']),
                'closing_line': float(row['closing_line']),
                'clv': float(row['clv']),
            }
        logger.info(f"Loaded CLV data for {len(clv_map)} players")
    except Exception as e:
        logger.warning(f"Failed to query CLV data: {e}")

    # Session 462: BettingPros line movement for line_drifted_down_under signal
    # and over_line_rose_heavy observation filter.
    # Computes points_line - opening_line per player (positive = line rose).
    bp_line_move_query = f"""
    SELECT player_lookup,
      AVG(points_line - opening_line) AS bp_line_movement
    FROM `{PROJECT_ID}.nba_raw.bettingpros_player_points_props`
    WHERE game_date = @target_date
      AND market_type = 'points'
      AND opening_line IS NOT NULL
      AND points_line IS NOT NULL
      AND is_best_line = TRUE
    GROUP BY player_lookup
    HAVING ABS(AVG(points_line - opening_line)) > 0
    """
    bp_line_movement_map = {}
    try:
        bp_rows = bq_client.query(bp_line_move_query, job_config=job_config).result(timeout=30)
        bp_line_movement_map = {
            row['player_lookup']: float(row['bp_line_movement'])
            for row in bp_rows if row['bp_line_movement'] is not None
        }
        logger.info(f"Loaded BettingPros line movement for {len(bp_line_movement_map)} players")
    except Exception as e:
        logger.warning(f"Failed to query BettingPros line movement: {e}")

    # Session 399: Sharp vs soft book line lean for sharp_book_lean signal.
    # Sharp books (FanDuel, DraftKings) set efficient lines; soft books
    # (BetRivers, Bovada, Fliff) lag. Divergence predicts direction:
    # sharp_lean >= 1.5 → OVER 70.3% HR (N=508)
    # sharp_lean <= -1.5 → UNDER 84.7% HR (N=202)
    sharp_lean_query = f"""
    WITH latest_lines AS (
      SELECT
        player_lookup, bookmaker, points_line,
        ROW_NUMBER() OVER (
          PARTITION BY player_lookup, bookmaker
          ORDER BY snapshot_timestamp DESC
        ) AS rn
      FROM `{PROJECT_ID}.nba_raw.odds_api_player_points_props`
      WHERE game_date = @target_date
        AND player_lookup IS NOT NULL
        AND points_line IS NOT NULL
    )
    SELECT
      player_lookup,
      AVG(CASE WHEN bookmaker IN ('fanduel', 'draftkings') THEN points_line END)
        - AVG(CASE WHEN bookmaker IN ('betrivers', 'bovada', 'fliff') THEN points_line END)
        AS sharp_lean
    FROM latest_lines
    WHERE rn = 1
    GROUP BY player_lookup
    HAVING COUNT(DISTINCT CASE WHEN bookmaker IN ('fanduel', 'draftkings') THEN bookmaker END) >= 1
       AND COUNT(DISTINCT CASE WHEN bookmaker IN ('betrivers', 'bovada', 'fliff') THEN bookmaker END) >= 1
    """
    try:
        sharp_lean_rows = bq_client.query(sharp_lean_query, job_config=job_config).result(timeout=30)
        sharp_lean_map = {row['player_lookup']: float(row['sharp_lean']) for row in sharp_lean_rows if row['sharp_lean'] is not None}
        logger.info(f"Loaded sharp book lean for {len(sharp_lean_map)} players")
    except Exception as e:
        logger.warning(f"Failed to query sharp book lean: {e}")
        sharp_lean_map = {}

    # Session 404: VSiN sharp money data — handle% vs ticket% divergence.
    # When handle (money) diverges from tickets, sharp bettors are on the money side.
    # This is a game-level signal: over_money_pct vs over_ticket_pct.
    vsin_query = f"""
    SELECT away_team, home_team,
      over_ticket_pct, under_ticket_pct,
      over_money_pct, under_money_pct
    FROM `{PROJECT_ID}.nba_raw.vsin_betting_splits`
    WHERE game_date = @target_date
      AND over_money_pct IS NOT NULL
      AND over_ticket_pct IS NOT NULL
    """
    vsin_map = {}  # {(away, home): {over_money_pct, over_ticket_pct, ...}}
    try:
        vsin_rows = bq_client.query(vsin_query, job_config=job_config).result(timeout=30)
        for row in vsin_rows:
            key = (row['away_team'], row['home_team'])
            vsin_map[key] = {
                'over_money_pct': float(row['over_money_pct']),
                'under_money_pct': float(row['under_money_pct']),
                'over_ticket_pct': float(row['over_ticket_pct']),
                'under_ticket_pct': float(row['under_ticket_pct']),
            }
        logger.info(f"Loaded VSiN betting splits for {len(vsin_map)} games")
    except Exception as e:
        logger.warning(f"Failed to query VSiN betting splits: {e}")

    # Session 404: RotoWire projected minutes for minutes_surge_over signal.
    # Session 405: Normalize player_lookup (remove hyphens) to match prediction format.
    rotowire_query = f"""
    SELECT REPLACE(player_lookup, '-', '') AS player_lookup, projected_minutes
    FROM `{PROJECT_ID}.nba_raw.rotowire_lineups`
    WHERE game_date = @target_date
      AND projected_minutes IS NOT NULL
      AND player_lookup IS NOT NULL
    """
    rotowire_minutes_map = {}
    try:
        rw_rows = bq_client.query(rotowire_query, job_config=job_config).result(timeout=30)
        rotowire_minutes_map = {
            row['player_lookup']: float(row['projected_minutes'])
            for row in rw_rows if row['projected_minutes']
        }
        logger.info(f"Loaded RotoWire minutes for {len(rotowire_minutes_map)} players")
    except Exception as e:
        logger.warning(f"Failed to query RotoWire minutes: {e}")

    predictions = []
    supplemental_map: Dict[str, Dict] = {}

    for row in rows:
        row_dict = dict(row)
        # Derive team/opponent from game_id (YYYYMMDD_AWAY_HOME)
        game_id = row_dict.get('game_id', '')
        parts = game_id.split('_') if game_id else []
        team_abbr = row_dict.get('team_abbr', '')
        if len(parts) >= 3:
            away_team, home_team = parts[1], parts[2]
            is_home = (team_abbr == home_team)
            opponent = away_team if is_home else home_team
        else:
            is_home = False
            opponent = ''

        pred = {
            'player_lookup': row_dict['player_lookup'],
            'game_id': game_id,
            'game_date': row_dict['game_date'],
            'system_id': row_dict['system_id'],
            'player_name': row_dict.get('player_full_name', ''),
            'team_abbr': team_abbr,
            'opponent_team_abbr': opponent,
            'predicted_points': row_dict['predicted_points'],
            'line_value': row_dict['line_value'],
            'recommendation': row_dict['recommendation'],
            'edge': row_dict['edge'],
            'confidence_score': row_dict['confidence_score'],
            'is_home': is_home,
            'rest_days': row_dict.get('rest_days'),
            'feature_quality_score': row_dict.get('feature_quality_score') or 0,
        }

        # Source model attribution (always set — needed by V9 UNDER 7+ filter etc.)
        source_sid = row_dict['system_id']
        pred['source_model_id'] = source_sid
        pred['source_model_family'] = classify_system_id(source_sid)

        # Multi-source attribution (Session 307)
        if multi_model:
            pred['n_models_eligible'] = row_dict.get('n_models_eligible') or 0
            champ_edge = row_dict.get('champion_edge')
            pred['champion_edge'] = float(champ_edge) if champ_edge is not None else None
            pred['direction_conflict'] = bool(row_dict.get('direction_conflict'))
            # Session 365: Model HR weight used in per-player selection
            pred['model_hr_weight'] = float(row_dict.get('model_hr_weight') or 0.91)

        predictions.append(pred)

        supp: Dict[str, Any] = {}

        # Player context
        supp['player_context'] = {
            'position': '',  # Not available in player_game_summary
        }

        if row_dict.get('three_pct_last_3') is not None:
            supp['three_pt_stats'] = {
                'three_pct_last_3': float(row_dict['three_pct_last_3']),
                'three_pct_season': float(row_dict.get('three_pct_season') or 0),
                'three_pct_std': float(row_dict.get('three_pct_std') or 0),
                'three_pa_per_game': float(row_dict.get('three_pa_per_game') or 0),
            }

        if row_dict.get('minutes_avg_last_3') is not None:
            supp['minutes_stats'] = {
                'minutes_avg_last_3': float(row_dict['minutes_avg_last_3']),
                'minutes_avg_season': float(row_dict.get('minutes_avg_season') or 0),
            }

        # Streak stats (for cold_snap, cold_continuation_2)
        if row_dict.get('prev_over_1') is not None:
            prev_correct = [
                row_dict.get('prev_correct_1'),
                row_dict.get('prev_correct_2'),
                row_dict.get('prev_correct_3'),
                row_dict.get('prev_correct_4'),
                row_dict.get('prev_correct_5'),
            ]
            prev_over = [
                row_dict.get('prev_over_1'),
                row_dict.get('prev_over_2'),
                row_dict.get('prev_over_3'),
                row_dict.get('prev_over_4'),
                row_dict.get('prev_over_5'),
            ]

            # Calculate consecutive beats/misses from most recent backwards
            consecutive_beats = 0
            for val in prev_correct:
                if val == 1:
                    consecutive_beats += 1
                else:
                    break

            consecutive_misses = 0
            last_miss_direction = None
            for i, val in enumerate(prev_correct):
                if val == 0:
                    consecutive_misses += 1
                    if i < len(prev_over) and prev_over[i] is not None:
                        last_miss_direction = 'OVER' if prev_over[i] == 1 else 'UNDER'
                else:
                    break

            supp['streak_stats'] = {
                'prev_correct': prev_correct,
                'prev_over': prev_over,
                'consecutive_line_beats': consecutive_beats,
                'consecutive_line_misses': consecutive_misses,
                'last_miss_direction': last_miss_direction,
            }

            # Also provide streak_data in backtest format for cold_continuation_2
            player_key = f"{row_dict['player_lookup']}::{row_dict['game_date']}"
            supp['streak_data'] = {
                player_key: {
                    'consecutive_line_beats': consecutive_beats,
                    'consecutive_line_misses': consecutive_misses,
                    'last_miss_direction': last_miss_direction,
                }
            }

        # Recovery stats (for blowout_recovery)
        if (row_dict.get('prev_minutes') is not None
                and row_dict.get('minutes_avg_season') is not None):
            supp['recovery_stats'] = {
                'prev_minutes': float(row_dict['prev_minutes']),
                'minutes_avg_season': float(row_dict['minutes_avg_season']),
            }

        # FG% stats (for fg_cold_continuation)
        if row_dict.get('fg_pct_last_3') is not None:
            supp['fg_stats'] = {
                'fg_pct_last_3': float(row_dict['fg_pct_last_3']),
                'fg_pct_season': float(row_dict.get('fg_pct_season') or 0),
                'fg_pct_std': float(row_dict.get('fg_pct_std') or 0),
            }

        # Rest stats (for b2b_fatigue_under)
        if row_dict.get('rest_days') is not None:
            supp['rest_stats'] = {
                'rest_days': int(row_dict['rest_days']),
            }

        # Player profile stats (for market-pattern UNDER signals, Session 274)
        supp['player_profile'] = {
            'starter_flag': row_dict.get('starter_flag'),
            'points_avg_season': float(row_dict.get('points_avg_season') or 0),
            'usage_avg_season': float(row_dict.get('usage_avg_season') or 0),
            'fta_season': float(row_dict.get('fta_season') or 0),
            'unassisted_fg_season': float(row_dict.get('unassisted_fg_season') or 0),
            'points_std_last_5': float(row_dict.get('points_std_last_5') or 0),
            'ft_rate_season': float(row_dict.get('ft_rate_season') or 0),
            'starter_rate_season': float(row_dict.get('starter_rate_season') or 0),
        }

        # V12 prediction (for cross-model consensus scoring)
        if row_dict.get('v12_recommendation'):
            supp['v12_prediction'] = {
                'recommendation': row_dict['v12_recommendation'],
                'edge': float(row_dict.get('v12_edge') or 0),
                'predicted_points': float(row_dict.get('v12_predicted_points') or 0),
                'confidence': float(row_dict.get('v12_confidence') or 0),
            }

        # Book disagreement stats (for book_disagreement signal, Session 303)
        if row_dict.get('multi_book_line_std') is not None:
            supp['book_stats'] = {
                'multi_book_line_std': float(row_dict['multi_book_line_std']),
                'book_std_source': row_dict.get('book_std_source', ''),
            }

        # Prop line delta stats (for prop_line_drop_over signal, Session 294)
        if row_dict.get('prev_line_value') is not None:
            current_line = float(row_dict.get('line_value') or 0)
            prev_line = float(row_dict['prev_line_value'])
            supp['prop_line_stats'] = {
                'prev_line_value': prev_line,
                'current_line_value': current_line,
                'line_delta': round(current_line - prev_line, 1),
            }

        # Copy player profile fields to prediction dict for signals that check pred directly
        pred['starter_flag'] = row_dict.get('starter_flag')
        pred['points_avg_season'] = float(row_dict.get('points_avg_season') or 0)
        pred['usage_avg_season'] = float(row_dict.get('usage_avg_season') or 0)
        pred['fta_season'] = float(row_dict.get('fta_season') or 0)
        pred['fta_avg_last_10'] = float(row_dict.get('fta_avg_last_10') or 0)
        pred['fta_cv_last_10'] = float(row_dict.get('fta_cv_last_10') or 0)
        pred['unassisted_fg_season'] = float(row_dict.get('unassisted_fg_season') or 0)
        pred['points_std_last_5'] = float(row_dict.get('points_std_last_5') or 0)
        pred['ft_rate_season'] = float(row_dict.get('ft_rate_season') or 0)
        pred['starter_rate_season'] = float(row_dict.get('starter_rate_season') or 0)

        # Teammate usage from feature store for aggregator filter (Session 355)
        tu = row_dict.get('teammate_usage_available')
        pred['teammate_usage_available'] = float(tu) if tu is not None else 0

        # Star teammates out from feature store for star_under filter (Session 367)
        sto = row_dict.get('star_teammates_out')
        pred['star_teammates_out'] = float(sto) if sto is not None else 0

        # Prop under streak from feature store for scoring_cold_streak_over signal (Session 371)
        pus = row_dict.get('prop_under_streak')
        pred['prop_under_streak'] = float(pus) if pus is not None else 0

        # Implied team total from feature store for high_scoring_environment_over signal (Session 373)
        itt = row_dict.get('implied_team_total')
        pred['implied_team_total'] = float(itt) if itt is not None else 0

        # Opponent pace from feature store for fast_pace_over signal (Session 374)
        op = row_dict.get('opponent_pace')
        pred['opponent_pace'] = float(op) if op is not None else 0

        # Points std last 10 from feature store for volatile_scoring_over signal (Session 374)
        pstd = row_dict.get('points_std_last_10')
        pred['points_std_last_10'] = float(pstd) if pstd is not None else 0

        # Points avg last 5/10 from feature store for hot_form_over signal (Session 410)
        pa5 = row_dict.get('points_avg_last_5')
        pred['points_avg_last_5'] = float(pa5) if pa5 is not None else 0
        pa10 = row_dict.get('points_avg_last_10')
        pred['points_avg_last_10'] = float(pa10) if pa10 is not None else 0

        # Session 411: Feature store values for new shadow signals
        pred['avg_pts_vs_opp'] = float(row_dict.get('avg_pts_vs_opp') or 0)
        pred['games_vs_opp'] = float(row_dict.get('games_vs_opp') or 0)
        pred['minutes_load_7d'] = float(row_dict.get('minutes_load_7d') or 0)
        pred['pts_avg_last3'] = float(row_dict.get('pts_avg_last3') or 0)
        pred['trend_slope'] = float(row_dict.get('trend_slope') or 0)
        pred['usage_rate_l5'] = float(row_dict.get('usage_rate_l5') or 0)
        pred['blowout_risk'] = float(row_dict.get('blowout_risk') or 0)

        # Spread magnitude for high_spread_over observation filter (Session 413)
        pred['spread_magnitude'] = float(row_dict.get('spread_magnitude') or 0)

        # Session 418: Previous game context for bounce-back and streak signals
        pred['prev_game_ratio'] = float(row_dict.get('prev_game_ratio') or 0)
        pred['prev_game_fg_pct'] = float(row_dict.get('prev_game_fg_pct') or 0)
        pred['prev_game_points'] = float(row_dict.get('prev_game_points') or 0)
        pred['prev_game_line'] = float(row_dict.get('prev_game_line') or 0)
        pred['prev_game_minutes'] = float(row_dict.get('prev_game_minutes') or 0)
        pos = row_dict.get('prop_over_streak')
        pred['prop_over_streak'] = float(pos) if pos is not None else 0
        orl = row_dict.get('over_rate_last_10')
        pred['over_rate_last_10'] = float(orl) if orl is not None else 0

        # Over trend: prev_over_1..5 from streak data for over_trend_over signal (Session 410)
        pred['prev_over_1'] = row_dict.get('prev_over_1')
        pred['prev_over_2'] = row_dict.get('prev_over_2')
        pred['prev_over_3'] = row_dict.get('prev_over_3')
        pred['prev_over_4'] = row_dict.get('prev_over_4')
        pred['prev_over_5'] = row_dict.get('prev_over_5')

        # Opponent stars out for opponent_depleted_under filter (Session 374b)
        # Uses team_stars_out dict queried separately, keyed by opponent team
        pred['opponent_stars_out'] = team_stars_out.get(opponent, 0)

        # Multi-book line std for high_book_std_under_block filter (Session 377/514)
        mbls = row_dict.get('multi_book_line_std')
        pred['multi_book_line_std'] = float(mbls) if mbls is not None else 0

        # Self-creation rate (rolling 10-game) for self_creation_over signal (Session 380)
        scr = row_dict.get('self_creation_rate_last_10')
        pred['self_creation_rate_last_10'] = float(scr) if scr is not None else 0

        # DraftKings intra-day line movement for sharp_line_move_over signal (Session 380)
        dlm_val = row_dict.get('dk_line_move_direction')
        pred['dk_line_move_direction'] = float(dlm_val) if dlm_val is not None else None

        # Copy prop line delta for aggregator pre-filter (Session 294)
        if row_dict.get('prev_line_value') is not None:
            current_line = float(row_dict.get('line_value') or 0)
            prev_line = float(row_dict['prev_line_value'])
            pred['prop_line_delta'] = round(current_line - prev_line, 1)

        # Q4 scoring ratio for q4_scorer_under_block filter (Session 397)
        pred['q4_scoring_ratio'] = q4_ratio_map.get(row_dict['player_lookup'], 0)

        # Mean-median gap for high_skew_over_block filter (Session 399)
        pred['mean_median_gap'] = skew_map.get(row_dict['player_lookup'], 0)

        # Sharp book lean for sharp_book_lean_over/under signals (Session 399)
        sbl = sharp_lean_map.get(row_dict['player_lookup'])
        pred['sharp_book_lean'] = float(sbl) if sbl is not None else None

        # Session 401/403: Projection consensus data (5 sources)
        # Session 434: Added ESPN Fantasy projections as fifth source
        proj_data = projection_map.get(row_dict['player_lookup'])
        if proj_data:
            line = float(pred.get('line_value') or 0)
            nf_pts = proj_data.get('numberfire')
            fp_pts = proj_data.get('fantasypros')
            dff_pts = proj_data.get('dailyfantasyfuel')
            dm_pts = proj_data.get('dimers')
            espn_pts = proj_data.get('espn')
            pred['numberfire_projected_points'] = nf_pts
            pred['fantasypros_projected_points'] = fp_pts
            pred['dailyfantasyfuel_projected_points'] = dff_pts
            pred['dimers_projected_points'] = dm_pts
            pred['espn_projected_points'] = espn_pts

            sources_above = 0
            sources_below = 0
            total_sources = 0
            for pts in [nf_pts, fp_pts, dff_pts, dm_pts, espn_pts]:
                if pts is not None and line > 0:
                    total_sources += 1
                    if pts > line:
                        sources_above += 1
                    elif pts < line:
                        sources_below += 1
            pred['projection_sources_above_line'] = sources_above
            pred['projection_sources_below_line'] = sources_below
            pred['projection_sources_total'] = total_sources
        else:
            pred['projection_sources_total'] = 0
            pred['projection_sources_above_line'] = 0
            pred['projection_sources_below_line'] = 0

        # Session 401: Predicted game pace from TeamRankings
        team_pace = team_pace_map.get(pred.get('team_abbr'))
        opp_pace = team_pace_map.get(opponent)
        pred['team_predicted_pace'] = team_pace
        pred['opponent_predicted_pace'] = opp_pace
        if team_pace and opp_pace:
            pred['predicted_game_pace'] = (team_pace + opp_pace) / 2.0
        else:
            pred['predicted_game_pace'] = None

        # Session 401: DvP data for opponent's defense vs player position
        opp_dvp = dvp_map.get(opponent, {})
        # We don't have player position in the main query, so check ALL position
        # or use the best available position data
        if opp_dvp:
            # Use "ALL" position if available, otherwise check common positions
            best_dvp = opp_dvp.get('ALL', {})
            pred['opponent_dvp_rank'] = best_dvp.get('rank')
            pred['opponent_dvp_points_allowed'] = best_dvp.get('points_allowed')
        else:
            pred['opponent_dvp_rank'] = None
            pred['opponent_dvp_points_allowed'] = None

        # Session 401: CLV data
        clv_data = clv_map.get(row_dict['player_lookup'])
        if clv_data:
            pred['closing_line_value'] = clv_data['clv']
            pred['opening_line'] = clv_data['opening_line']
            pred['closing_line'] = clv_data['closing_line']
        else:
            pred['closing_line_value'] = None

        # Session 462: BettingPros line movement
        bp_lm = bp_line_movement_map.get(row_dict['player_lookup'])
        pred['bp_line_movement'] = float(bp_lm) if bp_lm is not None else None

        # Session 462: Copy shooting stats to pred dict for new signals/observation filters
        pred['fg_pct_last_3'] = float(row_dict['fg_pct_last_3']) if row_dict.get('fg_pct_last_3') is not None else None
        pred['fg_pct_season'] = float(row_dict['fg_pct_season']) if row_dict.get('fg_pct_season') is not None else None
        pred['three_pct_last_3'] = float(row_dict['three_pct_last_3']) if row_dict.get('three_pct_last_3') is not None else None
        pred['three_pct_season'] = float(row_dict['three_pct_season']) if row_dict.get('three_pct_season') is not None else None

        # Compute consecutive negative +/- streak for pre-filter (Session 294)
        # neg_3plus + UNDER = 13.1% HR (N=84) — catastrophic anti-pattern
        neg_pm_streak = 0
        for lag_val in [row_dict.get('neg_pm_1'), row_dict.get('neg_pm_2'), row_dict.get('neg_pm_3')]:
            if lag_val == 1:
                neg_pm_streak += 1
            else:
                break
        if neg_pm_streak > 0:
            pred['neg_pm_streak'] = neg_pm_streak

        # Session 404: VSiN sharp money data — game-level handle vs ticket divergence.
        # Join via away_team/home_team from game_id parts.
        if len(parts) >= 3:
            vsin_data = vsin_map.get((parts[1], parts[2]))
            if vsin_data:
                pred['vsin_over_money_pct'] = vsin_data['over_money_pct']
                pred['vsin_under_money_pct'] = vsin_data['under_money_pct']
                pred['vsin_over_ticket_pct'] = vsin_data['over_ticket_pct']
                pred['vsin_under_ticket_pct'] = vsin_data['under_ticket_pct']
            else:
                pred['vsin_over_money_pct'] = None
        else:
            pred['vsin_over_money_pct'] = None

        # Session 404: RotoWire projected minutes for minutes_surge_over signal.
        rw_minutes = rotowire_minutes_map.get(row_dict['player_lookup'])
        pred['rotowire_projected_minutes'] = rw_minutes
        # Compare to season avg from player_profile
        season_minutes = supp.get('minutes_stats', {}).get('minutes_avg_season')
        if rw_minutes and season_minutes and season_minutes > 0:
            pred['minutes_projection_delta'] = rw_minutes - season_minutes
        else:
            pred['minutes_projection_delta'] = None

        supplemental_map[row_dict['player_lookup']] = supp

    return predictions, supplemental_map


def query_streak_data(
    bq_client: bigquery.Client,
    start_date: str,
    end_date: str,
    system_id: Optional[str] = None,
) -> Dict[str, Dict]:
    """Query consecutive line beats/misses for each player-game.

    Args:
        bq_client: BigQuery client.
        start_date: Start date for streak calculation window.
        end_date: End date for streak calculation window.
        system_id: Model to query streak data for. Defaults to best bets model.

    Returns:
        Dict keyed by 'player_lookup::game_date' with streak information.
    """
    model_id = system_id or get_best_bets_model_id()
    query = f"""
    WITH graded_predictions AS (
      SELECT
        pa.player_lookup,
        pa.game_date,
        pa.prediction_correct,
        pa.actual_points,
        pa.line_value,
        CASE
          WHEN pa.actual_points > pa.line_value THEN 'OVER'
          WHEN pa.actual_points < pa.line_value THEN 'UNDER'
          ELSE 'PUSH'
        END as actual_direction
      FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
      WHERE pa.game_date BETWEEN DATE_SUB(@start_date, INTERVAL 30 DAY) AND @end_date
        AND pa.system_id = '{model_id}'
        AND pa.prediction_correct IS NOT NULL
        AND pa.is_voided IS NOT TRUE
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY pa.player_lookup, pa.game_id
        ORDER BY pa.graded_at DESC
      ) = 1
    ),

    streak_calc AS (
      SELECT
        player_lookup,
        game_date,
        prediction_correct,
        actual_direction,

        -- Count consecutive beats (looking back, excluding current game)
        SUM(CASE WHEN prediction_correct THEN 1 ELSE 0 END)
          OVER (
            PARTITION BY player_lookup
            ORDER BY game_date
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
          ) as total_beats_last_10,

        -- Count consecutive misses (looking back, excluding current game)
        SUM(CASE WHEN NOT prediction_correct THEN 1 ELSE 0 END)
          OVER (
            PARTITION BY player_lookup
            ORDER BY game_date
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
          ) as total_misses_last_10,

        -- Get last 10 results as array to calculate true consecutive streaks
        ARRAY_AGG(prediction_correct)
          OVER (
            PARTITION BY player_lookup
            ORDER BY game_date
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
          ) as last_10_results,

        ARRAY_AGG(actual_direction)
          OVER (
            PARTITION BY player_lookup
            ORDER BY game_date
            ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
          ) as last_10_directions

      FROM graded_predictions
    )

    SELECT
      player_lookup,
      game_date,
      total_beats_last_10,
      total_misses_last_10,
      last_10_results,
      last_10_directions
    FROM streak_calc
    WHERE game_date >= @start_date
    ORDER BY player_lookup, game_date
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('start_date', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end_date', 'DATE', end_date),
        ]
    )

    rows = bq_client.query(query, job_config=job_config).result(timeout=60)

    streak_map: Dict[str, Dict] = {}

    for row in rows:
        row_dict = dict(row)
        key = f"{row_dict['player_lookup']}::{row_dict['game_date']}"

        # Calculate consecutive streaks from the arrays
        last_10_results = row_dict.get('last_10_results', [])
        last_10_directions = row_dict.get('last_10_directions', [])

        # Count consecutive beats (from most recent backwards)
        consecutive_beats = 0
        if last_10_results:
            for result in reversed(last_10_results):
                if result is True:
                    consecutive_beats += 1
                else:
                    break

        # Count consecutive misses (from most recent backwards)
        consecutive_misses = 0
        last_miss_direction = None
        if last_10_results and last_10_directions:
            for i, result in enumerate(reversed(last_10_results)):
                if result is False:
                    consecutive_misses += 1
                    if i < len(last_10_directions):
                        last_miss_direction = list(reversed(last_10_directions))[i]
                else:
                    break

        streak_map[key] = {
            'consecutive_line_beats': consecutive_beats,
            'consecutive_line_misses': consecutive_misses,
            'last_miss_direction': last_miss_direction,
            'total_beats_last_10': row_dict.get('total_beats_last_10', 0),
            'total_misses_last_10': row_dict.get('total_misses_last_10', 0)
        }

    logger.info(f"Loaded streak data for {len(streak_map)} player-games")
    return streak_map


# Module-level cache for games_vs_opponent (keyed by target_date)
_gvo_cache: Dict[str, Dict[tuple, int]] = {}


def query_games_vs_opponent(
    bq_client: bigquery.Client,
    target_date: str,
) -> Dict[tuple, int]:
    """Query season games played per player-opponent pair.

    Returns dict keyed by (player_lookup, opponent_team_abbr) -> count.
    Used by avoid-familiar filter in aggregator (Session 284).

    Results are cached per target_date within the same process.
    """
    if target_date in _gvo_cache:
        logger.info(f"games_vs_opponent cache hit for {target_date}")
        return _gvo_cache[target_date]

    query = f"""
    SELECT player_lookup, opponent_team_abbr, COUNT(*) as games_played
    FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
    WHERE game_date >= '2025-10-22'
      AND game_date < @target_date
      AND minutes_played > 0
    GROUP BY 1, 2
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    result = bq_client.query(query, job_config=job_config).result(timeout=60)

    gvo_map: Dict[tuple, int] = {}
    for row in result:
        gvo_map[(row.player_lookup, row.opponent_team_abbr)] = row.games_played

    logger.info(f"Loaded games_vs_opponent for {len(gvo_map)} player-opponent pairs")
    _gvo_cache[target_date] = gvo_map
    return gvo_map
