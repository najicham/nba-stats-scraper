"""
Terminal Output Formatter

Formats validation results for terminal display with
status indicators and clear visual hierarchy.
"""

from dataclasses import dataclass
from datetime import date
from typing import List, Optional
import sys

from shared.validation.context.schedule_context import ScheduleContext, format_schedule_summary
from shared.validation.context.player_universe import (
    PlayerUniverse, format_player_universe, get_missing_players
)
from shared.validation.validators.base import (
    PhaseValidationResult,
    TableValidation,
    ValidationStatus,
)
from shared.validation.chain_config import (
    ChainValidation,
)
from shared.validation.validators.maintenance_validator import (
    MaintenanceValidation,
)
from shared.validation.run_history import (
    RunHistorySummary,
    format_run_history_verbose,
    format_errors_section,
)
from shared.validation.firestore_state import (
    OrchestrationState,
    format_orchestration_state,
    format_orchestration_verbose,
)
from shared.validation.time_awareness import (
    TimeContext,
    format_time_context,
)

# Status indicators
STATUS_SYMBOLS = {
    ValidationStatus.COMPLETE: '✓',
    ValidationStatus.PARTIAL: '△',
    ValidationStatus.MISSING: '○',
    ValidationStatus.BOOTSTRAP_SKIP: '⊘',
    ValidationStatus.NOT_APPLICABLE: '─',
    ValidationStatus.ERROR: '✗',
}

STATUS_COLORS = {
    ValidationStatus.COMPLETE: '\033[92m',  # Green
    ValidationStatus.PARTIAL: '\033[93m',   # Yellow
    ValidationStatus.MISSING: '\033[91m',   # Red
    ValidationStatus.BOOTSTRAP_SKIP: '\033[94m',  # Blue
    ValidationStatus.NOT_APPLICABLE: '\033[90m',  # Gray
    ValidationStatus.ERROR: '\033[91m',     # Red
}

RESET = '\033[0m'
BOLD = '\033[1m'
DIM = '\033[2m'

LINE_WIDTH = 80
SEPARATOR = '─' * LINE_WIDTH
DOUBLE_SEPARATOR = '=' * LINE_WIDTH


def _format_grouped_issues(issues: List[str], game_date: date) -> List[str]:
    """
    Group similar issues together for more concise display.

    Example:
        Before: 5 lines of "X has no data for 2021-10-19"
        After: "✗ Missing data (5 tables): table1, table2, table3, table4, table5"
    """
    lines = []
    date_str = str(game_date)

    # Group by issue type
    no_data_tables = []
    missing_players_issues = []
    processor_failures = []
    other_issues = []

    for issue in issues:
        if f"has no data for {date_str}" in issue:
            # Extract table name (e.g., "player_game_summary has no data for...")
            table_name = issue.split(" has no data")[0]
            no_data_tables.append(table_name)
        elif "processor(s) failed" in issue:
            processor_failures.append(issue)
        elif "missing" in issue.lower() and "player" in issue.lower():
            missing_players_issues.append(issue)
        else:
            other_issues.append(issue)

    # Format grouped "no data" issues
    if no_data_tables:
        if len(no_data_tables) <= 3:
            # Few tables - show full names
            lines.append(f"  ✗ No data for {date_str}: {', '.join(no_data_tables)}")
        else:
            # Many tables - summarize
            lines.append(f"  ✗ No data for {date_str} ({len(no_data_tables)} tables):")
            lines.append(f"    {', '.join(no_data_tables)}")

    # Format processor failures (keep as-is, usually just one)
    for issue in processor_failures:
        lines.append(f"  ✗ {issue}")

    # Format missing players issues
    for issue in missing_players_issues:
        lines.append(f"  ✗ {issue}")

    # Format other issues
    for issue in other_issues:
        lines.append(f"  ✗ {issue}")

    return lines


@dataclass
class ValidationReport:
    """Complete validation report for formatting."""
    game_date: date
    schedule_context: ScheduleContext
    player_universe: PlayerUniverse
    phase_results: List[PhaseValidationResult]
    overall_status: str
    issues: List[str]
    warnings: List[str]
    run_history: Optional[RunHistorySummary] = None
    missing_players: Optional[List[str]] = None
    time_context: Optional[TimeContext] = None
    orchestration_state: Optional[OrchestrationState] = None


