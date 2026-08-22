"""Behaviour tests for the two opponent-pace signals.

Both read `prediction['opponent_pace']`, which until 2026-08-22 was populated
from feature_18_value (pct_paint, 0-1) instead of feature_14_value (raw
possessions/game, ~92-108). See test_feature_alias_contract.py for the wiring
guard; these tests pin the *scale* the signals expect, so a future change that
reintroduces a normalized value fails here too.
"""

import pytest

from ml.signals.fast_pace_over import FastPaceOverSignal
from ml.signals.slow_pace_under import SlowPaceUnderSignal


def over(pace):
    return {'recommendation': 'OVER', 'opponent_pace': pace}


def under(pace):
    return {'recommendation': 'UNDER', 'opponent_pace': pace}


class TestFastPaceOver:
    def setup_method(self):
        self.sig = FastPaceOverSignal()

    def test_fires_on_fast_raw_pace(self):
        assert self.sig.evaluate(over(104.0)).qualifies

    def test_does_not_fire_on_average_raw_pace(self):
        assert not self.sig.evaluate(over(99.0)).qualifies

    @pytest.mark.parametrize('normalized', [0.0, 0.5, 0.76, 0.9, 1.0])
    def test_normalized_values_never_qualify(self, normalized):
        """The pre-fix bug: a 0-1 column read as pace. Must be inert now."""
        assert not self.sig.evaluate(over(normalized)).qualifies

    def test_under_picks_never_qualify(self):
        assert not self.sig.evaluate(under(108.0)).qualifies

    def test_confidence_spans_the_realistic_pace_range(self):
        """Pre-fix the curve saturated 0.5 possessions past the threshold."""
        at_floor = self.sig.evaluate(over(102.0)).confidence
        mid = self.sig.evaluate(over(106.0)).confidence
        top = self.sig.evaluate(over(112.0)).confidence
        assert at_floor == pytest.approx(0.80)
        assert at_floor < mid < 0.90
        assert top == pytest.approx(0.90)  # capped, not pinned early


class TestSlowPaceUnder:
    def setup_method(self):
        self.sig = SlowPaceUnderSignal()

    def test_fires_on_slow_raw_pace(self):
        assert self.sig.evaluate(under(95.0)).qualifies

    def test_does_not_fire_on_fast_raw_pace(self):
        assert not self.sig.evaluate(under(101.0)).qualifies

    @pytest.mark.parametrize('normalized', [0.0, 0.25, 0.5, 0.99, 1.0])
    def test_normalized_values_are_rejected_by_the_scale_guard(self, normalized):
        """The pre-fix bug: `opp_pace > 99.0` can never be true on a 0-1 value,
        so this signal qualified EVERY UNDER at a pinned 0.90 confidence."""
        assert not self.sig.evaluate(under(normalized)).qualifies

    def test_missing_pace_defaults_to_zero_and_is_rejected(self):
        """Both query paths coerce a NULL pace to 0.0, not None."""
        assert not self.sig.evaluate(under(0.0)).qualifies

    def test_over_picks_never_qualify(self):
        assert not self.sig.evaluate(over(92.0)).qualifies

    def test_confidence_rises_as_pace_falls_and_is_capped(self):
        at_ceiling = self.sig.evaluate(under(99.0)).confidence
        mid = self.sig.evaluate(under(95.0)).confidence
        slowest = self.sig.evaluate(under(88.0)).confidence
        assert at_ceiling == pytest.approx(0.70)
        assert at_ceiling < mid < 0.90
        assert slowest == pytest.approx(0.90)

    def test_confidence_is_not_constant_across_the_qualifying_band(self):
        """Pre-fix every fire returned exactly 0.90, making the signal a
        constant. Distinct paces must produce distinct confidences."""
        confs = {self.sig.evaluate(under(p)).confidence for p in (92.0, 95.0, 98.0)}
        assert len(confs) == 3
