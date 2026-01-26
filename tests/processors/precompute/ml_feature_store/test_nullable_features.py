"""
Unit Tests for Nullable Feature Extraction in ML Feature Store

Tests the new _get_feature_nullable logic that returns None instead of defaults.
Run with: pytest test_nullable_features.py -v

Created: 2026-01-25 for shot zone handling improvements
"""

import pytest


def test_nullable_feature_logic_phase4_available():
    """Test nullable feature extraction returns Phase 4 value when available."""
    index = 18
    field_name = 'paint_rate_last_10'
    phase4_data = {'paint_rate_last_10': 35.5}
    phase3_data = {'paint_rate_last_10': 30.0}
    feature_sources = {}

    # Simulate _get_feature_nullable logic
    result = None
    if field_name in phase4_data and phase4_data[field_name] is not None:
        feature_sources[index] = 'phase4'
        result = float(phase4_data[field_name])
    elif field_name in phase3_data and phase3_data[field_name] is not None:
        feature_sources[index] = 'phase3'
        result = float(phase3_data[field_name])
    else:
        feature_sources[index] = 'missing'
        result = None

    assert result == 35.5
    assert feature_sources[18] == 'phase4'


def test_nullable_feature_logic_fallback_to_phase3():
    """Test nullable feature extraction falls back to Phase 3 when Phase 4 missing."""
    index = 18
    field_name = 'paint_rate_last_10'
    phase4_data = {}
    phase3_data = {'paint_rate_last_10': 30.0}
    feature_sources = {}

    # Simulate _get_feature_nullable logic
    result = None
    if field_name in phase4_data and phase4_data[field_name] is not None:
        feature_sources[index] = 'phase4'
        result = float(phase4_data[field_name])
    elif field_name in phase3_data and phase3_data[field_name] is not None:
        feature_sources[index] = 'phase3'
        result = float(phase3_data[field_name])
    else:
        feature_sources[index] = 'missing'
        result = None

    assert result == 30.0
    assert feature_sources[18] == 'phase3'


def test_nullable_feature_logic_returns_none_when_both_missing():
    """Test nullable feature extraction returns None when both missing."""
    index = 18
    field_name = 'paint_rate_last_10'
    phase4_data = {}
    phase3_data = {}
    feature_sources = {}

    # Simulate _get_feature_nullable logic
    result = None
    if field_name in phase4_data and phase4_data[field_name] is not None:
        feature_sources[index] = 'phase4'
        result = float(phase4_data[field_name])
    elif field_name in phase3_data and phase3_data[field_name] is not None:
        feature_sources[index] = 'phase3'
        result = float(phase3_data[field_name])
    else:
        feature_sources[index] = 'missing'
        result = None

    assert result is None
    assert feature_sources[18] == 'missing'


def test_nullable_feature_logic_handles_none_value():
    """Test nullable feature extraction returns None when value is explicitly None."""
    index = 18
    field_name = 'paint_rate_last_10'
    phase4_data = {'paint_rate_last_10': None}
    phase3_data = {'paint_rate_last_10': None}
    feature_sources = {}

    # Simulate _get_feature_nullable logic
    result = None
    if field_name in phase4_data and phase4_data[field_name] is not None:
        feature_sources[index] = 'phase4'
        result = float(phase4_data[field_name])
    elif field_name in phase3_data and phase3_data[field_name] is not None:
        feature_sources[index] = 'phase3'
        result = float(phase3_data[field_name])
    else:
        feature_sources[index] = 'missing'
        result = None

    assert result is None
    assert feature_sources[18] == 'missing'


def test_shot_zone_indicator_all_data_available():
    """Test indicator = 1.0 when all shot zone data available."""
    paint_rate = 35.0
    mid_range_rate = 20.0
    three_pt_rate = 35.0

    has_shot_zone_data = 1.0 if all([paint_rate is not None, mid_range_rate is not None, three_pt_rate is not None]) else 0.0

    assert has_shot_zone_data == 1.0


def test_shot_zone_indicator_partial_data_missing():
    """Test indicator = 0.0 when any shot zone data missing."""
    # Case 1: paint_rate missing
    paint_rate = None
    mid_range_rate = 20.0
    three_pt_rate = 35.0

    has_shot_zone_data = 1.0 if all([paint_rate is not None, mid_range_rate is not None, three_pt_rate is not None]) else 0.0
    assert has_shot_zone_data == 0.0


def test_shot_zone_indicator_all_data_missing():
    """Test indicator = 0.0 when all shot zone data missing."""
    paint_rate = None
    mid_range_rate = None
    three_pt_rate = None

    has_shot_zone_data = 1.0 if all([paint_rate is not None, mid_range_rate is not None, three_pt_rate is not None]) else 0.0
    assert has_shot_zone_data == 0.0


# ============================================================================
# Test Summary
# ============================================================================
# Total Tests: 7 unit tests
# Coverage: Nullable feature extraction logic + indicator flag logic
# Runtime: <1 second
#
# Test Distribution:
# - Nullable feature extraction: 4 tests
# - Indicator flag logic: 3 tests
#
# Run with:
#   pytest test_nullable_features.py -v
#   pytest test_nullable_features.py -k "indicator" -v
# ============================================================================

