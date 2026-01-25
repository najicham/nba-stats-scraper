#!/usr/bin/env python3
# File: data_processors/raw/balldontlie/bdl_standings_processor.py

import json
import logging
import re
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

class BdlStandingsProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Ball Don't Lie Standings Processor

    Processing Strategy: APPEND_ALWAYS
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: team_abbr, date_recorded, wins, losses, win_percentage, conference_rank
        Expected Skip Rate: N/A (APPEND_ALWAYS always writes, hash for monitoring only)
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'team_abbr',
        'date_recorded',
        'wins',
        'losses',
        'win_percentage',
        'conference_rank'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_standings'
        self.processing_strategy = 'MERGE_UPDATE'
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)

    def load_data(self) -> None:
        """Load standings data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def parse_record_string(self, record_str: str) -> Tuple[int, int]:
        """Parse '41-11' format into (wins, losses) tuple."""
        if not record_str or '-' not in record_str:
            return (0, 0)
        
        try:
            parts = record_str.split('-')
            wins = int(parts[0])
            losses = int(parts[1])
            return (wins, losses)
        except (ValueError, IndexError):
            logging.warning(f"Could not parse record string: {record_str}")
            return (0, 0)
    
    def calculate_season_display(self, season_year: int) -> str:
        """Convert 2024 to '2024-25'."""
        next_year = str(season_year + 1)[-2:]  # Get last 2 digits
        return f"{season_year}-{next_year}"
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate required fields in BDL standings data."""
        errors = []
        
        if 'season' not in data:
            errors.append("Missing season field")
        if 'standings' not in data:
            errors.append("Missing standings array")
        if 'timestamp' not in data:
            errors.append("Missing timestamp field")
            
        # Validate standings structure
        if 'standings' in data:
            for i, standing in enumerate(data['standings']):
                if 'team' not in standing:
                    errors.append(f"Standing {i}: Missing team object")
                elif 'abbreviation' not in standing['team']:
                    errors.append(f"Standing {i}: Missing team abbreviation")
                    
                required_fields = ['wins', 'losses', 'conference_rank', 'division_rank']
                for field in required_fields:
                    if field not in standing:
                        errors.append(f"Standing {i}: Missing {field}")
        
        return errors
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform BDL standings JSON into BigQuery rows."""
        # Validate data structure first
        validation_errors = self.validate_data(raw_data)
        if validation_errors:
            logging.error(f"Invalid data structure in {file_path}: {validation_errors}")
            
            # Notify about invalid data structure
            try:
                notify_error(
                    title="Invalid Standings Data Structure",
                    message=f"BDL standings data has invalid structure",
                    details={
                        'file_path': file_path,
                        'validation_errors': validation_errors,
                        'processor': 'BDL Standings'
                    },
                    processor_name="BDL Standings Processor"
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")
            
            return []
        
        rows = []
        parse_failures = []
        
        # Extract metadata
        season_year = raw_data.get('season')
        scrape_timestamp = raw_data.get('timestamp')
        
        # Parse file path to get date_recorded
        # Path format: /ball-dont-lie/standings/{season_formatted}/{date}/{timestamp}.json
        path_parts = file_path.split('/')
        date_str = None
        for part in path_parts:
            if re.match(r'\d{4}-\d{2}-\d{2}', part):
                date_str = part
                break
        
        if not date_str:
            logging.error(f"Could not extract date from file path: {file_path}")

            # Notify about date extraction failure
            try:
                notify_error(
                    title="Failed to Extract Date from Path",
                    message=f"Could not extract date from standings file path",
                    details={
                        'file_path': file_path,
                        'processor': 'BDL Standings'
                    },
                    processor_name="BDL Standings Processor"
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")

            self.transformed_data = rows

            # Smart Idempotency: Add data_hash to all records
            self.add_data_hash()
            return  # Exit early if no date found

        try:
            date_recorded = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            logging.error(f"Invalid date format in path: {date_str}")
            
            # Notify about invalid date format
            try:
                notify_error(
                    title="Invalid Date Format in Path",
                    message=f"Date string '{date_str}' has invalid format",
                    details={
                        'date_string': date_str,
                        'file_path': file_path,
                        'expected_format': 'YYYY-MM-DD',
                        'processor': 'BDL Standings'
                    },
                    processor_name="BDL Standings Processor"
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")
            
            self.transformed_data = rows
        # Process each team's standing
        for standing in raw_data.get('standings', []):
            team_data = standing.get('team', {})
            
            # Parse record strings
            conf_wins, conf_losses = self.parse_record_string(standing.get('conference_record'))
            div_wins, div_losses = self.parse_record_string(standing.get('division_record'))
            home_wins, home_losses = self.parse_record_string(standing.get('home_record'))
            road_wins, road_losses = self.parse_record_string(standing.get('road_record'))
            
            # Track parse failures
            if standing.get('conference_record') and (conf_wins == 0 and conf_losses == 0):
                parse_failures.append({
                    'team': team_data.get('abbreviation'),
                    'field': 'conference_record',
                    'value': standing.get('conference_record')
                })
            
            # Calculate derived fields
            wins = standing.get('wins', 0)
            losses = standing.get('losses', 0)
            games_played = wins + losses
            win_percentage = round(wins / games_played, 3) if games_played > 0 else 0.0
            
            row = {
                # Core identifiers
                'season_year': season_year,
                'season_display': self.calculate_season_display(season_year),
                'date_recorded': date_recorded.isoformat(),  # Convert date to string
                'team_id': team_data.get('id'),
                'team_abbr': team_data.get('abbreviation'),
                'team_city': team_data.get('city'),
                'team_name': team_data.get('name'),
                'team_full_name': team_data.get('full_name'),
                
                # Conference/Division
                'conference': team_data.get('conference'),
                'division': team_data.get('division'),
                'conference_rank': standing.get('conference_rank'),
                'division_rank': standing.get('division_rank'),
                
                # Overall record
                'wins': wins,
                'losses': losses,
                'win_percentage': win_percentage,
                'games_played': games_played,
                
                # Conference record
                'conference_record': standing.get('conference_record'),
                'conference_wins': conf_wins,
                'conference_losses': conf_losses,
                
                # Division record
                'division_record': standing.get('division_record'),
                'division_wins': div_wins,
                'division_losses': div_losses,
                
                # Home/Road splits
                'home_record': standing.get('home_record'),
                'home_wins': home_wins,
                'home_losses': home_losses,
                'road_record': standing.get('road_record'),
                'road_wins': road_wins,
                'road_losses': road_losses,
                
                # Processing metadata
                'scrape_timestamp': datetime.fromisoformat(scrape_timestamp.replace('Z', '+00:00')).isoformat() if scrape_timestamp else None,
                'source_file_path': file_path,
                'created_at': datetime.utcnow().isoformat(),
                'processed_at': datetime.utcnow().isoformat()
            }
            
            rows.append(row)
        
        logging.info(f"Transformed {len(rows)} team standings for {date_recorded}")
        
        # Warn if unexpected number of teams (NBA has 30 teams)
        if len(rows) != 30:
            try:
                notify_warning(
                    title="Unexpected Number of Teams",
                    message=f"Expected 30 teams in standings, got {len(rows)}",
                    details={
                        'team_count': len(rows),
                        'expected_count': 30,
                        'date_recorded': date_recorded.isoformat(),
                        'season_year': season_year,
                        'processor': 'BDL Standings'
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")
        
        # Warn about record parsing failures
        if parse_failures:
            try:
                notify_warning(
                    title="Record String Parsing Failures",
                    message=f"Failed to parse {len(parse_failures)} record strings",
                    details={
                        'failure_count': len(parse_failures),
                        'sample_failures': parse_failures[:5],
                        'processor': 'BDL Standings'
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")
        
        self.transformed_data = rows

    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load standings data using MERGE_UPDATE strategy."""
        if not rows:
            # Notify about empty data
            try:
                notify_warning(
                    title="No Standings Data to Process",
                    message="BDL standings data is empty",
                    details={
                        'processor': 'BDL Standings'
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")


            self.stats["rows_inserted"] = 0
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            # For MERGE_UPDATE: Delete existing data for this date
            date_recorded = rows[0]['date_recorded']
            season_year = rows[0]['season_year']
            
            delete_query = f"""
                DELETE FROM `{table_id}` 
                WHERE date_recorded = '{date_recorded}' 
                AND season_year = {season_year}
            """
            
            logging.info(f"Deleting existing data for {date_recorded}, season {season_year}")
            
            try:
                self.bq_client.query(delete_query).result(timeout=60)
            except Exception as delete_error:
                logging.error(f"Failed to delete existing standings: {delete_error}")
                
                # Notify about deletion failure
                try:
                    notify_error(
                        title="Failed to Delete Existing Standings",
                        message=f"Could not delete existing standings data for {date_recorded}",
                        details={
                            'date_recorded': date_recorded,
                            'season_year': season_year,
                            'error': str(delete_error),
                            'error_type': type(delete_error).__name__,
                            'processor': 'BDL Standings',
                            'impact': 'may_create_duplicate_data'
                        },
                        processor_name="BDL Standings Processor"
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
                
                raise delete_error
            
            # Update created_at for existing records (set to current time for new records)
            for row in rows:
                row['processed_at'] = datetime.utcnow().isoformat()
            
            # Insert new data using batch loading (not streaming insert)
            # This avoids the 20 DML limit and streaming buffer issues
            logging.info(f"Loading {len(rows)} standings for {date_recorded} using batch load")

            # Get table schema for load job
            table = self.bq_client.get_table(table_id)

            # Configure batch load job
            job_config = bigquery.LoadJobConfig(
                schema=table.schema,
                autodetect=False,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
            )

            # Load using batch job
            load_job = self.bq_client.load_table_from_json(
                rows,
                table_id,
                job_config=job_config
            )

            # Wait for completion
            load_job.result(timeout=60)
            logging.info(f"Successfully loaded {len(rows)} standings for {date_recorded}")

            self.stats["rows_inserted"] = len(rows)

            # Calculate summary statistics
            east_teams = sum(1 for row in rows if row['conference'] == 'East')
            west_teams = sum(1 for row in rows if row['conference'] == 'West')
            avg_games_played = sum(row['games_played'] for row in rows) / len(rows)

            # Get top teams by conference (already has default None - safe)
            east_leader = next((row for row in sorted(rows, key=lambda x: x['conference_rank'] or 99)
                               if row['conference'] == 'East'), None)
            west_leader = next((row for row in sorted(rows, key=lambda x: x['conference_rank'] or 99)
                               if row['conference'] == 'West'), None)

            # Send success notification
            try:
                notify_info(
                    title="BDL Standings Processing Complete",
                    message=f"Successfully processed standings for {len(rows)} teams on {date_recorded}",
                    details={
                        'total_teams': len(rows),
                        'date_recorded': date_recorded,
                        'season_year': season_year,
                        'season_display': rows[0]['season_display'],
                        'east_teams': east_teams,
                        'west_teams': west_teams,
                        'avg_games_played': round(avg_games_played, 1),
                        'east_leader': f"{east_leader['team_abbr']} ({east_leader['wins']}-{east_leader['losses']})" if east_leader else 'N/A',
                        'west_leader': f"{west_leader['team_abbr']} ({west_leader['wins']}-{west_leader['losses']})" if west_leader else 'N/A',
                        'table': self.table_name,
                        'processor': 'BDL Standings'
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")

        except Exception as e:
            error_msg = f"Error loading standings data: {str(e)}"
            logging.error(error_msg)
            errors.append(error_msg)

            self.stats["rows_inserted"] = 0
            
            # Notify about general processing error
            try:
                notify_error(
                    title="BDL Standings Processing Failed",
                    message=f"Unexpected error during standings processing: {str(e)}",
                    details={
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'BDL Standings'
                    },
                    processor_name="BDL Standings Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }
