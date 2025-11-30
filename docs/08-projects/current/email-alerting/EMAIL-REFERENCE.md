# Email Alert Reference Guide

Complete reference for all email types in the NBA Registry System.

---

## Quick Reference

| Emoji | Subject Pattern | Level | Recipients |
|-------|-----------------|-------|------------|
| 🚨 | `[CRITICAL] {processor} - Critical Error` | CRITICAL | `EMAIL_CRITICAL_TO` |
| ⚠️ | `[WARNING] High Unresolved Player Count: {n}` | WARNING | `EMAIL_ALERTS_TO` |
| 📊 | `[INFO] Daily Summary - {date}` | INFO | `EMAIL_ALERTS_TO` |
| 🆕 | `[INFO] New Players Discovered: {n}` | INFO | `EMAIL_ALERTS_TO` |
| ✅ | `[INFO] ✅ Pipeline Health - {date}` | INFO | `EMAIL_ALERTS_TO` |
| 🏀 | `[INFO] 🏀 Predictions Ready - {date} ({n}/{total})` | INFO | `EMAIL_ALERTS_TO` |
| ⏳ | `[WARNING] ⏳ Pipeline Stall - {phase} waiting {n}+ mins` | WARNING | `EMAIL_CRITICAL_TO` |
| 📦 | `[INFO] 📦 Backfill Progress - {season} {phase} ({pct}%)` | INFO | `EMAIL_ALERTS_TO` |
| 📉 | `[WARNING] 📉 Data Quality Degraded - {prev} → {curr}` | WARNING | `EMAIL_ALERTS_TO` |
| 🕐 | `[WARNING] 🕐 Stale Data Warning - {table} ({n}h old)` | WARNING | `EMAIL_ALERTS_TO` |

---

## Detailed Email Specifications

### 1. 🚨 Critical Error Alert

**Method:** `send_error_alert(error_message, error_details, processor_name)`

**Purpose:** Immediate notification of processor failures requiring investigation.

**Parameters:**
```python
error_message: str      # Main error description
error_details: Dict     # Key-value pairs of additional context
processor_name: str     # Name of failing processor (default: "Registry Processor")
```

**Sample Call:**
```python
alerter.send_error_alert(
    error_message="MERGE operation failed: duplicate key violation",
    error_details={
        'table': 'player_game_summary',
        'affected_rows': 45,
        'error_code': 'DUPLICATE_KEY',
        'stack_trace': 'line 234 in merge_data()'
    },
    processor_name="PlayerGameSummaryProcessor"
)
```

**Sample Output:**
```
Subject: [NBA Registry CRITICAL] PlayerGameSummaryProcessor - Critical Error

🚨 Critical Error Alert
Processor: PlayerGameSummaryProcessor
Time: 2025-11-30 09:45:23 UTC
Error: MERGE operation failed: duplicate key violation

Error Details:
• table: player_game_summary
• affected_rows: 45
• error_code: DUPLICATE_KEY
• stack_trace: line 234 in merge_data()
```

---

### 2. ⚠️ Unresolved Players Alert

**Method:** `send_unresolved_players_alert(unresolved_count, threshold)`

**Purpose:** Alert when player name resolution issues exceed threshold.

**Parameters:**
```python
unresolved_count: int   # Current count of unresolved players
threshold: int          # Threshold that was exceeded (default: 50)
```

**Sample Call:**
```python
alerter.send_unresolved_players_alert(
    unresolved_count=127,
    threshold=50
)
```

**Sample Output:**
```
Subject: [NBA Registry WARNING] High Unresolved Player Count: 127

⚠️ Unresolved Players Alert
Time: 2025-11-30 09:45:23 UTC
Unresolved Count: 127
Threshold: 50

The number of unresolved players has exceeded the threshold.
Manual review may be required.
```

---

### 3. 📊 Daily Summary

**Method:** `send_daily_summary(summary_data)`

**Purpose:** Daily operational metrics summary.

**Parameters:**
```python
summary_data: Dict      # Key-value pairs of metrics
```

**Sample Call:**
```python
alerter.send_daily_summary({
    'total_games_processed': 12,
    'total_players': 450,
    'records_inserted': 5400,
    'processing_time_minutes': 47,
    'errors_encountered': 0
})
```

---

### 4. 🆕 New Players Discovery Alert

**Method:** `send_new_players_discovery_alert(players, processing_run_id)`

**Purpose:** Notification when new players are added to the registry.

**Parameters:**
```python
players: List[Dict]     # List of {'name': str, 'player_id': str}
processing_run_id: str  # ID of the processing run
```

**Sample Call:**
```python
alerter.send_new_players_discovery_alert(
    players=[
        {'name': 'Victor Wembanyama', 'player_id': 'wembavi01'},
        {'name': 'Chet Holmgren', 'player_id': 'holmgch01'}
    ],
    processing_run_id='run_20251130_094523'
)
```

---

### 5. ✅ Pipeline Health Summary

