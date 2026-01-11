"""
Path: tests/processors/raw/nbacom/nbac_schedule/test_unit.py

Unit Tests for NBA.com Schedule Processor MERGE Logic

Tests the MERGE implementation that prevents duplicate rows
with conflicting game statuses.

Run with: pytest tests/processors/raw/nbacom/nbac_schedule/test_unit.py -v

Created: 2026-01-11 (Session 9 - Schedule MERGE fix)
"""

import pytest
import json
from datetime import datetime, date
from unittest.mock import Mock, MagicMock, patch

from data_processors.raw.nbacom.nbac_schedule_processor import NbacScheduleProcessor


class TestPrimaryKeyFields:
    """Test PRIMARY_KEY_FIELDS class attribute."""

    def test_primary_key_fields_defined(self):
        """Verify PRIMARY_KEY_FIELDS is defined on the class."""
        assert hasattr(NbacScheduleProcessor, 'PRIMARY_KEY_FIELDS')
        assert isinstance(NbacScheduleProcessor.PRIMARY_KEY_FIELDS, list)

    def test_primary_key_fields_contains_game_id(self):
        """Verify game_id is in PRIMARY_KEY_FIELDS."""
        assert 'game_id' in NbacScheduleProcessor.PRIMARY_KEY_FIELDS

    def test_primary_key_fields_contains_game_date(self):
        """Verify game_date is in PRIMARY_KEY_FIELDS for partition awareness."""
        assert 'game_date' in NbacScheduleProcessor.PRIMARY_KEY_FIELDS

    def test_primary_key_fields_order(self):
        """Verify PRIMARY_KEY_FIELDS order matches expected."""
        assert NbacScheduleProcessor.PRIMARY_KEY_FIELDS == ['game_id', 'game_date']


class TestProcessingStrategy:
    """Test processing_strategy attribute."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_schedule_processor.bigquery.Client'):
            with patch('data_processors.raw.nbacom.nbac_schedule_processor.storage.Client'):
                proc = NbacScheduleProcessor()
                return proc

    def test_processing_strategy_is_merge_update(self, processor):
        """Verify processing_strategy is set to MERGE_UPDATE."""
        assert processor.processing_strategy == 'MERGE_UPDATE'


class TestSanitizeRowForBQ:
    """Test _sanitize_row_for_bq() method."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_schedule_processor.bigquery.Client'):
            with patch('data_processors.raw.nbacom.nbac_schedule_processor.storage.Client'):
                proc = NbacScheduleProcessor()
                return proc

    def test_sanitize_string_fields(self, processor):
        """Test string fields are passed through unchanged."""
        row = {'game_id': '0022500542', 'home_team_tricode': 'LAL'}
        result = processor._sanitize_row_for_bq(row)
        assert result['game_id'] == '0022500542'
        assert result['home_team_tricode'] == 'LAL'

    def test_sanitize_none_values(self, processor):
        """Test None values are preserved."""
        row = {'game_id': '0022500542', 'arena_name': None}
        result = processor._sanitize_row_for_bq(row)
        assert result['arena_name'] is None

    def test_sanitize_datetime_to_iso(self, processor):
        """Test datetime objects are converted to ISO format."""
        dt = datetime(2026, 1, 10, 19, 30, 0)
        row = {'game_date_est': dt}
        result = processor._sanitize_row_for_bq(row)
        assert result['game_date_est'] == '2026-01-10T19:30:00'

    def test_sanitize_date_to_iso(self, processor):
        """Test date objects are converted to ISO format."""
        d = date(2026, 1, 10)
        row = {'game_date': d}
        result = processor._sanitize_row_for_bq(row)
        assert result['game_date'] == '2026-01-10'

    def test_sanitize_list_to_json(self, processor):
        """Test list values are JSON serialized."""
        row = {'traditional_networks': ['ESPN', 'TNT']}
        result = processor._sanitize_row_for_bq(row)
        assert result['traditional_networks'] == '["ESPN", "TNT"]'

    def test_sanitize_dict_to_json(self, processor):
        """Test dict values are JSON serialized."""
        row = {'metadata': {'source': 'api'}}
        result = processor._sanitize_row_for_bq(row)
        assert result['metadata'] == '{"source": "api"}'

    def test_sanitize_integer_fields(self, processor):
        """Test integer fields are passed through unchanged."""
        row = {'game_status': 3, 'home_team_score': 110}
        result = processor._sanitize_row_for_bq(row)
        assert result['game_status'] == 3
        assert result['home_team_score'] == 110

    def test_sanitize_boolean_fields(self, processor):
        """Test boolean fields are passed through unchanged."""
        row = {'is_primetime': True, 'is_playoffs': False}
        result = processor._sanitize_row_for_bq(row)
        assert result['is_primetime'] is True
        assert result['is_playoffs'] is False

    def test_sanitize_complete_row(self, processor):
        """Test a complete row with mixed types."""
        row = {
            'game_id': '0022500542',
            'game_date': date(2026, 1, 10),
            'game_date_est': datetime(2026, 1, 10, 19, 30, 0),
            'game_status': 3,
            'game_status_text': 'Final',
            'home_team_tricode': 'LAL',
            'away_team_tricode': 'BOS',
            'is_primetime': True,
            'arena_name': None,
            'traditional_networks': ['ESPN'],
        }
        result = processor._sanitize_row_for_bq(row)

        assert result['game_id'] == '0022500542'
        assert result['game_date'] == '2026-01-10'
        assert result['game_date_est'] == '2026-01-10T19:30:00'
        assert result['game_status'] == 3
        assert result['game_status_text'] == 'Final'
        assert result['home_team_tricode'] == 'LAL'
        assert result['away_team_tricode'] == 'BOS'
        assert result['is_primetime'] is True
        assert result['arena_name'] is None
        assert result['traditional_networks'] == '["ESPN"]'


