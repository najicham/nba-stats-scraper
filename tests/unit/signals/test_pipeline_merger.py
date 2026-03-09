"""Tests for pipeline_merger.py — Session 452+: game cap + slate observations."""

import pytest

from ml.signals.pipeline_merger import (
    MAX_PICKS_PER_GAME,
    MAX_PICKS_PER_TEAM,
    merge_model_pipelines,
    _compute_slate_observations,
)


def _make_candidate(
    player: str,
    team: str,
    game_id: str,
    composite_score: float = 10.0,
    recommendation: str = 'OVER',
    rescued: bool = False,
    rescue_signal: str = None,
    source_pipeline: str = 'model_a',
):
    """Build a minimal candidate dict for merger tests."""
    return {
        'player_lookup': player,
        'team_abbr': team,
        'game_id': game_id,
        'composite_score': composite_score,
        'recommendation': recommendation,
        'source_pipeline': source_pipeline,
        'signal_rescued': rescued,
        'rescue_signal': rescue_signal,
        'edge': composite_score,
    }


class TestGameCap:
    """Session 452: Game-level cap prevents same-game concentration."""

    def test_game_cap_limits_picks_from_same_game(self):
        """4 picks from same game (2 per team) should be capped to 3."""
        candidates = {
            'model_a': [
                _make_candidate('p1', 'SAS', 'g1', composite_score=10),
                _make_candidate('p2', 'SAS', 'g1', composite_score=9),
                _make_candidate('p3', 'HOU', 'g1', composite_score=8),
                _make_candidate('p4', 'HOU', 'g1', composite_score=7),
            ],
        }
        selected, summary = merge_model_pipelines(candidates, max_per_game=3)
        assert len(selected) == 3
        # p4 should be the one dropped (lowest composite, game cap hit)
        selected_players = {p['player_lookup'] for p in selected}
        assert 'p4' not in selected_players
        assert summary['rejection_counts'].get('game_cap', 0) == 1

    def test_game_cap_does_not_affect_different_games(self):
        """Picks from different games should not trigger game cap."""
        candidates = {
            'model_a': [
                _make_candidate('p1', 'SAS', 'g1', composite_score=10),
                _make_candidate('p2', 'HOU', 'g1', composite_score=9),
                _make_candidate('p3', 'BOS', 'g2', composite_score=8),
                _make_candidate('p4', 'CLE', 'g2', composite_score=7),
            ],
        }
        selected, summary = merge_model_pipelines(candidates, max_per_game=3)
        assert len(selected) == 4
        assert summary['rejection_counts'].get('game_cap', 0) == 0

    def test_game_cap_3_picks_all_pass(self):
        """Exactly 3 picks from same game (within team cap) should all pass."""
        candidates = {
            'model_a': [
                _make_candidate('p1', 'SAS', 'g1', composite_score=10),
                _make_candidate('p2', 'HOU', 'g1', composite_score=9),
                _make_candidate('p3', 'SAS', 'g1', composite_score=8),
            ],
        }
        # p1 (SAS#1), p2 (HOU#1), p3 (SAS#2) — all within both caps
        selected, summary = merge_model_pipelines(candidates, max_per_game=3)
        assert len(selected) == 3
        assert summary['rejection_counts'].get('game_cap', 0) == 0
        assert summary['rejection_counts'].get('team_cap', 0) == 0

    def test_game_cap_interacts_with_team_cap(self):
        """Team cap fires first when 2+ from same team, game cap is secondary."""
        candidates = {
            'model_a': [
                _make_candidate('p1', 'SAS', 'g1', composite_score=10),
                _make_candidate('p2', 'SAS', 'g1', composite_score=9),
                _make_candidate('p3', 'SAS', 'g1', composite_score=8),  # team cap
                _make_candidate('p4', 'HOU', 'g1', composite_score=7),
                _make_candidate('p5', 'HOU', 'g1', composite_score=6),  # team cap
                _make_candidate('p6', 'HOU', 'g1', composite_score=5),  # team cap (already seen)
            ],
        }
        selected, summary = merge_model_pipelines(
            candidates, max_per_game=3, max_per_team=2,
        )
        # p1 (SAS), p2 (SAS=2), p4 (HOU) pass. p3 team_cap, p5 game_cap (3 already), p6 team_cap
        assert len(selected) == 3
        selected_players = {p['player_lookup'] for p in selected}
        assert selected_players == {'p1', 'p2', 'p4'}

    def test_missing_game_id_bypasses_game_cap(self):
        """Picks without game_id should not be affected by game cap."""
        candidates = {
            'model_a': [
                _make_candidate('p1', 'SAS', '', composite_score=10),
                _make_candidate('p2', 'HOU', '', composite_score=9),
                _make_candidate('p3', 'BOS', '', composite_score=8),
                _make_candidate('p4', 'CLE', '', composite_score=7),
            ],
        }
        selected, summary = merge_model_pipelines(candidates, max_per_game=2)
        assert len(selected) == 4
        assert summary['rejection_counts'].get('game_cap', 0) == 0

    def test_default_game_cap_is_3(self):
        """Default MAX_PICKS_PER_GAME should be 3."""
        assert MAX_PICKS_PER_GAME == 3


