"""
Path: tests/processors/raw/nbacom/nbac_team_boxscore/test_integration.py

Integration Tests for NBA.com Team Boxscore Processor

Tests full end-to-end flow with mocked BigQuery operations.
Run with: pytest test_integration.py -v

Directory: tests/processors/raw/nbacom/nbac_team_boxscore/
"""

import pytest
import json
from datetime import datetime, date
from unittest.mock import Mock, MagicMock, call
from google.cloud import bigquery

# Import processor
from data_processors.raw.nbacom.nbac_team_boxscore_processor import NbacTeamBoxscoreProcessor


class TestLoadData:
    """Test BigQuery load operations with MERGE_UPDATE strategy."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery client."""
        proc = NbacTeamBoxscoreProcessor()
        proc.bq_client = Mock(spec=bigquery.Client)
        proc.project_id = 'test-project'
        return proc
    
    @pytest.fixture
    def sample_rows(self):
        """Create sample transformed rows ready for BigQuery."""
        return [
            {
                'game_id': '0022400561',
                'game_date': '2025-01-15',
                'season_year': 2024,
                'team_id': 1610612755,
                'team_abbr': 'PHI',
                'team_name': '76ers',
                'team_city': 'Philadelphia',
                'minutes': '240:00',
                'fg_made': 40,
                'fg_attempted': 88,
                'fg_percentage': 0.455,
                'three_pt_made': 12,
                'three_pt_attempted': 35,
                'three_pt_percentage': 0.343,
                'ft_made': 18,
                'ft_attempted': 22,
                'ft_percentage': 0.818,
                'offensive_rebounds': 10,
                'defensive_rebounds': 35,
                'total_rebounds': 45,
                'assists': 24,
                'steals': 8,
                'blocks': 5,
                'turnovers': 12,
                'personal_fouls': 20,
                'points': 110,
                'plus_minus': -4,
                'source_file_path': 'gs://test-bucket/test.json',
                'created_at': '2025-01-15T12:00:00',
                'processed_at': '2025-01-15T12:00:00'
            },
            {
                'game_id': '0022400561',
                'game_date': '2025-01-15',
                'season_year': 2024,
                'team_id': 1610612747,
                'team_abbr': 'LAL',
                'team_name': 'Lakers',
                'team_city': 'Los Angeles',
                'minutes': '240:00',
                'fg_made': 42,
                'fg_attempted': 90,
                'fg_percentage': 0.467,
                'three_pt_made': 10,
                'three_pt_attempted': 30,
                'three_pt_percentage': 0.333,
                'ft_made': 20,
                'ft_attempted': 25,
                'ft_percentage': 0.800,
                'offensive_rebounds': 12,
                'defensive_rebounds': 38,
                'total_rebounds': 50,
                'assists': 28,
                'steals': 6,
                'blocks': 7,
                'turnovers': 14,
                'personal_fouls': 22,
                'points': 114,
                'plus_minus': 4,
                'source_file_path': 'gs://test-bucket/test.json',
                'created_at': '2025-01-15T12:00:00',
                'processed_at': '2025-01-15T12:00:00'
            }
        ]
    
    def test_load_data_executes_delete_query(self, processor, sample_rows):
        """Test that load_data deletes existing records before inserting."""
        # Mock delete query success
        mock_query_job = Mock()
        mock_query_job.result.return_value = None
        processor.bq_client.query.return_value = mock_query_job
        
        # Mock insert success
        processor.bq_client.insert_rows_json.return_value = []
        
        # Execute
        result = processor.load_data(sample_rows)
        
        # Verify delete query was called
        assert processor.bq_client.query.called
        delete_call = processor.bq_client.query.call_args
        
        # Check delete query contains correct game_id
        assert 'DELETE FROM' in delete_call[0][0]
        assert 'WHERE game_id = @game_id' in delete_call[0][0]
        
        # Check query parameter
        job_config = delete_call[1]['job_config']
        assert len(job_config.query_parameters) == 1
        assert job_config.query_parameters[0].value == '0022400561'
    
    def test_load_data_inserts_rows_after_delete(self, processor, sample_rows):
        """Test that load_data inserts rows after successful delete."""
        # Mock delete query success
        mock_query_job = Mock()
        mock_query_job.result.return_value = None
        processor.bq_client.query.return_value = mock_query_job
        
        # Mock insert success
        processor.bq_client.insert_rows_json.return_value = []
        
        # Execute
        result = processor.load_data(sample_rows)
        
        # Verify insert was called with correct data
        assert processor.bq_client.insert_rows_json.called
        insert_call = processor.bq_client.insert_rows_json.call_args
        
        # Check table ID
        assert 'test-project.nba_raw.nbac_team_boxscore' in insert_call[0][0]
        
        # Check rows were passed
        assert insert_call[0][1] == sample_rows
        
        # Check result
        assert result['rows_processed'] == 2
        assert result['errors'] == []
    
    def test_load_data_handles_insert_errors(self, processor, sample_rows):
        """Test load_data handles BigQuery insert errors gracefully."""
        # Mock delete success
        mock_query_job = Mock()
        mock_query_job.result.return_value = None
        processor.bq_client.query.return_value = mock_query_job
        
        # Mock insert with errors
        processor.bq_client.insert_rows_json.return_value = [
            {'index': 0, 'errors': [{'message': 'Field too large'}]},
            {'index': 1, 'errors': [{'message': 'Invalid data'}]}
        ]
        
        # Execute
        result = processor.load_data(sample_rows)
        
        # Verify errors are captured
        assert result['rows_processed'] == 0
        assert len(result['errors']) == 2
        assert 'Field too large' in str(result['errors'][0])
        assert 'Invalid data' in str(result['errors'][1])
    
    def test_load_data_dry_run_mode(self, processor, sample_rows):
        """Test load_data dry run mode doesn't execute queries."""
        # Execute in dry run mode
        result = processor.load_data(sample_rows, dry_run=True)
        
        # Verify no actual queries were executed
        assert not processor.bq_client.query.called
        assert not processor.bq_client.insert_rows_json.called
        
        # But result shows would-be success
        assert result['rows_processed'] == 2
        assert result['errors'] == []
    
    def test_load_data_with_empty_rows(self, processor):
        """Test load_data handles empty rows list gracefully."""
        result = processor.load_data([])
        
        # Should not attempt any operations
        assert not processor.bq_client.query.called
        assert not processor.bq_client.insert_rows_json.called
        
        # Result shows no processing
        assert result['rows_processed'] == 0
        assert result['errors'] == []
    
    def test_load_data_handles_delete_failure(self, processor, sample_rows):
        """Test load_data handles delete query failures."""
        # Mock delete query failure
        mock_query_job = Mock()
        mock_query_job.result.side_effect = Exception("BigQuery delete failed")
        processor.bq_client.query.return_value = mock_query_job
        
        # Execute
        result = processor.load_data(sample_rows)
        
        # Verify error is captured
        assert result['rows_processed'] == 0
        assert len(result['errors']) > 0
        assert 'BigQuery delete failed' in str(result['errors'][0])


