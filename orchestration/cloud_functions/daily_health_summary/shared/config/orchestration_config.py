"""
Orchestration Configuration

Centralized configuration for pipeline orchestration settings.
These can be overridden via environment variables.

Version: 1.0
Created: 2025-12-02
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class PhaseTransitionConfig:
    """Configuration for phase transition orchestration."""

    # Phase 2 -> Phase 3: List of expected processors
    # NOTE: Phase 2->3 orchestrator is now monitoring-only. Phase 3 is triggered
    # directly via Pub/Sub subscription (nba-phase3-analytics-sub).
    # This list is used for tracking completeness in Firestore.
    phase2_expected_processors: List[str] = field(default_factory=lambda: [
        # Core daily processors that reliably publish completion messages
        'bdl_player_boxscores',       # Daily box scores from balldontlie
        'bigdataball_play_by_play',   # Per-game play-by-play
        'odds_api_game_lines',        # Per-game odds
        'nbac_schedule',              # Schedule updates
        'nbac_gamebook_player_stats', # Post-game player stats
        'br_rosters_current',         # Basketball-ref rosters
    ])

    # Phase 3 -> Phase 4: List of expected processors
    phase3_expected_processors: List[str] = field(default_factory=lambda: [
        'player_game_summary',
        'team_defense_game_summary',
        'team_offense_game_summary',
        'upcoming_player_game_context',
        'upcoming_team_game_context',
    ])

    # Phase 4 -> Phase 5: List of expected processors
    phase4_expected_processors: List[str] = field(default_factory=lambda: [
        'team_defense_zone_analysis',
        'player_shot_zone_analysis',
        'player_composite_factors',
        'player_daily_cache',
        'ml_feature_store',
    ])

    # Trigger mode: 'all_complete' or 'majority' (>80%)
    trigger_mode: str = 'all_complete'


@dataclass
class ScheduleStalenessConfig:
    """Configuration for schedule staleness handling."""

    # Maximum hours before schedule is considered stale
    max_stale_hours: int = 6

    # Manual override (can be set when NBA.com is down)
    # Set via env var: SCHEDULE_STALENESS_OVERRIDE_HOURS
    override_hours: Optional[int] = None

    # Override expiration (ISO format)
    # Set via env var: SCHEDULE_STALENESS_OVERRIDE_EXPIRES
    override_expires_at: Optional[datetime] = None

    def get_effective_max_hours(self) -> int:
        """Get the effective max stale hours, considering overrides."""
        if self.override_hours is not None:
            # Check if override has expired
            if self.override_expires_at is not None:
                if datetime.utcnow() > self.override_expires_at:
                    return self.max_stale_hours  # Override expired
            return self.override_hours
        return self.max_stale_hours


@dataclass
class PredictionModeConfig:
    """Configuration for prediction system behavior."""

    # Mode: 'strict' or 'fallback'
    # strict: Skip players without production-ready data
    # fallback: Make predictions with quality degradation flag
    mode: str = 'strict'

    # When in fallback mode, mark predictions for re-run
    fallback_rerun_enabled: bool = True

    # Quality degradation multiplier for fallback predictions
    fallback_quality_multiplier: float = 0.7

    # Use multiple lines by default (pre-compute line ranges)
    use_multiple_lines_default: bool = True

    # Line range for multiple lines (±N points from base)
    line_range_points: float = 2.0

    # Line increment for multiple lines
    line_increment: float = 1.0


@dataclass
class ProcessingModeConfig:
    """Configuration for daily vs backfill processing modes."""

    # Processing mode: 'daily' or 'backfill'
    # daily: Use schedule + roster (pre-game data)
    # backfill: Use gamebook (post-game data with actual players)
    mode: str = 'daily'

    # Roster staleness threshold (hours) for daily mode
    roster_max_stale_hours: int = 24

    # For daily mode: Skip players not in current roster
    daily_roster_strict: bool = True


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker behavior."""

    # Entity-level circuit breaker lockout duration
    # When a player/team fails processing multiple times, lock them out for this long
    # Default: 24 hours (was 7 days - too aggressive, caused cascading failures)
    entity_lockout_hours: int = 24

    # Maximum consecutive failures before entity is locked out
    entity_failure_threshold: int = 5

    # Auto-reset: Clear circuit breaker if data becomes available
    auto_reset_on_data: bool = True

    # Processor-level circuit breaker timeout (minutes)
    # How long a processor stays in "open" state after failures
    processor_timeout_minutes: int = 30

    # Processor failure threshold
    processor_failure_threshold: int = 5


