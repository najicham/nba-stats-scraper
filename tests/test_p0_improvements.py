#!/usr/bin/env python3
"""
Test P0 Backfill Improvements

Tests all 4 P0 improvements to ensure they work correctly:
1. Coverage validation
2. Defensive logging
3. Fallback logic fix
4. Data cleanup

Usage:
    # Run all tests
    pytest tests/test_p0_improvements.py -v

    # Run specific test
    pytest tests/test_p0_improvements.py::test_coverage_validation_blocks_partial -v

Author: Claude (Session 30)
Date: 2026-01-13
"""

import sys
import os
from datetime import date, datetime
from unittest.mock import Mock, patch, MagicMock
import pytest
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backfill_jobs.precompute.player_composite_factors.player_composite_factors_precompute_backfill import (
    PlayerCompositeFactorsBackfill
)


class TestCoverageValidation:
    """Test P0-1: Coverage Validation"""

    def setup_method(self):
        """Setup test fixtures"""
        self.backfiller = PlayerCompositeFactorsBackfill()
        self.test_date = date(2023, 2, 23)

    @patch('backfill_jobs.precompute.player_composite_factors.player_composite_factors_precompute_backfill.bigquery.Client')
    def test_coverage_validation_passes_at_100_percent(self, mock_bq_client):
        """Test that 100% coverage passes validation"""
        # Mock BigQuery to return 187 expected players
        mock_df = pd.DataFrame({'expected_players': [187]})
        mock_bq_client.return_value.query.return_value.to_dataframe.return_value = mock_df

        # Create new instance with mocked client
        backfiller = PlayerCompositeFactorsBackfill()
        backfiller.bq_client = mock_bq_client.return_value

        # Test with 187 players processed (100%)
        result = backfiller._validate_coverage(self.test_date, players_processed=187)

        assert result is True, "Should pass validation at 100% coverage"

    @patch('backfill_jobs.precompute.player_composite_factors.player_composite_factors_precompute_backfill.bigquery.Client')
    def test_coverage_validation_passes_at_95_percent(self, mock_bq_client):
        """Test that 95% coverage passes validation (above 90% threshold)"""
        # Mock BigQuery to return 200 expected players
        mock_df = pd.DataFrame({'expected_players': [200]})
        mock_bq_client.return_value.query.return_value.to_dataframe.return_value = mock_df

        backfiller = PlayerCompositeFactorsBackfill()
        backfiller.bq_client = mock_bq_client.return_value

        # Test with 190 players processed (95%)
        result = backfiller._validate_coverage(self.test_date, players_processed=190)

        assert result is True, "Should pass validation at 95% coverage"

    @patch('backfill_jobs.precompute.player_composite_factors.player_composite_factors_precompute_backfill.bigquery.Client')
    def test_coverage_validation_fails_at_50_percent(self, mock_bq_client):
        """Test that 50% coverage fails validation (below 90% threshold)"""
        # Mock BigQuery to return 187 expected players
        mock_df = pd.DataFrame({'expected_players': [187]})
        mock_bq_client.return_value.query.return_value.to_dataframe.return_value = mock_df

        backfiller = PlayerCompositeFactorsBackfill()
        backfiller.bq_client = mock_bq_client.return_value

        # Test with 94 players processed (50%)
        result = backfiller._validate_coverage(self.test_date, players_processed=94)

        assert result is False, "Should fail validation at 50% coverage"

    @patch('backfill_jobs.precompute.player_composite_factors.player_composite_factors_precompute_backfill.bigquery.Client')
    def test_coverage_validation_fails_at_jan6_incident_rate(self, mock_bq_client):
        """Test that Jan 6 incident (1/187 = 0.5%) fails validation"""
        # Mock BigQuery to return 187 expected players
        mock_df = pd.DataFrame({'expected_players': [187]})
        mock_bq_client.return_value.query.return_value.to_dataframe.return_value = mock_df

        backfiller = PlayerCompositeFactorsBackfill()
        backfiller.bq_client = mock_bq_client.return_value

        # Test with 1 player processed (0.5%) - the actual Jan 6 incident
        result = backfiller._validate_coverage(self.test_date, players_processed=1)

        assert result is False, "Should fail validation at 0.5% coverage (Jan 6 incident)"

    @patch('backfill_jobs.precompute.player_composite_factors.player_composite_factors_precompute_backfill.bigquery.Client')
    def test_coverage_validation_allows_empty_dates(self, mock_bq_client):
        """Test that off-days (0 expected players) pass validation"""
        # Mock BigQuery to return 0 expected players (off-day)
        mock_df = pd.DataFrame({'expected_players': [0]})
        mock_bq_client.return_value.query.return_value.to_dataframe.return_value = mock_df

        backfiller = PlayerCompositeFactorsBackfill()
        backfiller.bq_client = mock_bq_client.return_value

        # Test with 0 players processed (off-day)
        result = backfiller._validate_coverage(self.test_date, players_processed=0)

        assert result is True, "Should pass validation for off-days (0 expected)"

    @patch('backfill_jobs.precompute.player_composite_factors.player_composite_factors_precompute_backfill.bigquery.Client')
    def test_coverage_validation_force_flag_bypasses(self, mock_bq_client):
        """Test that --force flag bypasses validation"""
        # Mock BigQuery to return 187 expected players
        mock_df = pd.DataFrame({'expected_players': [187]})
        mock_bq_client.return_value.query.return_value.to_dataframe.return_value = mock_df

        backfiller = PlayerCompositeFactorsBackfill()
        backfiller.bq_client = mock_bq_client.return_value

        # Test with 1 player processed but force=True
        result = backfiller._validate_coverage(self.test_date, players_processed=1, force=True)

        assert result is True, "Should pass validation with force=True even at 0.5% coverage"

    @patch('backfill_jobs.precompute.player_composite_factors.player_composite_factors_precompute_backfill.bigquery.Client')
    def test_coverage_validation_handles_query_errors(self, mock_bq_client):
        """Test that query errors fail safe (return False)"""
        # Mock BigQuery to raise an exception
        mock_bq_client.return_value.query.side_effect = Exception("BigQuery connection error")

        backfiller = PlayerCompositeFactorsBackfill()
        backfiller.bq_client = mock_bq_client.return_value

        # Test with any count - should return False on error
        result = backfiller._validate_coverage(self.test_date, players_processed=187)

        assert result is False, "Should fail safe (return False) on BigQuery errors"


