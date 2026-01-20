# Centralized Error Logging Strategy

**Created**: 2026-01-20
**Status**: 🎯 COMPREHENSIVE - Ready for Implementation
**Priority**: P0 - Critical for Operations

---

## Executive Summary

**Problem**: Errors currently scattered across:
- Cloud Functions logs (7+ functions)
- Cloud Run logs (10+ services)
- Scraper logs (20+ scrapers)
- Processor logs (15+ processors)
- No aggregation, trending, or centralized view

**Solution**: Implement 3-layer error logging:
1. **Structured Logging** - Consistent format across all components
2. **Error Aggregation** - Cloud Error Reporting + BigQuery table
3. **Error Intelligence** - Trending, grouping, alerting

**Impact**:
- Reduce MTTD (Mean Time to Detect) from hours to minutes
- Enable proactive error prevention
- Single dashboard for all system errors

---

## Current State Analysis

### Error Logging Gaps

| Component | Current Logging | Issues |
|-----------|----------------|--------|
| **Cloud Functions** | Individual logs | No aggregation, hard to search |
| **Cloud Run Services** | Individual logs | No correlation across services |
| **Scrapers** | Print statements | Inconsistent format |
| **Processors** | Mixed formats | No structured fields |
| **BigQuery Jobs** | Job logs only | No business context |
| **Pub/Sub Messages** | Delivery only | No payload errors |

### What We Can't Answer Today

❌ "What are the top 5 errors in the past week?"
❌ "Is error rate increasing?"
❌ "Which scraper fails most often?"
❌ "What errors happened during Phase 4 on Jan 18?"
❌ "Are there error patterns by time of day?"
❌ "Which errors need immediate attention?"

---

## Proposed Architecture

### Layer 1: Structured Logging (All Components)

**Shared Error Logger Module**

