#!/usr/bin/env python3
"""
NBA Schedule Game Extractor                              v1.0 – 2025‑08‑04
---------------------------------------------------------------------------
* Reads NBA schedule JSON from GCS  
* Extracts games for date range
* Outputs list of games for workflow consumption
* MUCH more reliable than web scraping approach

Usage examples
--------------
  # Extract games for specific date range
  python scripts/extract_schedule_games.py \
      --start-date 2024-04-10 --end-date 2024-04-15 \
      --season 2023 --output /tmp/games_batch.json

  # Extract single date
  python scripts/extract_schedule_games.py \
      --date 2024-04-10 --season 2023 --output /tmp/games_single.json

  # For workflow consumption (Cloud Run compatible)
  python scripts/extract_schedule_games.py \
      --date 2024-04-10 --season 2023 --format workflow
"""

import json
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import sys
import os

# Add Google Cloud Storage if available
try:
    from google.cloud import storage
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


class ScheduleGameExtractor:
    """Extract games from NBA schedule JSON for gamebook collection."""
    
    def __init__(self, bucket_name: str = "nba-scraped-data"):
        self.bucket_name = bucket_name
        self.client = None
        if GCS_AVAILABLE:
            self.client = storage.Client()
    
    def read_schedule_from_gcs(self, season_year: int) -> Dict[str, Any]:
        """Read NBA schedule JSON from GCS."""
        if not self.client:
            raise RuntimeError("Google Cloud Storage not available")
            
        bucket = self.client.bucket(self.bucket_name)
        
        # Construct path to schedule file
        season_str = f"{season_year}-{(season_year + 1) % 100:02d}"
        schedule_prefix = f"nba-com/schedule/{season_str}/"
        
        logger.info(f"Looking for schedule files with prefix: {schedule_prefix}")
        
        # List files with this prefix
        blobs = list(bucket.list_blobs(prefix=schedule_prefix))
        schedule_blobs = [b for b in blobs if 'schedule' in b.name and b.name.endswith('.json')]
        
        if not schedule_blobs:
            raise FileNotFoundError(f"No schedule files found for season {season_str} in {schedule_prefix}")
        
        # Use the most recent schedule file
        latest_blob = max(schedule_blobs, key=lambda b: b.time_created)
        logger.info(f"Reading schedule from: {latest_blob.name}")
        
        schedule_data = json.loads(latest_blob.download_as_text())
        return schedule_data
    
    def read_schedule_from_file(self, file_path: str) -> Dict[str, Any]:
        """Read NBA schedule JSON from local file (for testing)."""
        with open(file_path, 'r') as f:
            return json.load(f)
    
    def extract_games_for_date(self, schedule_data: Dict, target_date: str) -> List[Dict]:
        """Extract games for a specific date."""
        return self.extract_games_for_date_range(schedule_data, target_date, target_date)
    
    def extract_games_for_date_range(self, schedule_data: Dict, start_date: str, end_date: str) -> List[Dict]:
        """Extract games within date range from schedule JSON."""
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        games = []
        
        # Navigate schedule structure - handle multiple possible formats
        schedule_games = self._get_schedule_games(schedule_data)
        
        for game_date_entry in schedule_games:
            # Extract date from various possible formats
            game_date = self._extract_game_date(game_date_entry)
            if not game_date:
                continue
            
            # Check if game is in date range
            if start_dt.date() <= game_date <= end_dt.date():
                games_for_date = game_date_entry.get('games', [])
                for game in games_for_date:
                    game_info = self._extract_game_info(game, game_date.strftime("%Y-%m-%d"))
                    if game_info:
                        games.append(game_info)
        
        return sorted(games, key=lambda g: (g['date'], g['game_code']))
    
    def _get_schedule_games(self, schedule_data: Dict) -> List[Dict]:
        """Extract games list from various schedule JSON formats."""
        # Try different possible paths in the JSON structure
        possible_paths = [
            ['leagueSchedule', 'gameDates'],
            ['gameDates'],
            ['schedule', 'gameDates'],
            ['games']
        ]
        
        for path in possible_paths:
            current = schedule_data
            try:
                for key in path:
                    current = current[key]
                if isinstance(current, list):
                    return current
            except (KeyError, TypeError):
                continue
        
        logger.warning("Could not find games in schedule JSON structure")
        return []
    
    def _extract_game_date(self, game_date_entry: Dict) -> Optional[datetime.date]:
        """Extract date from game date entry (FIXED for MM/DD/YYYY HH:MM:SS format)."""
        from datetime import datetime
        
        date_fields = ['gameDate', 'date', 'gameDateEst']
        
        for field in date_fields:
            date_str = game_date_entry.get(field, '')
            if date_str:
                try:
                    # Handle MM/DD/YYYY HH:MM:SS format (your actual format)
                    if '/' in date_str and ' ' in date_str:
                        # Extract just the date part: "10/05/2023 00:00:00" -> "10/05/2023"
                        date_part = date_str.split(' ')[0]
                        return datetime.strptime(date_part, "%m/%d/%Y").date()
                    # Handle MM/DD/YYYY format
                    elif '/' in date_str:
                        return datetime.strptime(date_str, "%m/%d/%Y").date()
                    # Handle ISO format with timezone
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                    # Handle YYYY-MM-DD format
                    elif '-' in date_str:
                        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
        
        return None
    
    def _extract_game_info(self, game: Dict, date_str: str) -> Optional[Dict[str, Any]]:
        """Extract game information for gamebook collection."""
        try:
            game_code = game.get('gameCode', '')
            
            if not game_code or '/' not in game_code:
                logger.debug(f"Invalid game code: {game_code}")
                return None
            
            # Extract teams
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            if not away_team or not home_team:
                logger.debug(f"Missing team info for game: {game_code}")
                return None
            
            # Extract date part from game code for URL construction
            date_part = game_code.split('/')[0]  # YYYYMMDD
            teams_part = game_code.split('/')[1]  # AWAYTEAMHOMETEAM
            
            # Construct PDF URLs (CORRECTED FORMAT)
            base_url = f"https://statsdmz.nba.com/pdfs/{date_part}/{date_part}_{teams_part}"
            short_pdf_url = f"{base_url}.pdf"        # NO _book suffix
            full_pdf_url = f"{base_url}_book.pdf"    # HAS _book suffix
            
            # Only include completed games (gameStatus = 3) for backfill
            game_status = game.get('gameStatus', 0)
            
            return {
                "date": date_str,
                "game_code": game_code,
                "game_id": game.get('gameId'),
                "away_team": away_team,
                "home_team": home_team,
                "matchup": f"{away_team}@{home_team}",
                "arena": game.get('arenaName', ''),
                "game_status": game_status,
                "game_status_text": game.get('gameStatusText', ''),
                "completed": game_status == 3,  # Only process completed games
                "pdf_urls": {
                    "short": short_pdf_url,
                    "full": full_pdf_url
                },
                # Ready-to-use scraper parameters
                "scraper_params": {
                    "scraper": "nbac_gamebook_pdf",
                    "game_code": game_code,
                    "version": "short",  # Start with short for Phase 2A
                    "group": "prod"
                }
            }
        except Exception as e:
            logger.warning(f"Error processing game {game.get('gameCode', 'unknown')}: {e}")
            return None
    
    def generate_workflow_batch(self, games: List[Dict], batch_size: int = 50) -> List[List[Dict]]:
        """Generate batches of games for workflow processing."""
        # Only include completed games for backfill
        completed_games = [g for g in games if g.get('completed', False)]
        
        batches = []
        for i in range(0, len(completed_games), batch_size):
            batch = completed_games[i:i + batch_size]
            batches.append(batch)
        
        return batches
    
    def save_results(self, games: List[Dict], output_path: str, format_type: str = "json"):
        """Save extracted games to file."""
        if format_type == "workflow":
            # Format for workflow consumption
            workflow_data = {
                "generated_at": datetime.now().isoformat(),
                "total_games": len(games),
                "completed_games": len([g for g in games if g.get('completed', False)]),
                "date_range": {
                    "start": min(g["date"] for g in games) if games else None,
                    "end": max(g["date"] for g in games) if games else None
                },
                "games": games,
                "batch_config": {
                    "rate_limit_seconds": 4,
                    "pdf_version": "short",
                    "max_concurrent": 1
                }
            }
            
            with open(output_path, 'w') as f:
                json.dump(workflow_data, f, indent=2)
        else:
            # Simple JSON list
            with open(output_path, 'w') as f:
                json.dump(games, f, indent=2)
        
        logger.info(f"✅ Saved {len(games)} games to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Extract NBA games from schedule JSON")
    
    # Date options (either single date or range)
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument("--date", help="Single date (YYYY-MM-DD)")
    date_group.add_argument("--start-date", help="Start date for range (YYYY-MM-DD)")
    
    parser.add_argument("--end-date", help="End date for range (YYYY-MM-DD, required with --start-date)")
    parser.add_argument("--season", type=int, required=True, help="Season year (e.g., 2023 for 2023-24)")
    parser.add_argument("--bucket", default="nba-scraped-data", help="GCS bucket name")
    parser.add_argument("--schedule-file", help="Local schedule JSON file (for testing)")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--format", choices=["json", "workflow"], default="json", help="Output format")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for workflow format")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Validation
    if args.start_date and not args.end_date:
        parser.error("--end-date required when using --start-date")
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        extractor = ScheduleGameExtractor(args.bucket)
        
        # Read schedule data
        if args.schedule_file:
            logger.info(f"Reading schedule from local file: {args.schedule_file}")
            schedule_data = extractor.read_schedule_from_file(args.schedule_file)
        else:
            logger.info(f"Reading schedule for season {args.season} from GCS...")
            schedule_data = extractor.read_schedule_from_gcs(args.season)
        
        # Extract games
        if args.date:
            logger.info(f"Extracting games for {args.date}")
            games = extractor.extract_games_for_date(schedule_data, args.date)
        else:
            logger.info(f"Extracting games from {args.start_date} to {args.end_date}")
            games = extractor.extract_games_for_date_range(schedule_data, args.start_date, args.end_date)
        
        if not games:
            logger.warning("No games found for the specified criteria")
            return 1
        
        # Filter to completed games for summary
        completed_games = [g for g in games if g.get('completed', False)]
        
        # Save or print results
        if args.output:
            extractor.save_results(games, args.output, args.format)
        else:
            # Print to stdout
            if args.format == "workflow":
                workflow_data = {
                    "games": games,
                    "total_games": len(games),
                    "completed_games": len(completed_games)
                }
                print(json.dumps(workflow_data, indent=2))
            else:
                print(json.dumps(games, indent=2))
        
        # Print summary
        logger.info(f"📊 Summary:")
        logger.info(f"   Total games: {len(games)}")
        logger.info(f"   Completed games: {len(completed_games)}")
        if games:
            logger.info(f"   Date range: {min(g['date'] for g in games)} to {max(g['date'] for g in games)}")
        
        # Show sample for verification
        if completed_games:
            sample = completed_games[0]
            logger.info(f"🏀 Sample game: {sample['matchup']} on {sample['date']}")
            logger.info(f"   PDF (short): {sample['pdf_urls']['short']}")
    
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())