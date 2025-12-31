#!/usr/bin/env python3
"""
File: processors/nbacom/nbac_injury_report_processor.py

Process NBA.com Injury Report data for player availability tracking.
Integrated notification system for monitoring and alerts.
"""

import json
import logging
import os
from datetime import datetime, date
from typing import Dict, List, Optional
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

logger = logging.getLogger(__name__)

class NbacInjuryReportProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Process NBA.com Injury Report data.

    Processing Strategy: APPEND_ALWAYS
    Smart Idempotency: Enabled (Pattern #14)
        Hash Fields: player_lookup, team, game_date, game_id, injury_status, reason, reason_category
        Expected Skip Rate: N/A (APPEND_ALWAYS always writes, hash for monitoring only)
    """

    # Smart Idempotency: Define meaningful fields for hash computation
    HASH_FIELDS = [
        'player_lookup',
        'team',
        'game_date',
        'game_id',
        'injury_status',
        'reason',
        'reason_category'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_injury_report'
        self.processing_strategy = 'APPEND_ALWAYS'  # Keep all reports for history
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        self.records_processed = 0
        self.records_failed = 0

    def load_data(self) -> None:
        """Load data from GCS."""
        self.raw_data = self.load_json_from_gcs()

    def validate_data(self, data: Dict) -> List[str]:
        """Validate the JSON data structure."""
        errors = []
        
        if 'metadata' not in data:
            errors.append("Missing 'metadata' section")
            
        if 'records' not in data:
            errors.append("Missing 'records' section")
            return errors
            
        if not isinstance(data['records'], list):
            errors.append("'records' should be a list")
            
        # Check first record structure if exists
        if data['records']:
            required_fields = ['date', 'gametime', 'matchup', 'team', 'player', 'status']
            first_record = data['records'][0]
            for field in required_fields:
                if field not in first_record:
                    errors.append(f"Missing required field in record: {field}")
        
        # Notify about validation failures
        if errors:
            try:
                notify_warning(
                    title="Injury Report Data Validation Failed",
                    message=f"Found {len(errors)} validation errors in injury report data",
                    details={
                        'errors': errors,
                        'has_metadata': 'metadata' in data,
                        'has_records': 'records' in data,
                        'record_count': len(data.get('records', []))
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
                    
        return errors
    
    def _normalize_player_name(self, player_name: str) -> tuple[str, str]:
        """
        Parse "Last, First" format and create normalized lookup.
        Returns (full_name, player_lookup)
        """
        if not player_name:
            return ("", "")
            
        # Parse "Hayes, Killian" format
        parts = player_name.split(',')
        if len(parts) == 2:
            last_name = parts[0].strip()
            first_name = parts[1].strip()
            full_name = f"{first_name} {last_name}"
        else:
            # Handle cases without comma
            full_name = player_name.strip()
            
        # Create normalized lookup
        player_lookup = full_name.lower()
        for char in [' ', "'", '.', '-', ',', 'jr', 'sr', 'ii', 'iii', 'iv']:
            player_lookup = player_lookup.replace(char, '')
            
        return (full_name, player_lookup)
    
    def _parse_matchup(self, matchup: str, game_date: str) -> Dict:
        """
        Parse matchup string like "MIA@DET" to extract teams and create game_id.
        Returns dict with away_team, home_team, and game_id
        """
        try:
            parts = matchup.split('@')
            if len(parts) != 2:
                logger.warning(f"Invalid matchup format: {matchup}")
                return {'away_team': '', 'home_team': '', 'game_id': ''}
                
            away_team = parts[0].strip()
            home_team = parts[1].strip()
            
            # Parse date to create game_id
            try:
                date_obj = datetime.strptime(game_date, '%m/%d/%Y')
                date_str = date_obj.strftime('%Y%m%d')
                game_id = f"{date_str}_{away_team}_{home_team}"
            except ValueError as e:
                logger.warning(f"Could not parse game date '{game_date}': {e}. Using raw format.")
                game_id = f"{game_date}_{away_team}_{home_team}"
                
            return {
                'away_team': away_team,
                'home_team': home_team,
                'game_id': game_id
            }
        except Exception as e:
            logger.error(f"Error parsing matchup '{matchup}': {e}")
            return {'away_team': '', 'home_team': '', 'game_id': ''}
    
    def _parse_game_time(self, gametime: str) -> Optional[str]:
        """Parse gametime like '07:00 (ET)' to standard format."""
        if not gametime:
            return None
        # Remove timezone indicator
        time_str = gametime.replace('(ET)', '').replace('(EST)', '').strip()
        return time_str
    
    def _categorize_reason(self, reason: str) -> str:
        """Categorize the reason for absence."""
        if not reason:
            return 'unknown'
            
        reason_lower = reason.lower()
        
        if 'injury/illness' in reason_lower:
            return 'injury'
        elif 'g league' in reason_lower:
            return 'g_league'
        elif 'suspension' in reason_lower:
            return 'suspension'
        elif 'health and safety' in reason_lower or 'protocol' in reason_lower:
            return 'health_safety_protocol'
        elif 'rest' in reason_lower:
            return 'rest'
        elif 'personal' in reason_lower:
            return 'personal'
        else:
            return 'other'
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        """Transform injury report data to BigQuery rows."""
        rows = []
        
        try:
            # Extract metadata
            metadata = raw_data.get('metadata', {})
            
            if not metadata:
                try:
                    notify_warning(
                        title="Missing Injury Report Metadata",
                        message="Injury report data missing metadata section",
                        details={
                            'file_path': file_path,
                            'has_records': 'records' in raw_data,
                            'record_count': len(raw_data.get('records', []))
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            report_date = metadata.get('gamedate', '')
            report_hour = metadata.get('hour24', metadata.get('hour', ''))
            scrape_time = metadata.get('scrape_time', '')
            run_id = metadata.get('run_id', '')
            
            # Parse report date (handle both %Y%m%d and %Y-%m-%d formats)
            report_date_obj = None
            for date_format in ('%Y%m%d', '%Y-%m-%d'):
                try:
                    report_date_obj = datetime.strptime(report_date, date_format).date()
                    break
                except ValueError:
                    continue

            if report_date_obj is None:
                logger.error(f"Error parsing report date '{report_date}': no matching format")
                report_date_obj = date.today()
                
                try:
                    notify_warning(
                        title="Invalid Report Date Format",
                        message=f"Could not parse report date, using today's date",
                        details={
                            'report_date': report_date,
                            'file_path': file_path,
                            'fallback_date': report_date_obj.isoformat()
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            season = self._get_nba_season(report_date_obj)
            
            # Get parsing stats
            parsing_stats = raw_data.get('parsing_stats', {})
            overall_confidence = parsing_stats.get('overall_confidence', 1.0)
            
            # Check for low confidence scores
            if overall_confidence < 0.85:
                try:
                    notify_warning(
                        title="Low Injury Report Confidence",
                        message=f"Injury report has low confidence score: {overall_confidence:.2%}",
                        details={
                            'overall_confidence': overall_confidence,
                            'file_path': file_path,
                            'report_date': report_date,
                            'record_count': len(raw_data.get('records', []))
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            
            # Process each injury record
            self.records_processed = 0
            self.records_failed = 0
            
            for record in raw_data.get('records', []):
                try:
                    # Parse player name
                    player_full_name, player_lookup = self._normalize_player_name(record['player'])
                    
                    # Parse matchup
                    matchup_info = self._parse_matchup(record['matchup'], record['date'])
                    
                    # Parse game time
                    game_time = self._parse_game_time(record.get('gametime', ''))
                    
                    # Categorize reason
                    reason_category = self._categorize_reason(record.get('reason', ''))
                    
                    row = {
                        'report_date': report_date_obj.isoformat(),
                        'report_hour': int(report_hour) if report_hour else None,
                        'season': season,
                        'game_date': datetime.strptime(record['date'], '%m/%d/%Y').date().isoformat(),
                        'game_time': game_time,
                        'game_id': matchup_info['game_id'],
                        'matchup': record['matchup'],
                        'away_team': matchup_info['away_team'],
                        'home_team': matchup_info['home_team'],
                        'team': record['team'],
                        'player_name_original': record['player'],
                        'player_full_name': player_full_name,
                        'player_lookup': player_lookup,
                        'injury_status': record['status'].lower(),
                        'reason': record.get('reason', ''),
                        'reason_category': reason_category,
                        'confidence_score': record.get('confidence', 1.0),
                        'overall_report_confidence': overall_confidence,
                        'scrape_time': scrape_time,
                        'run_id': run_id,
                        'source_file_path': file_path,
                        'processed_at': datetime.utcnow().isoformat()
                    }
                    
                    rows.append(row)
                    self.records_processed += 1
                    
                except Exception as e:
                    self.records_failed += 1
                    logger.error(f"Error processing injury record: {e}")
                    logger.error(f"Record data: {record}")
                    
                    # Notify about individual record failure if it seems significant
                    if self.records_failed == 1:  # First failure
                        try:
                            notify_error(
                                title="Injury Record Processing Failed",
                                message=f"Failed to process injury record: {str(e)}",
                                details={
                                    'file_path': file_path,
                                    'error_type': type(e).__name__,
                                    'record': str(record)[:200],
                                    'player': record.get('player', 'unknown')
                                },
                                processor_name="NBA.com Injury Report Processor"
                            )
                        except Exception as notify_ex:
                            logger.warning(f"Failed to send notification: {notify_ex}")
                    continue
            
            # Check for high failure rate
            total_records = len(raw_data.get('records', []))
            if total_records > 0:
                failure_rate = self.records_failed / total_records
                if failure_rate > 0.1:  # More than 10% failures
                    try:
                        notify_warning(
                            title="High Injury Record Failure Rate",
                            message=f"Failed to process {failure_rate:.1%} of injury records",
                            details={
                                'file_path': file_path,
                                'total_records': total_records,
                                'records_failed': self.records_failed,
                                'records_processed': self.records_processed,
                                'failure_rate': f"{failure_rate:.1%}"
                            }
                        )
                    except Exception as notify_ex:
                        logger.warning(f"Failed to send notification: {notify_ex}")
            
            logger.info(f"Transformed {len(rows)} injury records (failed: {self.records_failed})")
            self.transformed_data = rows

            # Smart Idempotency: Add data_hash to all records
            self.add_data_hash()

        except Exception as e:
            logger.error(f"Critical error in transform_data: {e}")
            
            # Notify about critical transformation failure
            try:
                notify_error(
                    title="Injury Report Transformation Failed",
                    message=f"Critical error transforming injury report data: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error_type': type(e).__name__,
                        'records_processed': self.records_processed,
                        'records_failed': self.records_failed
                    },
                    processor_name="NBA.com Injury Report Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise e
    
    def _get_nba_season(self, report_date_obj: date) -> str:
        """Determine NBA season from date. Season runs Oct-June."""
        try:
            year = report_date_obj.year
            month = report_date_obj.month
            
            # October-December is start of season
            if month >= 10:
                return f"{year}-{str(year+1)[2:]}"  # e.g., "2021-22"
            # January-September is end of season
            else:
                return f"{year-1}-{str(year)[2:]}"  # e.g., "2021-22"
        except Exception as e:
            logger.error(f"Error determining NBA season: {e}")
            # Return current year as fallback
            current_year = datetime.now().year
            return f"{current_year-1}-{str(current_year)[2:]}"
    
    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data
        """Load data to BigQuery using APPEND_ALWAYS strategy."""
        if not rows:
            logger.warning("No rows to load")
            return {'rows_processed': 0, 'errors': []}
        
        errors = []
        
        try:
            from google.cloud import bigquery
            client = bigquery.Client()
            table_id = 'nba_raw.nbac_injury_report'

            # Get table reference for schema
            table_ref = client.get_table(table_id)

            # Use batch loading instead of streaming inserts
            # This avoids the 90-minute streaming buffer that blocks DML operations
            # See: docs/05-development/guides/bigquery-best-practices.md
            job_config = bigquery.LoadJobConfig(
                schema=table_ref.schema,
                autodetect=False,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
                ignore_unknown_values=True
            )

            load_job = client.load_table_from_json(rows, table_id, job_config=job_config)
            load_job.result()

            if load_job.errors:
                errors.extend([str(e) for e in load_job.errors])
                logger.error(f"BigQuery load had errors: {load_job.errors[:3]}")

                # Notify about load errors
                try:
                    notify_error(
                        title="BigQuery Load Errors",
                        message=f"Encountered {len(load_job.errors)} errors loading injury report data",
                        details={
                            'table': 'nba_raw.nbac_injury_report',
                            'rows_attempted': len(rows),
                            'error_count': len(load_job.errors),
                            'errors': str(load_job.errors)[:500]
                        },
                        processor_name="NBA.com Injury Report Processor"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
            else:
                logger.info(f"Successfully appended {len(rows)} injury records")
                
                # Send success notification
                try:
                    notify_info(
                        title="Injury Report Processing Complete",
                        message=f"Successfully processed {len(rows)} injury records",
                        details={
                            'records_inserted': len(rows),
                            'records_failed': self.records_failed,
                            'table': 'nba_raw.nbac_injury_report'
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                
        except Exception as e:
            errors.append(str(e))
            logger.error(f"Error loading data: {e}")
            
            # Notify about critical load failure
            try:
                notify_error(
                    title="Injury Report Load Failed",
                    message=f"Failed to load injury report data to BigQuery: {str(e)}",
                    details={
                        'table': 'nba_raw.nbac_injury_report',
                        'rows_attempted': len(rows),
                        'error_type': type(e).__name__,
                        'error': str(e)
                    },
                    processor_name="NBA.com Injury Report Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
        
        return {'rows_processed': len(rows), 'errors': errors}

    def get_processor_stats(self) -> Dict:
        """Return processing statistics."""
        return {
            'rows_processed': self.stats.get('rows_inserted', 0),
            'rows_failed': self.stats.get('rows_failed', 0),
            'run_id': self.stats.get('run_id'),
            'total_runtime': self.stats.get('total_runtime', 0)
        }
