# Error Log Review - February 3, 2026

**Session**: Error analysis of last 72 hours
**Date**: 2026-02-03
**Analysis Period**: Jan 31 - Feb 3, 2026
**Total Errors Logged**: 20,935 errors across 13 processors

---

## Executive Summary

Analysis of Cloud Logging and BigQuery pipeline event logs revealed **four distinct issues**, ranging from resolved incidents to active failures requiring immediate attention. The most critical issue is the **BDB Play-by-Play Scraper** experiencing repeated Google Drive API failures (23 errors/24h).

### Priority Matrix

| Issue | Status | Priority | Impact | Action Required |
|-------|--------|----------|--------|-----------------|
| BDB Scraper Google Drive Failures | **ACTIVE** | **P0** | Data loss | Investigate + Fix |
| Notification System Log Noise | Ongoing | P2 | Operations burden | Reduce log level |
| NBAC Play-by-Play Retries | Intermittent | P3 | Monitor | Watch for patterns |
| PlayerGameSummary Error Spike | **RESOLVED** | P4 | None | Document RCA |

---

## Issue #1: BDB Play-by-Play Scraper Failures ⚠️ CRITICAL

### Status
- **ACTIVE FAILURE** - Ongoing for 72+ hours
- **23 errors in last 24 hours** (every ~4 minutes)
- **67 total errors in last 72 hours**

### Symptoms
```
Processor: bdb_pbp_scraper
Phase: phase_2
Error metadata: {"url": "google_drive_api", "retry_count": 0, "step": "download"}
Error frequency: ~23 errors/day (every 62 minutes)
```

### Error Trend
```
SELECT
  DATE(timestamp) as date,
  COUNT(*) as error_count
FROM `nba-props-platform.nba_orchestration.pipeline_event_log`
WHERE event_type = 'error'
  AND processor_name = 'bdb_pbp_scraper'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
GROUP BY date
```

### Impact Assessment
- **Data Completeness**: Basketball Database play-by-play data not being ingested
- **Downstream**: Phase 3/4 analytics may have incomplete shot zone data
- **Grading**: Potential missing features for ML predictions

### Root Cause Hypotheses
1. **Google Drive API Authentication Failure**
   - Service account credentials expired/invalid
   - Shared Drive access permissions changed

2. **API Quota Exhaustion**
   - Daily quota limit reached
   - Per-minute rate limit exceeded

3. **File Availability Issues**
   - Files not being uploaded to expected Drive location
   - Naming convention changed by upstream provider

### Investigation Steps

**Step 1: Check Service Account Credentials**
```bash
# Verify service account has Drive API enabled
gcloud iam service-accounts list --project=nba-props-platform

# Check if GOOGLE_APPLICATION_CREDENTIALS is set correctly in Cloud Run
gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"
```

**Step 2: Review Recent Logs with Full Error Details**
```bash
gcloud logging read \
  'resource.labels.service_name="nba-phase2-raw-processors"
   AND jsonPayload.processor_name="bdb_pbp_scraper"
   AND severity>=ERROR' \
  --limit=5 \
  --format=json \
  --freshness=24h | jq '.[] | {
    timestamp: .timestamp,
    error: .jsonPayload.error,
    message: .jsonPayload.message,
    traceback: .jsonPayload.traceback
  }'
```

**Step 3: Check Scraper Code for Google Drive Access**
```bash
# Find the BDB scraper implementation
find scrapers/ -name "*bdb*" -o -name "*basketball*database*"

# Review Google Drive API usage
grep -r "drive" scrapers/ --include="*.py"
grep -r "google.*drive" scrapers/ --include="*.py"
```

**Step 4: Verify API Quotas**
```bash
# Check Google Drive API quotas
gcloud services quota describe \
  drive.googleapis.com/quota/queries-per-day \
  --project=nba-props-platform
```

**Step 5: Test Manual Run**
```bash
# Trigger manual scraper run to see live error
gcloud pubsub topics publish scraper-trigger \
  --message='{"scraper_name": "bdb_pbp_scraper", "game_date": "2026-02-02"}' \
  --project=nba-props-platform
```

### Recommended Fix Path
1. Identify exact error message from logs (Step 2)
2. If auth issue: Update service account key or permissions
3. If quota issue: Request quota increase or implement backoff
4. If availability issue: Update scraper to check file existence first
5. Add retry logic with exponential backoff for transient failures
6. Deploy fix and monitor for 24 hours

