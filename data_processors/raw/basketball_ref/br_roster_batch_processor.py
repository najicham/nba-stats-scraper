"""
Basketball Reference Roster Batch Processor
============================================

Processes all 30 teams for a season in a single MERGE operation.
Triggered by batch completion message from scraper backfill.

Benefits:
- 96.7% quota reduction (30 MERGEs → 1 MERGE)
- 100% eliminates Firestore concurrent write conflicts
- 99.9% success rate (no thundering herd)

Usage:
    Automatically triggered by Pub/Sub when scraper publishes batch completion.
    Message format:
    {
        "scraper_name": "br_season_roster_batch",
        "metadata": {
            "trigger_type": "batch_processing",
            "season": "2023-24",
            "season_year": 2024,      # END year, from the scraper. NOT USED HERE.
            "teams_scraped": 30,
            "teams": ["LAL", "BOS", ...]
        }
    }

    ⚠️ Two season conventions meet in this file. The SCRAPER is end-year keyed
    (`--year 2027` -> season "2026-27"), so `metadata['season_year']` is the END
    year. `nba_raw.br_rosters_current`, `BasketballRefRosterExtractor` and
    `roster_registry_processor` are all START-year keyed (2026 <-> "2026-27").
    This processor derives the year from the season STRING and ignores the
    metadata field. Do not "fix" it back to `+ 1`.

Version: 2.0
Created: 2026-01-06
Repaired: 2026-08-21 — v1.0 never successfully wrote a row (see
    `_transform_team_roster`); every BR roster row in BigQuery was written by
    the per-file `BasketballRefRosterProcessor` before `129a5bf9` (2026-01-13)
    routed roster files here.
"""

import json
import logging
from datetime import date, datetime, timezone

from google.cloud import bigquery, storage

from data_processors.raw.processor_base import ProcessorBase
from data_processors.raw.smart_idempotency_mixin import SmartIdempotencyMixin
from data_processors.raw.utils.name_utils import normalize_name
from shared.clients.bigquery_pool import get_bigquery_client
from shared.utils.bigquery_retry import QUOTA_RETRY, SERIALIZATION_RETRY

logger = logging.getLogger(__name__)


