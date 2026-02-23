"""Model-Direction Affinity — blocks known-bad model+direction+edge combos.

Data analysis (Jan 9 - Feb 22) shows each model family has distinct direction
tendencies:
  - V9: OVER specialist — OVER 5-7 edge: 63.9%, OVER 7+: 66.7%.
    UNDER 7+: 39.3% (disaster)
  - V12 noveg: UNDER specialist — UNDER 3-5: 56.1%, UNDER 5-7: 66.7%.
    OVER 3-5: 50.0%
  - V12+vegas: UNDER only — UNDER 3-5: 65.0%. OVER 3-5: 30.8% (terrible)

Phase 1 (observation mode): Computes affinities and logs what would be blocked,
but does not actually block (BLOCK_THRESHOLD_HR = 0.0).

Phase 2 (active blocking): Set BLOCK_THRESHOLD_HR = 45.0 to start blocking.

Single public function: compute_model_direction_affinities().
Non-blocking: catches all exceptions, returns empty results on failure.

Created: 2026-02-22 (Session 330)
"""

import logging
from datetime import date
from typing import Any, Dict, Optional, Set, Tuple

from google.cloud import bigquery

from shared.config.nba_season_dates import get_season_start_date, get_season_year_from_date

logger = logging.getLogger(__name__)

# Phase 1: observation mode — set to 0.0 so nothing is blocked
# Phase 2: set to 45.0 (below breakeven after vig) to activate blocking
BLOCK_THRESHOLD_HR = 0.0

# Minimum graded picks in a combo before it can be flagged
MIN_SAMPLE_SIZE = 15

# Edge band boundaries
EDGE_BANDS = [
    ('3_5', 3.0, 5.0),
    ('5_7', 5.0, 7.0),
    ('7_plus', 7.0, float('inf')),
]


def get_affinity_group(source_model_family: str) -> Optional[str]:
    """Map a source_model_family key to an affinity group.

    Affinity groups collapse the 10+ model families into 3 behavioral groups
    based on direction performance patterns.

    Args:
        source_model_family: Family key from cross_model_subsets
            (e.g. 'v9_mae', 'v12_mae', 'v12_q43').

    Returns:
        Affinity group: 'v9', 'v12_noveg', or 'v12_vegas'. None if unrecognized.
    """
    if not source_model_family:
        return None

    # V9 family — all V9 variants share the same direction tendencies
    if source_model_family.startswith('v9'):
        return 'v9'

    # V12 noveg — uses v12_noveg feature set (no vegas features)
    # Includes: v12_q43, v12_q45 (noveg quantile models)
    if source_model_family in ('v12_q43', 'v12_q45'):
        return 'v12_noveg'

    # V12+vegas — uses full v12 feature set (includes vegas)
    # Includes: v12_mae, v12_vegas_q43, v12_vegas_q45
    if source_model_family in ('v12_mae', 'v12_vegas_q43', 'v12_vegas_q45'):
        return 'v12_vegas'

    return None


def _get_affinity_group_from_system_id(system_id: str) -> Optional[str]:
    """Map a system_id directly to an affinity group.

    Used by the BQ query classification since prediction_accuracy stores
    system_id, not family keys.

    Args:
        system_id: e.g. 'catboost_v9', 'catboost_v12_noveg_q43_train...'

    Returns:
        Affinity group: 'v9', 'v12_noveg', or 'v12_vegas'. None if unrecognized.
    """
    if not system_id:
        return None

    # V9 family
    if system_id.startswith('catboost_v9'):
        return 'v9'

    # V12 noveg — explicit noveg prefix or noveg quantile variants
    if system_id.startswith('catboost_v12_noveg'):
        return 'v12_noveg'

    # V12+vegas — remaining v12 models (catboost_v12 without noveg)
    if system_id.startswith('catboost_v12'):
        return 'v12_vegas'

    return None


def _classify_edge_band(edge: float) -> Optional[str]:
    """Classify an edge value into a band.

    Args:
        edge: Absolute edge value.

    Returns:
        Band label: '3_5', '5_7', or '7_plus'. None if below 3.
    """
    abs_edge = abs(edge)
    for band_label, low, high in EDGE_BANDS:
        if low <= abs_edge < high:
            return band_label
    return None


def check_model_direction_block(
    source_family: str,
    direction: str,
    edge: float,
    blocked_combos: Set[tuple],
) -> Optional[str]:
    """Check if a model+direction+edge combo should be blocked.

    O(1) set lookup.

    Args:
        source_family: Model family key (e.g. 'v9_mae', 'v12_mae').
        direction: 'OVER' or 'UNDER'.
        edge: Absolute edge value.
        blocked_combos: Set of (affinity_group, direction, edge_band) tuples.

    Returns:
        Block reason string if blocked, None if allowed.
    """
    if not blocked_combos:
        return None

    group = get_affinity_group(source_family)
    if not group:
        return None

    band = _classify_edge_band(abs(edge))
    if not band:
        return None

    combo = (group, direction, band)
    if combo in blocked_combos:
        return f"model_direction_affinity: {group} {direction} edge {band}"

    return None


