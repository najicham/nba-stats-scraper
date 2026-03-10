"""Tests for Cold3ptOverSignal."""

import pytest
from ml.signals.cold_3pt_over import Cold3ptOverSignal


@pytest.fixture
def signal():
    return Cold3ptOverSignal()


def _make_pred(recommendation='OVER', line_value=20.0):
    return {'recommendation': recommendation, 'line_value': line_value}


def _make_supp(three_pct_last_3=0.18, three_pct_season=0.35, three_pa_per_game=6.0):
    return {
        'three_pt_stats': {
            'three_pct_last_3': three_pct_last_3,
            'three_pct_season': three_pct_season,
            'three_pa_per_game': three_pa_per_game,
        }
    }


class TestCold3ptOver:
    def test_qualifies_cold_streak(self, signal):
        """Cold 3PT streak (18% vs 35% season) → qualifies."""
        pred = _make_pred()
        supp = _make_supp(three_pct_last_3=0.18, three_pct_season=0.35)
        result = signal.evaluate(pred, supplemental=supp)
        assert result.qualifies
        assert result.source_tag == 'cold_3pt_over'
        assert result.metadata['three_pt_deficit'] == pytest.approx(0.17, abs=0.001)

    def test_not_cold_enough(self, signal):
        """3PT deficit < 15% → does not qualify."""
        pred = _make_pred()
        supp = _make_supp(three_pct_last_3=0.25, three_pct_season=0.35)
        result = signal.evaluate(pred, supplemental=supp)
        assert not result.qualifies

    def test_under_direction_blocked(self, signal):
        """UNDER direction → does not qualify."""
        pred = _make_pred(recommendation='UNDER')
        supp = _make_supp(three_pct_last_3=0.15, three_pct_season=0.35)
        result = signal.evaluate(pred, supplemental=supp)
        assert not result.qualifies

    def test_low_volume_blocked(self, signal):
        """Low 3PA per game → does not qualify."""
        pred = _make_pred()
        supp = _make_supp(three_pct_last_3=0.15, three_pct_season=0.35, three_pa_per_game=1.5)
        result = signal.evaluate(pred, supplemental=supp)
        assert not result.qualifies

    def test_no_supplemental(self, signal):
        """Missing supplemental → does not qualify."""
        result = signal.evaluate(_make_pred(), supplemental=None)
        assert not result.qualifies

    def test_confidence_scales(self, signal):
        """Larger cold streak → higher confidence."""
        pred = _make_pred()
        mild = signal.evaluate(pred, supplemental=_make_supp(0.19, 0.35))
        extreme = signal.evaluate(pred, supplemental=_make_supp(0.05, 0.35))
        assert extreme.confidence > mild.confidence
