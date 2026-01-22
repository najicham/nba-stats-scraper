"""
Unit tests for rate_limit_config module

Tests configuration loading, validation, and environment variable parsing.
"""

import pytest
import os
from unittest.mock import patch
from io import StringIO

from shared.config.rate_limit_config import (
    get_rate_limit_config,
    validate_config,
    print_config_summary,
    DEFAULTS
)


class TestGetRateLimitConfig:
    """Test get_rate_limit_config function"""

    def test_get_rate_limit_config_defaults(self):
        """Test config uses defaults when env vars not set"""
        with patch.dict(os.environ, {}, clear=True):
            config = get_rate_limit_config()

            assert config['RATE_LIMIT_MAX_RETRIES'] == 5
            assert config['RATE_LIMIT_BASE_BACKOFF'] == 2.0
            assert config['RATE_LIMIT_MAX_BACKOFF'] == 120.0
            assert config['RATE_LIMIT_CB_THRESHOLD'] == 10
            assert config['RATE_LIMIT_CB_TIMEOUT'] == 300
            assert config['RATE_LIMIT_CB_ENABLED'] is True
            assert config['RATE_LIMIT_RETRY_AFTER_ENABLED'] is True
            assert config['HTTP_POOL_BACKOFF_FACTOR'] == 0.5
            assert config['SCRAPER_BACKOFF_FACTOR'] == 3.0

    def test_get_rate_limit_config_from_env_integers(self):
        """Test config loads integer values from environment"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_MAX_RETRIES': '10',
            'RATE_LIMIT_CB_THRESHOLD': '5'
        }, clear=False):
            config = get_rate_limit_config()

            assert config['RATE_LIMIT_MAX_RETRIES'] == 10
            assert config['RATE_LIMIT_CB_THRESHOLD'] == 5

    def test_get_rate_limit_config_from_env_floats(self):
        """Test config loads float values from environment"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_BASE_BACKOFF': '5.5',
            'RATE_LIMIT_MAX_BACKOFF': '300.0',
            'HTTP_POOL_BACKOFF_FACTOR': '1.5'
        }, clear=False):
            config = get_rate_limit_config()

            assert config['RATE_LIMIT_BASE_BACKOFF'] == 5.5
            assert config['RATE_LIMIT_MAX_BACKOFF'] == 300.0
            assert config['HTTP_POOL_BACKOFF_FACTOR'] == 1.5

    def test_get_rate_limit_config_from_env_booleans_true(self):
        """Test config loads boolean true values from environment"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_CB_ENABLED': 'true'
        }, clear=False):
            config = get_rate_limit_config()

            assert config['RATE_LIMIT_CB_ENABLED'] is True

    def test_get_rate_limit_config_from_env_booleans_1(self):
        """Test config loads boolean from '1'"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_CB_ENABLED': '1'
        }, clear=False):
            config = get_rate_limit_config()

            assert config['RATE_LIMIT_CB_ENABLED'] is True

    def test_get_rate_limit_config_from_env_booleans_yes(self):
        """Test config loads boolean from 'yes'"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_RETRY_AFTER_ENABLED': 'yes'
        }, clear=False):
            config = get_rate_limit_config()

            assert config['RATE_LIMIT_RETRY_AFTER_ENABLED'] is True

    def test_get_rate_limit_config_from_env_booleans_false(self):
        """Test config loads boolean false values from environment"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_CB_ENABLED': 'false',
            'RATE_LIMIT_RETRY_AFTER_ENABLED': 'FALSE'
        }, clear=False):
            config = get_rate_limit_config()

            assert config['RATE_LIMIT_CB_ENABLED'] is False
            assert config['RATE_LIMIT_RETRY_AFTER_ENABLED'] is False

    def test_get_rate_limit_config_from_env_booleans_0(self):
        """Test config loads boolean false from '0'"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_CB_ENABLED': '0'
        }, clear=False):
            config = get_rate_limit_config()

            assert config['RATE_LIMIT_CB_ENABLED'] is False

    def test_get_rate_limit_config_mixed_env_and_defaults(self):
        """Test config uses mix of env vars and defaults"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_MAX_RETRIES': '8',
            'RATE_LIMIT_CB_ENABLED': 'false'
        }, clear=True):
            config = get_rate_limit_config()

            # From env
            assert config['RATE_LIMIT_MAX_RETRIES'] == 8
            assert config['RATE_LIMIT_CB_ENABLED'] is False

            # From defaults
            assert config['RATE_LIMIT_BASE_BACKOFF'] == 2.0
            assert config['RATE_LIMIT_CB_THRESHOLD'] == 10

    def test_get_rate_limit_config_all_keys_present(self):
        """Test config returns all expected keys"""
        config = get_rate_limit_config()

        expected_keys = set(DEFAULTS.keys())
        actual_keys = set(config.keys())

        assert expected_keys == actual_keys


