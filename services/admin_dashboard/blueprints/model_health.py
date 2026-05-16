"""
Model Health Blueprint - Per-model bias, MAE, and edge-vs-Vegas tracking.

Surfaces the data populated daily by `ml/analysis/model_performance.py` and the
alert verdicts from `bin/monitoring/bias_decay_monitor.py`. Designed as the
operational view for the 2025-26 anomaly diagnosis (see
docs/08-projects/current/2026-05-15-2025-26-anomaly-rootcause/).

Routes:
- GET /model-health: Full page (Tailwind + Chart.js + Alpine.js).
- GET /api/model-health/per-model: Latest per-enabled-model snapshot
                                    with derived verdict. Frontend filters this
                                    payload for the alert banner client-side.
- GET /api/model-health/fleet-trend: Time-series of fleet-aggregate metrics
                                      (pred_bias, mae_gap, model_mae, vegas_mae).
- GET /api/model-health/model/<model_id>/trend: Per-model 30-day trajectory.
"""

import os
import logging
from datetime import date as date_cls

from flask import Blueprint, jsonify, request, render_template
from google.cloud import bigquery

from services.admin_dashboard.services.rate_limiter import rate_limit
from services.admin_dashboard.services.auth import check_auth

# Thresholds + classify_verdict live in a single shared module — both this
# blueprint and `bin/monitoring/bias_decay_monitor.py` import from there so
# the dashboard banner can't disagree with the Slack alerts.
from shared.monitoring.bias_decay_thresholds import (
    LOST_EDGE_MAE_GAP,
    LOST_EDGE_DAYS_REQUIRED,  # noqa: F401 — re-exported via SQL substitution
    LOST_EDGE_WINDOW,
    LOSING_BAD_MAE_GAP,
    LOSING_BAD_DAYS_REQUIRED,  # noqa: F401
    LOSING_BAD_WINDOW,
    MIN_N_FOR_VERDICT,  # noqa: F401 — used by classify_verdict
    classify_verdict,
)

logger = logging.getLogger(__name__)

model_health_bp = Blueprint('model_health', __name__)


def get_bq_client():
    project_id = os.environ.get('GCP_PROJECT_ID')
    return bigquery.Client(project=project_id)


def clamp_param(value, min_val: int, max_val: int, default: int) -> int:
    try:
        val = int(value)
        return max(min_val, min(max_val, val))
    except (TypeError, ValueError):
        return default


