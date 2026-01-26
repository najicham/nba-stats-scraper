# 2026-01-26 P0 Incident - Comprehensive TODO List

**Date:** 2026-01-26
**Status:** 🔴 ACTIVE P0 INCIDENT
**Time to Games:** 8 hours (7 PM ET kickoff)
**Critical Window:** 2 hours to fix for pre-game predictions

---

## Executive Summary

**Problem:** Complete pipeline failure for 2026-01-26 - identical to 2026-01-25
- Betting scrapers: 0 records
- Phase 3: 0 records
- No predictions for tonight's 7 games

**Root Cause (Hypothesis):**
- Betting scrapers didn't run OR failed silently
- Phase 3 never triggered OR waiting for Phase 2
- Systemic orchestration trigger issue (2 days in a row = pattern)

**Strategy:**
1. Investigation (30 min) - Understand what failed
2. Emergency Fix (30 min) - Manual triggers if needed
3. Validation (15 min) - Verify recovery
4. Root Cause (60 min) - Why repeat failure
5. Prevention (60 min) - Monitoring to catch earlier

---

## Task Organization

### 🔴 Phase 1: INVESTIGATION (Parallel - 30 min total)
**Goal:** Understand what failed and why

**Tasks to run IN PARALLEL:**
- Task #1: Investigate betting scraper failures ⏱️ 20 min
- Task #2: Check if scrapers were triggered ⏱️ 15 min
- Task #3: Verify Pub/Sub trigger chain ⏱️ 15 min
- Task #4: Check Phase 3 processor status ⏱️ 15 min

**Decision Point After Phase 1:**
```
IF scrapers didn't run → Manual trigger (Task #5)
IF scrapers ran but failed → Fix scraper issue then trigger
IF Phase 3 didn't run → Manual trigger (Task #6)
IF Phase 3 ran but failed → Fix processor issue then trigger
```

---

### 🟠 Phase 2: EMERGENCY FIX (Sequential - 40 min total)
**Goal:** Get data flowing for tonight's games

**Task #5: Manual trigger betting scrapers** ⏱️ 20 min
- **When:** If scrapers didn't run or failed
- **Action:** Force execution of odds_api scrapers
- **Validation:** Check BigQuery for records
- **Success:** 200-300 props, ~70 lines

**Task #6: Manual trigger Phase 3 processors** ⏱️ 20 min
- **When:** After Task #5 complete AND Phase 3 didn't run
- **Action:** Force execution of analytics processors
- **Validation:** Check BigQuery for records
- **Success:** 200-300 players, 14 teams

---

### 🟢 Phase 3: VALIDATION (Sequential - 20 min total)
**Goal:** Verify recovery and data quality

**Task #7: Validate betting data** ⏱️ 10 min
- **When:** After Task #5 complete
- **Check:** Record counts, data quality, game coverage
- **Success:** All 7 games have props and lines

**Task #8: Validate Phase 3 analytics** ⏱️ 10 min
- **When:** After Task #6 complete
- **Check:** Record counts, has_prop_line flags, GSW players
- **Success:** All 14 teams, 200-300 players

**Exit Criteria for Phase 3:**
- ✅ Betting data populated
- ✅ Game context populated
- ✅ Re-run validation script shows PASS
- ✅ API exports show 2026-01-26 date

---

### 🔵 Phase 4: ROOT CAUSE ANALYSIS (Parallel - 60 min total)
**Goal:** Understand why this happened again

**Task #9: Why 2026-01-25 fix didn't prevent this** ⏱️ 30 min
- **When:** Can run during/after Phase 2
- **Focus:** Review yesterday's remediation
- **Output:** Document gaps in previous fix

**Task #10: Check orchestration system health** ⏱️ 30 min
- **When:** Can run during/after Phase 2
- **Focus:** Systemic trigger issues
- **Output:** Identify infrastructure problems

---

### 🟣 Phase 5: DOCUMENTATION & PREVENTION (Sequential - 75 min total)
**Goal:** Document and prevent future occurrences

**Task #11: Document findings** ⏱️ 30 min
- **When:** After root cause clear
- **Output:** Incident report with timeline
- **Include:** What failed, why, how fixed, prevention

