"""
Run History Integration

Queries processor_run_history for detailed run information.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Any
import logging
import json

from google.cloud import bigquery

from shared.validation.config import PROJECT_ID

logger = logging.getLogger(__name__)


@dataclass
class ProcessorRun:
    """Information about a single processor run."""
    run_id: str
    processor_name: str
    phase: int
    status: str  # 'success', 'failed', 'partial', 'skipped'
    duration_seconds: float
    records_processed: int
    records_created: int
    records_updated: int
    records_skipped: int

    # Timestamps
    started_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None

    # Error/warning info
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Dependency info
    dependency_check_passed: bool = True
    missing_dependencies: List[str] = field(default_factory=list)
    stale_dependencies: List[str] = field(default_factory=list)

    # Alert info
    alert_sent: bool = False
    alert_type: Optional[str] = None

    # Source tracking
    trigger_source: Optional[str] = None
    cloud_run_service: Optional[str] = None


@dataclass
class RunHistorySummary:
    """Summary of all runs for a date."""
    game_date: date

    # Runs by phase
    phase_runs: Dict[int, List[ProcessorRun]] = field(default_factory=dict)

    # Aggregate stats
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    partial_runs: int = 0
    skipped_runs: int = 0

    # Issues
    errors: List[Dict[str, Any]] = field(default_factory=list)
    dependency_failures: List[Dict[str, Any]] = field(default_factory=list)
    alerts_sent: List[Dict[str, Any]] = field(default_factory=list)

    # Timing
    total_duration_seconds: float = 0


def get_run_history(
    game_date: date,
    client: Optional[bigquery.Client] = None
) -> RunHistorySummary:
    """
    Get run history for a date.

    Args:
        game_date: Date to get history for
        client: Optional BigQuery client

    Returns:
        RunHistorySummary with all run information
    """
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    summary = RunHistorySummary(game_date=game_date)

    # Query run history
    query = f"""
    SELECT
        run_id,
        processor_name,
        phase,
        status,
        COALESCE(duration_seconds, 0) as duration_seconds,
        COALESCE(records_processed, 0) as records_processed,
        COALESCE(records_created, 0) as records_created,
        COALESCE(records_updated, 0) as records_updated,
        COALESCE(records_skipped, 0) as records_skipped,
        started_at,
        processed_at,
        errors,
        warnings,
        COALESCE(dependency_check_passed, TRUE) as dependency_check_passed,
        missing_dependencies,
        stale_dependencies,
        COALESCE(alert_sent, FALSE) as alert_sent,
        alert_type,
        trigger_source,
        cloud_run_service
    FROM `{PROJECT_ID}.nba_reference.processor_run_history`
    WHERE data_date = @game_date
    ORDER BY phase, processor_name, started_at DESC
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )

    try:
        result = client.query(query, job_config=job_config).result(timeout=60)

        seen_processors = set()  # Track latest run per processor

        for row in result:
            processor_name = row.processor_name

            # Only take the latest run per processor
            if processor_name in seen_processors:
                continue
            seen_processors.add(processor_name)

            # Parse JSON fields
            errors = _parse_json_array(row.errors)
            warnings = _parse_json_array(row.warnings)
            missing_deps = _parse_json_array(row.missing_dependencies)
            stale_deps = _parse_json_array(row.stale_dependencies)

            run = ProcessorRun(
                run_id=row.run_id or '',
                processor_name=processor_name,
                phase=row.phase or 0,
                status=row.status or 'unknown',
                duration_seconds=float(row.duration_seconds or 0),
                records_processed=int(row.records_processed or 0),
                records_created=int(row.records_created or 0),
                records_updated=int(row.records_updated or 0),
                records_skipped=int(row.records_skipped or 0),
                started_at=row.started_at,
                processed_at=row.processed_at,
                errors=errors,
                warnings=warnings,
                dependency_check_passed=bool(row.dependency_check_passed),
                missing_dependencies=missing_deps,
                stale_dependencies=stale_deps,
                alert_sent=bool(row.alert_sent),
                alert_type=row.alert_type,
                trigger_source=row.trigger_source,
                cloud_run_service=row.cloud_run_service,
            )

            # Add to phase runs
            phase = run.phase
            if phase not in summary.phase_runs:
                summary.phase_runs[phase] = []
            summary.phase_runs[phase].append(run)

            # Update aggregate stats
            summary.total_runs += 1
            summary.total_duration_seconds += run.duration_seconds

            if run.status == 'success':
                summary.successful_runs += 1
            elif run.status == 'failed':
                summary.failed_runs += 1
            elif run.status == 'partial':
                summary.partial_runs += 1
            elif run.status == 'skipped':
                summary.skipped_runs += 1

            # Track issues
            if errors:
                summary.errors.append({
                    'processor': processor_name,
                    'phase': phase,
                    'status': run.status,
                    'errors': errors,
                    'run_id': run.run_id,
                    'time': run.processed_at,
                })

            if not run.dependency_check_passed:
                summary.dependency_failures.append({
                    'processor': processor_name,
                    'phase': phase,
                    'missing': missing_deps,
                    'stale': stale_deps,
                })

            if run.alert_sent:
                summary.alerts_sent.append({
                    'processor': processor_name,
                    'phase': phase,
                    'alert_type': run.alert_type,
                    'time': run.processed_at,
                })

    except Exception as e:
        logger.error(f"Error querying run history for {game_date}: {e}", exc_info=True)

    return summary


