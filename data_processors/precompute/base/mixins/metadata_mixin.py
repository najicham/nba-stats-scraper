"""
Metadata tracking for precompute processors.

Provides source metadata tracking and dependency result recording for audit trails.

Version: 1.0
Created: 2026-01-25
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MetadataMixin:
    """
    Metadata tracking for precompute processors.

    Tracks upstream data sources, completeness, and dependency check results
    for audit trail and debugging purposes.

    Requires from base class:
    - self.data_completeness_pct: float for completeness percentage
    - self.dependency_check_passed: bool for dependency status
    - self.upstream_data_age_hours: float for upstream data age
    - self.missing_dependencies_list: list for missing deps
    - self.stats: dict for processor statistics
    """

    def track_source_usage(self, dep_check: dict) -> None:
        """
        Track metadata about upstream data sources.

        Records completeness percentage, dependency status, and upstream
        data age for audit trail and monitoring.

        Args:
            dep_check: Dependency check result dictionary with keys:
                - all_critical_present: bool
                - missing: List[str]
                - details: Dict[str, Dict] with age_hours
        """
        # Calculate completeness percentage
        total_deps = len(dep_check.get('details', {}))
        missing_count = len(dep_check.get('missing', []))
        if total_deps > 0:
            self.data_completeness_pct = ((total_deps - missing_count) / total_deps) * 100
        else:
            self.data_completeness_pct = 100.0

        # Record dependency check status
        self.dependency_check_passed = dep_check.get('all_critical_present', True)
        self.missing_dependencies_list = dep_check.get('missing', [])

        # Calculate maximum upstream data age
        max_age = 0.0
        for table_name, details in dep_check.get('details', {}).items():
            if details.get('age_hours'):
                max_age = max(max_age, details['age_hours'])
        self.upstream_data_age_hours = max_age

        # Add to stats for reporting
        self.stats['data_completeness_pct'] = round(self.data_completeness_pct, 2)
        self.stats['dependency_check_passed'] = self.dependency_check_passed
        self.stats['upstream_data_age_hours'] = round(self.upstream_data_age_hours, 2)
        if self.missing_dependencies_list:
            self.stats['missing_dependencies'] = self.missing_dependencies_list

        logger.debug(
            f"Source tracking: {self.data_completeness_pct:.1f}% complete, "
            f"deps_passed={self.dependency_check_passed}, "
            f"age={self.upstream_data_age_hours:.1f}h"
        )
