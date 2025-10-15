#!/usr/bin/env python3
"""
Validate Missing Dates Against NBA Schedule
Cross-references missing referee dates with actual game data using Schedule Service

Usage:
    python scripts/audit/validate_missing_dates.py
"""

import sys
import os
from datetime import date
from collections import defaultdict

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

# Import Schedule Service
from shared.utils.schedule import NBAScheduleService, GameType

def load_missing_dates(filename='missing_referee_dates.txt'):
    """Load missing dates from file."""
    with open(filename, 'r') as f:
        dates = [date.fromisoformat(line.strip()) for line in f if line.strip()]
    return dates

def check_games_on_dates(missing_dates):
    """Check if games were actually played on missing dates using Schedule Service."""
    print("🔍 Checking missing dates against NBA Schedule Service...")
    print("=" * 70)
    print()
    
    try:
        # Initialize Schedule Service (GCS source of truth)
        schedule = NBAScheduleService.from_gcs_only()
        
        games_by_date = {}
        
        # Check each missing date
        for missing_date in missing_dates:
            date_str = missing_date.isoformat()
            
            # Check if games exist on this date
            if schedule.has_games_on_date(date_str):
                games = schedule.get_games_for_date(date_str)
                
                # Build sample games string
                sample_games = ', '.join([
                    f"{game.away_team}@{game.home_team}" 
                    for game in games[:3]
                ])
                
                # Store game info (using object with attributes like BigQuery row)
                class GameInfo:
                    def __init__(self, date, count, sample):
                        self.game_date = date
                        self.game_count = count
                        self.sample_games = sample
                
                games_by_date[missing_date] = GameInfo(
                    date=missing_date,
                    count=len(games),
                    sample=sample_games
                )
        
        print(f"✅ Successfully checked {len(missing_dates)} dates using Schedule Service")
        print()
        return games_by_date
        
    except Exception as e:
        print(f"❌ Error checking schedule: {e}")
        import traceback
        traceback.print_exc()
        return None

def categorize_missing_dates(missing_dates, games_by_date):
    """Categorize missing dates into games vs no-games."""
    dates_with_games = []
    dates_without_games = []
    
    for missing_date in missing_dates:
        if missing_date in games_by_date:
            game_info = games_by_date[missing_date]
            dates_with_games.append({
                'date': missing_date,
                'game_count': game_info.game_count,
                'sample_games': getattr(game_info, 'sample_games', '')
            })
        else:
            dates_without_games.append(missing_date)
    
    return dates_with_games, dates_without_games

def analyze_no_game_dates(dates_without_games):
    """Analyze dates without games to identify patterns."""
    patterns = {
        'june': [],
        'july_august': [],
        'february': [],
        'december_24_25': [],
        'other': []
    }
    
    for d in dates_without_games:
        if d.month == 6:
            patterns['june'].append(d)
        elif d.month in [7, 8]:
            patterns['july_august'].append(d)
        elif d.month == 2 and 14 <= d.day <= 20:
            patterns['february'].append(d)
        elif d.month == 12 and d.day in [24, 25]:
            patterns['december_24_25'].append(d)
        else:
            patterns['other'].append(d)
    
    return patterns

