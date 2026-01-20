"""
Chain Configuration for Validation V2

Loads fallback chain definitions from shared/config/data_sources/fallback_config.yaml
and provides dataclasses for chain-based validation.

This module is the bridge between the YAML config (source of truth) and the
validation logic that checks data availability.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path
import yaml


@dataclass
class SourceConfig:
    """Configuration for a single data source."""
    name: str
    description: str
    table: Optional[str]
    dataset: str
    is_primary: bool
    is_virtual: bool
    quality_tier: str  # gold, silver, bronze
    quality_score: int
    gcs_path_template: Optional[str] = None
    reconstruction_method: Optional[str] = None
    extraction_method: Optional[str] = None


@dataclass
class ChainConfig:
    """Configuration for a fallback chain."""
    name: str
    description: str
    severity: str  # critical, warning, info
    sources: List[SourceConfig]
    on_all_fail_action: str  # skip, placeholder, fail, continue_without
    on_all_fail_message: str
    quality_impact: int = 0  # Quality penalty when chain fails


@dataclass
class SourceValidation:
    """Validation result for a single source."""
    source: SourceConfig
    gcs_file_count: Optional[int] = None  # None if no GCS path
    bq_record_count: int = 0
    status: str = "missing"  # primary, fallback, available, missing, virtual


@dataclass
class ChainValidation:
    """Validation result for a complete chain."""
    chain: ChainConfig
    sources: List[SourceValidation] = field(default_factory=list)
    status: str = "missing"  # complete, partial, missing
    primary_available: bool = False
    fallback_used: bool = False
    impact_message: Optional[str] = None


# =============================================================================
# GCS PATH MAPPING
# =============================================================================
# Maps source names to their GCS path prefixes (from gcs_path_builder.py)
# These are the base paths - dates/subdirs are appended by the validator

GCS_PATH_MAPPING = {
    'nbac_gamebook_player_stats': 'nba-com/gamebooks-data',
    'nbac_team_boxscore': 'nba-com/team-boxscore',
    'bdl_player_boxscores': 'ball-dont-lie/boxscores',  # Note: boxscores not player-boxscores
    'bettingpros_player_points_props': 'bettingpros/player-props',
    'odds_api_player_points_props': 'odds-api/player-props',
    'odds_api_game_lines': 'odds-api/game-lines',
    'nbac_schedule': 'nba-com/schedule',  # Season-based, not date
    'espn_scoreboard': 'espn/scoreboard',
    'espn_boxscores': 'espn/boxscores',  # Player + team boxscores
    'bigdataball_play_by_play': 'big-data-ball',  # Complex path with season
    'nbac_play_by_play': 'nba-com/play-by-play',
    'nbac_injury_report': 'nba-com/injury-report-data',
    'bdl_injuries': 'ball-dont-lie/injuries',
}

# Sources that use season-based paths instead of date-based
SEASON_BASED_GCS_SOURCES = {'nbac_schedule', 'bigdataball_play_by_play'}

# GCS bucket name
GCS_BUCKET = 'nba-scraped-data'

# =============================================================================
# VIRTUAL SOURCE DEPENDENCIES
# =============================================================================
# Virtual sources depend on other chains for their data.
# Maps virtual source name -> input chain name that must have data.

VIRTUAL_SOURCE_DEPENDENCIES = {
    'reconstructed_team_from_players': 'player_boxscores',
    'espn_team_boxscore': 'player_boxscores',  # Extracted from espn_boxscores in player chain
}

# Chain validation order (dependencies first)
# This ensures input chains are validated before chains with virtual sources
CHAIN_VALIDATION_ORDER = [
    'game_schedule',      # No dependencies
    'player_boxscores',   # No dependencies
    'team_boxscores',     # Depends on player_boxscores (for virtual sources)
    'player_props',       # No dependencies
    'game_lines',         # No dependencies
    'shot_zones',         # No dependencies
    'injury_reports',     # No dependencies
]


def load_chain_configs() -> Dict[str, ChainConfig]:
    """
    Load fallback chain configs from YAML.

    Returns:
        Dict mapping chain_name -> ChainConfig
    """
    # Find the config file relative to this module
    config_path = Path(__file__).parent.parent / 'config' / 'data_sources' / 'fallback_config.yaml'

    if not config_path.exists():
        raise FileNotFoundError(f"Fallback config not found at {config_path}")

    with open(config_path) as f:
        data = yaml.safe_load(f)

    sources_data = data.get('sources', {})
    chains_data = data.get('fallback_chains', {})

    chains = {}
    for chain_name, chain_data in chains_data.items():
        # Build source configs for this chain
        source_configs = []
        source_names = chain_data.get('sources', [])

        for i, source_name in enumerate(source_names):
            source_data = sources_data.get(source_name, {})
            quality_data = source_data.get('quality', {})

            source_configs.append(SourceConfig(
                name=source_name,
                description=source_data.get('description', ''),
                table=source_data.get('table'),
                dataset=source_data.get('dataset', 'nba_raw'),
                is_primary=(i == 0),  # First source in chain is primary
                is_virtual=source_data.get('is_virtual', False),
                quality_tier=quality_data.get('tier', 'silver'),
                quality_score=quality_data.get('score', 85),
                gcs_path_template=GCS_PATH_MAPPING.get(source_name),
                reconstruction_method=source_data.get('reconstruction_method'),
                extraction_method=source_data.get('extraction_method'),
            ))

        # Get on_all_fail config
        on_all_fail = chain_data.get('on_all_fail', {})

        chains[chain_name] = ChainConfig(
            name=chain_name,
            description=chain_data.get('description', ''),
            severity=on_all_fail.get('severity', 'info'),
            sources=source_configs,
            on_all_fail_action=on_all_fail.get('action', 'skip'),
            on_all_fail_message=on_all_fail.get('message', ''),
            quality_impact=on_all_fail.get('quality_impact', 0),
        )

    return chains


# =============================================================================
# SINGLETON PATTERN FOR CACHED CONFIGS
# =============================================================================

_CHAIN_CONFIGS: Optional[Dict[str, ChainConfig]] = None


def get_chain_configs() -> Dict[str, ChainConfig]:
    """
    Get chain configs (cached singleton).

    Returns:
        Dict mapping chain_name -> ChainConfig
    """
    global _CHAIN_CONFIGS
    if _CHAIN_CONFIGS is None:
        _CHAIN_CONFIGS = load_chain_configs()
    return _CHAIN_CONFIGS


def reload_chain_configs() -> Dict[str, ChainConfig]:
    """
    Force reload of chain configs from YAML.
    Useful for testing or after config changes.

    Returns:
        Dict mapping chain_name -> ChainConfig
    """
    global _CHAIN_CONFIGS
    _CHAIN_CONFIGS = load_chain_configs()
    return _CHAIN_CONFIGS


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_chains_by_severity(severity: str) -> List[ChainConfig]:
    """Get all chains with a specific severity level."""
    chains = get_chain_configs()
    return [c for c in chains.values() if c.severity == severity]


def get_chain_for_source(source_name: str) -> Optional[ChainConfig]:
    """Find which chain a source belongs to."""
    chains = get_chain_configs()
    for chain in chains.values():
        for source in chain.sources:
            if source.name == source_name:
                return chain
    return None


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == '__main__':
    """Quick test to verify config loading works."""
    print("Loading chain configs...")
    chains = get_chain_configs()
    print(f"Loaded {len(chains)} chains:\n")

    for name, chain in chains.items():
        print(f"Chain: {name} ({chain.severity})")
        print(f"  Description: {chain.description}")
        print(f"  Sources ({len(chain.sources)}):")
        for src in chain.sources:
            primary = "PRIMARY" if src.is_primary else "fallback"
            virtual = " [VIRTUAL]" if src.is_virtual else ""
            gcs = f" (GCS: {src.gcs_path_template})" if src.gcs_path_template else ""
            print(f"    - {src.name}: {src.quality_tier} ({primary}){virtual}{gcs}")
        print(f"  On all fail: {chain.on_all_fail_action} - {chain.on_all_fail_message}")
        print()
