"""
orchestration/config_loader.py

Configuration loader with hot reload support for workflows.yaml.
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class WorkflowConfig:
    """
    Loads and validates workflow configuration from YAML.
    Supports hot reload (re-reads file if modified).
    """
    
    def __init__(self, config_path: str = "config/workflows.yaml"):
        self.config_path = config_path
        self._config: Optional[Dict[str, Any]] = None
        self._last_loaded: Optional[float] = None
        self._load_error: Optional[Exception] = None
    
    def get_config(self) -> Dict[str, Any]:
        """
        Get configuration, reloading if file changed.
        
        Returns:
            Dict with full configuration
        
        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If config file has invalid YAML
        """
        # Check if file was modified since last load
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        file_mtime = os.path.getmtime(self.config_path)
        
        # Reload if:
        # 1. Never loaded before, OR
        # 2. File modified since last load
        if self._last_loaded is None or file_mtime > self._last_loaded:
            try:
                with open(self.config_path, 'r') as f:
                    self._config = yaml.safe_load(f)
                
                self._last_loaded = file_mtime
                self._load_error = None
                
                logger.info("🔄 Reloaded workflow config from %s", self.config_path)
                
                # Basic validation
                self._validate_config(self._config)
                
            except Exception as e:
                self._load_error = e
                logger.error("Failed to load config: %s", e)
                
                # If we had a valid config before, keep using it
                if self._config is not None:
                    logger.warning("⚠️  Using previously loaded config due to load error")
                else:
                    # No fallback config, re-raise
                    raise
        
        return self._config
    
    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Basic config validation."""
        required_keys = ['version', 'environment', 'scrapers', 'workflows', 'settings']
        
        for key in required_keys:
            if key not in config:
                raise ValueError(f"Config missing required key: {key}")
        
        # Validate environment
        if config['environment'] not in ['production', 'dev']:
            raise ValueError(f"Invalid environment: {config['environment']}")
        
        # Validate workflows reference valid scrapers
        scraper_names = set(config['scrapers'].keys())
        
        for workflow_name, workflow_config in config['workflows'].items():
            execution_plan = workflow_config.get('execution_plan', {})
            
            # Check scrapers in execution plan
            if 'scrapers' in execution_plan:
                for scraper in execution_plan['scrapers']:
                    if scraper not in scraper_names:
                        raise ValueError(
                            f"Workflow '{workflow_name}' references unknown scraper: '{scraper}'"
                        )
            
            # Check single scraper
            if 'scraper' in execution_plan:
                scraper = execution_plan['scraper']
                if scraper not in scraper_names:
                    raise ValueError(
                        f"Workflow '{workflow_name}' references unknown scraper: '{scraper}'"
                    )
            
            # Check multi-step plans
            for key, value in execution_plan.items():
                if isinstance(value, dict) and 'scrapers' in value:
                    for scraper in value['scrapers']:
                        if scraper not in scraper_names:
                            raise ValueError(
                                f"Workflow '{workflow_name}' step '{key}' references unknown scraper: '{scraper}'"
                            )
    
    def get_workflow_config(self, workflow_name: str) -> Dict[str, Any]:
        """Get configuration for specific workflow."""
        config = self.get_config()
        
        if workflow_name not in config['workflows']:
            raise ValueError(f"Workflow not found: {workflow_name}")
        
        return config['workflows'][workflow_name]
    
    def get_scraper_config(self, scraper_name: str) -> Dict[str, Any]:
        """Get configuration for specific scraper."""
        config = self.get_config()
        
        if scraper_name not in config['scrapers']:
            raise ValueError(f"Scraper not found: {scraper_name}")
        
        return config['scrapers'][scraper_name]
    
    def is_workflow_enabled(self, workflow_name: str) -> bool:
        """Check if workflow is enabled."""
        try:
            workflow_config = self.get_workflow_config(workflow_name)
            return workflow_config.get('enabled', False)
        except ValueError:
            return False
    
    def get_enabled_workflows(self) -> list:
        """Get list of enabled workflow names."""
        config = self.get_config()
        return [
            name for name, wf_config in config['workflows'].items()
            if wf_config.get('enabled', False)
        ]
    
    def get_settings(self) -> Dict[str, Any]:
        """Get global settings."""
        config = self.get_config()
        return config.get('settings', {})
