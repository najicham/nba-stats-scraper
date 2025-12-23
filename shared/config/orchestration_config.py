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
        'br_roster',                  # Basketball-ref rosters
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
class OrchestrationConfig:
    """Main orchestration configuration."""

    phase_transitions: PhaseTransitionConfig = field(default_factory=PhaseTransitionConfig)
    schedule_staleness: ScheduleStalenessConfig = field(default_factory=ScheduleStalenessConfig)
    prediction_mode: PredictionModeConfig = field(default_factory=PredictionModeConfig)
    processing_mode: ProcessingModeConfig = field(default_factory=ProcessingModeConfig)
    new_player: NewPlayerConfig = field(default_factory=NewPlayerConfig)

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
