# Sonnet Investigation Task: Root Cause Analysis & Prevention

## Objective
Investigate WHY these data quality issues occurred and design systemic preventions. We know WHAT happened - now understand WHY the system allowed it and HOW to prevent recurrence.

## Context
On Jan 27, 2026, we discovered 6 data quality issues:
1. NULL usage_rate for 71% of players (team stats processed after player stats)
2. 0 predictions generated (betting lines scraped after Phase 3 ran)
3. 93 duplicate records (MERGE fallback to INSERT)
4. Impossible usage rates >100% (joining to partial team stats)
5. Incomplete analytics coverage (66-88% on some dates)
6. A previous Sonnet fix session was supposed to fix P0/P1 but didn't succeed

## Investigation Questions

### 1. Why Did the Previous Fix Session Partially Fail?

A Sonnet chat attempted fixes. Results from `fix-log.md`:

**What WORKED**:
- ✅ has_prop_line fixed via direct SQL UPDATE (37 players in 2 seconds)

**What FAILED**:
- ❌ Prediction coordinator timed out (>5 min HTTP timeout)
- ❌ Deployment failed (couldn't find correct deployment method)
- ❌ usage_rate still at 28.8%

**Key Blockers Found**:
1. **Cloud Run HTTP timeout**: Prediction coordinator couldn't respond within 5 minutes
2. **Deployment complexity**: Neither source-based nor image-based deploy worked
3. **Schema complexity**: Manual SQL fix for usage_rate was too complex

**Investigate further**:
```bash
# Check prediction coordinator logs to see if it actually processed
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-coordinator AND timestamp>=\"2026-01-27T14:00:00Z\"" --limit=50 --format=json

# Check for OOM or timeout errors
gcloud logging read "resource.type=cloud_run_revision AND textPayload:\"timeout\" OR textPayload:\"memory\" AND timestamp>=\"2026-01-27T00:00:00Z\"" --limit=20

# Check Cloud Run service config (timeout setting)
gcloud run services describe prediction-coordinator --region=us-west2 --format="value(spec.template.spec.timeoutSeconds)"
```

**Questions to answer**:
- Did the prediction coordinator actually start processing?
- Was it killed due to timeout before completing?
- What is the current timeout setting and is it sufficient?
- Why is deployment so complex? Is there missing documentation?

---

### 2. Why Is There No Processing Order Enforcement?

The architecture allows `player_game_summary` and `team_offense_game_summary` to run in parallel, even though player depends on team for usage_rate.

**Investigate**:
- How were dependencies originally designed?
- Is there documentation about expected processing order?
- Were there tests that should have caught this?

```bash
# Check for dependency documentation
find docs/ -name "*.md" -exec grep -l -i "dependency\|order\|sequence" {} \;

# Check for integration tests
find tests/ -name "*.py" -exec grep -l -i "usage_rate\|team.*player" {} \;

# Check orchestration config for any ordering hints
cat shared/config/orchestration_config.py | grep -A 20 "phase3"
```

**Questions to answer**:
- Was parallel execution intentional or accidental?
- Are there any existing mechanisms for processor dependencies?
- What would be the proper place to enforce ordering?

---

### 3. Why Did MERGE Create Duplicates?

The MERGE operation has deduplication logic but 93 duplicates were created during backfill.

**Investigate**:
- Check backfill logs from Jan 27 ~20:16
- Look for streaming buffer warnings
- Check if MERGE actually ran or fell back to INSERT

```bash
# Check backfill job logs
gcloud logging read "textPayload:\"backfill\" AND textPayload:\"player_game_summary\" AND timestamp>=\"2026-01-27T20:00:00Z\" AND timestamp<=\"2026-01-27T21:00:00Z\"" --limit=50

# Look for streaming buffer or MERGE warnings
gcloud logging read "textPayload:\"streaming buffer\" OR textPayload:\"MERGE failed\" AND timestamp>=\"2026-01-27T00:00:00Z\"" --limit=20
```

**Questions to answer**:
- Did MERGE execute or fall back?
- If fallback, what error triggered it?
- Why didn't post-save duplicate check alert us?

---

### 4. Why Is There No Alert for 0 Predictions?

The prediction coordinator found 0 eligible players and silently succeeded with 0 predictions. This should be a critical alert.

**Investigate**:
- Check prediction coordinator code for alerting logic
- Check if there's monitoring for prediction counts
- Check notification system configuration

```bash
# Find prediction coordinator alerting
grep -r "notify\|alert\|slack\|warning" prediction_coordinator/ --include="*.py"

# Check for monitoring queries
find . -name "*.sql" -exec grep -l "prediction.*count\|zero.*prediction" {} \;

# Check notification config
cat shared/config/notification_config.py 2>/dev/null || echo "No notification config found"
```

**Questions to answer**:
- Is there supposed to be an alert for 0 predictions?
- If yes, why didn't it fire?
- If no, why wasn't this anticipated?

---

### 5. Why Do Partial Team Stats Exist?

The `team_offense_game_summary` table has BOTH partial and complete records for the same game, causing impossible usage rates.

**Investigate**:
- How are team stats scraped and processed?
- Is there deduplication or "latest wins" logic?
- Why are early scrapes (partial data) not being replaced?

```bash
# Check team stats processor for dedup logic
grep -n "MERGE\|UPDATE\|duplicate\|latest" data_processors/analytics/team_offense_game_summary/*.py

# Check if there's a "completeness" check before saving
grep -n "complete\|final\|game_status" data_processors/analytics/team_offense_game_summary/*.py
```

**Questions to answer**:
- Should partial game data ever be saved?
- Is there a mechanism to mark data as "final"?
- Why doesn't MERGE replace partial with complete?

---

### 6. What Monitoring/Alerting Gaps Exist?

These issues went undetected until manual investigation.

**Investigate**:
- What monitoring exists today?
- What alerts should have fired but didn't?
- What new monitoring is needed?

```bash
# Find existing monitoring
find . -path ./node_modules -prune -o -name "*monitor*" -print
find . -path ./node_modules -prune -o -name "*alert*" -print

# Check for scheduled health checks
grep -r "health\|daily.*check\|validate" config/workflows.yaml

# Check BigQuery scheduled queries
bq ls --transfer_config --transfer_location=us
```

**Questions to answer**:
- Is there a daily data quality check?
- Are there alerts for: 0 predictions, low usage_rate coverage, duplicates?
- What monitoring would have caught these issues earlier?

---

## Deliverables

After investigation, produce:

### 1. Root Cause Report
Document each issue with:
- **What failed**: Specific component/logic
- **Why it failed**: Design flaw, missing check, race condition
- **When it started**: Was this always broken or recent regression?
- **Impact scope**: How many dates/players affected historically?

### 2. Prevention Recommendations
For each issue, recommend:
- **Immediate fix**: Code change to prevent recurrence
- **Detection mechanism**: Alert/monitor to catch if it happens again
- **Test coverage**: Integration test to prevent regression

### 3. Monitoring Gaps Analysis
List monitoring that should exist:
- Daily data quality assertions
- Pipeline timing alerts
- Prediction count thresholds
- Duplicate detection
- Coverage percentage alerts

### 4. Architecture Improvements
Suggest systemic changes:
- Processing order enforcement mechanism
- Data quality gates between phases
- Automatic reprocessing when dependencies complete
- Circuit breakers for cascade prevention

---

## Example Output Format

```markdown
## Issue: NULL Usage Rate

### What Failed
PlayerGameSummaryProcessor.extract_raw_data() queries team_offense_game_summary
for usage_rate calculation, but team stats don't exist yet.

### Why It Failed
- Phase 3 processors run in parallel with no ordering
- No dependency check before processing
- ANALYTICS_TRIGGERS maps both processors to same Pub/Sub trigger

### When It Started
This has likely been an intermittent issue since [date], but became worse
when [change] was made on [date].

### Historical Impact
Checked last 30 days:
- 12 days had >20% NULL usage_rate
- Affected ~2,400 player records total

### Prevention
1. **Code fix**: Add team stats availability check (see 01-team-stats-dependency.md)
2. **Monitor**: Alert if usage_rate NULL% > 20% for any day
3. **Test**: Integration test that processes player stats before team stats and verifies error handling

### Related Issues
- Connects to: Impossible usage rates (>100%)
- Root cause shared with: Partial team stats issue
```

---

## Investigation Approach

1. Start with logs and git history to understand timeline
2. Trace code paths for each failure mode
3. Check for missing tests/monitoring
4. Propose specific, actionable fixes
5. Prioritize by impact and implementation difficulty

**Time budget**: This investigation should take 60-90 minutes. Focus on actionable insights, not exhaustive documentation.