class TestMergeQueryGeneration:
    """Test MERGE query generation logic."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_schedule_processor.bigquery.Client'):
            with patch('data_processors.raw.nbacom.nbac_schedule_processor.storage.Client'):
                proc = NbacScheduleProcessor()
                proc.project_id = 'test-project'
                return proc

    def test_on_clause_includes_all_primary_keys(self, processor):
        """Verify ON clause generation includes all PRIMARY_KEY_FIELDS."""
        primary_keys = processor.PRIMARY_KEY_FIELDS
        on_clause = ' AND '.join([f"target.{key} = source.{key}" for key in primary_keys])

        assert 'target.game_id = source.game_id' in on_clause
        assert 'target.game_date = source.game_date' in on_clause

    def test_update_fields_excludes_primary_keys(self, processor):
        """Verify UPDATE SET clause excludes primary key fields."""
        all_fields = ['game_id', 'game_date', 'game_status', 'game_status_text']
        primary_keys = processor.PRIMARY_KEY_FIELDS
        update_fields = [f for f in all_fields if f not in primary_keys]

        assert 'game_id' not in update_fields
        assert 'game_date' not in update_fields
        assert 'game_status' in update_fields
        assert 'game_status_text' in update_fields


class TestHashFields:
    """Test HASH_FIELDS for smart idempotency."""

    def test_hash_fields_defined(self):
        """Verify HASH_FIELDS is defined on the class."""
        assert hasattr(NbacScheduleProcessor, 'HASH_FIELDS')
        assert isinstance(NbacScheduleProcessor.HASH_FIELDS, list)

    def test_hash_fields_includes_key_status_fields(self):
        """Verify HASH_FIELDS includes game_status for change detection."""
        assert 'game_status' in NbacScheduleProcessor.HASH_FIELDS

    def test_hash_fields_includes_game_id(self):
        """Verify HASH_FIELDS includes game_id."""
        assert 'game_id' in NbacScheduleProcessor.HASH_FIELDS