def format_validation_result(
    report: ValidationReport,
    use_color: bool = True,
    verbose: bool = False,
    show_missing: bool = False,
) -> str:
    """
    Format a complete validation report for terminal display.

    Args:
        report: ValidationReport to format
        use_color: Whether to use ANSI color codes
        verbose: Whether to show detailed run history
        show_missing: Whether to show missing player lists

    Returns:
        Formatted string for terminal output
    """
    lines = []

    # Header
    lines.append(_format_header(report, use_color))

    # Time Context (for today/yesterday)
    if report.time_context and (report.time_context.is_today or report.time_context.is_yesterday):
        lines.append(_format_section("TIME CONTEXT", use_color))
        lines.append(format_time_context(report.time_context))
        lines.append("")

    # Schedule Context
    lines.append(_format_section("SCHEDULE CONTEXT", use_color))
    lines.append(format_schedule_summary(report.schedule_context))
    lines.append("")

    # Orchestration State (for today/yesterday with Firestore)
    if (report.orchestration_state and
        report.orchestration_state.firestore_available and
        report.time_context and
        (report.time_context.is_today or report.time_context.is_yesterday)):
        lines.append(_format_section("ORCHESTRATION STATUS", use_color))
        if verbose:
            lines.append(format_orchestration_verbose(report.orchestration_state))
        else:
            lines.append(format_orchestration_state(report.orchestration_state))
        lines.append("")

    # Player Universe
    lines.append(_format_section("PLAYER UNIVERSE", use_color))
    lines.append(format_player_universe(report.player_universe))
    lines.append("")

    # Phase results
    for phase_result in report.phase_results:
        lines.append(_format_phase_result(phase_result, use_color, verbose))
        lines.append("")

    # Verbose: Run History Details
    if verbose and report.run_history:
        lines.append(_format_section("RUN HISTORY (VERBOSE)", use_color))
        lines.append(format_run_history_verbose(report.run_history))
        lines.append("")

    # Show missing players
    if show_missing and report.missing_players:
        lines.append(_format_missing_players(report.missing_players, use_color))
        lines.append("")

    # Issues and Warnings (including run history errors)
    has_issues = report.issues or report.warnings
    has_run_errors = (
        report.run_history and
        (report.run_history.errors or report.run_history.dependency_failures or report.run_history.alerts_sent)
    )

    if has_issues or has_run_errors:
        lines.append(DOUBLE_SEPARATOR)
        lines.append("ISSUES & WARNINGS")
        lines.append(DOUBLE_SEPARATOR)
        lines.append("")

        # Run history errors
        if has_run_errors:
            lines.append(format_errors_section(report.run_history))

        # Validation issues (grouped by type)
        if report.issues:
            lines.append("VALIDATION ISSUES:")
            lines.extend(_format_grouped_issues(report.issues, report.game_date))
            lines.append("")

        if report.warnings:
            lines.append("VALIDATION WARNINGS:")
            for warning in report.warnings:
                lines.append(f"  ⚠ {warning}")
            lines.append("")

    # Summary
    lines.append(_format_summary(report, use_color))

    return '\n'.join(lines)


def print_validation_result(
    report: ValidationReport,
    use_color: bool = None,
    verbose: bool = False,
    show_missing: bool = False,
):
    """
    Print validation report to stdout.

    Args:
        report: ValidationReport to print
        use_color: Whether to use colors (auto-detects if None)
        verbose: Whether to show detailed run history
        show_missing: Whether to show missing player lists
    """
    if use_color is None:
        use_color = sys.stdout.isatty()

    output = format_validation_result(report, use_color, verbose, show_missing)
    print(output)


def _format_missing_players(missing: List[str], use_color: bool) -> str:
    """Format missing players section."""
    lines = []
    lines.append(DOUBLE_SEPARATOR)
    lines.append("MISSING PLAYERS")
    lines.append(DOUBLE_SEPARATOR)
    lines.append("")

    lines.append(f"Total Missing: {len(missing)}")
    lines.append("")

    # Group by likely team (if team_abbr in player_lookup)
    lines.append("Players:")
    for i, player in enumerate(missing[:50]):  # Limit to 50
        lines.append(f"  {i+1}. {player}")

    if len(missing) > 50:
        lines.append(f"  ... and {len(missing) - 50} more")

    return '\n'.join(lines)


def _format_header(report: ValidationReport, use_color: bool) -> str:
    """Format the header section."""
    lines = []

    lines.append(DOUBLE_SEPARATOR)

    # Title with date info
    date_str = report.game_date.strftime('%Y-%m-%d')
    season_info = f"{report.schedule_context.season_string}, Day {report.schedule_context.season_day}"

    if report.schedule_context.is_bootstrap:
        bootstrap_tag = " [BOOTSTRAP]"
    else:
        bootstrap_tag = ""

    title = f"PIPELINE VALIDATION: {date_str} ({season_info}{bootstrap_tag})"
    lines.append(title)

    # Season progress indicator
    season_day = report.schedule_context.season_day
    # Regular season is ~170 days (Oct 22 - Apr 13)
    REGULAR_SEASON_DAYS = 170
    season_pct = min(100, (season_day / REGULAR_SEASON_DAYS) * 100)
    season_progress = f"Season Progress: {season_pct:.0f}% ({season_day} of ~{REGULAR_SEASON_DAYS} days)"
    lines.append(season_progress)

    lines.append(DOUBLE_SEPARATOR)
    lines.append("")

    return '\n'.join(lines)


