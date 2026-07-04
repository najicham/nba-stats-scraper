"""Tests for the per-game T-30 closing-line sweep (2026-07-03, P1.2).

select_imminent_events is the sweep's core decision: which Odds-API events
tip inside the [min_lead, max_lead]-minute window. With a 30-min scheduler
cadence and the default [15, 50] window every tipoff is captured at
minutes_before_tipoff in [0, 45] — the canonical closing window.
"""

from datetime import datetime, timezone

from scrapers.routes.closing_lines import (
    MAX_LEAD_MINUTES,
    MIN_LEAD_MINUTES,
    select_imminent_events,
)

NOW = datetime(2026, 11, 1, 23, 0, 0, tzinfo=timezone.utc)  # 6 PM ET


def _ev(event_id, commence_iso):
    return {'id': event_id, 'commence_time': commence_iso,
            'home_team': 'Milwaukee Bucks', 'away_team': 'Boston Celtics'}


class TestSelectImminentEvents:
    def test_event_inside_window_selected(self):
        events = [_ev('e1', '2026-11-01T23:30:00Z')]  # T+30
        assert [e['id'] for e in select_imminent_events(
            events, NOW, MIN_LEAD_MINUTES, MAX_LEAD_MINUTES)] == ['e1']

    def test_event_too_soon_and_too_far_excluded(self):
        events = [
            _ev('too_soon', '2026-11-01T23:10:00Z'),   # T+10 < 15
            _ev('too_far', '2026-11-02T00:00:00Z'),    # T+60 > 50
            _ev('in_window', '2026-11-01T23:20:00Z'),  # T+20
        ]
        assert [e['id'] for e in select_imminent_events(
            events, NOW, MIN_LEAD_MINUTES, MAX_LEAD_MINUTES)] == ['in_window']

    def test_window_boundaries_inclusive(self):
        events = [
            _ev('at_min', '2026-11-01T23:15:00Z'),  # exactly T+15
            _ev('at_max', '2026-11-01T23:50:00Z'),  # exactly T+50
        ]
        got = {e['id'] for e in select_imminent_events(
            events, NOW, MIN_LEAD_MINUTES, MAX_LEAD_MINUTES)}
        assert got == {'at_min', 'at_max'}

    def test_thirty_minute_cadence_covers_every_tipoff(self):
        # Sweeps fire every 30 min; window is 35 min wide -> any tipoff time
        # falls inside at least one sweep's window, with lead in [15, 50]
        # (=> capture lands at minutes_before_tipoff in [0, 45] afterwards).
        for tip_minute in range(0, 60, 5):
            tip = datetime(2026, 11, 2, 2, tip_minute, 0, tzinfo=timezone.utc)
            covered = False
            sweep = datetime(2026, 11, 2, 0, 0, 0, tzinfo=timezone.utc)
            while sweep < tip:
                if select_imminent_events(
                        [_ev('e', tip.isoformat())], sweep,
                        MIN_LEAD_MINUTES, MAX_LEAD_MINUTES):
                    covered = True
                    break
                sweep = sweep.replace(minute=sweep.minute % 60)
                from datetime import timedelta
                sweep += timedelta(minutes=30)
            assert covered, f'tipoff at :{tip_minute:02d} never swept'

    def test_malformed_events_skipped(self):
        events = [
            {'id': 'no_time'},
            {'commence_time': '2026-11-01T23:30:00Z'},          # no id
            _ev('bad_time', 'not-a-timestamp'),
            'not-a-dict',
            _ev('good', '2026-11-01T23:30:00Z'),
        ]
        assert [e['id'] for e in select_imminent_events(
            events, NOW, MIN_LEAD_MINUTES, MAX_LEAD_MINUTES)] == ['good']

    def test_naive_timestamp_treated_as_utc(self):
        events = [_ev('naive', '2026-11-01T23:30:00')]
        assert len(select_imminent_events(
            events, NOW, MIN_LEAD_MINUTES, MAX_LEAD_MINUTES)) == 1
