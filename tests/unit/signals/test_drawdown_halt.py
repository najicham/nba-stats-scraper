"""Tests for the drawdown circuit breaker and the pick-volume anomaly guard.

These are the guards that actually protect the season — `edge_halt` was demoted
to a degeneracy detector after it turned out to be anti-correlated with the only
collapse this system has experienced.

The invariants that matter most are the RELEASE ones. A drawdown halt freezes
the curve (no picks -> no results), so the metric can never recover on its own;
without a peak reset and a hard lifetime this guard is the permanent zero-pick
trap the edge-halt rewrite exists to have removed.
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from shared.config import drawdown_halt as dd


def day(i):
    return dt.date(2026, 1, 1) + dt.timedelta(days=i)


def pnl(i, wins, losses):
    return SimpleNamespace(game_date=day(i), wins=wins, losses=losses)


def flat(n, start=0):
    """Roughly break-even days that build graded volume without a big move."""
    return [pnl(start + i, 1, 1) for i in range(n)]


def vol(i, picks):
    return SimpleNamespace(game_date=day(i), picks=picks)


class TestDrawdownThresholds:
    def test_healthy_curve_does_not_halt(self):
        rows = [pnl(i, 3, 1) for i in range(30)]
        assert not dd.evaluate_drawdown(rows, day(31))['halt_active']

    def test_observed_healthy_max_does_not_halt(self):
        """2025-26's pre-collapse maximum drawdown was 3.64u over eight weeks."""
        rows = flat(20) + [pnl(20, 0, 3), pnl(21, 0, 1)]
        assert not dd.evaluate_drawdown(rows, day(22))['halt_active']

    def test_soft_threshold_halts(self):
        rows = flat(20) + [pnl(20, 0, 4), pnl(21, 0, 3)]
        out = dd.evaluate_drawdown(rows, day(22))
        assert out['halt_active'] is True
        assert out['dd_tier'] == 'soft'
        assert out['reason']

    def test_hard_threshold_reports_hard_tier(self):
        # Must land in ONE day: the halt fires on day 20 and blocks day 21, so
        # a two-day slide only ever reaches the soft tier. That is the guard
        # working — a slow bleed is soft, a single catastrophic slate is hard.
        rows = flat(20) + [pnl(20, 0, 12)]
        assert dd.evaluate_drawdown(rows, day(21))['dd_tier'] == 'hard'

    def test_a_slow_bleed_stays_soft(self):
        rows = flat(20) + [pnl(20, 0, 6), pnl(21, 0, 6)]
        assert dd.evaluate_drawdown(rows, day(22))['dd_tier'] == 'soft'

    def test_too_few_graded_picks_does_not_halt(self):
        rows = [pnl(0, 0, 8)]
        out = dd.evaluate_drawdown(rows, day(1))
        assert out['halt_active'] is False
        assert out['dd_graded_picks'] < dd.DD_MIN_GRADED

    def test_thresholds_sit_in_the_measured_gap(self):
        """Healthy seasons top out at 5.1-7.6u; no-edge seasons reach 11.6-14.8."""
        assert 3.64 < dd.DD_SOFT_THRESHOLD <= 7.6
        assert dd.DD_HARD_THRESHOLD > 7.6


