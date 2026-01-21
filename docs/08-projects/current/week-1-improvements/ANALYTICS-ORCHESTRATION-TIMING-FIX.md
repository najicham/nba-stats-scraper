# Analytics Processor Orchestration Timing Fix

## Problem Summary

**Issue:** PlayerGameSummaryProcessor receiving "stale data" and "no data" errors

**Error Details:**
```
❌ Processing Failed
Processor: NBA Platform
Error: Analytics Processor No Data Extracted: PlayerGameSummaryProcessor: No data extracted from raw tables
run_id: 87734855, table: player_game_summary, date_range: 2026-01-19

🕐 Stale Data Warning
Error: PlayerGameSummaryProcessor: Some sources are stale:
['nba_raw.bdl_player_boxscores: 8.8h old (warn: 6h)']
run_id: 3e3907c4, date_range: 2026-01-19
```

## Root Cause Analysis

### Timeline of Events (2026-01-20)

1. **02:05 UTC** - Scrapers complete for 2026-01-19 games
   - Data written to `nba_raw.bdl_player_boxscores`
   - Games finished late (West Coast games)

2. **10:47 UTC** - Analytics processor runs (8.8 hours later)
   - Attempts to process 2026-01-19 data
   - Data is 8.8 hours old
   - **Staleness threshold: 6 hours**
   - Result: Fails with "stale data" warning

### Why This Happens

1. **Fixed Schedule Problem**
   - Scrapers run on a schedule (e.g., 2:00 AM UTC)
   - Analytics processors also run on a fixed schedule (e.g., 10:45 AM UTC)
   - No coordination between them

2. **Late Games Issue**
   - West Coast NBA games can finish as late as 1:30 AM UTC
   - Scrapers run shortly after
   - Analytics runs many hours later on fixed schedule

3. **Staleness Check**
   - Analytics processors validate upstream data freshness
   - Default threshold: 6 hours
   - When games finish late + analytics runs on fixed schedule = staleness

## Solution Options

### Option 1: Event-Driven Analytics (Recommended)

**Approach:** Trigger analytics processors automatically when scrapers complete

**Architecture:**
```
Scraper Completion
    ↓
Pub/Sub Message ("scraper_completed")
    ↓
Cloud Function (analytics_orchestrator)
    ↓
Checks if all required scrapers complete
    ↓
Triggers Analytics Processor
```

**Implementation Steps:**

1. **Update Scraper to Publish Completion Event**
   ```python
   # In scraper completion handler
   from google.cloud import pubsub_v1

   publisher = pubsub_v1.PublisherClient()
   topic_path = publisher.topic_path('nba-props-platform', 'scraper-completion')

   message_data = {
       'scraper_name': 'bdl_player_boxscores',
       'game_date': '2026-01-19',
       'status': 'completed',
       'row_count': 281,
       'completion_timestamp': '2026-01-20T02:05:13Z'
   }

   publisher.publish(topic_path, json.dumps(message_data).encode('utf-8'))
   ```

2. **Create Orchestration Cloud Function**
   ```python
   # orchestration/cloud_functions/analytics_trigger/main.py

   from google.cloud import firestore
   from google.cloud import run_v2
   import json
   from datetime import datetime

   db = firestore.Client()
   run_client = run_v2.JobsClient()

   def trigger_analytics(event, context):
       """Triggered when scraper completes."""
       message_data = json.loads(base64.b64decode(event['data']))

       scraper_name = message_data['scraper_name']
       game_date = message_data['game_date']

       # Track scraper completion in Firestore
       doc_ref = db.collection('scraper_status').document(game_date)
       doc_ref.set({
           scraper_name: {
               'status': 'completed',
               'timestamp': message_data['completion_timestamp'],
               'row_count': message_data['row_count']
           }
       }, merge=True)

       # Check if all required scrapers are complete
       required_scrapers = [
           'bdl_player_boxscores',
           'nbacom_player_boxscores',
           'nbacom_team_boxscores'
       ]

       scraper_status = doc_ref.get().to_dict()
       all_complete = all(
           scraper in scraper_status and scraper_status[scraper]['status'] == 'completed'
           for scraper in required_scrapers
       )

       if all_complete:
           # Trigger analytics processor
           print(f"All scrapers complete for {game_date}, triggering analytics")

           # Call Cloud Run Job
           job_name = f"projects/nba-props-platform/locations/us-west2/jobs/nba-phase3-analytics-processors"

           request = run_v2.RunJobRequest(
               name=job_name,
               overrides={
                   'container_overrides': [{
                       'env': [
                           {'name': 'PROCESSOR', 'value': 'player_game_summary'},
                           {'name': 'START_DATE', 'value': game_date},
                           {'name': 'END_DATE', 'value': game_date}
                       ]
                   }]
               }
           )

           operation = run_client.run_job(request=request)
           print(f"Analytics job triggered: {operation.name}")
       else:
           missing = [s for s in required_scrapers if s not in scraper_status]
           print(f"Waiting for scrapers: {missing}")
   ```

