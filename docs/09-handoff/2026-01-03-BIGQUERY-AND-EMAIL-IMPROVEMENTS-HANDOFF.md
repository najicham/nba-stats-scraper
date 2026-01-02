# Handoff: BigQuery Serialization Fix & Email Alert Improvements
**Date**: January 3, 2026
**Status**: 🔄 Investigation Complete - Implementation Needed
**Priority**: HIGH (BigQuery), MEDIUM (Email headings)

---

## Quick Context

You're inheriting two related tasks:

1. **BigQuery Serialization Errors** (HIGH PRIORITY) - Multiple processors failing with concurrent update errors
2. **Email Alert Heading Improvements** (MEDIUM PRIORITY) - Better categorization of alert types

---

## Task 1: Fix BigQuery Serialization Errors 🚨

### The Problem

**14 serialization errors in 7 days**, escalating from 3/day → 8/day:

```
🚨 Critical Error Alert
Processor: Basketball Reference Roster Processor

Error: 400 Could not serialize access to table
nba-props-platform:nba_raw.br_rosters_current
due to concurrent update
```

### Root Cause (Already Identified)

**Multiple Cloud Run instances executing concurrent MERGE/UPDATE on same BigQuery partition + ZERO retry logic = Data gaps**

**Affected**:
- `nba_raw.br_rosters_current` (12 errors) - UPDATE queries
- `nba_raw.odds_api_game_lines` (2 errors) - MERGE queries

**Service**: `nba-phase2-raw-processors`
- Max instances: 10
- Concurrency: 20
- **Potential parallel operations**: 200

### What's Been Done ✅

✅ **Complete investigation** with 3 specialized agents:
- Agent aab89c9: Processor write patterns analyzed
- Agent a59199a: Error frequency and scaling correlation
- Agent adf6967: BigQuery schema analysis

✅ **Documentation created**:
- `/docs/08-projects/current/pipeline-reliability-improvements/2026-01-03-BIGQUERY-SERIALIZATION-INVESTIGATION.md`
- Full root cause analysis
- 5 solution options with effort/impact ratings
- 3-phase implementation plan

✅ **Solutions designed** (not yet implemented):
- Option 1: Add retry logic ⭐⭐⭐⭐⭐ (90% fix, 3 hours)
- Option 2: Reduce concurrency ⭐⭐⭐⭐ (75% fix, 5 minutes)
- Option 3: Distributed locking ⭐⭐⭐⭐⭐ (100% fix, 1-2 days)
- Option 4: Queue-based processing ⭐⭐⭐ (100% fix, 3-5 days)
- Option 5: INSERT-only redesign ⭐⭐⭐⭐ (Best practice, 1-2 weeks)

### What You Need to Do 🎯

#### Phase 1: Immediate Fix (Recommended) ✅

**Combine Options 1 + 2** for quick 90% error reduction

**Tasks**:
1. **Add retry logic** to processors (2-3 hours):
   ```python
   # File: shared/utils/bigquery_retry.py (CREATE NEW)
   from google.api_core import retry
   from google.api_core.exceptions import BadRequest

   def is_serialization_error(exc):
       return (
           isinstance(exc, BadRequest) and
           "Could not serialize access" in str(exc)
       )

   SERIALIZATION_RETRY = retry.Retry(
       predicate=is_serialization_error,
       initial=1.0,      # 1 second
       maximum=32.0,     # 32 seconds max
       multiplier=2.0,   # Exponential backoff
       deadline=120.0    # 2 minute timeout
   )
   ```

2. **Apply retry to processors**:
   - `data_processors/raw/basketball_ref/br_roster_processor.py:346`
     ```python
     # BEFORE
     query_job = self.bq_client.query(query)
     query_job.result(timeout=60)

     # AFTER
     from shared.utils.bigquery_retry import SERIALIZATION_RETRY

     query_job = self.bq_client.query(query)

     @SERIALIZATION_RETRY
     def execute_with_retry():
         return query_job.result(timeout=60)

     execute_with_retry()
     ```

   - `data_processors/raw/oddsapi/odds_game_lines_processor.py:606`
     ```python
     # Same pattern - wrap the MERGE execution
     ```

3. **Reduce Cloud Run concurrency** (5 minutes):
   ```bash
   gcloud run services update nba-phase2-raw-processors \
     --region=us-west2 \
     --max-instances=5 \    # Down from 10
     --concurrency=10        # Down from 20
   ```

