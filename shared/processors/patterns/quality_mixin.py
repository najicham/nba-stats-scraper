"""
Quality Mixin for Source Coverage System

Provides quality assessment, event logging, and alert deduplication
for analytics processors.

Usage:
    class MyProcessor(QualityMixin, AnalyticsProcessorBase):
        REQUIRED_FIELDS = ['points', 'minutes']
        OPTIONAL_FIELDS = ['plus_minus']

        def process(self):
            with self:  # Auto-flush on exit
                data = self.fetch_data()
                quality = self.assess_quality(data, sources_used=['primary'])
                self.load_with_quality(data, quality)

Version: 1.0
Created: 2025-11-26
"""

import json
import logging
import uuid
import tempfile
import os
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any

import pandas as pd
from google.cloud import bigquery

from shared.utils.notification_system import notify_error, notify_warning, notify_info
from shared.config.source_coverage import (
    QualityTier,
    SourceCoverageEventType,
    SourceCoverageSeverity,
    TIER_RANK,
    QUALITY_THRESHOLDS,
    SAMPLE_THRESHOLDS,
    get_tier_from_score,
    format_quality_issue,
)

logger = logging.getLogger(__name__)


class QualityMixin:
    """
    Mixin providing quality assessment and logging capabilities.

    IMPORTANT - Mixin Resolution Order (MRO):
    Python uses left-to-right MRO. Your class declaration order matters:

        # CORRECT ORDER:
        class MyProcessor(FallbackSourceMixin, QualityMixin, AnalyticsProcessorBase):
            pass

        # Mixins come BEFORE base class

    Features:
    - Season-aware quality thresholds
    - Event buffering (prevents 13+ BQ load jobs per game)
    - Alert deduplication (buffer + DB check)
    - Context manager for auto-flush
    """

    # ==========================================================================
    # CONFIGURATION (Subclasses can override)
    # ==========================================================================
    REQUIRED_FIELDS: List[str] = []
    OPTIONAL_FIELDS: List[str] = []
    FIELD_WEIGHTS: Dict[str, float] = {}
    PHASE: str = 'phase_3'
    OUTPUT_TABLE: str = ''

    # ==========================================================================
    # EVENT BUFFERING
    # ==========================================================================
    _event_buffer: List[Dict] = []

    # ==========================================================================
    # CONTEXT MANAGER - Auto-flush on exit
    # ==========================================================================
    def __enter__(self):
        """Enable context manager usage for auto-flush."""
        self._event_buffer = []
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Auto-flush events when exiting context, even on exception."""
        try:
            self.flush_events()
        except Exception as e:
            logger.error(f"Failed to flush events on exit: {e}")
        return False  # Don't suppress exceptions

    # ==========================================================================
    # QUALITY ASSESSMENT
    # ==========================================================================
    def assess_quality(
        self,
        data: pd.DataFrame,
        sources_used: List[str],
        reconstruction_applied: bool = False,
        game_date: date = None,
        context: Dict = None
    ) -> Dict:
        """
        Assess quality of data and return quality metrics.

        Args:
            data: DataFrame to assess
            sources_used: List of source names used
            reconstruction_applied: Whether reconstruction was used
            game_date: Game date for season-aware thresholds
            context: Additional context (expected_sample_size, etc.)

        Returns:
            Dict with tier, score, issues, metadata
        """
        context = context or {}
        issues = []
        score = 100.0
        metadata = {
            'sample_size': len(data),
            'sources_used': sources_used,
            'reconstruction_applied': reconstruction_applied,
            'assessment_timestamp': datetime.utcnow().isoformat(),
        }

        # Check for missing required fields
        for field in self.REQUIRED_FIELDS:
            if field not in data.columns:
                issues.append(format_quality_issue('missing_required', field))
                score = 0.0  # Unusable if missing required
                return {
                    'tier': QualityTier.UNUSABLE.value,
                    'score': score,
                    'issues': issues,
                    'metadata': metadata,
                }

        # Check for missing optional fields
        for field in self.OPTIONAL_FIELDS:
            if field not in data.columns:
                issues.append(format_quality_issue('missing_optional', field))
                weight = self.FIELD_WEIGHTS.get(field, 2.0)
                score -= weight

        # Check null rates in columns
        for col in data.columns:
            null_rate = data[col].isnull().mean()
            if null_rate > 0.5:
                issues.append(format_quality_issue('high_null_rate', f'{col}:{null_rate:.0%}'))
                score -= 10.0

        # Check sample size with season-aware thresholds
        expected_sample = context.get('expected_sample_size', 10)
        actual_sample = len(data)
        early_season = self._is_early_season(game_date)
        metadata['early_season'] = early_season

        if early_season:
            min_sample = SAMPLE_THRESHOLDS['early_season']
        else:
            min_sample = SAMPLE_THRESHOLDS['full_season']

        if actual_sample < min_sample:
            issues.append(format_quality_issue('thin_sample', f'{actual_sample}/{expected_sample}'))
            if not early_season:
                score -= 15.0

        # Check if backup sources were used
        primary_sources = ['primary', 'nbac_', 'nba_raw.nbac']
        used_backup = not any(
            any(p in s for p in primary_sources)
            for s in sources_used
        )
        if used_backup:
            issues.append('backup_source_used')
            score -= 5.0

        # Check if reconstruction was applied
        if reconstruction_applied:
            issues.append('reconstructed')
            score -= 10.0

        # Clamp score
        score = max(0.0, min(100.0, score))

        # Determine tier
        tier = self._determine_tier(
            score=score,
            issues=issues,
            reconstruction_applied=reconstruction_applied
        )

        return {
            'tier': tier.value if isinstance(tier, QualityTier) else tier,
            'score': score,
            'issues': issues,
            'metadata': metadata,
        }

    def _is_early_season(self, game_date: date = None) -> bool:
        """Check if date is in early season (first ~2 weeks)."""
        if game_date is None:
            return False

        # NBA season typically starts late October
        season_starts = {
            2024: date(2024, 10, 22),
            2025: date(2025, 10, 21),
        }
        year = game_date.year if game_date.month >= 10 else game_date.year - 1
        season_start = season_starts.get(year, date(year, 10, 22))

        days_into_season = (game_date - season_start).days
        return 0 <= days_into_season <= 14

    def _determine_tier(
        self,
        score: float,
        issues: List[str],
        reconstruction_applied: bool
    ) -> QualityTier:
        """Determine quality tier from score and issues."""
        # Start with score-based tier
        tier = get_tier_from_score(score)

        # Reconstruction caps at silver
        if reconstruction_applied and tier == QualityTier.GOLD:
            tier = QualityTier.SILVER

        # Missing required = unusable
        if any('missing_required' in i for i in issues):
            tier = QualityTier.UNUSABLE

        return tier

    # ==========================================================================
    # EVENT LOGGING
    # ==========================================================================
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
        Log a source coverage event to the buffer.

        Events are buffered to avoid many separate BigQuery load jobs.
        Call flush_events() at the end of your processor run, or use
        context manager for auto-flush.

        Returns:
            event_id (UUID)
        """
        event_id = str(uuid.uuid4())

        event_data = {
            'event_id': event_id,
            'event_timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type if isinstance(event_type, str) else event_type.value,
            'severity': severity if isinstance(severity, str) else severity.value,
            'phase': getattr(self, 'PHASE', 'unknown'),
            'table_name': getattr(self, 'OUTPUT_TABLE', getattr(self, 'table_name', 'unknown')),
            'processor_name': self.__class__.__name__,
            'game_id': game_id,
            'game_date': str(kwargs.get('game_date')) if kwargs.get('game_date') else None,
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
            'requires_alert': severity in [SourceCoverageSeverity.CRITICAL.value,
                                          SourceCoverageSeverity.WARNING.value,
                                          'critical', 'warning'],
            'alert_sent': False,
            'batch_id': kwargs.get('batch_id'),
            'environment': os.environ.get('ENVIRONMENT', 'prod'),
            'processor_run_id': getattr(self, 'run_id', None),
            'is_synthetic': False,
        }

        # Buffer the event
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

        Call at the end of every processor run, or use context manager.
        """
        if not self._event_buffer:
            return

        try:
            self._insert_quality_events_batch(self._event_buffer)
            logger.info(f"Flushed {len(self._event_buffer)} quality events to BigQuery")
        except Exception as e:
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
        if not events:
            return

        # Get BigQuery client
        bq_client = getattr(self, 'bq_client', None)
        if bq_client is None:
            bq_client = bigquery.Client()

        # Write to temp file as NDJSON
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            for event in events:
                f.write(json.dumps(event) + '\n')
            temp_path = f.name

        try:
            job_config = bigquery.LoadJobConfig(
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            )

            with open(temp_path, 'rb') as f:
                load_job = bq_client.load_table_from_file(
                    f,
                    'nba_reference.source_coverage_log',
                    job_config=job_config
                )
            load_job.result()
        finally:
            os.unlink(temp_path)

    def _should_send_alert(self, event_data: Dict) -> bool:
        """
        Check if we should send an alert, with deduplication.

        Checks BOTH the buffer AND the database to prevent duplicates.
        """
        event_type = event_data.get('event_type', '')
        primary_source = event_data.get('primary_source', '')

        # 1. Check buffer first (events not yet in database)
        for buffered in self._event_buffer:
            if (buffered.get('event_type') == event_type and
                buffered.get('primary_source') == primary_source and
                buffered.get('alert_sent', False)):
                logger.debug("Alert suppressed: already alerted in current batch")
                return False

        # 2. Then check database for recent alerts
        try:
            bq_client = getattr(self, 'bq_client', None)
            if bq_client is None:
                bq_client = bigquery.Client()

            query = f"""
                SELECT COUNT(*) as recent_alerts
                FROM nba_reference.source_coverage_log
                WHERE event_type = '{event_type}'
                  AND COALESCE(primary_source, '') = '{primary_source}'
                  AND alert_sent = TRUE
                  AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 4 HOUR)
            """
            result = bq_client.query(query).to_dataframe()
            return result.iloc[0]['recent_alerts'] == 0
        except Exception as e:
            logger.warning(f"Alert dedup check failed: {e}, sending alert anyway")
            return True

    def _send_alert(self, event_data: Dict):
        """Send alert using existing notification system."""
        severity = event_data.get('severity', 'info')

        if severity in ['critical', SourceCoverageSeverity.CRITICAL.value]:
            notify_error(
                title=f"Source Coverage: {event_data['event_type']}",
                message=event_data.get('description', ''),
                details={
                    'game_id': event_data.get('game_id'),
                    'event_id': event_data['event_id'],
                    'processor': event_data.get('processor_name'),
                },
                processor_name=event_data.get('processor_name', 'SourceCoverage')
            )
        elif severity in ['warning', SourceCoverageSeverity.WARNING.value]:
            notify_warning(
                title=f"Source Coverage: {event_data['event_type']}",
                message=event_data.get('description', ''),
                details={
                    'game_id': event_data.get('game_id'),
                    'event_id': event_data['event_id'],
                }
            )

    # ==========================================================================
    # QUALITY DEGRADATION DETECTION
    # ==========================================================================
    def check_quality_degradation(
        self,
        current_quality: Dict,
        game_date: date = None
    ) -> bool:
        """
        Check if quality has degraded from previous runs and send alert if so.

        Args:
            current_quality: Current quality assessment dict
            game_date: Date being processed

        Returns:
            True if degradation was detected and alert sent
        """
        try:
            previous_quality = self._get_previous_quality(game_date)
            if previous_quality is None:
                return False

            current_tier = current_quality.get('tier', 'UNKNOWN')
            previous_tier = previous_quality.get('tier', 'UNKNOWN')

            # Check if degraded
            tier_order = ['UNUSABLE', 'BRONZE', 'SILVER', 'GOLD']
            try:
                curr_idx = tier_order.index(current_tier)
                prev_idx = tier_order.index(previous_tier)
            except ValueError:
                return False

            if curr_idx < prev_idx:  # Quality decreased
                self._send_quality_degradation_alert(
                    current_quality=current_quality,
                    previous_quality=previous_quality,
                    game_date=game_date
                )
                return True

            return False

        except Exception as e:
            logger.warning(f"Error checking quality degradation: {e}")
            return False

    def _get_previous_quality(self, game_date: date = None) -> Optional[Dict]:
        """Get previous quality tier for comparison."""
        try:
            bq_client = getattr(self, 'bq_client', None)
            if bq_client is None:
                bq_client = bigquery.Client()

            # Query most recent quality for this processor
            processor_name = self.__class__.__name__
            date_filter = f"AND data_date = '{game_date}'" if game_date else ""

            query = f"""
                SELECT quality_tier, quality_score
                FROM nba_reference.processor_run_history
                WHERE processor_name = '{processor_name}'
                  {date_filter}
                  AND quality_tier IS NOT NULL
                ORDER BY processed_at DESC
                LIMIT 1
            """

            result = list(bq_client.query(query).result())
            if result:
                row = result[0]
                return {
                    'tier': row.quality_tier,
                    'score': row.quality_score
                }
            return None

        except Exception as e:
            logger.debug(f"Could not get previous quality: {e}")
            return None

    def _send_quality_degradation_alert(
        self,
        current_quality: Dict,
        previous_quality: Dict,
        game_date: date = None
    ):
        """Send email alert for quality degradation."""
        try:
            from shared.utils.email_alerting_ses import EmailAlerterSES

            # Determine reason for degradation
            issues = current_quality.get('issues', [])
            if 'reconstructed' in issues:
                reason = "Reconstruction was applied due to missing primary source data"
            elif 'backup_source_used' in issues:
                reason = "Backup/fallback data source was used"
            elif any('thin_sample' in str(i) for i in issues):
                reason = "Insufficient sample size for reliable analysis"
            else:
                reason = f"Quality issues detected: {', '.join(issues[:3])}"

            # Determine fallback sources
            metadata = current_quality.get('metadata', {})
            fallback_sources = metadata.get('sources_used', [])

            # Build alert data
            quality_data = {
                'processor_name': self.__class__.__name__,
                'date': str(game_date) if game_date else datetime.now().strftime('%Y-%m-%d'),
                'previous_quality': previous_quality.get('tier', 'UNKNOWN'),
                'current_quality': current_quality.get('tier', 'UNKNOWN'),
                'reason': reason,
                'fallback_sources': fallback_sources,
                'impact': 'Prediction confidence may be reduced. Consider reviewing data sources.'
            }

            alerter = EmailAlerterSES()
            success = alerter.send_data_quality_alert(quality_data)

            if success:
                logger.info(f"📉 Quality degradation alert sent for {self.__class__.__name__}")
            else:
                logger.warning("Failed to send quality degradation alert")

        except ImportError as e:
            logger.warning(f"Email alerter not available: {e}")
        except Exception as e:
            logger.error(f"Error sending quality degradation alert: {e}")

    # ==========================================================================
    # HELPER METHODS
    # ==========================================================================
    def build_quality_columns(self, quality: Dict) -> Dict:
        """
        Build quality columns dict for inserting into BigQuery.

        Use this when preparing rows for insertion.
        """
        return {
            'quality_tier': quality.get('tier'),
            'quality_score': quality.get('score'),
            'quality_issues': quality.get('issues', []),
            'data_sources': quality.get('metadata', {}).get('sources_used', []),
            'quality_sample_size': quality.get('metadata', {}).get('sample_size'),
            'quality_used_fallback': 'backup_source_used' in quality.get('issues', []),
            'quality_reconstructed': quality.get('metadata', {}).get('reconstruction_applied', False),
            'quality_calculated_at': datetime.utcnow().isoformat(),
            'quality_metadata': json.dumps(quality.get('metadata', {})),
        }
