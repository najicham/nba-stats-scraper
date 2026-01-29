"""
config/validation_config.py

Centralized validation threshold configuration loader.

Provides a simple interface to access validation thresholds defined in
config/validation_thresholds.yaml. Includes caching and sensible defaults
if the configuration file is missing.

Usage:
    from config.validation_config import get_threshold, get_config_section

    # Get a specific threshold
    warning_threshold = get_threshold('minutes_coverage', 'warning')  # Returns 90

    # Get with default fallback
    value = get_threshold('custom_metric', 'warning', default=80)

    # Get an entire config section
    coverage_config = get_config_section('coverage')

    # Reload config (useful for testing)
    reload_config()
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)

# Cache for loaded configuration
_config_cache: Optional[Dict[str, Any]] = None
_config_file_path: Optional[Path] = None


def _get_config_path() -> Path:
    """Get the path to the validation thresholds config file."""
    global _config_file_path
    if _config_file_path is not None:
        return _config_file_path

    # Try multiple locations
    possible_paths = [
        # Same directory as this file
        Path(__file__).parent / "validation_thresholds.yaml",
        # Project root config directory
        Path(__file__).parent.parent / "config" / "validation_thresholds.yaml",
        # Environment variable override
        Path(os.environ.get("VALIDATION_THRESHOLDS_PATH", ""))
        if os.environ.get("VALIDATION_THRESHOLDS_PATH")
        else None,
    ]

    for path in possible_paths:
        if path and path.exists():
            _config_file_path = path
            return path

    # Default to expected location even if it doesn't exist
    _config_file_path = Path(__file__).parent / "validation_thresholds.yaml"
    return _config_file_path


def _load_config() -> Dict[str, Any]:
    """Load the validation thresholds configuration from YAML file."""
    global _config_cache

    if _config_cache is not None:
        return _config_cache

    config_path = _get_config_path()

    try:
        import yaml

        if config_path.exists():
            with open(config_path, "r") as f:
                _config_cache = yaml.safe_load(f)
                logger.debug(f"Loaded validation config from {config_path}")
                return _config_cache
        else:
            logger.warning(
                f"Validation config not found at {config_path}, using defaults"
            )
            _config_cache = _get_default_config()
            return _config_cache

    except ImportError:
        logger.error("PyYAML not installed. Using default configuration.")
        _config_cache = _get_default_config()
        return _config_cache

    except Exception as e:
        logger.error(f"Error loading validation config: {e}. Using defaults.")
        _config_cache = _get_default_config()
        return _config_cache


def _get_default_config() -> Dict[str, Any]:
    """
    Return default configuration values.

    These defaults match the values specified in the YAML file and serve
    as a fallback if the file is missing or cannot be loaded.
    """
    return {
        "version": "1.0",
        "coverage": {
            "minutes_coverage": {"warning": 90, "critical": 80},
            "usage_rate_coverage": {"warning": 90, "critical": 80},
            "prediction_coverage": {"warning": 70, "critical": 50},
        },
        "field_completeness": {
            "fg_attempts": {"pass": 90},
            "ft_attempts": {"pass": 90},
            "three_pt_attempts": {"pass": 90},
            "default": {"pass": 85},
        },
        "phase_processing": {
            "phase3": {"expected_processors": 5},
            "phase4": {"expected_processors": 3},
            "phase5": {"expected_systems": 5},
        },
        "accuracy": {
            "spot_check": {"pass": 95, "warning": 90, "critical": 85},
            "prediction_accuracy": {"pass": 60, "warning": 50, "critical": 40},
        },
        "freshness": {
            "raw_data": {"max_age_hours": 24},
            "analytics": {"max_age_hours": 12},
            "predictions": {"max_age_hours": 8},
            "features": {"max_age_hours": 6},
        },
        "quality": {
            "feature_quality": {"pass": 75, "warning": 65, "critical": 50},
            "low_quality_percentage": {"max_allowed": 30},
            "quality_drop": {"threshold": 5},
        },
        "record_counts": {
            "predictions_per_system": {"min": 300, "typical": 335},
            "players_per_game": {"min": 10, "max": 15},
            "max_validation_failures": {"default": 5},
        },
        "duplicates": {
            "max_ratio": {"warning": 1.05, "critical": 1.10},
            "max_count": {"warning": 10, "critical": 50},
        },
        "grading": {
            "completion": {"pass": 100, "warning": 95},
            "backlog": {"max_days": 2},
        },
    }


def reload_config() -> Dict[str, Any]:
    """
    Force reload the configuration from disk.

    Useful for testing or when the config file has been updated.

    Returns:
        The freshly loaded configuration dictionary.
    """
    global _config_cache, _config_file_path
    _config_cache = None
    _config_file_path = None
    return _load_config()


def get_config() -> Dict[str, Any]:
    """
    Get the full validation configuration.

    Returns:
        The complete configuration dictionary.
    """
    return _load_config()


def get_config_section(section: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific section of the configuration.

    Args:
        section: The top-level section name (e.g., 'coverage', 'accuracy')

    Returns:
        The configuration section dictionary, or None if not found.
    """
    config = _load_config()
    return config.get(section)


