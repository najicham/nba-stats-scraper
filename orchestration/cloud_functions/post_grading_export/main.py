"""
Post-Grading Picks Re-Export Cloud Function

Re-exports picks files after grading completes so that actual scores and
hit/miss results are included in the JSON served to the frontend.

The picks exporter already JOINs with player_game_summary at query time,
so re-running the export after grading populates actuals without any
re-materialization step.

Trigger: Pub/Sub topic `nba-grading-complete`
Receives messages with:
- target_date: The date that was graded (YYYY-MM-DD)
- status: Grading outcome (success, skipped, etc.)
- graded_count: Number of predictions graded

Actions on success:
1. Re-export picks/{date}.json with actuals via AllSubsetsPicksExporter
2. Refresh subsets/season.json via SeasonSubsetPicksExporter

Version: 1.0
Created: 2026-02-13 (Session 242)
"""

import base64
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict

# Ensure deployed package root is in Python path (Cloud Functions runtime fix)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Lazy-loaded exporters
_picks_exporter = None
_season_exporter = None


def get_picks_exporter():
    """Get or create AllSubsetsPicksExporter (lazy initialization)."""
    global _picks_exporter
    if _picks_exporter is None:
        try:
            from data_processors.publishing.all_subsets_picks_exporter import AllSubsetsPicksExporter
            _picks_exporter = AllSubsetsPicksExporter()
            logger.info("AllSubsetsPicksExporter initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize AllSubsetsPicksExporter: {e}", exc_info=True)
            raise
    return _picks_exporter


def get_season_exporter():
    """Get or create SeasonSubsetPicksExporter (lazy initialization)."""
    global _season_exporter
    if _season_exporter is None:
        try:
            from data_processors.publishing.season_subset_picks_exporter import SeasonSubsetPicksExporter
            _season_exporter = SeasonSubsetPicksExporter()
            logger.info("SeasonSubsetPicksExporter initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize SeasonSubsetPicksExporter: {e}", exc_info=True)
            raise
    return _season_exporter


def parse_pubsub_message(cloud_event) -> Dict:
    """Parse Pub/Sub CloudEvent and extract message data."""
    try:
        pubsub_message = cloud_event.data.get('message', {})
        if 'data' in pubsub_message:
            message_data = json.loads(
                base64.b64decode(pubsub_message['data']).decode('utf-8')
            )
        else:
            message_data = {}
        return message_data
    except Exception as e:
        logger.error(f"Failed to parse Pub/Sub message: {e}", exc_info=True)
        return {}


@functions_framework.cloud_event
def main(cloud_event):
    """
    Handle grading completion event and re-export picks with actuals.

    Args:
        cloud_event: CloudEvent from Pub/Sub (nba-grading-complete topic)
    """
    start_time = datetime.now(timezone.utc)
    logger.info("Post-grading export triggered")

    # Parse incoming message
    message_data = parse_pubsub_message(cloud_event)

    target_date = message_data.get('target_date')
    status = message_data.get('status')
    graded_count = message_data.get('graded_count', 0)
    correlation_id = message_data.get('correlation_id', 'unknown')

    if not target_date:
        logger.error("No target_date in grading completion message")
        return

    logger.info(
        f"[{correlation_id}] Post-grading export for {target_date} "
        f"(status={status}, graded_count={graded_count})"
    )

    # Only re-export on successful grading
    if status != 'success':
        logger.info(
            f"[{correlation_id}] Skipping re-export — grading status was '{status}', not 'success'"
        )
        return

    if graded_count == 0:
        logger.info(f"[{correlation_id}] Skipping re-export — 0 predictions graded")
        return

    results = {}

    # 1. Re-export picks/{date}.json with actuals
    try:
        exporter = get_picks_exporter()
        picks_path = exporter.export(target_date, trigger_source='post-grading')
        results['picks_path'] = picks_path
        logger.info(f"[{correlation_id}] Re-exported picks to {picks_path}")
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to re-export picks for {target_date}: {e}",
            exc_info=True
        )
        results['picks_error'] = str(e)

    # 2. Refresh subsets/season.json
    try:
        season_exporter = get_season_exporter()
        season_path = season_exporter.export()
        results['season_path'] = season_path
        logger.info(f"[{correlation_id}] Refreshed season.json at {season_path}")
    except Exception as e:
        logger.error(
            f"[{correlation_id}] Failed to refresh season.json: {e}",
            exc_info=True
        )
        results['season_error'] = str(e)

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(
        f"[{correlation_id}] Post-grading export complete for {target_date} "
        f"in {duration:.1f}s: {results}"
    )
