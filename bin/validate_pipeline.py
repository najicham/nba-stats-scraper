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
from dataclasses import dataclass
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
    check_cross_table_consistency,
)
from shared.validation.output.terminal import (
    ValidationReport,
    print_validation_result,
    format_chain_section,
    format_maintenance_section,
)
from shared.validation.output.json_output import print_validation_json, format_combined_json
from shared.validation.validators.chain_validator import validate_all_chains
from shared.validation.validators.maintenance_validator import validate_maintenance
from shared.validation.run_history import get_run_history, RunHistorySummary
from shared.validation.context.player_universe import get_missing_players
from shared.validation.firestore_state import get_orchestration_state, OrchestrationState
from shared.validation.time_awareness import get_time_context, TimeContext, format_time_context

logger = logging.getLogger(__name__)


# Import shared mode detection function
from shared.validation.config import get_processing_mode as get_validation_mode


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
    skip_phase1_phase2: bool = False,
) -> ValidationReport:
    """
    Run full pipeline validation for a date.

    Args:
        game_date: Date to validate
        client: Optional BigQuery client
        phases: Specific phases to validate (None = all)
        verbose: Show detailed output
        show_missing: Show missing player details
        skip_phase1_phase2: Skip Phase 1/2 validation (when using chain view)

    Returns:
        ValidationReport with all results
    """
    import time as time_module

    if client is None:
        client = bigquery.Client(project=PROJECT_ID)

    if phases is None:
        if skip_phase1_phase2:
            phases = [3, 4, 5]  # Chain view handles P1/P2
        else:
            phases = [1, 2, 3, 4, 5]

    # Determine validation mode (daily vs backfill)
    validation_mode = get_validation_mode(game_date)
    logger.info(f"Validating pipeline for {game_date} (mode: {validation_mode})")
    total_start = time_module.time()

    # Get time context (for today/yesterday awareness)
    step_start = time_module.time()
    time_context = get_time_context(game_date)
    logger.info(f"  ├─ Time context ({time_module.time() - step_start:.1f}s)")

    # Get context
    step_start = time_module.time()
    schedule_context = get_schedule_context(game_date, client)
    logger.info(f"  ├─ Schedule: {schedule_context.game_count} games ({time_module.time() - step_start:.1f}s)")

    # Get player universe with mode (daily uses roster, backfill uses gamebook)
    step_start = time_module.time()
    player_universe = get_player_universe(game_date, client, mode=validation_mode)
    roster_warning = ""
    if validation_mode == 'daily' and player_universe.roster_date:
        days_stale = (game_date - player_universe.roster_date).days
        if days_stale > 7:
            roster_warning = f" ⚠️ STALE ({days_stale}d old)"
    logger.info(f"  ├─ Players: {player_universe.total_rostered} rostered ({player_universe.source}){roster_warning} ({time_module.time() - step_start:.1f}s)")

    # Get orchestration state from Firestore (for today/yesterday)
    orchestration_state = None
    if time_context.is_today or time_context.is_yesterday:
        step_start = time_module.time()
        orchestration_state = get_orchestration_state(game_date)
        logger.info(f"  ├─ Orchestration state ({time_module.time() - step_start:.1f}s)")

    # Get run history - always fetch for error detection, verbose mode shows details
    run_history = None
    if True:  # Always needed for error detection (failures, alerts, dependencies)
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

    # Cross-phase consistency check (Phase 3 → Phase 4)
    # Only run if both Phase 3 and Phase 4 have data
    if 3 in phases and 4 in phases:
        consistency = _check_cross_phase_consistency(client, game_date)
        if consistency and not consistency.get('is_consistent', True):
            missing_count = consistency.get('missing_count', 0)
            extra_count = consistency.get('extra_count', 0)
            if missing_count > 0:
                all_warnings.append(
                    f"Cross-phase mismatch: {missing_count} players in Phase 3 missing from Phase 4"
                )
            if extra_count > 0:
                all_warnings.append(
                    f"Cross-phase mismatch: {extra_count} extra players in Phase 4 not in Phase 3"
                )

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


