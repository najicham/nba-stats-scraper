#!/usr/bin/env python3
"""
File: processors/nbacom/nbac_gamebook_processor.py

Process NBA.com gamebook data (box scores with DNP/inactive players) for BigQuery storage.
Updated for optimized schema with enhanced name resolution tracking and data quality monitoring.

Key Features:
- Team mapping fixes (BKN->BRK, PHX->PHO, CHA->CHO)  
- Suffix handling (Holmes II -> Holmes)
- Complete resolution attempt logging
- Data quality indicators and flags
- Enhanced audit trail
- DEBUG LOGGING for cache resolution issues
"""

import json
import logging
import re
import os
import uuid
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from google.cloud import bigquery
from shared.utils.player_name_normalizer import normalize_name_for_lookup, extract_suffix

# Support both module execution and direct execution
try:
    # Module execution: python -m processors.nbacom.nbac_gamebook_processor
    from ..processor_base import ProcessorBase
except ImportError:
    # Direct execution: python processors/nbacom/nbac_gamebook_processor.py
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from data_processors.raw.processor_base import ProcessorBase

# Simple team mapper import now that shared/utils/__init__.py is clean
from shared.utils.nba_team_mapper import get_nba_tricode, get_nba_tricode_fuzzy

logger = logging.getLogger(__name__)


