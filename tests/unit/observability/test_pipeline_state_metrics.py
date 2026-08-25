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

    @staticmethod
    def _row(sport, n):
        r = Mock()
        r.sport = sport
        r.failed_count = n
        return r

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
            job.result.return_value = iter([self._row('nba', 9)])
            return job

        bq = Mock()
        bq.query.side_effect = fake_query
        assert mod.count_failed_rows(bq)['nba'] == 9

        sql = captured['sql']
        assert "status = 'FAILED'" in sql, 'must count the terminal state'
        assert 'LIMIT' not in sql.upper(), (
            'a LIMITed count saturates and stops measuring severity'
        )

    def test_sport_with_no_failures_still_reports_zero(self):
        """A healthy sport must publish 0, not vanish.

        If a recovered sport simply stopped appearing, "recovered" and "stopped
        being measured" would be the same observation — the exact confusion this
        change exists to remove.
        """
        mod = _load('gap_detector')
        job = Mock()
        job.result.return_value = iter([self._row('mlb', 74)])
        bq = Mock()
        bq.query.return_value = job

        counts = mod.count_failed_rows(bq)
        assert counts == {'mlb': 74, 'nba': 0}

    def test_query_failure_returns_none_not_zero(self):
        """0.0 for an unmeasured value reads as a healthy pipeline."""
        mod = _load('gap_detector')
        bq = Mock()
        bq.query.side_effect = RuntimeError('bigquery unavailable')
        assert mod.count_failed_rows(bq) is None

    def test_failed_count_is_emitted_per_sport(self):
        """One time series per sport, so an NBA threshold is reachable.

        MLB is a halted info-only product carrying a permanent backlog (74 rows
        on 2026-08-24). Summed into one number it would hold any NBA-relevant
        threshold permanently tripped.
        """
        mod = _load('gap_detector')
        with patch.object(mod, '_get_bq'), \
             patch.object(mod, 'select_overdue_rows', return_value=[]), \
             patch.object(mod, 'count_failed_rows', return_value={'nba': 0, 'mlb': 74}), \
             patch('shared.observability.metrics.emit_metric') as emit:
            summary, status = mod.gap_detector(_request())

        assert status == 200
        assert summary['failed_rows_14d'] == {'nba': 0, 'mlb': 74}

        by_sport = {
            c.kwargs['labels']['sport']: c.kwargs['value']
            for c in emit.call_args_list
            if c.kwargs.get('metric_name') == 'failed_count'
        }
        assert by_sport == {'nba': 0.0, 'mlb': 74.0}

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
             patch.object(mod, 'count_failed_rows', return_value={'nba': 3}), \
             patch('shared.observability.metrics.emit_metric',
                   side_effect=RuntimeError('monitoring down')):
            _, status = mod.gap_detector(_request())
        assert status == 200


class TestPlanningHorizon:
    """Planner liveness measured as a level, not an absence.

    Cloud Monitoring caps conditionAbsent at 23h30m and the planner's cadence is
    24h, so every legal absence window is shorter than the healthy gap between
    heartbeats and would fire ~1h a day, every day.
    """

    def test_horizon_is_emitted(self):
        mod = _load('gap_detector')
        with patch.object(mod, '_get_bq'), \
             patch.object(mod, 'select_overdue_rows', return_value=[]), \
             patch.object(mod, 'count_failed_rows', return_value={'nba': 0}), \
             patch.object(mod, 'planning_horizon_days', return_value=14), \
             patch('shared.observability.metrics.emit_metric') as emit:
            summary, status = mod.gap_detector(_request())

        assert status == 200
        assert summary['planning_horizon_days'] == 14
        assert _emitted(emit.call_args_list).get('planning_horizon_days') == 14.0

    def test_horizon_failure_emits_nothing(self):
        """Negative test: an unmeasured horizon must not publish a number.

        Publishing 0 would read as "planner catastrophically behind" and page on
        a BigQuery blip; publishing 14 would read as healthy. Neither is honest.
        """
        mod = _load('gap_detector')
        with patch.object(mod, '_get_bq'), \
             patch.object(mod, 'select_overdue_rows', return_value=[]), \
             patch.object(mod, 'count_failed_rows', return_value={'nba': 0}), \
             patch.object(mod, 'planning_horizon_days', return_value=None), \
             patch('shared.observability.metrics.emit_metric') as emit:
            _, status = mod.gap_detector(_request())

        assert status == 200
        assert 'planning_horizon_days' not in _emitted(emit.call_args_list)

    def test_query_failure_returns_none(self):
        mod = _load('gap_detector')
        bq = Mock()
        bq.query.side_effect = RuntimeError('bigquery unavailable')
        assert mod.planning_horizon_days(bq) is None

    def test_empty_table_returns_none_not_zero(self):
        """MAX() over an empty table is NULL; that is 'unknown', not 'today'."""
        mod = _load('gap_detector')
        job = Mock()
        job.result.return_value = iter([Mock(horizon_days=None)])
        bq = Mock()
        bq.query.return_value = job
        assert mod.planning_horizon_days(bq) is None


class TestEmitterDependencyIsDeclared:
    """A CF that emits metrics must ship the library that emits them.

    `_get_monitoring_client` swallows ImportError and returns None, so
    `emit_metric` degrades to a no-op with a single WARNING line. That is the
    correct behaviour for a telemetry path -- it must never crash the caller --
    but it means a missing `google-cloud-monitoring` in requirements.txt is
    invisible: the function runs, reports success, and emits nothing.

    Measured 2026-08-24: expected_outputs_planner had emitted metrics for
    exactly zero of its lifetime for this reason. It reported 420 rows written
    and no metric existed. Nothing anywhere would have caught that, because the
    only symptom is the absence of data.

    No allowlist. If a function calls emit_metric it declares the dependency.
    """

    CF_ROOT = REPO / 'orchestration' / 'cloud_functions'

    # Every public entry point of shared.observability.metrics. emit_phase_completion
    # is on this list because it calls emit_metric internally -- matching only the
    # literal 'emit_metric' misses it, which is how the grading CF's phase_completion
    # emission (the signal grading-low-coverage-alert.yaml filters on) went missing.
    EMITTERS = ('emit_metric', 'emit_phase_completion')

    @staticmethod
    def _strip_comments(src: str) -> str:
        """Drop `#` comment tails so a mention in prose is not read as a call.

        The first version of this check matched the substring anywhere and hit a
        comment in grading/main.py. It reached the right verdict by luck; luck is
        not a test.
        """
        out = []
        for line in src.splitlines():
            hash_at = line.find('#')
            out.append(line if hash_at == -1 else line[:hash_at])
        return '\n'.join(out)

    def _emitting_functions(self):
        for main in sorted(self.CF_ROOT.glob('*/main.py')):
            src = self._strip_comments(main.read_text())
            if any(f'{e}(' in src for e in self.EMITTERS):
                yield main.parent

    def test_at_least_one_emitting_function_is_discovered(self):
        """Guard the guard: a broken glob would make this suite vacuously pass."""
        assert list(self._emitting_functions()), (
            'discovered no metric-emitting Cloud Functions -- the check itself '
            'is broken, not the codebase'
        )

    def test_every_emitting_function_declares_google_cloud_monitoring(self):
        missing = []
        for d in self._emitting_functions():
            req = d / 'requirements.txt'
            if not req.exists() or 'google-cloud-monitoring' not in req.read_text():
                missing.append(d.name)
        assert not missing, (
            'these Cloud Functions call emit_metric but do not declare '
            f'google-cloud-monitoring, so every metric they emit is silently '
            f'dropped: {missing}'
        )


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
