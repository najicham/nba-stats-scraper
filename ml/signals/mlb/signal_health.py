#!/usr/bin/env python3
"""MLB Signal Health — daily multi-timeframe performance tracker for pitcher strikeout signals.

Queries signal_best_bets_picks + prediction_accuracy to produce rolling hit rate at
7d, 14d, 30d, and season timeframes for each signal. Classifies regime
(HOT / NORMAL / COLD) based on 7d-vs-season divergence.

Purpose: Monitoring and frontend transparency, NOT blocking.
    - COLD regime (divergence < -10) predicts degraded HR
    - HOT regime (divergence > +10, N >= 5, hr_30d >= 50%) predicts elevated HR
    - This is informational — signal count floors and filters handle actual pick quality.

MLB season window: April 1 – October 31 (regular season + playoffs).
Signal tags come from ml/signals/mlb/signals.py (is_shadow=False, is_negative_filter=False).

Usage:
    # Single date
    PYTHONPATH=. python ml/signals/mlb/signal_health.py --date 2026-04-15

    # Backfill range
    PYTHONPATH=. python ml/signals/mlb/signal_health.py --backfill --start 2026-04-01 --end 2026-04-15

Created: 2026-03-23
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
TABLE_ID = f'{PROJECT_ID}.mlb_predictions.signal_health_daily'

# MLB season typically starts early April (Opening Day) and runs through October.
# Used as the lower bound for "season" timeframe queries.
MLB_SEASON_START = '2026-03-27'  # Approximate Opening Day 2026

# Regime thresholds — same as NBA version.
COLD_THRESHOLD = -10.0   # divergence_7d_vs_season < -10 → COLD
HOT_THRESHOLD = 10.0     # divergence_7d_vs_season > +10 → HOT

# Signals that depend on model accuracy (decay with model staleness).
# In MLB, high_edge is purely model-output-dependent.
MODEL_DEPENDENT_SIGNALS = frozenset({
    'high_edge',
})

# Active MLB signals — non-shadow, non-negative-filter signals.
# Derived from ml/signals/mlb/signals.py (is_shadow=False, is_negative_filter=False).
# Shadow signals are still tracked for monitoring (separate frozenset below).
# Update this set when signals are promoted from shadow or demoted/removed.
ACTIVE_MLB_SIGNALS = frozenset({
    # Base / edge signals
    'high_edge',
    # Walk-forward validated (Session 433)
    'projection_agrees_over',
    'k_trending_over',
    'recent_k_above_line',
    # Regressor-transition signals (Session 441)
    'regressor_projection_agrees_over',
    'home_pitcher_over',
    'long_rest_over',
    # UNDER active signals
    'velocity_drop_under',
    'short_rest_under',
    'high_variance_under',
    # Contextual active signals
    'opponent_k_prone',
    'ballpark_k_boost',
    'umpire_k_friendly',
    # Session 460 promoted signals (cross-season validated)
    'high_csw_over',
    'elite_peripherals_over',
    'pitch_efficiency_depth_over',
    # Session 464 promoted signals (4-season replay validated)
    'day_game_shadow_over',
    'pitcher_on_roll_over',
    # Session 465 promoted signals
    'day_game_high_csw_combo_over',
    'xfip_elite_over',
})

# Shadow signals — tracked for monitoring, not yet production.
# These fire and are stored in signal_tags but don't count toward gates.
SHADOW_MLB_SIGNALS = frozenset({
    'swstr_surge',
    'line_movement_over',
    'weather_cold_under',
    'platoon_advantage',
    'ace_pitcher_over',
    'catcher_framing_over',
    'pitch_count_limit_under',
    'bad_opponent_over_obs',
    'bad_venue_over_obs',
    # Session 460 shadow signals
    'cold_weather_k_over',
    'lineup_k_spike_over',
    'short_starter_under',
    'game_total_low_over',
    'heavy_favorite_over',
    'bottom_up_agrees_over',
    'catcher_framing_poor_under',
    'rematch_familiarity_under',
    'cumulative_arm_stress_under',
    'taxed_bullpen_over',
    # Session 464 shadow signals
    'k_rate_reversion_under',
    'k_rate_bounce_over',
    'umpire_csw_combo_over',
    'rest_workload_stress_under',
    'low_era_high_k_combo_over',
    # Session 464 round 2
    'chase_rate_over',
    'contact_specialist_under',
    'humidity_over',
    'fresh_opponent_over',
    # Session 465 shadow combo signals
    'day_game_elite_peripherals_combo_over',
    'high_csw_low_era_high_k_combo_over',
})

# All signals tracked — active + shadow (negative filters excluded).
ALL_TRACKED_SIGNALS = ACTIVE_MLB_SIGNALS | SHADOW_MLB_SIGNALS


def compute_signal_health(
    bq_client: bigquery.Client,
    target_date: str,
    season_start: str = MLB_SEASON_START,
) -> List[Dict[str, Any]]:
    """Compute signal health metrics for a single date.

    Queries signal_best_bets_picks (unnested signal_tags) joined with
    prediction_accuracy across 4 timeframes (7d, 14d, 30d, season)
    for each active and shadow signal.

    Args:
        bq_client: BigQuery client.
        target_date: Date to compute health for (YYYY-MM-DD).
        season_start: Season start date for "season" timeframe lower bound.

    Returns:
        List of dicts ready for BigQuery insertion (one per signal_tag).
    """
    query = f"""
    -- Join signal_best_bets_picks with prediction_accuracy to get graded outcomes.
    -- signal_tags is ARRAY<STRING> in the picks table — unnest via CROSS JOIN.
    -- Filter to signals we track (active + shadow) to exclude ghost tags.
    WITH tagged AS (
      SELECT
        sbp.game_date,
        sbp.pitcher_lookup,
        sbp.system_id,
        signal_tag,
        pa.prediction_correct,
        pa.recommendation
      FROM `{PROJECT_ID}.mlb_predictions.signal_best_bets_picks` sbp
      CROSS JOIN UNNEST(sbp.signal_tags) AS signal_tag
      INNER JOIN `{PROJECT_ID}.mlb_predictions.prediction_accuracy` pa
        ON sbp.pitcher_lookup = pa.pitcher_lookup
        AND sbp.game_date = pa.game_date
        AND sbp.system_id = pa.system_id
      WHERE sbp.game_date >= @season_start
        AND sbp.game_date <= @target_date
        AND pa.prediction_correct IS NOT NULL
        AND pa.is_voided IS NOT TRUE
        AND pa.has_prop_line = TRUE
        AND pa.recommendation IN ('OVER', 'UNDER')
        AND signal_tag IN UNNEST(@all_signals)
    ),

    signal_metrics AS (
      SELECT
        signal_tag,

        -- 7d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
                AND prediction_correct) AS wins_7d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)) AS picks_7d,

        -- 14d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
                AND prediction_correct) AS wins_14d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)) AS picks_14d,

        -- 30d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
                AND prediction_correct) AS wins_30d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)) AS picks_30d,

        -- Season (since season_start)
        COUNTIF(prediction_correct) AS wins_season,
        COUNT(*) AS picks_season,

        -- Directional splits
        -- OVER 7d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
                AND recommendation = 'OVER' AND prediction_correct) AS wins_over_7d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
                AND recommendation = 'OVER') AS picks_over_7d,
        -- UNDER 7d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
                AND recommendation = 'UNDER' AND prediction_correct) AS wins_under_7d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
                AND recommendation = 'UNDER') AS picks_under_7d,
        -- OVER 30d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
                AND recommendation = 'OVER' AND prediction_correct) AS wins_over_30d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
                AND recommendation = 'OVER') AS picks_over_30d,
        -- UNDER 30d
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
                AND recommendation = 'UNDER' AND prediction_correct) AS wins_under_30d,
        COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
                AND recommendation = 'UNDER') AS picks_under_30d

      FROM tagged
      GROUP BY signal_tag
    )

    SELECT
      signal_tag,
      ROUND(100.0 * SAFE_DIVIDE(wins_7d, picks_7d), 1) AS hr_7d,
      ROUND(100.0 * SAFE_DIVIDE(wins_14d, picks_14d), 1) AS hr_14d,
      ROUND(100.0 * SAFE_DIVIDE(wins_30d, picks_30d), 1) AS hr_30d,
      ROUND(100.0 * SAFE_DIVIDE(wins_season, picks_season), 1) AS hr_season,
      picks_7d, picks_14d, picks_30d, picks_season,
      -- Directional splits
      ROUND(100.0 * SAFE_DIVIDE(wins_over_7d, picks_over_7d), 1) AS hr_over_7d,
      ROUND(100.0 * SAFE_DIVIDE(wins_under_7d, picks_under_7d), 1) AS hr_under_7d,
      ROUND(100.0 * SAFE_DIVIDE(wins_over_30d, picks_over_30d), 1) AS hr_over_30d,
      ROUND(100.0 * SAFE_DIVIDE(wins_under_30d, picks_under_30d), 1) AS hr_under_30d,
      picks_over_7d, picks_under_7d, picks_over_30d, picks_under_30d
    FROM signal_metrics
    WHERE picks_season > 0
    ORDER BY signal_tag
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ScalarQueryParameter('season_start', 'DATE', season_start),
            bigquery.ArrayQueryParameter('all_signals', 'STRING', sorted(ALL_TRACKED_SIGNALS)),
        ]
    )

    rows = bq_client.query(query, job_config=job_config).result(timeout=60)
    now = datetime.now(timezone.utc).isoformat()

    results = []
    for row in rows:
        hr_7d = row.hr_7d
        hr_season = row.hr_season

        # Divergence metrics
        div_7d = (
            round(hr_7d - hr_season, 1)
            if hr_7d is not None and hr_season is not None
            else None
        )
        div_14d = (
            round(row.hr_14d - hr_season, 1)
            if row.hr_14d is not None and hr_season is not None
            else None
        )

        # Regime classification.
        # HOT gate: require picks_7d >= 5 AND hr_30d >= 50% to prevent N=1 flukes
        # from inflating HOT status (mirrors Session 483 NBA fix).
        if div_7d is not None and div_7d < COLD_THRESHOLD:
            regime = 'COLD'
        elif (
            div_7d is not None
            and div_7d > HOT_THRESHOLD
            and row.picks_7d >= 5
            and (row.hr_30d is None or row.hr_30d >= 50.0)
        ):
            regime = 'HOT'
        else:
            regime = 'NORMAL'

        is_model_dep = row.signal_tag in MODEL_DEPENDENT_SIGNALS

        # Status — DEGRADING only for model-dependent signals with sufficient sample.
        # Guard DEGRADING with picks_7d >= 5 to suppress false alarms from
        # grading outages (mirrors Session 478 NBA fix).
        if regime == 'COLD' and is_model_dep:
            if row.picks_7d >= 5:
                status = 'DEGRADING'
            else:
                status = 'WATCH'
        elif div_7d is not None and div_7d < -5.0:
            status = 'WATCH'
        else:
            status = 'HEALTHY'

        def _f(v):
            """Convert BQ Decimal/float to Python float for JSON serialization."""
            return float(v) if v is not None else None

        results.append({
            'game_date': target_date,
            'signal_tag': row.signal_tag,
            'hr_7d': _f(hr_7d),
            'hr_14d': _f(row.hr_14d),
            'hr_30d': _f(row.hr_30d),
            'hr_season': _f(hr_season),
            'picks_7d': row.picks_7d,
            'picks_14d': row.picks_14d,
            'picks_30d': row.picks_30d,
            'picks_season': row.picks_season,
            'divergence_7d_vs_season': _f(div_7d),
            'divergence_14d_vs_season': _f(div_14d),
            'regime': regime,
            'status': status,
            'days_in_current_regime': None,  # Populated below
            # Directional splits
            'hr_over_7d': _f(row.hr_over_7d),
            'hr_under_7d': _f(row.hr_under_7d),
            'hr_over_30d': _f(row.hr_over_30d),
            'hr_under_30d': _f(row.hr_under_30d),
            'picks_over_7d': row.picks_over_7d,
            'picks_under_7d': row.picks_under_7d,
            'picks_over_30d': row.picks_over_30d,
            'picks_under_30d': row.picks_under_30d,
            'is_model_dependent': is_model_dep,
            'computed_at': now,
        })

    # Fill days_in_current_regime from prior rows
    _fill_regime_duration(bq_client, target_date, results)

    logger.info(
        f"Computed MLB signal health for {target_date}: "
        f"{len(results)} signals, "
        f"{sum(1 for r in results if r['regime'] == 'COLD')} COLD, "
        f"{sum(1 for r in results if r['regime'] == 'HOT')} HOT"
    )

    return results


