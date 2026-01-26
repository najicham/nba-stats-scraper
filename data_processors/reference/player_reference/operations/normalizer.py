"""
Roster Normalizer

Handles aggregation and normalization of roster data from multiple sources.
Coordinates validation, enhancement, and authority checking.
"""

import logging
import time
from datetime import date, datetime
from typing import Dict, List, Set, Tuple

import pandas as pd
from google.cloud import bigquery

from shared.utils.notification_system import notify_error

logger = logging.getLogger(__name__)


class RosterNormalizer:
    """
    Aggregates and normalizes roster data from multiple sources.

    Coordinates:
    - Source data fetching (via source handlers)
    - NBA.com canonical validation (via staleness detector)
    - Alias and unresolved record creation (via registry ops)
    - Authority and freshness checking (via processor)
    """

    def __init__(
        self,
        processor,
        source_handlers: Dict,
        staleness_detector,
        registry_ops
    ):
        """
        Initialize roster normalizer.

        Args:
            processor: The main processor instance (provides helper methods)
            source_handlers: Dict of source name to handler instance
            staleness_detector: StalenessDetector instance
            registry_ops: RegistryOperations instance
        """
        self.processor = processor
        self.source_handlers = source_handlers
        self.staleness_detector = staleness_detector
        self.registry_ops = registry_ops

    def aggregate_roster_assignments(
        self,
        roster_data: Dict[str, Set[str]],
        season_year: int,
        data_date: date,
        season_str: str,
        allow_backfill: bool = False,
        allow_source_fallback: bool = False
    ) -> Tuple[List[Dict], Dict]:
        """
        Aggregate roster data into registry records with NBA.com validation and staleness checking.

        Args:
            roster_data: Dict of roster sources and their players
            season_year: NBA season starting year
            data_date: Date this roster data represents
            season_str: Season string (e.g., "2024-2025")
            allow_backfill: If True, skip freshness checks for historical data
            allow_source_fallback: If True, use latest available data if exact date missing

        Returns:
            Tuple of (registry records, validation info dict)
        """
        start_time = time.time()
        logger.info("Aggregating roster assignments into registry records...")

        try:
            # Build NBA.com canonical set with freshness check
            canonical_start = time.time()
            nba_canonical_set, validation_info = self.staleness_detector.get_canonical_set_with_staleness_check(
                season_year, data_date, season_str
            )
            canonical_duration = time.time() - canonical_start
            logger.info(f"Built NBA.com canonical set in {canonical_duration:.2f}s")

            fallback_mode = len(nba_canonical_set) == 0

            if validation_info['validation_mode'] == 'none':
                logger.warning(f"⚠️ Running in NO VALIDATION mode - {validation_info.get('validation_skipped_reason')}")
            else:
                logger.info(f"Using {len(nba_canonical_set)} NBA.com player-team combinations as canonical set")

            # Source mapping
            source_map = {
                'espn_rosters': 'roster_espn',
                'basketball_reference': 'roster_br',
                'nba_player_list': 'roster_nba_com'
            }

            # Combine all roster sources and collect detailed data
            all_roster_players = set()
            player_team_details = {}
            unvalidated_players = []

            for source, players in roster_data.items():
                all_roster_players.update(players)

                # GET DETAILED DATA WITH STRICT DATE MATCHING
                detailed_data = self._get_detailed_roster_data(
                    source, season_year, data_date, allow_source_fallback
                )

                for player_lookup, details in detailed_data.items():
                    team_abbr = details['team_abbr']
                    key = (player_lookup, team_abbr)

                    # Validation logic
                    if source == 'nba_player_list':
                        should_create_record = True
                        actual_source_priority = 'roster_nba_com'
                    elif source in ['espn_rosters', 'basketball_reference']:
                        if validation_info['validation_mode'] == 'none':
                            should_create_record = True
                            actual_source_priority = source_map.get(source, 'roster_unknown')
                            logger.debug(f"⚠️ {source}: {player_lookup} on {team_abbr} accepted (no validation mode)")
                        elif key in nba_canonical_set:
                            should_create_record = True
                            actual_source_priority = 'roster_nba_com'
                            logger.debug(f"✓ {source}: {player_lookup} on {team_abbr} validated")
                        elif self.processor._check_player_aliases(player_lookup, team_abbr):
                            should_create_record = True
                            actual_source_priority = 'roster_nba_com'
                            logger.debug(f"✓ {source}: {player_lookup} on {team_abbr} validated via alias")
                        else:
                            should_create_record = False
                            unvalidated_players.append({
                                'source': source,
                                'player_lookup': player_lookup,
                                'team_abbr': team_abbr,
                                'display_name': details.get('player_full_name', player_lookup.title())
                            })
                            logger.debug(f"✗ {source}: {player_lookup} on {team_abbr} not in canonical set")
                    else:
                        should_create_record = True
                        actual_source_priority = source_map.get(source, 'roster_unknown')

                    if should_create_record:
                        if key not in player_team_details:
                            player_team_details[key] = {
                                'sources': [],
                                'enhancement_data': {},
                                'source_priority': actual_source_priority
                            }

                        player_team_details[key]['sources'].append(source)

                        if 'jersey_number' in details and details['jersey_number']:
                            player_team_details[key]['enhancement_data']['jersey_number'] = details['jersey_number']
                        if 'position' in details and details['position']:
                            player_team_details[key]['enhancement_data']['position'] = details['position']
                        if 'player_full_name' in details and details['player_full_name']:
                            player_team_details[key]['enhancement_data']['player_full_name'] = details['player_full_name']

            # Create unresolved records
            if unvalidated_players:
                logger.warning(f"Found {len(unvalidated_players)} player-team combinations not in NBA.com canonical set")
                self.registry_ops.create_unvalidated_records(unvalidated_players, season_year)

            # BULK RESOLUTION
            unique_player_lookups = list({lookup for (lookup, team) in player_team_details.keys()})
            logger.info(f"Performing bulk universal ID resolution for {len(unique_player_lookups)} validated roster players")

            universal_id_mappings = self.processor.bulk_resolve_universal_player_ids(unique_player_lookups)

            registry_records = []

            # Auto-create suffix aliases
            try:
                aliases_created = self._auto_create_suffix_aliases(player_team_details, season_year)
                if aliases_created > 0:
                    logger.info(f"Auto-created {aliases_created} suffix aliases for source matching")
            except Exception as e:
                logger.warning(f"Failed to auto-create aliases (non-fatal): {e}")

            logger.info(f"Creating records for {len(player_team_details)} validated player-team combinations")

            # ===================================================================
            # OPTIMIZATION: Batch fetch all existing records for this season
            # ===================================================================
            batch_fetch_start = time.time()
            existing_records_lookup = self._batch_fetch_existing_records(season_str)
            batch_fetch_duration = time.time() - batch_fetch_start
            if existing_records_lookup is not None:
                logger.info(f"Batch fetched {len(existing_records_lookup)} existing records in {batch_fetch_duration:.2f}s")

            # Track skipped records for reporting
            skipped_count = 0
            record_creation_start = time.time()
            records_checked = 0

            # Create registry records with PROTECTION CHECKS
            for (player_lookup, team_abbr), details in player_team_details.items():
                records_checked += 1

                # Log progress every 100 records
                if records_checked % 100 == 0:
                    elapsed = time.time() - record_creation_start
                    logger.info(f"Progress: {records_checked}/{len(player_team_details)} records checked in {elapsed:.1f}s")

                sources = details.get('sources', [])
                enhancement = details.get('enhancement_data', {})
                source_priority = details.get('source_priority', 'roster_unknown')

                # ===================================================================
                # PROTECTION 1: Get existing record (optimized batch lookup)
                # ===================================================================
                if existing_records_lookup is not None:
                    # Fast O(1) lookup from batch-fetched data
                    existing_record = existing_records_lookup.get((player_lookup, team_abbr))
                else:
                    # Fallback to individual query if batch fetch failed
                    existing_record = self.processor.get_existing_record(player_lookup, team_abbr, season_str)

                # PROTECTION 2: Freshness check (skip when backfilling historical data)
                if not allow_backfill:
                    should_update, freshness_reason = self.processor.should_update_record(
                        existing_record, data_date, self.processor.processor_type
                    )

                    if not should_update:
                        logger.debug(f"Skipping {player_lookup} on {team_abbr}: {freshness_reason}")
                        skipped_count += 1
                        continue  # Skip this record - data is stale
                elif existing_record and allow_backfill:
                    logger.debug(f"Backfill mode: allowing update for {player_lookup} on {team_abbr} (skipping freshness check)")

                # PROTECTION 3: Team authority check
                has_team_authority, authority_reason = self.processor.check_team_authority(
                    existing_record, self.processor.processor_type
                )

                # Determine confidence
                _, confidence_score = self._determine_roster_source_priority_and_confidence(
                    sources, enhancement, season_year
                )

                # Get universal player ID
                universal_id = universal_id_mappings.get(player_lookup, f"{player_lookup}_001")

                # Create base registry record
                record = {
                    'universal_player_id': universal_id,
                    'player_name': enhancement.get('player_full_name', player_lookup.title()),
                    'player_lookup': player_lookup,
                    'season': season_str,

                    # No game data yet
                    'first_game_date': None,
                    'last_game_date': None,
                    'games_played': 0,
                    'total_appearances': 0,
                    'inactive_appearances': 0,
                    'dnp_appearances': 0,

                    # Roster-specific fields
                    'jersey_number': enhancement.get('jersey_number'),
                    'position': enhancement.get('position'),
                    'last_roster_update': datetime.now(),

                    # Source metadata
                    'source_priority': source_priority,
                    'confidence_score': confidence_score,
                    'created_by': self.processor.processing_run_id,
                    'created_at': datetime.now(),
                    'processed_at': datetime.now()
                }

                # PROTECTION 4: Only set team_abbr if we have authority
                if has_team_authority:
                    record['team_abbr'] = team_abbr
                    logger.debug(f"Setting team for {player_lookup}: {authority_reason}")
                else:
                    # Don't include team_abbr in record - MERGE will preserve existing value
                    # But we still need it for other operations, so log it
                    logger.debug(f"Skipping team update for {player_lookup}: {authority_reason}")
                    # Still need to include team_abbr for new records or we'll fail
                    # The check is: if existing_record has games > 0, don't update team
                    # But if it's a new record, we must set team
                    if existing_record is None:
                        record['team_abbr'] = team_abbr

                # PROTECTION 5: Update activity date
                record = self.processor.update_activity_date(record, self.processor.processor_type, data_date)

                # Enhance with source tracking
                enhanced_record = self.processor.enhance_record_with_source_tracking(record, self.processor.processor_type)

                # Convert types
                enhanced_record = self.processor._convert_pandas_types_for_json(enhanced_record)
                registry_records.append(enhanced_record)

            if skipped_count > 0:
                logger.info(f"Skipped {skipped_count} records due to stale data")

            record_creation_duration = time.time() - record_creation_start
            logger.info(f"Created {len(registry_records)} registry records from validated roster data in {record_creation_duration:.2f}s")

            total_duration = time.time() - start_time
            logger.info(f"Total aggregation time: {total_duration:.2f}s")

            # Add counts to validation info
            validation_info['records_created'] = len(registry_records)
            validation_info['unvalidated_count'] = len(unvalidated_players)
            validation_info['records_skipped'] = skipped_count

            return registry_records, validation_info

        except Exception as e:
            logger.error(f"Failed to aggregate roster assignments: {e}")
            try:
                notify_error(
                    title="Roster Aggregation Failed",
                    message=f"Failed to aggregate roster assignments: {str(e)}",
                    details={
                        'season_year': season_year,
                        'error_type': type(e).__name__,
                        'players_attempted': len(all_roster_players) if 'all_roster_players' in locals() else 0,
                        'processor': 'roster_registry'
                    },
                    processor_name="Roster Registry Processor"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            raise

    def _get_detailed_roster_data(
        self,
        source: str,
        season_year: int,
        data_date: date,
        allow_fallback: bool = False
    ) -> Dict[str, Dict]:
        """
        Get detailed roster data for a specific source with strict date matching.

        Args:
            source: Source name ('espn_rosters', 'nba_player_list', 'basketball_reference')
            season_year: NBA season starting year
            data_date: Required date for source data
            allow_fallback: If True, use latest available if exact date missing

        Returns:
            Dictionary mapping player_lookup to their details
        """
        if source == 'espn_rosters' and 'espn' in self.source_handlers:
            return self.source_handlers['espn'].get_detailed_data(season_year, data_date, allow_fallback)
        elif source == 'nba_player_list' and 'nba' in self.source_handlers:
            return self.source_handlers['nba'].get_detailed_data(season_year, data_date, allow_fallback)
        elif source == 'basketball_reference' and 'br' in self.source_handlers:
            return self.source_handlers['br'].get_detailed_data(season_year, data_date, allow_fallback)
        else:
            logger.warning(f"Unknown roster source: {source}")
            return {}

    def _determine_roster_source_priority_and_confidence(
        self,
        sources: List[str],
        enhancement: Dict,
        season_year: int
    ) -> Tuple[str, float]:
        """
        Determine source priority and confidence with dynamic logic for roster data.

        Args:
            sources: List of source names
            enhancement: Enhancement data dict
            season_year: NBA season starting year

        Returns:
            Tuple of (source_priority, confidence_score)
        """
        current_year = date.today().year
        data_recency_days = (date.today() - date(season_year, 10, 1)).days

        if 'espn_rosters' in sources:
            source_priority = 'roster_espn'
            base_confidence = 0.8
        elif 'nba_player_list' in sources:
            source_priority = 'roster_nba_com'
            base_confidence = 0.7
        elif 'basketball_reference' in sources:
            source_priority = 'roster_br'
            base_confidence = 0.6
        else:
            source_priority = 'roster_unknown'
            base_confidence = 0.3

        confidence_score = base_confidence

        if len(sources) >= 3:
            confidence_score = min(confidence_score + 0.15, 1.0)
        elif len(sources) >= 2:
            confidence_score = min(confidence_score + 0.1, 1.0)

        if enhancement.get('jersey_number'):
            confidence_score = min(confidence_score + 0.05, 1.0)
        if enhancement.get('position'):
            confidence_score = min(confidence_score + 0.05, 1.0)

        if data_recency_days < 30:
            confidence_score = min(confidence_score + 0.1, 1.0)
        elif data_recency_days > 365:
            confidence_score = max(confidence_score - 0.1, 0.1)

        return source_priority, confidence_score

    def _batch_fetch_existing_records(self, season_str: str) -> Dict:
        """
        Batch fetch all existing records for a season.

        Args:
            season_str: Season string (e.g., "2024-2025")

        Returns:
            Dict mapping (player_lookup, team_abbr) to record dict, or None if failed
        """
        query = f"""
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
        FROM `{self.processor.project_id}.{self.processor.table_name}`
        WHERE season = @season
        """

        job_config = bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("season", "STRING", season_str)
        ])

        try:
            existing_records_df = self.processor.bq_client.query(query, job_config=job_config).to_dataframe()

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

            return existing_records_lookup

        except Exception as e:
            logger.warning(f"Error batch fetching existing records: {e}, falling back to individual queries")
            return None

    def _auto_create_suffix_aliases(
        self,
        player_team_details: Dict[Tuple[str, str], Dict],
        season_year: int
    ) -> int:
        """
        Auto-detect and create aliases for suffix mismatches (same team only).

        Args:
            player_team_details: Dict mapping (player_lookup, team_abbr) to details
            season_year: NBA season starting year

        Returns:
            Number of aliases created
        """
        suffixes = ['jr', 'sr', 'ii', 'iii', 'iv', 'v']
        aliases_to_create = []
        unresolved_to_create = []

        base_to_variants = {}
        for (player_lookup, team_abbr), details in player_team_details.items():
            base = player_lookup
            detected_suffix = None

            for suffix in suffixes:
                if player_lookup.endswith(suffix):
                    base = player_lookup[:-len(suffix)]
                    detected_suffix = suffix
                    break

            if base not in base_to_variants:
                base_to_variants[base] = []
            base_to_variants[base].append({
                'lookup': player_lookup,
                'suffix': detected_suffix,
                'team': team_abbr,
                'sources': details.get('sources', []),
                'display_name': details.get('enhancement_data', {}).get('player_full_name', player_lookup.title())
            })

        for base, variants in base_to_variants.items():
            if len(variants) > 1:
                teams = set(v['team'] for v in variants)

                if len(teams) == 1:
                    canonical = None
                    for variant in variants:
                        if 'nba_player_list' in variant['sources']:
                            canonical = variant
                            break

                    if not canonical:
                        canonical = next((v for v in variants if v['suffix']), variants[0])

                    for variant in variants:
                        if variant['lookup'] != canonical['lookup']:
                            aliases_to_create.append({
                                'alias_lookup': variant['lookup'],
                                'nba_canonical_lookup': canonical['lookup'],
                                'alias_display': variant['display_name'],
                                'nba_canonical_display': canonical['display_name'],
                                'alias_type': 'suffix_difference',
                                'alias_source': 'auto_detected',
                                'is_active': True,
                                'notes': f"Auto-detected suffix mismatch (same team: {variant['team']})",
                                'created_by': self.processor.processing_run_id,
                                'created_at': datetime.now(),
                                'processed_at': datetime.now()
                            })
                else:
                    for variant in variants:
                        primary_source = variant['sources'][0] if variant['sources'] else 'unknown'
                        source_map = {
                            'espn_rosters': 'espn',
                            'nba_player_list': 'nba_com',
                            'basketball_reference': 'br'
                        }
                        source_name = source_map.get(primary_source, primary_source)

                        unresolved_to_create.append({
                            'source': source_name,
                            'original_name': variant['display_name'],
                            'normalized_lookup': variant['lookup'],
                            'first_seen_date': date.today(),
                            'last_seen_date': date.today(),
                            'team_abbr': variant['team'],
                            'season': self.processor.calculate_season_string(season_year),
                            'occurrences': 1,
                            'example_games': [],
                            'status': 'pending',
                            'resolution_type': None,
                            'resolved_to_name': None,
                            'notes': f"Cross-team suffix mismatch: base '{base}' on teams {list(teams)} - needs review",
                            'reviewed_by': None,
                            'reviewed_at': None,
                            'created_at': datetime.now(),
                            'processed_at': datetime.now()
                        })

        if aliases_to_create:
            self.registry_ops.insert_aliases(aliases_to_create, self.processor._convert_pandas_types_for_json)
            logger.info(f"Auto-created {len(aliases_to_create)} suffix aliases")

        if unresolved_to_create:
            self.registry_ops.insert_unresolved_names(unresolved_to_create, self.processor._convert_pandas_types_for_json)
            logger.warning(f"Created {len(unresolved_to_create)} unresolved records for cross-team mismatches")

        return len(aliases_to_create)
