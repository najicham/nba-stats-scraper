"""The halt-state precedence chain in `halt_state_writer.evaluate_halt_state`.

WHY THIS EXISTS
---------------
`nba_orchestration.halt_state` is the single source of truth for "is the system
producing picks today?", and since 2026-08-21 an active row actually SUPPRESSES
NBA picks rather than merely labelling them. `evaluate_halt_state` composes six
independent detectors into one row:

    schedule(off_season / between_rounds)
      -> edge degeneracy
      -> volume anomaly
      -> unit drawdown
      -> fleet_blocked
      -> predictions_inactive
      -> pick_drought (MLB)
      -> manual override

The ORDER is load-bearing and none of it was tested. Two properties in
particular are easy to break by reordering and impossible to notice afterwards:

  * The performance breakers (volume, drawdown) sit ABOVE the infrastructure
    reasons, because "we are losing money" outranks "a component looks odd".
    Reversing them would relabel a real drawdown as `fleet_blocked` and route
    the operator to the wrong runbook.
  * The manual override is applied LAST and is ADD-ONLY. It must never be able
    to un-halt: a forgotten override that could resume the system would publish
    picks straight through an off-season.

Every detector is mocked. This file tests composition, not detection — the
detectors have their own tests (`test_edge_halt.py`, `test_drawdown_halt.py`,
`test_halt_gate.py`).
"""

import datetime as dt
from unittest import mock

import pytest

import orchestration.cloud_functions.halt_state_writer.main as writer


TODAY = dt.date(2026, 11, 15)


class _Chain:
    """Patches every detector `evaluate_halt_state` calls.

    Defaults describe a completely healthy in-season day: games on the schedule,
    no detector firing, no override. Each test turns on exactly the detectors it
    cares about, so a test that passes for the wrong reason is hard to write.
    """

    def __init__(self, **overrides):
        self.cfg = dict(
            has_games=True,
            games_today=8,
            has_future_games_14d=True,
            in_window=True,
            edge=(None, {}),
            volume=(None, {}),
            drawdown=(None, {}),
            transition=None,
            fleet=None,
            inactive=None,
            drought=None,
            override=None,
        )
        self.cfg.update(overrides)
        self._patches = []

    def __enter__(self):
        c = self.cfg
        specs = [
            ('_has_recent_games', lambda *a, **k: (c['has_games'], c['games_today'],
                                                   c['has_future_games_14d'])),
            ('_is_in_season_window', lambda *a, **k: c['in_window']),
            ('_nba_edge_degeneracy', lambda *a, **k: c['edge']),
            ('_nba_volume_anomaly', lambda *a, **k: c['volume']),
            ('_nba_unit_drawdown', lambda *a, **k: c['drawdown']),
            ('_fleet_in_transition', lambda *a, **k: c['transition']),
            ('_fleet_blocked', lambda *a, **k: c['fleet']),
            ('_predictions_inactive', lambda *a, **k: c['inactive']),
            ('_mlb_pick_drought', lambda *a, **k: c['drought']),
            ('_get_active_override', lambda *a, **k: c['override']),
        ]
        for name, fn in specs:
            p = mock.patch.object(writer, name, side_effect=fn)
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def run(sport='nba', today=TODAY, **overrides):
    with _Chain(**overrides):
        return writer.evaluate_halt_state(mock.Mock(), today, sport)


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #

def test_healthy_day_is_not_halted():
    out = run()
    assert out['halt_active'] is False
    assert out['halt_reason'] is None


def test_schedule_metrics_are_always_recorded():
    """These four keys are the audit trail for every row, halted or not."""
    m = run()['halt_metrics']
    assert m['games_today'] == 8
    assert m['has_games_in_21d_window'] is True
    assert m['has_future_games_14d'] is True
    assert m['in_season_window'] is True


# --------------------------------------------------------------------------- #
# Step 1 — schedule presence
# --------------------------------------------------------------------------- #

