"""
Firestore Orchestration State

Queries Firestore for orchestration completion status.
Shows "18/21 processors complete" for live monitoring.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProcessorStatus:
    """Status of a single processor in Firestore."""
    processor_name: str
    completed_at: Optional[datetime] = None
    status: str = 'pending'
    record_count: int = 0


@dataclass
class PhaseCompletionState:
    """Completion state for a phase from Firestore."""
    phase: int
    game_date: date
    collection_name: str

    # Processor statuses
    processors: Dict[str, ProcessorStatus] = field(default_factory=dict)

    # Aggregate info
    expected_count: int = 0
    completed_count: int = 0
    triggered: bool = False
    stall_alert_sent: bool = False

    @property
    def completion_pct(self) -> float:
        if self.expected_count == 0:
            return 0.0
        return (self.completed_count / self.expected_count) * 100

    @property
    def is_complete(self) -> bool:
        return self.completed_count >= self.expected_count


@dataclass
class OrchestrationState:
    """Complete orchestration state for a date."""
    game_date: date
    phases: Dict[int, PhaseCompletionState] = field(default_factory=dict)
    firestore_available: bool = True
    error_message: Optional[str] = None


def get_orchestration_state(game_date: date) -> OrchestrationState:
    """
    Get orchestration state from Firestore.

    Args:
        game_date: Date to check

    Returns:
        OrchestrationState with completion info
    """
    state = OrchestrationState(game_date=game_date)

    try:
        from google.cloud import firestore
        db = firestore.Client()

        # Check Phase 2 completion
        state.phases[2] = _get_phase_completion(
            db, game_date,
            collection='phase2_completion',
            expected_count=21,
            phase=2
        )

        # Check Phase 3 completion
        state.phases[3] = _get_phase_completion(
            db, game_date,
            collection='phase3_completion',
            expected_count=5,
            phase=3
        )

    except ImportError:
        state.firestore_available = False
        state.error_message = "google-cloud-firestore not installed"
        logger.warning("Firestore not available: google-cloud-firestore not installed")
    except Exception as e:
        state.firestore_available = False
        state.error_message = str(e)
        logger.warning(f"Error accessing Firestore: {e}")

    return state


def _get_phase_completion(
    db,
    game_date: date,
    collection: str,
    expected_count: int,
    phase: int,
) -> PhaseCompletionState:
    """Get completion state for a single phase."""

    state = PhaseCompletionState(
        phase=phase,
        game_date=game_date,
        collection_name=collection,
        expected_count=expected_count,
    )

    try:
        date_str = game_date.strftime('%Y-%m-%d')
        doc_ref = db.collection(collection).document(date_str)
        doc = doc_ref.get()

        if not doc.exists:
            return state

        data = doc.to_dict() or {}

        # Parse metadata fields
        state.completed_count = data.get('_completed_count', 0)
        state.triggered = data.get('_triggered', False)
        state.stall_alert_sent = data.get('_stall_alert_sent', False)

        # Parse processor statuses
        for key, value in data.items():
            if key.startswith('_'):
                continue  # Skip metadata fields

            if isinstance(value, dict):
                processor_status = ProcessorStatus(
                    processor_name=key,
                    completed_at=value.get('completed_at'),
                    status=value.get('status', 'unknown'),
                    record_count=value.get('record_count', 0),
                )
                state.processors[key] = processor_status

        # Recalculate completed count from actual processors
        completed = len([p for p in state.processors.values() if p.status == 'success'])
        if completed > 0:
            state.completed_count = completed

    except Exception as e:
        logger.error(f"Error getting {collection} for {game_date}: {e}")

    return state


def format_orchestration_state(state: OrchestrationState) -> str:
    """Format orchestration state for display."""
    lines = []

    if not state.firestore_available:
        lines.append(f"⚠ Firestore not available: {state.error_message}")
        return '\n'.join(lines)

    for phase_num in sorted(state.phases.keys()):
        phase_state = state.phases[phase_num]

        if phase_state.is_complete:
            status = '✓'
            status_text = 'Complete'
        elif phase_state.completed_count > 0:
            status = '△'
            status_text = f'In Progress ({phase_state.completed_count}/{phase_state.expected_count})'
        else:
            status = '○'
            status_text = 'Pending'

        lines.append(f"Phase {phase_num}: {status} {status_text}")

        if phase_state.triggered:
            lines.append(f"         Next phase triggered: Yes")
        if phase_state.stall_alert_sent:
            lines.append(f"         ⚠ Stall alert sent")

    return '\n'.join(lines)


def format_orchestration_verbose(state: OrchestrationState) -> str:
    """Format verbose orchestration state."""
    lines = []

    if not state.firestore_available:
        lines.append(f"⚠ Firestore not available: {state.error_message}")
        return '\n'.join(lines)

    for phase_num in sorted(state.phases.keys()):
        phase_state = state.phases[phase_num]

        lines.append(f"\nPhase {phase_num} Orchestration ({phase_state.collection_name})")
        lines.append("─" * 60)
        lines.append(f"  Completed: {phase_state.completed_count}/{phase_state.expected_count}")
        lines.append(f"  Triggered: {'Yes' if phase_state.triggered else 'No'}")

        if phase_state.processors:
            lines.append("  Processors:")
            for name, proc in sorted(phase_state.processors.items()):
                status_sym = '✓' if proc.status == 'success' else '○'
                time_str = proc.completed_at.strftime('%H:%M:%S') if proc.completed_at else '-'
                lines.append(f"    {status_sym} {name[:30]:<30s} {time_str} ({proc.record_count} records)")

    return '\n'.join(lines)
