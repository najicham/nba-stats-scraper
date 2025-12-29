#!/usr/bin/env python3
"""
Check orchestration state in Firestore.
Usage: python3 bin/monitoring/check_orchestration_state.py [DATE]
"""

import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from google.cloud import firestore


def main():
    # Get date from args or use today
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    else:
        et = ZoneInfo("America/New_York")
        target_date = datetime.now(et).strftime("%Y-%m-%d")

    db = firestore.Client()

    print(f"\n{'='*60}")
    print(f"ORCHESTRATION STATE FOR {target_date}")
    print(f"{'='*60}\n")

    # Expected Phase 3 processors
    expected_p3 = [
        'player_game_summary',
        'team_defense_game_summary',
        'team_offense_game_summary',
        'upcoming_player_game_context',
        'upcoming_team_game_context',
    ]

    # Check Phase 3 completion
    print("PHASE 3 COMPLETION:")
    p3_doc = db.collection('phase3_completion').document(target_date).get()
    if p3_doc.exists:
        data = p3_doc.to_dict()
        completed = [k for k in data if not k.startswith('_')]
        triggered = data.get('_triggered', False)
        count = data.get('_completed_count', len(completed))

        print(f"  Status: {count}/5 complete")
        print(f"  Phase 4 triggered: {triggered}")
        print()
        for proc in expected_p3:
            if proc in completed:
                ts = data[proc].get('completed_at', 'unknown') if isinstance(data[proc], dict) else 'complete'
                print(f"  + {proc} ({ts})")
            else:
                print(f"  - {proc} (MISSING)")
    else:
        print("  No completion document found")

    # Check Phase 4 completion
    print(f"\nPHASE 4 COMPLETION:")
    p4_doc = db.collection('phase4_completion').document(target_date).get()
    if p4_doc.exists:
        data = p4_doc.to_dict()
        triggered = data.get('_triggered', False)
        print(f"  Phase 5 triggered: {triggered}")
        for k, v in data.items():
            if not k.startswith('_'):
                print(f"  + {k}")
    else:
        print("  No completion document found")

    # Check run_history for stuck entries
    print(f"\nRUN HISTORY (stuck entries):")
    stuck = list(db.collection('run_history').where('status', '==', 'running').stream())
    if stuck:
        for doc in stuck[:10]:
            data = doc.to_dict()
            print(f"  ! {doc.id}: {data.get('processor_name', 'unknown')} started at {data.get('started_at', 'unknown')}")
    else:
        print("  No stuck entries")

    # Check tomorrow's state as well
    et = ZoneInfo("America/New_York")
    tomorrow = datetime.now(et).replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    tomorrow = (tomorrow + timedelta(days=1)).strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"TOMORROW'S STATE ({tomorrow})")
    print(f"{'='*60}\n")

    p3_tomorrow = db.collection('phase3_completion').document(tomorrow).get()
    if p3_tomorrow.exists:
        data = p3_tomorrow.to_dict()
        completed = [k for k in data if not k.startswith('_')]
        triggered = data.get('_triggered', False)
        print(f"  Phase 3: {len(completed)}/5 complete, Phase 4 triggered: {triggered}")
    else:
        print("  Phase 3: No data yet")

    p4_tomorrow = db.collection('phase4_completion').document(tomorrow).get()
    if p4_tomorrow.exists:
        data = p4_tomorrow.to_dict()
        triggered = data.get('_triggered', False)
        print(f"  Phase 4: Complete, Phase 5 triggered: {triggered}")
    else:
        print("  Phase 4: No data yet")

    print()


if __name__ == "__main__":
    main()