def _format_section(title: str, use_color: bool) -> str:
    """Format a section header."""
    return f"{title}\n{SEPARATOR}"


def _format_phase_result(result: PhaseValidationResult, use_color: bool, verbose: bool = False) -> str:
    """Format a single phase result."""
    lines = []

    # Phase header
    phase_name = _get_phase_name(result.phase)
    status_sym = STATUS_SYMBOLS.get(result.status, '?')

    if result.status == ValidationStatus.BOOTSTRAP_SKIP:
        header_note = " (Bootstrap - Expected Empty)"
    elif result.status == ValidationStatus.NOT_APPLICABLE:
        header_note = " (N/A)"
    else:
        header_note = ""

    lines.append(DOUBLE_SEPARATOR)
    lines.append(f"PHASE {result.phase}: {phase_name}{header_note}")
    lines.append(DOUBLE_SEPARATOR)
    lines.append("")

    # Table header
    if result.phase == 1:
        # Phase 1 format (GCS files)
        header = f"{'Source':<30s} {'JSON Files':>12s} {'Expected':>10s} {'Status':>12s}"
        lines.append(header)
        lines.append(SEPARATOR)

        for table_name, table in result.tables.items():
            json_count = table.metadata.get('json_files', table.record_count) if table.metadata else table.record_count
            expected = table.expected_count
            status_str = _format_status(table.status, use_color)

            line = f"{table_name:<30s} {json_count:>12d} {expected:>10d} {status_str:>12s}"
            lines.append(line)

            # Show GCS path hint if missing
            if table.status == ValidationStatus.MISSING and table.metadata:
                gcs_path = table.metadata.get('gcs_path', '')
                if gcs_path:
                    lines.append(f"{'':>30s} └─ gs://nba-scraped-data/{gcs_path}")

    elif result.phase == 2:
        # Phase 2 format
        header = f"{'Source':<40s} {'Records':>10s} {'Status':>10s}"
        lines.append(header)
        lines.append(SEPARATOR)

        for table_name, table in result.tables.items():
            status_sym = STATUS_SYMBOLS.get(table.status, '?')
            record_str = str(table.record_count) if table.record_count > 0 else '-'
            status_str = _format_status(table.status, use_color)

            line = f"{table_name:<40s} {record_str:>10s} {status_str:>10s}"
            lines.append(line)

    elif result.phase in (3, 4):
        # Phase 3/4 format with quality
        has_quality = any(t.quality for t in result.tables.values())

        if has_quality:
            header = f"{'Table':<35s} {'Records':>10s} {'Expected':>10s} {'Quality':>15s} {'Status':>10s}"
        else:
            header = f"{'Table':<35s} {'Records':>10s} {'Expected':>10s} {'Status':>10s}"
        lines.append(header)
        lines.append(SEPARATOR)

        for table_name, table in result.tables.items():
            record_str = str(table.record_count)

            # Show "—" for expected during bootstrap (instead of confusing "0")
            if table.status == ValidationStatus.BOOTSTRAP_SKIP:
                expected_str = "—"
            elif table.expected_count > 0:
                expected_str = f"{table.record_count}/{table.expected_count}"
                pct = table.completeness_pct
                expected_str = f"{expected_str} ({pct:.0f}%)"
            else:
                expected_str = record_str

            if has_quality and table.quality:
                quality_str = table.quality.to_summary_string()
            else:
                quality_str = "-"

            status_str = _format_status(table.status, use_color)

            if has_quality:
                line = f"{table_name:<35s} {record_str:>10s} {expected_str:>10s} {quality_str:>15s} {status_str:>10s}"
            else:
                line = f"{table_name:<35s} {record_str:>10s} {expected_str:>10s} {status_str:>10s}"
            lines.append(line)

            # Show prop breakdown if available (for player tables)
            if table.metadata.get('prop_summary'):
                lines.append(f"{'':>35s} └─ Props: {table.metadata['prop_summary']}")

    elif result.phase == 5:
        # Phase 5 format (predictions)
        header = f"{'Table':<35s} {'Predictions':>12s} {'Players':>12s} {'Expected':>12s} {'Status':>10s}"
        lines.append(header)
        lines.append(SEPARATOR)

        for table_name, table in result.tables.items():
            pred_str = str(table.record_count)
            player_str = str(table.player_count)
            # Show "—" for expected during bootstrap (instead of confusing "0/0")
            if table.status == ValidationStatus.BOOTSTRAP_SKIP:
                expected_str = "—"
            else:
                expected_str = f"{table.player_count}/{table.expected_players}"
            status_str = _format_status(table.status, use_color)

            line = f"{table_name:<35s} {pred_str:>12s} {player_str:>12s} {expected_str:>12s} {status_str:>10s}"
            lines.append(line)

            # Show prop breakdown if available
            if table.metadata.get('prop_summary'):
                lines.append(f"{'':>35s} └─ Props: {table.metadata['prop_summary']}")

    # Phase summary
    lines.append("")
    status_sym = STATUS_SYMBOLS.get(result.status, '?')
    status_text = _status_to_text(result.status)
    summary_line = f"→ Phase {result.phase}: {status_sym} {status_text}"

    if result.total_records > 0:
        summary_line += f" ({result.total_records} records)"

    lines.append(summary_line)

    return '\n'.join(lines)