@dataclass
class WorkerConcurrencyConfig:
    """Configuration for prediction worker concurrency.

    BigQuery has a limit of 20 concurrent DML operations per table.
    Our workers write to predictions table via MERGE, which counts as DML.

    With staging pattern: Workers write to staging (INSERT=no limit),
    coordinator does single MERGE (1 DML).

    Without staging pattern (legacy): Must limit total concurrent workers.
    """

    # Maximum Cloud Run instances
    # Via env: WORKER_MAX_INSTANCES
    # Reduced from 20 to 10 (Dec 31, 2025) - 50% reduction for 40% cost savings
    # 10 instances × 5 concurrency = 50 workers (sufficient for ~450 players/day)
    max_instances: int = 10

    # Concurrent requests per instance
    # Via env: WORKER_CONCURRENCY
    concurrency_per_instance: int = 5

    # Emergency mode: reduce concurrency when DML errors occur
    # Via env: WORKER_EMERGENCY_MODE
    emergency_mode_enabled: bool = False

    # Emergency mode settings (4×3=12 < 20 DML limit)
    emergency_max_instances: int = 4
    emergency_concurrency: int = 3

    def get_effective_max_instances(self) -> int:
        """Get current max instances (considers emergency mode)."""
        if self.emergency_mode_enabled:
            return self.emergency_max_instances
        return self.max_instances

    def get_effective_concurrency(self) -> int:
        """Get current concurrency per instance."""
        if self.emergency_mode_enabled:
            return self.emergency_concurrency
        return self.concurrency_per_instance


@dataclass
class SelfHealingConfig:
    """Configuration for self-healing behaviors."""

    # DML Rate Limit Handling
    # Via env: SELF_HEALING_DML_BACKOFF_ENABLED
    dml_backoff_enabled: bool = True

    # Via env: SELF_HEALING_DML_MAX_RETRIES
    dml_max_retries: int = 3

    # Base backoff in seconds (doubles each retry)
    dml_base_backoff_seconds: float = 5.0

    # Max backoff in seconds
    dml_max_backoff_seconds: float = 120.0

    # Alert on DML rate limit
    # Via env: SELF_HEALING_ALERT_ON_DML_LIMIT
    alert_on_dml_limit: bool = True

    # Auto-reduce concurrency on repeated DML errors
    # Via env: SELF_HEALING_AUTO_REDUCE_CONCURRENCY
    auto_reduce_concurrency: bool = True

    # Threshold: number of DML errors in window to trigger concurrency reduction
    dml_error_threshold: int = 5
    dml_error_window_seconds: int = 60

    # Coverage threshold alerts
    coverage_warning_threshold: float = 95.0
    coverage_critical_threshold: float = 85.0


@dataclass
class NewPlayerConfig:
    """Configuration for handling new players (rookies, traded players)."""

    # Minimum games required before making predictions
    min_games_required: int = 3

    # Bootstrap period (days) - matches BOOTSTRAP_DAYS
    bootstrap_days: int = 14

    # Use default line for new players (False = skip prediction)
    use_default_line: bool = False

    # Default line value if use_default_line is True
    default_line_value: float = 15.5

    # Mark new players for later processing
    mark_needs_bootstrap: bool = True


@dataclass
class WorkflowExecutionConfig:
    """
    Week 1: Configuration for workflow execution behavior.

    Makes parallel execution configurable per workflow instead of hardcoded.
    """

    # Workflows that should run in parallel
    # Via env: PARALLEL_WORKFLOWS (comma-separated)
    parallel_workflows: List[str] = field(default_factory=lambda: ['morning_operations'])

    # Max workers for parallel execution
    # Via env: WORKFLOW_MAX_WORKERS
    max_workers: int = 10

    # Execution timeout (seconds)
    # Via env: WORKFLOW_EXECUTION_TIMEOUT
    execution_timeout: int = 600  # 10 minutes

    def is_parallel(self, workflow_name: str) -> bool:
        """Check if workflow should run in parallel."""
        return workflow_name in self.parallel_workflows


