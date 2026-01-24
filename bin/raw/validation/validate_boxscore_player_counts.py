#!/usr/bin/env python3
"""
VALIDATOR: NBA Boxscore Player Count Validator (CORRECTED)

File: bin/processors/validation/validate_boxscore_player_counts.py

Validates player count consistency between NBA.com gamebook and BDL boxscore data:
- Compares TOTAL ROSTER SIZE (should match between sources - both include injured)
- Analyzes non-playing player categorization differences
- BDL uses "00" minutes format for DNP+injured, NBA.com separates DNP vs injured
- Identifies games with total roster discrepancies (data quality issues)
- Generates actionable reports for data quality investigation

Usage:
    python validate_boxscore_player_counts.py

Output:
    - Console report with total roster analysis and categorization differences
    - CSV exports with detailed game-by-game comparisons
    - Flagged games requiring data quality investigation
"""

import logging
import sys
from datetime import datetime, date
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from google.cloud import bigquery
import pandas as pd

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
class GamePlayerCounts:
    """Player count data for a specific game from one source."""
    game_date: date
    home_team: str
    away_team: str
    source: str  # 'nba_gamebook' or 'bdl_boxscore'
    total_players: int
    active_players: int
    non_playing_players: int  # DNP + injured combined
    dnp_players: int         # DNP only (NBA.com only)
    injured_players: int     # Injured only (NBA.com only)
    source_game_id: str

@dataclass
class PlayerCountComparison:
    """Comparison of player counts between sources for the same game."""
    game_date: date
    home_team: str
    away_team: str
    nba_total: Optional[int]
    nba_active: Optional[int] 
    nba_dnp: Optional[int]        # NBA.com DNP only
    nba_injured: Optional[int]    # NBA.com injured only
    nba_non_playing: Optional[int]  # NBA.com DNP + injured
    bdl_total: Optional[int]
    bdl_active: Optional[int]
    bdl_non_playing: Optional[int]  # BDL "00" minutes (DNP + injured)
    total_roster_difference: int     # Main validation metric
    active_difference: int
    non_playing_difference: int     # Categorization analysis
    discrepancy_severity: str       # 'none', 'minor', 'major', 'critical'
    data_quality_flags: List[str]