def _format_issues_section(issues: List[str], warnings: List[str], use_color: bool) -> str:
    """Format issues and warnings section."""
    lines = []

    lines.append(DOUBLE_SEPARATOR)
    lines.append("ISSUES & WARNINGS")
    lines.append(DOUBLE_SEPARATOR)
    lines.append("")

    if issues:
        lines.append("ISSUES:")
        for issue in issues:
            lines.append(f"  ✗ {issue}")
        lines.append("")

    if warnings:
        lines.append("WARNINGS:")
        for warning in warnings:
            lines.append(f"  ⚠ {warning}")

    return '\n'.join(lines)


def _format_summary(report: ValidationReport, use_color: bool) -> str:
    """Format the summary section."""
    lines = []

    lines.append(DOUBLE_SEPARATOR)
    lines.append("SUMMARY")
    lines.append(DOUBLE_SEPARATOR)
    lines.append("")

    # Overall status
    lines.append(f"Overall Status:    {report.overall_status}")

    # Phase summaries
    for phase_result in report.phase_results:
        phase_name = _get_phase_name(phase_result.phase)
        status_sym = STATUS_SYMBOLS.get(phase_result.status, '?')
        status_text = _status_to_text(phase_result.status)
        lines.append(f"Phase {phase_result.phase} ({phase_name[:7]}):  {status_sym} {status_text}")

    lines.append("")

    # Issue count
    if report.issues:
        lines.append(f"Issues:            {len(report.issues)}")
    if report.warnings:
        lines.append(f"Warnings:          {len(report.warnings)}")

    lines.append("")

    # Progress bar
    lines.append(_format_progress_bar(report, use_color))

    lines.append(DOUBLE_SEPARATOR)

    return '\n'.join(lines)


