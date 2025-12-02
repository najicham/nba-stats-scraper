#!/usr/bin/env python3
"""
Pipeline Validation Script

Comprehensive validation for NBA stats processing pipeline.
Validates data presence, completeness, and quality across all phases.

Usage:
    python3 bin/validate_pipeline.py 2021-10-19
    python3 bin/validate_pipeline.py 2021-10-19 --verbose
    python3 bin/validate_pipeline.py today

Examples:
    # Validate a historical date
    python3 bin/validate_pipeline.py 2021-10-19

    # Validate with verbose output
    python3 bin/validate_pipeline.py 2021-10-19 --verbose

    # Show missing players
    python3 bin/validate_pipeline.py 2021-10-19 --show-missing

    # Validate today's data
    python3 bin/validate_pipeline.py today

    # Validate specific phase only
    python3 bin/validate_pipeline.py 2021-10-19 --phase 3
"""

import sys
import argparse
import logging
from datetime import date, datetime, timedelta
from typing import Optional, List

from google.cloud import bigquery

# Add project root to path
sys.path.insert(0, '/home/naji/code/nba-stats-scraper')

from shared.validation.config import PROJECT_ID
from shared.validation.context.schedule_context import get_schedule_context, ScheduleContext
from shared.validation.context.player_universe import get_player_universe, PlayerUniverse
from shared.validation.validators import (
    validate_phase1,
    validate_phase2,
    validate_phase3,
    validate_phase4,
    validate_phase5,
    PhaseValidationResult,
    ValidationStatus,
)
from shared.validation.output.terminal import (
    ValidationReport,
    print_validation_result,
)
from shared.validation.output.json_output import print_validation_json
from shared.validation.run_history import get_run_history, RunHistorySummary
from shared.validation.context.player_universe import get_missing_players
from shared.validation.firestore_state import get_orchestration_state, OrchestrationState
from shared.validation.time_awareness import get_time_context, TimeContext, format_time_context

logger = logging.getLogger(__name__)


def parse_date(date_str: str) -> date:
    """Parse date string, handling special values like 'today' and 'yesterday'."""
    date_str = date_str.lower().strip()

    if date_str == 'today':
        return date.today()
    elif date_str == 'yesterday':
        return date.today() - timedelta(days=1)
    else:
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD, 'today', or 'yesterday'")


