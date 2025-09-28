#!/usr/bin/env python3
"""
File: data_processors/reference/player_reference/gamebook_registry_processor.py

Gamebook Registry Processor

Builds the NBA players registry from NBA.com gamebook data.
Refactored version that inherits from base classes for shared functionality.

Three Usage Scenarios:
1. Historical backfill: Process 4 years of gamebook data
2. Nightly updates: Triggered after gamebook processing completes
3. Enhanced name change detection: Optional investigation reporting
"""

import logging
import time
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional
import pandas as pd
from google.cloud import bigquery

from data_processors.reference.base.registry_processor_base import RegistryProcessorBase
from data_processors.reference.base.name_change_detection_mixin import NameChangeDetectionMixin
from data_processors.reference.base.database_strategies import DatabaseStrategiesMixin

logger = logging.getLogger(__name__)


class GamebookRegistryProcessor(RegistryProcessorBase, NameChangeDetectionMixin, DatabaseStrategiesMixin):
    """
    Registry processor for NBA.com gamebook data.
    
    Creates the authoritative player registry by analyzing NBA.com gamebook data:
    - Player game participation statistics
    - Team assignments and season tracking
    - Jersey numbers and positions from Basketball Reference enhancement
    - Enhanced name change detection and investigation reporting
    """
    
    def __init__(self, test_mode: bool = False, strategy: str = "merge", 
                 confirm_full_delete: bool = False,
                 enable_name_change_detection: bool = True):
        super().__init__(test_mode, strategy, confirm_full_delete, enable_name_change_detection)
        
        logger.info("Initialized Gamebook Registry Processor")
    
    def get_gamebook_player_data(self, season_filter: str = None, 
                               team_filter: str = None, 
                               date_range: Tuple[str, str] = None) -> pd.DataFrame:
        """Retrieve NBA.com gamebook player data with optional filters."""
        query_start = time.time()
        logger.info(f"PERF_METRIC: gamebook_query_start season={season_filter} team={team_filter}")
        
        # Build the query
        query = """
        SELECT 
            player_name,
            player_lookup,
            team_abbr,
            season_year,
            game_date,
            game_id,
            player_status,
            name_resolution_status,
            COUNT(*) as game_appearances
        FROM `{project}.nba_raw.nbac_gamebook_player_stats`
        WHERE player_name IS NOT NULL 
        AND team_abbr IS NOT NULL
        AND season_year IS NOT NULL
        """.format(project=self.project_id)
        
        query_params = []
        
        # Add filters
        if season_filter:
            season_year = int(season_filter.split('-')[0])
            query += " AND season_year = @season_year"
            query_params.append(bigquery.ScalarQueryParameter("season_year", "INT64", season_year))
        
        if team_filter:
            query += " AND team_abbr = @team_abbr"
            query_params.append(bigquery.ScalarQueryParameter("team_abbr", "STRING", team_filter))
            
        if date_range:
            query += " AND game_date BETWEEN @start_date AND @end_date"
            query_params.extend([
                bigquery.ScalarQueryParameter("start_date", "DATE", date_range[0]),
                bigquery.ScalarQueryParameter("end_date", "DATE", date_range[1])
            ])
        
        query += """
        GROUP BY 
            player_name, player_lookup, team_abbr, season_year, 
            game_date, game_id, player_status, name_resolution_status
        ORDER BY season_year, team_abbr, player_name
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=query_params)
        
        try:
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            logger.info(f"Retrieved {len(results)} player-game records from gamebook data")
            
            query_duration = time.time() - query_start
            logger.info(f"PERF_METRIC: gamebook_query_complete duration={query_duration:.3f}s rows_returned={len(results)}")
            
            return results
            
        except Exception as e:
            logger.error(f"Error querying gamebook data: {e}")
            raise e
    
    def get_roster_enhancement_data(self, season_filter: str = None, 
                                  season_years_filter: Tuple[int, int] = None) -> Dict[Tuple[str, str], Dict]:
        """Get jersey numbers and positions from Basketball Reference roster data."""
        logger.info("Loading roster enhancement data from Basketball Reference...")
        
        try:
            # Import team mapper with fallback
            try:
                from shared.utils.nba_team_mapper import nba_team_mapper
                logger.info("Successfully imported nba_team_mapper")
            except ImportError as e:
                logger.warning(f"Could not import nba_team_mapper: {e}")
                # Fallback mapping
                BR_TO_NBA_MAPPING = {
                    'BRK': 'BKN',  # Brooklyn
                    'CHO': 'CHA',  # Charlotte  
                    'PHO': 'PHX'   # Phoenix
                }
                nba_team_mapper = None
                logger.info("Using fallback hardcoded team mapping")
            
            # Query Basketball Reference with team codes
            query = """
            SELECT DISTINCT
                team_abbrev as br_team_abbr,
                player_lookup,
                player_full_name as original_name,
                jersey_number,
                position,
                season_year
            FROM `{project}.nba_raw.br_rosters_current`
            WHERE player_lookup IS NOT NULL
            AND team_abbrev IS NOT NULL
            """.format(project=self.project_id)
            
            query_params = []
            
            # Apply filters
            if season_filter:
                season_year = int(season_filter.split('-')[0])
                query += " AND season_year = @season_year"
                query_params.append(bigquery.ScalarQueryParameter("season_year", "INT64", season_year))
                logger.info(f"Filtering Basketball Reference data for season: {season_filter}")
                
            elif season_years_filter:
                start_year, end_year = season_years_filter
                query += " AND season_year BETWEEN @start_season_year AND @end_season_year"
                query_params.extend([
                    bigquery.ScalarQueryParameter("start_season_year", "INT64", start_year),
                    bigquery.ScalarQueryParameter("end_season_year", "INT64", end_year)
                ])
                logger.info(f"Filtering Basketball Reference data to season years: {start_year}-{end_year}")
            
            query += " ORDER BY season_year, team_abbrev, player_lookup"
            
            job_config = bigquery.QueryJobConfig(query_parameters=query_params)
            
            enhancement_start = time.time()
            results = self.bq_client.query(query, job_config=job_config).to_dataframe()
            enhancement_duration = time.time() - enhancement_start
            
            logger.info(f"PERF_METRIC: enhancement_data_duration={enhancement_duration:.3f}s rows_returned={len(results)}")
            logger.info(f"Retrieved {len(results)} roster records from Basketball Reference")
            
            if not results.empty:
                season_years = results['season_year'].unique()
                logger.info(f"Basketball Reference data contains season years: {sorted(season_years)}")
            
            # Build lookup dict with NBA team code mapping
            enhancement_data = {}
            mapped_count = 0
            unmapped_teams = set()
            team_mapping_log = {}
            
            for _, row in results.iterrows():
                br_team_abbr = row['br_team_abbr']
                nba_team_abbr = None
                
                # Apply team mapping
                if nba_team_mapper:
                    for team in nba_team_mapper.teams_data:
                        if team.br_tricode == br_team_abbr:
                            nba_team_abbr = team.nba_tricode
                            if br_team_abbr != nba_team_abbr:
                                if br_team_abbr not in team_mapping_log:
                                    logger.info(f"Team mapping: {br_team_abbr} → {nba_team_abbr}")
                                    team_mapping_log[br_team_abbr] = nba_team_abbr
                                mapped_count += 1
                            break
                else:
                    # Use hardcoded fallback mapping
                    nba_team_abbr = BR_TO_NBA_MAPPING.get(br_team_abbr, br_team_abbr)
                    if br_team_abbr != nba_team_abbr:
                        if br_team_abbr not in team_mapping_log:
                            logger.info(f"Fallback team mapping: {br_team_abbr} → {nba_team_abbr}")
                            team_mapping_log[br_team_abbr] = nba_team_abbr
                        mapped_count += 1
                
                if nba_team_abbr:
                    key = (nba_team_abbr, row['player_lookup'])
                    
                    if key in enhancement_data:
                        logger.warning(f"Overwriting enhancement data for {key}")
                    
                    enhancement_data[key] = {
                        'original_name': row['original_name'],
                        'jersey_number': row['jersey_number'] if pd.notna(row['jersey_number']) else None,
                        'position': row['position'] if pd.notna(row['position']) else None,
                        'season_year': row['season_year']
                    }
                else:
                    unmapped_teams.add(br_team_abbr)
            
            logger.info(f"Loaded enhancement data for {len(enhancement_data)} player-team combinations")
            if mapped_count > 0:
                logger.info(f"Applied team mapping to {mapped_count} records")
            if unmapped_teams:
                logger.warning(f"Unmapped team codes: {sorted(unmapped_teams)}")
            
            return enhancement_data
            
        except Exception as e:
            logger.error(f"Error loading roster enhancement data: {e}")
            return {}

    def _resolve_enhancement_via_alias(self, player_lookup: str, team_abbr: str, 
                                     enhancement_data: Dict) -> Tuple[Optional[Dict], bool]:
        """Attempt to resolve enhancement data via alias lookup."""
        
        # Direct lookup first
        direct_key = (team_abbr, player_lookup)
        if direct_key in enhancement_data:
            return enhancement_data[direct_key], False
        
        # Try alias resolution
        alias_query = f"""
        SELECT a.alias_lookup as br_alias_lookup
        FROM `{self.project_id}.{self.alias_table_name}` a
        WHERE a.nba_canonical_lookup = @canonical_lookup
        AND a.is_active = TRUE
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("canonical_lookup", "STRING", player_lookup),
        ])
        
        try:
            results = self.bq_client.query(alias_query, job_config=job_config).to_dataframe()
            
            if not results.empty:
                br_alias_lookup = results.iloc[0]['br_alias_lookup']
                br_key = (team_abbr, br_alias_lookup)
                
                if br_key in enhancement_data:
                    logger.info(f"Enhancement resolved via alias: {player_lookup} → {br_alias_lookup} for {team_abbr}")
                    self.stats['alias_resolutions'] += 1
                    return enhancement_data[br_key], True
                    
            return None, False
            
        except Exception as e:
            logger.warning(f"Error resolving enhancement via alias for {player_lookup}: {e}")
            return None, False

    def aggregate_player_stats(self, gamebook_df: pd.DataFrame, 
                             date_range: Tuple[str, str] = None) -> List[Dict]:
        """Aggregate gamebook data into registry records."""
        logger.info("Aggregating player statistics for registry...")
        
        # Determine season years for Basketball Reference filtering
        season_years_filter = None
        if date_range:
            start_season_year, end_season_year = self.date_to_nba_season_years(date_range)
            season_years_filter = (start_season_year, end_season_year)
        else:
            seasons_in_data = gamebook_df['season_year'].unique()
            if len(seasons_in_data) > 0:
                season_years_filter = (int(seasons_in_data.min()), int(seasons_in_data.max()))
        
        # Get roster enhancement data
        enhancement_data = self.get_roster_enhancement_data(season_years_filter=season_years_filter)
        
        registry_records = []
        
        # Group by logical business key
        groupby_cols = ['player_lookup', 'team_abbr', 'season_year']
        grouped = gamebook_df.groupby(groupby_cols)
        
        # Track which Basketball Reference players we found in gamebook
        found_br_players = set()
        
        for (player_lookup, team_abbr, season_year), group in grouped:
            # Calculate season string
            season_str = self.calculate_season_string(season_year)
            
            # Pick the most common player name variant
            name_counts = group['player_name'].value_counts()
            player_name = name_counts.index[0]
            
            # Calculate game participation stats
            total_appearances = len(group)
            unique_games = group['game_id'].nunique()
            
            # Get date range
            game_dates = pd.to_datetime(group['game_date'])
            first_game = game_dates.min().date()
            last_game = game_dates.max().date()
            
            # Count games by status
            status_counts = group['player_status'].value_counts()
            active_games = status_counts.get('active', 0)
            inactive_games = status_counts.get('inactive', 0)
            dnp_games = status_counts.get('dnp', 0)
            
            # Determine source priority and confidence
            resolution_statuses = group['name_resolution_status'].value_counts()
            if 'original' in resolution_statuses:
                source_priority = 'nba_gamebook'
                confidence_score = 1.0
            elif 'resolved' in resolution_statuses:
                source_priority = 'nba_gamebook_resolved'
                confidence_score = 0.9
            else:
                source_priority = 'nba_gamebook_uncertain'
                confidence_score = 0.7
            
            # Look up enhancement data (with alias resolution)
            enhancement, resolved_via_alias = self._resolve_enhancement_via_alias(
                player_lookup, team_abbr, enhancement_data
            )

            # Track found BR players
            if enhancement:
                if resolved_via_alias:
                    for br_key, br_data in enhancement_data.items():
                        if br_key[0] == team_abbr and br_data == enhancement:
                            found_br_players.add(br_key)
                            break
                else:
                    found_br_players.add((team_abbr, player_lookup))

            if enhancement is None:
                enhancement = {}

            # Resolve universal player ID
            universal_id = self.resolve_universal_player_id(player_lookup)
            
            # Create registry record
            record = {
                'universal_player_id': universal_id,
                'player_name': player_name,
                'player_lookup': player_lookup,
                'team_abbr': team_abbr,
                'season': season_str,
                'first_game_date': first_game,
                'last_game_date': last_game,
                'games_played': active_games,
                'total_appearances': total_appearances,
                'inactive_appearances': inactive_games,
                'dnp_appearances': dnp_games,
                'jersey_number': enhancement.get('jersey_number'),
                'position': enhancement.get('position'),
                'last_roster_update': date.today() if enhancement else None,
                'source_priority': source_priority,
                'confidence_score': confidence_score,
                'created_by': self.processing_run_id,
                'created_at': datetime.now(),
                'processed_at': datetime.now()
            }
            
            # Convert types for BigQuery
            record = self._convert_pandas_types_for_json(record)
            registry_records.append(record)
            
            # Update stats
            self.stats['players_processed'] += 1
            self.stats['seasons_processed'].add(season_str)
            self.stats['teams_processed'].add(team_abbr)
        
        # Handle unresolved Basketball Reference players
        self._handle_unresolved_br_players(enhancement_data, found_br_players)
        
        logger.info(f"Created {len(registry_records)} registry records")
        logger.info(f"Resolved {self.stats['alias_resolutions']} players via alias system")
        
        return registry_records

    def _handle_unresolved_br_players(self, enhancement_data: Dict, found_players: set):
        """Handle unresolved Basketball Reference players with conditional enhancement."""
        if self.enable_name_change_detection:
            return self._handle_unresolved_br_players_enhanced(enhancement_data, found_players)
        else:
            return self._handle_unresolved_br_players_original(enhancement_data, found_players)

    def _handle_unresolved_br_players_original(self, enhancement_data: Dict, found_players: set):
        """Original simple unresolved player handling (for backfill)."""
        unresolved_players = []
        current_datetime = datetime.now()
        current_date = current_datetime.date()
        
        for (team_abbr, player_lookup), enhancement in enhancement_data.items():
            if (team_abbr, player_lookup) not in found_players:
                if self._check_player_aliases(player_lookup, team_abbr):
                    continue
                
                unresolved_record = {
                    'source': 'basketball_reference',
                    'original_name': enhancement.get('original_name', 'Unknown'),
                    'normalized_lookup': player_lookup,
                    'first_seen_date': current_date,
                    'last_seen_date': current_date,
                    'team_abbr': team_abbr,
                    'season': self.calculate_season_string(enhancement.get('season_year', 2024)),
                    'occurrences': 1,
                    'example_games': [],
                    'status': 'pending',
                    'resolution_type': None,
                    'resolved_to_name': None,
                    'notes': f"Found in Basketball Reference roster but no NBA.com gamebook entries",
                    'reviewed_by': None,
                    'reviewed_at': None,
                    'created_at': current_datetime,
                    'processed_at': current_datetime
                }
                unresolved_players.append(unresolved_record)
        
        if unresolved_players:
            self._insert_unresolved_players(unresolved_players)
            self.stats['unresolved_players_found'] = len(unresolved_players)
            logger.info(f"Added {len(unresolved_players)} Basketball Reference players to unresolved queue")

    def _handle_unresolved_br_players_enhanced(self, enhancement_data: Dict, found_players: set):
        """Enhanced unresolved player handling with investigation reports."""
        unresolved_players = []
        investigation_report = {
            'detection_date': date.today().isoformat(),
            'processor_type': 'gamebook_registry_processor',
            'total_br_players': len(enhancement_data),
            'found_in_gamebook': len(found_players),
            'investigations': [],
            'summary': {}
        }
        
        current_datetime = datetime.now()
        current_date = current_datetime.date()
        
        for (team_abbr, player_lookup), enhancement in enhancement_data.items():
            if (team_abbr, player_lookup) not in found_players:
                
                # Enhanced alias checking
                alias_check_result = self._check_player_aliases_detailed(player_lookup, team_abbr)
                
                if alias_check_result['found']:
                    logger.info(f"Player {player_lookup} found via alias mapping for {team_abbr}")
                    continue
                
                # Create investigation if warranted
                if self._should_investigate_player(player_lookup):
                    investigation = self._create_enhanced_investigation(
                        player_lookup, team_abbr, enhancement, alias_check_result
                    )
                    
                    if investigation['confidence_score'] > 0.3:
                        investigation_report['investigations'].append(investigation)
                
                # Create unresolved record with enhanced data
                status = 'pending_name_change_review' if investigation['confidence_score'] > 0.5 else 'pending'
                notes = f"Potential name change - confidence: {investigation['confidence_score']:.2f}. {investigation['evidence_notes']}"
                
                unresolved_record = {
                    'source': 'basketball_reference',
                    'original_name': enhancement.get('original_name', 'Unknown'),
                    'normalized_lookup': player_lookup,
                    'first_seen_date': current_date,
                    'last_seen_date': current_date,
                    'team_abbr': team_abbr,
                    'season': self.calculate_season_string(enhancement.get('season_year', 2024)),
                    'occurrences': 1,
                    'example_games': [],
                    'status': status,
                    'resolution_type': None,
                    'resolved_to_name': None,
                    'notes': notes,
                    'reviewed_by': None,
                    'reviewed_at': None,
                    'created_at': current_datetime,
                    'processed_at': current_datetime
                }
                unresolved_players.append(unresolved_record)
        
        # Save investigation report if investigations found
        investigation_report['total_investigations'] = len(investigation_report['investigations'])
        if investigation_report['investigations']:
            self._save_investigation_report(investigation_report)
            logger.info(f"Saved investigation report with {len(investigation_report['investigations'])} potential name changes")
        
        # Insert unresolved players
        if unresolved_players:
            self._insert_unresolved_players(unresolved_players)
            self.stats['unresolved_players_found'] = len(unresolved_players)
            logger.info(f"Added {len(unresolved_players)} Basketball Reference players to unresolved queue")
        else:
            logger.info("No unresolved Basketball Reference players found")

    def transform_data(self, raw_data: Dict, file_path: str = None) -> List[Dict]:
        """Transform data for this processor."""
        # Extract filters from raw_data
        season_filter = raw_data.get('season_filter')
        team_filter = raw_data.get('team_filter') 
        date_range = raw_data.get('date_range')
        
        logger.info(f"Building registry with filters: season={season_filter}, team={team_filter}, date_range={date_range}")
        
        # Get gamebook data
        gamebook_df = self.get_gamebook_player_data(
            season_filter=season_filter,
            team_filter=team_filter, 
            date_range=date_range
        )
        
        if gamebook_df.empty:
            logger.warning("No gamebook data found for specified filters")
            return []
        
        # Aggregate into registry records
        registry_records = self.aggregate_player_stats(gamebook_df, date_range=date_range)
        
        return registry_records
    
    # High-level convenience methods
    def build_registry_for_season(self, season: str, team: str = None) -> Dict:
        """Build registry for a specific season."""
        logger.info(f"Building registry for season {season}" + (f", team {team}" if team else ""))
        
        season_start = time.time()
        logger.info(f"PERF_METRIC: season_processing_start season={season} team={team}")
        
        # Reset tracking for this run
        self.new_players_discovered = set()
        self.players_seen_this_run = set()

        # Reset stats
        self.stats = {
            'players_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'seasons_processed': set(),
            'teams_processed': set(),
            'unresolved_players_found': 0,
            'alias_resolutions': 0
        }
        
        # Create filter data
        filter_data = {
            'season_filter': season,
            'team_filter': team
        }
        
        # Transform and load
        rows = self.transform_data(filter_data)
        result = self.load_data(rows)

        result['new_players_discovered'] = list(self.new_players_discovered)
        if self.new_players_discovered:
            logger.info(f"Discovered {len(self.new_players_discovered)} new players: {', '.join(self.new_players_discovered)}")
        
        # Log summary
        logger.info(f"Registry build complete for {season}:")
        logger.info(f"  Records created: {len(rows)}")
        logger.info(f"  Records loaded: {result['rows_processed']}")
        logger.info(f"  Load errors: {len(result.get('errors', []))}")
        logger.info(f"  Players processed: {self.stats['players_processed']}")
        logger.info(f"  Teams: {len(self.stats['teams_processed'])}")
        logger.info(f"  Alias resolutions: {self.stats['alias_resolutions']}")
        logger.info(f"  Unresolved found: {self.stats['unresolved_players_found']}")
        
        season_duration = time.time() - season_start
        logger.info(f"PERF_METRIC: season_processing_complete season={season} duration={season_duration:.3f}s records={result['rows_processed']}")

        return {
            'season': season,
            'team_filter': team,
            'records_processed': result['rows_processed'],
            'records_created': len(rows),
            'players_processed': self.stats['players_processed'],
            'teams_processed': list(self.stats['teams_processed']),
            'alias_resolutions': self.stats['alias_resolutions'],
            'unresolved_found': self.stats['unresolved_players_found'],
            'errors': result.get('errors', []),
            'processing_run_id': self.processing_run_id
        }

    def build_historical_registry(self, seasons: List[str] = None) -> Dict:
        """Build registry from historical gamebook data."""
        logger.info("Starting historical registry build")
        
        if not seasons:
            # Get available seasons from gamebook data
            seasons_query = f"""
                SELECT DISTINCT season_year
                FROM `{self.project_id}.nba_raw.nbac_gamebook_player_stats`
                WHERE season_year IS NOT NULL
                ORDER BY season_year DESC
            """
            
            try:
                seasons_df = self.bq_client.query(seasons_query).to_dataframe()
                seasons = [f"{int(row['season_year'])}-{str(int(row['season_year']) + 1)[-2:]}" 
                          for _, row in seasons_df.iterrows()]
            except Exception as e:
                logger.error(f"Error querying available seasons: {e}")
                seasons = ["2021-22", "2022-23", "2023-24", "2024-25"]
        
        logger.info(f"Building historical registry for seasons: {seasons}")
        
        total_results = []
        for season in seasons:
            logger.info(f"Processing season {season}")
            result = self.build_registry_for_season(season)
            total_results.append(result)
        
        # Summary
        total_records = sum(r.get('records_processed', 0) for r in total_results)
        total_errors = sum(len(r.get('errors', [])) for r in total_results)
        
        return {
            'scenario': 'historical_backfill',
            'seasons_processed': seasons,
            'total_records_processed': total_records,
            'total_errors': total_errors,
            'individual_results': total_results,
            'processing_run_id': self.processing_run_id
        }