#!/usr/bin/env python3
"""Signal Health — compute daily multi-timeframe performance for each signal.

Queries pick_signal_tags + prediction_accuracy to produce rolling HR at
7d, 14d, 30d, season timeframes for each signal. Classifies regime
(HOT / NORMAL / COLD) based on 7d-vs-season divergence.

Purpose: Monitoring and frontend transparency, NOT blocking.
    - COLD regime (divergence < -10) predicts 39.6% HR
    - NORMAL regime predicts 80.0% HR
    - This is informational — the signal count floor and combo registry
      handle actual pick quality.

Usage:
    # Single date
    PYTHONPATH=. python ml/signals/signal_health.py --date 2026-02-14

    # Backfill range
    PYTHONPATH=. python ml/signals/signal_health.py --backfill --start 2026-01-09 --end 2026-02-14

Created: 2026-02-15 (Session 259)
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

from shared.config.model_selection import get_best_bets_model_id

PROJECT_ID = 'nba-props-platform'
SYSTEM_ID = get_best_bets_model_id()
TABLE_ID = f'{PROJECT_ID}.nba_predictions.signal_health_daily'

# Signals that depend on model accuracy (decay with model staleness)
MODEL_DEPENDENT_SIGNALS = frozenset({
    'high_edge', 'edge_spread_optimal', 'combo_he_ms', 'combo_3way',
})

# Active signals — only these are included in signal_health_daily.
# Ghost signals (removed signals with stale tags in pick_signal_tags)
# are filtered out at query time. Updated when signals are added/removed.
ACTIVE_SIGNALS = frozenset({
    # model_health excluded — intentionally not written to pick_signal_tags (Session 387)
    'high_edge', 'edge_spread_optimal',
    'combo_he_ms', 'combo_3way',
    'bench_under', '3pt_bounce',
    'rest_advantage_2d',
    'book_disagreement',
    'ft_rate_bench_over',
    # Session 371-380 additions
    'home_under',
    'scoring_cold_streak_over',
    'extended_rest_under',
    'starter_under',
    'high_scoring_environment_over',
    'fast_pace_over',
    'volatile_scoring_over',  # RE-ENABLED Session 411 — 77.8% post-toxic
    'low_line_over',
    'line_rising_over',
    'self_creation_over',
    'sharp_line_move_over',
    'sharp_line_drop_under',
    # Session 396-397 additions
    'b2b_boost_over',
    'q4_scorer_over',
    # b2b_fatigue_under DISABLED — 39.5% Feb HR (Session 373)
    # prop_line_drop_over DISABLED — conceptually backward, 39.1% Feb HR (Session 374b)
    # blowout_recovery DISABLED — 50% HR (7-7) in best bets, 25% in Feb (Session 349)
    # high_ft_under, self_creator_under, volatile_under, high_usage_under REMOVED (Session 326)
    # Session 401/404: Shadow signals — monitor firing/HR while accumulating data
    'projection_consensus_over',
    'projection_consensus_under',
    'predicted_pace_over',
    'dvp_favorable_over',
    'positive_clv_over',
    'positive_clv_under',
    # Session 404: VSiN sharp money signals (shadow)
    'sharp_money_over',
    'sharp_money_under',
    # Session 404: RotoWire minutes projection signal (shadow)
    'minutes_surge_over',
    # Session 410: Derived feature signals (shadow)
    'hot_form_over',
    'consistent_scorer_over',
    'over_trend_over',
    # Session 411: Feature store signals (shadow)
    'usage_surge_over',
    'scoring_momentum_over',
    'career_matchup_over',
    'minutes_load_over',
    'blowout_risk_under',
    # Session 418: Player profile signals (shadow)
    'bounce_back_over',
    'over_streak_reversion_under',
    # Session 414: Day-of-week signals (shadow)
    'day_of_week_over',
    'day_of_week_under',
    # Session 399: Sharp book lean signals
    'sharp_book_lean_over',  # active in rescue_tags
    'sharp_book_lean_under',  # Session 431: demoted to observation-only (zero fires 2026)
    # Session 413/417: Mean reversion (ACTIVE — production + rescue signal, was untracked!)
    'mean_reversion_under',
    # Session 422c/423: New UNDER signals (shadow)
    'volatile_starter_under',
    'downtrend_under',
    'star_favorite_under',
    'starter_away_overtrend_under',
    # Session 462-466: Promoted to active — 5-season cross-validated (were missing from ACTIVE_SIGNALS)
    'hot_3pt_under',
    'cold_3pt_over',
    'line_drifted_down_under',
    # Session 463: P0/P1 simulator signals (shadow — accumulating BB data)
    'ft_anomaly_under',
    'slow_pace_under',
    'star_line_under',
    'sharp_consensus_under',
    # Session 469: Direction-specific book disagreement (shadow — accumulating BB data)
    'book_disagree_over',
    'book_disagree_under',
    # usage_surge_over: graduated from shadow Session 495 (68.8% HR, N=32) — see line 94
})

# Regime thresholds (Session 257 analysis)
COLD_THRESHOLD = -10.0   # divergence_7d_vs_season < -10 → COLD
HOT_THRESHOLD = 10.0     # divergence_7d_vs_season > +10 → HOT


def check_signal_firing_canary(
    bq_client: bigquery.Client,
    target_date: str,
) -> List[Dict[str, Any]]:
    """Detect signals that stopped firing or are firing at degraded rates.

    Compares 7-day firing count to prior 23-day baseline for each active signal.
    Classifies as DEAD (0 fires when previously active), DEGRADING (>70% drop),
    or HEALTHY.

    Created: Session 387 — two 80%+ HR signals were dead for weeks undetected.

    Returns:
        List of dicts with signal_tag, firing_status, fires_7d, fires_prior_23d.
        Only returns DEAD or DEGRADING signals (empty list = all healthy).
    """
    query = f"""
    -- Session 433: Dedup pick_signal_tags for accurate fire counts
    WITH deduped_pst AS (
        SELECT * FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY game_date, player_lookup, system_id
                ORDER BY evaluated_at DESC
            ) AS _rn
            FROM `{PROJECT_ID}.nba_predictions.pick_signal_tags`
            WHERE game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
              AND game_date <= @target_date
        )
        WHERE _rn = 1
    ),

    firing_counts AS (
        SELECT
            signal_tag,
            COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 7 DAY)
                    AND game_date <= @target_date) AS fires_7d,
            COUNTIF(game_date > DATE_SUB(@target_date, INTERVAL 30 DAY)
                    AND game_date <= DATE_SUB(@target_date, INTERVAL 7 DAY)) AS fires_prior_23d
        FROM deduped_pst
        CROSS JOIN UNNEST(signal_tags) AS signal_tag
        WHERE signal_tag IN UNNEST(@active_signals)
        GROUP BY signal_tag
    ),

    -- Include signals with ZERO fires (not in pick_signal_tags at all)
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
            WHEN f.fires_7d > 0 AND f.fires_prior_23d > 0 AND f.fires_7d < f.fires_prior_23d * 0.3 THEN 2
            ELSE 3
        END
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ArrayQueryParameter('active_signals', 'STRING', sorted(ACTIVE_SIGNALS)),
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
            f"Signal firing canary for {target_date}: "
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
        logger.info(f"Signal firing canary for {target_date}: all signals healthy")

    return alerts


