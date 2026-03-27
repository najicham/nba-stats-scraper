"""
scraper.py

Flask blueprint for scraper execution routes.
Extracted from main_scraper_service.py for modular routing.

Path: scrapers/routes/scraper.py
"""

from __future__ import annotations

import logging
from flask import Blueprint, request, jsonify, current_app

# Import from centralized registry
from scrapers.registry import (
    get_scraper_instance,
    list_scrapers,
    scraper_exists
)

# Create blueprint
scraper = Blueprint('scraper', __name__)

# MLB scrapers that require event_id from a prior mlb_events call.
# When called without event_id, auto-discover events first.
_MLB_EVENT_DEPENDENT_SCRAPERS = {
    'mlb_pitcher_props',
    'mlb_batter_props',
}


def _resolve_game_date(params: dict) -> str | None:
    """Extract game_date from params, handling 'TODAY' sentinel."""
    from datetime import date as _date
    raw = params.get('game_date') or params.get('date')
    if raw and str(raw).upper() == 'TODAY':
        return _date.today().isoformat()
    return raw


def _auto_discover_mlb_events(game_date: str, group: str) -> list[str]:
    """
    Run mlb_events scraper to discover Odds API event IDs for a date.

    Returns list of event_id strings (may be empty).
    """
    logger = logging.getLogger(__name__)
    if not scraper_exists('mlb_events'):
        logger.warning("mlb_events scraper not in registry - cannot auto-discover")
        return []

    events_scraper = get_scraper_instance('mlb_events')
    result = events_scraper.run({
        'game_date': game_date,
        'group': group,
    })

    if not result:
        logger.warning("mlb_events scraper failed - no events discovered")
        return []

    stats = events_scraper.get_scraper_stats()
    event_ids = stats.get('event_ids', [])
    logger.info("Auto-discovered %d MLB event IDs for %s", len(event_ids), game_date)
    return event_ids


def _run_scraper_per_event(scraper_name: str, event_ids: list[str],
                           base_params: dict) -> dict:
    """
    Run an event-dependent MLB scraper once per event_id.

    Returns aggregate result dict.
    """
    logger = logging.getLogger(__name__)
    results = []
    total_rows = 0

    for event_id in event_ids:
        per_event_params = {**base_params, 'event_id': event_id}
        scraper_inst = get_scraper_instance(scraper_name)

        logger.info("Running %s for event %s", scraper_name, event_id)
        success = scraper_inst.run(per_event_params)
        stats = scraper_inst.get_scraper_stats()

        results.append({
            'event_id': event_id,
            'status': 'success' if success else 'error',
            'run_id': scraper_inst.run_id,
            'rowCount': stats.get('rowCount', 0),
        })
        if success:
            total_rows += stats.get('rowCount', 0)

    succeeded = sum(1 for r in results if r['status'] == 'success')
    failed = len(results) - succeeded

    return {
        'status': 'success' if succeeded > 0 else 'error',
        'message': (f"{scraper_name}: {succeeded}/{len(event_ids)} events succeeded, "
                    f"{total_rows} total rows"),
        'scraper': scraper_name,
        'events_total': len(event_ids),
        'events_succeeded': succeeded,
        'events_failed': failed,
        'total_rows': total_rows,
        'event_results': results,
    }


@scraper.route('/scrape', methods=['POST'])
def route_scraper():
    """Route to the appropriate scraper based on 'scraper' parameter."""
    try:
        # Get parameters from JSON body or query params
        params = None
        if request.is_json:
            params = request.get_json(silent=True)

        # Fallback to query params if JSON is None or not provided
        if params is None:
            params = request.args.to_dict()

        # Final safety check - ensure params is never None
        if params is None:
            params = {}

        # Get scraper name
        scraper_name = params.get("scraper")
        if not scraper_name:
            return jsonify({
                "error": "Missing required parameter: scraper",
                "available_scrapers": list_scrapers(),
                "note": "Provide scraper name in JSON body or query parameter"
            }), 400

        # Verify scraper exists
        if not scraper_exists(scraper_name):
            return jsonify({
                "error": f"Unknown scraper: {scraper_name}",
                "available_scrapers": list_scrapers()
            }), 400

        # ----------------------------------------------------------------
        # MLB auto-event-discovery: when an event-dependent scraper is
        # called without event_id, auto-discover events first, then run
        # the scraper once per event.
        # ----------------------------------------------------------------
        if (scraper_name in _MLB_EVENT_DEPENDENT_SCRAPERS
                and not params.get('event_id')):
            game_date = _resolve_game_date(params)
            if not game_date:
                return jsonify({
                    "error": (f"{scraper_name} requires event_id or game_date. "
                              "Provide at least one."),
                }), 400

            current_app.logger.info(
                "Auto-discovering MLB events for %s (game_date=%s)",
                scraper_name, game_date)

            group = params.get('group', 'prod')
            event_ids = _auto_discover_mlb_events(game_date, group)

            if not event_ids:
                return jsonify({
                    "status": "error",
                    "message": f"No MLB events found for {game_date}",
                    "scraper": scraper_name,
                }), 200  # 200 because no-games is not a server error

            # Build base params (exclude scraper name and date aliases)
            base_params = {k: v for k, v in params.items()
                          if k not in ('scraper', 'date')}
            base_params['game_date'] = game_date
            base_params.setdefault('group', 'prod')

            agg = _run_scraper_per_event(scraper_name, event_ids, base_params)
            status_code = 200 if agg['status'] == 'success' else 500
            return jsonify(agg), status_code

        # ----------------------------------------------------------------
        # Standard single-scraper path
        # ----------------------------------------------------------------

        # Load scraper using registry
        try:
            current_app.logger.info(f"Loading scraper: {scraper_name}")
            scraper = get_scraper_instance(scraper_name)
            current_app.logger.info(f"Successfully loaded {scraper_name}")
        except (ImportError, AttributeError) as e:
            current_app.logger.error(f"Failed to import scraper {scraper_name}: {e}")
            return jsonify({
                "error": f"Failed to load scraper: {scraper_name}",
                "details": str(e)
            }), 500

        # Remove 'scraper' from params before passing to scraper
        scraper_params = {k: v for k, v in params.items() if k != "scraper"}

        # Add default values
        scraper_params.setdefault("group", "prod")
        scraper_params.setdefault("debug", False)

        # Set debug logging if requested
        if scraper_params.get("debug"):
            logging.getLogger().setLevel(logging.DEBUG)

        # Run the scraper
        current_app.logger.info(f"Running scraper {scraper_name} with params: {scraper_params}")
        result = scraper.run(scraper_params)

        if result:
            return jsonify({
                "status": "success",
                "message": f"{scraper_name} completed successfully",
                "scraper": scraper_name,
                "run_id": scraper.run_id,
                "data_summary": scraper.get_scraper_stats()
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": f"{scraper_name} failed",
                "scraper": scraper_name,
                "run_id": scraper.run_id
            }), 500

    except Exception as e:
        current_app.logger.error(f"Scraper routing error: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "scraper": params.get("scraper", "unknown") if params else "unknown",
            "error_type": type(e).__name__
        }), 500