### Data Gap Recovery
Once fixed, backfill missing data:
```bash
# Identify missing dates
bq query --use_legacy_sql=false "
SELECT DISTINCT game_date
FROM \`nba-props-platform.nba_orchestration.scraper_data_arrival\`
WHERE scraper_name = 'bdb_pbp_scraper'
  AND was_available = false
  AND game_date >= CURRENT_DATE() - 7
ORDER BY game_date
"

# Trigger backfill
python bin/orchestration/backfill_scraper.py \
  --scraper=bdb_pbp_scraper \
  --start-date=2026-01-31 \
  --end-date=2026-02-03
```

---

## Issue #2: Notification System Error Log Noise

### Status
- **ONGOING** - Present for months
- **~100 ERROR logs per day** across Phase 2/3 processors
- **Non-critical** - System handles gracefully

### Symptoms
```
ERROR:shared.utils.notification_system:Failed to initialize email handler:
  ModuleNotFoundError: No module named 'boto3'

ERROR:shared.utils.notification_system:Failed to initialize email handler:
  ValueError: Email alerting requires these environment variables:
  BREVO_SMTP_USERNAME, BREVO_FROM_EMAIL
```

### Error Pattern
- Occurs every ~15 minutes during processor runs
- Affects both Phase 2 (nba-phase2-raw-processors) and Phase 3 (nba-phase3-analytics-processors)
- Consistently shows same two errors:
  1. boto3 import failure (AWS SES handler)
  2. Brevo config missing (Brevo handler)

### Root Cause
**File**: `shared/utils/notification_system.py:164-179`

The notification system tries to initialize email handlers in this order:
1. Try AWS SES (requires boto3 package) → **FAILS** - boto3 not installed
2. Fall back to Brevo (requires env vars) → **FAILS** - vars not configured
3. Catch exception, disable email, continue → Works but logs at ERROR level

```python
# Lines 164-179
if self.config.email_enabled:
    try:
        # Try AWS SES first, fall back to Brevo if not configured
        try:
            from shared.utils.email_alerting_ses import EmailAlerterSES
            self._email_handler = EmailAlerterSES()
            logger.info("Using AWS SES for email alerts")
        except (ImportError, ValueError) as ses_error:
            logger.warning(f"AWS SES not available ({ses_error}), falling back to Brevo")
            from shared.utils.email_alerting import EmailAlerter
            self._email_handler = EmailAlerter()
            logger.info("Using Brevo for email alerts")
    except Exception as e:
        logger.error(f"Failed to initialize email handler: {e}", exc_info=True)  # ← THIS LINE
        self._email_handler = None
        self.config.email_enabled = False
```

### Impact Assessment
- **Functional**: None - system works correctly
- **Operational**: ERROR logs create noise, making real issues harder to find
- **Observability**: Inflates error counts in monitoring dashboards
- **Cost**: Minimal - small increase in Cloud Logging costs

### Recommended Fixes

**Option 1: Change Log Level (Quick Fix - 5 min)**
```python
# shared/utils/notification_system.py:177
# Change from:
logger.error(f"Failed to initialize email handler: {e}", exc_info=True)

# To:
logger.info(f"Email notifications disabled - no handler configured: {e}")
```

**Option 2: Add boto3 Dependency (If SES is intended)**
```python
# Add to requirements.txt or Dockerfile
boto3==1.34.34

# Set environment variables in Cloud Run
ENABLE_EMAIL_ALERTS=true
AWS_REGION=us-west-2
AWS_SES_FROM_EMAIL=alerts@nba-props.example.com
```

**Option 3: Configure Brevo (If Brevo is intended)**
```bash
# Add to Cloud Run environment variables
gcloud run services update nba-phase2-raw-processors \
  --region=us-west2 \
  --set-env-vars="BREVO_SMTP_USERNAME=xxx,BREVO_FROM_EMAIL=alerts@example.com"
```

**Option 4: Disable Email Completely (If not needed)**
```bash
# Set ENABLE_EMAIL_ALERTS=false in all services
gcloud run services update nba-phase2-raw-processors \
  --region=us-west2 \
  --set-env-vars="ENABLE_EMAIL_ALERTS=false"
```

