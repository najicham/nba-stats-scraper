# ============================================================================
# FILE: shared/utils/schedule/tests/test_database_reader.py
# ============================================================================
"""Tests for database reader."""

import pytest
from unittest.mock import Mock, patch

from shared.utils.schedule.database_reader import ScheduleDatabaseReader


class TestScheduleDatabaseReader:
    """Test database reader functionality."""
    
    @pytest.fixture
    def mock_bq_client(self):
        """Create mock BigQuery client."""
        with patch('shared.utils.schedule.database_reader.bigquery.Client') as mock:
            yield mock
    
    def test_initialization(self, mock_bq_client):
        """Test database reader initializes correctly."""
        reader = ScheduleDatabaseReader(
            project_id='test-project',
            table_name='test_dataset.test_table'
        )
        
        assert reader.project_id == 'test-project'
        assert reader.table_name == 'test_dataset.test_table'
        assert reader._table_exists is None
    
    def test_table_exists_true(self, mock_bq_client):
        """Test table_exists returns True when table found."""
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.get_table.return_value = Mock()  # Table exists
        
        reader = ScheduleDatabaseReader()
        result = reader.table_exists()
        
        assert result is True
        assert reader._table_exists is True
    
    def test_table_exists_false(self, mock_bq_client):
        """Test table_exists returns False when table not found."""
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.get_table.side_effect = Exception("Not found")
        
        reader = ScheduleDatabaseReader()
        result = reader.table_exists()
        
        assert result is False
        assert reader._table_exists is False
    
    def test_table_exists_cached(self, mock_bq_client):
        """Test table_exists uses cache on second call."""
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.get_table.return_value = Mock()
        
        reader = ScheduleDatabaseReader()
        
        # First call
        reader.table_exists()
        assert mock_client.get_table.call_count == 1
        
        # Second call should use cache
        reader.table_exists()
        assert mock_client.get_table.call_count == 1  # Not called again
    
    def test_has_games_on_date_table_missing(self, mock_bq_client):
        """Test has_games_on_date returns None when table missing."""
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.get_table.side_effect = Exception("Not found")
        
        reader = ScheduleDatabaseReader()
        result = reader.has_games_on_date('2024-01-15')
        
        assert result is None  # Signals fallback to GCS
    
    def test_get_game_count_table_missing(self, mock_bq_client):
        """Test get_game_count returns None when table missing."""
        mock_client = Mock()
        mock_bq_client.return_value = mock_client
        mock_client.get_table.side_effect = Exception("Not found")
        
        reader = ScheduleDatabaseReader()
        result = reader.get_game_count('2024-01-15')
        
        assert result is None  # Signals fallback to GCS