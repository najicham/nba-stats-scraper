"""The fleet-wide model-sanity floor, on the path production actually uses.

WHY THIS FILE EXISTS SEPARATELY FROM test_aggregator_model_sanity.py
--------------------------------------------------------------------
`aggregator.aggregate()` carries a fleet-wide safety floor, and on the
production path it can never fire. `run_single_model_pipeline` calls
`aggregate()` once per model with ONLY that model's predictions, so the
aggregator's `n_models` is always 1 and its `1 > max(1, int(1*0.5))` test is
`1 > 1` — False. From the guards shipping until 2026-08-21 the floor was inert
exactly where it mattered, and the tests in the sibling file certify semantics
that only the default-mode analysis callers (signal_annotator, backtest, replay,
dry-run) ever reach.

The real floor is `_apply_fleet_sanity_floor` in `per_model_pipeline`, the only
caller that sees the whole fleet. These tests cover THAT one.

What it protects against: the enabled fleet is three near-clones of one family
(r >= 0.95). A shared feature regression trips the same guard on all three at
once. Left alone that is an indefinite zero-pick drought with
`halt_active: false`, no halt reason, and nothing to alert on — `pick_drought`
is MLB-only, `_predictions_inactive` sees predictions flowing, `fleet_blocked`
reads graded predictions rather than picks and stays healthy, and both pipeline
canaries are paused.
"""

from unittest import mock

import pytest

from ml.signals import per_model_pipeline as pmp
from ml.signals.per_model_pipeline import (
    MODEL_SANITY_MAX_BLOCK_FRACTION,
    PipelineResult,
    _apply_fleet_sanity_floor,
)


def result(system_id, *, blocked, n_candidates=3):
    """A PipelineResult as a single model's pipeline would return it.

    `model_sanity_block > 0` is the only signal available to the orchestrator
    that a model blocked itself — each pipeline sees one model, so any nonzero
    count means that model was the one culled.
    """
    return PipelineResult(
        system_id=system_id,
        candidates=[] if blocked else [{'player_lookup': f'p{i}'} for i in range(n_candidates)],
        all_predictions=[{'system_id': system_id}] * 25,
        filter_summary={
            'total_candidates': 25,
            'rejected': {'model_sanity_block': 25 if blocked else 0},
        },
        signal_results={},
    )


class _Rerun:
    """Stands in for `_run_one`. Records what was re-run and with what flag."""

    def __init__(self):
        self.calls = []

    def __call__(self, system_id, disable_sanity):
        self.calls.append((system_id, disable_sanity))
        return result(system_id, blocked=False, n_candidates=7)


def run(results):
    rerun = _Rerun()
    with mock.patch.dict('sys.modules'):
        _apply_fleet_sanity_floor(results, rerun)
    return rerun


# --------------------------------------------------------------------------- #
# The trip
# --------------------------------------------------------------------------- #

class TestFleetWideTrip:

    def test_all_three_clones_blocked_triggers_a_rerun(self):
        """The scenario the floor exists for: a shared regression culls the
        whole fleet, one model per pipeline run, and nothing downstream can tell
        that from a genuinely empty slate."""
        results = {m: result(m, blocked=True) for m in ('a', 'b', 'c')}
        rerun = run(results)

        assert sorted(s for s, _ in rerun.calls) == ['a', 'b', 'c']
        assert all(disable is True for _, disable in rerun.calls)
        assert all(results[m].candidates for m in ('a', 'b', 'c'))

    def test_rerun_replaces_the_blocked_results(self):
        results = {m: result(m, blocked=True) for m in ('a', 'b')}
        run(results)
        assert [len(results[m].candidates) for m in ('a', 'b')] == [7, 7]

    def test_two_of_three_trips_the_floor(self):
        """Above half, so it is a fleet verdict. The healthy model is NOT
        re-run — only the ones that blocked themselves."""
        results = {'a': result('a', blocked=True),
                   'b': result('b', blocked=True),
                   'c': result('c', blocked=False)}
        rerun = run(results)
        assert sorted(s for s, _ in rerun.calls) == ['a', 'b']

    def test_healthy_model_results_are_untouched(self):
        results = {'a': result('a', blocked=True),
                   'b': result('b', blocked=True),
                   'c': result('c', blocked=False, n_candidates=4)}
        run(results)
        assert len(results['c'].candidates) == 4

    def test_the_trip_is_logged_as_an_error(self):
        """A silent recovery would be as bad as the silent drought — the whole
        point is that someone finds out."""
        results = {m: result(m, blocked=True) for m in ('a', 'b')}
        with mock.patch.object(pmp.logger, 'error') as err:
            _apply_fleet_sanity_floor(results, _Rerun())
        assert err.called
        assert 'fleet-wide' in err.call_args[0][0]

    def test_metric_emit_failure_does_not_break_the_rerun(self):
        """Observability must never be load-bearing on the money path."""
        results = {m: result(m, blocked=True) for m in ('a', 'b')}
        rerun = _Rerun()
        with mock.patch('shared.observability.metrics.emit_metric',
                        side_effect=RuntimeError('monitoring down')):
            _apply_fleet_sanity_floor(results, rerun)
        assert len(rerun.calls) == 2


