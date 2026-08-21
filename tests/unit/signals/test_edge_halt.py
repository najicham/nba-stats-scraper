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
        # Days stay inside MAX_HALT_DAYS so this measures the streak rule, not
        # the lifetime cap (which now ages through thin days too).
        s = (series([DEGENERATE] * 5)
             + [row(5 + i, *HEALTHY, days_sampled=1) for i in range(5)])
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
            effective_date=dt.date(2026, 2, 28), halt_active=True,
            halt_reason='manual', halt_since=dt.date(2026, 2, 28))])
        out = eh.resolve_halt_state(client, dt.date(2026, 3, 1))
        assert out['halt_active'] is True
        assert out['halt_source'] == 'halt_state_fallback'
        assert out['reason']

    def test_fallback_carries_a_not_halted_row_forward_too(self):
        client = _ScriptedClient([SimpleNamespace(
            effective_date=dt.date(2026, 2, 28), halt_active=False,
            halt_reason=None, halt_since=None)])
        out = eh.resolve_halt_state(client, dt.date(2026, 3, 1))
        assert out['halt_active'] is False
        assert out['halt_source'] == 'halt_state_fallback'

    def test_carried_forward_halt_still_expires(self):
        """The MAX_HALT_DAYS lifetime lives in evaluate_halt_state, which the
        fallback path never reaches. Without enforcing it here, a carried
        halt is a halt with no expiry — the permanent trap this rewrite
        exists to remove, reintroduced through the back door."""
        started = dt.date(2026, 3, 1)
        target = started + dt.timedelta(days=eh.MAX_HALT_DAYS)
        client = _ScriptedClient([SimpleNamespace(
            effective_date=target - dt.timedelta(days=1), halt_active=True,
            halt_reason='edge_collapse', halt_since=started)])
        out = eh.resolve_halt_state(client, target)
        assert out['halt_active'] is False
        assert out['lifetime_expired'] is True

    def test_fallback_query_excludes_fallback_derived_rows(self):
        """halt_state_writer re-writes this table from resolve_halt_state's own
        output. Without the source filter, every row is <= 1 day old even when
        the last real computation was weeks ago, and FALLBACK_MAX_AGE_DAYS
        never engages."""
        captured = []

        class Capture:
            def query(self, sql, job_config=None):
                captured.append(sql)
                return SimpleNamespace(result=lambda *a, **k: [])

        eh._last_known_halt_row(Capture(), dt.date(2026, 3, 1), 'nba',
                                'nba-props-platform', None)
        assert len(captured) == 1
        sql = captured[0]
        # The filter must be in the SQL the client actually executes — not
        # merely mentioned in a docstring or comment.
        assert 'edge_halt_source' in sql
        assert "'halt_state_fallback', 'fail_closed', 'error'" in sql

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


# --- Reviewer 3 additions: state-machine edge cases -------------------------

MID_BAND = ((eh.HALT_EDGE_MEDIAN + eh.RELEASE_EDGE_MEDIAN) / 2,
            (eh.HALT_PCT_EDGE_3PLUS + eh.RELEASE_PCT_EDGE_3PLUS) / 2)


class TestLatchEdgeCases:
    def test_dead_band_does_not_rearm_a_spent_latch(self):
        """Dead-band days are neither release nor halt: the latch must stay set
        through them, so a stretch that hovers between the bands after a spent
        lifetime cannot silently re-halt."""
        s = series([DEGENERATE] * (eh.MAX_HALT_DAYS + 2)
                   + [MID_BAND] * 5
                   + [DEGENERATE] * 5)
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is False
        assert out['lifetime_spent'] is True

    def test_single_release_day_does_not_rearm_a_spent_latch(self):
        """Re-arm requires the same streak a normal release does. With a single
        day, a degenerate stretch oscillating around the band re-arms on one
        noisy day and starts a fresh MAX_HALT_DAYS halt, repeatedly — spending
        far more than the advertised two weeks."""
        s = series([DEGENERATE] * (eh.MAX_HALT_DAYS + 2)
                   + [HEALTHY]
                   + [DEGENERATE] * 2)
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is False
        assert out['lifetime_spent'] is True

    def test_sustained_recovery_rearms_the_latch(self):
        s = series([DEGENERATE] * (eh.MAX_HALT_DAYS + 2)
                   + [HEALTHY] * eh.RELEASE_CONSECUTIVE_DAYS
                   + [DEGENERATE] * 2)
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is True
        assert out['lifetime_spent'] is False

    def test_normal_streak_release_leaves_latch_unset(self):
        """A halt that releases via the 2-day streak never touched the latch,
        so the guard can fire again on the next episode."""
        s = series([DEGENERATE] * 5
                   + [HEALTHY] * eh.RELEASE_CONSECUTIVE_DAYS
                   + [DEGENERATE] * 3)
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is True
        assert out['lifetime_spent'] is False

    def test_lifetime_expired_clears_on_a_sustained_recovery(self):
        """halt_state_writer exports this as `edge_halt_lifetime_expired`. If it
        stayed True until the next halt began, alerting on it would fire
        indefinitely on a months-old event."""
        s = series([DEGENERATE] * (eh.MAX_HALT_DAYS + 2) + [HEALTHY] * 10)
        out = eh.evaluate_halt_state(s)
        assert out['lifetime_spent'] is False
        assert out['lifetime_expired'] is False


