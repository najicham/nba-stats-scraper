"""
Property-based tests for validation logic functions.

Uses Hypothesis to verify:
- Quality tier classification
- Completeness percentage calculations
- Data integrity checks
- Feature threshold validation
- Cross-table consistency logic
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Set, Optional


# =============================================================================
# Validation Data Structures (mirrors production code)
# =============================================================================

class ValidationStatus(Enum):
    """Status of a validation check."""
    COMPLETE = 'complete'
    PARTIAL = 'partial'
    MISSING = 'missing'
    BOOTSTRAP_SKIP = 'bootstrap_skip'
    NOT_APPLICABLE = 'not_applicable'
    ERROR = 'error'


@dataclass
class QualityDistribution:
    """Distribution of quality tiers."""
    gold: int = 0
    silver: int = 0
    bronze: int = 0
    poor: int = 0
    unusable: int = 0
    total: int = 0

    def __post_init__(self):
        self.total = self.gold + self.silver + self.bronze + self.poor + self.unusable

    def to_summary_string(self) -> str:
        return f"{self.gold}G {self.silver}S {self.bronze}B {self.poor}P {self.unusable}U"

    def production_ready_count(self) -> int:
        return self.gold + self.silver + self.bronze

    def has_issues(self) -> bool:
        return self.poor > 0 or self.unusable > 0


# Quality tier definitions (from production config)
QUALITY_TIERS = {
    'gold': {'min_score': 90, 'max_score': 100, 'production_ready': True},
    'silver': {'min_score': 75, 'max_score': 89, 'production_ready': True},
    'bronze': {'min_score': 60, 'max_score': 74, 'production_ready': True},
    'poor': {'min_score': 40, 'max_score': 59, 'production_ready': False},
    'unusable': {'min_score': 0, 'max_score': 39, 'production_ready': False},
}


# Feature thresholds (from production config)
FEATURE_THRESHOLDS = {
    'minutes_played': {'threshold': 99.0, 'critical': True},
    'usage_rate': {'threshold': 95.0, 'critical': True},
    'paint_attempts': {'threshold': 40.0, 'critical': False},
    'mid_range_attempts': {'threshold': 40.0, 'critical': False},
    'three_pt_attempts': {'threshold': 99.0, 'critical': True},
    'points': {'threshold': 99.5, 'critical': True},
    'fg_attempts': {'threshold': 99.0, 'critical': True},
    'rebounds': {'threshold': 99.0, 'critical': True},
    'assists': {'threshold': 99.0, 'critical': True},
}


# =============================================================================
# Validation Helper Functions
# =============================================================================

def get_quality_tier(score: float) -> str:
    """Determine quality tier from score."""
    if score >= 90:
        return 'gold'
    elif score >= 75:
        return 'silver'
    elif score >= 60:
        return 'bronze'
    elif score >= 40:
        return 'poor'
    else:
        return 'unusable'


def calculate_completeness_pct(actual: int, expected: int) -> float:
    """Calculate completeness percentage."""
    if expected <= 0:
        return 0.0
    return (actual / expected) * 100.0


def get_feature_threshold(feature: str) -> float:
    """Get threshold for a feature."""
    return FEATURE_THRESHOLDS.get(feature, {}).get('threshold', 95.0)


def is_critical_feature(feature: str) -> bool:
    """Check if a feature is critical."""
    return FEATURE_THRESHOLDS.get(feature, {}).get('critical', False)


def check_feature_coverage(coverage_pct: float, feature: str) -> bool:
    """Check if feature meets coverage threshold."""
    threshold = get_feature_threshold(feature)
    return coverage_pct >= threshold


# =============================================================================
# Strategies for Validation Testing
# =============================================================================

@composite
def quality_distribution(draw):
    """Generate a quality distribution."""
    return QualityDistribution(
        gold=draw(st.integers(min_value=0, max_value=100)),
        silver=draw(st.integers(min_value=0, max_value=50)),
        bronze=draw(st.integers(min_value=0, max_value=30)),
        poor=draw(st.integers(min_value=0, max_value=20)),
        unusable=draw(st.integers(min_value=0, max_value=10)),
    )


@composite
def player_set(draw, min_size=0, max_size=50):
    """Generate a set of player lookups."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    players = []
    for i in range(size):
        first = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=8))
        last = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=10))
        players.append(f"{first}{last}")
    return set(players)


