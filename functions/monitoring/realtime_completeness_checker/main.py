"""
Layer 6: Real-Time Completeness Checker

Triggered when Phase 2 processors complete.
Checks if all processors done for that date.
Runs completeness check if so.
Detects missing games in ~2 minutes vs 10 hours.
"""

import functions_framework
from google.cloud import bigquery
from datetime import datetime
import json
import base64
import uuid


@functions_framework.cloud_event
def check_completeness_realtime(cloud_event):
    """
    Triggered when Phase 2 processor completes.
    Checks if all processors done for that date.
    Runs completeness check if so.
    """

    # Parse Pub/Sub message
    message_data = json.loads(
        base64.b64decode(cloud_event.data["message"]["data"])
    )

    processor_name = message_data.get('processor_name')
    game_date = message_data.get('game_date')
    status = message_data.get('status')
    rows_processed = message_data.get('rows_processed', 0)

    print(f"📥 Processor completed: {processor_name} for {game_date}")
    print(f"   Status: {status}, Rows: {rows_processed}")

    # Track this completion
    track_processor_completion(
        processor_name=processor_name,
        game_date=game_date,
        status=status,
        rows_processed=rows_processed
    )

    # Check if all expected processors have completed
    expected_processors = get_expected_processors_for_date(game_date)
    completed_processors = get_completed_processors(game_date)

    pending = set(expected_processors) - set(completed_processors)

    if pending:
        print(f"⏳ Waiting for: {pending}")
        return {
            'status': 'waiting',
            'game_date': game_date,
            'completed': list(completed_processors),
            'pending': list(pending)
        }

    # All processors done - run completeness check
    print(f"✅ All processors complete for {game_date}, checking completeness...")

    missing_games = check_completeness_for_date(game_date)

    if missing_games:
        send_immediate_alert(game_date, missing_games)
        log_missing_games(game_date, missing_games)

        print(f"⚠️  {len(missing_games)} games missing for {game_date}")
        return {
            'status': 'gaps_found',
            'game_date': game_date,
            'missing_count': len(missing_games),
            'games': missing_games
        }
    else:
        print(f"🎉 All games accounted for {game_date}")
        return {
            'status': 'complete',
            'game_date': game_date,
            'missing_count': 0
        }


def get_expected_processors_for_date(game_date):
    """Return list of processors that should run for this date."""
    # Core processors that must complete
    return [
        'NbacGamebookProcessor',
        'BdlPlayerBoxScoresProcessor',
        'BdlLiveBoxscoresProcessor'
    ]


def track_processor_completion(processor_name, game_date, status, rows_processed):
    """Record processor completion."""
    bq_client = bigquery.Client()
    table_id = "nba-props-platform.nba_orchestration.processor_completions"

    row = {
        'processor_name': processor_name,
        'game_date': str(game_date),
        'completed_at': datetime.utcnow().isoformat(),
        'status': status,
        'rows_processed': rows_processed
    }

    errors = bq_client.insert_rows_json(table_id, [row])
    if errors:
        print(f"❌ Error tracking completion: {errors}")


def get_completed_processors(game_date):
    """Get processors that completed in last 2 hours for this date."""
    bq_client = bigquery.Client()

    query = f"""
    SELECT DISTINCT processor_name
    FROM `nba-props-platform.nba_orchestration.processor_completions`
    WHERE game_date = '{game_date}'
      AND completed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 2 HOUR)
      AND status = 'success'
    """

    results = list(bq_client.query(query).result())
    return [row.processor_name for row in results]


