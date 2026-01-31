"""
League Trends Blueprint

API endpoints for the League Trend Monitoring system.
Provides data for early warning detection of model drift through
league-wide and cohort-level trend analysis.

Created: 2026-01-30
"""

import os
import logging
from flask import Blueprint, jsonify, request
from google.cloud import bigquery

logger = logging.getLogger(__name__)

league_trends_bp = Blueprint('league_trends', __name__)

# Rate limiting decorator (import from main app)
try:
    from ..app import rate_limit, check_auth
except ImportError:
    # Fallback for testing
    def rate_limit(f):
        return f
    def check_auth():
        return True, None


def get_bq_client():
    """Get BigQuery client."""
    project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
    return bigquery.Client(project=project_id)


def clamp_param(value, min_val, max_val, default):
    """Clamp a parameter to valid range."""
    try:
        val = int(value) if value else default
        return max(min_val, min(max_val, val))
    except (ValueError, TypeError):
        return default


@league_trends_bp.route('/api/league-trends/scoring')
@rate_limit
def api_scoring_trends():
    """Get league-wide scoring environment trends.

    Query params:
        weeks (int): Number of weeks to return (1-12, default 8)

    Returns:
        JSON with weekly scoring metrics including:
        - avg_points, scoring_volatility
        - line_mae, line_bias
        - pct_overs_hitting
        - alert status
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    weeks = clamp_param(request.args.get('weeks'), 1, 12, 8)

    try:
        client = get_bq_client()
        query = f"""
        SELECT *
        FROM `nba_trend_monitoring.league_scoring_trends`
        WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
        ORDER BY week_start DESC
        """
        results = client.query(query).result()
        data = []
        for row in results:
            data.append({
                'week_start': str(row.week_start),
                'games': row.games,
                'players': row.players,
                'predictions': row.predictions,
                'avg_points': float(row.avg_points) if row.avg_points else None,
                'scoring_volatility': float(row.scoring_volatility) if row.scoring_volatility else None,
                'line_mae': float(row.line_mae) if row.line_mae else None,
                'line_bias': float(row.line_bias) if row.line_bias else None,
                'pct_overs_hitting': float(row.pct_overs_hitting) if row.pct_overs_hitting else None,
                'zero_point_pct': float(row.zero_point_pct) if row.zero_point_pct else None,
                'scoring_alert': row.scoring_alert,
                'market_balance_alert': row.market_balance_alert,
            })

        return jsonify({'data': data, 'weeks': weeks})

    except Exception as e:
        logger.error(f"Error fetching scoring trends: {e}")
        return jsonify({'error': str(e)}), 500


@league_trends_bp.route('/api/league-trends/cohorts')
@rate_limit
def api_cohort_trends():
    """Get performance trends by player cohort (star/starter/rotation/bench).

    Query params:
        weeks (int): Number of weeks to return (1-12, default 8)
        cohort (str): Filter to specific cohort (optional)

    Returns:
        JSON with cohort-level metrics including:
        - avg_actual, avg_predicted, prediction_bias
        - hit_rate, over_hit_rate, under_hit_rate
        - recommendation counts
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    weeks = clamp_param(request.args.get('weeks'), 1, 12, 8)
    cohort_filter = request.args.get('cohort', '')

    try:
        client = get_bq_client()

        cohort_clause = ""
        if cohort_filter and cohort_filter in ['star', 'starter', 'rotation', 'bench']:
            cohort_clause = f"AND player_cohort = '{cohort_filter}'"

        query = f"""
        SELECT *
        FROM `nba_trend_monitoring.cohort_performance_trends`
        WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
        {cohort_clause}
        ORDER BY week_start DESC, player_cohort
        """
        results = client.query(query).result()
        data = []
        for row in results:
            data.append({
                'week_start': str(row.week_start),
                'player_cohort': row.player_cohort,
                'predictions': row.predictions,
                'avg_actual': float(row.avg_actual) if row.avg_actual else None,
                'avg_predicted': float(row.avg_predicted) if row.avg_predicted else None,
                'avg_line': float(row.avg_line) if row.avg_line else None,
                'prediction_bias': float(row.prediction_bias) if row.prediction_bias else None,
                'vs_line_performance': float(row.vs_line_performance) if row.vs_line_performance else None,
                'hit_rate': float(row.hit_rate) if row.hit_rate else None,
                'avg_confidence': float(row.avg_confidence) if row.avg_confidence else None,
                'over_count': row.over_count,
                'under_count': row.under_count,
                'pass_count': row.pass_count,
                'over_hit_rate': float(row.over_hit_rate) if row.over_hit_rate else None,
                'under_hit_rate': float(row.under_hit_rate) if row.under_hit_rate else None,
            })

        return jsonify({'data': data, 'weeks': weeks, 'cohort': cohort_filter or 'all'})

    except Exception as e:
        logger.error(f"Error fetching cohort trends: {e}")
        return jsonify({'error': str(e)}), 500


