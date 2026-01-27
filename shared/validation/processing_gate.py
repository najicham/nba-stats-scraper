"""
Processing Gate for Data Lineage Integrity
===========================================

Unified gate that decides whether to proceed with processing based on
completeness checks and upstream dependency status.

Prevents cascade contamination by verifying data completeness before
computing downstream values.

Usage:
    gate = ProcessingGate(bq_client, project_id)

    result = gate.check_can_process(
        processor_name='PlayerCompositeFactorsProcessor',
        game_date=date(2026, 1, 26),
        entity_ids=['lebron_james', 'stephen_curry'],
        window_size=10
    )

    if result.status == GateStatus.FAIL:
        raise ProcessingBlockedError(result.message)

    if result.status == GateStatus.WAIT:
        return  # Will retry later

    # Proceed with processing, attach quality metadata
    for record in output_records:
        record.update(result.quality_metadata)

Created: 2026-01-26
"""

import logging
from datetime import date, datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional

from google.cloud import bigquery
from shared.utils.completeness_checker import CompletenessChecker

logger = logging.getLogger(__name__)


class GateStatus(Enum):
    """Processing gate status values."""
    PROCEED = "proceed"              # All checks passed
    PROCEED_WITH_WARNING = "proceed_warn"  # Minor issues, proceed with flags
    WAIT = "wait"                    # Data not ready, retry later
    FAIL = "fail"                    # Critical issue, cannot proceed


@dataclass
class GateResult:
    """Result from processing gate check."""
    status: GateStatus
    can_proceed: bool
    quality_score: float  # 0-1 scale
    message: str

    # Completeness details
    completeness_pct: float
    expected_count: int
    actual_count: int
    missing_items: List[str] = field(default_factory=list)
    quality_issues: List[str] = field(default_factory=list)

    # For downstream use
    quality_metadata: Dict = field(default_factory=dict)


class ProcessingBlockedError(Exception):
    """Raised when processing gate blocks execution."""
    def __init__(self, message: str, gate_result: Optional[GateResult] = None):
        self.message = message
        self.gate_result = gate_result
        super().__init__(self.message)


