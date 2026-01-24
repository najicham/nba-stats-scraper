"""
Scraper Health Dashboard Cloud Function

Provides a visual HTML dashboard showing scraper health status:
- Gap counts per scraper
- Last successful run times
- Recent errors
- Circuit breaker states (when available)

Access: https://us-west2-nba-props-platform.cloudfunctions.net/scraper-dashboard
"""

import functions_framework
from flask import Response
from google.cloud import bigquery
from datetime import datetime, timezone, timedelta
import logging
import html

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dashboard refresh interval (seconds)
REFRESH_INTERVAL = 60


def get_scraper_gaps(client: bigquery.Client) -> list:
    """Get gap counts per scraper."""
    query = """
    SELECT
        scraper_name,
        COUNT(*) as gap_count,
        MIN(game_date) as oldest_gap,
        MAX(game_date) as newest_gap,
        ARRAY_AGG(error_type ORDER BY game_date DESC LIMIT 3) as recent_errors
    FROM `nba-props-platform.nba_orchestration.scraper_failures`
    WHERE backfilled = FALSE
      AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY scraper_name
    ORDER BY gap_count DESC
    """
    try:
        result = client.query(query).result()
        return [dict(row) for row in result]
    except Exception as e:
        logger.error(f"Error getting gaps: {e}")
        return []


def get_recent_runs(client: bigquery.Client) -> list:
    """Get recent scraper runs from phase1_scraper_runs."""
    query = """
    SELECT
        scraper_name,
        MAX(run_started_at) as last_run,
        COUNTIF(status = 'success' AND run_started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)) as successes_24h,
        COUNTIF(status != 'success' AND run_started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)) as failures_24h
    FROM `nba-props-platform.nba_orchestration.phase1_scraper_runs`
    WHERE run_started_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
    GROUP BY scraper_name
    ORDER BY last_run DESC
    """
    try:
        result = client.query(query).result()
        return [dict(row) for row in result]
    except Exception as e:
        logger.error(f"Error getting runs: {e}")
        return []


def get_proxy_health(client: bigquery.Client) -> list:
    """Get recent proxy health metrics."""
    query = """
    SELECT
        proxy_provider,
        target_host,
        COUNTIF(success) as successes,
        COUNTIF(NOT success) as failures,
        ROUND(COUNTIF(success) * 100.0 / COUNT(*), 1) as success_rate
    FROM `nba-props-platform.nba_orchestration.proxy_health_metrics`
    WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    GROUP BY proxy_provider, target_host
    HAVING COUNT(*) >= 3
    ORDER BY success_rate ASC
    """
    try:
        result = client.query(query).result()
        return [dict(row) for row in result]
    except Exception as e:
        logger.error(f"Error getting proxy health: {e}")
        return []


def get_circuit_breaker_states(client: bigquery.Client) -> list:
    """Get circuit breaker states if table exists."""
    query = """
    SELECT
        proxy_provider,
        target_host,
        circuit_state,
        failure_count,
        last_failure_at,
        last_success_at
    FROM `nba-props-platform.nba_orchestration.proxy_circuit_breaker`
    ORDER BY updated_at DESC
    """
    try:
        result = client.query(query).result()
        return [dict(row) for row in result]
    except Exception as e:
        # Table may not exist yet
        logger.debug(f"Circuit breaker table not available: {e}")
        return []


def get_recent_backfills(client: bigquery.Client) -> list:
    """Get recently backfilled gaps."""
    query = """
    SELECT
        scraper_name,
        game_date,
        backfilled_at
    FROM `nba-props-platform.nba_orchestration.scraper_failures`
    WHERE backfilled = TRUE
      AND backfilled_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
    ORDER BY backfilled_at DESC
    LIMIT 10
    """
    try:
        result = client.query(query).result()
        return [dict(row) for row in result]
    except Exception as e:
        logger.error(f"Error getting backfills: {e}")
        return []


