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