4. **Deploy and monitor**:
   - Deploy to production
   - Monitor for 24 hours
   - Check error logs:
     ```bash
     gcloud logging read 'textPayload=~"Could not serialize"' \
       --limit=50 --freshness=24h
     ```

**Expected Result**: 90% reduction in serialization errors (2/day → <0.2/day)

**Effort**: 3-4 hours total
**Risk**: LOW

---

#### Phase 2: Robust Solution (Optional) ⭐

**Implement distributed locking** for 100% error elimination

See full implementation details in investigation document.

**Effort**: 1-2 days
**Risk**: MEDIUM

---

### Files to Modify

**New File**:
- `shared/utils/bigquery_retry.py` - Retry decorator

**Modify** (add retry logic):
- `data_processors/raw/basketball_ref/br_roster_processor.py` (line 346)
- `data_processors/raw/oddsapi/odds_game_lines_processor.py` (line 606)

**Infrastructure**:
- Cloud Run service: `nba-phase2-raw-processors` (reduce concurrency)

---

### Verification Steps

After deploying Phase 1:

1. **Check error rate**:
   ```bash
   # Should see <1 error per day
   gcloud logging read 'textPayload=~"Could not serialize"' \
     --limit=100 --freshness=7d --format=json | \
     jq -r '.[] | .timestamp' | cut -d'T' -f1 | uniq -c
   ```

2. **Verify retry behavior**:
   ```bash
   # Look for retry attempts in logs
   gcloud logging read 'textPayload=~"Retrying\|retry attempt"' \
     --limit=50 --freshness=24h
   ```

3. **Check data completeness**:
   ```sql
   -- Verify no missing roster data
   SELECT
     season_year, team_abbrev,
     MAX(last_scraped_date) as last_update,
     DATE_DIFF(CURRENT_DATE(), MAX(last_scraped_date), DAY) as days_stale
   FROM `nba_raw.br_rosters_current`
   GROUP BY season_year, team_abbrev
   HAVING days_stale > 2
   ORDER BY days_stale DESC
   ```

---

## Task 2: Improve Email Alert Headings 📧

### The Problem

**All errors currently use same heading**: "🚨 Critical Error Alert"

**User feedback**: Can't distinguish between:
- System failures (truly critical, service down)
- Data quality issues (missing data, needs investigation)
- Validation warnings (informational, non-critical)

### Current Email Alert Types

Based on codebase audit:

**Files with email alerting**:
- `shared/utils/email_alerting.py` - SendGrid implementation
- `shared/utils/email_alerting_ses.py` - AWS SES implementation
- `shared/utils/smart_alerting.py` - Smart deduplication
- `shared/utils/processor_alerting.py` - Processor-specific alerts
- `shared/alerts/alert_manager.py` - Central alert manager

**Current Alert Types** (all use "🚨 Critical Error Alert"):

1. **Processor Failures**:
   ```html
   <h2 style="color: #d32f2f;">🚨 Critical Error Alert</h2>
   <p><strong>Processor:</strong> Basketball Reference Roster</p>
   <p><strong>Error:</strong> Could not serialize access...</p>
   ```
   **Location**: `email_alerting.py:159`, `email_alerting_ses.py:156`

2. **Zero Rows Saved** (Data Quality):
   ```
   🚨 Critical Error Alert
   Processor: OddsApiPropsProcessor
   Error: ⚠️ Zero Rows Saved: Expected 33 rows but saved 0
   ```
   **Should be**: Data quality issue, not critical system error

3. **Unresolved Players**:
   ```html
   <h2 style="color: #ff9800;">⚠️ High Unresolved Player Count</h2>
   ```
   **Location**: `email_alerting.py:215` ✅ Already has appropriate heading!

4. **Performance Alerts**:
   ```html
   <h2 style="color: #ff9800;">⚠️ Processing Performance Alert</h2>
   ```
   **Location**: `email_alerting.py:274` ✅ Already has appropriate heading!

5. **Daily Summaries**:
   ```html
   <h2 style="color: #4caf50;">📊 Daily Registry Summary</h2>
   ```
   **Location**: `email_alerting.py:327` ✅ Already has appropriate heading!

### What You Need to Do 🎯

