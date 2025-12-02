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

        # Validation issues
        if report.issues:
            lines.append("VALIDATION ISSUES:")
            for issue in report.issues:
                lines.append(f"  ✗ {issue}")
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

            if table.expected_count > 0:
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

    # Weights based on mode
    # Phase 1 (GCS) is prerequisite for Phase 2, so lower weight
    if is_bootstrap:
        weights = {1: 0.10, 2: 0.35, 3: 0.55, 4: 0.0, 5: 0.0}
    else:
        weights = {1: 0.05, 2: 0.15, 3: 0.25, 4: 0.25, 5: 0.30}

    # Calculate weighted total
    total_pct = sum(phase_pcts.get(p, 0) * w for p, w in weights.items())

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
    phase_indicators = []
    for phase in [1, 2, 3, 4, 5]:
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
        else:
            sym = '?'
            color = '\033[90m' if use_color else ''  # Gray

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
