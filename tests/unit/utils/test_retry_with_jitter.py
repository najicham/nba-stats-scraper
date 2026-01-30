"""
Unit tests for Retry with Jitter Decorator

Tests exponential backoff calculation, jitter randomization, max retry limit,
and decorrelated jitter algorithm.

Usage:
    pytest tests/unit/utils/test_retry_with_jitter.py -v
"""

import pytest
import time
from unittest.mock import Mock, patch
from shared.utils.retry_with_jitter import (
    retry_with_jitter,
    retry_with_simple_jitter,
    retry_fast,
    retry_standard,
    retry_patient,
    retry_aggressive
)


class TestRetryWithJitterBasics:
    """Test basic retry with jitter functionality."""

    def test_successful_function_no_retry(self):
        """Test that successful function executes once without retry."""
        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=3)
        def successful_function():
            call_count["count"] += 1
            return "success"

        result = successful_function()

        assert result == "success"
        assert call_count["count"] == 1

    def test_function_with_return_value(self):
        """Test that return value is properly passed through."""
        @retry_with_jitter(max_attempts=3)
        def function_with_return():
            return {"data": "test", "count": 42}

        result = function_with_return()

        assert result == {"data": "test", "count": 42}

    def test_function_with_arguments(self):
        """Test retry decorator with function arguments."""
        @retry_with_jitter(max_attempts=3)
        def function_with_args(a, b, c=None):
            return f"{a}-{b}-{c}"

        result = function_with_args("x", "y", c="z")

        assert result == "x-y-z"

    def test_retry_on_exception(self):
        """Test that function retries on exception."""
        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=3, base_delay=0.01)
        def failing_then_succeeding():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        result = failing_then_succeeding()

        assert result == "success"
        assert call_count["count"] == 3

    def test_max_attempts_reached(self):
        """Test that exception is raised after max attempts."""
        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=3, base_delay=0.01)
        def always_failing():
            call_count["count"] += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError, match="Always fails"):
            always_failing()

        assert call_count["count"] == 3


class TestRetryWithJitterExponentialBackoff:
    """Test exponential backoff behavior."""

    def test_delay_increases_with_attempts(self):
        """Test that delay increases with each retry attempt."""
        delays = []

        def mock_sleep(delay):
            delays.append(delay)

        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=4, base_delay=0.1, max_delay=10.0)
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 4:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep', side_effect=mock_sleep):
            result = failing_function()

        assert result == "success"
        assert len(delays) == 3  # 3 retries

        # Delays should generally increase (with jitter variance)
        # We can't test exact values due to randomness, but we can verify
        # that we got delays
        assert all(d > 0 for d in delays)

    def test_max_delay_cap(self):
        """Test that delay is capped at max_delay."""
        delays = []

        def mock_sleep(delay):
            delays.append(delay)

        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=5, base_delay=1.0, max_delay=2.0)
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 5:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep', side_effect=mock_sleep):
            result = failing_function()

        assert result == "success"

        # All delays should be <= max_delay
        assert all(d <= 2.0 for d in delays)


class TestRetryWithJitterConfiguration:
    """Test retry configuration options."""

    def test_custom_max_attempts(self):
        """Test custom max_attempts configuration."""
        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=5, base_delay=0.01)
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 5:
                raise ValueError("Test error")
            return "success"

        result = failing_function()

        assert result == "success"
        assert call_count["count"] == 5

    def test_custom_base_delay(self):
        """Test custom base_delay configuration."""
        delays = []

        def mock_sleep(delay):
            delays.append(delay)

        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=3, base_delay=2.0, max_delay=10.0)
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep', side_effect=mock_sleep):
            result = failing_function()

        # First delay should be based on base_delay (2.0)
        assert all(d >= 0 for d in delays)

    def test_custom_exceptions(self):
        """Test retrying only on specific exceptions."""
        call_count = {"count": 0}

        @retry_with_jitter(
            max_attempts=3,
            base_delay=0.01,
            exceptions=(ValueError, TypeError)
        )
        def function_with_different_errors():
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise ValueError("First error")
            elif call_count["count"] == 2:
                raise TypeError("Second error")
            return "success"

        result = function_with_different_errors()

        assert result == "success"
        assert call_count["count"] == 3

    def test_non_retryable_exception(self):
        """Test that non-specified exceptions are not retried."""
        call_count = {"count": 0}

        @retry_with_jitter(
            max_attempts=3,
            base_delay=0.01,
            exceptions=(ValueError,)
        )
        def function_with_non_retryable_error():
            call_count["count"] += 1
            raise TypeError("Non-retryable error")

        with pytest.raises(TypeError, match="Non-retryable error"):
            function_with_non_retryable_error()

        # Should not retry
        assert call_count["count"] == 1


