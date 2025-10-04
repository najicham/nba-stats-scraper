"""
File: monitoring/processing_gap_detection/config/processor_config.py

Processor Monitoring Configuration Registry

Defines monitoring parameters for all data processors.
Start with nbac_player_list, expand to others in future phases.
"""

from datetime import timedelta
from typing import Dict, Any, Optional

# Processor monitoring configuration registry
PROCESSOR_MONITORING_CONFIG = {
    # NBA.com Player List - Phase 1 Implementation
    'nbac_player_list': {
        'display_name': 'NBA.com Player List',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'nba-com/player-list/{date}/',
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'nbac_player_list_current',
        'source_file_field': 'source_file_path',
        'processor_class': 'nbac_player_list_processor.NbacPlayerListProcessor',
        
        # Scheduling and frequency
        'frequency': 'daily',  # daily, multiple_daily, per_game, hourly
        'expected_runs_per_day': 1,
        'tolerance_hours': 6,  # Alert if file exists but not processed after 6 hours
        
        # Pub/Sub configuration for retries (Phase 2)
        'pubsub_topic': 'nba-data-processing',  # Shared topic
        'pubsub_topic_alt': 'nbac-player-list-processing',  # Dedicated topic (if exists)
        'pubsub_attributes': {
            'processor': 'nbac_player_list',
            'source': 'nba_com'
        },
        
        # Validation expectations
        'expected_record_count': {
            'min': 500,  # At least 500 active players
            'max': 700   # No more than 700 players
        },
        
        # Monitoring enabled
        'enabled': True,
        
        # Additional metadata
        'docs_url': 'https://docs.example.com/processors/nbac-player-list',
        'priority': 'high',  # high, medium, low
        'revenue_impact': True
    },
    
    # Template for adding more processors (disabled by default)
    'template_processor': {
        'display_name': 'Human Readable Name',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'source/data-type/{date}/',
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'table_name',
        'source_file_field': 'source_file_path',
        'processor_class': 'module.ProcessorClass',
        'frequency': 'daily',
        'expected_runs_per_day': 1,
        'tolerance_hours': 24,
        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {},
        'expected_record_count': None,  # Optional validation
        'enabled': False,
        'priority': 'medium',
        'revenue_impact': False
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
        """Check if monitoring is enabled for this processor."""
        return self._config.get('enabled', False)
    
    @property
    def display_name(self) -> str:
        """Get display name."""
        return self._config['display_name']
    
    @property
    def gcs_bucket(self) -> str:
        """Get GCS bucket name."""
        return self._config['gcs_bucket']
    
    def get_gcs_pattern(self, date_str: str) -> str:
        """Get GCS pattern with date substitution."""
        return self._config['gcs_pattern'].format(date=date_str)
    
    @property
    def bigquery_table(self) -> str:
        """Get fully qualified BigQuery table name."""
        dataset = self._config['bigquery_dataset']
        table = self._config['bigquery_table']
        return f"nba-props-platform.{dataset}.{table}"
    
    @property
    def source_file_field(self) -> str:
        """Get BigQuery field that stores GCS source path."""
        return self._config.get('source_file_field', 'source_file_path')
    
    @property
    def tolerance_hours(self) -> int:
        """Get tolerance hours before alerting."""
        return self._config['tolerance_hours']
    
    @property
    def pubsub_topic(self) -> str:
        """Get primary pub/sub topic name."""
        return self._config.get('pubsub_topic', 'nba-data-processing')
    
    @property
    def pubsub_topic_alt(self) -> Optional[str]:
        """Get alternative dedicated pub/sub topic if exists."""
        return self._config.get('pubsub_topic_alt')
    
    def get_pubsub_attributes(self, file_path: str, date_str: str) -> Dict[str, str]:
        """Build pub/sub message attributes for retry."""
        base_attrs = self._config.get('pubsub_attributes', {}).copy()
        base_attrs.update({
            'file_path': file_path,
            'date': date_str,
            'retry': 'true'
        })
        return base_attrs
    
    @property
    def expected_record_count(self) -> Optional[Dict[str, int]]:
        """Get expected record count range for validation."""
        return self._config.get('expected_record_count')
    
    @property
    def priority(self) -> str:
        """Get processor priority level."""
        return self._config.get('priority', 'medium')
    
    @property
    def revenue_impact(self) -> bool:
        """Check if processor has revenue impact."""
        return self._config.get('revenue_impact', False)
    
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


def validate_config():
    """Validate all processor configs have required fields."""
    required_fields = [
        'display_name', 'gcs_bucket', 'gcs_pattern', 
        'bigquery_dataset', 'bigquery_table', 
        'frequency', 'tolerance_hours', 'enabled'
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


if __name__ == "__main__":
    # Validation test
    try:
        validate_config()
        print("✅ Configuration validation passed")
        
        enabled = get_enabled_processors()
        print(f"\n✅ {len(enabled)} enabled processor(s):")
        for name, config in enabled.items():
            print(f"  - {config.display_name} (priority: {config.priority})")
            
    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        exit(1)
