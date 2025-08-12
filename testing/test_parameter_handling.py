#!/usr/bin/env python3
# FILE: test_parameter_handling.py
# Quick test to validate parameter conversion locally before deployment

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

def test_events_parameters():
    """Test that events scraper handles parameters correctly."""
    print("🧪 Testing Events Scraper Parameter Handling")
    print("=" * 50)
    
    try:
        from scrapers.oddsapi.oddsa_events_his import GetOddsApiHistoricalEvents
        
        # Test parameters
        test_opts = {
            "game_date": "2024-04-10",
            "snapshot_timestamp": "2024-04-10T20:00:00Z",
            "sport": "basketball_nba",
            "group": "dev"
        }
        
        print(f"Input parameters: {test_opts}")
        
        # Create scraper instance
        scraper = GetOddsApiHistoricalEvents()
        scraper.set_opts(test_opts)
        scraper.validate_opts()
        scraper.set_additional_opts()
        
        print(f"After processing:")
        print(f"  game_date: {scraper.opts.get('game_date')}")
        print(f"  date: {scraper.opts.get('date')}")
        print(f"  snapshot_timestamp: {scraper.opts.get('snapshot_timestamp')}")
        print(f"  timestamp: {scraper.opts.get('timestamp')}")
        
        # Validate results
        if scraper.opts.get("date") == "2024-04-10":
            print("✅ PASS: game_date correctly converted to date for GCS path")
        else:
            print(f"❌ FAIL: Expected date='2024-04-10', got '{scraper.opts.get('date')}'")
            
        if scraper.opts.get("snapshot_timestamp") == "2024-04-10T20:00:00Z":
            print("✅ PASS: snapshot_timestamp preserved for API call")
        else:
            print(f"❌ FAIL: snapshot_timestamp was modified: {scraper.opts.get('snapshot_timestamp')}")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_props_parameters():
    """Test that props scraper handles parameters correctly."""
    print("\n🧪 Testing Props Scraper Parameter Handling")
    print("=" * 50)
    
    try:
        from scrapers.oddsapi.oddsa_player_props_his import GetOddsApiHistoricalEventOdds
        
        # Test parameters
        test_opts = {
            "event_id": "abc123def456",
            "game_date": "2024-04-10", 
            "snapshot_timestamp": "2024-04-11T04:00:00Z",
            "teams": "MEMCLE",
            "group": "dev"
        }
        
        print(f"Input parameters: {test_opts}")
        
        # Create scraper instance
        scraper = GetOddsApiHistoricalEventOdds()
        scraper.set_opts(test_opts)
        scraper.validate_opts()
        scraper.set_additional_opts()
        
        print(f"After processing:")
        print(f"  game_date: {scraper.opts.get('game_date')}")
        print(f"  date: {scraper.opts.get('date')}")
        print(f"  snapshot_timestamp: {scraper.opts.get('snapshot_timestamp')}")
        print(f"  teams: {scraper.opts.get('teams')}")
        print(f"  snap: {scraper.opts.get('snap')}")
        
        # Validate results
        if scraper.opts.get("date") == "2024-04-10":
            print("✅ PASS: game_date correctly converted to date for GCS path")
        else:
            print(f"❌ FAIL: Expected date='2024-04-10', got '{scraper.opts.get('date')}'")
            
        if scraper.opts.get("snap") == "0400":
            print("✅ PASS: snap time correctly extracted from snapshot_timestamp")
        else:
            print(f"❌ FAIL: Expected snap='0400', got '{scraper.opts.get('snap')}'")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

def test_gcs_path_building():
    """Test GCS path building with correct parameters."""
    print("\n🧪 Testing GCS Path Building")
    print("=" * 50)
    
    try:
        from scrapers.utils.gcs_path_builder import GCSPathBuilder
        
        # Test events path template
        events_template = GCSPathBuilder.get_path("odds_api_events_history")
        print(f"Events template: {events_template}")
        
        # Test template substitution manually
        events_path = events_template % {
            "date": "2024-04-10",
            "timestamp": "20250810_143000"
        }
        print(f"Events path: {events_path}")
        expected_events = "odds-api/events-history/2024-04-10/20250810_143000.json"
        if events_path == expected_events:
            print("✅ PASS: Events path correct")
        else:
            print(f"❌ FAIL: Expected '{expected_events}', got '{events_path}'")
        
        # Test props path template
        props_template = GCSPathBuilder.get_path("odds_api_player_props_history")
        print(f"Props template: {props_template}")
        
        # Test template substitution manually
        props_path = props_template % {
            "date": "2024-04-10",
            "event_id": "abc123def456",
            "teams": "MEMCLE",
            "timestamp": "20250810_143000",
            "snap": "0400"
        }
        print(f"Props path: {props_path}")
        expected_props = "odds-api/player-props-history/2024-04-10/abc123def456-MEMCLE/20250810_143000-snap-0400.json"
        if props_path == expected_props:
            print("✅ PASS: Props path correct")
        else:
            print(f"❌ FAIL: Expected '{expected_props}', got '{props_path}'")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    print("🎯 Parameter Handling Validation Test")
    print("=" * 60)
    
    test_events_parameters()
    test_props_parameters() 
    test_gcs_path_building()
    
    print("\n" + "=" * 60)
    print("🎯 Test complete. If all PASS, parameters should work correctly!")
    print("   Next step: Deploy and test integration")