# shared/utils/sentry_config.py
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
import os

# SQLAlchemy integration is optional - only available if sqlalchemy is installed
try:
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False
    SqlalchemyIntegration = None


def is_local():
    """Check if running in local development environment."""
    return os.environ.get("ENV", "") == "local"


def get_sentry_dsn():
    """Get Sentry DSN from environment or return None."""
    return os.environ.get("SENTRY_DSN")

def configure_sentry():
    """Configure Sentry with optimal settings for NBA analytics platform"""

    # Get Sentry DSN from environment variable
    sentry_dsn = get_sentry_dsn()
    if not sentry_dsn:
        return
        
    environment = "development" if is_local() else os.getenv("ENVIRONMENT", "production")
    
    # Determine sampling rates based on environment
    if environment == "development":
        error_sample_rate = 1.0
        traces_sample_rate = 1.0
        profiles_sample_rate = 1.0
    elif environment == "staging":
        error_sample_rate = 1.0
        traces_sample_rate = 0.5
        profiles_sample_rate = 0.1
    else:  # production
        error_sample_rate = 1.0
        traces_sample_rate = 0.1
        profiles_sample_rate = 0.01
    
    sentry_sdk.init(
        dsn=sentry_dsn,
        environment=environment,
        
        # Error tracking
        sample_rate=error_sample_rate,
        
        # Performance monitoring
        enable_tracing=True,
        traces_sample_rate=traces_sample_rate,
        
        # Profiling (helps identify slow code)
        profiles_sample_rate=profiles_sample_rate,
        
        # Integrations
        integrations=[
            FlaskIntegration(
                transaction_style='endpoint'  # Track by Flask route
            ),
            *(
                [SqlalchemyIntegration()]  # Track database queries (if SQLAlchemy available)
                if HAS_SQLALCHEMY else []
            ),
            LoggingIntegration(
                level=None,  # Capture all log levels
                event_level=None  # Send logs as breadcrumbs
            ),
        ],
        
        # Release tracking
        release=os.getenv("SENTRY_RELEASE", "unknown"),
        
        # Additional context
        before_send=before_send_filter,
        before_send_transaction=before_send_transaction_filter,
        
        # PII settings
        send_default_pii=False,  # Don't send sensitive data
        
        # Performance
        max_breadcrumbs=50,  # Keep reasonable history
        attach_stacktrace=True,  # Always include stack traces
    )

def before_send_filter(event, hint):
    """Filter and enhance events before sending to Sentry"""
    
    # Add custom tags for better organization
    event.setdefault('tags', {})
    event['tags']['service'] = os.getenv('K_SERVICE', 'unknown')
    event['tags']['project'] = 'nba-analytics'
    
    # Add custom context
    event.setdefault('extra', {})
    event['extra']['container_id'] = os.getenv('HOSTNAME', 'unknown')
    
    # Filter out expected errors (don't spam Sentry)
    if 'exception' in event:
        exc_type = event['exception']['values'][0]['type']
        
        # Don't send these common/expected errors
        if exc_type in ['KeyboardInterrupt', 'SystemExit']:
            return None
            
        # Don't send rate limit errors (we expect these)
        if 'rate limit' in str(event).lower():
            return None
    
    return event

def before_send_transaction_filter(event, hint):
    """Filter performance transactions"""
    
    # Don't track health check requests (too noisy)
    if event.get('transaction', '').endswith('/health'):
        return None
        
    # Add custom tags for performance analysis
    event.setdefault('tags', {})
    event['tags']['service'] = os.getenv('K_SERVICE', 'unknown')
    
    return event

def add_scraper_context(scraper_name: str, run_id: str, opts: dict):
    """Add scraper-specific context to Sentry"""
    sentry_sdk.set_tag("scraper.name", scraper_name)
    sentry_sdk.set_tag("scraper.run_id", run_id)
    sentry_sdk.set_context("scraper_opts", {
        "sport": opts.get("sport"),
        "date": opts.get("date"),
        "group": opts.get("group"),
        "debug": opts.get("debug", False)
    })

def track_scraper_performance(scraper_name: str):
    """Decorator to track scraper performance"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with sentry_sdk.start_transaction(
                op="scraper",
                name=f"{scraper_name}.run"
            ) as transaction:
                transaction.set_tag("scraper.name", scraper_name)
                return func(*args, **kwargs)
        return wrapper
    return decorator