# =============================================================================
# Quality Tier Tests
# =============================================================================

class TestQualityTierClassification:
    """Property tests for quality tier classification."""

    @given(st.floats(min_value=90.0, max_value=100.0, allow_nan=False))
    def test_gold_tier_range(self, score):
        """Scores 90-100 should be gold."""
        tier = get_quality_tier(score)
        assert tier == 'gold'

    @given(st.floats(min_value=75.0, max_value=89.99, allow_nan=False))
    def test_silver_tier_range(self, score):
        """Scores 75-89 should be silver."""
        tier = get_quality_tier(score)
        assert tier == 'silver'

    @given(st.floats(min_value=60.0, max_value=74.99, allow_nan=False))
    def test_bronze_tier_range(self, score):
        """Scores 60-74 should be bronze."""
        tier = get_quality_tier(score)
        assert tier == 'bronze'

    @given(st.floats(min_value=40.0, max_value=59.99, allow_nan=False))
    def test_poor_tier_range(self, score):
        """Scores 40-59 should be poor."""
        tier = get_quality_tier(score)
        assert tier == 'poor'

    @given(st.floats(min_value=0.0, max_value=39.99, allow_nan=False))
    def test_unusable_tier_range(self, score):
        """Scores 0-39 should be unusable."""
        tier = get_quality_tier(score)
        assert tier == 'unusable'

    @given(st.floats(min_value=0.0, max_value=100.0, allow_nan=False))
    def test_tier_is_valid(self, score):
        """All scores should map to a valid tier."""
        tier = get_quality_tier(score)
        assert tier in ['gold', 'silver', 'bronze', 'poor', 'unusable']

    @given(st.floats(min_value=0.0, max_value=100.0, allow_nan=False))
    def test_tier_production_ready_consistency(self, score):
        """Production ready should match tier definition."""
        tier = get_quality_tier(score)
        is_production = QUALITY_TIERS[tier]['production_ready']

        if tier in ['gold', 'silver', 'bronze']:
            assert is_production is True
        else:
            assert is_production is False


# =============================================================================
# Completeness Percentage Tests
# =============================================================================

class TestCompletenessPercentage:
    """Property tests for completeness percentage calculation."""

    @given(
        st.integers(min_value=0, max_value=1000),
        st.integers(min_value=1, max_value=1000)
    )
    def test_completeness_in_valid_range(self, actual, expected):
        """Completeness should be non-negative."""
        result = calculate_completeness_pct(actual, expected)
        assert result >= 0.0

    @given(st.integers(min_value=1, max_value=1000))
    def test_exact_match_is_100(self, count):
        """Actual == expected should be 100%."""
        result = calculate_completeness_pct(count, count)
        assert result == 100.0

    @given(st.integers(min_value=1, max_value=1000))
    def test_zero_actual_is_0(self, expected):
        """Zero actual should be 0%."""
        result = calculate_completeness_pct(0, expected)
        assert result == 0.0

    @given(st.integers(min_value=0, max_value=1000))
    def test_zero_expected_is_0(self, actual):
        """Zero expected should be 0% (avoid division by zero)."""
        result = calculate_completeness_pct(actual, 0)
        assert result == 0.0

    @given(
        st.integers(min_value=1, max_value=1000),
        st.integers(min_value=1, max_value=1000)
    )
    def test_over_100_possible(self, actual, expected):
        """Over 100% is possible when actual > expected."""
        assume(actual > expected)
        result = calculate_completeness_pct(actual, expected)
        assert result > 100.0

    @given(
        st.integers(min_value=1, max_value=500),
        st.integers(min_value=501, max_value=1000)
    )
    def test_under_100_when_incomplete(self, actual, expected):
        """Under 100% when actual < expected."""
        assume(actual < expected)
        result = calculate_completeness_pct(actual, expected)
        assert result < 100.0