def _check_cross_phase_consistency(
    client: bigquery.Client,
    game_date: date,
) -> dict:
    """
    Check player consistency between Phase 3 (player_game_summary) and Phase 4 (ml_feature_store_v2).

    This catches issues where:
    - Phase 3 processed with gamebook but Phase 4 processed with BDL fallback
    - Processor bugs causing different player sets
    - Re-runs that created inconsistent data

    Returns:
        Dict with consistency metrics (is_consistent, missing_count, extra_count, etc.)
    """
    try:
        return check_cross_table_consistency(
            client=client,
            game_date=game_date,
            source_dataset='nba_analytics',
            source_table='player_game_summary',
            source_date_column='game_date',
            target_dataset='nba_predictions',
            target_table='ml_feature_store_v2',
            target_date_column='game_date',
            player_column='player_lookup',
        )
    except Exception as e:
        logger.debug(f"Could not check cross-phase consistency: {e}")
        return {'is_consistent': True}  # Assume consistent on error


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


@dataclass
class ChainRangeResult:
    """Result for chain validation over a date range."""
    game_date: date
    chain_validations: dict
    chains_complete: int
    chains_partial: int
    chains_missing: int
    total_chains: int


def validate_date_range_chains(
    start_date: date,
    end_date: date,
    client: Optional[bigquery.Client] = None,
) -> List[ChainRangeResult]:
    """
    Validate chain data for a range of dates.

    Args:
        start_date: First date to validate
        end_date: Last date to validate
        client: Optional BigQuery client

    Returns:
        List of ChainRangeResult for each date
    """
    from google.cloud import storage

    if client is None:
        client = bigquery.Client(project=PROJECT_ID)
    gcs_client = storage.Client()

    results = []
    current = start_date

    while current <= end_date:
        # Determine validation mode for this date
        validation_mode = get_validation_mode(current)
        logger.info(f"Validating chains for {current} (mode: {validation_mode})...")

        # Get schedule context
        schedule_context = get_schedule_context(current, client)

        # Validate chains - include roster chain for daily mode
        skip_roster = (validation_mode == 'backfill')
        chain_validations = validate_all_chains(
            game_date=current,
            schedule_context=schedule_context,
            bq_client=client,
            gcs_client=gcs_client,
            skip_roster_chain=skip_roster,
        )

        # Count statuses
        chains_complete = sum(1 for cv in chain_validations.values() if cv.status == 'complete')
        chains_partial = sum(1 for cv in chain_validations.values() if cv.status == 'partial')
        chains_missing = sum(1 for cv in chain_validations.values() if cv.status == 'missing')

        results.append(ChainRangeResult(
            game_date=current,
            chain_validations=chain_validations,
            chains_complete=chains_complete,
            chains_partial=chains_partial,
            chains_missing=chains_missing,
            total_chains=len(chain_validations),
        ))

        current += timedelta(days=1)

    return results