**Task #12: Implement monitoring** ⏱️ 45 min
- **When:** After immediate crisis resolved
- **Output:** Alerts to catch this earlier
- **Focus:** Early warning system for cascade failures

---

## Detailed Task Breakdown

### Task #1: Investigate Betting Scraper Failures
**Priority:** P0 - BLOCKER
**Time:** 20 minutes
**Dependencies:** None

**Investigation Steps:**

1. **Check if data exists in raw tables:**
   ```sql
   -- Check odds_api_player_points_props
   SELECT COUNT(*) as record_count,
          MIN(created_at) as first_record,
          MAX(created_at) as last_record
   FROM nba_raw.odds_api_player_points_props
   WHERE game_date = '2026-01-26';

   -- Check odds_api_game_lines
   SELECT COUNT(*) as record_count,
          MIN(created_at) as first_record,
          MAX(created_at) as last_record
   FROM nba_raw.odds_api_game_lines
   WHERE game_date = '2026-01-26';
   ```

2. **Check scraper execution logs:**
   ```bash
   # Player props scraper
   gcloud logging read \
     'resource.type=cloud_run_revision
      AND resource.labels.service_name=odds-api-player-props-scraper
      AND timestamp>="2026-01-26T00:00:00Z"' \
     --limit 100 --format json

   # Game lines scraper
   gcloud logging read \
     'resource.type=cloud_run_revision
      AND resource.labels.service_name=odds-api-game-lines-scraper
      AND timestamp>="2026-01-26T00:00:00Z"' \
     --limit 100 --format json
   ```

3. **Check for error patterns:**
   - API key errors (401, 403)
   - Rate limiting (429)
   - Timeout errors
   - Network errors
   - Empty responses

4. **Check API health:**
   ```bash
   # Test Odds API manually
   curl -I https://api.the-odds-api.com/v4/sports/basketball_nba/odds
   ```