def main():
    # Load missing dates
    try:
        missing_dates = load_missing_dates()
    except FileNotFoundError:
        print("❌ File 'missing_referee_dates.txt' not found")
        print("   Run: python scripts/audit/gcs_referee_audit.py first")
        return
    
    print(f"📋 Loaded {len(missing_dates)} missing dates from file")
    print()
    
    # Check against Ball Don't Lie data
    games_by_date = check_games_on_dates(missing_dates)
    
    if games_by_date is None:
        print("⚠️  Could not validate against game data")
        print("   You may need to scrape all missing dates to be safe")
        return
    
    # Categorize dates
    dates_with_games, dates_without_games = categorize_missing_dates(missing_dates, games_by_date)
    
    # Print summary
    print()
    print("📊 VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Total missing dates:           {len(missing_dates)}")
    print(f"✅ Dates WITH games:           {len(dates_with_games)} (NEED TO SCRAPE)")
    print(f"⚪ Dates with NO games:        {len(dates_without_games)} (off-days, OK to skip)")
    print()
    
    # Show dates with games (these need scraping)
    if dates_with_games:
        print("🎯 DATES THAT NEED SCRAPING (had games scheduled)")
        print("=" * 70)
        
        # Group by season
        by_season = defaultdict(list)
        for info in dates_with_games:
            d = info['date']
            if d.month >= 10:
                season = f"{d.year}-{(d.year + 1) % 100:02d}"
            else:
                season = f"{d.year - 1}-{d.year % 100:02d}"
            by_season[season].append(info)
        
        total_games = 0
        for season in sorted(by_season.keys()):
            dates = by_season[season]
            season_games = sum(d['game_count'] for d in dates)
            total_games += season_games
            
            print(f"\n{season} Season: {len(dates)} dates, ~{season_games} games")
            for info in sorted(dates, key=lambda x: x['date']):
                sample = info['sample_games'] if info['sample_games'] else 'N/A'
                print(f"  {info['date']}: {info['game_count']} games ({sample})")
        
        print()
        print(f"Total games to scrape: ~{total_games} games")
        print()
        
        # Write to file
        scrape_file = 'dates_to_scrape.txt'
        with open(scrape_file, 'w') as f:
            for info in sorted(dates_with_games, key=lambda x: x['date']):
                f.write(f"{info['date']}\n")
        print(f"📝 Written {len(dates_with_games)} dates to: {scrape_file}")
        print()
    
    # Analyze no-game dates
    if dates_without_games:
        print("⚪ DATES WITH NO GAMES (confirmed off-days)")
        print("=" * 70)
        
        patterns = analyze_no_game_dates(dates_without_games)
        
        if patterns['june']:
            print(f"\n📅 June dates ({len(patterns['june'])}): Post-playoffs/off-season")
            for d in sorted(patterns['june'])[:5]:
                print(f"  {d}")
            if len(patterns['june']) > 5:
                print(f"  ... and {len(patterns['june']) - 5} more")
        
        if patterns['july_august']:
            print(f"\n📅 July/August dates ({len(patterns['july_august'])}): Off-season")
            for d in sorted(patterns['july_august'])[:5]:
                print(f"  {d}")
        
        if patterns['february']:
            print(f"\n📅 February dates ({len(patterns['february'])}): All-Star break")
            for d in sorted(patterns['february']):
                print(f"  {d}")
        
        if patterns['december_24_25']:
            print(f"\n📅 December 24-25 ({len(patterns['december_24_25'])}): Christmas break")
            for d in sorted(patterns['december_24_25']):
                print(f"  {d}")
        
        if patterns['other']:
            print(f"\n📅 Other off-days ({len(patterns['other'])})")
            for d in sorted(patterns['other'])[:10]:
                print(f"  {d}")
            if len(patterns['other']) > 10:
                print(f"  ... and {len(patterns['other']) - 10} more")
        
        print()
        
        # Write to file
        skip_file = 'dates_no_games.txt'
        with open(skip_file, 'w') as f:
            for d in sorted(dates_without_games):
                f.write(f"{d}\n")
        print(f"📝 Written {len(dates_without_games)} dates to: {skip_file}")
        print()
    
    # Final recommendations
    print("🎯 RECOMMENDATIONS")
    print("=" * 70)
    
    if dates_with_games:
        print(f"1. Scrape {len(dates_with_games)} dates that had games:")
        print(f"   while read date; do")
        print(f"     echo \"Scraping $date...\"")
        print(f"     python scrapers/nbacom/nbac_referee_assignments.py --date $date")
        print(f"     sleep 2")
        print(f"   done < dates_to_scrape.txt")
        print()
    
    if dates_without_games:
        print(f"2. Skip {len(dates_without_games)} dates with no games (confirmed off-days)")
        print()
    
    print(f"3. After scraping, process all files:")
    print(f"   gcloud run jobs execute nbac-referee-processor-backfill \\")
    print(f"     --args=--start-date=2021-10-19,--end-date=2025-06-19 \\")
    print(f"     --region=us-west2")
    print()
    
    # Updated coverage estimate
    total_expected_with_games = len(dates_with_games) + 667  # 667 valid files we found
    print("📈 UPDATED COVERAGE ESTIMATE")
    print("=" * 70)
    print(f"Files ready to process:        667 files (~4,069 games)")
    print(f"Dates to scrape:               {len(dates_with_games)} dates (~{sum(d['game_count'] for d in dates_with_games)} games)")
    print(f"Confirmed off-days:            {len(dates_without_games)} dates (no action needed)")
    print()
    print(f"After scraping, total games:   ~{4069 + sum(d['game_count'] for d in dates_with_games)} games")
    print(f"Your target:                   5,503 games")
    print(f"Gap:                           ~{5503 - (4069 + sum(d['game_count'] for d in dates_with_games))} games")
    print()

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
