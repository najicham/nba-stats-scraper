#!/usr/bin/env python3
"""
VALIDATOR: NBA Boxscore Coverage Validator

File: bin/processors/validation/validate_nba_boxscore_coverage.py

Validates boxscore data completeness across NBA sources:
- nba_raw.nbac_schedule (master schedule)
- nba_raw.nbac_gamebook_player_stats (NBA.com player stats)  
- nba_raw.bdl_player_boxscores (Ball Don't Lie player stats)

Handles format differences, filters to NBA games only, and provides actionable gap analysis.

Usage:
    python validate_nba_data_coverage.py

Output:
    - Console summary report with coverage statistics
    - CSV export (nba_data_gaps.csv) with detailed gap analysis
    - Prioritized recommendations for data acquisition
"""

import logging
import sys
from datetime import datetime, date
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from google.cloud import bigquery
from google.cloud import storage
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
class GCSFileStatus:
    """Status of raw files in GCS for a missing game/date."""
    date: str
    source: str  # 'nba_gamebook' or 'bdl_boxscore'
    files_found: int
    files_expected: int
    file_paths: List[str]
    scraper_status: str  # 'complete', 'partial', 'missing'

@dataclass
class GameRecord:
    """Standardized game record for comparison across sources."""
    game_date: date
    home_team: str
    away_team: str
    season_year: int
    source_game_id: str
    source: str

@dataclass
class ValidationResult:
    """Results of validation analysis."""
    total_expected_games: int
    schedule_coverage: int
    gamebook_coverage: int
    bdl_coverage: int
    
    # Gap analysis
    missing_from_gamebook: List[GameRecord]
    missing_from_bdl: List[GameRecord]
    missing_from_both: List[GameRecord]
    
    # Additional insights
    schedule_only_games: List[GameRecord]  # Games in schedule but not in either source
    non_nba_games_in_schedule: List[GameRecord]  # Special events, exhibitions

