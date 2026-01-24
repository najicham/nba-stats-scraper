"""
Unit tests for orchestration/config_loader.py

Tests workflow configuration loading, validation, and hot-reload functionality.

Path: tests/unit/orchestration/test_config_loader.py
"""

import pytest
import yaml
from datetime import time
from unittest.mock import Mock, patch, mock_open
from orchestration.config_loader import WorkflowConfig


# Sample YAML config for testing
SAMPLE_CONFIG_YAML = """
workflows:
  test_workflow:
    enabled: true
    description: "Test workflow for unit tests"
    schedule:
      days_of_week: ["monday", "tuesday", "wednesday", "thursday", "friday"]
      time_windows:
        - start: "06:00"
          end: "08:00"
    conditions:
      games_today_required: true
      hours_before_first_game: 4.0
      cooldown_hours: 24
    scrapers:
      - name: "test_scraper_1"
        order: 1
        timeout_minutes: 5
        required: true
      - name: "test_scraper_2"
        order: 2
        timeout_minutes: 10
        required: false

  disabled_workflow:
    enabled: false
    description: "This workflow is disabled"
    schedule:
      days_of_week: ["monday"]
      time_windows:
        - start: "09:00"
          end: "10:00"
    conditions:
      games_today_required: false
    scrapers:
      - name: "test_scraper_3"
        order: 1

settings:
  timezone: "America/New_York"
  max_concurrent_workflows: 3
  default_timeout_minutes: 30
  retry_attempts: 3
"""


class TestWorkflowConfigInit:
    """Test WorkflowConfig initialization."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_successful_init(self, mock_exists):
        """Should successfully initialize with valid config file."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        
        assert config._config is not None
        assert 'workflows' in config._config
        assert 'settings' in config._config
    
    @patch('os.path.exists', return_value=False)
    def test_missing_config_file(self, mock_exists):
        """Should raise FileNotFoundError for missing config."""
        with pytest.raises(FileNotFoundError) as exc_info:
            WorkflowConfig(config_path='nonexistent.yaml')
        
        assert "Config file not found" in str(exc_info.value)
    
    @patch('builtins.open', mock_open(read_data="invalid: yaml: content: ["))
    @patch('os.path.exists', return_value=True)
    def test_invalid_yaml(self, mock_exists):
        """Should raise ValueError for invalid YAML."""
        with pytest.raises(ValueError) as exc_info:
            WorkflowConfig(config_path='config/workflows.yaml')
        
        assert "Invalid YAML" in str(exc_info.value)


class TestGetWorkflow:
    """Test getting workflow configuration."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_existing_workflow(self, mock_exists):
        """Should return workflow config for existing workflow."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        workflow = config.get_workflow('test_workflow')
        
        assert workflow is not None
        assert workflow['enabled'] is True
        assert workflow['description'] == "Test workflow for unit tests"
        assert 'schedule' in workflow
        assert 'conditions' in workflow
        assert 'scrapers' in workflow
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_nonexistent_workflow(self, mock_exists):
        """Should return None for nonexistent workflow."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        workflow = config.get_workflow('nonexistent_workflow')
        
        assert workflow is None


class TestGetEnabledWorkflows:
    """Test getting enabled workflows."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_enabled_workflows(self, mock_exists):
        """Should return only enabled workflows."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        enabled = config.get_enabled_workflows()
        
        assert 'test_workflow' in enabled
        assert 'disabled_workflow' not in enabled
        assert len(enabled) == 1
    
    @patch('builtins.open', mock_open(read_data="""
workflows:
  workflow_1:
    enabled: false
  workflow_2:
    enabled: false
settings:
  timezone: "America/New_York"
"""))
    @patch('os.path.exists', return_value=True)
    def test_no_enabled_workflows(self, mock_exists):
        """Should return empty list when no workflows enabled."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        enabled = config.get_enabled_workflows()
        
        assert len(enabled) == 0
        assert isinstance(enabled, list)


class TestGetWorkflows:
    """Test getting all workflows."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_all_workflows(self, mock_exists):
        """Should return all workflows."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        workflows = config.get_workflows()
        
        assert 'test_workflow' in workflows
        assert 'disabled_workflow' in workflows
        assert len(workflows) == 2