**Method:** `send_pipeline_health_summary(health_data)`

**Purpose:** Daily confirmation that all pipeline phases completed successfully.

**Parameters:**
```python
health_data: Dict = {
    'date': str,                    # Processing date (YYYY-MM-DD)
    'phases': Dict[str, Dict],      # Phase name → {complete, total, status}
    'total_duration_minutes': int,  # Total pipeline runtime
    'data_quality': str,            # GOLD/SILVER/BRONZE
    'gaps_detected': int,           # Number of data gaps found
    'records_processed': int        # Total records processed
}
```

**Sample Call:**
```python
alerter.send_pipeline_health_summary({
    'date': '2025-11-30',
    'phases': {
        'Phase 1 (Scrapers)': {'complete': 21, 'total': 21, 'status': 'success'},
        'Phase 2 (Raw)': {'complete': 21, 'total': 21, 'status': 'success'},
        'Phase 3 (Analytics)': {'complete': 5, 'total': 5, 'status': 'success'},
        'Phase 4 (Precompute)': {'complete': 5, 'total': 5, 'status': 'success'},
        'Phase 5 (Predictions)': {'complete': 448, 'total': 450, 'status': 'partial'},
    },
    'total_duration_minutes': 47,
    'data_quality': 'GOLD',
    'gaps_detected': 0,
    'records_processed': 52847
})
```

**Sample Output:**
```
Subject: [NBA Registry INFO] ✅ Pipeline Health - 2025-11-30

✅ Daily Pipeline Health Summary
Date: 2025-11-30
Generated: 2025-11-30 06:00:00 UTC

Phase Status
┌─────────────────────────┬────────────┐
│ Phase                   │ Status     │
├─────────────────────────┼────────────┤
│ Phase 1 (Scrapers)      │ ✅ 21/21   │
│ Phase 2 (Raw)           │ ✅ 21/21   │
│ Phase 3 (Analytics)     │ ✅ 5/5     │
│ Phase 4 (Precompute)    │ ✅ 5/5     │
│ Phase 5 (Predictions)   │ ⚠️ 448/450 │
└─────────────────────────┴────────────┘

Summary
• Total Duration: 47 minutes
• Data Quality: GOLD
• Gaps Detected: 0
• Records Processed: 52,847
```

---

### 6. 🏀 Prediction Completion Summary

**Method:** `send_prediction_completion_summary(prediction_data)`

**Purpose:** Notification when daily predictions are ready with top recommendations.

**Parameters:**
```python
prediction_data: Dict = {
    'date': str,                        # Prediction date
    'games_count': int,                 # Games scheduled today
    'players_predicted': int,           # Successfully predicted
    'players_total': int,               # Total attempted
    'failed_players': List[Dict],       # [{name, reason}]
    'confidence_distribution': Dict,    # {high, medium, low}
    'top_recommendations': List[Dict],  # [{player, line, recommendation, confidence}]
    'duration_minutes': int             # Time to complete
}
```

**Sample Call:**
```python
alerter.send_prediction_completion_summary({
    'date': '2025-11-30',
    'games_count': 12,
    'players_predicted': 448,
    'players_total': 450,
    'failed_players': [
        {'name': 'Giannis Antetokounmpo', 'reason': 'Missing feature vector'},
        {'name': 'Kevin Durant', 'reason': 'Model inference timeout'}
    ],
    'confidence_distribution': {'high': 234, 'medium': 189, 'low': 25},
    'top_recommendations': [
        {'player': 'LeBron James', 'line': 26.5, 'recommendation': 'OVER', 'confidence': 87},
        {'player': 'Stephen Curry', 'line': 28.5, 'recommendation': 'UNDER', 'confidence': 82},
    ],
    'duration_minutes': 8
})
```

**Sample Output:**
```
Subject: [NBA Registry INFO] 🏀 Predictions Ready - 2025-11-30 (448/450)

🏀 Prediction Completion Summary
Date: 2025-11-30
Generated: 2025-11-30 05:47:00 UTC

Overview
• Games Today: 12
• Players Predicted: 448/450
• Duration: 8 minutes

Confidence Distribution
• High (>80%): 234 players
• Medium (50-80%): 189 players
• Low (<50%): 25 players

Top Recommendations
• LeBron James: OVER 26.5 pts (87% confidence)
• Stephen Curry: UNDER 28.5 pts (82% confidence)

Failed Predictions
• Giannis Antetokounmpo: Missing feature vector
• Kevin Durant: Model inference timeout
```

---

### 7. ⏳ Dependency Stall Alert

**Method:** `send_dependency_stall_alert(stall_data)`

**Purpose:** Alert when a pipeline phase is stuck waiting for upstream completion.

**Parameters:**
```python
stall_data: Dict = {
    'waiting_phase': str,           # Phase waiting (e.g., "Phase 3")
    'blocked_by_phase': str,        # Phase being waited on
    'wait_minutes': int,            # Minutes waiting so far
    'missing_processors': List[str],# Processors not yet complete
    'completed_count': int,         # Number completed
    'total_count': int              # Total expected
}
```

