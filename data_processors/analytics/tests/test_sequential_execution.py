#!/usr/bin/env python3
"""
Test sequential execution groups for race condition prevention.

Session 124 Tier 1 - Testing Fix 1.1

This module tests the sequential execution groups implementation that prevents
the Feb 3 race condition where PlayerGameSummaryProcessor ran before
TeamOffenseGameSummaryProcessor.

Key tests:
1. Sequential execution order (Level 1 → Level 2)
2. DependencyFailureError handling
3. Feature flag (SEQUENTIAL_EXECUTION_ENABLED)
4. Startup validation (duplicate processor detection)
"""

import logging
import time
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockProcessor:
    """Mock processor for testing."""

    def __init__(self, name, delay=0, should_fail=False):
        self.__name__ = name  # Use __name__ as attribute, not method
        self.delay = delay
        self.should_fail = should_fail
        self.start_time = None
        self.end_time = None

    def run(self, opts):
        """Simulate processor execution."""
        self.start_time = time.time()
        if self.delay > 0:
            time.sleep(self.delay)
        self.end_time = time.time()

        if self.should_fail:
            return False
        return True

    def get_analytics_stats(self):
        """Return mock stats."""
        return {
            "records_processed": 10,
            "duration_ms": (self.end_time - self.start_time) * 1000 if self.end_time else 0
        }