def validate_date(
    game_date: date,
    client: Optional[bigquery.Client] = None,
    phases: Optional[List[int]] = None,
    verbose: bool = False,
    show_missing: bool = False,
) -> ValidationReport:
    """
    Run full pipeline validation for a date.

    Args:
        game_date: Date to validate
        client: Optional BigQuery client
        phases: Specific phases to validate (None = all)
        verbose: Show detailed output
        show_missing: Show missing player details

    Returns:
        ValidationReport with all results
    """
    import time as time_module

    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    if phases is None:
        phases = [1, 2, 3, 4, 5]

    logger.info(f"Validating pipeline for {game_date}")
    total_start = time_module.time()

    # Get time context (for today/yesterday awareness)
    step_start = time_module.time()
    time_context = get_time_context(game_date)
    logger.info(f"  ├─ Time context ({time_module.time() - step_start:.1f}s)")

    # Get context
    step_start = time_module.time()
    schedule_context = get_schedule_context(game_date, client)
    logger.info(f"  ├─ Schedule: {schedule_context.game_count} games ({time_module.time() - step_start:.1f}s)")

    step_start = time_module.time()
    player_universe = get_player_universe(game_date, client)
    logger.info(f"  ├─ Players: {player_universe.total_rostered} rostered ({time_module.time() - step_start:.1f}s)")

    # Get orchestration state from Firestore (for today/yesterday)
    orchestration_state = None
    if time_context.is_today or time_context.is_yesterday:
        step_start = time_module.time()
        orchestration_state = get_orchestration_state(game_date)
        logger.info(f"  ├─ Orchestration state ({time_module.time() - step_start:.1f}s)")

    # Get run history (for verbose mode or to check for errors)
    run_history = None
    if verbose or True:  # Always get run history for error detection
        step_start = time_module.time()
        run_history = get_run_history(game_date, client)
        logger.info(f"  ├─ Run history: {run_history.total_runs} runs ({time_module.time() - step_start:.1f}s)")

    # Run phase validators
    phase_results = []

    if 1 in phases:
        step_start = time_module.time()
        result = validate_phase1(game_date, schedule_context)
        phase_results.append(result)
        logger.info(f"  ├─ Phase 1 (GCS): {result.status.value} ({time_module.time() - step_start:.1f}s)")

    if 2 in phases:
        step_start = time_module.time()
        result = validate_phase2(game_date, schedule_context, player_universe, client)
        phase_results.append(result)
        logger.info(f"  ├─ Phase 2 (BQ): {result.status.value} ({time_module.time() - step_start:.1f}s)")

    if 3 in phases:
        step_start = time_module.time()
        result = validate_phase3(game_date, schedule_context, player_universe, client)
        phase_results.append(result)
        logger.info(f"  ├─ Phase 3: {result.status.value} ({time_module.time() - step_start:.1f}s)")

    if 4 in phases:
        step_start = time_module.time()
        result = validate_phase4(game_date, schedule_context, player_universe, client)
        phase_results.append(result)
        logger.info(f"  ├─ Phase 4: {result.status.value} ({time_module.time() - step_start:.1f}s)")

    if 5 in phases:
        step_start = time_module.time()
        result = validate_phase5(game_date, schedule_context, player_universe, client)
        phase_results.append(result)
        logger.info(f"  └─ Phase 5: {result.status.value} ({time_module.time() - step_start:.1f}s)")

    logger.info(f"  Total: {time_module.time() - total_start:.1f}s")

    # Collect all issues and warnings
    all_issues = []
    all_warnings = []

    for result in phase_results:
        all_issues.extend(result.issues)
        all_warnings.extend(result.warnings)

    # Add run history warnings
    if run_history and run_history.failed_runs > 0:
        all_issues.append(f"{run_history.failed_runs} processor(s) failed for this date")

    # Calculate missing players if requested or if there are issues
    missing_players = None
    if show_missing:
        # Get players who were processed in Phase 3 (player_game_summary)
        actual_processed = _get_processed_players(client, game_date)
        missing_players = get_missing_players(player_universe, actual_processed, 'all_players')
        if missing_players:
            logger.debug(f"Missing players: {len(missing_players)}")

    # Determine overall status
    overall_status = _determine_overall_status(phase_results, schedule_context)

    return ValidationReport(
        game_date=game_date,
        schedule_context=schedule_context,
        player_universe=player_universe,
        phase_results=phase_results,
        overall_status=overall_status,
        issues=all_issues,
        warnings=all_warnings,
        run_history=run_history,
        missing_players=missing_players,
        time_context=time_context,
        orchestration_state=orchestration_state,
    )


