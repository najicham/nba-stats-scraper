#!/usr/bin/env python3
# FILE: scripts/analyze_schedule_structure.py

"""
Analyze NBA schedule file structure to debug why games aren't being found.
"""

import json
import sys

def analyze_schedule_file(file_path):
    """Analyze the structure of an NBA schedule JSON file."""
    
    print("📊 Analyzing actual NBA schedule file...")
    print("=" * 60)
    
    try:
        with open(file_path, 'r') as f:
            schedule_data = json.load(f)
        
        print(f"🔍 TOP-LEVEL STRUCTURE:")
        print(f"Keys: {list(schedule_data.keys())}")
        print(f"File size: {len(json.dumps(schedule_data))} characters")
        print()

        # Check different possible paths for games
        possible_paths = [
            ['leagueSchedule', 'gameDates'],
            ['gameDates'], 
            ['schedule', 'gameDates'],
            ['games']
        ]

        found_games = None
        found_path = None
        
        for path in possible_paths:
            try:
                current = schedule_data
                for key in path:
                    current = current[key]
                if isinstance(current, list):
                    print(f"✅ Found games at: {'.'.join(path)} (length: {len(current)})")
                    found_games = current
                    found_path = path
                    if len(current) > 0:
                        print(f"📅 Sample date entry keys: {list(current[0].keys())}")
                    break
            except (KeyError, TypeError):
                print(f"❌ Path {'.'.join(path)}: not found")

        if found_games and len(found_games) > 0:
            print(f"\n🏀 GAME ANALYSIS:")
            
            # Look at first game date entry
            sample_game_date = found_games[0]
            print(f"Sample game date structure: {list(sample_game_date.keys())}")
            
            # Check date field names
            date_fields = ['gameDate', 'date', 'gameDateEst']
            for field in date_fields:
                if field in sample_game_date:
                    print(f"✅ Date field '{field}': {sample_game_date[field]}")
            
            if 'games' in sample_game_date and sample_game_date['games']:
                sample_game = sample_game_date['games'][0]
                print(f"Sample game structure: {list(sample_game.keys())}")
                print(f"Sample game details:")
                print(f"  Game Code: {sample_game.get('gameCode', 'MISSING')}")
                print(f"  Game ID: {sample_game.get('gameId', 'MISSING')}")
                print(f"  Game Status: {sample_game.get('gameStatus', 'MISSING')}")
                print(f"  Away Team: {sample_game.get('awayTeam', {}).get('teamTricode', 'MISSING')}")
                print(f"  Home Team: {sample_game.get('homeTeam', {}).get('teamTricode', 'MISSING')}")
                
                # Count games by status
                total_games = 0
                completed_games = 0
                status_counts = {}
                
                # Sample first 10 game dates to get statistics
                for game_date_entry in found_games[:10]:
                    if 'games' in game_date_entry:
                        for game in game_date_entry['games']:
                            total_games += 1
                            status = game.get('gameStatus', 'unknown')
                            status_counts[status] = status_counts.get(status, 0) + 1
                            if status == 3:
                                completed_games += 1
                
                print(f"\n📊 SAMPLE STATISTICS (first 10 game dates):")
                print(f"Total games: {total_games}")
                print(f"Completed games (status=3): {completed_games}")
                print(f"Game status distribution: {status_counts}")
                
                # Check date formats
                print(f"\n📅 DATE FORMAT ANALYSIS:")
                sample_dates = []
                for game_date_entry in found_games[:5]:
                    for field in date_fields:
                        if field in game_date_entry:
                            sample_dates.append(game_date_entry[field])
                            break
                
                print(f"Sample dates: {sample_dates}")
                
                # Check if dates are in expected range
                print(f"\n🎯 DATE RANGE CHECK:")
                print(f"Looking for games between: 2023-10-01 to 2024-06-30")
                print(f"Sample dates from file: {sample_dates[:3]}")
                
                # Try to parse one date to see format
                if sample_dates:
                    from datetime import datetime
                    sample_date = sample_dates[0]
                    print(f"Parsing sample date: '{sample_date}'")
                    
                    try:
                        if 'T' in sample_date:
                            parsed = datetime.fromisoformat(sample_date.replace('Z', '+00:00'))
                            print(f"✅ Parsed as ISO: {parsed.date()}")
                        elif '-' in sample_date:
                            parsed = datetime.strptime(sample_date[:10], "%Y-%m-%d")
                            print(f"✅ Parsed as YYYY-MM-DD: {parsed.date()}")
                        else:
                            print(f"❓ Unknown date format")
                    except Exception as e:
                        print(f"❌ Date parsing failed: {e}")
            
        else:
            print("❌ No games array found in schedule file!")
            print("🔍 Let's examine the full structure:")
            print(json.dumps(schedule_data, indent=2)[:1000] + "...")
            
    except Exception as e:
        print(f"❌ Error analyzing file: {e}")
        return False
    
    return True

if __name__ == "__main__":
    file_path = "/tmp/schedule_2023_24.json"
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    
    success = analyze_schedule_file(file_path)
    if not success:
        print(f"\nUsage: python {sys.argv[0]} [schedule_file.json]")
        print(f"Default file: {file_path}")
        sys.exit(1)