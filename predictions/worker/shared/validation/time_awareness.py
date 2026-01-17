"""
Time-Aware Monitoring

Understands the orchestration timeline and provides context-aware
expectations for "today" and "yesterday" validation.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, List
import pytz

# Eastern timezone (NBA games and orchestration use ET)
ET = pytz.timezone('America/New_York')
PT = pytz.timezone('America/Los_Angeles')


@dataclass
class PhaseExpectation:
    """Expected status for a phase at a given time."""
    phase: int
    expected_status: str  # 'complete', 'in_progress', 'pending', 'skip'
    reason: str
    next_run_time: Optional[str] = None


@dataclass
class TimeContext:
    """Time-aware context for validation."""
    game_date: date
    current_time: datetime
    current_time_et: datetime
    current_time_pt: datetime

    # Date relationships
    is_today: bool = False
    is_yesterday: bool = False
    is_historical: bool = False

    # Expected phase statuses
    phase_expectations: Dict[int, PhaseExpectation] = None

    def __post_init__(self):
        if self.phase_expectations is None:
            self.phase_expectations = {}


def get_time_context(game_date: date) -> TimeContext:
    """
    Get time-aware context for a date.

    Args:
        game_date: Date being validated

    Returns:
        TimeContext with expectations based on current time
    """
    # Get current time in multiple timezones
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    now_pt = now_utc.astimezone(PT)

    today = now_et.date()
    yesterday = today - timedelta(days=1)

    ctx = TimeContext(
        game_date=game_date,
        current_time=now_utc,
        current_time_et=now_et,
        current_time_pt=now_pt,
        is_today=(game_date == today),
        is_yesterday=(game_date == yesterday),
        is_historical=(game_date < yesterday),
    )

    # Calculate phase expectations
    ctx.phase_expectations = _calculate_expectations(game_date, now_et)

    return ctx


def _calculate_expectations(game_date: date, now_et: datetime) -> Dict[int, PhaseExpectation]:
    """Calculate expected phase statuses based on time."""
    today = now_et.date()
    yesterday = today - timedelta(days=1)
    hour = now_et.hour

    expectations = {}

    if game_date == today:
        # Today - games haven't completed yet (usually)
        expectations[2] = PhaseExpectation(
            phase=2,
            expected_status='pending',
            reason='Games in progress or not started',
            next_run_time='~midnight after games complete'
        )
        expectations[3] = PhaseExpectation(
            phase=3,
            expected_status='pending',
            reason='Waiting for Phase 2',
            next_run_time='~1:00 AM ET tomorrow'
        )
        expectations[4] = PhaseExpectation(
            phase=4,
            expected_status='pending',
            reason='Waiting for Phase 3',
            next_run_time='~2:00 AM ET tomorrow (CASCADE)'
        )

        if hour < 6:
            expectations[5] = PhaseExpectation(
                phase=5,
                expected_status='pending',
                reason='Scheduled for 6:15 AM ET',
                next_run_time='6:15 AM ET'
            )
        elif hour < 7:
            expectations[5] = PhaseExpectation(
                phase=5,
                expected_status='in_progress',
                reason='Currently running or just completed',
            )
        else:
            expectations[5] = PhaseExpectation(
                phase=5,
                expected_status='complete',
                reason='Ran at 6:15 AM ET',
            )

    elif game_date == yesterday:
        # Yesterday - depending on time, phases may still be running

        if hour < 1:
            # Before 1 AM - Phase 2 still processing
            expectations[2] = PhaseExpectation(
                phase=2,
                expected_status='in_progress',
                reason='Processing after games',
            )
            expectations[3] = PhaseExpectation(
                phase=3,
                expected_status='pending',
                reason='Waiting for Phase 2',
                next_run_time='~1:00 AM ET'
            )
            expectations[4] = PhaseExpectation(
                phase=4,
                expected_status='pending',
                reason='Waiting for Phase 3',
                next_run_time='~2:00 AM ET'
            )
            expectations[5] = PhaseExpectation(
                phase=5,
                expected_status='pending',
                reason='Waiting for Phase 4',
                next_run_time='6:15 AM ET'
            )

        elif hour < 2:
            # 1-2 AM - Phase 2 should be done, Phase 3 running
            expectations[2] = PhaseExpectation(
                phase=2,
                expected_status='complete',
                reason='Should have completed by now',
            )
            expectations[3] = PhaseExpectation(
                phase=3,
                expected_status='in_progress',
                reason='Currently running',
            )
            expectations[4] = PhaseExpectation(
                phase=4,
                expected_status='pending',
                reason='Waiting for Phase 3',
                next_run_time='~2:00 AM ET'
            )
            expectations[5] = PhaseExpectation(
                phase=5,
                expected_status='pending',
                reason='Waiting for Phase 4',
                next_run_time='6:15 AM ET'
            )

        elif hour < 4:
            # 2-4 AM - Phase 4 CASCADE running
            expectations[2] = PhaseExpectation(
                phase=2,
                expected_status='complete',
                reason='Should have completed',
            )
            expectations[3] = PhaseExpectation(
                phase=3,
                expected_status='complete',
                reason='Should have completed',
            )
            expectations[4] = PhaseExpectation(
                phase=4,
                expected_status='in_progress',
                reason='CASCADE running (11 PM PT = 2 AM ET)',
            )
            expectations[5] = PhaseExpectation(
                phase=5,
                expected_status='pending',
                reason='Waiting for Phase 4',
                next_run_time='6:15 AM ET'
            )

        elif hour < 7:
            # 4-7 AM - Phase 4 done, Phase 5 pending or running
            expectations[2] = PhaseExpectation(
                phase=2,
                expected_status='complete',
                reason='Should have completed',
            )
            expectations[3] = PhaseExpectation(
                phase=3,
                expected_status='complete',
                reason='Should have completed',
            )
            expectations[4] = PhaseExpectation(
                phase=4,
                expected_status='complete',
                reason='Should have completed',
            )

            if hour < 6:
                expectations[5] = PhaseExpectation(
                    phase=5,
                    expected_status='pending',
                    reason='Scheduled for 6:15 AM',
                    next_run_time='6:15 AM ET'
                )
            else:
                expectations[5] = PhaseExpectation(
                    phase=5,
                    expected_status='in_progress',
                    reason='Currently running or just completed',
                )

        else:
            # After 7 AM - all phases should be complete
            for phase in [2, 3, 4, 5]:
                expectations[phase] = PhaseExpectation(
                    phase=phase,
                    expected_status='complete',
                    reason='Should have completed',
                )

    else:
        # Historical - all phases should be complete (or never ran)
        for phase in [2, 3, 4, 5]:
            expectations[phase] = PhaseExpectation(
                phase=phase,
                expected_status='complete',
                reason='Historical date - should be complete or needs backfill',
            )

    return expectations


def format_time_context(ctx: TimeContext) -> str:
    """Format time context for display."""
    lines = []

    time_str = ctx.current_time_et.strftime('%I:%M %p ET')
    date_str = ctx.game_date.strftime('%Y-%m-%d')

    if ctx.is_today:
        lines.append(f"Validating: Today ({date_str})")
    elif ctx.is_yesterday:
        lines.append(f"Validating: Yesterday ({date_str})")
    else:
        lines.append(f"Validating: {date_str} (Historical)")

    lines.append(f"Current Time: {time_str}")
    lines.append("")

    lines.append("Expected Phase Status:")
    for phase in sorted(ctx.phase_expectations.keys()):
        exp = ctx.phase_expectations[phase]

        status_sym = {
            'complete': '✓',
            'in_progress': '⏳',
            'pending': '○',
            'skip': '⊘',
        }.get(exp.expected_status, '?')

        line = f"  Phase {phase}: {status_sym} {exp.reason}"
        if exp.next_run_time:
            line += f" → Next: {exp.next_run_time}"
        lines.append(line)

    return '\n'.join(lines)


def get_monitoring_message(ctx: TimeContext, actual_statuses: Dict[int, str]) -> List[str]:
    """
    Get monitoring messages comparing expected vs actual.

    Args:
        ctx: Time context
        actual_statuses: Dict of phase -> actual status

    Returns:
        List of warning/info messages
    """
    messages = []

    for phase, exp in ctx.phase_expectations.items():
        actual = actual_statuses.get(phase, 'unknown')

        # Check for concerning states
        if exp.expected_status == 'complete' and actual == 'missing':
            messages.append(f"⚠ Phase {phase} should be complete but has no data")
        elif exp.expected_status == 'complete' and actual == 'partial':
            messages.append(f"△ Phase {phase} partially complete - may need attention")
        elif exp.expected_status == 'in_progress' and actual == 'complete':
            messages.append(f"✓ Phase {phase} completed earlier than expected")
        elif exp.expected_status == 'pending' and actual == 'complete':
            messages.append(f"✓ Phase {phase} already complete")

    return messages