def _format_progress_bar(report: ValidationReport, use_color: bool) -> str:
    """
    Format a visual progress bar showing pipeline completion.

    Weights:
    - Bootstrap mode: P2=40%, P3=60% (P4/P5 not expected)
    - Regular mode: P2=15%, P3=25%, P4=25%, P5=35%

    Colors:
    - Green: 90-100% (complete)
    - Yellow: 50-89% (partial)
    - Red: 0-49% (needs work)
    - Blue: Bootstrap skip (expected)
    """
    lines = []
    is_bootstrap = report.schedule_context.is_bootstrap

    # Calculate phase completion percentages
    phase_pcts = {}
    for phase_result in report.phase_results:
        phase = phase_result.phase
        status = phase_result.status

        if status == ValidationStatus.COMPLETE:
            phase_pcts[phase] = 100.0
        elif status == ValidationStatus.BOOTSTRAP_SKIP:
            phase_pcts[phase] = 100.0  # Expected empty = complete for this context
        elif status == ValidationStatus.NOT_APPLICABLE:
            phase_pcts[phase] = 100.0  # N/A = doesn't count against us
        elif status == ValidationStatus.PARTIAL:
            # Calculate actual completion from tables
            if phase_result.tables:
                total_expected = sum(t.expected_count for t in phase_result.tables.values() if t.expected_count > 0)
                total_actual = sum(t.record_count for t in phase_result.tables.values())
                if total_expected > 0:
                    phase_pcts[phase] = (total_actual / total_expected) * 100
                else:
                    phase_pcts[phase] = 50.0  # Default for partial
            else:
                phase_pcts[phase] = 50.0
        else:  # MISSING or ERROR
            phase_pcts[phase] = 0.0

    # Get set of validated phases
    validated_phases = {p.phase for p in report.phase_results}

    # Weights based on mode
    # Phase 1 (GCS) is prerequisite for Phase 2, so lower weight
    # Note: When chain view is used, P1/P2 are not in phase_results
    if is_bootstrap:
        weights = {1: 0.10, 2: 0.35, 3: 0.55, 4: 0.0, 5: 0.0}
    else:
        weights = {1: 0.05, 2: 0.15, 3: 0.25, 4: 0.25, 5: 0.30}

    # Only use weights for validated phases, redistribute others
    active_weights = {p: w for p, w in weights.items() if p in validated_phases}
    if active_weights:
        # Normalize weights to sum to 1
        weight_sum = sum(active_weights.values())
        if weight_sum > 0:
            active_weights = {p: w / weight_sum for p, w in active_weights.items()}
    else:
        active_weights = weights  # Fallback

    # Calculate weighted total
    total_pct = sum(phase_pcts.get(p, 0) * w for p, w in active_weights.items())

    # Build progress bar (50 chars wide)
    BAR_WIDTH = 50
    filled = int(total_pct / 100 * BAR_WIDTH)
    empty = BAR_WIDTH - filled

    # Color based on completion
    if total_pct >= 90:
        bar_color = '\033[92m' if use_color else ''  # Green
    elif total_pct >= 50:
        bar_color = '\033[93m' if use_color else ''  # Yellow
    else:
        bar_color = '\033[91m' if use_color else ''  # Red

    reset = RESET if use_color else ''

    bar = f"{bar_color}{'█' * filled}{reset}{'░' * empty}"
    lines.append(f"Pipeline Progress: [{bar}] {total_pct:.0f}%")

    # Phase breakdown with mini indicators (match actual status, not just percentage)
    # Only show phases that were actually validated (validated_phases defined above)
    phase_indicators = []

    for phase in [1, 2, 3, 4, 5]:
        # Skip phases that weren't validated (e.g., P1/P2 when in chain view)
        if phase not in validated_phases:
            continue

        phase_result = next((p for p in report.phase_results if p.phase == phase), None)

        if phase_result:
            status = phase_result.status
            if status == ValidationStatus.COMPLETE:
                sym = '✓'
                color = '\033[92m' if use_color else ''  # Green
            elif status == ValidationStatus.BOOTSTRAP_SKIP:
                sym = '⊘'
                color = '\033[94m' if use_color else ''  # Blue
            elif status == ValidationStatus.NOT_APPLICABLE:
                sym = '─'
                color = '\033[90m' if use_color else ''  # Gray
            elif status == ValidationStatus.PARTIAL:
                sym = '△'
                color = '\033[93m' if use_color else ''  # Yellow
            else:  # MISSING or ERROR
                sym = '○'
                color = '\033[91m' if use_color else ''  # Red

            phase_indicators.append(f"{color}P{phase}{sym}{reset}")

    lines.append(f"                   {' '.join(phase_indicators)}")

    # Next action suggestion
    lines.append("")
    next_action = _get_next_action(report, phase_pcts, is_bootstrap)
    if next_action:
        lines.append(f"Next Action: {next_action}")

    return '\n'.join(lines)


def _get_next_action(report: ValidationReport, phase_pcts: dict, is_bootstrap: bool) -> str:
    """Determine the next action needed."""
    # Check phases in order
    for phase in [2, 3, 4, 5]:
        phase_result = next((p for p in report.phase_results if p.phase == phase), None)
        if not phase_result:
            continue

        if phase_result.status == ValidationStatus.NOT_APPLICABLE:
            return "No games scheduled - nothing to do"

        if phase_result.status == ValidationStatus.BOOTSTRAP_SKIP:
            continue  # Expected, move on

        if is_bootstrap and phase in [4, 5]:
            continue  # Not expected during bootstrap

        pct = phase_pcts.get(phase, 0)
        if pct < 90:
            phase_name = _get_phase_name(phase)
            if pct == 0:
                return f"Run {phase_name} backfill (0% complete)"
            else:
                return f"Complete {phase_name} backfill ({pct:.0f}% done)"

    # All complete
    if is_bootstrap:
        return "Bootstrap complete - Phase 4/5 will run after bootstrap period"
    return "All phases complete!"


def _get_phase_name(phase: int) -> str:
    """Get human-readable phase name."""
    names = {
        1: 'GCS JSON',
        2: 'RAW DATA (BQ)',
        3: 'ANALYTICS',
        4: 'PRECOMPUTE',
        5: 'PREDICTIONS',
    }
    return names.get(phase, f'PHASE {phase}')


def _format_status(status: ValidationStatus, use_color: bool) -> str:
    """Format status with optional color."""
    symbol = STATUS_SYMBOLS.get(status, '?')

    # Use short status names for table display
    short_names = {
        ValidationStatus.COMPLETE: 'Complete',
        ValidationStatus.PARTIAL: 'Partial',
        ValidationStatus.MISSING: 'Missing',
        ValidationStatus.BOOTSTRAP_SKIP: 'Bootstrap',
        ValidationStatus.NOT_APPLICABLE: 'N/A',
        ValidationStatus.ERROR: 'Error',
    }
    text = short_names.get(status, status.value)

    if use_color:
        color = STATUS_COLORS.get(status, '')
        return f"{color}{symbol} {text}{RESET}"
    else:
        return f"{symbol} {text}"


