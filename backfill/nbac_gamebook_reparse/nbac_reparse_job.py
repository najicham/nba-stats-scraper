#!/usr/bin/env python3
"""
FILE: backfill/nbac_gamebook_reparse/nbac_reparse_job.py

NBA Gamebook PDF Re-parse Job - Using Enhanced Scraper
Processes existing PDFs from GCS using the enhanced scraper with pdf_source="gcs"

This job runs much faster than the original downloader since it reads
PDFs from GCS instead of downloading from NBA.com. Uses the SAME
battle-tested parsing logic via the enhanced scraper.

Expected Runtime: 1-2 hours vs 6+ hours for download
"""

import os
import sys
import argparse
import logging
import requests
from typing import List, Optional
from datetime import datetime, timedelta

# Add current directory to path for imports
sys.path.insert(0, '/app')

class NBACGamebookReparseJob:
    """Backfill job for re-parsing existing gamebook PDFs using enhanced scraper"""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, 
                 bucket_name: str = "nba-scraped-data", limit: Optional[int] = None):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]
        self.bucket_name = bucket_name
        self.limit = limit
        
        # Rate limiting for scraper service calls (fast since no external downloads)
        self.RATE_LIMIT_DELAY = float(os.getenv("REPARSE_RATE_LIMIT", "0.5"))  # Configurable via env var  
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
    def get_existing_game_codes_from_gcs(self, seasons: List[int]) -> List[dict]:
        """
        Get actual game codes by scanning existing PDFs in GCS.
        This finds only games that actually exist as PDFs.
        """
        try:
            from google.cloud import storage
            
            # SIMPLE GCS TEST FIRST
            self.logger.info("🧪 Running simple GCS access test...")
            client = storage.Client()
            self.logger.info("✅ GCS client created successfully")
            
            bucket = client.bucket(self.bucket_name)
            self.logger.info(f"✅ Bucket accessed: {bucket.name}")
            
            # Test: List ANY blobs (no prefix)
            test_blobs = list(client.list_blobs(self.bucket_name, max_results=3))
            self.logger.info(f"✅ Found {len(test_blobs)} total blobs in bucket (no prefix)")
            for i, blob in enumerate(test_blobs):
                self.logger.info(f"  Test blob {i+1}: {blob.name}")
            
            # Test: List with our prefix
            test_prefix = "nba-com/"
            prefix_blobs = list(client.list_blobs(self.bucket_name, prefix=test_prefix, max_results=5))
            self.logger.info(f"✅ Found {len(prefix_blobs)} blobs with prefix '{test_prefix}'")
            for i, blob in enumerate(prefix_blobs):
                self.logger.info(f"  Prefix blob {i+1}: {blob.name}")
            
            self.logger.info("🧪 GCS test completed, proceeding with main scanning...")
            
            games = []
            season_strs = [f"{s}-{str(s+1)[-2:]}" for s in seasons]
            
            # Main scanning logic with the test results
            if len(test_blobs) == 0:
                self.logger.error("❌ No blobs found at all in bucket - permission issue?")
                return games
                
            if len(prefix_blobs) == 0:
                self.logger.error("❌ No blobs found with nba-com/ prefix - wrong path?")
                return games
            
            # GCS access confirmed working, proceed with full scanning
            self.logger.info("🔍 GCS access confirmed, proceeding with full PDF scanning...")
            
            # Scan the GCS bucket for existing PDFs
            prefix = "nba-com/gamebooks-pdf/"
            self.logger.info(f"Scanning GCS with prefix: {prefix}")
            
            # Get all game directories first, then find the most recent PDF in each
            game_dirs = {}
            blobs = bucket.list_blobs(prefix=prefix)
            
            blob_count = 0
            pdf_count = 0
            
            for blob in blobs:
                blob_count += 1
                if blob_count <= 10:  # Log first few blobs for debugging
                    self.logger.info(f"Processing blob: {blob.name}")
                    
                if not blob.name.endswith('.pdf'):
                    continue
                    
                pdf_count += 1
                if pdf_count <= 5:  # Log first few PDFs for debugging
                    self.logger.info(f"Found PDF: {blob.name}")
                    
                try:
                    # Parse: nba-com/gamebooks-pdf/2021-10-19/20211019-BKNMIL/20250809_061835.pdf
                    path_parts = blob.name.split('/')
                    self.logger.debug(f"Path parts for {blob.name}: {path_parts} (length: {len(path_parts)})")
                    
                    if len(path_parts) != 5:  # Exact structure expected
                        self.logger.debug(f"Skipping {blob.name}: wrong path length {len(path_parts)}")
                        continue
                        
                    date_dir = path_parts[2]      # "2021-10-19"  
                    game_dir = path_parts[3]      # "20211019-BKNMIL"
                    timestamp_file = path_parts[4] # "20250809_061835.pdf"
                    
                    self.logger.debug(f"Parsed: date_dir={date_dir}, game_dir={game_dir}, file={timestamp_file}")
                    
                    # Extract game_code from game directory (YYYYMMDD-TEAMTEAM)
                    if '-' not in game_dir or len(game_dir) != 15:
                        self.logger.debug(f"Skipping {game_dir}: invalid game directory format")
                        continue
                        
                    date_part, teams_part = game_dir.split('-', 1) 
                    if len(date_part) != 8 or len(teams_part) != 6:
                        self.logger.debug(f"Skipping {game_dir}: invalid date/teams format: {date_part}({len(date_part)}) / {teams_part}({len(teams_part)})")
                        continue
                        
                    game_code = f"{date_part}/{teams_part}"  # "20211019/BKNMIL"
                    
                    # Determine season
                    year = int(date_part[:4])
                    month = int(date_part[4:6])
                    
                    if month >= 10:  # Oct-Dec
                        season_year = year
                    else:  # Jan-Sep  
                        season_year = year - 1
                        
                    season_str = f"{season_year}-{str(season_year+1)[-2:]}"
                    
                    if pdf_count <= 5:  # Debug first few games
                        self.logger.info(f"Game {game_code}: season={season_str}, target_seasons={season_strs}")
                    
                    if season_str not in season_strs:
                        if pdf_count <= 5:
                            self.logger.info(f"Skipping {game_code}: season {season_str} not in target seasons {season_strs}")
                        continue
                    
                    # Track the most recent PDF for each game (highest timestamp)
                    game_key = f"{game_code}_{date_dir}"
                    timestamp_str = timestamp_file.replace('.pdf', '')  # "20250809_061835"
                    
                    if game_key not in game_dirs or timestamp_str > game_dirs[game_key]['timestamp']:
                        game_dirs[game_key] = {
                            'game_code': game_code,
                            'date': date_dir,
                            'season': season_str,
                            'pdf_path': blob.name,
                            'pdf_size': blob.size,
                            'timestamp': timestamp_str,
                            'game_dir': game_dir  # Store for JSON path
                        }
                        if pdf_count <= 5:
                            self.logger.info(f"Added/updated game: {game_code} with timestamp {timestamp_str}")
                        
                except Exception as e:
                    self.logger.error(f"Exception parsing blob {blob.name}: {e}")
                    continue
            
            self.logger.info(f"Scanned {blob_count} total blobs, {pdf_count} PDFs")
            
            # Convert to list, keeping only the most recent PDF per game
            games = list(game_dirs.values())
            self.logger.info(f"Found {len(games)} unique games with PDFs in GCS across seasons {seasons}")
            return sorted(games, key=lambda x: x['date'])
            
        except Exception as e:
            self.logger.error(f"Failed to scan GCS for existing PDFs: {e}")
            import traceback
            traceback.print_exc()
            raise
            
            # Scan the GCS bucket for existing PDFs
            prefix = "nba-com/gamebooks-pdf/"  # Fixed: nba-com not nbac-com
            blobs = bucket.list_blobs(prefix=prefix)
            
            for blob in blobs:
                if not blob.name.endswith('.pdf'):
                    continue
                    
                try:
                    # Parse blob path: nbac-com/gamebooks-pdf/2024-04-10/20240410_MEMCLE_20240410_143022.pdf
                    path_parts = blob.name.split('/')
                    if len(path_parts) < 4:
                        continue
                        
                    date_dir = path_parts[2]  # "2024-04-10"
                    filename = path_parts[3]   # "20240410_MEMCLE_20240410_143022.pdf"
                    
                    # Extract game_code from filename (before first timestamp)
                    # Pattern: YYYYMMDD_TEAMTEAM_timestamp.pdf
                    name_parts = filename.replace('.pdf', '').split('_')
                    if len(name_parts) >= 2:
                        date_part = name_parts[0]  # "20240410"
                        teams_part = name_parts[1] # "MEMCLE"
                        
                        if len(date_part) == 8 and len(teams_part) == 6:
                            game_code = f"{date_part}/{teams_part}"
                        
                        # Determine season from date_part
                        year = int(date_part[:4])
                        month = int(date_part[4:6])
                        
                        if month >= 10:  # Oct-Dec
                            season_year = year
                        else:  # Jan-Sep  
                            season_year = year - 1
                            
                        season_str = f"{season_year}-{str(season_year+1)[-2:]}"
                        
                        if season_str in season_strs:
                            games.append({
                                'game_code': game_code,
                                'date': date_dir,
                                'season': season_str,
                                'pdf_path': blob.name,
                                'pdf_size': blob.size
                            })
                                
                except Exception as e:
                    self.logger.debug(f"Could not parse blob {blob.name}: {e}")
                    continue
                    
            self.logger.info(f"Found {len(games)} existing PDFs in GCS across seasons {seasons}")
            return sorted(games, key=lambda x: x['date'])
            
        except Exception as e:
            self.logger.error(f"Failed to scan GCS for existing PDFs: {e}")
            raise

    def json_already_exists(self, game: dict) -> bool:
        """Check if parsed JSON already exists for this game"""
        try:
            from google.cloud import storage
            
            client = storage.Client()
            bucket = client.bucket(self.bucket_name)
            
            # JSON path structure: nba-com/gamebooks-data/2021-10-19/20211019-BKNMIL/timestamp.json
            date = game['date']
            game_dir = game['game_dir']  # "20211019-BKNMIL"
            
            json_dir_prefix = f"nba-com/gamebooks-data/{date}/{game_dir}/"
            
            # Check if any JSON files exist in this game directory
            blobs = bucket.list_blobs(prefix=json_dir_prefix)
            for blob in blobs:
                if blob.name.endswith('.json'):
                    self.logger.debug(f"JSON already exists: {blob.name}")
                    return True
            
            return False
            
        except Exception as e:
            self.logger.warning(f"Could not check if JSON exists for {game.get('game_code', 'unknown')}: {e}")
            return False

    def call_scraper_service(self, game: dict) -> bool:
        """Call the enhanced scraper service with pdf_source='gcs'"""
        try:
            payload = {
                "scraper": "nbac_gamebook_pdf",
                "game_code": game['game_code'],
                "pdf_source": "gcs",  # Key parameter for GCS mode
                "bucket_name": self.bucket_name,
                "pdf_path": game['pdf_path'],  # Exact path to the PDF in GCS
                "export_groups": "reparse_from_gcs"  # Use special export group for reparse
            }
            
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json=payload,
                timeout=60
            )
            
            game_code = game['game_code']
            
            if response.status_code == 200:
                result = response.json()
                if result.get('success'):
                    self.logger.debug(f"✅ {game_code}: Successfully processed")
                    return True
                else:
                    self.logger.error(f"❌ {game_code}: Scraper returned error: {result.get('error', 'Unknown')}")
                    return False
            else:
                self.logger.error(f"❌ {game_code}: HTTP {response.status_code}: {response.text[:200]}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ {game.get('game_code', 'unknown')}: Exception calling scraper service: {e}")
            return False

    def run(self, dry_run: bool = False, skip_existing: bool = True, force: bool = False) -> dict:
        """Run the reparse job"""
        
        self.logger.info("🏀 Starting NBA Gamebook PDF Reparse Job")
        self.logger.info("=" * 50)
        self.logger.info(f"Job file: nbac_reparse_job.py")
        self.logger.info(f"Mode: Reading existing PDFs from GCS")
        self.logger.info(f"Seasons: {self.seasons}")
        self.logger.info(f"Bucket: {self.bucket_name}")
        self.logger.info(f"Limit: {self.limit or 'None'}")
        self.logger.info(f"Skip existing: {skip_existing}")
        self.logger.info(f"Dry run: {dry_run}")
        self.logger.info("")
        
        # Get games by scanning existing PDFs in GCS
        games = self.get_existing_game_codes_from_gcs(self.seasons)
        
        if self.limit:
            games = games[:self.limit]
            
        stats = {
            'total_games': len(games),
            'already_parsed': 0,
            'successfully_parsed': 0,
            'failed_to_parse': 0,
            'skipped': 0
        }
        
        if dry_run:
            self.logger.info(f"🔍 DRY RUN: Would process {len(games)} games")
            
            # Show breakdown by season
            by_season = {}
            for game in games:
                season = game['season']
                by_season[season] = by_season.get(season, 0) + 1
                
            for season, count in sorted(by_season.items()):
                self.logger.info(f"  {season}: {count} games")
            
            # Show sample games
            self.logger.info("\nSample games:")
            for game in games[:10]:
                existing = "✅" if self.json_already_exists(game) else "⏳"
                self.logger.info(f"  {existing} {game['game_code']} ({game['season']}) - {game.get('pdf_size', 0):,} bytes")
            
            return {
                'dry_run': True,
                'total_games': len(games),
                'by_season': by_season
            }
        
        self.logger.info(f"Starting reparse of {len(games)} games using enhanced scraper")
        
        for i, game in enumerate(games, 1):
            game_code = game['game_code']
            date = game['date']
            
            # Check if already parsed
            if skip_existing and not force and self.json_already_exists(game):
                stats['already_parsed'] += 1
                if i % 100 == 0:
                    self.logger.info(f"Progress: {i}/{len(games)} ({i/len(games)*100:.1f}%) - {game_code} already exists")
                continue
            
            # Process the game using enhanced scraper with pdf_source="gcs"
            self.logger.info(f"[{i}/{len(games)}] Processing {game_code} ({game['season']})")
            
            success = self.call_scraper_service(game)
            
            if success:
                stats['successfully_parsed'] += 1
                self.logger.debug(f"✅ {game_code}: Processed successfully")
            else:
                stats['failed_to_parse'] += 1
                self.logger.error(f"❌ {game_code}: Processing failed")
            
            # Progress update every 50 items
            if i % 50 == 0:
                processed = i - stats['already_parsed']
                success_rate = stats['successfully_parsed'] / processed * 100 if processed > 0 else 0
                self.logger.info(f"Progress: {i}/{len(games)} ({i/len(games)*100:.1f}%) - Success rate: {success_rate:.1f}%")
            
            # Rate limiting (light since reading from GCS)
            if success and self.RATE_LIMIT_DELAY > 0:
                import time
                time.sleep(self.RATE_LIMIT_DELAY)
        
        # Final summary
        self.logger.info("")
        self.logger.info("🎯 REPARSE COMPLETE!")
        self.logger.info("=" * 50)
        self.logger.info(f"Total games found: {stats['total_games']}")
        self.logger.info(f"Already parsed: {stats['already_parsed']}")
        self.logger.info(f"Successfully parsed: {stats['successfully_parsed']}")
        self.logger.info(f"Failed to parse: {stats['failed_to_parse']}")
        
        processed = stats['total_games'] - stats['already_parsed']
        success_rate = stats['successfully_parsed'] / processed * 100 if processed > 0 else 100
        self.logger.info(f"Success rate: {success_rate:.1f}%")
        
        return stats


