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
    )

    SELECT
      p.*,
      ls.three_pct_last_3,
      ls.three_pct_season,
      ls.three_pct_std,
      ls.three_pa_per_game,
      ls.minutes_avg_last_3,
      ls.minutes_avg_season
    FROM preds p
    LEFT JOIN latest_stats ls ON ls.player_lookup = p.player_lookup
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

        supplemental_map[row_dict['player_lookup']] = supp

    return predictions, supplemental_map