class NBADataValidator:
    """
    Validates NBA data completeness across multiple sources.
    
    Handles:
    - Different game ID formats
    - Team code standardization  
    - NBA vs non-NBA game filtering
    - Comprehensive gap analysis
    """
    
    # Standard NBA team codes for filtering
    NBA_TEAMS = {
        'ATL', 'BKN', 'BOS', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
        'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK', 
        'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
    }
    
    def __init__(self, project_id: str = None, bucket_name: str = "nba-scraped-data"):
        if project_id is None:
            project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.project_id = project_id
        self.bucket_name = bucket_name
        self.client = bigquery.Client(project=project_id)
        self.storage_client = storage.Client(project=project_id)
        
    def validate_data_coverage(
        self, 
        start_date: str = "2021-10-01",
        end_date: str = "2025-06-30"
    ) -> Tuple[ValidationResult, List[GCSFileStatus]]:
        """
        Perform comprehensive data validation across all sources and check GCS for raw files.
        
        Validates the past 4 NBA seasons:
        - 2021-22 season (Oct 2021 - Jun 2022)
        - 2022-23 season (Oct 2022 - Jun 2023) 
        - 2023-24 season (Oct 2023 - Jun 2024)
        - 2024-25 season (Oct 2024 - Jun 2025)
        
        Args:
            start_date: Start date for validation (2021-10-01)
            end_date: End date for validation (2025-06-30)
            
        Returns:
            Tuple of (ValidationResult, List[GCSFileStatus]) with comprehensive analysis
        """
        logger.info(f"Starting NBA data validation for 4 seasons: {start_date} to {end_date}")
        
        # Load data from all sources
        logger.info("Loading schedule data...")
        schedule_games = self._load_schedule_games(start_date, end_date)
        
        logger.info("Loading gamebook data...")
        gamebook_games = self._load_gamebook_games(start_date, end_date)
        
        logger.info("Loading BDL data...")
        bdl_games = self._load_bdl_games(start_date, end_date)
        
        # Perform validation analysis
        logger.info("Performing validation analysis...")
        result = self._analyze_coverage(schedule_games, gamebook_games, bdl_games)
        
        # Check GCS for raw files on missing dates
        logger.info("Checking GCS for raw files on missing dates...")
        gcs_analysis = self._check_gcs_files_for_gaps(result)
        
        return result, gcs_analysis
    
    def _load_schedule_games(self, start_date: str, end_date: str) -> List[GameRecord]:
        """Load and standardize schedule data - regular season and playoffs only."""
        query = f"""
        SELECT 
            game_id,
            game_date,
            season_year,
            home_team_tricode,
            away_team_tricode,
            game_status_text
        FROM `{self.project_id}.nba_raw.nbac_schedule`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND home_team_tricode IN UNNEST({list(self.NBA_TEAMS)})
          AND away_team_tricode IN UNNEST({list(self.NBA_TEAMS)})
          AND (is_regular_season = true OR is_playoffs = true)
          AND is_all_star = false
        ORDER BY game_date, game_id
        """
        
        results = self.client.query(query).to_dataframe()
        
        games = []
        for _, row in results.iterrows():
            games.append(GameRecord(
                game_date=row['game_date'],
                home_team=row['home_team_tricode'],
                away_team=row['away_team_tricode'], 
                season_year=row['season_year'],
                source_game_id=row['game_id'],
                source='schedule'
            ))
        
        logger.info(f"Loaded {len(games)} NBA games from schedule")
        return games
    
    def _load_gamebook_games(self, start_date: str, end_date: str) -> List[GameRecord]:
        """Load and standardize gamebook data."""
        query = f"""
        SELECT DISTINCT
            game_id,
            game_date,
            season_year,
            home_team_abbr,
            away_team_abbr
        FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND home_team_abbr IN UNNEST({list(self.NBA_TEAMS)})
          AND away_team_abbr IN UNNEST({list(self.NBA_TEAMS)})
        ORDER BY game_date, game_id
        """
        
        results = self.client.query(query).to_dataframe()
        
        games = []
        for _, row in results.iterrows():
            games.append(GameRecord(
                game_date=row['game_date'],
                home_team=row['home_team_abbr'],
                away_team=row['away_team_abbr'],
                season_year=row['season_year'],
                source_game_id=row['game_id'],
                source='gamebook'
            ))
        
        logger.info(f"Loaded {len(games)} NBA games from gamebook")
        return games
    
    def _load_bdl_games(self, start_date: str, end_date: str) -> List[GameRecord]:
        """Load and standardize BDL data."""
        query = f"""
        SELECT DISTINCT
            game_id,
            game_date,
            season_year,
            home_team_abbr,
            away_team_abbr
        FROM `{self.project_id}.nba_raw.bdl_player_boxscores`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
          AND home_team_abbr IN UNNEST({list(self.NBA_TEAMS)})
          AND away_team_abbr IN UNNEST({list(self.NBA_TEAMS)})
        ORDER BY game_date, game_id
        """
        
        results = self.client.query(query).to_dataframe()
        
        games = []
        for _, row in results.iterrows():
            games.append(GameRecord(
                game_date=row['game_date'],
                home_team=row['home_team_abbr'],
                away_team=row['away_team_abbr'],
                season_year=row['season_year'],
                source_game_id=row['game_id'],
                source='bdl'
            ))
        
        logger.info(f"Loaded {len(games)} NBA games from BDL")
        return games
    
    def _create_game_key(self, game: GameRecord) -> str:
        """Create a standardized key for game matching across sources."""
        return f"{game.game_date}_{game.away_team}_{game.home_team}"
    
    def _analyze_coverage(
        self, 
        schedule_games: List[GameRecord], 
        gamebook_games: List[GameRecord], 
        bdl_games: List[GameRecord]
    ) -> ValidationResult:
        """Perform comprehensive coverage analysis."""
        
        # Create lookup sets for efficient matching
        schedule_keys = {self._create_game_key(g): g for g in schedule_games}
        gamebook_keys = {self._create_game_key(g): g for g in gamebook_games}
        bdl_keys = {self._create_game_key(g): g for g in bdl_games}
        
        # Use schedule as the reference (master list of expected games)
        all_expected_keys = set(schedule_keys.keys())
        
        # Find coverage gaps
        missing_from_gamebook = []
        missing_from_bdl = []
        missing_from_both = []
        
        for key in all_expected_keys:
            has_gamebook = key in gamebook_keys
            has_bdl = key in bdl_keys
            
            if not has_gamebook and not has_bdl:
                missing_from_both.append(schedule_keys[key])
            elif not has_gamebook:
                missing_from_gamebook.append(schedule_keys[key])
            elif not has_bdl:
                missing_from_bdl.append(schedule_keys[key])
        
        # Calculate coverage statistics
        gamebook_coverage = len(all_expected_keys) - len(missing_from_gamebook) - len(missing_from_both)
        bdl_coverage = len(all_expected_keys) - len(missing_from_bdl) - len(missing_from_both)
        
        return ValidationResult(
            total_expected_games=len(all_expected_keys),
            schedule_coverage=len(schedule_games),
            gamebook_coverage=gamebook_coverage,
            bdl_coverage=bdl_coverage,
            missing_from_gamebook=missing_from_gamebook,
            missing_from_bdl=missing_from_bdl,
            missing_from_both=missing_from_both,
            schedule_only_games=[],  # Not needed for this analysis
            non_nba_games_in_schedule=[]  # Filtered out already
        )
    
    def _check_gcs_files_for_gaps(self, result: ValidationResult) -> List[GCSFileStatus]:
        """Check GCS for raw JSON files on dates with missing data."""
        gcs_analysis = []
        
        # Check NBA.com gamebook files for missing dates
        nba_missing_dates = self._get_missing_dates(result.missing_from_gamebook + result.missing_from_both)
        for date_str in nba_missing_dates:
            gcs_status = self._check_nba_gamebook_files(date_str, result.missing_from_gamebook + result.missing_from_both)
            gcs_analysis.append(gcs_status)
        
        # Check BDL files for missing dates
        bdl_missing_dates = self._get_missing_dates(result.missing_from_bdl + result.missing_from_both)
        for date_str in bdl_missing_dates:
            gcs_status = self._check_bdl_files(date_str)
            gcs_analysis.append(gcs_status)
        
        return gcs_analysis
    
    def _get_missing_dates(self, missing_games: List[GameRecord]) -> Set[str]:
        """Get unique dates from missing games."""
        return set(game.game_date.strftime('%Y-%m-%d') for game in missing_games)
    
    def _check_nba_gamebook_files(self, date_str: str, missing_games: List[GameRecord]) -> GCSFileStatus:
        """Check for NBA.com gamebook JSON files for a specific date."""
        # Filter games for this specific date
        date_games = [game for game in missing_games if game.game_date.strftime('%Y-%m-%d') == date_str]
        
        files_found = 0
        file_paths = []
        
        for game in date_games:
            # Construct expected file path: nba-scraped-data/nba-com/gamebooks-data/2024-01-20/20240120-CLEATL/
            game_date_formatted = game.game_date.strftime('%Y-%m-%d')
            game_date_compact = game.game_date.strftime('%Y%m%d')
            game_code = f"{game_date_compact}-{game.away_team}{game.home_team}"
            
            prefix = f"nba-com/gamebooks-data/{game_date_formatted}/{game_code}/"
            
            # Check if any files exist with this prefix
            bucket = self.storage_client.bucket(self.bucket_name)
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=10))
            
            if blobs:
                files_found += 1
                file_paths.extend([blob.name for blob in blobs])
        
        files_expected = len(date_games)
        
        if files_found == files_expected:
            scraper_status = 'complete'
        elif files_found > 0:
            scraper_status = 'partial'
        else:
            scraper_status = 'missing'
        
        return GCSFileStatus(
            date=date_str,
            source='nba_gamebook',
            files_found=files_found,
            files_expected=files_expected,
            file_paths=file_paths,
            scraper_status=scraper_status
        )
    
    def _check_bdl_files(self, date_str: str) -> GCSFileStatus:
        """Check for BDL JSON files for a specific date."""
        # BDL has one file per date: nba-scraped-data/ball-dont-lie/boxscores/2024-01-20/
        prefix = f"ball-dont-lie/boxscores/{date_str}/"
        
        bucket = self.storage_client.bucket(self.bucket_name)
        blobs = list(bucket.list_blobs(prefix=prefix, max_results=10))
        
        files_found = len(blobs)
        file_paths = [blob.name for blob in blobs]
        files_expected = 1  # BDL has one file per date
        
        if files_found >= files_expected:
            scraper_status = 'complete'
        else:
            scraper_status = 'missing'
        
        return GCSFileStatus(
            date=date_str,
            source='bdl_boxscore',
            files_found=files_found,
            files_expected=files_expected,
            file_paths=file_paths,
            scraper_status=scraper_status
        )
    
    def print_validation_report(self, result: ValidationResult, gcs_analysis: List[GCSFileStatus], detailed: bool = False):
        """Print a comprehensive validation report with GCS file analysis."""
        print("\n" + "="*80)
        print("NBA DATA VALIDATION REPORT")
        print("="*80)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"Date Range: Past 4 NBA seasons (2021-22 through 2024-25)")
        
        # Coverage Summary
        print(f"\nCOVERAGE SUMMARY:")
        print(f"- Total Expected Games (Schedule): {result.total_expected_games:,}")
        print(f"- NBA.com Gamebook Coverage: {result.gamebook_coverage:,} ({result.gamebook_coverage/result.total_expected_games*100:.1f}%)")
        print(f"- BDL Boxscore Coverage: {result.bdl_coverage:,} ({result.bdl_coverage/result.total_expected_games*100:.1f}%)")
        
        both_covered = result.total_expected_games - len(result.missing_from_both) - len(result.missing_from_gamebook) - len(result.missing_from_bdl)
        print(f"- Both Sources Complete: {both_covered:,} ({both_covered/result.total_expected_games*100:.1f}%)")
        
        # Gap Analysis
        print(f"\nMISSING DATA ANALYSIS:")
        print(f"❌ Both Sources Missing: {len(result.missing_from_both):,} games")
        print(f"⚠️  NBA.com Missing, BDL Available: {len(result.missing_from_gamebook):,} games")
        print(f"⚠️  BDL Missing, NBA.com Available: {len(result.missing_from_bdl):,} games")
        
        # GCS File Analysis
        self._print_gcs_analysis(gcs_analysis)
        
        # Date-level analysis for 100% coverage targeting
        self._print_date_level_analysis(result)
        
        # Detailed breakdowns if requested
        if detailed:
            if result.missing_from_both:
                print(f"\n❌ GAMES MISSING FROM BOTH SOURCES ({len(result.missing_from_both)} games):")
                for game in sorted(result.missing_from_both, key=lambda x: x.game_date)[:20]:
                    print(f"  - {game.game_date}: {game.away_team} @ {game.home_team} (Season: {game.season_year})")
                if len(result.missing_from_both) > 20:
                    print(f"  ... and {len(result.missing_from_both) - 20} more games")
            
            if result.missing_from_gamebook:
                print(f"\n⚠️  GAMES MISSING FROM NBA.COM GAMEBOOK ({len(result.missing_from_gamebook)} games):")
                for game in sorted(result.missing_from_gamebook, key=lambda x: x.game_date)[:10]:
                    print(f"  - {game.game_date}: {game.away_team} @ {game.home_team}")
                if len(result.missing_from_gamebook) > 10:
                    print(f"  ... and {len(result.missing_from_gamebook) - 10} more games")
            
            if result.missing_from_bdl:
                print(f"\n⚠️  GAMES MISSING FROM BDL ({len(result.missing_from_bdl)} games):")
                for game in sorted(result.missing_from_bdl, key=lambda x: x.game_date)[:10]:
                    print(f"  - {game.game_date}: {game.away_team} @ {game.home_team}")
                if len(result.missing_from_bdl) > 10:
                    print(f"  ... and {len(result.missing_from_bdl) - 10} more games")
        
        # Recommendations
        self._print_recommendations(result, gcs_analysis)
        
        print(f"\nBottom Line: {both_covered/result.total_expected_games*100:.1f}% of expected NBA games have complete coverage from both sources.")
        print("="*80)
    
    def _print_gcs_analysis(self, gcs_analysis: List[GCSFileStatus]):
        """Print GCS file analysis for root cause identification."""
        print(f"\n🗂️  GCS RAW FILE ANALYSIS (Root Cause):")
        print("="*50)
        
        # Group by source
        nba_gcs = [g for g in gcs_analysis if g.source == 'nba_gamebook']
        bdl_gcs = [g for g in gcs_analysis if g.source == 'bdl_boxscore']
        
        if nba_gcs:
            print(f"\n🏀 NBA.COM GAMEBOOK RAW FILES:")
            for gcs_status in sorted(nba_gcs, key=lambda x: x.date):
                status_icon = "✅" if gcs_status.scraper_status == 'complete' else "⚠️" if gcs_status.scraper_status == 'partial' else "❌"
                print(f"  {status_icon} {gcs_status.date}: {gcs_status.files_found}/{gcs_status.files_expected} files ({gcs_status.scraper_status})")
                if gcs_status.scraper_status == 'complete':
                    print(f"      → PROCESSOR FAILURE: Raw files exist but weren't processed")
                elif gcs_status.scraper_status == 'missing':
                    print(f"      → SCRAPER FAILURE: No raw files found")
                else:
                    print(f"      → PARTIAL FAILURE: Some files missing from scraper")
        
        if bdl_gcs:
            print(f"\n📊 BDL BOXSCORE RAW FILES:")
            for gcs_status in sorted(bdl_gcs, key=lambda x: x.date):
                status_icon = "✅" if gcs_status.scraper_status == 'complete' else "❌"
                print(f"  {status_icon} {gcs_status.date}: {gcs_status.files_found}/{gcs_status.files_expected} files ({gcs_status.scraper_status})")
                if gcs_status.scraper_status == 'complete':
                    print(f"      → PROCESSOR FAILURE: Raw files exist but weren't processed")
                else:
                    print(f"      → SCRAPER FAILURE: No raw files found")
    
    def _print_recommendations(self, result: ValidationResult, gcs_analysis: List[GCSFileStatus]):
        """Print prioritized recommendations based on gap analysis and GCS findings."""
        print(f"\nRECOMMENDATIONS:")
        
        # Analyze GCS findings for actionable recommendations
        processor_failures = [g for g in gcs_analysis if g.scraper_status == 'complete']
        scraper_failures = [g for g in gcs_analysis if g.scraper_status == 'missing']
        
        priority = 1
        
        if result.missing_from_both:
            print(f"{priority}. HIGH PRIORITY: Investigate {len(result.missing_from_both)} games missing from both sources")
            priority += 1
        
        if processor_failures:
            nba_processor_failures = [g for g in processor_failures if g.source == 'nba_gamebook']
            bdl_processor_failures = [g for g in processor_failures if g.source == 'bdl_boxscore']
            
            if nba_processor_failures:
                dates = [g.date for g in nba_processor_failures]
                print(f"{priority}. HIGH PRIORITY: Process existing NBA.com raw files for dates: {', '.join(dates)}")
                priority += 1
            
            if bdl_processor_failures:
                dates = [g.date for g in bdl_processor_failures]
                print(f"{priority}. MEDIUM PRIORITY: Process existing BDL raw files for dates: {', '.join(dates)}")
                priority += 1
        
        if scraper_failures:
            nba_scraper_failures = [g for g in scraper_failures if g.source == 'nba_gamebook']
            bdl_scraper_failures = [g for g in scraper_failures if g.source == 'bdl_boxscore']
            
            if nba_scraper_failures:
                dates = [g.date for g in nba_scraper_failures]
                print(f"{priority}. MEDIUM PRIORITY: Re-scrape NBA.com data for dates: {', '.join(dates)}")
                priority += 1
            
            if bdl_scraper_failures:
                dates = [g.date for g in bdl_scraper_failures]
                print(f"{priority}. LOW PRIORITY: Re-scrape BDL data for dates: {', '.join(dates)}")
                priority += 1
        
        remaining_gaps = len(result.missing_from_gamebook) + len(result.missing_from_bdl) - len(processor_failures) - len(scraper_failures)
        if remaining_gaps > 0:
            print(f"{priority}. INVESTIGATE: {remaining_gaps} additional gaps need investigation")
    
    def _print_date_level_analysis(self, result: ValidationResult):
        """Print date-level gap analysis for 100% coverage targeting."""
        print(f"\n📅 DATE-LEVEL GAP ANALYSIS (For 100% Coverage):")
        print("="*50)
        
        # Calculate total games per date for percentage (needed for both NBA.com and BDL analysis)
        all_games_by_date = {}
        schedule_games = self._get_all_schedule_games()
        for game in schedule_games:
            date_str = game.game_date.strftime('%Y-%m-%d')
            if date_str not in all_games_by_date:
                all_games_by_date[date_str] = 0
            all_games_by_date[date_str] += 1
        
        # Analyze NBA.com gamebook gaps by date
        if result.missing_from_gamebook or result.missing_from_both:
            print(f"\n🏀 NBA.COM GAMEBOOK MISSING DATES:")
            nba_gaps_by_date = {}
            
            for game in result.missing_from_gamebook + result.missing_from_both:
                date_str = game.game_date.strftime('%Y-%m-%d')
                if date_str not in nba_gaps_by_date:
                    nba_gaps_by_date[date_str] = []
                nba_gaps_by_date[date_str].append(game)
            
            for date_str in sorted(nba_gaps_by_date.keys()):
                missing_count = len(nba_gaps_by_date[date_str])
                total_games = all_games_by_date.get(date_str, missing_count)
                percentage = (missing_count / total_games) * 100
                print(f"  {date_str}: {missing_count} games missing ({percentage:.1f}% of day's games)")
            
            print(f"\n  Total NBA.com gaps: {len(result.missing_from_gamebook) + len(result.missing_from_both)} games across {len(nba_gaps_by_date)} dates")
        else:
            print(f"\n🏀 NBA.COM GAMEBOOK MISSING DATES:")
            print(f"  ✅ No missing games - 100% coverage achieved!")
        
        # Analyze BDL gaps by date  
        if result.missing_from_bdl or result.missing_from_both:
            print(f"\n📊 BDL BOXSCORE MISSING DATES:")
            bdl_gaps_by_date = {}
            
            for game in result.missing_from_bdl + result.missing_from_both:
                date_str = game.game_date.strftime('%Y-%m-%d')
                if date_str not in bdl_gaps_by_date:
                    bdl_gaps_by_date[date_str] = []
                bdl_gaps_by_date[date_str].append(game)
            
            # Show top 20 dates with most missing games
            sorted_dates = sorted(bdl_gaps_by_date.items(), key=lambda x: len(x[1]), reverse=True)
            
            for date_str, games in sorted_dates[:20]:
                missing_count = len(games)
                total_games = all_games_by_date.get(date_str, missing_count)
                percentage = (missing_count / total_games) * 100
                print(f"  {date_str}: {missing_count} games missing ({percentage:.1f}% of day's games)")
            
            if len(sorted_dates) > 20:
                remaining_games = sum(len(games) for _, games in sorted_dates[20:])
                remaining_dates = len(sorted_dates) - 20
                print(f"  ... and {remaining_games} games across {remaining_dates} more dates")
            
            print(f"\n  Total BDL gaps: {len(result.missing_from_bdl) + len(result.missing_from_both)} games across {len(bdl_gaps_by_date)} dates")
        else:
            print(f"\n📊 BDL BOXSCORE MISSING DATES:")
            print(f"  ✅ No missing games - 100% coverage achieved!")
    
    def _get_all_schedule_games(self) -> List[GameRecord]:
        """Get all schedule games for date-level analysis. Called from within analysis."""
        # This is a simple implementation - in a production system you might cache this
        return self._load_schedule_games("2021-10-01", "2025-06-30")
    
    def export_date_level_gaps(self, result: ValidationResult):
        """Export separate date-level gap analysis for each source."""
        
        # Get all schedule games for percentage calculations
        schedule_games = self._get_all_schedule_games() 
        all_games_by_date = {}
        for game in schedule_games:
            date_str = game.game_date.strftime('%Y-%m-%d')
            if date_str not in all_games_by_date:
                all_games_by_date[date_str] = 0
            all_games_by_date[date_str] += 1
        
        # Export NBA.com Gamebook date-level gaps
        nba_gaps_by_date = {}
        for game in result.missing_from_gamebook + result.missing_from_both:
            date_str = game.game_date.strftime('%Y-%m-%d')
            if date_str not in nba_gaps_by_date:
                nba_gaps_by_date[date_str] = 0
            nba_gaps_by_date[date_str] += 1
        
        if nba_gaps_by_date:
            nba_date_analysis = []
            for date_str in sorted(nba_gaps_by_date.keys()):
                total_games = all_games_by_date.get(date_str, 0)
                missing_games = nba_gaps_by_date[date_str]
                nba_date_analysis.append({
                    'date': date_str,
                    'total_games_scheduled': total_games,
                    'games_missing': missing_games,
                    'percentage_missing': (missing_games / total_games * 100) if total_games > 0 else 0,
                    'source': 'nba_gamebook'
                })
            
            df_nba_dates = pd.DataFrame(nba_date_analysis)
            df_nba_dates = df_nba_dates.sort_values(['games_missing', 'percentage_missing'], ascending=[False, False])
            df_nba_dates.to_csv("nba_gamebook_date_gaps.csv", index=False)
            logger.info(f"Exported NBA.com gamebook date-level gaps to nba_gamebook_date_gaps.csv")
        
        # Export BDL date-level gaps
        bdl_gaps_by_date = {}
        for game in result.missing_from_bdl + result.missing_from_both:
            date_str = game.game_date.strftime('%Y-%m-%d')
            if date_str not in bdl_gaps_by_date:
                bdl_gaps_by_date[date_str] = 0
            bdl_gaps_by_date[date_str] += 1
        
        if bdl_gaps_by_date:
            bdl_date_analysis = []
            for date_str in sorted(bdl_gaps_by_date.keys()):
                total_games = all_games_by_date.get(date_str, 0)
                missing_games = bdl_gaps_by_date[date_str]
                bdl_date_analysis.append({
                    'date': date_str,
                    'total_games_scheduled': total_games,
                    'games_missing': missing_games,
                    'percentage_missing': (missing_games / total_games * 100) if total_games > 0 else 0,
                    'source': 'bdl_boxscore'
                })
            
            df_bdl_dates = pd.DataFrame(bdl_date_analysis)
            df_bdl_dates = df_bdl_dates.sort_values(['games_missing', 'percentage_missing'], ascending=[False, False])
            df_bdl_dates.to_csv("bdl_boxscore_date_gaps.csv", index=False)
            logger.info(f"Exported BDL boxscore date-level gaps to bdl_boxscore_date_gaps.csv")
        
        # Combined date-level overview
        combined_date_analysis = []
        all_gap_dates = set(nba_gaps_by_date.keys()) | set(bdl_gaps_by_date.keys())
        
        for date_str in sorted(all_gap_dates):
            total_games = all_games_by_date.get(date_str, 0)
            nba_missing = nba_gaps_by_date.get(date_str, 0)
            bdl_missing = bdl_gaps_by_date.get(date_str, 0)
            
            combined_date_analysis.append({
                'date': date_str,
                'total_games_scheduled': total_games,
                'nba_gamebook_missing': nba_missing,
                'nba_gamebook_missing_pct': (nba_missing / total_games * 100) if total_games > 0 else 0,
                'bdl_boxscore_missing': bdl_missing, 
                'bdl_boxscore_missing_pct': (bdl_missing / total_games * 100) if total_games > 0 else 0,
                'priority': 'high' if nba_missing > 0 else 'low'
            })
        
        if combined_date_analysis:
            df_combined_dates = pd.DataFrame(combined_date_analysis)
            df_combined_dates = df_combined_dates.sort_values(['nba_gamebook_missing', 'nba_gamebook_missing_pct'], ascending=[False, False])
            df_combined_dates.to_csv("nba_combined_date_gaps.csv", index=False)
            logger.info(f"Exported combined date-level gap analysis to nba_combined_date_gaps.csv")
    
    def export_gaps_to_csv(self, result: ValidationResult):
        """Export separate gap analysis CSV files for each source."""
        
        # Export NBA.com Gamebook gaps
        nba_gaps_data = []
        for game in result.missing_from_gamebook + result.missing_from_both:
            nba_gaps_data.append({
                'game_date': game.game_date,
                'away_team': game.away_team,
                'home_team': game.home_team,
                'season_year': game.season_year,
                'schedule_game_id': game.source_game_id,
                'matchup': f"{game.away_team} @ {game.home_team}",
                'priority': 'high' if game in result.missing_from_both else 'medium'
            })
        
        if nba_gaps_data:
            df_nba = pd.DataFrame(nba_gaps_data)
            df_nba = df_nba.sort_values(['game_date'])
            df_nba.to_csv("nba_gamebook_gaps.csv", index=False)
            logger.info(f"Exported {len(nba_gaps_data)} NBA.com gamebook gap records to nba_gamebook_gaps.csv")
        
        # Export BDL gaps
        bdl_gaps_data = []
        for game in result.missing_from_bdl + result.missing_from_both:
            bdl_gaps_data.append({
                'game_date': game.game_date,
                'away_team': game.away_team,
                'home_team': game.home_team,
                'season_year': game.season_year,
                'schedule_game_id': game.source_game_id,
                'matchup': f"{game.away_team} @ {game.home_team}",
                'priority': 'high' if game in result.missing_from_both else 'low'
            })
        
        if bdl_gaps_data:
            df_bdl = pd.DataFrame(bdl_gaps_data)
            df_bdl = df_bdl.sort_values(['game_date'])
            df_bdl.to_csv("bdl_boxscore_gaps.csv", index=False)
            logger.info(f"Exported {len(bdl_gaps_data)} BDL boxscore gap records to bdl_boxscore_gaps.csv")
        
        # Export combined summary for overview
        combined_gaps_data = []
        for game in result.missing_from_both:
            combined_gaps_data.append({
                'game_date': game.game_date,
                'away_team': game.away_team,
                'home_team': game.home_team,
                'season_year': game.season_year,
                'schedule_game_id': game.source_game_id,
                'nbacom_status': 'missing',
                'bdl_status': 'missing',
                'priority': 'high'
            })
        
        for game in result.missing_from_gamebook:
            combined_gaps_data.append({
                'game_date': game.game_date,
                'away_team': game.away_team,
                'home_team': game.home_team,
                'season_year': game.season_year,
                'schedule_game_id': game.source_game_id,
                'nbacom_status': 'missing',
                'bdl_status': 'available',
                'priority': 'medium'
            })
        
        for game in result.missing_from_bdl:
            combined_gaps_data.append({
                'game_date': game.game_date,
                'away_team': game.away_team,
                'home_team': game.home_team,
                'season_year': game.season_year,
                'schedule_game_id': game.source_game_id,
                'nbacom_status': 'available',
                'bdl_status': 'missing',
                'priority': 'low'
            })
        
        if combined_gaps_data:
            df_combined = pd.DataFrame(combined_gaps_data)
            df_combined = df_combined.sort_values(['priority', 'game_date'])
            df_combined.to_csv("nba_all_gaps_summary.csv", index=False)
            logger.info(f"Exported {len(combined_gaps_data)} combined gap records to nba_all_gaps_summary.csv")


def main():
    """Main function to run validation with GCS file checking."""
    validator = NBADataValidator()
    
    # Run validation for past 4 NBA seasons
    logger.info("Running NBA boxscore coverage validation for past 4 seasons...")
    result, gcs_analysis = validator.validate_data_coverage()
    
    # Print summary report with GCS analysis
    validator.print_validation_report(result, gcs_analysis, detailed=True)
    
    # Export detailed gaps and date-level analysis
    validator.export_gaps_to_csv(result)
    validator.export_date_level_gaps(result)
    
    logger.info("Validation complete!")


if __name__ == "__main__":
    main()