class NBAPlayerCountValidator:
    """
    Validates player count consistency between NBA.com and BDL sources.
    
    KEY INSIGHT: Both sources include injured players
    - Primary validation: Total roster size should match
    - Secondary analysis: How non-playing players are categorized
    """
    
    # Expected player count ranges for data quality validation
    MIN_EXPECTED_TOTAL_ROSTER = 30        # Total roster size
    MAX_EXPECTED_TOTAL_ROSTER = 40        # Total roster size
    MIN_EXPECTED_ACTIVE_PLAYERS = 10      # Active players per game
    MAX_EXPECTED_ACTIVE_PLAYERS = 18      # Active players per game
    MIN_EXPECTED_NON_PLAYING = 12         # DNP + injured combined
    MAX_EXPECTED_NON_PLAYING = 25         # DNP + injured combined
    
    # Total roster discrepancy thresholds (main validation metric)
    MINOR_TOTAL_DISCREPANCY = 1           # 1 player difference
    MAJOR_TOTAL_DISCREPANCY = 3           # 2-3 player difference  
    CRITICAL_TOTAL_DISCREPANCY = 3        # >3 player difference
    
    def __init__(self, project_id: str = None):
        if project_id is None:
            project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        
    def validate_player_counts(
        self, 
        start_date: str = "2021-10-01",
        end_date: str = "2025-06-30"
    ) -> List[PlayerCountComparison]:
        """
        Perform comprehensive player count validation across both sources.
        
        Args:
            start_date: Start date for validation (2021-10-01)
            end_date: End date for validation (2025-06-30)
            
        Returns:
            List of PlayerCountComparison objects with detailed analysis
        """
        logger.info(f"Starting NBA player count validation for 4 seasons: {start_date} to {end_date}")
        
        # Load player count data from both sources
        logger.info("Loading NBA.com gamebook player counts...")
        nba_player_counts = self._load_nba_player_counts(start_date, end_date)
        
        logger.info("Loading BDL boxscore player counts...")
        bdl_player_counts = self._load_bdl_player_counts(start_date, end_date)
        
        # Compare player counts between sources
        logger.info("Comparing total roster alignment between sources...")
        comparisons = self._compare_player_counts(nba_player_counts, bdl_player_counts)
        
        return comparisons
    
    def _load_nba_player_counts(self, start_date: str, end_date: str) -> List[GamePlayerCounts]:
        """Load player count data from NBA.com gamebook with correct status mapping."""
        query = f"""
        SELECT 
            game_date,
            home_team_abbr,
            away_team_abbr,
            game_id,
            COUNT(*) as total_players,
            COUNT(CASE WHEN player_status = 'active' THEN 1 END) as active_players,
            COUNT(CASE WHEN player_status = 'dnp' THEN 1 END) as dnp_players,
            COUNT(CASE WHEN player_status = 'inactive' THEN 1 END) as injured_players,
            COUNT(CASE WHEN player_status IN ('dnp', 'inactive') THEN 1 END) as non_playing_players
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND home_team_abbr IS NOT NULL
          AND away_team_abbr IS NOT NULL
        GROUP BY game_date, home_team_abbr, away_team_abbr, game_id
        ORDER BY game_date, game_id
        """
        
        results = self.client.query(query).to_dataframe()
        
        player_counts = []
        for _, row in results.iterrows():
            player_counts.append(GamePlayerCounts(
                game_date=row['game_date'],
                home_team=row['home_team_abbr'],
                away_team=row['away_team_abbr'],
                source='nba_gamebook',
                total_players=row['total_players'],
                active_players=row['active_players'],
                non_playing_players=row['non_playing_players'],
                dnp_players=row['dnp_players'],
                injured_players=row['injured_players'],
                source_game_id=row['game_id']
            ))
        
        logger.info(f"Loaded player counts for {len(player_counts)} NBA.com games")
        return player_counts
    
    def _load_bdl_player_counts(self, start_date: str, end_date: str) -> List[GamePlayerCounts]:
        """Load player count data from BDL boxscore with corrected minutes format detection."""
        query = f"""
        SELECT 
            game_date,
            home_team_abbr,
            away_team_abbr,
            game_id,
            COUNT(*) as total_players,
            -- CORRECTED: BDL uses "00" format, not "0:00"
            COUNT(CASE 
                WHEN minutes IS NOT NULL 
                AND minutes != '00' 
                AND minutes != '' 
                THEN 1 
            END) as active_players,
            COUNT(CASE 
                WHEN minutes IS NULL 
                OR minutes = '00' 
                OR minutes = '' 
                THEN 1 
            END) as non_playing_players
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND home_team_abbr IS NOT NULL
          AND away_team_abbr IS NOT NULL
        GROUP BY game_date, home_team_abbr, away_team_abbr, game_id
        HAVING COUNT(*) > 0  -- Ensure we have actual player records
        ORDER BY game_date, game_id
        """
        
        results = self.client.query(query).to_dataframe()
        
        player_counts = []
        for _, row in results.iterrows():
            player_counts.append(GamePlayerCounts(
                game_date=row['game_date'],
                home_team=row['home_team_abbr'],
                away_team=row['away_team_abbr'],
                source='bdl_boxscore',
                total_players=row['total_players'],
                active_players=row['active_players'],
                non_playing_players=row['non_playing_players'],
                dnp_players=0,  # BDL doesn't separate DNP vs injured
                injured_players=0,  # BDL doesn't separate DNP vs injured
                source_game_id=row['game_id']
            ))
        
        logger.info(f"Loaded player counts for {len(player_counts)} BDL games")
        return player_counts
    
    def _create_game_key(self, game_date: date, home_team: str, away_team: str) -> str:
        """Create standardized key for matching games across sources."""
        return f"{game_date}_{away_team}_{home_team}"
    
    def _compare_player_counts(
        self, 
        nba_counts: List[GamePlayerCounts], 
        bdl_counts: List[GamePlayerCounts]
    ) -> List[PlayerCountComparison]:
        """Compare total roster size and categorization between sources for the same games."""
        
        # Create lookup dictionaries
        nba_lookup = {
            self._create_game_key(g.game_date, g.home_team, g.away_team): g 
            for g in nba_counts
        }
        bdl_lookup = {
            self._create_game_key(g.game_date, g.home_team, g.away_team): g 
            for g in bdl_counts
        }
        
        # Find all games present in either source
        all_game_keys = set(nba_lookup.keys()) | set(bdl_lookup.keys())
        
        comparisons = []
        for game_key in all_game_keys:
            nba_game = nba_lookup.get(game_key)
            bdl_game = bdl_lookup.get(game_key)
            
            # Extract game details (prefer NBA.com data if available)
            if nba_game:
                game_date = nba_game.game_date
                home_team = nba_game.home_team
                away_team = nba_game.away_team
            else:
                game_date = bdl_game.game_date
                home_team = bdl_game.home_team
                away_team = bdl_game.away_team
            
            # Extract counts
            nba_total = nba_game.total_players if nba_game else None
            nba_active = nba_game.active_players if nba_game else None
            nba_dnp = nba_game.dnp_players if nba_game else None
            nba_injured = nba_game.injured_players if nba_game else None
            nba_non_playing = nba_game.non_playing_players if nba_game else None
            
            bdl_total = bdl_game.total_players if bdl_game else None
            bdl_active = bdl_game.active_players if bdl_game else None
            bdl_non_playing = bdl_game.non_playing_players if bdl_game else None
            
            # Calculate key metrics
            total_roster_diff = 0
            active_diff = 0
            non_playing_diff = 0
            data_quality_flags = []
            
            # MAIN VALIDATION: Total roster size should match
            if nba_game and bdl_game:
                total_roster_diff = abs(nba_total - bdl_total)
                active_diff = abs(nba_active - bdl_active)
                non_playing_diff = abs(nba_non_playing - bdl_non_playing)
            
            # Determine discrepancy severity based on TOTAL ROSTER alignment
            if not nba_game or not bdl_game:
                severity = 'missing_data'
            elif total_roster_diff == 0:
                severity = 'none'  # Perfect - total rosters match
            elif total_roster_diff <= self.MINOR_TOTAL_DISCREPANCY:
                severity = 'minor'  # Small total roster differences
            elif total_roster_diff <= self.MAJOR_TOTAL_DISCREPANCY:
                severity = 'major'  # Significant total roster differences
            else:
                severity = 'critical'  # Major total roster misalignment
            
            # Flag data quality issues
            if nba_game:
                if nba_total < self.MIN_EXPECTED_TOTAL_ROSTER:
                    data_quality_flags.append('nba_low_total_roster')
                if nba_total > self.MAX_EXPECTED_TOTAL_ROSTER:
                    data_quality_flags.append('nba_high_total_roster')
                if nba_active < self.MIN_EXPECTED_ACTIVE_PLAYERS:
                    data_quality_flags.append('nba_low_active_players')
                if nba_active > self.MAX_EXPECTED_ACTIVE_PLAYERS:
                    data_quality_flags.append('nba_high_active_players')
                if nba_non_playing < self.MIN_EXPECTED_NON_PLAYING:
                    data_quality_flags.append('nba_low_non_playing')
                if nba_non_playing > self.MAX_EXPECTED_NON_PLAYING:
                    data_quality_flags.append('nba_high_non_playing')
            
            if bdl_game:
                if bdl_total < self.MIN_EXPECTED_TOTAL_ROSTER:
                    data_quality_flags.append('bdl_low_total_roster')
                if bdl_total > self.MAX_EXPECTED_TOTAL_ROSTER:
                    data_quality_flags.append('bdl_high_total_roster')
                if bdl_active < self.MIN_EXPECTED_ACTIVE_PLAYERS:
                    data_quality_flags.append('bdl_low_active_players')
                if bdl_active > self.MAX_EXPECTED_ACTIVE_PLAYERS:
                    data_quality_flags.append('bdl_high_active_players')
                if bdl_non_playing < self.MIN_EXPECTED_NON_PLAYING:
                    data_quality_flags.append('bdl_low_non_playing')
                if bdl_non_playing > self.MAX_EXPECTED_NON_PLAYING:
                    data_quality_flags.append('bdl_high_non_playing')
            
            # Flag main validation failure
            if total_roster_diff > 0:
                data_quality_flags.append('total_roster_mismatch')
            
            # Flag large categorization differences (secondary concern)
            if non_playing_diff > 5:
                data_quality_flags.append('large_categorization_difference')
            
            if not nba_game:
                data_quality_flags.append('missing_nba_data')
            if not bdl_game:
                data_quality_flags.append('missing_bdl_data')
            
            comparisons.append(PlayerCountComparison(
                game_date=game_date,
                home_team=home_team,
                away_team=away_team,
                nba_total=nba_total,
                nba_active=nba_active,
                nba_dnp=nba_dnp,
                nba_injured=nba_injured,
                nba_non_playing=nba_non_playing,
                bdl_total=bdl_total,
                bdl_active=bdl_active,
                bdl_non_playing=bdl_non_playing,
                total_roster_difference=total_roster_diff,
                active_difference=active_diff,
                non_playing_difference=non_playing_diff,
                discrepancy_severity=severity,
                data_quality_flags=data_quality_flags
            ))
        
        return comparisons
    
    def print_validation_report(self, comparisons: List[PlayerCountComparison], detailed: bool = False):
        """Print comprehensive total roster validation report."""
        print("\n" + "="*80)
        print("NBA TOTAL ROSTER VALIDATION REPORT")
        print("="*80)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Date Range: Past 4 NBA seasons (2021-22 through 2024-25)")
        print(f"Focus: Total roster size should match (both sources include injured players)")
        
        # Overall statistics
        total_comparisons = len(comparisons)
        both_sources = len([c for c in comparisons if c.nba_total is not None and c.bdl_total is not None])
        nba_only = len([c for c in comparisons if c.nba_total is not None and c.bdl_total is None])
        bdl_only = len([c for c in comparisons if c.nba_total is None and c.bdl_total is not None])
        
        print(f"\nOVERALL STATISTICS:")
        print(f"- Total Games Analyzed: {total_comparisons:,}")
        print(f"- Both Sources Available: {both_sources:,} ({both_sources/total_comparisons*100:.1f}%)")
        print(f"- NBA.com Only: {nba_only:,}")
        print(f"- BDL Only: {bdl_only:,}")
        
        if both_sources > 0:
            # Total roster alignment analysis (main metric)
            perfect_alignment = len([c for c in comparisons if c.discrepancy_severity == 'none'])
            minor_discrepancy = len([c for c in comparisons if c.discrepancy_severity == 'minor'])
            major_discrepancy = len([c for c in comparisons if c.discrepancy_severity == 'major'])
            critical_discrepancy = len([c for c in comparisons if c.discrepancy_severity == 'critical'])
            
            print(f"\nTOTAL ROSTER ALIGNMENT (Primary Validation Metric):")
            print(f"Both sources should have identical total roster size (active + DNP + injured)")
            print(f"- Perfect Alignment: {perfect_alignment:,} ({perfect_alignment/both_sources*100:.1f}%)")
            print(f"- Minor Misalignment (1 player): {minor_discrepancy:,} ({minor_discrepancy/both_sources*100:.1f}%)")
            print(f"- Major Misalignment (2-3 players): {major_discrepancy:,} ({major_discrepancy/both_sources*100:.1f}%)")
            print(f"- Critical Misalignment (>3 players): {critical_discrepancy:,} ({critical_discrepancy/both_sources*100:.1f}%)")
            
            # Show roster composition statistics
            games_with_both = [c for c in comparisons if c.nba_total and c.bdl_total]
            if games_with_both:
                avg_nba_total = sum(c.nba_total for c in games_with_both) / len(games_with_both)
                avg_nba_active = sum(c.nba_active for c in games_with_both) / len(games_with_both)
                avg_nba_non_playing = sum(c.nba_non_playing for c in games_with_both) / len(games_with_both)
                avg_bdl_total = sum(c.bdl_total for c in games_with_both) / len(games_with_both)
                avg_bdl_active = sum(c.bdl_active for c in games_with_both) / len(games_with_both)
                avg_bdl_non_playing = sum(c.bdl_non_playing for c in games_with_both) / len(games_with_both)
                
                print(f"\nROSTER COMPOSITION ANALYSIS:")
                print(f"- Average NBA.com Total Roster: {avg_nba_total:.1f} (active + DNP + injured)")
                print(f"- Average BDL Total Roster: {avg_bdl_total:.1f} (active + non-playing)")
                print(f"- Average NBA.com Active: {avg_nba_active:.1f} | Non-playing: {avg_nba_non_playing:.1f}")
                print(f"- Average BDL Active: {avg_bdl_active:.1f} | Non-playing: {avg_bdl_non_playing:.1f}")
                print(f"- Expected Total Match: {avg_nba_total:.1f} ≈ {avg_bdl_total:.1f}")
        
        # Data quality issues
        quality_issues = [c for c in comparisons if c.data_quality_flags]
        if quality_issues:
            print(f"\nDATA QUALITY ISSUES:")
            print(f"- Games with Quality Flags: {len(quality_issues):,} ({len(quality_issues)/total_comparisons*100:.1f}%)")
            
            # Count specific flag types
            flag_counts = {}
            for comparison in quality_issues:
                for flag in comparison.data_quality_flags:
                    flag_counts[flag] = flag_counts.get(flag, 0) + 1
            
            for flag, count in sorted(flag_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {flag.replace('_', ' ').title()}: {count:,} games")
        
        # Detailed examples if requested
        if detailed and both_sources > 0:
            # Show worst total roster misalignments
            worst_misalignments = sorted(
                [c for c in comparisons if c.total_roster_difference > 0], 
                key=lambda x: x.total_roster_difference, 
                reverse=True
            )[:10]
            
            if worst_misalignments:
                print(f"\nWORST TOTAL ROSTER MISALIGNMENTS:")
                for comp in worst_misalignments:
                    print(f"  - {comp.game_date}: {comp.away_team} @ {comp.home_team}")
                    print(f"    NBA.com Total: {comp.nba_total} ({comp.nba_active} active + {comp.nba_non_playing} non-playing)")
                    print(f"    BDL Total: {comp.bdl_total} ({comp.bdl_active} active + {comp.bdl_non_playing} non-playing)")
                    print(f"    Total Difference: {comp.total_roster_difference} players ({comp.discrepancy_severity})")
                    if comp.nba_dnp is not None and comp.nba_injured is not None:
                        print(f"    NBA.com Breakdown: {comp.nba_dnp} DNP + {comp.nba_injured} injured")
        
        # Recommendations
        print(f"\nRECOMMENDATIONS:")
        print(f"Focus: Total roster size should match between sources")
        
        if both_sources > 0:
            success_rate = perfect_alignment / both_sources * 100
            print(f"1. CURRENT SUCCESS RATE: {success_rate:.1f}% of games have perfect total roster alignment")
            
            if critical_discrepancy > 0:
                print(f"2. HIGH PRIORITY: Investigate {critical_discrepancy} games with critical misalignment (>3 players)")
            if major_discrepancy > 0:
                print(f"3. MEDIUM PRIORITY: Review {major_discrepancy} games with major misalignment (2-3 players)")
            
            # Count total roster mismatches
            roster_mismatches = len([c for c in comparisons if 'total_roster_mismatch' in c.data_quality_flags])
            if roster_mismatches > 0:
                print(f"4. DATA QUALITY: Fix {roster_mismatches} games where total rosters don't match")
        
        print(f"\nBottom Line: Total roster alignment validates data completeness.")
        print("Perfect alignment = NBA.com Total = BDL Total (both include all players)")
        print("Categorization differences (DNP vs injured) are expected between sources")
        print("="*80)
    
    def export_comparisons_to_csv(self, comparisons: List[PlayerCountComparison]):
        """Export detailed total roster comparisons to CSV files."""
        
        # Export all comparisons
        all_data = []
        for comp in comparisons:
            all_data.append({
                'game_date': comp.game_date,
                'away_team': comp.away_team,
                'home_team': comp.home_team,
                'matchup': f"{comp.away_team} @ {comp.home_team}",
                'nba_total_roster': comp.nba_total,
                'nba_active_players': comp.nba_active,
                'nba_dnp_players': comp.nba_dnp,
                'nba_injured_players': comp.nba_injured,
                'nba_non_playing_total': comp.nba_non_playing,
                'bdl_total_roster': comp.bdl_total,
                'bdl_active_players': comp.bdl_active,
                'bdl_non_playing_total': comp.bdl_non_playing,
                'total_roster_difference': comp.total_roster_difference,
                'active_difference': comp.active_difference,
                'non_playing_difference': comp.non_playing_difference,
                'discrepancy_severity': comp.discrepancy_severity,
                'data_quality_flags': ','.join(comp.data_quality_flags) if comp.data_quality_flags else ''
            })
        
        if all_data:
            df_all = pd.DataFrame(all_data)
            df_all = df_all.sort_values(['total_roster_difference', 'game_date'], ascending=[False, True])
            df_all.to_csv("nba_total_roster_comparisons.csv", index=False)
            logger.info(f"Exported {len(all_data)} total roster comparisons to nba_total_roster_comparisons.csv")
        
        # Export only problematic games
        problematic_data = [
            data for data in all_data 
            if data['discrepancy_severity'] in ['major', 'critical'] or data['data_quality_flags']
        ]
        
        if problematic_data:
            df_problems = pd.DataFrame(problematic_data)
            df_problems = df_problems.sort_values(['discrepancy_severity', 'total_roster_difference'], ascending=[False, False])
            df_problems.to_csv("nba_total_roster_issues.csv", index=False)
            logger.info(f"Exported {len(problematic_data)} problematic games to nba_total_roster_issues.csv")


def main():
    """Main function to run total roster validation."""
    validator = NBAPlayerCountValidator()
    
    # Run validation for past 4 NBA seasons
    logger.info("Running NBA total roster validation for past 4 seasons...")
    comparisons = validator.validate_player_counts()
    
    # Print comprehensive report
    validator.print_validation_report(comparisons, detailed=True)
    
    # Export detailed analysis
    validator.export_comparisons_to_csv(comparisons)
    
    logger.info("Total roster validation complete!")


if __name__ == "__main__":
    main()