**Sample Call:**
```python
alerter.send_dependency_stall_alert({
    'waiting_phase': 'Phase 3',
    'blocked_by_phase': 'Phase 2',
    'wait_minutes': 45,
    'missing_processors': [
        'NbacomBoxScoresProcessor',
        'PbpStatsPlayByPlayProcessor'
    ],
    'completed_count': 19,
    'total_count': 21
})
```

---

### 8. 📦 Backfill Progress Report

**Method:** `send_backfill_progress_report(progress_data)`

**Purpose:** Progress updates during long-running backfill operations.

**Parameters:**
```python
progress_data: Dict = {
    'season': str,                      # Season being backfilled
    'phase': str,                       # Current phase
    'completed_dates': int,             # Dates processed
    'total_dates': int,                 # Total dates
    'successful': int,                  # Successful count
    'partial': int,                     # Partial success count
    'failed': int,                      # Failed count
    'failed_dates': List[str],          # List of failed dates
    'estimated_remaining_minutes': int, # ETA
    'alerts_suppressed': int            # Alerts batched/suppressed
}
```

**Sample Call:**
```python
alerter.send_backfill_progress_report({
    'season': '2023-24',
    'phase': 'Phase 3 Analytics',
    'completed_dates': 156,
    'total_dates': 175,
    'successful': 152,
    'partial': 3,
    'failed': 1,
    'failed_dates': ['2024-01-15'],
    'estimated_remaining_minutes': 45,
    'alerts_suppressed': 847
})
```

---

### 9. 📉 Data Quality Alert

**Method:** `send_data_quality_alert(quality_data)`

**Purpose:** Alert when data quality degrades from expected level.

**Parameters:**
```python
quality_data: Dict = {
    'processor_name': str,          # Processor detecting degradation
    'date': str,                    # Processing date
    'previous_quality': str,        # Previous level (GOLD/SILVER/BRONZE)
    'current_quality': str,         # Current level
    'reason': str,                  # Reason for degradation
    'fallback_sources': List[str],  # Backup sources used
    'impact': str                   # Impact description
}
```

**Sample Call:**
```python
alerter.send_data_quality_alert({
    'processor_name': 'PlayerGameSummaryProcessor',
    'date': '2025-11-30',
    'previous_quality': 'GOLD',
    'current_quality': 'BRONZE',
    'reason': 'Primary source (nba.com) unavailable due to API timeout',
    'fallback_sources': ['ESPN', 'Basketball-Reference'],
    'impact': 'Prediction confidence may be reduced for today\'s games.'
})
```

---

### 10. 🕐 Stale Data Warning

**Method:** `send_stale_data_warning(stale_data)`

**Purpose:** Warning when upstream data is older than expected freshness threshold.

**Parameters:**
```python
stale_data: Dict = {
    'processor_name': str,              # Processor detecting stale data
    'upstream_table': str,              # Stale table name
    'last_updated': str,                # When table was last updated
    'expected_freshness_hours': int,    # How fresh data should be
    'actual_age_hours': int,            # How old data actually is
    'possible_causes': List[str]        # Optional: override default causes
}
```

**Sample Call:**
```python
alerter.send_stale_data_warning({
    'processor_name': 'PlayerGameSummaryProcessor',
    'upstream_table': 'nba_raw.nbacom_boxscores',
    'last_updated': '2025-11-28 14:30:00 UTC',
    'expected_freshness_hours': 6,
    'actual_age_hours': 36
})
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_SES_ACCESS_KEY_ID` | Yes | - | AWS access key |
| `AWS_SES_SECRET_ACCESS_KEY` | Yes | - | AWS secret key |
| `AWS_SES_REGION` | No | `us-west-2` | AWS region |
| `AWS_SES_FROM_EMAIL` | Yes | - | Sender email address |
| `AWS_SES_FROM_NAME` | No | `NBA Registry System` | Sender display name |
| `EMAIL_ALERTS_TO` | Yes | - | Comma-separated alert recipients |
| `EMAIL_CRITICAL_TO` | No | Same as ALERTS_TO | Critical alert recipients |

---

## Usage Examples

### Basic Usage
```python
from shared.utils.email_alerting_ses import EmailAlerterSES

alerter = EmailAlerterSES()
alerter.send_error_alert("Something went wrong", {"details": "here"})
```

### With Notification Router (Recommended)
```python
from shared.utils.notification_system import notify_error

notify_error(
    title="Processor Failed",
    message="PlayerGameSummary failed during MERGE",
    details={'error_code': 'MERGE_FAILED'},
    processor_name="PlayerGameSummaryProcessor"
)
```

### In Backfill Mode (Suppresses Non-Critical)
```python
from shared.utils.notification_system import notify_error

notify_error(
    title="Minor Issue",
    message="Some records skipped",
    backfill_mode=True  # Will be batched, not sent immediately
)
```