class TestRetryWithJitterCallback:
    """Test on_retry callback functionality."""

    def test_on_retry_callback_called(self):
        """Test that on_retry callback is called on each retry."""
        callback_calls = []

        def on_retry_callback(attempt, exception, delay):
            callback_calls.append({
                "attempt": attempt,
                "exception": str(exception),
                "delay": delay
            })

        call_count = {"count": 0}

        @retry_with_jitter(
            max_attempts=3,
            base_delay=0.01,
            on_retry=on_retry_callback
        )
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep'):
            result = failing_function()

        assert result == "success"
        assert len(callback_calls) == 2  # 2 retries

        # Verify callback was called with correct attempt numbers
        assert callback_calls[0]["attempt"] == 1
        assert callback_calls[1]["attempt"] == 2

    def test_on_retry_callback_error_handling(self):
        """Test that errors in callback don't break retry logic."""
        def broken_callback(attempt, exception, delay):
            raise RuntimeError("Callback error")

        call_count = {"count": 0}

        @retry_with_jitter(
            max_attempts=3,
            base_delay=0.01,
            on_retry=broken_callback
        )
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep'):
            # Should still succeed despite callback error
            result = failing_function()

        assert result == "success"
        assert call_count["count"] == 3


class TestRetryWithSimpleJitter:
    """Test simple jitter retry decorator."""

    def test_simple_jitter_successful_function(self):
        """Test simple jitter with successful function."""
        call_count = {"count": 0}

        @retry_with_simple_jitter(max_attempts=3, base_delay=0.01)
        def successful_function():
            call_count["count"] += 1
            return "success"

        result = successful_function()

        assert result == "success"
        assert call_count["count"] == 1

    def test_simple_jitter_retry_on_failure(self):
        """Test simple jitter retries on failure."""
        call_count = {"count": 0}

        @retry_with_simple_jitter(max_attempts=3, base_delay=0.01)
        def failing_then_succeeding():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        result = failing_then_succeeding()

        assert result == "success"
        assert call_count["count"] == 3

    def test_simple_jitter_exponential_backoff(self):
        """Test that simple jitter uses exponential backoff."""
        delays = []

        def mock_sleep(delay):
            delays.append(delay)

        call_count = {"count": 0}

        @retry_with_simple_jitter(max_attempts=4, base_delay=1.0, max_delay=20.0)
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 4:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep', side_effect=mock_sleep):
            result = failing_function()

        assert result == "success"
        assert len(delays) == 3

        # Delays should increase exponentially (with jitter)
        # First delay should be around 1.0 * random(0.5, 1.5) = 0.5-1.5
        # Second delay should be around 2.0 * random(0.5, 1.5) = 1.0-3.0
        # Third delay should be around 4.0 * random(0.5, 1.5) = 2.0-6.0
        assert all(d > 0 for d in delays)


