"""Compute daily per-model performance profiles for model_profile_daily table.

Profiles each model across 6 dimensions (direction, tier, line_range, edge_band,
home_away, signal) using a 14-day rolling window. Used for data-driven per-model
filtering — replaces hardcoded family-level filters with individual model blocks.

Blocking threshold: hr_14d < 45% AND n_14d >= 15 (same as model_direction_affinity).
When individual model has N < 8 in a slice, falls back to affinity_group-level stats.

Usage:
    # Single date (used by Cloud Function)
    PYTHONPATH=. python ml/analysis/model_profile.py --date 2026-03-01

    # Backfill
    PYTHONPATH=. python ml/analysis/model_profile.py --backfill --start 2026-01-30

Created: 2026-03-01 (Session 384)
"""

import argparse
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from google.cloud import bigquery

logger = logging.getLogger(__name__)

TABLE_ID = 'nba-props-platform.nba_predictions.model_profile_daily'

# Blocking thresholds (same as model_direction_affinity)
BLOCK_THRESHOLD_HR = 45.0
MIN_SAMPLE_SIZE = 15

# Minimum individual model N before falling back to affinity group
MIN_MODEL_N = 8


def _build_affinity_group_case() -> str:
    """SQL CASE for classifying system_id into affinity groups."""
    return """
    CASE
        WHEN system_id LIKE 'catboost_v9_low_vegas%' THEN 'v9_low_vegas'
        WHEN system_id LIKE 'catboost_v9%' THEN 'v9'
        WHEN system_id LIKE 'catboost_v12_noveg%' THEN 'v12_noveg'
        WHEN system_id LIKE 'catboost_v16_noveg%' THEN 'v12_noveg'
        WHEN system_id LIKE 'lgbm_v12_noveg%' THEN 'v12_noveg'
        WHEN system_id LIKE 'xgb_v12_noveg%' THEN 'v12_noveg'
        WHEN system_id LIKE 'catboost_v12%' THEN 'v12_vegas'
        ELSE NULL
    END"""


def _build_tier_case() -> str:
    """SQL CASE for classifying line_value into tiers."""
    return """
    CASE
        WHEN line_value < 12 THEN 'bench'
        WHEN line_value < 15 THEN 'role'
        WHEN line_value < 25 THEN 'starter'
        ELSE 'star'
    END"""


def _build_line_range_case() -> str:
    """SQL CASE for classifying line_value into ranges."""
    return """
    CASE
        WHEN line_value < 12 THEN '0_12'
        WHEN line_value < 15 THEN '12_15'
        WHEN line_value < 20 THEN '15_20'
        WHEN line_value < 25 THEN '20_25'
        ELSE '25_plus'
    END"""


def _build_edge_band_case() -> str:
    """SQL CASE for classifying edge into bands."""
    return """
    CASE
        WHEN ABS(predicted_points - line_value) >= 7.0 THEN '7_plus'
        WHEN ABS(predicted_points - line_value) >= 5.0 THEN '5_7'
        WHEN ABS(predicted_points - line_value) >= 3.0 THEN '3_5'
        ELSE NULL
    END"""


