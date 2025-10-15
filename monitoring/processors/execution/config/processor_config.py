"""
File: monitoring/processor_execution_monitoring/config/processor_config.py

Processor Execution Monitoring Configuration Registry

Defines monitoring parameters for processors that log execution history.
Start with name registry processors (gamebook, roster).
"""

from typing import Dict, Any, Optional


# Processor execution monitoring configuration registry
PROCESSOR_MONITORING_CONFIG = {
    
    # Name Registry - Gamebook Processor
    'gamebook_processor': {
        'display_name': 'Gamebook Registry Processor',
        'execution_table': 'nba_reference.processor_run_history',
        'processor_filter': "processor_name = 'gamebook'",
        'date_field': 'processing_date',
        'status_field': 'status',
        
        # Scheduling expectations
        'expected_frequency': 'daily',  # How often it should run
        'staleness_threshold_days': 2,  # Alert if no success in N days
        
        # Monitoring settings
        'enabled': True,
        'priority': 'critical',  # critical, high, medium, low
        'revenue_impact': True,
        
        # Additional metadata
        'docs_url': 'https://docs.example.com/processors/gamebook-registry',
        'notes': 'Processes gamebook data into name registry - runs nightly after games'
    },
    
    # Name Registry - Roster Processor
    'roster_processor': {
        'display_name': 'Roster Registry Processor',
        'execution_table': 'nba_reference.processor_run_history',
        'processor_filter': "processor_name = 'roster'",
        'date_field': 'processing_date',
        'status_field': 'status',
        
        'expected_frequency': 'daily',
        'staleness_threshold_days': 3,  # More tolerant than gamebook
        
        'enabled': True,
        'priority': 'high',
        'revenue_impact': True,
        
        'docs_url': 'https://docs.example.com/processors/roster-registry',
        'notes': 'Updates roster registry - runs daily in morning operations'
    },
    
    # Template for adding more processors
    'template_processor': {
        'display_name': 'Human Readable Name',
        'execution_table': 'dataset.processor_run_history_table',
        'processor_filter': "processor_name = 'my_processor'",
        'date_field': 'processing_date',
        'status_field': 'status',
        
        'expected_frequency': 'daily',  # daily, hourly, weekly
        'staleness_threshold_days': 2,
        
        'enabled': False,
        'priority': 'medium',
        'revenue_impact': False,
        
        'docs_url': '',
        'notes': ''
    }
}


class ProcessorConfig:
    """Wrapper class for processor configuration with helper methods."""
    
    def __init__(self, processor_name: str):
        """Initialize with processor configuration."""
        if processor_name not in PROCESSOR_MONITORING_CONFIG:
            raise ValueError(f"Unknown processor: {processor_name}")
        
        self.name = processor_name
        self._config = PROCESSOR_MONITORING_CONFIG[processor_name]
    
    @property
    def enabled(self) -> bool:
        """Check if monitoring is enabled."""
        return self._config.get('enabled', False)
    
    @property
    def display_name(self) -> str:
        """Get display name."""
        return self._config['display_name']
    
    @property
    def execution_table(self) -> str:
        """Get fully qualified execution history table name."""
        table = self._config['execution_table']
        # Add project if not present
        if '.' in table and table.count('.') == 1:
            return f"nba-props-platform.{table}"
        return table
    
    @property
    def processor_filter(self) -> str:
        """Get WHERE clause filter for this processor."""
        return self._config['processor_filter']
    
    @property
    def date_field(self) -> str:
        """Get field name for processing date."""
        return self._config.get('date_field', 'processing_date')
    
    @property
    def status_field(self) -> str:
        """Get field name for run status."""
        return self._config.get('status_field', 'status')
    
    @property
    def expected_frequency(self) -> str:
        """Get expected run frequency."""
        return self._config.get('expected_frequency', 'daily')
    
    @property
    def staleness_threshold_days(self) -> int:
        """Get staleness threshold in days."""
        return self._config.get('staleness_threshold_days', 2)
    
    @property
    def priority(self) -> str:
        """Get processor priority level."""
        return self._config.get('priority', 'medium')
    
    @property
    def revenue_impact(self) -> bool:
        """Check if processor has revenue impact."""
        return self._config.get('revenue_impact', False)
    
    @property
    def notes(self) -> Optional[str]:
        """Get implementation notes if available."""
        return self._config.get('notes')
    
    def to_dict(self) -> Dict[str, Any]:
        """Get full configuration as dictionary."""
        return self._config.copy()


def get_enabled_processors() -> Dict[str, ProcessorConfig]:
    """Get all enabled processors."""
    return {
        name: ProcessorConfig(name)
        for name, config in PROCESSOR_MONITORING_CONFIG.items()
        if config.get('enabled', False) and name != 'template_processor'
    }


def get_processors_by_priority(priority: str) -> Dict[str, ProcessorConfig]:
    """
    Get all enabled processors of a specific priority.
    
    Args:
        priority: 'critical', 'high', 'medium', or 'low'
        
    Returns:
        Dict of processor name -> ProcessorConfig
    """
    return {
        name: config
        for name, config in get_enabled_processors().items()
        if config.priority == priority
    }


def validate_config():
    """Validate all processor configs have required fields."""
    required_fields = [
        'display_name', 'execution_table', 'processor_filter',
        'date_field', 'status_field', 'expected_frequency',
        'staleness_threshold_days', 'enabled'
    ]
    
    for processor_name, config in PROCESSOR_MONITORING_CONFIG.items():
        if processor_name == 'template_processor':
            continue
        
        for field in required_fields:
            if field not in config:
                raise ValueError(
                    f"Processor '{processor_name}' missing required field: {field}"
                )
    
    return True


def print_config_summary():
    """Print summary of all processor configurations."""
    print("\n" + "="*70)
    print("PROCESSOR EXECUTION MONITORING CONFIGURATION")
    print("="*70)
    
    enabled = get_enabled_processors()
    disabled = [
        name for name, config in PROCESSOR_MONITORING_CONFIG.items()
        if not config.get('enabled', False) and name != 'template_processor'
    ]
    
    print(f"\n✅ ENABLED PROCESSORS: {len(enabled)}")
    for name, config in enabled.items():
        priority_emoji = {
            'critical': '🔴',
            'high': '🟠',
            'medium': '🟡',
            'low': '🟢'
        }.get(config.priority, '⚪')
        
        revenue = "💰" if config.revenue_impact else "  "
        
        print(f"  {priority_emoji} {revenue} {config.display_name}")
        print(f"      Table: {config.execution_table}")
        print(f"      Filter: {config.processor_filter}")
        print(f"      Frequency: {config.expected_frequency}")
        print(f"      Staleness Threshold: {config.staleness_threshold_days} days")
    
    if disabled:
        print(f"\n⏸️  DISABLED PROCESSORS: {len(disabled)}")
        for name in disabled:
            config = PROCESSOR_MONITORING_CONFIG[name]
            print(f"  - {config['display_name']}")
            if 'notes' in config and config['notes']:
                print(f"    Note: {config['notes']}")
    
    # Priority summary
    print(f"\n📊 BY PRIORITY:")
    for priority in ['critical', 'high', 'medium', 'low']:
        priority_procs = get_processors_by_priority(priority)
        print(f"  {priority}: {len(priority_procs)} enabled")
    
    print("="*70 + "\n")


if __name__ == "__main__":
    # Validation test
    try:
        validate_config()
        print("✅ Configuration validation passed")
        print_config_summary()
            
    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        exit(1)