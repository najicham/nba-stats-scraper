#!/usr/bin/env python3
# FILE: scripts/validate_gamebook_data.py

"""
NBA Gamebook Data Validator
============================

Validates downloaded gamebook data in GCS before running full backfill.
Checks file structure, data quality, and resume logic paths.

Usage:
  # Validate specific game
  python scripts/validate_gamebook_data.py --game-code "20240410/MEMCLE"
  
  # Validate recent downloads
  python scripts/validate_gamebook_data.py --recent --limit 5
  
  # Check resume logic for all games in date range
  python scripts/validate_gamebook_data.py --check-resume --start-date 2024-04-10 --end-date 2024-04-15
"""

import json
import logging
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from google.cloud import storage

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class GamebookDataValidator:
    """Validates NBA gamebook data in GCS."""
    
    def __init__(self, bucket_name: str = "nba-scraped-data"):
        self.bucket_name = bucket_name
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
    
    def validate_game(self, game_code: str) -> Dict[str, Any]:
        """Validate data for a specific game."""
        logger.info(f"🔍 Validating game: {game_code}")
        
        # Convert game_code to expected GCS paths
        date_part = game_code.split('/')[0]  # YYYYMMDD
        clean_code = game_code.replace('/', '_')  # YYYYMMDD_TEAMTEAM
        
        # Convert YYYYMMDD to YYYY-MM-DD for GCS path
        year = date_part[:4]
        month = date_part[4:6] 
        day = date_part[6:8]
        date_formatted = f"{year}-{month}-{day}"
        
        # Expected GCS paths based on your exporter config
        pdf_prefix = f"nba-com/gamebooks-pdf/{date_formatted}/game_{clean_code}/"
        data_prefix = f"nba-com/gamebooks-data/{date_formatted}/game_{clean_code}/"
        
        validation_result = {
            "game_code": game_code,
            "date_formatted": date_formatted,
            "clean_code": clean_code,
            "pdf_files": [],
            "data_files": [],
            "pdf_exists": False,
            "data_exists": False,
            "data_analysis": None,
            "validation_status": "unknown"
        }
        
        try:
            # Check for PDF files
            pdf_blobs = list(self.bucket.list_blobs(prefix=pdf_prefix))
            validation_result["pdf_files"] = [blob.name for blob in pdf_blobs]
            validation_result["pdf_exists"] = len(pdf_blobs) > 0
            
            # Check for data files  
            data_blobs = list(self.bucket.list_blobs(prefix=data_prefix))
            validation_result["data_files"] = [blob.name for blob in data_blobs]
            validation_result["data_exists"] = len(data_blobs) > 0
            
            # Analyze JSON data if available
            if data_blobs:
                latest_data_blob = max(data_blobs, key=lambda b: b.time_created)
                logger.info(f"📊 Analyzing data file: {latest_data_blob.name}")
                
                try:
                    data_content = json.loads(latest_data_blob.download_as_text())
                    validation_result["data_analysis"] = self._analyze_json_data(data_content)
                except Exception as e:
                    validation_result["data_analysis"] = {"error": str(e)}
            
            # Determine overall status
            if validation_result["pdf_exists"] and validation_result["data_exists"]:
                validation_result["validation_status"] = "complete"
            elif validation_result["data_exists"]:
                validation_result["validation_status"] = "data_only"
            elif validation_result["pdf_exists"]:
                validation_result["validation_status"] = "pdf_only"
            else:
                validation_result["validation_status"] = "missing"
                
        except Exception as e:
            validation_result["validation_status"] = "error"
            validation_result["error"] = str(e)
            logger.error(f"Error validating {game_code}: {e}")
        
        return validation_result
    
    def _analyze_json_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze the structure and quality of gamebook JSON data."""
        analysis = {
            "structure_check": "✅ Valid",
            "data_completeness": {},
            "player_analysis": {},
            "quality_issues": [],
            "sample_data": {}
        }
        
        try:
            # Check required top-level fields
            required_fields = ["game_code", "date", "matchup", "active_players", "dnp_players", "inactive_players"]
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                analysis["structure_check"] = f"❌ Missing: {missing_fields}"
                analysis["quality_issues"].append(f"Missing required fields: {missing_fields}")
            
            # Player count analysis
            active_players = data.get("active_players", [])
            dnp_players = data.get("dnp_players", [])
            inactive_players = data.get("inactive_players", [])
            
            analysis["player_analysis"] = {
                "active_count": len(active_players),
                "dnp_count": len(dnp_players),
                "inactive_count": len(inactive_players),
                "total_count": len(active_players) + len(dnp_players) + len(inactive_players)
            }
            
            # Data completeness checks
            analysis["data_completeness"] = {
                "has_arena": bool(data.get("arena")),
                "has_attendance": bool(data.get("attendance")),
                "has_officials": bool(data.get("officials")),
                "has_timestamp": bool(data.get("timestamp")),
                "has_game_duration": bool(data.get("game_duration")),
            }
            
            # Sample player data
            if active_players:
                sample_active = active_players[0]
                analysis["sample_data"]["active_player"] = {
                    "name": sample_active.get("name"),
                    "team": sample_active.get("team"),
                    "has_stats": bool(sample_active.get("stats")),
                    "points": sample_active.get("stats", {}).get("points"),
                    "minutes": sample_active.get("stats", {}).get("minutes")
                }
            
            if dnp_players:
                sample_dnp = dnp_players[0]
                analysis["sample_data"]["dnp_player"] = {
                    "name": sample_dnp.get("name"),
                    "team": sample_dnp.get("team"),
                    "dnp_reason": sample_dnp.get("dnp_reason"),
                    "category": sample_dnp.get("category")
                }
            
            # Quality checks
            if analysis["player_analysis"]["total_count"] < 25:
                analysis["quality_issues"].append(f"Low player count: {analysis['player_analysis']['total_count']}")
            
            if analysis["player_analysis"]["active_count"] < 10:
                analysis["quality_issues"].append(f"Low active player count: {analysis['player_analysis']['active_count']}")
            
            # Check for obvious parsing issues
            if not data.get("arena") or not data.get("attendance"):
                analysis["quality_issues"].append("Missing game metadata (arena/attendance)")
                
        except Exception as e:
            analysis["structure_check"] = f"❌ Analysis failed: {e}"
        
        return analysis
    
    def check_recent_downloads(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Check most recent gamebook downloads."""
        logger.info(f"🔍 Checking {limit} most recent downloads...")
        
        # List recent data files
        data_prefix = "nba-com/gamebooks-data/"
        recent_blobs = []
        
        for blob in self.bucket.list_blobs(prefix=data_prefix):
            if blob.name.endswith('.json'):
                recent_blobs.append(blob)
        
        # Sort by creation time, get most recent
        recent_blobs.sort(key=lambda b: b.time_created, reverse=True)
        recent_blobs = recent_blobs[:limit]
        
        results = []
        for blob in recent_blobs:
            # Extract game_code from path
            # Path: nba-com/gamebooks-data/2024-04-10/game_20240410_MEMCLE/timestamp.json
            path_parts = blob.name.split('/')
            if len(path_parts) >= 4:
                game_dir = path_parts[3]  # "game_20240410_MEMCLE"
                if game_dir.startswith('game_'):
                    clean_code = game_dir[5:]  # "20240410_MEMCLE"
                    game_code = clean_code.replace('_', '/', 1)  # "20240410/MEMCLE"
                    
                    validation = self.validate_game(game_code)
                    validation["blob_name"] = blob.name
                    validation["created_at"] = blob.time_created.isoformat()
                    results.append(validation)
        
        return results
    
    def check_resume_logic(self, start_date: str, end_date: str) -> Dict[str, Any]:
        """Test resume logic by checking which games in date range exist."""
        logger.info(f"🔍 Checking resume logic for {start_date} to {end_date}")
        
        # Generate date range
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        results = {
            "date_range": f"{start_date} to {end_date}",
            "games_checked": 0,
            "games_exist": 0,
            "games_missing": 0,
            "existing_games": [],
            "missing_games": []
        }
        
        current_date = start_dt
        while current_date <= end_dt:
            date_str = current_date.strftime("%Y-%m-%d")
            
            # Check what games exist for this date
            date_prefix = f"nba-com/gamebooks-data/{date_str}/"
            
            game_dirs = set()
            for blob in self.bucket.list_blobs(prefix=date_prefix):
                path_parts = blob.name.split('/')
                if len(path_parts) >= 4 and path_parts[3].startswith('game_'):
                    game_dirs.add(path_parts[3])  # "game_20240410_MEMCLE"
            
            for game_dir in game_dirs:
                clean_code = game_dir[5:]  # Remove "game_" prefix
                game_code = clean_code.replace('_', '/', 1)  # Convert to standard format
                
                results["games_checked"] += 1
                results["games_exist"] += 1
                results["existing_games"].append({
                    "game_code": game_code,
                    "date": date_str,
                    "gcs_path": f"{date_prefix}{game_dir}/"
                })
            
            current_date += timedelta(days=1)
        
        results["games_missing"] = results["games_checked"] - results["games_exist"]
        
        return results
    
    def print_validation_report(self, validation: Dict[str, Any]):
        """Print a formatted validation report."""
        print(f"\n🏀 GAME VALIDATION REPORT")
        print(f"=" * 50)
        print(f"Game Code: {validation['game_code']}")
        print(f"Date: {validation['date_formatted']}")
        print(f"Status: {validation['validation_status']}")
        print()
        
        print(f"📁 GCS Files:")
        print(f"  PDF Files: {len(validation['pdf_files'])} {'✅' if validation['pdf_exists'] else '❌'}")
        print(f"  Data Files: {len(validation['data_files'])} {'✅' if validation['data_exists'] else '❌'}")
        
        if validation.get("data_analysis"):
            analysis = validation["data_analysis"]
            print(f"\n📊 Data Analysis:")
            print(f"  Structure: {analysis['structure_check']}")
            
            if "player_analysis" in analysis:
                pa = analysis["player_analysis"]
                print(f"  Players: {pa['active_count']} active, {pa['dnp_count']} DNP, {pa['inactive_count']} inactive")
                print(f"  Total: {pa['total_count']} players")
            
            if "data_completeness" in analysis:
                dc = analysis["data_completeness"]
                completeness_score = sum(dc.values()) / len(dc) * 100
                print(f"  Completeness: {completeness_score:.0f}%")
                
                missing = [k for k, v in dc.items() if not v]
                if missing:
                    print(f"  Missing: {missing}")
            
            if "sample_data" in analysis and analysis["sample_data"]:
                print(f"\n🏀 Sample Data:")
                sd = analysis["sample_data"]
                
                if "active_player" in sd:
                    ap = sd["active_player"]
                    print(f"  Active: {ap['name']} ({ap['team']}) - {ap['points']} pts, {ap['minutes']} min")
                
                if "dnp_player" in sd:
                    dp = sd["dnp_player"]
                    print(f"  DNP: {dp['name']} ({dp['team']}) - {dp['dnp_reason']}")
            
            if analysis.get("quality_issues"):
                print(f"\n⚠️  Quality Issues:")
                for issue in analysis["quality_issues"]:
                    print(f"  - {issue}")
        
        print()