def _fill_regime_duration(
    bq_client: bigquery.Client,
    target_date: str,
    results: List[Dict],
) -> None:
    """Fill days_in_current_regime by checking prior signal_health_daily rows."""
    if not results:
        return

    try:
        query = f"""
        SELECT signal_tag, regime, game_date
        FROM `{TABLE_ID}`
        WHERE game_date >= DATE_SUB(@target_date, INTERVAL 14 DAY)
          AND game_date < @target_date
        ORDER BY signal_tag, game_date DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )
        prior_rows = bq_client.query(query, job_config=job_config).result(timeout=30)

        # Build map: signal_tag -> list of prior regimes sorted most-recent first
        prior_map: Dict[str, List[str]] = {}
        for row in prior_rows:
            tag = row.signal_tag
            if tag not in prior_map:
                prior_map[tag] = []
            prior_map[tag].append(row.regime)

        for r in results:
            tag = r['signal_tag']
            current_regime = r['regime']
            streak = 1  # Today counts as day 1
            for prior_regime in prior_map.get(tag, []):
                if prior_regime == current_regime:
                    streak += 1
                else:
                    break
            r['days_in_current_regime'] = streak

    except Exception as e:
        logger.warning(f"Could not compute regime duration: {e}")
        for r in results:
            r['days_in_current_regime'] = 1


def write_health_rows(bq_client: bigquery.Client, rows: List[Dict]) -> int:
    """Write signal health rows to BigQuery using DELETE-before-INSERT.

    Deletes existing rows for the target date before appending to prevent
    duplicate rows from reruns/backfills.

    Args:
        bq_client: BigQuery client.
        rows: List of row dicts (output of compute_signal_health).

    Returns:
        Number of rows written.
    """
    if not rows:
        return 0

    target_date = rows[0]['game_date']

    # DELETE existing rows for this date
    delete_query = f"DELETE FROM `{TABLE_ID}` WHERE game_date = @target_date"
    delete_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )
    delete_job = bq_client.query(delete_query, job_config=delete_config)
    delete_job.result(timeout=60)
    deleted = delete_job.num_dml_affected_rows or 0
    if deleted > 0:
        logger.info(f"Deleted {deleted} existing rows for {target_date}")

    # WRITE_APPEND the new rows
    load_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_NEVER,
    )
    load_job = bq_client.load_table_from_json(rows, TABLE_ID, job_config=load_config)
    load_job.result(timeout=60)
    logger.info(f"Wrote {len(rows)} MLB signal health rows to {TABLE_ID}")
    return len(rows)


def check_signal_firing_canary(
    bq_client: bigquery.Client,
    target_date: str,
) -> List[Dict[str, Any]]:
    """Detect active MLB signals that stopped firing or are firing at degraded rates.

    Compares 7-day firing count to prior 23-day baseline for each active signal.
    Classifies as DEAD (0 fires when previously active), DEGRADING (>70% drop),
    or NEVER_FIRED (0 in full 30d window).

    Args:
        bq_client: BigQuery client.
        target_date: Date to check (YYYY-MM-DD).

    Returns:
        List of alert dicts for DEAD/DEGRADING/NEVER_FIRED signals.
        Empty list means all active signals are healthy.
    """
    query = f"""
    WITH firing_counts AS (
        SELECT
            signal_tag,
            COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
                    AND game_date <= @target_date) AS fires_7d,
            COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
                    AND game_date <= DATE_SUB(@target_date, INTERVAL 7 DAY)) AS fires_prior_23d
        FROM `{PROJECT_ID}.mlb_predictions.signal_best_bets_picks`
        CROSS JOIN UNNEST(signal_tags) AS signal_tag
        WHERE game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
          AND game_date <= @target_date
          AND signal_tag IN UNNEST(@active_signals)
        GROUP BY signal_tag
    ),

    -- Include signals with zero fires (not present in picks at all)
    all_signals AS (
        SELECT signal AS signal_tag
        FROM UNNEST(@active_signals) AS signal
    )

    SELECT
        a.signal_tag,
        COALESCE(f.fires_7d, 0) AS fires_7d,
        COALESCE(f.fires_prior_23d, 0) AS fires_prior_23d,
        CASE
            WHEN COALESCE(f.fires_7d, 0) = 0 AND COALESCE(f.fires_prior_23d, 0) > 0
                THEN 'DEAD'
            WHEN COALESCE(f.fires_7d, 0) = 0 AND COALESCE(f.fires_prior_23d, 0) = 0
                THEN 'NEVER_FIRED'
            WHEN f.fires_7d > 0
                AND f.fires_prior_23d > 0
                AND f.fires_7d < f.fires_prior_23d * 0.3
                THEN 'DEGRADING'
            ELSE 'HEALTHY'
        END AS firing_status
    FROM all_signals a
    LEFT JOIN firing_counts f ON a.signal_tag = f.signal_tag
    ORDER BY
        CASE
            WHEN COALESCE(f.fires_7d, 0) = 0 AND COALESCE(f.fires_prior_23d, 0) > 0 THEN 0
            WHEN COALESCE(f.fires_7d, 0) = 0 AND COALESCE(f.fires_prior_23d, 0) = 0 THEN 1
            WHEN f.fires_7d > 0 AND f.fires_prior_23d > 0
                 AND f.fires_7d < f.fires_prior_23d * 0.3 THEN 2
            ELSE 3
        END
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ArrayQueryParameter(
                'active_signals', 'STRING', sorted(ACTIVE_MLB_SIGNALS)
            ),
        ]
    )

    rows = bq_client.query(query, job_config=job_config).result(timeout=60)

    alerts = []
    for row in rows:
        status = row.firing_status
        if status in ('DEAD', 'DEGRADING', 'NEVER_FIRED'):
            alerts.append({
                'signal_tag': row.signal_tag,
                'firing_status': status,
                'fires_7d': row.fires_7d,
                'fires_prior_23d': row.fires_prior_23d,
            })

    if alerts:
        dead = [a for a in alerts if a['firing_status'] == 'DEAD']
        degrading = [a for a in alerts if a['firing_status'] == 'DEGRADING']
        never = [a for a in alerts if a['firing_status'] == 'NEVER_FIRED']
        logger.warning(
            f"MLB signal firing canary for {target_date}: "
            f"{len(dead)} DEAD, {len(degrading)} DEGRADING, {len(never)} NEVER_FIRED"
        )
        for a in dead:
            logger.warning(
                f"  DEAD: {a['signal_tag']} — 0 fires in 7d, "
                f"was {a['fires_prior_23d']} in prior 23d"
            )
        for a in degrading:
            logger.warning(
                f"  DEGRADING: {a['signal_tag']} — {a['fires_7d']} fires in 7d, "
                f"was {a['fires_prior_23d']} in prior 23d "
                f"({round(100 * a['fires_7d'] / max(a['fires_prior_23d'], 1))}% of baseline)"
            )
    else:
        logger.info(f"MLB signal firing canary for {target_date}: all active signals healthy")

    return alerts


