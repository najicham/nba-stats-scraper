"""
Unit tests for stale prediction threshold logic

Tests the business logic for determining when predictions are stale
based on line movement thresholds.

The threshold logic uses: ABS(current_line - prediction_line) >= threshold
Default threshold: 1.0 points

Related: predictions/coordinator/player_loader.py:1212-1337
"""

import pytest


class TestThresholdLogic:
    """Test suite for threshold business logic."""

    def test_threshold_below_1_0(self):
        """Test that line changes below 1.0 are NOT considered stale."""
        # Simulate the SQL WHERE clause logic
        prediction_line = 25.5
        current_line = 26.4
        threshold = 1.0

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert pytest.approx(line_change, abs=0.01) == 0.9
        assert is_stale is False

    def test_threshold_exactly_1_0(self):
        """Test that line change of exactly 1.0 IS considered stale."""
        prediction_line = 25.5
        current_line = 26.5
        threshold = 1.0

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert line_change == 1.0
        assert is_stale is True

    def test_threshold_above_1_0(self):
        """Test that line changes above 1.0 are considered stale."""
        prediction_line = 25.5
        current_line = 27.0
        threshold = 1.0

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert line_change == 1.5
        assert is_stale is True

    def test_negative_changes(self):
        """Test that negative line changes use absolute value."""
        # Current line decreased (prediction was 26.5, now 25.0)
        prediction_line = 26.5
        current_line = 25.0
        threshold = 1.0

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert line_change == 1.5  # ABS(-1.5) = 1.5
        assert is_stale is True

    def test_null_handling(self):
        """Test behavior with null/None values (should not match threshold)."""
        # In SQL, NULL comparisons return NULL (falsy)
        # Simulating that NULL values don't pass the threshold check
        prediction_line = None
        current_line = 26.5
        threshold = 1.0

        # In Python, simulate SQL behavior where NULL != any value
        if prediction_line is None or current_line is None:
            is_stale = False
        else:
            line_change = abs(current_line - prediction_line)
            is_stale = line_change >= threshold

        assert is_stale is False

    def test_large_threshold(self):
        """Test threshold can be increased for less sensitive detection."""
        prediction_line = 25.5
        current_line = 27.0
        threshold = 2.0  # Increased threshold

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert line_change == 1.5
        assert is_stale is False  # 1.5 < 2.0

    def test_small_threshold(self):
        """Test threshold can be decreased for more sensitive detection."""
        prediction_line = 25.5
        current_line = 26.0
        threshold = 0.5  # Decreased threshold

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert line_change == 0.5
        assert is_stale is True  # 0.5 >= 0.5

    def test_zero_change(self):
        """Test that no line change is not stale."""
        prediction_line = 25.5
        current_line = 25.5
        threshold = 1.0

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert line_change == 0.0
        assert is_stale is False

    def test_floating_point_precision(self):
        """Test threshold logic handles floating point precision correctly."""
        # Edge case: 0.999999... should not be >= 1.0
        prediction_line = 25.5
        current_line = 26.499999
        threshold = 1.0

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert line_change < 1.0
        assert is_stale is False

    def test_boundary_values(self):
        """Test threshold logic at common boundary values."""
        threshold = 1.0

        test_cases = [
            (25.5, 26.49, False),  # Just below threshold
            (25.5, 26.50, True),   # Exactly at threshold
            (25.5, 26.51, True),   # Just above threshold
            (30.0, 29.01, False),  # Negative change, just below (changed from 28.99 to avoid fp issues)
            (30.0, 29.00, True),   # Negative change, at threshold
            (30.0, 28.99, True),   # Negative change, above threshold
        ]

        for pred, curr, expected_stale in test_cases:
            line_change = abs(curr - pred)
            is_stale = line_change >= threshold
            assert is_stale == expected_stale, \
                f"pred={pred}, curr={curr}, change={line_change}, expected={expected_stale}"

    def test_realistic_nba_scenarios(self):
        """Test realistic NBA player prop scenarios."""
        threshold = 1.0

        # Scenario 1: Small intraday adjustment (news about starter/bench role)
        pred_points = 18.5
        curr_points = 18.0
        assert abs(curr_points - pred_points) < threshold  # Not stale

        # Scenario 2: Significant line movement (injury news, lineup change)
        pred_points = 25.5
        curr_points = 23.5
        assert abs(curr_points - pred_points) >= threshold  # Stale

        # Scenario 3: Star player, major news
        pred_points = 28.5
        curr_points = 31.0
        assert abs(curr_points - pred_points) >= threshold  # Stale

        # Scenario 4: Bench player, minor adjustment
        pred_points = 12.5
        curr_points = 12.0
        assert abs(curr_points - pred_points) < threshold  # Not stale