def get_threshold(
    metric: str,
    level: str,
    default: Optional[Union[int, float]] = None,
    section: Optional[str] = None,
) -> Union[int, float, None]:
    """
    Get a specific threshold value.

    This is the primary interface for accessing validation thresholds.

    Args:
        metric: The metric name (e.g., 'minutes_coverage', 'spot_check')
        level: The threshold level (e.g., 'warning', 'critical', 'pass')
        default: Default value if threshold not found
        section: Optional section to look in first (e.g., 'coverage', 'accuracy')

    Returns:
        The threshold value, or the default if not found.

    Examples:
        >>> get_threshold('minutes_coverage', 'warning')
        90
        >>> get_threshold('spot_check', 'pass')
        95
        >>> get_threshold('custom', 'warning', default=80)
        80
    """
    config = _load_config()

    # If section is specified, look there first
    if section:
        section_config = config.get(section, {})
        metric_config = section_config.get(metric, {})
        if level in metric_config:
            return metric_config[level]

    # Search through all sections for the metric
    search_sections = ["coverage", "accuracy", "quality", "freshness", "field_completeness"]

    for search_section in search_sections:
        section_config = config.get(search_section, {})
        metric_config = section_config.get(metric, {})
        if isinstance(metric_config, dict) and level in metric_config:
            return metric_config[level]

    # Check phase_processing for processor counts
    if metric in ["phase3", "phase4", "phase5"]:
        phase_config = config.get("phase_processing", {}).get(metric, {})
        if level == "expected_processors":
            return phase_config.get("expected_processors", default)
        if level == "expected_systems":
            return phase_config.get("expected_systems", default)

    # Check record_counts
    record_config = config.get("record_counts", {}).get(metric, {})
    if isinstance(record_config, dict) and level in record_config:
        return record_config[level]

    # Check grading
    grading_config = config.get("grading", {}).get(metric, {})
    if isinstance(grading_config, dict) and level in grading_config:
        return grading_config[level]

    # Check duplicates
    duplicates_config = config.get("duplicates", {}).get(metric, {})
    if isinstance(duplicates_config, dict) and level in duplicates_config:
        return duplicates_config[level]

    logger.debug(f"Threshold not found: metric={metric}, level={level}, using default={default}")
    return default


def get_phase_processors(phase: str) -> int:
    """
    Get the expected number of processors for a pipeline phase.

    Args:
        phase: The phase name ('phase3', 'phase4', 'phase5')

    Returns:
        The expected number of processors.
    """
    config = _load_config()
    phase_config = config.get("phase_processing", {}).get(phase, {})

    if "expected_processors" in phase_config:
        return phase_config["expected_processors"]
    if "expected_systems" in phase_config:
        return phase_config["expected_systems"]

    # Defaults
    defaults = {"phase3": 5, "phase4": 3, "phase5": 5}
    return defaults.get(phase, 0)


def get_prediction_systems() -> list:
    """
    Get the list of expected prediction system IDs.

    Returns:
        List of prediction system ID strings.
    """
    config = _load_config()
    phase5_config = config.get("phase_processing", {}).get("phase5", {})
    return phase5_config.get(
        "system_ids",
        [
            "catboost_v8",
            "ensemble_v1",
            "moving_average",
            "similarity_balanced_v1",
            "zone_matchup_v1",
        ],
    )