```python
# NEW FILE: shared/utils/error_logger.py

"""
Centralized Error Logger

Usage:
    from shared.utils.error_logger import ErrorLogger

    logger = ErrorLogger(component='phase4_processor', service='PDC')

    # Log error with context
    logger.error(
        error_type='DATA_VALIDATION_FAILED',
        message='Player data missing required fields',
        context={
            'game_date': '2026-01-20',
            'player_id': 'jokicni01',
            'missing_fields': ['points', 'rebounds']
        },
        severity='HIGH',
        actionable=True
    )
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Any
from enum import Enum
from google.cloud import bigquery
from google.cloud import error_reporting


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "LOW"           # Info, expected errors
    MEDIUM = "MEDIUM"     # Warnings, recoverable
    HIGH = "HIGH"         # Errors, needs attention
    CRITICAL = "CRITICAL" # System failures, immediate action


class ErrorCategory(Enum):
    """Error categories for grouping."""
    DATA_VALIDATION = "DATA_VALIDATION"
    API_FAILURE = "API_FAILURE"
    DATABASE_ERROR = "DATABASE_ERROR"
    PROCESSING_ERROR = "PROCESSING_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION = "AUTHENTICATION"
    RATE_LIMIT = "RATE_LIMIT"


class ErrorLogger:
    """
    Centralized error logger for NBA pipeline.

    Logs to:
    1. Cloud Logging (structured)
    2. Cloud Error Reporting (aggregation)
    3. BigQuery (analysis)
    4. Slack (critical only)
    """

    def __init__(
        self,
        component: str,
        service: Optional[str] = None,
        project_id: str = "nba-props-platform"
    ):
        """
        Initialize error logger.

        Args:
            component: High-level component (e.g., 'phase4', 'scraper', 'grading')
            service: Specific service name (e.g., 'PDC', 'bdl_box_scores')
            project_id: GCP project ID
        """
        self.component = component
        self.service = service or component
        self.project_id = project_id

        # Initialize loggers
        self.logger = logging.getLogger(f"{component}.{service}")
        self.error_client = error_reporting.Client()
        self.bq_client = bigquery.Client(project=project_id)

        # BigQuery table for error storage
        self.error_table = f"{project_id}.nba_monitoring.system_errors"

    def error(
        self,
        error_type: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        exception: Optional[Exception] = None,
        severity: str = "MEDIUM",
        category: str = "PROCESSING_ERROR",
        actionable: bool = False,
        auto_retry: bool = False
    ) -> str:
        """
        Log an error to all destinations.

        Args:
            error_type: Error identifier (e.g., 'MISSING_BOX_SCORES')
            message: Human-readable error message
            context: Additional context (game_date, player_id, etc.)
            exception: Python exception if available
            severity: LOW, MEDIUM, HIGH, CRITICAL
            category: Error category for grouping
            actionable: Requires human intervention?
            auto_retry: Should system auto-retry?

        Returns:
            error_id: Unique error ID for tracking
        """
        # Generate error ID
        error_id = f"{self.component}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"

        # Build structured error object
        error_record = {
            'error_id': error_id,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'component': self.component,
            'service': self.service,
            'error_type': error_type,
            'message': message,
            'severity': severity,
            'category': category,
            'context': context or {},
            'actionable': actionable,
            'auto_retry': auto_retry,
            'exception_type': type(exception).__name__ if exception else None,
            'exception_message': str(exception) if exception else None,
            'project_id': self.project_id
        }

        # 1. Log to Cloud Logging (structured)
        self.logger.error(
            json.dumps(error_record),
            extra={
                'json_fields': error_record,
                'severity': severity
            }
        )

        # 2. Report to Cloud Error Reporting (aggregation)
        if severity in ['HIGH', 'CRITICAL']:
            try:
                self.error_client.report(
                    f"[{severity}] {error_type}: {message}",
                    user=self.service
                )
            except Exception as e:
                self.logger.warning(f"Failed to report to Error Reporting: {e}")

        # 3. Write to BigQuery (analysis)
        try:
            self._write_to_bigquery(error_record)
        except Exception as e:
            self.logger.warning(f"Failed to write error to BigQuery: {e}")

        # 4. Send Slack alert (critical only)
        if severity == 'CRITICAL' and actionable:
            try:
                self._send_slack_alert(error_record)
            except Exception as e:
                self.logger.warning(f"Failed to send Slack alert: {e}")

        return error_id

    def _write_to_bigquery(self, error_record: Dict[str, Any]):
        """Write error to BigQuery for analysis."""
        # Convert context dict to JSON string
        error_record['context_json'] = json.dumps(error_record.pop('context'))

        # Insert row
        errors = self.bq_client.insert_rows_json(
            self.error_table,
            [error_record]
        )

        if errors:
            raise Exception(f"BigQuery insert failed: {errors}")

    def _send_slack_alert(self, error_record: Dict[str, Any]):
        """Send critical error to Slack."""
        import os
        import requests

        webhook_url = os.getenv('SLACK_WEBHOOK_URL_ERROR')
        if not webhook_url:
            return

        payload = {
            "attachments": [{
                "color": "#FF0000",
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"🚨 CRITICAL ERROR: {error_record['error_type']}"
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{error_record['message']}*"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Component:*\n{error_record['component']}"},
                            {"type": "mrkdwn", "text": f"*Service:*\n{error_record['service']}"},
                            {"type": "mrkdwn", "text": f"*Category:*\n{error_record['category']}"},
                            {"type": "mrkdwn", "text": f"*Error ID:*\n{error_record['error_id']}"}
                        ]
                    }
                ]
            }]
        }

        if error_record.get('context'):
            context_text = "\n".join([f"• {k}: {v}" for k, v in error_record['context'].items()])
            payload["attachments"][0]["blocks"].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Context:*\n{context_text}"
                }
            })

        requests.post(webhook_url, json=payload, timeout=10)


# Convenience functions
def log_scraper_error(scraper_name: str, error: Exception, game_date: str = None, **context):
    """Quick log for scraper errors."""
    logger = ErrorLogger(component='scraper', service=scraper_name)
    return logger.error(
        error_type='SCRAPER_FAILURE',
        message=f"Scraper {scraper_name} failed",
        exception=error,
        context={'game_date': game_date, **context},
        category='API_FAILURE',
        severity='HIGH',
        actionable=True,
        auto_retry=True
    )


def log_processor_error(processor_name: str, error: Exception, game_date: str = None, **context):
    """Quick log for processor errors."""
    logger = ErrorLogger(component='processor', service=processor_name)
    return logger.error(
        error_type='PROCESSOR_FAILURE',
        message=f"Processor {processor_name} failed",
        exception=error,
        context={'game_date': game_date, **context},
        category='PROCESSING_ERROR',
        severity='HIGH',
        actionable=True,
        auto_retry=True
    )


def log_validation_error(component: str, service: str, message: str, **context):
    """Quick log for validation errors."""
    logger = ErrorLogger(component=component, service=service)
    return logger.error(
        error_type='DATA_VALIDATION_FAILED',
        message=message,
        context=context,
        category='DATA_VALIDATION',
        severity='MEDIUM',
        actionable=False
    )
```

### Layer 2: BigQuery Error Table

**Schema for Centralized Error Storage**

```sql
-- NEW TABLE: nba_monitoring.system_errors

CREATE TABLE `nba-props-platform.nba_monitoring.system_errors` (
  error_id STRING NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  component STRING NOT NULL,       -- 'scraper', 'processor', 'phase4', etc.
  service STRING NOT NULL,          -- 'bdl_box_scores', 'PDC', etc.
  error_type STRING NOT NULL,       -- 'SCRAPER_FAILURE', 'MISSING_DATA', etc.
  message STRING NOT NULL,
  severity STRING NOT NULL,         -- 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'
  category STRING NOT NULL,         -- 'API_FAILURE', 'DATA_VALIDATION', etc.
  context_json STRING,              -- JSON with game_date, player_id, etc.
  actionable BOOLEAN NOT NULL,      -- Requires human intervention?
  auto_retry BOOLEAN NOT NULL,      -- Should system auto-retry?
  exception_type STRING,
  exception_message STRING,
  project_id STRING NOT NULL,
  resolved BOOLEAN DEFAULT FALSE,
  resolved_at TIMESTAMP,
  resolved_by STRING
)
PARTITION BY DATE(timestamp)
CLUSTER BY component, service, error_type, severity;

-- Indexes for fast queries
CREATE INDEX idx_error_lookup ON `nba-props-platform.nba_monitoring.system_errors`(timestamp DESC, severity, component);
```