class NbacGamebookProcessor(ProcessorBase):
    """Process NBA.com gamebook data with enhanced schema and comprehensive monitoring."""
    
    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.nbac_gamebook_player_stats'
        self.processing_strategy = 'MERGE_UPDATE'
        self.br_roster_cache = {}  # Cache for Basketball Reference rosters
        self.project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
        self.bq_client = bigquery.Client(project=self.project_id)
        
        # Resolution logging
        self.processing_run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
        self.resolution_logs = []  # Batch resolution logs
        self.log_batch_size = 100  # Insert logs in batches
        self.processing_start_time = datetime.now()
        self.files_processed = 0
        
        logger.info(f"Initialized processor with run ID: {self.processing_run_id}")
    
    def set_processing_date_range(self, start_date: str, end_date: str):
        """Set the date range for this processing run (for performance logging)."""
        self.processing_date_range_start = start_date
        self.processing_date_range_end = end_date
        logger.info(f"Set processing date range: {start_date} to {end_date}")

    def log_quality_issue(self, issue_type: str, severity: str, identifier: str, details: Dict):
        """Log data quality issues for review."""
        logger.warning(f"Quality issue [{severity}] {issue_type}: {identifier} - {details}")
        
    def load_br_rosters_for_season(self, season_year: int) -> None:
        """Cache Basketball Reference rosters for a season to resolve inactive player names."""
        if season_year in self.br_roster_cache:
            logger.info(f"Season {season_year} already in cache with {len(self.br_roster_cache[season_year])} entries")
            return
            
        query = f"""
        SELECT DISTINCT
            team_abbrev,
            player_last_name,
            player_full_name,
            player_lookup
        FROM `nba_raw.br_rosters_current`
        WHERE season_year = {season_year}
        """
        
        try:
            logger.info(f"=== CACHE LOADING START for season {season_year} ===")
            results = self.bq_client.query(query).to_dataframe()
            logger.info(f"Query returned {len(results)} rows, columns: {results.columns.tolist()}")
            
            if results.empty:
                logger.warning(f"No roster data found for season {season_year}")
                self.br_roster_cache[season_year] = {}
                return
            
            # Check for Charlie Brown Jr specifically
            brown_players = results[
                (results['team_abbrev'] == 'NYK') & 
                (results['player_last_name'] == 'Brown')
            ]
            logger.info(f"Found {len(brown_players)} Brown players on NYK: {brown_players['player_full_name'].tolist()}")
            
            # Build lookup: {(team, last_name): [list of players]}
            roster_lookup = defaultdict(list)
            brown_entries_added = 0
            total_entries_added = 0
            
            for idx, row in results.iterrows():
                # Check for NaN/None values that could break things
                team_abbrev = row['team_abbrev']
                player_last_name = row['player_last_name']
                
                if pd.isna(team_abbrev) or pd.isna(player_last_name):
                    logger.warning(f"Skipping row {idx} due to NaN values: team={team_abbrev}, last_name={player_last_name}")
                    continue
                
                # Build cache key
                key = (team_abbrev, player_last_name.lower())
                roster_lookup[key].append({
                    'full_name': row['player_full_name'],
                    'lookup': row['player_lookup']
                })
                total_entries_added += 1
                
                # Track Brown entries specifically
                if team_abbrev == 'NYK' and 'brown' in player_last_name.lower():
                    brown_entries_added += 1
                    logger.info(f"Added Brown player to cache: key={key}, name={row['player_full_name']}")
                    logger.info(f"  Full row data: {row.to_dict()}")
            
            # Store the cache
            self.br_roster_cache[season_year] = roster_lookup
            
            # Verify the cache was built correctly
            nyk_brown_key = ('NYK', 'brown')
            nyk_brown_matches = roster_lookup.get(nyk_brown_key, [])
            
            logger.info(f"=== CACHE BUILDING COMPLETE ===")
            logger.info(f"  Total DB rows processed: {len(results)}")
            logger.info(f"  Total cache entries added: {total_entries_added}")
            logger.info(f"  Unique cache keys: {len(roster_lookup)}")
            logger.info(f"  Brown entries added: {brown_entries_added}")
            logger.info(f"  NYK Brown key {nyk_brown_key} has {len(nyk_brown_matches)} matches")
            logger.info(f"  NYK Brown matches: {[m['full_name'] for m in nyk_brown_matches]}")
            
            # Show sample of cache keys for debugging
            sample_keys = list(roster_lookup.keys())[:10]
            logger.info(f"Sample cache keys: {sample_keys}")
            
            # Show all NYK keys for debugging
            nyk_keys = [k for k in roster_lookup.keys() if k[0] == 'NYK']
            logger.info(f"All NYK keys in cache ({len(nyk_keys)}): {nyk_keys}")
            
            # Double-check with direct lookup
            post_cache_lookup = self.br_roster_cache[season_year].get(nyk_brown_key, [])
            logger.info(f"Post-cache direct lookup for {nyk_brown_key}: {len(post_cache_lookup)} matches")
            if post_cache_lookup:
                logger.info(f"  Post-cache matches: {[m['full_name'] for m in post_cache_lookup]}")
            
            logger.info(f"=== CACHE LOADING END ===")
            
        except Exception as e:
            logger.error(f"CRITICAL ERROR loading BR rosters for {season_year}: {e}")
            logger.error(f"Query was: {query}")
            # Don't set empty cache on error - let it fail loudly
            raise e
    
    def log_resolution_attempt(self, original_name: str, team_abbr: str, season_year: int,
                             resolution_status: str, game_id: str, game_date: str,
                             player_status: str = None, resolved_name: str = None, 
                             method: str = None, confidence: float = None, 
                             matches_found: int = 0, potential_matches: List = None, 
                             error_details: str = None, source_file_path: str = None):
        """Log resolution attempt with comprehensive context."""
        
        log_entry = {
            'processing_run_id': self.processing_run_id,
            'processing_timestamp': datetime.now().isoformat(),
            'original_name': original_name,
            'team_abbr': team_abbr,
            'season_year': season_year,
            'resolution_status': resolution_status,
            'resolution_method': method,
            'confidence_score': confidence,
            'game_id': game_id,
            'game_date': game_date,
            'player_status': player_status,
            'resolved_name': resolved_name,
            'resolved_lookup': self.normalize_name(resolved_name) if resolved_name else None,
            'br_team_abbr_used': self.map_team_to_br_code(team_abbr),
            'roster_matches_found': matches_found,
            'potential_matches': str(potential_matches) if potential_matches else None,
            'error_details': error_details,
            'source_file_path': source_file_path,
            'processed_at': datetime.now().isoformat()
        }
        
        self.resolution_logs.append(log_entry)
        
        # Batch insert when we hit the batch size
        if len(self.resolution_logs) >= self.log_batch_size:
            self.flush_resolution_logs()

    def flush_resolution_logs(self):
        """Insert batched resolution logs to BigQuery."""
        if not self.resolution_logs:
            return
        
        try:
            table_id = f"{self.project_id}.nba_processing.name_resolution_log"
            errors = self.bq_client.insert_rows_json(table_id, self.resolution_logs)
            
            if errors:
                logger.error(f"Failed to insert resolution logs: {errors}")
            else:
                logger.info(f"Inserted {len(self.resolution_logs)} resolution logs")
            
            # Clear the batch
            self.resolution_logs = []
            
        except Exception as e:
            logger.error(f"Error flushing resolution logs: {e}")

    def log_processing_performance(self, date_range_start: str = None, date_range_end: str = None):
        """Log overall processing performance summary with enhanced metrics - FIXED VERSION."""
        
        try:
            end_time = datetime.now()

            # Use stored date range if not provided
            if not date_range_start and hasattr(self, 'processing_date_range_start'):
                date_range_start = self.processing_date_range_start
            if not date_range_end and hasattr(self, 'processing_date_range_end'):
                date_range_end = self.processing_date_range_end
            
            # Query the actual database for accurate stats instead of relying on in-memory logs
            stats_query = f"""
            SELECT 
                player_status,
                name_resolution_status,
                name_resolution_method,
                COUNT(*) as count
            FROM `{self.project_id}.{self.table_name}`
            WHERE processed_by_run_id = '{self.processing_run_id}'
            GROUP BY player_status, name_resolution_status, name_resolution_method
            ORDER BY player_status, name_resolution_status
            """
            
            try:
                stats_results = self.bq_client.query(stats_query).to_dataframe()
                logger.info(f"Retrieved {len(stats_results)} stat groups for performance calculation")
                
                # Initialize counters
                resolution_stats = {
                    'resolved': 0, 'not_found': 0, 'multiple_matches': 0, 'original': 0, 'error': 0,
                    'team_mapped': 0, 'suffix_handled': 0, 'direct_lookup': 0,
                    'inactive_total': 0, 'dnp_total': 0, 'active_total': 0,
                    'injury_database_resolved': 0, 'br_fallback_resolved': 0
                }
                
                # Process the results
                for _, row in stats_results.iterrows():
                    player_status = row['player_status']
                    resolution_status = row['name_resolution_status']
                    method = row['name_resolution_method'] or ''
                    count = row['count']
                    
                    # Count by player status
                    if player_status == 'inactive':
                        resolution_stats['inactive_total'] += count
                    elif player_status == 'dnp':
                        resolution_stats['dnp_total'] += count
                    elif player_status == 'active':
                        resolution_stats['active_total'] += count
                    
                    # Count by resolution status (only for inactive/dnp players that need resolution)
                    if player_status in ['inactive', 'dnp']:
                        if resolution_status in resolution_stats:
                            resolution_stats[resolution_status] += count
                    
                    # Count by method
                    if 'team_mapped' in method:
                        resolution_stats['team_mapped'] += count
                    if 'suffix_handled' in method:
                        resolution_stats['suffix_handled'] += count
                    if method == 'direct_lookup':
                        resolution_stats['direct_lookup'] += count
                    if 'injury_database' in method:
                        resolution_stats['injury_database_resolved'] += count
                    if method in ['auto_exact', 'pending_review']:
                        resolution_stats['injury_database_resolved'] += count
                
                # Calculate resolution rate for players that needed resolution (inactive players primarily)
                inactive_needing_resolution = resolution_stats['inactive_total']
                inactive_resolved = sum([
                    resolution_stats['resolved'],
                    resolution_stats['injury_database_resolved']
                ])
                
                # Avoid double counting - use max of the two counts
                inactive_resolved = max(resolution_stats['resolved'], resolution_stats['injury_database_resolved'])
                
                resolution_rate = inactive_resolved / inactive_needing_resolution if inactive_needing_resolution > 0 else 0
                
                logger.info(f"Performance calculation:")
                logger.info(f"  Total players processed: {resolution_stats['active_total'] + resolution_stats['inactive_total'] + resolution_stats['dnp_total']}")
                logger.info(f"  Active: {resolution_stats['active_total']}, Inactive: {resolution_stats['inactive_total']}, DNP: {resolution_stats['dnp_total']}")
                logger.info(f"  Inactive resolved: {inactive_resolved}/{inactive_needing_resolution} = {resolution_rate:.2%}")
                
            except Exception as e:
                logger.error(f"Error querying performance stats: {e}")
                # Fallback to original method if database query fails
                logger.warning("Falling back to in-memory resolution logs for performance calculation")
                
                resolution_stats = {
                    'resolved': 0, 'not_found': 0, 'multiple_matches': 0, 'original': 0, 'error': 0,
                    'team_mapped': 0, 'suffix_handled': 0, 'direct_lookup': 0,
                    'inactive_total': 0, 'dnp_total': 0, 'active_total': 0,
                    'injury_database_resolved': 0
                }
                
                for log_entry in self.resolution_logs:
                    status = log_entry['resolution_status']
                    method = log_entry.get('resolution_method', '')
                    player_status = log_entry.get('player_status', '')
                    
                    resolution_stats[status] = resolution_stats.get(status, 0) + 1
                    
                    if player_status == 'inactive':
                        resolution_stats['inactive_total'] += 1
                    elif player_status == 'dnp':
                        resolution_stats['dnp_total'] += 1
                
                inactive_needing_resolution = resolution_stats['inactive_total']
                inactive_resolved = resolution_stats['resolved']
                resolution_rate = inactive_resolved / inactive_needing_resolution if inactive_needing_resolution > 0 else 0

            # Create performance summary
            performance_summary = {
                'processing_run_id': self.processing_run_id,
                'processing_timestamp': self.processing_start_time.isoformat(),
                'total_players_processed': resolution_stats['active_total'] + resolution_stats['inactive_total'] + resolution_stats['dnp_total'],
                'active_players': resolution_stats['active_total'],
                'total_inactive_players': resolution_stats['inactive_total'],
                'total_dnp_players': resolution_stats['dnp_total'],
                'resolved_count': resolution_stats['resolved'],
                'not_found_count': resolution_stats['not_found'],
                'multiple_matches_count': resolution_stats['multiple_matches'],
                'original_count': resolution_stats['original'],
                'error_count': resolution_stats['error'],
                'team_mapping_fixes': resolution_stats['team_mapped'],
                'suffix_handling_fixes': resolution_stats['suffix_handled'],
                'direct_lookup_successes': resolution_stats['direct_lookup'],
                'injury_database_resolutions': resolution_stats['injury_database_resolved'],
                'resolution_rate': resolution_rate,
                'inactive_resolution_rate': resolution_rate,  # More specific metric
                'improvement_from_baseline': None,
                'date_range_start': date_range_start,
                'date_range_end': date_range_end,
                'files_processed': self.files_processed,
                'processing_duration_minutes': (end_time - self.processing_start_time).total_seconds() / 60,
                'created_at': datetime.now().isoformat()
            }
            
            # Log to BigQuery
            table_id = f"{self.project_id}.nba_processing.resolution_performance"
            errors = self.bq_client.insert_rows_json(table_id, [performance_summary])
            
            if errors:
                logger.error(f"Failed to log performance summary: {errors}")
            else:
                logger.info(f"Logged performance summary for run {self.processing_run_id}")
                logger.info(f"Total players processed: {performance_summary['total_players_processed']}")
                logger.info(f"Active: {resolution_stats['active_total']}, Inactive: {resolution_stats['inactive_total']}, DNP: {resolution_stats['dnp_total']}")
                logger.info(f"Inactive resolution rate: {resolution_rate:.2%} ({inactive_resolved}/{inactive_needing_resolution})")
                
                if resolution_stats['injury_database_resolved'] > 0:
                    logger.info(f"Injury database resolutions: {resolution_stats['injury_database_resolved']}")
                    
        except Exception as e:
            logger.error(f"Error logging performance: {e}")

    def finalize_processing(self):
        """Call this at the end of processing to flush remaining logs."""
        # Flush any remaining resolution logs
        self.flush_resolution_logs()
        
        # Log final performance summary
        self.log_processing_performance()
        
        logger.info(f"Processing run {self.processing_run_id} completed")

    
    def normalize_name(self, name: str) -> str:
        """Create normalized lookup key from name using shared utility."""
        return normalize_name_for_lookup(name)
    
    def handle_suffix_names(self, name: str) -> str:
        """Handle names with suffixes using shared utility."""
        base_name, _ = extract_suffix(name)
        return base_name
    
    def normalize_team_name(self, team_name: str) -> str:
        """Aggressively normalize team name for consistent mapping."""
        if not team_name:
            return ""
        
        # Convert to lowercase and strip whitespace
        normalized = team_name.lower().strip()
        
        # Handle known aliases first (before aggressive normalization)
        normalized = normalized.replace("la clippers", "los angeles clippers")
        normalized = normalized.replace("la lakers", "los angeles lakers")
        
        # Aggressive normalization: remove all non-alphanumeric characters
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        
        return normalized
    
    def map_team_to_br_code(self, team_abbr: str) -> str:
        """Map NBA.com team abbreviations to Basketball Reference codes."""
        if not team_abbr:
            return ""
            
        mapping = {
            'BKN': 'BRK',  # Brooklyn Nets
            'PHX': 'PHO',  # Phoenix Suns  
            'CHA': 'CHO',  # Charlotte Hornets
        }
        return mapping.get(team_abbr, team_abbr)

    def generate_quality_flags(self, resolution_status: str, method: str, 
                             team_abbr: str, br_team_abbr: str, 
                             original_name: str, lookup_name: str) -> List[str]:
        """Generate data quality flags for tracking resolution methods."""
        flags = []
        
        if team_abbr != br_team_abbr:
            flags.append('team_mapped')
        
        if original_name != lookup_name:
            flags.append('suffix_handled')
            
        if resolution_status == 'resolved':
            flags.append('name_resolved')
        elif resolution_status == 'multiple_matches':
            flags.append('multiple_candidates')
        elif resolution_status == 'not_found':
            flags.append('no_roster_match')
            
        if method and 'exception' in method:
            flags.append('processing_error')
            
        return flags

    def resolve_inactive_player(self, last_name: str, team_abbr: str, season_year: int,
                              game_id: str = None, game_date: str = None, 
                              player_status: str = None, source_file_path: str = None) -> Tuple[str, str, str, List[str], bool]:
        """Resolve inactive player with comprehensive logging and quality tracking."""
        
        # Add debug logging for Charlie Brown Jr. specifically
        is_debug_case = 'brown' in last_name.lower() and team_abbr == 'NYK'
        
        if is_debug_case:
            logger.info(f"=== RESOLVE DEBUG START ===")
            logger.info(f"Input: last_name='{last_name}', team_abbr='{team_abbr}', season_year={season_year}")
        
        try:
            # Load roster cache if needed
            self.load_br_rosters_for_season(season_year)
            
            if season_year not in self.br_roster_cache:
                if is_debug_case:
                    logger.error(f"CACHE MISS: Season {season_year} not in cache after loading")
                if game_id and game_date:
                    self.log_resolution_attempt(
                        last_name, team_abbr, season_year, 'not_found', game_id, game_date,
                        player_status=player_status, method='no_roster_cache', confidence=0.0, 
                        matches_found=0, error_details=f"No roster cache for season {season_year}",
                        source_file_path=source_file_path
                    )
                return last_name, self.normalize_name(last_name), 'not_found', ['no_roster_data'], True
            
            if is_debug_case:
                logger.info(f"Cache hit: Season {season_year} has {len(self.br_roster_cache[season_year])} entries")
            
            # Handle team abbreviation mapping
            br_team_abbr = self.map_team_to_br_code(team_abbr)
            was_team_mapped = br_team_abbr != team_abbr
            
            if is_debug_case:
                logger.info(f"Team mapping: '{team_abbr}' -> '{br_team_abbr}' (mapped: {was_team_mapped})")
            
            # Handle suffix removal
            lookup_name = self.handle_suffix_names(last_name)
            was_suffix_handled = lookup_name != last_name
            
            if is_debug_case:
                logger.info(f"Suffix handling: '{last_name}' -> '{lookup_name}' (handled: {was_suffix_handled})")
            
            # Determine method
            if was_team_mapped and was_suffix_handled:
                method = 'team_mapped_suffix_handled'
            elif was_team_mapped:
                method = 'team_mapped'
            elif was_suffix_handled:
                method = 'suffix_handled'
            else:
                method = 'direct_lookup'
            
            # Look up in roster cache
            roster_key = (br_team_abbr, lookup_name.lower())
            
            if is_debug_case:
                logger.info(f"Lookup key: {roster_key}")
                
                # Debug cache state
                cache_keys = list(self.br_roster_cache[season_year].keys())
                logger.info(f"Total cache keys: {len(cache_keys)}")
                
                # Look for similar keys
                similar_keys = [k for k in cache_keys if k[0] == br_team_abbr]
                logger.info(f"Keys for team {br_team_abbr}: {similar_keys}")
                
                brown_keys = [k for k in cache_keys if 'brown' in str(k[1]).lower()]
                logger.info(f"Keys containing 'brown': {brown_keys}")
                
                # Check exact match
                exact_key_exists = roster_key in self.br_roster_cache[season_year]
                logger.info(f"Exact key {roster_key} exists in cache: {exact_key_exists}")
            
            matches = self.br_roster_cache[season_year].get(roster_key, [])
            
            if is_debug_case:
                logger.info(f"Lookup result: {len(matches)} matches found")
                if matches:
                    logger.info(f"Matches: {[m['full_name'] for m in matches]}")
                else:
                    logger.warning(f"NO MATCHES for key {roster_key}")
                    # Try to debug what went wrong
                    team_brown_keys = [k for k in cache_keys if k[0] == br_team_abbr and 'brown' in k[1]]
                    logger.info(f"Brown players on {br_team_abbr}: {team_brown_keys}")
                logger.info(f"=== RESOLVE DEBUG END ===")
            
            # Generate quality flags
            quality_flags = self.generate_quality_flags(
                'resolved' if len(matches) == 1 else 'multiple_matches' if len(matches) > 1 else 'not_found',
                method, team_abbr, br_team_abbr, last_name, lookup_name
            )
            
            if len(matches) == 1:
                # Single match found
                resolved_name = matches[0]['full_name']
                if game_id and game_date:
                    self.log_resolution_attempt(
                        last_name, team_abbr, season_year, 'resolved', game_id, game_date,
                        player_status=player_status, resolved_name=resolved_name, method=method, 
                        confidence=1.0, matches_found=1, potential_matches=[matches[0]],
                        source_file_path=source_file_path
                    )
                return resolved_name, matches[0]['lookup'], 'resolved', quality_flags, False
                
            elif len(matches) > 1:
                # Multiple matches - needs manual review
                if game_id and game_date:
                    self.log_resolution_attempt(
                        last_name, team_abbr, season_year, 'multiple_matches', game_id, game_date,
                        player_status=player_status, method=method, confidence=0.6, 
                        matches_found=len(matches), potential_matches=matches,
                        source_file_path=source_file_path
                    )
                return last_name, self.normalize_name(last_name), 'multiple_matches', quality_flags, True
                
            else:
                # No match found
                requires_review = player_status == 'inactive'  # Injured players need more attention
                if game_id and game_date:
                    self.log_resolution_attempt(
                        last_name, team_abbr, season_year, 'not_found', game_id, game_date,
                        player_status=player_status, method=method, confidence=0.0, 
                        matches_found=0, error_details=f"No roster match for '{lookup_name}' on {br_team_abbr}",
                        source_file_path=source_file_path
                    )
                return last_name, self.normalize_name(last_name), 'not_found', quality_flags, requires_review
                
        except Exception as e:
            # Log the error
            if game_id and game_date:
                self.log_resolution_attempt(
                    last_name, team_abbr, season_year, 'error', game_id, game_date,
                    player_status=player_status, method='exception', confidence=0.0, 
                    matches_found=0, error_details=str(e), source_file_path=source_file_path
                )
            logger.error(f"Error resolving {last_name}: {e}")
            if is_debug_case:
                logger.info(f"=== RESOLVE DEBUG END (ERROR) ===")
            return last_name, self.normalize_name(last_name), 'not_found', ['processing_error'], True

    def get_roster_matches(self, last_name: str, team_abbr: str, season_year: int) -> List[Dict]:
        """Get potential roster matches for enhanced resolution."""
        # Load roster cache if needed
        self.load_br_rosters_for_season(season_year)
        
        if season_year not in self.br_roster_cache:
            return []
        
        # Fix team abbreviation mapping
        br_team_abbr = self.map_team_to_br_code(team_abbr)
        
        # Look up in roster cache
        roster_key = (br_team_abbr, last_name.lower())
        return self.br_roster_cache[season_year].get(roster_key, [])
    
    def extract_game_info(self, file_path: str, data: Dict) -> Dict:
        """Extract game metadata from file path and data."""
        # Path format: nba-com/gamebooks-data/2021-10-19/20211019-BKNMIL/20250827_234400.json
        path_parts = file_path.split('/')
        date_str = path_parts[-3]  # 2021-10-19
        game_code = path_parts[-2]  # 20211019-BKNMIL
        
        # Parse game code
        date_part = game_code[:8]  # 20211019
        teams_part = game_code[9:]  # BKNMIL
        
        # Extract teams (first 3 chars = away, last 3 = home)
        away_team = teams_part[:3] if len(teams_part) >= 6 else None
        home_team = teams_part[3:6] if len(teams_part) >= 6 else None
        
        # Build game_id in standard format
        game_id = f"{date_part}_{away_team}_{home_team}" if away_team and home_team else game_code
        
        # Extract season year (Oct-Dec = current year, Jan-Jun = previous year)
        game_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        month = game_date.month
        season_year = game_date.year if month >= 10 else game_date.year - 1
        
        return {
            'game_id': game_id,
            'game_code': data.get('game_code', game_code),
            'game_date': game_date,
            'season_year': season_year,
            'home_team_abbr': home_team,
            'away_team_abbr': away_team
        }
    
    def validate_data(self, data: Dict) -> List[str]:
        """Validate the gamebook JSON structure."""
        errors = []
        
        # Check for required fields
        if 'game_code' not in data:
            errors.append("Missing 'game_code' field")
        
        # Check for at least one player array
        player_arrays = ['active_players', 'dnp_players', 'inactive_players']
        if not any(arr in data for arr in player_arrays):
            errors.append(f"No player arrays found. Expected at least one of: {player_arrays}")
        
        return errors
    
    def convert_minutes(self, minutes_str: str) -> Optional[float]:
        """Convert minutes string (MM:SS) to decimal."""
        if not minutes_str or minutes_str == '-':
            return None
        try:
            parts = minutes_str.split(':')
            if len(parts) == 2:
                return float(parts[0]) + float(parts[1]) / 60
        except (ValueError, AttributeError):
            pass
        return None
    
    def get_team_abbreviation(self, team_name: str) -> Optional[str]:
        """Map team name to NBA tricode using shared utility."""
        if not team_name:
            return None
        
        # Try exact match first (fast)
        result = get_nba_tricode(team_name)
        if result:
            return result
        
        # Try fuzzy match (robust)
        result = get_nba_tricode_fuzzy(team_name, min_confidence=80)
        if result:
            return result
        
        # Log unmapped for debugging
        logger.warning(f"Could not map team name: '{team_name}'")
        return None
    
    def process_active_player(self, player: Dict, game_info: Dict, source_file_path: str) -> Dict:
        """Process an active player with stats."""
        stats = player.get('stats', {})
        
        # Determine team abbreviation
        team_abbr = None
        if player.get('team'):
            # Map full team name to abbreviation using aggressive normalization
            team_abbr = self.get_team_abbreviation(player['team'])
        
        return {
            'game_id': game_info['game_id'],
            'game_code': game_info['game_code'],
            'game_date': game_info['game_date'].isoformat() if hasattr(game_info['game_date'], 'isoformat') else game_info['game_date'],
            'season_year': game_info['season_year'],
            'home_team_abbr': game_info['home_team_abbr'],
            'away_team_abbr': game_info['away_team_abbr'],
            'player_name': player.get('name'),
            'player_name_original': player.get('name'),
            'player_lookup': self.normalize_name(player.get('name', '')),
            'team_abbr': team_abbr,
            'player_status': 'active',
            'dnp_reason': None,
            'name_resolution_status': 'original',
            'name_resolution_confidence': None,
            'name_resolution_method': None,
            'br_team_abbr_used': None,
            # Stats
            'minutes': stats.get('minutes'),
            'minutes_decimal': self.convert_minutes(stats.get('minutes')),
            'points': stats.get('points'),
            'field_goals_made': stats.get('field_goals_made'),
            'field_goals_attempted': stats.get('field_goals_attempted'),
            'field_goal_percentage': stats.get('field_goal_percentage'),
            'three_pointers_made': stats.get('three_pointers_made'),
            'three_pointers_attempted': stats.get('three_pointers_attempted'),
            'three_point_percentage': stats.get('three_point_percentage'),
            'free_throws_made': stats.get('free_throws_made'),
            'free_throws_attempted': stats.get('free_throws_attempted'),
            'free_throw_percentage': stats.get('free_throw_percentage'),
            'offensive_rebounds': stats.get('offensive_rebounds'),
            'defensive_rebounds': stats.get('defensive_rebounds'),
            'total_rebounds': stats.get('rebounds_total', stats.get('rebounds')),
            'assists': stats.get('assists'),
            'steals': stats.get('steals'),
            'blocks': stats.get('blocks'),
            'turnovers': stats.get('turnovers'),
            'personal_fouls': stats.get('fouls', stats.get('personal_fouls')),
            'plus_minus': stats.get('plus_minus'),
            # Processing metadata
            'processed_by_run_id': self.processing_run_id,
            'source_file_path': source_file_path,
            'data_quality_flags': [],
            'requires_manual_review': False
        }
    
    def process_inactive_player(self, player: Dict, game_info: Dict, status: str, 
                              source_file_path: str) -> Dict:
        """Process a DNP or inactive player with enhanced schema support."""
        # Determine team abbreviation
        team_abbr = None
        if player.get('team'):
            team_abbr = self.get_team_abbreviation(player['team'])
        
        # For inactive players, try to resolve full name
        player_name = player.get('name', '')
        player_lookup = self.normalize_name(player_name)
        resolution_status = 'original'
        confidence = None
        method = None
        quality_flags = []
        requires_review = False
        br_team_abbr_used = None
        
        if status == 'inactive' and player_name and team_abbr:
            # Try to resolve the name WITH full context for logging
            resolved_name, resolved_lookup, resolution_status, quality_flags, requires_review = self.resolve_with_injury_database(
                player_name,              # 1st: last_name with suffix
                team_abbr,                # 2nd: team_abbr  
                game_info['season_year'], # 3rd: season_year
                game_info['game_date'].isoformat() if hasattr(game_info['game_date'], 'isoformat') else str(game_info['game_date']),  # 4th: game_date
                reason=player.get('reason', ''),  # keyword: reason
                game_id=game_info['game_id'],     # keyword: game_id
                player_status=status,             # keyword: player_status
                source_file_path=source_file_path # keyword: source_file_path
            )
            
            br_team_abbr_used = self.map_team_to_br_code(team_abbr)
            
            if resolution_status == 'resolved':
                player_name = resolved_name
                player_lookup = resolved_lookup
                confidence = 1.0
                method = 'auto_exact'
            elif resolution_status == 'multiple_matches':
                confidence = 0.6
                method = 'pending_review'
            elif resolution_status == 'not_found':
                confidence = 0.0
                method = 'not_found'
        
        return {
            'game_id': game_info['game_id'],
            'game_code': game_info['game_code'],
            'game_date': game_info['game_date'].isoformat() if hasattr(game_info['game_date'], 'isoformat') else game_info['game_date'],
            'season_year': game_info['season_year'],
            'home_team_abbr': game_info['home_team_abbr'],
            'away_team_abbr': game_info['away_team_abbr'],
            'player_name': player_name,
            'player_name_original': player.get('name'),
            'player_lookup': player_lookup,
            'team_abbr': team_abbr,
            'player_status': status,
            'dnp_reason': player.get('dnp_reason') or player.get('reason'),
            'name_resolution_status': resolution_status,
            'name_resolution_confidence': confidence,
            'name_resolution_method': method,
            'br_team_abbr_used': br_team_abbr_used,
            # All stats are NULL for inactive players
            'minutes': None,
            'minutes_decimal': None,
            'points': None,
            'field_goals_made': None,
            'field_goals_attempted': None,
            'field_goal_percentage': None,
            'three_pointers_made': None,
            'three_pointers_attempted': None,
            'three_point_percentage': None,
            'free_throws_made': None,
            'free_throws_attempted': None,
            'free_throw_percentage': None,
            'offensive_rebounds': None,
            'defensive_rebounds': None,
            'total_rebounds': None,
            'assists': None,
            'steals': None,
            'blocks': None,
            'turnovers': None,
            'personal_fouls': None,
            'plus_minus': None,
            # Processing metadata  
            'processed_by_run_id': self.processing_run_id,
            'source_file_path': source_file_path,
            'data_quality_flags': quality_flags,
            'requires_manual_review': requires_review
        }
    
    def transform_data(self, raw_data: Dict, file_path: str) -> List[Dict]:
        """Transform gamebook data to BigQuery rows."""
        rows = []
        
        # Track file processing
        self.files_processed += 1
        
        # Extract game information
        game_info = self.extract_game_info(file_path, raw_data)
        
        # Process active players
        for player in raw_data.get('active_players', []):
            row = self.process_active_player(player, game_info, file_path)
            rows.append(row)
        
        # Process DNP players with source file context
        for player in raw_data.get('dnp_players', []):
            row = self.process_inactive_player(player, game_info, 'dnp', file_path)
            rows.append(row)
        
        # Process inactive players with source file context
        for player in raw_data.get('inactive_players', []):
            row = self.process_inactive_player(player, game_info, 'inactive', file_path)
            rows.append(row)
        
        logger.info(f"Processed {len(rows)} players from {file_path} (File #{self.files_processed})")
        return rows
    
    def load_data(self, rows: List[Dict], **kwargs) -> Dict:
        """Load data to BigQuery using MERGE_UPDATE strategy."""
        if not rows:
            return {'rows_processed': 0, 'errors': []}
        
        table_id = f"{self.project_id}.{self.table_name}"
        errors = []
        
        try:
            if self.processing_strategy == 'MERGE_UPDATE':
                # For MERGE_UPDATE, we'll delete existing game data first
                game_id = rows[0]['game_id']
                delete_query = f"""
                DELETE FROM `{table_id}`
                WHERE game_id = '{game_id}'
                """
                self.bq_client.query(delete_query).result()
                logger.info(f"Deleted existing data for game {game_id}")
            
            # Insert new rows
            result = self.bq_client.insert_rows_json(table_id, rows)
            if result:
                errors.extend([str(e) for e in result])
                
            # If this is the final batch, finalize processing
            if kwargs.get('is_final_batch', False):
                self.finalize_processing()
                
        except Exception as e:
            errors.append(str(e))
            logger.error(f"Failed to load data: {e}")
        
        return {
            'rows_processed': len(rows) if not errors else 0,
            'errors': errors
        }

    # Legacy methods kept for compatibility
    def resolve_inactive_player_enhanced(self, last_name: str, team_abbr: str, season_year: int) -> Dict:
        """Enhanced name resolution with database integration (legacy compatibility)."""
        resolved_name, resolved_lookup, resolution_status, quality_flags, requires_review = self.resolve_inactive_player(
            last_name, team_abbr, season_year
        )
        
        return {
            'name': resolved_name,
            'lookup': resolved_lookup,
            'status': resolution_status,
            'confidence': 1.0 if resolution_status == 'resolved' else 0.6 if resolution_status == 'multiple_matches' else 0.0,
            'method': 'auto_exact' if resolution_status == 'resolved' else resolution_status
        }

    def get_existing_resolution(self, resolution_id: str) -> Optional[Dict]:
        """Check if resolution already exists in database (stub for future enhancement)."""
        return None

    def create_resolution_record(self, resolution_data: Dict):
        """Insert new resolution record into database (stub for future enhancement)."""
        pass

    def update_resolution_games_count(self, resolution_id: str):
        """Update the count of games affected by this resolution (stub for future enhancement)."""
        pass

    # Data-driven disambiguation without hard-coded player names
    def disambiguate_injury_matches(self, matches_df, gamebook_reason: str, last_name: str) -> dict:
        """Use data-driven heuristics to pick best match from injury database."""
        
        gamebook_reason_lower = gamebook_reason.lower() if gamebook_reason else ""
        
        # Strategy 1: Direct reason keyword matching (data-driven)
        if gamebook_reason_lower:
            for _, match in matches_df.iterrows():
                injury_reason_lower = match['injury_reason'].lower() if match['injury_reason'] else ""
                
                # Match specific injury types
                if 'g league' in gamebook_reason_lower and 'g league' in injury_reason_lower:
                    return match.to_dict()
                if 'two-way' in gamebook_reason_lower and 'two-way' in injury_reason_lower:
                    return match.to_dict()
                if any(keyword in gamebook_reason_lower and keyword in injury_reason_lower 
                    for keyword in ['injury', 'illness', 'strain', 'sprain']):
                    return match.to_dict()
        
        # Strategy 2: Use injury database patterns (data-driven heuristics)
        
        # For G-League/Two-way assignments, prefer players with G-League reasons in injury DB
        if 'g league' in gamebook_reason_lower or 'two-way' in gamebook_reason_lower:
            gleague_matches = matches_df[matches_df['injury_reason'].str.contains('g league|two-way', case=False, na=False)]
            if not gleague_matches.empty:
                return gleague_matches.iloc[0].to_dict()
        
        # For injury reasons, prefer players with injury-related reasons in injury DB  
        if any(keyword in gamebook_reason_lower for keyword in ['injury', 'illness', 'strain', 'sprain']):
            injury_matches = matches_df[matches_df['injury_reason'].str.contains('injury|illness|strain|sprain', case=False, na=False)]
            if not injury_matches.empty:
                return injury_matches.iloc[0].to_dict()
        
        # Strategy 3: Use injury status patterns (data-driven)
        # Players with status "out" are often more established (vs "questionable" for minor issues)
        out_players = matches_df[matches_df['injury_status'] == 'out']
        if len(out_players) == 1:
            return out_players.iloc[0].to_dict()
        
        # Strategy 4: Use confidence scores from injury database (data-driven)
        # Higher confidence scores suggest better data quality for that player
        highest_confidence = matches_df.loc[matches_df['confidence_score'].idxmax()] if 'confidence_score' in matches_df.columns else None
        if highest_confidence is not None:
            return highest_confidence.to_dict()
        
        # Strategy 5: Alphabetical consistency (deterministic fallback)
        # Always pick the first alphabetically to ensure reproducible results
        return matches_df.sort_values('player_full_name').iloc[0].to_dict()

    def resolve_with_injury_database(self, last_name: str, team_abbr: str, season_year: int,
                                    game_date: str, reason: str = None, game_id: str = None,
                                    player_status: str = None, source_file_path: str = None) -> Tuple[str, str, str, List[str], bool]:
        """Resolve player name using injury database integration (data-driven)."""
        
        try:
            # Query injury database for exact game and team match
            injury_query = f"""
            SELECT DISTINCT
                player_full_name,
                player_lookup,
                injury_status,
                reason as injury_reason,
                confidence_score
            FROM `nba_raw.nbac_injury_report`
            WHERE team = '{team_abbr}'
            AND game_date = '{game_date}'
            AND (
                LOWER(player_full_name) LIKE LOWER('%{last_name}%') OR
                LOWER('{last_name}') LIKE LOWER('%' || SPLIT(player_full_name, ' ')[OFFSET(1)] || '%')
            )
            ORDER BY confidence_score DESC
            """
            
            results = self.bq_client.query(injury_query).to_dataframe()
            
            if len(results) == 1:
                # Single match found - highest confidence
                resolved_name = results.iloc[0]['player_full_name']
                confidence = float(results.iloc[0]['confidence_score']) if results.iloc[0]['confidence_score'] else 0.95
                
                if game_id:
                    self.log_resolution_attempt(
                        last_name, team_abbr, season_year, 'resolved', game_id, game_date,
                        player_status=player_status, resolved_name=resolved_name,
                        method='injury_database_single_match', confidence=confidence, matches_found=1,
                        source_file_path=source_file_path
                    )
                return resolved_name, self.normalize_name(resolved_name), 'resolved', ['injury_database_single'], False
            
            elif len(results) > 1:
                # Multiple matches - use data-driven disambiguation
                disambiguation_result = self.disambiguate_injury_matches(results, reason, last_name)
                resolved_name = disambiguation_result['player_full_name']
                
                # Determine confidence based on disambiguation method used
                if reason and any(keyword in reason.lower() for keyword in ['g league', 'two-way', 'injury', 'illness']):
                    confidence = 0.85  # Good confidence when reason helps disambiguation
                    method = 'injury_database_reason_matched'
                else:
                    confidence = 0.70  # Lower confidence when using heuristics
                    method = 'injury_database_heuristic_pick'
                
                if game_id:
                    self.log_resolution_attempt(
                        last_name, team_abbr, season_year, 'resolved', game_id, game_date,
                        player_status=player_status, resolved_name=resolved_name,
                        method=method, confidence=confidence, 
                        matches_found=len(results), potential_matches=results.to_dict('records'),
                        error_details=f"Disambiguated using: {results.columns.tolist()}",
                        source_file_path=source_file_path
                    )
                return resolved_name, self.normalize_name(resolved_name), 'resolved', ['injury_database_disambiguated'], False
            
            else:
                # No injury database matches - fall back to Basketball Reference
                return self.resolve_inactive_player(last_name, team_abbr, season_year, game_id, game_date, player_status, source_file_path)
                
        except Exception as e:
            logger.error(f"Error in injury database resolution for {last_name}: {e}")
            # Fall back to Basketball Reference on error
            return self.resolve_inactive_player(last_name, team_abbr, season_year, game_id, game_date, player_status, source_file_path)
        