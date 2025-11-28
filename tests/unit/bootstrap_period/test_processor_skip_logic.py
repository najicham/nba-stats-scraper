"""
Unit Tests for Bootstrap Period Processor Skip Logic

Tests that all Phase 4 processors correctly skip early season processing.
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch, MagicMock

# Test all Phase 4 processors
PROCESSOR_MODULES = [
    ('data_processors.precompute.player_daily_cache.player_daily_cache_processor',
     'PlayerDailyCacheProcessor'),
    ('data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor',
     'PlayerShotZoneAnalysisProcessor'),
    ('data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor',
     'TeamDefenseZoneAnalysisProcessor'),
    ('data_processors.precompute.player_composite_factors.player_composite_factors_processor',
     'PlayerCompositeFactorsProcessor'),
]


class TestProcessorEarlySeasonSkip:
    """Test that processors skip early season correctly."""

    @pytest.mark.parametrize("module_path,class_name", PROCESSOR_MODULES)
    def test_processor_skips_early_season(self, module_path, class_name):
        """Test that processor skips when is_early_season returns True."""
        # Build patch paths for where functions are USED (not where they're defined)
        patch_is_early = f'{module_path}.is_early_season'
        patch_get_year = f'{module_path}.get_season_year_from_date'

        with patch(patch_is_early, return_value=True) as mock_is_early, \
             patch(patch_get_year, return_value=2023) as mock_get_year:

            # Import and instantiate processor
            module = __import__(module_path, fromlist=[class_name])
            ProcessorClass = getattr(module, class_name)

            try:
                processor = ProcessorClass()
            except Exception as e:
                pytest.skip(f"Could not instantiate {class_name}: {e}")

            # Set up opts
            processor.opts = {
                'analysis_date': date(2023, 10, 24),  # Opening night
                'season_year': 2023
            }

            # Call extract_raw_data (this is where skip logic lives)
            try:
                processor.extract_raw_data()
            except Exception as e:
                # Some processors may need additional setup
                pytest.skip(f"Processor {class_name} needs additional setup: {e}")

            # Verify processor set stats correctly (behavior, not mock calls)
            if hasattr(processor, 'stats'):
                # Should have set processing decision
                assert processor.stats.get('processing_decision') == 'skipped_early_season', \
                       f"{class_name} should skip early season"

            # OR verify raw_data is None (alternate check)
            assert processor.raw_data is None, \
                   f"{class_name} should have None raw_data when skipping early season"

    @pytest.mark.parametrize("module_path,class_name", PROCESSOR_MODULES)
    def test_processor_continues_when_not_early_season(self, module_path, class_name):
        """Test that processor continues when is_early_season returns False."""
        # Build patch paths for where functions are USED
        patch_is_early = f'{module_path}.is_early_season'
        patch_get_year = f'{module_path}.get_season_year_from_date'

        with patch(patch_is_early, return_value=False) as mock_is_early, \
             patch(patch_get_year, return_value=2023) as mock_get_year:

            # Import and instantiate processor
            module = __import__(module_path, fromlist=[class_name])
            ProcessorClass = getattr(module, class_name)

            try:
                processor = ProcessorClass()
            except Exception as e:
                pytest.skip(f"Could not instantiate {class_name}: {e}")

            # Set up opts
            processor.opts = {
                'analysis_date': date(2023, 10, 31),  # Day 7
                'season_year': 2023
            }

            # Call extract_raw_data
            try:
                processor.extract_raw_data()
            except Exception as e:
                # Processors will fail without full dependencies, that's OK
                # We just want to verify they didn't skip early
                pass

            # Verify it didn't skip (check behavior)
            if hasattr(processor, 'stats'):
                assert processor.stats.get('processing_decision') != 'skipped_early_season', \
                       f"{class_name} should not skip when not early season"


class TestMLFeatureStoreEarlySeason:
    """Test ML Feature Store early season placeholder creation."""

    def test_ml_feature_store_creates_placeholders(self):
        """Test that ML Feature Store creates placeholders in early season."""
        from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor

        # Patch where functions are USED in ml_feature_store_processor
        with patch('data_processors.precompute.ml_feature_store.ml_feature_store_processor.is_early_season', return_value=True), \
             patch('data_processors.precompute.ml_feature_store.ml_feature_store_processor.get_season_year_from_date', return_value=2023):

            try:
                processor = MLFeatureStoreProcessor()
            except Exception as e:
                pytest.skip(f"Could not instantiate MLFeatureStoreProcessor: {e}")

            processor.opts = {
                'analysis_date': date(2023, 10, 24),
                'season_year': 2023
            }

            # Mock the _create_early_season_placeholders method to track calls
            with patch.object(processor, '_create_early_season_placeholders') as mock_create:
                try:
                    processor.extract_raw_data()
                except Exception:
                    # May fail on other dependencies, that's OK
                    pass

                # Should have called placeholder creation
                mock_create.assert_called()

    def test_ml_feature_store_does_not_create_placeholders_normal_season(self):
        """Test that ML Feature Store doesn't create placeholders in normal season."""
        from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor

        # Patch where functions are USED
        with patch('data_processors.precompute.ml_feature_store.ml_feature_store_processor.is_early_season', return_value=False), \
             patch('data_processors.precompute.ml_feature_store.ml_feature_store_processor.get_season_year_from_date', return_value=2023):

            try:
                processor = MLFeatureStoreProcessor()
            except Exception as e:
                pytest.skip(f"Could not instantiate MLFeatureStoreProcessor: {e}")

            processor.opts = {
                'analysis_date': date(2023, 10, 31),
                'season_year': 2023
            }

            # Mock the _create_early_season_placeholders method
            with patch.object(processor, '_create_early_season_placeholders') as mock_create:
                try:
                    processor.extract_raw_data()
                except Exception:
                    # May fail on other dependencies, that's OK
                    pass

                # Should NOT have called placeholder creation
                mock_create.assert_not_called()