class ProcessingGate:
    """
    Unified processing gate for Phase 3+ processors.

    Combines completeness checking with dependency validation to prevent
    cascade contamination from incomplete upstream data.

    Thresholds:
    - min_completeness: 80% - Below this, gate returns FAIL
    - window_completeness_threshold: 70% - Below this, return NULL for windows
    - grace_period_hours: 36 - Wait this long before failing

    Gate Status Logic:
    - completeness >= 100%: PROCEED
    - completeness < 100% and hours_since_game < 36: WAIT (data still arriving)
    - completeness >= 80%: PROCEED_WITH_WARNING
    - completeness < 80%: FAIL
    """

    def __init__(
        self,
        bq_client: bigquery.Client,
        project_id: str,
        min_completeness: float = 0.8,  # 80%
        grace_period_hours: int = 36,
        window_completeness_threshold: float = 0.7  # 70%
    ):
        """
        Initialize processing gate.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID
            min_completeness: Minimum completeness to proceed (0-1 scale)
            grace_period_hours: Hours to wait before failing
            window_completeness_threshold: Minimum for computing windows
        """
        self.bq_client = bq_client
        self.project_id = project_id
        self.min_completeness = min_completeness
        self.grace_period_hours = grace_period_hours
        self.window_completeness_threshold = window_completeness_threshold

        # Initialize completeness checker
        self.completeness_checker = CompletenessChecker(bq_client, project_id)

    def check_can_process(
        self,
        processor_name: str,
        game_date: date,
        entity_ids: List[str],
        window_size: int = 10,
        window_type: str = 'games',
        upstream_table: str = 'nba_analytics.player_game_summary',
        upstream_entity_field: str = 'player_lookup',
        season_start_date: Optional[date] = None,
        allow_override: bool = False
    ) -> GateResult:
        """
        Check if processing can proceed for given entities and date.

        Args:
            processor_name: Name of processor requesting gate check
            game_date: Date being processed
            entity_ids: List of entity IDs (player_lookup or team_abbr)
            window_size: Window size for completeness check
            window_type: 'games' or 'days'
            upstream_table: Upstream table to check
            upstream_entity_field: Entity field in upstream table
            season_start_date: Season start date for completeness check
            allow_override: If True, bypass gate checks

        Returns:
            GateResult with status and quality metadata
        """
        if allow_override:
            logger.info(f"Gate check bypassed for {processor_name} (override=True)")
            return GateResult(
                status=GateStatus.PROCEED,
                can_proceed=True,
                quality_score=1.0,
                message="Gate check bypassed",
                completeness_pct=100.0,
                expected_count=len(entity_ids),
                actual_count=len(entity_ids),
                quality_metadata={
                    'gate_status': 'bypassed',
                    'processing_context': 'override'
                }
            )

        logger.info(
            f"Gate check: {processor_name} for {len(entity_ids)} entities "
            f"on {game_date} (window={window_size} {window_type})"
        )

        # Check completeness for all entities
        try:
            completeness_results = self.completeness_checker.check_completeness_batch(
                entity_ids=entity_ids,
                entity_type='player' if 'player' in upstream_entity_field else 'team',
                analysis_date=game_date,
                upstream_table=upstream_table,
                upstream_entity_field=upstream_entity_field,
                lookback_window=window_size,
                window_type=window_type,
                season_start_date=season_start_date,
                fail_on_incomplete=False,
                dnp_aware=True  # Exclude DNP games from expected count
            )
        except Exception as e:
            logger.error(f"Completeness check failed: {e}", exc_info=True)
            return GateResult(
                status=GateStatus.FAIL,
                can_proceed=False,
                quality_score=0.0,
                message=f"Completeness check error: {str(e)}",
                completeness_pct=0.0,
                expected_count=len(entity_ids),
                actual_count=0,
                quality_issues=[f"check_error: {str(e)}"],
                quality_metadata={
                    'gate_status': 'error',
                    'error_type': type(e).__name__
                }
            )

        # Aggregate completeness metrics
        total_expected = sum(r['expected_count'] for r in completeness_results.values())
        total_actual = sum(r['actual_count'] for r in completeness_results.values())
        avg_completeness_pct = sum(r['completeness_pct'] for r in completeness_results.values()) / len(completeness_results) if completeness_results else 0.0

        incomplete_entities = [
            entity_id for entity_id, result in completeness_results.items()
            if not result['is_complete']
        ]

        # Calculate hours since game (for grace period)
        hours_since_game = (datetime.now() - datetime.combine(game_date, datetime.min.time())).total_seconds() / 3600

        # Determine gate status
        status = self._determine_gate_status(
            completeness_pct=avg_completeness_pct / 100.0,  # Convert to 0-1 scale
            hours_since_game=hours_since_game
        )

        # Build quality issues list
        quality_issues = []
        if incomplete_entities:
            quality_issues.append(f"{len(incomplete_entities)}/{len(entity_ids)} entities incomplete")

        # Calculate quality score (0-1 scale)
        quality_score = avg_completeness_pct / 100.0

        # Build message
        if status == GateStatus.PROCEED:
            message = f"All checks passed ({avg_completeness_pct:.1f}% complete)"
        elif status == GateStatus.PROCEED_WITH_WARNING:
            message = f"Proceeding with warnings ({avg_completeness_pct:.1f}% complete, {len(incomplete_entities)} incomplete)"
        elif status == GateStatus.WAIT:
            message = f"Waiting for data ({avg_completeness_pct:.1f}% complete, {hours_since_game:.1f}h since game)"
        else:  # FAIL
            message = f"Insufficient data ({avg_completeness_pct:.1f}% complete, threshold={self.min_completeness*100:.0f}%)"

        # Build quality metadata for downstream attachment
        quality_metadata = {
            'gate_status': status.value,
            'gate_timestamp': datetime.utcnow().isoformat(),
            'gate_processor': processor_name,
            'quality_score': quality_score,
            'completeness_pct': avg_completeness_pct / 100.0,
            'window_size': window_size,
            'window_type': window_type,
            'processing_context': self._determine_processing_context(game_date, hours_since_game)
        }

        # Log decision
        logger.info(
            f"Gate decision: {status.value} - {message} "
            f"(expected={total_expected}, actual={total_actual})"
        )

        return GateResult(
            status=status,
            can_proceed=status in (GateStatus.PROCEED, GateStatus.PROCEED_WITH_WARNING),
            quality_score=quality_score,
            message=message,
            completeness_pct=avg_completeness_pct,
            expected_count=total_expected,
            actual_count=total_actual,
            missing_items=incomplete_entities,
            quality_issues=quality_issues,
            quality_metadata=quality_metadata
        )

    def _determine_gate_status(
        self,
        completeness_pct: float,  # 0-1 scale
        hours_since_game: float
    ) -> GateStatus:
        """
        Determine gate status based on completeness and time elapsed.

        Logic:
        - 100% complete: PROCEED
        - <100% and within grace period: WAIT
        - >=80%: PROCEED_WITH_WARNING
        - <80%: FAIL

        Args:
            completeness_pct: Completeness percentage (0-1 scale)
            hours_since_game: Hours elapsed since game date

        Returns:
            GateStatus
        """
        if completeness_pct >= 1.0:
            return GateStatus.PROCEED

        if hours_since_game < self.grace_period_hours and completeness_pct < 1.0:
            return GateStatus.WAIT  # Data still arriving

        if completeness_pct >= self.min_completeness:
            return GateStatus.PROCEED_WITH_WARNING

        return GateStatus.FAIL

    def _determine_processing_context(self, game_date: date, hours_since_game: float) -> str:
        """
        Determine processing context based on timing.

        Args:
            game_date: Game date
            hours_since_game: Hours elapsed since game

        Returns:
            Context string: 'daily', 'backfill', 'manual', or 'cascade'
        """
        if hours_since_game < 48:
            return 'daily'
        elif hours_since_game < 168:  # 7 days
            return 'cascade'
        else:
            return 'backfill'

    def check_window_completeness(
        self,
        player_id: str,
        game_date: date,
        window_size: int,
        upstream_table: str = 'nba_analytics.player_game_summary',
        season_start_date: Optional[date] = None
    ) -> GateResult:
        """
        Check single player's window completeness.

        Args:
            player_id: Player lookup ID
            game_date: Date being processed
            window_size: Number of games in window
            upstream_table: Upstream table to check
            season_start_date: Season start date

        Returns:
            GateResult for this specific player/window
        """
        return self.check_can_process(
            processor_name='WindowCheck',
            game_date=game_date,
            entity_ids=[player_id],
            window_size=window_size,
            window_type='games',
            upstream_table=upstream_table,
            upstream_entity_field='player_lookup',
            season_start_date=season_start_date
        )
