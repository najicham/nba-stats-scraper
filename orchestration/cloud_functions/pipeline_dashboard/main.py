"""
Pipeline Health Dashboard Cloud Function
=========================================
Visual HTML dashboard for monitoring processor health, prediction coverage,
and alert history.

Serves an auto-refreshing HTML page with:
- Recent processor runs and success rates
- Active processor heartbeats
- Prediction coverage per game
- Alert history from stale processor monitor

Version: 1.0
Created: 2026-01-24
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from google.cloud import firestore, bigquery
import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Standardized GCP project ID - uses GCP_PROJECT_ID with fallback to GCP_PROJECT
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')


@functions_framework.http
def pipeline_dashboard(request):
    """
    Serve pipeline health dashboard.

    Query params:
        - format: 'html' (default) or 'json'
        - date: Date to show (default: today)
        - phase: Filter by phase (optional)

    Returns:
        HTML dashboard or JSON data
    """
    try:
        request_args = request.args
        output_format = request_args.get('format', 'html')
        date_str = request_args.get('date', datetime.now().strftime('%Y-%m-%d'))
        phase_filter = request_args.get('phase')

        # Validate format parameter
        valid_formats = ('html', 'json')
        if output_format not in valid_formats:
            return {'error': f'Invalid format: {output_format}. Must be one of: {valid_formats}'}, 400

        # Validate date format
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return {'error': f'Invalid date format: {date_str}. Expected YYYY-MM-DD'}, 400

        # Validate phase if provided
        valid_phases = ('phase1', 'phase2', 'phase3', 'phase4', 'phase5', 'phase6')
        if phase_filter and phase_filter.lower() not in valid_phases:
            return {'error': f'Invalid phase: {phase_filter}. Must be one of: {valid_phases}'}, 400

        # Initialize clients
        fs_client = firestore.Client(project=PROJECT_ID)
        bq_client = bigquery.Client(project=PROJECT_ID)

        # Gather data
        data = {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'date': date_str,
            'processor_runs': get_processor_runs(bq_client, date_str, phase_filter),
            'heartbeats': get_active_heartbeats(fs_client),
            'coverage': get_prediction_coverage(bq_client, date_str),
            'alerts': get_recent_alerts(bq_client),
            'phase_summary': get_phase_summary(bq_client, date_str),
            'degraded_runs': get_degraded_dependency_runs(bq_client, date_str),
            'shot_zone_quality': get_shot_zone_quality(bq_client)
        }

        if output_format == 'json':
            return data, 200, {'Content-Type': 'application/json'}
        else:
            html = render_dashboard_html(data)
            return html, 200, {'Content-Type': 'text/html'}

    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}, 500


def get_processor_runs(bq_client: bigquery.Client, date_str: str, phase: str = None) -> List[Dict]:
    """Get recent processor runs from processor_run_history."""
    phase_filter = f"AND phase = '{phase}'" if phase else ""

    query = f"""
    SELECT
        processor_name,
        phase,
        status,
        data_date,
        started_at,
        completed_at,
        records_processed,
        TIMESTAMP_DIFF(completed_at, started_at, SECOND) as duration_seconds,
        failure_category,
        skip_reason
    FROM `{PROJECT_ID}.nba_reference.processor_run_history`
    WHERE data_date = @date
      {phase_filter}
    ORDER BY started_at DESC
    LIMIT 100
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("date", "DATE", date_str),
        ]
    )

    try:
        result = list(bq_client.query(query, job_config=job_config).result())
        return [dict(row) for row in result]
    except Exception as e:
        logger.error(f"Error getting processor runs: {e}", exc_info=True)
        return []


