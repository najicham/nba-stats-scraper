"""Tests for the halt GATE — the publishing/writer half of the 2026-08-21 batch.

Reviewer finding that prompted this file: every test written for that batch
covered `shared/config/edge_halt.py`. The half that actually decides whether
picks reach the public JSON — the exporter's Step 0, `halt_envelope`'s
carry-forward/fail-closed tiers, the `validate_content` excusals, and the
writer's opening-night guard — had **zero** coverage, so "906 tests pass"
carried no signal about any of it.

These are the invariants worth breaking a build over.
"""
import datetime as dt
import os
from types import SimpleNamespace
from unittest import mock

import pytest

from data_processors.publishing.base_exporter import BaseExporter
from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter


# --------------------------------------------------------------------------- #
# halt_envelope: the three tiers (direct hit / carry-forward / fail-closed)
# --------------------------------------------------------------------------- #

class _StubExporter(BaseExporter):
    """Concrete BaseExporter — the class is abstract on generate_json."""

    def __init__(self):  # noqa: D107 - deliberately skips BaseExporter.__init__
        self.project_id = 'test-project'
        self.bucket_name = 'test-bucket'

    def generate_json(self, target_date, **kwargs):  # pragma: no cover
        return {}


def _envelope_exporter(rows_or_exc):
    """A BaseExporter whose halt_state query returns `rows` (or raises)."""
    exp = _StubExporter()
    if isinstance(rows_or_exc, Exception):
        exp.query_to_list = mock.Mock(side_effect=rows_or_exc)
    else:
        exp.query_to_list = mock.Mock(return_value=rows_or_exc)
    return exp


class TestHaltEnvelopeTiers:
    def test_direct_row_hit(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        exp = _envelope_exporter([{
            'effective_date': today, 'halt_active': True,
            'halt_reason': 'off_season', 'halt_since': dt.date(2026, 5, 27),
        }])
        env = exp.halt_envelope(sport='nba', target_date=today)
        assert env['halt_active'] is True
        assert env['halt_reason'] == 'off_season'
        assert 'halt_carried_forward_from' not in env

    def test_carry_forward_marks_its_source(self):
        """`halt_state` has a real 4-day write gap (2026-08-16..19) that was
        never backfilled. Since the envelope now GATES publishing, a single
        missed write would otherwise cost a slate."""
        today = dt.datetime.now(dt.timezone.utc).date()
        older = today - dt.timedelta(days=2)
        exp = _envelope_exporter([{
            'effective_date': older, 'halt_active': True,
            'halt_reason': 'off_season', 'halt_since': dt.date(2026, 5, 27),
        }])
        env = exp.halt_envelope(sport='nba', target_date=today)
        assert env['halt_active'] is True
        assert env['halt_carried_forward_from'] == older.isoformat()

    def test_carry_forward_is_symmetric(self):
        """A not-halted row carries forward too — the protection guards
        publishing as much as halting."""
        today = dt.datetime.now(dt.timezone.utc).date()
        exp = _envelope_exporter([{
            'effective_date': today - dt.timedelta(days=1), 'halt_active': False,
            'halt_reason': None, 'halt_since': None,
        }])
        env = exp.halt_envelope(sport='nba', target_date=today)
        assert env['halt_active'] is False

    def test_recent_date_with_no_row_fails_closed(self):
        today = dt.datetime.now(dt.timezone.utc).date()
        env = _envelope_exporter([]).halt_envelope(sport='nba', target_date=today)
        assert env['halt_active'] is True
        assert env['halt_reason'] == 'unknown_state'

    def test_old_date_with_no_row_fails_open(self):
        """Historical re-exports must not be blocked."""
        old = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=60)
        env = _envelope_exporter([]).halt_envelope(sport='nba', target_date=old)
        assert env['halt_active'] is False
        assert env['halt_reason'] == 'unknown_state'

    def test_query_error_fails_open_with_unknown_state(self):
        exp = _envelope_exporter(RuntimeError('bq down'))
        env = exp.halt_envelope(sport='nba', target_date=dt.date(2026, 3, 8))
        assert env['halt_active'] is False
        assert env['halt_reason'] == 'unknown_state'

    def test_carry_forward_window_is_bounded(self):
        """The lookback must be a bounded constant, not unbounded history."""
        assert 1 <= BaseExporter.HALT_CARRY_FORWARD_DAYS <= 7


# --------------------------------------------------------------------------- #
# Step 0: halt_state actually gates NBA picks
# --------------------------------------------------------------------------- #

def _gate_exporter(envelope):
    exp = SignalBestBetsExporter.__new__(SignalBestBetsExporter)
    exp.halt_envelope = mock.Mock(return_value=envelope)
    exp._get_best_bets_record = mock.Mock(return_value={'season': {}})
    exp.get_generated_at = mock.Mock(return_value='2026-08-21T00:00:00Z')
    exp.bq_client = mock.Mock()
    return exp


HALTED = {
    'halt_active': True, 'halt_reason': 'manual',
    'halt_since': '2026-03-09', 'halt_source_date': '2026-03-10',
}