# =============================================================================
# Quality Distribution Tests
# =============================================================================

class TestQualityDistribution:
    """Property tests for QualityDistribution dataclass."""

    @given(quality_distribution())
    def test_total_is_sum(self, dist):
        """Total should equal sum of all tiers."""
        expected_total = dist.gold + dist.silver + dist.bronze + dist.poor + dist.unusable
        assert dist.total == expected_total

    @given(quality_distribution())
    def test_production_ready_excludes_poor_unusable(self, dist):
        """Production ready count should exclude poor and unusable."""
        result = dist.production_ready_count()
        expected = dist.gold + dist.silver + dist.bronze
        assert result == expected

    @given(quality_distribution())
    def test_has_issues_logic(self, dist):
        """has_issues should be True only if poor or unusable > 0."""
        result = dist.has_issues()
        expected = dist.poor > 0 or dist.unusable > 0
        assert result == expected

    @given(
        st.integers(min_value=0, max_value=100),
        st.integers(min_value=0, max_value=50),
        st.integers(min_value=0, max_value=30),
    )
    def test_no_issues_when_clean(self, gold, silver, bronze):
        """Distribution with no poor/unusable should have no issues."""
        dist = QualityDistribution(gold=gold, silver=silver, bronze=bronze, poor=0, unusable=0)
        assert not dist.has_issues()

    @given(quality_distribution())
    def test_summary_string_format(self, dist):
        """Summary string should have correct format."""
        result = dist.to_summary_string()

        assert 'G' in result
        assert 'S' in result
        assert 'B' in result
        assert 'P' in result
        assert 'U' in result

        # Should contain the actual counts
        assert str(dist.gold) in result
        assert str(dist.unusable) in result


# =============================================================================
# Feature Threshold Tests
# =============================================================================

class TestFeatureThresholds:
    """Property tests for feature threshold validation."""

    @given(st.sampled_from(list(FEATURE_THRESHOLDS.keys())))
    def test_known_features_have_thresholds(self, feature):
        """Known features should return defined threshold."""
        result = get_feature_threshold(feature)
        expected = FEATURE_THRESHOLDS[feature]['threshold']
        assert result == expected

    @given(st.text(min_size=1, max_size=20).filter(lambda x: x not in FEATURE_THRESHOLDS))
    def test_unknown_features_return_default(self, feature):
        """Unknown features should return default 95.0."""
        result = get_feature_threshold(feature)
        assert result == 95.0

    @given(st.sampled_from(['minutes_played', 'usage_rate', 'three_pt_attempts', 'points', 'fg_attempts', 'assists']))
    def test_critical_features_identified(self, feature):
        """Critical features should be identified correctly."""
        result = is_critical_feature(feature)
        assert result is True

    @given(st.sampled_from(['paint_attempts', 'mid_range_attempts']))
    def test_non_critical_features_identified(self, feature):
        """Non-critical features should be identified correctly."""
        result = is_critical_feature(feature)
        assert result is False

    @given(
        st.floats(min_value=0.0, max_value=100.0, allow_nan=False),
        st.sampled_from(list(FEATURE_THRESHOLDS.keys()))
    )
    def test_coverage_check_logic(self, coverage, feature):
        """Coverage check should compare against threshold correctly."""
        threshold = get_feature_threshold(feature)
        result = check_feature_coverage(coverage, feature)
        expected = coverage >= threshold
        assert result == expected


# =============================================================================
# Cross-Table Consistency Tests
# =============================================================================

