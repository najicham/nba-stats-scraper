"""
Fallback Source Mixin

Provides automatic fallback data source functionality for processors.
Reads fallback chains from config and tries sources in order,
logging events to source_coverage_log.

Usage:
    class MyProcessor(FallbackSourceMixin, QualityMixin, BaseProcessor):
        def extract_team_data(self, game_id, game_date):
            result = self.try_fallback_chain(
                chain_name='team_boxscores',
                extractors={
                    'nbac_team_boxscore': lambda: self._query_nbac(game_id),
                    'reconstructed_team_from_players': lambda: self._reconstruct(game_id),
                },
                context={'game_id': game_id, 'game_date': game_date},
            )

            if result.success:
                return result.data, result.quality_tier, result.quality_score
            elif result.should_skip:
                return None, None, None
            elif result.is_placeholder:
                return self._create_placeholder(), 'unusable', 0

Version: 1.0
Created: 2025-11-30
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any

import pandas as pd

from shared.config.data_sources import DataSourceConfig, FallbackChainConfig
from shared.config.source_coverage import (
    SourceCoverageEventType,
    SourceCoverageSeverity,
)
from shared.processors.patterns.quality_columns import (
    build_standard_quality_columns,
    build_quality_columns_with_legacy,
    build_completeness_columns,
)

logger = logging.getLogger(__name__)


@dataclass
class FallbackResult:
    """
    Result of attempting a fallback chain.

    Attributes:
        success: Whether data was successfully retrieved
        data: The retrieved DataFrame (None if failed)
        source_used: Name of source that provided data
        quality_tier: Quality tier for this data
        quality_score: Numeric quality score (0-100)
        sources_tried: List of sources attempted
        is_primary: Whether primary source was used
        is_reconstructed: Whether data was reconstructed
        is_placeholder: Whether this is a placeholder record
        should_skip: Whether processing should skip this entity
        continued_without: Whether processing continued without this data
        quality_issues: List of quality issues to record
    """
    success: bool
    data: Optional[pd.DataFrame]
    source_used: Optional[str]
    quality_tier: str
    quality_score: float
    sources_tried: List[str] = field(default_factory=list)
    is_primary: bool = True
    is_reconstructed: bool = False
    is_placeholder: bool = False
    should_skip: bool = False
    continued_without: bool = False
    quality_issues: List[str] = field(default_factory=list)


class FallbackSourceMixin:
    """
    Mixin providing automatic fallback data source functionality.

    Reads fallback chains from shared/config/data_sources/fallback_config.yaml
    and tries sources in order until one succeeds. Logs events to
    source_coverage_log via QualityMixin.

    Requires:
        - Must be used with QualityMixin for event logging
        - Processors should inherit: FallbackSourceMixin, QualityMixin, BaseProcessor

    Example:
        class TeamDefenseProcessor(FallbackSourceMixin, QualityMixin, BaseProcessor):

            def _extract_opponent_data(self, game_id, game_date):
                result = self.try_fallback_chain(
                    chain_name='team_boxscores',
                    extractors={
                        'nbac_team_boxscore': lambda: self._query_team_boxscore(game_id),
                        'reconstructed_team_from_players': lambda: self._reconstruct_from_players(game_id),
                        'espn_team_boxscore': lambda: self._query_espn(game_id),
                    },
                    context={'game_id': game_id, 'game_date': game_date},
                )

                if result.should_skip:
                    logger.warning(f"Skipping game {game_id}: no team data")
                    return None

                if result.is_placeholder:
                    return self._create_placeholder_record(game_id)

                # Use result.data, result.quality_tier, result.quality_score
                return result.data
    """

    _ds_config: DataSourceConfig = None

    def _ensure_ds_config(self):
        """Lazy-load the data source configuration."""
        if self._ds_config is None:
            self._ds_config = DataSourceConfig()

    def try_fallback_chain(
        self,
        chain_name: str,
        extractors: Dict[str, Callable[[], pd.DataFrame]],
        context: Dict[str, Any] = None,
    ) -> FallbackResult:
        """
        Try sources in fallback chain order until one succeeds.

        Args:
            chain_name: Name of fallback chain from config (e.g., 'team_boxscores')
            extractors: Dict mapping source names to callables that return DataFrames.
                        Each callable should take no arguments and return a DataFrame
                        (or None/empty DataFrame if data not available).
            context: Additional context for logging (game_id, game_date, player_id, etc.)

        Returns:
            FallbackResult with data and quality information.
            Check result.success, result.should_skip, result.is_placeholder
            to determine how to proceed.

        Example:
            result = self.try_fallback_chain(
                chain_name='team_boxscores',
                extractors={
                    'nbac_team_boxscore': lambda: self._query_nbac(game_id),
                    'reconstructed_team_from_players': lambda: self._reconstruct(game_id),
                },
                context={'game_id': game_id, 'game_date': game_date},
            )
        """
        self._ensure_ds_config()
        context = context or {}

        # Get chain configuration
        chain = self._ds_config.get_fallback_chain(chain_name)
        sources_tried = []
        quality_issues = []

        logger.debug(f"Starting fallback chain '{chain_name}' with {len(chain.sources)} sources")

        for source_name in chain.sources:
            # Check if extractor was provided for this source
            if source_name not in extractors:
                logger.warning(
                    f"No extractor provided for source '{source_name}' in chain '{chain_name}', skipping"
                )
                continue

            # Get source configuration
            source_config = self._ds_config.get_source(source_name)
            extractor = extractors[source_name]

            try:
                logger.debug(f"Trying source: {source_name}")
                df = extractor()

                # Check if we got valid data
                if df is not None and not df.empty:
                    # Success!
                    is_fallback = not source_config.is_primary
                    is_reconstructed = source_config.reconstruction_method is not None

                    # Track quality issues
                    if is_fallback:
                        quality_issues.append('backup_source_used')
                    if is_reconstructed:
                        quality_issues.append('reconstructed')

                    # Log fallback usage to source_coverage_log
                    if is_fallback:
                        self._log_fallback_used(
                            chain=chain,
                            source_name=source_name,
                            source_config=source_config,
                            sources_tried=sources_tried,
                            context=context,
                        )

                    logger.info(
                        f"Fallback chain '{chain_name}' succeeded with source '{source_name}' "
                        f"(quality: {source_config.quality_tier}, {source_config.quality_score})"
                    )

                    return FallbackResult(
                        success=True,
                        data=df,
                        source_used=source_name,
                        quality_tier=source_config.quality_tier,
                        quality_score=source_config.quality_score,
                        sources_tried=sources_tried + [source_name],
                        is_primary=source_config.is_primary,
                        is_reconstructed=is_reconstructed,
                        quality_issues=quality_issues,
                    )

                # Source returned empty data
                sources_tried.append(source_name)
                logger.info(f"Source '{source_name}' returned empty data, trying next")

            except Exception as e:
                sources_tried.append(source_name)
                logger.warning(f"Source '{source_name}' failed with error: {e}")

        # All sources failed - handle according to config
        logger.warning(
            f"All sources failed for chain '{chain_name}'. "
            f"Tried: {sources_tried}. Action: {chain.on_all_fail_action}"
        )

        return self._handle_all_sources_failed(chain, sources_tried, context)

    def _log_fallback_used(
        self,
        chain: FallbackChainConfig,
        source_name: str,
        source_config,
        sources_tried: List[str],
        context: Dict[str, Any],
    ):
        """Log fallback usage to source_coverage_log via QualityMixin."""
        # Check if we have log_quality_event method (from QualityMixin)
        if not hasattr(self, 'log_quality_event'):
            logger.debug("QualityMixin not available, skipping event logging")
            return

        try:
            self.log_quality_event(
                event_type=SourceCoverageEventType.FALLBACK_USED.value,
                severity=SourceCoverageSeverity.INFO.value,
                description=f"Used fallback source '{source_name}' for {chain.name}",
                game_id=context.get('game_id'),
                game_date=context.get('game_date'),
                player_id=context.get('player_id'),
                team_abbr=context.get('team_abbr'),
                primary_source=chain.sources[0] if chain.sources else None,
                primary_source_status='missing',
                fallback_sources_tried=sources_tried,
                resolution='used_fallback',
                quality_after={
                    'tier': source_config.quality_tier,
                    'score': source_config.quality_score,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to log fallback event: {e}")

    def _handle_all_sources_failed(
        self,
        chain: FallbackChainConfig,
        sources_tried: List[str],
        context: Dict[str, Any],
    ) -> FallbackResult:
        """Handle when all sources in a chain fail."""
        self._ensure_ds_config()

        action = chain.on_all_fail_action
        game_id = context.get('game_id')
        game_date = context.get('game_date')

        # Log the failure to source_coverage_log
        self._log_source_missing(chain, sources_tried, context)

        # Handle based on configured action
        if action == 'fail':
            # Raise exception - this is for truly critical data
            raise ValueError(
                f"{chain.on_all_fail_message} "
                f"(chain: {chain.name}, tried: {sources_tried})"
            )

        elif action == 'skip':
            # Skip this entity, continue to next
            return FallbackResult(
                success=False,
                data=None,
                source_used=None,
                quality_tier='unusable',
                quality_score=0,
                sources_tried=sources_tried,
                should_skip=True,
                quality_issues=['all_sources_failed'],
            )

        elif action == 'placeholder':
            # Create a placeholder record with unusable quality
            return FallbackResult(
                success=False,
                data=None,
                source_used=None,
                quality_tier=chain.on_all_fail_quality_tier or 'unusable',
                quality_score=chain.on_all_fail_quality_score or 0,
                sources_tried=sources_tried,
                is_placeholder=True,
                quality_issues=['all_sources_failed', 'placeholder_created'],
            )

        elif action == 'continue_without':
            # Continue processing without this data, but degrade quality
            base_score = 100
            impact = chain.on_all_fail_quality_impact or -20
            degraded_score = max(0, base_score + impact)
            tier = self._ds_config.get_tier_from_score(degraded_score)

            return FallbackResult(
                success=True,  # Continue processing
                data=pd.DataFrame(),  # Empty but valid
                source_used=None,
                quality_tier=tier,
                quality_score=degraded_score,
                sources_tried=sources_tried,
                continued_without=True,
                quality_issues=['data_unavailable', f'quality_degraded_by_{abs(impact)}'],
            )

        else:
            raise ValueError(f"Unknown on_all_fail action: {action}")

    def _log_source_missing(
        self,
        chain: FallbackChainConfig,
        sources_tried: List[str],
        context: Dict[str, Any],
    ):
        """Log source missing event to source_coverage_log."""
        if not hasattr(self, 'log_quality_event'):
            return

        # Map severity string to enum
        severity_map = {
            'critical': SourceCoverageSeverity.CRITICAL.value,
            'warning': SourceCoverageSeverity.WARNING.value,
            'info': SourceCoverageSeverity.INFO.value,
        }

        # Determine downstream impact
        action = chain.on_all_fail_action
        if action == 'fail':
            downstream_impact = 'processing_blocked'
        elif action == 'skip':
            downstream_impact = 'entity_skipped'
        elif action == 'placeholder':
            downstream_impact = 'predictions_blocked'
        else:
            downstream_impact = 'confidence_reduced'

        try:
            self.log_quality_event(
                event_type=SourceCoverageEventType.SOURCE_MISSING.value,
                severity=severity_map.get(chain.on_all_fail_severity, 'warning'),
                description=chain.on_all_fail_message,
                game_id=context.get('game_id'),
                game_date=context.get('game_date'),
                player_id=context.get('player_id'),
                team_abbr=context.get('team_abbr'),
                primary_source=chain.sources[0] if chain.sources else None,
                primary_source_status='missing',
                fallback_sources_tried=sources_tried,
                resolution='failed' if action == 'fail' else 'skipped',
                downstream_impact=downstream_impact,
            )
        except Exception as e:
            logger.warning(f"Failed to log source missing event: {e}")

    def build_quality_columns_from_result(
        self,
        result: FallbackResult,
        additional_issues: List[str] = None,
        completeness: Dict[str, Any] = None,
        include_legacy: bool = True,
    ) -> Dict[str, Any]:
        """
        Build standard quality columns dict from a FallbackResult.

        Uses the centralized build_standard_quality_columns() helper to ensure
        consistent column output across all processors.

        Args:
            result: FallbackResult from try_fallback_chain()
            additional_issues: Extra quality issues to append
            completeness: Optional completeness metrics dict (for Phase 4 only)
            include_legacy: If True, include deprecated legacy columns for
                           backward compatibility during migration

        Returns:
            Dict of quality column names to values

        Example:
            result = self.try_fallback_chain(...)
            quality_cols = self.build_quality_columns_from_result(result)
            row.update(quality_cols)
        """
        # Combine quality issues
        issues = list(result.quality_issues)
        if additional_issues:
            issues.extend(additional_issues)

        # Build data sources list
        sources = [result.source_used] if result.source_used else []

        # Use the centralized helper (with or without legacy columns)
        if include_legacy:
            columns = build_quality_columns_with_legacy(
                tier=result.quality_tier,
                score=result.quality_score,
                issues=issues,
                sources=sources,
            )
        else:
            columns = build_standard_quality_columns(
                tier=result.quality_tier,
                score=result.quality_score,
                issues=issues,
                sources=sources,
            )

        # Add completeness if provided (Phase 4 precompute tables only)
        if completeness:
            columns.update(build_completeness_columns(
                expected=completeness.get('expected', 0),
                actual=completeness.get('actual', 0),
            ))

        return columns

    def get_source_quality(self, source_name: str) -> tuple:
        """
        Get quality tier and score for a source.

        Args:
            source_name: Name of the data source

        Returns:
            Tuple of (quality_tier, quality_score)

        Example:
            tier, score = self.get_source_quality('bdl_player_boxscores')
            # ('silver', 85)
        """
        self._ensure_ds_config()
        source = self._ds_config.get_source(source_name)
        return (source.quality_tier, source.quality_score)

    def get_chain_sources(self, chain_name: str) -> List[str]:
        """
        Get list of source names in a fallback chain.

        Args:
            chain_name: Name of the fallback chain

        Returns:
            List of source names in priority order
        """
        self._ensure_ds_config()
        chain = self._ds_config.get_fallback_chain(chain_name)
        return chain.sources
