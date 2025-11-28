# NBA Props Platform - Source Coverage System Design
## Part 3: Implementation Guide

**Created:** 2025-11-26
**Parent Document:** [Part 1: Core Design & Architecture](01-core-design.md)

---

> **PREREQUISITE: Streaming Buffer Migration**
>
> Complete the streaming buffer migration **before** implementing source coverage.
> Both systems use batch loading (`load_table_from_json`) instead of streaming inserts.
>
> See: `docs/08-projects/current/streaming-buffer-migration/`
>
> This ensures:
> - No streaming buffer conflicts during source coverage implementation
> - Consistent BigQuery loading patterns across all processors
> - Processors can immediately UPDATE/DELETE after INSERT

---

## Table of Contents

1. [Implementation Overview](#implementation-overview)
2. [Event Type Constants](#event-type-constants)
3. [Quality Mixin](#quality-mixin)
4. [Fallback Source Mixin](#fallback-source-mixin)
5. [Coverage Audit Processor](#coverage-audit-processor)
6. [Example Processor Integration](#example-processor-integration)
7. [Alert System](#alert-system)
8. [Utility Functions](#utility-functions)

---

## Implementation Overview

### File Structure

```
/shared_services/
+-- constants/
|   +-- source_coverage.py          [NEW] Event type enums
+-- processors/
|   +-- quality_mixin.py            [NEW] Quality scoring logic
|   +-- fallback_source_mixin.py    [NEW] Fallback handling
+-- utils/
    +-- source_coverage_utils.py    [NEW] Helper functions

/data_processors/analytics/
+-- player_game_summary/
    +-- player_game_summary_processor.py  [MODIFIED] Add mixins

/data_processors/
+-- source_coverage_audit.py        [NEW] Daily audit job

/tests/
+-- unit/
|   +-- test_quality_mixin.py
|   +-- test_fallback_mixin.py
+-- integration/
    +-- test_source_coverage_flow.py
```

### Adaptation Notes for This Codebase

**Use existing infrastructure:**

| Need | Use This | Location |
|------|----------|----------|
| Error notifications | `notify_error()` | `shared/utils/notification_system.py` |
| Warning notifications | `notify_warning()` | `shared/utils/notification_system.py` |
| Info notifications | `notify_info()` | `shared/utils/notification_system.py` |
| Quality issues list | `self.quality_issues` | `analytics_base.py:86` |
| Source metadata | `self.source_metadata` | `analytics_base.py:83` |
| BigQuery client | `self.bq_client` | Already on base classes |
| Batch loading | `load_table_from_json()` | See `bigquery-best-practices.md` |

**Do NOT:**
- Create new alert/notification functions
- Use `insert_rows_json()` (streaming buffer issues)
- Create traditional indexes (BigQuery doesn't support them)

### Integration Pattern

Every Phase 3+ processor should follow this pattern:

```python
from shared_services.processors.quality_mixin import QualityMixin
from shared_services.processors.fallback_source_mixin import FallbackSourceMixin
from data_processors.analytics.analytics_base import AnalyticsProcessorBase

class MyProcessor(
    FallbackSourceMixin,    # Try multiple sources
    QualityMixin,           # Calculate quality
    AnalyticsProcessorBase  # Existing base (has quality_issues, source_metadata)
):
    # Configure quality assessment
    REQUIRED_FIELDS = ['field1', 'field2']
    OPTIONAL_FIELDS = ['field3', 'field4']

    # Configure fallback behavior
    PRIMARY_SOURCES = ['source1']
    FALLBACK_SOURCES = ['source2', 'source3']

    def process(self):
        # Mixins handle everything else
        pass
```

---

## Event Type Constants

### File: `/shared_services/constants/source_coverage.py`

```python
"""
Source Coverage Event Type Constants

Provides standardized event types and severity levels for source coverage logging.
Use these constants instead of magic strings to prevent typos and enable IDE autocomplete.
"""


class SourceCoverageEventType:
    """
    Standardized event types for source coverage log.

    Usage:
        from shared_services.constants.source_coverage import SourceCoverageEventType

        self.log_quality_event(
            event_type=SourceCoverageEventType.FALLBACK_USED,
            ...
        )
    """

    # Source availability
    SOURCE_MISSING = 'source_missing'
    SOURCE_DEGRADED = 'source_degraded'
    SOURCE_TIMEOUT = 'source_timeout'
    SOURCE_ERROR = 'source_error'

    # Fallback handling
    FALLBACK_USED = 'fallback_used'
    FALLBACK_FAILED = 'fallback_failed'

    # Reconstruction
    RECONSTRUCTION = 'reconstruction'
    RECONSTRUCTION_FAILED = 'reconstruction_failed'

    # Sample size
    INSUFFICIENT_SAMPLE = 'insufficient_sample'
    THIN_SAMPLE = 'thin_sample'

    # Player-specific
    NEW_PLAYER = 'new_player_no_history'
    TRADED_PLAYER = 'traded_player_context'

    # Quality
    QUALITY_DEGRADATION = 'quality_degradation'

    # Validation
    VALIDATION_FAILURE = 'validation_failure'

    # Audit
    SILENT_FAILURE = 'silent_failure'


class SourceCoverageSeverity:
    """
    Severity levels for coverage events.

    CRITICAL: Blocks predictions, immediate alert
    WARNING: Degrades quality, digest alert
    INFO: Notable but acceptable, log only
    """
    CRITICAL = 'critical'
    WARNING = 'warning'
    INFO = 'info'


class QualityTier:
    """Quality tier constants"""
    GOLD = 'gold'
    SILVER = 'silver'
    BRONZE = 'bronze'
    POOR = 'poor'
    UNUSABLE = 'unusable'
```

---

## Quality Mixin

### File: `/shared_services/processors/quality_mixin.py`

```python
"""
Quality Mixin for Source Coverage

Provides quality scoring, tier calculation, and event logging capabilities
to any processor that inherits from it.

ADAPTATION NOTE: This mixin is designed to work with AnalyticsProcessorBase
which already has self.quality_issues and self.source_metadata attributes.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime, date
import pandas as pd
import uuid

from shared_services.constants.source_coverage import (
    SourceCoverageEventType,
    SourceCoverageSeverity,
    QualityTier
)
# Use existing notification system
from shared.utils.notification_system import notify_error, notify_warning, notify_info


class QualityMixin:
    """
    Mixin providing quality assessment and logging capabilities.

    IMPORTANT - Mixin Resolution Order (MRO):
    Python uses left-to-right MRO. Your class declaration order matters:

        # CORRECT ORDER:
        class MyProcessor(FallbackSourceMixin, QualityMixin, AnalyticsProcessorBase):
            pass

        # FallbackSourceMixin methods take precedence over QualityMixin
        # Both mixin methods take precedence over AnalyticsProcessorBase
        # Base class must be LAST

    Usage:
        class MyProcessor(QualityMixin, AnalyticsProcessorBase):
            REQUIRED_FIELDS = ['points', 'minutes']
            OPTIONAL_FIELDS = ['plus_minus']
            FIELD_WEIGHTS = {'points': 10.0, 'minutes': 8.0}

            def process(self):
                data = self.fetch_data()
                quality = self.assess_quality(data, sources_used=['primary'])
                self.load_with_quality(data, quality)
                self.flush_events()  # IMPORTANT: Call at end of processor run
    """

    # ==========================================================================
    # CONFIGURATION (Subclasses override these)
    # ==========================================================================
    REQUIRED_FIELDS: List[str] = []
    OPTIONAL_FIELDS: List[str] = []
    FIELD_WEIGHTS: Dict[str, float] = {}

    # ==========================================================================
    # EVENT BUFFERING - Prevents 13+ separate BQ load jobs per game
    # ==========================================================================
    _event_buffer: List[Dict] = []

    # ==========================================================================
    # CONTEXT MANAGER - Auto-flush on exit (even on crash)
    # ==========================================================================
    def __enter__(self):
        """Enable context manager usage for auto-flush."""
        self._event_buffer = []  # Reset buffer on entry
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Auto-flush events when exiting context, even on exception."""
        try:
            self.flush_events()
        except Exception as e:
            # Log but don't suppress the original exception
            logger.error(f"Failed to flush events on exit: {e}")
        return False  # Don't suppress exceptions

    # Usage:
    # with PlayerGameSummaryProcessor() as processor:
    #     processor.process_game(game_id)
    # # Events auto-flushed here, even if exception occurred

    # Season-aware thresholds
    SAMPLE_THRESHOLD_EARLY_SEASON: int = 3    # First 10 games of season
    SAMPLE_THRESHOLD_MID_SEASON: int = 5      # Games 11-30
    SAMPLE_THRESHOLD_FULL_SEASON: int = 8     # After game 30

    def assess_quality(
        self,
        data: pd.DataFrame,
        sources_used: List[str],
        reconstruction_applied: bool = False,
        context: Optional[Dict[str, Any]] = None,
        game_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Comprehensive quality assessment with season-aware thresholds.

        Args:
            data: DataFrame to assess
            sources_used: Which sources were used (in priority order)
            reconstruction_applied: Was data reconstructed?
            context: Additional context (e.g., expected_sample_size)
            game_date: Date of game (for season-aware thresholds)

        Returns:
            {
                'tier': 'silver',
                'score': 85.5,
                'issues': ['backup_source_used'],
                'sources': ['espn_backup'],
                'metadata': {...}
            }
        """
        issues = []
        context = context or {}

        # 1. Check required fields
        missing_required = [
            f for f in self.REQUIRED_FIELDS
            if f not in data.columns
        ]

        if missing_required:
            return {
                'tier': QualityTier.UNUSABLE,
                'score': 0.0,
                'issues': [f'missing_required:{f}' for f in missing_required],
                'sources': sources_used,
                'metadata': {
                    'critical_failure': True,
                    'missing_required_fields': missing_required
                }
            }

        # 2. Check optional fields
        missing_optional = [
            f for f in self.OPTIONAL_FIELDS
            if f not in data.columns
        ]

        if missing_optional:
            issues.extend([f'missing_optional:{f}' for f in missing_optional])

        # 3. Calculate base completeness score
        total_fields = len(self.REQUIRED_FIELDS) + len(self.OPTIONAL_FIELDS)
        present_fields = total_fields - len(missing_optional)

        if total_fields > 0:
            completeness_score = (present_fields / total_fields) * 100
        else:
            completeness_score = 100.0

        # 4. Apply field weights if defined
        if self.FIELD_WEIGHTS:
            weighted_score = self._calculate_weighted_score(data)
            completeness_score = (completeness_score + weighted_score) / 2

        # 5. Check null rates and apply penalty
        null_penalty = self._calculate_null_penalty(data)
        completeness_score = max(0, completeness_score - null_penalty)

        if null_penalty > 10:
            issues.append(f'high_null_rate:{null_penalty:.1f}pct')

        # 6. Sample size check (season-aware)
        sample_size = len(data) if isinstance(data, pd.DataFrame) else 1

        if 'expected_sample_size' in context:
            expected = context['expected_sample_size']
        elif game_date:
            expected = self._get_expected_sample_size(game_date)
        else:
            expected = 10  # Default fallback

        if sample_size < expected * 0.5:
            issues.append(f'thin_sample:{sample_size}/{expected}')
            completeness_score *= 0.8  # 20% penalty

        # Check if early season
        early_season = game_date and self._is_early_season(game_date)

        # 7. Determine tier
        tier = self._score_to_tier(
            score=completeness_score,
            sources_used=sources_used,
            reconstruction_applied=reconstruction_applied,
            sample_size=sample_size,
            expected_sample_size=expected,
            early_season=early_season
        )

        # 8. Build result
        return {
            'tier': tier,
            'score': round(completeness_score, 1),
            'issues': issues,
            'sources': sources_used,
            'metadata': {
                'sample_size': sample_size,
                'expected_sample_size': expected,
                'null_penalty': round(null_penalty, 1),
                'reconstruction_applied': reconstruction_applied,
                'early_season': early_season,
                'games_into_season': self._get_games_into_season(game_date) if game_date else None,
                'assessment_timestamp': datetime.utcnow().isoformat()
            }
        }

    def _get_season_start(self, game_date: date) -> date:
        """Get the start date of the NBA season for a given game date."""
        year = game_date.year

        # If game is Jan-June, it's the previous year's season
        if game_date.month <= 6:
            year -= 1

        # Season typically starts around Oct 20-25
        return date(year, 10, 15)

    def _get_games_into_season(self, game_date: date) -> int:
        """Estimate how many games into the season we are."""
        season_start = self._get_season_start(game_date)
        days_elapsed = (game_date - season_start).days
        return max(0, days_elapsed // 2)

    def _get_expected_sample_size(
        self,
        game_date: date,
        default_expected: int = 10
    ) -> int:
        """Get expected sample size based on season progress."""
        games_into_season = self._get_games_into_season(game_date)

        if games_into_season < 10:
            return min(self.SAMPLE_THRESHOLD_EARLY_SEASON, games_into_season + 1)
        elif games_into_season < 30:
            return self.SAMPLE_THRESHOLD_MID_SEASON
        else:
            return self.SAMPLE_THRESHOLD_FULL_SEASON

    def _is_early_season(self, game_date: date) -> bool:
        """Check if game is in early season (first 15 games)"""
        return self._get_games_into_season(game_date) < 15

    def _calculate_weighted_score(self, data: pd.DataFrame) -> float:
        """Calculate score based on field importance weights"""
        if not self.FIELD_WEIGHTS:
            return 100.0

        total_weight = sum(self.FIELD_WEIGHTS.values())
        achieved_weight = sum(
            self.FIELD_WEIGHTS.get(field, 0)
            for field in data.columns
            if field in self.FIELD_WEIGHTS
        )

        return (achieved_weight / total_weight * 100) if total_weight > 0 else 100.0

    def _calculate_null_penalty(self, data: pd.DataFrame) -> float:
        """Penalize high null rates in important fields"""
        if data.empty:
            return 0.0

        penalty = 0.0

        # Check important fields
        for field, weight in self.FIELD_WEIGHTS.items():
            if field in data.columns:
                null_rate = data[field].isnull().mean()
                if null_rate > 0.1:  # More than 10% nulls
                    penalty += (null_rate - 0.1) * weight * 50

        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field in data.columns:
                null_rate = data[field].isnull().mean()
                if null_rate > 0.2:  # More than 20% nulls in required
                    penalty += (null_rate - 0.2) * 100

        return min(penalty, 50)  # Cap at 50 points

    def _score_to_tier(
        self,
        score: float,
        sources_used: List[str],
        reconstruction_applied: bool,
        sample_size: int,
        expected_sample_size: int = 10,
        early_season: bool = False
    ) -> str:
        """Convert numeric score to tier with season-aware adjustments."""

        # Base tier from score
        if score >= 95:
            tier = QualityTier.GOLD
        elif score >= 75:
            tier = QualityTier.SILVER
        elif score >= 50:
            tier = QualityTier.BRONZE
        elif score >= 25:
            tier = QualityTier.POOR
        else:
            return QualityTier.UNUSABLE

        # Rule 1: Backup source used
        if sources_used and 'primary' not in sources_used:
            if tier == QualityTier.GOLD:
                tier = QualityTier.SILVER

        # Rule 2: Reconstruction applied
        if reconstruction_applied:
            if tier == QualityTier.GOLD:
                tier = QualityTier.SILVER

        # Rule 3: Sample size check (season-aware)
        sample_ratio = sample_size / expected_sample_size if expected_sample_size > 0 else 1.0

        if early_season:
            # Relaxed thresholds for early season
            if sample_ratio < 0.3:
                if tier in [QualityTier.GOLD, QualityTier.SILVER]:
                    tier = QualityTier.BRONZE
        else:
            # Normal season thresholds
            if sample_ratio < 0.5:
                if tier in [QualityTier.GOLD, QualityTier.SILVER]:
                    tier = QualityTier.BRONZE

        # Rule 4: Very thin sample
        if sample_size < 2:
            tier = QualityTier.POOR

        return tier

    def log_quality_event(
        self,
        event_type: str,
        severity: str,
        description: str,
        quality_before: Optional[Dict] = None,
        quality_after: Optional[Dict] = None,
        game_id: Optional[str] = None,
        player_id: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        Log a source coverage event to the buffer (written on flush).

        Events are buffered to avoid 13+ separate BigQuery load jobs per game.
        Call flush_events() at the end of your processor run.

        Returns:
            event_id (UUID)
        """
        event_id = str(uuid.uuid4())

        event_data = {
            'event_id': event_id,
            'event_timestamp': datetime.utcnow(),
            'event_type': event_type,
            'severity': severity,
            'phase': getattr(self, 'PHASE', 'unknown'),
            'table_name': getattr(self, 'OUTPUT_TABLE', 'unknown'),
            'processor_name': self.__class__.__name__,
            'game_id': game_id,
            'game_date': kwargs.get('game_date'),
            'season': kwargs.get('season'),
            'player_id': player_id,
            'team_abbr': kwargs.get('team_abbr'),
            'description': description,
            'primary_source': kwargs.get('primary_source'),
            'primary_source_status': kwargs.get('primary_source_status'),
            'fallback_sources_tried': kwargs.get('fallback_sources_tried', []),
            'resolution': kwargs.get('resolution'),
            'resolution_details': kwargs.get('resolution_details'),
            'quality_tier_before': quality_before.get('tier') if quality_before else None,
            'quality_tier_after': quality_after.get('tier') if quality_after else None,
            'quality_score_before': quality_before.get('score') if quality_before else None,
            'quality_score_after': quality_after.get('score') if quality_after else None,
            'downstream_impact': kwargs.get('downstream_impact'),
            'requires_alert': severity in [SourceCoverageSeverity.CRITICAL, SourceCoverageSeverity.WARNING],
            'alert_sent': False,
            'environment': 'prod',
            'processor_run_id': getattr(self, 'run_id', None),
            'is_synthetic': False
        }

        # Buffer the event (don't write immediately)
        self._event_buffer.append(event_data)

        # Send alert if needed (alerts are immediate, not buffered)
        if event_data['requires_alert']:
            if self._should_send_alert(event_data):
                self._send_alert(event_data)
                event_data['alert_sent'] = True

        return event_id

    def flush_events(self):
        """
        Flush buffered events to BigQuery.

        IMPORTANT: Call this at the end of every processor run!
        This writes all buffered events in a single batch load job.
        """
        if not self._event_buffer:
            return

        try:
            self._insert_quality_events_batch(self._event_buffer)
            logger.info(f"Flushed {len(self._event_buffer)} quality events to BigQuery")
        except Exception as e:
            # Don't fail the processor, but log loudly
            logger.error(f"FAILED to flush quality events: {e}")
            notify_error(
                title="Source coverage event logging failed",
                message=str(e),
                details={'event_count': len(self._event_buffer)},
                processor_name=self.__class__.__name__
            )
        finally:
            self._event_buffer = []

    def _insert_quality_events_batch(self, events: List[Dict]):
        """Insert multiple events to source coverage log in single batch."""
        df = pd.DataFrame(events)

        # Convert datetime objects
        if 'event_timestamp' in df.columns:
            df['event_timestamp'] = df['event_timestamp'].apply(
                lambda x: x.isoformat() if isinstance(x, datetime) else x
            )

        # Use batch loading (not streaming inserts)
        from google.cloud import bigquery

        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND
        )

        load_job = self.bq_client.load_table_from_json(
            df.to_dict('records'),
            'nba_reference.source_coverage_log',
            job_config=job_config
        )
        load_job.result()

    def _should_send_alert(self, event_data: Dict) -> bool:
        """
        Check if we should send an alert, with deduplication.

        Prevents alert storms during outages:
        - NBA.com down = 10 games × 26 players × 3 processors = 780 potential alerts
        - With dedup: 1 alert per (event_type + primary_source) per 4 hours

        IMPORTANT: Check BOTH the buffer AND the database.
        Events in the buffer haven't been written to DB yet, so we'd miss them
        and send duplicate alerts within the same processor run.
        """
        event_type = event_data['event_type']
        primary_source = event_data.get('primary_source', '')

        # 1. Check buffer first (events not yet in database)
        # Without this, processing 13 players would send 13 alerts!
        for buffered in self._event_buffer:
            if (buffered.get('event_type') == event_type and
                buffered.get('primary_source') == primary_source and
                buffered.get('alert_sent', False)):
                logger.debug(f"Alert suppressed: already alerted in current batch")
                return False

        # 2. Then check database for recent alerts
        try:
            query = f"""
                SELECT COUNT(*) as recent_alerts
                FROM nba_reference.source_coverage_log
                WHERE event_type = '{event_type}'
                  AND primary_source = '{primary_source}'
                  AND alert_sent = TRUE
                  AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
            """
            result = self.bq_client.query(query).to_dataframe()
            return result.iloc[0]['recent_alerts'] == 0
        except Exception as e:
            logger.warning(f"Alert dedup check failed: {e}, sending alert anyway")
            return True

    def _send_alert(self, event_data: Dict):
        """Send alert using existing notification system."""

        if event_data['severity'] == SourceCoverageSeverity.CRITICAL:
            notify_error(
                title=f"Source Coverage: {event_data['event_type']}",
                message=event_data['description'],
                details={
                    'game_id': event_data.get('game_id'),
                    'event_id': event_data['event_id']
                },
                processor_name=event_data.get('processor_name', 'SourceCoverage')
            )
        elif event_data['severity'] == SourceCoverageSeverity.WARNING:
            notify_warning(
                title=f"Source Coverage: {event_data['event_type']}",
                message=event_data['description'],
                details={
                    'game_id': event_data.get('game_id'),
                    'event_id': event_data['event_id']
                }
            )
```

---

## Fallback Source Mixin

### File: `/shared_services/processors/fallback_source_mixin.py`

```python
"""
Fallback Source Mixin

Provides automatic fallback to alternative data sources when primary source fails.
"""

from typing import Dict, List, Tuple, Optional, Callable
import pandas as pd
import logging

from shared_services.constants.source_coverage import (
    SourceCoverageEventType,
    SourceCoverageSeverity
)

logger = logging.getLogger(__name__)


class FallbackSourceMixin:
    """
    Mixin providing automatic fallback to alternative data sources.

    Usage:
        class MyProcessor(FallbackSourceMixin, QualityMixin, AnalyticsProcessorBase):
            PRIMARY_SOURCES = ['nbac_team_boxscore']
            FALLBACK_SOURCES = ['espn_team_boxscore', 'bdl_box_scores']
            RECONSTRUCTION_ALLOWED = True
    """

    # ==========================================================================
    # CONFIGURATION (Subclasses override these)
    # ==========================================================================
    PRIMARY_SOURCES: List[str] = []
    FALLBACK_SOURCES: List[str] = []
    RECONSTRUCTION_ALLOWED: bool = False

    def fetch_with_fallback(
        self,
        game_id: str,
        fetch_functions: Dict[str, Callable],
        reconstruction_fn: Optional[Callable] = None
    ) -> Tuple[Optional[pd.DataFrame], List[str]]:
        """
        Try sources in priority order, optionally reconstruct if all fail.

        Args:
            game_id: Game ID to fetch
            fetch_functions: Dict mapping source name to fetch function
            reconstruction_fn: Optional function to reconstruct data

        Returns:
            (data, sources_tried)
        """
        sources_tried = []
        all_sources = self.PRIMARY_SOURCES + self.FALLBACK_SOURCES

        # Try each source in order
        for source_name in all_sources:
            if source_name not in fetch_functions:
                logger.warning(f"No fetch function provided for {source_name}")
                continue

            try:
                logger.info(f"Attempting {source_name} for game {game_id}")

                data = fetch_functions[source_name](game_id)

                if data is not None and not data.empty:
                    sources_tried.append(source_name)

                    # Log if using fallback
                    if source_name in self.FALLBACK_SOURCES:
                        self.log_quality_event(
                            event_type=SourceCoverageEventType.FALLBACK_USED,
                            severity=SourceCoverageSeverity.INFO,
                            description=f"Primary source unavailable, used {source_name}",
                            game_id=game_id,
                            primary_source=self.PRIMARY_SOURCES[0] if self.PRIMARY_SOURCES else 'unknown',
                            primary_source_status='missing',
                            fallback_sources_tried=[source_name],
                            resolution='used_fallback'
                        )

                    logger.info(f"Successfully fetched from {source_name}")
                    return data, sources_tried
                else:
                    sources_tried.append(f"{source_name}_empty")
                    logger.warning(f"{source_name} returned no data for {game_id}")

            except Exception as e:
                sources_tried.append(f"{source_name}_error")
                logger.error(f"{source_name} failed for {game_id}: {str(e)}")
                continue

        # All sources failed - try reconstruction if allowed
        if self.RECONSTRUCTION_ALLOWED and reconstruction_fn:
            try:
                logger.info(f"All sources failed, attempting reconstruction for {game_id}")

                data = reconstruction_fn(game_id)

                if data is not None and not data.empty:
                    sources_tried.append('reconstructed')

                    self.log_quality_event(
                        event_type=SourceCoverageEventType.RECONSTRUCTION,
                        severity=SourceCoverageSeverity.INFO,
                        description="Data reconstructed from alternative sources",
                        game_id=game_id,
                        primary_source=self.PRIMARY_SOURCES[0] if self.PRIMARY_SOURCES else 'unknown',
                        primary_source_status='missing',
                        fallback_sources_tried=sources_tried,
                        resolution='reconstructed'
                    )

                    logger.info(f"Successfully reconstructed data for {game_id}")
                    return data, sources_tried
                else:
                    sources_tried.append('reconstruction_empty')

            except Exception as e:
                logger.error(f"Reconstruction failed for {game_id}: {str(e)}")
                sources_tried.append('reconstruction_error')

        # Complete failure - log critical event
        self.log_quality_event(
            event_type=SourceCoverageEventType.SOURCE_MISSING,
            severity=SourceCoverageSeverity.CRITICAL,
            description=f"No data available from any source for {game_id}",
            game_id=game_id,
            primary_source=self.PRIMARY_SOURCES[0] if self.PRIMARY_SOURCES else 'unknown',
            primary_source_status='missing',
            fallback_sources_tried=sources_tried,
            resolution='failed',
            downstream_impact='predictions_blocked'
        )

        return None, sources_tried
```

---

## Coverage Audit Processor

### File: `/data_processors/source_coverage_audit.py`

```python
"""
Source Coverage Audit Processor

Daily job to detect games that should have been processed but weren't.
Catches silent failures where processors never ran or failed before logging.
"""

from typing import List, Dict, Any
from datetime import date, datetime, timedelta
import uuid
import pandas as pd
import logging
import os

from google.cloud import bigquery
from shared.utils.notification_system import notify_error, notify_info
from shared_services.constants.source_coverage import (
    SourceCoverageEventType,
    SourceCoverageSeverity
)

# IMPORTANT: Use proper timezone handling
# Games are scheduled in PT, but Python date.today() uses system timezone (usually UTC)
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:
    from backports.zoneinfo import ZoneInfo  # Python 3.8

PT = ZoneInfo("America/Los_Angeles")

logger = logging.getLogger(__name__)


class SourceCoverageAuditProcessor:
    """
    Daily audit to detect silent processing failures.

    Compares:
    - What SHOULD exist (from schedule)
    - What DOES exist (log + data tables)

    Creates synthetic events for games completely missing.
    """

    # Configurable: Add tables as pipeline grows
    # Can also be loaded from YAML config
    AUDIT_CHECK_TABLES = [
        ('nba_raw.nbac_team_boxscore', 'game_id'),
        ('nba_raw.nbac_player_boxscore', 'game_id'),
        ('nba_analytics.player_game_summary', 'game_id'),
        ('nba_analytics.team_offense_game_summary', 'game_id'),
    ]

    def __init__(self, dry_run: bool = False):
        self.bq_client = bigquery.Client()
        self.dry_run = dry_run or os.environ.get('AUDIT_DRY_RUN', 'false').lower() == 'true'

    def run_daily_audit(self, target_date: date = None):
        """Main audit flow for a single date."""
        if target_date is None:
            # CRITICAL: Use PT timezone for game dates, not UTC
            # Monday 11 PM PT game would be missed if using UTC date.today()
            now_pt = datetime.now(PT)
            target_date = (now_pt - timedelta(days=1)).date()

        logger.info(f"Running source coverage audit for {target_date}")

        # 1. Get scheduled games
        scheduled_games = self.get_scheduled_games(target_date)
        logger.info(f"Found {len(scheduled_games)} scheduled games")

        if not scheduled_games:
            logger.info("No games scheduled, skipping audit")
            return

        # 2. Check each game
        issues_found = 0
        for game in scheduled_games:
            coverage_status = self.check_game_coverage(game)

            if coverage_status['status'] != 'normal':
                issues_found += 1
                self.handle_coverage_issue(game, coverage_status)

        # 3. Summary
        logger.info(f"Audit complete: {issues_found} issues found out of {len(scheduled_games)} games")

        # 4. Send summary if issues found
        if issues_found > 0:
            self.send_audit_summary(target_date, issues_found, len(scheduled_games))

    def get_scheduled_games(self, target_date: date) -> List[Dict]:
        """Get all games scheduled for target date"""
        query = f"""
        SELECT
            game_id,
            game_date,
            home_team_abbr,
            away_team_abbr,
            season
        FROM nba_raw.nbac_schedule
        WHERE game_date = '{target_date}'
          AND game_status = 'Final'
        ORDER BY game_id
        """

        df = self.bq_client.query(query).to_dataframe()
        return df.to_dict('records')

    def check_game_coverage(self, game: Dict) -> Dict[str, Any]:
        """Check if game has proper coverage."""
        game_id = game['game_id']

        # Check coverage log
        log_query = f"""
        SELECT COUNT(*) as event_count
        FROM nba_reference.source_coverage_log
        WHERE game_id = '{game_id}'
          AND DATE(event_timestamp) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """
        log_events = self.bq_client.query(log_query).to_dataframe()
        has_log_events = log_events.iloc[0]['event_count'] > 0

        # Check data tables
        tables_with_data = []
        tables_without_data = []

        for table, id_column in self.AUDIT_CHECK_TABLES:
            try:
                result = self.bq_client.query(f"""
                    SELECT COUNT(*) as row_count
                    FROM `{table}`
                    WHERE {id_column} = '{game_id}'
                """).to_dataframe()

                if result.iloc[0]['row_count'] > 0:
                    tables_with_data.append(table)
                else:
                    tables_without_data.append(table)

            except Exception as e:
                logger.warning(f"Could not check {table}: {e}")
                continue

        # Determine status
        if not has_log_events and len(tables_with_data) == 0:
            return {
                'status': 'completely_missing',
                'severity': 'critical',
                'description': f"Game {game_id} scheduled but never processed"
            }
        elif not has_log_events and len(tables_with_data) > 0:
            return {
                'status': 'data_exists_no_log',
                'severity': 'warning',
                'description': f"Game {game_id} has data but no coverage log events"
            }
        elif has_log_events and len(tables_with_data) == 0:
            return {
                'status': 'logged_but_no_data',
                'severity': 'critical',
                'description': f"Game {game_id} has log events but no data"
            }
        else:
            return {
                'status': 'normal',
                'severity': 'info',
                'description': f"Game {game_id} has both log events and data"
            }

    def handle_coverage_issue(self, game: Dict, status: Dict):
        """Handle detected coverage issue"""
        if status['status'] == 'normal':
            return

        # DRY RUN MODE: Log what would happen without making changes
        if self.dry_run:
            logger.info(f"[DRY RUN] Would create synthetic event for {game['game_id']}")
            logger.info(f"[DRY RUN] Severity: {status['severity']}")
            logger.info(f"[DRY RUN] Description: {status['description']}")
            if status['severity'] == 'critical':
                logger.info(f"[DRY RUN] Would send critical alert")
            return

        # Create synthetic event
        event_id = self.create_synthetic_event(game, status)

        logger.warning(f"Coverage issue detected: {status['description']}")

        # Send alert if critical
        if status['severity'] == 'critical':
            notify_error(
                title="Silent Processing Failure Detected",
                message=status['description'],
                details={
                    'game_id': game['game_id'],
                    'game_date': str(game['game_date']),
                    'event_id': event_id
                },
                processor_name='SourceCoverageAudit'
            )

    def create_synthetic_event(self, game: Dict, status: Dict) -> str:
        """Create synthetic coverage event for audit-detected issue"""
        event_id = str(uuid.uuid4())

        event_data = [{
            'event_id': event_id,
            'event_timestamp': datetime.utcnow().isoformat(),
            'event_type': SourceCoverageEventType.SILENT_FAILURE,
            'severity': status['severity'],
            'is_synthetic': True,
            'phase': 'audit',
            'processor_name': 'SourceCoverageAuditProcessor',
            'game_id': game['game_id'],
            'game_date': str(game['game_date']),
            'season': game.get('season'),
            'description': status['description'],
            'resolution': 'requires_investigation',
            'requires_alert': status['severity'] == 'critical',
            'environment': 'prod'
        }]

        # Use batch loading
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND
        )

        load_job = self.bq_client.load_table_from_json(
            event_data,
            'nba_reference.source_coverage_log',
            job_config=job_config
        )
        load_job.result()

        return event_id

    def send_audit_summary(self, target_date: date, issues_found: int, total_games: int):
        """Send daily audit summary"""
        notify_info(
            title=f"Source Coverage Audit - {target_date}",
            message=f"Checked {total_games} games, found {issues_found} issues",
            details={
                'target_date': str(target_date),
                'total_games': total_games,
                'issues_found': issues_found,
                'success_rate': f"{((total_games - issues_found) / total_games * 100):.1f}%"
            }
        )


if __name__ == '__main__':
    processor = SourceCoverageAuditProcessor()
    processor.run_daily_audit()
```

---

## Example Processor Integration

### File: Example integration with existing processor

```python
"""
Example: Adding source coverage to an existing processor

Shows how to integrate QualityMixin and FallbackSourceMixin
with your existing AnalyticsProcessorBase.
"""

from shared_services.processors.quality_mixin import QualityMixin
from shared_services.processors.fallback_source_mixin import FallbackSourceMixin
from data_processors.analytics.analytics_base import AnalyticsProcessorBase
from shared_services.constants.source_coverage import QualityTier


class PlayerGameSummaryProcessor(
    FallbackSourceMixin,
    QualityMixin,
    AnalyticsProcessorBase  # Your existing base class
):
    """
    Phase 3 processor with source coverage integration.

    Note: AnalyticsProcessorBase already has:
    - self.quality_issues (list)
    - self.source_metadata (dict)
    - self.bq_client
    """

    # ==========================================================================
    # PROCESSOR CONFIG
    # ==========================================================================
    PHASE = 'phase_3'
    OUTPUT_TABLE = 'nba_analytics.player_game_summary'

    # ==========================================================================
    # QUALITY MIXIN CONFIG
    # ==========================================================================
    REQUIRED_FIELDS = ['game_id', 'player_id', 'points', 'minutes_played']
    OPTIONAL_FIELDS = ['plus_minus', 'rebounds', 'assists', 'shot_zones']
    FIELD_WEIGHTS = {
        'points': 10.0,
        'minutes_played': 8.0,
        'plus_minus': 3.0,
        'shot_zones': 5.0
    }

    # ==========================================================================
    # FALLBACK MIXIN CONFIG
    # ==========================================================================
    PRIMARY_SOURCES = ['nbac_gamebook_player_stats']
    FALLBACK_SOURCES = ['bdl_player_boxscores', 'espn_game_boxscore']
    RECONSTRUCTION_ALLOWED = False

    def process_game(self, game_id: str, game_date=None):
        """Process one game with full quality tracking."""

        self.logger.info(f"Processing game {game_id}")

        # 1. Fetch with automatic fallback
        data, sources_tried = self.fetch_with_fallback(
            game_id,
            fetch_functions={
                'nbac_gamebook_player_stats': lambda gid: self.fetch_gamebook(gid),
                'bdl_player_boxscores': lambda gid: self.fetch_bdl(gid),
                'espn_game_boxscore': lambda gid: self.fetch_espn(gid)
            }
        )

        if data is None:
            self.logger.error(f"No data available for {game_id}")
            return None

        # 2. Transform data
        transformed = self.transform_player_stats(data)

        # 3. Assess quality (with season awareness)
        quality = self.assess_quality(
            data=transformed,
            sources_used=sources_tried,
            reconstruction_applied=False,
            game_date=game_date,
            context={'expected_sample_size': 10}
        )

        self.logger.info(f"Quality for {game_id}: {quality['tier']} ({quality['score']:.1f})")

        # 4. Add quality columns to dataframe
        transformed['quality_tier'] = quality['tier']
        transformed['quality_score'] = quality['score']
        transformed['quality_issues'] = [quality['issues']] * len(transformed)
        transformed['data_sources'] = [quality['sources']] * len(transformed)
        transformed['quality_metadata'] = [quality['metadata']] * len(transformed)

        # 5. Load using batch (not streaming)
        self.load_dataframe_batch(
            df=transformed,
            table=self.OUTPUT_TABLE
        )

        return quality

    def fetch_gamebook(self, game_id: str):
        """Fetch from NBA.com gamebook (primary source)"""
        query = f"""
        SELECT * FROM nba_raw.nbac_gamebook_player_stats
        WHERE game_id = '{game_id}'
        """
        return self.bq_client.query(query).to_dataframe()

    def fetch_bdl(self, game_id: str):
        """Fetch from Ball Don't Lie (backup)"""
        query = f"""
        SELECT * FROM nba_raw.bdl_player_boxscores
        WHERE game_id = '{game_id}'
        """
        return self.bq_client.query(query).to_dataframe()

    def fetch_espn(self, game_id: str):
        """Fetch from ESPN (backup)"""
        query = f"""
        SELECT * FROM nba_raw.espn_game_boxscore
        WHERE game_id = '{game_id}'
        """
        return self.bq_client.query(query).to_dataframe()
```

---

## Phase 4: Quality Inheritance Example

**Critical concept:** Phase 4 tables aggregate Phase 3 data. Quality must be inherited using "worst wins" rule.

### File: Example Phase 4 processor with quality inheritance

```python
"""
Example: Phase 4 processor that inherits quality from Phase 3

Key principle: Quality can only stay same or degrade, never improve.
If you aggregate 10 games where 9 are gold and 1 is silver, result is silver.

WARNING - Reprocessing Cascade:
If you backfill/reprocess Phase 3 data, downstream Phase 4 quality becomes STALE.
Use quality_calculated_at to detect staleness and trigger reprocessing.
"""

from datetime import date, datetime
from typing import Dict, Optional
from shared_services.processors.quality_mixin import QualityMixin
from shared_services.utils.source_coverage_utils import aggregate_quality_tiers
from shared_services.constants.source_coverage import (
    SourceCoverageEventType,
    SourceCoverageSeverity
)


class PlayerRollingAverageProcessor(QualityMixin):
    """
    Phase 4 processor: Calculate 10-game rolling averages.
    Inherits quality from underlying Phase 3 player_game_summary rows.
    """

    PHASE = 'phase_4'
    OUTPUT_TABLE = 'nba_precompute.player_rolling_averages'

    def calculate_rolling_average(self, player_id: str, game_date: date) -> Optional[Dict]:
        """
        Calculate rolling average with inherited quality.

        The resulting quality is the WORST quality of all input games.
        """

        # 1. Fetch last 10 games WITH their quality columns
        query = f"""
            SELECT
                points,
                rebounds,
                assists,
                quality_tier,
                quality_score,
                quality_issues,
                quality_calculated_at
            FROM nba_analytics.player_game_summary
            WHERE player_id = '{player_id}'
              AND game_date < '{game_date}'
            ORDER BY game_date DESC
            LIMIT 10
        """

        games = self.bq_client.query(query).to_dataframe()

        if games.empty:
            return None

        # 2. Calculate the statistics
        stats = {
            'player_id': player_id,
            'game_date': game_date,
            'avg_points': games['points'].mean(),
            'avg_rebounds': games['rebounds'].mean(),
            'avg_assists': games['assists'].mean(),
            'games_in_sample': len(games),
        }

        # 3. INHERIT QUALITY: Worst tier wins
        # This is the critical part - quality degrades through aggregation
        input_tiers = games['quality_tier'].tolist()
        stats['quality_tier'] = aggregate_quality_tiers(input_tiers)

        # Worst score wins (minimum)
        stats['quality_score'] = games['quality_score'].min()

        # Combine all issues from input games
        all_issues = []
        for issues in games['quality_issues']:
            if issues:
                all_issues.extend(issues)
        stats['quality_issues'] = list(set(all_issues))  # Dedupe

        # Track what went into this calculation
        stats['quality_sample_size'] = len(games)
        stats['quality_calculated_at'] = datetime.utcnow()
        stats['quality_metadata'] = {
            'input_tiers': input_tiers,
            'input_scores': games['quality_score'].tolist(),
            'aggregation_method': 'worst_wins'
        }

        return stats

    def process_player(self, player_id: str, game_date: date):
        """Process one player's rolling average."""

        stats = self.calculate_rolling_average(player_id, game_date)

        if stats is None:
            self.log_quality_event(
                event_type=SourceCoverageEventType.INSUFFICIENT_SAMPLE,
                severity=SourceCoverageSeverity.WARNING,
                description=f"No games found for {player_id} before {game_date}",
                player_id=player_id,
                game_date=game_date
            )
            return

        # Load to BigQuery
        self.load_row(stats)

        # Don't forget to flush events at end of processor run!
        # self.flush_events()  # Called in main process() method
```

---

## Phase 5: Prediction Confidence Capping

**Core feature:** Predictions must respect quality tier ceilings.

### File: Example prediction confidence capping

```python
"""
Prediction Confidence Capping

Quality tier sets maximum confidence level.
A silver-quality input cannot produce gold-confidence output.
"""

from datetime import datetime
from typing import Dict, Optional

from shared_services.processors.quality_mixin import QualityMixin
from shared_services.constants.source_coverage import (
    SourceCoverageEventType,
    SourceCoverageSeverity
)

# Quality tier confidence ceilings
QUALITY_CONFIDENCE_CEILING = {
    'gold': 1.00,      # 100% - Full confidence allowed
    'silver': 0.95,    # 95% - Slight penalty for backup sources
    'bronze': 0.80,    # 80% - Significant penalty for thin samples
    'poor': 0.60,      # 60% - Strong warning, limited confidence
    'unusable': 0.00,  # 0% - Cannot generate prediction
}


class PredictionGenerator(QualityMixin):
    """Generate predictions with quality-aware confidence capping."""

    def generate_prediction(
        self,
        player_id: str,
        game_id: str,
        features: Dict
    ) -> Optional[Dict]:
        """
        Generate prediction with confidence capped by quality tier.

        Args:
            player_id: Universal player ID
            game_id: Game ID for prediction
            features: Feature dictionary including quality_tier

        Returns:
            Prediction dict or None if quality is unusable
        """

        quality_tier = features.get('quality_tier', 'bronze')

        # GATE: Skip prediction if quality is unusable
        if quality_tier == 'unusable':
            self.log_quality_event(
                event_type=SourceCoverageEventType.QUALITY_DEGRADATION,
                severity=SourceCoverageSeverity.WARNING,
                description=f"Prediction skipped due to unusable quality tier",
                player_id=player_id,
                game_id=game_id,
                downstream_impact='prediction_skipped'
            )
            return None

        # Generate base prediction from model
        base_confidence = self.model.predict_proba(features)
        predicted_value = self.model.predict(features)

        # CAP confidence by quality tier
        max_confidence = QUALITY_CONFIDENCE_CEILING.get(quality_tier, 0.60)
        final_confidence = min(base_confidence, max_confidence)

        # Build prediction response
        prediction = {
            'player_id': player_id,
            'game_id': game_id,
            'predicted_points': predicted_value,
            'base_confidence': base_confidence,
            'final_confidence': final_confidence,
            'confidence_capped': base_confidence > max_confidence,

            # Include quality info for API consumers
            'quality_tier': quality_tier,
            'quality_score': features.get('quality_score'),
            'quality_issues': features.get('quality_issues', []),

            # Metadata
            'prediction_timestamp': datetime.utcnow().isoformat(),
            'model_version': self.model_version,
        }

        # Log if confidence was capped significantly
        if base_confidence - final_confidence > 0.10:
            self.log_quality_event(
                event_type=SourceCoverageEventType.QUALITY_DEGRADATION,
                severity=SourceCoverageSeverity.INFO,
                description=f"Confidence capped from {base_confidence:.2f} to {final_confidence:.2f} due to {quality_tier} quality",
                player_id=player_id,
                game_id=game_id,
                quality_after={'tier': quality_tier, 'score': features.get('quality_score')}
            )

        return prediction


# API Response should include quality info for consumers
# Example API response:
#
# {
#     "player": "LeBron James",
#     "predicted_points": 27.5,
#     "confidence": 0.85,
#     "quality_tier": "silver",
#     "quality_issues": ["backup_source_used"],
#     "confidence_capped": true,
#     "note": "Confidence reduced from 0.92 due to silver-tier data quality"
# }
```

---

## Utility Functions

### File: `/shared_services/utils/source_coverage_utils.py`

```python
"""
Source Coverage Utility Functions
"""

from typing import List


def aggregate_quality_tiers(tiers: List[str]) -> str:
    """
    Determine overall quality tier from multiple input tiers.
    Worst quality wins.
    """
    tier_rank = {
        'unusable': 0,
        'poor': 1,
        'bronze': 2,
        'silver': 3,
        'gold': 4
    }

    worst_rank = min(tier_rank.get(t, 0) for t in tiers)

    for tier, rank in tier_rank.items():
        if rank == worst_rank:
            return tier

    return 'unusable'


def calculate_weighted_quality_score(
    scores: List[float],
    weights: List[float] = None
) -> float:
    """Calculate weighted average quality score."""
    if not scores:
        return 0.0

    if weights is None:
        weights = [1.0] * len(scores)

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.0

    weighted_sum = sum(s * w for s, w in zip(scores, weights))
    return weighted_sum / total_weight


def format_quality_issues(issues: List[str]) -> str:
    """Format quality issues list into human-readable string."""
    if not issues:
        return "No issues"

    expansions = {
        'missing_optional': 'Missing optional field',
        'missing_required': 'Missing required field',
        'thin_sample': 'Insufficient sample size',
        'high_null_rate': 'High null rate',
        'backup_source_used': 'Using backup source'
    }

    formatted = []
    for issue in issues:
        parts = issue.split(':', 1)
        prefix = parts[0]
        detail = parts[1] if len(parts) > 1 else ''

        readable = expansions.get(prefix, prefix.replace('_', ' ').title())
        if detail:
            readable += f": {detail}"

        formatted.append(readable)

    return '; '.join(formatted)
```

---

## Summary

This implementation guide provides:

- **Event type constants** - Standardized enums for consistency
- **Quality mixin** - Complete quality scoring with season-aware thresholds
- **Fallback mixin** - Automatic source fallback handling
- **Audit processor** - Silent failure detection
- **Example integration** - Full processor with all features
- **Utility functions** - Common operations

**Key adaptations for this codebase:**
- Uses existing `notify_error/warning/info` functions
- Extends `AnalyticsProcessorBase` which has `quality_issues`, `source_metadata`
- Uses batch loading (`load_table_from_json`) instead of streaming inserts
- Season-aware thresholds to avoid false bronzes early season

**Next:** See [Part 4: Testing & Operations](04-testing-operations.md) for testing strategies and operational procedures.

---

*End of Part 3: Implementation Guide*
