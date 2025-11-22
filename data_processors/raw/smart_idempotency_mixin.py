#!/usr/bin/env python3
"""
data_processors/raw/smart_idempotency_mixin.py

Smart Idempotency Mixin (Pattern #14)

Provides hash-based skip logic for Phase 2 raw processors to prevent
unnecessary cascade processing when source data hasn't meaningfully changed.

Key Features:
- Computes SHA256 hash (16 chars) of meaningful fields only
- Queries existing hash from BigQuery before write
- Skips write if hash matches (MERGE_UPDATE strategy)
- Writes with hash for monitoring (APPEND_ALWAYS strategy)
- Tracks skip metrics for monitoring

Usage:
    class MyProcessor(SmartIdempotencyMixin, ProcessorBase):
        # Define which fields to hash (meaningful fields only)
        HASH_FIELDS = ['game_id', 'player_lookup', 'injury_status', 'reason']

        def transform_data(self):
            # Transform data normally
            self.transformed_data = {...}

            # Mixin automatically adds data_hash field
            self.add_data_hash()  # Call this after transform_data

        def save_data(self):
            # Mixin checks hash and skips if unchanged
            if self.should_skip_write():
                logger.info("Skipping write - data unchanged")
                self.stats['rows_skipped'] = len(self.transformed_data)
                return

            # Proceed with normal save
            super().save_data()

Architecture:
- Mixin extends processor base class
- No modification to base class required
- Child processors opt-in by inheriting mixin
- Backwards compatible (processors without mixin work unchanged)

Implementation Phases:
- Week 1: Critical processors (injuries, props) - 50% reduction expected
- Week 2: Medium priority (boxscores, play-by-play)
- Week 3+: Low priority (schedules, rosters)
"""

import hashlib
import logging
from typing import Dict, List, Optional, Any
from google.cloud import bigquery

logger = logging.getLogger(__name__)


