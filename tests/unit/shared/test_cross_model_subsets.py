"""
Unit tests for cross-model subset definitions.

Tests classify_system_id() and build_system_id_sql_filter() from
shared/config/cross_model_subsets.py.

Run:
    pytest tests/unit/shared/test_cross_model_subsets.py -v

Coverage:
    pytest tests/unit/shared/test_cross_model_subsets.py --cov=shared.config.cross_model_subsets --cov-report=html
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

from shared.config.cross_model_subsets import (
    MODEL_FAMILIES,
    classify_system_id,
    build_system_id_sql_filter,
)


# ============================================================================
# TEST: classify_system_id — v9_mae family
# ============================================================================

class TestClassifyV9Mae:
    """Tests for v9_mae classification (exact match + catchall)."""

    def test_exact_match_catboost_v9(self):
        """Exact 'catboost_v9' matches v9_mae."""
        assert classify_system_id('catboost_v9') == 'v9_mae'

    def test_v9_catchall_with_feature_suffix(self):
        """V9 catchall: 'catboost_v9_33f_train...' falls through to v9_mae."""
        assert classify_system_id('catboost_v9_33f_train_something') == 'v9_mae'

    def test_v9_catchall_with_train_dates(self):
        """V9 catchall: registry-style name with training dates."""
        assert classify_system_id('catboost_v9_50f_huber_train20251102_20260131') == 'v9_mae'

    def test_v9_mae_does_not_match_prefix_of_q43(self):
        """catboost_v9_q43_* should NOT match v9_mae (should match v9_q43)."""
        result = classify_system_id('catboost_v9_q43_train1102_0131')
        assert result == 'v9_q43'
        assert result != 'v9_mae'

    def test_v9_mae_does_not_match_prefix_of_q45(self):
        """catboost_v9_q45_* should NOT match v9_mae (should match v9_q45)."""
        result = classify_system_id('catboost_v9_q45_train1102_0131')
        assert result == 'v9_q45'
        assert result != 'v9_mae'


# ============================================================================
# TEST: classify_system_id — v9_q43 family
# ============================================================================

class TestClassifyV9Q43:
    """Tests for v9_q43 classification (prefix match)."""

    def test_standard_v9_q43_model(self):
        """Standard v9 quantile 0.43 model name."""
        assert classify_system_id('catboost_v9_q43_train1102_0131') == 'v9_q43'

    def test_v9_q43_with_long_suffix(self):
        """V9 q43 with extended training metadata in name."""
        assert classify_system_id('catboost_v9_q43_train20251215_20260201_retrain') == 'v9_q43'


# ============================================================================
# TEST: classify_system_id — v9_q45 family
# ============================================================================

class TestClassifyV9Q45:
    """Tests for v9_q45 classification (prefix match)."""

    def test_standard_v9_q45_model(self):
        """Standard v9 quantile 0.45 model name."""
        assert classify_system_id('catboost_v9_q45_train1102_0131') == 'v9_q45'

    def test_v9_q45_with_long_suffix(self):
        """V9 q45 with extended training metadata."""
        assert classify_system_id('catboost_v9_q45_train20260111_20260222_20260223_001122') == 'v9_q45'


# ============================================================================
# TEST: classify_system_id — v9_low_vegas family
# ============================================================================

class TestClassifyV9LowVegas:
    """Tests for v9_low_vegas classification."""

    def test_standard_v9_low_vegas_model(self):
        """Standard v9 low-vegas model name."""
        assert classify_system_id('catboost_v9_low_vegas_train1102_0131') == 'v9_low_vegas'

    def test_v9_low_vegas_with_dates(self):
        """V9 low-vegas with full date range."""
        assert classify_system_id('catboost_v9_low_vegas_train20251215_20260201') == 'v9_low_vegas'


# ============================================================================
# TEST: classify_system_id — v12_q43 (noveg) family
# ============================================================================

class TestClassifyV12Q43Noveg:
    """Tests for v12_q43 classification (noveg quantile)."""

    def test_standard_v12_noveg_q43_model(self):
        """Standard v12 no-vegas quantile 0.43 model."""
        assert classify_system_id('catboost_v12_noveg_q43_train1102_0131') == 'v12_q43'

    def test_v12_noveg_q43_with_retrain_suffix(self):
        """V12 noveg q43 with extended retrain suffix."""
        assert classify_system_id('catboost_v12_noveg_q43_train20260111_20260222') == 'v12_q43'


# ============================================================================
# TEST: classify_system_id — v12_q45 (noveg) family
# ============================================================================

class TestClassifyV12Q45Noveg:
    """Tests for v12_q45 classification (noveg quantile)."""

    def test_standard_v12_noveg_q45_model(self):
        """Standard v12 no-vegas quantile 0.45 model."""
        assert classify_system_id('catboost_v12_noveg_q45_train1102_0131') == 'v12_q45'

    def test_v12_noveg_q45_with_retrain_suffix(self):
        """V12 noveg q45 with extended retrain suffix."""
        assert classify_system_id('catboost_v12_noveg_q45_train20260111_20260222') == 'v12_q45'


# ============================================================================
# TEST: classify_system_id — v12_vegas_q43 family
# ============================================================================

class TestClassifyV12VegasQ43:
    """Tests for v12_vegas_q43 classification (primary + alt pattern)."""

    def test_primary_pattern_catboost_v12_q43(self):
        """Primary pattern: catboost_v12_q43_*."""
        assert classify_system_id('catboost_v12_q43_train1102_0131') == 'v12_vegas_q43'

    def test_alt_pattern_catboost_v12_vegas_q43(self):
        """Alt pattern: catboost_v12_vegas_q43_*."""
        assert classify_system_id('catboost_v12_vegas_q43_train1102_0131') == 'v12_vegas_q43'

    def test_session_333_bug_regression(self):
        """Session 333 bug: catboost_v12_vegas_q43_train0104_0215 must NOT classify as v12_mae.

        This was a real production bug where the v12_mae catch-all was matching
        vegas quantile models because the alt_pattern check was missing or
        the ordering was wrong.
        """
        result = classify_system_id('catboost_v12_vegas_q43_train0104_0215')
        assert result == 'v12_vegas_q43', (
            f"Session 333 regression: expected 'v12_vegas_q43' but got '{result}'. "
            "The v12_mae catch-all must NOT swallow vegas quantile models."
        )

    def test_v12_vegas_q43_with_full_dates(self):
        """V12 vegas q43 with full date format."""
        assert classify_system_id('catboost_v12_vegas_q43_train20260111_20260222') == 'v12_vegas_q43'


# ============================================================================
# TEST: classify_system_id — v12_vegas_q45 family
# ============================================================================

class TestClassifyV12VegasQ45:
    """Tests for v12_vegas_q45 classification (primary + alt pattern)."""

    def test_primary_pattern_catboost_v12_q45(self):
        """Primary pattern: catboost_v12_q45_*."""
        assert classify_system_id('catboost_v12_q45_train1102_0131') == 'v12_vegas_q45'

    def test_alt_pattern_catboost_v12_vegas_q45(self):
        """Alt pattern: catboost_v12_vegas_q45_*."""
        assert classify_system_id('catboost_v12_vegas_q45_train1102_0131') == 'v12_vegas_q45'

    def test_v12_vegas_q45_with_full_dates(self):
        """V12 vegas q45 with full date format."""
        assert classify_system_id('catboost_v12_vegas_q45_train20260111_20260222') == 'v12_vegas_q45'


# ============================================================================
# TEST: classify_system_id — v12_mae family (catch-all)
# ============================================================================

class TestClassifyV12Mae:
    """Tests for v12_mae classification (broad catch-all)."""

    def test_bare_catboost_v12(self):
        """Bare 'catboost_v12' matches v12_mae catch-all."""
        assert classify_system_id('catboost_v12') == 'v12_mae'

    def test_v12_noveg_train_matches_v12_mae(self):
        """catboost_v12_noveg_train* (no quantile) matches v12_mae."""
        assert classify_system_id('catboost_v12_noveg_train20251102_20260131') == 'v12_mae'

    def test_v12_train_matches_v12_mae(self):
        """catboost_v12_train* (V12+vegas MAE) matches v12_mae."""
        assert classify_system_id('catboost_v12_train20251102_20260131') == 'v12_mae'

    def test_production_v12_model_name(self):
        """The actual production V12 model name from the registry."""
        result = classify_system_id(
            'catboost_v12_50f_huber_rsm50_train20251102-20260131_20260213_213149'
        )
        assert result == 'v12_mae'

    def test_v12_mae_does_not_catch_noveg_q43(self):
        """v12_mae must NOT catch noveg q43 models (ordering test)."""
        assert classify_system_id('catboost_v12_noveg_q43_train1102_0131') != 'v12_mae'

    def test_v12_mae_does_not_catch_noveg_q45(self):
        """v12_mae must NOT catch noveg q45 models (ordering test)."""
        assert classify_system_id('catboost_v12_noveg_q45_train1102_0131') != 'v12_mae'

    def test_v12_mae_does_not_catch_vegas_q43(self):
        """v12_mae must NOT catch vegas q43 models (ordering test)."""
        assert classify_system_id('catboost_v12_q43_train1102_0131') != 'v12_mae'

    def test_v12_mae_does_not_catch_vegas_q45(self):
        """v12_mae must NOT catch vegas q45 models (ordering test)."""
        assert classify_system_id('catboost_v12_q45_train1102_0131') != 'v12_mae'


# ============================================================================
# TEST: classify_system_id — Unknown / None cases
# ============================================================================

class TestClassifyUnknown:
    """Tests for unrecognized model IDs returning None."""

    def test_xgboost_returns_none(self):
        """Completely unknown model family returns None."""
        assert classify_system_id('xgboost_v1_something') is None

    def test_random_string_returns_none(self):
        """Random garbage string returns None."""
        assert classify_system_id('not_a_model') is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        assert classify_system_id('') is None

    def test_lightgbm_returns_none(self):
        """Another unknown model type."""
        assert classify_system_id('lightgbm_v3_train20260101') is None

    def test_partial_catboost_no_version_returns_none(self):
        """catboost without version number returns None."""
        assert classify_system_id('catboost_something') is None

    def test_catboost_v10_returns_none(self):
        """catboost_v10 (non-existent family) returns None."""
        assert classify_system_id('catboost_v10_train1102_0131') is None


# ============================================================================
# TEST: classify_system_id — Ordering / No Ambiguity
# ============================================================================

class TestClassifyNoAmbiguity:
    """Tests that known production model names classify uniquely and correctly.

    This validates that MODEL_FAMILIES ordering is correct: more specific
    patterns match before broader catch-alls.
    """

    KNOWN_PRODUCTION_MODELS = {
        # (system_id, expected_family)
        'catboost_v9': 'v9_mae',
        'catboost_v9_q43_train1102_0131': 'v9_q43',
        'catboost_v9_q45_train1102_0131': 'v9_q45',
        'catboost_v9_low_vegas_train1102_0131': 'v9_low_vegas',
        'catboost_v12_noveg_q43_train1102_0131': 'v12_q43',
        'catboost_v12_noveg_q45_train1102_0131': 'v12_q45',
        'catboost_v12_q43_train1102_0131': 'v12_vegas_q43',
        'catboost_v12_vegas_q43_train0104_0215': 'v12_vegas_q43',
        'catboost_v12_q45_train1102_0131': 'v12_vegas_q45',
        'catboost_v12_vegas_q45_train0104_0215': 'v12_vegas_q45',
        'catboost_v12_50f_huber_rsm50_train20251102-20260131_20260213_213149': 'v12_mae',
        'catboost_v12_noveg_train20251102_20260131': 'v12_mae',
        'catboost_v12_train20251102_20260131': 'v12_mae',
    }

    @pytest.mark.parametrize(
        'system_id,expected_family',
        list(KNOWN_PRODUCTION_MODELS.items()),
        ids=list(KNOWN_PRODUCTION_MODELS.keys()),
    )
    def test_known_model_classifies_correctly(self, system_id, expected_family):
        """Each known production model classifies to exactly one family."""
        assert classify_system_id(system_id) == expected_family

    def test_all_families_have_at_least_one_match(self):
        """Every MODEL_FAMILIES entry is reachable by at least one known model."""
        classified_families = set()
        for system_id in self.KNOWN_PRODUCTION_MODELS:
            family = classify_system_id(system_id)
            if family:
                classified_families.add(family)

        for family_key in MODEL_FAMILIES:
            assert family_key in classified_families, (
                f"Family '{family_key}' is defined in MODEL_FAMILIES but no known "
                "production model classifies into it. Add a test case."
            )


# ============================================================================
# TEST: classify_system_id — V9 catchall edge cases
# ============================================================================

class TestClassifyV9Catchall:
    """Tests for the V9 catchall fallback at the end of classify_system_id."""

    def test_v9_unknown_variant_falls_to_catchall(self):
        """An unknown V9 variant (not q43/q45/low_vegas) falls to v9_mae catchall."""
        assert classify_system_id('catboost_v9_experimental_train1102_0131') == 'v9_mae'

    def test_v9_with_feature_count_prefix_falls_to_catchall(self):
        """V9 with feature count in name falls to catchall."""
        assert classify_system_id('catboost_v9_33f_mae_train20260101_20260215') == 'v9_mae'

    def test_v9_exact_match_takes_priority_over_catchall(self):
        """Exact 'catboost_v9' matches via exact check, not the catchall."""
        # This is subtle: the exact match in MODEL_FAMILIES fires first,
        # but both paths lead to v9_mae. Verify the result is correct.
        assert classify_system_id('catboost_v9') == 'v9_mae'

    def test_v9_q43_matches_specific_not_catchall(self):
        """v9_q43 prefix match fires before the v9 catchall."""
        # If the catchall were hit instead, it would still return v9_mae.
        # But the actual path should be v9_q43 via prefix match.
        assert classify_system_id('catboost_v9_q43_anything') == 'v9_q43'


# ============================================================================
# TEST: build_system_id_sql_filter — no alias
# ============================================================================

class TestBuildSqlFilterNoAlias:
    """Tests for build_system_id_sql_filter() without a table alias."""

    def test_returns_parenthesized_string(self):
        """Output is wrapped in parentheses."""
        result = build_system_id_sql_filter()
        assert result.startswith('(')
        assert result.endswith(')')

    def test_contains_or_clauses(self):
        """Output contains OR-joined clauses."""
        result = build_system_id_sql_filter()
        assert ' OR ' in result

    def test_contains_exact_match_for_v9(self):
        """Output contains exact match clause for catboost_v9."""
        result = build_system_id_sql_filter()
        assert "system_id = 'catboost_v9'" in result

    def test_contains_like_for_prefix_families(self):
        """Output contains LIKE clauses for prefix-match families."""
        result = build_system_id_sql_filter()
        assert "system_id LIKE 'catboost_v9_q43_%'" in result
        assert "system_id LIKE 'catboost_v9_q45_%'" in result
        assert "system_id LIKE 'catboost_v12_noveg_q43_%'" in result
        assert "system_id LIKE 'catboost_v12_noveg_q45_%'" in result
        assert "system_id LIKE 'catboost_v12%'" in result

    def test_contains_alt_pattern_for_vegas_q43(self):
        """Output contains alt_pattern LIKE for v12_vegas_q43."""
        result = build_system_id_sql_filter()
        assert "system_id LIKE 'catboost_v12_vegas_q43_%'" in result

    def test_contains_alt_pattern_for_vegas_q45(self):
        """Output contains alt_pattern LIKE for v12_vegas_q45."""
        result = build_system_id_sql_filter()
        assert "system_id LIKE 'catboost_v12_vegas_q45_%'" in result

    def test_no_table_alias_prefix(self):
        """Without alias, column is just 'system_id' not 'X.system_id'."""
        result = build_system_id_sql_filter()
        # Should NOT contain a dot-prefixed system_id (unless part of a pattern string)
        assert '.system_id' not in result


# ============================================================================
# TEST: build_system_id_sql_filter — with alias
# ============================================================================

class TestBuildSqlFilterWithAlias:
    """Tests for build_system_id_sql_filter() with a table alias."""

    def test_alias_prefixes_all_columns(self):
        """When alias is provided, all system_id refs are prefixed."""
        result = build_system_id_sql_filter(alias='p')
        assert "p.system_id = 'catboost_v9'" in result
        assert "p.system_id LIKE 'catboost_v9_q43_%'" in result

    def test_alias_with_longer_name(self):
        """Alias can be a longer name like 'predictions'."""
        result = build_system_id_sql_filter(alias='predictions')
        assert "predictions.system_id = 'catboost_v9'" in result
        assert "predictions.system_id LIKE 'catboost_v12%'" in result

    def test_clause_count_matches_family_count(self):
        """Number of clauses should match families + alt patterns."""
        result = build_system_id_sql_filter(alias='t')
        # Count expected clauses: one per family + one per alt_pattern
        expected_clauses = len(MODEL_FAMILIES)
        for info in MODEL_FAMILIES.values():
            if 'alt_pattern' in info:
                expected_clauses += 1
        actual_clauses = result.count(' OR ') + 1
        assert actual_clauses == expected_clauses


# ============================================================================
# TEST: MODEL_FAMILIES structure integrity
# ============================================================================

class TestModelFamiliesStructure:
    """Tests that MODEL_FAMILIES entries have required fields."""

    def test_all_families_have_pattern(self):
        """Every family must have a 'pattern' string."""
        for key, info in MODEL_FAMILIES.items():
            assert 'pattern' in info, f"Family '{key}' missing 'pattern'"
            assert isinstance(info['pattern'], str), f"Family '{key}' pattern is not a string"

    def test_all_families_have_exact_flag(self):
        """Every family must have an 'exact' boolean."""
        for key, info in MODEL_FAMILIES.items():
            assert 'exact' in info, f"Family '{key}' missing 'exact'"
            assert isinstance(info['exact'], bool), f"Family '{key}' exact is not a bool"

    def test_all_families_have_feature_set(self):
        """Every family must have a 'feature_set'."""
        for key, info in MODEL_FAMILIES.items():
            assert 'feature_set' in info, f"Family '{key}' missing 'feature_set'"

    def test_all_families_have_loss(self):
        """Every family must have a 'loss' type."""
        for key, info in MODEL_FAMILIES.items():
            assert 'loss' in info, f"Family '{key}' missing 'loss'"
            assert info['loss'] in ('mae', 'quantile'), (
                f"Family '{key}' has unknown loss '{info['loss']}'"
            )

    def test_family_count(self):
        """Sanity check: expect 9 families (update if families added/removed)."""
        assert len(MODEL_FAMILIES) == 9


# ============================================================================
# RUN TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