def get_active_heartbeats(fs_client: firestore.Client) -> List[Dict]:
    """Get active processor heartbeats from Firestore."""
    try:
        docs = (
            fs_client.collection('processor_heartbeats')
            .where('status', '==', 'running')
            .stream()
        )

        heartbeats = []
        now = datetime.now(timezone.utc)

        for doc in docs:
            data = doc.to_dict()
            last_heartbeat = data.get('last_heartbeat')

            if hasattr(last_heartbeat, 'timestamp'):
                last_heartbeat = datetime.fromtimestamp(
                    last_heartbeat.timestamp(), tz=timezone.utc
                )

            age_seconds = (now - last_heartbeat).total_seconds() if last_heartbeat else 0

            heartbeats.append({
                'processor_name': data.get('processor_name'),
                'run_id': data.get('run_id'),
                'data_date': data.get('data_date'),
                'progress': data.get('progress', 0),
                'total': data.get('total', 0),
                'status_message': data.get('status_message', ''),
                'age_seconds': int(age_seconds),
                'health': 'healthy' if age_seconds < 300 else 'stale' if age_seconds < 900 else 'dead'
            })

        return heartbeats

    except Exception as e:
        logger.error(f"Error getting heartbeats: {e}", exc_info=True)
        return []


def get_prediction_coverage(bq_client: bigquery.Client, date_str: str) -> Dict:
    """Get prediction coverage per game."""
    query = f"""
    WITH predictions AS (
        SELECT
            game_id,
            COUNT(DISTINCT player_lookup) as player_count
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date = @date
          AND is_active = TRUE
        GROUP BY game_id
    ),
    schedule AS (
        SELECT
            game_id,
            CONCAT(away_team_abbr, '@', home_team_abbr) as matchup,
            game_start_time
        FROM `{PROJECT_ID}.nba_reference.schedule_service_cache`
        WHERE game_date = @date
    )
    SELECT
        s.game_id,
        s.matchup,
        s.game_start_time,
        COALESCE(p.player_count, 0) as player_count,
        CASE
            WHEN COALESCE(p.player_count, 0) >= 8 THEN 'OK'
            WHEN COALESCE(p.player_count, 0) >= 4 THEN 'LOW'
            ELSE 'CRITICAL'
        END as status
    FROM schedule s
    LEFT JOIN predictions p ON s.game_id = p.game_id
    ORDER BY s.game_start_time
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("date", "DATE", date_str),
        ]
    )

    try:
        result = list(bq_client.query(query, job_config=job_config).result())
        games = [dict(row) for row in result]

        total_games = len(games)
        ok_count = sum(1 for g in games if g['status'] == 'OK')
        low_count = sum(1 for g in games if g['status'] == 'LOW')
        critical_count = sum(1 for g in games if g['status'] == 'CRITICAL')

        return {
            'games': games,
            'summary': {
                'total': total_games,
                'ok': ok_count,
                'low': low_count,
                'critical': critical_count
            }
        }

    except Exception as e:
        logger.error(f"Error getting coverage: {e}", exc_info=True)
        return {'games': [], 'summary': {'total': 0, 'ok': 0, 'low': 0, 'critical': 0}}


def get_recent_alerts(bq_client: bigquery.Client) -> List[Dict]:
    """Get recent alerts from processor run history failures."""
    query = f"""
    SELECT
        processor_name,
        data_date,
        status,
        failure_category,
        skip_reason,
        started_at,
        completed_at
    FROM `{PROJECT_ID}.nba_reference.processor_run_history`
    WHERE status IN ('failed', 'skipped')
      AND data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
    ORDER BY started_at DESC
    LIMIT 50
    """

    try:
        result = list(bq_client.query(query).result())
        return [dict(row) for row in result]
    except Exception as e:
        logger.error(f"Error getting alerts: {e}", exc_info=True)
        return []


def get_phase_summary(bq_client: bigquery.Client, date_str: str) -> Dict:
    """Get summary by phase."""
    query = f"""
    SELECT
        phase,
        COUNT(*) as total_runs,
        COUNTIF(status = 'success') as success_count,
        COUNTIF(status = 'failed') as failed_count,
        COUNTIF(status = 'skipped') as skipped_count,
        ROUND(COUNTIF(status = 'success') * 100.0 / COUNT(*), 1) as success_rate
    FROM `{PROJECT_ID}.nba_reference.processor_run_history`
    WHERE data_date = @date
    GROUP BY phase
    ORDER BY phase
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("date", "DATE", date_str),
        ]
    )

    try:
        result = list(bq_client.query(query, job_config=job_config).result())
        return {row['phase']: dict(row) for row in result}
    except Exception as e:
        logger.error(f"Error getting phase summary: {e}", exc_info=True)
        return {}