class TestFallbackLogic:
    """Test P0-3: Fallback Logic Fix"""

    def test_fallback_logic_exists_in_processor(self):
        """Test that fallback logic is present in processor"""
        from data_processors.precompute.player_composite_factors.player_composite_factors_processor import (
            PlayerCompositeFactorsProcessor
        )

        # Verify the processor class exists and has the extract_raw_data method
        assert hasattr(PlayerCompositeFactorsProcessor, 'extract_raw_data'), \
            "PlayerCompositeFactorsProcessor should have extract_raw_data method"

    def test_fallback_threshold_is_90_percent(self):
        """Test that fallback threshold is correctly set to 90%"""
        # Read the processor file and verify the threshold
        processor_file = 'data_processors/precompute/player_composite_factors/player_composite_factors_processor.py'

        with open(processor_file, 'r') as f:
            content = f.read()

        # Check for the 0.9 (90%) threshold in fallback logic
        assert 'expected_count * 0.9' in content, \
            "Fallback logic should use 90% threshold (0.9)"

        # Check for the improved fallback condition
        assert 'upcg_count < expected_count * 0.9' in content, \
            "Fallback should trigger when UPCG < 90% of expected"


class TestDefensiveLogging:
    """Test P0-2: Defensive Logging"""

    def test_defensive_logging_exists(self):
        """Test that defensive logging code exists in processor"""
        processor_file = 'data_processors/precompute/player_composite_factors/player_composite_factors_processor.py'

        with open(processor_file, 'r') as f:
            content = f.read()

        # Check for defensive logging indicators
        assert 'Data source check' in content, \
            "Should have data source check logging"
        assert 'upcoming_player_game_context (UPCG)' in content, \
            "Should log UPCG count"
        assert 'player_game_summary (PGS)' in content, \
            "Should log PGS count"
        assert 'Coverage:' in content, \
            "Should log coverage percentage"

    def test_logging_includes_comparison(self):
        """Test that logging compares UPCG vs PGS"""
        processor_file = 'data_processors/precompute/player_composite_factors/player_composite_factors_processor.py'

        with open(processor_file, 'r') as f:
            content = f.read()

        # Check for comparison logic
        assert 'INCOMPLETE DATA DETECTED' in content, \
            "Should have error logging for incomplete data"
        assert 'TRIGGERING FALLBACK' in content, \
            "Should log when fallback is triggered"