class TestValidateConfig:
    """Test validate_config function"""

    def test_validate_config_valid_config(self):
        """Test validation passes for valid config"""
        config = {
            'RATE_LIMIT_MAX_RETRIES': 5,
            'RATE_LIMIT_BASE_BACKOFF': 2.0,
            'RATE_LIMIT_MAX_BACKOFF': 120.0,
            'RATE_LIMIT_CB_THRESHOLD': 10,
            'RATE_LIMIT_CB_TIMEOUT': 300.0,
            'HTTP_POOL_BACKOFF_FACTOR': 0.5,
            'SCRAPER_BACKOFF_FACTOR': 3.0
        }

        is_valid, errors = validate_config(config)

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_config_negative_max_retries(self):
        """Test validation fails for negative max_retries"""
        config = {
            'RATE_LIMIT_MAX_RETRIES': -1,
            'RATE_LIMIT_BASE_BACKOFF': 2.0,
            'RATE_LIMIT_MAX_BACKOFF': 120.0  # Need this to avoid KeyError
        }

        is_valid, errors = validate_config(config)

        assert is_valid is False
        assert any('RATE_LIMIT_MAX_RETRIES' in error for error in errors)
        assert any('must be positive' in error for error in errors)

    def test_validate_config_zero_max_retries(self):
        """Test validation fails for zero max_retries"""
        config = {
            'RATE_LIMIT_MAX_RETRIES': 0
        }

        is_valid, errors = validate_config(config)

        assert is_valid is False
        assert any('RATE_LIMIT_MAX_RETRIES' in error for error in errors)

    def test_validate_config_negative_base_backoff(self):
        """Test validation fails for negative base_backoff"""
        config = {
            'RATE_LIMIT_BASE_BACKOFF': -2.0
        }

        is_valid, errors = validate_config(config)

        assert is_valid is False
        assert any('RATE_LIMIT_BASE_BACKOFF' in error for error in errors)

    def test_validate_config_zero_backoff(self):
        """Test validation fails for zero backoff values"""
        config = {
            'RATE_LIMIT_BASE_BACKOFF': 0.0,
            'HTTP_POOL_BACKOFF_FACTOR': 0.0
        }

        is_valid, errors = validate_config(config)

        assert is_valid is False
        assert len(errors) == 2

    def test_validate_config_max_backoff_less_than_base(self):
        """Test validation fails when max_backoff < base_backoff"""
        config = {
            'RATE_LIMIT_BASE_BACKOFF': 10.0,
            'RATE_LIMIT_MAX_BACKOFF': 5.0
        }

        is_valid, errors = validate_config(config)

        assert is_valid is False
        assert any('must be >=' in error for error in errors)
        assert any('RATE_LIMIT_MAX_BACKOFF' in error for error in errors)

    def test_validate_config_max_backoff_equal_to_base(self):
        """Test validation passes when max_backoff == base_backoff"""
        config = {
            'RATE_LIMIT_BASE_BACKOFF': 10.0,
            'RATE_LIMIT_MAX_BACKOFF': 10.0
        }

        is_valid, errors = validate_config(config)

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_config_multiple_errors(self):
        """Test validation collects multiple errors"""
        config = {
            'RATE_LIMIT_MAX_RETRIES': -1,
            'RATE_LIMIT_BASE_BACKOFF': 10.0,
            'RATE_LIMIT_MAX_BACKOFF': 5.0,
            'RATE_LIMIT_CB_THRESHOLD': 0
        }

        is_valid, errors = validate_config(config)

        assert is_valid is False
        # Should have at least 3 errors
        assert len(errors) >= 3

    def test_validate_config_missing_keys(self):
        """Test validation handles missing keys gracefully"""
        config = {
            'RATE_LIMIT_MAX_RETRIES': 5
        }

        is_valid, errors = validate_config(config)

        # Should pass - validation only checks keys that are present
        assert is_valid is True

    def test_validate_config_empty_config(self):
        """Test validation passes for empty config"""
        config = {}

        is_valid, errors = validate_config(config)

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_config_all_negative_floats(self):
        """Test validation catches all negative float values"""
        config = {
            'RATE_LIMIT_BASE_BACKOFF': -1.0,
            'RATE_LIMIT_MAX_BACKOFF': -2.0,
            'RATE_LIMIT_CB_TIMEOUT': -3.0,
            'HTTP_POOL_BACKOFF_FACTOR': -0.5,
            'SCRAPER_BACKOFF_FACTOR': -1.5
        }

        is_valid, errors = validate_config(config)

        assert is_valid is False
        # Should have 5 errors for the negative values
        # Note: max_backoff check won't fail because both are negative
        assert len(errors) >= 5