**Expected Findings:**
- IF no logs → Scraper never ran (go to Task #2)
- IF logs show errors → Identify error type for fixing
- IF logs show success but 0 records → Data source issue

---

### Task #2: Check If Scrapers Were Triggered
**Priority:** P0 - BLOCKER
**Time:** 15 minutes
**Dependencies:** None

**Investigation Steps:**

1. **Check Cloud Scheduler jobs:**
   ```bash
   # List all scheduler jobs
   gcloud scheduler jobs list --filter="nba" --format="table(name,schedule,state,lastAttemptTime)"

   # Check specific scraper jobs
   gcloud scheduler jobs describe odds-api-player-props-daily
   gcloud scheduler jobs describe odds-api-game-lines-daily
   ```

2. **Check Pub/Sub trigger messages:**
   ```bash
   # Check if trigger messages were published
   gcloud pubsub topics list --filter="odds-api"

   # Check message publish logs
   gcloud logging read \
     'resource.type=pubsub_topic
      AND timestamp>="2026-01-26T00:00:00Z"
      AND (resource.labels.topic_id="odds-api-player-props-trigger"
           OR resource.labels.topic_id="odds-api-game-lines-trigger")' \
     --limit 50
   ```

3. **Check orchestration controller logs:**
   ```bash
   # Check master controller
   gcloud logging read \
     'resource.labels.service_name=nba-orchestration-controller
      AND timestamp>="2026-01-26T00:00:00Z"
      AND ("odds-api" OR "betting")' \
     --limit 100
   ```

**Expected Findings:**
- IF scheduler jobs disabled → Re-enable
- IF scheduler ran but no Pub/Sub → Pub/Sub issue
- IF Pub/Sub message sent but scraper didn't run → Cloud Run issue

---

### Task #3: Verify Phase 2 → Phase 3 Pub/Sub Chain
**Priority:** P0 - BLOCKER
**Time:** 15 minutes
**Dependencies:** None

**Investigation Steps:**

1. **Check Phase 2 completion topic:**
   ```bash
   # Check if completion message was published
   gcloud pubsub topics describe nba-phase2-raw-complete

   # Check recent publishes
   gcloud logging read \
     'resource.type=pubsub_topic
      AND resource.labels.topic_id="nba-phase2-raw-complete"
      AND timestamp>="2026-01-26T00:00:00Z"' \
     --limit 50
   ```

2. **Check Phase 3 subscription:**
   ```bash
   # Check subscription health
   gcloud pubsub subscriptions describe nba-phase3-analytics-sub

   # Check for undelivered messages
   gcloud pubsub subscriptions pull nba-phase3-analytics-sub \
     --limit=10 --auto-ack=false

   # Check dead letter queue
   gcloud pubsub subscriptions pull nba-phase3-analytics-dlq \
     --limit=10 --auto-ack=false
   ```

3. **Check message delivery logs:**
   ```bash
   gcloud logging read \
     'resource.type=pubsub_subscription
      AND resource.labels.subscription_id="nba-phase3-analytics-sub"
      AND timestamp>="2026-01-26T00:00:00Z"' \
     --limit 50
   ```

**Expected Findings:**
- IF no Phase 2 completion message → Phase 2 not complete (check Task #1)
- IF message published but not delivered → Subscription issue
- IF message in dead letter queue → Delivery failed, check why

---

### Task #4: Check Phase 3 Processor Execution Status
**Priority:** P0 - BLOCKER
**Time:** 15 minutes
**Dependencies:** None

**Investigation Steps:**

1. **Check processor run logs:**
   ```bash
   # upcoming_player_game_context processor
   gcloud logging read \
     'resource.labels.service_name=upcoming-player-game-context-processor
      AND timestamp>="2026-01-26T00:00:00Z"' \
     --limit 100 --format json

   # upcoming_team_game_context processor
   gcloud logging read \
     'resource.labels.service_name=upcoming-team-game-context-processor
      AND timestamp>="2026-01-26T00:00:00Z"' \
     --limit 100 --format json
   ```

2. **Check pipeline event log:**
   ```sql
   SELECT
     event_type,
     processor_name,
     event_timestamp,
     status,
     error_message
   FROM nba_orchestration.pipeline_event_log
   WHERE DATE(event_timestamp) = '2026-01-26'
     AND processor_name IN ('upcoming_player_game_context', 'upcoming_team_game_context')
   ORDER BY event_timestamp DESC
   LIMIT 50;
   ```

3. **Check circuit breaker status:**
   ```sql
   SELECT
     table_name,
     is_breaker_open,
     failure_count,
     last_failure_time,
     breaker_opened_at
   FROM nba_orchestration.circuit_breaker_status
   WHERE table_name IN ('upcoming_player_game_context', 'upcoming_team_game_context');
   ```

**Expected Findings:**
- IF no logs → Processors never ran (Pub/Sub issue)
- IF logs show errors → Identify error for fixing
- IF circuit breaker open → Override and retry

---

### Task #5: Manual Trigger Betting Scrapers
**Priority:** P0 - IMMEDIATE
**Time:** 20 minutes
**Dependencies:** Task #1, #2 complete

**Execution Steps:**

1. **Locate manual trigger scripts:**
   ```bash
   # Check for manual trigger utilities
   ls orchestration/manual_triggers/
   ls scripts/manual_scraper_trigger.py
   ```

2. **Trigger player props scraper:**
   ```bash
   # Method 1: Direct script
   python orchestration/manual_trigger.py \
     --scraper odds_api_player_points_props \
     --date 2026-01-26 \
     --verbose

   # Method 2: Cloud Run direct invoke
   gcloud run services invoke odds-api-player-props-scraper \
     --platform managed \
     --region us-west2 \
     --headers "X-Game-Date: 2026-01-26"
   ```

3. **Trigger game lines scraper:**
   ```bash
   python orchestration/manual_trigger.py \
     --scraper odds_api_game_lines \
     --date 2026-01-26 \
     --verbose
   ```

4. **Monitor execution:**
   ```bash
   # Watch logs in real-time
   gcloud logging tail \
     'resource.labels.service_name=odds-api-player-props-scraper' \
     --format=json

   # Check for completion
   watch -n 5 'bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_raw.odds_api_player_points_props WHERE game_date = \"2026-01-26\""'
   ```

5. **Validate results:**
   - See Task #7 for validation queries

**Success Criteria:**
- ✅ Scraper logs show successful execution
- ✅ No error messages in logs
- ✅ Records appear in BigQuery within 5 minutes
- ✅ Record counts in expected range (200-300 props, ~70 lines)

---

### Task #6: Manual Trigger Phase 3 Processors
**Priority:** P0 - IMMEDIATE
**Time:** 20 minutes
**Dependencies:** Task #5 complete, betting data validated

**Execution Steps:**

1. **Locate processor trigger scripts:**
   ```bash
   # Check for processor triggers
   ls data_processors/analytics/upcoming_player_game_context/trigger.py
   ls orchestration/manual_trigger_phase3.py
   ```

2. **Trigger player context processor:**
   ```bash
   # Method 1: Direct processor script
   python -m data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor \
     2026-01-26 \
     --skip-downstream-trigger

   # Method 2: Via orchestration script
   python orchestration/manual_trigger_phase3.py \
     --processor upcoming_player_game_context \
     --date 2026-01-26
   ```

3. **Trigger team context processor:**
   ```bash
   python -m data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor \
     2026-01-26 \
     --skip-downstream-trigger
   ```

4. **Monitor execution:**
   ```bash
   # Watch processor logs
   gcloud logging tail \
     'resource.labels.service_name=upcoming-player-game-context-processor' \
     --format=json

   # Check for records
   watch -n 5 'bq query --use_legacy_sql=false "SELECT COUNT(*) FROM nba_analytics.upcoming_player_game_context WHERE game_date = \"2026-01-26\""'
   ```

5. **Check for errors:**
   - Circuit breaker blocking?
   - Missing dependencies?
   - Data quality issues?

**Success Criteria:**
- ✅ Processor logs show successful execution
- ✅ No error messages or warnings
- ✅ Records appear in BigQuery
- ✅ Record counts match expectations (200-300 players, 14 teams)

---

### Task #7: Validate Betting Data
**Priority:** P0 - VALIDATION
**Time:** 10 minutes
**Dependencies:** Task #5 complete

**Validation Queries:**

```sql
-- 1. Check player props count
SELECT
  COUNT(*) as total_props,
  COUNT(DISTINCT player_name) as unique_players,
  COUNT(DISTINCT game_id) as unique_games,
  MIN(created_at) as first_record,
  MAX(created_at) as last_record
FROM nba_raw.odds_api_player_points_props
WHERE game_date = '2026-01-26';
-- Expected: 200-300 props, 7 games

-- 2. Check game lines count
SELECT
  COUNT(*) as total_lines,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT bookmaker) as unique_bookmakers
FROM nba_raw.odds_api_game_lines
WHERE game_date = '2026-01-26';
-- Expected: ~70 lines, 7 games, ~10 bookmakers

-- 3. Check game coverage
SELECT
  game_id,
  COUNT(*) as prop_count
FROM nba_raw.odds_api_player_points_props
WHERE game_date = '2026-01-26'
GROUP BY game_id
ORDER BY game_id;
-- Expected: All 7 games present

-- 4. Check data quality
SELECT
  player_name,
  bookmaker,
  points_over_under,
  over_price,
  under_price
FROM nba_raw.odds_api_player_points_props
WHERE game_date = '2026-01-26'
LIMIT 10;
-- Expected: Reasonable values, no NULLs in critical fields
```

**Pass Criteria:**
- ✅ Total props >= 200
- ✅ All 7 games have props
- ✅ Major bookmakers present (DraftKings, FanDuel, etc.)
- ✅ Odds values are reasonable (e.g., -110 to +110 range)
- ✅ No obvious data quality issues

---

### Task #8: Validate Phase 3 Game Context
**Priority:** P0 - VALIDATION
**Time:** 10 minutes
**Dependencies:** Task #6 complete

**Validation Queries:**

```sql
-- 1. Check player context count
SELECT
  COUNT(*) as total_players,
  COUNT(DISTINCT player_id) as unique_players,
  COUNT(DISTINCT game_id) as unique_games,
  SUM(CASE WHEN has_prop_line THEN 1 ELSE 0 END) as players_with_props,
  SUM(CASE WHEN NOT has_prop_line THEN 1 ELSE 0 END) as players_without_props
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-26';
-- Expected: 200-300 total, 7 games, some with props some without

-- 2. Check team context count
SELECT
  COUNT(*) as total_teams,
  COUNT(DISTINCT game_id) as unique_games,
  COUNT(DISTINCT team_abbr) as unique_teams
FROM nba_analytics.upcoming_team_game_context
WHERE game_date = '2026-01-26';
-- Expected: 14 records (2 per game), 7 games, 14 teams

-- 3. Check GSW specifically (known issue from 2026-01-25)
SELECT
  COUNT(*) as gsw_player_count,
  STRING_AGG(player_name, ', ') as players
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-26'
  AND team_abbr = 'GSW';
-- Expected: ~17 GSW players

-- 4. Check data quality
SELECT
  player_name,
  team_abbr,
  opponent_abbr,
  has_prop_line,
  season_avg_points,
  last_5_avg_points
FROM nba_analytics.upcoming_player_game_context
WHERE game_date = '2026-01-26'
LIMIT 20;
-- Expected: Reasonable stats, no critical NULLs
```

**Pass Criteria:**
- ✅ Total players >= 200
- ✅ All 14 teams present (7 games × 2 teams)
- ✅ GSW players present (not 0 like yesterday)
- ✅ has_prop_line flags correctly set
- ✅ Stats look reasonable (no obvious data issues)

---

### Task #9: Why 2026-01-25 Remediation Didn't Prevent This
**Priority:** P1 - ROOT CAUSE
**Time:** 30 minutes
**Dependencies:** Can run in parallel with Phase 2

**Investigation Steps:**

1. **Review 2026-01-25 incident docs:**
   ```bash
   # Read remediation reports
   cat docs/incidents/2026-01-25-REMEDIATION-COMPLETION-REPORT.md
   cat docs/incidents/2026-01-25-ACTION-3-REMEDIATION-REPORT.md
   cat docs/08-projects/current/2026-01-25-incident-remediation/STATUS.md
   ```

2. **Compare failure patterns:**
   ```sql
   -- 2026-01-25 data
   SELECT
     'player_props' as source,
     COUNT(*) as record_count
   FROM nba_raw.odds_api_player_points_props
   WHERE game_date = '2026-01-25'
   UNION ALL
   SELECT
     'game_lines' as source,
     COUNT(*) as record_count
   FROM nba_raw.odds_api_game_lines
   WHERE game_date = '2026-01-25'
   UNION ALL
   -- 2026-01-26 data
   SELECT
     'player_props' as source,
     COUNT(*) as record_count
   FROM nba_raw.odds_api_player_points_props
   WHERE game_date = '2026-01-26'
   UNION ALL
   SELECT
     'game_lines' as source,
     COUNT(*) as record_count
   FROM nba_raw.odds_api_game_lines
   WHERE game_date = '2026-01-26';
   ```

3. **Check what was "fixed" yesterday:**
   - GSW/SAC player extraction bug → Fixed JOIN condition
   - Table ID duplication → Fixed table_name
   - Schema mismatch → Added 4 fields
   - Return value bug → Fixed boolean return
   - **MISSING:** Betting scraper issues?

4. **Check if fixes were deployed:**
   ```bash
   # Check recent commits
   git log --since="2026-01-25" --oneline

   # Check if processors deployed
   gcloud run services describe upcoming-player-game-context-processor \
     --region us-west2 \
     --format="value(metadata.annotations.deployed_at)"
   ```

**Key Questions:**
- Did yesterday's incident involve betting scrapers failing?
- Was betting scraper issue identified but not fixed?
- Were all fixes actually deployed to production?
- Is there a common root cause we missed?

**Expected Output:**
- Document what was fixed vs what should have been fixed
- Identify gaps in 2026-01-25 remediation
- Determine if betting scrapers were working yesterday

---

### Task #10: Check Orchestration Trigger System Health
**Priority:** P1 - SYSTEMIC
**Time:** 30 minutes
**Dependencies:** Can run in parallel with Phase 2

**Investigation Steps:**

1. **Check Cloud Scheduler success rates:**
   ```bash
   # Get all scheduler job statuses for past week
   for job in $(gcloud scheduler jobs list --format="value(name)" | grep nba); do
     echo "=== $job ==="
     gcloud logging read \
       "resource.type=cloud_scheduler_job
        AND resource.labels.job_id=$job
        AND timestamp>=\"2026-01-20T00:00:00Z\"" \
       --limit 50 --format="table(timestamp,protoPayload.status.message)"
   done
   ```

2. **Check Pub/Sub delivery metrics:**
   ```bash
   # Check topic publish rates
   gcloud pubsub topics list --filter="nba" \
     --format="table(name,publishMessageCount,publishMessageErrorCount)"

   # Check subscription delivery rates
   gcloud pubsub subscriptions list --filter="nba" \
     --format="table(name,numUndeliveredMessages,oldestUnackedMessageAge)"
   ```

3. **Check phase completion patterns:**
   ```sql
   -- Phase completion events past 7 days
   SELECT
     DATE(event_timestamp) as event_date,
     phase,
     COUNT(*) as completion_count,
     COUNT(DISTINCT processor_name) as unique_processors
   FROM nba_orchestration.pipeline_event_log
   WHERE event_type = 'phase_complete'
     AND event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
   GROUP BY event_date, phase
   ORDER BY event_date DESC, phase;
   ```

4. **Check circuit breaker states:**
   ```sql
   -- Circuit breakers that are open
   SELECT
     table_name,
     is_breaker_open,
     failure_count,
     last_failure_time,
     last_failure_reason,
     breaker_opened_at
   FROM nba_orchestration.circuit_breaker_status
   WHERE is_breaker_open = TRUE
   ORDER BY breaker_opened_at DESC;
   ```

5. **Check recent code changes:**
   ```bash
   # Check orchestration-related commits past week
   git log --since="2026-01-20" --grep="orchestration" --oneline
   git log --since="2026-01-20" --grep="trigger" --oneline
   git log --since="2026-01-20" --grep="pubsub" --oneline
   ```

**Expected Findings:**
- Scheduler success rate past 7 days
- Any systematic Pub/Sub delivery issues
- Pattern of phase completion failures
- Recent code changes that might have broken triggers

---

### Task #11: Document Findings and Create Incident Report
**Priority:** P2 - DOCUMENTATION
**Time:** 30 minutes
**Dependencies:** Tasks #1-10 complete

**Report Structure:**

```markdown
# 2026-01-26 Pipeline Failure - Incident Report

## Timeline
- 6:00 AM: Phase 5 predictions ran, found 0 features
- 10:20 AM: Validation discovered failure
- [Your timeline of investigation and fixes]

## Root Cause
- Primary: [What actually failed]
- Secondary: [Contributing factors]
- Systemic: [Why it happened 2 days in a row]

## What Failed
- Betting scrapers: [Status and why]
- Phase 3 processors: [Status and why]
- Trigger chain: [Any issues found]

## Why 2026-01-25 Fix Didn't Prevent This
- [What was fixed yesterday]
- [What was missed]
- [Why repeat failure occurred]

## Immediate Fixes Applied
- [Manual triggers used]
- [Data validated]
- [Pipeline recovered]

## Permanent Fixes Needed
- [Scraper reliability improvements]
- [Trigger chain hardening]
- [Monitoring additions]

## Prevention Measures
- [Early detection alerts]
- [Automatic recovery mechanisms]
- [Systematic testing]
```

**Output Location:**
- `docs/incidents/2026-01-26-PIPELINE-FAILURE-INCIDENT-REPORT.md`

---

### Task #12: Implement Monitoring to Detect This Earlier
**Priority:** P2 - PREVENTION
**Time:** 45 minutes
**Dependencies:** Incident resolved

**Monitoring to Add:**

1. **Phase 2 Betting Data Alert:**
   ```python
   # Alert if betting scrapers return 0 records by 10 AM
   # Location: orchestration/monitors/betting_data_monitor.py

   def check_betting_data_present():
       # Check odds_api tables for today
       # If count = 0 AND time > 10:00 AM → Alert
       pass
   ```

2. **Phase 3 Analytics Alert:**
   ```python
   # Alert if Phase 3 has 0 records by 11 AM
   # Location: orchestration/monitors/analytics_monitor.py

   def check_analytics_present():
       # Check upcoming_player_game_context for today
       # If count = 0 AND time > 11:00 AM → Alert
       pass
   ```

3. **Repeat Failure Pattern Alert:**
   ```python
   # Alert on 2+ consecutive days of same failure
   # Location: orchestration/monitors/pattern_detector.py

   def check_repeat_failure():
       # Query last 2 days
       # If same failure pattern → Critical alert
       pass
   ```

4. **Dashboard Widget:**
   ```sql
   -- Add to monitoring dashboard
   -- Shows Phase 2 scraper success by date
   SELECT
     DATE(created_at) as date,
     COUNT(*) as records,
     COUNT(DISTINCT game_date) as games
   FROM nba_raw.odds_api_player_points_props
   WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
   GROUP BY date
   ORDER BY date DESC;
   ```

5. **Slack Notification Setup:**
   ```python
   # Send critical alerts to #nba-pipeline-alerts
   # Severity levels:
   # - P0: Immediate (betting data 0 at 10 AM)
   # - P1: Soon (Phase 3 0 at 11 AM)
   # - P2: Pattern (2+ day repeat failure)
   ```

**Implementation Steps:**
1. Create monitor scripts in orchestration/monitors/
2. Add to Cloud Scheduler (run hourly 9 AM - 12 PM)
3. Configure Slack webhook integration
4. Add dashboard widgets
5. Test with simulated failures
6. Document monitoring system in runbooks

---

## Execution Order

### Critical Path (Must complete before games):
```
Start (Now)
    ↓
Phase 1: Investigation (30 min - PARALLEL)
├── Task #1: Betting scrapers ⏱️ 20 min
├── Task #2: Scraper triggers ⏱️ 15 min
├── Task #3: Pub/Sub chain ⏱️ 15 min
└── Task #4: Phase 3 status ⏱️ 15 min
    ↓
Decision Point: What needs manual trigger?
    ↓
Phase 2: Emergency Fix (40 min - SEQUENTIAL)
├── Task #5: Trigger betting scrapers ⏱️ 20 min
└── Task #6: Trigger Phase 3 ⏱️ 20 min
    ↓
Phase 3: Validation (20 min - SEQUENTIAL)
├── Task #7: Validate betting data ⏱️ 10 min
└── Task #8: Validate Phase 3 ⏱️ 10 min
    ↓
✅ CRISIS RESOLVED (90 min total)
    ↓
Games Start (7 PM ET)
```

### Post-Crisis Analysis (Can do later):
```
Phase 4: Root Cause (60 min - PARALLEL)
├── Task #9: Why repeat failure ⏱️ 30 min
└── Task #10: Orchestration health ⏱️ 30 min
    ↓
Phase 5: Documentation (75 min - SEQUENTIAL)
├── Task #11: Incident report ⏱️ 30 min
└── Task #12: Monitoring ⏱️ 45 min
    ↓
✅ INCIDENT COMPLETE
```

---

## Success Criteria

### Immediate Success (Before Games):
- ✅ Betting data: 200-300 props, ~70 lines
- ✅ Player context: 200-300 records
- ✅ Team context: 14 records
- ✅ GSW players present (not 0)
- ✅ Validation script passes
- ✅ API exports show 2026-01-26

### Root Cause Success (Post-Crisis):
- ✅ Understand why betting scrapers failed
- ✅ Understand why Phase 3 didn't run
- ✅ Understand why 2 days in a row
- ✅ Document gaps in 2026-01-25 fix
- ✅ Identify systemic issues

### Prevention Success (Long-term):
- ✅ Monitoring alerts on scraper failure
- ✅ Monitoring alerts on Phase 3 failure
- ✅ Pattern detection for repeat failures
- ✅ Dashboard shows pipeline health
- ✅ Automated recovery where possible

---

## Time Budget

**Critical Path (Must do now):**
- Investigation: 30 min
- Emergency fix: 40 min
- Validation: 20 min
- **Total: 90 minutes**

**Post-Crisis (Can do later):**
- Root cause: 60 min
- Documentation: 30 min
- Monitoring: 45 min
- **Total: 135 minutes**

**Grand Total: ~4 hours**

---

## Next Action

**START HERE:**

Begin Phase 1 tasks IN PARALLEL:
```bash
# Terminal 1: Betting scrapers
# Run Task #1

# Terminal 2: Scraper triggers
# Run Task #2

# Terminal 3: Pub/Sub chain
# Run Task #3

# Terminal 4: Phase 3 status
# Run Task #4
```

After 30 minutes, reconvene with findings and proceed to Phase 2 based on what failed.

---

**Document Status:** Ready for execution
**Next Update:** After Phase 1 complete
**Owner:** Incident Response Team
