"""
Property-based tests for odds calculations and conversions.

Uses Hypothesis to verify:
- American ↔ Decimal ↔ Fractional round-trip conversions
- Probability bounds (0-1)
- Vig calculation consistency
- Implied probability calculations
- Odds format validation
"""

import pytest
from hypothesis import given, strategies as st, assume, settings, example
from hypothesis.strategies import composite
from fractions import Fraction


# =============================================================================
# Odds Conversion Functions
# =============================================================================

def american_to_decimal(american_odds):
    """Convert American odds to Decimal odds."""
    if american_odds >= 100:
        return 1 + (american_odds / 100)
    elif american_odds <= -100:
        return 1 + (100 / abs(american_odds))
    else:
        raise ValueError(f"Invalid American odds: {american_odds}")


def decimal_to_american(decimal_odds):
    """Convert Decimal odds to American odds."""
    if decimal_odds < 1.0:
        raise ValueError(f"Invalid decimal odds: {decimal_odds}")

    if decimal_odds >= 2.0:
        return int((decimal_odds - 1) * 100)
    else:
        return int(-100 / (decimal_odds - 1))


def american_to_probability(american_odds):
    """Convert American odds to implied probability."""
    if american_odds >= 100:
        return 100 / (american_odds + 100)
    elif american_odds <= -100:
        return abs(american_odds) / (abs(american_odds) + 100)
    else:
        raise ValueError(f"Invalid American odds: {american_odds}")


def decimal_to_probability(decimal_odds):
    """Convert Decimal odds to implied probability."""
    if decimal_odds < 1.0:
        raise ValueError(f"Invalid decimal odds: {decimal_odds}")

    return 1.0 / decimal_odds


def probability_to_decimal(probability):
    """Convert probability to Decimal odds."""
    if probability <= 0 or probability >= 1:
        raise ValueError(f"Probability must be between 0 and 1: {probability}")

    return 1.0 / probability


def calculate_vig(prob1, prob2):
    """Calculate vig (overround) from two probabilities."""
    total = prob1 + prob2
    return total - 1.0


def remove_vig(prob1, prob2):
    """Remove vig to get true probabilities."""
    total = prob1 + prob2
    if total <= 1.0:
        # No vig to remove
        return prob1, prob2

    return prob1 / total, prob2 / total


# =============================================================================
# Strategies for Odds Testing
# =============================================================================

@composite
def american_odds_positive(draw):
    """Generate positive American odds (+100 to +1000)."""
    return draw(st.integers(min_value=100, max_value=1000))


@composite
def american_odds_negative(draw):
    """Generate negative American odds (-1000 to -100)."""
    return draw(st.integers(min_value=-1000, max_value=-100))


@composite
def american_odds_any(draw):
    """Generate any valid American odds."""
    return draw(st.one_of(american_odds_positive(), american_odds_negative()))


@composite
def decimal_odds(draw):
    """Generate valid Decimal odds (1.01 to 20.0)."""
    return draw(st.floats(min_value=1.01, max_value=20.0, allow_nan=False, allow_infinity=False))


@composite
def probability(draw):
    """Generate valid probability (0.01 to 0.99)."""
    return draw(st.floats(min_value=0.01, max_value=0.99, allow_nan=False, allow_infinity=False))


# =============================================================================
# Round-Trip Conversion Tests
# =============================================================================

class TestRoundTripConversions:
    """Test that odds conversions are reversible."""

    @given(american_odds_positive())
    @settings(max_examples=200)
    def test_american_to_decimal_to_american_positive(self, american):
        """Property: American -> Decimal -> American (positive odds)."""
        decimal = american_to_decimal(american)
        back_to_american = decimal_to_american(decimal)

        # Allow small rounding error
        assert abs(back_to_american - american) <= 1

    @given(american_odds_negative())
    def test_american_to_decimal_to_american_negative(self, american):
        """Property: American -> Decimal -> American (negative odds)."""
        decimal = american_to_decimal(american)
        back_to_american = decimal_to_american(decimal)

        # Allow small rounding error
        assert abs(back_to_american - american) <= 1

    @given(decimal_odds())
    def test_decimal_to_american_to_decimal(self, decimal):
        """Property: Decimal -> American -> Decimal round trip."""
        american = decimal_to_american(decimal)
        back_to_decimal = american_to_decimal(american)

        # Allow small rounding error (0.5%)
        assert abs(back_to_decimal - decimal) <= decimal * 0.005

    @given(probability())
    def test_probability_to_decimal_to_probability(self, prob):
        """Property: Probability -> Decimal -> Probability round trip."""
        decimal = probability_to_decimal(prob)
        back_to_prob = decimal_to_probability(decimal)

        # Should be very close
        assert abs(back_to_prob - prob) < 0.0001


# =============================================================================
# Probability Bounds Tests
# =============================================================================

