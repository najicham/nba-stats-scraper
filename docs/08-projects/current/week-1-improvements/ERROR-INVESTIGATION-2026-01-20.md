# Error Investigation Summary - 2026-01-20

## Issues Investigated

This document summarizes the investigation of several errors received on 2026-01-20.

### 1. ✅ Alert Emails Using Brevo Instead of AWS SES

**Status:** ROOT CAUSE IDENTIFIED + PARTIALLY FIXED

**Problem:** All alert emails were being sent via Brevo instead of AWS SES.

**Root Cause:** Deployment scripts were not configured to pass AWS SES credentials to Cloud Run services. The notification system tries AWS SES first, but when credentials are missing, it falls back to Brevo.

**Fix Applied:**
- Updated `bin/shared/deploy_common.sh` to prefer AWS SES with Brevo fallback
- Updated `bin/analytics/deploy/deploy_analytics_processors.sh` to use AWS SES

**Remaining Work:**
- 10+ other deployment scripts still need to be updated with the same pattern
- See: [`AWS-SES-MIGRATION.md`](./AWS-SES-MIGRATION.md)

**Next Steps:**
1. Add AWS SES credentials to `.env` file:
   ```bash
   AWS_SES_ACCESS_KEY_ID=your-key
   AWS_SES_SECRET_ACCESS_KEY=your-secret
   AWS_SES_REGION=us-west-2
   AWS_SES_FROM_EMAIL=alert@989.ninja
   ```
2. Redeploy analytics processors: `./bin/analytics/deploy/deploy_analytics_processors.sh`
3. Update remaining deployment scripts using pattern in AWS-SES-MIGRATION.md
4. Verify emails show "X-SES-Message-ID" header instead of Brevo headers

---

### 2. ✅ PlayerGameSummaryProcessor Stale Data Errors

**Status:** ROOT CAUSE IDENTIFIED + SOLUTION DOCUMENTED

**Errors:**
```
❌ No Data Extracted: PlayerGameSummaryProcessor
🕐 Stale Data Warning: bdl_player_boxscores 8.8h old (warn threshold: 6h)
```

**Root Cause:** Orchestration timing mismatch
- Scrapers completed at 02:05 UTC on 2026-01-20
- Analytics processor ran at 10:47 UTC (8.8 hours later)
- Staleness threshold is 6 hours
- Result: Data flagged as too stale

**Why This Happens:**
- Both scrapers and analytics run on fixed schedules
- No coordination between them
- Late West Coast games + fixed analytics schedule = staleness

**Solutions:**

**Quick Fix (Option 2 - 1 hour):**
- Schedule analytics processor to run 30 minutes after scrapers
- Increase staleness threshold to 12 hours
- Deploy immediately to stop errors

**Recommended Long-term (Option 1 - 2-3 weeks):**
- Implement event-driven analytics triggering
- Scrapers publish completion event → Cloud Function checks all required scrapers complete → Triggers analytics
- Optimal timing, handles all edge cases
- Cost: ~$2/month additional

See: [`ANALYTICS-ORCHESTRATION-TIMING-FIX.md`](./ANALYTICS-ORCHESTRATION-TIMING-FIX.md)

**Next Steps:**
1. **Immediate:** Adjust analytics schedule to run 30 min after scrapers
2. **Week 1-2:** Implement event-driven orchestration
3. **Week 3:** Test dual-running (scheduled + event-driven)
4. **Week 4:** Cut over to event-driven only

---

### 3. ⏸️ NBA.com Scraper "Expected 2 teams, got 0"

**Status:** INVESTIGATED - NO FIX NEEDED (DEFERRED)

**Errors:**
```
DownloadDataException: Expected 2 teams for game 0022500014, got 0
DownloadDataException: Expected 2 teams for game 0022500017, got 0
```

**Root Cause:** NBA.com API returned empty team data for specific games.

**Location:** `scrapers/nbacom/nbac_team_boxscore.py:259`

**Likely Reasons:**
1. Games hadn't finished when scraper ran
2. Games were postponed/cancelled
3. NBA.com API temporary data availability issue

**Analysis:**
- The scraper correctly validates that exactly 2 teams should be returned
- This is appropriate error handling - better to fail than to process incomplete data
- Need to investigate what happened to these specific games

**Action Items:**
1. Check if games 0022500014 and 0022500017 were postponed/cancelled
2. Review scraper retry logic - should it retry if 0 teams returned?
3. Consider adding special handling for postponed games
4. Monitor if this recurs

**Deferred:** Low priority for now, needs more investigation into specific game circumstances.