def _parse_json_array(value: Optional[str]) -> List[str]:
    """Parse a JSON array string, returning empty list on failure."""
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def get_processor_run_for_table(
    summary: RunHistorySummary,
    processor_name: str
) -> Optional[ProcessorRun]:
    """Get the run for a specific processor."""
    for phase_runs in summary.phase_runs.values():
        for run in phase_runs:
            if run.processor_name == processor_name:
                return run
    return None


def format_run_status(run: ProcessorRun) -> str:
    """Format run status for display."""
    status_symbols = {
        'success': '✓',
        'failed': '✗',
        'partial': '△',
        'skipped': '⊘',
        'unknown': '?',
    }
    symbol = status_symbols.get(run.status, '?')

    duration_str = f"{run.duration_seconds:.1f}s" if run.duration_seconds else ""

    parts = [f"{symbol} {run.status.title()}"]
    if duration_str:
        parts.append(f"({duration_str})")
    if run.records_created > 0:
        parts.append(f"{run.records_created} records")

    return ' '.join(parts)


def format_run_history_verbose(summary: RunHistorySummary) -> str:
    """Format run history for verbose display."""
    lines = []

    # Sort phases numerically (handle both int and string phase keys)
    sorted_phases = sorted(summary.phase_runs.keys(), key=lambda x: int(x) if str(x).isdigit() else 99)

    for phase in sorted_phases:
        runs = summary.phase_runs[phase]
        # Clean up phase name (handle "phase_3" -> "3")
        phase_display = str(phase).replace('phase_', '').replace('_precompute', ' (Precompute)')
        lines.append(f"\nPhase {phase_display} Runs ({len(runs)} processors)")
        lines.append("─" * 70)

        for run in sorted(runs, key=lambda r: r.processor_name):
            lines.append(f"  {run.processor_name}")
            lines.append(f"    Status:    {format_run_status(run)}")

            if run.run_id:
                lines.append(f"    Run ID:    {run.run_id[:20]}...")

            if run.records_created or run.records_updated:
                lines.append(f"    Records:   {run.records_created} created, {run.records_updated} updated")

            if run.errors:
                lines.append(f"    Errors:    {len(run.errors)} errors")
                for err in run.errors[:2]:  # Show first 2
                    lines.append(f"               - {err[:60]}...")

            if run.warnings:
                lines.append(f"    Warnings:  {len(run.warnings)} warnings")

            if not run.dependency_check_passed:
                lines.append(f"    Deps:      FAILED")
                if run.missing_dependencies:
                    lines.append(f"               Missing: {run.missing_dependencies}")

            if run.alert_sent:
                lines.append(f"    Alert:     [{run.alert_type}]")

            lines.append("")

    return '\n'.join(lines)


def format_errors_section(summary: RunHistorySummary) -> str:
    """Format errors section for display."""
    lines = []

    # Processor errors
    if summary.errors:
        lines.append(f"PROCESSOR ERRORS ({len(summary.errors)})")
        lines.append("─" * 70)
        for error in summary.errors[:5]:  # Show first 5
            lines.append(f"✗ {error['processor']}")
            lines.append(f"  Status:    {error['status']}")
            if error['errors']:
                lines.append(f"  Error:     {error['errors'][0][:60]}...")
            if error.get('time'):
                lines.append(f"  Time:      {error['time']}")
            lines.append(f"  Run ID:    {error['run_id'][:30]}...")
            lines.append("")

    # Dependency failures
    if summary.dependency_failures:
        lines.append(f"DEPENDENCY FAILURES ({len(summary.dependency_failures)})")
        lines.append("─" * 70)
        for failure in summary.dependency_failures[:5]:
            lines.append(f"⚠ {failure['processor']}")
            if failure['missing']:
                lines.append(f"  Missing:   {failure['missing']}")
            if failure['stale']:
                lines.append(f"  Stale:     {failure['stale']}")
            lines.append("")

    # Alerts sent
    if summary.alerts_sent:
        lines.append(f"ALERTS SENT ({len(summary.alerts_sent)})")
        lines.append("─" * 70)
        for alert in summary.alerts_sent[:10]:
            time_str = alert['time'].strftime('%H:%M:%S') if alert.get('time') else ''
            lines.append(f"  [{alert['alert_type']}] {alert['processor']} - {time_str}")
        lines.append("")

    return '\n'.join(lines) if lines else ""
