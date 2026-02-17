"""Tests for player blacklist — blocks chronically losing players from best bets.

Tests cover:
1. Players below threshold are blacklisted
2. Players above threshold are NOT blacklisted
3. min_picks respected (insufficient picks = not blacklisted)
4. Boundary: exactly 40% HR = NOT blacklisted (strict <)
5. Empty results / query failure returns empty set
6. Custom thresholds work
7. Aggregator integration: blacklisted player excluded from picks

Run with: pytest tests/unit/signals/test_player_blacklist.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from ml.signals.player_blacklist import compute_player_blacklist
from ml.signals.aggregator import BestBetsAggregator, ALGORITHM_VERSION
from ml.signals.base_signal import SignalResult


# ============================================================================
# FIXTURES
# ============================================================================

def _make_bq_row(player_lookup, wins, losses, total_picks, hit_rate):
    """Create a dict mimicking a BigQuery row."""
    return {
        'player_lookup': player_lookup,
        'wins': wins,
        'losses': losses,
        'total_picks': total_picks,
        'hit_rate': hit_rate,
    }


def _mock_bq_client(rows):
    """Create a mock BQ client that returns the given rows."""
    client = Mock()
    result_mock = Mock()
    result_mock.result.return_value = [row for row in rows]
    # Make rows iterable (dict(row) works because rows are already dicts)
    client.query.return_value = result_mock
    return client


# ============================================================================
# compute_player_blacklist TESTS
# ============================================================================

class TestComputePlayerBlacklist:
    """Tests for compute_player_blacklist function."""

    def test_blacklists_player_below_threshold(self):
        """Player with 25% HR on 8 picks should be blacklisted."""
        rows = [
            _make_bq_row('john_doe', wins=2, losses=6, total_picks=8, hit_rate=25.0),
        ]
        client = _mock_bq_client(rows)

        blacklisted, stats = compute_player_blacklist(client, '2026-02-17')

        assert 'john_doe' in blacklisted
        assert stats['blacklisted'] == 1
        assert stats['evaluated'] == 1

    def test_does_not_blacklist_player_above_threshold(self):
        """Player with 60% HR should NOT be blacklisted."""
        rows = [
            _make_bq_row('good_player', wins=6, losses=4, total_picks=10, hit_rate=60.0),
        ]
        client = _mock_bq_client(rows)

        blacklisted, stats = compute_player_blacklist(client, '2026-02-17')

        assert 'good_player' not in blacklisted
        assert stats['blacklisted'] == 0
        assert stats['evaluated'] == 1

    def test_boundary_exactly_40_percent_not_blacklisted(self):
        """Exactly 40% HR = NOT blacklisted (strict less-than)."""
        rows = [
            _make_bq_row('boundary_player', wins=4, losses=6, total_picks=10, hit_rate=40.0),
        ]
        client = _mock_bq_client(rows)

        blacklisted, stats = compute_player_blacklist(client, '2026-02-17')

        assert 'boundary_player' not in blacklisted
        assert stats['blacklisted'] == 0

    def test_boundary_just_below_40_is_blacklisted(self):
        """39.9% HR should be blacklisted."""
        rows = [
            _make_bq_row('almost_player', wins=3, losses=5, total_picks=8, hit_rate=39.9),
        ]
        client = _mock_bq_client(rows)

        blacklisted, stats = compute_player_blacklist(client, '2026-02-17')

        assert 'almost_player' in blacklisted
        assert stats['blacklisted'] == 1

    def test_min_picks_respected_via_query(self):
        """Players with fewer than min_picks are excluded by the SQL HAVING clause.

        The BQ query already filters via HAVING COUNT(*) >= @min_picks,
        so rows returned always meet the threshold. We test that compute
        correctly handles an empty result (no players meet min_picks).
        """
        rows = []  # No rows returned = no players with enough picks
        client = _mock_bq_client(rows)

        blacklisted, stats = compute_player_blacklist(client, '2026-02-17')

        assert len(blacklisted) == 0
        assert stats['evaluated'] == 0

    def test_multiple_players_mixed(self):
        """Mix of good and bad players — only bad ones blacklisted."""
        rows = [
            _make_bq_row('bad_player_1', wins=1, losses=9, total_picks=10, hit_rate=10.0),
            _make_bq_row('good_player', wins=7, losses=3, total_picks=10, hit_rate=70.0),
            _make_bq_row('bad_player_2', wins=3, losses=7, total_picks=10, hit_rate=30.0),
            _make_bq_row('ok_player', wins=5, losses=5, total_picks=10, hit_rate=50.0),
        ]
        client = _mock_bq_client(rows)

        blacklisted, stats = compute_player_blacklist(client, '2026-02-17')

        assert blacklisted == {'bad_player_1', 'bad_player_2'}
        assert stats['blacklisted'] == 2
        assert stats['evaluated'] == 4

    def test_stats_sorted_worst_first(self):
        """Player stats in output should be sorted worst HR first."""
        rows = [
            _make_bq_row('medium_bad', wins=3, losses=7, total_picks=10, hit_rate=30.0),
            _make_bq_row('very_bad', wins=1, losses=9, total_picks=10, hit_rate=10.0),
        ]
        client = _mock_bq_client(rows)

        _, stats = compute_player_blacklist(client, '2026-02-17')

        players = stats['players']
        assert len(players) == 2
        assert players[0]['player_lookup'] == 'very_bad'
        assert players[1]['player_lookup'] == 'medium_bad'

    def test_empty_results_returns_empty_set(self):
        """No rows from query → empty blacklist."""
        client = _mock_bq_client([])

        blacklisted, stats = compute_player_blacklist(client, '2026-02-17')

        assert blacklisted == set()
        assert stats['blacklisted'] == 0

    def test_query_failure_returns_empty_set(self):
        """BigQuery exception → empty blacklist (non-blocking)."""
        client = Mock()
        client.query.side_effect = Exception("BQ timeout")

        blacklisted, stats = compute_player_blacklist(client, '2026-02-17')

        assert blacklisted == set()
        assert stats['blacklisted'] == 0

    def test_custom_thresholds(self):
        """Custom min_picks and hr_threshold work correctly."""
        rows = [
            # 45% HR — would pass default 40% but fail custom 50%
            _make_bq_row('marginal_player', wins=9, losses=11, total_picks=20, hit_rate=45.0),
        ]
        client = _mock_bq_client(rows)

        blacklisted, stats = compute_player_blacklist(
            client, '2026-02-17', hr_threshold=50.0
        )

        assert 'marginal_player' in blacklisted
        assert stats['blacklisted'] == 1

    def test_custom_system_id_passed_to_query(self):
        """system_id parameter is passed to the BQ query."""
        client = _mock_bq_client([])

        compute_player_blacklist(
            client, '2026-02-17', system_id='catboost_v12'
        )

        # Verify the query was called
        assert client.query.called
        call_args = client.query.call_args
        job_config = call_args[1].get('job_config') or call_args[0][1] if len(call_args[0]) > 1 else call_args[1]['job_config']
        # Find the system_id parameter
        params = {p.name: p.value for p in job_config.query_parameters}
        assert params['system_id'] == 'catboost_v12'


# ============================================================================
# AGGREGATOR INTEGRATION TESTS
# ============================================================================

class TestAggregatorBlacklistIntegration:
    """Test that the aggregator respects player_blacklist."""

    def _make_prediction(self, player_lookup, game_id='game1', edge=5.0):
        return {
            'player_lookup': player_lookup,
            'game_id': game_id,
            'player_name': player_lookup.replace('_', ' ').title(),
            'team_abbr': 'LAL',
            'opponent_team_abbr': 'BOS',
            'predicted_points': 25.0,
            'line_value': 20.0,
            'current_points_line': 20.0,
            'recommendation': 'OVER',
            'edge': edge,
            'confidence_score': 0.95,
            'feature_quality_score': 95,
        }

    def _make_qualifying_signals(self, source_tag1='model_health', source_tag2='high_edge'):
        return [
            SignalResult(qualifies=True, confidence=0.8, source_tag=source_tag1),
            SignalResult(qualifies=True, confidence=0.9, source_tag=source_tag2),
        ]

    @patch('ml.signals.aggregator.load_combo_registry', return_value={})
    def test_blacklisted_player_excluded(self, mock_registry):
        """Blacklisted player should not appear in picks."""
        predictions = [
            self._make_prediction('bad_player'),
            self._make_prediction('good_player'),
        ]
        signal_results = {
            'bad_player::game1': self._make_qualifying_signals(),
            'good_player::game1': self._make_qualifying_signals(),
        }

        aggregator = BestBetsAggregator(
            combo_registry={},
            player_blacklist={'bad_player'},
        )
        picks = aggregator.aggregate(predictions, signal_results)

        player_lookups = [p['player_lookup'] for p in picks]
        assert 'bad_player' not in player_lookups
        assert 'good_player' in player_lookups

    @patch('ml.signals.aggregator.load_combo_registry', return_value={})
    def test_no_blacklist_all_players_considered(self, mock_registry):
        """Without blacklist, all qualifying players are considered."""
        predictions = [
            self._make_prediction('player_a'),
            self._make_prediction('player_b'),
        ]
        signal_results = {
            'player_a::game1': self._make_qualifying_signals(),
            'player_b::game1': self._make_qualifying_signals(),
        }

        aggregator = BestBetsAggregator(combo_registry={})
        picks = aggregator.aggregate(predictions, signal_results)

        assert len(picks) == 2

    @patch('ml.signals.aggregator.load_combo_registry', return_value={})
    def test_empty_blacklist_same_as_none(self, mock_registry):
        """Empty blacklist set should not filter anyone."""
        predictions = [self._make_prediction('player_a')]
        signal_results = {
            'player_a::game1': self._make_qualifying_signals(),
        }

        aggregator = BestBetsAggregator(
            combo_registry={},
            player_blacklist=set(),
        )
        picks = aggregator.aggregate(predictions, signal_results)

        assert len(picks) == 1

    def test_algorithm_version_updated(self):
        """ALGORITHM_VERSION should reflect the player blacklist session."""
        assert 'v284' in ALGORITHM_VERSION
        assert 'blacklist' in ALGORITHM_VERSION
