"""
Phase 3 Completion Checker - Mode-Aware

Checks Phase 3 processor completion status with awareness of orchestration mode
(overnight vs same_day vs tomorrow), eliminating false "incomplete" alarms.

Usage:
    from shared.validation.phase3_completion_checker import check_phase3_completion

    result = check_phase3_completion(processing_date='2026-02-02')
    print(f"Status: {result['status']}")  # 'complete', 'incomplete', 'unknown'
    print(f"Summary: {result['summary']}")  # "5/5 (overnight)" or "1/1 (same_day)"

Session: 85 (2026-02-02)
"""

from typing import Dict, Set, Optional
from datetime import datetime
from google.cloud import firestore

# Mode expectations (matching orchestration/cloud_functions/phase3_to_phase4/main.py)
MODE_EXPECTATIONS = {
    'overnight': {
        'expected_count': 5,
        'expected_processors': {
            'player_game_summary',
            'team_offense_game_summary',
            'team_defense_game_summary',
            'upcoming_player_game_context',
            'upcoming_team_game_context'
        }
    },
    'same_day': {
        'expected_count': 1,
        'expected_processors': {
            'upcoming_player_game_context'
        }
    },
    'tomorrow': {
        'expected_count': 1,
        'expected_processors': {
            'upcoming_player_game_context'
        }
    }
}


def check_phase3_completion(
    processing_date: Optional[str] = None,
    project_id: str = 'nba-props-platform'
) -> Dict:
    """
    Check Phase 3 completion status for a given processing date with mode awareness.

    Args:
        processing_date: Date string (YYYY-MM-DD) or None for today
        project_id: GCP project ID

    Returns:
        Dict with:
            - status: 'complete', 'incomplete', or 'unknown'
            - mode: Orchestration mode ('overnight', 'same_day', 'tomorrow', or 'unknown')
            - completed_count: Number of processors that completed
            - expected_count: Number of processors expected for this mode
            - completed_processors: Set of processor names that completed
            - expected_processors: Set of processor names expected for this mode
            - summary: Human-readable summary (e.g., "5/5 (overnight)")
            - triggered: Whether Phase 4 was triggered
            - trigger_reason: Why Phase 4 was triggered (if applicable)
    """
    if processing_date is None:
        processing_date = datetime.now().strftime('%Y-%m-%d')

    # Get Firestore document
    db = firestore.Client(project=project_id)
    doc = db.collection('phase3_completion').document(processing_date).get()

    if not doc.exists:
        return {
            'status': 'unknown',
            'mode': 'unknown',
            'completed_count': 0,
            'expected_count': 0,
            'completed_processors': set(),
            'expected_processors': set(),
            'summary': f'No completion record for {processing_date}',
            'triggered': False,
            'trigger_reason': None
        }

    data = doc.to_dict()

    # Extract mode (defaults to 'overnight' if not specified)
    mode = data.get('_mode', 'overnight')

    # Get mode expectations
    expectations = MODE_EXPECTATIONS.get(mode, MODE_EXPECTATIONS['overnight'])
    expected_count = expectations['expected_count']
    expected_processors = expectations['expected_processors']

    # Get completed processors (exclude metadata fields starting with _)
    completed_processors = {k for k in data.keys() if not k.startswith('_')}
    completed_count = len(completed_processors)

    # Determine status
    if completed_count >= expected_count:
        status = 'complete'
    else:
        status = 'incomplete'

    # Get trigger info
    triggered = data.get('_triggered', False)
    trigger_reason = data.get('_trigger_reason', None)

    # Create summary
    summary = f"{completed_count}/{expected_count} ({mode} mode)"

    return {
        'status': status,
        'mode': mode,
        'completed_count': completed_count,
        'expected_count': expected_count,
        'completed_processors': completed_processors,
        'expected_processors': expected_processors,
        'summary': summary,
        'triggered': triggered,
        'trigger_reason': trigger_reason,
        'raw_data': data  # Include full Firestore data for debugging
    }


def format_completion_status(result: Dict, verbose: bool = False) -> str:
    """
    Format completion check result as human-readable string.

    Args:
        result: Result from check_phase3_completion()
        verbose: Include detailed processor breakdown

    Returns:
        Formatted string
    """
    status_emoji = {
        'complete': '✅',
        'incomplete': '⚠️',
        'unknown': '❓'
    }

    emoji = status_emoji.get(result['status'], '❓')

    output = f"{emoji} Phase 3: {result['summary']}"

    if result['triggered']:
        output += f" (Phase 4 triggered: {result['trigger_reason']})"

    if verbose and result['completed_processors']:
        output += "\n  Completed processors:"
        for proc in sorted(result['completed_processors']):
            output += f"\n    - {proc}"

        # Show missing processors if incomplete
        if result['status'] == 'incomplete':
            missing = result['expected_processors'] - result['completed_processors']
            if missing:
                output += "\n  Missing processors:"
                for proc in sorted(missing):
                    output += f"\n    - {proc}"

    return output


if __name__ == '__main__':
    """Test/manual execution"""
    import sys

    date = sys.argv[1] if len(sys.argv) > 1 else None
    verbose = '--verbose' in sys.argv or '-v' in sys.argv

    result = check_phase3_completion(processing_date=date)
    print(format_completion_status(result, verbose=verbose))

    if verbose:
        print(f"\nRaw result:")
        import json
        print(json.dumps({k: v for k, v in result.items() if k != 'raw_data'},
                        indent=2, default=str))