# --------------------------------------------------------------------------- #
# The non-trip — a per-model pathology must still be blocked
# --------------------------------------------------------------------------- #

class TestPerModelPathologyStillBlocks:

    def test_one_of_three_does_not_trip(self):
        results = {'a': result('a', blocked=True),
                   'b': result('b', blocked=False),
                   'c': result('c', blocked=False)}
        rerun = run(results)
        assert rerun.calls == []
        assert results['a'].candidates == []

    def test_two_of_four_does_not_trip(self):
        """Exactly half. The floor disarms on MORE than half, not on half."""
        results = {'a': result('a', blocked=True), 'b': result('b', blocked=True),
                   'c': result('c', blocked=False), 'd': result('d', blocked=False)}
        rerun = run(results)
        assert rerun.calls == []

    def test_three_of_four_trips(self):
        results = {'a': result('a', blocked=True), 'b': result('b', blocked=True),
                   'c': result('c', blocked=True), 'd': result('d', blocked=False)}
        rerun = run(results)
        assert sorted(s for s, _ in rerun.calls) == ['a', 'b', 'c']

    def test_single_model_fleet_is_never_disarmed(self):
        """`1 > max(1, 0)` is False. A one-model fleet with a broken model gets
        blocked, which is correct — there is no healthy peer to contradict it."""
        results = {'only': result('only', blocked=True)}
        rerun = run(results)
        assert rerun.calls == []

    def test_nothing_blocked_is_a_no_op(self):
        results = {m: result(m, blocked=False) for m in ('a', 'b', 'c')}
        rerun = run(results)
        assert rerun.calls == []

    def test_empty_results_is_a_no_op(self):
        rerun = run({})
        assert rerun.calls == []


# --------------------------------------------------------------------------- #
# Robustness of the detection signal
# --------------------------------------------------------------------------- #

class TestDetectionSignal:

    def test_missing_rejected_key_is_treated_as_not_blocked(self):
        """A pipeline that raised returns `filter_summary` without the counter.
        An errored model must not be read as a sanity block — otherwise a
        transient exception in two of three pipelines would disarm the guards."""
        errored = PipelineResult(
            system_id='a', candidates=[], all_predictions=[],
            filter_summary={'total_candidates': 0, 'rejected': {}, 'error': 'boom'},
            signal_results={})
        results = {'a': errored,
                   'b': result('b', blocked=True),
                   'c': result('c', blocked=False)}
        rerun = run(results)
        assert rerun.calls == []

    def test_none_rejected_is_handled(self):
        odd = PipelineResult(system_id='a', candidates=[], all_predictions=[],
                             filter_summary={'rejected': None}, signal_results={})
        results = {'a': odd, 'b': result('b', blocked=True)}
        rerun = run(results)
        assert rerun.calls == []

    def test_legacy_block_is_not_a_sanity_block(self):
        """`catboost_v12` / `catboost_v9` are blocked by the legacy blocklist,
        which is deliberately NOT subject to this floor. They must not count
        toward the fraction, or two legacy models in a three-model fleet would
        disarm the real guards."""
        legacy = PipelineResult(
            system_id='catboost_v9', candidates=[], all_predictions=[],
            filter_summary={'rejected': {'legacy_block': 25}}, signal_results={})
        results = {'catboost_v9': legacy,
                   'b': result('b', blocked=True),
                   'c': result('c', blocked=False)}
        rerun = run(results)
        assert rerun.calls == []


# --------------------------------------------------------------------------- #
# The two constants must not drift apart
# --------------------------------------------------------------------------- #

def test_fraction_matches_the_aggregator_constant():
    """`aggregator.aggregate()` defines the same threshold as a local. If the
    two drift, the default-mode callers and the production path disagree about
    what "fleet-wide" means."""
    import inspect
    from ml.signals.aggregator import BestBetsAggregator
    src = inspect.getsource(BestBetsAggregator.aggregate)
    assert f'MODEL_SANITY_MAX_BLOCK_FRACTION = {MODEL_SANITY_MAX_BLOCK_FRACTION}' in src


def test_disable_flag_actually_disarms_the_guards():
    """End-to-end on the flag the floor sets: the same one-way model that gets
    blocked normally must survive with `disable_model_sanity=True`."""
    from ml.signals.aggregator import BestBetsAggregator
    from tests.unit.signals.test_aggregator_model_sanity import (
        _one_way_model, _signals_for)

    preds = _one_way_model('broken_v1')
    sigs = _signals_for(preds)

    _, blocked = BestBetsAggregator().aggregate(preds, sigs)
    assert blocked['rejected']['model_sanity_block'] == len(preds)

    _, allowed = BestBetsAggregator(disable_model_sanity=True).aggregate(preds, sigs)
    assert allowed['rejected'].get('model_sanity_block', 0) == 0