class TestProbabilityBounds:
    """Test that probabilities are always in valid range."""

    @given(american_odds_any())
    def test_american_to_probability_in_range(self, american):
        """Property: American odds produce probability in (0, 1)."""
        prob = american_to_probability(american)

        assert 0 < prob < 1

    @given(decimal_odds())
    def test_decimal_to_probability_in_range(self, decimal):
        """Property: Decimal odds produce probability in (0, 1)."""
        prob = decimal_to_probability(decimal)

        assert 0 < prob < 1

    @given(american_odds_positive())
    def test_positive_odds_imply_underdog(self, american):
        """Property: Positive American odds imply probability < 0.5."""
        prob = american_to_probability(american)

        assert prob < 0.5

    @given(american_odds_negative())
    def test_negative_odds_imply_favorite(self, american):
        """Property: Negative American odds imply probability > 0.5."""
        prob = american_to_probability(american)

        assert prob > 0.5


# =============================================================================
# Decimal Odds Range Tests
# =============================================================================

class TestDecimalOddsRange:
    """Test decimal odds ranges."""

    @given(american_odds_positive())
    def test_positive_american_to_decimal_greater_than_2(self, american):
        """Property: Positive American odds -> Decimal odds >= 2.0."""
        decimal = american_to_decimal(american)

        assert decimal >= 2.0

    @given(american_odds_negative())
    def test_negative_american_to_decimal_less_than_2(self, american):
        """Property: Negative American odds -> Decimal odds < 2.0."""
        decimal = american_to_decimal(american)

        assert 1.0 < decimal < 2.0

    @given(decimal_odds())
    def test_decimal_always_greater_than_1(self, decimal):
        """Property: Valid decimal odds always > 1.0."""
        assert decimal > 1.0


# =============================================================================
# Vig Calculation Tests
# =============================================================================

class TestVigCalculation:
    """Test vig (overround) calculations."""

    @given(probability(), probability())
    def test_vig_is_total_minus_one(self, prob1, prob2):
        """Property: Vig = (prob1 + prob2) - 1."""
        vig = calculate_vig(prob1, prob2)
        expected = prob1 + prob2 - 1.0

        assert abs(vig - expected) < 0.0001

    @given(probability(), probability())
    def test_fair_odds_have_zero_vig(self, prob1, prob2):
        """Property: Fair odds (sum to 1) have zero vig."""
        assume(abs(prob1 + prob2 - 1.0) < 0.01)  # Close to fair

        vig = calculate_vig(prob1, prob2)

        assert abs(vig) < 0.02

    @given(probability(), probability())
    def test_remove_vig_sums_to_one(self, prob1, prob2):
        """Property: After removing vig, probabilities sum to 1."""
        true_prob1, true_prob2 = remove_vig(prob1, prob2)

        total = true_prob1 + true_prob2

        assert abs(total - 1.0) < 0.0001

    @given(probability(), probability())
    def test_remove_vig_preserves_ratio(self, prob1, prob2):
        """Property: Removing vig preserves probability ratio."""
        assume(prob2 > 0.01)  # Avoid division by zero

        original_ratio = prob1 / prob2
        true_prob1, true_prob2 = remove_vig(prob1, prob2)
        new_ratio = true_prob1 / true_prob2

        # Ratio should be preserved
        assert abs(original_ratio - new_ratio) < 0.0001


# =============================================================================
# Relationship Tests
# =============================================================================

class TestOddsRelationships:
    """Test relationships between odds formats."""

    @given(american_odds_positive(), american_odds_positive())
    def test_higher_positive_odds_lower_probability(self, odds1, odds2):
        """Property: Higher positive odds -> lower probability."""
        assume(odds1 != odds2)

        prob1 = american_to_probability(odds1)
        prob2 = american_to_probability(odds2)

        if odds1 > odds2:
            assert prob1 < prob2
        else:
            assert prob1 > prob2

    @given(american_odds_negative(), american_odds_negative())
    def test_higher_negative_odds_higher_probability(self, odds1, odds2):
        """Property: Higher (less negative) odds -> lower probability."""
        assume(odds1 != odds2)

        prob1 = american_to_probability(odds1)
        prob2 = american_to_probability(odds2)

        # -110 is higher (less negative) than -200
        # -110 implies lower probability than -200
        if odds1 > odds2:  # e.g., -110 > -200
            assert prob1 < prob2
        else:
            assert prob1 > prob2

    @given(decimal_odds(), decimal_odds())
    def test_higher_decimal_lower_probability(self, odds1, odds2):
        """Property: Higher decimal odds -> lower probability."""
        assume(abs(odds1 - odds2) > 0.1)

        prob1 = decimal_to_probability(odds1)
        prob2 = decimal_to_probability(odds2)

        if odds1 > odds2:
            assert prob1 < prob2
        else:
            assert prob1 > prob2


# =============================================================================
# Even Money Tests
# =============================================================================

class TestEvenMoney:
    """Test even money (50/50) odds."""

    def test_even_money_american(self):
        """Property: +100 American odds = 50% probability."""
        prob = american_to_probability(100)

        assert abs(prob - 0.5) < 0.01

    def test_even_money_decimal(self):
        """Property: 2.0 Decimal odds = 50% probability."""
        prob = decimal_to_probability(2.0)

        assert abs(prob - 0.5) < 0.0001

    def test_even_money_conversion(self):
        """Property: +100 American = 2.0 Decimal."""
        decimal = american_to_decimal(100)

        assert abs(decimal - 2.0) < 0.01