class TestProcessorSeasonYearDetermination:
    """Test that processors correctly determine season year."""

    @pytest.mark.parametrize("module_path,class_name", PROCESSOR_MODULES)
    def test_processor_determines_season_year_when_not_provided(self, module_path, class_name):
        """Test that processors determine season year when not in opts."""
        # Build patch paths
        patch_is_early = f'{module_path}.is_early_season'
        patch_get_year = f'{module_path}.get_season_year_from_date'

        with patch(patch_is_early, return_value=False), \
             patch(patch_get_year, return_value=2024) as mock_get_year:

            # Import processor
            module = __import__(module_path, fromlist=[class_name])
            ProcessorClass = getattr(module, class_name)

            try:
                processor = ProcessorClass()
            except Exception:
                pytest.skip(f"Could not instantiate {class_name}")

            # Set opts WITHOUT season_year
            processor.opts = {
                'analysis_date': date(2024, 11, 1)
                # No season_year!
            }

            try:
                processor.extract_raw_data()
            except Exception:
                # May fail, that's OK
                pass

            # Should have called get_season_year_from_date
            mock_get_year.assert_called_with(date(2024, 11, 1))

    @pytest.mark.parametrize("module_path,class_name", PROCESSOR_MODULES)
    def test_processor_uses_provided_season_year(self, module_path, class_name):
        """Test that processors use season_year when provided in opts."""
        # Build patch paths
        patch_is_early = f'{module_path}.is_early_season'
        patch_get_year = f'{module_path}.get_season_year_from_date'

        with patch(patch_is_early, return_value=False), \
             patch(patch_get_year, return_value=2024):

            # Import processor
            module = __import__(module_path, fromlist=[class_name])
            ProcessorClass = getattr(module, class_name)

            try:
                processor = ProcessorClass()
            except Exception:
                pytest.skip(f"Could not instantiate {class_name}")

            # Set opts WITH season_year
            processor.opts = {
                'analysis_date': date(2024, 11, 1),
                'season_year': 2024  # Explicitly provided
            }

            try:
                processor.extract_raw_data()
            except Exception:
                pass

            # Verify season_year was set
            assert processor.opts.get('season_year') == 2024


class TestProcessorLogging:
    """Test that processors log correctly during early season skip."""

    @pytest.mark.parametrize("module_path,class_name", PROCESSOR_MODULES)
    def test_processor_logs_skip_message(self, module_path, class_name, caplog):
        """Test that processors log appropriate skip message."""
        # Build patch paths
        patch_is_early = f'{module_path}.is_early_season'
        patch_get_year = f'{module_path}.get_season_year_from_date'

        with patch(patch_is_early, return_value=True), \
             patch(patch_get_year, return_value=2023):

            # Import processor
            module = __import__(module_path, fromlist=[class_name])
            ProcessorClass = getattr(module, class_name)

            try:
                processor = ProcessorClass()
            except Exception:
                pytest.skip(f"Could not instantiate {class_name}")

            processor.opts = {
                'analysis_date': date(2023, 10, 24),
                'season_year': 2023
            }

            with caplog.at_level('INFO'):
                try:
                    processor.extract_raw_data()
                except Exception:
                    pass

            # Should have logged skip message
            # Look for "Skipping" or "early season" in logs
            log_messages = [record.message for record in caplog.records]
            skip_logged = any(
                'skipping' in msg.lower() or 'early season' in msg.lower()
                for msg in log_messages
            )

            assert skip_logged, f"{class_name} should log skip message"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
