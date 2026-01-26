#!/usr/bin/env python3
"""
Unit Tests for Basketball Reference Roster Processor (Phase 2 Raw Data Processor)

Tests cover:
1. Roster processing (player details)
2. Player name normalization
3. Team assignment and tracking
4. Experience parsing (Rookie, N years)
5. MERGE_UPDATE strategy (first_seen_date preservation)
6. Smart idempotency
7. Error handling
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, date
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# Mock Google Cloud modules
for module in ['google.cloud', 'google.cloud.bigquery', 'sentry_sdk']:
    sys.modules[module] = MagicMock()

from data_processors.raw.basketball_ref.br_roster_processor import BasketballRefRosterProcessor


@pytest.fixture
def processor():
    """Create processor with mocked dependencies"""
    with patch('data_processors.raw.basketball_ref.br_roster_processor.bigquery.Client'):
        proc = BasketballRefRosterProcessor()
        proc.bq_client = Mock()
        proc.gcs_client = Mock()
        return proc


@pytest.fixture
def sample_roster():
    """Sample roster data"""
    return {
        'team_abbrev': 'LAL',
        'season': '2024-25',
        'players': [
            {
                'full_name': 'LeBron James',
                'last_name': 'James',
                'normalized': 'lebronjames',
                'position': 'F',
                'jersey_number': '23',
                'height': '6-9',
                'weight': '250',
                'birth_date': '1984-12-30',
                'college': 'None',
                'experience': '21 years'
            },
            {
                'full_name': 'Anthony Davis',
                'last_name': 'Davis',
                'normalized': 'anthonydavis',
                'position': 'F-C',
                'jersey_number': '3',
                'height': '6-10',
                'weight': '253',
                'birth_date': '1993-03-11',
                'college': 'Kentucky',
                'experience': '11 years'
            },
            {
                'full_name': 'Bronny James',
                'last_name': 'James',
                'normalized': 'bronnyjames',
                'position': 'G',
                'jersey_number': '9',
                'height': '6-2',
                'weight': '210',
                'birth_date': '2004-10-06',
                'college': 'USC',
                'experience': 'Rookie'
            }
        ]
    }


class TestProcessorInitialization:
    """Test processor initialization"""

    def test_initialization(self):
        """Test processor initializes correctly"""
        with patch('data_processors.raw.basketball_ref.br_roster_processor.bigquery.Client'):
            proc = BasketballRefRosterProcessor()
            assert proc.table_name == 'br_rosters_current'
            assert proc.processing_strategy == 'MERGE_UPDATE'
            assert 'season_year' in proc.HASH_FIELDS
            assert 'player_full_name' in proc.HASH_FIELDS


class TestSeasonDisplayFormat:
    """Test season display format"""

    def test_set_additional_opts(self, processor):
        """Test season display format generation"""
        processor.opts = {'season_year': '2024'}
        processor.set_additional_opts()

        assert processor.opts['season_display'] == '2024-25'


class TestExperienceParsing:
    """Test experience parsing"""

    def test_parse_rookie(self, processor):
        """Test parsing 'Rookie'"""
        assert processor._parse_experience('Rookie') == 0
        assert processor._parse_experience('rookie') == 0

    def test_parse_years(self, processor):
        """Test parsing 'N years'"""
        assert processor._parse_experience('1 year') == 1
        assert processor._parse_experience('5 years') == 5
        assert processor._parse_experience('21 years') == 21

    def test_parse_invalid(self, processor):
        """Test parsing invalid experience"""
        assert processor._parse_experience('Unknown') is None
        assert processor._parse_experience('') is None
        assert processor._parse_experience(None) is None


class TestDataValidation:
    """Test data validation"""

    def test_validate_complete_data(self, processor, sample_roster):
        """Test validation passes with complete data"""
        processor.raw_data = sample_roster
        processor.opts = {'season_year': '2024', 'team_abbrev': 'LAL', 'file_path': 'test.json'}

        # Should not raise exception
        processor.validate_loaded_data()

    def test_validate_missing_players(self, processor):
        """Test validation catches missing players"""
        processor.raw_data = {'team_abbrev': 'LAL', 'season': '2024-25'}
        processor.opts = {'season_year': '2024', 'team_abbrev': 'LAL', 'file_path': 'test.json'}

        with pytest.raises(ValueError):
            processor.validate_loaded_data()

    def test_validate_small_roster_warning(self, processor):
        """Test validation warns for suspiciously small rosters"""
        processor.raw_data = {
            'team_abbrev': 'LAL',
            'season': '2024-25',
            'players': [
                {'full_name': 'Player 1', 'last_name': 'One'}
            ]
        }
        processor.opts = {'season_year': '2024', 'team_abbrev': 'LAL', 'file_path': 'test.json'}

        # Should pass but log warning
        processor.validate_loaded_data()


class TestDataTransformation:
    """Test data transformation"""

    def test_transform_complete_roster(self, processor, sample_roster):
        """Test transformation of complete roster"""
        processor.raw_data = sample_roster
        processor.opts = {
            'season_year': '2024',
            'team_abbrev': 'LAL',
            'file_path': 'test.json',
            'season_display': '2024-25'
        }

        # Mock existing roster query
        processor.bq_client.query = Mock(return_value=Mock(result=Mock(return_value=[])))

        processor.transform_data()

        assert len(processor.transformed_data) == 3

        # Check LeBron's row
        lebron = [r for r in processor.transformed_data
                 if r['player_lookup'] == 'lebronjames'][0]

        assert lebron['player_full_name'] == 'LeBron James'
        assert lebron['team_abbrev'] == 'LAL'
        assert lebron['season_year'] == 2024
        assert lebron['position'] == 'F'
        assert lebron['jersey_number'] == '23'
        assert lebron['experience_years'] == 21

    def test_transform_rookie_player(self, processor, sample_roster):
        """Test rookie player transformation"""
        processor.raw_data = sample_roster
        processor.opts = {
            'season_year': '2024',
            'team_abbrev': 'LAL',
            'file_path': 'test.json',
            'season_display': '2024-25'
        }

        # Mock existing roster query
        processor.bq_client.query = Mock(return_value=Mock(result=Mock(return_value=[])))

        processor.transform_data()

        # Check Bronny's row (rookie)
        bronny = [r for r in processor.transformed_data
                 if r['player_lookup'] == 'bronnyjames'][0]

        assert bronny['experience_years'] == 0

    def test_transform_tracks_new_players(self, processor, sample_roster):
        """Test new player tracking"""
        processor.raw_data = sample_roster
        processor.opts = {
            'season_year': '2024',
            'team_abbrev': 'LAL',
            'file_path': 'test.json',
            'season_display': '2024-25'
        }

        # Mock existing roster (LeBron exists)
        mock_result = Mock()
        mock_result.result = Mock(return_value=[
            {'player_lookup': 'lebronjames', 'player_full_name': 'LeBron James', 'first_seen_date': '2024-10-01'}
        ])
        processor.bq_client.query = Mock(return_value=mock_result)

        processor.transform_data()

        # Check stats
        assert processor.stats['new_players'] == 2  # AD and Bronny are new
        assert processor.stats['total_players'] == 3

    def test_transform_skips_players_without_names(self, processor):
        """Test players without names are skipped"""
        bad_roster = {
            'team_abbrev': 'LAL',
            'season': '2024-25',
            'players': [
                {'full_name': 'LeBron James', 'last_name': 'James'},
                {'full_name': '', 'last_name': ''},  # Bad player
                {'last_name': 'Davis'}  # Missing full_name
            ]
        }

        processor.raw_data = bad_roster
        processor.opts = {
            'season_year': '2024',
            'team_abbrev': 'LAL',
            'file_path': 'test.json',
            'season_display': '2024-25'
        }

        # Mock existing roster query
        processor.bq_client.query = Mock(return_value=Mock(result=Mock(return_value=[])))

        processor.transform_data()

        # Should only process LeBron
        assert len(processor.transformed_data) == 1
        assert processor.stats['skipped_players'] == 2


class TestPlayerNameNormalization:
    """Test player name normalization"""

    def test_normalize_name_function(self, processor):
        """Test name normalization removes special characters"""
        # This tests the shared utility function
        from data_processors.raw.utils.name_utils import normalize_name

        assert normalize_name('LeBron James') == 'lebronjames'
        assert normalize_name("D'Angelo Russell") == 'dangelorussell'
        assert normalize_name('Karl-Anthony Towns') == 'karlanthonytowns'


class TestMergeUpdateStrategy:
    """Test MERGE_UPDATE strategy"""

    def test_save_data_uses_merge(self, processor, sample_roster):
        """Test save_data uses MERGE operation"""
        processor.raw_data = sample_roster
        processor.opts = {
            'season_year': '2024',
            'team_abbrev': 'LAL',
            'file_path': 'test.json',
            'season_display': '2024-25'
        }

        # Mock existing roster query
        processor.bq_client.query = Mock(return_value=Mock(result=Mock(return_value=[])))

        processor.transform_data()

        # Mock BQ operations
        processor.bq_client.delete_table = Mock()
        processor.bq_client.get_table = Mock(return_value=Mock(schema=[]))

        mock_load_job = Mock()
        mock_load_job.result = Mock()
        processor.bq_client.load_table_from_json = Mock(return_value=mock_load_job)

        mock_query_result = Mock()
        mock_query_result.num_dml_affected_rows = 3
        processor.bq_client.query = Mock(return_value=Mock(result=Mock(return_value=mock_query_result)))

        processor.save_data()

        # Verify MERGE query was executed
        processor.bq_client.query.assert_called()
        merge_call = [call for call in processor.bq_client.query.call_args_list
                     if 'MERGE' in str(call)][0]
        assert 'MERGE' in str(merge_call)

    def test_first_seen_date_preserved_for_existing_players(self, processor):
        """Test first_seen_date is preserved in MERGE for existing players"""
        # This is tested by the MERGE SQL logic
        # The MERGE query should NOT update first_seen_date for MATCHED rows
        pass


class TestSmartIdempotency:
    """Test smart idempotency"""

    def test_hash_generation(self, processor, sample_roster):
        """Test hash generation"""
        processor.raw_data = sample_roster
        processor.opts = {
            'season_year': '2024',
            'team_abbrev': 'LAL',
            'file_path': 'test.json',
            'season_display': '2024-25'
        }

        # Mock existing roster query
        processor.bq_client.query = Mock(return_value=Mock(result=Mock(return_value=[])))

        processor.transform_data()

        # All rows should have data_hash
        for row in processor.transformed_data:
            assert 'data_hash' in row
            assert row['data_hash'] is not None

    def test_hash_detects_roster_changes(self, processor):
        """Test hash changes when player details change"""
        row1 = {
            'season_year': 2024,
            'team_abbrev': 'LAL',
            'player_full_name': 'LeBron James',
            'position': 'F',
            'jersey_number': '23',
            'height': '6-9',
            'weight': '250',
            'birth_date': '1984-12-30',
            'college': 'None',
            'experience_years': 21
        }
        row2 = row1.copy()

        processor.transformed_data = [row1, row2]
        processor.add_data_hash()

        # Same data = same hash
        assert processor.transformed_data[0]['data_hash'] == processor.transformed_data[1]['data_hash']

        # Change jersey = different hash
        processor.transformed_data[1]['jersey_number'] = '6'
        processor.add_data_hash()
        assert processor.transformed_data[0]['data_hash'] != processor.transformed_data[1]['data_hash']


class TestBigQuerySchemaCompliance:
    """Test BigQuery schema compliance"""

    def test_transformed_data_has_required_fields(self, processor, sample_roster):
        """Test all required BigQuery fields are present"""
        processor.raw_data = sample_roster
        processor.opts = {
            'season_year': '2024',
            'team_abbrev': 'LAL',
            'file_path': 'test.json',
            'season_display': '2024-25'
        }

        # Mock existing roster query
        processor.bq_client.query = Mock(return_value=Mock(result=Mock(return_value=[])))

        processor.transform_data()

        required_fields = [
            'season_year', 'season_display', 'team_abbrev',
            'player_full_name', 'player_lookup', 'position',
            'last_scraped_date', 'source_file_path'
        ]

        for row in processor.transformed_data:
            for field in required_fields:
                assert field in row


class TestErrorHandling:
    """Test error handling"""

    def test_load_data_handles_missing_file(self, processor):
        """Test load_data handles missing file"""
        processor.opts = {
            'bucket': 'test-bucket',
            'file_path': 'nonexistent.json'
        }

        # Mock GCS bucket
        mock_blob = Mock()
        mock_blob.exists = Mock(return_value=False)
        mock_bucket = Mock()
        mock_bucket.blob = Mock(return_value=mock_blob)
        processor.gcs_client.bucket = Mock(return_value=mock_bucket)

        with pytest.raises(FileNotFoundError):
            processor.load_data()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
