#!/usr/bin/env python3
"""
VALIDATOR: NBA Player Name Matching Validator (UPDATED)

File: bin/processors/validation/validate_player_name_matching.py

Validates player name consistency between NBA.com gamebook and BDL boxscore data:
- Comprehensive comparison including ALL players (active, inactive, dnp)
- Identifies exact matches, close matches, and genuine mismatches
- Analyzes player status impact on cross-source availability
- Generates actionable recommendations for props platform data quality
- Enhanced name normalization and matching algorithms

Usage:
    python validate_player_name_matching.py --date 2024-01-15
    python validate_player_name_matching.py --start-date 2024-01-01 --end-date 2024-01-31

Output:
    - Comprehensive console report with status analysis
    - CSV exports with detailed name comparison data
    - Actionable recommendations for name mapping rules
"""

import logging
import sys
import argparse
from datetime import datetime, date
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from google.cloud import bigquery
import pandas as pd
import re
from difflib import SequenceMatcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class PlayerRecord:
    """Player record from a single source."""
    game_date: date
    game_id: str
    team_abbr: str
    player_name: str
    normalized_name: str
    minutes: str
    points: int
    source: str  # 'nba' or 'bdl'
    player_status: str = None  # NBA.com only: 'active', 'inactive', 'dnp'
    dnp_reason: str = None     # NBA.com only: injury details, etc.

@dataclass
class NameMatchResult:
    """Result of comprehensive name matching analysis."""
    game_date: date
    game_id: str
    team_abbr: str
    nba_name: str
    bdl_name: str
    match_type: str  # 'exact', 'close', 'mismatch', 'nba_only', 'bdl_only'
    similarity_score: float
    nba_minutes: str
    bdl_minutes: str
    nba_points: int
    bdl_points: int
    nba_status: str
    nba_dnp_reason: str
    stats_match: bool
    name_pattern: str  # Classification of name difference
    confidence: str   # 'high', 'medium', 'low' - confidence in match

