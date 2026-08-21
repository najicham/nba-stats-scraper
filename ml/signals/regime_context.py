"""Daily regime context based on yesterday's best bets hit rate.

Session 412: BB HR autocorrelation r=0.43 — after a bad day (<50%),
next day averages 53.9%. After great (75%+), 72.2%. OVER HR swings
33-67% by regime while UNDER stays 50%+. Tightening OVER exposure
after bad days is the high-leverage move.

Regime classification:
  - cautious: yesterday BB HR < 50% AND N >= 5
    → raise OVER edge floor +1.0 (5→6), disable OVER signal rescue
  - normal: 50-74% or insufficient data → no changes
  - confident: 75%+ → no changes (don't loosen)

Edge degeneracy guard (rewritten 2026-08-21, was the "edge-collapse auto-halt"):
  - Trigger: 7d median-across-models edge < 0.35 AND edge-3+ share < 0.30%
  - Release: either condition recovers past a 10% band for 2 consecutive days,
    or the halt hits its 14-day automatic lifetime
  - Effect: Zero picks exported (halt before merge)
  - Thresholds, basis and validation live in shared/config/edge_halt.py.

  This is a pathology detector, not a market circuit breaker. The Session 515
  version fired on 865 of 865 prediction-days; the 2026-08-19 rewrite fixed that
  but was calibrated on a fleet-composition artifact — on a fixed model set the
  2026 collapse does not appear at all. Read the WHY THE MARKET-BREAKER FRAMING
  WAS RETIRED section in shared/config/edge_halt.py before touching the numbers.
  Real collapse detection is drawdown-based and lives in halt_state.
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

from shared.config.edge_halt import (
    HALT_EDGE_MEDIAN,
    HALT_PCT_EDGE_3PLUS,
    resolve_halt_state,
)

logger = logging.getLogger(__name__)


def _apply_warmup_guard(result: Dict[str, Any]) -> Dict[str, Any]:
    """Fail CLOSED to a conservative posture when trailing windows are empty.

    2026-07-03: At 2026-27 season open the trailing edge/BB windows are empty,
    so every regime lever (edge auto-halt, TIGHT-market OVER floor, cautious
    regime) defaults to OFF/permissive. That is the WRONG default before we have
    any live evidence. When the edge-halt window has < 3 distinct prediction-days
    sampled, treat it as warmup and adopt the TIGHT/cautious posture:
      - raise the OVER edge floor to its TIGHT value (+1.0 → 6.0 base becomes 7.0)
      - disable OVER signal rescue
      - flag that UNDERs should require real_sc >= 2 (already the aggregator
        default, surfaced here for the exporter/observability)

    Behavior-preserving once >= 3 days of edge history exist (warmup=False) —
    the normal regime logic then owns these fields.
    """
    days_sampled = result.get('edge_halt_days_sampled') or 0
    yesterday_picks = result.get('yesterday_bb_picks') or 0

    # 2026-07-03 (revised): trigger on days_sampled < 3 ALONE. The earlier
    # `AND yesterday_picks == 0` disarmed the guard on day 2 of the season (once
    # day-1 picks graded), so it only protected opening day. days_sampled counts
    # distinct prediction-days in the trailing 7d window; mid-season it is 5-7
    # (predictions generate daily even under halt), so < 3 fires only at true
    # season open or after a 5+ day prediction outage / All-Star break — where a
    # conservative posture is desirable anyway.
    if days_sampled < 3:
        result['warmup_conservative'] = True
        # Raise OVER floor to TIGHT value and disable OVER rescue (fail closed).
        result['over_edge_floor_delta'] = max(
            result.get('over_edge_floor_delta', 0.0), 1.0)
        result['disable_over_rescue'] = True
        # Surface the UNDER real_sc>=2 requirement (aggregator already enforces
        # this as its default UNDER floor; expose it so the exporter can report it).
        result['under_min_real_sc'] = 2
        # halt_source matters for reading this log: days_sampled is 0 on the
        # fallback and fail-closed paths too, so mid-season this line can mean
        # "the edge query failed", not "the season just opened".
        logger.warning(
            "Warmup guard ACTIVE (edge_halt_days_sampled=%s, yesterday_bb_picks=%s, "
            "edge_halt_source=%s): conservative posture — OVER floor +1.0, "
            "OVER rescue disabled, UNDER real_sc>=2.",
            days_sampled, yesterday_picks, result.get('edge_halt_source', 'unknown'),
        )
    else:
        result.setdefault('warmup_conservative', False)

    return result


def get_regime_context(bq_client, target_date: date) -> Dict[str, Any]:
    """Query yesterday's BB HR and classify the regime.

    Returns dict with:
        yesterday_bb_hr: float or None
        yesterday_bb_picks: int
        regime_state: 'cautious' | 'normal' | 'confident'
        over_edge_floor_delta: +1.0 (cautious) or 0.0
        disable_over_rescue: True (cautious) or False
        mae_gap_7d: float or None (model MAE - Vegas MAE, 7d rolling)
        num_games_on_slate: int or None (games scheduled for target_date)
    """
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    yesterday = target_date - timedelta(days=1)
    result = {
        'yesterday_bb_hr': None,
        'yesterday_bb_picks': 0,
        'regime_state': 'normal',
        'over_edge_floor_delta': 0.0,
        'disable_over_rescue': False,
        'mae_gap_7d': None,
        'vegas_mae_7d': None,
        'num_games_on_slate': None,
        # Edge degeneracy guard (see shared/config/edge_halt.py)
        'bb_auto_halt_active': False,
        'bb_auto_halt_reason': '',
        'rolling_7d_edge_median': None,
        'rolling_7d_pct_edge_3plus': None,
        'edge_halt_days_sampled': 0,
        'edge_halt_release_streak': 0,
        'edge_halt_models_7d': None,
        'edge_halt_source': 'unknown',
        # Back-compat aliases for existing exporter/halt_state diagnostics.
        'rolling_7d_avg_edge': None,
        'rolling_7d_pct_edge_5plus': None,
        # 2026-07-03: warmup fail-closed posture (see _apply_warmup_guard)
        'warmup_conservative': False,
        'under_min_real_sc': None,
    }

    try:
        query = """
            SELECT
                COUNT(*) as total_picks,
                COUNTIF(prediction_correct) as wins,
                ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNT(*), 0), 1) as hit_rate
            FROM `nba-props-platform.nba_predictions.prediction_accuracy`
            WHERE game_date = @yesterday
              AND has_prop_line = TRUE
              AND recommendation IN ('OVER', 'UNDER')
              AND prediction_correct IS NOT NULL
              AND system_id IN (
                  SELECT system_id FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
                  WHERE game_date = @yesterday
                    AND player_lookup IN (
                        SELECT player_lookup FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
                        WHERE game_date = @yesterday
                    )
              )
        """
        # Simpler approach: use signal_best_bets_picks directly for yesterday's BB HR
        query = """
            SELECT
                COUNT(*) as total_picks,
                COUNTIF(p.prediction_correct) as wins,
                ROUND(100.0 * COUNTIF(p.prediction_correct) / NULLIF(COUNT(*), 0), 1) as hit_rate
            FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` bb
            JOIN `nba-props-platform.nba_predictions.prediction_accuracy` p
              ON bb.player_lookup = p.player_lookup
              AND bb.game_date = p.game_date
              AND bb.system_id = p.system_id
              AND p.recommendation = bb.recommendation
              AND p.line_value = bb.line_value
            WHERE bb.game_date = @yesterday
              AND p.prediction_correct IS NOT NULL
        """
        from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter
        job_config = QueryJobConfig(
            query_parameters=[
                ScalarQueryParameter('yesterday', 'DATE', yesterday),
            ]
        )
        rows = list(bq_client.query(query, job_config=job_config).result())

        if rows and rows[0].total_picks > 0:
            row = rows[0]
            result['yesterday_bb_hr'] = float(row.hit_rate)
            result['yesterday_bb_picks'] = row.total_picks

            result['regime_state'] = _classify_regime(
                float(row.hit_rate), row.total_picks
            )
    except Exception as e:
        logger.warning(f"Regime context query failed (non-fatal): {e}")
        # 2026-07-03 (revised): do NOT early-return here. The old early return
        # skipped the TIGHT-market check AND the entire edge-based auto-halt
        # evaluation below — so a transient failure of THIS (yesterday-HR) query
        # would lift an active edge-collapse halt (fail OPEN). Instead fall
        # through: regime_state stays 'normal' (a no-op below), while the macro
        # and edge-halt queries still run under their own try/except, and the
        # end-of-function warmup guard still applies the conservative posture
        # when the trailing windows are empty.

    # Apply regime effects
    if result['regime_state'] == 'cautious':
        result['over_edge_floor_delta'] = 1.0
        result['disable_over_rescue'] = True

    logger.info(
        f"Regime context: {result['regime_state']} "
        f"(yesterday HR={result['yesterday_bb_hr']}%, "
        f"N={result['yesterday_bb_picks']})"
    )

    # Session 442: MAE gap — when model MAE exceeds Vegas MAE, BB HR craters.
    # Session 483: Also fetch vegas_mae_7d and market_regime. When TIGHT (MAE < 4.5),
    # raise OVER floor +1.0 and disable rescue — the market is too accurate to exploit.
    # March 8 root cause: vegas_mae was 4.40 (TIGHT) but system kept generating picks.
    try:
        macro_query = """
            SELECT mae_gap_7d, vegas_mae_7d, market_regime
            FROM `nba-props-platform.nba_predictions.league_macro_daily`
            WHERE game_date = @yesterday
        """
        from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter
        macro_config = QueryJobConfig(
            query_parameters=[
                ScalarQueryParameter('yesterday', 'DATE', yesterday),
            ]
        )
        macro_rows = list(bq_client.query(macro_query, job_config=macro_config).result())
        if macro_rows:
            row = macro_rows[0]
            if row.mae_gap_7d is not None:
                result['mae_gap_7d'] = round(float(row.mae_gap_7d), 3)
                logger.info(f"MAE gap (yesterday): {result['mae_gap_7d']}")
            if row.vegas_mae_7d is not None:
                vegas_mae = float(row.vegas_mae_7d)
                result['vegas_mae_7d'] = round(vegas_mae, 3)
                market_regime = getattr(row, 'market_regime', None)
                logger.info(f"Vegas MAE (yesterday): {vegas_mae:.2f}, regime: {market_regime}")
                # TIGHT market: books are highly accurate, OVER edge is model noise not opportunity.
                # Raise floor +1.0 (5.0→6.0) and disable all OVER rescue.
                if vegas_mae < 4.5:
                    result['over_edge_floor_delta'] = max(result['over_edge_floor_delta'], 1.0)
                    result['disable_over_rescue'] = True
                    logger.warning(
                        f"TIGHT market (vegas_mae={vegas_mae:.2f} < 4.5): "
                        f"raising OVER floor +1.0 and disabling OVER rescue"
                    )
    except Exception as e:
        logger.warning(f"MAE gap / Vegas MAE query failed (non-fatal): {e}")

    # Session 442: Slate size — thin slates (4-6 games) have 51.2% BB HR.
    try:
        slate_query = """
            SELECT COUNT(*) as num_games
            FROM `nba-props-platform.nba_reference.nba_schedule`
            WHERE game_date = @target_date
              AND game_status IN (1, 2, 3)
        """
        from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter
        slate_config = QueryJobConfig(
            query_parameters=[
                ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )
        slate_rows = list(bq_client.query(slate_query, job_config=slate_config).result())
        if slate_rows and slate_rows[0].num_games is not None:
            result['num_games_on_slate'] = slate_rows[0].num_games
            logger.info(f"Slate size: {result['num_games_on_slate']} games")
    except Exception as e:
        logger.warning(f"Slate size query failed (non-fatal): {e}")

    # Edge degeneracy guard. `resolve_halt_state` never fails open: on a query
    # error it carries forward the most recent halt_state row, and only halts
    # outright when that is unavailable too. The previous `query_halt_state`
    # returned a bare None on error and this block left bb_auto_halt_active at
    # False — a transient BigQuery failure during a real halt published picks.
    halt = resolve_halt_state(bq_client, target_date, sport='nba')
    result['rolling_7d_edge_median'] = halt['edge_med_7d']
    result['rolling_7d_pct_edge_3plus'] = halt['pct_e3_7d']
    result['edge_halt_days_sampled'] = halt['days_sampled']
    result['edge_halt_release_streak'] = halt['release_streak']
    result['edge_halt_models_7d'] = halt['models_7d']
    result['edge_halt_source'] = halt['halt_source']
    # Back-compat aliases: the exporter and halt_state JSON still publish
    # these key names as diagnostics.
    result['rolling_7d_avg_edge'] = halt['edge_med_7d']
    result['rolling_7d_pct_edge_5plus'] = halt['pct_e3_7d']

    if halt['halt_active']:
        result['bb_auto_halt_active'] = True
        result['bb_auto_halt_reason'] = halt['reason'] or 'edge degeneracy halt'
        logger.warning(result['bb_auto_halt_reason'])
    else:
        logger.info(
            "Edge metrics 7d: median=%s, pct_e3=%s%%, models=%s, days=%s, source=%s "
            "(halt threshold: median<%s AND pct_e3<%s%%)",
            halt['edge_med_7d'], halt['pct_e3_7d'], halt['models_7d'],
            halt['days_sampled'], halt['halt_source'],
            HALT_EDGE_MEDIAN, HALT_PCT_EDGE_3PLUS,
        )

    # 2026-07-03: Season-open fail-closed guard. When trailing windows are empty
    # (edge_halt_days_sampled < 3 AND no BB picks yesterday), adopt the
    # conservative posture instead of the permissive defaults. No-op once >= 3
    # days of history exist.
    result = _apply_warmup_guard(result)

    return result


def get_market_compression(bq_client, target_date) -> Dict[str, Any]:
    """Query edge distribution to detect market compression.

    Session 421: Compares 7d vs 30d P90 edge at edge 3+ to detect
    compression. During toxic windows (Jan 30-Feb 25), edge compresses
    severely (ratio 0.596 RED). Observation mode — logged but not acted on.

    Returns dict with:
        p90_edge_7d: float or None
        p90_edge_30d: float or None
        avg_edge_7d: float or None
        avg_edge_30d: float or None
        compression_ratio: float or None (p90_7d / p90_30d)
        status: 'RED' (<0.70) | 'YELLOW' (0.70-0.85) | 'GREEN' (>0.85)
    """
    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)

    result = {
        'p90_edge_7d': None,
        'p90_edge_30d': None,
        'avg_edge_7d': None,
        'avg_edge_30d': None,
        'compression_ratio': None,
        'status': None,
    }

    try:
        query = """
            SELECT
                APPROX_QUANTILES(
                    CASE WHEN game_date >= DATE_SUB(@target_date, INTERVAL 7 DAY)
                    THEN ABS(predicted_points - line_value) END,
                    100
                )[OFFSET(90)] as p90_edge_7d,
                APPROX_QUANTILES(
                    ABS(predicted_points - line_value),
                    100
                )[OFFSET(90)] as p90_edge_30d,
                AVG(CASE WHEN game_date >= DATE_SUB(@target_date, INTERVAL 7 DAY)
                    THEN ABS(predicted_points - line_value) END) as avg_edge_7d,
                AVG(ABS(predicted_points - line_value)) as avg_edge_30d
            FROM `nba-props-platform.nba_predictions.prediction_accuracy`
            WHERE game_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
              AND game_date < @target_date
              AND has_prop_line = TRUE
              AND recommendation IN ('OVER', 'UNDER')
              AND prediction_correct IS NOT NULL
              AND ABS(predicted_points - line_value) >= 3.0
        """
        from google.cloud.bigquery import QueryJobConfig, ScalarQueryParameter
        job_config = QueryJobConfig(
            query_parameters=[
                ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )
        rows = list(bq_client.query(query, job_config=job_config).result())

        if rows and rows[0].p90_edge_7d is not None and rows[0].p90_edge_30d is not None:
            row = rows[0]
            result['p90_edge_7d'] = round(float(row.p90_edge_7d), 2)
            result['p90_edge_30d'] = round(float(row.p90_edge_30d), 2)
            result['avg_edge_7d'] = round(float(row.avg_edge_7d), 2) if row.avg_edge_7d else None
            result['avg_edge_30d'] = round(float(row.avg_edge_30d), 2) if row.avg_edge_30d else None

            ratio = float(row.p90_edge_7d) / float(row.p90_edge_30d)
            result['compression_ratio'] = round(ratio, 3)
            if ratio < 0.70:
                result['status'] = 'RED'
            elif ratio < 0.85:
                result['status'] = 'YELLOW'
            else:
                result['status'] = 'GREEN'

            logger.info(
                f"Market compression: {result['status']} "
                f"(ratio={result['compression_ratio']}, "
                f"p90_7d={result['p90_edge_7d']}, "
                f"p90_30d={result['p90_edge_30d']})"
            )
    except Exception as e:
        logger.warning(f"Market compression query failed (non-fatal): {e}")

    return result


def _classify_regime(hr: float, n_picks: int) -> str:
    """Classify regime based on yesterday's BB hit rate.

    Thresholds from Session 411 autocorrelation analysis:
    - Bad day (<50%): next day averages 53.9% (cautious)
    - Great day (75%+): next day averages 72.2% (confident)
    - Normal: no regime adjustment needed
    """
    if n_picks < 5:
        return 'normal'  # Insufficient data
    if hr < 50.0:
        return 'cautious'
    if hr >= 75.0:
        return 'confident'
    return 'normal'
