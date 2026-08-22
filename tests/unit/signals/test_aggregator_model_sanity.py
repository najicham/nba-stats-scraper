"""Unit tests for the per-model sanity guards in `BestBetsAggregator.aggregate`.

WHY THESE EXIST
---------------
Three guards sit in the hot path and *silently delete* every candidate from a
model they trip:

  1. direction imbalance  — >95% one-way over >=20 predictions (Session 378c)
  2. median-edge cap      — per-model median edge > 5.5 (2026-08-21)
  3. prediction-spread    — per-model stddev < 2.0 (2026-08-21)

plus a fleet-wide safety floor that DISARMS all three when they would block more
than half the fleet, because a correlated trip is a halt-class event and an
indefinite silent zero-pick drought is worse than publishing.

Until 2026-08-21 none of this had a single test, and a blocked candidate did not
even increment a filter counter. The `model_sanity_block` counter asserted here
was added alongside these tests.

The guards are exercised through the public `aggregate()` entry point rather than
by reaching into internals, so a refactor that moves them cannot quietly make the
tests vacuous: each test asserts on the counter AND on which models survive into
`picks`.

⚠️ SCOPE. The multi-model cases here — everything in `TestFleetWideSafetyFloor` —
exercise DEFAULT mode, which production does not use. `run_single_model_pipeline`
calls `aggregate()` once per model with only that model's predictions, so on the
production path this class's `n_models` is always 1 and its fleet-wide floor
cannot fire. Default mode is still real (signal_annotator, the backtest, replay
and dry-run tools all pass a multi-model list), so these tests are not vacuous —
but the floor that protects the LIVE slate is `_apply_fleet_sanity_floor` in
`per_model_pipeline`, covered by `test_fleet_sanity_floor.py`. Read the two files
together.
"""

from unittest import mock

import pytest

from ml.signals.aggregator import BestBetsAggregator
from ml.signals.base_signal import SignalResult


# Mirrors the constants in aggregator.aggregate(). Duplicated deliberately: if
# someone edits the thresholds, these tests must fail rather than follow along.
MIN_PREDS = 20
MAX_MEDIAN_EDGE = 5.5
MIN_PRED_STDDEV = 2.0


def _pred(system_id, i, *, predicted_points, line_value, recommendation):
    """One prediction. Field defaults mirror tests/unit/signals/test_aggregator.py."""
    return {
        'player_lookup': f'player_{system_id}_{i}',
        'game_id': f'20261115_G{i % 5}',
        'player_name': f'Player {i}',
        'team_abbr': 'LAL',
        'opponent_team_abbr': 'GSW',
        'system_id': system_id,
        'predicted_points': predicted_points,
        'line_value': line_value,
        'recommendation': recommendation,
        'edge': abs(predicted_points - line_value),
        'confidence_score': 0.85,
        'feature_quality_score': 90,
        'prop_line_delta': None,
        'neg_pm_streak': 0,
        'games_vs_opponent': 0,
        'source_model_family': '',
        'is_home': True,
        'points_avg_season': 0,
        'teammate_usage_available': 0,
        'trend_slope': 2.0,
        'spread_magnitude': 0,
    }


def _healthy_model(system_id, n=MIN_PREDS):
    """A model no guard should touch: balanced direction, edge ~3, wide spread.

    Spread comes from the LINE moving across players, not from a fixed offset,
    so the prediction stddev is comfortably above the 2.0 floor.
    """
    preds = []
    for i in range(n):
        line = 15.0 + (i % 10) * 2.0          # 15..33 -> stddev ~5.7
        rec = 'OVER' if i % 2 == 0 else 'UNDER'
        pp = line + 3.0 if rec == 'OVER' else line - 3.0
        preds.append(_pred(system_id, i, predicted_points=pp,
                           line_value=line, recommendation=rec))
    return preds


def _one_way_model(system_id, n=MIN_PREDS, direction='UNDER'):
    """Trips guard 1: every prediction the same direction."""
    preds = []
    for i in range(n):
        line = 15.0 + (i % 10) * 2.0
        pp = line + 3.0 if direction == 'OVER' else line - 3.0
        preds.append(_pred(system_id, i, predicted_points=pp,
                           line_value=line, recommendation=direction))
    return preds


def _huge_edge_model(system_id, n=MIN_PREDS, edge=7.0):
    """Trips guard 2: median edge above the cap, direction still balanced."""
    preds = []
    for i in range(n):
        line = 15.0 + (i % 10) * 2.0
        rec = 'OVER' if i % 2 == 0 else 'UNDER'
        pp = line + edge if rec == 'OVER' else line - edge
        preds.append(_pred(system_id, i, predicted_points=pp,
                           line_value=line, recommendation=rec))
    return preds


