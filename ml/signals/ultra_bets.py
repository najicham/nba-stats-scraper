"""Ultra Bets — high-confidence pick classification layer.

Classifies best bets picks into an "Ultra" tier based on criteria
discovered in Session 326 backtesting. Ultra is a label ON TOP of
best bets (not a separate exporter). Each pick is checked against
hardcoded criteria; matches are returned with backtest HR and sample size.

Criteria HRs are from Session 326 backtest (Jan 9 - Feb 21, 2026).
Update manually after retrains.

Live HR tracking added Session 327: compute_ultra_live_hrs() queries
graded picks after BACKTEST_END to track real-world performance.
Ultra data is internal-only (BQ); stripped from public JSON export.

Created: 2026-02-22 (Session 326)
Updated: 2026-02-22 (Session 327 — live HR, internal-only)
"""

import logging
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Backtest window. Live HR queries start after BACKTEST_END.
# Update both after re-validation backtests.
BACKTEST_START = '2026-01-09'
BACKTEST_END = '2026-02-21'

# Each criterion: id, description, backtest_hr, backtest_n, backtest_period, backtest_date
ULTRA_CRITERIA = [
    {
        'id': 'v12_edge_6plus',
        'description': 'V12+vegas model, edge >= 6',
        'backtest_hr': 100.0,
        'backtest_n': 26,
        'backtest_period': '2026-01-09 to 2026-02-21',
        'backtest_date': '2026-02-22',
    },
    {
        'id': 'v12_over_edge_5plus',
        'description': 'V12+vegas OVER, edge >= 5',
        'backtest_hr': 100.0,
        'backtest_n': 18,
        'backtest_period': '2026-01-09 to 2026-02-21',
        'backtest_date': '2026-02-22',
    },
    # consensus_3plus_edge_5plus REMOVED (Session 327): 0 live picks ever fired.
    {
        'id': 'v12_edge_4_5plus',
        'description': 'V12+vegas model, edge >= 4.5',
        'backtest_hr': 77.2,
        'backtest_n': 57,
        'backtest_period': '2026-01-09 to 2026-02-21',
        'backtest_date': '2026-02-22',
    },
]


def parse_ultra_criteria(raw) -> list:
    """Parse ultra_criteria from BQ (stored as JSON string) into a list."""
    import json
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(raw, list):
        return raw
    return []


def _check_criterion(criterion_id: str, pick: Dict[str, Any]) -> bool:
    """Check if a pick matches a specific ultra criterion."""
    source_family = pick.get('source_model_family', '')
    edge = abs(pick.get('edge') or 0)
    direction = pick.get('recommendation', '')
    model_agreement = pick.get('model_agreement_count', 0)

    if criterion_id == 'v12_edge_6plus':
        return source_family.startswith('v12') and edge >= 6.0

    if criterion_id == 'v12_over_edge_5plus':
        return source_family.startswith('v12') and direction == 'OVER' and edge >= 5.0

    # consensus_3plus_edge_5plus REMOVED (Session 327)

    if criterion_id == 'v12_edge_4_5plus':
        return source_family.startswith('v12') and edge >= 4.5

    return False


def classify_ultra_pick(pick: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Classify a pick against all ultra criteria.

    Args:
        pick: Pick dict from aggregator (needs source_model_family, edge,
              recommendation, model_agreement_count).

    Returns:
        List of matched criteria dicts with id, description, backtest_hr,
        backtest_n, backtest_period, backtest_date. Empty list if no
        criteria match.
    """
    matched = []
    for criterion in ULTRA_CRITERIA:
        if _check_criterion(criterion['id'], pick):
            matched.append({
                'id': criterion['id'],
                'description': criterion['description'],
                'backtest_hr': criterion['backtest_hr'],
                'backtest_n': criterion['backtest_n'],
                'backtest_period': criterion['backtest_period'],
                'backtest_date': criterion['backtest_date'],
            })
    return matched


def check_ultra_over_gate(
    bq_client: bigquery.Client,
    project_id: str = 'nba-props-platform',
) -> Dict[str, Any]:
    """Check if the OVER ultra gate has been met for public exposure.

    Gate: graded ultra OVER picks >= 50 AND HR >= 80%.

    Returns:
        Dict with 'gate_met' (bool), 'n' (int), 'hr' (float or None).
    """
    TARGET_N = 50
    TARGET_HR = 80.0

    query = f"""
    SELECT
      COUNT(*) AS n,
      COUNTIF(prediction_correct = TRUE) AS wins
    FROM `{project_id}.nba_predictions.signal_best_bets_picks`
    WHERE game_date >= '{BACKTEST_START}'
      AND ultra_tier = TRUE
      AND recommendation = 'OVER'
      AND prediction_correct IS NOT NULL
    """

    try:
        rows = list(bq_client.query(query).result(timeout=30))
        if rows and rows[0].n > 0:
            n = rows[0].n
            hr = round(100.0 * rows[0].wins / n, 1)
            gate_met = n >= TARGET_N and hr >= TARGET_HR
            logger.info(
                f"Ultra OVER gate: N={n}, HR={hr}%, "
                f"gate_met={gate_met} (need N>={TARGET_N}, HR>={TARGET_HR}%)"
            )
            return {'gate_met': gate_met, 'n': n, 'hr': hr}
    except Exception as e:
        logger.warning(f"Ultra OVER gate check failed (non-fatal): {e}")

    return {'gate_met': False, 'n': 0, 'hr': None}


def compute_ultra_live_hrs(
    bq_client: bigquery.Client,
    project_id: str = 'nba-props-platform',
) -> Dict[str, Dict[str, Any]]:
    """Compute live hit rates for each ultra criterion from graded picks.

    Queries signal_best_bets_picks for rows after BACKTEST_END that have
    ultra_tier=TRUE and prediction_correct IS NOT NULL. Extracts criterion
    IDs from the ultra_criteria JSON array and computes per-criterion stats.

    Args:
        bq_client: BigQuery client.
        project_id: GCP project ID.

    Returns:
        Dict mapping criterion_id to {'live_hr': float, 'live_n': int}.
        Empty dict if no graded ultra picks exist yet.
    """
    query = f"""
    SELECT
      JSON_EXTRACT_SCALAR(criteria, '$.id') AS criterion_id,
      COUNT(*) AS live_n,
      COUNTIF(prediction_correct = TRUE) AS live_wins
    FROM `{project_id}.nba_predictions.signal_best_bets_picks`,
    UNNEST(JSON_EXTRACT_ARRAY(ultra_criteria, '$')) AS criteria
    WHERE game_date > @backtest_end
      AND ultra_tier = TRUE
      AND prediction_correct IS NOT NULL
    GROUP BY criterion_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('backtest_end', 'DATE', BACKTEST_END),
        ]
    )

    try:
        rows = bq_client.query(query, job_config=job_config).result(timeout=30)
        result = {}
        for row in rows:
            cid = row.criterion_id
            if cid and row.live_n > 0:
                result[cid] = {
                    'live_hr': round(100.0 * row.live_wins / row.live_n, 1),
                    'live_n': row.live_n,
                }
        logger.info(f"Ultra live HRs (post {BACKTEST_END}): {result}")
        return result
    except Exception as e:
        logger.warning(f"Failed to compute ultra live HRs (non-fatal): {e}")
        return {}
