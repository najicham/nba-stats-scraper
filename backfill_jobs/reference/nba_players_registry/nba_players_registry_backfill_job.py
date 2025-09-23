#!/usr/bin/env python3
"""
File: processor_backfill/nba_players_registry/nba_players_registry_backfill_job.py

Backfill job for building NBA Players Registry from historical gamebook data

Usage Examples:
=============

1. Deploy Job:
   ./processor_backfill/nba_players_registry/deploy.sh

2. Test with Single Season:
   gcloud run jobs execute nba-players-registry-processor-backfill --args=--season=2023-24 --region=us-west2

3. Full Historical Backfill:
   gcloud run jobs execute nba-players-registry-processor-backfill --args=--all-seasons --region=us-west2

4. Recent Date Range:
   gcloud run jobs execute nba-players-registry-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2

5. Test Mode (NEW):
   gcloud run jobs execute nba-players-registry-processor-backfill --args=--start-date=2022-10-01,--end-date=2022-10-31,--test-mode --region=us-west2

6. Monitor Logs:
   gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow

7. Registry Summary:
   gcloud run jobs execute nba-players-registry-processor-backfill --args=--summary-only --region=us-west2
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.reference.player_reference.nba_players_registry_processor import NbaPlayersRegistryProcessor


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


class NbaPlayersRegistryBackfill:
    """Backfill job for building NBA Players Registry from gamebook data."""
    
    def __init__(self, test_mode: bool = False):
        self.processor = NbaPlayersRegistryProcessor(test_mode=test_mode)
        
        # Available seasons based on typical NBA data availability
        self.available_seasons = [
            '2021-22', '2022-23', '2023-24', '2024-25'
        ]
        
    def get_available_seasons_from_data(self) -> List[str]:
        """Query the database to find available seasons in gamebook data."""
        try:
            query = f"""
            SELECT DISTINCT 
                CONCAT(CAST(season_year AS STRING), '-', LPAD(CAST(season_year + 1 - 2000 AS STRING), 2, '0')) as season
            FROM `{self.processor.project_id}.nba_raw.nbac_gamebook_player_stats`
            WHERE season_year IS NOT NULL
            ORDER BY season_year DESC
            """
            
            results = self.processor.bq_client.query(query).to_dataframe()
            
            if not results.empty:
                seasons = results['season'].tolist()
                logging.info(f"Found {len(seasons)} seasons in gamebook data: {seasons}")
                return seasons
            else:
                logging.warning("No seasons found in gamebook data, using default list")
                return self.available_seasons
                
        except Exception as e:
            logging.error(f"Error querying available seasons: {e}")
            return self.available_seasons
    
    def build_registry_for_all_seasons(self) -> Dict:
        """Build registry for all available seasons."""
        logging.info("Starting full registry backfill for all seasons")
        
        seasons = self.get_available_seasons_from_data()
        
        if not seasons:
            logging.error("No seasons available for processing")
            return {'error': 'No seasons found'}
        
        results = {
            'seasons_processed': [],
            'total_records': 0,
            'total_players': 0,
            'errors': [],
            'start_time': datetime.now().isoformat(),
            'end_time': None
        }
        
        for i, season in enumerate(seasons, 1):
            logging.info(f"Processing season {i}/{len(seasons)}: {season}")
            
            try:
                season_result = self.processor.build_registry_for_season(season)
                
                results['seasons_processed'].append({
                    'season': season,
                    'records_processed': season_result['records_processed'],
                    'players_processed': season_result['players_processed'],
                    'teams_processed': len(season_result['teams_processed']),
                    'errors': season_result['errors']
                })
                
                results['total_records'] += season_result['records_processed']
                results['total_players'] += season_result['players_processed']
                
                if season_result['errors']:
                    results['errors'].extend(season_result['errors'])
                
                logging.info(f"Completed {season}: {season_result['records_processed']} records, {season_result['players_processed']} players")
                
            except Exception as e:
                error_msg = f"Error processing season {season}: {str(e)}"
                logging.error(error_msg)
                results['errors'].append(error_msg)
        
        results['end_time'] = datetime.now().isoformat()
        
        # Final summary
        logging.info("=" * 60)
        logging.info("REGISTRY BACKFILL SUMMARY:")
        logging.info(f"  Seasons processed: {len(results['seasons_processed'])}")
        logging.info(f"  Total registry records: {results['total_records']}")
        logging.info(f"  Total unique players: {results['total_players']}")
        logging.info(f"  Errors: {len(results['errors'])}")
        
        start_time = datetime.fromisoformat(results['start_time'])
        end_time = datetime.fromisoformat(results['end_time'])
        duration = (end_time - start_time).total_seconds() / 60
        logging.info(f"  Duration: {duration:.1f} minutes")
        logging.info("=" * 60)
        
        return results
    
    def build_registry_for_season(self, season: str) -> Dict:
        """Build registry for a specific season."""
        logging.info(f"Building registry for season: {season}")
        
        # Validate season format
        if not self.validate_season_format(season):
            error_msg = f"Invalid season format: {season}. Expected format: YYYY-YY (e.g., 2023-24)"
            logging.error(error_msg)
            return {'error': error_msg}
        
        try:
            result = self.processor.build_registry_for_season(season)
            
            logging.info(f"Registry build complete for {season}:")
            logging.info(f"  Records: {result['records_processed']}")
            logging.info(f"  Players: {result['players_processed']}")
            logging.info(f"  Teams: {len(result['teams_processed'])}")
            
            return result
            
        except Exception as e:
            error_msg = f"Error building registry for season {season}: {str(e)}"
            logging.error(error_msg)
            return {'error': error_msg}
    
    def build_registry_for_date_range(self, start_date: str, end_date: str) -> Dict:
        """Build registry for a specific date range."""
        logging.info(f"Building registry for date range: {start_date} to {end_date}")
        
        try:
            # Validate dates
            datetime.strptime(start_date, '%Y-%m-%d')
            datetime.strptime(end_date, '%Y-%m-%d')
            
            result = self.processor.build_registry_for_date_range(start_date, end_date)
            
            logging.info(f"Registry build complete for {start_date} to {end_date}:")
            logging.info(f"  Records: {result['records_processed']}")
            logging.info(f"  Players: {result['players_processed']}")
            logging.info(f"  Seasons: {len(result['seasons_processed'])}")
            
            return result
            
        except ValueError as e:
            error_msg = f"Invalid date format: {e}. Expected YYYY-MM-DD"
            logging.error(error_msg)
            return {'error': error_msg}
        except Exception as e:
            error_msg = f"Error building registry for date range: {str(e)}"
            logging.error(error_msg)
            return {'error': error_msg}
    
    def get_registry_summary(self) -> Dict:
        """Get summary of current registry state."""
        logging.info("Getting registry summary...")
        
        try:
            summary = self.processor.get_registry_summary()
            
            if 'error' in summary:
                logging.error(f"Error getting summary: {summary['error']}")
                return summary
            
            # Handle None values AND pandas NaN/NaT for empty registry
            import pandas as pd
            
            total_records = summary.get('total_records', 0) or 0
            unique_players = summary.get('unique_players', 0) or 0
            seasons_covered = summary.get('seasons_covered', 0) or 0
            teams_covered = summary.get('teams_covered', 0) or 0
            total_games = summary.get('total_games_played', 0) or 0
            
            # Handle NaN for average games
            avg_games_raw = summary.get('avg_games_per_record', 0)
            avg_games = 0.0 if pd.isna(avg_games_raw) else (avg_games_raw or 0.0)
            
            # Handle NaT for last updated
            last_updated_raw = summary.get('last_updated')
            last_updated = 'Never' if pd.isna(last_updated_raw) else (last_updated_raw or 'Never')
            
            # Print summary
            logging.info("=" * 60)
            logging.info("NBA PLAYERS REGISTRY SUMMARY:")
            logging.info(f"  Total Records: {total_records:,}")
            logging.info(f"  Unique Players: {unique_players:,}")
            logging.info(f"  Seasons Covered: {seasons_covered}")
            logging.info(f"  Teams Covered: {teams_covered}")
            logging.info(f"  Total Games: {total_games:,}")
            logging.info(f"  Avg Games/Record: {avg_games:.1f}")
            logging.info(f"  Last Updated: {last_updated}")
            logging.info("")
            
            if 'seasons_breakdown' in summary and summary['seasons_breakdown']:
                logging.info("Season Breakdown:")
                for season_info in summary['seasons_breakdown']:
                    logging.info(f"  {season_info['season']}: {season_info['records']} records, {season_info['players']} players, {season_info['teams']} teams")
            
            logging.info("=" * 60)
            
            return summary
            
        except Exception as e:
            error_msg = f"Error getting registry summary: {str(e)}"
            logging.error(error_msg)
            return {'error': error_msg}
    
    def validate_season_format(self, season: str) -> bool:
        """Validate season string format (YYYY-YY)."""
        try:
            parts = season.split('-')
            if len(parts) != 2:
                return False
            
            year1 = int(parts[0])
            year2 = int(parts[1])
            
            # Check that it's a valid NBA season format
            if year1 < 2000 or year1 > 2030:
                return False
            
            # Check that second year is year1 + 1 (last 2 digits)
            expected_year2 = (year1 + 1) % 100
            if year2 != expected_year2:
                return False
            
            return True
            
        except (ValueError, IndexError):
            return False
    
    def run_backfill(self, args) -> Dict:
        """Run the appropriate backfill based on arguments."""
        
        if args.summary_only:
            return self.get_registry_summary()
        
        elif args.all_seasons:
            return self.build_registry_for_all_seasons()
        
        elif args.season:
            return self.build_registry_for_season(args.season)
        
        elif args.start_date and args.end_date:
            return self.build_registry_for_date_range(args.start_date, args.end_date)
        
        else:
            # Default: build for current season
            current_date = date.today()
            if current_date.month >= 10:  # Oct-Dec = new season starting
                current_season_year = current_date.year
            else:  # Jan-Sep = season ending
                current_season_year = current_date.year - 1
            
            current_season = f"{current_season_year}-{str(current_season_year + 1)[-2:]}"
            logging.info(f"No specific parameters provided, building for current season: {current_season}")
            return self.build_registry_for_season(current_season)


def main():
    parser = argparse.ArgumentParser(description='NBA Players Registry Backfill Job')
    
    # Mutually exclusive group for different modes
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--all-seasons', action='store_true', 
                           help='Build registry for all available seasons')
    mode_group.add_argument('--season', type=str, 
                           help='Build registry for specific season (e.g., 2023-24)')
    mode_group.add_argument('--summary-only', action='store_true',
                           help='Show registry summary without building')
    
    # Date range options (used together)
    parser.add_argument('--start-date', type=str, 
                       help='Start date for date range processing (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str,
                       help='End date for date range processing (YYYY-MM-DD)')
    
    # Test mode option
    parser.add_argument('--test-mode', action='store_true',
                       help='Run in test mode using test tables')
    
    args = parser.parse_args()
    
    # Validate date range arguments
    if (args.start_date and not args.end_date) or (args.end_date and not args.start_date):
        parser.error("Both --start-date and --end-date must be provided together")
    
    if args.start_date and args.end_date and (args.all_seasons or args.season):
        parser.error("Date range cannot be used with --all-seasons or --season")
    
    logging.info("Starting NBA Players Registry Backfill Job")
    logging.info(f"Arguments: {vars(args)}")
    
    backfiller = NbaPlayersRegistryBackfill(test_mode=args.test_mode)
    
    try:
        result = backfiller.run_backfill(args)
        
        if 'error' in result:
            logging.error(f"Backfill failed: {result['error']}")
            return 1
        else:
            logging.info("Backfill completed successfully")
            return 0
            
    except Exception as e:
        logging.error(f"Unexpected error during backfill: {str(e)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())