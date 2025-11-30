# Email Alerting Integration Plan

This document details how each email type will be integrated into the NBA pipeline system.

---

## 1. ✅ Pipeline Health Summary

**Trigger:** Daily at 6 AM Pacific Time
**Method:** `send_pipeline_health_summary()`

### Implementation

Create a Cloud Function triggered by Cloud Scheduler that:
1. Queries `processor_run_history` for yesterday's runs
2. Aggregates status by phase
3. Calculates total duration
4. Checks for gaps
5. Sends health summary email

### Files to Create/Modify

```
monitoring/
  health_summary/
    main.py              # Cloud Function entry point
    requirements.txt     # Dependencies
```

### Cloud Scheduler Setup

```bash
gcloud scheduler jobs create http pipeline-health-summary \
  --schedule="0 6 * * *" \
  --time-zone="America/Los_Angeles" \
  --uri="https://REGION-PROJECT.cloudfunctions.net/pipeline-health-summary" \
  --http-method=POST
```

### Sample Query

```sql
SELECT
  CASE
    WHEN processor_name LIKE '%Scraper%' THEN 'Phase 1 (Scrapers)'
    WHEN phase = 'raw' THEN 'Phase 2 (Raw)'
    WHEN phase = 'analytics' THEN 'Phase 3 (Analytics)'
    WHEN phase = 'precompute' THEN 'Phase 4 (Precompute)'
    WHEN phase = 'predictions' THEN 'Phase 5 (Predictions)'
  END as phase_name,
  COUNT(CASE WHEN status = 'success' THEN 1 END) as success_count,
  COUNT(*) as total_count
FROM `nba-props-platform.nba_reference.processor_run_history`
WHERE data_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
GROUP BY phase_name
```

### Data Structure

```python
health_data = {
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
}
```

---

## 2. 🏀 Prediction Completion Summary

**Trigger:** Phase 5 coordinator completion
**Method:** `send_prediction_completion_summary()`

### Implementation

Modify `predictions/coordinator/coordinator.py` to:
1. Track prediction results as workers complete
2. Calculate confidence distribution
3. Identify top recommendations
4. Send summary email when all workers done

### Files to Modify

```
predictions/coordinator/coordinator.py   # Add email trigger on completion
```

### Integration Point

```python
# In coordinator.py, after all predictions complete:

def _send_completion_email(self):
    """Send prediction completion summary email."""
    from shared.utils.email_alerting_ses import EmailAlerterSES

    alerter = EmailAlerterSES()
    alerter.send_prediction_completion_summary({
        'date': self.game_date,
        'games_count': len(self.games),
        'players_predicted': self.successful_predictions,
        'players_total': self.total_players,
        'failed_players': self.failed_players,
        'confidence_distribution': self._calculate_confidence_distribution(),
        'top_recommendations': self._get_top_recommendations(5),
        'duration_minutes': self._get_duration_minutes()
    })
```

### Data Sources

- `nba_predictions.player_prop_predictions` - Prediction results
- Coordinator in-memory tracking during run

---

## 3. ⏳ Dependency Stall Alert

**Trigger:** Orchestrator waiting > 30 minutes for upstream phase
**Method:** `send_dependency_stall_alert()`

### Implementation

Modify orchestrators to track wait time and send alert:
1. Record first message timestamp in Firestore
2. On each subsequent message, check elapsed time
3. If > 30 minutes and not all processors complete, send stall alert
4. Only send once per stall (track in Firestore)

### Files to Modify

```
orchestration/cloud_functions/phase2_to_phase3/main.py   # Add stall detection
orchestration/cloud_functions/phase3_to_phase4/main.py   # Add stall detection
```

### Integration Point

```python
# In orchestrator, after checking completion status:

def _check_for_stall(self, doc_data: dict, data_date: str):
    """Check if phase is stalled and send alert."""
    first_completion_time = doc_data.get('first_completion_at')
    if not first_completion_time:
        return

    elapsed_minutes = (datetime.now() - first_completion_time).total_seconds() / 60

    if elapsed_minutes > 30 and not doc_data.get('stall_alert_sent'):
        # Get missing processors
        completed = set(doc_data.get('completed_processors', []))
        all_processors = set(EXPECTED_PROCESSORS)
        missing = list(all_processors - completed)

        from shared.utils.email_alerting_ses import EmailAlerterSES
        alerter = EmailAlerterSES()
        alerter.send_dependency_stall_alert({
            'waiting_phase': 'Phase 3',
            'blocked_by_phase': 'Phase 2',
            'wait_minutes': int(elapsed_minutes),
            'missing_processors': missing,
            'completed_count': len(completed),
            'total_count': len(all_processors)
        })

        # Mark alert sent
        self._update_firestore(data_date, {'stall_alert_sent': True})
```

### Firestore Document Updates

Add fields:
- `first_completion_at`: Timestamp of first processor completion
- `stall_alert_sent`: Boolean to prevent duplicate alerts

---

## 4. 📦 Backfill Progress Report

**Trigger:** Every 25% progress during backfill
**Method:** `send_backfill_progress_report()`

### Implementation

Modify backfill job runner to:
1. Track progress as dates complete
2. At 25%, 50%, 75%, 100% milestones, send progress email
3. Aggregate success/failure counts
4. Track suppressed alerts

### Files to Create/Modify

```
scripts/backfill/backfill_runner.py      # Add progress tracking
shared/alerts/alert_manager.py           # Add suppression counter
```

### Integration Point