def _constant_model(system_id, n=MIN_PREDS, value=22.0):
    """Trips guard 3 only.

    A model emitting one constant near the middle of the line distribution:
    direction splits ~50/50 (escapes guard 1) and the median edge stays under
    the cap (escapes guard 2). Near-zero spread is the only thing that sees it.
    """
    preds = []
    for i in range(n):
        line = value + (2.0 if i % 2 else -2.0)   # edge is exactly 2.0 for all
        rec = 'UNDER' if i % 2 else 'OVER'
        preds.append(_pred(system_id, i, predicted_points=value,
                           line_value=line, recommendation=rec))
    return preds


def _signals_for(preds, n_qualifying=5):
    """Enough qualifying signals per candidate to clear the SC gates."""
    out = {}
    for p in preds:
        key = f"{p['player_lookup']}::{p['game_id']}"
        out[key] = [SignalResult(qualifies=True, confidence=0.5,
                                 source_tag=f'signal_{i}')
                    for i in range(n_qualifying)]
    return out


def _run(preds, **agg_kwargs):
    # The fleet-wide disarm path calls shared.observability.metrics.emit_metric.
    # Unmocked, that is a live Cloud Monitoring write on any machine where
    # google-cloud-monitoring is installed and ADC resolves — it happens to
    # no-op here only because the package is absent.
    agg = BestBetsAggregator(**agg_kwargs)
    with mock.patch('shared.observability.metrics.emit_metric'):
        picks, summary = agg.aggregate(preds, _signals_for(preds))
    return picks, summary


def _surviving_models(picks):
    return {p.get('system_id') for p in picks}


# ---------------------------------------------------------------------------
# Guard 1 — direction imbalance
# ---------------------------------------------------------------------------

class TestDirectionImbalanceGuard:

    def test_one_way_model_is_blocked_and_counted(self):
        preds = _one_way_model('broken_v1')
        picks, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == len(preds)
        assert 'broken_v1' not in _surviving_models(picks)

    def test_one_way_over_is_blocked_too(self):
        """The guard is two-sided; an all-OVER artifact is the same pathology."""
        preds = _one_way_model('broken_over_v1', direction='OVER')
        picks, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == len(preds)
        assert 'broken_over_v1' not in _surviving_models(picks)

    def test_below_minimum_sample_is_not_blocked(self):
        """19 one-way predictions is not enough evidence; 20 is the bar.

        This is the guard's own false-positive protection — assert it, because a
        silent off-by-one here would block a model on its first thin slate.
        """
        preds = _one_way_model('thin_v1', n=MIN_PREDS - 1)
        _, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == 0

    def test_exactly_at_minimum_sample_is_blocked(self):
        preds = _one_way_model('atbar_v1', n=MIN_PREDS)
        _, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == MIN_PREDS


# ---------------------------------------------------------------------------
# Guard 2 — median-edge cap (the large-edge degeneracy hole)
# ---------------------------------------------------------------------------

class TestMedianEdgeCap:

    def test_median_edge_above_cap_is_blocked(self):
        preds = _huge_edge_model('stale_v1', edge=MAX_MEDIAN_EDGE + 1.5)
        picks, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == len(preds)
        assert 'stale_v1' not in _surviving_models(picks)

    def test_median_edge_below_cap_is_not_blocked(self):
        """4.5 is inside the healthy five-season range (max 4.52). Must survive.

        Guards this direction explicitly: the whole point of 5.5 rather than 4.5
        is that well-calibrated models have reached 4.52 and must not be culled.
        """
        preds = _huge_edge_model('healthy_high_v1', edge=4.5)
        _, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == 0

    def test_edge_uses_current_points_line_when_line_value_absent(self):
        """`line_value` is the aggregator's name; the predictions table uses
        `current_points_line`. The guard reads both — if that fallback breaks,
        every edge silently becomes unmeasurable and the cap stops firing."""
        preds = _huge_edge_model('altkey_v1', edge=MAX_MEDIAN_EDGE + 1.5)
        for p in preds:
            p['current_points_line'] = p.pop('line_value')
        _, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == len(preds)


# ---------------------------------------------------------------------------
# Guard 3 — prediction-spread floor (constant-serving model)
# ---------------------------------------------------------------------------

