"""
Conftest for property-based tests.

Configures Hypothesis settings for the NBA Stats Scraper test suite.
"""

import pytest
from hypothesis import settings, Verbosity, Phase

# =============================================================================
# Hypothesis Profiles
# =============================================================================

# Default profile for regular test runs
settings.register_profile(
    "default",
    max_examples=100,
    deadline=None,  # Disable deadline for complex tests
    suppress_health_check=[],
    verbosity=Verbosity.normal,
)

# CI profile with more examples for thorough testing
settings.register_profile(
    "ci",
    max_examples=500,
    deadline=None,
    suppress_health_check=[],
    verbosity=Verbosity.normal,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
)

# Debug profile with verbose output
settings.register_profile(
    "debug",
    max_examples=50,
    deadline=None,
    verbosity=Verbosity.verbose,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
)

# Quick profile for fast feedback during development
settings.register_profile(
    "quick",
    max_examples=20,
    deadline=None,
    verbosity=Verbosity.quiet,
    phases=[Phase.explicit, Phase.generate],  # Skip shrinking for speed
)

# Load the default profile
settings.load_profile("default")


# =============================================================================
# Pytest Fixtures
# =============================================================================

@pytest.fixture
def nba_teams():
    """Fixture providing valid NBA team abbreviations."""
    return [
        "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
        "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
        "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"
    ]


@pytest.fixture
def injury_statuses():
    """Fixture providing valid injury statuses."""
    return ['available', 'probable', 'questionable', 'doubtful', 'out']


@pytest.fixture
def quality_tiers():
    """Fixture providing quality tier definitions."""
    return {
        'gold': {'min_score': 90, 'max_score': 100, 'production_ready': True},
        'silver': {'min_score': 75, 'max_score': 89, 'production_ready': True},
        'bronze': {'min_score': 60, 'max_score': 74, 'production_ready': True},
        'poor': {'min_score': 40, 'max_score': 59, 'production_ready': False},
        'unusable': {'min_score': 0, 'max_score': 39, 'production_ready': False},
    }


@pytest.fixture
def feature_thresholds():
    """Fixture providing feature threshold definitions."""
    return {
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
# Pytest Hooks
# =============================================================================

def pytest_configure(config):
    """Configure pytest for property tests."""
    # Register the property marker
    config.addinivalue_line(
        "markers", "property: mark test as property-based test using Hypothesis"
    )


def pytest_collection_modifyitems(config, items):
    """Add property marker to all tests in this directory."""
    for item in items:
        if "property" in str(item.fspath):
            item.add_marker(pytest.mark.property)
