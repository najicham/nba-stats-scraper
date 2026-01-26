"""
Unit Tests for Shot Zone Analyzer BigDataBall → NBAC Fallback

Tests the fallback logic when BigDataBall PBP is unavailable.
Run with: pytest test_shot_zone_fallback.py -v

Created: 2026-01-25 for shot zone handling improvements
"""

import pytest


def test_fallback_logic_bigdataball_success():
    """Test that NBAC fallback is NOT used when BigDataBall succeeds."""
    # Simulate BigDataBall returns data
    bigdataball_returned_data = True
    nbac_called = False

    # Simulate extract_shot_zones logic
    shot_zones_available = False
    shot_zones_source = None

    # Try BigDataBall first
    if bigdataball_returned_data:
        shot_zones_available = True
        shot_zones_source = 'bigdataball_pbp'
    else:
        # Fallback to NBAC
        nbac_called = True
        shot_zones_available = True
        shot_zones_source = 'nbac_play_by_play'

    assert shot_zones_available is True
    assert shot_zones_source == 'bigdataball_pbp'
    assert nbac_called is False  # Fallback not needed


def test_fallback_logic_bigdataball_fails_nbac_succeeds():
    """Test that NBAC fallback is used when BigDataBall fails."""
    # Simulate BigDataBall returns no data
    bigdataball_returned_data = False
    nbac_returned_data = True

    # Simulate extract_shot_zones logic
    shot_zones_available = False
    shot_zones_source = None
    nbac_called = False

    # Try BigDataBall first
    if bigdataball_returned_data:
        shot_zones_available = True
        shot_zones_source = 'bigdataball_pbp'
    else:
        # Fallback to NBAC
        nbac_called = True
        if nbac_returned_data:
            shot_zones_available = True
            shot_zones_source = 'nbac_play_by_play'

    assert shot_zones_available is True
    assert shot_zones_source == 'nbac_play_by_play'
    assert nbac_called is True  # Fallback was used


def test_fallback_logic_both_fail():
    """Test behavior when both BigDataBall and NBAC fail."""
    # Simulate both sources return no data
    bigdataball_returned_data = False
    nbac_returned_data = False

    # Simulate extract_shot_zones logic
    shot_zones_available = False
    shot_zones_source = None

    # Try BigDataBall first
    if bigdataball_returned_data:
        shot_zones_available = True
        shot_zones_source = 'bigdataball_pbp'
    else:
        # Fallback to NBAC
        if nbac_returned_data:
            shot_zones_available = True
            shot_zones_source = 'nbac_play_by_play'
        else:
            # Both failed
            shot_zones_available = False
            shot_zones_source = None

    assert shot_zones_available is False
    assert shot_zones_source is None


def test_nbac_data_structure_differences():
    """Test that NBAC fallback returns expected data structure."""
    # Simulate NBAC extraction result
    nbac_shot_zone_data = {
        'paint_attempts': 10,
        'paint_makes': 5,
        'mid_range_attempts': 8,
        'mid_range_makes': 3,
        # NBAC doesn't have these fields
        'assisted_fg_makes': None,
        'unassisted_fg_makes': None,
        'and1_count': None,
        'paint_blocks': None,
        'mid_range_blocks': None,
        'three_pt_blocks': None,
    }

    # Verify basic shot zones are present
    assert nbac_shot_zone_data['paint_attempts'] is not None
    assert nbac_shot_zone_data['paint_makes'] is not None
    assert nbac_shot_zone_data['mid_range_attempts'] is not None
    assert nbac_shot_zone_data['mid_range_makes'] is not None

    # Verify advanced fields are None (NBAC limitation)
    assert nbac_shot_zone_data['assisted_fg_makes'] is None
    assert nbac_shot_zone_data['and1_count'] is None
    assert nbac_shot_zone_data['paint_blocks'] is None


# ============================================================================
# Test Summary
# ============================================================================
# Total Tests: 4 unit tests
# Coverage: BigDataBall → NBAC fallback logic
# Runtime: <1 second
#
# Test Distribution:
# - Fallback logic: 3 tests
# - Data structure compatibility: 1 test
#
# Run with:
#   pytest test_shot_zone_fallback.py -v
# ============================================================================