def compute_profiles_for_date(
    bq_client: bigquery.Client,
    target_date: date,
    project_id: str = 'nba-props-platform',
) -> List[dict]:
    """Compute per-model profiles across all dimensions for a single date.

    Uses a single BQ query with UNION ALL across dimension slices to minimize
    scans of prediction_accuracy.

    Args:
        bq_client: BigQuery client.
        target_date: Date to compute profiles for.
        project_id: GCP project ID.

    Returns:
        List of row dicts ready for BQ insert.
    """
    from shared.config.cross_model_subsets import build_system_id_sql_filter

    sql_filter = build_system_id_sql_filter()
    affinity_case = _build_affinity_group_case()
    tier_case = _build_tier_case()
    line_range_case = _build_line_range_case()
    edge_band_case = _build_edge_band_case()

    query = f"""
    WITH base AS (
        SELECT
            system_id,
            {affinity_case} AS affinity_group,
            recommendation,
            line_value,
            predicted_points,
            ABS(predicted_points - line_value) AS edge,
            prediction_correct,
            -- Derive is_home from game_id format: YYYYMMDD_AWAY_HOME
            (team_abbr = SPLIT(game_id, '_')[SAFE_OFFSET(2)]) AS is_home
        FROM `{project_id}.nba_predictions.prediction_accuracy`
        WHERE game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
          AND game_date <= @target_date
          AND ABS(predicted_points - line_value) >= 3
          AND {sql_filter}
          AND prediction_correct IS NOT NULL
          AND is_voided IS NOT TRUE
    ),

    -- Best bets data for this window
    bb AS (
        SELECT
            sbp.source_model_id,
            sbp.recommendation,
            sbp.line_value,
            -- Derive is_home from game_id format
            (pa.team_abbr = SPLIT(pa.game_id, '_')[SAFE_OFFSET(2)]) AS is_home,
            pa.prediction_correct,
            ABS(pa.predicted_points - pa.line_value) AS edge,
            pa.predicted_points
        FROM `{project_id}.nba_predictions.signal_best_bets_picks` sbp
        LEFT JOIN `{project_id}.nba_predictions.prediction_accuracy` pa
            ON sbp.player_lookup = pa.player_lookup
            AND sbp.game_date = pa.game_date
            AND sbp.system_id = pa.system_id
            AND pa.is_voided IS NOT TRUE
        WHERE sbp.game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
          AND sbp.game_date <= @target_date
          AND sbp.source_model_id IS NOT NULL
          AND pa.prediction_correct IS NOT NULL
    ),

    -- Signal tags for signal dimension
    signal_base AS (
        SELECT
            pst.system_id,
            tag,
            pa.prediction_correct
        FROM `{project_id}.nba_predictions.pick_signal_tags` pst
        CROSS JOIN UNNEST(pst.signal_tags) AS tag
        JOIN `{project_id}.nba_predictions.prediction_accuracy` pa
            ON pst.player_lookup = pa.player_lookup
            AND pst.game_date = pa.game_date
            AND pst.system_id = pa.system_id
            AND pa.is_voided IS NOT TRUE
        WHERE pst.game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
          AND pst.game_date <= @target_date
          AND pa.prediction_correct IS NOT NULL
          AND ABS(pa.predicted_points - pa.line_value) >= 3
          AND {sql_filter.replace('system_id', 'pst.system_id')}
    ),

    -- Dimension: direction (OVER/UNDER)
    dim_direction AS (
        SELECT
            system_id, affinity_group,
            'direction' AS dimension,
            recommendation AS dimension_value,
            COUNT(*) AS n_14d,
            COUNTIF(prediction_correct) AS wins_14d,
            COUNTIF(NOT prediction_correct) AS losses_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr_14d
        FROM base
        GROUP BY system_id, affinity_group, recommendation
    ),

    -- Dimension: tier (bench/role/starter/star)
    dim_tier AS (
        SELECT
            system_id, affinity_group,
            'tier' AS dimension,
            {tier_case} AS dimension_value,
            COUNT(*) AS n_14d,
            COUNTIF(prediction_correct) AS wins_14d,
            COUNTIF(NOT prediction_correct) AS losses_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr_14d
        FROM base
        GROUP BY system_id, affinity_group, dimension_value
    ),

    -- Dimension: line_range
    dim_line_range AS (
        SELECT
            system_id, affinity_group,
            'line_range' AS dimension,
            {line_range_case} AS dimension_value,
            COUNT(*) AS n_14d,
            COUNTIF(prediction_correct) AS wins_14d,
            COUNTIF(NOT prediction_correct) AS losses_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr_14d
        FROM base
        GROUP BY system_id, affinity_group, dimension_value
    ),

    -- Dimension: edge_band
    dim_edge_band AS (
        SELECT
            system_id, affinity_group,
            'edge_band' AS dimension,
            {edge_band_case} AS dimension_value,
            COUNT(*) AS n_14d,
            COUNTIF(prediction_correct) AS wins_14d,
            COUNTIF(NOT prediction_correct) AS losses_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr_14d
        FROM base
        WHERE {edge_band_case} IS NOT NULL
        GROUP BY system_id, affinity_group, dimension_value
    ),

    -- Dimension: home_away
    dim_home_away AS (
        SELECT
            system_id, affinity_group,
            'home_away' AS dimension,
            CASE WHEN is_home THEN 'HOME' ELSE 'AWAY' END AS dimension_value,
            COUNT(*) AS n_14d,
            COUNTIF(prediction_correct) AS wins_14d,
            COUNTIF(NOT prediction_correct) AS losses_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr_14d
        FROM base
        GROUP BY system_id, affinity_group, dimension_value
    ),

    -- Dimension: signal (per signal tag effectiveness per model)
    dim_signal AS (
        SELECT
            system_id,
            CAST(NULL AS STRING) AS affinity_group,  -- filled in post-processing
            'signal' AS dimension,
            tag AS dimension_value,
            COUNT(*) AS n_14d,
            COUNTIF(prediction_correct) AS wins_14d,
            COUNTIF(NOT prediction_correct) AS losses_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS hr_14d
        FROM signal_base
        GROUP BY system_id, tag
    ),

    -- Best bets by direction (for bb_hr_14d on direction dimension)
    bb_direction AS (
        SELECT
            source_model_id AS system_id,
            'direction' AS dimension,
            recommendation AS dimension_value,
            COUNT(*) AS bb_n_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS bb_hr_14d
        FROM bb
        GROUP BY source_model_id, recommendation
    ),

    -- Best bets by home_away
    bb_home_away AS (
        SELECT
            source_model_id AS system_id,
            'home_away' AS dimension,
            CASE WHEN is_home THEN 'HOME' ELSE 'AWAY' END AS dimension_value,
            COUNT(*) AS bb_n_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS bb_hr_14d
        FROM bb
        GROUP BY source_model_id, dimension_value
    ),

    -- Best bets by tier
    bb_tier AS (
        SELECT
            source_model_id AS system_id,
            'tier' AS dimension,
            {tier_case} AS dimension_value,
            COUNT(*) AS bb_n_14d,
            ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) AS bb_hr_14d
        FROM bb
        GROUP BY source_model_id, dimension_value
    ),

    -- UNION all dimensions
    all_dims AS (
        SELECT * FROM dim_direction
        UNION ALL SELECT * FROM dim_tier
        UNION ALL SELECT * FROM dim_line_range
        UNION ALL SELECT * FROM dim_edge_band
        UNION ALL SELECT * FROM dim_home_away
        UNION ALL SELECT * FROM dim_signal
    ),

    -- UNION all best bets
    all_bb AS (
        SELECT * FROM bb_direction
        UNION ALL SELECT * FROM bb_home_away
        UNION ALL SELECT * FROM bb_tier
    )

    SELECT
        d.system_id,
        d.affinity_group,
        d.dimension,
        d.dimension_value,
        d.hr_14d,
        d.n_14d,
        d.wins_14d,
        d.losses_14d,
        b.bb_hr_14d,
        b.bb_n_14d
    FROM all_dims d
    LEFT JOIN all_bb b
        ON d.system_id = b.system_id
        AND d.dimension = b.dimension
        AND d.dimension_value = b.dimension_value
    ORDER BY d.system_id, d.dimension, d.dimension_value
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    try:
        results = list(bq_client.query(query, job_config=job_config).result(timeout=120))
    except Exception as e:
        logger.error(f"Profile query failed for {target_date}: {e}")
        return []

    if not results:
        logger.warning(f"No profile data found for {target_date}")
        return []

    # Build affinity group lookup for signal dimension rows (which have NULL affinity_group)
    affinity_lookup = {}
    for row in results:
        if row.affinity_group and row.system_id not in affinity_lookup:
            affinity_lookup[row.system_id] = row.affinity_group

    # Also compute affinity group level stats for fallback
    group_stats = _compute_group_fallback_stats(results, affinity_lookup)

    now = datetime.now(timezone.utc)
    rows = []

    for row in results:
        model_id = row.system_id
        aff_group = row.affinity_group or affinity_lookup.get(model_id)
        dimension = row.dimension
        dim_value = row.dimension_value
        hr = row.hr_14d
        n = row.n_14d

        # Fallback: when individual model N < MIN_MODEL_N, use affinity group stats
        used_fallback = False
        if n < MIN_MODEL_N and aff_group:
            group_key = (aff_group, dimension, dim_value)
            if group_key in group_stats:
                gs = group_stats[group_key]
                hr = gs['hr']
                n = gs['n']
                used_fallback = True

        # Determine blocking
        is_blocked = False
        block_reason = None
        if hr is not None and n >= MIN_SAMPLE_SIZE and hr < BLOCK_THRESHOLD_HR:
            is_blocked = True
            source = f"group:{aff_group}" if used_fallback else f"model:{model_id}"
            block_reason = (
                f"{dimension}={dim_value}: {hr:.1f}% HR (N={n}) "
                f"< {BLOCK_THRESHOLD_HR}% threshold ({source})"
            )

        rows.append({
            'game_date': target_date.isoformat(),
            'model_id': model_id,
            'affinity_group': aff_group,
            'dimension': dimension,
            'dimension_value': dim_value,
            'hr_14d': round(hr, 1) if hr is not None else None,
            'n_14d': n,
            'wins_14d': row.wins_14d if not used_fallback else None,
            'losses_14d': row.losses_14d if not used_fallback else None,
            'bb_hr_14d': round(row.bb_hr_14d, 1) if row.bb_hr_14d is not None else None,
            'bb_n_14d': row.bb_n_14d,
            'is_blocked': is_blocked,
            'block_reason': block_reason,
            'computed_at': now.isoformat(),
        })

    # Log summary
    blocked_count = sum(1 for r in rows if r['is_blocked'])
    models = set(r['model_id'] for r in rows)
    logger.info(
        f"Computed {len(rows)} profile rows for {target_date}: "
        f"{len(models)} models, {blocked_count} blocked slices"
    )
    if blocked_count > 0:
        blocked_slices = [
            f"{r['model_id']} {r['dimension']}={r['dimension_value']} "
            f"({r['hr_14d']}% N={r['n_14d']})"
            for r in rows if r['is_blocked']
        ]
        for s in blocked_slices[:10]:
            logger.info(f"  BLOCKED: {s}")
        if len(blocked_slices) > 10:
            logger.info(f"  ... and {len(blocked_slices) - 10} more")

    return rows


def _compute_group_fallback_stats(
    results: list,
    affinity_lookup: Dict[str, str],
) -> Dict[Tuple[str, str, str], dict]:
    """Aggregate dimension stats at affinity group level for fallback.

    When an individual model has too few observations in a slice (N < MIN_MODEL_N),
    we fall back to the affinity group aggregate.

    Returns:
        Dict of (affinity_group, dimension, dimension_value) -> {hr, n, wins, losses}
    """
    from collections import defaultdict

    accum = defaultdict(lambda: {'wins': 0, 'losses': 0})

    for row in results:
        group = row.affinity_group or affinity_lookup.get(row.system_id)
        if not group:
            continue
        key = (group, row.dimension, row.dimension_value)
        accum[key]['wins'] += row.wins_14d or 0
        accum[key]['losses'] += row.losses_14d or 0

    group_stats = {}
    for key, vals in accum.items():
        total = vals['wins'] + vals['losses']
        if total > 0:
            group_stats[key] = {
                'hr': round(100.0 * vals['wins'] / total, 1),
                'n': total,
                'wins': vals['wins'],
                'losses': vals['losses'],
            }

    return group_stats


def write_profile_rows(bq_client: bigquery.Client, rows: List[dict]) -> int:
    """Write profile rows to model_profile_daily. Returns rows written.

    Uses DELETE-before-write to prevent duplicate rows when re-run.
    """
    if not rows:
        return 0

    target_date = rows[0]['game_date']

    delete_query = f"""
    DELETE FROM `{TABLE_ID}`
    WHERE game_date = @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    delete_job = bq_client.query(delete_query, job_config=job_config)
    delete_result = delete_job.result(timeout=60)
    deleted = delete_job.num_dml_affected_rows or 0
    if deleted > 0:
        logger.info(f"Deleted {deleted} existing profile rows for {target_date}")

    load_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )
    load_job = bq_client.load_table_from_json(rows, TABLE_ID, job_config=load_config)
    load_job.result(timeout=60)

    logger.info(f"Wrote {len(rows)} profile rows to model_profile_daily")
    return len(rows)