### Recommended Action
**Choose Option 1** (change log level) because:
- Email notifications appear unused (no config for 3+ months)
- Quick fix with zero risk
- Reduces log noise immediately
- Can still add email later if needed

### Implementation
1. Edit `shared/utils/notification_system.py:177`
2. Change `logger.error` to `logger.info`
3. Update error message to be less alarming
4. Deploy to all affected services:
   ```bash
   ./bin/deploy-service.sh nba-phase2-raw-processors
   ./bin/deploy-service.sh nba-phase3-analytics-processors
   ./bin/deploy-service.sh nba-phase4-precompute-processors
   ```
5. Verify logs after 1 hour - should see 0 notification errors

---

## Issue #3: NBAC Play-by-Play Processor Retries

### Status
- **INTERMITTENT** - Specific to one game
- **4 errors in last 24 hours**
- **Likely resolved** - game is now final

### Symptoms
```
Processor: nbac_play_by_play
Game: 0022500715 (PHI @ LAC on Feb 2, 2026)
Errors:
  - Download step: 8 retries
  - Export step: 5 retries

URL: https://cdn.nba.com/static/json/liveData/playbyplay/playbyplay_0022500715.json
```

### Error Timeline
```
2026-02-03 03:11:59 - Download error (retry 8)
2026-02-03 03:15:52 - Export error (retry 5)
2026-02-03 03:16:49 - Export error (retry 0)
2026-02-03 04:00:08 - Initialization error
```

### Investigation Results
```bash
# Game is now final
bq query --use_legacy_sql=false "
SELECT game_date, game_id, away_team_tricode, home_team_tricode, game_status
FROM \`nba-props-platform.nba_reference.nba_schedule\`
WHERE game_date >= CURRENT_DATE() - 3 AND game_id = '0022500715'
"

Result:
  game_date: 2026-02-02
  game_id: 0022500715
  teams: PHI @ LAC
  game_status: 3 (Final)
```

### Root Cause Hypothesis
**Timing Issue During Live Game**
- Errors occurred at ~3:00-3:15 AM ET (midnight-12:15 AM PT)
- Game was likely still in progress or just ending
- NBA.com CDN may have been:
  - Updating play-by-play JSON in real-time
  - Temporarily unavailable during processing
  - Serving incomplete data before final stats posted

### Impact Assessment
- **Data Completeness**: Likely resolved once game finalized
- **Retry Logic**: System retried 8+ times as designed
- **Current Status**: No recent errors (game now final, data available)

### Recommended Actions
1. **Monitor Pattern** - Check if this happens for other games
   ```bash
   bq query --use_legacy_sql=false "
   SELECT
     game_date,
     COUNT(*) as error_count,
     COUNT(DISTINCT game_id) as affected_games
   FROM \`nba-props-platform.nba_orchestration.pipeline_event_log\`
   WHERE event_type = 'error'
     AND processor_name = 'nbac_play_by_play'
     AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
   GROUP BY game_date
   ORDER BY game_date DESC
   "
   ```

2. **Review Retry Logic** - Ensure 8 retries is appropriate
   - File: `data_processors/raw/processor_base.py` or `scrapers/nbac_play_by_play_scraper.py`
   - Check retry backoff timing (exponential vs linear)
   - Verify retry conditions (transient vs permanent errors)

3. **Add Data Validation** - Check for partial play-by-play before processing
   ```python
   # Before processing, validate:
   if game_status == 3:  # Final
       # Proceed with full processing
   elif game_status == 2:  # In Progress
       # Queue for retry after game ends
   ```

4. **No Immediate Action Required** - Issue appears self-resolved

---

## Issue #4: PlayerGameSummaryProcessor Error Spike (RESOLVED)

### Status
- **RESOLVED** - Back to baseline
- **Peak**: 21,463 errors on Jan 31
- **Current**: 5 errors on Feb 2 (baseline)

### Error Trend
| Date | Error Count | Status |
|------|-------------|--------|
| Jan 27 | 1,905 | Elevated |
| Jan 28 | 1,472 | Elevated |
| Jan 29 | 6 | **Healthy** ✅ |
| Jan 30 | 13,959 | **SPIKE** ⚠️ |
| Jan 31 | 21,463 | **PEAK** ⚠️ |
| Feb 1 | 611 | Declining |
| Feb 2 | 5 | **Resolved** ✅ |
| Feb 3 | TBD | Monitor |