class SmartIdempotencyMixin:
    """
    Mixin for Phase 2 raw processors to enable smart idempotency.

    Provides hash-based skip logic to prevent cascade processing when
    source data hasn't meaningfully changed.

    Class Variables (must be set by child class):
        HASH_FIELDS (List[str]): Fields to include in hash computation.
                                  Should include only meaningful fields,
                                  excluding metadata like processed_at,
                                  scrape_timestamp, confidence_score, etc.

    Instance Variables (set by mixin):
        _computed_hash (str): Most recently computed hash value
        _existing_hash (str): Hash value from existing BigQuery record
        _hash_match (bool): Whether computed hash matches existing hash

    Methods:
        compute_data_hash(): Compute hash from specified fields
        add_data_hash(): Add data_hash field to transformed_data
        query_existing_hash(): Query existing hash from BigQuery
        should_skip_write(): Determine if write should be skipped
        get_idempotency_stats(): Return skip statistics
    """

    # Child classes MUST define this
    HASH_FIELDS: List[str] = []

    # Mixin instance variables
    _computed_hash: Optional[str] = None
    _existing_hash: Optional[str] = None
    _hash_match: bool = False
    _idempotency_stats: Dict[str, int] = {}

    def compute_data_hash(self, record: Dict[str, Any]) -> str:
        """
        Compute SHA256 hash (16 chars) from meaningful fields only.

        Args:
            record: Single data record (dict)

        Returns:
            str: 16-character hash (first 16 chars of SHA256 hex digest)

        Raises:
            ValueError: If HASH_FIELDS not defined or hash field missing

        Algorithm:
            1. Extract values for HASH_FIELDS from record
            2. Convert to canonical string representation (sorted, normalized)
            3. Compute SHA256
            4. Return first 16 characters (sufficient uniqueness, compact storage)

        Example:
            record = {
                'player_lookup': 'lebronjames',
                'injury_status': 'out',
                'reason': 'left ankle',
                'processed_at': '2025-01-15 10:00:00'  # NOT included in hash
            }

            hash = self.compute_data_hash(record)
            # Returns: "a3f2b1c9d4e5f6a7"
        """
        if not self.HASH_FIELDS:
            raise ValueError(
                f"{self.__class__.__name__} must define HASH_FIELDS for smart idempotency"
            )

        # Extract hash field values
        hash_values = []
        for field in self.HASH_FIELDS:
            if field not in record:
                raise ValueError(
                    f"Hash field '{field}' not found in record. "
                    f"Available fields: {list(record.keys())}"
                )

            value = record[field]

            # Normalize value to string representation
            # Handle None, numbers, strings, dates consistently
            if value is None:
                normalized = "NULL"
            elif isinstance(value, (int, float)):
                # Normalize numbers (avoid float precision issues)
                normalized = str(value)
            elif isinstance(value, str):
                # Strip whitespace for consistency
                normalized = value.strip()
            else:
                # Dates, timestamps, etc. - convert to ISO string
                normalized = str(value)

            hash_values.append(f"{field}:{normalized}")

        # Create canonical string (sorted for consistency)
        canonical_string = "|".join(sorted(hash_values))

        # Compute SHA256 hash
        hash_bytes = canonical_string.encode('utf-8')
        sha256_hash = hashlib.sha256(hash_bytes).hexdigest()

        # Return first 16 characters (sufficient uniqueness)
        # Collision probability: ~1 in 18 quintillion for 16 hex chars
        return sha256_hash[:16]

    def add_data_hash(self) -> None:
        """
        Add data_hash field to each record in transformed_data.

        Call this method at the end of transform_data() after all meaningful
        fields have been populated.

        Modifies:
            self.transformed_data: Adds 'data_hash' field to each record
            self._idempotency_stats: Tracks hashing statistics

        Example:
            def transform_data(self):
                # Normal transformation
                self.transformed_data = [
                    {'player': 'lebron', 'status': 'out', ...},
                    {'player': 'curry', 'status': 'probable', ...}
                ]

                # Add hashes (call this last)
                self.add_data_hash()
        """
        if not hasattr(self, 'transformed_data'):
            logger.warning("No transformed_data to add hashes to")
            return

        # Handle both list and dict formats
        if isinstance(self.transformed_data, dict):
            records = [self.transformed_data]
        elif isinstance(self.transformed_data, list):
            records = self.transformed_data
        else:
            logger.error(f"Unexpected transformed_data type: {type(self.transformed_data)}")
            return

        # Compute hash for each record
        hashes_added = 0
        for record in records:
            try:
                data_hash = self.compute_data_hash(record)
                record['data_hash'] = data_hash
                hashes_added += 1
            except Exception as e:
                logger.error(f"Failed to compute hash for record: {e}")
                # Add NULL hash to maintain schema consistency
                record['data_hash'] = None

        logger.info(f"Added data_hash to {hashes_added}/{len(records)} records")
        self._idempotency_stats['hashes_computed'] = hashes_added

    def query_existing_hash(
        self,
        primary_keys: Dict[str, Any],
        table_id: str = None
    ) -> Optional[str]:
        """
        Query existing data_hash from BigQuery for given primary keys.

        Args:
            primary_keys: Dict of primary key field names and values
                         Example: {'game_id': '0022400561', 'player_lookup': 'lebronjames'}
            table_id: Full table ID (defaults to self.table_name)

        Returns:
            str: Existing hash value if record exists, None otherwise

        Example:
            existing_hash = self.query_existing_hash({
                'game_id': '0022400561',
                'player_lookup': 'lebronjames'
            })

            if existing_hash == computed_hash:
                # Skip write
                pass
        """
        table_id = table_id or self.table_name

        # Build WHERE clause from primary keys
        where_conditions = []
        for key, value in primary_keys.items():
            if value is None:
                where_conditions.append(f"{key} IS NULL")
            elif isinstance(value, str):
                # Escape single quotes
                escaped_value = value.replace("'", "\\'")
                # Check if this looks like a date (YYYY-MM-DD format)
                if len(value) == 10 and value[4] == '-' and value[7] == '-':
                    where_conditions.append(f"{key} = DATE('{escaped_value}')")
                else:
                    where_conditions.append(f"{key} = '{escaped_value}'")
            else:
                where_conditions.append(f"{key} = {value}")

        where_clause = " AND ".join(where_conditions)

        # Query for existing hash
        query = f"""
        SELECT data_hash
        FROM `{table_id}`
        WHERE {where_clause}
        LIMIT 1
        """

        try:
            if not hasattr(self, 'bq_client') or self.bq_client is None:
                logger.warning("No BigQuery client available for hash lookup")
                return None

            query_job = self.bq_client.query(query)
            results = list(query_job.result())

            if results and results[0].data_hash:
                return results[0].data_hash
            else:
                return None

        except Exception as e:
            logger.error(f"Failed to query existing hash: {e}")
            return None

    def should_skip_write(self) -> bool:
        """
        Determine if write should be skipped based on hash comparison.

        Decision logic depends on processing strategy:

        MERGE_UPDATE strategy:
            - Query existing hash for each record's primary keys
            - Compare to computed hash
            - Skip ENTIRE write operation if ALL hashes match
            - Return True to skip, False to proceed

        APPEND_ALWAYS strategy:
            - Always return False (never skip)
            - Hash is written for monitoring/auditing
            - Downstream consumers can use hash to detect duplicates

        Returns:
            bool: True if write should be skipped, False otherwise

        Updates:
            self.stats: Adds 'rows_skipped', 'rows_hash_match', etc.

        Example (MERGE_UPDATE):
            def save_data(self):
                # Check idempotency
                if self.should_skip_write():
                    logger.info("Skipping write - data unchanged")
                    return

                # Proceed with write
                super().save_data()

        Example (APPEND_ALWAYS):
            def save_data(self):
                # APPEND_ALWAYS always writes (never skips)
                # Hash is included for monitoring
                super().save_data()
        """
        # Check if processor defines processing strategy
        strategy = getattr(self, 'processing_strategy', 'MERGE_UPDATE')

        # APPEND_ALWAYS: Never skip (hash is for monitoring only)
        if strategy == 'APPEND_ALWAYS':
            logger.debug("APPEND_ALWAYS strategy - never skipping")
            self._idempotency_stats['strategy'] = 'APPEND_ALWAYS'
            self._idempotency_stats['skip_check_performed'] = False
            return False

        # MERGE_UPDATE: Check hashes and potentially skip
        self._idempotency_stats['strategy'] = 'MERGE_UPDATE'
        self._idempotency_stats['skip_check_performed'] = True

        if not self.transformed_data:
            logger.debug("No transformed data to check")
            return False

        # Determine primary key fields from processor
        primary_keys = getattr(self, 'PRIMARY_KEYS', None)

        if not primary_keys:
            # If PRIMARY_KEYS not defined, infer from HASH_FIELDS
            # Typically first 1-3 fields in HASH_FIELDS are primary keys
            # This is a fallback - processors should define PRIMARY_KEYS
            logger.debug("PRIMARY_KEYS not defined, skipping hash comparison")
            return False

        # Check hash for each record
        matches = 0
        total = len(self.transformed_data)

        # Check if table has partition column (commonly 'game_date')
        partition_col = getattr(self, 'PARTITION_COLUMN', 'game_date')

        for record in self.transformed_data:
            # Extract primary key values
            pk_dict = {key: record.get(key) for key in primary_keys}

            # Add partition column if it exists in record
            if partition_col and partition_col in record:
                pk_dict[partition_col] = record.get(partition_col)

            # Query existing hash
            existing_hash = self.query_existing_hash(pk_dict)
            computed_hash = record.get('data_hash')

            if existing_hash and computed_hash and existing_hash == computed_hash:
                matches += 1
            else:
                # At least one record differs, must write
                break

        # Update stats
        self._idempotency_stats['hashes_matched'] = matches
        self._idempotency_stats['total_records'] = total

        # Skip only if ALL records match
        if matches == total and total > 0:
            self._idempotency_stats['rows_skipped'] = total
            logger.info(f"Smart idempotency: All {total} record(s) unchanged, skipping write")
            return True

        logger.debug(f"Smart idempotency: {matches}/{total} records matched, proceeding with write")
        return False

    def get_idempotency_stats(self) -> Dict[str, Any]:
        """
        Return smart idempotency statistics for monitoring.

        Returns:
            Dict with keys:
                - hashes_computed: Number of hashes computed
                - hashes_matched: Number of records with matching hash
                - rows_skipped: Number of rows skipped (MERGE_UPDATE only)
                - strategy: Processing strategy used
                - skip_check_performed: Whether skip check was run

        Example:
            stats = processor.get_idempotency_stats()
            # {
            #     'hashes_computed': 450,
            #     'hashes_matched': 425,
            #     'rows_skipped': 425,
            #     'strategy': 'MERGE_UPDATE',
            #     'skip_check_performed': True
            # }
        """
        return {
            'hashes_computed': self._idempotency_stats.get('hashes_computed', 0),
            'hashes_matched': self._idempotency_stats.get('hashes_matched', 0),
            'rows_skipped': self._idempotency_stats.get('rows_skipped', 0),
            'strategy': self._idempotency_stats.get('strategy', 'unknown'),
            'skip_check_performed': self._idempotency_stats.get('skip_check_performed', False)
        }


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

