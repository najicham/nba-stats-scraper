# External Service Circuit Breaker Pattern

## Overview

The external service circuit breaker provides protection against cascading failures when calling external APIs and services. It complements the existing circuit breaker implementations in the codebase:

| Circuit Breaker | Scope | Use Case |
|-----------------|-------|----------|
| `CircuitBreakerMixin` | Processor-level | Phase 3/4/5 data processors |
| `SystemCircuitBreaker` | Prediction system-level | Phase 5 ML systems (xgboost, ensemble, etc.) |
| `RateLimitHandler` | Rate-limit specific | API rate limiting with backoff |
| `ExternalServiceCircuitBreaker` | External service calls | Slack, GCS, third-party APIs |

## Quick Start

### Option 1: Decorator (Recommended for Functions)

```python
from shared.utils.external_service_circuit_breaker import circuit_breaker_protected

@circuit_breaker_protected("external_api")
def fetch_data_from_api():
    response = requests.get("https://api.example.com/data")
    response.raise_for_status()
    return response.json()
```

### Option 2: Context Manager

```python
from shared.utils.external_service_circuit_breaker import get_service_circuit_breaker

cb = get_service_circuit_breaker("gcs_upload")
with cb:
    blob.upload_from_string(data)
```

### Option 3: Wrapper Function

```python
from shared.utils.external_service_circuit_breaker import call_with_circuit_breaker

result = call_with_circuit_breaker(
    "external_api",
    lambda: requests.get("https://api.example.com/data")
)
```

### Option 4: Direct Call

```python
from shared.utils.external_service_circuit_breaker import (
    ExternalServiceCircuitBreaker,
    CircuitBreakerError,
)

cb = ExternalServiceCircuitBreaker("my_service")

try:
    result = cb.call(lambda: external_api_call())
except CircuitBreakerError:
    # Service is down, use fallback
    result = get_cached_result()
```

## Circuit Breaker States

```
    CLOSED ──(failures >= threshold)──> OPEN
       ^                                   │
       │                                   │
    (success)                         (timeout expires)
       │                                   │
       └──────── HALF_OPEN <───────────────┘
                    │
              (any failure)
                    │
                    v
                  OPEN
```

1. **CLOSED**: Normal operation. Requests pass through. Failures are tracked.
2. **OPEN**: Service is failing. Requests fail fast without attempting.
3. **HALF_OPEN**: Testing recovery. Limited requests allowed through.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EXTERNAL_CB_THRESHOLD` | 5 | Failures before opening circuit |
| `EXTERNAL_CB_TIMEOUT_SECONDS` | 300 | Seconds to stay open before testing |
| `EXTERNAL_CB_HALF_OPEN_MAX_CALLS` | 3 | Successes needed in half-open to close |

### Programmatic Configuration

```python
from shared.utils.external_service_circuit_breaker import (
    ExternalServiceCircuitBreaker,
    CircuitBreakerConfig,
)

config = CircuitBreakerConfig(
    threshold=3,              # Open after 3 failures
    timeout_seconds=120,      # Stay open for 2 minutes
    half_open_max_calls=2,    # Need 2 successes to recover
)

cb = ExternalServiceCircuitBreaker("critical_api", config=config)
```

## Currently Protected Services

### GCS API (Phase 6 Publishing)

```python
# In data_processors/publishing/base_exporter.py
from shared.utils.external_service_circuit_breaker import (
    get_service_circuit_breaker,
    CircuitBreakerError,
)

GCS_CIRCUIT_BREAKER_SERVICE = "gcs_api_export"

def upload_to_gcs(self, json_data, path):
    cb = get_service_circuit_breaker(GCS_CIRCUIT_BREAKER_SERVICE)

    if not cb.is_available():
        raise CircuitBreakerError(...)

    try:
        self._upload_blob_with_retry(blob, json_str, cache_control)
        cb._record_success()
    except (ServiceUnavailable, DeadlineExceeded) as e:
        cb._record_failure(e)
        raise
```

### Slack Webhook API

```python
# In shared/utils/notification_system.py
SLACK_CIRCUIT_BREAKER_SERVICE = "slack_webhook_api"

def send_notification(self, ...):
    cb = get_service_circuit_breaker(SLACK_CIRCUIT_BREAKER_SERVICE)

    if not cb.is_available():
        logger.warning("Slack circuit breaker OPEN - skipping notification")
        return False

    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        cb._record_success()
        return True
    except requests.exceptions.RequestException as e:
        cb._record_failure(e)
        return False
```

## Monitoring

### Get All Circuit Breaker Status

```python
from shared.utils.external_service_circuit_breaker import get_all_circuit_breaker_status

status = get_all_circuit_breaker_status()
for service_name, info in status.items():
    print(f"{service_name}: {info['state']}")
    if info['state'] == 'OPEN':
        print(f"  - Opened at: {info['opened_at']}")
        print(f"  - Timeout remaining: {info['timeout_remaining']:.1f}s")
```

### Manual Reset

```python
from shared.utils.external_service_circuit_breaker import reset_circuit_breaker

# Reset specific circuit
reset_circuit_breaker("slack_webhook_api")

# Reset all circuits
from shared.utils.external_service_circuit_breaker import reset_all_circuit_breakers
reset_all_circuit_breakers()
```

## Adding Circuit Breaker to New Services

1. Choose a unique service name (e.g., `"new_external_api"`)
2. Get or create circuit breaker: `cb = get_service_circuit_breaker("new_external_api")`
3. Wrap external calls with circuit breaker protection
4. Handle `CircuitBreakerError` appropriately (fallback, skip, etc.)

### Example: Adding to a New API Client

```python
from shared.utils.external_service_circuit_breaker import (
    get_service_circuit_breaker,
    CircuitBreakerError,
    CircuitBreakerConfig,
)

# Custom config for this API (optional)
config = CircuitBreakerConfig(
    threshold=5,
    timeout_seconds=180,
)

class MyApiClient:
    def __init__(self):
        self.cb = get_service_circuit_breaker("my_api", config)

    def fetch_data(self, endpoint):
        if not self.cb.is_available():
            raise CircuitBreakerError(...)

        try:
            response = requests.get(f"{BASE_URL}/{endpoint}")
            response.raise_for_status()
            self.cb._record_success()
            return response.json()
        except requests.RequestException as e:
            self.cb._record_failure(e)
            raise
```

## Related Files

- `shared/utils/external_service_circuit_breaker.py` - Main implementation
- `shared/processors/patterns/circuit_breaker_mixin.py` - Processor-level circuit breaker
- `predictions/worker/system_circuit_breaker.py` - Prediction system circuit breaker
- `shared/utils/rate_limit_handler.py` - Rate limit handling with circuit breaker
- `shared/constants/resilience.py` - Centralized resilience constants
- `shared/config/circuit_breaker_config.py` - Processor circuit breaker configuration

## Best Practices

1. **Choose appropriate thresholds**: Critical services may need lower thresholds (faster detection)
2. **Use meaningful service names**: Makes monitoring and debugging easier
3. **Handle CircuitBreakerError gracefully**: Implement fallbacks when possible
4. **Log circuit state changes**: Already done by the library, but add context in your code
5. **Monitor circuit breaker status**: Use `get_all_circuit_breaker_status()` in health checks