def format_canary_slack_message(alerts: List[Dict], target_date: str) -> Optional[str]:
    """Format canary alerts into a Slack message. Returns None if no alerts."""
    if not alerts:
        return None

    dead = [a for a in alerts if a['firing_status'] == 'DEAD']
    degrading = [a for a in alerts if a['firing_status'] == 'DEGRADING']
    never = [a for a in alerts if a['firing_status'] == 'NEVER_FIRED']

    lines = [f"*Signal Firing Canary — {target_date}*"]

    if dead:
        lines.append("")
        lines.append("🔴 *DEAD SIGNALS* (fired before, now zero):")
        for a in dead:
            lines.append(
                f"  • `{a['signal_tag']}` — 0 fires in 7d "
                f"(was {a['fires_prior_23d']} in prior 23d)"
            )

    if degrading:
        lines.append("")
        lines.append("🟡 *DEGRADING SIGNALS* (>70% drop from baseline):")
        for a in degrading:
            pct = round(100 * a['fires_7d'] / max(a['fires_prior_23d'], 1))
            lines.append(
                f"  • `{a['signal_tag']}` — {a['fires_7d']} fires in 7d "
                f"(was {a['fires_prior_23d']} in prior 23d, {pct}% of baseline)"
            )

    if never:
        lines.append("")
        lines.append("⚪ *NEVER FIRED* (0 fires in 30d — check configuration):")
        for a in never:
            lines.append(f"  • `{a['signal_tag']}`")

    lines.append("")
    lines.append("_Check `ml/signals/` for broken thresholds, dead dependencies, or feature scale mismatches._")

    return "\n".join(lines)