#### Step 1: Audit All Alert Types

**Task**: Review all email alert call sites and categorize them

**Approach**:
```bash
# Find all places that send processor error emails
grep -rn "send_processor_error\|send_alert\|send_error" \
  /home/naji/code/nba-stats-scraper --include="*.py" -A 5 -B 5
```

**Create categorization**:
- 🚨 **Critical Error** - Service failures, crashes, can't continue
- ❌ **Processing Error** - Failed to process data, will retry
- ⚠️ **Data Quality Issue** - Data missing/incomplete, needs investigation
- ℹ️ **Validation Warning** - Data anomaly, informational only
- 📊 **Summary/Report** - Daily summaries, reports

#### Step 2: Design New Alert Headings

**Proposed Structure**:

```python
ALERT_TYPES = {
    'system_failure': {
        'emoji': '🚨',
        'heading': 'Critical System Error',
        'color': '#d32f2f',  # Red
        'description': 'Service down, immediate action required'
    },
    'processing_error': {
        'emoji': '❌',
        'heading': 'Processing Error',
        'color': '#f44336',  # Dark red
        'description': 'Failed to process data, will auto-retry'
    },
    'data_gap': {
        'emoji': '⚠️',
        'heading': 'Data Gap Detected',
        'color': '#ff9800',  # Orange
        'description': 'Expected data missing, investigation needed'
    },
    'zero_rows': {
        'emoji': '📉',
        'heading': 'Zero Rows Saved',
        'color': '#ff9800',  # Orange
        'description': 'Processor ran but saved no data'
    },
    'validation_warning': {
        'emoji': 'ℹ️',
        'heading': 'Data Validation Notice',
        'color': '#2196f3',  # Blue
        'description': 'Data anomaly detected, review recommended'
    },
    'performance': {
        'emoji': '⏱️',
        'heading': 'Performance Alert',
        'color': '#ff9800',  # Orange
        'description': 'Processing slower than expected'
    },
    'summary': {
        'emoji': '📊',
        'heading': 'Daily Summary Report',
        'color': '#4caf50',  # Green
        'description': 'Scheduled summary/report'
    }
}
```

#### Step 3: Update Alert Functions

**Main files to update**:

1. **`shared/utils/email_alerting.py`** (line 159):
   ```python
   # BEFORE
   <h2 style="color: #d32f2f;">🚨 Critical Error Alert</h2>

   # AFTER
   def get_alert_heading(error_type):
       alert_config = ALERT_TYPES.get(error_type, ALERT_TYPES['system_failure'])
       return f"""<h2 style="color: {alert_config['color']};">
           {alert_config['emoji']} {alert_config['heading']}
       </h2>"""

   # Usage
   <h2>{{get_alert_heading(alert_type)}}</h2>
   ```

2. **`shared/utils/email_alerting_ses.py`** (line 156):
   - Same update as above

3. **`shared/utils/smart_alerting.py`** (line 108):
   - Add alert type detection logic
   - Route to appropriate heading

4. **Add alert type detection**:
   ```python
   def detect_alert_type(error_msg: str, error_data: dict) -> str:
       """Detect appropriate alert type from error message."""

       # Zero rows saved
       if "Zero Rows Saved" in error_msg or "saved 0" in error_msg:
           return 'zero_rows'

       # Serialization conflicts (transient)
       if "Could not serialize" in error_msg:
           return 'processing_error'

       # Service crashes
       if "crashed" in error_msg.lower() or "terminated" in error_msg.lower():
           return 'system_failure'

       # Data validation
       if "validation" in error_msg.lower() or "unexpected" in error_msg.lower():
           return 'validation_warning'

       # Default to processing error
       return 'processing_error'
   ```

#### Step 4: Test Changes

**Test email rendering**:
```python
# Create test script: test_email_alerts.py
from shared.utils.email_alerting_ses import EmailAlerterSES

alerter = EmailAlerterSES()

# Test each alert type
test_cases = [
    {
        'type': 'system_failure',
        'processor': 'Test Processor',
        'error': 'Service crashed and could not restart'
    },
    {
        'type': 'zero_rows',
        'processor': 'OddsApiPropsProcessor',
        'error': '⚠️ Zero Rows Saved: Expected 33 rows but saved 0'
    },
    # ... etc
]

for test in test_cases:
    alerter.send_processor_error(
        processor=test['processor'],
        error_msg=test['error'],
        alert_type=test['type']  # NEW parameter
    )
```