class TestThinInteractions:
    def test_halted_with_null_target_metrics_does_not_crash(self):
        """A halt carried into a thin stretch: the target row has NULL 7d
        metrics (7+ dataless days). The reason string must not blow up
        formatting None — a crash here bypasses the fail-closed chain because
        evaluate_halt_state runs OUTSIDE query_halt_state's try/except."""
        s = series([DEGENERATE] * 5) + [row(5, None, None, days_sampled=0)]
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is True
        assert out['edge_med_7d'] is None
        assert out['days_sampled'] == 0

    def test_release_streak_survives_an_interleaved_thin_day(self):
        """'2 consecutive EVALUABLE days': a thin day neither credits nor
        resets the streak, so healthy-thin-healthy releases."""
        s = (series([DEGENERATE] * 5)
             + [row(5, *HEALTHY)]
             + [row(6, None, None, days_sampled=0)]
             + [row(7, *HEALTHY)])
        assert eh.evaluate_halt_state(s)['halt_active'] is False

    def test_lifetime_expiry_fires_during_a_no_data_stretch(self):
        """The lifetime is a calendar-day promise. A halt that lapses during an
        all-star break or a pipeline gap must not stay live until games AND
        data both come back."""
        s = (series([DEGENERATE] * 5)
             + [row(5 + i, None, None, days_sampled=0)
                for i in range(eh.MAX_HALT_DAYS + 5)])
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is False
        assert out['lifetime_expired'] is True


class TestKeyParity:
    def test_error_state_carries_every_success_key(self):
        """halt_state_writer hard-indexes models_7d / halt_source /
        lifetime_expired; every branch must expose them."""
        ok = eh.evaluate_halt_state(series([HEALTHY] * 5))
        err = eh._error_state('x')
        assert set(ok) - set(err) == set()
        assert set(err) - set(ok) == {'error_detail'}  # only via .get()

    def test_fail_closed_state_carries_writer_keys(self):
        out = eh.resolve_halt_state(_FailingClient(), dt.date(2026, 3, 1))
        for k in ('models_7d', 'halt_source', 'lifetime_expired',
                  'days_sampled', 'halt_active', 'reason'):
            assert k in out, k


# --- Reviewer 9 additions: property simulation + untested transitions --------


class TestSecondEpisode:
    """The lifetime clock across episodes. Every lifetime test above uses a
    single halt episode, so nothing pinned that a SECOND halt gets its own
    fresh MAX_HALT_DAYS rather than inheriting the first episode's clock —
    the difference between a 14-day promise per episode and a guard that
    expires instantly forever after its first firing."""

    def test_second_halt_gets_a_fresh_lifetime_clock(self):
        rel = eh.RELEASE_CONSECUTIVE_DAYS
        s = series([DEGENERATE] * 5
                   + [HEALTHY] * rel
                   + [DEGENERATE] * (eh.MAX_HALT_DAYS - 1))
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is True
        assert out['lifetime_expired'] is False
        # ...and the onset reported is the SECOND episode's first day.
        assert out['halt_started'] == dt.date(2026, 1, 1) + dt.timedelta(days=5 + rel)

    def test_second_halt_expires_on_its_own_schedule(self):
        rel = eh.RELEASE_CONSECUTIVE_DAYS
        s = series([DEGENERATE] * 5
                   + [HEALTHY] * rel
                   + [DEGENERATE] * (eh.MAX_HALT_DAYS + 1))
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is False
        assert out['lifetime_expired'] is True

    def test_rearm_streak_survives_an_interleaved_thin_day(self):
        """Parity with the release streak rule: a thin day neither credits nor
        resets the RE-ARM streak, so healthy-thin-healthy after a spent
        lifetime re-arms the guard and the next degenerate stretch halts."""
        base = eh.MAX_HALT_DAYS + 2
        s = (series([DEGENERATE] * base)
             + [row(base, *HEALTHY)]
             + [row(base + 1, None, None, days_sampled=0)]
             + [row(base + 2, *HEALTHY)]
             + [row(base + 3, *DEGENERATE), row(base + 4, *DEGENERATE)])
        out = eh.evaluate_halt_state(s)
        assert out['lifetime_spent'] is False
        assert out['halt_active'] is True

    def test_recovery_landing_on_the_lifetime_boundary_still_releases(self):
        """Release streak day 2 coincides with the lifetime lapse. The lifetime
        check runs first, so the machine labels this an expiry rather than a
        streak release — an ordering choice, deliberately not pinned here.
        What must hold either way: the halt lifts and nothing crashes."""
        s = series([DEGENERATE] * (eh.MAX_HALT_DAYS - 1) + [HEALTHY] * 2)
        out = eh.evaluate_halt_state(s)
        assert out['halt_active'] is False


