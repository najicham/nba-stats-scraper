# shared/utils/__init__.py
"""
Shared utilities for NBA analytics platform
"""

from .bigquery_client import BigQueryClient
from .storage_client import StorageClient
from .pubsub_client import PubSubClient
# from .logging_utils import setup_logging, get_logger
# from .metrics_utils import send_metric, create_custom_metric
from .auth_utils import get_service_account_credentials
# Lazy-loaded team mapper - use get_nba_tricode() convenience functions instead of direct import
from .nba_team_mapper import get_nba_tricode, get_nba_tricode_fuzzy

# Game ID conversion utilities
from .game_id_converter import (
    GameIdConverter,
    get_game_id_converter,
    to_standard_game_id,
    parse_game_id,
    is_standard_game_id
)

# Environment validation utilities
from .env_validation import (
    validate_required_env_vars,
    get_required_env_var,
    MissingEnvironmentVariablesError
)

# Rate limiting utilities
from .rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    get_rate_limiter,
    get_rate_limiter_for_url,
    get_all_rate_limiter_stats,
    reset_all_rate_limiters,
    rate_limited,
)

# Prometheus metrics utilities
from .prometheus_metrics import (
    PrometheusMetrics,
    create_metrics_blueprint,
    setup_prometheus_metrics,
    MetricsMiddleware,
    Counter,
    Gauge,
    Histogram
)


__all__ = [
    "BigQueryClient",
    "StorageClient",
    "PubSubClient",
    #"setup_logging",
    #"get_logger",
    #"send_metric",
    #"create_custom_metric",
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
    # Rate limiting
    "RateLimiter",
    "RateLimitConfig",
    "get_rate_limiter",
    "get_rate_limiter_for_url",
    "get_all_rate_limiter_stats",
    "reset_all_rate_limiters",
    "rate_limited",
    # Prometheus metrics
    "PrometheusMetrics",
    "create_metrics_blueprint",
    "setup_prometheus_metrics",
    "MetricsMiddleware",
    "Counter",
    "Gauge",
    "Histogram",
]