class TestSchedulePresence:

    def test_no_games_in_window_is_off_season(self):
        out = run(has_games=False, games_today=0)
        assert out['halt_active'] is True
        assert out['halt_reason'] == 'off_season'

    def test_outside_season_window_is_off_season(self):
        out = run(in_window=False)
        assert out['halt_reason'] == 'off_season'

    def test_in_window_but_no_future_games_is_between_rounds(self):
        out = run(has_future_games_14d=False)
        assert out['halt_active'] is True
        assert out['halt_reason'] == 'between_rounds'

    def test_off_season_short_circuits_every_later_detector(self):
        """Once off_season is set, the later detectors must not even run: they
        query tables that are empty in the off-season and their metrics would be
        noise on the row."""
        with _Chain(has_games=False, games_today=0,
                    volume=('volume_anomaly', {'vol_trigger_picks': 99})) as _:
            out = writer.evaluate_halt_state(mock.Mock(), TODAY, 'nba')
        assert out['halt_reason'] == 'off_season'
        assert 'vol_trigger_picks' not in out['halt_metrics']


# --------------------------------------------------------------------------- #
# Step 2 — the NBA breakers, and their relative order
# --------------------------------------------------------------------------- #

class TestNbaBreakerPrecedence:

    def test_edge_degeneracy_halts(self):
        out = run(edge=('edge_collapse', {'edge_med_7d': 0.2}))
        assert out['halt_reason'] == 'edge_collapse'
        assert out['halt_metrics']['edge_med_7d'] == 0.2

    def test_volume_anomaly_halts(self):
        out = run(volume=('volume_anomaly', {'vol_trigger_picks': 16}))
        assert out['halt_reason'] == 'volume_anomaly'

    def test_unit_drawdown_halts(self):
        out = run(drawdown=('unit_drawdown', {'dd_units': -7.1}))
        assert out['halt_reason'] == 'unit_drawdown'

    def test_volume_outranks_drawdown(self):
        """Documented order: volume is checked first because it needs no grading
        and is the guard that recovers the money in replay."""
        out = run(volume=('volume_anomaly', {'vol_trigger_picks': 16}),
                  drawdown=('unit_drawdown', {'dd_units': -7.1}))
        assert out['halt_reason'] == 'volume_anomaly'

    def test_edge_outranks_volume(self):
        out = run(edge=('edge_collapse', {'edge_med_7d': 0.2}),
                  volume=('volume_anomaly', {'vol_trigger_picks': 16}))
        assert out['halt_reason'] == 'edge_collapse'

    def test_drawdown_outranks_fleet_blocked(self):
        """The one that matters most. `fleet_blocked` sends the operator to
        model health; `unit_drawdown` sends them to the drawdown runbook and a
        3/7-day release with a peak reset. Getting this backwards means a real
        money-losing streak is investigated as a model-registry problem."""
        out = run(drawdown=('unit_drawdown', {'dd_units': -11.0}),
                  fleet={'fleet_blocked_models': 3})
        assert out['halt_reason'] == 'unit_drawdown'

    def test_volume_outranks_predictions_inactive(self):
        out = run(volume=('volume_anomaly', {'vol_trigger_picks': 16}),
                  inactive={'past_game_days_3d': 3})
        assert out['halt_reason'] == 'volume_anomaly'

    def test_nba_breakers_are_skipped_for_mlb(self):
        """MLB thresholds are not calibrated; the guards must not run there even
        if the underlying queries would return something."""
        out = run(sport='mlb',
                  edge=('edge_collapse', {'edge_med_7d': 0.2}),
                  volume=('volume_anomaly', {'vol_trigger_picks': 16}),
                  drawdown=('unit_drawdown', {'dd_units': -11.0}))
        assert out['halt_active'] is False
        assert out['halt_reason'] is None


# --------------------------------------------------------------------------- #
# Step 3 — fleet_blocked and its transition suspension
# --------------------------------------------------------------------------- #

