"""
Dependency Configuration for Pipeline Processors
==================================================
Defines hard and soft dependencies between processors to enable
graceful degradation when upstream processors partially fail.

Key Concepts:
- HARD dependencies: Must succeed 100% or downstream skips entirely
- SOFT dependencies: Proceed if coverage > threshold, with warning

This was created after the Jan 23, 2026 incident where a single
upstream failure blocked all downstream processing (binary pass/fail).

Usage:
    from shared.config.dependency_config import DependencyConfig

    config = DependencyConfig()
    deps = config.get_dependencies('MLFeatureStoreProcessor')

    for dep_name, dep_config in deps.items():
        coverage = check_upstream_coverage(dep_name, data_date)
        if dep_config['type'] == 'soft':
            if coverage >= dep_config['min_coverage']:
                # Proceed with warning
                logger.warning(f"Proceeding with degraded {dep_name}: {coverage:.1%}")
            else:
                # Fail
                raise DependencyNotMetError(f"{dep_name} coverage {coverage:.1%} < {dep_config['min_coverage']:.1%}")

Version: 1.0
Created: 2026-01-24
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DependencyType(Enum):
    """Type of dependency."""
    HARD = "hard"  # Must succeed 100%
    SOFT = "soft"  # Can proceed with partial coverage


@dataclass
class DependencyRule:
    """Configuration for a single dependency."""
    upstream_processor: str
    dependency_type: DependencyType
    min_coverage: float = 1.0  # Minimum coverage required (0.0-1.0)
    fallback_action: str = "skip"  # What to do if not met: skip, warn, use_fallback
    fallback_data_source: Optional[str] = None  # Alternative data source if available
    description: str = ""

    def to_dict(self) -> dict:
        return {
            'upstream_processor': self.upstream_processor,
            'type': self.dependency_type.value,
            'min_coverage': self.min_coverage,
            'fallback_action': self.fallback_action,
            'fallback_data_source': self.fallback_data_source,
            'description': self.description
        }


class DependencyConfig:
    """
    Central configuration for processor dependencies.

    Defines which processors depend on which, and under what conditions
    a processor can proceed with degraded upstream data.
    """

    # Phase 4 Precompute Dependencies
    PHASE4_DEPENDENCIES = {
        'PlayerDailyCacheProcessor': {
            'PlayerGameSummaryProcessor': DependencyRule(
                upstream_processor='PlayerGameSummaryProcessor',
                dependency_type=DependencyType.SOFT,
                min_coverage=0.8,  # 80% of players must have game summary
                fallback_action='warn',
                description='Can proceed with 80% coverage - missing players wont get cache'
            ),
        },
        'PlayerCompositeFactorsProcessor': {
            'PlayerDailyCacheProcessor': DependencyRule(
                upstream_processor='PlayerDailyCacheProcessor',
                dependency_type=DependencyType.SOFT,
                min_coverage=0.7,  # 70% coverage OK
                fallback_action='warn',
                description='Can proceed with 70% coverage - missing players wont get factors'
            ),
            'UpcomingPlayerGameContextProcessor': DependencyRule(
                upstream_processor='UpcomingPlayerGameContextProcessor',
                dependency_type=DependencyType.SOFT,
                min_coverage=0.8,  # 80% of players with upcoming games
                fallback_action='warn',
                description='Can proceed with 80% coverage for players with upcoming games'
            ),
        },
        'MLFeatureStoreProcessor': {
            'PlayerCompositeFactorsProcessor': DependencyRule(
                upstream_processor='PlayerCompositeFactorsProcessor',
                dependency_type=DependencyType.SOFT,
                min_coverage=0.7,
                fallback_action='warn',
                description='Can proceed with 70% coverage - missing players wont get features'
            ),
            'PlayerDailyCacheProcessor': DependencyRule(
                upstream_processor='PlayerDailyCacheProcessor',
                dependency_type=DependencyType.SOFT,
                min_coverage=0.7,
                fallback_action='warn',
                description='Can proceed with 70% coverage'
            ),
        },
    }

    # Phase 5 Prediction Dependencies
    PHASE5_DEPENDENCIES = {
        'PredictionCoordinator': {
            'MLFeatureStoreProcessor': DependencyRule(
                upstream_processor='MLFeatureStoreProcessor',
                dependency_type=DependencyType.SOFT,
                min_coverage=0.6,  # Can generate predictions for 60% of players
                fallback_action='warn',
                description='Generate predictions for available players'
            ),
        },
    }

    # Phase 3 Analytics Dependencies (these should be softer too)
    PHASE3_DEPENDENCIES = {
        'UpcomingPlayerGameContextProcessor': {
            'PlayerGameSummaryProcessor': DependencyRule(
                upstream_processor='PlayerGameSummaryProcessor',
                dependency_type=DependencyType.SOFT,
                min_coverage=0.8,
                fallback_action='warn',
                description='Can proceed with 80% coverage'
            ),
        },
    }

    # Merge all dependencies
    ALL_DEPENDENCIES = {
        **PHASE3_DEPENDENCIES,
        **PHASE4_DEPENDENCIES,
        **PHASE5_DEPENDENCIES,
    }

    def __init__(self):
        """Initialize dependency configuration."""
        self._dependencies = self.ALL_DEPENDENCIES

    def get_dependencies(self, processor_name: str) -> Dict[str, DependencyRule]:
        """
        Get dependencies for a processor.

        Args:
            processor_name: Name of the processor

        Returns:
            Dictionary of dependency rules (upstream_name -> DependencyRule)
        """
        return self._dependencies.get(processor_name, {})

    def get_min_coverage(self, processor_name: str, upstream_name: str) -> float:
        """
        Get minimum required coverage for an upstream dependency.

        Args:
            processor_name: Name of the downstream processor
            upstream_name: Name of the upstream processor

        Returns:
            Minimum coverage required (0.0-1.0), defaults to 1.0 (100%)
        """
        deps = self.get_dependencies(processor_name)
        if upstream_name in deps:
            return deps[upstream_name].min_coverage
        return 1.0  # Default to hard dependency

    def is_soft_dependency(self, processor_name: str, upstream_name: str) -> bool:
        """
        Check if a dependency is soft (allows partial coverage).

        Args:
            processor_name: Name of the downstream processor
            upstream_name: Name of the upstream processor

        Returns:
            True if soft dependency, False if hard or unknown
        """
        deps = self.get_dependencies(processor_name)
        if upstream_name in deps:
            return deps[upstream_name].dependency_type == DependencyType.SOFT
        return False

    def check_dependency(
        self,
        processor_name: str,
        upstream_name: str,
        actual_coverage: float
    ) -> tuple:
        """
        Check if a dependency is met.

        Args:
            processor_name: Name of the downstream processor
            upstream_name: Name of the upstream processor
            actual_coverage: Actual coverage percentage (0.0-1.0)

        Returns:
            Tuple of (is_met: bool, message: str, action: str)
            - is_met: Whether to proceed
            - message: Human-readable status message
            - action: 'proceed', 'warn_and_proceed', or 'skip'
        """
        deps = self.get_dependencies(processor_name)

        if upstream_name not in deps:
            # Unknown dependency - treat as hard (must be 100%)
            if actual_coverage >= 1.0:
                return True, f"{upstream_name} fully available", "proceed"
            else:
                return False, f"{upstream_name} not fully available ({actual_coverage:.1%})", "skip"

        rule = deps[upstream_name]

        if actual_coverage >= rule.min_coverage:
            if actual_coverage < 1.0:
                return True, (
                    f"{upstream_name} at {actual_coverage:.1%} coverage "
                    f"(meets soft threshold of {rule.min_coverage:.1%})"
                ), "warn_and_proceed"
            else:
                return True, f"{upstream_name} fully available", "proceed"
        else:
            return False, (
                f"{upstream_name} at {actual_coverage:.1%} coverage "
                f"(below minimum of {rule.min_coverage:.1%})"
            ), "skip"

    def to_dict(self) -> dict:
        """Export configuration as dictionary."""
        return {
            proc: {name: rule.to_dict() for name, rule in deps.items()}
            for proc, deps in self._dependencies.items()
        }


# Singleton instance
_config_instance = None


def get_dependency_config() -> DependencyConfig:
    """Get singleton dependency configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = DependencyConfig()
    return _config_instance
