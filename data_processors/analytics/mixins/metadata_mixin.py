"""
Source metadata tracking and smart reprocessing for analytics processors.

Provides source usage tracking with hash-based change detection, smart skip logic
based on source hash comparisons, and backfill candidate identification.

Version: 1.0
Created: 2026-01-25
"""

import logging
from typing import Dict, List, Optional
from google.api_core.exceptions import GoogleAPIError

logger = logging.getLogger(__name__)


class MetadataMixin:
    """
    Source metadata tracking and smart reprocessing for analytics processors.

    Provides:
    - Source usage tracking with hash-based change detection
    - Smart skip logic based on source hash comparisons
    - Backfill candidate identification

    Requires from base class:
    - self.bq_client: BigQuery client
    - self.project_id: GCP project ID
    - self.source_metadata: Dict for tracking metadata
    - self.get_dependencies(): Method returning dependency config
    - self.table_name: Output table name
    - self.get_output_dataset(): Method returning dataset
    """

    def track_source_usage(self, dep_check: dict) -> None:
        """
        Record what sources were used during processing.
        Populates source_metadata dict AND per-source attributes.

        Enhanced to include data_hash tracking for smart idempotency integration.
        Copied from PrecomputeProcessorBase with Phase 3 adaptations.
        """
        self.source_metadata = {}

        for table_name, dep_result in dep_check['details'].items():
            config = self.get_dependencies()[table_name]
            prefix = config['field_prefix']

            if not dep_result.get('exists', False):
                # Source missing - use NULL for all fields (including hash)
                setattr(self, f'{prefix}_last_updated', None)
                setattr(self, f'{prefix}_rows_found', None)
                setattr(self, f'{prefix}_completeness_pct', None)
                setattr(self, f'{prefix}_hash', None)  # NEW: Hash tracking
                continue

            # Source exists - store raw values
            row_count = dep_result.get('row_count', 0)
            expected = dep_result.get('expected_count_min', 1)
            data_hash = dep_result.get('data_hash')  # NEW: Extract hash from dependency check

            # Calculate completeness
            if expected > 0:
                completeness_pct = (row_count / expected) * 100
                completeness_pct = min(completeness_pct, 100.0)  # Cap at 100%
            else:
                completeness_pct = 100.0

            # Store in metadata dict
            self.source_metadata[table_name] = {
                'last_updated': dep_result.get('last_updated'),
                'rows_found': row_count,
                'rows_expected': expected,
                'completeness_pct': round(completeness_pct, 2),
                'age_hours': dep_result.get('age_hours'),
                'data_hash': data_hash  # NEW: Include hash in metadata
            }

            # Store as attributes for easy access (4 fields per source now)
            setattr(self, f'{prefix}_last_updated', dep_result.get('last_updated'))
            setattr(self, f'{prefix}_rows_found', row_count)
            setattr(self, f'{prefix}_completeness_pct', round(completeness_pct, 2))
            setattr(self, f'{prefix}_hash', data_hash)  # NEW: Store hash attribute

        logger.info(f"Source tracking complete: {len(self.source_metadata)} sources tracked")

    def build_source_tracking_fields(self) -> dict:
        """
        Build dict of all source tracking fields for output records.

        Enhanced to include data_hash tracking for smart idempotency integration.
        Copied from PrecomputeProcessorBase.

        Returns:
            dict: All source tracking fields ready to merge into record (4 fields per source)
        """
        fields = {}

        # Only build if processor has dependencies
        if not hasattr(self, 'get_dependencies'):
            return fields

        # Per-source fields (4 fields per source: last_updated, rows_found, completeness_pct, hash)
        for table_name, config in self.get_dependencies().items():
            prefix = config['field_prefix']
            fields[f'{prefix}_last_updated'] = getattr(self, f'{prefix}_last_updated', None)
            fields[f'{prefix}_rows_found'] = getattr(self, f'{prefix}_rows_found', None)
            fields[f'{prefix}_completeness_pct'] = getattr(self, f'{prefix}_completeness_pct', None)
            fields[f'{prefix}_hash'] = getattr(self, f'{prefix}_hash', None)  # NEW: Hash field

        return fields

    def get_previous_source_hashes(self, game_date: str, game_id: str = None) -> Dict[str, Optional[str]]:
        """
        Get previous source hashes from BigQuery for smart reprocessing.

        Queries the Phase 3 table to find the most recent hash values for each
        source that was used in previous processing. This enables smart reprocessing
        by comparing current Phase 2 hashes with previous values.

        Args:
            game_date: Game date to query (YYYY-MM-DD)
            game_id: Optional game ID for more specific lookup

        Returns:
            Dict mapping source prefix to hash value:
            {
                'source_gamebook_hash': 'a3f5c2...',
                'source_boxscore_hash': 'b7e2d9...',
                ...
            }
            Returns empty dict if no previous data found or on error.

        Example:
            previous_hashes = processor.get_previous_source_hashes('2024-11-20', '0022400089')
            if previous_hashes.get('source_gamebook_hash') == current_hash:
                logger.info("Source unchanged, can skip processing")
        """
        if not hasattr(self, 'table_name') or not self.table_name:
            logger.warning("table_name not set - cannot get previous hashes")
            return {}

        dependencies = self.get_dependencies()
        if not dependencies:
            logger.debug("No dependencies defined - no previous hashes to check")
            return {}

        # Build WHERE clause
        where_clause = f"game_date = '{game_date}'"
        if game_id:
            where_clause += f" AND game_id = '{game_id}'"

        # Build SELECT for all hash fields
        hash_fields = []
        for table_name, config in dependencies.items():
            prefix = config['field_prefix']
            hash_fields.append(f'{prefix}_hash')

        if not hash_fields:
            return {}

        # Handle table_name that may already include dataset prefix (e.g., 'nba_analytics.table')
        if '.' in self.table_name:
            table_ref = f"{self.project_id}.{self.table_name}"
        else:
            table_ref = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        query = f"""
        SELECT {', '.join(hash_fields)}
        FROM `{table_ref}`
        WHERE {where_clause}
        ORDER BY processed_at DESC
        LIMIT 1
        """

        try:
            result = self.bq_client.query(query).result(timeout=300)
            for row in result:
                # Convert row to dict
                hashes = {}
                for field in hash_fields:
                    hashes[field] = row.get(field)
                return hashes

            # No previous data found
            logger.debug(f"No previous data found for {game_date} {game_id or ''}")
            return {}

        except GoogleAPIError as e:
            logger.warning(f"Error querying previous hashes: {e}")
            return {}

    def should_skip_processing(self, game_date: str, game_id: str = None,
                               check_all_sources: bool = False) -> tuple[bool, str]:
        """
        Determine if processing can be skipped based on source hash comparison.

        Implements smart reprocessing pattern: skip Phase 3 processing if Phase 2
        source data hashes are unchanged from previous run. This is the Phase 3
        equivalent of Phase 2's smart idempotency pattern.

        Args:
            game_date: Game date being processed
            game_id: Optional game ID for more specific matching
            check_all_sources: If True, ALL sources must be unchanged to skip.
                             If False, only check primary (first) source.

        Returns:
            Tuple of (should_skip: bool, reason: str)
            - (True, "All sources unchanged") - can skip processing
            - (False, "Source X changed") - must process
            - (False, "No previous data") - first time processing

        Example:
            skip, reason = processor.should_skip_processing('2024-11-20', '0022400089')
            if skip:
                logger.info(f"Skipping processing: {reason}")
                return []  # Skip extract_raw_data
        """
        dependencies = self.get_dependencies()
        if not dependencies:
            return False, "No dependencies defined"

        # Get previous hashes from BigQuery
        previous_hashes = self.get_previous_source_hashes(game_date, game_id)
        if not previous_hashes:
            return False, "No previous data (first time processing)"

        # Get current hashes from dependency check (already tracked)
        current_hashes = {}
        for table_name, config in dependencies.items():
            prefix = config['field_prefix']
            hash_attr = f'{prefix}_hash'
            current_hash = getattr(self, hash_attr, None)
            if current_hash:
                current_hashes[hash_attr] = current_hash

        if not current_hashes:
            return False, "No current hashes available"

        # Determine which sources to check
        if check_all_sources:
            sources_to_check = list(dependencies.keys())
        else:
            # Check only primary (first) source
            sources_to_check = [list(dependencies.keys())[0]]

        # Compare hashes
        changed_sources = []
        unchanged_sources = []

        for table_name in sources_to_check:
            config = dependencies[table_name]
            prefix = config['field_prefix']
            hash_field = f'{prefix}_hash'

            previous_hash = previous_hashes.get(hash_field)
            current_hash = current_hashes.get(hash_field)

            if previous_hash is None or current_hash is None:
                changed_sources.append(f"{table_name} (new/missing)")
                continue

            if previous_hash != current_hash:
                changed_sources.append(f"{table_name} (hash changed)")
                logger.debug(f"{table_name} hash changed: {previous_hash[:8]}... -> {current_hash[:8]}...")
            else:
                unchanged_sources.append(table_name)
                logger.debug(f"{table_name} hash unchanged: {current_hash[:8]}...")

        # Decision
        if changed_sources:
            reason = f"Sources changed: {', '.join(changed_sources)}"
            return False, reason
        else:
            reason = f"All {len(unchanged_sources)} source(s) unchanged"
            return True, reason

    def find_backfill_candidates(self, lookback_days: int = 30,
                                 primary_source_only: bool = True) -> List[Dict]:
        """
        Find games that have Phase 2 data but are missing Phase 3 analytics.

        Implements historical backfill awareness pattern from dependency docs.
        This enables Phase 3 to detect and process historical games that were
        backfilled in Phase 2 after the normal processing window.

        Args:
            lookback_days: How many days to look back (default: 30)
            primary_source_only: Only check primary source table (default: True)

        Returns:
            List[Dict]: Each dict contains:
                {
                    'game_date': str (YYYY-MM-DD),
                    'game_id': str,
                    'phase2_last_updated': str (ISO timestamp),
                    'phase2_row_count': int
                }

        Example:
            # Find games needing processing
            candidates = processor.find_backfill_candidates(lookback_days=7)
            for game in candidates:
                logger.info(f"Backfill needed: {game['game_date']} - {game['game_id']}")
                processor.run({
                    'start_date': game['game_date'],
                    'end_date': game['game_date']
                })
        """
        if not hasattr(self, 'table_name') or not self.table_name:
            logger.warning("table_name not set - cannot find backfill candidates")
            return []

        dependencies = self.get_dependencies()
        if not dependencies:
            logger.warning("No dependencies defined - cannot find backfill candidates")
            return []

        # Use first dependency as primary source (typically the critical one)
        if primary_source_only:
            primary_table = list(dependencies.keys())[0]
            source_tables = [primary_table]
        else:
            # Check all critical dependencies
            source_tables = [
                table for table, config in dependencies.items()
                if config.get('critical', True)
            ]

        if not source_tables:
            logger.warning("No source tables to check for backfill")
            return []

        # Build queries to find games with Phase 2 data but no Phase 3 data
        # NOTE: Using two separate queries to avoid cross-region JOIN issues
        #       (nba_raw may be in different region than nba_analytics)
        source_table = source_tables[0]
        source_config = dependencies[source_table]
        date_field = source_config.get('date_field', 'game_date')

        phase3_table = f"{self.project_id}.{self.get_output_dataset()}.{self.table_name}"

        try:
            logger.info(f"Searching for backfill candidates (last {lookback_days} days)...")

            # Query 1: Get all Phase 2 games in date range
            phase2_query = f"""
            SELECT DISTINCT
                {date_field} as game_date,
                game_id,
                MAX(processed_at) as phase2_last_updated,
                COUNT(*) as phase2_row_count
            FROM `{self.project_id}.{source_table}`
            WHERE {date_field} >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
                AND {date_field} < CURRENT_DATE()
            GROUP BY game_date, game_id
            """

            phase2_games = {}
            for row in self.bq_client.query(phase2_query).result(timeout=60):
                key = f"{row.game_date}_{row.game_id}"
                phase2_games[key] = {
                    'game_date': row.game_date.isoformat() if hasattr(row.game_date, 'isoformat') else str(row.game_date),
                    'game_id': row.game_id,
                    'phase2_last_updated': row.phase2_last_updated.isoformat() if row.phase2_last_updated else None,
                    'phase2_row_count': row.phase2_row_count
                }

            if not phase2_games:
                logger.info("No Phase 2 games found in date range")
                return []

            # Query 2: Get all Phase 3 games in same date range
            phase3_query = f"""
            SELECT DISTINCT
                game_date,
                game_id
            FROM `{phase3_table}`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
                AND game_date < CURRENT_DATE()
            """

            phase3_games = set()
            for row in self.bq_client.query(phase3_query).result(timeout=60):
                game_date = row.game_date.isoformat() if hasattr(row.game_date, 'isoformat') else str(row.game_date)
                key = f"{game_date}_{row.game_id}"
                phase3_games.add(key)

            # Find games in Phase 2 but not in Phase 3
            candidates = []
            for key, game_info in phase2_games.items():
                if key not in phase3_games:
                    candidates.append(game_info)

            # Sort by game_date ascending (oldest first)
            candidates.sort(key=lambda x: x['game_date'])

            if candidates:
                logger.info(f"Found {len(candidates)} games needing backfill processing")
                # Log first few for visibility
                for candidate in candidates[:5]:
                    logger.info(f"  - {candidate['game_date']}: {candidate['game_id']} "
                              f"({candidate['phase2_row_count']} Phase 2 records)")
                if len(candidates) > 5:
                    logger.info(f"  ... and {len(candidates) - 5} more games")
            else:
                logger.info("No backfill candidates found - all games processed")

            return candidates

        except GoogleAPIError as e:
            logger.error(f"Error finding backfill candidates: {e}")
            return []