# =============================================================================
# Extreme Odds Tests
# =============================================================================

class TestExtremeOdds:
    """Test extreme (very high/low) odds values."""

    @given(st.integers(min_value=1000, max_value=10000))
    def test_very_high_positive_american(self, american):
        """Property: Very high positive odds -> very low probability."""
        prob = american_to_probability(american)

        assert prob < 0.1  # Less than 10%

    @given(st.integers(min_value=-10000, max_value=-1000))
    def test_very_high_negative_american(self, american):
        """Property: Very negative odds -> very high probability."""
        prob = american_to_probability(american)

        assert prob > 0.9  # More than 90%

    @given(st.floats(min_value=10.0, max_value=100.0, allow_nan=False))
    def test_very_high_decimal(self, decimal):
        """Property: Very high decimal odds -> low probability."""
        prob = decimal_to_probability(decimal)

        assert prob < 0.15  # Less than 15%


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error handling for invalid inputs."""

    @given(st.integers(min_value=-99, max_value=99))
    def test_invalid_american_range_raises_error(self, invalid_odds):
        """Property: American odds in (-100, 100) are invalid."""
        with pytest.raises(ValueError):
            american_to_decimal(invalid_odds)

    @given(st.floats(min_value=0.0, max_value=0.99, allow_nan=False))
    def test_decimal_less_than_1_raises_error(self, invalid_decimal):
        """Property: Decimal odds < 1.0 are invalid."""
        with pytest.raises(ValueError):
            decimal_to_american(invalid_decimal)

    @given(st.sampled_from([0.0, 1.0, -0.1, 1.1]))
    def test_invalid_probability_raises_error(self, invalid_prob):
        """Property: Probability must be in (0, 1) exclusive."""
        with pytest.raises(ValueError):
            probability_to_decimal(invalid_prob)


# =============================================================================
# Consistency Tests
# =============================================================================

class TestConsistency:
    """Test that odds calculations are consistent."""

    @given(american_odds_any())
    def test_conversion_deterministic(self, american):
        """Property: Same odds produce same conversion."""
        decimal1 = american_to_decimal(american)
        decimal2 = american_to_decimal(american)
        decimal3 = american_to_decimal(american)

        assert decimal1 == decimal2 == decimal3

    @given(probability())
    def test_probability_conversion_deterministic(self, prob):
        """Property: Same probability produces same odds."""
        decimal1 = probability_to_decimal(prob)
        decimal2 = probability_to_decimal(prob)

        assert decimal1 == decimal2


# =============================================================================
# Known Values Tests
# =============================================================================

class TestKnownValues:
    """Test specific known odds conversions."""

    def test_known_american_to_decimal(self):
        """Test known American to Decimal conversions."""
        known_conversions = [
            (100, 2.0),
            (200, 3.0),
            (-110, 1.91),
            (-200, 1.5),
            (150, 2.5),
        ]

        for american, expected_decimal in known_conversions:
            decimal = american_to_decimal(american)
            assert abs(decimal - expected_decimal) < 0.02

    def test_known_american_to_probability(self):
        """Test known American to Probability conversions."""
        known_conversions = [
            (100, 0.50),
            (200, 0.33),
            (-110, 0.524),
            (-200, 0.667),
        ]

        for american, expected_prob in known_conversions:
            prob = american_to_probability(american)
            assert abs(prob - expected_prob) < 0.01

    def test_common_betting_lines(self):
        """Test common betting lines."""
        # Standard point spread odds
        prob_110 = american_to_probability(-110)
        assert abs(prob_110 - 0.524) < 0.01

        # Moneyline favorite
        prob_150 = american_to_probability(-150)
        assert abs(prob_150 - 0.6) < 0.01

        # Moneyline underdog
        prob_plus_150 = american_to_probability(150)
        assert abs(prob_plus_150 - 0.4) < 0.01


# =============================================================================
# Vig Edge Cases Tests
# =============================================================================

class TestVigEdgeCases:
    """Test edge cases in vig calculations."""

    def test_no_vig_fair_odds(self):
        """Property: Fair odds (no vig) sum to 1.0."""
        prob1 = 0.5
        prob2 = 0.5

        vig = calculate_vig(prob1, prob2)

        assert abs(vig) < 0.0001

    def test_typical_bookmaker_vig(self):
        """Test typical bookmaker vig (4-5%)."""
        # Two -110 lines (typical for point spreads)
        prob1 = american_to_probability(-110)
        prob2 = american_to_probability(-110)

        vig = calculate_vig(prob1, prob2)

        # Typical vig is around 4-5%
        assert 0.04 < vig < 0.06

    @given(probability())
    def test_remove_zero_vig_is_identity(self, prob):
        """Property: Removing zero vig doesn't change probabilities."""
        # Create fair odds that sum to 1.0
        prob1 = prob
        prob2 = 1.0 - prob

        true_prob1, true_prob2 = remove_vig(prob1, prob2)

        assert abs(true_prob1 - prob1) < 0.0001
        assert abs(true_prob2 - prob2) < 0.0001


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--hypothesis-show-statistics'])
