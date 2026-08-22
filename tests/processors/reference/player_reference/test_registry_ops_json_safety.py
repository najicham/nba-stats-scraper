"""Records handed to load_table_from_json must contain no date objects.

insert_unresolved_names() took its type converter as an OPTIONAL argument.
normalizer.py:579 supplied it; registry_ops.py:144 did not. The second path put
raw datetime.date values on the wire, load_table_from_json raised "Object of
type date is not JSON serializable", and the exception was logged and
swallowed — so unresolved_player_names silently stayed empty.

Observed live in the 2026-08-22 seed rehearsal: the table finished a successful
run with 0 rows, immediately after the normalizer logged 62 unresolved
player-team combinations.

These tests pin the invariant at the boundary — whatever reaches
load_table_from_json must survive json.dumps — rather than pinning the
behaviour of any one caller.
"""

import json
from datetime import date, datetime

import pytest

from data_processors.reference.player_reference.operations.registry_ops import _json_safe


def test_date_becomes_iso_string():
    out = _json_safe({'last_seen_date': date(2026, 10, 5)})
    assert out['last_seen_date'] == '2026-10-05'


def test_datetime_keeps_its_time_component():
    """datetime subclasses date — checking date first would truncate."""
    out = _json_safe({'created_at': datetime(2026, 10, 5, 14, 30, 5)})
    assert out['created_at'] == '2026-10-05T14:30:05'
    assert 'T' in out['created_at']


def test_dates_inside_lists_are_converted():
    out = _json_safe({'example_games': [date(2026, 10, 5), date(2026, 10, 7)]})
    assert out['example_games'] == ['2026-10-05', '2026-10-07']


def test_is_idempotent():
    once = _json_safe({'last_seen_date': date(2026, 10, 5)})
    assert _json_safe(once) == once


def test_non_date_values_are_untouched():
    rec = {'normalized_lookup': 'lebronjames', 'occurrences': 3,
           'status': 'pending', 'reviewed_by': None, 'is_active': True}
    assert _json_safe(rec) == rec


def test_the_exact_record_shape_registry_ops_builds_is_serializable():
    """The literal dict from registry_ops.py:125-140, which broke the load."""
    record = {
        'normalized_lookup': 'someplayer',
        'first_seen_date': date.today(),
        'last_seen_date': date.today(),
        'team_abbr': 'LAL',
        'season': '2026-27',
        'occurrences': 1,
        'example_games': [],
        'status': 'pending',
        'resolution_type': None,
        'resolved_to_name': None,
        'notes': 'Found in espn but not in NBA.com canonical set',
        'reviewed_by': None,
        'reviewed_at': None,
        'created_at': datetime.now(),
        'processed_at': datetime.now(),
    }
    with pytest.raises(TypeError):
        json.dumps(record)          # the bug
    json.dumps(_json_safe(record))  # the fix