class TestPredictionSpreadFloor:

    def test_constant_model_is_blocked(self):
        preds = _constant_model('constant_v1')
        picks, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == len(preds)
        assert 'constant_v1' not in _surviving_models(picks)

    def test_constant_model_escapes_the_other_two_guards(self):
        """Documents WHY this guard exists rather than trusting the other two.

        If this ever fails, the fixture drifted and the block above may be
        crediting the wrong guard.
        """
        preds = _constant_model('constant_v1')
        overs = sum(1 for p in preds if p['recommendation'] == 'OVER')
        assert 0.05 <= overs / len(preds) <= 0.95, "would trip the direction guard"
        edges = sorted(abs(p['predicted_points'] - p['line_value']) for p in preds)
        assert edges[len(edges) // 2] <= MAX_MEDIAN_EDGE, "would trip the edge cap"

    def test_wide_spread_model_is_not_blocked(self):
        preds = _healthy_model('healthy_v1')
        _, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == 0


# ---------------------------------------------------------------------------
# The fleet-wide safety floor
# ---------------------------------------------------------------------------

class TestFleetWideSafetyFloor:
    """DEFAULT-mode only — see the scope note in the module docstring. The
    production equivalent is `test_fleet_sanity_floor.py`."""

    def test_all_models_pathological_blocks_nothing(self):
        """Two of two models trip => disarm. A fleet-wide trip must surface as a
        halt/model-health event, not as a silent empty slate."""
        preds = _one_way_model('broken_a') + _one_way_model('broken_b')
        picks, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == 0
        assert _surviving_models(picks) <= {'broken_a', 'broken_b'}

    def test_majority_of_three_models_blocks_nothing(self):
        """2 of 3 is above the 50% fraction, so the floor disarms."""
        preds = (_one_way_model('broken_a') + _one_way_model('broken_b')
                 + _healthy_model('healthy_c'))
        _, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == 0

    def test_minority_of_three_models_still_blocks(self):
        """1 of 3 is a per-model pathology. The block must stand — otherwise the
        floor would swallow the case the guards were built for."""
        preds = (_one_way_model('broken_a') + _healthy_model('healthy_b')
                 + _healthy_model('healthy_c'))
        picks, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == MIN_PREDS
        assert 'broken_a' not in _surviving_models(picks)

    def test_single_model_fleet_still_blocks(self):
        """n_models=1: `max(1, int(1*0.5))` is 1 and `1 > 1` is False, so a
        one-model fleet is NOT disarmed. Pinning this because the arithmetic is
        the kind that flips silently under an innocuous-looking edit."""
        preds = _one_way_model('only_v1')
        _, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == MIN_PREDS

    def test_half_of_four_models_still_blocks(self):
        """Exactly 50% is `2 > max(1, 2)` => False => the block stands. The floor
        disarms on MORE than half, not on half."""
        preds = (_one_way_model('broken_a') + _one_way_model('broken_b')
                 + _healthy_model('healthy_c') + _healthy_model('healthy_d'))
        _, summary = _run(preds)
        assert summary['rejected']['model_sanity_block'] == 2 * MIN_PREDS


# ---------------------------------------------------------------------------
# Legacy blocklist interaction
# ---------------------------------------------------------------------------

class TestLegacyBlocklistIsNotSubjectToTheFloor:

    def test_legacy_models_blocked_even_when_they_are_the_whole_fleet(self):
        """`LEGACY_MODEL_BLOCKLIST` is applied AFTER the fleet-wide reset, so it
        is deliberately unaffected by it. These two models bypass the registry
        and must never source picks regardless of fleet composition."""
        preds = _healthy_model('catboost_v12') + _healthy_model('catboost_v9')
        picks, summary = _run(preds)
        assert summary['rejected']['legacy_block'] == 2 * MIN_PREDS
        assert summary['rejected']['model_sanity_block'] == 0
        assert picks == []

    def test_legacy_block_counted_separately_from_sanity_block(self):
        preds = _healthy_model('catboost_v9') + _one_way_model('broken_a') \
            + _healthy_model('healthy_c')
        _, summary = _run(preds)
        assert summary['rejected']['legacy_block'] == MIN_PREDS
        assert summary['rejected']['model_sanity_block'] == MIN_PREDS


# ---------------------------------------------------------------------------
# Non-regression: the guards must not touch a healthy fleet
# ---------------------------------------------------------------------------

def test_healthy_fleet_is_untouched():
    preds = (_healthy_model('m_a') + _healthy_model('m_b') + _healthy_model('m_c'))
    _, summary = _run(preds)
    assert summary['rejected']['model_sanity_block'] == 0
    assert summary['rejected']['legacy_block'] == 0


def test_empty_input_does_not_create_the_counter():
    """`filter_summary['rejected']` is a defaultdict and the existing suite
    asserts its EXACT key set on empty input. A write-only counter must not
    appear there."""
    agg = BestBetsAggregator()
    _, summary = agg.aggregate([], {})
    assert 'model_sanity_block' not in summary['rejected']
