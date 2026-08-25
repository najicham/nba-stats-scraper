"""The safety net must be able to see its own terminal states.

Two blind spots at the root of the pipeline-state design, both found on
2026-08-24 by reading `nba_orchestration.expected_outputs` rather than the code.

  gap_detector      `overdue_count` counts EXPECTED + DEGRADED only. When a row
                    exhausts MAX_BACKFILL_ATTEMPTS and flips to FAILED it LEAVES
                    that set, so the metric goes DOWN. Giving up looked like
                    recovery. The module docstring said "alert fires"; no alert
                    watched FAILED at all, and 8 consecutive days of FAILED MLB
                    rows (2026-08-17..24) paged nobody.

  planner           emitted no telemetry whatsoever. If it stops producing rows
                    there are no EXPECTED rows, so `overdue_count` is 0 and the
                    expected-outputs-overdue alert reads healthy. Total failure
                    was indistinguishable from a quiet day.

Both fixes are metrics, so the assertions are on what was emitted — a metric
that is silently not emitted is the whole bug class being fixed here, and the
tests below therefore assert absence as carefully as they assert presence.
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


def _emitted(calls):
    """{metric_name: value} from emit_metric call args, kwargs-or-positional."""
    out = {}
    for c in calls:
        if c.kwargs.get('metric_name') is not None:
            out[c.kwargs['metric_name']] = c.kwargs.get('value')
        elif c.args:
            out[c.args[0]] = c.args[1] if len(c.args) > 1 else None
    return out


# ---------------------------------------------------------------------------


class TestGapDetectorFailedCount:

    def test_failed_query_is_uncapped_and_filters_terminal_state(self):
        """The severity gauge must not inherit select_overdue_rows' LIMIT.

        overdue_count is len() of a LIMITed query, so it saturates at
        MAX_PUBLISHES_PER_RUN and cannot express "50 broken" vs "500 broken".
        """
        mod = _load('gap_detector')
        captured = {}

        def fake_query(sql, job_config=None):
            captured['sql'] = sql
            job = Mock()
            job.result.return_value = iter([Mock(failed_count=9)])
            return job

        bq = Mock()
        bq.query.side_effect = fake_query
        assert mod.count_failed_rows(bq) == 9

        sql = captured['sql']
        assert "status = 'FAILED'" in sql, 'must count the terminal state'
        assert 'LIMIT' not in sql.upper(), (
            'a LIMITed count saturates and stops measuring severity'
        )

    def test_query_failure_returns_none_not_zero(self):
        """0.0 for an unmeasured value reads as a healthy pipeline."""
        mod = _load('gap_detector')
        bq = Mock()
        bq.query.side_effect = RuntimeError('bigquery unavailable')
        assert mod.count_failed_rows(bq) is None

    def test_failed_count_is_emitted_when_measured(self):
        mod = _load('gap_detector')
        with patch.object(mod, '_get_bq'), \
             patch.object(mod, 'select_overdue_rows', return_value=[]), \
             patch.object(mod, 'count_failed_rows', return_value=12), \
             patch('shared.observability.metrics.emit_metric') as emit:
            summary, status = mod.gap_detector(_request())

        assert status == 200
        assert summary['failed_rows_14d'] == 12
        assert _emitted(emit.call_args_list).get('failed_count') == 12.0

    def test_failed_count_is_NOT_emitted_when_unmeasured(self):
        """Negative test: a broken count must publish nothing, not 0.0.

        This is the assertion that distinguishes the fix from the bug it
        replaces — emitting 0.0 here would recreate "giving up looks healthy"
        one layer down.
        """
        mod = _load('gap_detector')
        with patch.object(mod, '_get_bq'), \
             patch.object(mod, 'select_overdue_rows', return_value=[]), \
             patch.object(mod, 'count_failed_rows', return_value=None), \
             patch('shared.observability.metrics.emit_metric') as emit:
            summary, status = mod.gap_detector(_request())

        emitted = _emitted(emit.call_args_list)
        assert status == 200, 'telemetry gaps must stay fail-open'
        assert 'failed_count' not in emitted, (
            'an unmeasured failure count must be absent, never 0.0'
        )
        assert 'overdue_count' in emitted, 'the other metric must still publish'

    def test_telemetry_failure_does_not_crash_the_cf(self):
        """Negative test: emission is best-effort, escalation is the real job."""
        mod = _load('gap_detector')
        with patch.object(mod, '_get_bq'), \
             patch.object(mod, 'select_overdue_rows', return_value=[]), \
             patch.object(mod, 'count_failed_rows', return_value=3), \
             patch('shared.observability.metrics.emit_metric',
                   side_effect=RuntimeError('monitoring down')):
            _, status = mod.gap_detector(_request())
        assert status == 200


class TestPlannerHeartbeat:

    def test_heartbeat_emitted_on_clean_run(self):
        mod = _load('expected_outputs_planner')
        with patch.object(mod, '_get_bq_client', return_value=Mock()), \
             patch.object(mod, 'plan_date', return_value=7), \
             patch('shared.observability.metrics.emit_metric') as emit:
            _, status = mod.expected_outputs_planner(_request())

        assert status == 200
        assert 'planner_rows_written' in _emitted(emit.call_args_list)

    def test_heartbeat_emitted_on_partial_failure_too(self):
        """Ran-and-failed and did-not-run are different facts.

        The absence alert keys on this metric, so a 500 must still emit —
        otherwise a partially-failing planner would additionally trip the
        "planner is dead" alert and conflate two distinct incidents.
        """
        mod = _load('expected_outputs_planner')
        with patch.object(mod, '_get_bq_client', return_value=Mock()), \
             patch.object(mod, 'plan_date', side_effect=RuntimeError('merge failed')), \
             patch('shared.observability.metrics.emit_metric') as emit:
            _, status = mod.expected_outputs_planner(_request())

        assert status == 500
        assert 'planner_rows_written' in _emitted(emit.call_args_list), (
            'a planner that ran and failed must not look like a planner that '
            'never ran'
        )

    def test_monitoring_outage_does_not_break_planning(self):
        """Negative test: the planner's job is the grid, not the telemetry."""
        mod = _load('expected_outputs_planner')
        with patch.object(mod, '_get_bq_client', return_value=Mock()), \
             patch.object(mod, 'plan_date', return_value=7), \
             patch('shared.observability.metrics.emit_metric',
                   side_effect=RuntimeError('monitoring down')):
            _, status = mod.expected_outputs_planner(_request())
        assert status == 200
