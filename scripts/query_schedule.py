#!/usr/bin/env python3
"""
Save as: scripts/query_schedule.py

NBA Schedule Query Helper
Extracts game codes from Phase 1 schedule data for the gamebook scraper
"""

import json
import argparse
from datetime import datetime
from typing import List, Dict, Any

def load_schedule(filename: str) -> List[Dict[str, Any]]:
    """Load schedule data from JSON file."""
    with open(filename, 'r') as f:
        return json.load(f)

def filter_games(games: List[Dict], date: str = None, start_date: str = None, 
                 end_date: str = None, season: str = None, team: str = None) -> List[Dict]:
    """Filter games based on criteria."""
    filtered = []
    
    for game in games:
        game_date = game.get('date', '')
        away_team = game.get('away_team', '')
        home_team = game.get('home_team', '')
        game_season = game.get('season', '')
        
        # Date filtering
        if date and game_date != date:
            continue
        if start_date and game_date < start_date:
            continue
        if end_date and game_date > end_date:
            continue
        if season and season not in str(game_season):
            continue
        if team and team.upper() not in [away_team.upper(), home_team.upper()]:
            continue
            
        filtered.append(game)
    
    return filtered

def main():
    parser = argparse.ArgumentParser(description='Query NBA schedule for game codes')
    parser.add_argument('--schedule_file', default='data/nba_schedule.json',
                       help='Path to schedule JSON file')
    parser.add_argument('--date', help='Specific date (YYYY-MM-DD)')
    parser.add_argument('--start_date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end_date', help='End date (YYYY-MM-DD)')
    parser.add_argument('--season', help='NBA season (e.g., 2023-24)')
    parser.add_argument('--team', help='Team code (e.g., MEM)')
    parser.add_argument('--count', action='store_true', help='Just show count')
    parser.add_argument('--format', choices=['game_code', 'full'], default='game_code',
                       help='Output format')
    
    args = parser.parse_args()
    
    try:
        # Load schedule
        schedule = load_schedule(args.schedule_file)
        
        # Apply filters
        filtered_games = filter_games(
            schedule,
            date=args.date,
            start_date=args.start_date,
            end_date=args.end_date,
            season=args.season,
            team=args.team
        )
        
        if args.count:
            print(len(filtered_games))
            return
        
        # Output results
        for game in filtered_games:
            if args.format == 'game_code':
                print(game.get('game_code', ''))
            else:
                print(f"{game.get('game_code', ''):<15} {game.get('date', ''):<12} "
                      f"{game.get('away_team', '')}@{game.get('home_team', ''):<8} "
                      f"{game.get('season', '')}")
                
    except FileNotFoundError:
        print(f"Error: Schedule file not found: {args.schedule_file}")
        print("Make sure you've run Phase 1 (schedule collection) first")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1

if __name__ == '__main__':
    exit(main())