```python
# In backfill runner:

class BackfillRunner:
    def __init__(self, season: str, phase: str, dates: list):
        self.season = season
        self.phase = phase
        self.total_dates = len(dates)
        self.completed = 0
        self.successful = 0
        self.partial = 0
        self.failed = 0
        self.failed_dates = []
        self.last_milestone = 0
        self.alerts_suppressed = 0

    def _check_milestone(self):
        """Send progress report at milestones."""
        progress_pct = (self.completed / self.total_dates) * 100
        milestone = int(progress_pct // 25) * 25

        if milestone > self.last_milestone and milestone > 0:
            self.last_milestone = milestone
            self._send_progress_email()

    def _send_progress_email(self):
        from shared.utils.email_alerting_ses import EmailAlerterSES
        alerter = EmailAlerterSES()
        alerter.send_backfill_progress_report({
            'season': self.season,
            'phase': self.phase,
            'completed_dates': self.completed,
            'total_dates': self.total_dates,
            'successful': self.successful,
            'partial': self.partial,
            'failed': self.failed,
            'failed_dates': self.failed_dates[-10:],
            'estimated_remaining_minutes': self._estimate_remaining(),
            'alerts_suppressed': self.alerts_suppressed
        })
```

---

## 5. 📉 Data Quality Alert

**Trigger:** Quality score drops from previous level
**Method:** `send_data_quality_alert()`

### Implementation

Modify quality mixin to:
1. Track previous quality level (from BigQuery or cache)
2. Compare current quality after calculation
3. If degraded, send alert with reason

### Files to Modify

```
shared/processors/patterns/quality_mixin.py   # Add quality change detection
```

### Integration Point

```python
# In quality_mixin.py:

def _check_quality_change(self, current_quality: str, previous_quality: str):
    """Check if quality degraded and send alert."""
    quality_order = ['UNUSABLE', 'BRONZE', 'SILVER', 'GOLD']

    curr_idx = quality_order.index(current_quality)
    prev_idx = quality_order.index(previous_quality)

    if curr_idx < prev_idx:  # Quality decreased
        from shared.utils.email_alerting_ses import EmailAlerterSES
        alerter = EmailAlerterSES()
        alerter.send_data_quality_alert({
            'processor_name': self.processor_name,
            'date': self.data_date,
            'previous_quality': previous_quality,
            'current_quality': current_quality,
            'reason': self._get_degradation_reason(),
            'fallback_sources': self._get_fallback_sources_used(),
            'impact': self._get_impact_description()
        })
```

### Quality Tracking

Query previous quality from `processor_run_history`:
```sql
SELECT data_quality
FROM processor_run_history
WHERE processor_name = @processor
  AND data_date = DATE_SUB(@date, INTERVAL 1 DAY)
ORDER BY created_at DESC
LIMIT 1
```

---

## 6. 🕐 Stale Data Warning

**Trigger:** Upstream data older than expected freshness
**Method:** `send_stale_data_warning()`

### Implementation

Modify dependency checker to:
1. Query upstream table metadata for last update time
2. Compare against expected freshness threshold
3. If stale, send warning before proceeding

### Files to Modify

```
shared/processors/mixins/dependency_checker_mixin.py   # Add staleness check
```

### Integration Point

```python
# In dependency_checker_mixin.py:

def _check_data_freshness(self, upstream_table: str, expected_hours: int = 6):
    """Check if upstream data is fresh enough."""
    query = f"""
    SELECT TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(created_at), HOUR) as hours_old
    FROM `{upstream_table}`
    """
    result = self.bq_client.query(query).result()
    hours_old = list(result)[0].hours_old

    if hours_old > expected_hours:
        from shared.utils.email_alerting_ses import EmailAlerterSES
        alerter = EmailAlerterSES()
        alerter.send_stale_data_warning({
            'processor_name': self.processor_name,
            'upstream_table': upstream_table,
            'last_updated': f'{hours_old} hours ago',
            'expected_freshness_hours': expected_hours,
            'actual_age_hours': hours_old
        })
        return False  # Data is stale
    return True  # Data is fresh
```

---

## Implementation Status

| Priority | Email Type | Status | Implementation |
|----------|------------|--------|----------------|
| 1 | ✅ Pipeline Health | DONE | `monitoring/health_summary/main.py` |
| 2 | 🏀 Prediction Completion | DONE | `predictions/coordinator/coordinator.py` |
| 3 | ⏳ Dependency Stall | DONE | `monitoring/stall_detection/main.py` |
| 4 | 📦 Backfill Progress | DONE | `shared/alerts/backfill_progress_tracker.py` |
| 5 | 📉 Data Quality | DONE | `shared/processors/patterns/quality_mixin.py` |
| 6 | 🕐 Stale Data | DONE | `shared/utils/data_freshness_checker.py` |

---

## Testing Plan

### Unit Tests
- [ ] Test each email method with mock data
- [ ] Verify HTML escaping works correctly
- [ ] Test edge cases (empty lists, zero values)

### Integration Tests
- [ ] Trigger each email from actual pipeline component
- [ ] Verify correct data flows through
- [ ] Test rate limiting during backfill

### End-to-End Tests
- [ ] Run full pipeline and verify health summary sent
- [ ] Run predictions and verify completion email sent
- [ ] Simulate stall and verify alert sent

---

## Rollout Plan

### Week 1: Core Alerts
1. Deploy Pipeline Health Summary Cloud Function
2. Set up Cloud Scheduler trigger
3. Integrate Prediction Completion into coordinator
4. Test both in production

### Week 2: Warning Alerts
1. Add Dependency Stall detection to orchestrators
2. Add Stale Data check to dependency checker
3. Test with synthetic delays

### Week 3: Quality & Backfill
1. Integrate Data Quality alert into quality mixin
2. Add Backfill Progress to backfill runner
3. Run test backfill to verify

### Week 4: Monitoring & Tuning
1. Monitor email volume
2. Adjust thresholds if needed
3. Document operational procedures