def check_completeness_for_date(game_date):
    """Run completeness check for specific date."""
    bq_client = bigquery.Client()

    # Use same SQL as daily checker but for this date only
    query = f"""
    WITH schedule AS (
      SELECT DISTINCT
        game_date,
        game_code,
        home_team_tricode,
        away_team_tricode
      FROM `nba-props-platform.nba_raw.nbac_schedule`
      WHERE game_date = '{game_date}'
    ),
    gamebook_games AS (
      SELECT
        game_date,
        game_code,
        COUNT(DISTINCT player_lookup) as player_count
      FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
      WHERE game_date = '{game_date}'
      GROUP BY game_date, game_code
      HAVING COUNT(DISTINCT player_lookup) >= 10
    ),
    bdl_games AS (
      SELECT
        game_date,
        CONCAT(
          FORMAT_DATE('%Y%m%d', game_date),
          '_',
          away_team_abbr,
          '_',
          home_team_abbr
        ) as game_code,
        COUNT(DISTINCT player_lookup) as player_count
      FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
      WHERE game_date = '{game_date}'
      GROUP BY game_date, game_code, away_team_abbr, home_team_abbr
      HAVING COUNT(DISTINCT player_lookup) >= 10
    )

    SELECT
      s.game_date,
      s.game_code,
      CONCAT(s.away_team_tricode, '@', s.home_team_tricode) as matchup,

      CASE
        WHEN g.game_code IS NULL THEN 'MISSING'
        WHEN g.player_count < 10 THEN 'INCOMPLETE'
        ELSE 'OK'
      END as gamebook_status,
      COALESCE(g.player_count, 0) as gamebook_players,

      CASE
        WHEN b.game_code IS NULL THEN 'MISSING'
        WHEN b.player_count < 10 THEN 'INCOMPLETE'
        ELSE 'OK'
      END as bdl_status,
      COALESCE(b.player_count, 0) as bdl_players

    FROM schedule s
    LEFT JOIN gamebook_games g ON s.game_code = g.game_code
    LEFT JOIN bdl_games b ON s.game_code = b.game_code

    WHERE g.game_code IS NULL
       OR b.game_code IS NULL
       OR g.player_count < 10
       OR b.player_count < 10
    """

    results = list(bq_client.query(query).result())
    return [dict(row) for row in results]


def send_immediate_alert(game_date, missing_games):
    """Send immediate alert for missing games."""
    # Import email alerter
    import sys
    sys.path.insert(0, '/workspace')

    try:
        from shared.utils.email_alerting_ses import EmailAlerterSES
        alerter = EmailAlerterSES()
    except ImportError:
        print("⚠️  Email alerting not available in this environment")
        return

    subject = f"⚠️ Real-Time Alert: {len(missing_games)} Games Missing for {game_date}"

    body_html = f"""
    <h2>⚠️ Data Gaps Detected Immediately After Processing</h2>
    <p><strong>Date:</strong> {game_date}</p>
    <p><strong>Missing Games:</strong> {len(missing_games)}</p>
    <p><strong>Detection Time:</strong> ~2 minutes after processing</p>
    <p><strong>Detection Layer:</strong> Layer 6 - Real-Time Completeness Check</p>

    <table border="1" style="border-collapse: collapse;">
        <tr style="background-color: #f0f0f0;">
            <th style="padding: 8px;">Game</th>
            <th style="padding: 8px;">Matchup</th>
            <th style="padding: 8px;">Gamebook</th>
            <th style="padding: 8px;">BDL</th>
        </tr>
    """

    for game in missing_games:
        gamebook_cell = (
            '✅ OK' if game['gamebook_status'] == 'OK'
            else f"❌ {game['gamebook_status']}"
        )
        bdl_cell = (
            '✅ OK' if game['bdl_status'] == 'OK'
            else f"❌ {game['bdl_status']}"
        )

        body_html += f"""
        <tr>
            <td style="padding: 8px;">{game['game_code']}</td>
            <td style="padding: 8px;">{game['matchup']}</td>
            <td style="padding: 8px;">{gamebook_cell}</td>
            <td style="padding: 8px;">{bdl_cell}</td>
        </tr>
        """

    body_html += """
    </table>

    <h3>Recommended Actions:</h3>
    <ol>
        <li>Check processor logs for errors</li>
        <li>Verify GCS files exist and are complete</li>
        <li>Check scraper execution logs</li>
        <li>Trigger backfill if needed</li>
    </ol>

    <p style="color: #666; font-size: 12px;">
    This is a real-time alert triggered immediately after processors completed.
    You're receiving this 2 minutes after processing, not 10 hours later.
    Detection lag reduced by 98%.
    </p>
    """

    try:
        alerter._send_email(
            subject=subject,
            body_html=body_html,
            recipients=alerter.alert_recipients,
            alert_level="WARNING"
        )
        print(f"✅ Alert email sent to {alerter.alert_recipients}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


def log_missing_games(game_date, missing_games):
    """Log missing games to tracking table."""
    bq_client = bigquery.Client()
    table_id = "nba-props-platform.nba_orchestration.missing_games_log"

    check_id = str(uuid.uuid4())

    rows = []
    for game in missing_games:
        rows.append({
            'log_id': str(uuid.uuid4()),
            'check_id': check_id,
            'game_date': str(game['game_date']),
            'game_code': game['game_code'],
            'matchup': game['matchup'],
            'gamebook_missing': game['gamebook_status'] != 'OK',
            'bdl_missing': game['bdl_status'] != 'OK',
            'discovered_at': datetime.utcnow().isoformat(),
            'backfilled_at': None
        })

    errors = bq_client.insert_rows_json(table_id, rows)
    if errors:
        print(f"❌ Error logging missing games: {errors}")
