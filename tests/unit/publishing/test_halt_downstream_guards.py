"""Two one-line halt guards that each exist because of a real past incident.

1. `post_grading_export.patch_best_bets_json` — the halted RE-ADD guard.
   A halt zeroes the published GCS day file, but any rows a pre-halt export
   already wrote to `signal_best_bets_picks` are still `signal_status='active'`.
   The next morning's grading patch sees them as "missing from the JSON" and,
   without the guard, re-adds all of them — republishing a full graded slate
   under `halt_active: true`. Since 2026-08-21 halt_state actually suppresses
   picks, so this silently undoes real-money suppression in the public record.

2. `weekly_retrain.is_computed_edge_halt` — the governance-loosening gate.
   Publishing and governance have OPPOSITE safe directions. `resolve_halt_state`
   is deliberately fail-CLOSED for publishing: on a BigQuery failure it falls
   back to the last known row and, failing that, halts. Reading `halt_active`
   alone would therefore let a transient 5 AM BigQuery outage — or a
   carried-forward `off_season` row — loosen the model governance gates for
   every family's retrain.
"""

from unittest import mock

import pytest

import orchestration.cloud_functions.post_grading_export.main as pge
import orchestration.cloud_functions.weekly_retrain.main as wr


# --------------------------------------------------------------------------- #
# 1. The halted re-add guard
# --------------------------------------------------------------------------- #

def bq_pick(lookup, *, actual=30.0, correct=True):
    return {
        'player_lookup': lookup,
        'player_name': lookup.title(),
        'team': 'LAL',
        'opponent': 'GSW',
        'direction': 'UNDER',
        'line': 27.5,
        'prediction': 22.0,
        'edge': 5.5,
        'confidence': 0.8,
        'system_id': 'catboost_v12_noveg_train0206_0402',
        'signals': ['home_under'],
        'game_id': '20261115_LAL_GSW',
        'actual': actual,
        'correct': correct,
    }


def json_pick(lookup):
    return {'player_lookup': lookup, 'player': lookup.title(), 'direction': 'UNDER'}