class TestThresholdEdgeCases:
    """Test edge cases for threshold logic."""

    def test_very_large_line_change(self):
        """Test extremely large line changes (e.g., player scratched)."""
        prediction_line = 25.5
        current_line = 0.0  # Player scratched, line removed
        threshold = 1.0

        # In practice, scratched players have NULL lines, not 0.0
        # But test the math edge case
        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        assert line_change == 25.5
        assert is_stale is True

    def test_both_null(self):
        """Test when both prediction and current line are NULL."""
        prediction_line = None
        current_line = None
        threshold = 1.0

        if prediction_line is None or current_line is None:
            is_stale = False
        else:
            line_change = abs(current_line - prediction_line)
            is_stale = line_change >= threshold

        assert is_stale is False

    def test_negative_threshold(self):
        """Test that negative thresholds would match all changes."""
        # This shouldn't happen in production, but test the logic
        prediction_line = 25.5
        current_line = 25.6
        threshold = -1.0

        line_change = abs(current_line - prediction_line)
        is_stale = line_change >= threshold

        # ABS always returns positive, so will always be >= negative threshold
        assert is_stale is True

    def test_zero_threshold(self):
        """Test that zero threshold matches any non-zero change."""
        prediction_line = 25.5
        threshold = 0.0

        # Test non-zero change
        current_line = 25.6
        line_change = abs(current_line - prediction_line)
        assert (line_change >= threshold) is True

        # Test zero change
        current_line = 25.5
        line_change = abs(current_line - prediction_line)
        assert (line_change >= threshold) is True  # 0.0 >= 0.0


class TestThresholdCalculation:
    """Test the actual calculation helper function."""

    @staticmethod
    def is_stale_prediction(
        prediction_line: float,
        current_line: float,
        threshold: float = 1.0
    ) -> bool:
        """
        Helper function implementing the stale prediction logic.

        This mirrors the SQL logic: ABS(current_line - prediction_line) >= threshold

        Args:
            prediction_line: Line used when prediction was made
            current_line: Current betting line
            threshold: Minimum change to consider stale (default 1.0)

        Returns:
            True if prediction is stale, False otherwise
        """
        if prediction_line is None or current_line is None:
            return False

        line_change = abs(current_line - prediction_line)
        return line_change >= threshold

    def test_helper_function_basic(self):
        """Test the helper function with basic inputs."""
        assert self.is_stale_prediction(25.5, 26.5) is True  # Change of 1.0
        assert self.is_stale_prediction(25.5, 26.4) is False  # Change of 0.9
        assert self.is_stale_prediction(25.5, 24.5) is True  # Negative change of 1.0

    def test_helper_function_with_custom_threshold(self):
        """Test helper function with custom thresholds."""
        assert self.is_stale_prediction(25.5, 27.0, threshold=2.0) is False  # 1.5 < 2.0
        assert self.is_stale_prediction(25.5, 26.0, threshold=0.5) is True  # 0.5 >= 0.5

    def test_helper_function_null_handling(self):
        """Test helper function handles None values correctly."""
        assert self.is_stale_prediction(None, 26.5) is False
        assert self.is_stale_prediction(25.5, None) is False
        assert self.is_stale_prediction(None, None) is False
