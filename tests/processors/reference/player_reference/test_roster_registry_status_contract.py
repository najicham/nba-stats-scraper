"""`status` must reflect what reached BigQuery, not that no exception escaped.

Background
----------
save_registry_data() reports write failures as DATA, not exceptions —
database_strategies.py:230 returns {'rows_processed': 0, 'errors': [...]} after
logging. process_daily_rosters() then set result['status'] = 'success'
unconditionally, never reading 'errors'.

The 2026-08-22 seed rehearsal hit this for real: the MERGE failed and the run
printed "Status: success, Records processed: 0", exit code 0.

Oct 1-19 is a one-shot gate. A write that fails while reporting success is the
most expensive failure mode available on this path, so these tests pin the
three cases apart: a clean write, a write that errored, and a write that
silently landed nothing.
"""

from datetime import date
from unittest.mock import Mock, patch

import pytest

from data_processors.reference.player_reference.roster_registry_processor import (
    RosterRegistryProcessor,
)


@pytest.fixture
def processor():
    with patch(
        'data_processors.reference.player_reference.roster_registry_processor.bigquery.Client'
    ) as mock_client_class:
        mock_client_class.return_value = Mock()
        with patch(
            'data_processors.reference.base.registry_processor_base.UniversalPlayerIDResolver'
        ):
            proc = RosterRegistryProcessor(test_mode=True, strategy='merge')
    # Both protection layers pass; we are testing what happens after them.
    proc.check_gamebook_precedence = Mock(return_value=(False, None))
    return proc


def run(proc, impl_result):
    proc._build_registry_for_season_impl = Mock(return_value=dict(impl_result))
    return proc.process_daily_rosters(
        season_year=2026, data_date=date(2026, 10, 5), allow_backfill=True
    )


def test_clean_write_is_success(processor):
    out = run(processor, {'records_created': 696, 'records_processed': 696, 'errors': []})
    assert out['status'] == 'success'


def test_write_error_is_failure_not_success(processor):
    """The exact rehearsal case: MERGE failed, zero rows, errors returned."""
    out = run(processor, {
        'records_created': 696,
        'records_processed': 0,
        'errors': ['MERGE mode (temp table) failed: No such field: universal_player_id'],
    })
    assert out['status'] == 'failed'
    assert 'universal_player_id' in out['reason']


def test_silent_zero_row_write_is_failure(processor):
    """Records built but none landed, and nothing reported an error."""
    out = run(processor, {'records_created': 696, 'records_processed': 0, 'errors': []})
    assert out['status'] == 'failed'
    assert '0' in out['reason']


def test_legitimately_empty_build_is_not_a_failure(processor):
    """Nothing to write is not the same as failing to write.

    Guards against over-correcting: a no-op run must stay 'success' or the gate
    becomes a false alarm.
    """
    out = run(processor, {'records_created': 0, 'records_processed': 0, 'errors': []})
    assert out['status'] == 'success'