class TestDrawdownRelease:
    def test_peak_resets_on_release_so_the_halt_cannot_re_fire(self):
        """THE critical property. A halt freezes the curve, so drawdown from the
        OLD peak stays above the threshold forever and the halt re-fires every
        morning. Without the reset this guard is a permanent trap."""
        rows = flat(20) + [pnl(20, 0, 7)]
        target = day(20) + dt.timedelta(days=dd.DD_SOFT_COOLDOWN_DAYS)
        out = dd.evaluate_drawdown(rows, target)
        assert out['halt_active'] is False
        assert out['dd_peak_units'] == pytest.approx(out['dd_cum_units'])

    def test_halt_holds_through_its_cooldown(self):
        rows = flat(20) + [pnl(20, 0, 7)]
        target = day(20) + dt.timedelta(days=dd.DD_SOFT_COOLDOWN_DAYS - 1)
        assert dd.evaluate_drawdown(rows, target)['halt_active'] is True

    def test_hard_tier_holds_longer_than_soft(self):
        assert dd.DD_HARD_COOLDOWN_DAYS > dd.DD_SOFT_COOLDOWN_DAYS
        rows = flat(20) + [pnl(20, 0, 12)]
        target = day(20) + dt.timedelta(days=dd.DD_SOFT_COOLDOWN_DAYS)
        assert dd.evaluate_drawdown(rows, target)['halt_active'] is True

    def test_cooldown_release_always_beats_the_lifetime_cap(self):
        """The cooldown is unconditional and shorter than DD_MAX_HALT_DAYS, so
        the lifetime cap is unreachable by design and a long-elapsed halt is
        reported as a normal release — NOT as `lifetime_expired`.

        Checking the lifetime first was a real bug: rows are pick-days, not
        calendar days, so the next row after a halt can land weeks later (an
        all-star break, a sparse late season, a grading outage). Such a halt had
        in fact released on its 3-day cooldown, but every later morning reported
        `lifetime_expired=True` and logged 'an operator must write a
        halt_overrides row' about an episode that ended weeks earlier.

        DD_MAX_HALT_DAYS is kept as a backstop for anyone who later makes the
        cooldown conditional; see the constant's docstring."""
        rows = flat(20) + [pnl(20, 0, 12)]
        target = day(20) + dt.timedelta(days=dd.DD_MAX_HALT_DAYS)
        out = dd.evaluate_drawdown(rows, target)
        assert out['halt_active'] is False
        assert out['dd_lifetime_expired'] is False
        assert out['dd_peak_units'] == pytest.approx(out['dd_cum_units'])

    def test_grading_lag_is_reported(self):
        out = dd.evaluate_drawdown(flat(20), day(25))
        assert out['dd_graded_through'] == day(19).isoformat()
        assert out['dd_grading_lag_days'] == 6

    def test_season_scoped_peak(self):
        assert dd.season_start_for(dt.date(2027, 3, 1)) == dt.date(2026, 10, 1)
        assert dd.season_start_for(dt.date(2026, 9, 30)) == dt.date(2025, 10, 1)


class TestVolumeAnomaly:
    BASE = [vol(i, 2) for i in range(10)]

    def test_normal_volume_does_not_halt(self):
        assert not dd.evaluate_volume_anomaly(self.BASE + [vol(10, 3)], day(11))['halt_active']

    def test_spike_halts(self):
        out = dd.evaluate_volume_anomaly(self.BASE + [vol(10, 16)], day(11))
        assert out['halt_active'] is True
        assert out['vol_trigger_picks'] == 16
        assert out['reason']

    def test_absolute_floor_protects_a_quiet_baseline(self):
        """3x a median of 2 is 6 picks — far too twitchy. The floor is what
        stops a normal 7-pick day zeroing the slate."""
        assert not dd.evaluate_volume_anomaly(self.BASE + [vol(10, 7)], day(11))['halt_active']

    def test_window_catches_a_spike_that_is_not_yesterday(self):
        """Load-bearing: 2026-03-06 published 13 picks, 03-07 published 1, and
        the 03-08 slate lost 9.18u. A one-day window sees only the quiet day."""
        rows = self.BASE + [vol(10, 16), vol(11, 1)]
        assert dd.evaluate_volume_anomaly(rows, day(12))['halt_active'] is True

    def test_dormant_until_enough_prior_pick_days(self):
        assert not dd.evaluate_volume_anomaly([vol(0, 2), vol(1, 30)], day(2))['halt_active']

    def test_zero_pick_days_do_not_deflate_the_baseline(self):
        """Otherwise a halt lowers its own median and every later day looks
        anomalous — a self-reinforcing halt."""
        rows = self.BASE + [vol(10, 0), vol(11, 0), vol(12, 7)]
        assert not dd.evaluate_volume_anomaly(rows, day(13))['halt_active']

    def test_stale_series_does_not_halt(self):
        """Nothing published recently is a drought, not an anomaly — and a
        different guard's job."""
        assert not dd.evaluate_volume_anomaly(self.BASE, day(60))['halt_active']

    def test_empty_series(self):
        assert dd.evaluate_volume_anomaly([], day(5))['halt_active'] is False


