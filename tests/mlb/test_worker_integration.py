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
        # Reset worker-level singleton (predictor cache)
        import predictions.mlb.worker as worker_module
        worker_module._prediction_systems = None
        # Reset config singleton — env-var changes via @patch.dict won't take
        # effect on a subsequent call to get_config() if the cached config was
        # built with a different MLB_ACTIVE_SYSTEMS in a prior test.
        from predictions.mlb.config import reset_config
        reset_config()

    # ========================================================================
    # System Registry Tests
    # ========================================================================
    #
    # NOTE on patch targets: worker.py imports predictor classes INSIDE
    # get_prediction_systems() (lazy import — avoids loading heavy ML modules
    # at process start, supports optional systems). Mocks must target the
    # source modules, NOT predictions.mlb.worker, because the names aren't
    # in worker's module namespace.

    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor')
    def test_get_prediction_systems_single_system(self, mock_v1_class):
        """Test system registry with single active system"""
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        systems = get_prediction_systems()

        assert len(systems) == 1
        assert 'v1_baseline' in systems
        mock_v1_instance.load_model.assert_called_once()

    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline,v1_6_rolling'})
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor')
    @patch('predictions.mlb.prediction_systems.v1_6_rolling_predictor.V1_6RollingPredictor')
    def test_get_prediction_systems_two_systems(self, mock_v1_6_class, mock_v1_class):
        """Test system registry with two active systems"""
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

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
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor')
    @patch('predictions.mlb.prediction_systems.v1_6_rolling_predictor.V1_6RollingPredictor')
    @patch('predictions.mlb.prediction_systems.ensemble_v1.MLBEnsembleV1')
    def test_get_prediction_systems_all_systems(self, mock_ensemble_class, mock_v1_6_class, mock_v1_class):
        """Test system registry with all active systems including ensemble"""
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        mock_v1_6_instance = MagicMock()
        mock_v1_6_instance.load_model.return_value = True
        mock_v1_6_class.return_value = mock_v1_6_instance

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
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor')
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

    # ========================================================================
    # Multi-System Batch Prediction Tests
    # ========================================================================
    #
    # NOTE on the new flow (Session ~519): run_multi_system_batch_predictions
    # no longer routes through PitcherStrikeoutsPredictor.batch_predict.
    # Features come from pitcher_loader.load_batch_features and predictions
    # are produced by predictor.predict() one pitcher × system at a time.
    # Tests mock the loaders to return features and exercise per-predictor
    # predict() return values.

    @staticmethod
    def _features_for(pitcher_lookup, team_abbr='NYY', opponent='BOS', line=6.5):
        return {
            pitcher_lookup: {
                'team_abbr': team_abbr,
                'opponent_team_abbr': opponent,
                'strikeouts_line': line,
            }
        }

    @patch('predictions.mlb.supplemental_loader.load_supplemental_by_pitcher')
    @patch('predictions.mlb.pitcher_loader.load_schedule_context')
    @patch('predictions.mlb.pitcher_loader.load_batch_features')
    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor')
    def test_run_multi_system_batch_single_pitcher(
        self, mock_v1_class, mock_load_features, mock_load_schedule, mock_load_supp
    ):
        """Test batch predictions for single pitcher with single system"""
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_instance.predict.return_value = {
            'pitcher_lookup': 'gerrit_cole',
            'predicted_strikeouts': 6.5,
            'confidence': 75,
            'recommendation': 'OVER',
            'model_version': 'v1_test',
        }
        mock_v1_class.return_value = mock_v1_instance

        mock_load_features.return_value = self._features_for('gerrit_cole')
        mock_load_schedule.return_value = ({}, {})
        mock_load_supp.return_value = {}

        test_date = date(2026, 1, 20)
        predictions = run_multi_system_batch_predictions(test_date)

        assert len(predictions) == 1
        assert predictions[0]['pitcher_lookup'] == 'gerrit_cole'
        assert predictions[0]['system_id'] == 'v1_baseline'
        assert predictions[0]['game_date'] == '2026-01-20'

    @patch('predictions.mlb.supplemental_loader.load_supplemental_by_pitcher')
    @patch('predictions.mlb.pitcher_loader.load_schedule_context')
    @patch('predictions.mlb.pitcher_loader.load_batch_features')
    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor')
    def test_run_multi_system_batch_multiple_pitchers(
        self, mock_v1_class, mock_load_features, mock_load_schedule, mock_load_supp
    ):
        """Test batch predictions for multiple pitchers"""
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        # predictor.predict is called per pitcher — return shape per call
        mock_v1_instance.predict.side_effect = lambda pitcher_lookup, features, strikeouts_line: {
            'pitcher_lookup': pitcher_lookup,
            'predicted_strikeouts': 7.0,
            'confidence': 75,
            'recommendation': 'OVER',
        }
        mock_v1_class.return_value = mock_v1_instance

        features = {
            **self._features_for('gerrit_cole', 'NYY', 'BOS'),
            **self._features_for('shohei_ohtani', 'LAD', 'SD'),
        }
        mock_load_features.return_value = features
        mock_load_schedule.return_value = ({}, {})
        mock_load_supp.return_value = {}

        test_date = date(2026, 1, 20)
        predictions = run_multi_system_batch_predictions(test_date)

        assert len(predictions) == 2
        pitcher_lookups = {p['pitcher_lookup'] for p in predictions}
        assert pitcher_lookups == {'gerrit_cole', 'shohei_ohtani'}
        # system_id annotated by the worker, not the predictor
        assert all(p['system_id'] == 'v1_baseline' for p in predictions)

    @patch('predictions.mlb.supplemental_loader.load_supplemental_by_pitcher')
    @patch('predictions.mlb.pitcher_loader.load_schedule_context')
    @patch('predictions.mlb.pitcher_loader.load_batch_features')
    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline'})
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor')
    def test_run_multi_system_batch_no_pitchers(
        self, mock_v1_class, mock_load_features, mock_load_schedule, mock_load_supp
    ):
        """Test batch predictions when feature loader returns no pitchers"""
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_class.return_value = mock_v1_instance

        mock_load_features.return_value = {}
        mock_load_schedule.return_value = ({}, {})
        mock_load_supp.return_value = {}

        test_date = date(2026, 1, 20)
        predictions = run_multi_system_batch_predictions(test_date)

        assert predictions == []
        # When no pitchers, predictor.predict should never be called
        mock_v1_instance.predict.assert_not_called()

    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': ''})  # no active systems
    def test_run_multi_system_batch_no_systems(self):
        """Test batch predictions when no systems configured.

        When MLB_ACTIVE_SYSTEMS is empty, get_prediction_systems() returns {} and
        run_multi_system_batch_predictions short-circuits before loading features.
        """
        test_date = date(2026, 1, 20)
        predictions = run_multi_system_batch_predictions(test_date)
        assert predictions == []

    # ========================================================================
    # Circuit Breaker Tests
    # ========================================================================

    @patch('predictions.mlb.supplemental_loader.load_supplemental_by_pitcher')
    @patch('predictions.mlb.pitcher_loader.load_schedule_context')
    @patch('predictions.mlb.pitcher_loader.load_batch_features')
    @patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': 'v1_baseline,v1_6_rolling'})
    @patch('predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor')
    @patch('predictions.mlb.prediction_systems.v1_6_rolling_predictor.V1_6RollingPredictor')
    def test_circuit_breaker_continues_on_error(
        self, mock_v1_6_class, mock_v1_class, mock_load_features, mock_load_schedule, mock_load_supp
    ):
        """Test that if one system fails, others continue (circuit breaker pattern)"""
        # V1 works
        mock_v1_instance = MagicMock()
        mock_v1_instance.load_model.return_value = True
        mock_v1_instance.predict.return_value = {
            'pitcher_lookup': 'gerrit_cole',
            'predicted_strikeouts': 6.5,
        }
        mock_v1_class.return_value = mock_v1_instance

        # V1.6 fails on predict()
        mock_v1_6_instance = MagicMock()
        mock_v1_6_instance.load_model.return_value = True
        mock_v1_6_instance.predict.side_effect = Exception("Model failed")
        mock_v1_6_class.return_value = mock_v1_6_instance

        mock_load_features.return_value = self._features_for('gerrit_cole')
        mock_load_schedule.return_value = ({}, {})
        mock_load_supp.return_value = {}

        test_date = date(2026, 1, 20)

        # Should not raise — circuit breaker catches V1.6's exception
        predictions = run_multi_system_batch_predictions(test_date)

        # V1.6's prediction skipped, V1's still landed
        assert len(predictions) == 1
        assert predictions[0]['system_id'] == 'v1_baseline'

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