def backfill(
    bq_client: bigquery.Client,
    start_date: date,
    end_date: Optional[date] = None,
) -> int:
    """Backfill model_profile_daily from start_date to end_date."""
    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    query = """
    SELECT DISTINCT game_date
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date BETWEEN @start AND @end
      AND ABS(predicted_points - line_value) >= 3
    ORDER BY game_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('start', 'DATE', start_date),
            bigquery.ScalarQueryParameter('end', 'DATE', end_date),
        ]
    )
    dates = [row.game_date for row in bq_client.query(query, job_config=job_config).result()]

    if not dates:
        logger.warning(f"No graded predictions found between {start_date} and {end_date}")
        return 0

    logger.info(f"Backfilling {len(dates)} dates from {dates[0]} to {dates[-1]}")

    total_rows = 0
    for d in dates:
        rows = compute_profiles_for_date(bq_client, d)
        if rows:
            write_profile_rows(bq_client, rows)
            total_rows += len(rows)

    logger.info(f"Backfill complete: {total_rows} rows across {len(dates)} dates")
    return total_rows


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    parser = argparse.ArgumentParser(description='Compute model profile daily metrics')
    parser.add_argument('--date', type=str, help='Single date to compute (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='Backfill historical data')
    parser.add_argument('--start', type=str, default='2026-01-30',
                        help='Backfill start date (default: 2026-01-30)')
    parser.add_argument('--end', type=str, help='Backfill end date (default: yesterday)')
    args = parser.parse_args()

    bq_client = bigquery.Client(project='nba-props-platform')

    if args.backfill:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else None
        total = backfill(bq_client, start, end)
        print(f"Backfill complete: {total} rows written")
    elif args.date:
        target = date.fromisoformat(args.date)
        rows = compute_profiles_for_date(bq_client, target)
        written = write_profile_rows(bq_client, rows)
        print(f"\nComputed {written} profile rows for {target}")

        # Summary by model
        from collections import defaultdict
        model_blocked = defaultdict(list)
        for r in rows:
            if r['is_blocked']:
                model_blocked[r['model_id']].append(
                    f"{r['dimension']}={r['dimension_value']} ({r['hr_14d']}% N={r['n_14d']})"
                )

        if model_blocked:
            print(f"\nBlocked slices ({sum(len(v) for v in model_blocked.values())} total):")
            for model, slices in sorted(model_blocked.items()):
                for s in slices:
                    print(f"  {model}: {s}")
        else:
            print("\nNo blocked slices found")
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