def format_chain_range_summary(results: List[ChainRangeResult], use_color: bool = True) -> str:
    """Format summary for chain date range validation."""
    lines = []

    lines.append("=" * 80)
    lines.append("DATE RANGE CHAIN VALIDATION SUMMARY")
    lines.append("=" * 80)
    lines.append("")

    # Overall stats
    total_dates = len(results)
    all_complete = sum(1 for r in results if r.chains_complete == r.total_chains)
    some_partial = sum(1 for r in results if r.chains_partial > 0 and r.chains_missing == 0)
    some_missing = sum(1 for r in results if r.chains_missing > 0)
    complete_pct = (all_complete / total_dates * 100) if total_dates > 0 else 0

    # Progress bar
    bar_width = 40
    filled = int(complete_pct / 100 * bar_width)
    empty = bar_width - filled
    if use_color:
        if complete_pct >= 90:
            bar_color = '\033[92m'  # Green
        elif complete_pct >= 50:
            bar_color = '\033[93m'  # Yellow
        else:
            bar_color = '\033[91m'  # Red
        reset = '\033[0m'
    else:
        bar_color = ''
        reset = ''

    progress_bar = f"[{bar_color}{'█' * filled}{reset}{'░' * empty}] {complete_pct:.1f}%"
    lines.append(f"Progress: {progress_bar}")
    lines.append("")

    lines.append(f"Dates: {total_dates} total")
    lines.append(f"  ✓ Complete: {all_complete}")
    if some_partial > 0:
        lines.append(f"  △ Partial:  {some_partial}")
    if some_missing > 0:
        lines.append(f"  ○ Missing:  {some_missing}")
    lines.append("")

    # Visual sparkline - show each date as a single character
    lines.append("VISUAL TIMELINE")
    lines.append("-" * 80)

    # Build sparkline with colors
    sparkline_chars = []
    for r in results:
        if r.chains_complete == r.total_chains:
            char = '✓'
            color = '\033[92m' if use_color else ''
        elif r.chains_missing > 0:
            char = '○'
            color = '\033[91m' if use_color else ''
        else:
            char = '△'
            color = '\033[93m' if use_color else ''
        sparkline_chars.append(f"{color}{char}{reset}")

    # Group into weeks (7 chars) for readability
    if total_dates <= 14:
        # Short range - show all on one line with date markers
        start_date = results[0].game_date.strftime('%m/%d')
        end_date = results[-1].game_date.strftime('%m/%d')
        sparkline = ''.join(sparkline_chars)
        # Add spacing between chars for readability
        spaced_sparkline = ' '.join([c for c in sparkline_chars])
        lines.append(f"  {start_date}  {spaced_sparkline}  {end_date}")
    else:
        # Long range - show in weekly rows
        week_num = 0
        for i in range(0, total_dates, 7):
            week_chars = sparkline_chars[i:i+7]
            week_start = results[i].game_date.strftime('%m/%d')
            week_end_idx = min(i + 6, total_dates - 1)
            week_end = results[week_end_idx].game_date.strftime('%m/%d')

            # Count statuses for this week
            week_results = results[i:i+7]
            week_complete = sum(1 for r in week_results if r.chains_complete == r.total_chains)
            week_total = len(week_results)

            week_line = ''.join(week_chars)
            lines.append(f"  {week_start}-{week_end}: {week_line} ({week_complete}/{week_total})")
            week_num += 1

    lines.append("")
    lines.append("  Legend: ✓=Complete  △=Partial  ○=Missing")
    lines.append("")

    # Per-date table (only for short ranges)
    if total_dates <= 14:
        lines.append("PER-DATE DETAILS")
        lines.append("-" * 80)
        lines.append(f"{'Date':<12} {'Complete':>10} {'Partial':>10} {'Missing':>10} {'Status':<20}")
        lines.append("-" * 80)

        for r in results:
            date_str = r.game_date.strftime('%Y-%m-%d')

            if r.chains_complete == r.total_chains:
                status = "✓ All complete"
                color = '\033[92m' if use_color else ''
            elif r.chains_missing > 0:
                status = f"○ {r.chains_missing} missing"
                color = '\033[91m' if use_color else ''
            else:
                status = f"△ {r.chains_partial} partial"
                color = '\033[93m' if use_color else ''

            lines.append(
                f"{date_str:<12} {r.chains_complete:>10} {r.chains_partial:>10} "
                f"{r.chains_missing:>10} {color}{status}{reset}"
            )

        lines.append("")

    # Chain-by-chain breakdown
    if results:
        lines.append("CHAIN COVERAGE ACROSS DATE RANGE")
        lines.append("-" * 80)

        # Collect chain names from first result
        chain_names = list(results[0].chain_validations.keys())

        for chain_name in sorted(chain_names):
            complete_count = sum(
                1 for r in results
                if r.chain_validations.get(chain_name) and
                   r.chain_validations[chain_name].status == 'complete'
            )
            pct = (complete_count / total_dates) * 100 if total_dates > 0 else 0

            if pct >= 90:
                color = '\033[92m' if use_color else ''
            elif pct >= 50:
                color = '\033[93m' if use_color else ''
            else:
                color = '\033[91m' if use_color else ''

            reset = '\033[0m' if use_color else ''

            lines.append(f"  {chain_name:<30} {color}{complete_count:>3}/{total_dates} ({pct:5.1f}%){reset}")

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
    parser.add_argument(
        '--legacy-view',
        action='store_true',
        help='Use legacy flat view instead of chain view for Phase 1-2'
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

            use_color = not args.no_color

            if args.legacy_view:
                # Legacy view - validate phases 1-5
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
                # Chain view (V2) - validate chains
                chain_results = validate_date_range_chains(
                    start_date=start_date,
                    end_date=end_date,
                )

                # Output results
                if args.format == 'terminal':
                    print(format_chain_range_summary(chain_results, use_color=use_color))
                else:
                    # JSON output for chain range with comprehensive summary
                    from shared.validation.output.json_output import format_date_range_json
                    print(format_date_range_json(
                        chain_results=chain_results,
                        start_date=start_date,
                        end_date=end_date,
                        pretty=True,
                    ))
        else:
            # Single date validation
            # For chain view (default), skip P1/P2 in validate_date since chain_validator handles them
            use_chain_view = not args.legacy_view
            report = validate_date(
                game_date=start_date,
                phases=phases,
                verbose=args.verbose,
                show_missing=args.show_missing,
                skip_phase1_phase2=use_chain_view,
            )

            # Output results
            if args.format == 'terminal':
                use_color = not args.no_color

                # Legacy view - flat Phase 1 and Phase 2 lists
                if args.legacy_view:
                    print_validation_result(
                        report,
                        use_color=use_color,
                        verbose=args.verbose,
                        show_missing=args.show_missing,
                    )
                else:
                    # Chain view (V2, default) - shows Phase 1-2 as unified chain view
                    # Run chain validation (this replaces P1/P2 validation)
                    # Include roster chain for daily mode (start_date >= today)
                    validation_mode = get_validation_mode(start_date)
                    skip_roster = (validation_mode == 'backfill')
                    chain_validations = validate_all_chains(
                        game_date=start_date,
                        schedule_context=report.schedule_context,
                        skip_roster_chain=skip_roster,
                    )

                    # Print chain section
                    print(format_chain_section(chain_validations, use_color=use_color))
                    print()

                    # Run maintenance validation (for today/yesterday)
                    maintenance = validate_maintenance(
                        game_date=start_date,
                        time_context=report.time_context,
                    )
                    if maintenance:
                        print(format_maintenance_section(maintenance, use_color=use_color))
                        print()

                    # Print Phase 3-5 using standard output (P1/P2 already excluded)
                    print_validation_result(
                        report,
                        use_color=use_color,
                        verbose=args.verbose,
                        show_missing=args.show_missing,
                    )
            else:
                # JSON output
                if args.legacy_view:
                    # Legacy view - standard JSON
                    print_validation_json(report, pretty=True)
                else:
                    # Chain view - combined JSON with chain data
                    # Include roster chain for daily mode
                    validation_mode = get_validation_mode(start_date)
                    skip_roster = (validation_mode == 'backfill')
                    chain_validations = validate_all_chains(
                        game_date=start_date,
                        schedule_context=report.schedule_context,
                        skip_roster_chain=skip_roster,
                    )
                    maintenance = validate_maintenance(
                        game_date=start_date,
                        time_context=report.time_context,
                    )
                    print(format_combined_json(
                        report=report,
                        chain_validations=chain_validations,
                        maintenance=maintenance,
                        pretty=True,
                    ))

    except Exception as e:
        logger.exception(f"Validation failed: {e}")
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
