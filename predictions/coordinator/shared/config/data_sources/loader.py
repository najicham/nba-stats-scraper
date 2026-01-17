"""
Data Source Configuration Loader

Provides typed access to fallback_config.yaml for data source definitions,
fallback chains, quality tiers, and reconstruction methods.

Usage:
    from shared.config.data_sources import DataSourceConfig

    config = DataSourceConfig()
    source = config.get_source('nbac_team_boxscore')
    chain = config.get_fallback_chain('team_boxscores')
    tier = config.get_tier_from_score(85)

Version: 1.0
Created: 2025-11-30
"""

import yaml
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SourceConfig:
    """Configuration for a single data source."""
    name: str
    description: str
    dataset: str
    table: Optional[str]
    scraper: Optional[str]
    is_primary: bool
    is_virtual: bool
    coverage_pct: Optional[float]
    quality_tier: str
    quality_score: float
    reconstruction_method: Optional[str] = None
    extraction_method: Optional[str] = None
    differences: Optional[str] = None
    unique_value: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class FallbackChainConfig:
    """Configuration for a fallback chain."""
    name: str
    description: str
    phase: str
    consumers: List[str]
    sources: List[str]
    on_all_fail_action: str
    on_all_fail_severity: str
    on_all_fail_message: str
    on_all_fail_quality_tier: Optional[str] = None
    on_all_fail_quality_score: Optional[float] = None
    on_all_fail_quality_impact: Optional[float] = None


@dataclass
class QualityTierConfig:
    """Configuration for a quality tier."""
    name: str
    score_min: float
    score_max: float
    confidence_ceiling: float
    description: str
    prediction_eligible: bool


@dataclass
class ReconstructionMethod:
    """Configuration for a data reconstruction method."""
    name: str
    description: str
    input_chain: Optional[str]
    input_table: Optional[str]
    method: str
    fields: List[str] = field(default_factory=list)
    filter_condition: Optional[str] = None
    validation: Optional[str] = None
    quality_notes: Optional[str] = None


@dataclass
class RemediationOption:
    """Configuration for a manual remediation option."""
    name: str
    description: str
    requires_manual_decision: bool
    quality_tier_if_used: str
    can_reconstruct: List[Dict[str, Any]]
    cannot_reliably_reconstruct: List[Dict[str, Any]]


