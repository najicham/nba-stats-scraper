"""
schedule_fix.py

Flask blueprint for schedule fix routes.
Extracted from main_scraper_service.py to improve modularity.

Routes:
- POST /generate-daily-schedule - Generate expected daily schedule for monitoring
- POST /fix-stale-schedule - Fix stale schedule data (mark old in-progress games as Final)

Path: scrapers/routes/schedule_fix.py
"""

import logging
from flask import Blueprint, request, jsonify
from google.cloud import bigquery
from orchestration.schedule_locker import DailyScheduleLocker
from shared.config.gcp_config import get_project_id


# Create blueprint
schedule_fix = Blueprint('schedule_fix', __name__)

# Initialize components (lazy load to avoid startup overhead)
_locker = None


def get_locker():
    """Get or initialize the DailyScheduleLocker instance."""
    global _locker
    if _locker is None:
        _locker = DailyScheduleLocker()
    return _locker


@schedule_fix.route('/generate-daily-schedule', methods=['POST'])
def generate_schedule():
    """
    Generate expected daily schedule for monitoring.
    Called once daily at 5 AM ET by Cloud Scheduler.

    Optional JSON body:
    {
        "date": "2025-01-15"  # Optional - default is today
    }
    """
    try:
        data = request.get_json(silent=True, force=True) or {}
        target_date = data.get('date')

        logging.info("📅 Generating daily expected schedule")

        locker = get_locker()
        result = locker.generate_daily_schedule(target_date)

        return jsonify({
            "status": "success",
            "schedule": result
        }), 200

    except Exception as e:
        logging.error(f"Schedule generation failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }), 500


@schedule_fix.route('/fix-stale-schedule', methods=['POST'])
def fix_stale_schedule():
    """
    Fix stale schedule data - marks old in-progress games as Final.

    This prevents analytics processors from skipping due to ENABLE_GAMES_FINISHED_CHECK
    when schedule data hasn't been refreshed.

    Games are considered stale if:
    - game_status is 1 (Scheduled) or 2 (In Progress)
    - game_date is in the past
    - More than 4 hours have passed since the assumed game time

    Added: Jan 23, 2026 - Automated via Cloud Scheduler (every 4 hours)
    """
    try:
        logging.info("🔧 Running stale schedule fix...")

        client = bigquery.Client(project=get_project_id())

        # Find stale games
        query = """
        SELECT
            game_id,
            game_date,
            game_status,
            time_slot,
            home_team_tricode as home_team_abbr,
            away_team_tricode as away_team_abbr,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(),
                TIMESTAMP(CONCAT(CAST(game_date AS STRING), ' 19:00:00'), 'America/New_York'),
                HOUR) as hours_since_start
        FROM `nba_raw.nbac_schedule`
        WHERE game_status IN (1, 2)
          AND game_date < CURRENT_DATE('America/New_York')
        ORDER BY game_date DESC, time_slot
        """

        results = list(client.query(query).result())
        stale_games = []

        for row in results:
            if row.hours_since_start and row.hours_since_start > 4:
                stale_games.append({
                    'game_id': row.game_id,
                    'game_date': str(row.game_date),
                    'current_status': row.game_status,
                    'matchup': f"{row.away_team_abbr}@{row.home_team_abbr}",
                    'hours_since_start': row.hours_since_start
                })

        if not stale_games:
            logging.info("✅ No stale games found")
            return jsonify({
                "status": "success",
                "message": "No stale games found",
                "games_fixed": 0
            }), 200

        # Group by date for partition-safe updates
        games_by_date = {}
        for game in stale_games:
            gdate = game['game_date']
            if gdate not in games_by_date:
                games_by_date[gdate] = []
            games_by_date[gdate].append(game['game_id'])

        # Update games
        total_updated = 0
        for gdate, gids in games_by_date.items():
            game_ids_str = "', '".join(gids)
            update_query = f"""
            UPDATE `nba_raw.nbac_schedule`
            SET game_status = 3, game_status_text = 'Final'
            WHERE game_date = '{gdate}'
              AND game_id IN ('{game_ids_str}')
            """
            client.query(update_query).result()
            total_updated += len(gids)
            logging.info(f"  Updated {len(gids)} games for {gdate}")

        logging.info(f"✅ Fixed {total_updated} stale games")

        return jsonify({
            "status": "success",
            "message": f"Fixed {total_updated} stale games",
            "games_fixed": total_updated,
            "games": [g['matchup'] for g in stale_games]
        }), 200

    except Exception as e:
        logging.error(f"Stale schedule fix failed: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "error_type": type(e).__name__
        }), 500
