"""Shared supplemental data queries for signal evaluation.

Provides the BigQuery queries and row-parsing logic needed to build
the supplemental dicts that signals require (3PT stats, minutes stats,
model health). Used by both SignalBestBetsExporter and SignalAnnotator
to avoid duplicating the 50-line SQL.
"""

import logging
from typing import Any, Dict, List, Tuple

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
SYSTEM_ID = 'catboost_v9'


def query_model_health(bq_client: bigquery.Client) -> Dict[str, Any]:
    """Query rolling 7-day hit rate for edge 3+ picks.

    Returns:
        Dict with hit_rate_7d_edge3 (float or None), graded_count (int).
    """
    query = f"""
    SELECT
      COUNTIF(prediction_correct) as wins,
      COUNT(*) as graded_count,
      ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1)
        AS hit_rate_7d_edge3
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
      AND game_date < CURRENT_DATE()
      AND system_id = '{SYSTEM_ID}'
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
) -> Tuple[List[Dict], Dict[str, Dict]]:
    """Query active predictions with supplemental signal data.

    Returns:
        Tuple of (predictions list, supplemental_map keyed by player_lookup).
    """
    query = f"""
    WITH preds AS (
      SELECT
        p.player_lookup,
        p.game_id,
        p.game_date,
        p.system_id,
        p.player_name,
        p.team_abbr,
        p.opponent_team_abbr,
        CAST(p.predicted_points AS FLOAT64) AS predicted_points,
        CAST(p.line_value AS FLOAT64) AS line_value,
        p.recommendation,
        CAST(p.predicted_points - p.line_value AS FLOAT64) AS edge,
        CAST(p.confidence_score AS FLOAT64) AS confidence_score
      FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions` p
      WHERE p.game_date = @target_date
        AND p.system_id = '{SYSTEM_ID}'
        AND p.is_active = TRUE
        AND p.recommendation IN ('OVER', 'UNDER')
        AND p.line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
    ),

    -- Rolling stats for 3PT and minutes signals
    game_stats AS (
      SELECT
        player_lookup,
        game_date,
        minutes_played,
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
                ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS minutes_avg_season
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

    -- Streak data: prior actual over/under outcomes (for cold_snap signal)
    streak_data AS (
      SELECT
        player_lookup,
        game_date,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 1) OVER w AS prev_over_1,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 2) OVER w AS prev_over_2,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 3) OVER w AS prev_over_3,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 4) OVER w AS prev_over_4,
        LAG(CASE WHEN actual_points > line_value THEN 1 ELSE 0 END, 5) OVER w AS prev_over_5
      FROM (
        SELECT *
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '2025-10-22'
          AND system_id = '{SYSTEM_ID}'
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
    )

    SELECT
      p.*,
      ls.three_pct_last_3,
      ls.three_pct_season,
      ls.three_pct_std,
      ls.three_pa_per_game,
      ls.minutes_avg_last_3,
      ls.minutes_avg_season,
      ls.minutes_played AS prev_minutes,
      DATE_DIFF(@target_date, ls.game_date, DAY) AS rest_days,
      lsk.prev_over_1, lsk.prev_over_2, lsk.prev_over_3,
      lsk.prev_over_4, lsk.prev_over_5
    FROM preds p
    LEFT JOIN latest_stats ls ON ls.player_lookup = p.player_lookup
    LEFT JOIN latest_streak lsk ON lsk.player_lookup = p.player_lookup
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
        pred = {
            'player_lookup': row_dict['player_lookup'],
            'game_id': row_dict['game_id'],
            'game_date': row_dict['game_date'],
            'system_id': row_dict['system_id'],
            'player_name': row_dict.get('player_name', ''),
            'team_abbr': row_dict.get('team_abbr', ''),
            'opponent_team_abbr': row_dict.get('opponent_team_abbr', ''),
            'predicted_points': row_dict['predicted_points'],
            'line_value': row_dict['line_value'],
            'recommendation': row_dict['recommendation'],
            'edge': row_dict['edge'],
            'confidence_score': row_dict['confidence_score'],
        }
        predictions.append(pred)

        supp: Dict[str, Any] = {}

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

        # Streak stats (for cold_snap)
        if row_dict.get('prev_over_1') is not None:
            supp['streak_stats'] = {
                'prev_correct': [],  # not available in production query
                'prev_over': [
                    row_dict.get('prev_over_1'),
                    row_dict.get('prev_over_2'),
                    row_dict.get('prev_over_3'),
                    row_dict.get('prev_over_4'),
                    row_dict.get('prev_over_5'),
                ],
            }

        # Recovery stats (for blowout_recovery)
        if (row_dict.get('prev_minutes') is not None
                and row_dict.get('minutes_avg_season') is not None):
            supp['recovery_stats'] = {
                'prev_minutes': float(row_dict['prev_minutes']),
                'minutes_avg_season': float(row_dict['minutes_avg_season']),
            }

        # Rest stats (for future signals)
        if row_dict.get('rest_days') is not None:
            supp['rest_stats'] = {
                'rest_days': int(row_dict['rest_days']),
            }

        supplemental_map[row_dict['player_lookup']] = supp

    return predictions, supplemental_map


def query_streak_data(
    bq_client: bigquery.Client,
    start_date: str,
    end_date: str
) -> Dict[str, Dict]:
    """Query consecutive line beats/misses for each player-game.

    Returns:
        Dict keyed by 'player_lookup::game_date' with streak information.
    """
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
        AND pa.system_id = '{SYSTEM_ID}'
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
