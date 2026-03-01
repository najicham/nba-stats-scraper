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
) -> Tuple[List[Dict], Dict[str, Dict]]:
    """Query active predictions with supplemental signal data.

    Args:
        bq_client: BigQuery client.
        target_date: Date string in YYYY-MM-DD format.
        system_id: Model to query predictions for. Defaults to best bets model.
        multi_model: If True, query all CatBoost families and pick highest-edge
            prediction per player. Adds source_model_id, n_models_eligible,
            champion_edge, direction_conflict to each prediction dict.

    Returns:
        Tuple of (predictions list, supplemental_map keyed by player_lookup).
    """
    model_id = system_id or get_best_bets_model_id()

    if multi_model:
        system_filter = build_system_id_sql_filter('p')
        preds_cte = f"""
    -- Session 366: Model HR weight with post-filter fallback chain.
    -- Priority: best-bets HR (21d, N>=8) → raw HR (14d, N>=10) → 50% default.
    -- Self-bootstrapping: new models use raw HR until they accumulate 8+ best-bets picks.
    WITH model_hr AS (
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
      WHERE p.game_date = @target_date
        AND {system_filter}
        AND p.is_active = TRUE
        AND p.recommendation IN ('OVER', 'UNDER')
        AND p.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
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
        preds_cte = f"""
    WITH preds AS (
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
      WHERE p.game_date = @target_date
        AND p.system_id = '{model_id}'
        AND p.is_active = TRUE
        AND p.recommendation IN ('OVER', 'UNDER')
        AND p.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
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
        AND p2.recommendation IN ('OVER', 'UNDER')
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY p2.player_lookup, p2.game_id ORDER BY p2.system_id DESC
      ) = 1
    ),

    -- Multi-book line std, teammate_usage, star_teammates_out, prop_under_streak for signals (Session 303, 355, 367, 371)
    book_stats AS (
      SELECT
        player_lookup,
        game_date,
        feature_50_value AS multi_book_line_std,
        feature_50_source AS book_std_source,
        feature_47_value AS teammate_usage_available,
        feature_37_value AS star_teammates_out,
        feature_52_value AS prop_under_streak,
        feature_42_value AS implied_team_total
      FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
      WHERE game_date = @target_date
    ),

    -- Previous game prop line for line delta signal (Session 294)
    -- Gets the most recent previous line for each player from the same model
    prev_prop_lines AS (
      SELECT
        pp.player_lookup,
        CAST(pp.current_points_line AS FLOAT64) AS prev_line_value,
        pp.game_date AS prev_line_date
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` pp
      WHERE pp.game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
        AND pp.game_date < @target_date
        AND pp.system_id = '{model_id}'
        AND pp.is_active = TRUE
        AND pp.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY pp.player_lookup ORDER BY pp.game_date DESC
      ) = 1
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
      bs.implied_team_total
    FROM preds p
    LEFT JOIN latest_stats ls ON ls.player_lookup = p.player_lookup
    LEFT JOIN latest_streak lsk ON lsk.player_lookup = p.player_lookup
    LEFT JOIN v12_preds v12 ON v12.player_lookup = p.player_lookup AND v12.game_id = p.game_id
    LEFT JOIN prev_prop_lines ppl ON ppl.player_lookup = p.player_lookup
    LEFT JOIN book_stats bs ON bs.player_lookup = p.player_lookup AND bs.game_date = p.game_date
    ORDER BY p.player_lookup
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    rows = bq_client.query(query, job_config=job_config).result(timeout=60)

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

        # Multi-source attribution (Session 307)
        if multi_model:
            source_sid = row_dict['system_id']
            pred['source_model_id'] = source_sid
            pred['source_model_family'] = classify_system_id(source_sid)
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

        # Copy prop line delta for aggregator pre-filter (Session 294)
        if row_dict.get('prev_line_value') is not None:
            current_line = float(row_dict.get('line_value') or 0)
            prev_line = float(row_dict['prev_line_value'])
            pred['prop_line_delta'] = round(current_line - prev_line, 1)

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