3. **Deploy Cloud Function**
   ```bash
   gcloud functions deploy analytics-trigger \
       --runtime python311 \
       --trigger-topic scraper-completion \
       --entry-point trigger_analytics \
       --region us-west2 \
       --memory 256MB \
       --timeout 60s
   ```

**Pros:**
- ✅ Optimal timing - analytics runs as soon as data is ready
- ✅ No stale data issues
- ✅ Scales automatically for any schedule changes
- ✅ Handles late games elegantly

**Cons:**
- ⚠️ Requires new infrastructure (Cloud Function, Firestore)
- ⚠️ More complex orchestration logic
- ⚠️ Need to handle failure retry logic

### Option 2: Adjust Scraper + Analytics Schedules (Quick Fix)

**Approach:** Run analytics processor shortly after scrapers complete

**Implementation:**

1. **Check Current Scraper Schedule**
   ```bash
   # Look at Cloud Scheduler jobs
   gcloud scheduler jobs describe nba-scrapers-daily --location=us-west2
   ```

2. **Schedule Analytics to Run 30 Minutes After Scrapers**
   ```bash
   # If scrapers run at 02:00 UTC, schedule analytics at 02:30 UTC
   gcloud scheduler jobs create http nba-analytics-daily \
       --schedule="30 2 * * *" \
       --time-zone="UTC" \
       --uri="https://nba-phase3-analytics-processors-xxxxx-uw.a.run.app/process-analytics" \
       --http-method=POST \
       --headers="Content-Type=application/json" \
       --message-body='{"processor":"player_game_summary","start_date":"yesterday","end_date":"yesterday"}' \
       --location=us-west2
   ```

3. **Or: Increase Staleness Threshold**
   ```python
   # In analytics_base.py or processor configuration
   STALENESS_WARNING_HOURS = 12  # Increased from 6
   ```

**Pros:**
- ✅ Simple to implement
- ✅ No new infrastructure needed
- ✅ Can be done immediately

**Cons:**
- ⚠️ Still has timing dependency
- ⚠️ Breaks if scraper schedule changes
- ⚠️ Late games still might cause issues
- ⚠️ Wastes resources running at fixed time even when no games

### Option 3: Smart Scheduling with Retry Logic (Hybrid)

**Approach:** Schedule analytics at expected time, but add retry logic for stale data

**Implementation:**

1. **Update Analytics Processor to Retry on Stale Data**
   ```python
   # In analytics_base.py

   def run(self):
       max_retries = 3
       retry_delay_minutes = 15

       for attempt in range(max_retries):
           try:
               self._check_dependencies()
               self._extract_data()
               self._transform_data()
               self._save_data()
               return
           except DataTooStaleError as e:
               if attempt < max_retries - 1:
                   logger.info(f"Data stale, retrying in {retry_delay_minutes}min (attempt {attempt + 1}/{max_retries})")
                   time.sleep(retry_delay_minutes * 60)
               else:
                   logger.error(f"Data still stale after {max_retries} attempts")
                   raise
   ```

2. **Increase Cloud Run Timeout**
   ```bash
   # Allow time for retries (15 min * 3 retries = 45 min + processing time)
   gcloud run services update nba-phase3-analytics-processors \
       --timeout=3600 \
       --region=us-west2
   ```

**Pros:**
- ✅ Handles temporary staleness issues
- ✅ Simple to implement
- ✅ Works with existing infrastructure

**Cons:**
- ⚠️ Wastes Cloud Run execution time on retries
- ⚠️ Not optimal - still waiting unnecessarily
- ⚠️ Can hit Cloud Run timeout limits

## Recommendation

### Recommended Solution: Option 1 (Event-Driven)

**Why:**
- Most robust long-term solution
- Handles all edge cases (late games, schedule changes)
- Optimal resource usage
- Industry best practice