@league_trends_bp.route('/api/league-trends/model-health')
@rate_limit
def api_model_health_trends():
    """Get model health metrics including confidence calibration.

    Query params:
        weeks (int): Number of weeks to return (1-12, default 8)

    Returns:
        JSON with model health metrics including:
        - overall_hit_rate, overall_bias
        - confidence bucket hit rates and calibration errors
        - recommendation balance
        - alert status
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    weeks = clamp_param(request.args.get('weeks'), 1, 12, 8)

    try:
        client = get_bq_client()
        query = f"""
        SELECT *
        FROM `nba_trend_monitoring.model_health_trends`
        WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
        ORDER BY week_start DESC
        """
        results = client.query(query).result()
        data = []
        for row in results:
            data.append({
                'week_start': str(row.week_start),
                'total_predictions': row.total_predictions,
                'graded_predictions': row.graded_predictions,
                'overall_hit_rate': float(row.overall_hit_rate) if row.overall_hit_rate else None,
                'overall_bias': float(row.overall_bias) if row.overall_bias else None,
                'over_bias': float(row.over_bias) if row.over_bias else None,
                'under_bias': float(row.under_bias) if row.under_bias else None,
                'conf_90_hit_rate': float(row.conf_90_hit_rate) if row.conf_90_hit_rate else None,
                'conf_85_90_hit_rate': float(row.conf_85_90_hit_rate) if row.conf_85_90_hit_rate else None,
                'conf_80_85_hit_rate': float(row.conf_80_85_hit_rate) if row.conf_80_85_hit_rate else None,
                'conf_90_count': row.conf_90_count,
                'conf_85_90_count': row.conf_85_90_count,
                'conf_80_85_count': row.conf_80_85_count,
                'pct_over_recs': float(row.pct_over_recs) if row.pct_over_recs else None,
                'pct_under_recs': float(row.pct_under_recs) if row.pct_under_recs else None,
                'over_hit_rate': float(row.over_hit_rate) if row.over_hit_rate else None,
                'under_hit_rate': float(row.under_hit_rate) if row.under_hit_rate else None,
                'mae': float(row.mae) if row.mae else None,
                'error_std': float(row.error_std) if row.error_std else None,
                'bias_alert': row.bias_alert,
                'calibration_alert': row.calibration_alert,
                'recommendation_balance_alert': row.recommendation_balance_alert,
            })

        return jsonify({'data': data, 'weeks': weeks})

    except Exception as e:
        logger.error(f"Error fetching model health trends: {e}")
        return jsonify({'error': str(e)}), 500


@league_trends_bp.route('/api/league-trends/alerts')
@rate_limit
def api_trend_alerts():
    """Get current active alerts from trend monitoring.

    Returns:
        JSON with list of active alerts including:
        - category, severity, description
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()
        query = """
        SELECT *
        FROM `nba_trend_monitoring.trend_alerts_summary`
        """
        results = client.query(query).result()
        data = []
        for row in results:
            data.append({
                'category': row.category,
                'severity': row.severity,
                'description': row.description,
            })

        return jsonify({
            'data': data,
            'alert_count': len(data),
            'has_critical': any(d['severity'] == 'CRITICAL' for d in data),
            'has_warning': any(d['severity'] == 'WARNING' for d in data),
        })

    except Exception as e:
        logger.error(f"Error fetching trend alerts: {e}")
        return jsonify({'error': str(e)}), 500


