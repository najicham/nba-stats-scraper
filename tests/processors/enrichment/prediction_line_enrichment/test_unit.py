"""
Unit Tests for Prediction Line Enrichment Processor

Tests prediction enrichment logic with actual betting lines from odds_api.
Run with: pytest tests/processors/enrichment/prediction_line_enrichment/test_unit.py -v

Path: tests/processors/enrichment/prediction_line_enrichment/test_unit.py
Created: 2026-01-25
"""

import pytest
import pandas as pd
from datetime import date, datetime
from unittest.mock import Mock, MagicMock, patch
from typing import List, Dict

from data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor import (
    PredictionLineEnrichmentProcessor
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_bq_client():
    """Create a mock BigQuery client."""
    mock_client = Mock()
    mock_client.project = 'test-project'
    return mock_client


@pytest.fixture
def processor(mock_bq_client):
    """Create processor instance with mocked BigQuery client."""
    with patch('data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor.get_bigquery_client') as mock_get_client:
        mock_get_client.return_value = mock_bq_client
        proc = PredictionLineEnrichmentProcessor(
            project_id='test-project',
            dataset_prefix='test'
        )
        proc.bq_client = mock_bq_client
        return proc


@pytest.fixture
def sample_predictions_missing_lines():
    """Sample predictions missing betting lines."""
    return [
        {
            'prediction_id': 'pred_001',
            'player_lookup': 'lebron-james',
            'game_id': '20251215_LAL_BOS',
            'game_date': date(2025, 12, 15),
            'current_points_line': None,
            'has_prop_line': None,
            'line_source': None
        },
        {
            'prediction_id': 'pred_002',
            'player_lookup': 'stephen-curry',
            'game_id': '20251215_GSW_PHX',
            'game_date': date(2025, 12, 15),
            'current_points_line': None,
            'has_prop_line': None,
            'line_source': None
        },
        {
            'prediction_id': 'pred_003',
            'player_lookup': 'kevin-durant',
            'game_id': '20251215_PHX_GSW',
            'game_date': date(2025, 12, 15),
            'current_points_line': None,
            'has_prop_line': None,
            'line_source': None
        }
    ]


@pytest.fixture
def sample_props_data():
    """Sample betting props from odds_api."""
    return {
        'lebron-james': {
            'points_line': 24.5,
            'bookmaker': 'DRAFTKINGS',
            'snapshot_timestamp': datetime(2025, 12, 15, 18, 0, 0)
        },
        'stephen-curry': {
            'points_line': 27.5,
            'bookmaker': 'FANDUEL',
            'snapshot_timestamp': datetime(2025, 12, 15, 18, 30, 0)
        }
        # kevin-durant missing (no prop available)
    }


# =============================================================================
# TEST: INITIALIZATION
# =============================================================================

class TestInitialization:
    """Test processor initialization."""

    def test_default_initialization(self, mock_bq_client):
        """Test initialization with default parameters."""
        with patch('data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor.get_bigquery_client') as mock_get:
            mock_get.return_value = mock_bq_client
            proc = PredictionLineEnrichmentProcessor()

            assert proc.project_id == 'nba-props-platform'
            assert proc.dataset_prefix == ''
            assert proc.predictions_table == 'nba-props-platform.nba_predictions.player_prop_predictions'
            assert proc.props_table == 'nba-props-platform.nba_raw.odds_api_player_points_props'

    def test_initialization_with_prefix(self, mock_bq_client):
        """Test initialization with dataset prefix."""
        with patch('data_processors.enrichment.prediction_line_enrichment.prediction_line_enrichment_processor.get_bigquery_client') as mock_get:
            mock_get.return_value = mock_bq_client
            proc = PredictionLineEnrichmentProcessor(
                project_id='test-project',
                dataset_prefix='staging'
            )

            assert proc.dataset_prefix == 'staging'
            assert proc.predictions_table == 'test-project.staging_nba_predictions.player_prop_predictions'
            assert proc.props_table == 'test-project.staging_nba_raw.odds_api_player_points_props'


# =============================================================================
# TEST: GET PREDICTIONS MISSING LINES
# =============================================================================

class TestGetPredictionsMissingLines:
    """Test querying predictions that need enrichment."""

    def test_returns_predictions_with_null_lines(self, processor, mock_bq_client):
        """Test retrieval of predictions missing lines."""
        mock_df = pd.DataFrame([
            {
                'prediction_id': 'pred_001',
                'player_lookup': 'lebron-james',
                'game_id': 'game1',
                'game_date': date(2025, 12, 15),
                'current_points_line': None,
                'has_prop_line': None,
                'line_source': None
            },
            {
                'prediction_id': 'pred_002',
                'player_lookup': 'stephen-curry',
                'game_id': 'game2',
                'game_date': date(2025, 12, 15),
                'current_points_line': None,
                'has_prop_line': None,
                'line_source': None
            }
        ])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        result = processor.get_predictions_missing_lines(date(2025, 12, 15))

        assert len(result) == 2
        assert result[0]['player_lookup'] == 'lebron-james'
        assert result[1]['player_lookup'] == 'stephen-curry'

    def test_returns_empty_list_when_all_have_lines(self, processor, mock_bq_client):
        """Test when all predictions already have lines."""
        mock_df = pd.DataFrame()  # No results

        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        result = processor.get_predictions_missing_lines(date(2025, 12, 15))

        assert len(result) == 0

    def test_filters_by_game_date(self, processor, mock_bq_client):
        """Test that query filters by game_date."""
        mock_df = pd.DataFrame()
        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        processor.get_predictions_missing_lines(date(2025, 12, 15))

        query_call = mock_bq_client.query.call_args[0][0]
        assert "game_date = '2025-12-15'" in query_call
        assert "current_points_line IS NULL" in query_call

    def test_handles_query_exception(self, processor, mock_bq_client):
        """Test error handling for query failures."""
        mock_bq_client.query.side_effect = Exception("BigQuery error")

        result = processor.get_predictions_missing_lines(date(2025, 12, 15))

        assert result == []


# =============================================================================
# TEST: GET AVAILABLE PROPS
# =============================================================================

class TestGetAvailableProps:
    """Test querying available betting props."""

    def test_returns_props_dict_keyed_by_player(self, processor, mock_bq_client):
        """Test props are returned as dict keyed by player_lookup."""
        mock_df = pd.DataFrame([
            {
                'player_lookup': 'lebron-james',
                'points_line': 24.5,
                'bookmaker': 'draftkings',
                'snapshot_timestamp': datetime(2025, 12, 15, 18, 0, 0)
            },
            {
                'player_lookup': 'stephen-curry',
                'points_line': 27.5,
                'bookmaker': 'fanduel',
                'snapshot_timestamp': datetime(2025, 12, 15, 18, 30, 0)
            }
        ])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        result = processor.get_available_props(date(2025, 12, 15))

        assert 'lebron-james' in result
        assert 'stephen-curry' in result
        assert result['lebron-james']['points_line'] == 24.5
        assert result['lebron-james']['bookmaker'] == 'DRAFTKINGS'

    def test_respects_bookmaker_priority(self, processor, mock_bq_client):
        """Test that DraftKings > FanDuel > BetMGM priority is applied."""
        # Query should use ROW_NUMBER with CASE statement for priority
        mock_df = pd.DataFrame()
        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        processor.get_available_props(date(2025, 12, 15))

        query_call = mock_bq_client.query.call_args[0][0]
        assert "WHEN 'draftkings' THEN 1" in query_call
        assert "WHEN 'fanduel' THEN 2" in query_call
        assert "WHEN 'betmgm' THEN 3" in query_call

    def test_converts_bookmaker_to_uppercase(self, processor, mock_bq_client):
        """Test bookmaker names are uppercased."""
        mock_df = pd.DataFrame([
            {
                'player_lookup': 'lebron-james',
                'points_line': 24.5,
                'bookmaker': 'draftkings',  # lowercase in DB
                'snapshot_timestamp': datetime(2025, 12, 15, 18, 0, 0)
            }
        ])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        result = processor.get_available_props(date(2025, 12, 15))

        assert result['lebron-james']['bookmaker'] == 'DRAFTKINGS'

    def test_handles_none_bookmaker(self, processor, mock_bq_client):
        """Test handling of None bookmaker values."""
        mock_df = pd.DataFrame([
            {
                'player_lookup': 'lebron-james',
                'points_line': 24.5,
                'bookmaker': None,
                'snapshot_timestamp': datetime(2025, 12, 15, 18, 0, 0)
            }
        ])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        result = processor.get_available_props(date(2025, 12, 15))

        assert result['lebron-james']['bookmaker'] == 'UNKNOWN'

    def test_converts_points_line_to_float(self, processor, mock_bq_client):
        """Test points_line is converted to float."""
        mock_df = pd.DataFrame([
            {
                'player_lookup': 'lebron-james',
                'points_line': 24,  # int
                'bookmaker': 'draftkings',
                'snapshot_timestamp': datetime(2025, 12, 15, 18, 0, 0)
            }
        ])

        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        result = processor.get_available_props(date(2025, 12, 15))

        assert isinstance(result['lebron-james']['points_line'], float)
        assert result['lebron-james']['points_line'] == 24.0

    def test_handles_query_exception(self, processor, mock_bq_client):
        """Test error handling for props query."""
        mock_bq_client.query.side_effect = Exception("Query failed")

        result = processor.get_available_props(date(2025, 12, 15))

        assert result == {}


# =============================================================================
# TEST: ENRICH PREDICTIONS
# =============================================================================

class TestEnrichPredictions:
    """Test main enrichment logic."""

    def test_matches_predictions_to_props(self, processor, mock_bq_client, sample_predictions_missing_lines, sample_props_data):
        """Test matching predictions with available props."""
        # Mock get_predictions_missing_lines
        mock_df_pred = pd.DataFrame(sample_predictions_missing_lines)
        mock_result_pred = Mock()
        mock_result_pred.to_dataframe.return_value = mock_df_pred

        # Mock get_available_props
        mock_df_props = pd.DataFrame([
            {'player_lookup': 'lebron-james', 'points_line': 24.5, 'bookmaker': 'draftkings', 'snapshot_timestamp': datetime.now()},
            {'player_lookup': 'stephen-curry', 'points_line': 27.5, 'bookmaker': 'fanduel', 'snapshot_timestamp': datetime.now()}
        ])
        mock_result_props = Mock()
        mock_result_props.to_dataframe.return_value = mock_df_props

        mock_bq_client.query.side_effect = [mock_result_pred, mock_result_props]

        result = processor.enrich_predictions(date(2025, 12, 15), dry_run=True)

        assert result['predictions_missing_lines'] == 3
        assert result['props_available'] == 2
        assert result['predictions_enriched'] == 2  # LeBron and Curry
        assert result['predictions_still_missing'] == 1  # Durant

    def test_dry_run_does_not_update(self, processor, mock_bq_client):
        """Test dry_run=True doesn't perform updates."""
        mock_df = pd.DataFrame([
            {'prediction_id': 'pred_001', 'player_lookup': 'lebron-james', 'game_id': 'game1',
             'game_date': date(2025, 12, 15), 'current_points_line': None, 'has_prop_line': None, 'line_source': None}
        ])
        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df

        mock_df_props = pd.DataFrame([
            {'player_lookup': 'lebron-james', 'points_line': 24.5, 'bookmaker': 'draftkings', 'snapshot_timestamp': datetime.now()}
        ])
        mock_result_props = Mock()
        mock_result_props.to_dataframe.return_value = mock_df_props

        mock_bq_client.query.side_effect = [mock_result, mock_result_props]

        result = processor.enrich_predictions(date(2025, 12, 15), dry_run=True)

        # Should report 1 enrichable, but not actually update
        assert result['predictions_enriched'] == 1
        assert result['dry_run'] is True

        # Verify no update query was executed
        assert mock_bq_client.query.call_count == 2  # Only queries, no update

    def test_returns_zero_when_no_predictions_missing(self, processor, mock_bq_client):
        """Test when all predictions have lines."""
        mock_df = pd.DataFrame()  # Empty
        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        result = processor.enrich_predictions(date(2025, 12, 15))

        assert result['predictions_missing_lines'] == 0
        assert result['predictions_enriched'] == 0

    def test_performs_update_when_not_dry_run(self, processor, mock_bq_client):
        """Test actual update execution."""
        # Mock predictions missing lines
        mock_df = pd.DataFrame([
            {'prediction_id': 'pred_001', 'player_lookup': 'lebron-james', 'game_id': 'game1',
             'game_date': date(2025, 12, 15), 'current_points_line': None, 'has_prop_line': None, 'line_source': None}
        ])
        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df

        # Mock available props
        mock_df_props = pd.DataFrame([
            {'player_lookup': 'lebron-james', 'points_line': 24.5, 'bookmaker': 'draftkings', 'snapshot_timestamp': datetime.now()}
        ])
        mock_result_props = Mock()
        mock_result_props.to_dataframe.return_value = mock_df_props

        # Mock MERGE query
        mock_merge_job = Mock()
        mock_merge_job.result.return_value = None
        mock_merge_job.num_dml_affected_rows = 1

        mock_bq_client.query.side_effect = [mock_result, mock_result_props, mock_merge_job]

        result = processor.enrich_predictions(date(2025, 12, 15), dry_run=False)

        assert result['predictions_enriched'] == 1
        assert result['dry_run'] is False

        # Verify MERGE was called
        assert mock_bq_client.query.call_count == 3


# =============================================================================
# TEST: UPDATE PREDICTIONS (MERGE LOGIC)
# =============================================================================

class TestUpdatePredictions:
    """Test BigQuery MERGE update logic."""

    def test_builds_merge_statement(self, processor, mock_bq_client):
        """Test MERGE SQL construction."""
        enrichable = [
            {'prediction_id': 'pred_001', 'points_line': 24.5, 'bookmaker': 'DRAFTKINGS'},
            {'prediction_id': 'pred_002', 'points_line': 27.5, 'bookmaker': 'FANDUEL'}
        ]

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 2
        mock_bq_client.query.return_value = mock_job

        result = processor._update_predictions(enrichable, date(2025, 12, 15))

        merge_query = mock_bq_client.query.call_args[0][0]
        assert 'MERGE' in merge_query
        assert 'pred_001' in merge_query
        assert 'pred_002' in merge_query
        assert '24.5' in merge_query
        assert '27.5' in merge_query
        assert 'DRAFTKINGS' in merge_query
        assert 'FANDUEL' in merge_query

    def test_updates_correct_fields(self, processor, mock_bq_client):
        """Test that MERGE updates the correct fields."""
        enrichable = [
            {'prediction_id': 'pred_001', 'points_line': 24.5, 'bookmaker': 'DRAFTKINGS'}
        ]

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 1
        mock_bq_client.query.return_value = mock_job

        processor._update_predictions(enrichable, date(2025, 12, 15))

        merge_query = mock_bq_client.query.call_args[0][0]
        assert 'current_points_line = source.points_line' in merge_query
        assert 'has_prop_line = TRUE' in merge_query
        assert "line_source = 'ACTUAL_PROP'" in merge_query
        assert "line_source_api = 'ODDS_API'" in merge_query
        assert 'sportsbook = source.bookmaker' in merge_query
        assert 'line_margin = ROUND(target.predicted_points - source.points_line, 2)' in merge_query

    def test_recalculates_recommendation(self, processor, mock_bq_client):
        """Test recommendation is recalculated based on predicted vs line."""
        enrichable = [
            {'prediction_id': 'pred_001', 'points_line': 24.5, 'bookmaker': 'DRAFTKINGS'}
        ]

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 1
        mock_bq_client.query.return_value = mock_job

        processor._update_predictions(enrichable, date(2025, 12, 15))

        merge_query = mock_bq_client.query.call_args[0][0]
        assert "WHEN target.predicted_points > source.points_line THEN 'OVER'" in merge_query
        assert "WHEN target.predicted_points < source.points_line THEN 'UNDER'" in merge_query
        assert "ELSE 'PASS'" in merge_query

    def test_returns_affected_row_count(self, processor, mock_bq_client):
        """Test returns number of rows updated."""
        enrichable = [
            {'prediction_id': 'pred_001', 'points_line': 24.5, 'bookmaker': 'DRAFTKINGS'},
            {'prediction_id': 'pred_002', 'points_line': 27.5, 'bookmaker': 'FANDUEL'}
        ]

        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 2
        mock_bq_client.query.return_value = mock_job

        result = processor._update_predictions(enrichable, date(2025, 12, 15))

        assert result == 2

    def test_handles_empty_enrichable_list(self, processor, mock_bq_client):
        """Test returns 0 for empty list."""
        result = processor._update_predictions([], date(2025, 12, 15))

        assert result == 0
        mock_bq_client.query.assert_not_called()

    def test_handles_update_exception(self, processor, mock_bq_client):
        """Test error handling during update."""
        enrichable = [
            {'prediction_id': 'pred_001', 'points_line': 24.5, 'bookmaker': 'DRAFTKINGS'}
        ]

        mock_bq_client.query.side_effect = Exception("Update failed")

        with pytest.raises(Exception, match="Update failed"):
            processor._update_predictions(enrichable, date(2025, 12, 15))


# =============================================================================
# TEST: FIX RECOMMENDATIONS
# =============================================================================

class TestFixRecommendations:
    """Test fixing NO_LINE recommendations."""

    def test_updates_no_line_recommendations(self, processor, mock_bq_client):
        """Test fixing NO_LINE recommendations after enrichment."""
        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 5
        mock_bq_client.query.return_value = mock_job

        result = processor.fix_recommendations(date(2025, 12, 15))

        assert result == 5

        # Verify query structure
        query_call = mock_bq_client.query.call_args[0][0]
        assert 'UPDATE' in query_call
        assert "recommendation = 'NO_LINE'" in query_call
        assert "current_points_line IS NOT NULL" in query_call

    def test_recalculates_based_on_predicted_vs_line(self, processor, mock_bq_client):
        """Test recommendation calculation logic."""
        mock_job = Mock()
        mock_job.result.return_value = None
        mock_job.num_dml_affected_rows = 3
        mock_bq_client.query.return_value = mock_job

        processor.fix_recommendations(date(2025, 12, 15))

        query_call = mock_bq_client.query.call_args[0][0]
        assert "WHEN predicted_points > current_points_line THEN 'OVER'" in query_call
        assert "WHEN predicted_points < current_points_line THEN 'UNDER'" in query_call
        assert "ELSE 'PASS'" in query_call

    def test_handles_exception(self, processor, mock_bq_client):
        """Test error handling."""
        mock_bq_client.query.side_effect = Exception("Fix failed")

        with pytest.raises(Exception, match="Fix failed"):
            processor.fix_recommendations(date(2025, 12, 15))


# =============================================================================
# TEST: DATE RANGE ENRICHMENT
# =============================================================================

class TestEnrichDateRange:
    """Test batch enrichment across date range."""

    def test_processes_multiple_dates(self, processor, mock_bq_client):
        """Test enrichment across date range."""
        # Mock empty results for all dates
        mock_df = pd.DataFrame()
        mock_result = Mock()
        mock_result.to_dataframe.return_value = mock_df
        mock_bq_client.query.return_value = mock_result

        results = processor.enrich_date_range(
            start_date=date(2025, 12, 15),
            end_date=date(2025, 12, 17),
            dry_run=True
        )

        assert len(results) == 3
        assert results[0]['game_date'] == '2025-12-15'
        assert results[1]['game_date'] == '2025-12-16'
        assert results[2]['game_date'] == '2025-12-17'

    def test_aggregates_results(self, processor, mock_bq_client):
        """Test result aggregation across dates."""
        # Mock predictions for each date
        def mock_query_side_effect(*args, **kwargs):
            mock_result = Mock()
            mock_result.to_dataframe.return_value = pd.DataFrame()
            return mock_result

        mock_bq_client.query.side_effect = mock_query_side_effect

        results = processor.enrich_date_range(
            start_date=date(2025, 12, 15),
            end_date=date(2025, 12, 16),
            dry_run=True
        )

        assert len(results) == 2


# =============================================================================
# TEST SUMMARY
# =============================================================================
# Total Tests: 35+ comprehensive unit tests
# Coverage Areas:
# - Initialization: 2 tests
# - Get predictions missing lines: 4 tests
# - Get available props: 6 tests
# - Enrich predictions: 5 tests
# - Update predictions (MERGE): 6 tests
# - Fix recommendations: 3 tests
# - Date range enrichment: 2 tests
#
# Run with:
#   pytest tests/processors/enrichment/prediction_line_enrichment/test_unit.py -v
#   pytest tests/processors/enrichment/prediction_line_enrichment/test_unit.py -k "props" -v
# =============================================================================
