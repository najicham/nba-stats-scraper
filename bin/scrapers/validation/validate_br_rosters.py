#!/usr/bin/env python3
"""
scripts/validate_br_data.py

Basketball Reference Data Validator                     v1.2 - 2025-08-07
------------------------------------------------------------------------
Validates Basketball Reference season roster data quality across multiple seasons.
Downloads sample files from GCS and runs comprehensive data quality checks.

FIXES in v1.2:
- Added specific Unicode corruption detection (Ä, Ã characters)
- Added temp directory cleanup
- Enhanced jq analysis with Unicode corruption checks
- Improved error reporting with corruption examples
- Added sample Unicode output verification

Usage:
    # Validate single season (sample teams)
    python scripts/validate_br_data.py --seasons 2024

    # Validate ALL teams for a season (120 files total)
    python scripts/validate_br_data.py --seasons 2024 --all-teams

    # Validate multiple seasons with all teams
    python scripts/validate_br_data.py --seasons 2022,2023,2024,2025 --all-teams

    # Show jq output alongside Python analysis  
    python scripts/validate_br_data.py --seasons 2024 --show-jq

    # Only run jq commands (skip Python analysis)
    python scripts/validate_br_data.py --seasons 2024 --jq-only

    # Detailed error reporting
    python scripts/validate_br_data.py --seasons 2024 --all-teams --verbose
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import tempfile
import atexit

# Add parent directory to path to import shared config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from shared.config.nba_teams import BASKETBALL_REF_TEAMS

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class BasketballRefDataValidator:
    """Validates Basketball Reference season roster data quality."""
    
    def __init__(self, bucket="nba-scraped-data", sample_teams=None, all_teams=False, 
                 verbose=False, show_jq=False, jq_only=False):
        self.bucket = bucket
        self.all_teams = all_teams
        self.sample_teams = sample_teams or (self._get_all_teams() if all_teams else ["LAL", "GSW", "MEM", "BOS", "MIA"])
        self.verbose = verbose
        self.show_jq = show_jq
        self.jq_only = jq_only
        self.temp_dir = tempfile.mkdtemp(prefix="br_validation_")
        self.validation_results = {}
        
        # Register cleanup
        atexit.register(self._cleanup_temp_dir)
        
        # Log configuration
        if self.all_teams:
            logger.info("All-teams mode: Will validate all 30 teams per season")
        else:
            logger.info("Sample mode: Will validate %d teams per season", len(self.sample_teams))
    
    def _cleanup_temp_dir(self):
        """Clean up temporary directory."""
        if hasattr(self, 'temp_dir') and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                if self.verbose:
                    logger.info("Cleaned up temp directory: %s", self.temp_dir)
            except Exception as e:
                logger.warning("Failed to clean up temp directory %s: %s", self.temp_dir, e)
    
    def _get_all_teams(self) -> List[str]:
        """Return all 30 NBA team abbreviations (Basketball Reference format)."""
        return BASKETBALL_REF_TEAMS
        
    def validate_seasons(self, seasons: List[int]) -> Dict[str, Any]:
        """Validate data quality for multiple seasons."""
        mode_desc = "ALL TEAMS" if self.all_teams else f"SAMPLE ({len(self.sample_teams)} teams)"
        
        logger.info("Starting Basketball Reference data validation")
        logger.info("Seasons: %s", seasons)
        logger.info("Mode: %s", mode_desc)
        logger.info("Teams: %s", self.sample_teams if not self.all_teams else "All 30 NBA teams")
        logger.info("Show JQ: %s, JQ Only: %s", self.show_jq, self.jq_only)
        logger.info("Temp directory: %s", self.temp_dir)
        
        overall_results = {
            "timestamp": datetime.now().isoformat(),
            "seasons_tested": seasons,
            "validation_mode": "all_teams" if self.all_teams else "sample",
            "teams_per_season": len(self.sample_teams),
            "sample_teams": self.sample_teams if not self.all_teams else "all_30_teams",
            "bucket": self.bucket,
            "seasons": {},
            "summary": {}
        }
        
        for season_year in seasons:
            logger.info(f"\n{'='*60}")
            logger.info(f"VALIDATING SEASON {season_year} ({season_year-1}-{str(season_year)[2:]}) - {mode_desc}")
            logger.info(f"{'='*60}")
            
            season_results = self.validate_season(season_year)
            overall_results["seasons"][str(season_year)] = season_results
        
        # Generate summary
        if not self.jq_only:
            overall_results["summary"] = self.generate_summary(overall_results["seasons"])
            
            # Print final report
            self.print_final_report(overall_results)
        else:
            overall_results["summary"] = {"mode": "jq_only", "note": "Comprehensive analysis skipped"}
            print(f"\n📋 JQ-ONLY MODE COMPLETED")
            print(f"Analyzed {len(seasons)} seasons with {len(self.sample_teams)} teams per season")
        
        return overall_results
    
    def validate_season(self, season_year: int) -> Dict[str, Any]:
        """Validate data quality for a single season."""
        season_str = f"{season_year-1}-{str(season_year)[2:]}"
        
        results = {
            "season": season_str,
            "year": season_year,
            "validation_mode": "all_teams" if self.all_teams else "sample",
            "gcs_check": {},
            "data_quality": {},
            "teams_analyzed": [],
            "issues_found": [],
            "metrics": {}
        }
        
        # 1. Check GCS structure
        logger.info("1. Checking GCS file structure...")
        gcs_results = self.check_gcs_structure(season_str)
        results["gcs_check"] = gcs_results
        
        if not gcs_results["files_exist"]:
            logger.error(f"No files found for season {season_str}")
            results["issues_found"].append("No files found in GCS")
            return results
        
        # 2. Download and analyze files
        logger.info("2. Downloading %s files...", "all team" if self.all_teams else "sample")
        downloaded_files = self.download_files(season_str)
        results["teams_analyzed"] = list(downloaded_files.keys())
        
        if not downloaded_files:
            logger.error("No files could be downloaded")
            results["issues_found"].append("Failed to download files")
            return results
        
        # 3. Run jq analysis if requested (FIXED: now actually called!)
        if self.show_jq or self.jq_only:
            logger.info("3. Running jq analysis...")
            self.run_jq_analysis(downloaded_files, season_str)
        
        # 4. Run Python data quality checks (skip if jq_only)
        if not self.jq_only:
            step_num = 4 if (self.show_jq or self.jq_only) else 3
            logger.info(f"{step_num}. Running Python data quality analysis...")
            quality_results = self.analyze_data_quality(downloaded_files)
            results["data_quality"] = quality_results
            results["metrics"] = quality_results.get("metrics", {})
            
            # 5. Identify issues
            issues = self.identify_issues(quality_results)
            results["issues_found"] = issues
        
        return results
    
    def check_gcs_structure(self, season_str: str) -> Dict[str, Any]:
        """Check if expected files exist in GCS."""
        gcs_path = f"gs://{self.bucket}/basketball-ref/season-rosters/{season_str}/"
        
        try:
            # List files in GCS
            result = subprocess.run(
                ["gcloud", "storage", "ls", gcs_path],
                capture_output=True, text=True, check=True
            )
            
            files = [line.strip() for line in result.stdout.split('\n') if line.strip()]
            file_count = len(files)
            
            logger.info(f"Found {file_count} files in {gcs_path}")
            
            # Extract team names from files
            available_teams = []
            for file_url in files:
                filename = file_url.split('/')[-1]  # Get filename from full path
                team_abbrev = filename.replace('.json', '')
                available_teams.append(team_abbrev)
            
            return {
                "files_exist": file_count > 0,
                "file_count": file_count,
                "expected_count": 30,
                "files_missing": max(0, 30 - file_count),
                "gcs_path": gcs_path,
                "available_teams": sorted(available_teams),
                "sample_files": files[:5] if files else []
            }
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to list GCS files: {e}", exc_info=True)
            return {
                "files_exist": False,
                "error": str(e),
                "gcs_path": gcs_path
            }
    
    def download_files(self, season_str: str) -> Dict[str, str]:
        """Download files for analysis (all teams or sample teams)."""
        downloaded = {}
        failed_teams = []
        download_times = []
        
        # Determine which teams to download
        teams_to_download = self.sample_teams
        
        logger.info(f"Downloading {len(teams_to_download)} team files from GCS...")
        start_time = datetime.now()
        
        for i, team in enumerate(teams_to_download, 1):
            gcs_file = f"gs://{self.bucket}/basketball-ref/season-rosters/{season_str}/{team}.json"
            local_file = os.path.join(self.temp_dir, f"{team}_{season_str.replace('-', '_')}.json")
            
            # Time each download
            download_start = datetime.now()
            
            try:
                result = subprocess.run(
                    ["gcloud", "storage", "cp", gcs_file, local_file],
                    capture_output=True, text=True, check=True
                )
                
                download_time = (datetime.now() - download_start).total_seconds()
                download_times.append(download_time)
                
                downloaded[team] = local_file
                file_size = os.path.getsize(local_file)
                
                # Calculate ETA
                avg_time = sum(download_times) / len(download_times)
                remaining_files = len(teams_to_download) - i
                eta_seconds = remaining_files * avg_time
                eta_str = f", ETA: {eta_seconds:.0f}s" if remaining_files > 0 else ""
                
                logger.info(f"[{i:2d}/{len(teams_to_download):2d}] ✅ {team}: {file_size:,} bytes ({download_time:.1f}s{eta_str})")
                
            except subprocess.CalledProcessError as e:
                download_time = (datetime.now() - download_start).total_seconds()
                failed_teams.append(team)
                error_msg = e.stderr.strip() if e.stderr else 'Unknown error'
                logger.warning(f"[{i:2d}/{len(teams_to_download):2d}] ❌ {team} failed ({download_time:.1f}s): {error_msg}")
        
        # Final timing summary
        total_time = (datetime.now() - start_time).total_seconds()
        avg_download_time = sum(download_times) / len(download_times) if download_times else 0
        
        if failed_teams:
            logger.warning(f"Failed to download {len(failed_teams)} teams: {failed_teams}")
        
        logger.info(f"Download completed: {len(downloaded)}/{len(teams_to_download)} files in {total_time:.1f}s (avg: {avg_download_time:.1f}s per file)")
        return downloaded
    
    def run_jq_analysis(self, files: Dict[str, str], season_str: str):
        """Run the jq validation commands for manual inspection. (FIXED: now actually called!)"""
        
        print(f"\n{'='*70}")
        print(f"🔍 JQ ANALYSIS - SEASON {season_str}")
        print(f"{'='*70}")
        
        file_paths = list(files.values())
        # SECURITY FIX: Use shlex.quote to prevent command injection
        import shlex
        file_pattern_safe = " ".join(shlex.quote(path) for path in file_paths)

        teams_analyzed = list(files.keys())
        print(f"\nAnalyzing {len(teams_analyzed)} teams: {', '.join(teams_analyzed)}")

        try:
            # 1. Player counts by team
            print(f"\n📊 PLAYER COUNTS BY TEAM:")
            print("   Format: (team_abbrev, playerCount)")
            subprocess.run(f"jq -r '.team_abbrev + \": \" + (.playerCount | tostring)' {file_pattern_safe}",
                          shell=True, check=False)
            
            # 2. UNICODE CORRUPTION CHECK (NEW!)
            print(f"\n🔍 UNICODE CORRUPTION CHECK:")
            print("   (Should be EMPTY - looking for corrupted characters like Ä, Ã)")
            result = subprocess.run(
                f"jq '.players[] | select(.full_name | test(\"Ä|Ã|Ü|Ö\")) | {{name: .full_name, ascii: .full_name_ascii, team: parent.team_abbrev}}' {file_pattern_safe}",
                shell=True, check=False, capture_output=True, text=True
            )
            if result.stdout.strip():
                print("   ⚠️  UNICODE CORRUPTION DETECTED:")
                print(result.stdout)
            else:
                print("   ✅ NO UNICODE CORRUPTION FOUND")
            
            # 3. Unicode samples (NEW!)
            print(f"\n🌍 UNICODE EXAMPLES:")
            print("   (International players showing proper UTF-8 → ASCII conversion)")
            result = subprocess.run(
                f"jq '.players[] | select(.full_name != .full_name_ascii) | \"   \" + .full_name + \" → \" + .full_name_ascii' {file_pattern_safe} | head -10",
                shell=True, check=False, capture_output=True, text=True
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print("   ℹ️  No international players found in analyzed teams")
            
            # 4. Suffix examples
            print(f"\n🏷️  SUFFIX EXAMPLES:")
            print("   (Players with suffixes - should show proper last_name extraction)")
            result = subprocess.run(
                f"jq '.players[] | select(.suffix != \"\") | {{name: .full_name, last_name: .last_name, suffix: .suffix}}' {file_pattern_safe}",
                shell=True, check=False, capture_output=True, text=True
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print("   ✅ No players with suffixes found in analyzed teams")

            # 5. Last name validation (should be empty)
            print(f"\n✅ LAST NAME VALIDATION CHECK:")
            print("   (Should be EMPTY - no suffixes should appear in last names)")
            result = subprocess.run(
                f"jq '.players[] | select(.last_name | test(\"Jr|Sr|II|III|IV\")) | {{name: .full_name, last_name: .last_name, team: parent.team_abbrev}}' {file_pattern_safe}",
                shell=True, check=False, capture_output=True, text=True
            )
            if result.stdout.strip():
                print("   ⚠️  VALIDATION FAILED - Issues found:")
                print(result.stdout)
            else:
                print("   ✅ VALIDATION PASSED - No suffixes found in last names")
            
            # 6. Normalization samples
            if file_paths:
                sample_file = file_paths[0]
                sample_team = list(files.keys())[0]
                print(f"\n🔤 NORMALIZATION SAMPLES ({sample_team}):")
                print("   (First 3 players - should be lowercase, no suffixes)")
                subprocess.run(["jq", ".players[0:3] | .[] | \"  \" + .full_name + \" → \" + .normalized", sample_file], shell=False, check=False)
            
            # 7. Position distribution across all teams
            print(f"\n🏀 POSITION DISTRIBUTION:")
            print("   (Should see standard NBA positions: PG, SG, SF, PF, C)")
            # Use sh -c with positional args to avoid shell injection while supporting pipes
            subprocess.run(["sh", "-c", "jq -r '.players[].position' \"$@\" | sort | uniq -c | sort -nr", "_"] + file_paths, shell=False, check=False)
            
            # 8. Sample players from each team
            print(f"\n👥 SAMPLE PLAYERS BY TEAM:")
            for team, file_path in files.items():
                print(f"\n   📋 {team} (first 2 players):")
                subprocess.run(["jq", "-r", ".players[0:2] | .[] | \"    #\" + (.jersey_number | tostring) + \" \" + .full_name + \" (\" + .last_name + \") - \" + .position", file_path], shell=False, check=False)
            
            # 9. Data completeness check
            print(f"\n📋 DATA COMPLETENESS:")
            print("   (Checking for missing required fields)")
            result = subprocess.run(
                f"jq '.players[] | select(.full_name == \"\" or .last_name == \"\" or .normalized == \"\") | {{team: parent.team_abbrev, name: .full_name, issue: \"missing_required_field\"}}' {file_pattern_safe}",
                shell=True, check=False, capture_output=True, text=True
            )
            if result.stdout.strip():
                print("   ⚠️  Missing data found:")
                print(result.stdout)
            else:
                print("   ✅ All required fields present")
        
        except Exception as e:
            logger.error(f"Error running jq analysis: %s", e, exc_info=True)
            print(f"   ❌ Error: {e}")
        
        print(f"\n{'='*70}")
    
    def analyze_data_quality(self, files: Dict[str, str]) -> Dict[str, Any]:
        """Run comprehensive data quality analysis."""
        results = {
            "player_counts": {},
            "unicode_corruption": {},  # NEW: Unicode corruption analysis
            "suffix_analysis": {},
            "normalization_check": {},
            "last_name_validation": {},
            "position_analysis": {},
            "data_completeness": {},
            "metrics": {}
        }
        
        all_players = []
        total_players = 0
        teams_with_issues = []
        
        for team, file_path in files.items():
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                # Basic structure validation
                player_count = data.get("playerCount", 0)
                players = data.get("players", [])
                
                results["player_counts"][team] = player_count
                total_players += player_count
                all_players.extend(players)
                
                # Team-specific analysis with enhanced error reporting
                team_issues = self.analyze_team_data(team, data)
                if team_issues:
                    teams_with_issues.append({"team": team, "issues": team_issues})
                
                if self.verbose:
                    logger.info(f"✅ {team}: {player_count} players")
                    
            except Exception as e:
                error_msg = f"File read error: {e}"
                logger.error(f"❌ Error analyzing {team}: {error_msg}", exc_info=True)
                teams_with_issues.append({"team": team, "issues": [error_msg]})
        
        # Aggregate analysis
        results["unicode_corruption"] = self.check_unicode_corruption(all_players)  # NEW!
        results["suffix_analysis"] = self.analyze_suffixes(all_players)
        results["normalization_check"] = self.check_normalization(all_players)
        results["last_name_validation"] = self.validate_last_names(all_players)
        results["position_analysis"] = self.analyze_positions(all_players)
        results["data_completeness"] = self.check_data_completeness(all_players)
        
        # Calculate metrics
        results["metrics"] = {
            "total_teams_analyzed": len(files),
            "total_players": total_players,
            "avg_players_per_team": round(total_players / len(files), 1) if files else 0,
            "teams_with_issues": len(teams_with_issues),
            "suffix_players_count": len([p for p in all_players if p.get("suffix")]),
            "suffix_percentage": round(len([p for p in all_players if p.get("suffix")]) / total_players * 100, 1) if total_players > 0 else 0,
            "unicode_corruption_count": len(results["unicode_corruption"]["corrupted_players"]),  # NEW!
            "validation_mode": "all_teams" if self.all_teams else "sample"
        }
        
        results["teams_with_issues"] = teams_with_issues
        
        return results
    
    def check_unicode_corruption(self, players: List[Dict]) -> Dict[str, Any]:
        """NEW: Check for Unicode corruption in player names."""
        corruption_patterns = ["Ä", "Ã", "Ü", "Ö", "É", "È"]  # Common corruption chars
        corrupted_players = []
        potential_fixes = []
        
        for player in players:
            full_name = player.get("full_name", "")
            full_name_ascii = player.get("full_name_ascii", "")
            
            # Check for corruption patterns
            for pattern in corruption_patterns:
                if pattern in full_name:
                    corrupted_players.append({
                        "name": full_name,
                        "ascii_version": full_name_ascii,
                        "corruption_char": pattern,
                        "team": player.get("team", "unknown")
                    })
                    break
        
        # Check for successful Unicode conversions (proper international names)
        successful_conversions = []
        for player in players:
            full_name = player.get("full_name", "")
            full_name_ascii = player.get("full_name_ascii", "")
            
            # If they're different and no corruption patterns, it's likely a good conversion
            if (full_name != full_name_ascii and 
                not any(char in full_name for char in corruption_patterns)):
                successful_conversions.append({
                    "original": full_name,
                    "ascii": full_name_ascii,
                    "team": player.get("team", "unknown")
                })
        
        return {
            "corrupted_players": corrupted_players,
            "successful_conversions": successful_conversions[:10],  # Show first 10
            "corruption_count": len(corrupted_players),
            "conversion_count": len(successful_conversions),
            "status": "CLEAN" if len(corrupted_players) == 0 else "CORRUPTED"
        }
    
    def check_data_completeness(self, players: List[Dict]) -> Dict[str, Any]:
        """Check for missing required fields across all players."""
        missing_full_name = []
        missing_last_name = []
        missing_normalized = []
        missing_position = []
        
        for player in players:
            name = player.get("full_name", "")
            if not name or name.strip() == "":
                missing_full_name.append({
                    "team": player.get("team", "unknown"),
                    "index": players.index(player)
                })
            
            last_name = player.get("last_name", "")
            if not last_name or last_name.strip() == "":
                missing_last_name.append({
                    "name": name,
                    "team": player.get("team", "unknown")
                })
            
            normalized = player.get("normalized", "")
            if not normalized or normalized.strip() == "":
                missing_normalized.append({
                    "name": name,
                    "team": player.get("team", "unknown")
                })
            
            position = player.get("position", "")
            if not position or position.strip() == "":
                missing_position.append({
                    "name": name,
                    "team": player.get("team", "unknown")
                })
        
        return {
            "missing_full_name": missing_full_name,
            "missing_last_name": missing_last_name,
            "missing_normalized": missing_normalized,
            "missing_position": missing_position,
            "completeness_score": self._calculate_completeness_score(players),
            "total_players": len(players)
        }
    
    def _calculate_completeness_score(self, players: List[Dict]) -> float:
        """Calculate data completeness score as percentage."""
        if not players:
            return 0.0
        
        required_fields = ["full_name", "last_name", "normalized", "position"]
        total_fields = len(players) * len(required_fields)
        complete_fields = 0
        
        for player in players:
            for field in required_fields:
                value = player.get(field, "")
                if value and value.strip():
                    complete_fields += 1
        
        return round(complete_fields / total_fields * 100, 1) if total_fields > 0 else 0.0
    
    def analyze_team_data(self, team: str, data: Dict) -> List[str]:
        """Analyze individual team data for issues with enhanced error reporting."""
        issues = []
        
        player_count = data.get("playerCount", 0)
        players = data.get("players", [])
        
        # Check player count consistency
        if len(players) != player_count:
            issues.append(f"Player count mismatch: reported {player_count}, actual {len(players)}")
        
        # Check reasonable player count range
        if player_count < 10:
            issues.append(f"Unusually low player count: {player_count} (missing data?)")
        elif player_count > 35:
            issues.append(f"Very high player count: {player_count} (verify data quality)")
        
        # Check for required fields with specific player names
        for i, player in enumerate(players):
            player_ref = f"Player #{i+1}"
            full_name = player.get("full_name", "")
            
            if full_name:
                player_ref = f"'{full_name}'"
            
            if not full_name or full_name.strip() == "":
                issues.append(f"{player_ref}: Missing full_name")
            
            if not player.get("last_name"):
                issues.append(f"{player_ref}: Missing last_name")
            
            if "normalized" not in player:
                issues.append(f"{player_ref}: Missing normalized field")
            
            # Check for obvious data quality issues
            if full_name and len(full_name.strip()) < 2:
                issues.append(f"{player_ref}: Full name too short: '{full_name}'")
        
        return issues
    
    def analyze_suffixes(self, players: List[Dict]) -> Dict[str, Any]:
        """Analyze suffix handling across all players."""
        suffix_players = [p for p in players if p.get("suffix")]
        suffix_counts = {}
        
        for player in suffix_players:
            suffix = player["suffix"]
            suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        
        # Check for common suffix issues
        issues = []
        for player in suffix_players:
            # Make sure suffix isn't in the last_name
            if player.get("suffix") in player.get("last_name", ""):
                issues.append({
                    "player": player['full_name'],
                    "team": player.get("team", "unknown"),
                    "issue": f"Suffix '{player['suffix']}' found in last_name '{player['last_name']}'"
                })
        
        return {
            "total_with_suffix": len(suffix_players),
            "suffix_distribution": suffix_counts,
            "sample_suffix_players": suffix_players[:5],
            "issues": issues
        }
    
    def check_normalization(self, players: List[Dict]) -> Dict[str, Any]:
        """Check normalization quality."""
        issues = []
        samples = []
        
        for player in players[:10]:  # Check first 10 for samples
            full_name = player.get("full_name", "")
            normalized = player.get("normalized", "")
            team = player.get("team", "unknown")
            
            samples.append({
                "full_name": full_name, 
                "normalized": normalized,
                "team": team
            })
            
            # Check if normalized is lowercase
            if normalized != normalized.lower():
                issues.append({
                    "player": full_name,
                    "team": team,
                    "issue": f"Normalized name not lowercase: '{normalized}'"
                })
            
            # Check if suffixes are removed
            suffixes = ["jr", "sr", "ii", "iii", "iv"]
            for suffix in suffixes:
                if suffix in normalized.lower():
                    issues.append({
                        "player": full_name,
                        "team": team,
                        "issue": f"Suffix '{suffix}' found in normalized name: '{normalized}'"
                    })
        
        return {
            "samples": samples,
            "issues": issues,
            "total_issues": len(issues)
        }
    
    def validate_last_names(self, players: List[Dict]) -> Dict[str, Any]:
        """Validate that last names don't contain suffixes."""
        problematic_last_names = []
        suffix_patterns = ["Jr", "Sr", "II", "III", "IV", "Jr.", "Sr."]
        
        for player in players:
            last_name = player.get("last_name", "")
            team = player.get("team", "unknown")
            for pattern in suffix_patterns:
                if pattern in last_name:
                    problematic_last_names.append({
                        "full_name": player.get("full_name"),
                        "last_name": last_name,
                        "team": team,
                        "issue": f"Contains '{pattern}'"
                    })
        
        return {
            "problematic_count": len(problematic_last_names),
            "problematic_names": problematic_last_names,
            "validation_passed": len(problematic_last_names) == 0
        }
    
    def analyze_positions(self, players: List[Dict]) -> Dict[str, Any]:
        """Analyze position data quality."""
        position_counts = {}
        missing_positions = 0
        players_missing_positions = []
        
        for player in players:
            position = player.get("position", "")
            team = player.get("team", "unknown")
            
            if position and position.strip():
                position_counts[position] = position_counts.get(position, 0) + 1
            else:
                missing_positions += 1
                players_missing_positions.append({
                    "name": player.get("full_name", "unknown"),
                    "team": team
                })
        
        return {
            "position_distribution": position_counts,
            "missing_positions": missing_positions,
            "players_missing_positions": players_missing_positions[:10],  # Show first 10
            "total_players": len(players)
        }
    
    def identify_issues(self, quality_results: Dict) -> List[str]:
        """Identify significant data quality issues."""
        issues = []
        
        # NEW: Check Unicode corruption
        unicode_status = quality_results["unicode_corruption"]["status"]
        corruption_count = quality_results["unicode_corruption"]["corruption_count"]
        if unicode_status == "CORRUPTED":
            issues.append(f"Unicode corruption detected: {corruption_count} players with corrupted names")
        
        # Check suffix validation
        if not quality_results["last_name_validation"]["validation_passed"]:
            count = quality_results["last_name_validation"]["problematic_count"]
            issues.append(f"Last name validation failed: {count} players with suffixes in last_name")
        
        # Check normalization issues
        norm_issues = quality_results["normalization_check"]["total_issues"]
        if norm_issues > 0:
            issues.append(f"Normalization issues: {norm_issues} problems found")
        
        # Check suffix analysis issues
        suffix_issues = len(quality_results["suffix_analysis"]["issues"])
        if suffix_issues > 0:
            issues.append(f"Suffix handling issues: {suffix_issues} problems found")
        
        # Check data completeness
        completeness = quality_results["data_completeness"]["completeness_score"]
        if completeness < 95.0:
            issues.append(f"Data completeness low: {completeness}% (expected >95%)")
        
        # Check team-specific issues
        teams_with_issues = quality_results.get("teams_with_issues", [])
        if teams_with_issues:
            issues.append(f"Team data issues: {len(teams_with_issues)} teams have problems")
        
        return issues
    
    def generate_summary(self, seasons_results: Dict) -> Dict[str, Any]:
        """Generate overall summary across all seasons."""
        total_teams = 0
        total_players = 0
        total_issues = 0
        total_unicode_corruption = 0
        seasons_with_issues = 0
        
        validation_modes = set()
        
        for season_year, results in seasons_results.items():
            metrics = results.get("metrics", {})
            total_teams += metrics.get("total_teams_analyzed", 0)
            total_players += metrics.get("total_players", 0)
            total_unicode_corruption += metrics.get("unicode_corruption_count", 0)
            validation_modes.add(metrics.get("validation_mode", "unknown"))
            
            issues = results.get("issues_found", [])
            if issues:
                seasons_with_issues += 1
                total_issues += len(issues)
        
        return {
            "seasons_analyzed": len(seasons_results),
            "validation_mode": list(validation_modes)[0] if len(validation_modes) == 1 else "mixed",
            "total_teams_analyzed": total_teams,
            "total_players": total_players,
            "avg_players_per_team": round(total_players / total_teams, 1) if total_teams > 0 else 0,
            "seasons_with_issues": seasons_with_issues,
            "total_issues_found": total_issues,
            "unicode_corruption_total": total_unicode_corruption,  # NEW!
            "overall_health": "EXCELLENT" if total_issues == 0 else "GOOD" if total_issues < 5 else "NEEDS_ATTENTION"
        }
    
    def print_final_report(self, results: Dict[str, Any]):
        """Print comprehensive final report."""
        print(f"\n{'='*70}")
        print("🏀 BASKETBALL REFERENCE DATA VALIDATION REPORT")
        print(f"{'='*70}")
        
        summary = results["summary"]
        mode_desc = "ALL TEAMS (30 per season)" if results.get("validation_mode") == "all_teams" else f"SAMPLE TEAMS ({results.get('teams_per_season', 'unknown')} per season)"
        
        print(f"Generated: {results['timestamp']}")
        print(f"Bucket: gs://{results['bucket']}")
        print(f"Mode: {mode_desc}")
        if results.get("sample_teams") != "all_30_teams":
            print(f"Sample teams: {', '.join(results['sample_teams'])}")
        
        print(f"\n📊 OVERALL SUMMARY:")
        print(f"  Seasons analyzed: {summary['seasons_analyzed']}")
        print(f"  Teams analyzed: {summary['total_teams_analyzed']}")
        print(f"  Total players: {summary['total_players']:,}")
        print(f"  Avg players/team: {summary['avg_players_per_team']}")
        print(f"  Unicode corruption: {summary['unicode_corruption_total']} players")  # NEW!
        print(f"  Issues found: {summary['total_issues_found']}")
        print(f"  Overall health: {summary['overall_health']}")
        
        # Season-by-season breakdown
        print(f"\n📅 SEASON BREAKDOWN:")
        for season_year, season_results in results["seasons"].items():
            metrics = season_results.get("metrics", {})
            issues = season_results.get("issues_found", [])
            unicode_corruption = metrics.get("unicode_corruption_count", 0)
            teams_analyzed = metrics.get("total_teams_analyzed", 0)
            status = "✅ PASS" if not issues else "⚠️  ISSUES"
            
            unicode_indicator = f" (🌍 {unicode_corruption} corrupted)" if unicode_corruption > 0 else ""
            
            print(f"  {season_results['season']:>8}: {teams_analyzed:>2} teams, "
                  f"{metrics.get('total_players', 0):>4} players, "
                  f"{len(issues):>2} issues {status}{unicode_indicator}")
        
        # Issues details with enhanced reporting
        issues_found = False
        for season_year, season_results in results["seasons"].items():
            issues = season_results.get("issues_found", [])
            teams_with_issues = season_results.get("data_quality", {}).get("teams_with_issues", [])
            unicode_corruption = season_results.get("data_quality", {}).get("unicode_corruption", {})
            
            if issues or teams_with_issues or unicode_corruption.get("corruption_count", 0) > 0:
                if not issues_found:
                    print(f"\n⚠️  DETAILED ISSUES:")
                    issues_found = True
                    
                print(f"\n  Season {season_results['season']}:")
                
                # Unicode corruption (NEW!)
                if unicode_corruption.get("corruption_count", 0) > 0:
                    print(f"    🌍 Unicode corruption found:")
                    for corrupted in unicode_corruption.get("corrupted_players", [])[:5]:  # Show first 5
                        print(f"      - {corrupted['name']} → {corrupted['ascii_version']} ({corrupted['team']})")
                
                # General issues
                for issue in issues:
                    print(f"    • {issue}")
                
                # Team-specific issues
                for team_issue in teams_with_issues:
                    team = team_issue["team"]
                    team_problems = team_issue["issues"]
                    print(f"    📋 {team}:")
                    for problem in team_problems:
                        print(f"      - {problem}")
        
        if not issues_found:
            print(f"\n🎉 NO ISSUES FOUND - DATA QUALITY EXCELLENT!")
            print(f"✅ All {summary['total_teams_analyzed']} teams passed validation")
            print(f"✅ All {summary['total_players']:,} players have complete data")
            if summary['unicode_corruption_total'] == 0:
                print(f"✅ No Unicode corruption detected")
        
        print(f"\n📁 Analysis files: {self.temp_dir}")
        print(f"   (Will be automatically cleaned up on exit)")
        print(f"{'='*70}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate Basketball Reference season roster data quality",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--seasons",
        type=str,
        required=True,
        help="Comma-separated list of seasons (ending years, e.g., '2024,2025')"
    )
    
    parser.add_argument(
        "--bucket",
        default="nba-scraped-data",
        help="GCS bucket name (default: nba-scraped-data)"
    )
    
    parser.add_argument(
        "--teams",
        type=str,
        help="Comma-separated list of sample teams (default: LAL,GSW,MEM,BOS,MIA)"
    )
    
    parser.add_argument(
        "--all-teams",
        action="store_true",
        help="Validate ALL 30 teams per season (instead of just samples)"
    )
    
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick validation with fewer sample teams (LAL,MEM only)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Verbose output with detailed analysis"
    )
    
    parser.add_argument(
        "--output",
        help="Save detailed results to JSON file"
    )
    
    parser.add_argument(
        "--show-jq",
        action="store_true",
        help="Show raw jq command output in addition to Python analysis"
    )
    
    parser.add_argument(
        "--jq-only",
        action="store_true",
        help="Skip Python analysis, only run jq commands for manual inspection"
    )
    
    args = parser.parse_args()
    
    # Parse seasons
    seasons = [int(year.strip()) for year in args.seasons.split(",")]
    
    # Parse teams
    if args.teams:
        sample_teams = [team.strip().upper() for team in args.teams.split(",")]
    elif args.quick:
        sample_teams = ["LAL", "MEM"]  # Just 2 teams for quick check
    elif args.all_teams:
        sample_teams = None  # Will be set to all 30 teams in validator
    else:
        sample_teams = ["LAL", "GSW", "MEM", "BOS", "MIA"]  # Default 5 teams
    
    # Create validator and run
    if args.verbose:
        logger.info("Arguments: all_teams=%s, show_jq=%s, jq_only=%s, verbose=%s", 
                   args.all_teams, args.show_jq, args.jq_only, args.verbose)
    
    validator = BasketballRefDataValidator(
        bucket=args.bucket,
        sample_teams=sample_teams,
        all_teams=args.all_teams,
        verbose=args.verbose,
        show_jq=args.show_jq,
        jq_only=args.jq_only
    )
    
    try:
        results = validator.validate_seasons(seasons)
        
        # Save results if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2)
            logger.info(f"Detailed results saved to: {args.output}")
        
        # Exit with non-zero if issues found (unless jq_only mode)
        if args.jq_only:
            return 0  # jq_only is just for inspection
        
        total_issues = results["summary"]["total_issues_found"]
        return 0 if total_issues == 0 else 1
        
    except Exception as e:
        logger.error(f"Validation failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())