def main():
    parser = argparse.ArgumentParser(description="NBA Gamebook PDF Reparse Job - nbac_reparse_job.py")
    
    # Service configuration
    parser.add_argument("--scraper-service-url", 
                      default=os.getenv("SCRAPER_SERVICE_URL", "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"),
                      help="URL of the scraper service")
    
    # Season selection
    parser.add_argument("--seasons", nargs="+", type=int,
                      default=[2021, 2022, 2023, 2024],
                      help="Seasons to process (default: 2021 2022 2023 2024)")
    
    # GCS configuration
    parser.add_argument("--bucket-name", 
                      default="nba-scraped-data",
                      help="GCS bucket name")
    
    # Limiting options
    parser.add_argument("--limit", type=int, 
                      help="Limit number of games to process (for testing)")
    
    # Behavior options
    parser.add_argument("--dry-run", action="store_true",
                      help="Show what would be processed without doing it")
    
    parser.add_argument("--force", action="store_true",
                      help="Re-parse even if JSON already exists")
    
    # Parse arguments
    args = parser.parse_args()
    
    # Create and run the job
    job = NBACGamebookReparseJob(
        scraper_service_url=args.scraper_service_url,
        seasons=args.seasons,
        bucket_name=args.bucket_name,
        limit=args.limit
    )
    
    try:
        result = job.run(
            dry_run=args.dry_run,
            skip_existing=not args.force,
            force=args.force
        )
        
        # Exit successfully
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n⏸️  Job interrupted by user")
        sys.exit(1)
        
    except Exception as e:
        print(f"❌ Job failed with error: {e}")
        logging.exception("Job failed")
        sys.exit(1)

if __name__ == "__main__":
    main()