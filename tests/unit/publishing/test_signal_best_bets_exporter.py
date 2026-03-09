"""
Unit Tests for SignalBestBetsExporter

Tests cover:
1. 0-prediction path includes all metadata fields (via per-model pipeline)
2. filter_summary and edge_distribution in output
3. Status exporter best_bets service check
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# Mock SharedContext for tests (matches per_model_pipeline.SharedContext)
@dataclass
class _MockSharedContext:
    target_date: str = '2026-02-20'
    all_predictions: Dict[str, List[Dict]] = field(default_factory=dict)
    supplemental_map: Dict[str, Dict] = field(default_factory=dict)
    model_health_map: Dict[str, Optional[float]] = field(default_factory=dict)
    default_model_health_hr: Optional[float] = 65.0
    signal_health: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    combo_registry: Optional[Dict] = None
    player_blacklist: Set[str] = field(default_factory=set)
    blacklist_stats: Dict[str, Any] = field(default_factory=dict)
    model_direction_blocks: Set[tuple] = field(default_factory=set)
    model_direction_affinity_stats: Dict[str, Any] = field(default_factory=dict)
    model_profile_store: Any = None
    regime_context: Dict[str, Any] = field(default_factory=dict)
    games_vs_opponent: Dict[tuple, int] = field(default_factory=dict)
    runtime_demoted_filters: Set[str] = field(default_factory=set)
    direction_health: Dict[str, Any] = field(default_factory=dict)
    opponent_stars_out: Dict[str, int] = field(default_factory=dict)


class TestZeroPredictionPath:
    """Test that the 0-prediction early return includes full metadata."""

    def _make_exporter(self):
        """Create exporter with per-model pipeline returning 0 predictions."""
        # Build a SharedContext with no predictions (0-prediction path)
        shared_ctx = _MockSharedContext(
            target_date='2026-02-20',
            all_predictions={},
            signal_health={'high_edge': {'regime': 'NORMAL'}},
            blacklist_stats={'evaluated': 10, 'blacklisted': 0, 'players': []},
            direction_health={
                'over_hr_14d': 60.0, 'under_hr_14d': 55.0,
                'over_n': 20, 'under_n': 15,
            },
            default_model_health_hr=65.0,
        )

        with patch('data_processors.publishing.signal_best_bets_exporter.run_all_model_pipelines') as mock_pipelines, \
             patch('data_processors.publishing.base_exporter.storage.Client'), \
             patch('data_processors.publishing.signal_best_bets_exporter.get_best_bets_model_id', return_value='catboost_v9'):

            mock_pipelines.return_value = ({}, shared_ctx)

            from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter
            exporter = SignalBestBetsExporter()

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


class TestPerModelPipelineIntegration:
    """Test that per-model pipeline results are correctly merged and formatted.

    Session 443: Replaces the old TestHealthGate class. The health gate was
    removed in Session 347 — model health is now informational only (status
    reported in JSON, does NOT block picks). Per-model pipeline architecture
    handles all model health via shared context.
    """

    def _make_exporter_with_picks(self):
        """Create exporter with per-model pipeline returning picks."""
        shared_ctx = _MockSharedContext(
            target_date='2026-02-20',
            all_predictions={
                'model_a': [
                    {'player_lookup': 'player1', 'game_id': '20260220_ATL_BOS',
                     'edge': 5.0, 'recommendation': 'OVER'},
                ],
            },
            signal_health={'high_edge': {'regime': 'NORMAL'}},
            blacklist_stats={'evaluated': 5, 'blacklisted': 0, 'players': []},
            direction_health={
                'over_hr_14d': 60.0, 'under_hr_14d': 55.0,
                'over_n': 20, 'under_n': 15,
            },
            default_model_health_hr=45.0,  # Below breakeven
        )

        # Mock pipeline result with one candidate
        mock_pick = {
            'player_lookup': 'player1',
            'player_name': 'Test Player',
            'game_id': '20260220_ATL_BOS',
            'team_abbr': 'ATL',
            'opponent_team_abbr': 'BOS',
            'predicted_points': 25.0,
            'line_value': 20.0,
            'recommendation': 'OVER',
            'edge': 5.0,
            'confidence_score': 70.0,
            'system_id': 'model_a',
            'source_pipeline': 'model_a',
            'source_model_id': 'model_a',
            'source_model_family': 'test',
            'composite_score': 8.5,
            'signal_tags': ['high_edge'],
            'signal_count': 1,
            'real_signal_count': 1,
            'rank': 1,
        }

        with patch('data_processors.publishing.signal_best_bets_exporter.run_all_model_pipelines') as mock_pipelines, \
             patch('data_processors.publishing.signal_best_bets_exporter.merge_model_pipelines') as mock_merge, \
             patch('data_processors.publishing.signal_best_bets_exporter.build_pick_angles', return_value=['Edge 5.0']), \
             patch('data_processors.publishing.signal_best_bets_exporter.compute_ultra_live_hrs', return_value={}), \
             patch('data_processors.publishing.signal_best_bets_exporter.check_ultra_over_gate', return_value={'gate_met': False, 'n': 0, 'hr': None}), \
             patch('data_processors.publishing.signal_best_bets_exporter.SignalSubsetMaterializer'), \
             patch('ml.signals.registry.build_default_registry') as mock_registry, \
             patch('data_processors.publishing.base_exporter.storage.Client'), \
             patch('data_processors.publishing.signal_best_bets_exporter.get_best_bets_model_id', return_value='catboost_v9'):

            # Mock PipelineResult
            mock_result = Mock()
            mock_result.candidates = [mock_pick]
            mock_result.all_predictions = shared_ctx.all_predictions['model_a']
            mock_result.filter_summary = {
                'total_candidates': 1, 'passed_filters': 1,
                'rejected': {}, 'filtered_picks': [],
            }
            mock_result.signal_results = {}

            mock_pipelines.return_value = ({'model_a': mock_result}, shared_ctx)
            mock_merge.return_value = ([mock_pick], {
                'total_candidates': 1, 'unique_players': 1,
                'models_contributing': 1, 'selected_count': 1,
                'direction_over': 1, 'direction_under': 0,
                'algorithm_version': 'v443_per_model_pipelines',
            })

            # Mock signal registry for signals_evaluated (inline import)
            mock_signal = Mock()
            mock_signal.tag = 'high_edge'
            mock_registry.return_value.all.return_value = [mock_signal]

            from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter
            exporter = SignalBestBetsExporter()

            exporter._get_best_bets_record = Mock(return_value={
                'season': {'wins': 20, 'losses': 15, 'pct': 57.1},
                'month': {'wins': 2, 'losses': 5, 'pct': 28.6},
                'week': {'wins': 0, 'losses': 3, 'pct': 0.0},
            })
            exporter._filter_started_games = Mock(return_value=([mock_pick], set()))
            exporter._query_game_times = Mock(return_value={})

            result = exporter.generate_json('2026-02-20')

        return result

    def test_below_breakeven_still_returns_picks(self):
        """Session 347: Health gate removed — picks returned even when HR < breakeven."""
        result = self._make_exporter_with_picks()
        assert result['total_picks'] == 1
        assert result['model_health']['status'] == 'blocked'
        assert result['health_gate_active'] is False

    def test_merge_summary_included(self):
        result = self._make_exporter_with_picks()
        assert 'merge_summary' in result
        assert result['merge_summary']['algorithm_version'] == 'v443_per_model_pipelines'

    def test_picks_have_pipeline_provenance(self):
        result = self._make_exporter_with_picks()
        pick = result['picks'][0]
        assert pick['source_model'] == 'model_a'
        assert pick['source_pipeline'] == 'model_a'

    def test_model_bb_candidates_collected(self):
        result = self._make_exporter_with_picks()
        assert '_model_bb_candidates' in result
        assert len(result['_model_bb_candidates']) == 1


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
