"""Schema and writer-parity tests for `BasketballRefRosterBatchProcessor`.

WHY THESE EXIST
---------------
This processor shipped in January 2026 and NEVER successfully wrote a row. It
emitted `player_name` / `player_name_ascii` / `last_name` / `suffix` (no such
columns on `nba_raw.br_rosters_current`), omitted four REQUIRED columns, put a
TIMESTAMP into a REQUIRED DATE, and computed `season_year = start_year + 1`
while the table, the path extractor and the registry reader all use the START
year. Commit 129a5bf9 (2026-01-13) routed BR roster files here from the
schema-correct per-file `BasketballRefRosterProcessor`; BR data went stale that
same day and the player registry had no 2026-27 rows seven months later.

The defect was invisible because nothing compared the two writers, and nothing
compared either of them to the table. These tests do both, offline:

  * TARGET_SCHEMA is a frozen copy of the live BigQuery schema (read
    2026-08-21). If the table changes, one of these tests fails and the frozen
    copy has to be updated deliberately.
  * The parity tests assert the batch writer emits the same fields, with the
    same values, as the per-file writer for the same input.
"""

import datetime as dt
from unittest import mock

import pytest


# Frozen from `bq.get_table('nba-props-platform.nba_raw.br_rosters_current')`
# on 2026-08-21: (name, type, mode).
TARGET_SCHEMA = [
    ('season_year', 'INTEGER', 'REQUIRED'),
    ('season_display', 'STRING', 'REQUIRED'),
    ('team_abbrev', 'STRING', 'REQUIRED'),
    ('player_full_name', 'STRING', 'REQUIRED'),
    ('player_last_name', 'STRING', 'REQUIRED'),
    ('player_normalized', 'STRING', 'REQUIRED'),
    ('player_lookup', 'STRING', 'REQUIRED'),
    ('position', 'STRING', 'NULLABLE'),
    ('jersey_number', 'STRING', 'NULLABLE'),
    ('height', 'STRING', 'NULLABLE'),
    ('weight', 'STRING', 'NULLABLE'),
    ('birth_date', 'STRING', 'NULLABLE'),
    ('college', 'STRING', 'NULLABLE'),
    ('experience_years', 'INTEGER', 'NULLABLE'),
    ('first_seen_date', 'DATE', 'REQUIRED'),
    ('last_scraped_date', 'DATE', 'NULLABLE'),
    ('source_file_path', 'STRING', 'NULLABLE'),
    ('processed_at', 'TIMESTAMP', 'NULLABLE'),
    ('data_hash', 'STRING', 'NULLABLE'),
]
COLUMNS = {n for n, _, _ in TARGET_SCHEMA}
REQUIRED = {n for n, _, m in TARGET_SCHEMA if m == 'REQUIRED'}

# Exactly what `scrapers/basketball_ref/br_season_roster.py` emits per player.
# It does NOT emit birth_date, college or experience.
SCRAPED_PLAYER = {
    'jersey_number': '11',
    'full_name': 'Trae Young',
    'full_name_ascii': 'Trae Young',
    'last_name': 'Young',
    'normalized': 'trae young',
    'suffix': '',
    'position': 'PG',
    'height': '6-1',
    'weight': '164',
}


@pytest.fixture
def processor():
    with mock.patch('google.cloud.storage.Client'), \
            mock.patch('shared.clients.bigquery_pool.get_bigquery_client'):
        from data_processors.raw.basketball_ref import br_roster_batch_processor as m
        p = m.BasketballRefRosterBatchProcessor()
    p.stats = {}
    p.team_data = []
    return p


def roster(*players, team='ATL'):
    return {'team_abbrev': team, 'season': '2026-27', 'players': list(players)}


def transform(processor, *players, team='ATL', season='2026-27'):
    processor._transform_team_roster(
        roster(*players, team=team), team, season,
        f'basketball-ref/season-rosters/{season}/{team}.json')
    return processor.team_data


# --------------------------------------------------------------------------- #
# Schema alignment — the bug that made this processor a no-op for seven months
# --------------------------------------------------------------------------- #