def _status_to_text(status: ValidationStatus) -> str:
    """Convert status to human-readable text."""
    mapping = {
        ValidationStatus.COMPLETE: 'Complete',
        ValidationStatus.PARTIAL: 'Partial - needs attention',
        ValidationStatus.MISSING: 'Missing - needs backfill',
        ValidationStatus.BOOTSTRAP_SKIP: 'Bootstrap skip (expected)',
        ValidationStatus.NOT_APPLICABLE: 'Not applicable',
        ValidationStatus.ERROR: 'Error during validation',
    }
    return mapping.get(status, status.value)


# =============================================================================
# CHAIN VIEW FORMATTING (V2)
# =============================================================================

# Chain status symbols
CHAIN_STATUS_SYMBOLS = {
    'complete': '✓',
    'partial': '△',
    'missing': '○',
}

# Source status symbols
SOURCE_STATUS_SYMBOLS = {
    'primary': '✓ Primary',
    'fallback': '✓ Fallback',
    'available': '✓ Available',
    'missing': '○ Missing',
    'virtual': '⊘ Virtual',
}

# Severity order for sorting (critical first)
SEVERITY_ORDER = {'critical': 0, 'warning': 1, 'info': 2}

# Quality tier colors
QUALITY_TIER_COLORS = {
    'gold': '\033[92m',    # Green - highest quality
    'silver': '\033[93m',  # Yellow - fallback quality
    'bronze': '\033[33m',  # Orange/brown - lowest quality
}


def format_chain_section(
    chain_validations: dict,
    use_color: bool = True,
) -> str:
    """
    Format all chains in a unified view for Phase 1-2 data sources.

    Args:
        chain_validations: Dict mapping chain_name -> ChainValidation
        use_color: Whether to use ANSI color codes

    Returns:
        Formatted string for terminal output
    """
    from typing import Dict
    lines = []

    lines.append(DOUBLE_SEPARATOR)
    lines.append("PHASE 1-2: DATA SOURCES BY CHAIN")
    lines.append(DOUBLE_SEPARATOR)
    lines.append("")

    # Sort chains by severity (critical first), then by name
    sorted_chains = sorted(
        chain_validations.items(),
        key=lambda x: (SEVERITY_ORDER.get(x[1].chain.severity, 3), x[0])
    )

    # Format each chain
    for chain_name, chain_val in sorted_chains:
        lines.extend(_format_single_chain(chain_val, use_color))
        lines.append("")

    # Summary
    complete_count = sum(1 for _, cv in sorted_chains if cv.status == 'complete')
    partial_count = sum(1 for _, cv in sorted_chains if cv.status == 'partial')
    missing_count = sum(1 for _, cv in sorted_chains if cv.status == 'missing')
    fallback_count = sum(1 for _, cv in sorted_chains if cv.fallback_used)
    total = len(sorted_chains)

    summary_parts = [f"{complete_count}/{total} chains complete"]
    if fallback_count > 0:
        summary_parts.append(f"{fallback_count} using fallback")
    if partial_count > 0:
        summary_parts.append(f"{partial_count} partial")
    if missing_count > 0:
        summary_parts.append(f"{missing_count} missing")

    lines.append(f"→ Data Sources: {', '.join(summary_parts)}")

    return '\n'.join(lines)


def _format_single_chain(chain_val: ChainValidation, use_color: bool) -> list:
    """
    Format a single chain with its sources.

    Args:
        chain_val: ChainValidation result
        use_color: Whether to use ANSI color codes

    Returns:
        List of formatted lines
    """
    lines = []

    chain = chain_val.chain
    status_symbol = CHAIN_STATUS_SYMBOLS.get(chain_val.status, '?')

    # Status color
    if use_color:
        if chain_val.status == 'complete':
            status_color = '\033[92m'  # Green
        elif chain_val.status == 'partial':
            status_color = '\033[93m'  # Yellow
        else:  # missing
            status_color = '\033[91m'  # Red
        reset = RESET
    else:
        status_color = ''
        reset = ''

    # Chain header line
    # Format: "Chain: player_boxscores (critical) ─────────── Status: ✓ Complete"
    chain_header = f"Chain: {chain.name} ({chain.severity})"
    padding_len = 55 - len(chain_header)
    padding = '─' * max(padding_len, 3)
    status_text = f"{status_color}{status_symbol} {chain_val.status.title()}{reset}"
    lines.append(f"{chain_header} {padding} Status: {status_text}")

    # Source table header
    lines.append("  Source                              GCS JSON    BQ Records   Quality   Status")
    lines.append("  " + "─" * 80)

    # Format each source
    for sv in chain_val.sources:
        src = sv.source

        # Primary indicator
        if src.is_primary:
            prefix = "  ★ "
        else:
            prefix = "    "

        # Source name (truncate/pad to 32 chars)
        name = src.name[:32].ljust(32)

        # GCS column (8 chars, right-aligned)
        if sv.gcs_file_count is not None:
            gcs_str = str(sv.gcs_file_count).rjust(8)
        else:
            gcs_str = "-".rjust(8)

        # BQ column (12 chars, right-aligned)
        if src.is_virtual:
            bq_str = "-".rjust(12)
        else:
            bq_str = str(sv.bq_record_count).rjust(12)

        # Quality tier (8 chars, left-aligned) with color
        quality_tier = src.quality_tier
        if use_color:
            quality_color = QUALITY_TIER_COLORS.get(quality_tier, '')
            quality_str = f"{quality_color}{quality_tier.ljust(8)}{RESET}"
        else:
            quality_str = quality_tier.ljust(8)

        # Status (with color if enabled)
        status_text = SOURCE_STATUS_SYMBOLS.get(sv.status, sv.status)
        if use_color:
            if sv.status in ('primary', 'fallback', 'available'):
                status_color = '\033[92m'  # Green
            elif sv.status == 'virtual':
                status_color = '\033[94m'  # Blue
            else:  # missing
                status_color = '\033[91m'  # Red
            status_str = f"{status_color}{status_text}{RESET}"
        else:
            status_str = status_text

        lines.append(f"{prefix}{name} {gcs_str} {bq_str}   {quality_str}  {status_str}")

    # Impact message if present
    if chain_val.impact_message:
        lines.append(f"  └─ {chain_val.impact_message}")

    return lines