class TestPrintConfigSummary:
    """Test print_config_summary function"""

    def test_print_config_summary_output(self):
        """Test print_config_summary produces output"""
        with patch.dict(os.environ, {}, clear=True):
            # Capture stdout
            with patch('sys.stdout', new=StringIO()) as fake_out:
                print_config_summary()
                output = fake_out.getvalue()

            assert "RATE LIMIT CONFIGURATION" in output
            assert "Core Rate Limiting:" in output
            assert "Circuit Breaker:" in output
            assert "Max Retries:" in output
            assert "Base Backoff:" in output
            assert "Threshold:" in output

    def test_print_config_summary_shows_values(self):
        """Test print_config_summary shows actual config values"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_MAX_RETRIES': '10',
            'RATE_LIMIT_BASE_BACKOFF': '5.0'
        }, clear=True):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                print_config_summary()
                output = fake_out.getvalue()

            assert "10" in output
            assert "5.0" in output

    def test_print_config_summary_shows_validation_errors(self):
        """Test print_config_summary shows validation errors"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_BASE_BACKOFF': '10.0',
            'RATE_LIMIT_MAX_BACKOFF': '5.0'  # Invalid: less than base
        }, clear=True):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                print_config_summary()
                output = fake_out.getvalue()

            # Should show validation errors
            assert "Invalid" in output or "VALIDATION ERRORS" in output or "✗" in output

    def test_print_config_summary_no_errors(self):
        """Test print_config_summary with valid config"""
        with patch.dict(os.environ, {}, clear=True):
            with patch('sys.stdout', new=StringIO()) as fake_out:
                print_config_summary()
                output = fake_out.getvalue()

            # Should not have error section or should say valid
            assert "VALIDATION ERRORS" not in output or "Configuration is valid" in output


class TestDefaults:
    """Test DEFAULTS constant"""

    def test_defaults_has_all_keys(self):
        """Test DEFAULTS dict has all expected keys"""
        expected_keys = {
            'RATE_LIMIT_MAX_RETRIES',
            'RATE_LIMIT_BASE_BACKOFF',
            'RATE_LIMIT_MAX_BACKOFF',
            'RATE_LIMIT_CB_THRESHOLD',
            'RATE_LIMIT_CB_TIMEOUT',
            'RATE_LIMIT_CB_ENABLED',
            'RATE_LIMIT_RETRY_AFTER_ENABLED',
            'HTTP_POOL_BACKOFF_FACTOR',
            'SCRAPER_BACKOFF_FACTOR'
        }

        assert set(DEFAULTS.keys()) == expected_keys

    def test_defaults_valid_values(self):
        """Test DEFAULTS dict has valid default values"""
        is_valid, errors = validate_config(DEFAULTS)

        assert is_valid is True
        assert len(errors) == 0

    def test_defaults_types(self):
        """Test DEFAULTS dict has correct types"""
        assert isinstance(DEFAULTS['RATE_LIMIT_MAX_RETRIES'], int)
        assert isinstance(DEFAULTS['RATE_LIMIT_BASE_BACKOFF'], float)
        assert isinstance(DEFAULTS['RATE_LIMIT_MAX_BACKOFF'], float)
        assert isinstance(DEFAULTS['RATE_LIMIT_CB_THRESHOLD'], int)
        assert isinstance(DEFAULTS['RATE_LIMIT_CB_TIMEOUT'], (int, float))
        assert isinstance(DEFAULTS['RATE_LIMIT_CB_ENABLED'], bool)
        assert isinstance(DEFAULTS['RATE_LIMIT_RETRY_AFTER_ENABLED'], bool)
        assert isinstance(DEFAULTS['HTTP_POOL_BACKOFF_FACTOR'], float)
        assert isinstance(DEFAULTS['SCRAPER_BACKOFF_FACTOR'], float)


class TestIntegration:
    """Integration tests for config module"""

    def test_load_validate_workflow(self):
        """Test typical load and validate workflow"""
        # Load config
        config = get_rate_limit_config()

        # Validate config
        is_valid, errors = validate_config(config)

        assert is_valid is True
        assert len(errors) == 0

    def test_override_and_validate(self):
        """Test overriding config and validating"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_MAX_RETRIES': '20',
            'RATE_LIMIT_BASE_BACKOFF': '1.0',
            'RATE_LIMIT_MAX_BACKOFF': '60.0'
        }, clear=True):
            config = get_rate_limit_config()
            is_valid, errors = validate_config(config)

            assert config['RATE_LIMIT_MAX_RETRIES'] == 20
            assert config['RATE_LIMIT_BASE_BACKOFF'] == 1.0
            assert config['RATE_LIMIT_MAX_BACKOFF'] == 60.0
            assert is_valid is True

    def test_invalid_override_detected(self):
        """Test invalid override is detected by validation"""
        with patch.dict(os.environ, {
            'RATE_LIMIT_MAX_RETRIES': '-5'
        }, clear=True):
            config = get_rate_limit_config()
            is_valid, errors = validate_config(config)

            assert config['RATE_LIMIT_MAX_RETRIES'] == -5
            assert is_valid is False
            assert len(errors) > 0