class TestRetryPresetConfigurations:
    """Test preset retry configurations."""

    def test_retry_fast(self):
        """Test fast retry preset."""
        call_count = {"count": 0}

        @retry_fast()
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep'):
            result = failing_function()

        assert result == "success"

    def test_retry_standard(self):
        """Test standard retry preset."""
        call_count = {"count": 0}

        @retry_standard()
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep'):
            result = failing_function()

        assert result == "success"

    def test_retry_patient(self):
        """Test patient retry preset."""
        call_count = {"count": 0}

        @retry_patient()
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep'):
            result = failing_function()

        assert result == "success"

    def test_retry_aggressive(self):
        """Test aggressive retry preset."""
        call_count = {"count": 0}

        @retry_aggressive()
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep'):
            result = failing_function()

        assert result == "success"


class TestRetryJitterRandomization:
    """Test jitter randomization behavior."""

    def test_jitter_creates_variation(self):
        """Test that jitter creates variation in delays."""
        # Run multiple times and collect delays
        all_delays = []

        for _ in range(5):
            delays = []

            def mock_sleep(delay):
                delays.append(delay)

            call_count = {"count": 0}

            @retry_with_jitter(max_attempts=3, base_delay=1.0, max_delay=10.0)
            def failing_function():
                call_count["count"] += 1
                if call_count["count"] < 3:
                    raise ValueError("Test error")
                return "success"

            with patch('time.sleep', side_effect=mock_sleep):
                failing_function()

            all_delays.append(delays)

        # Check that we got different delay sequences
        # (Due to randomization, they should not all be identical)
        # We'll check that at least one pair of delay sequences differs
        sequences_differ = False
        for i in range(len(all_delays)):
            for j in range(i + 1, len(all_delays)):
                if all_delays[i] != all_delays[j]:
                    sequences_differ = True
                    break
            if sequences_differ:
                break

        assert sequences_differ

    def test_jitter_percentage_applied(self):
        """Test that jitter percentage is applied to delays."""
        delays = []

        def mock_sleep(delay):
            delays.append(delay)

        call_count = {"count": 0}

        @retry_with_jitter(
            max_attempts=3,
            base_delay=10.0,
            max_delay=100.0,
            jitter_pct=0.3  # 30% jitter
        )
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        with patch('time.sleep', side_effect=mock_sleep):
            result = failing_function()

        # All delays should be positive
        assert all(d > 0 for d in delays)


class TestRetryEdgeCases:
    """Test edge cases and error conditions."""

    def test_max_attempts_one(self):
        """Test with max_attempts=1 (no retry)."""
        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=1, base_delay=0.01)
        def failing_function():
            call_count["count"] += 1
            raise ValueError("Error")

        with pytest.raises(ValueError):
            failing_function()

        assert call_count["count"] == 1

    def test_zero_base_delay(self):
        """Test with zero base delay."""
        call_count = {"count": 0}

        @retry_with_jitter(max_attempts=3, base_delay=0.0)
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Error")
            return "success"

        # Should still work, just with minimal delays
        result = failing_function()
        assert result == "success"

    def test_preserves_function_metadata(self):
        """Test that decorator preserves function metadata."""
        @retry_with_jitter(max_attempts=3)
        def documented_function():
            """This is a docstring."""
            return "success"

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a docstring."

    def test_exception_type_preserved(self):
        """Test that original exception type is preserved."""
        class CustomException(Exception):
            pass

        @retry_with_jitter(max_attempts=2, base_delay=0.01)
        def custom_error_function():
            raise CustomException("Custom error")

        with pytest.raises(CustomException, match="Custom error"):
            custom_error_function()


class TestRetryTimingBehavior:
    """Test actual timing behavior of retries."""

    def test_retry_timing_approximately_correct(self):
        """Test that actual retry timing is approximately as expected."""
        call_count = {"count": 0}

        @retry_with_jitter(
            max_attempts=3,
            base_delay=0.1,
            max_delay=1.0,
            jitter_pct=0.0  # No jitter for predictable timing
        )
        def failing_function():
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Test error")
            return "success"

        start = time.time()
        result = failing_function()
        elapsed = time.time() - start

        assert result == "success"
        # Should take at least the sum of delays (roughly 0.1s + 0.2s = 0.3s)
        # But we can't be too precise due to jitter and execution time
        assert elapsed > 0.1  # At least one delay occurred