@model_health_bp.route('/model-health')
@rate_limit
def model_health_page():
    """Main Model Health page."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    sport = request.args.get('sport', 'nba')
    return render_template('model_health.html', sport=sport)


@model_health_bp.route('/api/model-health/per-model')
@rate_limit
def api_per_model():
    """Latest snapshot per enabled model, with derived verdict + lookback counts.

    Reads `model_performance_daily` for the most recent row in the last 14
    days per (enabled) model, plus rolling counts used by the verdict.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    project_id = os.environ.get('GCP_PROJECT_ID')
    include_all = request.args.get('include_disabled', 'false').lower() == 'true'

    enabled_filter = '' if include_all else 'JOIN active a USING (model_id)'
    enabled_cte = (
        '' if include_all else
        f"WITH active AS ("
        f"  SELECT model_id FROM `{project_id}.nba_predictions.model_registry`"
        f"  WHERE enabled = TRUE"
        f"), "
    )
    leading_with = 'WITH' if include_all else ''

    query = f"""
    {enabled_cte}{leading_with}
    recent AS (
      SELECT
        mpd.game_date, mpd.model_id,
        mpd.pred_bias_7d, mpd.pred_bias_14d, mpd.pred_bias_30d,
        mpd.model_mae_7d, mpd.vegas_mae_7d, mpd.mae_gap_7d,
        mpd.rolling_hr_7d, mpd.rolling_n_7d,
        mpd.state AS hr_state, mpd.days_since_training,
        ROW_NUMBER() OVER (PARTITION BY mpd.model_id ORDER BY mpd.game_date DESC) AS rn
      FROM `{project_id}.nba_predictions.model_performance_daily` mpd
      {enabled_filter}
      WHERE mpd.game_date BETWEEN DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
                              AND CURRENT_DATE()
    ),
    consec AS (
      SELECT
        model_id,
        COUNTIF(mae_gap_7d > {LOST_EDGE_MAE_GAP}
                AND game_date > DATE_SUB(CURRENT_DATE(), INTERVAL {LOST_EDGE_WINDOW} DAY))
          AS lost_edge_days,
        COUNTIF(mae_gap_7d > {LOSING_BAD_MAE_GAP}
                AND game_date > DATE_SUB(CURRENT_DATE(), INTERVAL {LOSING_BAD_WINDOW} DAY))
          AS losing_bad_days
      FROM recent
      GROUP BY model_id
    )
    SELECT
      r.game_date, r.model_id,
      r.pred_bias_7d, r.pred_bias_14d, r.pred_bias_30d,
      r.model_mae_7d, r.vegas_mae_7d, r.mae_gap_7d,
      r.rolling_hr_7d, r.rolling_n_7d, r.hr_state, r.days_since_training,
      c.lost_edge_days, c.losing_bad_days
    FROM recent r
    JOIN consec c USING (model_id)
    WHERE r.rn = 1
    ORDER BY r.model_id
    """

    try:
        client = get_bq_client()
        rows = [dict(r) for r in client.query(query).result()]
        for r in rows:
            r['verdict'] = classify_verdict(r)
            # Serialize dates
            if r.get('game_date'):
                r['game_date'] = r['game_date'].isoformat()
        return jsonify({'data': rows, 'count': len(rows)})
    except Exception as e:
        logger.error(f"Error fetching per-model snapshot: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@model_health_bp.route('/api/model-health/fleet-trend')
@rate_limit
def api_fleet_trend():
    """Fleet-aggregate metrics over time.

    Aggregates across enabled models. Sample-weighted means so a model with
    1000 graded predictions contributes more than one with 20.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 60), 7, 365, 60)
    project_id = os.environ.get('GCP_PROJECT_ID')

    query = f"""
    WITH active AS (
      SELECT model_id
      FROM `{project_id}.nba_predictions.model_registry`
      WHERE enabled = TRUE
    )
    SELECT
      mpd.game_date,
      -- Sample-weighted aggregates (each model weighted by its rolling_n_7d)
      SAFE_DIVIDE(
        SUM(mpd.pred_bias_7d * mpd.rolling_n_7d),
        SUM(mpd.rolling_n_7d)
      ) AS fleet_pred_bias_7d,
      SAFE_DIVIDE(
        SUM(mpd.mae_gap_7d * mpd.rolling_n_7d),
        SUM(mpd.rolling_n_7d)
      ) AS fleet_mae_gap_7d,
      SAFE_DIVIDE(
        SUM(mpd.model_mae_7d * mpd.rolling_n_7d),
        SUM(mpd.rolling_n_7d)
      ) AS fleet_model_mae_7d,
      SAFE_DIVIDE(
        SUM(mpd.vegas_mae_7d * mpd.rolling_n_7d),
        SUM(mpd.rolling_n_7d)
      ) AS fleet_vegas_mae_7d,
      SAFE_DIVIDE(
        SUM(mpd.rolling_hr_7d * mpd.rolling_n_7d),
        SUM(mpd.rolling_n_7d)
      ) AS fleet_hr_7d,
      SUM(mpd.rolling_n_7d) AS fleet_n_7d,
      COUNT(DISTINCT mpd.model_id) AS active_models
    FROM `{project_id}.nba_predictions.model_performance_daily` mpd
    JOIN active a USING (model_id)
    WHERE mpd.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
      AND mpd.rolling_n_7d > 0
    GROUP BY mpd.game_date
    ORDER BY mpd.game_date
    """

    try:
        client = get_bq_client()
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter('days', 'INT64', days)]
        )
        results = client.query(query, job_config=job_config).result()
        data = []
        for row in results:
            d = dict(row)
            if d.get('game_date'):
                d['game_date'] = d['game_date'].isoformat()
            # Round for cleaner display; keep None as None
            for k in ('fleet_pred_bias_7d', 'fleet_mae_gap_7d',
                      'fleet_model_mae_7d', 'fleet_vegas_mae_7d',
                      'fleet_hr_7d'):
                v = d.get(k)
                if v is not None:
                    d[k] = round(float(v), 3)
            data.append(d)
        return jsonify({'data': data, 'days': days})
    except Exception as e:
        logger.error(f"Error fetching fleet trend: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@model_health_bp.route('/api/model-health/model/<model_id>/trend')
@rate_limit
def api_model_trend(model_id: str):
    """30-day per-model trajectory for the drill-down view."""
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days', 60), 7, 365, 60)
    project_id = os.environ.get('GCP_PROJECT_ID')

    query = f"""
    SELECT
      game_date,
      pred_bias_7d, pred_bias_14d, pred_bias_30d,
      model_mae_7d, vegas_mae_7d, mae_gap_7d,
      rolling_hr_7d, rolling_n_7d, state
    FROM `{project_id}.nba_predictions.model_performance_daily`
    WHERE model_id = @model_id
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
    ORDER BY game_date
    """

    try:
        client = get_bq_client()
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('model_id', 'STRING', model_id),
                bigquery.ScalarQueryParameter('days', 'INT64', days),
            ]
        )
        results = client.query(query, job_config=job_config).result()
        data = []
        for row in results:
            d = dict(row)
            if d.get('game_date'):
                d['game_date'] = d['game_date'].isoformat()
            data.append(d)
        return jsonify({'model_id': model_id, 'data': data, 'days': days})
    except Exception as e:
        logger.error(f"Error fetching model trend for {model_id}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