**Expected Output**:
- System failures: 🚨 Red, urgent tone
- Zero rows: 📉 Orange, investigation needed
- Validation: ℹ️ Blue, informational

---

### Files to Modify (Email Headings)

**Update**:
- `shared/utils/email_alerting.py` (line 159, add alert type detection)
- `shared/utils/email_alerting_ses.py` (line 156, add alert type detection)
- `shared/utils/smart_alerting.py` (line 108, add routing)
- `shared/utils/processor_alerting.py` (update _build_email_body)

**Create New**:
- `shared/utils/alert_types.py` - Central alert type definitions
- `test_email_alerts.py` - Test different alert types

---

### Verification Steps (Email)

1. **Send test emails** for each alert type
2. **Verify headings** match expected emoji/color/text
3. **Check email filtering** rules still work
4. **Validate Slack integration** (if applicable)

---

## Priority Guidance

**If you only have time for one task**:
→ Do **Task 1 (BigQuery)** first - It's causing active data gaps

**If you have 4+ hours**:
→ Do **Task 1 Phase 1** (3 hours) + **Task 2 Step 1-2** (1 hour audit + design)

**If you have a full day**:
→ Do **Task 1 Phase 1** + **Task 2 complete implementation**

---

## Success Criteria

### BigQuery Fix
- ✅ Serialization errors reduced from 8/day → <1/day
- ✅ Retry logic working (visible in logs)
- ✅ No new data gaps in br_rosters_current
- ✅ No new data gaps in odds_api_game_lines

### Email Headings
- ✅ At least 4 distinct alert heading types implemented
- ✅ Zero rows errors use 📉 instead of 🚨
- ✅ System failures clearly marked with 🚨
- ✅ Validation warnings use ℹ️
- ✅ Test emails sent and verified

---

## Reference Documentation

### BigQuery Investigation
- **Full investigation**: `/docs/08-projects/current/pipeline-reliability-improvements/2026-01-03-BIGQUERY-SERIALIZATION-INVESTIGATION.md`
- **Agent reports**: Check investigation document for agent IDs
- **Service config**: `nba-phase2-raw-processors` Cloud Run service

### Email Alerting
- **Current code**: `shared/utils/email_alerting*.py`
- **Alert manager**: `shared/alerts/alert_manager.py`
- **Processor alerting**: `shared/utils/processor_alerting.py`

### Related Issues
- **Prediction coordinator**: Already fixed (separate issue)
- **Health check script**: `/bin/monitoring/check_morning_run.sh`

---

## Quick Commands

**Check BigQuery errors**:
```bash
gcloud logging read 'textPayload=~"Could not serialize"' \
  --limit=50 --freshness=7d
```

**Find email alert call sites**:
```bash
grep -rn "send_processor_error\|Critical Error Alert" \
  /home/naji/code/nba-stats-scraper/shared --include="*.py"
```

**Test Cloud Run config**:
```bash
gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 --format="value(spec.template.spec.containerConcurrency)"
```

**Deploy changes**:
```bash
# After code changes
gcloud run services update nba-phase2-raw-processors \
  --region=us-west2 \
  --source=.
```

---

## Questions to Consider

1. **BigQuery**: Should we implement Phase 2 (distributed locking) immediately, or wait to see if Phase 1 is sufficient?

2. **Email**: Should we preserve backward compatibility with old alert format, or do a hard cutover?

3. **Testing**: Should we test in staging first, or deploy directly to production with careful monitoring?

4. **Monitoring**: Should we add metrics for retry attempts and alert type distribution?

---

## Notes from Previous Session

- Prediction coordinator is **production-ready** (separate service, already fixed)
- 7 AM automatic run scheduled for tomorrow - monitor with health check script
- All prediction coordinator fixes documented in separate handoff
- This BigQuery issue is **separate** from prediction coordinator
- Email heading improvement is **user feedback**, not critical

---

**Created**: 2026-01-03 ~01:00 UTC
**Created by**: Claude Sonnet 4.5
**Status**: Ready for next session

**Next session**: Implement BigQuery retry logic (Phase 1), then audit email alert types.

Good luck! Both tasks are well-scoped and achievable. 🚀
