#!/usr/bin/env python3
# FILE: testing/props_timing_tester.py

"""
Props Timing Tester
===================

Test different timestamp strategies to find optimal windows for props data.
Uses the actual events data to calculate dynamic timestamps.
"""

import json
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Add project path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def load_events_data():
    """Load the events data from our successful test."""
    try:
        with open('../test-events.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ test-events.json not found. Run this from testing/ directory after copying the events file.")
        return None

def parse_game_time(commence_time_str: str) -> datetime:
    """Parse ISO timestamp to datetime object."""
    return datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))

def calculate_test_timestamps(game_start: datetime) -> Dict[str, str]:
    """Calculate various test timestamps relative to game start."""
    
    test_times = {
        # Pre-game windows
        "6h_before": (game_start - timedelta(hours=6)).isoformat().replace('+00:00', 'Z'),
        "4h_before": (game_start - timedelta(hours=4)).isoformat().replace('+00:00', 'Z'),
        "2h_before": (game_start - timedelta(hours=2)).isoformat().replace('+00:00', 'Z'),
        "1h_before": (game_start - timedelta(hours=1)).isoformat().replace('+00:00', 'Z'),
        "30m_before": (game_start - timedelta(minutes=30)).isoformat().replace('+00:00', 'Z'),
        
        # Live windows  
        "game_start": game_start.isoformat().replace('+00:00', 'Z'),
        "15m_into": (game_start + timedelta(minutes=15)).isoformat().replace('+00:00', 'Z'),
        "30m_into": (game_start + timedelta(minutes=30)).isoformat().replace('+00:00', 'Z'),
        "1h_into": (game_start + timedelta(hours=1)).isoformat().replace('+00:00', 'Z'),
        
        # Post-game windows
        "2h_after": (game_start + timedelta(hours=2)).isoformat().replace('+00:00', 'Z'),
        "4h_after": (game_start + timedelta(hours=4)).isoformat().replace('+00:00', 'Z'),
        "6h_after": (game_start + timedelta(hours=6)).isoformat().replace('+00:00', 'Z'),
    }
    
    return test_times

def analyze_events_timing():
    """Analyze all events and their timing patterns."""
    events_data = load_events_data()
    if not events_data:
        return
    
    events = events_data.get("data", [])
    
    print("🎯 NBA Events Timing Analysis")
    print("=" * 60)
    print(f"Total events: {len(events)}")
    print()
    
    # Group events by start time patterns
    time_patterns = {}
    
    for event in events:
        game_start = parse_game_time(event["commence_time"])
        hour = game_start.hour
        
        if hour not in time_patterns:
            time_patterns[hour] = []
        time_patterns[hour].append({
            "teams": f"{event['away_team']} @ {event['home_team']}",
            "start_time": event["commence_time"],
            "start_hour_utc": hour
        })
    
    print("📊 Game Start Time Patterns (UTC):")
    for hour in sorted(time_patterns.keys()):
        games = time_patterns[hour]
        print(f"  {hour:02d}:XX UTC - {len(games)} games")
        for game in games[:2]:  # Show first 2 games
            local_time = parse_game_time(game["start_time"])
            print(f"    • {game['teams']}")
            print(f"      Start: {game['start_time']} ({local_time.strftime('%I:%M %p')} UTC)")
    
    return events

def generate_test_commands(events: List[Dict[str, Any]]) -> None:
    """Generate test commands for different timing strategies."""
    
    print("\n🧪 PROPS TIMING TEST COMMANDS")
    print("=" * 60)
    print("Copy and run these commands to test different timing windows:\n")
    
    # Test with first 3 events for variety
    test_events = events[:3]
    
    for i, event in enumerate(test_events, 1):
        event_id = event["id"]
        game_start = parse_game_time(event["commence_time"])
        teams = f"{event['away_team']} @ {event['home_team']}"
        
        print(f"## Event {i}: {teams}")
        print(f"## Game starts: {event['commence_time']}")
        print()
        
        test_times = calculate_test_timestamps(game_start)
        
        # Test key timing windows
        key_tests = ["2h_before", "1h_before", "30m_before", "15m_into", "2h_after"]
        
        for test_name in key_tests:
            timestamp = test_times[test_name]
            print(f"# Test: {test_name}")
            print(f"python tools/fixtures/capture.py oddsa_player_props_his \\")
            print(f"    --event_id {event_id} \\")
            print(f"    --game_date 2024-04-10 \\")
            print(f"    --snapshot_timestamp {timestamp} \\")
            print(f"    --debug")
            print()
        
        print("-" * 50)
        print()

def create_optimal_timestamp_function():
    """Create a function template for optimal timestamp calculation."""
    
    template = '''
def calculate_optimal_props_timestamp(commence_time_str: str, strategy: str = "pregame") -> str:
    """
    Calculate optimal timestamp for props data based on game start time.
    
    Args:
        commence_time_str: Game start time in ISO format (e.g., "2024-04-10T23:10:00Z")
        strategy: Timing strategy - "pregame", "live", or "final"
    
    Returns:
        Optimal timestamp for props API call
    """
    from datetime import datetime, timedelta
    
    game_start = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
    
    if strategy == "pregame":
        # 1 hour before game start - best for opening lines
        optimal_time = game_start - timedelta(hours=1)
    elif strategy == "live":  
        # 15 minutes into game - live odds available
        optimal_time = game_start + timedelta(minutes=15)
    elif strategy == "final":
        # 30 minutes before game - final pregame odds
        optimal_time = game_start - timedelta(minutes=30)
    else:
        # Default: 1 hour before
        optimal_time = game_start - timedelta(hours=1)
    
    return optimal_time.isoformat().replace('+00:00', 'Z')

# Example usage:
# commence_time = "2024-04-10T23:10:00Z"  # Memphis @ Cleveland
# props_timestamp = calculate_optimal_props_timestamp(commence_time, "pregame")
# print(f"Optimal props timestamp: {props_timestamp}")
# # Output: "2024-04-10T22:10:00Z" (1 hour before)
'''
    
    print("\n🔧 OPTIMAL TIMESTAMP FUNCTION TEMPLATE")
    print("=" * 60)
    print(template)

def main():
    """Run the complete timing analysis."""
    print("🎯 Props Timing Strategy Development")
    print("=" * 60)
    print()
    
    # Load and analyze events
    events = analyze_events_timing()
    if not events:
        return
    
    # Generate test commands
    generate_test_commands(events)
    
    # Show optimal function template
    create_optimal_timestamp_function()
    
    print("\n🎯 TESTING STRATEGY:")
    print("1. Run the test commands above to see which timing windows work")
    print("2. Note which strategies return 200 vs 404")
    print("3. Update the job to use dynamic timestamps")
    print("4. Test integration with multiple events")
    print()
    print("📊 Expected Results:")
    print("✅ Pre-game (1-2h before): Should work for most events")
    print("✅ Live (15-30m into): Should work during games")  
    print("❌ Post-game (4h+ after): Likely 404 for most events")

if __name__ == "__main__":
    main()
    