"""
Example 1: Injury Report Processor (APPEND_ALWAYS strategy)

class NbacInjuryReportProcessor(SmartIdempotencyMixin, ProcessorBase):
    # Define meaningful fields for hash
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
        self.processing_strategy = 'APPEND_ALWAYS'  # Track all changes

    def transform_data(self):
        # Transform data normally
        self.transformed_data = []
        for injury in self.raw_data['injuries']:
            record = {
                'player_lookup': self.normalize_name(injury['player']),
                'team': injury['team'],
                'game_date': injury['game_date'],
                'game_id': injury['game_id'],
                'injury_status': injury['status'],
                'reason': injury['reason'],
                'reason_category': self.categorize_reason(injury['reason']),
                'scrape_timestamp': datetime.now(),  # NOT in hash
                'processed_at': datetime.now()        # NOT in hash
            }
            self.transformed_data.append(record)

        # Add hashes (call this last)
        self.add_data_hash()

    def save_data(self):
        # APPEND_ALWAYS always writes (hash is for monitoring)
        # Downstream can use hash to detect when injury status actually changed
        super().save_data()

        # Log idempotency stats
        stats = self.get_idempotency_stats()
        logger.info(f"Idempotency stats: {stats}")


Example 2: Player Boxscore Processor (MERGE_UPDATE strategy)

class BdlPlayerBoxscoresProcessor(SmartIdempotencyMixin, ProcessorBase):
    # Define meaningful fields for hash
    HASH_FIELDS = [
        'game_id',
        'player_lookup',
        'points',
        'rebounds',
        'assists',
        'field_goals_made',
        'field_goals_attempted'
    ]

    def __init__(self):
        super().__init__()
        self.table_name = 'nba_raw.bdl_player_boxscores'
        self.processing_strategy = 'MERGE_UPDATE'  # Update in place

    def transform_data(self):
        # Transform data normally
        self.transformed_data = []
        for game in self.raw_data['games']:
            record = {
                'game_id': game['id'],
                'player_lookup': self.normalize_name(game['player']),
                'points': game['pts'],
                'rebounds': game['reb'],
                'assists': game['ast'],
                'field_goals_made': game['fgm'],
                'field_goals_attempted': game['fga'],
                'scrape_timestamp': datetime.now(),  # NOT in hash
                'processed_at': datetime.now()        # NOT in hash
            }
            self.transformed_data.append(record)

        # Add hashes
        self.add_data_hash()

    def save_data(self):
        # Check idempotency - skip if all hashes match
        if self.should_skip_write():
            logger.info("Skipping write - all boxscores unchanged")
            self.stats['rows_skipped'] = len(self.transformed_data)
            return

        # Proceed with write (MERGE strategy)
        super().save_data()

        # Log stats
        stats = self.get_idempotency_stats()
        logger.info(f"Idempotency stats: {stats}")
"""
