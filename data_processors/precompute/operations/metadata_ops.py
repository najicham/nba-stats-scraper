"""
File: data_processors/precompute/operations/metadata_ops.py

Metadata operations for precompute processors.

Extracted from precompute_base.py to improve modularity and testability.
Handles source tracking and metadata field building for precompute records.

Dependencies (required by this mixin):
- self.source_metadata: Dict for tracking metadata
- self.get_dependencies(): Method returning dependency config
- self.bq_client: BigQuery client
- self.project_id: GCP project ID

Version: 1.0
Created: 2026-01-25
"""

import logging
from typing import Dict

logger = logging.getLogger(__name__)


class PrecomputeMetadataOpsMixin:
    """
    Mixin providing metadata tracking operations for precompute processors.

    This mixin handles:
    - Building source tracking fields for output records
    - Calculating expected row counts based on dependency check types
    - Recording source usage metadata from dependency checks

    Required Dependencies:
        Must be mixed into a class that provides:
        - self.source_metadata (Dict): Dictionary for tracking source metadata
        - self.get_dependencies() (method): Returns dependency configuration dict
        - self.bq_client: BigQuery client instance
        - self.project_id (str): GCP project ID
        - self.data_completeness_pct (float): Overall completeness percentage
        - self.upstream_data_age_hours (float): Maximum upstream data age
        - self.dependency_check_passed (bool): Whether dependency checks passed
        - self.missing_dependencies_list (List[str]): List of missing dependencies

    Usage:
        class MyProcessor(PrecomputeMetadataOpsMixin, BaseProcessor):
            def calculate_precompute(self):
                # Build source tracking fields
                source_fields = self.build_source_tracking_fields()

                # Add to each output record
                record.update(source_fields)
    """

    def build_source_tracking_fields(self) -> dict:
        """
        Build dict of all source tracking fields for output records.
        Extracts from self.source_metadata populated by track_source_usage().

        Note: Returns empty dict in backfill mode since these fields don't exist
        in the BigQuery schema and would cause MERGE failures.

        Returns:
            Dict with source_* fields per v4.0 spec (3 fields per source)
        """
        # Skip source tracking in backfill mode - fields don't exist in BigQuery schema
        if getattr(self, 'is_backfill_mode', False):
            return {}

        fields = {}

        # Per-source fields (populated by track_source_usage)
        for table_name, config in self.get_dependencies().items():
            prefix = config['field_prefix']
            metadata = self.source_metadata.get(table_name, {})

            fields[f'{prefix}_last_updated'] = metadata.get('last_updated')
            fields[f'{prefix}_rows_found'] = metadata.get('rows_found')
            fields[f'{prefix}_completeness_pct'] = metadata.get('completeness_pct')

        # Optional early season fields
        if hasattr(self, 'early_season_flag') and self.early_season_flag:
            fields['early_season_flag'] = True
            fields['insufficient_data_reason'] = getattr(self, 'insufficient_data_reason', None)
        else:
            fields['early_season_flag'] = None
            fields['insufficient_data_reason'] = None

        return fields

    def _calculate_expected_count(self, config: dict, dep_result: dict) -> int:
        """
        Calculate expected row count based on check_type.

        Args:
            config: Dependency configuration
            dep_result: Results from dependency check

        Returns:
            Expected number of rows
        """
        check_type = config.get('check_type', 'existence')

        if check_type == 'per_team_game_count':
            # Expected = min_games_required × number of teams
            teams_with_data = dep_result.get('teams_found', 30)
            min_games = config.get('min_games_required', 15)
            return min_games * teams_with_data

        elif check_type == 'lookback':
            # Use configured expected count or estimate
            return config.get('expected_count_min', 100)

        elif check_type == 'date_match':
            # Expect one record per entity (e.g., 30 teams)
            return config.get('expected_count_min', 30)

        elif check_type == 'existence':
            return config.get('expected_count_min', 1)

        else:
            # Unknown check type - use configured minimum
            return config.get('expected_count_min', 1)

    def track_source_usage(self, dep_check: dict) -> None:
        """
        Record what sources were used.
        Populates self.source_metadata dict AND per-source attributes.

        This method:
        1. Iterates through dependency check results
        2. Calculates completeness percentage for each source
        3. Stores metadata in self.source_metadata dict
        4. Sets per-source attributes (e.g., self.tdgs_last_updated)
        5. Calculates overall metrics (data_completeness_pct, upstream_data_age_hours)

        Args:
            dep_check: Dependency check results dict with 'details' key
        """
        self.source_metadata = {}
        completeness_values = []
        age_values = []
        missing_deps = []

        for table_name, dep_result in dep_check['details'].items():
            config = self.get_dependencies()[table_name]
            prefix = config.get('field_prefix', table_name.split('.')[-1])

            if not dep_result.get('exists', False):
                missing_deps.append(table_name)
                # Set attributes to None for missing sources
                setattr(self, f'{prefix}_last_updated', None)
                setattr(self, f'{prefix}_rows_found', None)
                setattr(self, f'{prefix}_completeness_pct', None)
                continue

            # Calculate completeness
            row_count = dep_result.get('row_count', 0)
            expected = self._calculate_expected_count(config, dep_result)
            completeness = (row_count / expected * 100) if expected > 0 else 100
            completeness = min(completeness, 100.0)

            completeness_values.append(completeness)

            if dep_result.get('age_hours') is not None:
                age_values.append(dep_result['age_hours'])

            # Store in metadata dict
            self.source_metadata[table_name] = {
                'last_updated': dep_result.get('last_updated'),
                'rows_found': row_count,
                'rows_expected': expected,
                'completeness_pct': round(completeness, 2),
                'age_hours': dep_result.get('age_hours')
            }

            # ALSO store as attributes for easy access
            setattr(self, f'{prefix}_last_updated', dep_result.get('last_updated'))
            setattr(self, f'{prefix}_rows_found', row_count)
            setattr(self, f'{prefix}_completeness_pct', round(completeness, 2))

        # Calculate overall metrics (keep existing logic)
        if completeness_values:
            self.data_completeness_pct = round(
                sum(completeness_values) / len(completeness_values), 2
            )
        else:
            self.data_completeness_pct = 0.0

        if age_values:
            self.upstream_data_age_hours = round(max(age_values), 2)
        else:
            self.upstream_data_age_hours = 0.0

        self.dependency_check_passed = dep_check['all_critical_present']
        self.missing_dependencies_list = missing_deps

        logger.info(f"Source tracking complete: completeness={self.data_completeness_pct}%, "
                f"max_age={self.upstream_data_age_hours}h")