class TestCrossTableConsistency:
    """Property tests for cross-table consistency checking."""

    @given(player_set(min_size=0, max_size=50))
    def test_identical_sets_are_consistent(self, players):
        """Identical player sets should be consistent."""
        source_players = players
        target_players = players.copy()

        missing_in_target = source_players - target_players
        extra_in_target = target_players - source_players

        assert len(missing_in_target) == 0
        assert len(extra_in_target) == 0

    @given(
        player_set(min_size=5, max_size=50),
        st.integers(min_value=1, max_value=5)
    )
    def test_missing_players_detected(self, source_players, num_missing):
        """Missing players in target should be detected."""
        assume(len(source_players) >= num_missing)

        players_list = list(source_players)
        target_players = set(players_list[num_missing:])  # Remove first N

        missing_in_target = source_players - target_players

        assert len(missing_in_target) == num_missing

    @given(
        player_set(min_size=5, max_size=50),
        st.integers(min_value=1, max_value=5)
    )
    def test_extra_players_detected(self, base_players, num_extra):
        """Extra players in target should be detected."""
        source_players = base_players

        # Add extra players to target
        target_players = base_players.copy()
        for i in range(num_extra):
            target_players.add(f"extraplayer{i}")

        extra_in_target = target_players - source_players

        assert len(extra_in_target) == num_extra

    @given(player_set(min_size=0, max_size=50), player_set(min_size=0, max_size=50))
    def test_set_difference_properties(self, source, target):
        """Set difference should have correct properties."""
        missing = source - target
        extra = target - source

        # Missing players are in source but not target
        for player in missing:
            assert player in source
            assert player not in target

        # Extra players are in target but not source
        for player in extra:
            assert player in target
            assert player not in source


# =============================================================================
# Data Integrity Result Tests
# =============================================================================

class TestDataIntegrityResult:
    """Property tests for data integrity result logic."""

    @dataclass
    class DataIntegrityResult:
        """Result of data integrity checks."""
        duplicate_count: int = 0
        null_player_lookup_count: int = 0
        null_critical_fields: Dict[str, int] = None
        has_issues: bool = False
        issues: List[str] = None

        def __post_init__(self):
            if self.null_critical_fields is None:
                self.null_critical_fields = {}
            if self.issues is None:
                self.issues = []
            self._determine_has_issues()

        def _determine_has_issues(self):
            self.has_issues = (
                self.duplicate_count > 0 or
                self.null_player_lookup_count > 0 or
                any(v > 0 for v in self.null_critical_fields.values())
            )

    @given(
        st.integers(min_value=0, max_value=100),
        st.integers(min_value=0, max_value=100),
    )
    def test_has_issues_with_duplicates(self, duplicate_count, null_count):
        """Duplicates should trigger has_issues."""
        result = self.DataIntegrityResult(
            duplicate_count=duplicate_count,
            null_player_lookup_count=null_count
        )

        if duplicate_count > 0 or null_count > 0:
            assert result.has_issues is True
        else:
            assert result.has_issues is False

    @given(st.dictionaries(
        keys=st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz_"),
        values=st.integers(min_value=0, max_value=100),
        min_size=0,
        max_size=5
    ))
    def test_has_issues_with_null_fields(self, null_fields):
        """Null critical fields should trigger has_issues."""
        result = self.DataIntegrityResult(null_critical_fields=null_fields)

        has_nulls = any(v > 0 for v in null_fields.values())
        assert result.has_issues == has_nulls

    def test_clean_result_has_no_issues(self):
        """Clean result should have no issues."""
        result = self.DataIntegrityResult(
            duplicate_count=0,
            null_player_lookup_count=0,
            null_critical_fields={}
        )

        assert result.has_issues is False


# =============================================================================
# Validation Status Tests
# =============================================================================