def get_signal_health_summary(
    bq_client: bigquery.Client,
    target_date: str,
) -> Dict[str, Dict[str, Any]]:
    """Get signal health summary dict for a given date.

    Used by exporters and monitoring scripts to fetch current regime per signal.

    Returns:
        Dict keyed by signal_tag with hr_7d, hr_season, regime, status,
        is_model_dependent. Returns empty dict if no data found.
    """
    query = f"""
    SELECT signal_tag, hr_7d, hr_season, regime, status, is_model_dependent
    FROM `{TABLE_ID}`
    WHERE game_date = @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    try:
        rows = bq_client.query(query, job_config=job_config).result(timeout=30)
        return {
            row.signal_tag: {
                'hr_7d': row.hr_7d,
                'hr_season': row.hr_season,
                'regime': row.regime,
                'status': row.status,
                'is_model_dependent': row.is_model_dependent,
            }
            for row in rows
        }
    except Exception as e:
        logger.warning(f"Could not load MLB signal health for {target_date}: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(
        description="MLB Signal Health Computation — daily HR tracker for pitcher K signals"
    )
    parser.add_argument('--date', help='Single date to compute (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='Backfill a date range')
    parser.add_argument(
        '--start', default='2026-04-01',
        help='Backfill start date (default: 2026-04-01)',
    )
    parser.add_argument(
        '--end', default='2026-10-31',
        help='Backfill end date (default: 2026-10-31)',
    )
    parser.add_argument(
        '--season-start', default=MLB_SEASON_START,
        help=f'Season start date for "season" timeframe (default: {MLB_SEASON_START})',
    )
    parser.add_argument('--dry-run', action='store_true', help='Print without writing to BQ')
    parser.add_argument(
        '--canary', action='store_true',
        help='Run signal firing canary (detect dead/degrading active signals)',
    )
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    # Signal firing canary mode
    if args.canary:
        from datetime import date as date_type
        check_date = args.date or str(date_type.today())
        print(f"\n=== MLB Signal Firing Canary — {check_date} ===\n")
        alerts = check_signal_firing_canary(client, check_date)
        if alerts:
            dead = [a for a in alerts if a['firing_status'] == 'DEAD']
            degrading = [a for a in alerts if a['firing_status'] == 'DEGRADING']
            never = [a for a in alerts if a['firing_status'] == 'NEVER_FIRED']
            if dead:
                print(f"DEAD signals ({len(dead)}):")
                for a in dead:
                    print(f"  {a['signal_tag']} — 0 fires in 7d (was {a['fires_prior_23d']} prior 23d)")
            if degrading:
                print(f"DEGRADING signals ({len(degrading)}):")
                for a in degrading:
                    pct = round(100 * a['fires_7d'] / max(a['fires_prior_23d'], 1))
                    print(f"  {a['signal_tag']} — {a['fires_7d']} fires in 7d "
                          f"(was {a['fires_prior_23d']} prior 23d, {pct}% of baseline)")
            if never:
                print(f"NEVER_FIRED signals ({len(never)}):")
                for a in never:
                    print(f"  {a['signal_tag']}")
        else:
            print("All active signals healthy — no alerts.")
        print(f"\nActive signals checked: {len(ACTIVE_MLB_SIGNALS)}")
        return

    # Determine dates to process
    if args.date:
        dates = [args.date]
    elif args.backfill:
        # Query distinct game dates from picks table in the specified range
        dates_q = f"""
        SELECT DISTINCT game_date
        FROM `{PROJECT_ID}.mlb_predictions.signal_best_bets_picks`
        WHERE game_date BETWEEN @start AND @end
        ORDER BY game_date
        """
        dates_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter('start', 'DATE', args.start),
            bigquery.ScalarQueryParameter('end', 'DATE', args.end),
        ])
        dates = [
            str(row.game_date)
            for row in client.query(dates_q, job_config=dates_config).result()
        ]
        if not dates:
            print(f"No picks found in signal_best_bets_picks for {args.start} – {args.end}")
            sys.exit(0)
    else:
        print("Specify --date DATE or --backfill [--start YYYY-MM-DD] [--end YYYY-MM-DD]")
        sys.exit(1)

    print(f"Computing MLB signal health for {len(dates)} date(s)")
    total = 0

    for i, date_str in enumerate(dates):
        rows = compute_signal_health(client, date_str, season_start=args.season_start)
        cold = sum(1 for r in rows if r['regime'] == 'COLD')
        hot = sum(1 for r in rows if r['regime'] == 'HOT')
        degrading = sum(1 for r in rows if r['status'] == 'DEGRADING')
        print(
            f"[{i+1}/{len(dates)}] {date_str}: {len(rows)} signals, "
            f"{cold} COLD, {hot} HOT, {degrading} DEGRADING"
        )

        if not args.dry_run and rows:
            write_health_rows(client, rows)
            total += len(rows)

    print(f"\nTotal rows written: {total}")
    if args.dry_run:
        print("(DRY RUN — nothing written)")


if __name__ == '__main__':
    main()
