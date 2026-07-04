"""Regression tests for the model_bb_candidates writer (measurement-infra Component 2).

The bug class these guard against (2026-07-04): `_collect_all_model_candidates` emitted
Python lists into STRING columns (qualifying_subsets, filters_passed/failed,
observation_flags) — any non-empty one fails the WHOLE load job, silently (the writer
swallowed the error), which is how ~2 months of provenance were lost. It also emitted
float into the INTEGER `star_teammates_out`, and read schema key names (home_away,
is_back_to_back) that the pipeline never sets (it sets is_home / rest_days) so those
columns were silently NULL.

The `test_every_emitted_field_type_conforms_to_schema` test is the one that would have
caught all of it — it validates every emitted value's Python type against the BQ schema
JSON, exactly what a load-type round-trip does, but without needing BigQuery.
"""
import json
import os
from types import SimpleNamespace

from data_processors.publishing.signal_best_bets_exporter import SignalBestBetsExporter

SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "schemas", "model_bb_candidates.json"
)

# BQ column type -> acceptable Python types for a non-NULL value.
_TYPE_OK = {
    "STRING": (str,),
    "INTEGER": (int,),
    "FLOAT": (float, int),
    "BOOLEAN": (bool,),
    "TIMESTAMP": (str,),
    "DATE": (str,),
    "INT64": (int,),
    "FLOAT64": (float, int),
}


def _load_schema():
    with open(SCHEMA_PATH) as f:
        return {field["name"]: field for field in json.load(f)}


def _collect(candidates):
    # _collect_all_model_candidates does not touch self / any client, so bypass __init__.
    exporter = SignalBestBetsExporter.__new__(SignalBestBetsExporter)
    results = {"catboost_v12_noveg": SimpleNamespace(candidates=candidates)}
    return exporter._collect_all_model_candidates(results, "2026-01-10")


def _sample_candidate(**overrides):
    """A candidate dict shaped like real pipeline output (the mismatched key names +
    list-typed values that broke the load)."""
    base = {
        "player_lookup": "lebronjames",
        "game_id": "20260110_LAL_BOS",
        "system_id": "catboost_v12_noveg",
        "player_name": "LeBron James",
        "team_abbr": "LAL",
        "opponent_team_abbr": "BOS",
        "predicted_points": 25.3,
        "line_value": 27.5,
        "recommendation": "UNDER",
        "edge": 2.2,
        "confidence_score": 0.61,
        "composite_score": 1.4,
        "signal_count": 4,
        "real_signal_count": 2,
        "signal_tags": ["home_under", "b2b_fatigue_under"],  # REPEATED -> stays a list
        "signal_rescued": False,
        # Pipeline key names (the fix maps these to home_away / is_back_to_back):
        "is_home": True,
        "rest_days": 0,
        "star_teammates_out": 2.0,  # float -> must become INTEGER
        # List-typed values destined for STRING columns (the load-killer):
        "qualifying_subsets": [{"subset": "low_line_under"}],
        "filters_passed": ["cold_fg_under", "high_book_std_under_block"],
        "filters_failed": [],
        "observation_flags": ["obs_low_variance"],
        "book_count": 7,
        "was_selected": True,
    }
    base.update(overrides)
    return base


def test_every_emitted_field_type_conforms_to_schema():
    schema = _load_schema()
    rows = _collect([_sample_candidate()])
    assert rows, "collect produced no rows"
    for row in rows:
        for name, val in row.items():
            assert name in schema, f"emitted column {name!r} is not in the BQ schema"
            field = schema[name]
            if val is None:
                continue
            if field.get("mode") == "REPEATED":
                assert isinstance(val, list), f"{name} is REPEATED but got {type(val).__name__}"
                continue
            if field["type"] in ("INTEGER", "FLOAT", "INT64", "FLOAT64"):
                # bool is a subclass of int; a bool in a numeric column is a bug.
                assert not isinstance(val, bool), f"{name} got bool in a numeric column"
            assert isinstance(val, _TYPE_OK[field["type"]]), (
                f"{name}={val!r} ({type(val).__name__}) does not fit BQ {field['type']}"
            )


def test_list_into_string_columns_are_json_serialized():
    row = _collect([_sample_candidate()])[0]
    assert isinstance(row["qualifying_subsets"], str) and row["qualifying_subsets"].startswith("[")
    assert isinstance(row["filters_passed"], str)
    assert isinstance(row["observation_flags"], str)
    # empty list -> None (clean NULL), never "[]"
    assert row["filters_failed"] is None


def test_missing_list_keys_are_none_not_empty_list():
    minimal = {
        "player_lookup": "x",
        "system_id": "m",
        "game_id": "g",
        "recommendation": "UNDER",
        "edge": 1.0,
    }
    row = _collect([minimal])[0]
    for col in ("qualifying_subsets", "filters_passed", "filters_failed", "observation_flags"):
        assert row[col] is None, f"{col} should be None, got {row[col]!r}"


def test_key_name_mappings_home_away_and_b2b():
    row = _collect([_sample_candidate(is_home=True, rest_days=0, star_teammates_out=2.0)])[0]
    assert row["home_away"] == "home"
    assert row["is_back_to_back"] is True  # 0 days rest = back-to-back
    assert row["star_teammates_out"] == 2 and isinstance(row["star_teammates_out"], int)

    away = _collect([_sample_candidate(is_home=False, rest_days=2)])[0]
    assert away["home_away"] == "away"
    assert away["is_back_to_back"] is False


def test_null_context_keys_stay_null():
    row = _collect([_sample_candidate(is_home=None, rest_days=None, star_teammates_out=None)])[0]
    assert row["home_away"] is None
    assert row["is_back_to_back"] is None
    assert row["star_teammates_out"] is None


def test_export_run_at_stamped_once_per_run():
    rows = _collect([_sample_candidate(), _sample_candidate(player_lookup="anthonydavis")])
    assert rows[0]["export_run_at"]
    assert rows[0]["export_run_at"] == rows[1]["export_run_at"], "export_run_at must be one stamp/run"


def test_book_count_persisted_as_int():
    row = _collect([_sample_candidate(book_count=9)])[0]
    assert row["book_count"] == 9 and isinstance(row["book_count"], int)