def format_chain_progress_bar(
    chain_validations: dict,
    report: 'ValidationReport',
    use_color: bool = True,
) -> str:
    """
    Format a progress bar that includes chain status.

    Args:
        chain_validations: Dict mapping chain_name -> ChainValidation
        report: Full validation report (for other phase info)
        use_color: Whether to use ANSI color codes

    Returns:
        Formatted progress bar string
    """
    lines = []

    # Calculate chain completion
    complete_chains = sum(1 for cv in chain_validations.values() if cv.status == 'complete')
    total_chains = len(chain_validations)
    chain_pct = (complete_chains / total_chains * 100) if total_chains > 0 else 0

    # Get Phase 3-5 status from report
    phase_pcts = {}
    for phase_result in report.phase_results:
        phase = phase_result.phase
        if phase_result.status == ValidationStatus.COMPLETE:
            phase_pcts[phase] = 100.0
        elif phase_result.status == ValidationStatus.BOOTSTRAP_SKIP:
            phase_pcts[phase] = 100.0
        elif phase_result.status == ValidationStatus.NOT_APPLICABLE:
            phase_pcts[phase] = 100.0
        elif phase_result.status == ValidationStatus.PARTIAL:
            phase_pcts[phase] = 50.0
        else:
            phase_pcts[phase] = 0.0

    # Weighted total (chains replace P1-P2)
    is_bootstrap = report.schedule_context.is_bootstrap
    if is_bootstrap:
        weights = {'chains': 0.45, 3: 0.55, 4: 0.0, 5: 0.0}
    else:
        weights = {'chains': 0.20, 3: 0.25, 4: 0.25, 5: 0.30}

    total_pct = (
        chain_pct * weights['chains'] +
        phase_pcts.get(3, 0) * weights[3] +
        phase_pcts.get(4, 0) * weights[4] +
        phase_pcts.get(5, 0) * weights[5]
    )

    # Build progress bar
    BAR_WIDTH = 50
    filled = int(total_pct / 100 * BAR_WIDTH)
    empty = BAR_WIDTH - filled

    if use_color:
        if total_pct >= 90:
            bar_color = '\033[92m'  # Green
        elif total_pct >= 50:
            bar_color = '\033[93m'  # Yellow
        else:
            bar_color = '\033[91m'  # Red
        reset = RESET
    else:
        bar_color = ''
        reset = ''

    bar = f"{bar_color}{'█' * filled}{reset}{'░' * empty}"
    lines.append(f"Pipeline Progress: [{bar}] {total_pct:.0f}%")

    # Phase indicators with chain summary
    indicators = []

    # P1-2 (chains)
    if chain_pct >= 90:
        sym, color = '✓', '\033[92m' if use_color else ''
    elif chain_pct >= 50:
        sym, color = '△', '\033[93m' if use_color else ''
    else:
        sym, color = '○', '\033[91m' if use_color else ''
    indicators.append(f"{color}P1-2{sym}{reset}")

    # P3-5
    for phase in [3, 4, 5]:
        phase_result = next((p for p in report.phase_results if p.phase == phase), None)
        if phase_result:
            status = phase_result.status
            if status == ValidationStatus.COMPLETE:
                sym, color = '✓', '\033[92m' if use_color else ''
            elif status == ValidationStatus.BOOTSTRAP_SKIP:
                sym, color = '⊘', '\033[94m' if use_color else ''
            elif status == ValidationStatus.NOT_APPLICABLE:
                sym, color = '─', '\033[90m' if use_color else ''
            elif status == ValidationStatus.PARTIAL:
                sym, color = '△', '\033[93m' if use_color else ''
            else:
                sym, color = '○', '\033[91m' if use_color else ''
            indicators.append(f"{color}P{phase}{sym}{reset}")

    chain_summary = f"({complete_chains}/{total_chains} chains complete)"
    lines.append(f"                   {' '.join(indicators)}  {chain_summary}")

    return '\n'.join(lines)


