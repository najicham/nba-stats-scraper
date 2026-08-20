"""Tests for the edge-collapse auto-halt state machine.

The predecessor to this code halted on 865 of 865 prediction-days across five
seasons and could never release. These tests pin the two properties whose
absence caused that: the halt must not fire on healthy markets, and once fired
it must be able to release.
"""
import datetime as dt
from types import SimpleNamespace

import pytest

from shared.config import edge_halt as eh


def row(day, edge_med, pct_e3, days_sampled=7):
    return SimpleNamespace(
        game_date=dt.date(2026, 1, 1) + dt.timedelta(days=day),
        edge_med_7d=edge_med, pct_e3_7d=pct_e3,
        days_sampled=days_sampled, n_player_games=120,
    )


def series(specs):
    return [row(i, e, p) for i, (e, p) in enumerate(specs)]


class TestHaltCondition:
    def test_healthy_market_does_not_halt(self):
        # Typical healthy season values (2021-22 through 2024-25 floors).
        assert not eh.evaluate_halt_state(series([(1.8, 20.0)] * 30))['halt_active']

    def test_collapse_halts(self):
        assert eh.evaluate_halt_state(series([(1.0, 5.0)] * 10))['halt_active']

    def test_requires_both_conditions(self):
        """The conjunction is load-bearing: in 2023-24 and 2024-25 the trailing
        median dipped below 1.4 while the market was healthy, and only the
        edge-3+ share kept the system live."""
        low_median_only = eh.evaluate_halt_state(series([(1.30, 17.0)] * 20))
        assert not low_median_only['halt_active']
        low_pct_only = eh.evaluate_halt_state(series([(1.9, 8.0)] * 20))
        assert not low_pct_only['halt_active']

    def test_boundary_is_strict_less_than(self):
        at_threshold = series([(eh.HALT_EDGE_MEDIAN, eh.HALT_PCT_EDGE_3PLUS)] * 10)
        assert not eh.evaluate_halt_state(at_threshold)['halt_active']


class TestRelease:
    def test_release_is_reachable(self):
        """The whole point of the rewrite: the old release condition required
        values above the all-time maximum, so a halt was permanent."""
        s = series([(1.0, 5.0)] * 10 + [(1.7, 15.0)] * eh.RELEASE_CONSECUTIVE_DAYS)
        assert not eh.evaluate_halt_state(s)['halt_active']

    def test_release_needs_full_streak(self):
        s = series([(1.0, 5.0)] * 10 + [(1.7, 15.0)] * (eh.RELEASE_CONSECUTIVE_DAYS - 1))
        assert eh.evaluate_halt_state(s)['halt_active']

    def test_streak_resets_on_a_bad_day(self):
        s = series([(1.0, 5.0)] * 10
                   + [(1.7, 15.0)] * (eh.RELEASE_CONSECUTIVE_DAYS - 1)
                   + [(1.5, 15.0)]                       # below release, resets
                   + [(1.7, 15.0)] * (eh.RELEASE_CONSECUTIVE_DAYS - 1))
        assert eh.evaluate_halt_state(s)['halt_active']

    def test_hysteresis_gap_prevents_flapping(self):
        """Values between the halt and release thresholds hold the current state
        in both directions — that band is the whole purpose of hysteresis."""
        mid = (eh.HALT_EDGE_MEDIAN + eh.RELEASE_EDGE_MEDIAN) / 2
        assert eh.evaluate_halt_state(series([(mid, 15.0)] * 20))['halt_active'] is False
        held = series([(1.0, 5.0)] * 5 + [(mid, 15.0)] * 20)
        assert eh.evaluate_halt_state(held)['halt_active'] is True

    def test_release_ignores_pct_e3(self):
        s = series([(1.0, 5.0)] * 10 + [(1.7, 2.0)] * eh.RELEASE_CONSECUTIVE_DAYS)
        assert not eh.evaluate_halt_state(s)['halt_active']


class TestThinData:
    def test_below_min_days_is_not_evaluated(self):
        s = [row(i, 1.0, 5.0, days_sampled=eh.MIN_DAYS_SAMPLED - 1) for i in range(10)]
        out = eh.evaluate_halt_state(s)
        assert not out['halt_active']
        assert out['days_evaluated'] == 0

    def test_thin_days_do_not_advance_release_streak(self):
        s = (series([(1.0, 5.0)] * 10)
             + [row(20 + i, 1.7, 15.0, days_sampled=1) for i in range(5)])
        assert eh.evaluate_halt_state(s)['halt_active']

    def test_null_median_skipped(self):
        s = series([(1.8, 20.0)] * 5)
        s.insert(2, row(99, None, None))
        assert not eh.evaluate_halt_state(s)['halt_active']

    def test_empty_series(self):
        out = eh.evaluate_halt_state([])
        assert out['halt_active'] is False and out['days_sampled'] == 0


class TestReporting:
    def test_reason_populated_only_when_halted(self):
        assert eh.evaluate_halt_state(series([(1.0, 5.0)] * 10))['reason']
        assert eh.evaluate_halt_state(series([(1.8, 20.0)] * 10))['reason'] == ''

    def test_halt_started_tracks_onset(self):
        s = series([(1.8, 20.0)] * 4 + [(1.0, 5.0)] * 5)
        out = eh.evaluate_halt_state(s)
        assert out['halt_started'] == dt.date(2026, 1, 5)

    def test_last_row_values_reported(self):
        out = eh.evaluate_halt_state(series([(1.8, 20.0), (1.9, 22.0)]))
        assert out['edge_med_7d'] == pytest.approx(1.9)
        assert out['pct_e3_7d'] == pytest.approx(22.0)


class TestThresholds:
    def test_release_above_halt(self):
        """Without a gap the state machine flaps day to day."""
        assert eh.RELEASE_EDGE_MEDIAN > eh.HALT_EDGE_MEDIAN

    def test_lookback_exceeds_longest_observed_collapse(self):
        """The 2026 collapse ran 56 days; a shorter lookback would forget it and
        silently release."""
        assert eh.LOOKBACK_DAYS > 56


class TestQuery:
    def test_sql_is_parameterized_and_bounded(self):
        sql = eh.build_daily_edge_query()
        assert '@target_date' in sql and '@lookback' in sql
        # Partition/date bound present so this never full-scans.
        assert 'game_date >=' in sql

    def test_sql_dedupes_to_player_game(self):
        """Median across models per player-game, not a mean over raw rows — the
        fleet grew 2.3 -> 16.8 models/player-game and a row-mean tracks that."""
        sql = eh.build_daily_edge_query()
        assert 'GROUP BY game_date, player_lookup, game_id' in sql
        assert 'APPROX_QUANTILES' in sql