class TestHaltedReAddGuard:

    def test_halted_file_does_not_gain_picks(self):
        """THE incident. Zero picks published, three rows left active in BQ."""
        bb = {'halt_active': True, 'halt_reason': 'unit_drawdown', 'picks': []}
        picks = {n: bq_pick(n) for n in ('a', 'b', 'c')}

        wins, losses = pge.patch_best_bets_json(bb, picks, '2026-11-15')

        assert bb['picks'] == []
        assert bb['total_picks'] == 0
        assert (wins, losses) == (0, 0)

    @pytest.mark.parametrize('reason', [
        'off_season', 'manual', 'edge_collapse', 'unit_drawdown',
        'volume_anomaly', 'fleet_blocked', 'predictions_inactive',
    ])
    def test_guard_is_reason_agnostic(self, reason):
        """It keys on `halt_active`, not on the reason. Every halt reason
        suppresses publishing, so every one must suppress the re-add."""
        bb = {'halt_active': True, 'halt_reason': reason, 'picks': []}
        pge.patch_best_bets_json(bb, {'a': bq_pick('a')}, '2026-11-15')
        assert bb['picks'] == []

    def test_unhalted_file_still_gains_missing_picks(self):
        """The guard must not break the feature it guards: on a normal day a
        pick added by a manual override after export IS backfilled."""
        bb = {'halt_active': False, 'picks': []}
        wins, losses = pge.patch_best_bets_json(
            bb, {'a': bq_pick('a', correct=True)}, '2026-11-15')
        assert [p['player_lookup'] for p in bb['picks']] == ['a']
        assert (wins, losses) == (1, 0)

    def test_missing_halt_key_is_treated_as_not_halted(self):
        """Files published before the halt envelope existed have no
        `halt_active` key. Those days were genuinely live; don't strand them."""
        bb = {'picks': []}
        pge.patch_best_bets_json(bb, {'a': bq_pick('a')}, '2026-11-15')
        assert len(bb['picks']) == 1

    def test_halted_file_still_grades_picks_it_already_published(self):
        """Suppressing the RE-ADD is not the same as suppressing grading. A day
        that published picks and was halted later must still show results."""
        bb = {
            'halt_active': True,
            'halt_reason': 'volume_anomaly',
            'picks': [json_pick('already_there')],
        }
        picks = {
            'already_there': bq_pick('already_there', actual=19.0, correct=True),
            'never_published': bq_pick('never_published'),
        }
        wins, losses = pge.patch_best_bets_json(bb, picks, '2026-11-15')

        assert [p['player_lookup'] for p in bb['picks']] == ['already_there']
        assert bb['picks'][0]['result'] == 'WIN'
        assert bb['picks'][0]['actual'] == 19.0
        assert (wins, losses) == (1, 0)

    def test_record_reflects_only_published_picks_when_halted(self):
        bb = {
            'halt_active': True, 'halt_reason': 'manual',
            'picks': [json_pick('p1'), json_pick('p2')],
        }
        picks = {
            'p1': bq_pick('p1', correct=True),
            'p2': bq_pick('p2', correct=False),
            'p3': bq_pick('p3', correct=False),   # would have been re-added
            'p4': bq_pick('p4', correct=False),
        }
        pge.patch_best_bets_json(bb, picks, '2026-11-15')
        assert bb['record']['day'] == {'wins': 1, 'losses': 1, 'pct': 0.5}
        assert bb['total_picks'] == 2

    def test_ungraded_picks_do_not_move_the_record(self):
        bb = {'halt_active': False, 'picks': [json_pick('p1')]}
        wins, losses = pge.patch_best_bets_json(
            bb, {'p1': bq_pick('p1', actual=None)}, '2026-11-15')
        assert (wins, losses) == (0, 0)
        assert bb['record']['day']['pct'] == 0.0
        assert 'result' not in bb['picks'][0]

    def test_existing_season_month_week_records_survive(self):
        """Only the `day` bucket is recomputed; the rolling records are carried
        through untouched."""
        bb = {
            'halt_active': False,
            'picks': [],
            'record': {'season': {'wins': 415}, 'month': {'wins': 20},
                       'week': {'wins': 5}},
        }
        pge.patch_best_bets_json(bb, {}, '2026-11-15')
        assert bb['record']['season'] == {'wins': 415}
        assert bb['record']['month'] == {'wins': 20}
        assert bb['record']['week'] == {'wins': 5}

    def test_guard_logs_loudly(self):
        """A suppressed re-add must be visible in logs — otherwise a halted day
        with active BQ rows looks identical to a day with nothing to add."""
        bb = {'halt_active': True, 'halt_reason': 'unit_drawdown', 'picks': []}
        with mock.patch.object(pge.logger, 'warning') as warn:
            pge.patch_best_bets_json(bb, {'a': bq_pick('a')}, '2026-11-15', 'cid')
        assert warn.called
        assert 'halted' in warn.call_args[0][0]


# --------------------------------------------------------------------------- #
# 2. The governance-loosening gate
# --------------------------------------------------------------------------- #

class TestIsComputedEdgeHalt:

    def test_computed_active_halt_loosens(self):
        assert wr.is_computed_edge_halt(
            {'halt_active': True, 'halt_source': 'computed'}) is True

    def test_computed_but_not_active_does_not_loosen(self):
        assert wr.is_computed_edge_halt(
            {'halt_active': False, 'halt_source': 'computed'}) is False

    @pytest.mark.parametrize('source', ['fallback', 'last_known', 'row', 'manual', None])
    def test_non_computed_source_never_loosens(self, source):
        """The whole point. `resolve_halt_state` is fail-closed for publishing:
        a BigQuery outage yields an ACTIVE halt from a non-computed source. That
        must tighten governance, not relax it."""
        assert wr.is_computed_edge_halt(
            {'halt_active': True, 'halt_source': source}) is False

    def test_carried_forward_off_season_row_does_not_loosen(self):
        """Every off-season day carries an active row. If that loosened the
        gates, the first retrain of the season would run with season-restart
        governance and could promote a model that never earned it."""
        assert wr.is_computed_edge_halt(
            {'halt_active': True, 'halt_source': 'last_known',
             'halt_reason': 'off_season'}) is False

    def test_missing_source_key_does_not_loosen(self):
        assert wr.is_computed_edge_halt({'halt_active': True}) is False

    def test_empty_state_does_not_loosen(self):
        assert wr.is_computed_edge_halt({}) is False