class TestStepZeroGate:
    def test_active_halt_returns_zero_picks_without_running_pipelines(self):
        """The gate must short-circuit BEFORE the per-model pipelines: it is
        both the correctness property and the reason a halted date is cheap."""
        exp = _gate_exporter(HALTED)
        with mock.patch(
            'data_processors.publishing.signal_best_bets_exporter.run_all_model_pipelines',
            side_effect=AssertionError('pipelines must not run on a halted date'),
        ):
            out = exp.generate_json('2026-03-10')
        assert out['total_picks'] == 0
        assert out['picks'] == []
        assert out['halt_active'] is True
        assert out['halt_reason'] == 'manual'
        assert out['halt_metrics']['halt_source'] == 'halt_state'

    def test_gate_is_reason_agnostic(self):
        """Decision 4 lands as its own reason string. Any active halt must
        suppress — a whitelist is how the NBA exporter ended up stamping the
        envelope without enforcing it."""
        for reason in ('off_season', 'between_rounds', 'predictions_inactive',
                       'fleet_blocked', 'edge_collapse', 'unit_drawdown',
                       'volume_anomaly', 'manual'):
            exp = _gate_exporter({**HALTED, 'halt_reason': reason})
            with mock.patch(
                'data_processors.publishing.signal_best_bets_exporter.run_all_model_pipelines',
                side_effect=AssertionError('pipelines ran'),
            ):
                out = exp.generate_json('2026-03-10')
            assert out['total_picks'] == 0, reason

    def test_kill_switch_publishes_through_a_halt(self):
        """The halt path is one-way by design (overrides can only ADD a halt),
        so without this the only way back from a false halt is pinning Cloud
        Run traffic to an old revision."""
        exp = _gate_exporter(HALTED)
        sentinel = RuntimeError('reached the pipelines — gate bypassed')
        with mock.patch.dict(os.environ, {'HALT_GATE_ENABLED': 'false'}):
            with mock.patch(
                'data_processors.publishing.signal_best_bets_exporter.run_all_model_pipelines',
                side_effect=sentinel,
            ):
                with pytest.raises(RuntimeError, match='gate bypassed'):
                    exp.generate_json('2026-03-10')

    def test_gate_is_on_by_default(self):
        exp = _gate_exporter(HALTED)
        env = {k: v for k, v in os.environ.items() if k != 'HALT_GATE_ENABLED'}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch(
                'data_processors.publishing.signal_best_bets_exporter.run_all_model_pipelines',
                side_effect=AssertionError('pipelines ran'),
            ):
                assert exp.generate_json('2026-03-10')['total_picks'] == 0


# --------------------------------------------------------------------------- #
# validate_content: which halts legitimately produce zero picks
# --------------------------------------------------------------------------- #

class TestValidateContentExcusal:
    def _payload(self, reason):
        return {
            'date': '2026-03-10', 'halt_active': True, 'halt_reason': reason,
            'total_picks': 0, 'picks': [],
            'model_health': {'status': 'halted', 'hit_rate_7d': None},
        }

    def test_real_halt_reasons_are_excused(self):
        exp = SignalBestBetsExporter.__new__(SignalBestBetsExporter)
        for reason in ('off_season', 'edge_collapse', 'fleet_blocked',
                       'manual', 'unit_drawdown'):
            assert exp.validate_content(self._payload(reason)) is None, reason

    def test_unknown_state_is_not_excused(self):
        """`unknown_state` means "we don't know", not "legitimately zero".
        Letting it through would turn a writer outage into a silent multi-day
        drought that overwrites good files."""
        exp = SignalBestBetsExporter.__new__(SignalBestBetsExporter)
        exp.project_id = 'test-project'
        exp.bucket_name = 'test-bucket'
        payload = self._payload('unknown_state')
        del payload['model_health']            # force a deterministic floor
        assert exp.validate_content(payload) is not None


# --------------------------------------------------------------------------- #
# The writer's opening-night guard
# --------------------------------------------------------------------------- #

class TestPredictionsInactiveOpeningNight:
    """The writer runs 5 AM ET; the daily workflow starts ~6 AM. On opening day
    the lookback contains no predictions because the season has not started —
    and halt_state now GATES publishing, so the 5 AM row would zero the whole
    opening slate. Verified live: 2026-10-20 has past_game_days=0."""

    def _run(self, recent_preds, upcoming_games, past_game_days):
        import orchestration.cloud_functions.halt_state_writer.main as writer
        row = SimpleNamespace(recent_preds=recent_preds,
                              upcoming_games=upcoming_games,
                              past_game_days=past_game_days)
        bq = mock.Mock()
        bq.query.return_value.result.return_value = [row]
        return writer._predictions_inactive(bq, 'nba', dt.date(2026, 10, 20))

    def test_opening_night_does_not_halt(self):
        assert self._run(0, 56, 0) is None

    def test_first_day_back_from_a_league_gap_does_not_halt(self):
        assert self._run(0, 40, 0) is None

    def test_genuinely_dead_pipeline_still_halts(self):
        out = self._run(0, 40, 3)
        assert out is not None and out['past_game_days_3d'] == 3

    def test_flowing_predictions_never_halt(self):
        assert self._run(1091, 40, 3) is None
