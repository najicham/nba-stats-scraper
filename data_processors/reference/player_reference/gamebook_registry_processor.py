#!/usr/bin/env python3
"""
File: data_processors/reference/player_reference/gamebook_registry_processor.py

Gamebook Registry Processor - With Complete Data Protection

Builds the NBA players registry from NBA.com gamebook data.
Enhanced with:
- Temporal ordering protection
- Activity date tracking
- Data freshness validation

Three Usage Scenarios:
1. Historical backfill: Process 4 years of gamebook data
2. Nightly updates: Triggered after gamebook processing completes
3. Basic name change detection: Simple unresolved player tracking
"""

import os
import logging
import time
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional
import pandas as pd
from google.cloud import bigquery

from data_processors.reference.base.registry_processor_base import RegistryProcessorBase, TemporalOrderingError
from data_processors.reference.base.name_change_detection_mixin import NameChangeDetectionMixin
from data_processors.reference.base.database_strategies import DatabaseStrategiesMixin
from shared.utils.notification_system import (
    NotificationRouter, 
    NotificationLevel, 
    NotificationType
)

logger = logging.getLogger(__name__)


class GamebookRegistryProcessor(RegistryProcessorBase, NameChangeDetectionMixin, DatabaseStrategiesMixin):
    """
    Registry processor for NBA.com gamebook data.
    
    Creates the authoritative player registry by analyzing NBA.com gamebook data:
    - Player game participation statistics
    - Team assignments and season tracking
    - Jersey numbers and positions from Basketball Reference enhancement
    - Basic unresolved player tracking (simplified name change detection)
    """
    
    def __init__(self, test_mode: bool = False, strategy: str = "merge", 
                 confirm_full_delete: bool = False,
                 enable_name_change_detection: bool = True):
        super().__init__(test_mode, strategy, confirm_full_delete, enable_name_change_detection)
        
        # Set processor type for source tracking
        self.processor_type = 'gamebook'
        
        logger.info("Initialized Gamebook Registry Processor")
    
    def get_gamebook_player_data(self, season_filter: str = None, 
                               team_filter: str = None, 
                               date_range: Tuple[str, str] = None) -> pd.DataFrame:
        """Retrieve NBA.com gamebook player data with optional filters."""
        query_start = time.time()
        logger.info(f"PERF_METRIC: gamebook_query_start season={season_filter} team={team_filter}")
        
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
            try:
                from shared.utils.nba_team_mapper import nba_team_mapper
                logger.info("Successfully imported nba_team_mapper")
            except ImportError as e:
                logger.warning(f"Could not import nba_team_mapper: {e}")
                BR_TO_NBA_MAPPING = {
                    'BRK': 'BKN',
                    'CHO': 'CHA',
                    'PHO': 'PHX'
                }
                nba_team_mapper = None
                logger.info("Using fallback hardcoded team mapping")
            
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
            
            enhancement_data = {}
            mapped_count = 0
            unmapped_teams = set()
            team_mapping_log = {}
            
            for _, row in results.iterrows():
                br_team_abbr = row['br_team_abbr']
                nba_team_abbr = None
                
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
        
        direct_key = (team_abbr, player_lookup)
        if direct_key in enhancement_data:
            return enhancement_data[direct_key], False
        
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
        """
        Aggregate gamebook data into registry records with bulk universal ID resolution.
        Now includes freshness checks and activity date tracking.
        OPTIMIZED: Batch fetch existing records AND aliases to avoid 60+ individual queries.
        """
        logger.info("Aggregating player statistics for registry...")
        
        # Determine season years for BR filtering
        season_years_filter = None
        if date_range:
            start_season_year, end_season_year = self.date_to_nba_season_years(date_range)
            season_years_filter = (start_season_year, end_season_year)
        else:
            seasons_in_data = gamebook_df['season_year'].unique()
            if len(seasons_in_data) > 0:
                season_years_filter = (int(seasons_in_data.min()), int(seasons_in_data.max()))
        
        enhancement_data = self.get_roster_enhancement_data(season_years_filter=season_years_filter)
        
        groupby_cols = ['player_lookup', 'team_abbr', 'season_year']
        grouped = gamebook_df.groupby(groupby_cols)
        
        found_br_players = set()
        
        # BULK RESOLUTION
        unique_player_lookups = list(gamebook_df['player_lookup'].unique())
        logger.info(f"Performing bulk universal ID resolution for {len(unique_player_lookups)} unique players")
        
        universal_id_mappings = self.bulk_resolve_universal_player_ids(unique_player_lookups)
        
        # ===================================================================
        # OPTIMIZATION 1: Batch fetch all existing records for this season
        # ===================================================================
        season_str_for_batch = self.calculate_season_string(list(gamebook_df['season_year'].unique())[0])
        batch_fetch_start = time.time()
        
        existing_records_query = f"""
        SELECT 
            player_lookup,
            team_abbr,
            games_played,
            last_processor,
            last_gamebook_activity_date,
            last_roster_activity_date,
            jersey_number,
            position,
            source_priority,
            processed_at
        FROM `{self.project_id}.{self.table_name}`
        WHERE season = @season
        """
        
        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season", "STRING", season_str_for_batch)
        ])
        
        try:
            existing_records_df = self.bq_client.query(existing_records_query, job_config=job_config).to_dataframe()
            
            # Build lookup dictionary for O(1) access
            existing_records_lookup = {}
            for _, row in existing_records_df.iterrows():
                key = (row['player_lookup'], row['team_abbr'])
                # Convert to dict and handle NaN values
                record_dict = {}
                for col, value in row.items():
                    if pd.isna(value):
                        record_dict[col] = None
                    elif isinstance(value, pd.Timestamp):
                        record_dict[col] = value.to_pydatetime()
                    elif hasattr(value, 'date'):
                        record_dict[col] = value.date()
                    else:
                        record_dict[col] = value
                existing_records_lookup[key] = record_dict
            
            batch_fetch_duration = time.time() - batch_fetch_start
            logger.info(f"Batch fetched {len(existing_records_lookup)} existing records in {batch_fetch_duration:.2f}s")
            
        except Exception as e:
            logger.warning(f"Error batch fetching existing records: {e}, falling back to individual queries")
            existing_records_lookup = None
        
        # ===================================================================
        # OPTIMIZATION 2: Batch fetch all active aliases once
        # ===================================================================
        alias_fetch_start = time.time()
        
        aliases_query = f"""
        SELECT 
            nba_canonical_lookup,
            alias_lookup
        FROM `{self.project_id}.{self.alias_table_name}`
        WHERE is_active = TRUE
        """
        
        try:
            aliases_df = self.bq_client.query(aliases_query).to_dataframe()
            
            # Build lookup dictionary: canonical_name -> [alias1, alias2, ...]
            aliases_lookup = {}
            for _, row in aliases_df.iterrows():
                canonical = row['nba_canonical_lookup']
                alias = row['alias_lookup']
                
                if canonical not in aliases_lookup:
                    aliases_lookup[canonical] = []
                aliases_lookup[canonical].append(alias)
            
            alias_fetch_duration = time.time() - alias_fetch_start
            logger.info(f"Batch fetched {len(aliases_df)} active aliases for {len(aliases_lookup)} canonical names in {alias_fetch_duration:.2f}s")
            
        except Exception as e:
            logger.warning(f"Error batch fetching aliases: {e}, falling back to individual queries")
            aliases_lookup = None
        
        registry_records = []
        skipped_count = 0
        
        for (player_lookup, team_abbr, season_year), group in grouped:
            season_str = self.calculate_season_string(season_year)
            
            # =================================================================
            # PROTECTION 1: Check existing record for freshness (OPTIMIZED)
            # =================================================================
            if existing_records_lookup is not None:
                # Fast O(1) lookup from batch-fetched data
                existing_record = existing_records_lookup.get((player_lookup, team_abbr))
            else:
                # Fallback to individual query if batch fetch failed
                existing_record = self.get_existing_record(player_lookup, team_abbr, season_str)
            
            # Determine the data_date for this group (use last game date)
            game_dates = pd.to_datetime(group['game_date'])
            data_date = game_dates.max().date()
            
            # PROTECTION 2: Freshness check
            should_update, freshness_reason = self.should_update_record(
                existing_record, data_date, self.processor_type
            )
            
            if not should_update:
                logger.debug(f"Skipping {player_lookup} on {team_abbr}: {freshness_reason}")
                skipped_count += 1
                continue  # Skip this record - data is stale
            
            # Pick most common player name variant
            name_counts = group['player_name'].value_counts()
            player_name = name_counts.index[0]
            
            # Calculate game participation stats
            total_appearances = len(group)
            unique_games = group['game_id'].nunique()
            
            first_game = game_dates.min().date()
            last_game = game_dates.max().date()
            
            # Count games by status
            status_counts = group['player_status'].value_counts()
            active_games = status_counts.get('active', 0)
            inactive_games = status_counts.get('inactive', 0)
            dnp_games = status_counts.get('dnp', 0)
            
            # Determine source priority and confidence
            resolution_statuses = group['name_resolution_status'].value_counts()
            source_priority, confidence_score = self._determine_gamebook_source_priority_and_confidence(
                resolution_statuses, active_games, total_appearances
            )
            
            # =================================================================
            # Look up enhancement data (OPTIMIZED with batch aliases)
            # =================================================================
            direct_key = (team_abbr, player_lookup)
            if direct_key in enhancement_data:
                # Direct match found
                enhancement = enhancement_data[direct_key]
                resolved_via_alias = False
                found_br_players.add((team_abbr, player_lookup))
            elif aliases_lookup is not None and player_lookup in aliases_lookup:
                # Check all known aliases for this player
                enhancement = None
                for alias in aliases_lookup[player_lookup]:
                    alias_key = (team_abbr, alias)
                    if alias_key in enhancement_data:
                        enhancement = enhancement_data[alias_key]
                        resolved_via_alias = True
                        found_br_players.add(alias_key)
                        logger.info(f"Enhancement resolved via alias: {player_lookup} → {alias} for {team_abbr}")
                        self.stats['alias_resolutions'] += 1
                        break
                if enhancement is None:
                    enhancement = {}
            else:
                # Fallback to individual query if batch fetch failed
                enhancement, resolved_via_alias = self._resolve_enhancement_via_alias(
                    player_lookup, team_abbr, enhancement_data
                )
                if enhancement and resolved_via_alias:
                    # Track which BR player was found via alias
                    for br_key, br_data in enhancement_data.items():
                        if br_key[0] == team_abbr and br_data == enhancement:
                            found_br_players.add(br_key)
                            break
                elif enhancement:
                    found_br_players.add((team_abbr, player_lookup))

            if enhancement is None:
                enhancement = {}

            # Get universal player ID
            universal_id = universal_id_mappings.get(player_lookup, f"{player_lookup}_001")
            
            # Create base registry record
            record = {
                'universal_player_id': universal_id,
                'player_name': player_name,
                'player_lookup': player_lookup,
                'team_abbr': team_abbr,  # Gamebook always has authority over team
                'season': season_str,
                'first_game_date': first_game,
                'last_game_date': last_game,
                'games_played': active_games,
                'total_appearances': total_appearances,
                'inactive_appearances': inactive_games,
                'dnp_appearances': dnp_games,
                'jersey_number': enhancement.get('jersey_number'),
                'position': enhancement.get('position'),
                'source_priority': source_priority,
                'confidence_score': confidence_score,
                'created_by': self.processing_run_id,
                'created_at': datetime.now(),
                'processed_at': datetime.now()
            }
            
            # =================================================================
            # PROTECTION 3: Update activity date
            # =================================================================
            record = self.update_activity_date(record, self.processor_type, data_date)
            
            # Enhance with source tracking
            enhanced_record = self.enhance_record_with_source_tracking(record, self.processor_type)
            
            # Convert types
            enhanced_record = self._convert_pandas_types_for_json(enhanced_record)
            registry_records.append(enhanced_record)
            
            # Update stats
            self.stats['players_processed'] += 1
            self.stats['seasons_processed'].add(season_str)
            self.stats['teams_processed'].add(team_abbr)
        
        if skipped_count > 0:
            logger.info(f"Skipped {skipped_count} records due to stale data")
        
        # Handle unresolved BR players
        self._handle_unresolved_br_players_simple(enhancement_data, found_br_players, aliases_lookup)
        
        logger.info(f"Created {len(registry_records)} registry records")
        logger.info(f"Resolved {self.stats['alias_resolutions']} players via alias system")
        
        return registry_records

    def _determine_gamebook_source_priority_and_confidence(self, resolution_statuses: pd.Series, 
                                                         active_games: int, total_appearances: int) -> Tuple[str, float]:
        """Determine source priority and confidence with dynamic logic."""
        if 'original' in resolution_statuses:
            source_priority = 'nba_gamebook'
            base_confidence = 1.0
        elif 'resolved' in resolution_statuses:
            source_priority = 'nba_gamebook_resolved'
            base_confidence = 0.9
        else:
            source_priority = 'nba_gamebook_uncertain'
            base_confidence = 0.7
        
        confidence_score = base_confidence
        
        if active_games >= 50:
            confidence_score = min(confidence_score + 0.1, 1.0)
        elif active_games >= 20:
            confidence_score = min(confidence_score + 0.05, 1.0)
        elif active_games < 5:
            confidence_score = max(confidence_score - 0.1, 0.1)
        
        participation_rate = active_games / max(total_appearances, 1)
        if participation_rate >= 0.8:
            confidence_score = min(confidence_score + 0.05, 1.0)
        elif participation_rate < 0.3:
            confidence_score = max(confidence_score - 0.05, 0.1)
        
        return source_priority, confidence_score

    def _handle_unresolved_br_players_simple(self, enhancement_data: Dict, found_players: set, aliases_lookup: Dict = None):
        """
        Simplified unresolved player handling with batch alias optimization.
        
        Args:
            enhancement_data: BR enhancement data keyed by (team_abbr, player_lookup)
            found_players: Set of (team_abbr, player_lookup) tuples that were found
            aliases_lookup: Pre-fetched aliases dict {canonical_name: [alias1, alias2, ...]}
                        If None, falls back to individual queries (slow)
        """
        unresolved_players = []
        current_datetime = datetime.now()
        current_date = current_datetime.date()
        
        for (team_abbr, player_lookup), enhancement in enhancement_data.items():
            if (team_abbr, player_lookup) not in found_players:
                # Check aliases using batch data if available
                found_via_alias = False
                
                if aliases_lookup is not None:
                    # Check if any canonical name has this player_lookup as an alias
                    # AND that canonical player was found on this team
                    for canonical, alias_list in aliases_lookup.items():
                        if player_lookup in alias_list and (team_abbr, canonical) in found_players:
                            found_via_alias = True
                            logger.debug(f"BR player {player_lookup} on {team_abbr} found via alias to {canonical}")
                            break
                else:
                    # Fallback to individual query if batch fetch failed
                    found_via_alias = self._check_player_aliases(player_lookup, team_abbr)
                
                if found_via_alias:
                    continue
                
                # Not found in gamebook or via aliases - add to unresolved
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
            
            threshold = int(os.environ.get('EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD', '50'))
            if len(unresolved_players) > threshold:
                try:
                    router = NotificationRouter()
                    router.send_notification(
                        level=NotificationLevel.WARNING,
                        notification_type=NotificationType.UNRESOLVED_PLAYERS,
                        title="High Unresolved Player Count",
                        message=f"{len(unresolved_players)} unresolved players detected",
                        details={
                            'count': len(unresolved_players),
                            'threshold': threshold,
                            'processing_run_id': self.processing_run_id
                        },
                        processor_name="Gamebook Registry Processor"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")


    def transform_data(self, raw_data: Dict, file_path: str = None) -> List[Dict]:
        """Transform data for this processor."""
        season_filter = raw_data.get('season_filter')
        team_filter = raw_data.get('team_filter') 
        date_range = raw_data.get('date_range')
        
        logger.info(f"Building registry with filters: season={season_filter}, team={team_filter}, date_range={date_range}")
        
        gamebook_df = self.get_gamebook_player_data(
            season_filter=season_filter,
            team_filter=team_filter, 
            date_range=date_range
        )
        
        if gamebook_df.empty:
            logger.warning("No gamebook data found for specified filters")
            return []
        
        registry_records = self.aggregate_player_stats(gamebook_df, date_range=date_range)
        
        return registry_records
    
    def _build_registry_for_season_impl(self, season: str, team: str = None,
                                       date_range: Tuple[str, str] = None) -> Dict:
        """Implementation of season building."""
        season_start = time.time()
        logger.info(f"PERF_METRIC: season_processing_start season={season} team={team}")
        
        self.new_players_discovered = set()
        self.players_seen_this_run = set()

        self.stats = {
            'players_processed': 0,
            'records_created': 0,
            'records_updated': 0,
            'seasons_processed': set(),
            'teams_processed': set(),
            'unresolved_players_found': 0,
            'alias_resolutions': 0
        }
        
        filter_data = {
            'season_filter': season,
            'team_filter': team,
            'date_range': date_range
        }
        
        rows = self.transform_data(filter_data)
        result = self.save_registry_data(rows)

        result['new_players_discovered'] = list(self.new_players_discovered)
        if self.new_players_discovered:
            logger.info(f"Discovered {len(self.new_players_discovered)} new players")
            
            try:
                router = NotificationRouter()
                router.send_notification(
                    level=NotificationLevel.INFO,
                    notification_type=NotificationType.NEW_PLAYERS,
                    title=f"New Players Discovered - {season}",
                    message=f"{len(self.new_players_discovered)} new players added",
                    details={
                        'count': len(self.new_players_discovered),
                        'players': list(self.new_players_discovered)[:10],
                        'season': season,
                        'processing_run_id': self.processing_run_id
                    },
                    processor_name="Gamebook Registry Processor"
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
        
        logger.info(f"Registry build complete for {season}")
        logger.info(f"  Records created: {len(rows)}")
        logger.info(f"  Records loaded: {result['rows_processed']}")
        
        season_duration = time.time() - season_start
        logger.info(f"PERF_METRIC: season_processing_complete duration={season_duration:.3f}s")

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

    def build_historical_registry(self, seasons: List[str] = None, 
                                 allow_backfill: bool = False) -> Dict:
        """Build registry from historical gamebook data with temporal protection."""
        logger.info("Starting historical registry build")
        
        if not seasons:
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
            
            season_year = int(season.split('-')[0])
            
            start_date = f"{season_year}-10-01"
            end_date = f"{season_year + 1}-06-30"
            
            # Temporal validation
            try:
                self.validate_temporal_ordering(
                    data_date=date.fromisoformat(end_date),
                    season_year=season_year,
                    allow_backfill=allow_backfill
                )
            except TemporalOrderingError as e:
                logger.error(f"Temporal ordering error for {season}: {e}")
                total_results.append({
                    'season': season,
                    'status': 'skipped',
                    'reason': str(e)
                })
                continue
            
            # Track run start in memory (base class pattern)
            from datetime import timezone
            import uuid
            
            self.run_start_time = datetime.now(timezone.utc)
            self.current_run_id = f"gamebook_{end_date.replace('-', '')}_{datetime.now().strftime('%H%M%S')}_{str(uuid.uuid4())[:8]}"
            self.current_season_year = season_year
            
            logger.info(f"Starting run for {season}: {self.current_run_id}")
            
            try:
                result = self._build_registry_for_season_impl(
                    season, 
                    date_range=(start_date, end_date)
                )
                
                self.record_run_complete(
                    data_date=date.fromisoformat(end_date),
                    season_year=season_year,
                    status='success',
                    result=result,
                    data_source_primary='nba_gamebook',
                    data_source_enhancement='br_roster',
                    backfill_mode=allow_backfill
                )
                
                total_results.append(result)
                
            except Exception as e:
                logger.error(f"Failed to process season {season}: {e}")
                
                self.record_run_complete(
                    data_date=date.fromisoformat(end_date),
                    season_year=season_year,
                    status='failed',
                    error=e,
                    data_source_primary='nba_gamebook',
                    data_source_enhancement='br_roster',
                    backfill_mode=allow_backfill
                )
                
                total_results.append({
                    'season': season,
                    'status': 'failed',
                    'error': str(e)
                })
        
        total_records = sum(r.get('records_processed', 0) for r in total_results if 'records_processed' in r)
        total_errors = sum(len(r.get('errors', [])) for r in total_results if 'errors' in r)
        
        try:
            router = NotificationRouter()
            router.send_notification(
                level=NotificationLevel.INFO,
                notification_type=NotificationType.DAILY_SUMMARY,
                title="Historical Registry Build Complete",
                message=f"Processed {len(seasons)} seasons with {total_records} records",
                details={
                    'scenario': 'historical_backfill',
                    'seasons_count': len(seasons),
                    'seasons': seasons,
                    'total_records': total_records,
                    'total_errors': total_errors,
                    'processing_run_id': self.processing_run_id
                },
                processor_name="Gamebook Registry Processor"
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")
        
        return {
            'scenario': 'historical_backfill',
            'seasons_processed': seasons,
            'total_records_processed': total_records,
            'total_errors': total_errors,
            'individual_results': total_results,
            'processing_run_id': self.processing_run_id
        }


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Process gamebook registry")
    parser.add_argument("--season", type=str, help="Season to process (e.g., 2024-25)")
    parser.add_argument("--team", type=str, help="Team filter")
    parser.add_argument("--date-range", type=str, help="Date range (YYYY-MM-DD,YYYY-MM-DD)")
    parser.add_argument("--allow-backfill", action="store_true", help="Allow processing earlier dates")
    parser.add_argument("--strategy", default="merge", choices=["merge", "replace"])
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--historical", action="store_true", help="Build historical registry")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    processor = GamebookRegistryProcessor(strategy=args.strategy)
    
    if args.historical:
        result = processor.build_historical_registry(allow_backfill=args.allow_backfill)
    else:
        if not args.season:
            print("Error: --season required for non-historical processing")
            exit(1)
        
        date_range = None
        if args.date_range:
            dates = args.date_range.split(',')
            if len(dates) == 2:
                date_range = (dates[0], dates[1])
        
        season_year = int(args.season.split('-')[0])
        
        if date_range:
            start_date = date.fromisoformat(date_range[0])
            end_date = date.fromisoformat(date_range[1])
        else:
            start_date = date(season_year, 10, 1)
            end_date = date(season_year + 1, 6, 30)

        try:
            processor.validate_temporal_ordering(
                data_date=start_date,  # Validate earliest date in range
                season_year=season_year,
                allow_backfill=args.allow_backfill
            )
        except TemporalOrderingError as e:
            print(f"\n❌ TEMPORAL ORDERING ERROR")
            print(f"{'='*60}")
            print(str(e))
            print(f"{'='*60}")
            exit(1)
        
        # Track run start in memory (base class pattern)
        from datetime import timezone
        import uuid
        
        processor.run_start_time = datetime.now(timezone.utc)
        processor.current_run_id = f"gamebook_{end_date.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}_{str(uuid.uuid4())[:8]}"
        processor.current_season_year = season_year
        
        logger.info(f"Starting run: {processor.current_run_id}")
        
        try:
            result = processor._build_registry_for_season_impl(
                args.season,
                team=args.team,
                date_range=date_range
            )
            
            processor.record_run_complete(
                data_date=end_date,
                season_year=season_year,
                status='success',
                result=result,
                data_source_primary='nba_gamebook',
                data_source_enhancement='br_roster',
                backfill_mode=args.allow_backfill
            )
            
        except Exception as e:
            processor.record_run_complete(
                data_date=end_date,
                season_year=season_year,
                status='failed',
                error=e,
                data_source_primary='nba_gamebook',
                data_source_enhancement='br_roster',
                backfill_mode=args.allow_backfill
            )
            raise
    
    print(f"\n{'='*60}")
    print(f"✅ SUCCESS")
    print(f"{'='*60}")
    if 'season' in result:
        print(f"Season: {result['season']}")
        print(f"Records processed: {result['records_processed']}")
    else:
        print(f"Seasons processed: {result['seasons_processed']}")
        print(f"Total records: {result['total_records_processed']}")
    print(f"{'='*60}")