class TestSchemaAlignment:

    def test_emits_no_column_that_does_not_exist(self, processor):
        row = transform(processor, SCRAPED_PLAYER)[0]
        assert set(row) - COLUMNS - {'data_hash'} == set()

    def test_emits_every_required_column(self, processor):
        row = transform(processor, SCRAPED_PLAYER)[0]
        assert REQUIRED - set(row) == set()

    def test_no_required_column_is_null_or_empty(self, processor):
        row = transform(processor, SCRAPED_PLAYER)[0]
        empty = {k for k in REQUIRED if row.get(k) in (None, '')}
        assert empty == set()

    def test_emits_every_column_the_table_has(self, processor):
        """A missing NULLABLE column is not an error, but silently dropping one
        (e.g. `source_file_path`, which is the only provenance the table keeps)
        is the kind of gap nobody notices. Assert full coverage."""
        row = transform(processor, SCRAPED_PLAYER)[0]
        assert COLUMNS - set(row) - {'data_hash'} == set()

    def test_date_columns_are_dates_not_timestamps(self, processor):
        """`first_seen_date` is a REQUIRED DATE. v1.0 put `CURRENT_TIMESTAMP()`
        there, which is a load error, not a coercion."""
        row = transform(processor, SCRAPED_PLAYER)[0]
        for col in ('first_seen_date', 'last_scraped_date'):
            dt.date.fromisoformat(row[col])          # raises if it is a timestamp

    def test_processed_at_is_a_timestamp(self, processor):
        row = transform(processor, SCRAPED_PLAYER)[0]
        assert 'T' in row['processed_at']


# --------------------------------------------------------------------------- #
# Season-year convention — two conventions meet in this file
# --------------------------------------------------------------------------- #

class TestSeasonYearConvention:

    def test_season_year_is_the_start_year(self, processor):
        """`br_rosters_current` pairs season_year=2025 with '2025-26'. v1.0 used
        `start + 1`, so every row it tried to write was keyed to the wrong
        season — including against the registry reader and the path extractor."""
        row = transform(processor, SCRAPED_PLAYER, season='2026-27')[0]
        assert row['season_year'] == 2026
        assert row['season_display'] == '2026-27'

    def test_metadata_season_year_is_ignored(self, processor):
        """The scraper backfill publishes `season_year` as the ENDING year
        (2027 for 2026-27). The transform must derive from the season STRING."""
        processor.opts = {'metadata': {'season': '2026-27', 'season_year': 2027}}
        row = transform(processor, SCRAPED_PLAYER, season='2026-27')[0]
        assert row['season_year'] == 2026


# --------------------------------------------------------------------------- #
# Parity with the per-file writer — they share a table and a MERGE key
# --------------------------------------------------------------------------- #

class TestWriterParity:

    def _per_file_row(self):
        """Reproduce `BasketballRefRosterProcessor.transform_data` for one
        player, without instantiating it (its __init__ builds a BQ client)."""
        from data_processors.raw.utils.name_utils import normalize_name
        p = SCRAPED_PLAYER
        return {
            'season_year': 2026,
            'season_display': '2026-27',
            'team_abbrev': 'ATL',
            'player_full_name': p.get('full_name'),
            'player_last_name': p.get('last_name', ''),
            'player_normalized': p.get('normalized', ''),
            'player_lookup': normalize_name(p.get('full_name', '')),
            'position': p.get('position'),
            'jersey_number': p.get('jersey_number'),
            'height': p.get('height'),
            'weight': p.get('weight'),
            'birth_date': p.get('birth_date'),
            'college': p.get('college'),
            'experience_years': None,
        }

    def test_identity_and_detail_fields_match_the_per_file_writer(self, processor):
        row = transform(processor, SCRAPED_PLAYER)[0]
        for k, v in self._per_file_row().items():
            assert row[k] == v, f"{k}: batch={row[k]!r} per-file={v!r}"

    def test_player_lookup_matches_the_existing_merge_key(self, processor):
        """The MERGE joins on player_lookup. The 3,250 rows already in the table
        were written as `normalize_name(full_name)` ('traeyoung'), NOT as the
        scraper's `normalized` field ('trae young'), which is what v1.0 used —
        so v1.0 would have duplicated every player had it ever run."""
        row = transform(processor, SCRAPED_PLAYER)[0]
        assert row['player_lookup'] == 'traeyoung'
        assert row['player_normalized'] == 'trae young'

    def test_hash_fields_match_the_per_file_processor(self):
        from data_processors.raw.basketball_ref.br_roster_batch_processor import (
            BasketballRefRosterBatchProcessor)
        from data_processors.raw.basketball_ref.br_roster_processor import (
            BasketballRefRosterProcessor)
        assert (BasketballRefRosterBatchProcessor.HASH_FIELDS
                == BasketballRefRosterProcessor.HASH_FIELDS)

    def test_hash_is_computable_from_an_emitted_row(self, processor):
        """`compute_data_hash` raises on a MISSING key, so every HASH_FIELD has
        to be present in the row the transform produces."""
        row = transform(processor, SCRAPED_PLAYER)[0]
        assert isinstance(processor.compute_data_hash(row), str)


# --------------------------------------------------------------------------- #
# The MERGE contract the registry reader depends on
# --------------------------------------------------------------------------- #