class TestPropertySimulation:
    """Randomized daily series against invariants that must hold for EVERY
    series. Example-based tests pin one transition each; interaction bugs (the
    f"{None:.3f}" crash lived at thin-days x halted) only fall out of walking
    the whole reachable state space. Seed is FIXED — this repo's CI (and the
    Cloud Build test gate) must be deterministic."""

    SEED = 20260821
    N_SERIES = 300
    MAX_LEN = 45

    EXPECTED_KEYS = {
        'error', 'halt_active', 'halt_source', 'edge_med_7d', 'pct_e3_7d',
        'models_7d', 'days_sampled', 'days_evaluated', 'halt_started',
        'carried_forward_from', 'release_streak', 'lifetime_expired',
        'lifetime_spent', 'reason',
    }

    @staticmethod
    def _random_rows(rng):
        n = rng.randint(1, TestPropertySimulation.MAX_LEN)
        rows, day = [], 0
        while len(rows) < n:
            r = rng.random()
            if r < 0.08:
                # Long no-data gap: all-star break / pipeline outage, long
                # enough to lap MAX_HALT_DAYS sometimes.
                for _ in range(rng.randint(5, eh.MAX_HALT_DAYS + 6)):
                    rows.append(row(day, None, None, days_sampled=0))
                    day += 1
                continue
            if r < 0.30:      # degenerate: both strictly below the halt bar
                e = rng.uniform(0.0, eh.HALT_EDGE_MEDIAN * 0.999)
                p = rng.uniform(0.0, eh.HALT_PCT_EDGE_3PLUS * 0.999)
            elif r < 0.50:    # healthy: at/above the release bar
                e = rng.uniform(eh.RELEASE_EDGE_MEDIAN, 3.0)
                p = rng.uniform(eh.RELEASE_PCT_EDGE_3PLUS, 25.0)
            elif r < 0.60:    # dead band on both metrics
                e = rng.uniform(eh.HALT_EDGE_MEDIAN, eh.RELEASE_EDGE_MEDIAN * 0.999)
                p = rng.uniform(eh.HALT_PCT_EDGE_3PLUS, eh.RELEASE_PCT_EDGE_3PLUS * 0.999)
            elif r < 0.70:    # one-sided: only one metric collapsed
                if rng.random() < 0.5:
                    e, p = rng.uniform(0.0, eh.HALT_EDGE_MEDIAN * 0.999), rng.uniform(eh.RELEASE_PCT_EDGE_3PLUS, 25.0)
                else:
                    e, p = rng.uniform(eh.RELEASE_EDGE_MEDIAN, 3.0), rng.uniform(0.0, eh.HALT_PCT_EDGE_3PLUS * 0.999)
            elif r < 0.80:    # exact boundary values
                e, p = rng.choice([
                    (eh.HALT_EDGE_MEDIAN, eh.HALT_PCT_EDGE_3PLUS),
                    (eh.RELEASE_EDGE_MEDIAN, 0.0),
                    (0.0, eh.RELEASE_PCT_EDGE_3PLUS),
                    (eh.HALT_EDGE_MEDIAN, 0.0),
                    (0.0, eh.HALT_PCT_EDGE_3PLUS),
                ])
            elif r < 0.90:    # NULL metrics on a full-width window
                e, p = None, None
            else:             # edge present, pct NULL (code defaults pct to 0.0)
                e, p = rng.uniform(0.0, 3.0), None
            days_sampled = rng.choice([0, 1, 2, 3, 4, 7, 7, 7, 7])
            models = rng.choice([None, 1.0, 2.9, 5.7])
            rows.append(SimpleNamespace(
                game_date=dt.date(2026, 1, 1) + dt.timedelta(days=day),
                edge_med_7d=e, pct_e3_7d=p,
                days_sampled=days_sampled, models_7d=models,
            ))
            day += 1
        return rows

    def _check_invariants(self, rows, out):
        assert set(out) == self.EXPECTED_KEYS
        assert out['error'] is False
        assert out['halt_source'] == 'computed'
        assert out['halt_active'] in (True, False)

        if out['halt_active']:
            # A live halt always knows when it started, started on a real
            # row, and has NEVER held longer than the calendar-day promise.
            assert out['halt_started'] is not None
            assert out['halt_started'] in {r.game_date for r in rows}
            held = (rows[-1].game_date - out['halt_started']).days
            assert 0 <= held < eh.MAX_HALT_DAYS
            assert out['lifetime_expired'] is False
            assert out['reason']  # includes the None-metrics 'n/a' case
        else:
            assert out['halt_started'] is None
            assert out['release_streak'] == 0
            assert out['reason'] == ''

        # The expiry flag is only ever raised by spending a lifetime.
        if out['lifetime_expired']:
            assert out['lifetime_spent'] is True

        # A completed streak releases and resets, so the reported streak is
        # always strictly below the release requirement.
        assert 0 <= out['release_streak'] < eh.RELEASE_CONSECUTIVE_DAYS

        # Independent re-derivation of what counts as an evaluable day.
        expected_eval = sum(
            1 for r in rows
            if int(r.days_sampled or 0) >= eh.MIN_DAYS_SAMPLED
            and r.edge_med_7d is not None)
        assert out['days_evaluated'] == expected_eval

        # Reporting describes the TARGET row (defect e), thin or not.
        if rows:
            assert out['days_sampled'] == int(rows[-1].days_sampled or 0)
            em = rows[-1].edge_med_7d
            assert out['edge_med_7d'] == (float(em) if em is not None else None)
        else:
            assert out['days_sampled'] == 0

    def test_invariants_hold_for_every_random_series_at_every_prefix(self):
        import random
        rng = random.Random(self.SEED)
        for _ in range(self.N_SERIES):
            rows = self._random_rows(rng)
            # Every prefix: the invariants must hold on every intermediate
            # day the writer could have been invoked, not just the last.
            for k in range(len(rows) + 1):
                out = eh.evaluate_halt_state(rows[:k])
                self._check_invariants(rows[:k], out)

    def test_evaluation_is_deterministic_and_does_not_mutate_rows(self):
        import copy
        import random
        rng = random.Random(self.SEED + 1)
        for _ in range(20):
            rows = self._random_rows(rng)
            frozen = copy.deepcopy(rows)
            first = eh.evaluate_halt_state(rows)
            second = eh.evaluate_halt_state(rows)
            assert first == second
            assert [vars(r) for r in rows] == [vars(r) for r in frozen]


class TestBigQueryClientContract:
    """The stub clients above implement `query(sql, job_config=...)` returning
    an object with `.result(timeout=...)`. Pin that shape against the REAL
    google-cloud-bigquery client (installed both here and in the Cloud Build
    test gate), so a library signature change breaks a test instead of
    silently diverging from the stubs."""

    def test_stub_shape_matches_real_client(self):
        import inspect
        from google.cloud import bigquery

        query_params = inspect.signature(bigquery.Client.query).parameters
        # edge_halt calls client.query(sql, job_config=...): SQL is the first
        # positional after self, job_config passed by keyword.
        assert list(query_params)[1] == 'query'
        assert 'job_config' in query_params

        result_params = inspect.signature(bigquery.job.QueryJob.result).parameters
        assert 'timeout' in result_params

        # The exact constructor calls edge_halt makes must build cleanly.
        cfg = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter('target_date', 'DATE', dt.date(2026, 3, 1)),
            bigquery.ScalarQueryParameter('max_age', 'INT64', 3),
            bigquery.ScalarQueryParameter('sport', 'STRING', 'nba'),
        ])
        assert len(cfg.query_parameters) == 3
