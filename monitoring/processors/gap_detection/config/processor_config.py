"""
File: monitoring/processing_gap_detection/config/processor_config.py

Processor Monitoring Configuration Registry

Defines monitoring parameters for all data processors with support for multiple
GCS path patterns. Extensible design supports future processor additions.

Pattern Types:
  - simple_date: {source}/{data-type}/{date}/
  - date_nested: {source}/{data-type}/{date}/{subdir}/
  - season_based: {source}/{data-type}/{season}/
"""

from datetime import timedelta
from typing import Dict, Any, Optional

# ============================================================================
# PROCESSOR MONITORING CONFIGURATION REGISTRY
# ============================================================================

PROCESSOR_MONITORING_CONFIG = {
    
    # ========================================================================
    # PATTERN 1: SIMPLE DATE-BASED PROCESSORS
    # GCS Path: {source}/{data-type}/{date}/
    # ========================================================================
    
    'nbac_player_list': {
        'display_name': 'NBA.com Player List',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'nba-com/player-list/{date}/',
        'gcs_pattern_type': 'simple_date',
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'nbac_player_list_current',
        'source_file_field': 'source_file_path',
        'processor_class': 'nbac_player_list_processor.NbacPlayerListProcessor',
        
        # Scheduling and frequency
        'frequency': 'daily',
        'expected_runs_per_day': 1,
        'tolerance_hours': 6,
        
        # Pub/Sub configuration for retries (Phase 2)
        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {
            'processor': 'nbac_player_list',
            'source': 'nba_com'
        },
        
        # Validation expectations
        'expected_record_count': {
            'min': 500,
            'max': 700
        },
        
        'enabled': True,
        'docs_url': 'https://docs.example.com/processors/nbac-player-list',
        'priority': 'high',
        'revenue_impact': True
    },
    
    'bdl_player_boxscores': {
        'display_name': 'BDL Player Box Scores',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'ball-dont-lie/boxscores/{date}/',
        'gcs_pattern_type': 'simple_date',
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'bdl_player_boxscores',
        'source_file_field': 'source_file_path',
        'processor_class': 'bdl_boxscores_processor.BdlBoxscoresProcessor',
        
        'frequency': 'daily',
        'expected_runs_per_day': 2,  # 8 PM and 11 PM PT
        'tolerance_hours': 4,  # Alert if not processed 4 hours after game time
        
        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {
            'processor': 'bdl_boxscores',
            'source': 'ball_dont_lie'
        },
        
        'expected_record_count': {
            'min': 200,   # ~10 games * 20 players minimum
            'max': 1000   # ~15 games * 65 players maximum
        },
        
        'enabled': True,
        'priority': 'critical',
        'revenue_impact': True,
        'notes': 'Critical for prop bet settlement - must process within 4 hours of games'
    },
    
    'bdl_active_players': {
        'display_name': 'BDL Active Players',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'ball-dont-lie/active-players/{date}/',
        'gcs_pattern_type': 'simple_date',
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'bdl_active_players_current',
        'source_file_field': 'source_file_path',
        'processor_class': 'bdl_active_players_processor.BdlActivePlayersProcessor',
        
        'frequency': 'daily',
        'expected_runs_per_day': 1,
        'tolerance_hours': 6,
        
        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {
            'processor': 'bdl_active_players',
            'source': 'ball_dont_lie'
        },
        
        'expected_record_count': {
            'min': 500,
            'max': 600
        },
        
        'enabled': True,
        'priority': 'high',
        'revenue_impact': True,
        'notes': 'Player validation source - cross-checks against NBA.com'
    },
    
    'bdl_injuries': {
        'display_name': 'BDL Injuries',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'ball-dont-lie/injuries/{date}/',
        'gcs_pattern_type': 'simple_date',
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'bdl_injuries',
        'source_file_field': 'source_file_path',
        'processor_class': 'bdl_injuries_processor.BdlInjuriesProcessor',
        
        'frequency': 'daily',
        'expected_runs_per_day': 1,
        'tolerance_hours': 8,
        
        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {
            'processor': 'bdl_injuries',
            'source': 'ball_dont_lie'
        },
        
        'expected_record_count': {
            'min': 10,   # At least 10 injured players
            'max': 200   # Up to 200 injury records
        },
        
        'enabled': True,
        'priority': 'high',
        'revenue_impact': True,
        'notes': 'Backup injury data source for cross-validation'
    },
    
    'bdl_standings': {
        'display_name': 'BDL Standings',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'ball-dont-lie/standings/2024-25/{date}/',
        'gcs_pattern_type': 'simple_date',
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'bdl_standings',
        'source_file_field': 'source_file_path',
        'processor_class': 'bdl_standings_processor.BdlStandingsProcessor',
        
        'frequency': 'daily',
        'expected_runs_per_day': 1,
        'tolerance_hours': 12,
        
        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {
            'processor': 'bdl_standings',
            'source': 'ball_dont_lie'
        },
        
        'expected_record_count': {
            'min': 30,
            'max': 30
        },
        
        'enabled': True,
        'priority': 'medium',
        'revenue_impact': False,
        'notes': 'Team performance context - not critical for prop operations'
    },
    
    # ========================================================================
    # PATTERN 2: DATE + NESTED STRUCTURE (Advanced)
    # GCS Path: {source}/{data-type}/{date}/{subdir}/
    # Note: Requires enhanced GCS inspection logic
    # ========================================================================
    
    'nbac_injury_report': {
        'display_name': 'NBA.com Injury Report',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'nba-com/injury-report-data/{date}/',
        'gcs_pattern_type': 'date_nested',
        'nested_structure': 'hourly',  # Has subdirectories by hour
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'nbac_injury_report',
        'source_file_field': 'source_file_path',
        'processor_class': 'nbac_injury_report_processor.NbacInjuryReportProcessor',
        
        'frequency': 'hourly',
        'expected_runs_per_day': 24,
        'tolerance_hours': 3,
        
        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {
            'processor': 'nbac_injury_report',
            'source': 'nba_com'
        },
        
        'expected_record_count': {
            'min': 20,
            'max': 500
        },
        
        'enabled': False,  # Disable until nested path support added
        'priority': 'critical',
        'revenue_impact': True,
        'notes': 'FUTURE: Requires enhanced GCS inspector for hourly subdirectories'
    },
    
    'odds_api_player_props': {
        'display_name': 'Odds API Player Props (Current)',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'odds-api/player-props/{date}/',
        'gcs_pattern_type': 'date_nested',
        'nested_structure': 'event_id',  # Has subdirectories by event ID (e.g., eventid-AWYHOME)
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'odds_api_player_points_props',
        'source_file_field': 'source_file_path',
        'processor_class': 'odds_api_props_processor.OddsApiPropsProcessor',

        'frequency': 'daily',
        'expected_runs_per_day': 3,  # Multiple snapshots per day
        'tolerance_hours': 8,  # Alert if no props 8 hours after expected scrape

        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {
            'processor': 'odds_api_props',
            'source': 'odds_api',
            'data_type': 'current'
        },

        'expected_record_count': {
            'min': 500,   # ~8 games * 15 players * 4 bookmakers
            'max': 5000   # ~15 games * 20 players * 8 bookmakers * multiple snapshots
        },

        'enabled': True,  # ENABLED 2026-01-11: Critical for prop prediction pipeline
        'priority': 'critical',
        'revenue_impact': True,
        'notes': 'Critical for prop bet predictions. Gap detected Jan 2026 led to 2 months of missing predictions.'
    },

    'odds_api_props_history': {
        'display_name': 'Odds API Player Props History',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'odds-api/player-props-history/{date}/',
        'gcs_pattern_type': 'date_nested',
        'nested_structure': 'event_id',  # Has subdirectories by event ID
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'odds_api_player_points_props',
        'source_file_field': 'source_file_path',
        'processor_class': 'odds_api_props_processor.OddsApiPropsProcessor',

        'frequency': 'daily',
        'expected_runs_per_day': 1,
        'tolerance_hours': 4,

        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {
            'processor': 'odds_api_props',
            'source': 'odds_api',
            'data_type': 'history'
        },

        'expected_record_count': {
            'min': 100,
            'max': 500
        },

        'enabled': False,  # Historical endpoint - not used for daily monitoring
        'priority': 'critical',
        'revenue_impact': True,
        'notes': 'Historical endpoint for backfills only. Use odds_api_player_props for daily monitoring.'
    },
    
    # ========================================================================
    # TEMPLATE FOR ADDING NEW PROCESSORS
    # Copy this template and fill in appropriate values
    # ========================================================================
    
    'template_processor': {
        'display_name': 'Human Readable Name',
        'gcs_bucket': 'nba-scraped-data',
        'gcs_pattern': 'source/data-type/{date}/',
        'gcs_pattern_type': 'simple_date',  # or 'date_nested', 'season_based'
        'bigquery_dataset': 'nba_raw',
        'bigquery_table': 'table_name',
        'source_file_field': 'source_file_path',
        'processor_class': 'module.ProcessorClass',
        
        'frequency': 'daily',
        'expected_runs_per_day': 1,
        'tolerance_hours': 24,
        
        'pubsub_topic': 'nba-data-processing',
        'pubsub_attributes': {},
        
        'expected_record_count': None,
        
        'enabled': False,
        'priority': 'medium',
        'revenue_impact': False
    }
}


