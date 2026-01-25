# shared/utils/__init__.py
"""
Shared utilities for NBA analytics platform with lazy loading.

Heavy modules (pandas, psutil, etc.) are loaded on-demand to reduce
cold start time and prevent import errors in cloud functions.
"""

# Lightweight imports only - no external dependencies beyond Google Cloud SDK
from .bigquery_client import BigQueryClient
from .storage_client import StorageClient
from .pubsub_client import PubSubClient
from .auth_utils import get_service_account_credentials
from .nba_team_mapper import get_nba_tricode, get_nba_tricode_fuzzy

# Game ID conversion utilities (lightweight)
from .game_id_converter import (
    GameIdConverter,
    get_game_id_converter,
    to_standard_game_id,
    parse_game_id,
    is_standard_game_id
)

# Environment validation utilities (lightweight)
from .env_validation import (
    validate_required_env_vars,
    get_required_env_var,
    MissingEnvironmentVariablesError
)


__all__ = [
    # Lightweight imports (loaded immediately)
    "BigQueryClient",
    "StorageClient",
    "PubSubClient",
    "get_service_account_credentials",
    "get_nba_tricode",
    "get_nba_tricode_fuzzy",
    # Game ID converter
    "GameIdConverter",
    "get_game_id_converter",
    "to_standard_game_id",
    "parse_game_id",
    "is_standard_game_id",
    # Environment validation
    "validate_required_env_vars",
    "get_required_env_var",
    "MissingEnvironmentVariablesError",

    # Heavy imports (lazy-loaded on access)
    # Rate limiting
    "RateLimiter",
    "RateLimitConfig",
    "get_rate_limiter",
    "get_rate_limiter_for_url",
    "get_all_rate_limiter_stats",
    "reset_all_rate_limiters",
    "rate_limited",
    # Prometheus metrics (psutil dependency)
    "PrometheusMetrics",
    "create_metrics_blueprint",
    "setup_prometheus_metrics",
    "MetricsMiddleware",
    "Counter",
    "Gauge",
    "Histogram",
    # Roster management (pandas dependency)
    "RosterManager",
    "RosterChangeTracker",
    "ActiveRosterCalculator",
    "RosterChange",
    "PlayerAvailability",
    "TeamRoster",
    "TransactionType",
    "AvailabilityStatus",
    "get_roster_manager",
    "get_active_roster",
    "check_player_availability",
    "get_roster_changes",
    # Completion tracking
    "CompletionTracker",
    "get_completion_tracker",
    # Proxy management
    "ProxyManager",
    "ProxyHealth",
    "ProxyHealthMetrics",
    "ProxyStatus",
    "ProxyConfig",
    "get_proxy_manager",
    "get_healthy_proxy_urls",
    "record_proxy_result",
]


def __getattr__(name):
    """
    Lazy load heavy modules only when accessed.

    This prevents importing pandas, psutil, and other heavy dependencies
    unless they're actually needed by the calling code.
    """

    # Rate limiting utilities
    if name in ['RateLimiter', 'RateLimitConfig', 'get_rate_limiter',
                'get_rate_limiter_for_url', 'get_all_rate_limiter_stats',
                'reset_all_rate_limiters', 'rate_limited']:
        from .rate_limiter import (
            RateLimiter,
            RateLimitConfig,
            get_rate_limiter,
            get_rate_limiter_for_url,
            get_all_rate_limiter_stats,
            reset_all_rate_limiters,
            rate_limited,
        )
        return locals()[name]

    # Prometheus metrics utilities (psutil)
    if name in ['PrometheusMetrics', 'create_metrics_blueprint', 'setup_prometheus_metrics',
                'MetricsMiddleware', 'Counter', 'Gauge', 'Histogram']:
        from .prometheus_metrics import (
            PrometheusMetrics,
            create_metrics_blueprint,
            setup_prometheus_metrics,
            MetricsMiddleware,
            Counter,
            Gauge,
            Histogram
        )
        return locals()[name]

    # Roster management utilities (pandas)
    if name in ['RosterManager', 'RosterChangeTracker', 'ActiveRosterCalculator',
                'RosterChange', 'PlayerAvailability', 'TeamRoster', 'TransactionType',
                'AvailabilityStatus', 'get_roster_manager', 'get_active_roster',
                'check_player_availability', 'get_roster_changes']:
        from .roster_manager import (
            RosterManager,
            RosterChangeTracker,
            ActiveRosterCalculator,
            RosterChange,
            PlayerAvailability,
            TeamRoster,
            TransactionType,
            AvailabilityStatus,
            get_roster_manager,
            get_active_roster,
            check_player_availability,
            get_roster_changes,
        )
        return locals()[name]

    # Completion tracking
    if name in ['CompletionTracker', 'get_completion_tracker']:
        from .completion_tracker import (
            CompletionTracker,
            get_completion_tracker,
        )
        return locals()[name]

    # Proxy management
    if name in ['ProxyManager', 'ProxyHealth', 'ProxyHealthMetrics', 'ProxyStatus',
                'ProxyConfig', 'get_proxy_manager', 'get_healthy_proxy_urls',
                'record_proxy_result']:
        from .proxy_manager import (
            ProxyManager,
            ProxyHealth,
            ProxyHealthMetrics,
            ProxyStatus,
            ProxyConfig,
            get_proxy_manager,
            get_healthy_proxy_urls,
            record_proxy_result,
        )
        return locals()[name]

    raise AttributeError(f"module 'shared.utils' has no attribute '{name}'")
