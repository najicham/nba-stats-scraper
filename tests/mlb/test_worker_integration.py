# tests/mlb/test_worker_integration.py
"""
Integration tests for MLB Worker multi-system predictions

Tests end-to-end multi-system prediction flow:
- System registry initialization
- Multi-system batch predictions
- BigQuery write with system_id
- Circuit breaker pattern
"""

import pytest
from datetime import date
from unittest.mock import Mock, MagicMock, patch
from predictions.mlb.worker import get_prediction_systems, run_multi_system_batch_predictions


class TestWorkerIntegration:
    """Integration tests for worker with multi-system support"""

    def teardown_method(self):
        """Cleanup after each test"""
        # Reset global singleton
        import predictions.mlb.worker as worker_module
        worker_module._prediction_systems = None

    # ========================================================================
    # System Registry Tests
    # ========================================================================

    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.worker.V1BaselinePredictor')
    def test_get_prediction_systems_single_system(self, mock_v1_class):
        """Test system registry with single active system"""
        # Mock V1 predictor
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        systems = get_prediction_systems()

        assert len(systems) == 1
        assert 'v1_baseline' in systems
        mock_v1_instance.load_model.assert_called_once()

    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline,v1_6_rolling'})
    @patch('predictions.mlb.worker.V1BaselinePredictor')
    @patch('predictions.mlb.worker.V1_6RollingPredictor')
    def test_get_prediction_systems_two_systems(self, mock_v1_6_class, mock_v1_class):
        """Test system registry with two active systems"""
        # Mock V1 predictor
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        # Mock V1.6 predictor
        mock_v1_6_instance = MagicMock()
        mock_v1_6_instance.load_model.return_value = True
        mock_v1_6_class.return_value = mock_v1_6_instance

        systems = get_prediction_systems()

        assert len(systems) == 2
        assert 'v1_baseline' in systems
        assert 'v1_6_rolling' in systems
        mock_v1_instance.load_model.assert_called_once()
        mock_v1_6_instance.load_model.assert_called_once()

    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline,v1_6_rolling,ensemble_v1'})
    @patch('predictions.mlb.worker.V1BaselinePredictor')
    @patch('predictions.mlb.worker.V1_6RollingPredictor')
    @patch('predictions.mlb.worker.MLBEnsembleV1')
    def test_get_prediction_systems_all_systems(self, mock_ensemble_class, mock_v1_6_class, mock_v1_class):
        """Test system registry with all active systems including ensemble"""
        # Mock V1 predictor
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        # Mock V1.6 predictor
        mock_v1_6_instance = MagicMock()
        mock_v1_6_instance.load_model.return_value = True
        mock_v1_6_class.return_value = mock_v1_6_instance

        # Mock ensemble predictor
        mock_ensemble_instance = MagicMock()
        mock_ensemble_class.return_value = mock_ensemble_instance

        systems = get_prediction_systems()

        assert len(systems) == 3
        assert 'v1_baseline' in systems
        assert 'v1_6_rolling' in systems
        assert 'ensemble_v1' in systems

        # Ensemble should be initialized with V1 and V1.6 as dependencies
        mock_ensemble_class.assert_called_once()
        call_kwargs = mock_ensemble_class.call_args[1]
        assert 'v1_predictor' in call_kwargs
        assert 'v1_6_predictor' in call_kwargs

    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.worker.V1BaselinePredictor')
    def test_get_prediction_systems_singleton(self, mock_v1_class):
        """Test system registry is singleton"""
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        systems1 = get_prediction_systems()
        systems2 = get_prediction_systems()

        assert systems1 is systems2
        # Should only initialize once
        assert mock_v1_class.call_count == 1

    # ========================================================================
    # Multi-System Batch Prediction Tests
    # ========================================================================

    @patch('predictions.mlb.worker.PitcherStrikeoutsPredictor')
    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.worker.V1BaselinePredictor')
    def test_run_multi_system_batch_single_pitcher(self, mock_v1_class, mock_legacy_predictor_class):
        """Test batch predictions for single pitcher with single system"""
        # Mock V1 predictor
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        # Mock legacy predictor for feature loading
        mock_legacy_instance = MagicMock()
        mock_legacy_predictor_class.return_value = mock_legacy_instance
        mock_legacy_instance.batch_predict.return_value = [
            {
                'pitcher_lookup': 'gerrit-cole',
                'predicted_strikeouts': 6.5,
                'confidence': 75,
                'recommendation': 'OVER',
                'model_version': 'v1_test',
                'game_date': '2026-01-20',
                'team_abbr': 'NYY',
                'opponent_team_abbr': 'BOS'
            }
        ]

        test_date = date(2026, 1, 20)
        predictions = run_multi_system_batch_predictions(test_date)

        assert len(predictions) == 1
        assert predictions[0]['pitcher_lookup'] == 'gerrit-cole'
        assert predictions[0]['system_id'] == 'v1_baseline'

    @patch('predictions.mlb.worker.PitcherStrikeoutsPredictor')
    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.worker.V1BaselinePredictor')
    def test_run_multi_system_batch_multiple_pitchers(self, mock_v1_class, mock_legacy_predictor_class):
        """Test batch predictions for multiple pitchers"""
        # Mock V1 predictor
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        # Mock legacy predictor for feature loading
        mock_legacy_instance = MagicMock()
        mock_legacy_predictor_class.return_value = mock_legacy_instance
        mock_legacy_instance.batch_predict.return_value = [
            {
                'pitcher_lookup': 'gerrit-cole',
                'predicted_strikeouts': 6.5,
                'confidence': 75,
                'recommendation': 'OVER',
                'system_id': 'v1_baseline'
            },
            {
                'pitcher_lookup': 'shohei-ohtani',
                'predicted_strikeouts': 7.2,
                'confidence': 80,
                'recommendation': 'OVER',
                'system_id': 'v1_baseline'
            }
        ]

        test_date = date(2026, 1, 20)
        predictions = run_multi_system_batch_predictions(test_date)

        assert len(predictions) == 2
        pitcher_lookups = {p['pitcher_lookup'] for p in predictions}
        assert 'gerrit-cole' in pitcher_lookups
        assert 'shohei-ohtani' in pitcher_lookups

    @patch('predictions.mlb.worker.PitcherStrikeoutsPredictor')
    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.worker.V1BaselinePredictor')
    def test_run_multi_system_batch_no_pitchers(self, mock_v1_class, mock_legacy_predictor_class):
        """Test batch predictions when no pitchers found"""
        # Mock V1 predictor
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        # Mock legacy predictor returns empty
        mock_legacy_instance = MagicMock()
        mock_legacy_predictor_class.return_value = mock_legacy_instance
        mock_legacy_instance.batch_predict.return_value = []

        test_date = date(2026, 1, 20)
        predictions = run_multi_system_batch_predictions(test_date)

        assert len(predictions) == 0

    @patch('predictions.mlb.worker.PitcherStrikeoutsPredictor')
    @patch.dict('os.environ', {})  # No active systems
    def test_run_multi_system_batch_no_systems(self, mock_legacy_predictor_class):
        """Test batch predictions when no systems configured"""
        test_date = date(2026, 1, 20)
        predictions = run_multi_system_batch_predictions(test_date)

        assert len(predictions) == 0

    # ========================================================================
    # Circuit Breaker Tests
    # ========================================================================

    @patch('predictions.mlb.worker.PitcherStrikeoutsPredictor')
    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline,v1_6_rolling'})
    @patch('predictions.mlb.worker.V1BaselinePredictor')
    @patch('predictions.mlb.worker.V1_6RollingPredictor')
    def test_circuit_breaker_continues_on_error(self, mock_v1_6_class, mock_v1_class, mock_legacy_predictor_class):
        """Test that if one system fails, others continue (circuit breaker pattern)"""
        # Mock V1 predictor (works)
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_instance.predict.return_value = {
            'pitcher_lookup': 'gerrit-cole',
            'predicted_strikeouts': 6.5,
            'system_id': 'v1_baseline'
        }
        mock_v1_class.return_value = mock_v1_instance

        # Mock V1.6 predictor (fails)
        mock_v1_6_instance = MagicMock()
        mock_v1_6_instance.load_model.return_value = True
        mock_v1_6_instance.predict.side_effect = Exception("Model failed")
        mock_v1_6_class.return_value = mock_v1_6_instance

        # Mock legacy predictor for feature loading
        mock_legacy_instance = MagicMock()
        mock_legacy_predictor_class.return_value = mock_legacy_instance
        mock_legacy_instance.batch_predict.return_value = [
            {
                'pitcher_lookup': 'gerrit-cole',
                'predicted_strikeouts': 6.5,
                'system_id': 'v1_baseline'
            }
        ]

        test_date = date(2026, 1, 20)

        # Should not raise exception - circuit breaker catches it
        predictions = run_multi_system_batch_predictions(test_date)

        # Should still have V1 predictions even though V1.6 failed
        assert len(predictions) >= 1

    # ========================================================================
    # BigQuery Write Tests
    # ========================================================================

    @patch('predictions.mlb.worker.get_bq_client')
    def test_write_predictions_to_bigquery_includes_system_id(self, mock_get_client):
        """Test BigQuery write includes system_id field"""
        from predictions.mlb.worker import write_predictions_to_bigquery

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.insert_rows_json.return_value = []

        predictions = [
            {
                'pitcher_lookup': 'gerrit-cole',
                'predicted_strikeouts': 6.5,
                'confidence': 75,
                'recommendation': 'OVER',
                'system_id': 'v1_baseline',  # NEW
                'model_version': 'v1_test'
            }
        ]

        test_date = date(2026, 1, 20)
        rows_written = write_predictions_to_bigquery(predictions, test_date)

        assert rows_written == 1
        mock_client.insert_rows_json.assert_called_once()

        # Verify system_id is in the row
        call_args = mock_client.insert_rows_json.call_args
        rows = call_args[0][1]
        assert len(rows) == 1
        assert 'system_id' in rows[0]
        assert rows[0]['system_id'] == 'v1_baseline'

    @patch('predictions.mlb.worker.get_bq_client')
    def test_write_predictions_to_bigquery_multiple_systems(self, mock_get_client):
        """Test BigQuery write with multiple systems per pitcher"""
        from predictions.mlb.worker import write_predictions_to_bigquery

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.insert_rows_json.return_value = []

        predictions = [
            {
                'pitcher_lookup': 'gerrit-cole',
                'predicted_strikeouts': 6.0,
                'system_id': 'v1_baseline',
                'confidence': 70,
                'recommendation': 'PASS'
            },
            {
                'pitcher_lookup': 'gerrit-cole',
                'predicted_strikeouts': 6.8,
                'system_id': 'v1_6_rolling',
                'confidence': 75,
                'recommendation': 'OVER'
            },
            {
                'pitcher_lookup': 'gerrit-cole',
                'predicted_strikeouts': 6.5,
                'system_id': 'ensemble_v1',
                'confidence': 73,
                'recommendation': 'OVER'
            }
        ]

        test_date = date(2026, 1, 20)
        rows_written = write_predictions_to_bigquery(predictions, test_date)

        assert rows_written == 3
        # Verify all 3 rows written with different system_ids
        call_args = mock_client.insert_rows_json.call_args
        rows = call_args[0][1]
        assert len(rows) == 3
        system_ids = {row['system_id'] for row in rows}
        assert system_ids == {'v1_baseline', 'v1_6_rolling', 'ensemble_v1'}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