class DataSourceConfig:
    """
    Singleton configuration loader for data source fallback system.

    Loads fallback_config.yaml and provides typed access to:
    - Data source definitions
    - Fallback chains
    - Quality tier definitions
    - Reconstruction methods
    - Remediation options

    Example:
        config = DataSourceConfig()

        # Get source info
        source = config.get_source('nbac_team_boxscore')
        print(source.quality_tier)  # 'gold'

        # Get fallback chain
        chain = config.get_fallback_chain('team_boxscores')
        for src_name in chain.sources:
            src = config.get_source(src_name)
            print(f"{src_name}: {src.quality_score}")

        # Convert score to tier
        tier = config.get_tier_from_score(85)  # 'silver'
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if DataSourceConfig._initialized:
            return
        self._load_config()
        DataSourceConfig._initialized = True

    def _load_config(self):
        """Load and parse the YAML configuration file."""
        config_path = Path(__file__).parent / 'fallback_config.yaml'

        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path) as f:
            self._raw_config = yaml.safe_load(f)

        self._parse_sources()
        self._parse_chains()
        self._parse_tiers()
        self._parse_reconstruction_methods()
        self._parse_remediation_options()

        logger.info(
            f"Loaded data source config: {len(self._sources)} sources, "
            f"{len(self._chains)} chains, {len(self._tiers)} tiers"
        )

    def _parse_sources(self):
        """Parse source definitions into typed objects."""
        self._sources: Dict[str, SourceConfig] = {}

        for name, data in self._raw_config.get('sources', {}).items():
            quality = data.get('quality', {})
            self._sources[name] = SourceConfig(
                name=name,
                description=data.get('description', ''),
                dataset=data.get('dataset', ''),
                table=data.get('table'),
                scraper=data.get('scraper'),
                is_primary=data.get('is_primary', False),
                is_virtual=data.get('is_virtual', False),
                coverage_pct=data.get('coverage_pct'),
                quality_tier=quality.get('tier', 'gold'),
                quality_score=quality.get('score', 100),
                reconstruction_method=data.get('reconstruction_method'),
                extraction_method=data.get('extraction_method'),
                differences=data.get('differences'),
                unique_value=data.get('unique_value'),
                notes=data.get('notes'),
            )

    def _parse_chains(self):
        """Parse fallback chains into typed objects."""
        self._chains: Dict[str, FallbackChainConfig] = {}

        for name, data in self._raw_config.get('fallback_chains', {}).items():
            on_fail = data.get('on_all_fail', {})
            self._chains[name] = FallbackChainConfig(
                name=name,
                description=data.get('description', ''),
                phase=data.get('phase', ''),
                consumers=data.get('consumers', []),
                sources=data.get('sources', []),
                on_all_fail_action=on_fail.get('action', 'skip'),
                on_all_fail_severity=on_fail.get('severity', 'warning'),
                on_all_fail_message=on_fail.get('message', ''),
                on_all_fail_quality_tier=on_fail.get('quality_tier'),
                on_all_fail_quality_score=on_fail.get('quality_score'),
                on_all_fail_quality_impact=on_fail.get('quality_impact'),
            )

    def _parse_tiers(self):
        """Parse quality tier definitions."""
        self._tiers: Dict[str, QualityTierConfig] = {}

        for name, data in self._raw_config.get('quality_tiers', {}).items():
            self._tiers[name] = QualityTierConfig(
                name=name,
                score_min=data.get('score_min', 0),
                score_max=data.get('score_max', 100),
                confidence_ceiling=data.get('confidence_ceiling', 1.0),
                description=data.get('description', ''),
                prediction_eligible=data.get('prediction_eligible', True),
            )

    def _parse_reconstruction_methods(self):
        """Parse reconstruction method definitions."""
        self._reconstruction_methods: Dict[str, ReconstructionMethod] = {}

        for name, data in self._raw_config.get('reconstruction_methods', {}).items():
            self._reconstruction_methods[name] = ReconstructionMethod(
                name=name,
                description=data.get('description', ''),
                input_chain=data.get('input_chain'),
                input_table=data.get('input_table'),
                method=data.get('method', ''),
                fields=data.get('fields', []),
                filter_condition=data.get('filter'),
                validation=data.get('validation'),
                quality_notes=data.get('quality_notes'),
            )

    def _parse_remediation_options(self):
        """Parse manual remediation options."""
        self._remediation_options: Dict[str, RemediationOption] = {}

        for name, data in self._raw_config.get('remediation_options', {}).items():
            self._remediation_options[name] = RemediationOption(
                name=name,
                description=data.get('description', ''),
                requires_manual_decision=data.get('requires_manual_decision', True),
                quality_tier_if_used=data.get('quality_tier_if_used', 'bronze'),
                can_reconstruct=data.get('can_reconstruct', []),
                cannot_reliably_reconstruct=data.get('cannot_reliably_reconstruct', []),
            )

    # =========================================================================
    # PUBLIC API - Sources
    # =========================================================================

    def get_source(self, name: str) -> SourceConfig:
        """
        Get configuration for a data source.

        Args:
            name: Source name (e.g., 'nbac_team_boxscore')

        Returns:
            SourceConfig with all source properties

        Raises:
            ValueError: If source name not found
        """
        if name not in self._sources:
            available = ', '.join(sorted(self._sources.keys()))
            raise ValueError(f"Unknown source: '{name}'. Available: {available}")
        return self._sources[name]

    def get_source_safe(self, name: str) -> Optional[SourceConfig]:
        """Get source config, returning None if not found."""
        return self._sources.get(name)

    def list_sources(self) -> List[str]:
        """List all available source names."""
        return list(self._sources.keys())

    def get_primary_sources(self) -> List[SourceConfig]:
        """Get all primary (non-fallback) sources."""
        return [s for s in self._sources.values() if s.is_primary]

    def get_fallback_sources(self) -> List[SourceConfig]:
        """Get all fallback (non-primary) sources."""
        return [s for s in self._sources.values() if not s.is_primary]

    # =========================================================================
    # PUBLIC API - Fallback Chains
    # =========================================================================

    def get_fallback_chain(self, name: str) -> FallbackChainConfig:
        """
        Get configuration for a fallback chain.

        Args:
            name: Chain name (e.g., 'team_boxscores')

        Returns:
            FallbackChainConfig with sources and failure behavior

        Raises:
            ValueError: If chain name not found
        """
        if name not in self._chains:
            available = ', '.join(sorted(self._chains.keys()))
            raise ValueError(f"Unknown fallback chain: '{name}'. Available: {available}")
        return self._chains[name]

    def get_fallback_chain_safe(self, name: str) -> Optional[FallbackChainConfig]:
        """Get chain config, returning None if not found."""
        return self._chains.get(name)

    def list_fallback_chains(self) -> List[str]:
        """List all available fallback chain names."""
        return list(self._chains.keys())

    def get_chains_for_consumer(self, processor_name: str) -> List[FallbackChainConfig]:
        """Get all fallback chains used by a specific processor."""
        return [
            chain for chain in self._chains.values()
            if processor_name in chain.consumers
        ]

    # =========================================================================
    # PUBLIC API - Quality Tiers
    # =========================================================================

    def get_tier(self, name: str) -> QualityTierConfig:
        """
        Get configuration for a quality tier.

        Args:
            name: Tier name ('gold', 'silver', 'bronze', 'poor', 'unusable')

        Returns:
            QualityTierConfig with thresholds and eligibility
        """
        if name not in self._tiers:
            available = ', '.join(sorted(self._tiers.keys()))
            raise ValueError(f"Unknown tier: '{name}'. Available: {available}")
        return self._tiers[name]

    def get_tier_from_score(self, score: float) -> str:
        """
        Determine tier name from numeric score.

        Delegates to shared.config.source_coverage.get_tier_from_score()
        to ensure a single source of truth for tier thresholds.

        Args:
            score: Quality score (0-100)

        Returns:
            Tier name ('gold', 'silver', 'bronze', 'poor', 'unusable')
        """
        # Delegate to source_coverage - the canonical implementation
        from shared.config.source_coverage import get_tier_from_score as _canonical_get_tier
        tier = _canonical_get_tier(score)
        # Return string value (source_coverage returns QualityTier enum)
        return tier.value if hasattr(tier, 'value') else tier

    def get_confidence_ceiling(self, tier_or_score) -> float:
        """
        Get confidence ceiling for a tier or score.

        Args:
            tier_or_score: Either tier name (str) or quality score (float)

        Returns:
            Confidence ceiling (0.0 to 1.0)
        """
        if isinstance(tier_or_score, (int, float)):
            tier_name = self.get_tier_from_score(tier_or_score)
        else:
            tier_name = tier_or_score

        tier = self._tiers.get(tier_name)
        return tier.confidence_ceiling if tier else 0.0

    def is_prediction_eligible(self, tier_or_score) -> bool:
        """
        Check if a tier/score is eligible for predictions.

        Args:
            tier_or_score: Either tier name (str) or quality score (float)

        Returns:
            True if predictions can be made
        """
        if isinstance(tier_or_score, (int, float)):
            tier_name = self.get_tier_from_score(tier_or_score)
        else:
            tier_name = tier_or_score

        tier = self._tiers.get(tier_name)
        return tier.prediction_eligible if tier else False

    # =========================================================================
    # PUBLIC API - Reconstruction Methods
    # =========================================================================

    def get_reconstruction_method(self, name: str) -> Optional[ReconstructionMethod]:
        """Get a reconstruction method by name."""
        return self._reconstruction_methods.get(name)

    def list_reconstruction_methods(self) -> List[str]:
        """List all available reconstruction method names."""
        return list(self._reconstruction_methods.keys())

    # =========================================================================
    # PUBLIC API - Remediation Options
    # =========================================================================

    def get_remediation_option(self, name: str) -> Optional[RemediationOption]:
        """Get a remediation option by name."""
        return self._remediation_options.get(name)

    def list_remediation_options(self) -> List[str]:
        """List all available remediation option names."""
        return list(self._remediation_options.keys())

    # =========================================================================
    # PUBLIC API - Propagation Rules
    # =========================================================================

    def get_propagation_rules(self) -> Dict[str, Any]:
        """Get quality propagation rules."""
        return self._raw_config.get('quality_propagation', {})

    def get_prediction_requirements(self) -> Dict[str, Any]:
        """Get Phase 5 prediction requirements."""
        propagation = self.get_propagation_rules()
        return propagation.get('prediction_requirements', {
            'min_quality_score': 70,
            'require_production_ready': True,
        })

    # =========================================================================
    # PUBLIC API - Future Sources
    # =========================================================================

    def get_future_sources(self) -> Dict[str, Any]:
        """Get information about future (not yet consumed) sources."""
        return self._raw_config.get('future_sources', {})

    # =========================================================================
    # UTILITIES
    # =========================================================================

    def reload(self):
        """Force reload of configuration (useful for testing)."""
        DataSourceConfig._initialized = False
        self._load_config()
        DataSourceConfig._initialized = True

    def validate(self) -> List[str]:
        """
        Validate configuration integrity.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Check that all chain sources exist
        for chain in self._chains.values():
            for source_name in chain.sources:
                if source_name not in self._sources:
                    errors.append(
                        f"Chain '{chain.name}' references unknown source: '{source_name}'"
                    )

        # Check tier score ranges don't overlap
        tier_ranges = [(t.name, t.score_min, t.score_max) for t in self._tiers.values()]
        for i, (name1, min1, max1) in enumerate(tier_ranges):
            for name2, min2, max2 in tier_ranges[i+1:]:
                if min1 <= max2 and min2 <= max1:
                    # Check if they actually overlap (not just touch)
                    if not (max1 == min2 or max2 == min1):
                        errors.append(
                            f"Tier ranges overlap: {name1} ({min1}-{max1}) "
                            f"and {name2} ({min2}-{max2})"
                        )

        return errors


# Module-level convenience function
def get_config() -> DataSourceConfig:
    """Get the singleton DataSourceConfig instance."""
    return DataSourceConfig()