class TestSlateObservations:
    """Session 453: Slate-level structural observations."""

    def test_heavy_over_lean(self):
        """80%+ OVER picks with 5+ total should tag slate_heavy_over_lean."""
        picks = [
            {'recommendation': 'OVER', 'game_id': f'g{i}'} for i in range(5)
        ]
        result = _compute_slate_observations(picks, {f'g{i}': 1 for i in range(5)})
        assert 'slate_heavy_over_lean' in result['tags']

    def test_heavy_under_lean(self):
        """80%+ UNDER picks with 5+ total should tag slate_heavy_under_lean."""
        picks = [
            {'recommendation': 'UNDER', 'game_id': f'g{i}'} for i in range(5)
        ]
        result = _compute_slate_observations(picks, {f'g{i}': 1 for i in range(5)})
        assert 'slate_heavy_under_lean' in result['tags']

    def test_no_lean_at_60_pct(self):
        """60% OVER should NOT trigger directional lean."""
        picks = [
            {'recommendation': 'OVER', 'game_id': f'g{i}'} for i in range(3)
        ] + [
            {'recommendation': 'UNDER', 'game_id': f'g{i}'} for i in range(3, 5)
        ]
        result = _compute_slate_observations(picks, {f'g{i}': 1 for i in range(5)})
        assert 'slate_heavy_over_lean' not in result['tags']
        assert 'slate_heavy_under_lean' not in result['tags']

    def test_no_lean_with_few_picks(self):
        """Even 100% OVER should NOT trigger with <5 picks."""
        picks = [
            {'recommendation': 'OVER', 'game_id': f'g{i}'} for i in range(3)
        ]
        result = _compute_slate_observations(picks, {f'g{i}': 1 for i in range(3)})
        assert 'slate_heavy_over_lean' not in result['tags']

    def test_same_game_same_direction(self):
        """2+ picks from same game in same direction should tag."""
        picks = [
            {'recommendation': 'OVER', 'game_id': 'g1', 'player_lookup': 'p1'},
            {'recommendation': 'OVER', 'game_id': 'g1', 'player_lookup': 'p2'},
        ]
        result = _compute_slate_observations(picks, {'g1': 2})
        assert 'slate_same_game_same_dir' in result['tags']

    def test_same_game_different_direction_no_tag(self):
        """Picks from same game in opposite directions should NOT tag same_dir."""
        picks = [
            {'recommendation': 'OVER', 'game_id': 'g1'},
            {'recommendation': 'UNDER', 'game_id': 'g1'},
        ]
        result = _compute_slate_observations(picks, {'g1': 2})
        assert 'slate_same_game_same_dir' not in result['tags']

    def test_game_concentration(self):
        """3+ picks from one game should tag slate_game_concentration."""
        picks = [
            {'recommendation': 'OVER', 'game_id': 'g1'},
            {'recommendation': 'UNDER', 'game_id': 'g1'},
            {'recommendation': 'OVER', 'game_id': 'g1'},
        ]
        result = _compute_slate_observations(picks, {'g1': 3})
        assert 'slate_game_concentration' in result['tags']

    def test_empty_slate(self):
        """Empty slate should return empty tags."""
        result = _compute_slate_observations([], {})
        assert result['tags'] == []

    def test_slate_obs_on_merged_picks(self):
        """Slate observations should be attached to selected picks after merge."""
        candidates = {
            'model_a': [
                _make_candidate('p1', 'SAS', 'g1', composite_score=10, recommendation='OVER'),
                _make_candidate('p2', 'HOU', 'g1', composite_score=9, recommendation='OVER'),
                _make_candidate('p3', 'BOS', 'g2', composite_score=8, recommendation='OVER'),
                _make_candidate('p4', 'CLE', 'g2', composite_score=7, recommendation='OVER'),
                _make_candidate('p5', 'LAL', 'g3', composite_score=6, recommendation='OVER'),
            ],
        }
        selected, summary = merge_model_pipelines(candidates)
        # 5 OVER picks = 100% lean
        assert 'slate_heavy_over_lean' in summary['slate_observations']['tags']
        # All picks should have the observation tags
        for pick in selected:
            assert 'slate_observation_tags' in pick