class TestMergeContract:

    def _merge_sql(self):
        """Source of `_execute_merge` with SQL comment lines stripped.

        The comments explain why the hash gate must not come back and therefore
        quote the exact predicate these tests forbid.
        """
        import inspect
        from data_processors.raw.basketball_ref.br_roster_batch_processor import (
            BasketballRefRosterBatchProcessor)
        src = inspect.getsource(BasketballRefRosterBatchProcessor._execute_merge)
        return '\n'.join(ln for ln in src.split('\n')
                         if not ln.lstrip().startswith('--'))

    def test_matched_clause_is_unconditional(self):
        """`BRRosterSource.get_roster_players` selects
        `WHERE last_scraped_date = @data_date` and treats a non-empty result as
        a full match. If the MERGE only updates CHANGED rows, only the handful
        of players who changed that day carry today's date — so the registry
        seeds from a few players and reports success. It must update every
        matched row every run, exactly like the per-file writer.

        A NULL `data_hash` (75 legacy rows have one) would also make a
        `!=` predicate NULL, freezing those rows permanently."""
        sql = self._merge_sql()
        assert 'WHEN MATCHED THEN' in sql
        assert 'data_hash != target.data_hash' not in sql

    def test_merge_key_is_season_team_player(self):
        sql = self._merge_sql()
        for key in ('season_year', 'team_abbrev', 'player_lookup'):
            assert f'target.{key} = source.{key}' in sql

    def test_first_seen_date_is_not_updated_on_match(self):
        """It is set once, on insert. Refreshing it every day would erase the
        only record of when a player joined a roster."""
        sql = self._merge_sql()
        update = sql.split('WHEN MATCHED THEN')[1].split('WHEN NOT MATCHED')[0]
        assert 'first_seen_date' not in update

    def test_last_scraped_date_is_updated_on_match(self):
        sql = self._merge_sql()
        update = sql.split('WHEN MATCHED THEN')[1].split('WHEN NOT MATCHED')[0]
        assert 'last_scraped_date = source.last_scraped_date' in update


# --------------------------------------------------------------------------- #
# Input robustness
# --------------------------------------------------------------------------- #

class TestInputHandling:

    def test_nameless_player_is_skipped_not_written_as_empty(self, processor):
        """`player_full_name` is REQUIRED; an empty string would fail the load
        for the whole 600-row batch, taking all 30 teams down with it."""
        rows = transform(processor, {'position': 'SG'}, SCRAPED_PLAYER)
        assert len(rows) == 1
        assert processor.stats['players_skipped'] == 1

    def test_team_abbrev_prefers_the_scraped_value(self, processor):
        processor._transform_team_roster(
            roster(SCRAPED_PLAYER, team='BRK'), 'WRONG', '2026-27', 'p.json')
        assert processor.team_data[0]['team_abbrev'] == 'BRK'

    def test_team_abbrev_falls_back_to_the_filename(self, processor):
        processor._transform_team_roster(
            {'players': [SCRAPED_PLAYER]}, 'BRK', '2026-27', 'p.json')
        assert processor.team_data[0]['team_abbrev'] == 'BRK'

    def test_empty_roster_produces_no_rows(self, processor):
        assert transform(processor) == []


# --------------------------------------------------------------------------- #
# The --current-season flag on the backfill job
# --------------------------------------------------------------------------- #

class TestCurrentSeasonResolution:
    """`br-rosters-batch-daily` passes `--current-season` so no scheduler ever
    carries a hardcoded year again. The job it replaced was created with
    `--seasons=2025` in January 2026 and therefore re-scraped the 2024-25
    rosters every morning for six months. The flag resolves to the ENDING year,
    matching the scraper's convention."""

    @pytest.mark.parametrize('today,expected_ending_year', [
        (dt.date(2026, 9, 30), 2026),    # off-season: still 2025-26
        (dt.date(2026, 10, 1), 2027),    # season tagging flips on Oct 1
        (dt.date(2026, 10, 20), 2027),   # opening night
        (dt.date(2027, 4, 15), 2027),    # late season, calendar year rolled
    ])
    def test_resolution(self, today, expected_ending_year):
        from shared.utils.season_utils import get_current_season_year
        assert get_current_season_year(today) + 1 == expected_ending_year

    def test_ending_year_maps_back_to_the_gcs_season_string(self):
        """The scraper builds its GCS path as f"{year-1}-{year[2:]}"."""
        year = 2027
        assert f"{year - 1}-{str(year)[2:]}" == '2026-27'

    def test_flag_exists_on_the_backfill_job(self):
        """Guards against the flag being dropped while the catalog still sends
        it — argparse would exit 2 and the scheduler would still report success,
        because `:run` only creates the execution."""
        import importlib.util
        from pathlib import Path
        p = Path('backfill_jobs/scrapers/br_rosters/br_rosters_scraper_backfill.py')
        src = p.read_text()
        assert '"--current-season"' in src
        assert 'args.current_season' in src
