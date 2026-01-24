"""
Pydantic Models for Pub/Sub Message Validation

Provides type-safe validation for Pub/Sub messages used by cloud functions
in the pipeline orchestration.

Usage:
    from shared.validation.pubsub_models import Phase2CompletionMessage

    try:
        msg = Phase2CompletionMessage.model_validate(message_data)
        # Access typed fields safely
        processor = msg.processor_name
        game_date = msg.game_date
    except ValidationError as e:
        logger.error(f"Invalid message: {e}")

Created: 2026-01-24
"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


class Phase2CompletionMessage(BaseModel):
    """
    Message schema for Phase 2 processor completion events.

    Published to: nba-phase2-raw-complete
    Consumed by: phase2_to_phase3 orchestrator
    """
    processor_name: str = Field(
        ...,
        description="Name of the processor that completed (e.g., 'BdlGamesProcessor')"
    )
    game_date: str = Field(
        ...,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Game date in YYYY-MM-DD format"
    )
    phase: str = Field(
        default="phase_2_raw",
        description="Pipeline phase identifier"
    )
    execution_id: Optional[str] = Field(
        default=None,
        description="Unique execution identifier"
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Correlation ID for tracing"
    )
    output_table: Optional[str] = Field(
        default=None,
        description="Output BigQuery table name"
    )
    output_dataset: Optional[str] = Field(
        default=None,
        description="Output BigQuery dataset name"
    )
    status: Literal["success", "partial", "failed", "skipped"] = Field(
        default="success",
        description="Processing status"
    )
    record_count: int = Field(
        default=0,
        ge=0,
        description="Number of records processed"
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="Processing completion timestamp"
    )


class Phase3CompletionMessage(BaseModel):
    """
    Message schema for Phase 3 processor completion events.

    Published to: nba-phase3-analytics-complete
    Consumed by: phase3_to_phase4 orchestrator
    """
    processor_name: str = Field(
        ...,
        description="Name of the processor that completed"
    )
    game_date: str = Field(
        ...,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Game date in YYYY-MM-DD format"
    )
    phase: str = Field(
        default="phase_3_analytics",
        description="Pipeline phase identifier"
    )
    execution_id: Optional[str] = Field(
        default=None,
        description="Unique execution identifier"
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Correlation ID for tracing"
    )
    output_table: Optional[str] = Field(
        default=None,
        description="Output BigQuery table name"
    )
    status: Literal["success", "partial", "failed", "skipped"] = Field(
        default="success",
        description="Processing status"
    )
    record_count: int = Field(
        default=0,
        ge=0,
        description="Number of records processed"
    )
    metadata: Optional[dict] = Field(
        default=None,
        description="Additional metadata from processor"
    )


class Phase3AnalyticsMessage(BaseModel):
    """
    Message schema for Phase 3 analytics trigger events.

    Published to: nba-phase3-trigger
    Consumed by: phase3_to_phase4 orchestrator
    """
    game_date: str = Field(
        ...,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Game date in YYYY-MM-DD format"
    )
    trigger_source: str = Field(
        default="phase2_to_phase3",
        description="Source that triggered Phase 3"
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Correlation ID for tracing"
    )
    completed_processors: Optional[list[str]] = Field(
        default=None,
        description="List of Phase 2 processors that completed"
    )


class ScraperCompletionMessage(BaseModel):
    """
    Message schema for Phase 1 scraper completion events.

    Published to: nba-phase1-scrapers-complete
    Consumed by: Phase 2 raw processors
    """
    scraper_name: str = Field(
        ...,
        description="Name of the scraper (e.g., 'bdl_player_boxscores')"
    )
    gcs_path: str = Field(
        ...,
        description="GCS path to the scraped data file"
    )
    execution_id: str = Field(
        ...,
        description="Unique scraper execution identifier"
    )
    status: Literal["success", "partial", "failed"] = Field(
        ...,
        description="Scraper execution status"
    )
    game_date: Optional[str] = Field(
        default=None,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Game date in YYYY-MM-DD format"
    )
    record_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Number of records scraped"
    )
    triggered_at: Optional[str] = Field(
        default=None,
        description="Scraper trigger timestamp"
    )
    # Recovery fields (from cleanup_processor)
    recovery: bool = Field(
        default=False,
        description="Whether this is a recovery message"
    )
    recovery_reason: Optional[str] = Field(
        default=None,
        description="Reason for recovery (e.g., 'cleanup_processor')"
    )
    original_execution_id: Optional[str] = Field(
        default=None,
        description="Original execution ID if this is a recovery"
    )


class GradingTriggerMessage(BaseModel):
    """
    Message schema for Phase 6 grading trigger events.
    """
    target_date: str = Field(
        default="yesterday",
        description="Target date for grading ('today', 'yesterday', or YYYY-MM-DD)"
    )
    sport: Literal["nba", "mlb"] = Field(
        default="nba",
        description="Sport to grade"
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Correlation ID for tracing"
    )


# ============================================================================
# HTTP REQUEST MODELS (for Cloud Functions with HTTP triggers)
# ============================================================================


class SelfHealRequest(BaseModel):
    """
    Request schema for self-heal HTTP endpoint.

    The self-heal function can be triggered with optional parameters.
    """
    target_date: Optional[str] = Field(
        default=None,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Optional target date in YYYY-MM-DD format"
    )
    force_heal: bool = Field(
        default=False,
        description="Force healing even if data appears complete"
    )
    skip_phase3: bool = Field(
        default=False,
        description="Skip Phase 3 checks"
    )


class ScraperAvailabilityRequest(BaseModel):
    """
    Request schema for scraper availability monitor HTTP endpoint.
    """
    date: Optional[str] = Field(
        default=None,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Target date to check in YYYY-MM-DD format (defaults to yesterday)"
    )
    send_alert: bool = Field(
        default=True,
        description="Whether to send Slack alert if issues found"
    )


class HealthSummaryRequest(BaseModel):
    """
    Request schema for daily health summary HTTP endpoint.
    """
    target_date: Optional[str] = Field(
        default=None,
        pattern=r'^\d{4}-\d{2}-\d{2}$',
        description="Target date for summary (defaults to today)"
    )
    send_slack: bool = Field(
        default=True,
        description="Whether to send Slack summary"
    )


# Helper function for parsing with validation
def parse_with_validation(data: dict, model_class: type[BaseModel]) -> BaseModel:
    """
    Parse dictionary data into a validated Pydantic model.

    Args:
        data: Raw dictionary data from Pub/Sub message
        model_class: Pydantic model class to validate against

    Returns:
        Validated model instance

    Raises:
        pydantic.ValidationError: If validation fails
    """
    return model_class.model_validate(data)
