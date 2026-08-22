"""The fleet-wide model-sanity floor, on the path production actually uses.

WHY THIS FILE EXISTS SEPARATELY FROM test_aggregator_model_sanity.py
--------------------------------------------------------------------
`aggregator.aggregate()` carries a fleet-wide safety floor, and on the
signal-best-bets path it can never fire. `run_single_model_pipeline` calls
`aggregate()` once per model with ONLY that model's predictions, so the
aggregator's `n_models` is always 1 and its `1 > max(1, int(1*0.5))` test is
`1 > 1` — False. From the guards shipping until 2026-08-21 the floor was inert
on the path that picks money.

The sibling file's multi-model cases are not vacuous — `signal_annotator` is
production (`subset-picks` ships in `TONIGHT_EXPORT_TYPES`) and passes a real
multi-model list, as do the backtest/replay/dry-run tools. They just do not
cover the signal-best-bets slate.

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


def legacy_result(system_id):
    """A model culled by LEGACY_MODEL_BLOCKLIST — it can never contribute picks,
    so it is neither a sanity block nor part of the fleet the floor judges."""
    return PipelineResult(
        system_id=system_id, candidates=[], all_predictions=[],
        filter_summary={'total_candidates': 25, 'rejected': {'legacy_block': 25}},
        signal_results={})


def errored_result(system_id):
    return PipelineResult(
        system_id=system_id, candidates=[], all_predictions=[],
        filter_summary={'total_candidates': 0, 'rejected': {}, 'error': 'boom'},
        signal_results={})


class _Rerun:
    """Stands in for `_run_one`. Records what was re-run and with what flag."""

    def __init__(self):
        self.calls = []

    def __call__(self, system_id, disable_sanity):
        self.calls.append((system_id, disable_sanity))
        return result(system_id, blocked=False, n_candidates=7)


def run(results):
    """Invoke the floor with observability stubbed out.

    ⚠️ The first version of this helper used a bare `mock.patch.dict('sys.modules')`,
    which snapshots and restores sys.modules and mocks NOTHING. Every trip test
    then executed the real `emit_metric`; it no-opped only because
    google-cloud-monitoring is absent from this venv. On a CI image with the
    package and ADC present, the unit suite would have written real
    `model_sanity_fleet_wide_trip` time series into the production project.
    """
    rerun = _Rerun()
    with mock.patch('shared.observability.metrics.emit_metric') as emit:
        _apply_fleet_sanity_floor(results, rerun)
    rerun.emit = emit
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

    def test_the_trip_emits_the_metric(self):
        results = {m: result(m, blocked=True) for m in ('a', 'b')}
        rerun = run(results)
        assert rerun.emit.called
        assert rerun.emit.call_args[0][0] == 'model_sanity_fleet_wide_trip'
        assert rerun.emit.call_args[0][1] == 2.0

    def test_no_trip_emits_nothing(self):
        results = {'a': result('a', blocked=True), 'b': result('b', blocked=False),
                   'c': result('c', blocked=False)}
        rerun = run(results)
        assert not rerun.emit.called

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

    def test_errored_pipeline_is_not_read_as_a_sanity_block(self):
        """A pipeline that raised returns `filter_summary` without the counter,
        so it stays out of the numerator. Here the one real self-block is 1 of 2
        eligible models — not a majority — so nothing is disarmed."""
        results = {'a': errored_result('a'),
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
        which is deliberately NOT subject to this floor."""
        results = {'catboost_v9': legacy_result('catboost_v9'),
                   'b': result('b', blocked=True),
                   'c': result('c', blocked=False)}
        rerun = run(results)
        assert rerun.calls == []

    def test_legacy_models_do_not_dilute_the_denominator(self):
        """THE dilution bug. Two real clones both self-block; two legacy
        prediction sets are also on the date. Counting them gives n=4 and
        `2 <= max(1,2)` — no trip, and an indefinite zero-pick day with
        `halt_active: false`. The legacy models cannot contribute picks, so the
        real fleet is 2 of 2 and the floor must trip."""
        results = {'catboost_v9': legacy_result('catboost_v9'),
                   'catboost_v12': legacy_result('catboost_v12'),
                   'a': result('a', blocked=True),
                   'b': result('b', blocked=True)}
        rerun = run(results)
        assert sorted(s for s, _ in rerun.calls) == ['a', 'b']

    def test_errored_pipelines_do_not_dilute_the_denominator(self):
        """Same one-sided error: an errored pipeline is already out of the
        numerator, so leaving it in the denominator can only suppress a trip."""
        results = {'boom': errored_result('boom'),
                   'a': result('a', blocked=True),
                   'b': result('b', blocked=True)}
        rerun = run(results)
        assert sorted(s for s, _ in rerun.calls) == ['a', 'b']

    def test_forensics_survive_the_rerun(self):
        """A fleet-wide trip must not be the one day whose audit shows nothing
        was blocked. The pre-rerun count is carried onto the replacement."""
        results = {m: result(m, blocked=True) for m in ('a', 'b')}
        run(results)
        for m in ('a', 'b'):
            fs = results[m].filter_summary
            assert fs['model_sanity_block_disarmed'] == 25
            assert fs['model_sanity_fleet_wide_trip'] is True


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
