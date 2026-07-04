"""
Measurement-infra C1 — unconditional shadow-tag persistence.

Verifies that pre-signal-stage filter rejections (the ~40 _record_filtered
call sites that pass no sig_tags) now persist the FULL qualifying-signal tag
list — including SHADOW_SIGNALS — into filter_summary['filtered_picks'], so the
promotion stream (v_bb_candidate_signal_stream) carries shadow tags for every
filtered candidate, not just the post-signal-stage sites.

Zero serve-path change: the picks list is unaffected (the edit only enriches
filtered_picks metadata).

See: docs/08-projects/current/measurement-infrastructure/00-SPEC.md (Component 1)
"""

import pytest

from ml.signals.aggregator import BestBetsAggregator, SHADOW_SIGNALS
from ml.signals.base_signal import SignalResult


def _sig(tag: str, qualifies: bool = True) -> SignalResult:
    return SignalResult(qualifies=qualifies, confidence=0.5, source_tag=tag)


def _pred(**kw) -> dict:
    """Minimal prediction dict; kwargs override defaults."""
    base = {
        'player_lookup': 'player_a',
        'game_id': '20260220_LAL_GSW',
        'player_name': 'Player A',
        'team_abbr': 'LAL',
        'opponent_team_abbr': 'GSW',
        'predicted_points': 14.0,
        'line_value': 20.0,
        'recommendation': 'UNDER',
        'edge': 6.0,
        'confidence_score': 0.85,
        'feature_quality_score': 90,
        'teammate_usage_available': 20,  # triggers med_usage_under (pre-signal block)
        'trend_slope': 2.0,
        'is_home': True,  # avoid under_star_away on line>=23 away picks
    }
    base.update(kw)
    return base


def _signals_for(pred, tags):
    key = f"{pred['player_lookup']}::{pred['game_id']}"
    return {key: [_sig(t) for t in tags]}


def _find_filtered(summary, reason):
    return [f for f in summary['filtered_picks'] if f['filter_reason'] == reason]


class TestShadowTagPersistence:
    def test_pre_signal_block_records_full_tag_list(self):
        """med_usage_under is a pre-signal-stage block that passes NO sig_tags.
        After C1 its filtered record carries the full qualifying tag list."""
        pred = _pred()
        tags = ['model_health', 'b2b_fatigue_under', 'home_under', 'whole_line_precision']
        signals = _signals_for(pred, tags)
        agg = BestBetsAggregator()
        picks, summary = agg.aggregate([pred], signals)

        assert len(picks) == 0  # med_usage_under blocks
        recs = _find_filtered(summary, 'med_usage_under')
        assert len(recs) == 1, "expected one med_usage_under filtered record"
        assert set(recs[0]['signal_tags']) == set(tags), (
            "pre-signal filter must persist the full qualifying tag list"
        )

    def test_shadow_tags_specifically_present(self):
        """The SHADOW_SIGNALS in the candidate's signals appear on the record —
        this is the whole point (shadow evals only exist in memory otherwise)."""
        pred = _pred()
        shadow = ['b2b_fatigue_under', 'whole_line_precision', 'national_tv_under']
        assert all(s in SHADOW_SIGNALS for s in shadow)
        signals = _signals_for(pred, ['model_health'] + shadow)
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], signals)

        recs = _find_filtered(summary, 'med_usage_under')
        assert len(recs) == 1
        for s in shadow:
            assert s in recs[0]['signal_tags'], f"shadow tag {s} missing from record"

    def test_only_qualifying_signals_persisted(self):
        """Non-qualifying signals are excluded (mirrors the post-stage tag list)."""
        pred = _pred()
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _sig('model_health', qualifies=True),
            _sig('b2b_fatigue_under', qualifies=True),
            _sig('downtrend_under', qualifies=False),  # not qualifying → excluded
        ]}
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], signals)
        recs = _find_filtered(summary, 'med_usage_under')
        assert set(recs[0]['signal_tags']) == {'model_health', 'b2b_fatigue_under'}

    def test_empty_signal_results_records_empty_tags(self):
        """No signals for the candidate → empty tag list, no crash."""
        pred = _pred()
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], {})  # empty signal_results
        recs = _find_filtered(summary, 'med_usage_under')
        assert len(recs) == 1
        assert recs[0]['signal_tags'] == []

    def test_explicit_tags_not_overridden(self):
        """Post-signal-stage sites that pass an explicit tag list keep it — the
        fallback only fires when sig_tags is None. A signal_count reject (which
        passes tags explicitly) must reflect exactly the qualifying tags."""
        pred = _pred(teammate_usage_available=0)  # avoid the pre-signal block
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        # Only 1 qualifying signal → below required SC → signal_count reject
        signals = {key: [_sig('model_health')]}
        agg = BestBetsAggregator()
        _, summary = agg.aggregate([pred], signals)
        recs = _find_filtered(summary, 'signal_count')
        assert len(recs) == 1
        assert recs[0]['signal_tags'] == ['model_health']


class TestServePathUnchanged:
    """C1 is metadata-only: the selected picks must be identical to pre-C1."""

    def test_passing_pick_still_selected_with_shadow_tags_present(self):
        """A pick that passes all filters is selected regardless of shadow tags
        in signal_results — the filtered_picks enrichment never touches picks."""
        pred = _pred(teammate_usage_available=0, line_value=26.0)
        key = f"{pred['player_lookup']}::{pred['game_id']}"
        signals = {key: [
            _sig('model_health'),
            _sig('combo_he_ms'),
            _sig('rest_advantage_2d'),
            _sig('whole_line_precision'),  # shadow — must not affect selection
            _sig('home_under'),
        ]}
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate([pred], signals)
        assert len(picks) == 1
        assert picks[0]['player_lookup'] == 'player_a'
        assert picks[0]['recommendation'] == 'UNDER'

    def test_selection_deterministic_multi_pred(self):
        """Golden regression pin: fixed input → fixed selected (player, rec, edge).
        Guards the serve path against accidental selection drift."""
        preds = [
            _pred(player_lookup='p_win', line_value=26.0, edge=6.0,
                  teammate_usage_available=0),
            _pred(player_lookup='p_edgefloor', edge=2.0,
                  teammate_usage_available=0),       # dropped: edge floor
            _pred(player_lookup='p_medusage', edge=6.0),  # dropped: med_usage_under
        ]
        signals = {}
        for p in preds:
            signals[f"{p['player_lookup']}::{p['game_id']}"] = [
                _sig('model_health'), _sig('combo_he_ms'),
                _sig('rest_advantage_2d'), _sig('home_under'),
                _sig('b2b_fatigue_under'),  # shadow present on all
            ]
        agg = BestBetsAggregator()
        picks, _ = agg.aggregate(preds, signals)
        selected = {(p['player_lookup'], p['recommendation']) for p in picks}
        assert selected == {('p_win', 'UNDER')}