class TestGetSettings:
    """Test getting settings."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_settings(self, mock_exists):
        """Should return settings dictionary."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        settings = config.get_settings()
        
        assert 'timezone' in settings
        assert settings['timezone'] == 'America/New_York'
        assert 'max_concurrent_workflows' in settings
        assert settings['max_concurrent_workflows'] == 3
    
    @patch('builtins.open', mock_open(read_data="""
workflows:
  test_workflow:
    enabled: true
# No settings section
"""))
    @patch('os.path.exists', return_value=True)
    def test_missing_settings_section(self, mock_exists):
        """Should return empty dict when settings section missing."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        settings = config.get_settings()
        
        assert isinstance(settings, dict)
        assert len(settings) == 0


class TestGetScrapers:
    """Test getting scrapers for a workflow."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_scrapers(self, mock_exists):
        """Should return list of scrapers for workflow."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        scrapers = config.get_scrapers('test_workflow')
        
        assert len(scrapers) == 2
        assert scrapers[0]['name'] == 'test_scraper_1'
        assert scrapers[0]['order'] == 1
        assert scrapers[0]['required'] is True
        assert scrapers[1]['name'] == 'test_scraper_2'
        assert scrapers[1]['order'] == 2
        assert scrapers[1]['required'] is False
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_scrapers_sorted(self, mock_exists):
        """Should return scrapers sorted by order."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        scrapers = config.get_scrapers('test_workflow')
        
        # Verify order is ascending
        orders = [s['order'] for s in scrapers]
        assert orders == sorted(orders)
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_scrapers_nonexistent_workflow(self, mock_exists):
        """Should return empty list for nonexistent workflow."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        scrapers = config.get_scrapers('nonexistent')
        
        assert scrapers == []


class TestIsWorkflowEnabled:
    """Test checking if workflow is enabled."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_enabled_workflow(self, mock_exists):
        """Should return True for enabled workflow."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        assert config.is_workflow_enabled('test_workflow') is True
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_disabled_workflow(self, mock_exists):
        """Should return False for disabled workflow."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        assert config.is_workflow_enabled('disabled_workflow') is False
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_nonexistent_workflow(self, mock_exists):
        """Should return False for nonexistent workflow."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        assert config.is_workflow_enabled('nonexistent') is False


class TestHotReload:
    """Test configuration hot reload functionality."""
    
    @patch('builtins.open')
    @patch('os.path.exists', return_value=True)
    @patch('os.path.getmtime')
    def test_reload_when_file_modified(self, mock_getmtime, mock_exists, mock_file):
        """Should reload config when file is modified."""
        # Setup mock file reads
        mock_file.return_value = mock_open(read_data=SAMPLE_CONFIG_YAML).return_value
        
        # First load - time = 1000
        mock_getmtime.return_value = 1000
        config = WorkflowConfig(config_path='config/workflows.yaml')
        original_config = config._config
        
        # Simulate file modification - time = 2000
        mock_getmtime.return_value = 2000
        
        # Get workflow - should trigger reload
        workflow = config.get_workflow('test_workflow')
        
        # Config should be reloaded (new object)
        assert config._config is not original_config
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    @patch('os.path.getmtime')
    def test_no_reload_when_file_unchanged(self, mock_getmtime, mock_exists):
        """Should not reload config when file unchanged."""
        # Constant modification time
        mock_getmtime.return_value = 1000
        
        config = WorkflowConfig(config_path='config/workflows.yaml')
        original_config = config._config
        
        # Get workflow multiple times
        config.get_workflow('test_workflow')
        config.get_workflow('test_workflow')
        
        # Config should be same object (not reloaded)
        assert config._config is original_config


class TestGetConfig:
    """Test getting full config."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_get_full_config(self, mock_exists):
        """Should return complete config dictionary."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        full_config = config.get_config()
        
        assert 'workflows' in full_config
        assert 'settings' in full_config
        assert len(full_config['workflows']) == 2


class TestWorkflowValidation:
    """Test workflow configuration validation."""
    
    @patch('builtins.open', mock_open(read_data="""
workflows:
  invalid_workflow:
    enabled: true
    # Missing required fields
settings:
  timezone: "America/New_York"
"""))
    @patch('os.path.exists', return_value=True)
    def test_handles_invalid_workflow_structure(self, mock_exists):
        """Should handle workflows with missing required fields gracefully."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        
        # Should not crash, but workflow may be incomplete
        workflow = config.get_workflow('invalid_workflow')
        assert workflow is not None
        
        # Should handle missing scrapers gracefully
        scrapers = config.get_scrapers('invalid_workflow')
        assert isinstance(scrapers, list)


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestConfigIntegration:
    """Integration tests for config loader."""
    
    @patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML))
    @patch('os.path.exists', return_value=True)
    def test_full_workflow_access_pattern(self, mock_exists):
        """Test typical usage pattern for workflow access."""
        config = WorkflowConfig(config_path='config/workflows.yaml')
        
        # Get enabled workflows
        enabled_workflows = config.get_enabled_workflows()
        assert len(enabled_workflows) > 0
        
        # For each enabled workflow
        for workflow_name in enabled_workflows:
            # Get workflow config
            workflow = config.get_workflow(workflow_name)
            assert workflow is not None
            
            # Get scrapers for workflow
            scrapers = config.get_scrapers(workflow_name)
            assert isinstance(scrapers, list)
            
            # Get settings
            settings = config.get_settings()
            assert 'timezone' in settings


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def config_loader():
    """Fixture providing a configured WorkflowConfig instance."""
    with patch('builtins.open', mock_open(read_data=SAMPLE_CONFIG_YAML)), \
         patch('os.path.exists', return_value=True):
        return WorkflowConfig(config_path='config/workflows.yaml')
