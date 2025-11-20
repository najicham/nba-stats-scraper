#!/usr/bin/env python3
import json, logging, re, os
from typing import Dict, List, Optional
from datetime import datetime
from google.cloud import bigquery
from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.utils.name_utils import normalize_name
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

class BdlActivePlayersProcessor(ProcessorBase):
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_active_players_current'
        self.processing_strategy = 'MERGE_UPDATE'  # Current-state data
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
        # Load NBA.com player data for validation
        self.nba_com_players = self._load_nba_com_players()
    
    def parse_json(self, json_content: str, file_path: str) -> Dict:
        """Parse Ball Don't Lie Active Players JSON."""
        try:
            data = json.loads(json_content)
            
            # Convert Ball Don't Lie format to expected format
            if 'activePlayers' in data:
                return {
                    'data': data['activePlayers'],  # Convert activePlayers -> data
                    'metadata': {
                        'ident': data.get('ident'),
                        'timestamp': data.get('timestamp'),
                        'playerCount': data.get('playerCount'),
                        'source_file': file_path
                    }
                }
            else:
                logging.error(f"No 'activePlayers' field found in {file_path}")
                
                # Notify about missing activePlayers field
                try:
                    notify_error(
                        title="Invalid BDL Active Players Data",
                        message=f"Missing 'activePlayers' field in data",
                        details={
                            'file_path': file_path,
                            'available_fields': list(data.keys()) if isinstance(data, dict) else 'not_a_dict',
                            'processor': 'BDL Active Players'
                        },
                        processor_name="BDL Active Players Processor"
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
                
                return None
                
        except json.JSONDecodeError as e:
            logging.error(f"JSON decode error in {file_path}: {e}")
            
            # Notify about JSON parsing failure
            try:
                notify_error(
                    title="JSON Parsing Failed",
                    message=f"Failed to parse BDL active players JSON",
                    details={
                        'file_path': file_path,
                        'error': str(e),
                        'error_type': 'JSONDecodeError',
                        'processor': 'BDL Active Players'
                    },
                    processor_name="BDL Active Players Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return None
        except Exception as e:
            logging.error(f"Error parsing JSON from {file_path}: {e}")
            
            # Notify about unexpected parsing error
            try:
                notify_error(
                    title="Unexpected Parsing Error",
                    message=f"Unexpected error parsing active players data: {str(e)}",
                    details={
                        'file_path': file_path,
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'processor': 'BDL Active Players'
                    },
                    processor_name="BDL Active Players Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return None
    
    def _load_nba_com_players(self) -> Dict[str, Dict]:
        """Load current NBA.com player data for validation."""
        try:
            if not self.bq_client:
                logging.error("BigQuery client not initialized")
                
                # Notify about missing BigQuery client
                try:
                    notify_error(
                        title="BigQuery Client Not Initialized",
                        message="Cannot load NBA.com players for validation",
                        details={
                            'processor': 'BDL Active Players',
                            'impact': 'validation_disabled'
                        },
                        processor_name="BDL Active Players Processor"
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
                
                return {}
                
            query = """
            SELECT player_lookup, player_full_name, team_abbr, player_id
            FROM `nba-props-platform.nba_raw.nbac_player_list_current`
            WHERE is_active = TRUE
            """
            results = self.bq_client.query(query).result()
            
            players = {}
            for row in results:
                players[row.player_lookup] = {
                    'full_name': row.player_full_name,
                    'team_abbr': row.team_abbr,
                    'player_id': row.player_id
                }
            logging.info(f"Loaded {len(players)} NBA.com players for validation")
            
            # Warn if very few players loaded
            if len(players) < 400:  # NBA typically has 450+ active players
                try:
                    notify_warning(
                        title="Low NBA.com Player Count",
                        message=f"Only loaded {len(players)} NBA.com players for validation",
                        details={
                            'player_count': len(players),
                            'expected_minimum': 400,
                            'processor': 'BDL Active Players',
                            'impact': 'validation_may_be_incomplete'
                        }
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
            
            return players
        except Exception as e:
            logging.warning(f"Could not load NBA.com players for validation: {e}")
            
            # Notify about validation data loading failure
            try:
                notify_warning(
                    title="Failed to Load Validation Data",
                    message=f"Could not load NBA.com players for validation: {str(e)}",
                    details={
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'processor': 'BDL Active Players',
                        'impact': 'validation_disabled'
                    }
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
            
            return {}
    
    def normalize_text(self, text: str) -> str:
        """Aggressive normalization for data consistency."""
        if not text:
            return ""
        normalized = text.lower().strip()
        # Remove all non-alphanumeric characters
        return re.sub(r'[^a-z0-9]', '', normalized)
    
    def validate_data(self, data: Dict) -> List[str]:
        errors = []
        
        if 'data' not in data:
            errors.append("Missing 'data' field in JSON")
            return errors
            
        if not isinstance(data['data'], list):
            errors.append("'data' field is not a list")
            return errors
        
        for i, player in enumerate(data['data']):
            if 'id' not in player:
                errors.append(f"Player {i}: Missing 'id' field")
            if 'first_name' not in player:
                errors.append(f"Player {i}: Missing 'first_name' field")
            if 'last_name' not in player:
                errors.append(f"Player {i}: Missing 'last_name' field")
            if 'team' not in player or not isinstance(player['team'], dict):
                errors.append(f"Player {i}: Missing or invalid 'team' field")
            elif 'abbreviation' not in player['team']:
                errors.append(f"Player {i}: Missing team abbreviation")
        
        return errors
    
    def _validate_against_nba_com(self, player_lookup: str, bdl_team_abbr: str, player_full_name: str) -> Dict[str, str]:
        """Validate BDL data against NBA.com data."""
        validation_issues = []
        nba_com_data = self.nba_com_players.get(player_lookup)
        
        if not nba_com_data:
            return {
                'has_issues': True,
                'status': 'missing_nba_com',
                'details': json.dumps({
                    'issues': [{'type': 'missing_nba_com', 'message': 'Player not found in NBA.com data'}]
                }),
                'nba_com_team': None
            }
        
        # Check team mismatch
        nba_team = nba_com_data['team_abbr']
        if bdl_team_abbr != nba_team:
            validation_issues.append({
                'type': 'team_mismatch',
                'bdl_team': bdl_team_abbr,
                'nba_com_team': nba_team,
                'severity': 'medium'
            })
        
        if validation_issues:
            return {
                'has_issues': True,
                'status': 'team_mismatch' if any(issue['type'] == 'team_mismatch' for issue in validation_issues) else 'data_quality_issue',
                'details': json.dumps({'issues': validation_issues}),
                'nba_com_team': nba_team
            }
        else:
            return {
                'has_issues': False,
                'status': 'validated',
                'details': json.dumps({'issues': []}),
                'nba_com_team': nba_team
            }
    
    def transform_data(self) -> None:
        """Transform raw data into transformed data."""
        raw_data = self.raw_data
        file_path = self.raw_data.get('metadata', {}).get('source_file', 'unknown')
        rows = []

        for player_data in raw_data['data']:
            # Basic player info
            first_name = player_data.get('first_name', '').strip()
            last_name = player_data.get('last_name', '').strip()
            player_full_name = f"{first_name} {last_name}".strip()
            player_lookup = normalize_name(player_full_name)
            
            # Team info
            team_info = player_data.get('team', {})
            team_abbr = team_info.get('abbreviation', '')
            
            # Perform validation against NBA.com data
            validation_result = self._validate_against_nba_com(
                player_lookup, team_abbr, player_full_name
            )
            
            row = {
                # Primary identifiers
                'player_lookup': player_lookup,
                'bdl_player_id': player_data.get('id'),
                'first_name': first_name,
                'last_name': last_name,
                'player_full_name': player_full_name,
                
                # Team assignment
                'bdl_team_id': team_info.get('id'),
                'team_abbr': team_abbr,
                'team_city': team_info.get('city', ''),
                'team_name': team_info.get('name', ''),
                'team_full_name': team_info.get('full_name', ''),
                'team_conference': team_info.get('conference', ''),
                'team_division': team_info.get('division', ''),
                
                # Player attributes  
                'position': player_data.get('position', ''),
                'height': player_data.get('height', ''),
                'weight': player_data.get('weight', ''),
                'jersey_number': player_data.get('jersey_number', ''),
                
                # Career information
                'college': player_data.get('college', ''),
                'country': player_data.get('country', ''),
                'draft_year': player_data.get('draft_year'),
                'draft_round': player_data.get('draft_round'),
                'draft_number': player_data.get('draft_number'),
                
                # Validation tracking
                'has_validation_issues': validation_result['has_issues'],
                'validation_status': validation_result['status'],
                'validation_details': validation_result['details'],
                'nba_com_team_abbr': validation_result['nba_com_team'],
                'validation_last_check': datetime.utcnow().isoformat(),
                
                # Processing metadata
                'last_seen_date': datetime.utcnow().date().isoformat(),
                'source_file_path': file_path,
                'processed_at': datetime.utcnow().isoformat()
            }
            
            rows.append(row)

        self.transformed_data = rows
    
    def load_data(self) -> None:
        """Load active players data from GCS."""
        # Load raw JSON from GCS
        raw_json = self.load_json_from_gcs()

        # Parse and transform the JSON structure
        gcs_path = f"gs://{self.opts.get('bucket')}/{self.opts.get('file_path')}"
        self.raw_data = self.parse_json(json.dumps(raw_json), gcs_path)

    def save_data(self) -> None:
        """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
        rows = self.transformed_data

        if not rows:
            # Notify about empty data
            try:
                notify_warning(
                    title="No Active Players to Process",
                    message="BDL active players data is empty",
                    details={
                        'processor': 'BDL Active Players',
                        'expected_minimum': 400
                    }
                )
            except Exception as e:
                logging.warning(f"Failed to send notification: {e}")

            return
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # For current-state data, clear existing data before inserting
                try:
                    delete_query = f"DELETE FROM `{table_id}` WHERE TRUE"
                    self.bq_client.query(delete_query).result()
                    logging.info(f"Cleared existing data from {table_id}")
                except Exception as delete_error:
                    logging.error(f"Failed to clear existing data: {delete_error}")
                    
                    # Notify about deletion failure
                    try:
                        notify_error(
                            title="Failed to Clear Existing Data",
                            message=f"Could not clear existing active players data: {str(delete_error)}",
                            details={
                                'table': self.table_name,
                                'error': str(delete_error),
                                'error_type': type(delete_error).__name__,
                                'processor': 'BDL Active Players',
                                'impact': 'may_create_duplicate_data'
                            },
                            processor_name="BDL Active Players Processor"
                        )
                    except Exception as e:
                        logging.warning(f"Failed to send notification: {e}")
                    
                    raise delete_error
            
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                logging.error(f"BigQuery insert errors: {errors}")
                
                # Notify about BigQuery insert errors
                try:
                    notify_error(
                        title="BigQuery Insert Failed",
                        message=f"Failed to insert active players data into BigQuery",
                        details={
                            'error_count': len(result),
                            'sample_errors': [str(e) for e in result[:3]],
                            'rows_attempted': len(rows),
                            'table': self.table_name,
                            'processor': 'BDL Active Players'
                        },
                        processor_name="BDL Active Players Processor"
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
            else:
                logging.info(f"Successfully inserted {len(rows)} rows into {table_id}")
                
                # Log validation summary
                total_issues = sum(1 for row in rows if row['has_validation_issues'])
                missing_nba_com = sum(1 for row in rows if row['validation_status'] == 'missing_nba_com')
                team_mismatches = sum(1 for row in rows if row['validation_status'] == 'team_mismatch')
                
                logging.info(f"Validation summary: {total_issues}/{len(rows)} players have validation issues")
                
                # Notify about high validation issue rate
                validation_issue_rate = (total_issues / len(rows)) * 100 if rows else 0
                if validation_issue_rate > 20:  # More than 20% have issues
                    try:
                        notify_warning(
                            title="High Validation Issue Rate",
                            message=f"{validation_issue_rate:.1f}% of active players have validation issues",
                            details={
                                'total_players': len(rows),
                                'total_issues': total_issues,
                                'missing_nba_com': missing_nba_com,
                                'team_mismatches': team_mismatches,
                                'issue_rate_pct': round(validation_issue_rate, 1),
                                'processor': 'BDL Active Players'
                            }
                        )
                    except Exception as e:
                        logging.warning(f"Failed to send notification: {e}")
                
                # Send success notification
                try:
                    notify_info(
                        title="BDL Active Players Processing Complete",
                        message=f"Successfully processed {len(rows)} active players",
                        details={
                            'total_players': len(rows),
                            'validation_issues': total_issues,
                            'missing_from_nba_com': missing_nba_com,
                            'team_mismatches': team_mismatches,
                            'validated_clean': len(rows) - total_issues,
                            'table': self.table_name,
                            'processor': 'BDL Active Players'
                        }
                    )
                except Exception as e:
                    logging.warning(f"Failed to send notification: {e}")
                    
        except Exception as e:
            errors.append(str(e))
            logging.error(f"Error loading data: {e}")
            
            # Notify about general processing error
            try:
                notify_error(
                    title="BDL Active Players Processing Failed",
                    message=f"Unexpected error during active players processing: {str(e)}",
                    details={
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'rows_attempted': len(rows),
                        'processor': 'BDL Active Players'
                    },
                    processor_name="BDL Active Players Processor"
                )
            except Exception as notify_ex:
                logging.warning(f"Failed to send notification: {notify_ex}")
        
        return {'rows_processed': len(rows) if not errors else 0, 'errors': errors}