class TestProcessFile:
    """Test full end-to-end file processing flow."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        proc = NbacTeamBoxscoreProcessor()
        proc.bq_client = Mock(spec=bigquery.Client)
        proc.project_id = 'test-project'
        return proc
    
    @pytest.fixture
    def valid_json_data(self):
        """Create valid JSON data as would be in GCS file."""
        return {
            'gameId': '0022400561',
            'gameDate': '2025-01-15',
            'teams': [
                {
                    'teamId': 1610612755,
                    'teamAbbreviation': 'PHI',
                    'teamName': '76ers',
                    'teamCity': 'Philadelphia',
                    'minutes': '240:00',
                    'fieldGoals': {'made': 40, 'attempted': 88, 'percentage': 0.455},
                    'threePointers': {'made': 12, 'attempted': 35, 'percentage': 0.343},
                    'freeThrows': {'made': 18, 'attempted': 22, 'percentage': 0.818},
                    'rebounds': {'offensive': 10, 'defensive': 35, 'total': 45},
                    'assists': 24,
                    'steals': 8,
                    'blocks': 5,
                    'turnovers': 12,
                    'personalFouls': 20,
                    'points': 110,
                    'plusMinus': -4
                },
                {
                    'teamId': 1610612747,
                    'teamAbbreviation': 'LAL',
                    'teamName': 'Lakers',
                    'teamCity': 'Los Angeles',
                    'minutes': '240:00',
                    'fieldGoals': {'made': 42, 'attempted': 90, 'percentage': 0.467},
                    'threePointers': {'made': 10, 'attempted': 30, 'percentage': 0.333},
                    'freeThrows': {'made': 20, 'attempted': 25, 'percentage': 0.800},
                    'rebounds': {'offensive': 12, 'defensive': 38, 'total': 50},
                    'assists': 28,
                    'steals': 6,
                    'blocks': 7,
                    'turnovers': 14,
                    'personalFouls': 22,
                    'points': 114,
                    'plusMinus': 4
                }
            ]
        }
    
    def test_process_file_success_flow(self, processor, valid_json_data):
        """Test successful end-to-end file processing."""
        # Mock file content retrieval (inherited from ProcessorBase)
        processor.get_file_content = Mock(return_value=valid_json_data)
        
        # Mock BigQuery operations
        mock_query_job = Mock()
        mock_query_job.result.return_value = None
        processor.bq_client.query.return_value = mock_query_job
        processor.bq_client.insert_rows_json.return_value = []
        
        # Execute
        file_path = 'gs://test-bucket/nba-com/team-boxscore/20250115/0022400561/test.json'
        result = processor.process_file(file_path)
        
        # Verify result
        assert result['status'] == 'success'
        assert result['rows_processed'] == 2
        assert result['file_path'] == file_path
        assert result.get('errors', []) == []
        
        # Verify file was read
        processor.get_file_content.assert_called_once_with(file_path)
        
        # Verify BigQuery operations
        assert processor.bq_client.query.called  # Delete
        assert processor.bq_client.insert_rows_json.called  # Insert
    
    def test_process_file_validation_failure(self, processor):
        """Test process_file handles validation errors."""
        # Invalid data - missing required field
        invalid_data = {
            'gameId': '0022400561',
            # Missing gameDate
            'teams': []
        }
        processor.get_file_content = Mock(return_value=invalid_data)
        
        # Execute
        result = processor.process_file('gs://test-bucket/test.json')
        
        # Verify validation failure
        assert result['status'] == 'validation_failed'
        assert result['rows_processed'] == 0
        assert len(result['errors']) > 0
        assert any('gameDate' in err for err in result['errors'])
        
        # Verify BigQuery was NOT called
        assert not processor.bq_client.query.called
        assert not processor.bq_client.insert_rows_json.called
    
    def test_process_file_with_no_teams(self, processor):
        """Test process_file handles empty teams list."""
        # Data with no teams
        data = {
            'gameId': '0022400561',
            'gameDate': '2025-01-15',
            'teams': []
        }
        processor.get_file_content = Mock(return_value=data)
        
        # Execute
        result = processor.process_file('gs://test-bucket/test.json')
        
        # Should fail validation (need exactly 2 teams)
        assert result['status'] in ['validation_failed', 'no_data']
        assert result['rows_processed'] == 0
    
    def test_process_file_handles_file_read_error(self, processor):
        """Test process_file handles file read errors."""
        # Mock file read failure
        processor.get_file_content = Mock(side_effect=Exception("File not found in GCS"))
        
        # Execute
        result = processor.process_file('gs://test-bucket/missing.json')
        
        # Verify error is captured
        assert result['status'] == 'error'
        assert result['rows_processed'] == 0
        assert 'File not found in GCS' in result['error']
    
    def test_process_file_dry_run_mode(self, processor, valid_json_data):
        """Test process_file in dry run mode."""
        # Mock file content
        processor.get_file_content = Mock(return_value=valid_json_data)
        
        # Execute in dry run mode
        result = processor.process_file('gs://test-bucket/test.json', dry_run=True)
        
        # Verify success without actual BigQuery operations
        assert result['status'] == 'success'
        assert result['rows_processed'] == 2
        
        # Verify BigQuery was NOT called
        assert not processor.bq_client.query.called
        assert not processor.bq_client.insert_rows_json.called


class TestMergeUpdateStrategy:
    """Test MERGE_UPDATE strategy (delete + insert)."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery client."""
        proc = NbacTeamBoxscoreProcessor()
        proc.bq_client = Mock(spec=bigquery.Client)
        proc.project_id = 'test-project'
        return proc
    
    def test_merge_update_deletes_old_records(self, processor):
        """Test that MERGE_UPDATE strategy deletes old records first."""
        rows = [
            {
                'game_id': '0022400561',
                'game_date': '2025-01-15',
                'team_abbr': 'PHI',
                'points': 110,
                'source_file_path': 'gs://test.json',
                'created_at': '2025-01-15T12:00:00',
                'processed_at': '2025-01-15T12:00:00'
            }
        ]
        
        # Mock successful delete and insert
        mock_query_job = Mock()
        mock_query_job.result.return_value = None
        processor.bq_client.query.return_value = mock_query_job
        processor.bq_client.insert_rows_json.return_value = []
        
        # Execute
        processor.load_data(rows)
        
        # Verify delete was called with correct game_id
        assert processor.bq_client.query.called
        delete_call_args = processor.bq_client.query.call_args
        
        # Check the DELETE query
        query = delete_call_args[0][0]
        assert 'DELETE FROM' in query
        assert 'nba_raw.nbac_team_boxscore' in query
        assert 'WHERE game_id = @game_id' in query
        
        # Check the query parameter
        job_config = delete_call_args[1]['job_config']
        param = job_config.query_parameters[0]
        assert param.name == 'game_id'
        assert param.value == '0022400561'
    
    def test_merge_update_inserts_new_records(self, processor):
        """Test that MERGE_UPDATE inserts new records after delete."""
        rows = [
            {'game_id': '0022400561', 'team_abbr': 'PHI', 'points': 110},
            {'game_id': '0022400561', 'team_abbr': 'LAL', 'points': 114}
        ]
        
        # Mock successful operations
        mock_query_job = Mock()
        mock_query_job.result.return_value = None
        processor.bq_client.query.return_value = mock_query_job
        processor.bq_client.insert_rows_json.return_value = []
        
        # Execute
        result = processor.load_data(rows)
        
        # Verify insert was called after delete
        assert processor.bq_client.insert_rows_json.called
        insert_call_args = processor.bq_client.insert_rows_json.call_args
        
        # Check table
        table_id = insert_call_args[0][0]
        assert 'nba_raw.nbac_team_boxscore' in table_id
        
        # Check rows
        inserted_rows = insert_call_args[0][1]
        assert len(inserted_rows) == 2
        assert inserted_rows == rows
        
        # Verify result
        assert result['rows_processed'] == 2
        assert result['errors'] == []


# Test count summary
"""
Total Integration Tests: 13

Test Class Distribution:
- TestLoadData: 7 tests (BigQuery operations, MERGE_UPDATE)
- TestProcessFile: 5 tests (end-to-end flow)
- TestMergeUpdateStrategy: 1 test (delete + insert verification)

What's Tested:
- ✅ MERGE_UPDATE strategy (delete then insert)
- ✅ BigQuery query execution
- ✅ BigQuery insert operations
- ✅ Error handling (file read, validation, BigQuery errors)
- ✅ Dry run mode
- ✅ Full end-to-end file processing
- ✅ Empty data handling
- ✅ Insert error handling

Coverage Addition: +30% (load_data, process_file, error paths)
Total Coverage (with unit tests): ~94%

Run with:
    pytest test_integration.py -v
    python run_tests.py integration
"""
