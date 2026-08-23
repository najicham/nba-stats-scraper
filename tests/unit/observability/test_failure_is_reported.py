"""Handlers must report failure as failure.

Phase B of docs/09-handoff/2026-08-22-SESSION-7-START.md. Opening night through
~Nov 4 produces zero picks by design, and almost nothing pages anyone through
that window. The precondition for noticing a real failure in it is that failing
code says so.

Of the six defects found on the roster seed path on 2026-08-22/23, FOUR reported
success while failing. That is not one bad code path, it is a habit, and these
are the places it was already known to live:

  weekly_retrain            returned 200 on total failure, by design, with the
                            comment "so scheduler doesn't retry" — and nothing
                            else in the system watches model age.
  expected_outputs_planner  returned 200 with a populated errors list, so a
                            grid with holes reported success. The reconciler can
                            only flip rows that exist; an unplanned date is never
                            missed.
  halt_state_writer         docstring promised "500 on unrecoverable error" and
                            the function's only return was 200.
  prediction_accuracy       turned BigQuery NotFound / ServiceUnavailable /
                            DeadlineExceeded into [] and {}, which grade_date
                            renders as {'status': 'no_predictions'} — a success
                            shape. Its comment claimed this enabled a Pub/Sub
                            retry; it did not, because the caller never saw an
                            error.

Each test asserts the HTTP status or the exception, not the log line, because
the log line is what everyone already had.
"""

import importlib.util
import pathlib
from unittest.mock import Mock, patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f'cf_{name}', REPO / 'orchestration' / 'cloud_functions' / name / 'main.py'
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _request(**args):
    r = Mock()
    r.args = args
    return r


# ---------------------------------------------------------------------------


class TestWeeklyRetrain:

    @staticmethod
    def _exploding_request():
        """A request whose arg parsing raises, tripping the outer handler.

        weekly_retrain wraps its whole body in one try/except, so any failure
        inside converges on the same return. Argument parsing is simply the
        earliest reachable point and needs no knowledge of the module's internals.
        """
        r = Mock()
        r.args.get.side_effect = RuntimeError('retrain blew up')
        return r

    def test_total_failure_returns_500_not_200(self):
        mod = _load('weekly_retrain')
        body, status = mod.weekly_retrain(self._exploding_request())
        assert status == 500, (
            'a retrain that died must not report success — nothing else in the '
            'system watches model age'
        )
        assert body['status'] == 'error'

    def test_a_broken_alert_channel_is_itself_logged(self):
        """The failure alert was wrapped in `except Exception: pass`."""
        mod = _load('weekly_retrain')
        with patch.object(mod, 'send_slack_notification', side_effect=RuntimeError('webhook 404')), \
             patch.object(mod.logger, 'error') as log_error:
            _, status = mod.weekly_retrain(self._exploding_request())
        assert status == 500
        assert any('failed to send failure alert' in str(c) for c in log_error.call_args_list), (
            'losing the only notification channel must leave a trace'
        )


class TestExpectedOutputsPlanner:

    def test_planning_errors_return_500(self):
        mod = _load('expected_outputs_planner')
        with patch.object(mod, '_get_bq_client', return_value=Mock()), \
             patch.object(mod, 'plan_date', side_effect=RuntimeError('merge failed')):
            body, status = mod.expected_outputs_planner(_request())
        assert status == 500, 'holes in the expected_outputs grid are never noticed downstream'
        assert body['errors']

    def test_a_clean_run_still_returns_200(self):
        """Guard against over-correcting the gate into a false alarm."""
        mod = _load('expected_outputs_planner')
        with patch.object(mod, '_get_bq_client', return_value=Mock()), \
             patch.object(mod, 'plan_date', return_value=7):
            body, status = mod.expected_outputs_planner(_request())
        assert status == 200
        assert not body['errors']
        assert body['rows_written'] > 0


class TestHaltStateWriter:

    def test_a_failed_sport_returns_500(self):
        mod = _load('halt_state_writer')
        with patch.object(mod, '_get_bq_client', return_value=Mock()), \
             patch.object(mod, 'evaluate_halt_state', side_effect=RuntimeError('query failed')):
            body, status = mod.halt_state_writer(_request(sport='nba'))
        assert status == 500, (
            'a missing halt_state row sends exporters down resolve_halt_state(), '
            'whose fail-closed branch decides publishing'
        )
        assert 'error' in body['results']['nba']

    def test_a_clean_run_still_returns_200(self):
        mod = _load('halt_state_writer')
        decision = {'halt_active': False, 'halt_reason': None, 'halt_metrics': {}}
        with patch.object(mod, '_get_bq_client', return_value=Mock()), \
             patch.object(mod, 'evaluate_halt_state', return_value=decision), \
             patch.object(mod, '_last_halt_state', return_value=None), \
             patch.object(mod, '_resolve_halt_since', return_value=None), \
             patch.object(mod, 'write_halt_state'), \
             patch.object(mod, 'maybe_alert_on_change'):
            body, status = mod.halt_state_writer(_request(sport='nba'))
        assert status == 200
        assert 'error' not in body['results']['nba']

    def test_the_docstring_promise_is_kept(self):
        """It promised a 500 for years while having exactly one return, a 200."""
        mod = _load('halt_state_writer')
        assert '500 on unrecoverable error' in mod.halt_state_writer.__doc__