class TestFleetBlocked:

    def test_fleet_blocked_halts(self):
        out = run(fleet={'fleet_blocked_models': 3})
        assert out['halt_active'] is True
        assert out['halt_reason'] == 'fleet_blocked'
        assert out['halt_metrics']['fleet_blocked_models'] == 3

    def test_fleet_in_transition_suppresses_the_halt_but_is_recorded(self):
        """A fresh fleet with no model_performance_daily rows yet reads as
        BLOCKED from the prior generation's stale decay_state. Suspending the
        halt is correct; losing the audit trail is not."""
        out = run(transition={'fleet_in_transition_models': 3,
                              'fleet_in_transition_ages': [1, 1, 2],
                              'fleet_in_transition_mpd_rows': 0},
                  fleet={'fleet_blocked_models': 3})
        assert out['halt_active'] is False
        assert out['halt_reason'] is None
        assert out['halt_metrics']['fleet_in_transition_models'] == 3
        assert 'fleet_blocked_models' not in out['halt_metrics']

    def test_fleet_blocked_applies_to_mlb_too(self):
        out = run(sport='mlb', fleet={'fleet_blocked_models': 2})
        assert out['halt_reason'] == 'fleet_blocked'


# --------------------------------------------------------------------------- #
# Steps 4 and 5 — last-resort detectors
# --------------------------------------------------------------------------- #

class TestLastResortDetectors:

    def test_predictions_inactive_halts(self):
        out = run(inactive={'past_game_days_3d': 3})
        assert out['halt_reason'] == 'predictions_inactive'

    def test_fleet_blocked_outranks_predictions_inactive(self):
        out = run(fleet={'fleet_blocked_models': 3},
                  inactive={'past_game_days_3d': 3})
        assert out['halt_reason'] == 'fleet_blocked'

    def test_pick_drought_is_mlb_only(self):
        out = run(sport='nba', drought={'drought_days': 3})
        assert out['halt_active'] is False

    def test_pick_drought_halts_for_mlb(self):
        out = run(sport='mlb', drought={'drought_days': 3})
        assert out['halt_reason'] == 'pick_drought'


# --------------------------------------------------------------------------- #
# Step 6 — the manual override, which is ADD-ONLY
# --------------------------------------------------------------------------- #

class TestManualOverride:

    OVR = {'halt_reason': 'manual', 'override_created_by': 'naji'}

    def test_override_halts_an_otherwise_healthy_day(self):
        out = run(override=self.OVR)
        assert out['halt_active'] is True
        assert out['halt_reason'] == 'manual'
        assert out['halt_metrics']['manual_override'] == self.OVR

    def test_override_cannot_resume_the_system(self):
        """THE invariant. An override may only ADD a halt. If it could clear
        one, a forgotten row would publish a full slate through the off-season —
        and since the gate went live, that is a real-money failure, not a label."""
        out = run(has_games=False, games_today=0, override=self.OVR)
        assert out['halt_active'] is True
        assert out['halt_reason'] == 'off_season'

    def test_natural_reason_wins_over_the_override_reason(self):
        """When both fire, the operator needs the DIAGNOSTIC reason, not
        'manual'. The override still lands in halt_metrics for the audit."""
        out = run(drawdown=('unit_drawdown', {'dd_units': -11.0}),
                  override=self.OVR)
        assert out['halt_reason'] == 'unit_drawdown'
        assert out['halt_metrics']['manual_override'] == self.OVR

    def test_override_applies_to_mlb(self):
        out = run(sport='mlb', override=self.OVR)
        assert out['halt_reason'] == 'manual'


# --------------------------------------------------------------------------- #
# Shape contract — downstream readers index these keys directly
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('kwargs', [
    {},
    {'has_games': False, 'games_today': 0},
    {'drawdown': ('unit_drawdown', {'dd_units': -11.0})},
    {'override': {'halt_reason': 'manual', 'override_created_by': 'naji'}},
])
def test_return_shape_is_stable(kwargs):
    out = run(**kwargs)
    assert set(out) == {'halt_active', 'halt_reason', 'halt_metrics'}
    assert isinstance(out['halt_active'], bool)
    assert isinstance(out['halt_metrics'], dict)
    assert (out['halt_reason'] is None) == (out['halt_active'] is False)
