"""
Unit tests for scrapers/registry.py

Tests scraper registry functionality including:
- Registry structure and completeness
- Scraper instantiation
- Error handling
- Info and listing functions

Path: tests/unit/scrapers/test_registry.py
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from scrapers.registry import (
    SCRAPER_REGISTRY,
    SCRAPER_GROUPS,
    get_scraper_instance,
    get_scraper_info,
    list_scrapers,
    scraper_exists,
    get_scrapers_by_group
)


class TestScraperRegistry:
    """Test the SCRAPER_REGISTRY structure and content."""
    
    def test_registry_not_empty(self):
        """Registry should contain scrapers."""
        assert len(SCRAPER_REGISTRY) > 0
        
    def test_registry_expected_count(self):
        """Registry should have 33 scrapers (as of Nov 2025)."""
        # 7 OddsAPI + 6 BDL + 2 BettingPros + 1 BR + 2 BigDataBall + 12 NBA.com + 3 ESPN
        expected_count = 33
        actual_count = len(SCRAPER_REGISTRY)
        assert actual_count == expected_count, (
            f"Expected {expected_count} scrapers, found {actual_count}. "
            f"Did you add or remove scrapers?"
        )
    
    def test_registry_format(self):
        """Each registry entry should have correct format."""
        for scraper_name, entry in SCRAPER_REGISTRY.items():
            # Entry should be tuple of 2 strings
            assert isinstance(entry, tuple), f"{scraper_name}: entry not a tuple"
            assert len(entry) == 2, f"{scraper_name}: entry should have 2 elements"
            
            module_path, class_name = entry
            assert isinstance(module_path, str), f"{scraper_name}: module_path not string"
            assert isinstance(class_name, str), f"{scraper_name}: class_name not string"
            assert len(module_path) > 0, f"{scraper_name}: module_path empty"
            assert len(class_name) > 0, f"{scraper_name}: class_name empty"
    
    def test_registry_no_duplicates(self):
        """Registry should not have duplicate scraper names."""
        names = list(SCRAPER_REGISTRY.keys())
        assert len(names) == len(set(names)), "Found duplicate scraper names"
    
    def test_registry_naming_convention(self):
        """Scraper names should follow snake_case convention."""
        for scraper_name in SCRAPER_REGISTRY.keys():
            # Should be lowercase with underscores
            assert scraper_name.islower(), f"{scraper_name} should be lowercase"
            assert " " not in scraper_name, f"{scraper_name} should not have spaces"


class TestScraperGroups:
    """Test the SCRAPER_GROUPS structure."""
    
    def test_groups_exist(self):
        """Scraper groups should be defined."""
        assert len(SCRAPER_GROUPS) > 0
    
    def test_expected_groups(self):
        """Should have expected scraper groups."""
        expected_groups = ['odds_api', 'ball_dont_lie', 'nba_com', 'espn', 'discovery']
        for group in expected_groups:
            assert group in SCRAPER_GROUPS, f"Missing group: {group}"
    
    def test_all_group_scrapers_in_registry(self):
        """All scrapers in groups should exist in main registry."""
        for group_name, scrapers in SCRAPER_GROUPS.items():
            for scraper_name in scrapers:
                assert scraper_name in SCRAPER_REGISTRY, (
                    f"Scraper '{scraper_name}' in group '{group_name}' "
                    f"not found in SCRAPER_REGISTRY"
                )
    
    def test_groups_cover_all_scrapers(self):
        """All scrapers should belong to at least one group."""
        all_grouped_scrapers = set()
        for scrapers in SCRAPER_GROUPS.values():
            all_grouped_scrapers.update(scrapers)
        
        ungrouped = set(SCRAPER_REGISTRY.keys()) - all_grouped_scrapers
        assert len(ungrouped) == 0, f"Ungrouped scrapers: {ungrouped}"


class TestGetScraperInstance:
    """Test the get_scraper_instance() function."""
    
    def test_unknown_scraper_raises_error(self):
        """Should raise ValueError for unknown scraper."""
        with pytest.raises(ValueError) as exc_info:
            get_scraper_instance('nonexistent_scraper')
        
        assert "Unknown scraper" in str(exc_info.value)
        assert "nonexistent_scraper" in str(exc_info.value)
    
    @patch('scrapers.registry.__import__')
    def test_successful_instantiation(self, mock_import):
        """Should successfully instantiate a valid scraper."""
        # Create mock scraper class
        mock_class = Mock()
        mock_instance = Mock()
        mock_class.return_value = mock_instance
        
        # Setup mock module
        mock_module = Mock()
        mock_module.GetOddsApiHistoricalEvents = mock_class
        mock_import.return_value = mock_module
        
        # Test instantiation
        result = get_scraper_instance('oddsa_events_his')
        
        # Verify
        assert result == mock_instance
        mock_import.assert_called_once()
        mock_class.assert_called_once_with()
    
    @patch('scrapers.registry.__import__')
    def test_import_error_handling(self, mock_import):
        """Should handle import errors gracefully."""
        mock_import.side_effect = ImportError("Module not found")
        
        with pytest.raises(ImportError) as exc_info:
            get_scraper_instance('oddsa_events_his')
        
        assert "Failed to load scraper" in str(exc_info.value)
    
    @patch('scrapers.registry.__import__')
    def test_attribute_error_handling(self, mock_import):
        """Should handle missing class errors gracefully."""
        mock_module = Mock()
        mock_module.GetOddsApiHistoricalEvents = None  # Class doesn't exist
        mock_import.return_value = mock_module
        
        # Make getattr raise AttributeError
        def side_effect(obj, name):
            raise AttributeError(f"No attribute {name}")
        
        with patch('builtins.getattr', side_effect=side_effect):
            with pytest.raises(ImportError) as exc_info:
                get_scraper_instance('oddsa_events_his')
        
        assert "Failed to load scraper" in str(exc_info.value)


class TestGetScraperInfo:
    """Test the get_scraper_info() function."""
    
    def test_get_info_single_scraper(self):
        """Should return info for a single scraper."""
        info = get_scraper_info('oddsa_events_his')
        
        assert 'name' in info
        assert 'module' in info
        assert 'class' in info
        assert info['name'] == 'oddsa_events_his'
        assert isinstance(info['module'], str)
        assert isinstance(info['class'], str)
    
    def test_get_info_all_scrapers(self):
        """Should return info for all scrapers when no name provided."""
        info = get_scraper_info()
        
        assert 'scrapers' in info
        assert 'count' in info
        assert isinstance(info['scrapers'], list)
        assert info['count'] == len(SCRAPER_REGISTRY)
        assert len(info['scrapers']) == info['count']
    
    def test_get_info_unknown_scraper(self):
        """Should raise ValueError for unknown scraper."""
        with pytest.raises(ValueError) as exc_info:
            get_scraper_info('nonexistent_scraper')
        
        assert "Unknown scraper" in str(exc_info.value)


class TestListScrapers:
    """Test the list_scrapers() function."""
    
    def test_returns_list(self):
        """Should return a list."""
        result = list_scrapers()
        assert isinstance(result, list)
    
    def test_correct_count(self):
        """Should return all scraper names."""
        result = list_scrapers()
        assert len(result) == len(SCRAPER_REGISTRY)
    
    def test_contains_known_scrapers(self):
        """Should contain known scraper names."""
        result = list_scrapers()
        assert 'oddsa_events_his' in result
        assert 'bdl_games' in result
        assert 'nbac_schedule_api' in result


class TestScraperExists:
    """Test the scraper_exists() function."""
    
    def test_existing_scraper(self):
        """Should return True for existing scraper."""
        assert scraper_exists('oddsa_events_his') is True
        assert scraper_exists('bdl_games') is True
    
    def test_nonexistent_scraper(self):
        """Should return False for nonexistent scraper."""
        assert scraper_exists('nonexistent_scraper') is False
        assert scraper_exists('') is False


class TestGetScrapersByGroup:
    """Test the get_scrapers_by_group() function."""
    
    def test_valid_group(self):
        """Should return scrapers for valid group."""
        result = get_scrapers_by_group('odds_api')
        assert isinstance(result, list)
        assert len(result) > 0
        assert 'oddsa_events_his' in result
    
    def test_all_groups(self):
        """Should return scrapers for all defined groups."""
        for group_name in SCRAPER_GROUPS.keys():
            result = get_scrapers_by_group(group_name)
            assert isinstance(result, list)
            assert len(result) > 0
    
    def test_invalid_group(self):
        """Should raise ValueError for invalid group."""
        with pytest.raises(ValueError) as exc_info:
            get_scrapers_by_group('nonexistent_group')
        
        assert "Unknown scraper group" in str(exc_info.value)


class TestRegistryIntegration:
    """Integration tests for registry functionality."""
    
    def test_can_list_and_get_info_for_all(self):
        """Should be able to list all scrapers and get info for each."""
        scrapers = list_scrapers()
        
        for scraper_name in scrapers:
            info = get_scraper_info(scraper_name)
            assert info['name'] == scraper_name
            assert len(info['module']) > 0
            assert len(info['class']) > 0
    
    def test_groups_consistency(self):
        """Group membership should be consistent with registry."""
        for group_name, group_scrapers in SCRAPER_GROUPS.items():
            # All scrapers in group should exist
            for scraper_name in group_scrapers:
                assert scraper_exists(scraper_name)
            
            # get_scrapers_by_group should return same list
            result = get_scrapers_by_group(group_name)
            assert set(result) == set(group_scrapers)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_scraper_names():
    """Sample scraper names for testing."""
    return [
        'oddsa_events_his',
        'bdl_games',
        'nbac_schedule_api',
        'espn_roster',
        'bigdataball_discovery'
    ]


# ============================================================================
# PARAMETRIZED TESTS
# ============================================================================

@pytest.mark.parametrize("scraper_name", [
    'oddsa_events_his',
    'bdl_games', 
    'nbac_schedule_api',
    'espn_roster'
])
def test_known_scrapers_exist(scraper_name):
    """Parametrized test: all known scrapers should exist."""
    assert scraper_exists(scraper_name)
    info = get_scraper_info(scraper_name)
    assert info['name'] == scraper_name


@pytest.mark.parametrize("group_name", list(SCRAPER_GROUPS.keys()))
def test_all_groups_return_scrapers(group_name):
    """Parametrized test: all groups should return at least one scraper."""
    scrapers = get_scrapers_by_group(group_name)
    assert len(scrapers) > 0
