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

Session 515: Edge-based auto-halt.
  - Trigger: 7d avg edge < 5.0 AND edge-5+ pick rate < 50%
  - Effect: Zero picks exported (halt before merge)
  - In normal seasons: never fires. In 2025-26: fires late Feb.
  - 2025-26 P/L impact: stopping Feb 28 = +31.07u vs +23.10u (34.5% better)
"""

import logging
from datetime import date, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


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
        # Session 515: Edge-based auto-halt
        'bb_auto_halt_active': False,
        'bb_auto_halt_reason': '',
        'rolling_7d_avg_edge': None,
        'rolling_7d_pct_edge_5plus': None,
        'edge_halt_days_sampled': 0,
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
        # Default to 'normal' — no regime adjustments
        return result

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

    # Session 515: Edge-based auto-halt
    # When 7d avg edge < 5.0 AND edge-5+ pick rate < 50%, the market is too
    # compressed for profitable picking. Halt all BB picks.
    # Walk-forward validated: in 2025-26, fires late Feb → saves +8 units.
    # In normal seasons (2021-2025): never fires (edge stays 4.0+ through April).
    try:
        edge_halt_query = """
            WITH daily_edges AS (
              SELECT
                game_date,
                AVG(ABS(predicted_points - current_points_line)) as avg_edge,
                COUNTIF(ABS(predicted_points - current_points_line) >= 5.0) as edge_5plus,
                COUNT(*) as total
              FROM `nba-props-platform.nba_predictions.player_prop_predictions`
              WHERE game_date >= DATE_SUB(@target_date, INTERVAL 7 DAY)
                AND game_date < @target_date
              GROUP BY game_date
            )
            SELECT
              ROUND(AVG(avg_edge), 2) as rolling_7d_avg_edge,
              ROUND(100.0 * SUM(edge_5plus) / NULLIF(SUM(total), 0), 1) as rolling_7d_pct_edge_5plus,
              COUNT(*) as days_sampled
            FROM daily_edges
        """
        edge_config = QueryJobConfig(
            query_parameters=[
                ScalarQueryParameter('target_date', 'DATE', target_date),
            ]
        )
        edge_rows = list(bq_client.query(edge_halt_query, job_config=edge_config).result())

        if edge_rows and edge_rows[0].rolling_7d_avg_edge is not None:
            row = edge_rows[0]
            avg_edge = float(row.rolling_7d_avg_edge)
            pct_5plus = float(row.rolling_7d_pct_edge_5plus) if row.rolling_7d_pct_edge_5plus else 0.0
            days_sampled = int(row.days_sampled)

            result['rolling_7d_avg_edge'] = avg_edge
            result['rolling_7d_pct_edge_5plus'] = pct_5plus
            result['edge_halt_days_sampled'] = days_sampled

            edge_threshold = 5.0
            pick_rate_threshold = 50.0

            if avg_edge < edge_threshold and pct_5plus < pick_rate_threshold and days_sampled >= 3:
                result['bb_auto_halt_active'] = True
                result['bb_auto_halt_reason'] = (
                    f"Edge-based auto-halt: 7d avg edge {avg_edge:.2f} < {edge_threshold} "
                    f"AND {pct_5plus:.1f}% edge-5+ picks < {pick_rate_threshold}% "
                    f"(N={days_sampled} days)"
                )
                logger.warning(result['bb_auto_halt_reason'])
            else:
                logger.info(
                    f"Edge metrics 7d: avg={avg_edge:.2f}, pct_5plus={pct_5plus:.1f}%, "
                    f"days={days_sampled} "
                    f"(halt threshold: avg<{edge_threshold} AND pct<{pick_rate_threshold}%)"
                )
    except Exception as e:
        logger.warning(f"Edge-based halt query failed (non-fatal): {e}")

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