def _get_processed_players(client: bigquery.Client, game_date: date) -> set:
    """Get set of players processed in player_game_summary."""
    query = f"""
    SELECT DISTINCT player_lookup
    FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
    WHERE game_date = @game_date
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
        ]
    )
    try:
        result = client.query(query, job_config=job_config).result()
        return {row.player_lookup for row in result}
    except Exception as e:
        logger.error(f"Error querying processed players: {e}")
        return set()


def _determine_overall_status(
    phase_results: List[PhaseValidationResult],
    schedule_context: ScheduleContext,
) -> str:
    """Determine overall pipeline status."""

    if not schedule_context.is_valid_processing_date:
        return f"N/A - {schedule_context.skip_reason}"

    statuses = [r.status for r in phase_results]

    if all(s == ValidationStatus.COMPLETE for s in statuses):
        return "✓ COMPLETE - All phases validated"
    elif all(s == ValidationStatus.BOOTSTRAP_SKIP for s in statuses):
        return "⊘ BOOTSTRAP - Expected empty"
    elif all(s in (ValidationStatus.COMPLETE, ValidationStatus.BOOTSTRAP_SKIP) for s in statuses):
        return "✓ COMPLETE - With bootstrap skips"
    elif any(s == ValidationStatus.MISSING for s in statuses):
        return "○ INCOMPLETE - Missing data, needs backfill"
    elif any(s == ValidationStatus.PARTIAL for s in statuses):
        return "△ PARTIAL - Some data present, needs attention"
    elif any(s == ValidationStatus.ERROR for s in statuses):
        return "✗ ERROR - Validation errors occurred"
    else:
        return "? UNKNOWN"


def validate_date_range(
    start_date: date,
    end_date: date,
    client: Optional[bigquery.Client] = None,
    phases: Optional[List[int]] = None,
) -> List[ValidationReport]:
    """
    Validate a range of dates.

    Args:
        start_date: First date to validate
        end_date: Last date to validate
        client: Optional BigQuery client
        phases: Specific phases to validate

    Returns:
        List of ValidationReports for each date
    """
    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    reports = []
    current = start_date

    while current <= end_date:
        logger.info(f"Validating {current}...")
        report = validate_date(
            game_date=current,
            client=client,
            phases=phases,
            verbose=False,
            show_missing=False,
        )
        reports.append(report)
        current += timedelta(days=1)

    return reports


def format_range_summary(reports: List[ValidationReport]) -> str:
    """Format summary for date range validation."""
    lines = []

    lines.append("=" * 80)
    lines.append("DATE RANGE VALIDATION SUMMARY")
    lines.append("=" * 80)
    lines.append("")

    # Count statuses
    complete = 0
    partial = 0
    missing = 0
    bootstrap = 0
    no_games = 0

    for report in reports:
        status = report.overall_status
        if "COMPLETE" in status:
            complete += 1
        elif "PARTIAL" in status:
            partial += 1
        elif "INCOMPLETE" in status or "Missing" in status:
            missing += 1
        elif "BOOTSTRAP" in status:
            bootstrap += 1
        elif "N/A" in status:
            no_games += 1

    lines.append(f"Dates Validated: {len(reports)}")
    lines.append(f"  ✓ Complete:    {complete}")
    lines.append(f"  △ Partial:     {partial}")
    lines.append(f"  ○ Missing:     {missing}")
    lines.append(f"  ⊘ Bootstrap:   {bootstrap}")
    lines.append(f"  ─ No games:    {no_games}")
    lines.append("")

    # Per-date summary
    lines.append("PER-DATE STATUS")
    lines.append("-" * 80)

    for report in reports:
        date_str = report.game_date.strftime('%Y-%m-%d')
        status = report.overall_status[:40]
        games = report.schedule_context.game_count
        players = report.player_universe.total_active

        lines.append(f"{date_str}  {games:2d} games  {players:3d} players  {status}")

    lines.append("")
    lines.append("=" * 80)

    return '\n'.join(lines)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Validate NBA stats processing pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 bin/validate_pipeline.py 2021-10-19
  python3 bin/validate_pipeline.py today --verbose
  python3 bin/validate_pipeline.py 2021-10-19 --phase 3
  python3 bin/validate_pipeline.py 2021-10-19 2021-10-25   # Date range
        """
    )

    parser.add_argument(
        'date',
        help="Start date (YYYY-MM-DD, 'today', or 'yesterday')"
    )
    parser.add_argument(
        'end_date',
        nargs='?',
        default=None,
        help="End date for range validation (optional)"
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed output including run history'
    )
    parser.add_argument(
        '--show-missing',
        action='store_true',
        help='Show list of missing players'
    )
    parser.add_argument(
        '--phase',
        type=int,
        choices=[1, 2, 3, 4, 5],
        help='Validate specific phase only (1=GCS, 2=BQ Raw, 3=Analytics, 4=Precompute, 5=Predictions)'
    )
    parser.add_argument(
        '--format',
        choices=['terminal', 'json'],
        default='terminal',
        help='Output format (default: terminal)'
    )
    parser.add_argument(
        '--no-color',
        action='store_true',
        help='Disable colored output'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Parse dates
    try:
        start_date = parse_date(args.date)
        end_date = parse_date(args.end_date) if args.end_date else None
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Determine phases to validate
    phases = [args.phase] if args.phase else None

    # Run validation
    try:
        if end_date:
            # Date range validation
            if end_date < start_date:
                print("Error: End date must be after start date", file=sys.stderr)
                sys.exit(1)

            reports = validate_date_range(
                start_date=start_date,
                end_date=end_date,
                phases=phases,
            )

            # Output results
            if args.format == 'terminal':
                print(format_range_summary(reports))
            else:
                # JSON output for range
                import json
                output = {
                    'range': {
                        'start': start_date.isoformat(),
                        'end': end_date.isoformat(),
                        'total_dates': len(reports),
                    },
                    'dates': []
                }
                for report in reports:
                    output['dates'].append({
                        'date': report.game_date.isoformat(),
                        'status': report.overall_status,
                        'games': report.schedule_context.game_count,
                        'players': report.player_universe.total_active,
                    })
                print(json.dumps(output, indent=2))
        else:
            # Single date validation
            report = validate_date(
                game_date=start_date,
                phases=phases,
                verbose=args.verbose,
                show_missing=args.show_missing,
            )

            # Output results
            if args.format == 'terminal':
                use_color = not args.no_color
                print_validation_result(
                    report,
                    use_color=use_color,
                    verbose=args.verbose,
                    show_missing=args.show_missing,
                )
            else:
                # JSON output
                print_validation_json(report, pretty=True)

    except Exception as e:
        logger.exception(f"Validation failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
