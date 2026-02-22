"""
Unit Tests for SignalBestBetsExporter

Tests cover:
1. 0-prediction path includes all metadata fields
2. filter_summary and edge_distribution in output
3. Status exporter best_bets service check
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


class TestZeroPredictionPath:
    """Test that the 0-prediction early return includes full metadata."""

    def _make_exporter(self):
        """Create exporter with all external calls mocked."""
        with patch('data_processors.publishing.signal_best_bets_exporter.get_signal_health_summary') as mock_sh, \
             patch('data_processors.publishing.signal_best_bets_exporter.compute_player_blacklist') as mock_bl, \
             patch('data_processors.publishing.signal_best_bets_exporter.query_model_health') as mock_mh, \
             patch('data_processors.publishing.signal_best_bets_exporter.query_predictions_with_supplements') as mock_preds, \
             patch('data_processors.publishing.base_exporter.storage.Client'), \
             patch('data_processors.publishing.signal_best_bets_exporter.get_best_bets_model_id', return_value='catboost_v9'):

            from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter
            exporter = SignalBestBetsExporter()

            # Mock model health
            mock_mh.return_value = {'hit_rate_7d_edge3': 65.0, 'graded_count': 50}

            # Mock 0 predictions
            mock_preds.return_value = ([], {})

            # Mock signal health
            mock_sh.return_value = {'high_edge': {'regime': 'NORMAL'}}

            # Mock player blacklist
            mock_bl.return_value = (set(), {'evaluated': 10, 'blacklisted': 0, 'players': []})

            # Mock direction health
            exporter._query_direction_health = Mock(return_value={
                'over_hr_14d': 60.0, 'under_hr_14d': 55.0, 'over_n': 20, 'under_n': 15
            })

            # Mock record
            exporter._get_best_bets_record = Mock(return_value={
                'season': {'wins': 10, 'losses': 5, 'pct': 66.7},
                'month': {'wins': 3, 'losses': 2, 'pct': 60.0},
                'week': {'wins': 1, 'losses': 0, 'pct': 100.0},
            })

            result = exporter.generate_json('2026-02-20')

        return result

    def test_zero_pred_has_record(self):
        result = self._make_exporter()
        assert 'record' in result
        assert result['record']['season']['wins'] == 10

    def test_zero_pred_has_signal_health(self):
        result = self._make_exporter()
        assert 'signal_health' in result
        assert 'high_edge' in result['signal_health']

    def test_zero_pred_has_direction_health(self):
        result = self._make_exporter()
        assert 'direction_health' in result
        assert result['direction_health']['over_hr_14d'] == 60.0

    def test_zero_pred_has_player_blacklist(self):
        result = self._make_exporter()
        assert 'player_blacklist' in result
        assert result['player_blacklist']['evaluated'] == 10

    def test_zero_pred_has_min_signal_count(self):
        result = self._make_exporter()
        assert 'min_signal_count' in result

    def test_zero_pred_has_filter_summary(self):
        result = self._make_exporter()
        assert 'filter_summary' in result
        assert result['filter_summary']['total_candidates'] == 0
        assert result['filter_summary']['passed_filters'] == 0
        assert result['filter_summary']['rejected'] == {}

    def test_zero_pred_has_edge_distribution(self):
        result = self._make_exporter()
        assert 'edge_distribution' in result
        assert result['edge_distribution']['total_predictions'] == 0
        assert result['edge_distribution']['max_edge'] is None

    def test_zero_pred_still_has_picks_and_total(self):
        result = self._make_exporter()
        assert result['picks'] == []
        assert result['total_picks'] == 0


class TestHealthGate:
    """Test that health gate blocks picks when model HR < breakeven."""

    def _make_blocked_exporter(self):
        """Create exporter with model health BLOCKED (HR below breakeven)."""
        with patch('data_processors.publishing.signal_best_bets_exporter.get_signal_health_summary') as mock_sh, \
             patch('data_processors.publishing.signal_best_bets_exporter.compute_player_blacklist') as mock_bl, \
             patch('data_processors.publishing.signal_best_bets_exporter.query_model_health') as mock_mh, \
             patch('data_processors.publishing.signal_best_bets_exporter.query_predictions_with_supplements') as mock_preds, \
             patch('data_processors.publishing.base_exporter.storage.Client'), \
             patch('data_processors.publishing.signal_best_bets_exporter.get_best_bets_model_id', return_value='catboost_v9'):

            from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter
            exporter = SignalBestBetsExporter()

            # Model health BELOW breakeven (52.4%)
            mock_mh.return_value = {'hit_rate_7d_edge3': 45.0, 'graded_count': 30}

            # These should NOT be called (early return before predictions query)
            mock_preds.return_value = (
                [{'player_lookup': 'should_not_appear', 'game_id': 'g1',
                  'edge': 8.0, 'recommendation': 'OVER'}],
                {},
            )

            mock_sh.return_value = {'high_edge': {'regime': 'HOT'}}
            mock_bl.return_value = (set(), {'evaluated': 5, 'blacklisted': 1, 'players': []})

            exporter._query_direction_health = Mock(return_value={
                'over_hr_14d': 50.0, 'under_hr_14d': 40.0, 'over_n': 10, 'under_n': 10
            })
            exporter._get_best_bets_record = Mock(return_value={
                'season': {'wins': 20, 'losses': 15, 'pct': 57.1},
                'month': {'wins': 2, 'losses': 5, 'pct': 28.6},
                'week': {'wins': 0, 'losses': 3, 'pct': 0.0},
            })

            result = exporter.generate_json('2026-02-20')

            # Verify predictions were NOT queried (early return before Step 2)
            mock_preds.assert_not_called()

        return result

    def test_health_gate_returns_zero_picks(self):
        result = self._make_blocked_exporter()
        assert result['picks'] == []
        assert result['total_picks'] == 0

    def test_health_gate_flag_present(self):
        result = self._make_blocked_exporter()
        assert result['health_gate_active'] is True
        assert 'below breakeven' in result['health_gate_reason']

    def test_health_gate_preserves_metadata(self):
        result = self._make_blocked_exporter()
        assert result['model_health']['status'] == 'blocked'
        assert result['model_health']['hit_rate_7d'] == 45.0
        assert result['record']['season']['wins'] == 20
        assert result['signal_health'] == {'high_edge': {'regime': 'HOT'}}
        assert result['direction_health']['over_hr_14d'] == 50.0

    def test_health_gate_has_empty_filter_summary(self):
        result = self._make_blocked_exporter()
        assert result['filter_summary']['total_candidates'] == 0
        assert result['edge_distribution']['total_predictions'] == 0


class TestStatusExporterBestBets:
    """Test that status.json includes best_bets service."""

    def test_best_bets_in_services(self):
        with patch('data_processors.publishing.status_exporter.get_bigquery_client'), \
             patch('data_processors.publishing.base_exporter.storage.Client'):
            from data_processors.publishing.status_exporter import StatusExporter
            exporter = StatusExporter()

            exporter._check_live_data_status = Mock(return_value={'status': 'healthy'})
            exporter._check_tonight_data_status = Mock(return_value={'status': 'healthy'})
            exporter._check_grading_status = Mock(return_value={'status': 'healthy'})
            exporter._check_predictions_status = Mock(return_value={'status': 'healthy'})
            exporter._check_best_bets_status = Mock(return_value={
                'status': 'healthy',
                'message': '3 best bets available',
                'total_picks': 3,
                'last_update': '2026-02-20T12:00:00Z',
            })

            result = exporter.generate_json()

            assert 'best_bets' in result['services']
            assert result['services']['best_bets']['total_picks'] == 3

    def test_zero_picks_does_not_degrade_overall(self):
        """0 best bets picks should NOT cause overall_status to degrade."""
        with patch('data_processors.publishing.status_exporter.get_bigquery_client'), \
             patch('data_processors.publishing.base_exporter.storage.Client'):
            from data_processors.publishing.status_exporter import StatusExporter
            exporter = StatusExporter()

            exporter._check_live_data_status = Mock(return_value={'status': 'healthy'})
            exporter._check_tonight_data_status = Mock(return_value={'status': 'healthy'})
            exporter._check_grading_status = Mock(return_value={'status': 'healthy'})
            exporter._check_predictions_status = Mock(return_value={'status': 'healthy'})
            # best_bets is healthy with 0 picks
            exporter._check_best_bets_status = Mock(return_value={
                'status': 'healthy',
                'message': '0 picks today — all candidates filtered out',
                'total_picks': 0,
            })

            result = exporter.generate_json()

            assert result['overall_status'] == 'healthy'

    def test_stale_best_bets_in_known_issues(self):
        """Stale best bets should appear in known_issues."""
        with patch('data_processors.publishing.status_exporter.get_bigquery_client'), \
             patch('data_processors.publishing.base_exporter.storage.Client'):
            from data_processors.publishing.status_exporter import StatusExporter
            exporter = StatusExporter()

            exporter._check_live_data_status = Mock(return_value={'status': 'healthy'})
            exporter._check_tonight_data_status = Mock(return_value={'status': 'healthy'})
            exporter._check_grading_status = Mock(return_value={'status': 'healthy'})
            exporter._check_predictions_status = Mock(return_value={'status': 'healthy'})
            exporter._check_best_bets_status = Mock(return_value={
                'status': 'degraded',
                'message': 'Best bets file stale',
            })

            result = exporter.generate_json()

            assert any(
                'stale' in issue['message'].lower()
                for issue in result['known_issues']
            )

    def test_best_bets_during_break(self):
        """During an active break, best_bets should be healthy."""
        with patch('data_processors.publishing.status_exporter.get_bigquery_client'), \
             patch('data_processors.publishing.base_exporter.storage.Client'):
            from data_processors.publishing.status_exporter import StatusExporter
            exporter = StatusExporter()

            break_info = {
                'headline': 'All-Star Break',
                'message': 'Games resume Thursday, Feb 19',
                'resume_date': '2026-02-19',
                'last_game_date': '2026-02-12'
            }
            exporter._check_active_break = Mock(return_value=break_info)
            exporter._check_live_data_status = Mock(return_value={'status': 'healthy'})
            exporter._check_tonight_data_status = Mock(return_value={'status': 'healthy'})
            exporter._check_grading_status = Mock(return_value={'status': 'healthy'})
            exporter._check_predictions_status = Mock(return_value={'status': 'healthy'})

            # Use real _check_best_bets_status but mock storage
            mock_bucket = MagicMock()
            mock_blob = MagicMock()
            mock_blob.exists.return_value = False
            mock_bucket.blob.return_value = mock_blob
            exporter._get_storage_client = Mock(return_value=MagicMock(
                bucket=Mock(return_value=mock_bucket)
            ))

            result = exporter.generate_json()

            bb = result['services']['best_bets']
            assert bb['status'] == 'healthy'
            assert 'All-Star Break' in bb['message']