---

### 4. ⏸️ Localhost:8080 Connection Reset Errors

**Status:** INVESTIGATED - LIKELY RELATED TO ISSUE #3 (DEFERRED)

**Errors:**
```
Max retries exceeded: HTTPConnectionPool(host='localhost', port=8080):
Max retries exceeded with url: /scrape
(Caused by ProtocolError('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer')))
```

**Root Cause:** Scraper service (running on port 8080) crashing during request processing.

**Connection to Issue #3:**
- Timeline matches: NBA.com scraper errors at 7:05-7:09 PM PST
- Connection resets happen shortly after
- When scraper raises validation error (0 teams), Flask service may crash or reset connection

**Analysis:**
- The scraper service should handle validation errors gracefully
- Connection reset suggests the service is dying instead of returning an error response
- Workflow retry logic tries 3 times and still fails

**Potential Fixes:**
1. Add better error handling in scraper Flask endpoints
2. Ensure validation errors return HTTP 500 instead of crashing
3. Add health check to detect crashed services
4. Review Docker container logs for crash details

**Deferred:** Low priority for now, monitor if this recurs.

---

## Summary Table

| Issue | Status | Priority | Time to Fix | Impact |
|-------|--------|----------|-------------|--------|
| 1. Brevo vs AWS SES | Partially Fixed | HIGH | 2-4 hours | HIGH - Cost savings |
| 2. Analytics Timing | Documented | HIGH | 1 hour (quick fix) | HIGH - Reliability |
| 3. NBA.com 0 teams | Investigated | LOW | Unknown | LOW - Rare occurrence |
| 4. Connection Reset | Investigated | LOW | 2-3 hours | LOW - Rare occurrence |

## Recommended Action Plan

### This Week (Jan 20-26)
1. **Day 1: AWS SES Migration**
   - Add AWS SES credentials to `.env`
   - Update high-priority deployment scripts (scrapers, raw processors, precompute)
   - Redeploy services
   - Verify emails using AWS SES
   - Time: 3-4 hours

2. **Day 2: Analytics Timing Quick Fix**
   - Check current scraper schedule
   - Schedule analytics to run 30 min after scrapers
   - Increase staleness threshold to 12 hours
   - Deploy and monitor
   - Time: 1 hour

3. **Day 3-5: Monitoring**
   - Verify AWS SES emails
   - Verify no more stale data errors
   - Monitor for recurrence of issues #3 and #4

### Next 2-3 Weeks
1. **Event-Driven Analytics** (Issue #2 long-term fix)
   - Week 1: Implement scraper completion events
   - Week 2: Build orchestration Cloud Function
   - Week 3: Test and cut over

2. **Remaining AWS SES Migration**
   - Update MLB-specific deployment scripts
   - Update monitoring/backfill scripts
   - Remove Brevo credentials once confirmed working

## Files Modified

### Code Changes
- `bin/shared/deploy_common.sh` - Updated email config functions
- `bin/analytics/deploy/deploy_analytics_processors.sh` - AWS SES support

### Documentation Created
- `docs/08-projects/current/week-1-improvements/AWS-SES-MIGRATION.md` - Complete SES migration guide
- `docs/08-projects/current/week-1-improvements/ANALYTICS-ORCHESTRATION-TIMING-FIX.md` - Orchestration fix options
- `docs/08-projects/current/week-1-improvements/ERROR-INVESTIGATION-2026-01-20.md` - This summary

### Scripts Created
- `scripts/update_ses_config.sh` - Bulk update script for remaining deployment scripts (not tested)

## Questions for User

1. **AWS SES Credentials:** Do you have the AWS SES credentials ready, or do we need to create them in AWS?

2. **Analytics Schedule:** What time do the scrapers currently run? (Need this to schedule analytics correctly)

3. **Event-Driven Priority:** Should we implement the event-driven solution immediately, or is the quick fix sufficient for now?

4. **Deployment Priority:** Which deployment scripts are most critical to update first?
   - Scrapers?
   - Raw processors?
   - Precompute?
   - All of them?

## References

- AWS SES Migration: [`AWS-SES-MIGRATION.md`](./AWS-SES-MIGRATION.md)
- Analytics Timing Fix: [`ANALYTICS-ORCHESTRATION-TIMING-FIX.md`](./ANALYTICS-ORCHESTRATION-TIMING-FIX.md)
- Notification System Code: `shared/utils/notification_system.py`
- Analytics Base Code: `data_processors/analytics/analytics_base.py`
- NBA.com Scraper: `scrapers/nbacom/nbac_team_boxscore.py`
