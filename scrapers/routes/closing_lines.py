"""
closing_lines.py

Per-game T-30 closing-line sweep (2026-07-03, CLV closing-line capture).

The betting_lines workflow runs on a fixed ~2h cadence and stops producing
snapshots by ~18:00 ET, while NBA games tip 19:00-22:30 ET — so for most of
the slate the last captured line is T-2h to T-6h, NOT the close the CLV
research was validated on (+15.8pp UNDER edge measured on to-the-tip
snapshots). This route closes that gap:

- Invoked by Cloud Scheduler every 30 min on game days
  (job: nba-closing-lines-sweep; see bin/deploy/deploy_closing_lines_scheduler.sh).
- Cheap BQ pre-check against nbac_schedule: any game tipping in the next
  [15, 50] minutes? If not, no-op (no scraper runs, no API calls).
- Otherwise: run oddsa_events (quota-free endpoint), select the imminent
  events by the API's own commence_time, and run oddsa_player_props once per
  imminent event with snapshot_type='closing'.

With a 30-min cadence and a 35-min-wide window every game gets >= 1 capture
at minutes_before_tipoff in [0, 45] — the canonical closing window
(see check_closing_line_capture canary + supplemental_data CLV query).

Path: scrapers/routes/closing_lines.py
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

logger = logging.getLogger(__name__)

closing_lines = Blueprint('closing_lines', __name__)

# A game is "imminent" when its tipoff is within [MIN_LEAD, MAX_LEAD] minutes
# from now. 35-min width + 30-min scheduler cadence guarantees every tipoff
# lands in exactly one or two sweeps (double-capture is harmless — the
# closing definition takes the LAST snapshot in [0, 45]).
MIN_LEAD_MINUTES = 15
MAX_LEAD_MINUTES = 50


def _imminent_games_from_schedule(now_utc: datetime) -> int:
    """Count games tipping within the lead window (BQ, no API cost).

    Uses nbac_schedule.game_date_est — despite the name it is a true UTC
    instant (verified: LAC@SAC 9 PM ET stored as 01:00Z next day), so compare
    TIMESTAMPs directly. game_date spans today±1 ET for the partition filter
    (late ET games cross the UTC date line). Fail-open on error: return -1 so
    the sweep proceeds to the events call (the events endpoint is quota-free;
    missing a close costs more than a redundant call).
    """
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project='nba-props-platform')
        query = """
        SELECT COUNT(*) AS n
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date BETWEEN DATE_SUB(@today_et, INTERVAL 1 DAY)
                            AND DATE_ADD(@today_et, INTERVAL 1 DAY)
          AND game_status = 1
          AND game_date_est BETWEEN TIMESTAMP_ADD(@now, INTERVAL @min_lead MINUTE)
                                AND TIMESTAMP_ADD(@now, INTERVAL @max_lead MINUTE)
        """
        import pytz
        today_et = now_utc.astimezone(pytz.timezone('America/New_York')).date()
        job = client.query(query, job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('today_et', 'DATE', today_et),
                bigquery.ScalarQueryParameter('now', 'TIMESTAMP', now_utc),
                bigquery.ScalarQueryParameter('min_lead', 'INT64', MIN_LEAD_MINUTES),
                bigquery.ScalarQueryParameter('max_lead', 'INT64', MAX_LEAD_MINUTES),
            ]
        ))
        return int(list(job.result(timeout=20))[0].n)
    except Exception as e:  # noqa: BLE001 — pre-check must not block the sweep
        logger.warning("closing-line sweep schedule pre-check failed: %s", e)
        return -1


def select_imminent_events(events: list, now_utc: datetime,
                           min_lead: int, max_lead: int) -> list:
    """Filter Odds-API event dicts to those tipping in [min_lead, max_lead] min.

    Uses the API's own commence_time — authoritative for
    minutes_before_tipoff, which the props processor derives from it.
    Malformed events (no id / no commence_time / bad timestamp) are skipped.
    """
    lo = now_utc + timedelta(minutes=min_lead)
    hi = now_utc + timedelta(minutes=max_lead)
    imminent = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        ct_raw = ev.get('commence_time')
        if not ct_raw or not ev.get('id'):
            continue
        try:
            ct = datetime.fromisoformat(str(ct_raw).replace('Z', '+00:00'))
        except ValueError:
            continue
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        if lo <= ct <= hi:
            imminent.append(ev)
    return imminent


@closing_lines.route('/closing-line-sweep', methods=['POST'])
def closing_line_sweep():
    """Capture a to-the-tip odds snapshot for games tipping in ~15-50 min.

    Always returns 200 (scheduler treats non-200 as failure; a no-games
    sweep is success). Body: {'status', 'imminent_games', 'events_swept',
    'events_failed'}.
    """
    from scrapers.registry import get_scraper_instance

    params = (request.get_json(silent=True) or {}) if request.is_json else {}
    min_lead = int(params.get('min_lead_minutes', MIN_LEAD_MINUTES))
    max_lead = int(params.get('max_lead_minutes', MAX_LEAD_MINUTES))

    now_utc = datetime.now(timezone.utc)
    import pytz
    game_date_et = now_utc.astimezone(pytz.timezone('America/New_York')).date().isoformat()

    # 1. Cheap schedule pre-check (no API cost). -1 = check failed, proceed.
    n_scheduled = _imminent_games_from_schedule(now_utc)
    if n_scheduled == 0:
        return jsonify({
            'status': 'success',
            'imminent_games': 0,
            'events_swept': 0,
            'message': 'no games tipping in the lead window',
        }), 200

    # 2. Discover today's events (the /events endpoint is quota-free).
    try:
        events_scraper = get_scraper_instance('oddsa_events')
        ok = events_scraper.run({
            'sport': 'basketball_nba',
            'game_date': game_date_et,
            'group': params.get('group', 'prod'),
        })
        events = []
        if ok and hasattr(events_scraper, 'data') and isinstance(events_scraper.data, dict):
            events = events_scraper.data.get('events', []) or []
    except Exception as e:  # noqa: BLE001
        logger.error("closing-line sweep: oddsa_events failed: %s", e)
        return jsonify({'status': 'error', 'message': f'events discovery failed: {e}'}), 200

    # 3. Select imminent events by the API's own commence_time.
    imminent = select_imminent_events(events, now_utc, min_lead, max_lead)

    if not imminent:
        return jsonify({
            'status': 'success',
            'imminent_games': 0,
            'events_swept': 0,
            'message': f'{len(events)} events today, none tipping in '
                       f'[{min_lead},{max_lead}] min',
        }), 200

    # 4. One closing-tagged props snapshot per imminent event.
    swept, failed = 0, 0
    for ev in imminent:
        try:
            props_scraper = get_scraper_instance('oddsa_player_props')
            ok = props_scraper.run({
                'event_id': ev['id'],
                'game_date': game_date_et,
                'snapshot_type': 'closing',
                'group': params.get('group', 'prod'),
            })
            if ok:
                swept += 1
            else:
                failed += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.error("closing-line sweep: props failed for event %s: %s",
                         ev.get('id'), e)

    logger.info(
        "closing-line sweep: %d imminent game(s), %d swept, %d failed "
        "(window [%d,%d] min)", len(imminent), swept, failed, min_lead, max_lead,
    )
    return jsonify({
        'status': 'success' if failed == 0 else 'partial',
        'imminent_games': len(imminent),
        'events_swept': swept,
        'events_failed': failed,
    }), 200