def get_degraded_dependency_runs(bq_client: bigquery.Client, date_str: str) -> Dict:
    """
    Get runs that proceeded with degraded dependencies.

    Identifies processors that ran successfully but with less than 100%
    upstream coverage (soft dependency threshold was met but not ideal).
    """
    # Query for runs with partial coverage indicators
    query = f"""
    WITH runs AS (
        SELECT
            processor_name,
            data_date,
            status,
            started_at,
            records_processed,
            skip_reason,
            -- Try to extract coverage info from skip_reason or summary
            REGEXP_EXTRACT(COALESCE(skip_reason, ''), r'(\d+\.?\d*)%') as coverage_pct
        FROM `{PROJECT_ID}.nba_reference.processor_run_history`
        WHERE data_date = @date
          AND status = 'success'
          AND (
              LOWER(COALESCE(skip_reason, '')) LIKE '%degraded%'
              OR LOWER(COALESCE(skip_reason, '')) LIKE '%soft%'
              OR LOWER(COALESCE(skip_reason, '')) LIKE '%partial%'
              OR LOWER(COALESCE(skip_reason, '')) LIKE '%coverage%'
          )
    )
    SELECT
        processor_name,
        data_date,
        started_at,
        records_processed,
        skip_reason,
        coverage_pct
    FROM runs
    ORDER BY started_at DESC
    LIMIT 20
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("date", "DATE", date_str),
        ]
    )

    try:
        result = list(bq_client.query(query, job_config=job_config).result())
        runs = [dict(row) for row in result]

        # Summary
        degraded_count = len(runs)
        processors_affected = len(set(r['processor_name'] for r in runs))

        return {
            'runs': runs,
            'summary': {
                'degraded_count': degraded_count,
                'processors_affected': processors_affected
            }
        }

    except Exception as e:
        logger.error(f"Error getting degraded runs: {e}", exc_info=True)
        return {'runs': [], 'summary': {'degraded_count': 0, 'processors_affected': 0}}


def get_shot_zone_quality(bq_client: bigquery.Client) -> Dict:
    """
    Get shot zone data quality metrics for last 3 days.

    Returns:
        - Daily completeness % (has_complete_shot_zones)
        - Average paint/three/mid-range rates
        - Anomaly detection (paint <25%, three >55%)
    """
    query = f"""
    WITH daily_metrics AS (
        SELECT
            game_date,
            COUNT(*) as total_records,
            COUNTIF(has_complete_shot_zones = TRUE) as complete_records,
            ROUND(COUNTIF(has_complete_shot_zones = TRUE) * 100.0 / COUNT(*), 1) as pct_complete,

            -- Average rates for complete records only
            ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
                THEN SAFE_DIVIDE(paint_attempts * 100.0,
                     paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as avg_paint_rate,
            ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
                THEN SAFE_DIVIDE(three_attempts_pbp * 100.0,
                     paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as avg_three_rate,
            ROUND(AVG(CASE WHEN has_complete_shot_zones = TRUE
                THEN SAFE_DIVIDE(mid_range_attempts * 100.0,
                     paint_attempts + mid_range_attempts + three_attempts_pbp) END), 1) as avg_mid_rate,

            -- Anomaly detection
            COUNTIF(has_complete_shot_zones = TRUE
                AND SAFE_DIVIDE(paint_attempts * 100.0,
                     paint_attempts + mid_range_attempts + three_attempts_pbp) < 25) as low_paint_count,
            COUNTIF(has_complete_shot_zones = TRUE
                AND SAFE_DIVIDE(three_attempts_pbp * 100.0,
                     paint_attempts + mid_range_attempts + three_attempts_pbp) > 55) as high_three_count
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
          AND minutes_played > 0
        GROUP BY game_date
        ORDER BY game_date DESC
    )
    SELECT * FROM daily_metrics
    """

    try:
        result = list(bq_client.query(query).result())
        daily_data = [dict(row) for row in result]

        # Calculate overall status
        if not daily_data:
            status = 'NO_DATA'
            status_message = 'No recent data available'
        else:
            latest_day = daily_data[0]
            pct_complete = latest_day.get('pct_complete', 0)
            avg_paint = latest_day.get('avg_paint_rate', 0)
            avg_three = latest_day.get('avg_three_rate', 0)

            # Determine status
            if pct_complete >= 85 and 30 <= avg_paint <= 45 and 20 <= avg_three <= 50:
                status = 'OK'
                status_message = 'Shot zone data quality is good'
            elif pct_complete >= 50 or (avg_paint < 25 or avg_three > 55):
                status = 'WARNING'
                status_message = 'Shot zone data quality degraded'
            else:
                status = 'CRITICAL'
                status_message = 'Shot zone data quality critical'

        return {
            'daily_data': daily_data,
            'status': status,
            'status_message': status_message
        }

    except Exception as e:
        logger.error(f"Error getting shot zone quality: {e}", exc_info=True)
        return {
            'daily_data': [],
            'status': 'ERROR',
            'status_message': f'Error querying shot zone data: {str(e)}'
        }


def render_dashboard_html(data: Dict) -> str:
    """Render dashboard as HTML."""

    # Generate phase summary cards
    phase_cards = ""
    for phase, stats in data.get('phase_summary', {}).items():
        success_rate = stats.get('success_rate', 0)
        status_class = 'success' if success_rate >= 90 else 'warning' if success_rate >= 70 else 'danger'
        phase_cards += f"""
        <div class="card phase-card">
            <h3>{phase.replace('_', ' ').title()}</h3>
            <div class="stat {status_class}">{success_rate}%</div>
            <div class="details">
                {stats.get('success_count', 0)} / {stats.get('total_runs', 0)} succeeded
            </div>
        </div>
        """

    # Generate heartbeat rows
    heartbeat_rows = ""
    for hb in data.get('heartbeats', []):
        health_class = hb['health']
        progress_pct = (hb['progress'] / hb['total'] * 100) if hb['total'] > 0 else 0
        heartbeat_rows += f"""
        <tr class="{health_class}">
            <td>{hb['processor_name']}</td>
            <td>{hb['data_date']}</td>
            <td>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {progress_pct}%"></div>
                </div>
                {hb['progress']}/{hb['total']}
            </td>
            <td>{hb['age_seconds']}s ago</td>
            <td><span class="status-badge {health_class}">{hb['health'].upper()}</span></td>
        </tr>
        """

    if not heartbeat_rows:
        heartbeat_rows = '<tr><td colspan="5" class="empty">No active processors</td></tr>'

    # Generate coverage rows
    coverage_rows = ""
    coverage = data.get('coverage', {})
    for game in coverage.get('games', []):
        status_class = game['status'].lower()
        coverage_rows += f"""
        <tr class="{status_class}">
            <td>{game['matchup']}</td>
            <td>{game['player_count']}</td>
            <td><span class="status-badge {status_class}">{game['status']}</span></td>
        </tr>
        """

    if not coverage_rows:
        coverage_rows = '<tr><td colspan="3" class="empty">No games scheduled</td></tr>'

    coverage_summary = coverage.get('summary', {})

    # Generate alert rows
    alert_rows = ""
    for alert in data.get('alerts', [])[:20]:
        alert_rows += f"""
        <tr>
            <td>{alert['processor_name']}</td>
            <td>{alert['data_date']}</td>
            <td>{alert['failure_category'] or alert['status']}</td>
            <td class="skip-reason">{(alert['skip_reason'] or '')[:50]}</td>
        </tr>
        """

    if not alert_rows:
        alert_rows = '<tr><td colspan="4" class="empty">No recent alerts</td></tr>'

    # Generate degraded dependency rows
    degraded_rows = ""
    degraded = data.get('degraded_runs', {})
    for run in degraded.get('runs', [])[:10]:
        coverage_pct = run.get('coverage_pct', 'N/A')
        degraded_rows += f"""
        <tr class="warning">
            <td>{run['processor_name']}</td>
            <td>{run['data_date']}</td>
            <td>{coverage_pct}%</td>
            <td class="skip-reason">{(run.get('skip_reason') or '')[:60]}</td>
        </tr>
        """

    if not degraded_rows:
        degraded_rows = '<tr><td colspan="4" class="empty">No degraded dependency runs</td></tr>'

    degraded_summary = degraded.get('summary', {})

    # Generate shot zone quality rows
    shot_zone_rows = ""
    shot_zone = data.get('shot_zone_quality', {})
    shot_zone_status = shot_zone.get('status', 'NO_DATA')
    shot_zone_status_message = shot_zone.get('status_message', 'Unknown')
    shot_zone_status_class = shot_zone_status.lower() if shot_zone_status != 'NO_DATA' else 'warning'

    for day in shot_zone.get('daily_data', []):
        pct_complete = day.get('pct_complete', 0)
        paint_rate = day.get('avg_paint_rate', 0)
        three_rate = day.get('avg_three_rate', 0)
        mid_rate = day.get('avg_mid_rate', 0)
        low_paint = day.get('low_paint_count', 0)
        high_three = day.get('high_three_count', 0)

        # Determine row status
        if pct_complete >= 85 and 30 <= paint_rate <= 45 and 20 <= three_rate <= 50:
            row_status = 'ok'
            status_text = 'GOOD'
        elif pct_complete >= 50:
            row_status = 'low'
            status_text = 'DEGRADED'
        else:
            row_status = 'critical'
            status_text = 'CRITICAL'

        # Format anomalies
        anomalies = []
        if low_paint > 0:
            anomalies.append(f"{low_paint} low paint")
        if high_three > 0:
            anomalies.append(f"{high_three} high 3pt")
        anomaly_text = ", ".join(anomalies) if anomalies else "-"

        shot_zone_rows += f"""
        <tr class="{row_status}">
            <td>{day['game_date']}</td>
            <td>{pct_complete}% ({day['complete_records']}/{day['total_records']})</td>
            <td>{paint_rate}%</td>
            <td>{three_rate}%</td>
            <td>{mid_rate}%</td>
            <td class="skip-reason">{anomaly_text}</td>
            <td><span class="status-badge {row_status}">{status_text}</span></td>
        </tr>
        """

    if not shot_zone_rows:
        shot_zone_rows = '<tr><td colspan="7" class="empty">No shot zone data available</td></tr>'

    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Pipeline Health Dashboard</title>
    <meta http-equiv="refresh" content="60">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #333;
        }}
        h1 {{ color: #00d4ff; }}
        .timestamp {{ color: #888; font-size: 14px; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .card {{
            background: #16213e;
            border-radius: 8px;
            padding: 15px;
        }}
        .card h3 {{ color: #aaa; font-size: 14px; margin-bottom: 10px; }}
        .stat {{ font-size: 32px; font-weight: bold; }}
        .stat.success {{ color: #00ff88; }}
        .stat.warning {{ color: #ffaa00; }}
        .stat.danger {{ color: #ff4444; }}
        .details {{ color: #888; font-size: 12px; margin-top: 5px; }}
        .section {{ margin-bottom: 30px; }}
        .section h2 {{ color: #00d4ff; margin-bottom: 15px; font-size: 18px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #16213e;
            border-radius: 8px;
            overflow: hidden;
        }}
        th, td {{ padding: 12px; text-align: left; }}
        th {{ background: #1a1a3e; color: #aaa; font-weight: 500; }}
        tr:hover {{ background: #1e2a4a; }}
        tr.healthy {{ }}
        tr.stale {{ background: #3a3a1e; }}
        tr.dead {{ background: #3a1e1e; }}
        tr.ok {{ }}
        tr.low {{ background: #3a3a1e; }}
        tr.critical {{ background: #3a1e1e; }}
        .status-badge {{
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
        }}
        .status-badge.healthy, .status-badge.ok {{ background: #1a4a1a; color: #00ff88; }}
        .status-badge.stale, .status-badge.low {{ background: #4a4a1a; color: #ffaa00; }}
        .status-badge.dead, .status-badge.critical {{ background: #4a1a1a; color: #ff4444; }}
        .progress-bar {{
            width: 100px;
            height: 8px;
            background: #333;
            border-radius: 4px;
            display: inline-block;
            margin-right: 8px;
            vertical-align: middle;
        }}
        .progress-fill {{
            height: 100%;
            background: #00d4ff;
            border-radius: 4px;
        }}
        .empty {{ color: #666; text-align: center; font-style: italic; }}
        .skip-reason {{ color: #888; font-size: 12px; }}
        .coverage-summary {{
            display: flex;
            gap: 20px;
            margin-bottom: 15px;
        }}
        .coverage-stat {{
            padding: 8px 16px;
            border-radius: 4px;
            font-weight: 500;
        }}
        .coverage-stat.ok {{ background: #1a4a1a; color: #00ff88; }}
        .coverage-stat.low {{ background: #4a4a1a; color: #ffaa00; }}
        .coverage-stat.critical {{ background: #4a1a1a; color: #ff4444; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Pipeline Health Dashboard</h1>
        <div class="timestamp">
            Date: {data['date']} | Updated: {data['generated_at'][:19]} UTC
            <br>Auto-refresh: 60s
        </div>
    </div>

    <div class="grid">
        {phase_cards}
    </div>

    <div class="section">
        <h2>Active Processors</h2>
        <table>
            <thead>
                <tr>
                    <th>Processor</th>
                    <th>Date</th>
                    <th>Progress</th>
                    <th>Last Heartbeat</th>
                    <th>Health</th>
                </tr>
            </thead>
            <tbody>
                {heartbeat_rows}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Prediction Coverage</h2>
        <div class="coverage-summary">
            <span class="coverage-stat ok">{coverage_summary.get('ok', 0)} OK</span>
            <span class="coverage-stat low">{coverage_summary.get('low', 0)} LOW</span>
            <span class="coverage-stat critical">{coverage_summary.get('critical', 0)} CRITICAL</span>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Game</th>
                    <th>Players</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {coverage_rows}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Shot Zone Data Quality (Last 3 Days)</h2>
        <div class="coverage-summary">
            <span class="coverage-stat {shot_zone_status_class}">{shot_zone_status_message}</span>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Completeness</th>
                    <th>Paint Rate</th>
                    <th>Three Rate</th>
                    <th>Mid Rate</th>
                    <th>Anomalies</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {shot_zone_rows}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Recent Alerts (Last 3 Days)</h2>
        <table>
            <thead>
                <tr>
                    <th>Processor</th>
                    <th>Date</th>
                    <th>Category</th>
                    <th>Reason</th>
                </tr>
            </thead>
            <tbody>
                {alert_rows}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Degraded Dependency Runs</h2>
        <div class="coverage-summary">
            <span class="coverage-stat warning">{degraded_summary.get('degraded_count', 0)} Degraded Runs</span>
            <span class="coverage-stat warning">{degraded_summary.get('processors_affected', 0)} Processors</span>
        </div>
        <p style="color: #888; font-size: 12px; margin-bottom: 10px;">
            Processors that ran successfully but with less than 100% upstream coverage (soft dependency threshold met)
        </p>
        <table>
            <thead>
                <tr>
                    <th>Processor</th>
                    <th>Date</th>
                    <th>Coverage</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
                {degraded_rows}
            </tbody>
        </table>
    </div>
</body>
</html>
"""
    return html


@functions_framework.http
def health(request):
    """Health check endpoint for pipeline_dashboard."""
    return json.dumps({
        'status': 'healthy',
        'function': 'pipeline_dashboard',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