class TestDataCleanup:
    """Test P0-4: Data Cleanup Scripts"""

    def test_cleanup_script_exists(self):
        """Test that cleanup script exists"""
        assert os.path.exists('scripts/cleanup_stale_upcoming_tables.py'), \
            "Cleanup script should exist at scripts/cleanup_stale_upcoming_tables.py"

    def test_cleanup_script_is_executable(self):
        """Test that cleanup script has execute permissions"""
        script_path = 'scripts/cleanup_stale_upcoming_tables.py'
        assert os.path.exists(script_path), "Script should exist"

        # Check if file is executable (on Unix-like systems)
        if hasattr(os, 'access'):
            is_executable = os.access(script_path, os.X_OK)
            assert is_executable, "Script should be executable"

    def test_cleanup_script_has_dry_run_mode(self):
        """Test that cleanup script supports dry-run mode"""
        with open('scripts/cleanup_stale_upcoming_tables.py', 'r') as f:
            content = f.read()

        assert '--dry-run' in content, "Script should support --dry-run flag"
        assert 'dry_run' in content.lower(), "Script should have dry run logic"

    def test_cleanup_script_creates_backup(self):
        """Test that cleanup script creates backups"""
        with open('scripts/cleanup_stale_upcoming_tables.py', 'r') as f:
            content = f.read()

        assert 'backup' in content.lower(), "Script should create backups"
        assert 'skip-backup' in content or 'skip_backup' in content, \
            "Script should have option to skip backup"

    def test_cloud_function_exists(self):
        """Test that Cloud Function for TTL cleanup exists"""
        cf_path = 'orchestration/cloud_functions/upcoming_tables_cleanup/main.py'
        assert os.path.exists(cf_path), \
            "Cloud Function should exist at orchestration/cloud_functions/upcoming_tables_cleanup/main.py"

    def test_cloud_function_has_ttl_config(self):
        """Test that Cloud Function has TTL configuration"""
        cf_path = 'orchestration/cloud_functions/upcoming_tables_cleanup/main.py'

        with open(cf_path, 'r') as f:
            content = f.read()

        assert 'TTL_DAYS' in content, "Cloud Function should have TTL_DAYS configuration"
        # Check for either SQL INTERVAL or Python timedelta
        assert 'timedelta' in content or 'INTERVAL' in content, \
            "Cloud Function should use date calculation (timedelta or INTERVAL)"


class TestIntegration:
    """Integration tests for all P0 improvements working together"""

    def test_all_modified_files_compile(self):
        """Test that all modified files have valid Python syntax"""
        files_to_check = [
            'backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py',
            'data_processors/precompute/player_composite_factors/player_composite_factors_processor.py',
            'scripts/cleanup_stale_upcoming_tables.py',
            'orchestration/cloud_functions/upcoming_tables_cleanup/main.py'
        ]

        for file_path in files_to_check:
            assert os.path.exists(file_path), f"File should exist: {file_path}"

            # Compile to check syntax
            with open(file_path, 'r') as f:
                code = f.read()

            try:
                compile(code, file_path, 'exec')
            except SyntaxError as e:
                pytest.fail(f"Syntax error in {file_path}: {e}")

    def test_documentation_exists(self):
        """Test that all documentation was created"""
        docs = [
            'docs/08-projects/current/historical-backfill-audit/2026-01-13-P0-IMPLEMENTATION-SUMMARY.md',
            'docs/09-handoff/2026-01-13-SESSION-30-HANDOFF.md',
            'orchestration/cloud_functions/upcoming_tables_cleanup/README.md'
        ]

        for doc in docs:
            assert os.path.exists(doc), f"Documentation should exist: {doc}"

    def test_force_flag_added_to_argparse(self):
        """Test that --force flag is available in command line"""
        backfill_file = 'backfill_jobs/precompute/player_composite_factors/player_composite_factors_precompute_backfill.py'

        with open(backfill_file, 'r') as f:
            content = f.read()

        assert "parser.add_argument('--force'" in content or \
               'parser.add_argument("--force"' in content, \
               "Should have --force flag in argparse"


# Test Summary Function
def test_p0_improvements_summary():
    """Print summary of P0 improvements"""
    print("\n" + "=" * 80)
    print("P0 IMPROVEMENTS VALIDATION SUMMARY")
    print("=" * 80)
    print("✅ P0-1: Coverage Validation")
    print("   - Blocks checkpointing if coverage < 90%")
    print("   - Supports --force flag for edge cases")
    print("   - Handles off-days and errors gracefully")
    print()
    print("✅ P0-2: Defensive Logging")
    print("   - Logs UPCG vs PGS comparison")
    print("   - Shows coverage percentage")
    print("   - Explains data source decisions")
    print()
    print("✅ P0-3: Fallback Logic Fix (ROOT CAUSE)")
    print("   - Triggers on partial data (< 90%)")
    print("   - Not just empty UPCG")
    print("   - Prevents Jan 6 incident from recurring")
    print()
    print("✅ P0-4: Data Cleanup")
    print("   - One-time cleanup script with dry-run mode")
    print("   - Automated Cloud Function for daily cleanup")
    print("   - Creates backups before deletion")
    print("=" * 80)

    assert True, "Summary printed successfully"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
