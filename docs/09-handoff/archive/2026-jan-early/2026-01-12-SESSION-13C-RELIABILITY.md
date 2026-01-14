# Session 13C: Reliability Improvements

**Date:** January 12, 2026
**Focus:** Pipeline retry mechanisms and monitoring alerts
**Priority:** P1-P2

---

## Tasks

### 1. P1-2: PlayerGameSummaryProcessor Retry Mechanism

**Context:** From Session 10/11 - PlayerGameSummaryProcessor failed for Jan 10 with no automatic retry. Had to manually trigger.

**Goal:** Add automatic retry/self-healing for Phase 3 processor failures

**Files to investigate:**
```
data_processors/analytics/player_game_summary/player_game_summary_processor.py
orchestration/cloud_functions/self_heal/main.py  # Reference for retry patterns
orchestration/cloud_functions/  # Look for existing retry patterns
```

**Approach options:**
1. Add retry logic within the processor itself
2. Create a self-heal function that detects Phase 3 failures
3. Add Cloud Scheduler job that checks and retriggers

---

### 2. P2-2: Grading Delay Alert

**Goal:** Alert if no grading records for yesterday by 10 AM ET

**Implementation:**
```python
# Cloud Function triggered at 10 AM ET
# Checks prediction_accuracy for yesterday
# Sends alert if count = 0
```

**Files to reference:**
```
orchestration/cloud_functions/grading/main.py  # Grading logic
orchestration/cloud_functions/self_heal/main.py  # Alert patterns
```

**Suggested location:** `orchestration/cloud_functions/grading_alert/`

---

### 3. P2-3: Live Export Staleness Alert

**Goal:** Alert if `today.json` is more than 4 hours old during game hours (4 PM - 2 AM ET)

**Files:**
```
data_processors/publishing/live_grading_exporter.py
orchestration/cloud_functions/live_export/  # If exists
```

**Implementation considerations:**
- Check GCS bucket for file modification time
- Only alert during game hours (4 PM - 2 AM ET)
- Consider using Cloud Monitoring instead of custom function

---

## Key Docs to Read

```bash
# Pipeline reliability improvements master plan
cat docs/08-projects/current/pipeline-reliability-improvements/MASTER-TODO.md

# Existing self-heal patterns
cat orchestration/cloud_functions/self_heal/main.py

# Health check script (reference for what to monitor)
cat tools/monitoring/check_pipeline_health.py
```

---

## Existing Infrastructure

### Current Schedulers
```bash
# List all schedulers
gcloud scheduler jobs list --location=us-west2

# Key ones:
# - grading-daily (11:00 UTC / 6 AM ET)
# - same-day-predictions
# - phase4-daily
```

### Current Cloud Functions
```bash
gcloud functions list
```

### Alert Patterns Used
- Email via SendGrid (`shared/notifications/email_sender.py`)
- Slack webhooks
- Cloud Monitoring (if configured)

---

## DO NOT WORK ON

These are handled by other sessions:
- **Session 13A:** Pipeline recovery (Phase 4, predictions, grading backfill)
- **Session 13B:** line_value = 20 investigation, prop matching

---

## Success Criteria

1. PlayerGameSummaryProcessor has automatic retry on failure
2. Alert fires if grading is late (by 10 AM ET next day)
3. Alert fires if live export is stale during games

---

## Implementation Priority

1. **Grading delay alert** (easiest, high value)
2. **PlayerGameSummaryProcessor retry** (medium complexity)
3. **Live export staleness alert** (lower priority)