class TestContract:
    def test_reasons_are_distinct_and_not_manual(self):
        """`manual` means an operator acted. Overloading it would destroy the
        audit trail and make these guards indistinguishable in halt_state."""
        assert dd.HALT_REASON_DRAWDOWN == 'unit_drawdown'
        assert dd.HALT_REASON_VOLUME == 'volume_anomaly'
        assert dd.HALT_REASON_DRAWDOWN != dd.HALT_REASON_VOLUME

    def test_sql_is_parameterised_and_season_bounded(self):
        for sql in (dd.build_daily_pnl_query(), dd.build_daily_volume_query()):
            assert '@season_start' in sql and '@target_date' in sql
            assert 'game_date >=' in sql

    def test_pnl_join_uses_all_five_keys(self):
        """Joining on fewer keys multiplies rows and inflates wins AND losses."""
        sql = dd.build_daily_pnl_query()
        for key in ('pa.game_date', 'pa.player_lookup', 'pa.system_id',
                    'pa.recommendation', 'pa.line_value'):
            assert key in sql, key


class TestReviewFindings:
    """Adversarial-review additions (2026-08-21, reviewer 3)."""

    def test_volume_halt_releases_when_the_spike_leaves_the_window(self):
        """A spike halts exactly VOL_COOLDOWN_DAYS mornings; on the next morning
        the (suppressed, hence absent) window is empty and picks resume."""
        rows = [vol(i, 2) for i in range(10)] + [vol(10, 16)]
        # Halted mornings: spike is 1..3 days back.
        for t in (11, 12, 13):
            assert dd.evaluate_volume_anomaly(rows, day(t))['halt_active'] is True, t
        # Morning 14: spike is 4 days back, suppressed days published nothing.
        assert dd.evaluate_volume_anomaly(rows, day(14))['halt_active'] is False

    def test_volume_guard_rearms_after_an_episode(self):
        """A second spike after a suppressed window must halt again, and the
        first spike must not have inflated the trailing median."""
        rows = [vol(i, 2) for i in range(10)] + [vol(10, 16), vol(14, 2), vol(15, 16)]
        out = dd.evaluate_volume_anomaly(rows, day(16))
        assert out['halt_active'] is True
        assert out['vol_trigger_date'] == day(15).isoformat()
        assert out['vol_trailing_median'] == 2

    def test_cooldown_release_across_a_row_gap_is_not_labeled_lifetime_expiry(self):
        """REAL BUG (left failing, 2026-08-21 review): a soft halt that released
        via its 3-day cooldown must not be re-labeled as a lifetime expiry just
        because the NEXT pick-day row is >= DD_MAX_HALT_DAYS later (all-star
        break, late-season sparsity, grading outage).

        Timeline: halt trips on day 20; every morning from day 23 onward this
        function correctly reports halt_active=False, dd_lifetime_expired=False
        (aging path). But once a row appears at day 45, the in-loop replay hits
        the `elapsed >= DD_MAX_HALT_DAYS` branch BEFORE the cooldown branch and
        flips dd_lifetime_expired to True for every remaining morning of the
        season — a permanently wrong 'operator must write a halt_overrides row'
        audit flag (plus a daily WARNING log) for a halt that in fact released
        quietly 22 days earlier. Decisions are unaffected; the telemetry lies.
        """
        rows = flat(20) + [pnl(20, 0, 7)]
        # Before the gap-row exists the function itself says: released, no expiry.
        pre = dd.evaluate_drawdown(rows, day(30))
        assert pre['halt_active'] is False
        assert pre['dd_lifetime_expired'] is False
        # The same episode, seen after the next pick-day arrives 25 days later.
        post = dd.evaluate_drawdown(rows + [pnl(45, 1, 1)], day(46))
        assert post['halt_active'] is False
        assert post['dd_lifetime_expired'] is False, (
            "cooldown-released halt re-labeled as lifetime expiry after a row gap"
        )