@dataclass
class OrchestrationConfig:
    """Main orchestration configuration."""

    phase_transitions: PhaseTransitionConfig = field(default_factory=PhaseTransitionConfig)
    schedule_staleness: ScheduleStalenessConfig = field(default_factory=ScheduleStalenessConfig)
    prediction_mode: PredictionModeConfig = field(default_factory=PredictionModeConfig)
    processing_mode: ProcessingModeConfig = field(default_factory=ProcessingModeConfig)
    new_player: NewPlayerConfig = field(default_factory=NewPlayerConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    worker_concurrency: WorkerConcurrencyConfig = field(default_factory=WorkerConcurrencyConfig)
    self_healing: SelfHealingConfig = field(default_factory=SelfHealingConfig)
    workflow_execution: WorkflowExecutionConfig = field(default_factory=WorkflowExecutionConfig)

    @classmethod
    def from_environment(cls) -> 'OrchestrationConfig':
        """Create config from environment variables."""
        config = cls()

        # Schedule staleness overrides
        override_hours = os.environ.get('SCHEDULE_STALENESS_OVERRIDE_HOURS')
        if override_hours:
            config.schedule_staleness.override_hours = int(override_hours)

        override_expires = os.environ.get('SCHEDULE_STALENESS_OVERRIDE_EXPIRES')
        if override_expires:
            config.schedule_staleness.override_expires_at = datetime.fromisoformat(override_expires)

        # Prediction mode
        pred_mode = os.environ.get('PREDICTION_MODE')
        if pred_mode in ('strict', 'fallback'):
            config.prediction_mode.mode = pred_mode

        # Processing mode
        proc_mode = os.environ.get('PROCESSING_MODE')
        if proc_mode in ('daily', 'backfill'):
            config.processing_mode.mode = proc_mode

        # Multiple lines default
        use_multiple = os.environ.get('USE_MULTIPLE_LINES_DEFAULT')
        if use_multiple is not None:
            config.prediction_mode.use_multiple_lines_default = use_multiple.lower() == 'true'

        # Circuit breaker config
        entity_lockout = os.environ.get('CIRCUIT_BREAKER_ENTITY_LOCKOUT_HOURS')
        if entity_lockout:
            config.circuit_breaker.entity_lockout_hours = int(entity_lockout)

        auto_reset = os.environ.get('CIRCUIT_BREAKER_AUTO_RESET')
        if auto_reset is not None:
            config.circuit_breaker.auto_reset_on_data = auto_reset.lower() == 'true'

        # Worker concurrency config
        max_instances = os.environ.get('WORKER_MAX_INSTANCES')
        if max_instances:
            config.worker_concurrency.max_instances = int(max_instances)

        concurrency = os.environ.get('WORKER_CONCURRENCY')
        if concurrency:
            config.worker_concurrency.concurrency_per_instance = int(concurrency)

        emergency_mode = os.environ.get('WORKER_EMERGENCY_MODE')
        if emergency_mode is not None:
            config.worker_concurrency.emergency_mode_enabled = emergency_mode.lower() == 'true'

        # Self-healing config
        dml_backoff = os.environ.get('SELF_HEALING_DML_BACKOFF_ENABLED')
        if dml_backoff is not None:
            config.self_healing.dml_backoff_enabled = dml_backoff.lower() == 'true'

        dml_max_retries = os.environ.get('SELF_HEALING_DML_MAX_RETRIES')
        if dml_max_retries:
            config.self_healing.dml_max_retries = int(dml_max_retries)

        alert_on_dml = os.environ.get('SELF_HEALING_ALERT_ON_DML_LIMIT')
        if alert_on_dml is not None:
            config.self_healing.alert_on_dml_limit = alert_on_dml.lower() == 'true'

        auto_reduce = os.environ.get('SELF_HEALING_AUTO_REDUCE_CONCURRENCY')
        if auto_reduce is not None:
            config.self_healing.auto_reduce_concurrency = auto_reduce.lower() == 'true'

        # Week 1: Workflow execution config
        parallel_workflows = os.environ.get('PARALLEL_WORKFLOWS')
        if parallel_workflows:
            config.workflow_execution.parallel_workflows = [w.strip() for w in parallel_workflows.split(',')]

        max_workers = os.environ.get('WORKFLOW_MAX_WORKERS')
        if max_workers:
            config.workflow_execution.max_workers = int(max_workers)

        exec_timeout = os.environ.get('WORKFLOW_EXECUTION_TIMEOUT')
        if exec_timeout:
            config.workflow_execution.execution_timeout = int(exec_timeout)

        return config


# Singleton instance
_config: Optional[OrchestrationConfig] = None


def get_orchestration_config() -> OrchestrationConfig:
    """Get the orchestration configuration (singleton)."""
    global _config
    if _config is None:
        _config = OrchestrationConfig.from_environment()
    return _config


def reload_orchestration_config() -> OrchestrationConfig:
    """Reload configuration from environment."""
    global _config
    _config = OrchestrationConfig.from_environment()
    return _config