def main():
    parser = argparse.ArgumentParser(description="Validate NBA gamebook data in GCS")
    
    # Validation modes
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--game-code", help="Validate specific game (YYYYMMDD/TEAMTEAM)")
    mode_group.add_argument("--recent", action="store_true", help="Check recent downloads")
    mode_group.add_argument("--check-resume", action="store_true", help="Test resume logic for date range")
    
    # Additional options
    parser.add_argument("--bucket", default="nba-scraped-data", help="GCS bucket name")
    parser.add_argument("--limit", type=int, default=10, help="Limit for recent downloads")
    parser.add_argument("--start-date", help="Start date for resume check (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date for resume check (YYYY-MM-DD)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.check_resume and (not args.start_date or not args.end_date):
        parser.error("--check-resume requires --start-date and --end-date")
    
    try:
        validator = GamebookDataValidator(args.bucket)
        
        if args.game_code:
            # Validate specific game
            validation = validator.validate_game(args.game_code)
            validator.print_validation_report(validation)
            
            # Show file contents with jq-style analysis
            if validation["data_exists"]:
                print("📄 JSON STRUCTURE (jq-style):")
                print("-" * 30)
                
                # Get the data file content
                data_files = validation["data_files"]
                if data_files:
                    latest_file = max(data_files)  # Most recent by name
                    blob = validator.bucket.blob(latest_file)
                    data_content = json.loads(blob.download_as_text())
                    
                    # Show key structure
                    print("Top-level keys:")
                    for key in sorted(data_content.keys()):
                        value = data_content[key]
                        if isinstance(value, list):
                            print(f"  .{key}: [{len(value)} items]")
                        elif isinstance(value, dict):
                            print(f"  .{key}: {{...}} ({len(value)} keys)")
                        else:
                            print(f"  .{key}: {type(value).__name__}")
                    
                    # Show player samples
                    if data_content.get("active_players"):
                        print(f"\nActive player sample:")
                        ap = data_content["active_players"][0]
                        print(f"  Name: {ap.get('name')}")
                        print(f"  Team: {ap.get('team')}")
                        print(f"  Points: {ap.get('stats', {}).get('points')}")
                        print(f"  Stats keys: {list(ap.get('stats', {}).keys())}")
                    
                    if data_content.get("dnp_players"):
                        print(f"\nDNP player sample:")
                        dp = data_content["dnp_players"][0]
                        print(f"  Name: {dp.get('name')}")
                        print(f"  Reason: {dp.get('dnp_reason')}")
        
        elif args.recent:
            # Check recent downloads
            recent_validations = validator.check_recent_downloads(args.limit)
            
            print(f"\n🔍 RECENT DOWNLOADS ({len(recent_validations)} found)")
            print("=" * 60)
            
            for validation in recent_validations:
                status_emoji = {
                    "complete": "✅",
                    "data_only": "📊", 
                    "pdf_only": "📄",
                    "missing": "❌",
                    "error": "💥"
                }.get(validation["validation_status"], "❓")
                
                print(f"{status_emoji} {validation['game_code']} - {validation['validation_status']}")
                
                if validation.get("data_analysis", {}).get("player_analysis"):
                    pa = validation["data_analysis"]["player_analysis"]
                    print(f"   Players: {pa['active_count']} active, {pa['dnp_count']} DNP, {pa['inactive_count']} inactive")
        
        elif args.check_resume:
            # Test resume logic
            resume_results = validator.check_resume_logic(args.start_date, args.end_date)
            
            print(f"\n🔄 RESUME LOGIC TEST")
            print("=" * 50)
            print(f"Date Range: {resume_results['date_range']}")
            print(f"Games Found: {resume_results['games_exist']} existing")
            print(f"Would Skip: {resume_results['games_exist']} games")
            print(f"Would Download: {resume_results['games_missing']} games")
            
            if resume_results["existing_games"]:
                print(f"\nExisting games (showing first 5):")
                for game in resume_results["existing_games"][:5]:
                    print(f"  ✅ {game['game_code']} - {game['date']}")
    
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())