### Layer 3: Error Intelligence (Queries & Dashboards)

**Common Error Analysis Queries**

```sql
-- Top errors in past 24 hours
SELECT
  error_type,
  COUNT(*) as error_count,
  MAX(severity) as max_severity,
  MIN(timestamp) as first_occurrence,
  MAX(timestamp) as last_occurrence,
  ARRAY_AGG(DISTINCT component) as affected_components
FROM `nba-props-platform.nba_monitoring.system_errors`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY error_type
ORDER BY error_count DESC
LIMIT 10;

-- Error rate trending (hourly)
SELECT
  TIMESTAMP_TRUNC(timestamp, HOUR) as hour,
  component,
  severity,
  COUNT(*) as error_count
FROM `nba-props-platform.nba_monitoring.system_errors`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY hour, component, severity
ORDER BY hour DESC;

-- Actionable errors (need human intervention)
SELECT
  error_id,
  timestamp,
  component,
  service,
  error_type,
  message,
  JSON_EXTRACT_SCALAR(context_json, '$.game_date') as game_date
FROM `nba-props-platform.nba_monitoring.system_errors`
WHERE actionable = TRUE
  AND resolved = FALSE
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY severity DESC, timestamp DESC;

-- Error patterns by time of day
SELECT
  EXTRACT(HOUR FROM timestamp) as hour_of_day,
  component,
  COUNT(*) as error_count,
  COUNT(DISTINCT error_type) as unique_error_types
FROM `nba-props-platform.nba_monitoring.system_errors`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY hour_of_day, component
ORDER BY hour_of_day, error_count DESC;
```

---

## Implementation Plan

### Phase 1: Foundation (This Week - 3 hours)

#### 1.1 Create Error Infrastructure ✅

```bash
# 1. Create BigQuery table
bq mk --table \
  nba-props-platform:nba_monitoring.system_errors \
  schemas/bigquery/nba_monitoring/system_errors.json

# 2. Enable Cloud Error Reporting
gcloud services enable clouderrorreporting.googleapis.com

# 3. Create error dashboard (Cloud Monitoring)
# (Manual - use UI to create dashboard with queries above)
```

#### 1.2 Deploy Shared Error Logger

```bash
# 1. Add to shared utilities
cp shared/utils/error_logger.py <already created above>

# 2. Install in all Cloud Functions
# Add to requirements.txt:
# google-cloud-error-reporting==1.*
```

#### 1.3 Integrate into Existing Code

**Example: Box Score Scraper**

```python
# BEFORE
try:
    result = scrape_box_scores(game_date)
except Exception as e:
    logger.error(f"Scraper failed: {e}")
    raise

# AFTER
from shared.utils.error_logger import log_scraper_error

try:
    result = scrape_box_scores(game_date)
except Exception as e:
    error_id = log_scraper_error(
        scraper_name='bdl_box_scores',
        error=e,
        game_date=game_date,
        scheduled_games=scheduled_count,
        scraped_games=scraped_count
    )
    logger.error(f"Scraper failed with error_id: {error_id}")
    raise
```

### Phase 2: Rollout (Next Week - 4 hours)

**Priority Order**:
1. ✅ Scrapers (highest error rate)
2. ✅ Phase 4 processors (critical for predictions)
3. ✅ Grading functions
4. ✅ Cloud Functions
5. ✅ Orchestration

### Phase 3: Intelligence (Next 2 Weeks - 6 hours)

1. **Error Dashboards** (Cloud Monitoring)
   - Top errors by component
   - Error rate trends
   - Actionable error queue
   - Error resolution tracking

2. **Automated Error Analysis** (Daily Report)
   - Top 10 errors
   - New error types
   - Recurring errors
   - Resolution recommendations

3. **Predictive Alerting**
   - Alert on error rate spikes
   - Alert on new error types
   - Alert on recurring patterns

---

## Success Metrics

### Before vs After

| Metric | Before | Target | Measurement |
|--------|--------|--------|-------------|
| **Error Visibility** | 20% | 95% | % errors centrally logged |
| **MTTD (Mean Time to Detect)** | Hours | <5 min | Avg time error → alert |
| **Error Resolution Time** | Days | <2 hours | Avg time detect → fix |
| **Proactive Detection** | 0% | 30% | % errors caught before impact |
| **Error Grouping** | Manual | Automatic | Using error_type + category |

---

## Related Documents

- [SYSTEMIC-ANALYSIS-AND-ROBUSTNESS-PLAN.md](../08-projects/current/week-0-deployment/SYSTEMIC-ANALYSIS-AND-ROBUSTNESS-PLAN.md)
- [DEPLOYMENT-CHECKLIST.md](./DEPLOYMENT-CHECKLIST.md)

---

**Status**: 📋 Ready for Implementation
**Next Step**: Create BigQuery table and deploy shared logger