def render_dashboard(gaps: list, runs: list, proxy_health: list,
                     circuit_states: list, recent_backfills: list) -> str:
    """Render HTML dashboard."""

    # Build gaps table
    gaps_html = ""
    if gaps:
        for g in gaps:
            name = html.escape(str(g.get('scraper_name', 'Unknown')))
            count = g.get('gap_count', 0)
            oldest = str(g.get('oldest_gap', 'N/A'))
            errors = g.get('recent_errors', []) or []

            if count >= 5:
                status_class = "status-red"
                icon = "&#x1F534;"  # Red circle
            elif count >= 3:
                status_class = "status-orange"
                icon = "&#x1F7E0;"  # Orange circle
            else:
                status_class = "status-yellow"
                icon = "&#x1F7E1;"  # Yellow circle

            errors_str = ", ".join([html.escape(str(e)[:30]) for e in errors[:2]]) if errors else "N/A"

            gaps_html += f"""
            <tr>
                <td>{icon} {name}</td>
                <td class="{status_class}">{count}</td>
                <td>{oldest}</td>
                <td style="font-size: 11px;">{errors_str}</td>
            </tr>
            """
    else:
        gaps_html = '<tr><td colspan="4" style="text-align: center; color: #28a745;">&#x2705; No gaps!</td></tr>'

    # Build runs table
    runs_html = ""
    all_scrapers = set()
    run_map = {}
    for r in runs:
        name = r.get('scraper_name', 'Unknown')
        all_scrapers.add(name)
        run_map[name] = r

    # Also add scrapers from gaps that might not have recent runs
    for g in gaps:
        all_scrapers.add(g.get('scraper_name', 'Unknown'))

    for name in sorted(all_scrapers):
        r = run_map.get(name, {})
        last_run = r.get('last_run')
        successes = r.get('successes_24h', 0)
        failures = r.get('failures_24h', 0)

        # Calculate time ago
        if last_run:
            if hasattr(last_run, 'timestamp'):
                time_ago = datetime.now(timezone.utc) - last_run.replace(tzinfo=timezone.utc)
            else:
                time_ago = timedelta(hours=999)
            hours_ago = time_ago.total_seconds() / 3600

            if hours_ago < 1:
                time_str = f"{int(time_ago.total_seconds() / 60)}m ago"
            elif hours_ago < 24:
                time_str = f"{hours_ago:.1f}h ago"
            else:
                time_str = f"{hours_ago / 24:.1f}d ago"

            if hours_ago < 6:
                time_class = "status-green"
            elif hours_ago < 12:
                time_class = "status-yellow"
            else:
                time_class = "status-red"
        else:
            time_str = "No data"
            time_class = "status-gray"

        # Health indicator
        gap_scraper = next((g for g in gaps if g.get('scraper_name') == name), None)
        gap_count = gap_scraper.get('gap_count', 0) if gap_scraper else 0

        if gap_count == 0 and failures == 0:
            health_icon = "&#x1F7E2;"  # Green
        elif gap_count < 3 and failures < 3:
            health_icon = "&#x1F7E1;"  # Yellow
        else:
            health_icon = "&#x1F534;"  # Red

        runs_html += f"""
        <tr>
            <td>{health_icon} {html.escape(name)}</td>
            <td class="{time_class}">{time_str}</td>
            <td style="color: #28a745;">{successes}</td>
            <td style="color: #d32f2f;">{failures}</td>
            <td>{gap_count}</td>
        </tr>
        """

    # Build proxy health table
    proxy_html = ""
    if proxy_health:
        for p in proxy_health:
            provider = html.escape(str(p.get('proxy_provider', 'Unknown')))
            target = html.escape(str(p.get('target_host', 'Unknown')))
            rate = p.get('success_rate', 0)
            successes = p.get('successes', 0)
            failures = p.get('failures', 0)

            if rate >= 90:
                rate_class = "status-green"
            elif rate >= 70:
                rate_class = "status-yellow"
            else:
                rate_class = "status-red"

            proxy_html += f"""
            <tr>
                <td>{provider}</td>
                <td>{target}</td>
                <td class="{rate_class}">{rate}%</td>
                <td>{successes}/{successes + failures}</td>
            </tr>
            """
    else:
        proxy_html = '<tr><td colspan="4" style="text-align: center;">No proxy data</td></tr>'

    # Build backfills table
    backfills_html = ""
    if recent_backfills:
        for b in recent_backfills:
            name = html.escape(str(b.get('scraper_name', 'Unknown')))
            date = str(b.get('game_date', 'N/A'))
            when = b.get('backfilled_at')
            when_str = when.strftime('%H:%M') if when else 'N/A'

            backfills_html += f"<tr><td>{name}</td><td>{date}</td><td>{when_str}</td></tr>"
    else:
        backfills_html = '<tr><td colspan="3" style="text-align: center;">No recent backfills</td></tr>'

    # Full HTML
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Scraper Health Dashboard</title>
        <meta http-equiv="refresh" content="{REFRESH_INTERVAL}">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                margin: 20px;
                background: #f5f5f5;
            }}
            h1 {{ color: #333; margin-bottom: 5px; }}
            .subtitle {{ color: #666; margin-bottom: 20px; }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
                gap: 20px;
            }}
            .card {{
                background: white;
                border-radius: 8px;
                padding: 15px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }}
            .card h2 {{
                margin-top: 0;
                font-size: 16px;
                color: #333;
                border-bottom: 1px solid #eee;
                padding-bottom: 10px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                font-size: 13px;
            }}
            th, td {{
                text-align: left;
                padding: 8px 6px;
                border-bottom: 1px solid #eee;
            }}
            th {{
                background: #f9f9f9;
                font-weight: 600;
            }}
            .status-green {{ color: #28a745; font-weight: bold; }}
            .status-yellow {{ color: #ffc107; font-weight: bold; }}
            .status-orange {{ color: #ff9800; font-weight: bold; }}
            .status-red {{ color: #d32f2f; font-weight: bold; }}
            .status-gray {{ color: #999; }}
            .timestamp {{
                text-align: right;
                color: #999;
                font-size: 12px;
                margin-top: 10px;
            }}
        </style>
    </head>
    <body>
        <h1>&#x1F4CA; Scraper Health Dashboard</h1>
        <p class="subtitle">Auto-refreshes every {REFRESH_INTERVAL} seconds</p>

        <div class="grid">
            <div class="card">
                <h2>&#x26A0;&#xFE0F; Current Gaps (Unbackfilled Failures)</h2>
                <table>
                    <tr><th>Scraper</th><th>Gaps</th><th>Oldest</th><th>Recent Errors</th></tr>
                    {gaps_html}
                </table>
            </div>

            <div class="card">
                <h2>&#x1F3C3; Scraper Status (Last 24h)</h2>
                <table>
                    <tr><th>Scraper</th><th>Last Run</th><th>&#x2705;</th><th>&#x274C;</th><th>Gaps</th></tr>
                    {runs_html}
                </table>
            </div>

            <div class="card">
                <h2>&#x1F310; Proxy Health (Last 24h)</h2>
                <table>
                    <tr><th>Provider</th><th>Target</th><th>Success</th><th>Requests</th></tr>
                    {proxy_html}
                </table>
            </div>

            <div class="card">
                <h2>&#x2705; Recent Backfills (Last 24h)</h2>
                <table>
                    <tr><th>Scraper</th><th>Date</th><th>Time</th></tr>
                    {backfills_html}
                </table>
            </div>
        </div>

        <p class="timestamp">Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
    </body>
    </html>
    """

    return html_content


@functions_framework.http
def scraper_dashboard(request):
    """
    Main entry point for the Cloud Function.

    Returns HTML dashboard of scraper health.
    """
    try:
        client = bigquery.Client()

        # Gather data
        gaps = get_scraper_gaps(client)
        runs = get_recent_runs(client)
        proxy_health = get_proxy_health(client)
        circuit_states = get_circuit_breaker_states(client)
        recent_backfills = get_recent_backfills(client)

        # Render dashboard
        html_content = render_dashboard(
            gaps, runs, proxy_health, circuit_states, recent_backfills
        )

        return Response(html_content, mimetype='text/html')

    except Exception as e:
        logger.error(f"Dashboard error: {e}", exc_info=True)
        return Response(
            f"<html><body><h1>Error</h1><p>{html.escape(str(e))}</p></body></html>",
            status=500,
            mimetype='text/html'
        )


@functions_framework.http
def health(request):
    """Health check endpoint for scraper_dashboard."""
    return json.dumps({
        'status': 'healthy',
        'function': 'scraper_dashboard',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