# =============================================================================
# MAINTENANCE SECTION FORMATTING
# =============================================================================

def format_maintenance_section(
    maintenance: MaintenanceValidation,
    use_color: bool = True,
) -> str:
    """
    Format the daily maintenance section (roster & registry).

    Args:
        maintenance: MaintenanceValidation result
        use_color: Whether to use ANSI color codes

    Returns:
        Formatted string for terminal output
    """
    if maintenance is None:
        return ""

    lines = []

    lines.append(DOUBLE_SEPARATOR)
    lines.append("DAILY MAINTENANCE (Roster & Registry)")
    lines.append(DOUBLE_SEPARATOR)
    lines.append("")

    # Roster chain
    if maintenance.roster_chain:
        lines.extend(_format_roster_chain(maintenance.roster_chain, use_color))
        lines.append("")

    # Registry status
    if maintenance.registry_status:
        lines.extend(_format_registry_status(maintenance.registry_status, use_color))
        lines.append("")

    # Unresolved players warning
    if maintenance.unresolved_players > 0:
        lines.append(f"Unresolved Players: {maintenance.unresolved_players}")
        if maintenance.unresolved_players > 100:
            lines.append("  └─ Consider running player resolution job")
        lines.append("")

    # Overall status
    if maintenance.is_current:
        status = "✓ Current"
        color = '\033[92m' if use_color else ''
    else:
        status = "△ Stale - needs refresh"
        color = '\033[93m' if use_color else ''

    reset = RESET if use_color else ''
    lines.append(f"→ Maintenance Status: {color}{status}{reset}")

    return '\n'.join(lines)


def _format_roster_chain(roster_chain: ChainValidation, use_color: bool) -> list:
    """Format the roster chain status."""
    lines = []

    status_symbol = CHAIN_STATUS_SYMBOLS.get(roster_chain.status, '?')
    if use_color:
        if roster_chain.status == 'complete':
            color = '\033[92m'
        elif roster_chain.status == 'partial':
            color = '\033[93m'
        else:
            color = '\033[91m'
        reset = RESET
    else:
        color = ''
        reset = ''

    lines.append(f"Chain: player_roster (critical) ─────────────────── Status: {color}{status_symbol} {roster_chain.status.title()}{reset}")

    # Source table
    lines.append("  Source                              Records    Quality   Status")
    lines.append("  " + "─" * 64)

    for sv in roster_chain.sources:
        src = sv.source
        prefix = "  ★ " if src.is_primary else "    "

        name = src.name[:32].ljust(32)
        records = str(sv.bq_record_count).rjust(8)

        # Quality tier with color
        quality_tier = src.quality_tier
        if use_color:
            quality_color = QUALITY_TIER_COLORS.get(quality_tier, '')
            quality = f"{quality_color}{quality_tier.ljust(8)}{RESET}"
        else:
            quality = quality_tier.ljust(8)

        status_text = SOURCE_STATUS_SYMBOLS.get(sv.status, sv.status)
        if use_color:
            if sv.status in ('primary', 'fallback', 'available'):
                status_color = '\033[92m'
            else:
                status_color = '\033[91m'
            status_str = f"{status_color}{status_text}{RESET}"
        else:
            status_str = status_text

        lines.append(f"{prefix}{name} {records}    {quality}  {status_str}")

    return lines


def _format_registry_status(registry, use_color: bool) -> list:
    """Format registry status."""
    lines = []

    lines.append("Registry Status:")

    # Total players
    lines.append(f"  nba_players_registry          {registry.total_players:>8,} players")

    # Last update
    if registry.last_update:
        update_str = registry.last_update.strftime('%Y-%m-%d %H:%M')
        staleness = registry.staleness_days

        if staleness <= 2:
            status = "✓ Current"
            color = '\033[92m' if use_color else ''
        elif staleness <= 7:
            status = f"△ {staleness} days old"
            color = '\033[93m' if use_color else ''
        else:
            status = f"○ {staleness} days old (STALE)"
            color = '\033[91m' if use_color else ''

        reset = RESET if use_color else ''
        lines.append(f"  Last update: {update_str}            {color}{status}{reset}")
    else:
        lines.append("  Last update: Unknown")

    return lines