def check_signal_rescue_performance(
    bq_client: bigquery.Client,
    target_date: str,
) -> Optional[Dict[str, Any]]:
    """Check signal rescue performance over trailing 14 days.

    Returns summary dict with rescued vs normal HR, or None if no data.
    Fires warning if rescue HR drops below 50% on 5+ picks.

    Created: Session 398.
    """
    query = f"""
    SELECT
        COUNTIF(bb.signal_rescued = TRUE AND pa.prediction_correct) as rescued_wins,
        COUNTIF(bb.signal_rescued = TRUE AND pa.prediction_correct IS NOT NULL) as rescued_total,
        COUNTIF(bb.signal_rescued IS NOT TRUE AND pa.prediction_correct) as normal_wins,
        COUNTIF(bb.signal_rescued IS NOT TRUE AND pa.prediction_correct IS NOT NULL) as normal_total
    FROM `{PROJECT_ID}.nba_predictions.signal_best_bets_picks` bb
    LEFT JOIN `{PROJECT_ID}.nba_predictions.prediction_accuracy` pa
        ON bb.player_lookup = pa.player_lookup
        AND bb.game_date = pa.game_date
        AND bb.system_id = pa.system_id
        AND pa.recommendation = bb.recommendation
        AND pa.line_value = bb.line_value
    WHERE bb.game_date > DATE_SUB(@target_date, INTERVAL 14 DAY)
      AND bb.game_date <= @target_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
        ]
    )

    try:
        row = next(iter(bq_client.query(query, job_config=job_config).result(timeout=30)))
        rescued_total = row.rescued_total or 0
        normal_total = row.normal_total or 0
        rescued_wins = row.rescued_wins or 0
        normal_wins = row.normal_wins or 0

        rescued_hr = round(100.0 * rescued_wins / rescued_total, 1) if rescued_total > 0 else None
        normal_hr = round(100.0 * normal_wins / normal_total, 1) if normal_total > 0 else None

        result = {
            'rescued_total': rescued_total,
            'rescued_wins': rescued_wins,
            'rescued_hr': rescued_hr,
            'normal_total': normal_total,
            'normal_wins': normal_wins,
            'normal_hr': normal_hr,
        }

        if rescued_total > 0:
            logger.info(
                f"Signal rescue performance (14d to {target_date}): "
                f"{rescued_wins}/{rescued_total} ({rescued_hr}% HR) rescued, "
                f"{normal_wins}/{normal_total} ({normal_hr}% HR) normal"
            )
            if rescued_total >= 5 and rescued_hr is not None and rescued_hr < 50.0:
                logger.warning(
                    f"Signal rescue UNDERPERFORMING: {rescued_hr}% HR on {rescued_total} picks "
                    f"(below 50% breakeven). Consider reviewing rescue_tags."
                )
                result['alert'] = 'UNDERPERFORMING'

        return result

    except Exception as e:
        logger.warning(f"Could not check signal rescue performance: {e}")
        return None


def compute_signal_health(
    bq_client: bigquery.Client,
    target_date: str,
) -> List[Dict[str, Any]]:
    """Compute signal health metrics for a single date.

    Queries pick_signal_tags (unnested) joined with prediction_accuracy
    across 4 timeframes (7d, 14d, 30d, season) for each signal.

    Args:
        bq_client: BigQuery client.
        target_date: Date to compute health for (YYYY-MM-DD).

    Returns:
        List of dicts ready for BigQuery insertion (one per signal_tag).
    """
    query = f"""
    -- Session 433: Dedup pick_signal_tags to handle intermittent 2x row duplication.
    -- Root cause: signal_annotator._write_rows() can append without DELETE on error.
    -- ROW_NUMBER deduplicates per (game_date, player_lookup, system_id).
    -- Session 493: Pre-dedup prediction_accuracy — pick_signal_tags lacks recommendation/line_value
    -- so we can't filter in the JOIN; deduplicate PA to one row per (player,date,model) first.
    WITH deduped_pa AS (
      SELECT * EXCEPT(rn) FROM (
        SELECT *,
          ROW_NUMBER() OVER (
            PARTITION BY player_lookup, game_date, system_id
            ORDER BY
              CASE WHEN recommendation IN ('OVER','UNDER') THEN 0 ELSE 1 END,
              CASE WHEN prediction_correct IS NOT NULL THEN 0 ELSE 1 END,
              graded_at DESC
          ) AS rn
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date >= '2025-10-22'
          AND game_date <= @target_date
      ) WHERE rn = 1
    ),
    deduped_pst AS (
      SELECT * FROM (
        SELECT *, ROW_NUMBER() OVER (
          PARTITION BY game_date, player_lookup, system_id
          ORDER BY evaluated_at DESC
        ) AS _rn
        FROM `{PROJECT_ID}.nba_predictions.pick_signal_tags`
        WHERE game_date >= '2025-10-22'
          AND game_date <= @target_date
      )
      WHERE _rn = 1
    ),

    tagged AS (
      SELECT
        pst.game_date,
        pst.player_lookup,
        pst.system_id,
        signal_tag,
        pa.prediction_correct,
        pa.recommendation
      FROM deduped_pst pst
      CROSS JOIN UNNEST(pst.signal_tags) AS signal_tag
      INNER JOIN deduped_pa pa
        ON pst.player_lookup = pa.player_lookup
        AND pst.game_date = pa.game_date
        AND pst.system_id = pa.system_id
      WHERE pa.prediction_correct IS NOT NULL
        AND pa.is_voided IS NOT TRUE
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

        -- Season
        COUNTIF(prediction_correct) AS wins_season,
        COUNT(*) AS picks_season,

        -- Directional splits (Session 398)
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
      -- Directional splits (Session 398)
      ROUND(100.0 * SAFE_DIVIDE(wins_over_7d, picks_over_7d), 1) AS hr_over_7d,
      ROUND(100.0 * SAFE_DIVIDE(wins_under_7d, picks_under_7d), 1) AS hr_under_7d,
      ROUND(100.0 * SAFE_DIVIDE(wins_over_30d, picks_over_30d), 1) AS hr_over_30d,
      ROUND(100.0 * SAFE_DIVIDE(wins_under_30d, picks_under_30d), 1) AS hr_under_30d,
      picks_over_7d, picks_under_7d, picks_over_30d, picks_under_30d
    FROM signal_metrics
    WHERE picks_season > 0
      AND signal_tag IN UNNEST(@active_signals)
    ORDER BY signal_tag
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ArrayQueryParameter('active_signals', 'STRING', sorted(ACTIVE_SIGNALS)),
        ]
    )

    rows = bq_client.query(query, job_config=job_config).result(timeout=60)
    now = datetime.now(timezone.utc).isoformat()

    results = []
    for row in rows:
        hr_7d = row.hr_7d
        hr_season = row.hr_season

        # Divergence
        div_7d = round(hr_7d - hr_season, 1) if hr_7d is not None and hr_season is not None else None
        div_14d = round(row.hr_14d - hr_season, 1) if row.hr_14d is not None and hr_season is not None else None

        # Regime classification
        # Session 483: HOT gate — require picks_7d >= 5 AND hr_30d >= 50%.
        # Previously a signal could go HOT on N=1 (one lucky pick → divergence +83pp),
        # inflating the 1.2x multiplier for signals with terrible 30d records.
        # Example: bounce_back_over 100% 7d (N=1), 16.7% 30d — NOT legitimately HOT.
        if div_7d is not None and div_7d < COLD_THRESHOLD:
            regime = 'COLD'
        elif (div_7d is not None and div_7d > HOT_THRESHOLD
              and row.picks_7d >= 5
              and (row.hr_30d is None or row.hr_30d >= 50.0)):
            regime = 'HOT'
        else:
            regime = 'NORMAL'

        is_model_dep = row.signal_tag in MODEL_DEPENDENT_SIGNALS

        # Status
        # Session 478: guard DEGRADING with picks_7d >= 5 to suppress false alarms
        # from grading outages (fewer graded picks → COLD regime from small-N noise,
        # not real signal degradation). Insufficient data → WATCH, not DEGRADING.
        if regime == 'COLD' and is_model_dep:
            if row.picks_7d >= 5:
                status = 'DEGRADING'
            else:
                status = 'WATCH'  # Too few picks to distinguish degradation from grading gap
        elif div_7d is not None and div_7d < -5.0:
            status = 'WATCH'
        else:
            status = 'HEALTHY'

        results.append({
            'game_date': target_date,
            'signal_tag': row.signal_tag,
            'hr_7d': hr_7d,
            'hr_14d': row.hr_14d,
            'hr_30d': row.hr_30d,
            'hr_season': hr_season,
            'picks_7d': row.picks_7d,
            'picks_14d': row.picks_14d,
            'picks_30d': row.picks_30d,
            'picks_season': row.picks_season,
            'divergence_7d_vs_season': div_7d,
            'divergence_14d_vs_season': div_14d,
            'regime': regime,
            'status': status,
            'days_in_current_regime': None,  # Populated by consecutive-day logic below
            # Directional splits (Session 398)
            'hr_over_7d': row.hr_over_7d,
            'hr_under_7d': row.hr_under_7d,
            'hr_over_30d': row.hr_over_30d,
            'hr_under_30d': row.hr_under_30d,
            'picks_over_7d': row.picks_over_7d,
            'picks_under_7d': row.picks_under_7d,
            'picks_over_30d': row.picks_over_30d,
            'picks_under_30d': row.picks_under_30d,
            'is_model_dependent': is_model_dep,
            'computed_at': now,
        })

    # Compute days_in_current_regime by checking prior days
    _fill_regime_duration(bq_client, target_date, results)

    logger.info(
        f"Computed signal health for {target_date}: "
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

        # Build map: signal_tag -> list of (date, regime) sorted by date desc
        prior_map: Dict[str, List] = {}
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

    Session 400: Added dedup — deletes existing rows for the target date
    before appending. Prevents duplicate rows from reruns/backfills.
    Pattern copied from model_performance.py:455-491.
    """
    if not rows:
        return 0

    # DELETE existing rows for this date before writing
    target_date = rows[0]['game_date']
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
    logger.info(f"Wrote {len(rows)} signal health rows to {TABLE_ID}")
    return len(rows)


def get_signal_health_summary(
    bq_client: bigquery.Client,
    target_date: str,
) -> Dict[str, Dict[str, Any]]:
    """Get signal health summary for JSON export.

    Returns:
        Dict keyed by signal_tag with hr_7d, hr_season, regime, status.
    """
    query = f"""
    SELECT signal_tag, hr_7d, hr_season, regime, status, is_model_dependent
    FROM `{TABLE_ID}`
    WHERE game_date = @target_date
      AND signal_tag IN UNNEST(@active_signals)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', target_date),
            bigquery.ArrayQueryParameter('active_signals', 'STRING', sorted(ACTIVE_SIGNALS)),
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
        logger.warning(f"Could not load signal health for {target_date}: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(description="Signal Health Computation")
    parser.add_argument('--date', help='Single date to compute (YYYY-MM-DD)')
    parser.add_argument('--backfill', action='store_true', help='Backfill a date range')
    parser.add_argument('--start', default='2026-01-09', help='Backfill start date')
    parser.add_argument('--end', default='2026-02-14', help='Backfill end date')
    parser.add_argument('--dry-run', action='store_true', help='Print without writing')
    parser.add_argument('--canary', action='store_true',
                        help='Run signal firing canary (detect dead/degrading signals)')
    args = parser.parse_args()

    client = bigquery.Client(project=PROJECT_ID)

    # Signal firing canary mode (Session 387)
    if args.canary:
        from datetime import date as date_type
        check_date = args.date or str(date_type.today())
        print(f"\n=== Signal Firing Canary — {check_date} ===\n")
        alerts = check_signal_firing_canary(client, check_date)
        if alerts:
            msg = format_canary_slack_message(alerts, check_date)
            if msg:
                print(msg)
        else:
            print("All signals healthy — no alerts.")
        print(f"\nActive signals checked: {len(ACTIVE_SIGNALS)}")
        return

    if args.date:
        dates = [args.date]
    elif args.backfill:
        # Get game dates in range
        dates_q = f"""
        SELECT DISTINCT game_date
        FROM `{PROJECT_ID}.nba_predictions.pick_signal_tags`
        WHERE game_date BETWEEN @start AND @end
        ORDER BY game_date
        """
        dates_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("start", "DATE", args.start),
            bigquery.ScalarQueryParameter("end", "DATE", args.end),
        ])
        dates = [str(row.game_date) for row in client.query(dates_q, job_config=dates_config).result()]
    else:
        print("Specify --date or --backfill")
        sys.exit(1)

    print(f"Computing signal health for {len(dates)} date(s)")
    total = 0

    for i, date_str in enumerate(dates):
        rows = compute_signal_health(client, date_str)
        cold = sum(1 for r in rows if r['regime'] == 'COLD')
        degrading = sum(1 for r in rows if r['status'] == 'DEGRADING')
        print(f"[{i+1}/{len(dates)}] {date_str}: {len(rows)} signals, {cold} COLD, {degrading} DEGRADING")

        if not args.dry_run and rows:
            write_health_rows(client, rows)
            total += len(rows)

    print(f"\nTotal rows written: {total}")
    if args.dry_run:
        print("(DRY RUN — nothing written)")


if __name__ == '__main__':
    main()