class BasketballRefRosterBatchProcessor(SmartIdempotencyMixin, ProcessorBase):
    """
    Batch processor for Basketball Reference season rosters.

    Reads all 30 team files from GCS and processes them in a single
    BigQuery MERGE operation for maximum efficiency.

    Writes the SAME rows `BasketballRefRosterProcessor` writes, by design: both
    target `nba_raw.br_rosters_current`, and a divergence between them shows up
    as a silent no-op rather than an error. See `_transform_team_roster` for the
    column parity and `_execute_merge` for the MATCHED-clause parity -- the
    second is the easier one to lose, because a hash gate looks like a pure
    optimisation and is actually a change to what `last_scraped_date` means.
    """

    #: Must match `BasketballRefRosterProcessor.HASH_FIELDS` — the two writers
    #: share a target table, so a different hash basis would make every row look
    #: changed on the next run by the other processor.
    HASH_FIELDS = [
        'season_year',
        'team_abbrev',
        'player_full_name',
        'position',
        'jersey_number',
        'height',
        'weight',
        'birth_date',
        'college',
        'experience_years',
    ]

    def __init__(self):
        super().__init__()
        self.processor_name = "br_roster_batch_processor"
        self.team_data = []  # Will hold all team rosters
        self.gcs_client = storage.Client()
        # Use connection pool for BigQuery (reduces connection overhead by 40%+)
        self.bq_client = get_bigquery_client('nba-props-platform')

    def load_data(self) -> None:
        """Load all team roster files for the season from GCS."""
        # Extract season from metadata
        metadata = self.opts.get('metadata', {})
        season = metadata.get('season')

        if not season:
            raise ValueError("Season required for batch processing (should be in metadata)")

        logger.info(f"📦 Loading batch: season={season}")

        # GCS configuration
        bucket_name = self.opts.get('bucket', 'nba-scraped-data')
        prefix = f'basketball-ref/season-rosters/{season}/'

        # List all files in season directory
        bucket = self.gcs_client.bucket(bucket_name)
        blobs = bucket.list_blobs(prefix=prefix)

        team_count = 0
        for blob in blobs:
            # Skip non-JSON files and completion markers
            if not blob.name.endswith('.json') or blob.name.endswith('_COMPLETE.json'):
                continue

            # Extract team abbreviation from filename
            team_abbr = blob.name.split('/')[-1].replace('.json', '')

            # Download and parse roster data
            try:
                content = blob.download_as_text()
                team_roster = json.loads(content)

                # Transform team roster to BigQuery rows
                self._transform_team_roster(team_roster, team_abbr, season, blob.name)
                team_count += 1

            except Exception as e:
                logger.error(f"Failed to load roster for {team_abbr}: {e}")
                # Continue with other teams even if one fails

        logger.info(f"✅ Loaded {team_count} teams, {len(self.team_data)} total players")

        if team_count < 30:
            logger.warning(f"⚠️ Expected 30 teams, found {team_count}")

        # Set self.raw_data for ProcessorBase validation
        self.raw_data = self.team_data

        self.stats['teams_loaded'] = team_count
        self.stats['players_loaded'] = len(self.team_data)

    def transform_data(self) -> None:
        """Rows are built during load_data(); this only stamps the idempotency hash."""
        self.transformed_data = self.raw_data
        if self.transformed_data:
            self.add_data_hash()

    def _transform_team_roster(self, roster_data: dict, team_abbr: str, season: str,
                               source_file_path: str = None):
        """
        Transform Basketball Reference roster data to the br_rosters_current schema.

        ⚠️ This MUST stay field-for-field identical to
        `BasketballRefRosterProcessor.transform_data`. Until 2026-08-21 it was not:
        it emitted `player_name` / `player_name_ascii` / `last_name` / `suffix`
        (no such columns), omitted the REQUIRED `season_display`,
        `player_full_name`, `player_last_name` and `player_normalized`, and set
        `season_year = start_year + 1` while the table, the path extractor and the
        registry reader all use the START year. The MERGE could not parse, so this
        processor never wrote a row. BR rosters went stale on 2026-01-13, the day
        `129a5bf9` routed roster files here.

        Args:
            roster_data: Parsed JSON from GCS file
            team_abbr: Team abbreviation from the file name (e.g., "LAL")
            season: Season string (e.g., "2023-24")
            source_file_path: GCS object name, for provenance
        """
        # "2025-26" -> 2025. START year, matching br_rosters_current, the path
        # extractor and roster_registry_processor. Note metadata['season_year']
        # from the scraper backfill is the END year (2026) and is NOT used here.
        season_year = int(season.split('-')[0])
        today = date.today().isoformat()

        # Prefer the abbreviation the scraper recorded; fall back to the filename.
        team_abbrev = roster_data.get('team_abbrev') or team_abbr

        for player in roster_data.get('players', []):
            full_name = player.get('full_name')
            if not full_name:
                logger.warning(f"Skipping player without name on {team_abbrev}: {player}")
                self.stats['players_skipped'] = self.stats.get('players_skipped', 0) + 1
                continue

            self.team_data.append({
                'season_year': season_year,
                'season_display': season,
                'team_abbrev': team_abbrev,

                # Player identity
                'player_full_name': full_name,
                'player_last_name': player.get('last_name', ''),
                'player_normalized': player.get('normalized', ''),
                'player_lookup': normalize_name(full_name),

                # Player details (strings, as the scraper emits them)
                'position': player.get('position'),
                'jersey_number': player.get('jersey_number'),
                'height': player.get('height'),
                'weight': player.get('weight'),

                # The BR roster scraper does not emit these; kept for schema parity.
                'birth_date': player.get('birth_date'),
                'college': player.get('college'),
                'experience_years': None,

                # Tracking. first_seen_date is REQUIRED and is a DATE, not a
                # TIMESTAMP; the MERGE preserves the existing value on match.
                'first_seen_date': today,
                'last_scraped_date': today,
                'source_file_path': source_file_path,
                'processed_at': datetime.now(timezone.utc).isoformat(),
            })

    def save_data(self) -> None:
        """Save all teams in a single MERGE operation."""
        rows = self.transformed_data or self.team_data
        if not rows:
            logger.warning("No data to save")
            self.stats['rows_inserted'] = 0
            return

        project = self.opts.get('project') or self.opts.get('project_id') or 'nba-props-platform'
        dataset = 'nba_raw'

        target_table_id = f"{project}.{dataset}.br_rosters_current"
        temp_table_id = f"{project}.{dataset}.br_rosters_temp_batch_{self.run_id}"

        logger.info(f"Creating temp table: {temp_table_id}")

        # Derive the temp schema from the target rather than restating it. The
        # hand-written copy this replaced had drifted away from the real table
        # and the MERGE could not parse.
        target_table = self.bq_client.get_table(target_table_id)

        job_config = bigquery.LoadJobConfig(
            schema=target_table.schema,
            autodetect=False,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        )

        try:
            load_job = self.bq_client.load_table_from_json(
                rows,
                temp_table_id,
                job_config=job_config
            )
            load_job.result()  # Wait for completion

            logger.info(f"✅ Loaded {len(rows)} rows to {temp_table_id}")

            # Execute MERGE for all teams (SINGLE OPERATION)
            self._execute_merge(temp_table_id, target_table_id)

            # Track stats
            self.stats['rows_inserted'] = self.stats.get('rows_merged', 0)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to save data: {error_msg}")

            # Update stats for failure tracking
            self.stats['rows_inserted'] = 0

            raise

        finally:
            # Clean up temp table
            try:
                self.bq_client.delete_table(temp_table_id, not_found_ok=True)
                logger.info(f"✅ Cleaned up temp table: {temp_table_id}")
            except Exception as e:
                logger.warning(f"Failed to delete temp table: {e}")

    def _execute_merge(self, temp_table_id: str, target_table_id: str):
        """
        Execute a single MERGE for all 30 teams (the point of this processor).

        Column list is kept in lockstep with
        `BasketballRefRosterProcessor.save_data`; `first_seen_date` is preserved
        for existing players and only set on insert.
        """
        merge_query = f"""
        MERGE `{target_table_id}` AS target
        USING `{temp_table_id}` AS source
        ON target.season_year = source.season_year
           AND target.team_abbrev = source.team_abbrev
           AND target.player_lookup = source.player_lookup

        -- UNCONDITIONAL, exactly like BasketballRefRosterProcessor. Do NOT add a
        -- `AND source.data_hash != target.data_hash` gate here, however tempting
        -- the DML saving looks on a ~600-row table:
        --
        --   * `nba_reference` reads this table by DATE, not by content.
        --     `BRRosterSource.get_roster_players` runs
        --     `WHERE last_scraped_date = @data_date` and treats a non-empty
        --     result as a full match. Under a hash gate only the handful of
        --     players who CHANGED that day carry today's date, so the registry
        --     would silently seed itself from 3 players and report success.
        --   * `data_hash` is NULL on 75 legacy rows, and `!=` against NULL is
        --     NULL, so those rows would never be updated and never repaired.
        WHEN MATCHED THEN
          UPDATE SET
            season_display = source.season_display,
            player_full_name = source.player_full_name,
            player_last_name = source.player_last_name,
            player_normalized = source.player_normalized,
            position = source.position,
            jersey_number = source.jersey_number,
            height = source.height,
            weight = source.weight,
            birth_date = source.birth_date,
            college = source.college,
            experience_years = source.experience_years,
            last_scraped_date = source.last_scraped_date,
            source_file_path = source.source_file_path,
            processed_at = source.processed_at,
            data_hash = source.data_hash

        WHEN NOT MATCHED THEN
          INSERT (
            season_year, season_display, team_abbrev,
            player_full_name, player_last_name, player_normalized, player_lookup,
            position, jersey_number, height, weight, birth_date, college, experience_years,
            first_seen_date, last_scraped_date, source_file_path, processed_at, data_hash
          )
          VALUES (
            source.season_year, source.season_display, source.team_abbrev,
            source.player_full_name, source.player_last_name, source.player_normalized, source.player_lookup,
            source.position, source.jersey_number, source.height, source.weight,
            source.birth_date, source.college, source.experience_years,
            COALESCE(source.first_seen_date, source.last_scraped_date),
            source.last_scraped_date, source.source_file_path, source.processed_at, source.data_hash
          )
        """

        logger.info(f"Executing MERGE from {temp_table_id} to {target_table_id}")

        @QUOTA_RETRY
        @SERIALIZATION_RETRY
        def execute_merge_with_retry():
            query_job = self.bq_client.query(merge_query)
            query_job.result()  # Wait for completion
            return query_job

        query_job = execute_merge_with_retry()

        # `result().total_rows` is 0 for DML — the affected count lives on the job.
        rows_affected = query_job.num_dml_affected_rows or 0

        logger.info(f"✅ MERGE complete - {rows_affected} rows affected")

        self.stats['rows_merged'] = rows_affected
        self.stats['teams_processed'] = len(
            set(row['team_abbrev'] for row in (self.transformed_data or self.team_data))
        )

    def validate_data(self) -> None:
        """Validate that we loaded a reasonable number of teams and players."""
        teams_loaded = self.stats.get('teams_loaded', 0)
        players_loaded = self.stats.get('players_loaded', 0)

        if teams_loaded < 25:
            logger.warning(f"⚠️ Only loaded {teams_loaded} teams (expected 30)")

        if players_loaded < 300:  # Expect ~10-15 players per team
            logger.warning(f"⚠️ Only loaded {players_loaded} players (seems low)")

        logger.info(f"Validation: {teams_loaded} teams, {players_loaded} players")