# ============================================================================
# PROCESSOR CONFIGURATION WRAPPER CLASS
# ============================================================================

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
    
    @property
    def gcs_pattern_type(self) -> str:
        """Get GCS pattern type (simple_date, date_nested, season_based)."""
        return self._config.get('gcs_pattern_type', 'simple_date')
    
    def get_gcs_pattern(self, date_str: str) -> str:
        """
        Get GCS pattern with date substitution.
        
        Args:
            date_str: Date string in YYYY-MM-DD format
            
        Returns:
            GCS prefix pattern for searching
        """
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
    
    @property
    def notes(self) -> Optional[str]:
        """Get implementation notes if available."""
        return self._config.get('notes')
    
    def to_dict(self) -> Dict[str, Any]:
        """Get full configuration as dictionary."""
        return self._config.copy()


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_enabled_processors() -> Dict[str, ProcessorConfig]:
    """Get all enabled processors."""
    return {
        name: ProcessorConfig(name)
        for name, config in PROCESSOR_MONITORING_CONFIG.items()
        if config.get('enabled', False) and name != 'template_processor'
    }


def get_processors_by_pattern(pattern_type: str) -> Dict[str, ProcessorConfig]:
    """
    Get all enabled processors of a specific pattern type.
    
    Args:
        pattern_type: 'simple_date', 'date_nested', or 'season_based'
        
    Returns:
        Dict of processor name -> ProcessorConfig
    """
    return {
        name: config
        for name, config in get_enabled_processors().items()
        if config.gcs_pattern_type == pattern_type
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


# ============================================================================
# CONFIGURATION SUMMARY
# ============================================================================

def print_config_summary():
    """Print summary of all processor configurations."""
    print("\n" + "="*70)
    print("PROCESSOR MONITORING CONFIGURATION SUMMARY")
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
        print(f"      Pattern: {config.gcs_pattern_type}")
        print(f"      Tolerance: {config.tolerance_hours}h")
        if config.expected_record_count:
            min_rec = config.expected_record_count['min']
            max_rec = config.expected_record_count['max']
            print(f"      Expected records: {min_rec}-{max_rec}")
    
    if disabled:
        print(f"\n⏸️  DISABLED PROCESSORS: {len(disabled)}")
        for name in disabled:
            config = PROCESSOR_MONITORING_CONFIG[name]
            print(f"  - {config['display_name']}")
            if 'notes' in config:
                print(f"    Note: {config['notes']}")
    
    # Pattern summary
    print(f"\n📊 BY PATTERN TYPE:")
    for pattern in ['simple_date', 'date_nested', 'season_based']:
        pattern_procs = get_processors_by_pattern(pattern)
        print(f"  {pattern}: {len(pattern_procs)} enabled")
    
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