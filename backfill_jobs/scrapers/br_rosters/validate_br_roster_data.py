#!/usr/bin/env python3
"""
GCS Basketball Reference Roster Data Validation
==============================================

Validates Basketball Reference roster data directly from Google Cloud Storage.
Uses strategic sampling rather than checking all 150 files for efficiency.

Usage:
    python validate_gcs_br_data.py --sample-validation
    python validate_gcs_br_data.py --corruption-check
    python validate_gcs_br_data.py --full-inventory
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from collections import defaultdict, Counter
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class GCSBRValidator:
    """Validates Basketball Reference roster data in Google Cloud Storage."""
    
    def __init__(self):
        self.gcs_base_path = "gs://nba-scraped-data/basketball-ref/season-rosters/"
        self.seasons = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
        self.teams = [
            "ATL", "BOS", "BRK", "CHO", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
            "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", 
            "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
        ]
        
        # Validation results
        self.corruption_issues = []
        self.jersey_issues = []
        self.unicode_issues = []
        self.missing_files = []
        
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    def run_gsutil_cmd(self, cmd: List[str]) -> str:
        """Run gsutil command and return output."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"gsutil command failed: {' '.join(cmd)}")
            logger.error(f"Error: {e.stderr}")
            return ""
    
    def get_gcs_file_content(self, gcs_path: str) -> Dict[str, Any]:
        """Download and parse JSON content from GCS."""
        try:
            content = self.run_gsutil_cmd(["gsutil", "cat", gcs_path])
            if content:
                return json.loads(content)
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {gcs_path}: {e}")
            return {}
    
    def check_file_inventory(self) -> None:
        """Check that expected files exist in GCS."""
        logger.info("Checking file inventory in GCS...")
        
        # Get all files in the basketball-ref directory
        all_files = self.run_gsutil_cmd([
            "gsutil", "ls", "-r", f"{self.gcs_base_path}**/*.json"
        ])
        
        if not all_files:
            logger.error("No files found in GCS basketball-ref directory")
            return
        
        found_files = set(all_files.strip().split('\n'))
        expected_files = set()
        
        # Generate expected file paths
        for season in self.seasons:
            for team in self.teams:
                expected_path = f"{self.gcs_base_path}{season}/{team}.json"
                expected_files.add(expected_path)
        
        missing = expected_files - found_files
        extra = found_files - expected_files
        
        logger.info(f"Expected files: {len(expected_files)}")
        logger.info(f"Found files: {len(found_files)}")
        logger.info(f"Missing files: {len(missing)}")
        logger.info(f"Extra files: {len(extra)}")
        
        if missing:
            logger.warning("Missing files:")
            for f in sorted(missing):
                logger.warning(f"  {f}")
        
        self.missing_files = list(missing)
    
    def validate_sample_teams(self) -> None:
        """Validate a strategic sample of teams across seasons."""
        logger.info("Validating sample teams...")
        
        # Strategic sample: teams known to have had issues + random selection
        sample_teams = ["NYK", "LAL", "MEM", "GSW", "BOS", "MIA", "DAL", "DEN"]
        sample_seasons = ["2023-24", "2024-25", "2025-26"]  # Recent seasons
        
        total_players = 0
        files_checked = 0
        
        for season in sample_seasons:
            for team in sample_teams:
                gcs_path = f"{self.gcs_base_path}{season}/{team}.json"
                data = self.get_gcs_file_content(gcs_path)
                
                if data:
                    files_checked += 1
                    players = data.get('players', [])
                    total_players += len(players)
                    
                    # Validate this team's data
                    self._validate_team_data(data, team, season)
                else:
                    self.missing_files.append(gcs_path)
        
        logger.info(f"Sample validation: {files_checked} files, {total_players} total players")
    
    def check_name_corruption_across_all_files(self) -> None:
        """Check for name corruption across all files efficiently."""
        logger.info("Checking for corrupted names across all files...")
        
        # Use gsutil to get all file contents and grep for corruption patterns
        corruption_patterns = [
            r'^\d+,\s*\d+$',      # "4, 44" pattern
            r'^\d+\s+\d+$',       # "4 44" pattern  
            r'^\d+-\d+$',         # "6-8" height pattern
            r'^\d{1,2}$',         # Single digit only
        ]
        
        corrupted_found = False
        
        for season in self.seasons:
            for team in self.teams:
                gcs_path = f"{self.gcs_base_path}{season}/{team}.json"
                data = self.get_gcs_file_content(gcs_path)
                
                if not data:
                    continue
                
                for player in data.get('players', []):
                    full_name = player.get('full_name', '')
                    last_name = player.get('last_name', '')
                    
                    # Check for corruption patterns
                    for pattern in corruption_patterns:
                        if re.match(pattern, full_name) or re.match(pattern, last_name):
                            self.corruption_issues.append({
                                'team': team,
                                'season': season,
                                'player': player,
                                'corruption_type': pattern,
                                'gcs_path': gcs_path
                            })
                            corrupted_found = True
        
        if not corrupted_found:
            logger.info("No corrupted names found across all files ✅")
        else:
            logger.error(f"Found {len(self.corruption_issues)} corrupted names!")
    
    def _validate_team_data(self, data: Dict[str, Any], team: str, season: str) -> None:
        """Validate data for a single team."""
        players = data.get('players', [])
        
        for player in players:
            # Check for name corruption
            full_name = player.get('full_name', '')
            if re.match(r'^[\d\s,\-]+$', full_name):
                self.corruption_issues.append({
                    'team': team,
                    'season': season,
                    'player': player,
                    'issue': 'corrupted_name'
                })
            
            # Check jersey numbers
            jersey = player.get('jersey_number', '')
            if jersey and not re.match(r'^\d{1,2}$', jersey):
                self.jersey_issues.append({
                    'team': team,
                    'season': season,
                    'player': full_name,
                    'invalid_jersey': jersey
                })
            
            # Check Unicode handling
            full_name_ascii = player.get('full_name_ascii', '')
            if full_name != full_name_ascii:
                # This is expected for international players
                has_unicode = any(ord(char) > 127 for char in full_name)
                has_ascii_conversion = all(ord(char) <= 127 for char in full_name_ascii)
                
                if has_unicode and not has_ascii_conversion:
                    self.unicode_issues.append({
                        'team': team,
                        'season': season,
                        'player': full_name,
                        'ascii_version': full_name_ascii
                    })
    
    def verify_charlie_brown_fix(self) -> None:
        """Specifically verify the Charlie Brown Jr. fix."""
        logger.info("Verifying Charlie Brown Jr. fix...")
        
        # Check NYK 2024 specifically
        gcs_path = f"{self.gcs_base_path}2023-24/NYK.json"
        data = self.get_gcs_file_content(gcs_path)
        
        if not data:
            logger.error("Could not load NYK 2023-24 data for Charlie Brown Jr. verification")
            return
        
        charlie_brown = None
        for player in data.get('players', []):
            if 'brown' in player.get('full_name', '').lower():
                charlie_brown = player
                break
        
        if charlie_brown:
            logger.info("Charlie Brown Jr. verification:")
            logger.info(f"  Name: {charlie_brown.get('full_name')}")
            logger.info(f"  Last name: {charlie_brown.get('last_name')}")
            logger.info(f"  Normalized: {charlie_brown.get('normalized')}")
            logger.info(f"  Jersey numbers: {charlie_brown.get('all_jersey_numbers', [])}")
            
            # Check if fix worked
            if charlie_brown.get('full_name') == 'Charlie Brown Jr.':
                logger.info("✅ Charlie Brown Jr. fix confirmed working!")
            else:
                logger.error("❌ Charlie Brown Jr. still shows corrupted data")
        else:
            logger.warning("Charlie Brown Jr. not found in NYK 2023-24 roster")
    
    def print_summary(self) -> None:
        """Print validation summary."""
        logger.info("=" * 60)
        logger.info("GCS VALIDATION SUMMARY")
        logger.info("=" * 60)
        
        # File inventory
        if hasattr(self, 'missing_files'):
            logger.info(f"Missing files: {len(self.missing_files)}")
        
        # Name corruption
        if self.corruption_issues:
            logger.error(f"❌ CORRUPTED NAMES: {len(self.corruption_issues)} found")
            for issue in self.corruption_issues[:5]:  # Show first 5
                logger.error(f"  {issue['team']} {issue['season']}: {issue.get('corruption_type', 'unknown')}")
        else:
            logger.info("✅ NAME CORRUPTION: None found")
        
        # Jersey numbers
        if self.jersey_issues:
            logger.warning(f"⚠️  JERSEY ISSUES: {len(self.jersey_issues)} found")
        else:
            logger.info("✅ JERSEY NUMBERS: Valid")
        
        # Unicode
        if self.unicode_issues:
            logger.warning(f"⚠️  UNICODE ISSUES: {len(self.unicode_issues)} found")
        else:
            logger.info("✅ UNICODE HANDLING: Valid")
        
        # Overall status
        total_issues = len(self.corruption_issues) + len(self.jersey_issues) + len(self.unicode_issues)
        if total_issues == 0:
            logger.info("🎉 OVERALL STATUS: PASSED")
        else:
            logger.error(f"❌ OVERALL STATUS: {total_issues} issues found")


def main():
    parser = argparse.ArgumentParser(description="Validate Basketball Reference data in GCS")
    
    parser.add_argument("--sample-validation", action="store_true", 
                       help="Run strategic sample validation (recommended)")
    parser.add_argument("--corruption-check", action="store_true",
                       help="Check for name corruption across all files")
    parser.add_argument("--full-inventory", action="store_true",
                       help="Check complete file inventory")
    parser.add_argument("--charlie-brown-test", action="store_true",
                       help="Test the specific Charlie Brown Jr. fix")
    
    args = parser.parse_args()
    
    validator = GCSBRValidator()
    
    if args.sample_validation or not any([args.corruption_check, args.full_inventory, args.charlie_brown_test]):
        # Default: run sample validation
        validator.check_file_inventory()
        validator.validate_sample_teams()
        validator.verify_charlie_brown_fix()
    
    if args.corruption_check:
        validator.check_name_corruption_across_all_files()
    
    if args.full_inventory:
        validator.check_file_inventory()
    
    if args.charlie_brown_test:
        validator.verify_charlie_brown_fix()
    
    validator.print_summary()
    
    # Return exit code based on results
    total_issues = len(validator.corruption_issues) + len(validator.jersey_issues) + len(validator.unicode_issues)
    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())