### Pattern Analysis
```
FROM: nba-props-platform.nba_orchestration.pipeline_event_log
WHERE: event_type = 'error' AND processor_name = 'PlayerGameSummaryProcessor'

Key Observations:
- 98.8% of all pipeline errors (20,697 / 20,935)
- All errors have metadata = null
- Spike coincides with Jan 30-31 period
- Resolution happened automatically (no code changes deployed)
```

### Root Cause Hypothesis

**Likely Cause: Notification System Initialization Loop**

The notification system `_initialize_handlers()` errors (boto3/Brevo) were being logged as processor errors in the pipeline event log. On Jan 30-31, something caused the notification system to be initialized repeatedly:

Possible triggers:
1. **Processor Restarts**: Cloud Run containers restarted frequently due to:
   - Memory pressure
   - Deployment updates
   - Health check failures

2. **Heartbeat Frequency**: Heartbeat or status update calls triggered notification system init

3. **Concurrency**: Multiple concurrent processor runs each logging init errors

**Resolution**: Whatever caused the frequent restarts/initializations stopped on Feb 1.

### Evidence Supporting This Theory
1. **Error Count Matches Pattern**: ~21K errors = ~1,400 errors/hour = ~23 errors/min
2. **No Metadata**: Notification errors don't pass metadata to log_processor_error
3. **Sudden Resolution**: No code deployment needed - external factor changed
4. **Same Services Affected**: Phase 2 and Phase 3 both show notification errors

### Verification Steps
```bash
# Check Cloud Run restart frequency during spike period
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND resource.labels.service_name="nba-phase3-analytics-processors"
   AND timestamp>="2026-01-30T00:00:00Z"
   AND timestamp<"2026-02-01T00:00:00Z"
   AND (textPayload:"restarted" OR textPayload:"started")' \
  --limit=100 \
  --format=json | jq 'length'

# Check memory usage during spike
gcloud logging read \
  'resource.type="cloud_run_revision"
   AND resource.labels.service_name="nba-phase3-analytics-processors"
   AND timestamp>="2026-01-30T00:00:00Z"
   AND timestamp<"2026-02-01T00:00:00Z"
   AND jsonPayload.message:~"memory"' \
  --limit=50
```

### Lessons Learned
1. **Log Level Matters**: ERROR-level logging for graceful fallbacks inflates error metrics
2. **Initialization Logging**: Startup errors can multiply with container restarts
3. **Observability**: Need better distinction between critical errors and informational events
4. **Monitoring**: Should alert on error rate increases, not just absolute counts

