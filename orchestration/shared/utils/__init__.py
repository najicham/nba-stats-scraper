# Orchestration Shared Utilities
#
# This package contains utilities shared across orchestration cloud functions.
# To consolidate duplicate code, all cloud functions should import from here.
#
# Usage:
#   from orchestration.shared.utils import retry_with_jitter
#   from orchestration.shared.utils.bigquery_retry import SERIALIZATION_RETRY
#   from orchestration.shared.utils.slack_retry import send_slack_webhook_with_retry

# Retry utilities
from orchestration.shared.utils.retry_with_jitter import (
    retry_with_jitter,
    retry_with_simple_jitter,
    retry_fast,
    retry_standard,
    retry_patient,
    retry_aggressive,
)

from orchestration.shared.utils.circuit_breaker import CircuitBreaker
from orchestration.shared.utils.distributed_lock import DistributedLock

# BigQuery retry decorators
from orchestration.shared.utils.bigquery_retry import (
    SERIALIZATION_RETRY,
    QUOTA_RETRY,
    TRANSIENT_RETRY,
    retry_on_serialization,
    retry_on_quota_exceeded,
    retry_on_transient,
    is_serialization_error,
    is_quota_exceeded_error,
    is_transient_error,
    extract_table_name,
)

# Slack utilities
from orchestration.shared.utils.slack_retry import (
    retry_slack_webhook,
    send_slack_webhook_with_retry,
)

from orchestration.shared.utils.slack_channels import (
    send_to_slack,
    send_prediction_summary_to_slack,
    send_health_summary_to_slack,
    send_stall_alert_to_slack,
    test_all_channels,
)

# Storage utilities
from orchestration.shared.utils.storage_client import StorageClient, GCS_RETRY

# Pub/Sub utilities
from orchestration.shared.utils.pubsub_client import PubSubClient

# Alert utilities
from orchestration.shared.utils.alert_types import (
    ALERT_TYPES,
    get_alert_config,
    detect_alert_type,
    format_alert_heading,
    get_alert_html_heading,
)

from orchestration.shared.utils.email_alerting import (
    EmailAlerter,
    AlertThresholds,
    send_quick_error_alert,
)

# Hash utilities
from orchestration.shared.utils.hash_utils import (
    compute_hash_from_dict,
    compute_hash_static,
)

__all__ = [
    # Retry
    'retry_with_jitter',
    'retry_with_simple_jitter',
    'retry_fast',
    'retry_standard',
    'retry_patient',
    'retry_aggressive',
    'CircuitBreaker',
    'DistributedLock',
    # BigQuery
    'SERIALIZATION_RETRY',
    'QUOTA_RETRY',
    'TRANSIENT_RETRY',
    'retry_on_serialization',
    'retry_on_quota_exceeded',
    'retry_on_transient',
    'is_serialization_error',
    'is_quota_exceeded_error',
    'is_transient_error',
    'extract_table_name',
    # Slack
    'retry_slack_webhook',
    'send_slack_webhook_with_retry',
    'send_to_slack',
    'send_prediction_summary_to_slack',
    'send_health_summary_to_slack',
    'send_stall_alert_to_slack',
    'test_all_channels',
    # Storage
    'StorageClient',
    'GCS_RETRY',
    # Pub/Sub
    'PubSubClient',
    # Alerts
    'ALERT_TYPES',
    'get_alert_config',
    'detect_alert_type',
    'format_alert_heading',
    'get_alert_html_heading',
    'EmailAlerter',
    'AlertThresholds',
    'send_quick_error_alert',
    # Hash
    'compute_hash_from_dict',
    'compute_hash_static',
]
