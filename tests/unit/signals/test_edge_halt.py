"""Tests for the edge degeneracy guard's state machine and fallback chain.

Three generations of this code have failed in three different ways, and every
test below pins one of them:

  Session 515   halted on 865 of 865 prediction-days and could never release.
  2026-08-19    fixed that, but calibrated on a fleet-composition artifact,
                released only via an asymmetric bar (a false halt would not
                have cleared for 63 days), and failed OPEN on a query error.
  2026-08-21    demoted to a degeneracy guard with a symmetric release, a
                bounded automatic lifetime, and a fail-closed fallback chain.
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from shared.config import edge_halt as eh


# Representative values. HEALTHY is the low end of what production has actually
# read on the warm-up basis (min 0.871 / 6.72% over 1,663 days); DEGENERATE is
# what "predictions stopped disagreeing with the line" looks like.
HEALTHY = (0.9, 7.0)
DEGENERATE = (0.1, 0.05)


def row(day, edge_med, pct_e3, days_sampled=7, models_7d=5.0):
    return SimpleNamespace(
        game_date=dt.date(2026, 1, 1) + dt.timedelta(days=day),
        edge_med_7d=edge_med, pct_e3_7d=pct_e3,
        days_sampled=days_sampled, models_7d=models_7d,
    )


def series(specs):
    return [row(i, e, p) for i, (e, p) in enumerate(specs)]


class TestHaltCondition:
    def test_healthy_market_does_not_halt(self):
        assert not eh.evaluate_halt_state(series([HEALTHY] * 30))['halt_active']

    def test_five_season_floors_do_not_halt(self):
        """The tightest values ever observed on either basis, day after day.

        production warm-up basis: 0.871 / 6.72%   (1,663 days)
        fixed procedure wf_sim:   0.656 / 0.65%   (563 days)
        """
        for floor in [(0.871, 6.72), (0.656, 0.65)]:
            assert not eh.evaluate_halt_state(series([floor] * 60))['halt_active'], floor

    def test_degenerate_predictions_halt(self):
        assert eh.evaluate_halt_state(series([DEGENERATE] * 10))['halt_active']

    def test_requires_both_conditions(self):
        """The conjunction is load-bearing. pct_e3 is what keeps the system live
        when the median dips — it is not an independent collapse detector."""
        low_median_only = eh.evaluate_halt_state(series([(0.2, 7.0)] * 20))
        assert not low_median_only['halt_active']
        low_pct_only = eh.evaluate_halt_state(series([(0.9, 0.05)] * 20))
        assert not low_pct_only['halt_active']

    def test_boundary_is_strict_less_than(self):
        at_threshold = series([(eh.HALT_EDGE_MEDIAN, eh.HALT_PCT_EDGE_3PLUS)] * 10)
        assert not eh.evaluate_halt_state(at_threshold)['halt_active']


class TestRelease:
    def test_release_is_reachable(self):
        s = series([DEGENERATE] * 5 + [HEALTHY] * eh.RELEASE_CONSECUTIVE_DAYS)
        assert not eh.evaluate_halt_state(s)['halt_active']

    def test_release_needs_full_streak(self):
        s = series([DEGENERATE] * 5 + [HEALTHY] * (eh.RELEASE_CONSECUTIVE_DAYS - 1))
        assert eh.evaluate_halt_state(s)['halt_active']

    def test_release_is_symmetric_either_condition_suffices(self):
        """The halt needs BOTH conditions, so the release needs only ONE.

        The 2026-08-19 version halted below 1.4 but released only at >= 1.6 for
        three days on the median alone — a false halt on 2026-02-15 would not
        have cleared for 63 days, i.e. through season end.
        """
        rel_days = eh.RELEASE_CONSECUTIVE_DAYS
        median_only = series([DEGENERATE] * 5
                             + [(eh.RELEASE_EDGE_MEDIAN, 0.0)] * rel_days)
        assert not eh.evaluate_halt_state(median_only)['halt_active']
        pct_only = series([DEGENERATE] * 5
                          + [(0.0, eh.RELEASE_PCT_EDGE_3PLUS)] * rel_days)
        assert not eh.evaluate_halt_state(pct_only)['halt_active']

    def test_streak_resets_on_a_bad_day(self):
        s = series([DEGENERATE] * 5
                   + [HEALTHY] * (eh.RELEASE_CONSECUTIVE_DAYS - 1)
                   + [DEGENERATE]
                   + [HEALTHY] * (eh.RELEASE_CONSECUTIVE_DAYS - 1))
        assert eh.evaluate_halt_state(s)['halt_active']

    def test_band_holds_state_in_both_directions(self):
        mid_e = (eh.HALT_EDGE_MEDIAN + eh.RELEASE_EDGE_MEDIAN) / 2
        mid_p = (eh.HALT_PCT_EDGE_3PLUS + eh.RELEASE_PCT_EDGE_3PLUS) / 2
        assert eh.evaluate_halt_state(series([(mid_e, mid_p)] * 20))['halt_active'] is False
        held = series([DEGENERATE] * 3 + [(mid_e, mid_p)] * 5)
        assert eh.evaluate_halt_state(held)['halt_active'] is True


class TestBoundedLifetime:
    def test_halt_self_releases_after_max_days(self):
        """A false positive must cost weeks, not a season. Permanence requires a
        human writing a halt_overrides row."""
        s = series([DEGENERATE] * (eh.MAX_HALT_DAYS + 3))
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is False
        assert out['lifetime_expired'] is True

    def test_halt_holds_until_the_lifetime_is_reached(self):
        s = series([DEGENERATE] * eh.MAX_HALT_DAYS)
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is True
        assert out['lifetime_expired'] is False

    def test_lifetime_counts_calendar_days_not_evaluable_days(self):
        """Thin days still age the halt — otherwise an all-star break could
        stall the clock and extend a false halt indefinitely."""
        s = ([row(i, *DEGENERATE) for i in range(2)]
             + [row(2 + i, None, None, days_sampled=0) for i in range(eh.MAX_HALT_DAYS)]
             + [row(2 + eh.MAX_HALT_DAYS, *DEGENERATE)])
        assert eh.evaluate_halt_state(s)['lifetime_expired'] is True


class TestThinData:
    def test_below_min_days_is_not_evaluated(self):
        s = [row(i, *DEGENERATE, days_sampled=eh.MIN_DAYS_SAMPLED - 1) for i in range(10)]
        out = eh.evaluate_halt_state(s)
        assert not out['halt_active']
        assert out['days_evaluated'] == 0

    def test_thin_days_do_not_advance_release_streak(self):
        s = (series([DEGENERATE] * 5)
             + [row(20 + i, *HEALTHY, days_sampled=1) for i in range(5)])
        assert eh.evaluate_halt_state(s)['halt_active']

    def test_null_median_skipped(self):
        s = series([HEALTHY] * 5)
        s.insert(2, row(99, None, None))
        assert not eh.evaluate_halt_state(s)['halt_active']

    def test_empty_series(self):
        out = eh.evaluate_halt_state([])
        assert out['halt_active'] is False and out['days_sampled'] == 0


class TestReporting:
    def test_days_sampled_describes_the_target_date(self):
        """Defect (e): this used to report the last EVALUATED row, so a thin
        target day inherited an older day's count and halt_state_writer's
        MIN_DAYS_SAMPLED guard could never reject it."""
        s = series([HEALTHY] * 5) + [row(9, None, None, days_sampled=1)]
        out = eh.evaluate_halt_state(s)
        assert out['days_sampled'] == 1
        assert out['days_evaluated'] == 5

    def test_reason_populated_only_when_halted(self):
        assert eh.evaluate_halt_state(series([DEGENERATE] * 5))['reason']
        assert eh.evaluate_halt_state(series([HEALTHY] * 5))['reason'] == ''

    def test_halt_started_tracks_onset(self):
        s = series([HEALTHY] * 4 + [DEGENERATE] * 5)
        assert eh.evaluate_halt_state(s)['halt_started'] == dt.date(2026, 1, 5)

    def test_target_row_values_reported(self):
        out = eh.evaluate_halt_state(series([(0.9, 7.0), (1.1, 9.0)]))
        assert out['edge_med_7d'] == pytest.approx(1.1)
        assert out['pct_e3_7d'] == pytest.approx(9.0)

    def test_healthy_result_is_not_an_error(self):
        assert eh.evaluate_halt_state(series([HEALTHY] * 5))['error'] is False
        assert eh.evaluate_halt_state(series([HEALTHY] * 5))['halt_source'] == 'computed'


class TestThresholds:
    def test_release_above_halt(self):
        assert eh.RELEASE_EDGE_MEDIAN > eh.HALT_EDGE_MEDIAN
        assert eh.RELEASE_PCT_EDGE_3PLUS > eh.HALT_PCT_EDGE_3PLUS

    def test_thresholds_sit_below_every_observed_floor(self):
        """Placed off five-season floors with margin, on both bases. The fixed
        procedure floor (0.656 / 0.65%) is the binding one."""
        assert eh.HALT_EDGE_MEDIAN < 0.656 * 0.75
        assert eh.HALT_PCT_EDGE_3PLUS < 0.65 * 0.75

    def test_lookback_spans_the_off_season(self):
        """Defect (f): 120 days was shorter than the Apr -> Oct gap, so any
        end-of-season halt was forgotten by the next opener."""
        assert eh.LOOKBACK_DAYS > 190


class TestSeasonScoping:
    def test_replay_is_clamped_to_the_current_season(self):
        assert eh.series_start_for(dt.date(2027, 3, 1)) == dt.date(2026, 10, 1)

    def test_lookback_binds_late_in_a_long_season(self):
        target = dt.date(2027, 6, 1)
        assert eh.series_start_for(target) == target - dt.timedelta(days=eh.LOOKBACK_DAYS)

    def test_season_start_boundary(self):
        assert eh.season_start_for(dt.date(2026, 10, 1)) == dt.date(2026, 10, 1)
        assert eh.season_start_for(dt.date(2026, 9, 30)) == dt.date(2025, 10, 1)


class _FailingClient:
    def query(self, *a, **k):
        raise RuntimeError('bigquery unavailable')


class _ScriptedClient:
    """Fails the edge query, then answers the halt_state fallback lookup."""

    def __init__(self, fallback_rows):
        self.fallback_rows = fallback_rows
        self.calls = 0

    def query(self, sql, job_config=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('edge query failed')
        rows = self.fallback_rows
        return SimpleNamespace(result=lambda *a, **k: rows)


class TestFailClosed:
    def test_query_failure_returns_an_error_sentinel_not_none(self):
        """Defect (c): a bare None was read as "not halted" by two of the three
        callers, so a transient failure during a real halt published picks."""
        out = eh.query_halt_state(_FailingClient(), dt.date(2026, 3, 1))
        assert out['error'] is True
        assert out['halt_active'] is None

    def test_resolve_falls_back_to_the_last_halt_state_row(self):
        client = _ScriptedClient([SimpleNamespace(
            effective_date=dt.date(2026, 2, 28), halt_active=True, halt_reason='manual')])
        out = eh.resolve_halt_state(client, dt.date(2026, 3, 1))
        assert out['halt_active'] is True
        assert out['halt_source'] == 'halt_state_fallback'
        assert out['reason']

    def test_fallback_carries_a_not_halted_row_forward_too(self):
        client = _ScriptedClient([SimpleNamespace(
            effective_date=dt.date(2026, 2, 28), halt_active=False, halt_reason=None)])
        out = eh.resolve_halt_state(client, dt.date(2026, 3, 1))
        assert out['halt_active'] is False
        assert out['halt_source'] == 'halt_state_fallback'

    def test_no_fallback_available_fails_closed(self):
        out = eh.resolve_halt_state(_FailingClient(), dt.date(2026, 3, 1))
        assert out['halt_active'] is True
        assert out['halt_source'] == 'fail_closed'

    def test_healthy_path_does_not_consult_the_fallback(self):
        rows = series([HEALTHY] * 5)

        class Ok:
            calls = 0

            def query(self, sql, job_config=None):
                Ok.calls += 1
                return SimpleNamespace(result=lambda *a, **k: rows)

        client = Ok()
        out = eh.resolve_halt_state(client, dt.date(2026, 3, 1))
        assert out['halt_active'] is False and Ok.calls == 1


class TestQuery:
    def test_sql_is_parameterized_and_bounded(self):
        sql = eh.build_daily_edge_query()
        assert '@target_date' in sql and '@series_start' in sql
        # Partition/date bound present so this never full-scans.
        assert 'game_date >=' in sql

    def test_sql_applies_the_warm_up_quarantine(self):
        """Defect (a): without this, ~20 experiment models that lived 1-5 days
        moved the circuit breaker and produced the February 2026 halt."""
        sql = eh.build_daily_edge_query()
        assert f'h.prior_days >= {eh.MIN_MODEL_HISTORY_DAYS}' in sql
        assert f'p.n_rows >= {eh.MIN_MODEL_ROWS_PER_DAY}' in sql

    def test_sql_aggregates_per_model_then_across_models(self):
        """Median across models, not a mean over raw rows — the fleet ranged
        from 2.3 to 16.8 models/player-game and a row-mean tracks that."""
        sql = eh.build_daily_edge_query()
        assert 'GROUP BY game_date, system_id' in sql
        assert 'APPROX_QUANTILES(model_edge_med, 100)[OFFSET(50)]' in sql


class TestLifetimeLatch:
    def test_expired_halt_does_not_immediately_re_fire(self):
        """Without the latch the machine re-halts the next day on the same
        degenerate stretch and the lifetime cap accomplishes nothing."""
        s = series([DEGENERATE] * (eh.MAX_HALT_DAYS + 30))
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is False
        assert out['lifetime_spent'] is True

    def test_guard_re_arms_after_a_genuine_recovery(self):
        s = series([DEGENERATE] * (eh.MAX_HALT_DAYS + 2)
                   + [HEALTHY] * 5
                   + [DEGENERATE] * 3)
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is True
        assert out['lifetime_spent'] is False