def compute_model_direction_affinities(
    bq_client: bigquery.Client,
    target_date: str,
    project_id: str = 'nba-props-platform',
    lookback_days: int = 45,
    block_threshold_hr: float = BLOCK_THRESHOLD_HR,
    min_sample_size: int = MIN_SAMPLE_SIZE,
) -> Tuple[Dict[str, Any], Set[tuple], Dict[str, Any]]:
    """Compute model-direction affinities from graded prediction history.

    Queries prediction_accuracy for all system_ids, groups by affinity_group
    + direction + edge_band, and identifies combos with hit rates below
    the blocking threshold.

    Args:
        bq_client: BigQuery client.
        target_date: Date string YYYY-MM-DD (query up to day before).
        project_id: GCP project ID.
        lookback_days: Number of days to look back for grading data.
        block_threshold_hr: HR below which a combo is blocked.
        min_sample_size: Minimum graded picks for a combo to be evaluated.

    Returns:
        Tuple of (affinities_dict, blocked_combos_set, stats_dict):
            affinities_dict: Nested dict {group: {direction: {band: {hr, n, ...}}}}.
            blocked_combos_set: Set of (group, direction, band) tuples to block.
            stats_dict: Summary for JSON output.
    """
    empty_result = ({}, set(), {
        'lookback_days': lookback_days,
        'block_threshold_hr': block_threshold_hr,
        'min_sample_size': min_sample_size,
        'combos_evaluated': 0,
        'combos_blocked': 0,
        'blocked_list': [],
        'observation_mode': block_threshold_hr <= 0,
    })

    try:
        target = date.fromisoformat(target_date) if isinstance(target_date, str) else target_date

        query = f"""
        WITH classified AS (
            SELECT
                system_id,
                recommendation,
                ABS(predicted_points - line_value) AS edge,
                prediction_correct,
                CASE
                    WHEN system_id LIKE 'catboost_v9%' THEN 'v9'
                    WHEN system_id LIKE 'catboost_v12_noveg%' THEN 'v12_noveg'
                    WHEN system_id LIKE 'catboost_v12%' THEN 'v12_vegas'
                    ELSE NULL
                END AS affinity_group
            FROM `{project_id}.nba_predictions.prediction_accuracy`
            WHERE game_date >= DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
              AND game_date < @target_date
              AND ABS(predicted_points - line_value) >= 3
              AND is_voided = FALSE
              AND recommendation IN ('OVER', 'UNDER')
        ),
        banded AS (
            SELECT
                affinity_group,
                recommendation AS direction,
                CASE
                    WHEN edge >= 7.0 THEN '7_plus'
                    WHEN edge >= 5.0 THEN '5_7'
                    WHEN edge >= 3.0 THEN '3_5'
                END AS edge_band,
                prediction_correct
            FROM classified
            WHERE affinity_group IS NOT NULL
        )
        SELECT
            affinity_group,
            direction,
            edge_band,
            COUNT(*) AS total_picks,
            COUNTIF(prediction_correct = TRUE) AS wins,
            COUNTIF(prediction_correct = FALSE) AS losses,
            ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) AS hit_rate
        FROM banded
        GROUP BY affinity_group, direction, edge_band
        HAVING COUNT(*) >= @min_sample_size
        ORDER BY affinity_group, direction, edge_band
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
                bigquery.ScalarQueryParameter('lookback_days', 'INT64', lookback_days),
                bigquery.ScalarQueryParameter('min_sample_size', 'INT64', min_sample_size),
            ]
        )

        result = bq_client.query(query, job_config=job_config).result(timeout=60)
        rows = [dict(row) for row in result]

        # Build affinities dict
        affinities: Dict[str, Any] = {}
        blocked_combos: Set[tuple] = set()
        blocked_list = []
        would_block_list = []

        for row in rows:
            group = row['affinity_group']
            direction = row['direction']
            band = row['edge_band']
            hr = float(row['hit_rate'])
            n = row['total_picks']

            # Nested dict: {group: {direction: {band: stats}}}
            if group not in affinities:
                affinities[group] = {}
            if direction not in affinities[group]:
                affinities[group][direction] = {}

            combo_stats = {
                'hit_rate': hr,
                'total_picks': n,
                'wins': row['wins'],
                'losses': row['losses'],
            }
            affinities[group][direction][band] = combo_stats

            # Check if this combo should be blocked
            if hr < block_threshold_hr:
                blocked_combos.add((group, direction, band))
                blocked_list.append({
                    'group': group,
                    'direction': direction,
                    'edge_band': band,
                    'hit_rate': hr,
                    'total_picks': n,
                })

            # Log what WOULD be blocked at production threshold (45%)
            if hr < 45.0:
                would_block_list.append({
                    'group': group,
                    'direction': direction,
                    'edge_band': band,
                    'hit_rate': hr,
                    'total_picks': n,
                })

        stats = {
            'lookback_days': lookback_days,
            'block_threshold_hr': block_threshold_hr,
            'min_sample_size': min_sample_size,
            'combos_evaluated': len(rows),
            'combos_blocked': len(blocked_combos),
            'blocked_list': blocked_list,
            'would_block_at_45': would_block_list,
            'observation_mode': block_threshold_hr <= 0,
        }

        # Log summary
        if would_block_list:
            would_block_str = ', '.join(
                f"{b['group']} {b['direction']} {b['edge_band']}: {b['hit_rate']}% ({b['total_picks']})"
                for b in would_block_list
            )
            logger.info(
                f"Model-direction affinity: {len(rows)} combos evaluated, "
                f"{len(blocked_combos)} blocked (threshold={block_threshold_hr}%). "
                f"Would block at 45%: {would_block_str}"
            )
        else:
            logger.info(
                f"Model-direction affinity: {len(rows)} combos evaluated, "
                f"0 would be blocked at 45%"
            )

        return affinities, blocked_combos, stats

    except Exception as e:
        logger.warning(f"Model-direction affinity computation failed (non-fatal): {e}")
        return empty_result