class TestSequentialExecution(unittest.TestCase):
    """Test sequential execution groups."""

    def setUp(self):
        """Set up test fixtures."""
        # Import after sys.path is set
        from data_processors.analytics.main_analytics_service import (
            run_processors_sequential,
            DependencyFailureError,
            normalize_trigger_config,
            SEQUENTIAL_EXECUTION_ENABLED
        )
        self.run_processors_sequential = run_processors_sequential
        self.DependencyFailureError = DependencyFailureError
        self.normalize_trigger_config = normalize_trigger_config
        self.SEQUENTIAL_EXECUTION_ENABLED = SEQUENTIAL_EXECUTION_ENABLED

    def test_sequential_execution_order(self):
        """Test that Level 1 completes before Level 2 starts."""
        # Create mock processors with artificial delays
        team_processor = MockProcessor("TeamOffenseGameSummaryProcessor", delay=0.2)
        player_processor = MockProcessor("PlayerGameSummaryProcessor", delay=0.1)

        # Configure processor groups
        processor_groups = [
            {
                'level': 1,
                'processors': [team_processor],
                'parallel': False,
                'dependencies': [],
                'description': 'Team stats'
            },
            {
                'level': 2,
                'processors': [player_processor],
                'parallel': False,
                'dependencies': ['TeamOffenseGameSummaryProcessor'],
                'description': 'Player stats'
            }
        ]

        opts = {
            'start_date': '2026-02-03',
            'end_date': '2026-02-03',
            'project_id': 'test-project'
        }

        # Mock run_single_analytics_processor to call processor.run()
        def mock_run_processor(proc_class, opts):
            success = proc_class.run(opts)
            return {
                'processor': proc_class.__name__,
                'status': 'success' if success else 'error',
                'stats': proc_class.get_analytics_stats()
            }

        with patch('data_processors.analytics.main_analytics_service.run_single_analytics_processor', side_effect=mock_run_processor):
            results = self.run_processors_sequential(processor_groups, opts)

        # Verify both processors completed
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]['processor'], 'TeamOffenseGameSummaryProcessor')
        self.assertEqual(results[1]['processor'], 'PlayerGameSummaryProcessor')

        # Verify sequential order: team processor finished before player started
        self.assertIsNotNone(team_processor.end_time)
        self.assertIsNotNone(player_processor.start_time)
        self.assertLess(team_processor.end_time, player_processor.start_time,
                        "Team processor should complete before player processor starts")

        logger.info(f"✅ Sequential execution order verified: "
                    f"Team finished at {team_processor.end_time:.3f}, "
                    f"Player started at {player_processor.start_time:.3f}")

    def test_dependency_failure_blocks_level2(self):
        """Test that Level 1 failure blocks Level 2 execution."""
        # Create mock processors where Level 1 fails
        team_processor = MockProcessor("TeamOffenseGameSummaryProcessor", should_fail=True)
        player_processor = MockProcessor("PlayerGameSummaryProcessor")

        processor_groups = [
            {
                'level': 1,
                'processors': [team_processor],
                'parallel': False,
                'dependencies': [],
                'description': 'Team stats'
            },
            {
                'level': 2,
                'processors': [player_processor],
                'parallel': False,
                'dependencies': ['TeamOffenseGameSummaryProcessor'],
                'description': 'Player stats'
            }
        ]

        opts = {
            'start_date': '2026-02-03',
            'end_date': '2026-02-03',
            'project_id': 'test-project'
        }

        def mock_run_processor(proc_class, opts):
            success = proc_class.run(opts)
            return {
                'processor': proc_class.__name__,
                'status': 'success' if success else 'error',
                'stats': proc_class.get_analytics_stats()
            }

        with patch('data_processors.analytics.main_analytics_service.run_single_analytics_processor', side_effect=mock_run_processor):
            with self.assertRaises(self.DependencyFailureError) as context:
                self.run_processors_sequential(processor_groups, opts)

        # Verify error message mentions the critical dependency
        self.assertIn('TeamOffenseGameSummaryProcessor', str(context.exception))

        # Verify player processor never started
        self.assertIsNone(player_processor.start_time,
                          "Player processor should not start if dependency fails")

        logger.info(f"✅ Dependency failure correctly blocks Level 2: {context.exception}")

    def test_normalize_trigger_config_list(self):
        """Test that simple list format is converted to group format."""
        # Simple list format (backward compatibility)
        from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

        simple_list = [PlayerGameSummaryProcessor]

        groups = self.normalize_trigger_config(simple_list)

        # Verify conversion to group format
        self.assertIsInstance(groups, list)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['level'], 1)
        self.assertEqual(groups[0]['processors'], simple_list)
        self.assertTrue(groups[0]['parallel'])
        self.assertEqual(groups[0]['dependencies'], [])

        logger.info(f"✅ Simple list correctly normalized to group format")

    def test_normalize_trigger_config_dict(self):
        """Test that dict format is preserved."""
        # Dict format (already in group format)
        from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

        dict_format = [
            {
                'level': 1,
                'processors': [PlayerGameSummaryProcessor],
                'parallel': False,
                'dependencies': [],
                'description': 'Test'
            }
        ]

        groups = self.normalize_trigger_config(dict_format)

        # Verify format is unchanged
        self.assertEqual(groups, dict_format)

        logger.info(f"✅ Dict format correctly preserved")

    def test_empty_config(self):
        """Test that empty config returns empty list."""
        groups = self.normalize_trigger_config([])
        self.assertEqual(groups, [])

        groups = self.normalize_trigger_config(None)
        self.assertEqual(groups, [])

        logger.info(f"✅ Empty config correctly handled")

    def test_feature_flag_enabled(self):
        """Test that SEQUENTIAL_EXECUTION_ENABLED is set correctly."""
        # This test verifies the feature flag is accessible
        # The actual value depends on environment variable
        self.assertIsInstance(self.SEQUENTIAL_EXECUTION_ENABLED, bool)
        logger.info(f"✅ Feature flag SEQUENTIAL_EXECUTION_ENABLED = {self.SEQUENTIAL_EXECUTION_ENABLED}")

    def test_partial_level1_failure_with_specific_dependency(self):
        """Test that only specific dependencies are checked, not all Level 1 processors."""
        # PlayerGameSummaryProcessor depends on TeamOffenseGameSummaryProcessor (NOT TeamDefense)
        # If TeamDefense fails but TeamOffense succeeds, Player should still run

        team_offense = MockProcessor("TeamOffenseGameSummaryProcessor", delay=0.1)
        team_defense = MockProcessor("TeamDefenseGameSummaryProcessor", should_fail=True)
        player = MockProcessor("PlayerGameSummaryProcessor", delay=0.1)

        processor_groups = [
            {
                'level': 1,
                'processors': [team_offense, team_defense],
                'parallel': True,  # Both run in parallel
                'dependencies': [],
                'description': 'Team stats'
            },
            {
                'level': 2,
                'processors': [player],
                'parallel': False,
                'dependencies': ['TeamOffenseGameSummaryProcessor'],  # ONLY depends on offense
                'description': 'Player stats'
            }
        ]

        opts = {
            'start_date': '2026-02-03',
            'end_date': '2026-02-03',
            'project_id': 'test-project'
        }

        def mock_run_processor(proc_class, opts):
            success = proc_class.run(opts)
            return {
                'processor': proc_class.__name__,
                'status': 'success' if success else 'error',
                'stats': proc_class.get_analytics_stats()
            }

        with patch('data_processors.analytics.main_analytics_service.run_single_analytics_processor', side_effect=mock_run_processor):
            # This should NOT raise DependencyFailureError because TeamDefense is not a dependency
            results = self.run_processors_sequential(processor_groups, opts)

        # Verify player processor ran despite TeamDefense failure
        self.assertIsNotNone(player.start_time,
                             "Player processor should run if SPECIFIC dependency (TeamOffense) succeeds")

        logger.info(f"✅ Partial Level 1 failure correctly handled (specific dependencies)")


class TestStartupValidation(unittest.TestCase):
    """Test startup validation."""

    def test_validate_processor_groups_no_duplicates(self):
        """Test that validate_processor_groups accepts valid configs."""
        # This test verifies that the validation function doesn't raise errors
        # for valid configs (already run at startup)

        from data_processors.analytics.main_analytics_service import validate_processor_groups

        # Should not raise any errors
        try:
            validate_processor_groups()
            success = True
        except Exception as e:
            success = False
            logger.error(f"Validation failed: {e}")

        self.assertTrue(success, "validate_processor_groups should accept current config")
        logger.info(f"✅ Startup validation passed")


if __name__ == '__main__':
    unittest.main()