def get_freshness_threshold(data_type: str) -> int:
    """
    Get the maximum age in hours for a data type.

    Args:
        data_type: Type of data ('raw_data', 'analytics', 'predictions', 'features')

    Returns:
        Maximum age in hours.
    """
    config = _load_config()
    freshness_config = config.get("freshness", {}).get(data_type, {})
    return freshness_config.get("max_age_hours", 24)


def check_threshold(
    value: Union[int, float],
    metric: str,
    section: Optional[str] = None,
) -> str:
    """
    Check a value against warning and critical thresholds.

    Args:
        value: The value to check
        metric: The metric name
        section: Optional section to look in

    Returns:
        'pass', 'warning', or 'critical' status string
    """
    critical = get_threshold(metric, "critical", default=0, section=section)
    warning = get_threshold(metric, "warning", default=0, section=section)

    if critical is not None and value < critical:
        return "critical"
    if warning is not None and value < warning:
        return "warning"
    return "pass"


# Convenience aliases for common thresholds
def get_minutes_coverage_threshold(level: str = "warning") -> int:
    """Get minutes coverage threshold."""
    return get_threshold("minutes_coverage", level, default=90 if level == "warning" else 80)


def get_usage_rate_coverage_threshold(level: str = "warning") -> int:
    """Get usage rate coverage threshold."""
    return get_threshold("usage_rate_coverage", level, default=90 if level == "warning" else 80)


def get_prediction_coverage_threshold(level: str = "warning") -> int:
    """Get prediction coverage threshold."""
    return get_threshold("prediction_coverage", level, default=70 if level == "warning" else 50)


def get_spot_check_threshold(level: str = "pass") -> int:
    """Get spot check accuracy threshold."""
    return get_threshold("spot_check", level, default=95)


if __name__ == "__main__":
    # Demo/test the configuration loader
    import sys

    logging.basicConfig(level=logging.DEBUG)

    print("=" * 60)
    print("Validation Thresholds Configuration Loader")
    print("=" * 60)

    config_path = _get_config_path()
    print(f"\nConfig file: {config_path}")
    print(f"Config exists: {config_path.exists()}")

    print("\n--- Coverage Thresholds ---")
    print(f"minutes_coverage warning: {get_threshold('minutes_coverage', 'warning')}")
    print(f"minutes_coverage critical: {get_threshold('minutes_coverage', 'critical')}")
    print(f"usage_rate_coverage warning: {get_threshold('usage_rate_coverage', 'warning')}")
    print(f"prediction_coverage warning: {get_threshold('prediction_coverage', 'warning')}")
    print(f"prediction_coverage critical: {get_threshold('prediction_coverage', 'critical')}")

    print("\n--- Field Completeness ---")
    print(f"fg_attempts pass: {get_threshold('fg_attempts', 'pass', section='field_completeness')}")
    print(f"ft_attempts pass: {get_threshold('ft_attempts', 'pass', section='field_completeness')}")

    print("\n--- Phase Processing ---")
    print(f"phase3 expected processors: {get_phase_processors('phase3')}")
    print(f"phase5 expected systems: {get_phase_processors('phase5')}")

    print("\n--- Accuracy Thresholds ---")
    print(f"spot_check pass: {get_threshold('spot_check', 'pass')}")
    print(f"spot_check warning: {get_threshold('spot_check', 'warning')}")
    print(f"spot_check critical: {get_threshold('spot_check', 'critical')}")

    print("\n--- Prediction Systems ---")
    print(f"Systems: {get_prediction_systems()}")

    print("\n--- Freshness Thresholds ---")
    print(f"raw_data max_age: {get_freshness_threshold('raw_data')} hours")
    print(f"predictions max_age: {get_freshness_threshold('predictions')} hours")

    print("\n--- Threshold Checking ---")
    test_value = 85
    print(f"Value {test_value} vs minutes_coverage: {check_threshold(test_value, 'minutes_coverage')}")
    test_value = 75
    print(f"Value {test_value} vs minutes_coverage: {check_threshold(test_value, 'minutes_coverage')}")

    print("\n--- Default Fallback ---")
    print(f"nonexistent metric: {get_threshold('nonexistent', 'warning', default=42)}")

    print("\n" + "=" * 60)
    print("Configuration loaded successfully!")