class NBAPlayerNameValidator:
    """
    Enhanced validator for player name consistency between NBA.com and BDL.
    
    Key Features:
    - Includes ALL players regardless of status (active/inactive/dnp)
    - Status-aware matching analysis for props platform needs
    - Enhanced name normalization with common NBA patterns
    - Confidence scoring for match quality assessment
    """
    
    def __init__(self, project_id: str = None):
        if project_id is None:
            project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        
    def validate_name_matching(
        self, 
        target_date: str = None,
        start_date: str = "2024-01-01",
        end_date: str = "2024-01-31"
    ) -> List[NameMatchResult]:
        """
        Perform comprehensive name matching validation.
        
        Args:
            target_date: Single date for validation (format: YYYY-MM-DD)
            start_date: Start date for range validation
            end_date: End date for range validation
            
        Returns:
            List of NameMatchResult objects with detailed analysis
        """
        if target_date:
            start_date = end_date = target_date
            logger.info(f"Validating player name matching for: {target_date}")
        else:
            logger.info(f"Validating player name matching: {start_date} to {end_date}")
        
        # Load player data from both sources
        logger.info("Loading NBA.com gamebook player data (ALL statuses)...")
        nba_players = self._load_nba_players(start_date, end_date)
        
        logger.info("Loading BDL boxscore player data...")
        bdl_players = self._load_bdl_players(start_date, end_date)
        
        # Perform enhanced name matching analysis
        logger.info("Analyzing name matching patterns...")
        match_results = self._analyze_name_matches(nba_players, bdl_players)
        
        return match_results
    
    def _load_nba_players(self, start_date: str, end_date: str) -> List[PlayerRecord]:
        """Load ALL NBA.com player data regardless of status."""
        query = f"""
        SELECT 
            game_date,
            game_id,
            team_abbr,
            player_name,
            player_status,
            dnp_reason,
            minutes,
            points
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND team_abbr IS NOT NULL
          AND player_name IS NOT NULL
        ORDER BY game_date, game_id, team_abbr, player_name
        """
        
        try:
            results = self.client.query(query).to_dataframe()
        except Exception as e:
            logger.error(f"Failed to load NBA.com data: {e}")
            return []
        
        players = []
        for _, row in results.iterrows():
            # Handle NULL values properly
            minutes = str(row['minutes']) if pd.notna(row['minutes']) else '0:00'
            points = int(row['points']) if pd.notna(row['points']) else 0
            dnp_reason = str(row['dnp_reason']) if pd.notna(row['dnp_reason']) else None
            
            players.append(PlayerRecord(
                game_date=row['game_date'],
                game_id=row['game_id'],
                team_abbr=row['team_abbr'],
                player_name=row['player_name'],
                normalized_name=self._normalize_name(row['player_name']),
                minutes=minutes,
                points=points,
                source='nba',
                player_status=row['player_status'],
                dnp_reason=dnp_reason
            ))
        
        logger.info(f"Loaded {len(players)} NBA.com player records (all statuses included)")
        return players
    
    def _load_bdl_players(self, start_date: str, end_date: str) -> List[PlayerRecord]:
        """Load BDL player data."""
        query = f"""
        SELECT 
            game_date,
            game_id,
            team_abbr,
            player_full_name,
            minutes,
            points
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND team_abbr IS NOT NULL
          AND player_full_name IS NOT NULL
        ORDER BY game_date, game_id, team_abbr, player_full_name
        """
        
        try:
            results = self.client.query(query).to_dataframe()
        except Exception as e:
            logger.error(f"Failed to load BDL data: {e}")
            return []
        
        players = []
        for _, row in results.iterrows():
            # Handle NULL values properly
            minutes = str(row['minutes']) if pd.notna(row['minutes']) else '0'
            points = int(row['points']) if pd.notna(row['points']) else 0
            
            players.append(PlayerRecord(
                game_date=row['game_date'],
                game_id=row['game_id'],
                team_abbr=row['team_abbr'],
                player_name=row['player_full_name'],
                normalized_name=self._normalize_name(row['player_full_name']),
                minutes=minutes,
                points=points,
                source='bdl'
            ))
        
        logger.info(f"Loaded {len(players)} BDL player records")
        return players
    
    def _normalize_name(self, name: str) -> str:
        """Enhanced name normalization for NBA player names."""
        if not name:
            return ""
        
        # Basic cleanup
        normalized = re.sub(r'\s+', ' ', name.strip())
        
        # Convert to uppercase for comparison
        normalized = normalized.upper()
        
        # Remove common punctuation but preserve apostrophes
        normalized = re.sub(r"[^\w\s']", '', normalized)
        
        # Standardize generational suffixes (key NBA naming pattern)
        normalized = re.sub(r'\bJR\.?\b', 'JR', normalized)
        normalized = re.sub(r'\bSR\.?\b', 'SR', normalized)
        normalized = re.sub(r'\bIII\.?\b', 'III', normalized)
        normalized = re.sub(r'\bIV\.?\b', 'IV', normalized)
        
        # Clean up extra spaces
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        return normalized
    
    def _create_game_team_key(self, game_id: str, team_abbr: str) -> str:
        """Create unique key for grouping players by game and team."""
        return f"{game_id}_{team_abbr}"
    
    def _calculate_similarity(self, name1: str, name2: str) -> float:
        """Enhanced similarity calculation."""
        # Basic string similarity
        basic_similarity = SequenceMatcher(None, name1, name2).ratio()
        
        # Word-level similarity (handles reordering)
        words1 = set(name1.split())
        words2 = set(name2.split())
        
        if not words1 or not words2:
            return basic_similarity
        
        common_words = len(words1 & words2)
        total_words = len(words1 | words2)
        word_similarity = common_words / total_words if total_words > 0 else 0
        
        # Weighted combination (favor word similarity for NBA names)
        return (basic_similarity * 0.4) + (word_similarity * 0.6)
    
    def _stats_match(self, nba_player: PlayerRecord, bdl_player: PlayerRecord) -> bool:
        """Enhanced stats matching for player identification."""
        # Points must match exactly (strong indicator)
        if nba_player.points != bdl_player.points:
            return False
        
        # Extract and compare minutes
        nba_min = self._extract_minutes(nba_player.minutes)
        bdl_min = self._extract_minutes(bdl_player.minutes)
        
        # For players with significant minutes, allow small variance
        if nba_min > 5 or bdl_min > 5:
            return abs(nba_min - bdl_min) <= 1
        
        # For players with minimal/no minutes, exact match required
        return nba_min == bdl_min
    
    def _extract_minutes(self, minutes_str: str) -> int:
        """Extract minutes as integer from various formats."""
        if not minutes_str or minutes_str == 'nan':
            return 0
        
        # Handle "MM:SS" format
        if ':' in minutes_str:
            parts = minutes_str.split(':')
            try:
                return int(float(parts[0]))
            except (ValueError, IndexError):
                return 0
        
        # Handle direct minute values
        try:
            return int(float(minutes_str))
        except ValueError:
            return 0
    
    def _classify_name_pattern(self, nba_name: str, bdl_name: str) -> str:
        """Enhanced classification of name differences."""
        nba_norm = self._normalize_name(nba_name)
        bdl_norm = self._normalize_name(bdl_name)
        
        # Exact match
        if nba_norm == bdl_norm:
            return 'exact_match'
        
        # Generational suffix differences (common NBA issue)
        nba_words = set(nba_norm.split())
        bdl_words = set(bdl_norm.split())
        
        generational_suffixes = {'JR', 'SR', 'III', 'IV'}
        nba_suffixes = nba_words & generational_suffixes
        bdl_suffixes = bdl_words & generational_suffixes
        
        if nba_suffixes != bdl_suffixes:
            return 'generational_suffix'
        
        # Name order differences
        if nba_words == bdl_words:
            return 'word_order'
        
        # Core name similarity (nickname vs full name)
        core_words_overlap = len(nba_words & bdl_words) / max(len(nba_words), len(bdl_words))
        if core_words_overlap >= 0.5:
            if abs(len(nba_norm) - len(bdl_norm)) > 5:
                return 'nickname_vs_full'
            else:
                return 'minor_formatting'
        
        # Apostrophe differences
        if nba_name.count("'") != bdl_name.count("'"):
            return 'apostrophe_difference'
        
        return 'significant_difference'
    
    def _determine_confidence(self, similarity: float, stats_match: bool, pattern: str) -> str:
        """Determine confidence level in the match."""
        if pattern == 'exact_match':
            return 'high'
        
        if stats_match and similarity > 0.7:
            return 'high'
        
        if similarity > 0.8 or (stats_match and similarity > 0.5):
            return 'medium'
        
        if pattern in ['generational_suffix', 'word_order', 'minor_formatting']:
            return 'medium'
        
        return 'low'
    
    def _analyze_name_matches(
        self, 
        nba_players: List[PlayerRecord], 
        bdl_players: List[PlayerRecord]
    ) -> List[NameMatchResult]:
        """Enhanced name matching analysis with status awareness."""
        
        # Group players by game and team
        nba_by_game_team = {}
        bdl_by_game_team = {}
        
        for player in nba_players:
            key = self._create_game_team_key(player.game_id, player.team_abbr)
            if key not in nba_by_game_team:
                nba_by_game_team[key] = []
            nba_by_game_team[key].append(player)
        
        for player in bdl_players:
            key = self._create_game_team_key(player.game_id, player.team_abbr)
            if key not in bdl_by_game_team:
                bdl_by_game_team[key] = []
            bdl_by_game_team[key].append(player)
        
        match_results = []
        
        # Analyze each game/team combination
        all_keys = set(nba_by_game_team.keys()) | set(bdl_by_game_team.keys())
        
        for key in sorted(all_keys):
            nba_team_players = nba_by_game_team.get(key, [])
            bdl_team_players = bdl_by_game_team.get(key, [])
            
            # Enhanced matching algorithm
            used_bdl_indices = set()
            
            for nba_player in nba_team_players:
                best_match = None
                best_score = 0
                best_stats_match = False
                best_bdl_idx = -1
                
                for i, bdl_player in enumerate(bdl_team_players):
                    if i in used_bdl_indices:
                        continue
                    
                    # Calculate similarity and stats match
                    similarity = self._calculate_similarity(
                        nba_player.normalized_name, 
                        bdl_player.normalized_name
                    )
                    stats_match = self._stats_match(nba_player, bdl_player)
                    
                    # Enhanced scoring: prioritize stats match + decent name similarity
                    if stats_match and similarity > 0.3:
                        best_match = bdl_player
                        best_score = similarity
                        best_stats_match = True
                        best_bdl_idx = i
                        break  # Stats match is strong indicator
                    elif similarity > best_score and similarity > 0.6:
                        best_match = bdl_player
                        best_score = similarity
                        best_stats_match = stats_match
                        best_bdl_idx = i
                
                if best_match:
                    used_bdl_indices.add(best_bdl_idx)
                    
                    # Classify match quality
                    pattern = self._classify_name_pattern(nba_player.player_name, best_match.player_name)
                    confidence = self._determine_confidence(best_score, best_stats_match, pattern)
                    
                    if pattern == 'exact_match':
                        match_type = 'exact'
                    elif confidence in ['high', 'medium']:
                        match_type = 'close'
                    else:
                        match_type = 'mismatch'
                    
                    match_results.append(NameMatchResult(
                        game_date=nba_player.game_date,
                        game_id=nba_player.game_id,
                        team_abbr=nba_player.team_abbr,
                        nba_name=nba_player.player_name,
                        bdl_name=best_match.player_name,
                        match_type=match_type,
                        similarity_score=best_score,
                        nba_minutes=nba_player.minutes,
                        bdl_minutes=best_match.minutes,
                        nba_points=nba_player.points,
                        bdl_points=best_match.points,
                        nba_status=nba_player.player_status,
                        nba_dnp_reason=nba_player.dnp_reason,
                        stats_match=best_stats_match,
                        name_pattern=pattern,
                        confidence=confidence
                    ))
                else:
                    # NBA player not found in BDL
                    match_results.append(NameMatchResult(
                        game_date=nba_player.game_date,
                        game_id=nba_player.game_id,
                        team_abbr=nba_player.team_abbr,
                        nba_name=nba_player.player_name,
                        bdl_name=None,
                        match_type='nba_only',
                        similarity_score=0.0,
                        nba_minutes=nba_player.minutes,
                        bdl_minutes=None,
                        nba_points=nba_player.points,
                        bdl_points=None,
                        nba_status=nba_player.player_status,
                        nba_dnp_reason=nba_player.dnp_reason,
                        stats_match=False,
                        name_pattern='missing_from_bdl',
                        confidence='high'  # High confidence it's missing
                    ))
            
            # Find BDL players not matched to NBA players
            for i, bdl_player in enumerate(bdl_team_players):
                if i not in used_bdl_indices:
                    match_results.append(NameMatchResult(
                        game_date=bdl_player.game_date,
                        game_id=bdl_player.game_id,
                        team_abbr=bdl_player.team_abbr,
                        nba_name=None,
                        bdl_name=bdl_player.player_name,
                        match_type='bdl_only',
                        similarity_score=0.0,
                        nba_minutes=None,
                        bdl_minutes=bdl_player.minutes,
                        nba_points=None,
                        bdl_points=bdl_player.points,
                        nba_status=None,
                        nba_dnp_reason=None,
                        stats_match=False,
                        name_pattern='missing_from_nba',
                        confidence='high'  # High confidence it's missing
                    ))
        
        logger.info(f"Generated {len(match_results)} match analysis results")
        return match_results
    
    def print_comprehensive_report(self, results: List[NameMatchResult]):
        """Print comprehensive validation report with actionable insights."""
        print("\n" + "="*90)
        print("NBA PLAYER NAME MATCHING VALIDATION REPORT - ENHANCED")
        print("="*90)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Purpose: Cross-source player identity validation for NBA Props Platform")
        
        # Overall statistics
        total_results = len(results)
        exact_matches = len([r for r in results if r.match_type == 'exact'])
        close_matches = len([r for r in results if r.match_type == 'close'])
        mismatches = len([r for r in results if r.match_type == 'mismatch'])
        nba_only = len([r for r in results if r.match_type == 'nba_only'])
        bdl_only = len([r for r in results if r.match_type == 'bdl_only'])
        
        print(f"\nOVERALL MATCHING STATISTICS:")
        print(f"  Total Player Records Analyzed: {total_results:,}")
        print(f"  Exact Name Matches: {exact_matches:,} ({exact_matches/total_results*100:.1f}%)")
        print(f"  Close Matches (same player): {close_matches:,} ({close_matches/total_results*100:.1f}%)")
        print(f"  Mismatches (uncertain): {mismatches:,} ({mismatches/total_results*100:.1f}%)")
        print(f"  NBA.com Only: {nba_only:,} ({nba_only/total_results*100:.1f}%)")
        print(f"  BDL Only: {bdl_only:,} ({bdl_only/total_results*100:.1f}%)")
        
        successful_matches = exact_matches + close_matches
        success_rate = successful_matches/total_results*100 if total_results > 0 else 0
        print(f"\n🎯 MATCHING SUCCESS RATE: {success_rate:.1f}%")
        
        # Player status analysis for matched players
        matched_with_status = [r for r in results if r.match_type in ['exact', 'close'] and r.nba_status]
        if matched_with_status:
            status_counts = {}
            for result in matched_with_status:
                status = result.nba_status
                status_counts[status] = status_counts.get(status, 0) + 1
            
            print(f"\nPLAYER STATUS BREAKDOWN (Matched Players):")
            for status, count in sorted(status_counts.items()):
                pct = count/len(matched_with_status)*100
                print(f"  {status.title()}: {count:,} ({pct:.1f}%)")
        
        # Name pattern analysis
        pattern_counts = {}
        confidence_counts = {'high': 0, 'medium': 0, 'low': 0}
        
        for result in results:
            if result.match_type in ['exact', 'close', 'mismatch']:
                pattern = result.name_pattern
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
                confidence_counts[result.confidence] += 1
        
        if pattern_counts:
            print(f"\nNAME VARIATION PATTERNS:")
            for pattern, count in sorted(pattern_counts.items(), key=lambda x: x[1], reverse=True)[:8]:
                print(f"  {pattern.replace('_', ' ').title()}: {count:,} cases")
        
        print(f"\nMATCH CONFIDENCE LEVELS:")
        for confidence, count in confidence_counts.items():
            if count > 0:
                pct = count/total_results*100
                print(f"  {confidence.title()} Confidence: {count:,} ({pct:.1f}%)")
        
        # Analysis of unmatched players
        if nba_only > 0:
            print(f"\nNBA.COM ONLY ANALYSIS ({nba_only} players):")
            nba_only_results = [r for r in results if r.match_type == 'nba_only']
            
            # Status breakdown of NBA-only players
            nba_only_status = {}
            for result in nba_only_results:
                status = result.nba_status or 'unknown'
                nba_only_status[status] = nba_only_status.get(status, 0) + 1
            
            for status, count in sorted(nba_only_status.items()):
                print(f"  {status.title()}: {count} players")
            
            # Show examples
            print(f"\n  Examples (first 5):")
            for result in nba_only_results[:5]:
                status_info = f" ({result.nba_status})" if result.nba_status else ""
                print(f"    {result.nba_name}{status_info} - {result.nba_points} pts, {result.nba_minutes} min")
        
        if bdl_only > 0:
            print(f"\nBDL ONLY ANALYSIS ({bdl_only} players):")
            bdl_only_results = [r for r in results if r.match_type == 'bdl_only']
            
            # Points distribution for BDL-only players
            zero_points = len([r for r in bdl_only_results if r.bdl_points == 0])
            with_points = bdl_only - zero_points
            
            print(f"  Players with 0 points: {zero_points} (likely injured/inactive)")
            print(f"  Players with >0 points: {with_points} (potential data gaps)")
            
            if with_points > 0:
                print(f"\n  Players with points (potential issues):")
                scoring_players = [r for r in bdl_only_results if r.bdl_points > 0]
                for result in scoring_players[:5]:
                    print(f"    {result.bdl_name} - {result.bdl_points} pts, {result.bdl_minutes} min")
        
        # Actionable recommendations
        print(f"\n📋 ACTIONABLE RECOMMENDATIONS:")
        
        if success_rate >= 80:
            print(f"✅ GOOD: {success_rate:.1f}% success rate is acceptable for production")
        else:
            print(f"⚠️  CONCERN: {success_rate:.1f}% success rate may impact props accuracy")
        
        if close_matches > 0:
            print(f"🔧 BUILD NAME MAPPER: {close_matches} close matches need standardization rules")
        
        if pattern_counts:
            top_pattern = max(pattern_counts.items(), key=lambda x: x[1])
            print(f"🎯 PRIORITY PATTERN: Focus on '{top_pattern[0]}' ({top_pattern[1]} cases)")
        
        if mismatches > total_results * 0.05:
            print(f"🔍 INVESTIGATE: {mismatches} mismatches need manual review")
        
        print(f"\n💡 PROPS PLATFORM IMPACT:")
        print(f"   - {successful_matches} players have reliable cross-source matching")
        print(f"   - {nba_only + bdl_only} players need special handling in props validation")
        print(f"   - Name mapper needed for {close_matches} variation patterns")
        
        print("="*90)
    
    def export_results_to_csv(self, results: List[NameMatchResult]):
        """Export comprehensive analysis to CSV files."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Export all results with full details
        all_data = []
        for result in results:
            all_data.append({
                'game_date': result.game_date,
                'game_id': result.game_id,
                'team_abbr': result.team_abbr,
                'nba_name': result.nba_name,
                'bdl_name': result.bdl_name,
                'match_type': result.match_type,
                'similarity_score': round(result.similarity_score, 3),
                'confidence': result.confidence,
                'name_pattern': result.name_pattern,
                'nba_minutes': result.nba_minutes,
                'bdl_minutes': result.bdl_minutes,
                'nba_points': result.nba_points,
                'bdl_points': result.bdl_points,
                'nba_status': result.nba_status,
                'nba_dnp_reason': result.nba_dnp_reason,
                'stats_match': result.stats_match
            })
        
        if all_data:
            df_all = pd.DataFrame(all_data)
            df_all = df_all.sort_values(['match_type', 'confidence', 'similarity_score'], 
                                      ascending=[True, False, False])
            
            filename = f"nba_player_name_matching_{timestamp}.csv"
            df_all.to_csv(filename, index=False)
            logger.info(f"📊 Exported {len(all_data)} detailed results to {filename}")
        
        # Export actionable subsets
        self._export_actionable_subsets(results, timestamp)
    
    def _export_actionable_subsets(self, results: List[NameMatchResult], timestamp: str):
        """Export specific subsets for actionable use."""
        
        # Close matches for name mapping rules
        close_matches = [r for r in results if r.match_type == 'close']
        if close_matches:
            close_data = [{
                'nba_name': r.nba_name,
                'bdl_name': r.bdl_name,
                'pattern': r.name_pattern,
                'similarity': round(r.similarity_score, 3),
                'confidence': r.confidence,
                'stats_match': r.stats_match,
                'example_game': r.game_id
            } for r in close_matches]
            
            df_close = pd.DataFrame(close_data)
            df_close = df_close.sort_values(['pattern', 'confidence', 'similarity'], 
                                          ascending=[True, False, False])
            
            filename = f"name_mapping_rules_{timestamp}.csv"
            df_close.to_csv(filename, index=False)
            logger.info(f"🔧 Exported {len(close_matches)} name mapping rules to {filename}")
        
        # Problematic cases needing review
        problems = [r for r in results if r.match_type == 'mismatch' or 
                   (r.match_type == 'bdl_only' and r.bdl_points > 0)]
        if problems:
            problem_data = [{
                'issue_type': r.match_type,
                'game_id': r.game_id,
                'team': r.team_abbr,
                'nba_name': r.nba_name,
                'bdl_name': r.bdl_name,
                'nba_points': r.nba_points,
                'bdl_points': r.bdl_points,
                'similarity': round(r.similarity_score, 3) if r.similarity_score else 0,
                'nba_status': r.nba_status,
                'investigation_priority': 'high' if r.match_type == 'mismatch' else 'medium'
            } for r in problems]
            
            df_problems = pd.DataFrame(problem_data)
            df_problems = df_problems.sort_values(['investigation_priority', 'issue_type'])
            
            filename = f"data_quality_issues_{timestamp}.csv"
            df_problems.to_csv(filename, index=False)
            logger.info(f"🔍 Exported {len(problems)} data quality issues to {filename}")


def main():
    """Main function with enhanced command line interface."""
    parser = argparse.ArgumentParser(description='NBA Player Name Matching Validator')
    parser.add_argument('--date', type=str, help='Single date to validate (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, default='2024-01-01', 
                       help='Start date for range validation (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default='2024-01-31',
                       help='End date for range validation (YYYY-MM-DD)')
    parser.add_argument('--export', action='store_true', 
                       help='Export detailed results to CSV files')
    
    args = parser.parse_args()
    
    validator = NBAPlayerNameValidator()
    
    # Run validation
    logger.info("🏀 Starting NBA Player Name Matching Validation...")
    results = validator.validate_name_matching(
        target_date=args.date,
        start_date=args.start_date,
        end_date=args.end_date
    )
    
    if not results:
        logger.error("❌ No results generated. Check data availability.")
        return
    
    # Print comprehensive report
    validator.print_comprehensive_report(results)
    
    # Export if requested
    if args.export:
        validator.export_results_to_csv(results)
    
    logger.info("✅ Player name matching validation complete!")


if __name__ == "__main__":
    main()