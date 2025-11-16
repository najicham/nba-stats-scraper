# Phase 3 Troubleshooting & Recovery

**File:** `docs/processors/04-phase3-troubleshooting.md`
**Created:** 2025-11-15 15:00 PST
**Last Updated:** 2025-11-15 15:00 PST
**Purpose:** Failure scenarios, recovery procedures, and runbooks for Phase 3 processors
**Status:** Draft (awaiting deployment)
**Audience:** On-call engineers troubleshooting Phase 3 issues

**Related Docs:**
- **Operations:** See `02-phase3-operations-guide.md` for processor specifications
- **Scheduling:** See `03-phase3-scheduling-strategy.md` for Cloud Scheduler configuration
- **Phase 1 Troubleshooting:** See `docs/orchestration/04-troubleshooting.md` for comparison

---

## Table of Contents

1. [Quick Diagnosis](#quick-diagnosis)
2. [Failure Scenarios](#failure-scenarios)
3. [Manual Recovery Runbook](#manual-recovery-runbook)
4. [Retry Strategy](#retry-strategy)
5. [Alert Configuration](#alert-configuration)
6. [Common Issues](#common-issues)

---

## Quick Diagnosis

### Is Phase 3 Working?

Run this query to check overall Phase 3 health:

```sql
-- Quick health check for Phase 3
SELECT
  'player_game_summary' as processor,
  CASE WHEN COUNT(*) >= 200 THEN '✅ OK' ELSE '❌ FAILED' END as status,
  COUNT(*) as rows,
  MAX(processed_at) as last_run,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_since_last_run
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'team_offense_game_summary',
  CASE WHEN COUNT(*) >= 20 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*),
  MAX(processed_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR)
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'team_defense_game_summary',
  CASE WHEN COUNT(*) >= 20 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*),
  MAX(processed_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR)
FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT
  'upcoming_team_game_context',
  CASE WHEN COUNT(*) >= 20 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*),
  MAX(processed_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR)
FROM `nba-props-platform.nba_analytics.upcoming_team_game_context`
WHERE game_date = CURRENT_DATE()

UNION ALL

SELECT
  'upcoming_player_game_context',
  CASE WHEN COUNT(*) >= 100 THEN '✅ OK' ELSE '❌ FAILED' END,
  COUNT(*),
  MAX(processed_at),
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR)
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();
```

**Expected Output (Healthy):**
```
processor                     | status    | rows | last_run            | hours_since_last_run
------------------------------|-----------|------|---------------------|---------------------
player_game_summary           | ✅ OK     | 452  | 2025-11-15 02:33:15 | 12
team_offense_game_summary     | ✅ OK     | 28   | 2025-11-15 02:33:18 | 12
team_defense_game_summary     | ✅ OK     | 28   | 2025-11-15 02:33:20 | 12
upcoming_team_game_context    | ✅ OK     | 60   | 2025-11-15 17:05:42 | 0
upcoming_player_game_context  | ✅ OK     | 178  | 2025-11-15 17:06:15 | 0
```

---

### Check Recent Executions

```bash
# Check all Phase 3 job executions in last 24h
for job in phase3-player-game-summary phase3-team-offense-game-summary phase3-team-defense-game-summary phase3-upcoming-team-game-context phase3-upcoming-player-game-context; do
  echo "=== $job ==="
  gcloud run jobs executions list \
    --job=$job \
    --region=us-central1 \
    --limit=5 \
    --format="table(name,status,startTime)"
  echo ""
done
```

---

### Check Cloud Scheduler

```bash
# Verify scheduler jobs are enabled
gcloud scheduler jobs list \
  --location=us-central1 \
  --filter="name:phase3" \
  --format="table(name,state,schedule)"
```

**Expected Output:**
```
NAME                          STATE    SCHEDULE
phase3-historical-nightly     ENABLED  0 2 * * *
phase3-team-context-morning   ENABLED  0 6 * * *
phase3-team-context-midday    ENABLED  0 12 * * *
phase3-team-context-pregame   ENABLED  0 17 * * *
phase3-player-context-morning ENABLED  30 6 * * *
phase3-player-context-pregame ENABLED  0 18 * * *
```

---

## Failure Scenarios

### Scenario 1: Player Game Summary Fails

**Symptoms:**
- Query shows < 200 player records for yesterday
- Cloud Run execution shows FAILED status
- Logs show errors like "Table not found" or "No data"

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| Team processors | ✅ Unaffected | Parallel, independent |
| Phase 4/5 | ❌ Missing data | Need player performance data |

**Diagnosis:**

```bash
# Check execution logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=phase3-player-game-summary AND severity>=ERROR" \
  --limit=50 \
  --format=json \
  --project=nba-props-platform
```

**Common Errors:**

**Error:** "Table not found: nba_raw.nbac_gamebook_player_stats"
- **Cause:** Phase 2 gamebook processor failed
- **Recovery:** Check Phase 2 processor status, manually trigger if needed

**Error:** "No rows returned for date 2025-11-14"
- **Cause:** No games yesterday OR Phase 2 data missing
- **Recovery:** Verify games scheduled, check Phase 2 data

**Recovery Steps:**

1. **Verify Phase 2 Data Exists:**
```sql
-- Check Phase 2 source data
SELECT COUNT(*) as gamebook_rows
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date = '2025-11-14';

SELECT COUNT(*) as bdl_rows
FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
WHERE game_date = '2025-11-14';
```

2. **If Phase 2 Missing → Fix Phase 2 First:**
```bash
# See Phase 2 troubleshooting
# docs/processors/01-phase2-operations-guide.md
```

3. **If Phase 2 Complete → Manually Trigger:**
```bash
gcloud run jobs execute phase3-player-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-14,END_DATE=2025-11-14"
```

4. **Verify Success:**
```sql
SELECT COUNT(*) as rows
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2025-11-14';
-- Expected: 400-500 rows
```

**Timeline:**
- Auto-retry: +6 minutes (3 attempts × 2 min each)
- Manual intervention: +10-30 minutes
- Total delay: ~16-36 minutes (still meets Phase 4 11 PM deadline)

---

### Scenario 2: All Historical Processors Fail (Phase 2 Incomplete)

**Symptoms:**
- All 3 historical processors fail within 10 seconds
- All logs show "dependency check failed"
- No Phase 2 data for yesterday

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| All Phase 3 | ❌ BLOCKED | No source data |
| Phase 4/5 | ❌ BLOCKED | No analytics |

**Detection:**
- Dependency check at start of each processor fails
- Query returns 0 rows for yesterday's game_date

**Recovery:**

1. **Alert on-call immediately (CRITICAL)**

2. **Investigate Phase 2 scraper failures:**
```bash
# Check Phase 2 processor status
# See docs/processors/01-phase2-operations-guide.md

# Query Phase 2 completion
bq query --use_legacy_sql=false "
SELECT
  'nbac_gamebook_player_stats' as table_name,
  COUNT(*) as rows
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date = CURRENT_DATE() - 1

UNION ALL

SELECT 'nbac_team_boxscore', COUNT(*)
FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
WHERE game_date = CURRENT_DATE() - 1
"
```

3. **Fix Phase 2 → Manually trigger Phase 3:**
```bash
# Once Phase 2 complete, trigger Phase 3
gcloud pubsub topics publish phase3-start \
  --message '{"trigger":"manual_recovery","phase":"3","start_date":"2025-11-14","end_date":"2025-11-14"}'
```

**Timeline:**
- Variable (depends on Phase 2 issue)
- May need to skip day if unrecoverable

---

### Scenario 3: Upcoming Team Context Fails

**Symptoms:**
- Query shows < 20 team records for today
- Logs show "schedule not found" or "no games today"

**Impact:**

| Component | Status | Impact |
|-----------|--------|--------|
| Player context | ⚠️ Can still run | Doesn't depend on team context, only uses if available |
| Phase 4 | ⚠️ Reduced quality | Missing team-level fatigue/betting |
| Phase 5 | ⚠️ Reduced confidence | In predictions |

**Recovery:**

1. **Check Schedule Data:**
```sql
-- Verify schedule exists for today
SELECT *
FROM `nba-props-platform.nba_raw.nbac_schedule`
WHERE game_date = CURRENT_DATE()
LIMIT 5;
```

2. **If Schedule Missing → Check Phase 2 Schedule Scraper:**
```bash
# Check recent schedule scraper runs
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers AND textPayload:\"nbac_schedule\"" \
  --limit=20
```

3. **Manually Trigger Team Context:**
```bash
gcloud run jobs execute phase3-upcoming-team-game-context \
  --region us-central1 \
  --set-env-vars "START_DATE=$(date +%Y-%m-%d),END_DATE=$(date +%Y-%m-%d)"
```

4. **Player Context Continues Anyway (Graceful Degradation):**
- Player context will run without team context
- 36 team-level fields will be NULL
- Predictions still possible, slightly reduced accuracy

**Timeline:**
- Auto-retry: +20 minutes (2 retries × 10 min each)
- Manual intervention: +15-30 minutes
- Total delay: ~35-50 minutes

---

### Scenario 4: Upcoming Player Context Fails

**Symptoms:**
- Query shows < 100 players for today
- Logs show "no props available" or "dependency missing"

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| Phase 4 | ❌ BLOCKED | player_composite_factors needs this |
| Phase 5 | ❌ BLOCKED | All prediction models need this |

**This is CRITICAL - blocks all predictions**

**Recovery:**

1. **Check DRIVER Data (Props):**
```sql
-- Player context needs props to know which players to process
SELECT COUNT(DISTINCT player_name) as players_with_props
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date = CURRENT_DATE();
-- Expected: 150-250 players
```

2. **If Props Missing → Check Odds API Scraper:**
```bash
# Check odds API scraper status
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers AND textPayload:\"odds_api\"" \
  --limit=20

# Manually trigger odds scraper
curl -X POST https://[SCRAPER_URL]/scraper/oddsa-player-props
```

3. **Once Props Arrive → Trigger Player Context:**
```bash
gcloud run jobs execute phase3-upcoming-player-game-context \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

4. **Verify Success:**
```sql
SELECT COUNT(*) as players
FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
WHERE game_date = CURRENT_DATE();
-- Expected: 150-250 players
```

**Timeline:**
- Auto-retry: +30 minutes (2 retries × 15 min each)
- Manual intervention: +15-30 minutes
- Total delay: ~45-60 minutes (still meets Phase 4 11 PM deadline)

---

### Scenario 5: Props Data Unavailable

**Symptoms:**
- Upcoming player context fails with "No players to process"
- Query returns 0 players with props

**Impact:**

| Component | Status | Reason |
|-----------|--------|--------|
| Upcoming contexts | ❌ BLOCKED | No players to process without props |
| Phase 4/5 | ❌ BLOCKED | No prediction context |

**Detection:**
- DRIVER query returns 0 players with props
- Dependency check fails for `odds_api_player_points_props`

**Recovery:**

1. **Check Odds API Scraper Status:**
```bash
# Check recent scraper runs
gcloud logging read \
  "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers AND textPayload:\"oddsa-player-props\"" \
  --limit=20 \
  --format=json
```

2. **Common Causes:**
- API key expired/invalid
- Rate limit exceeded
- Odds API down
- Scraper configuration error

3. **Fix Odds Scraper:**
```bash
# Verify API key
# Check Phase 1 orchestration logs

# Manually trigger scraper
curl -X POST https://[SCRAPER_URL]/scraper/oddsa-player-props

# Verify data arrived
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT player_name) FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date = CURRENT_DATE()
"
```

4. **Once Props Available → Trigger Phase 3:**
```bash
# Trigger both upcoming contexts
gcloud pubsub topics publish props-updated \
  --message '{"event_type":"manual_recovery","game_date":"2025-11-15"}'
```

**Timeline:**
- Depends on odds API scraper fix
- Typically 15-60 minutes if scraper restarted
- May need manual intervention if API issues

---

### Scenario 6: Streaming Buffer Conflicts

**Symptoms:**
- Logs show "Cannot delete rows while streaming buffer active"
- Processor retries and eventually succeeds

**Impact:**
- ⚠️ Temporary delay (usually auto-resolves)
- May create temporary duplicate records

**Recovery:**
- **No action needed** - Processor logs warning and continues
- Next run cleans up duplicates automatically
- Duplicates cleared within 24 hours

**Example Log:**
```
WARNING: Streaming buffer active, waiting 60 seconds before DELETE
INFO: Retry successful after streaming buffer cleared
```

**If Persistent:**
```bash
# Check streaming buffer status
bq show --format=json nba_analytics.upcoming_player_game_context | grep streamingBuffer

# Wait 90 seconds for buffer to clear
sleep 90

# Retry manually
gcloud run jobs execute phase3-upcoming-player-game-context \
  --region us-central1 \
  --set-env-vars "GAME_DATE=$(date +%Y-%m-%d)"
```

---

## Manual Recovery Runbook

### Complete Manual Phase 3 Trigger

**Use this when Phase 3 needs to be run manually for a specific date.**

#### Step 1: Verify Phase 2 Complete

```bash
# Check Phase 2 has data for target date
bq query --use_legacy_sql=false "
SELECT
  'nbac_gamebook_player_stats' as table_name,
  COUNT(*) as row_count
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date = '2025-11-15'

UNION ALL

SELECT
  'nbac_team_boxscore',
  COUNT(*)
FROM \`nba-props-platform.nba_raw.nbac_team_boxscore\`
WHERE game_date = '2025-11-15'

UNION ALL

SELECT
  'odds_api_player_points_props',
  COUNT(*)
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date = '2025-11-15'
"
```

**Expected:** All counts > 0

---

#### Step 2: Trigger Historical Processors (Parallel)

**Option A: Via Pub/Sub** (all 3 triggered simultaneously)
```bash
gcloud pubsub topics publish phase3-start \
  --message '{
    "trigger": "manual",
    "phase": "3",
    "trigger_time": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
    "start_date": "2025-11-14",
    "end_date": "2025-11-14",
    "source": "manual"
  }'
```

**Option B: Via Cloud Run Jobs** (trigger each separately)
```bash
# Trigger all 3 in parallel (use & to background)
gcloud run jobs execute phase3-player-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-14,END_DATE=2025-11-14" &

gcloud run jobs execute phase3-team-offense-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-14,END_DATE=2025-11-14" &

gcloud run jobs execute phase3-team-defense-game-summary \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-14,END_DATE=2025-11-14" &

wait  # Wait for all 3 to complete
```

---

#### Step 3: Verify Historical Processing

```bash
# Check which historical processors completed
bq query --use_legacy_sql=false "
SELECT
  'player_game_summary' as processor,
  COUNT(*) as rows,
  MAX(processed_at) as completed_at
FROM \`nba-props-platform.nba_analytics.player_game_summary\`
WHERE game_date = '2025-11-14'

UNION ALL

SELECT
  'team_offense_game_summary',
  COUNT(*),
  MAX(processed_at)
FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`
WHERE game_date = '2025-11-14'

UNION ALL

SELECT
  'team_defense_game_summary',
  COUNT(*),
  MAX(processed_at)
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date = '2025-11-14'
"
```

**Expected:**
- player_game_summary: 400-500 rows
- team_offense_game_summary: 20-30 rows
- team_defense_game_summary: 20-30 rows

---

#### Step 4: Trigger Upcoming Context (Sequential)

```bash
# Trigger team context first
gcloud run jobs execute phase3-upcoming-team-game-context \
  --region us-central1 \
  --set-env-vars "START_DATE=2025-11-15,END_DATE=2025-11-15"

# Wait 30 seconds for team context to complete
sleep 30

# Then trigger player context
gcloud run jobs execute phase3-upcoming-player-game-context \
  --region us-central1 \
  --set-env-vars "GAME_DATE=2025-11-15"
```

---

#### Step 5: Verify Upcoming Context

```bash
# Check final output
bq query --use_legacy_sql=false "
SELECT
  'upcoming_team_game_context' as processor,
  COUNT(*) as rows,
  MAX(processed_at) as completed_at
FROM \`nba-props-platform.nba_analytics.upcoming_team_game_context\`
WHERE game_date = '2025-11-15'

UNION ALL

SELECT
  'upcoming_player_game_context',
  COUNT(*),
  MAX(processed_at)
FROM \`nba-props-platform.nba_analytics.upcoming_player_game_context\`
WHERE game_date = '2025-11-15'
"
```

**Expected:**
- team >= 20 rows
- player >= 100 rows

---

## Retry Strategy

### Processor-Level Retries

| Attribute | Value | Configuration |
|-----------|-------|---------------|
| **Max Retries** | 2 (3 total attempts) | `--max-retries 2` in Cloud Run job |
| **Backoff** | Exponential (5s, 10s, 20s) | Automatic |
| **Timeout** | Per-processor (see specs) | `--timeout` in Cloud Run job |

**Retry Criteria:**
- ✅ Transient errors (network timeouts, BigQuery rate limits)
- ✅ Dependency delays (source not yet available)
- ✅ Data quality issues (validation warnings, not errors)

**Don't Retry:**
- ❌ Missing critical dependencies (immediate fail with clear error)
- ❌ Configuration errors (missing environment variables)
- ❌ Auth errors (insufficient permissions)
- ❌ Schema errors (table not found)

---

### Pub/Sub Message Retries

| Attribute | Value | Configuration |
|-----------|-------|---------------|
| **Max Delivery Attempts** | 3 | `--max-delivery-attempts 3` in subscription |
| **Backoff** | Exponential (10s, 20s, 40s) | Automatic |
| **DLQ** | Move to dead letter queue after 3 failures | `--dead-letter-topic` in subscription |

**Manual Recovery from DLQ:**
```bash
# List messages in DLQ
gcloud pubsub subscriptions pull phase3-player-game-summary-dlq \
  --limit=10 \
  --format=json

# After fixing issue, republish message
gcloud pubsub topics publish phase3-start \
  --message '{"trigger":"manual_retry","phase":"3","start_date":"2025-11-14","end_date":"2025-11-14"}'
```

---

## Alert Configuration

### Slack Alerts (Non-Critical)

**Trigger:**
- Processing time > threshold
- Low data quality (<90%)
- Graceful degradation used (BDL fallback, ESPN fallback)

**Channel:** `#nba-props-alerts`

**Example:**
```
⚠️ Phase 3 Warning: player_game_summary
Duration: 8 seconds (threshold: 10s)
Rows: 445 players
Data Quality: BDL fallback used for 3 games
Date: 2025-01-14
```

---

### PagerDuty Alerts (Critical)

**Trigger:**
- All retries exhausted
- No data for yesterday's games
- Critical dependency missing
- Overall duration > 2 hours
- Upcoming contexts failed (blocks Phase 4/5)

**Escalation:** Immediate page to on-call

**Example:**
```
🚨 CRITICAL: Phase 3 Failure
Processor: upcoming_player_game_context
Error: Missing dependency: nba_raw.odds_api_player_points_props
Retries: 3/3 exhausted
Impact: Blocks Phase 4 player_composite_factors (ALL Phase 5 predictions)
Action Required: Check odds API scraper status
Date: 2025-01-15 06:30 ET
```

---

### Alert Rules

| Rule | Severity | Action |
|------|----------|--------|
| Historical processors all fail | **Critical** | PagerDuty (blocks everything) |
| Any historical processor fails all retries | High | Slack + Page if >1 hour |
| Upcoming team context fails all retries | High | Slack + Page if not resolved by 8 AM |
| Upcoming player context fails all retries | **Critical** | PagerDuty (blocks Phase 4/5) |
| Any processor > 2x max duration | High | Slack |
| Overall Phase 3 duration > 2 hours | **Critical** | PagerDuty |
| No historical data for yesterday | **Critical** | PagerDuty (after 4 AM) |
| No upcoming context for today | **Critical** | PagerDuty (after 8 AM on game day) |

---

## Common Issues

### Issue: "No games scheduled for date"

**Cause:** No NBA games on that date (All-Star break, off-season, etc.)

**Solution:** This is expected behavior, not an error
```bash
# Verify no games scheduled
bq query --use_legacy_sql=false "
SELECT COUNT(*) as games
FROM \`nba-props-platform.nba_raw.nbac_schedule\`
WHERE game_date = '2025-11-14'
"
# If 0, this is normal - no action needed
```

---

### Issue: "Data quality tier = 'low'"

**Cause:** Both primary and fallback sources unavailable

**Solution:** Investigate Phase 2 data sources
```sql
-- Check which sources are available
SELECT
  COUNT(CASE WHEN source = 'nbac_gamebook' THEN 1 END) as gamebook_games,
  COUNT(CASE WHEN source = 'bdl' THEN 1 END) as bdl_games
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2025-11-14';
```

---

### Issue: "Duplicate records in table"

**Cause:** Streaming buffer conflict + retry created duplicates

**Solution:** Auto-clears within 24 hours, or manually delete:
```sql
-- Find duplicates
SELECT
  player_id,
  game_id,
  COUNT(*) as dup_count
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date = '2025-11-14'
GROUP BY player_id, game_id
HAVING COUNT(*) > 1;

-- Deduplication will occur on next run
-- Or manually trigger DELETE + INSERT
```

---

## Related Documentation

**Operations:**
- `02-phase3-operations-guide.md` - Processor specifications and monitoring

**Scheduling:**
- `03-phase3-scheduling-strategy.md` - Cloud Scheduler and Pub/Sub setup

**Infrastructure:**
- `docs/infrastructure/01-pubsub-integration-verification.md` - Pub/Sub testing

**Phase 2 Troubleshooting:**
- `01-phase2-operations-guide.md` - Troubleshooting upstream Phase 2 issues

---

**Last Updated:** 2025-11-15 15:00 PST
**Status:** 🚧 Draft (awaiting deployment)
**Next Review:** After Phase 3 deployment
