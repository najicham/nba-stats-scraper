# FILE: testing/dynamic_timestamp_utils.py

"""
Dynamic Timestamp Utilities for Props Collection
===============================================

Functions to calculate optimal props timestamps based on actual game start times.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Any

def calculate_optimal_props_timestamp(commence_time_str: str, strategy: str = "pregame") -> str:
    """
    Calculate optimal timestamp for props data based on game start time.
    
    Args:
        commence_time_str: Game start time in ISO format (e.g., "2024-04-10T23:10:00Z")
        strategy: Timing strategy - "pregame", "live", "final", or "safe"
    
    Returns:
        Optimal timestamp for props API call
    """
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
    elif strategy == "safe":
        # 2 hours before - very conservative, should always work
        optimal_time = game_start - timedelta(hours=2)
    else:
        # Default: 1 hour before
        optimal_time = game_start - timedelta(hours=1)
    
    return optimal_time.isoformat().replace('+00:00', 'Z')

def analyze_game_timing_patterns(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Analyze timing patterns across all events.
    
    Args:
        events: List of event dictionaries with commence_time
        
    Returns:
        Analysis summary with timing patterns
    """
    patterns = {
        "total_events": len(events),
        "time_zones": {},
        "hour_distribution": {},
        "recommendations": {}
    }
    
    for event in events:
        game_start = datetime.fromisoformat(event["commence_time"].replace('Z', '+00:00'))
        hour_utc = game_start.hour
        
        # Count games by hour
        if hour_utc not in patterns["hour_distribution"]:
            patterns["hour_distribution"][hour_utc] = 0
        patterns["hour_distribution"][hour_utc] += 1
    
    # Generate recommendations based on patterns
    patterns["recommendations"] = {
        "primary_strategy": "pregame",
        "fallback_strategy": "safe", 
        "avoid_windows": ["6h_after", "12h_after"],
        "optimal_windows": ["2h_before", "1h_before", "30m_before"]
    }
    
    return patterns

def build_props_requests_with_dynamic_timing(events: List[Dict[str, Any]], 
                                           game_date: str,
                                           strategy: str = "pregame") -> List[Dict[str, Any]]:
    """
    Build props API requests with dynamic timestamps based on game start times.
    
    Args:
        events: List of events from events API
        game_date: Eastern date for GCS paths (e.g., "2024-04-10") 
        strategy: Timing strategy to use
        
    Returns:
        List of props request payloads with optimal timestamps
    """
    requests = []
    
    for event in events:
        # Calculate optimal timestamp for this specific game
        optimal_timestamp = calculate_optimal_props_timestamp(
            event["commence_time"], 
            strategy
        )
        
        props_request = {
            "scraper": "oddsa_player_props_his",
            "event_id": event["id"],
            "game_date": game_date,
            "snapshot_timestamp": optimal_timestamp,
            "group": "prod",
            # Add metadata for debugging
            "_game_info": {
                "teams": f"{event.get('away_team', '')} @ {event.get('home_team', '')}",
                "original_start": event["commence_time"],
                "props_timestamp": optimal_timestamp,
                "strategy": strategy
            }
        }
        
        requests.append(props_request)
    
    return requests

def validate_timestamp_strategy(events: List[Dict[str, Any]], strategy: str = "pregame") -> None:
    """
    Print validation info for a timestamp strategy.
    
    Args:
        events: List of events
        strategy: Strategy to validate
    """
    print(f"\n🧪 Validating '{strategy}' strategy:")
    print("-" * 50)
    
    for i, event in enumerate(events[:3], 1):  # Test first 3 events
        game_start_str = event["commence_time"]
        optimal_timestamp = calculate_optimal_props_timestamp(game_start_str, strategy)
        
        game_start = datetime.fromisoformat(game_start_str.replace('Z', '+00:00'))
        props_time = datetime.fromisoformat(optimal_timestamp.replace('Z', '+00:00'))
        
        time_diff = props_time - game_start
        diff_hours = time_diff.total_seconds() / 3600
        
        teams = f"{event.get('away_team', '')} @ {event.get('home_team', '')}"
        
        print(f"{i}. {teams}")
        print(f"   Game start: {game_start_str}")
        print(f"   Props time: {optimal_timestamp}")
        print(f"   Difference: {diff_hours:+.1f} hours")
        
        if diff_hours < -0.5:
            print(f"   Status: ✅ Pre-game ({abs(diff_hours):.1f}h before)")
        elif diff_hours > 0.5:
            print(f"   Status: ⚠️  Post-game ({diff_hours:.1f}h after)")
        else:
            print(f"   Status: 🔴 Game time")
        print()

# Test with actual events data
if __name__ == "__main__":
    # Example test with Memphis @ Cleveland game
    test_event = {
        "id": "eef78bee2f630d615486f953ca851264",
        "commence_time": "2024-04-10T23:10:00Z",
        "away_team": "Memphis Grizzlies", 
        "home_team": "Cleveland Cavaliers"
    }
    
    strategies = ["safe", "pregame", "final", "live"]
    
    print("🎯 Dynamic Timestamp Calculation Examples")
    print("=" * 60)
    
    for strategy in strategies:
        timestamp = calculate_optimal_props_timestamp(
            test_event["commence_time"], 
            strategy
        )
        print(f"{strategy:>8}: {timestamp}")
    
    print(f"\nGame starts: {test_event['commence_time']}")
    print(f"Teams: {test_event['away_team']} @ {test_event['home_team']}")