@league_trends_bp.route('/api/league-trends/daily')
@rate_limit
def api_daily_trends():
    """Get daily trend summary for the last 30 days.

    Query params:
        days (int): Number of days to return (1-60, default 30)

    Returns:
        JSON with daily metrics for quick trend checks.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    days = clamp_param(request.args.get('days'), 1, 60, 30)

    try:
        client = get_bq_client()
        query = f"""
        SELECT *
        FROM `nba_trend_monitoring.daily_trend_summary`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
        ORDER BY game_date DESC
        """
        results = client.query(query).result()
        data = []
        for row in results:
            data.append({
                'game_date': str(row.game_date),
                'predictions': row.predictions,
                'graded': row.graded,
                'hit_rate': float(row.hit_rate) if row.hit_rate else None,
                'avg_actual': float(row.avg_actual) if row.avg_actual else None,
                'avg_predicted': float(row.avg_predicted) if row.avg_predicted else None,
                'bias': float(row.bias) if row.bias else None,
                'avg_confidence': float(row.avg_confidence) if row.avg_confidence else None,
                'pct_over': float(row.pct_over) if row.pct_over else None,
                'over_hit_rate': float(row.over_hit_rate) if row.over_hit_rate else None,
                'under_hit_rate': float(row.under_hit_rate) if row.under_hit_rate else None,
                'dnp_count': row.dnp_count,
            })

        return jsonify({'data': data, 'days': days})

    except Exception as e:
        logger.error(f"Error fetching daily trends: {e}")
        return jsonify({'error': str(e)}), 500


@league_trends_bp.route('/api/league-trends/star-players')
@rate_limit
def api_star_player_trends():
    """Get performance trends for star players (line >= 20).

    Query params:
        weeks (int): Number of weeks to return (1-12, default 4)
        player (str): Filter to specific player_lookup (optional)

    Returns:
        JSON with star player weekly performance.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    weeks = clamp_param(request.args.get('weeks'), 1, 12, 4)
    player_filter = request.args.get('player', '')

    try:
        client = get_bq_client()

        player_clause = ""
        if player_filter:
            # Sanitize input
            player_filter = player_filter.replace("'", "").replace('"', '')[:50]
            player_clause = f"AND player_lookup = '{player_filter}'"

        query = f"""
        SELECT *
        FROM `nba_trend_monitoring.star_player_trends`
        WHERE week_start >= DATE_SUB(CURRENT_DATE(), INTERVAL {weeks} WEEK)
        {player_clause}
        ORDER BY week_start DESC, avg_line DESC
        LIMIT 100
        """
        results = client.query(query).result()
        data = []
        for row in results:
            data.append({
                'week_start': str(row.week_start),
                'player_lookup': row.player_lookup,
                'games': row.games,
                'avg_actual': float(row.avg_actual) if row.avg_actual else None,
                'avg_predicted': float(row.avg_predicted) if row.avg_predicted else None,
                'avg_line': float(row.avg_line) if row.avg_line else None,
                'prediction_bias': float(row.prediction_bias) if row.prediction_bias else None,
                'vs_line': float(row.vs_line) if row.vs_line else None,
                'times_over': row.times_over,
                'times_under': row.times_under,
                'hit_rate': float(row.hit_rate) if row.hit_rate else None,
                'dnp_games': row.dnp_games,
            })

        return jsonify({'data': data, 'weeks': weeks, 'player': player_filter or 'all'})

    except Exception as e:
        logger.error(f"Error fetching star player trends: {e}")
        return jsonify({'error': str(e)}), 500


@league_trends_bp.route('/api/league-trends/summary')
@rate_limit
def api_trend_summary():
    """Get a comprehensive trend summary for quick health check.

    Returns:
        JSON with key metrics from all trend categories.
    """
    is_valid, error = check_auth()
    if not is_valid:
        return error

    try:
        client = get_bq_client()

        # Get latest scoring trends
        scoring_query = """
        SELECT * FROM `nba_trend_monitoring.league_scoring_trends`
        ORDER BY week_start DESC LIMIT 2
        """
        scoring = list(client.query(scoring_query).result())

        # Get latest model health
        health_query = """
        SELECT * FROM `nba_trend_monitoring.model_health_trends`
        ORDER BY week_start DESC LIMIT 2
        """
        health = list(client.query(health_query).result())

        # Get alerts
        alerts_query = """
        SELECT * FROM `nba_trend_monitoring.trend_alerts_summary`
        """
        alerts = list(client.query(alerts_query).result())

        # Build summary
        current_scoring = scoring[0] if scoring else None
        prev_scoring = scoring[1] if len(scoring) > 1 else None
        current_health = health[0] if health else None
        prev_health = health[1] if len(health) > 1 else None

        summary = {
            'scoring': {
                'current_avg_points': float(current_scoring.avg_points) if current_scoring else None,
                'prev_avg_points': float(prev_scoring.avg_points) if prev_scoring else None,
                'pct_overs_hitting': float(current_scoring.pct_overs_hitting) if current_scoring else None,
                'scoring_alert': current_scoring.scoring_alert if current_scoring else 'UNKNOWN',
            },
            'model_health': {
                'current_hit_rate': float(current_health.overall_hit_rate) if current_health else None,
                'prev_hit_rate': float(prev_health.overall_hit_rate) if prev_health else None,
                'current_bias': float(current_health.overall_bias) if current_health else None,
                'conf_90_hit_rate': float(current_health.conf_90_hit_rate) if current_health else None,
                'calibration_alert': current_health.calibration_alert if current_health else 'UNKNOWN',
            },
            'alerts': {
                'count': len(alerts),
                'critical_count': sum(1 for a in alerts if a.severity == 'CRITICAL'),
                'warning_count': sum(1 for a in alerts if a.severity == 'WARNING'),
                'items': [{'category': a.category, 'severity': a.severity, 'description': a.description} for a in alerts],
            },
            'overall_status': 'CRITICAL' if any(a.severity == 'CRITICAL' for a in alerts)
                            else 'WARNING' if any(a.severity == 'WARNING' for a in alerts)
                            else 'OK'
        }

        return jsonify(summary)

    except Exception as e:
        logger.error(f"Error fetching trend summary: {e}")
        return jsonify({'error': str(e)}), 500