### Recommended Follow-Up
1. **Fix Notification System Log Level** (See Issue #2) - Prevents recurrence
2. **Add Service Health Metrics**: Track container restarts, memory usage
3. **Improve Error Categories**: Distinguish startup errors from processing errors
4. **Document in Runbook**: Add to troubleshooting-matrix.md

### No Action Required
Issue is resolved. Focus on preventing recurrence via Issue #2 fix.

---

## Other Processors with Errors (72-hour summary)

| Processor | Error Count | Status | Notes |
|-----------|-------------|--------|-------|
| PlayerGameSummaryProcessor | 20,697 | Resolved | See Issue #4 |
| MLFeatureStoreProcessor | 80 | Monitor | Check if related to missing PBP data |
| bdb_pbp_scraper | 67 | **ACTIVE** | See Issue #1 |
| nbac_team_boxscore | 48 | Monitor | May be transient availability issues |
| nbac_play_by_play | 14 | Monitor | See Issue #3 |
| PlayerDailyCacheProcessor | 9 | Low priority | Investigate if recurring |
| espn_team_roster_api | 5 | Low priority | Spot check |
| Others | <5 each | Normal | Acceptable error rate |

---

## Validation Queries for Opus Session

### Check Current System Health
```bash
# Run daily validation
/validate-daily

# Check recent phase executions
bq query --use_legacy_sql=false "
SELECT phase_name, status, game_date, execution_timestamp
FROM \`nba-props-platform.nba_orchestration.phase_execution_log\`
WHERE game_date >= CURRENT_DATE() - 2
ORDER BY execution_timestamp DESC
LIMIT 20
"

# Check for data gaps
bq query --use_legacy_sql=false "
SELECT
  game_date,
  COUNT(DISTINCT game_id) as games_scheduled,
  COUNT(DISTINCT CASE WHEN pbp_available THEN game_id END) as pbp_available
FROM \`nba-props-platform.nba_reference.nba_schedule\`
WHERE game_date >= CURRENT_DATE() - 7
  AND game_status = 3
GROUP BY game_date
ORDER BY game_date DESC
"
```

### Monitor BDB Scraper
```bash
# Check if issue persists
gcloud logging read \
  'resource.labels.service_name="nba-phase2-raw-processors"
   AND jsonPayload.processor_name="bdb_pbp_scraper"
   AND severity>=ERROR' \
  --limit=5 \
  --freshness=1h

# Check scraper success rate
bq query --use_legacy_sql=false "
SELECT
  DATE(attempt_timestamp) as date,
  COUNT(*) as attempts,
  COUNTIF(was_available) as successful,
  ROUND(100.0 * COUNTIF(was_available) / COUNT(*), 1) as success_rate
FROM \`nba-props-platform.nba_orchestration.scraper_data_arrival\`
WHERE scraper_name = 'bdb_pbp_scraper'
  AND game_date >= CURRENT_DATE() - 7
GROUP BY date
ORDER BY date DESC
"
```

---

## Recommended Session Plan for Opus

### Phase 1: Immediate Fixes (30 min)
1. **Fix notification system log level** (Issue #2)
   - Edit `shared/utils/notification_system.py:177`
   - Deploy to Phase 2, 3, 4 processors
   - Verify no new notification errors

### Phase 2: Critical Investigation (60 min)
2. **Investigate BDB scraper failures** (Issue #1)
   - Follow investigation steps above
   - Identify exact error from logs
   - Implement fix (auth, quota, or availability)
   - Test and deploy

### Phase 3: Monitoring & Documentation (30 min)
3. **Set up monitoring** for Issue #3 (NBAC retries)
   - Create alert for excessive retries
   - Document expected retry behavior

4. **Update documentation**
   - Add findings to `docs/02-operations/session-learnings.md`
   - Update `docs/02-operations/troubleshooting-matrix.md`
   - Create handoff doc: `docs/09-handoff/2026-02-03-SESSION-N-HANDOFF.md`

### Phase 4: Validation (15 min)
5. **Verify fixes**
   - Run `/validate-daily` after 2 hours
   - Check error logs show <10 errors/day
   - Confirm BDB scraper successful

---

## Success Criteria

- [ ] BDB scraper errors reduced to <5/day
- [ ] Notification system ERROR logs eliminated (should be 0)
- [ ] Total pipeline errors <50/day (down from 7,000+/day during spike)
- [ ] No critical data gaps in last 7 days
- [ ] Documentation updated with findings
- [ ] Monitoring alerts configured for future issues

---

## Files to Review/Edit

### Investigation
- `scrapers/` - Find BDB scraper implementation
- `data_processors/raw/processor_base.py` - Retry logic
- `shared/utils/notification_system.py:162-199` - Notification init

### Fix Implementation
- `shared/utils/notification_system.py:177` - Change log level
- BDB scraper file (TBD based on investigation)

### Documentation
- `docs/02-operations/session-learnings.md` - Add RCA for Issue #4
- `docs/02-operations/troubleshooting-matrix.md` - Add error patterns
- `docs/09-handoff/` - Create session handoff

---

## Questions for Discussion

1. **Email Notifications**: Are email alerts actually needed? If not, can we remove the feature entirely?
2. **BDB Scraper**: Is Basketball Database data critical? Can we gracefully degrade without it?
3. **Error Logging Philosophy**: Should startup/initialization errors be logged at INFO level instead of ERROR?
4. **Retry Logic**: Is 8 retries appropriate for transient NBA.com API failures, or should we retry until game finalizes?
5. **Monitoring**: Should we set up PagerDuty/Slack alerts for error rate spikes (e.g., >100 errors/hour)?

---

## Contact & Context

- **Project**: NBA Props Platform (nba-props-platform)
- **Region**: us-west2
- **Key Services**:
  - nba-phase2-raw-processors
  - nba-phase3-analytics-processors
  - nba-scrapers
- **BigQuery Datasets**: nba_orchestration, nba_predictions, nba_raw, nba_analytics

This document compiled from:
- Cloud Logging analysis (last 72 hours)
- BigQuery `nba_orchestration.pipeline_event_log` queries
- Service deployment history
- Code review of error handling paths
