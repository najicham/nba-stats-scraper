"""Constructor contract for RosterRegistryProcessor.

Why this file is separate from test_roster_registry.py
------------------------------------------------------
That file's `processor` fixture ends with:

    proc.source_dates_used = {}

which CREATES an attribute the constructor never created. Every test in that
module therefore ran against an object production could never build, and all of
them passed while `get_current_roster_data()` died at
roster_registry_processor.py:183 on `self.source_dates_used.update(...)` in
every real run — the third independent blocker found on the Oct 1-19 roster seed
path, discovered 2026-08-22 by running the seed rehearsal rather than reading
the code.

The lesson is narrow and worth keeping: a fixture that repairs the object under
test converts a crash into a green suite. These tests assert what the
CONSTRUCTOR produces, and deliberately do not use that fixture.
"""

from unittest.mock import Mock, patch

import pytest

from data_processors.reference.player_reference.roster_registry_processor import (
    RosterRegistryProcessor,
)


@pytest.fixture
def bare_processor():
    """A processor built exactly as production builds it — nothing patched on after."""
    with patch(
        'data_processors.reference.player_reference.roster_registry_processor.bigquery.Client'
    ) as mock_client_class:
        mock_client_class.return_value = Mock()
        with patch(
            'data_processors.reference.base.registry_processor_base.UniversalPlayerIDResolver'
        ):
            return RosterRegistryProcessor(test_mode=True, strategy='merge')


def test_source_dates_used_exists_after_construction(bare_processor):
    """get_current_roster_data() calls .update() on this unconditionally."""
    assert hasattr(bare_processor, 'source_dates_used'), (
        "RosterRegistryProcessor.__init__ must create source_dates_used. "
        "roster_registry_processor.py:183 calls .update() on it with no guard, "
        "so a missing attribute is an AttributeError on every real run."
    )
    assert isinstance(bare_processor.source_dates_used, dict)


def test_source_dates_used_supports_update(bare_processor):
    """The exact call site that crashed — .update() on a fresh instance."""
    bare_processor.source_dates_used.update({
        'espn_roster_date': None,
        'nbacom_source_date': None,
        'br_scrape_date': None,
        'espn_matched': False,
        'nbacom_matched': False,
        'br_matched': False,
        'used_fallback': True,
    })
    assert bare_processor.source_dates_used['used_fallback'] is True


def test_attributes_the_run_path_reads_are_all_constructed(bare_processor):
    """Guard the whole class of bug, not just the one instance of it."""
    for attr in ('source_dates_used', 'processor_type', 'espn_handler',
                 'nba_handler', 'br_handler', 'gamebook_validator'):
        assert hasattr(bare_processor, attr), (
            f"__init__ did not create '{attr}'. If a test fixture assigns it, "
            f"that fixture is hiding a production crash."
        )


class TestTestModeIsolation:
    """--test-mode must isolate every table the processor WRITES.

    Until 2026-08-22 it isolated three of four. `self.table_name` honoured test
    mode, but RegistryOperations was constructed with the string literals
    "nba_reference.player_aliases" and "nba_reference.unresolved_player_names",
    so a --test-mode run wrote those two straight to production. The 2026-08-22
    seed rehearsal put 62 rows into the live unresolved_player_names table.

    The failure was quiet in the worst way: the scratch table stayed empty and
    nothing errored, which reads as "the write silently did nothing" rather than
    "the write went somewhere else."

    A test mode that isolates most tables is more dangerous than none, because
    it gets trusted. These assert on the objects that actually issue the writes,
    not on the base-class attributes — the base class was always correct; the
    caller ignored it.
    """

    def test_registry_ops_writes_are_isolated(self, bare_processor):
        ops = bare_processor.registry_ops
        for attr in ('table_name', 'alias_table_name', 'unresolved_table_name'):
            value = getattr(ops, attr)
            assert '_test_' in value, (
                f"RegistryOperations.{attr} = {value!r} in test mode. This object "
                f"performs writes, so a production table name here means "
                f"--test-mode writes to production."
            )

    def test_registry_ops_matches_the_base_class_attributes(self, bare_processor):
        """Guards the specific mistake: literals passed instead of attributes."""
        ops = bare_processor.registry_ops
        assert ops.table_name == bare_processor.table_name
        assert ops.alias_table_name == bare_processor.alias_table_name
        assert ops.unresolved_table_name == bare_processor.unresolved_table_name

    def test_gamebook_validator_reads_production_on_purpose(self, bare_processor):
        """Documented asymmetry — reads may cross into production, writes may not.

        The precedence check is meaningless against an empty test table, and the
        test-suffixed run-history table is never created, so pointing this at
        self.run_history_table would trip the validator's fail-closed path and
        block every rehearsal. If this ever changes, it must be a decision.
        """
        assert bare_processor.gamebook_validator.run_history_table == (
            'nba_reference.processor_run_history'
        )