**Implementation Timeline:**
- **Phase 1 (Week 1):** Implement scraper completion events
- **Phase 2 (Week 2):** Build orchestration Cloud Function
- **Phase 3 (Week 3):** Test with dual running (scheduled + event-driven)
- **Phase 4 (Week 4):** Cut over to event-driven only

**Quick Fix (Meanwhile):** Option 2
- Adjust analytics schedule to run 30 minutes after scrapers
- Increase staleness threshold to 12 hours
- This buys time while implementing proper event-driven solution

## Monitoring & Validation

### Metrics to Track

1. **Time from Scraper Completion to Analytics Start**
   - Target: < 5 minutes (event-driven)
   - Current: ~8-9 hours (fixed schedule)

2. **Stale Data Error Rate**
   - Target: 0%
   - Current: ~15-20% for late games

3. **Analytics Processing Success Rate**
   - Target: >99%
   - Monitor after implementation

### Dashboard Queries

```sql
-- Time between scraper and analytics completion
SELECT
  DATE(analytics.created_at) as process_date,
  AVG(TIMESTAMP_DIFF(analytics.created_at, scraper.created_at, MINUTE)) as avg_delay_minutes,
  MIN(TIMESTAMP_DIFF(analytics.created_at, scraper.created_at, MINUTE)) as min_delay_minutes,
  MAX(TIMESTAMP_DIFF(analytics.created_at, scraper.created_at, MINUTE)) as max_delay_minutes
FROM `nba-props-platform.nba_raw.bdl_player_boxscores` scraper
JOIN `nba-props-platform.nba_analytics.player_game_summary` analytics
  ON scraper.game_date = analytics.game_date
WHERE scraper.game_date >= CURRENT_DATE() - 30
GROUP BY process_date
ORDER BY process_date DESC;

-- Stale data error rate
SELECT
  DATE(created_at) as error_date,
  COUNT(*) as total_runs,
  SUM(CASE WHEN error_message LIKE '%stale%' THEN 1 ELSE 0 END) as stale_errors,
  ROUND(100.0 * SUM(CASE WHEN error_message LIKE '%stale%' THEN 1 ELSE 0 END) / COUNT(*), 2) as stale_error_rate_pct
FROM `nba-props-platform.monitoring.processor_run_history`
WHERE processor_name = 'PlayerGameSummaryProcessor'
  AND created_at >= CURRENT_DATE() - 30
GROUP BY error_date
ORDER BY error_date DESC;
```

## Implementation Checklist

### Quick Fix (Option 2) - 1 hour
- [ ] Determine current scraper completion time
- [ ] Schedule analytics 30 min after scrapers
- [ ] Increase staleness threshold to 12 hours
- [ ] Deploy and test
- [ ] Monitor for 1 week

### Event-Driven Solution (Option 1) - 2-3 weeks
- [ ] Create `scraper-completion` Pub/Sub topic
- [ ] Update scrapers to publish completion events
- [ ] Create Firestore collection for scraper status tracking
- [ ] Build analytics orchestration Cloud Function
- [ ] Deploy Cloud Function
- [ ] Test with dry-run mode
- [ ] Enable event-driven analytics triggers
- [ ] Monitor for 1 week dual-running
- [ ] Cut over to event-driven only
- [ ] Remove old scheduled jobs

## Cost Impact

### Event-Driven (Option 1)
- Cloud Function invocations: ~30/day × $0.0000004 = negligible
- Firestore reads/writes: ~100/day × $0.00006 = $0.006/day = $2/month
- Pub/Sub messages: ~30/day × $0.00000040 = negligible
- **Total: ~$2/month additional cost**

### Savings
- Reduced analytics failures → fewer reruns → saves money
- Optimal timing → reduced Cloud Run execution time → saves money
- **Net: Cost neutral or slight savings**

## Rollback Plan

If event-driven system has issues:
1. Re-enable scheduled Cloud Scheduler jobs
2. Disable Cloud Function trigger
3. System reverts to fixed schedule
4. No data loss - just returns to previous behavior

## References

- Analytics Base Code: `data_processors/analytics/analytics_base.py`
- Notification System: `shared/utils/notification_system.py`
- Current Schedules: Check Cloud Scheduler in GCP Console
- Related: [Pipeline Reliability Improvements](./pipeline-reliability-improvements/)