class TestValidationStatus:
    """Property tests for validation status logic."""

    def _determine_status(self, completeness_pct: float) -> ValidationStatus:
        """Determine validation status from completeness."""
        if completeness_pct >= 100.0:
            return ValidationStatus.COMPLETE
        elif completeness_pct > 0:
            return ValidationStatus.PARTIAL
        else:
            return ValidationStatus.MISSING

    @given(st.floats(min_value=100.0, max_value=200.0, allow_nan=False))
    def test_complete_status(self, pct):
        """100%+ should be COMPLETE."""
        result = self._determine_status(pct)
        assert result == ValidationStatus.COMPLETE

    @given(st.floats(min_value=0.01, max_value=99.99, allow_nan=False))
    def test_partial_status(self, pct):
        """Between 0 and 100 should be PARTIAL."""
        result = self._determine_status(pct)
        assert result == ValidationStatus.PARTIAL

    @given(st.floats(min_value=-10.0, max_value=0.0, allow_nan=False))
    def test_missing_status(self, pct):
        """0 or less should be MISSING."""
        result = self._determine_status(pct)
        assert result == ValidationStatus.MISSING

    def test_status_enum_values(self):
        """All expected status values should exist."""
        assert ValidationStatus.COMPLETE.value == 'complete'
        assert ValidationStatus.PARTIAL.value == 'partial'
        assert ValidationStatus.MISSING.value == 'missing'
        assert ValidationStatus.BOOTSTRAP_SKIP.value == 'bootstrap_skip'
        assert ValidationStatus.NOT_APPLICABLE.value == 'not_applicable'
        assert ValidationStatus.ERROR.value == 'error'


# =============================================================================
# Threshold Boundary Tests
# =============================================================================

class TestThresholdBoundaries:
    """Property tests for threshold boundary conditions."""

    @given(st.sampled_from(list(FEATURE_THRESHOLDS.keys())))
    @example('minutes_played')
    @example('paint_attempts')
    def test_exactly_at_threshold_passes(self, feature):
        """Coverage exactly at threshold should pass."""
        threshold = get_feature_threshold(feature)
        result = check_feature_coverage(threshold, feature)
        assert result is True

    @given(st.sampled_from(list(FEATURE_THRESHOLDS.keys())))
    def test_just_below_threshold_fails(self, feature):
        """Coverage just below threshold should fail."""
        threshold = get_feature_threshold(feature)
        result = check_feature_coverage(threshold - 0.001, feature)
        assert result is False

    @given(st.sampled_from(list(FEATURE_THRESHOLDS.keys())))
    def test_just_above_threshold_passes(self, feature):
        """Coverage just above threshold should pass."""
        threshold = get_feature_threshold(feature)
        result = check_feature_coverage(threshold + 0.001, feature)
        assert result is True


# =============================================================================
# Quality Score Boundary Tests
# =============================================================================

class TestQualityScoreBoundaries:
    """Property tests for quality score boundary conditions."""

    @example(90.0)  # Gold boundary
    @example(75.0)  # Silver boundary
    @example(60.0)  # Bronze boundary
    @example(40.0)  # Poor boundary
    @given(st.floats(min_value=0.0, max_value=100.0, allow_nan=False))
    def test_boundary_values_classified_correctly(self, score):
        """Boundary values should be classified to higher tier."""
        tier = get_quality_tier(score)

        if score >= 90:
            assert tier == 'gold'
        elif score >= 75:
            assert tier == 'silver'
        elif score >= 60:
            assert tier == 'bronze'
        elif score >= 40:
            assert tier == 'poor'
        else:
            assert tier == 'unusable'

    def test_exact_boundary_values(self):
        """Test exact boundary values."""
        assert get_quality_tier(90.0) == 'gold'
        assert get_quality_tier(89.9999) == 'silver'
        assert get_quality_tier(75.0) == 'silver'
        assert get_quality_tier(74.9999) == 'bronze'
        assert get_quality_tier(60.0) == 'bronze'
        assert get_quality_tier(59.9999) == 'poor'
        assert get_quality_tier(40.0) == 'poor'
        assert get_quality_tier(39.9999) == 'unusable'


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
