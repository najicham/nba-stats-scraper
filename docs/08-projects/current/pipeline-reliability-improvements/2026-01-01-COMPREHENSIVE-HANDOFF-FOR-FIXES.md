# COMPREHENSIVE HANDOFF - January 1, 2026 (Ready to Fix)

**Session Status**: 🟢 INVESTIGATION COMPLETE - Ready for Implementation
**Time**: 2026-01-01 15:45 ET
**Context Analyzed**: 6.5M tokens across 5 parallel agents
**Current State**: System operational but multiple critical issues identified
**Next Action**: Start implementing fixes in priority order

---

## 🎯 MISSION FOR NEW CHAT

You are taking over after a **massive 3-hour deep-dive investigation** that analyzed the entire NBA stats pipeline. We found:
- ✅ **5 critical issues** - All root causes identified
- 🚨 **8 hidden issues** - Systematic scan revealed monitoring blind spots
- 📋 **Complete fix plan** - Step-by-step instructions ready
- 🎮 **5 games tonight** - System is working but needs fixes before evening

**YOUR MAIN OBJECTIVES:**
1. **Fix all critical issues** in priority order (list below)
2. **Test each fix** thoroughly before moving to next
3. **Update documentation** in `/docs/08-projects/current/pipeline-reliability-improvements/` after each fix
4. **Create git commits** with proper messages for each logical group of fixes
5. **Validate system health** after all fixes complete

---

## 📚 INVESTIGATION ARTIFACTS

**All findings documented here:**

### **Primary Documentation** (START HERE)
1. **`2026-01-01-MASTER-FINDINGS-AND-FIX-PLAN.md`** ← **READ THIS FIRST**
   - Complete agent findings summary
   - All 13 issues with root causes
   - Prioritized fix checklist
   - Testing procedures

2. **`PIPELINE_SCAN_REPORT_2026-01-01.md`** (at project root)
   - Hidden issues deep scan
   - 8 critical findings missed by monitoring
   - Injuries data 41 days stale!
   - Systematic failure patterns

3. **`2026-01-01-DAILY-VALIDATION-INVESTIGATION.md`**
   - Initial validation results
   - Daily orchestration status
   - Error log analysis

### **Agent Investigation Outputs**
- **Agent 1**: PlayerGameSummaryProcessor DataFrame error (SOLVED)
- **Agent 2**: Team processors 5-day stoppage (ROOT CAUSE FOUND)
- **Agent 3**: Coordinator deployment failures (RESOLVED)
- **Agent 4**: Hidden pipeline issues scan (8 CRITICAL ISSUES)
- **Agent 5**: Orchestration tracking divergence (EXPLAINED)

---

## 🔥 CRITICAL ISSUES - FIX IN THIS ORDER

### **PRIORITY 1: QUICK WINS (Before Tonight's Games)**

#### **Issue 1.1: PlayerGameSummaryProcessor Fix** ⚡
**Time**: 5 minutes
**Impact**: 40% failure rate → 0%, unblocks Phase 3 completion

**The Bug:**
```python
# File: data_processors/analytics/player_game_summary/player_game_summary_processor.py
# Line 309

# CURRENT (BROKEN):
if skip:
    logger.info(f"SMART REPROCESSING: Skipping processing - {reason}")
    self.raw_data = []  # ❌ BUG: Sets list instead of DataFrame
    return

# Later at line 736:
if self.raw_data.empty:  # ❌ CRASH: Tries to call .empty on a list!
    return
```

**The Fix:**
```python
# Change line 309 FROM:
self.raw_data = []

# TO:
self.raw_data = pd.DataFrame()
```

**Implementation Steps:**
1. Read the file to verify current state
2. Use Edit tool to change line 309
3. Test the fix:
```bash
PYTHONPATH=. python3 -m data_processors.analytics.player_game_summary.player_game_summary_processor \
  --start-date 2025-12-31 --end-date 2025-12-31
# Should complete without AttributeError
```
4. Verify in BigQuery:
```sql
SELECT COUNT(*)
FROM nba_analytics.player_game_summary
WHERE game_date = '2025-12-31'
-- Should see records if fix worked
```

**Git Commit:**
```bash
git add data_processors/analytics/player_game_summary/player_game_summary_processor.py
git commit -m "fix: PlayerGameSummaryProcessor DataFrame type error

Smart reprocessing feature was setting self.raw_data to empty list []
but validation expects DataFrame and calls .empty attribute.

This caused 40% failure rate (4 of 10 runs) when skip logic triggered.

Fix: Change line 309 to use pd.DataFrame() instead of []

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**Deploy:**
```bash
./bin/analytics/deploy/deploy_analytics_processors.sh
```

---

#### **Issue 1.2: Data Completeness Checker Deployment** ⚡
**Time**: 15 minutes
**Impact**: Restores monitoring visibility

**Current State:**
- New function code exists in `functions/monitoring/data_completeness_checker/`
- Files are UNTRACKED (not in git)
- Function is deployed but using OLD version that imports from 'shared' (doesn't exist in Cloud Function)

**The Fix:**
Deploy the updated version that uses boto3 directly:

```bash
cd functions/monitoring/data_completeness_checker

gcloud functions deploy data-completeness-checker \
  --gen2 \
  --runtime=python312 \
  --region=us-west2 \
  --source=. \
  --entry-point=check_completeness \
  --trigger-http \
  --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform" \
  --timeout=540s \
  --memory=512Mi
```

**Test:**
```bash
# Test function
FUNCTION_URL=$(gcloud functions describe data-completeness-checker \
  --region=us-west2 --gen2 --format="value(serviceConfig.uri)")

curl $FUNCTION_URL
# Should return JSON with check results, no ModuleNotFoundError
```

**Git Commit:**
```bash
git add functions/monitoring/data_completeness_checker/
git commit -m "feat: Add data completeness monitoring Cloud Function

Daily check for missing games by comparing NBA schedule against:
- Gamebook player stats
- BDL player boxscores

Sends email alerts when games are missing or incomplete.
Logs results to nba_orchestration.data_completeness_checks table.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### **PRIORITY 2: URGENT DATA GAPS**

#### **Issue 2.1: Injuries Data Emergency** 🚨
**Time**: 1-2 hours
**Impact**: **41 DAYS STALE** - Users making decisions on Nov 21 data!

**Current State:**
```
Table: nba_raw.bdl_injuries
Last Updated: 2025-11-21 19:34:35
Staleness: 985 hours (41 DAYS!)
Workflow: injury_discovery failing 11/60 times in last 7 days
```

**Investigation Steps:**

1. **Check BDL Injuries API:**
```bash
# Test if API is working
curl -H "Authorization: $(gcloud secrets versions access latest --secret='BALLDONTLIE_API_KEY')" \
  "https://api.balldontlie.io/v1/injuries"
# If returns 401/403: API key issue
# If returns 404: Endpoint changed
# If returns data: API working, scraper broken
```

2. **Check NBA.com Injury Report Scraper:**
```bash
gcloud logging read \
  'resource.labels.service_name="nba-phase1-scrapers" AND textPayload=~"nbac_injury_report" AND severity>=ERROR' \
  --limit=10 --freshness=7d
```

3. **Check Workflow Execution:**
```sql
SELECT
  execution_time,
  workflow_name,
  status,
  scrapers_requested,
  scrapers_succeeded,
  scrapers_failed
FROM `nba_orchestration.workflow_executions`
WHERE workflow_name = 'injury_discovery'
  AND execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY execution_time DESC
LIMIT 20
```

**Potential Fixes:**

**If API key expired:**
```bash
# Update secret (get new key from BDL dashboard)
echo -n "NEW_API_KEY" | gcloud secrets versions add BALLDONTLIE_API_KEY --data-file=-
```

**If API endpoint changed:**
- Check BDL API documentation
- Update scraper code to new endpoint
- Redeploy Phase 1 scrapers

**If scraper code broken:**
- Read `scrapers/balldontlie/injuries_scraper.py`
- Check recent changes with `git log`
- Fix bug and redeploy

**Manual Backfill (if API working):**
```bash
# Backfill 41 days of missing data
PYTHONPATH=. python3 scripts/backfill_injuries.py \
  --start-date 2025-11-22 \
  --end-date 2026-01-01
```

**Git Commit After Fix:**
```bash
git add scrapers/balldontlie/injuries_scraper.py  # or whatever files changed
git commit -m "fix: Restore injuries data scraper

Injuries data was stale for 41 days (last update: Nov 21, 2025).

Root cause: [DESCRIBE WHAT YOU FOUND]
Fix: [DESCRIBE YOUR FIX]

Backfilled data from 2025-11-22 to 2026-01-01.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

#### **Issue 2.2: Team Boxscore Missing Data** 🔍
**Time**: 2-3 hours
**Impact**: 5 days of team analytics missing (12/27-12/31)

**Current State:**
```
Table: nba_raw.nbac_team_boxscore
Data exists for: 2025-12-26 (2 rows)
Missing: 2025-12-27, 12-28, 12-29, 12-30, 12-31 (0 rows!)

Affected Processors:
- TeamDefenseGameSummaryProcessor (last ran 12/26)
- UpcomingTeamGameContextProcessor (last ran 12/26)

Missing Output Tables:
- team_defense_game_summary
- upcoming_team_game_context
- team_defense_zone_analysis
- player_shot_zone_analysis
- player_composite_factors
- player_daily_cache
```

**Investigation Steps:**

1. **Check if scraper ran:**
```sql
SELECT *
FROM `nba_orchestration.scraper_execution_log`
WHERE scraper_name LIKE '%team%boxscore%'
  AND triggered_at >= '2025-12-27'
ORDER BY triggered_at DESC
```

2. **Check GCS for raw files:**
```bash
for date in 2025-12-27 2025-12-28 2025-12-29 2025-12-30 2025-12-31; do
  echo "=== $date ==="
  gsutil ls gs://nba-scraped-data/nba-com/team-boxscore-data/$date/ 2>&1 | head -5
done
```

3. **Check processor run history:**
```sql
SELECT processor_name, data_date, status, records_processed, started_at, errors
FROM nba_reference.processor_run_history
WHERE processor_name = 'NbacTeamBoxscoreProcessor'
  AND data_date >= '2025-12-27'
ORDER BY started_at DESC
```

**Potential Scenarios:**

**Scenario A: Scraper didn't run**
```bash
# Manually trigger scraper for each date
for date in 2025-12-27 2025-12-28 2025-12-29 2025-12-30 2025-12-31; do
  echo "Scraping $date..."
  PYTHONPATH=. python3 scrapers/nbacom/team_boxscore_scraper.py --date $date
done
```

**Scenario B: Files in GCS but not processed**
```bash
# Re-trigger processor for each file
for date in 2025-12-27 2025-12-28 2025-12-29 2025-12-30 2025-12-31; do
  GCS_FILE=$(gsutil ls gs://nba-scraped-data/nba-com/team-boxscore-data/$date/ | head -1)

  curl -X POST https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app/process \
    -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    -H "Content-Type: application/json" \
    -d "{\"message\": {\"data\": \"$(echo -n "{\"scraper_name\": \"nbac_team_boxscore\", \"gcs_path\": \"$GCS_FILE\", \"status\": \"success\"}" | base64 -w0)\"}}"
done
```

**Scenario C: NBA.com API changed**
- Review NBA.com API documentation
- Update scraper to match new format
- Test scraper on recent date
- Backfill missing dates

**Backfill Team Processors:**
```bash
# After team boxscore data is available, run team processors
curl -X POST https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app/process-date-range \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "start_date": "2025-12-27",
    "end_date": "2025-12-31",
    "processors": ["TeamDefenseGameSummaryProcessor", "UpcomingTeamGameContextProcessor"],
    "backfill_mode": true
  }'
```

**Verify Backfill:**
```sql
-- Check team_defense_game_summary
SELECT game_date, COUNT(*) as teams
FROM nba_analytics.team_defense_game_summary
WHERE game_date BETWEEN '2025-12-27' AND '2025-12-31'
GROUP BY game_date
ORDER BY game_date
-- Should see rows for each date

-- Check upcoming_team_game_context
SELECT game_date, COUNT(*) as teams
FROM nba_analytics.upcoming_team_game_context
WHERE game_date BETWEEN '2025-12-27' AND '2025-12-31'
GROUP BY game_date
ORDER BY game_date
```

**Git Commit:**
```bash
git add [files you changed]
git commit -m "fix: Backfill team boxscore data for 12/27-12/31

Root cause: [DESCRIBE WHAT YOU FOUND]
Fix: [DESCRIBE YOUR FIX]

Backfilled 5 days of team analytics:
- TeamDefenseGameSummaryProcessor
- UpcomingTeamGameContextProcessor

Restored 6 missing output tables.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### **PRIORITY 3: SYSTEM RELIABILITY**

#### **Issue 3.1: BigQuery Timeout Improvements** ⚡
**Time**: 30 minutes
**Impact**: Prevents indefinite query hangs

**Current State:**
- 85 uncommitted files with `timeout=60` added to BigQuery queries
- BDL date parsing fix also uncommitted
- All changes tested and safe to deploy

**Implementation:**
```bash
# Stage all timeout improvements
git add data_processors/
git add predictions/coordinator/player_loader.py
git add predictions/coordinator/run_history.py
git add predictions/worker/execution_logger.py

# Stage BDL fix (CRITICAL - fixes date parsing bug)
git add data_processors/raw/main_processor_service.py

# Remove backup files
rm Dockerfile.backup.*

# Commit
git commit -m "perf: Add BigQuery query timeouts and BDL date parsing fix

Add timeout=60 to all BigQuery .result() calls across:
- All Phase 2 processors (76 files)
- Phase 3/4 processors
- Prediction coordinator and worker
- Shared utilities

This prevents indefinite hangs on slow BigQuery queries.

Also fix BDL processor to read actual game dates from JSON data
instead of file path. File path date may differ from actual game
dates in backfill scenarios.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# Push to remote
git push origin main
```

**Deploy Phase 2 (for BDL fix):**
```bash
./bin/raw/deploy/deploy_processors_simple.sh
```

**Verify Deployment:**
```bash
# Check Phase 2 service revision
gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 \
  --format="value(status.latestReadyRevisionName,status.url)"

# Test health
curl $(gcloud run services describe nba-phase2-raw-processors \
  --region=us-west2 --format="value(status.url)")/health
```

---

#### **Issue 3.2: Workflow Failures** 🚨
**Time**: 1-2 hours
**Impact**: Stop data gaps from accumulating

**Current State:**
```
Failing Workflows (last 7 days):
- injury_discovery: 11/60 failures (82% success)
- referee_discovery: 12/54 failures (78% success)
- betting_lines: 12/54 failures (78% success)
- schedule_dependency: 6/33 failures (82% success)

Pattern: All failures show scrapers_succeeded=0, scrapers_failed=1-3
Timing: Concentrated on Dec 31 (hourly 11:05-19:05)
```

**Investigation Steps:**

1. **Check API credentials:**
```bash
# Check Odds API key
gcloud secrets versions access latest --secret="ODDS_API_KEY"

# Check BettingPros credentials
gcloud secrets versions access latest --secret="BETTINGPROS_API_KEY"

# Check NBA.com credentials
gcloud secrets versions access latest --secret="NBA_API_KEY"
```

2. **Check for rate limiting:**
```bash
gcloud logging read \
  'severity>=ERROR AND (textPayload=~"429" OR textPayload=~"rate limit")' \
  --limit=50 --freshness=7d
```

3. **Check workflow execution details:**
```sql
SELECT
  execution_id,
  execution_time,
  workflow_name,
  status,
  scrapers_requested,
  scrapers_succeeded,
  scrapers_failed,
  error_summary
FROM `nba_orchestration.workflow_executions`
WHERE status = 'failed'
  AND execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
ORDER BY execution_time DESC
LIMIT 30
```

**Potential Fixes:**

**If API keys expired:**
```bash
# Rotate keys (get new keys from provider dashboards)
echo -n "NEW_KEY" | gcloud secrets versions add ODDS_API_KEY --data-file=-
echo -n "NEW_KEY" | gcloud secrets versions add BETTINGPROS_API_KEY --data-file=-
```

**If rate limiting:**
```python
# Add exponential backoff to scrapers
from google.api_core.retry import Retry

retry = Retry(
    initial=1.0,
    maximum=60.0,
    multiplier=2.0,
    deadline=300.0,
    predicate=lambda exc: getattr(exc, 'status_code', None) == 429
)
```

**If workflow orchestration issue:**
- Read `orchestration/workflows/injury_discovery.py`
- Check recent changes
- Add retry logic for transient failures
- Add alerting for >3 consecutive failures

**Git Commit:**
```bash
git add [files you changed]
git commit -m "fix: Resolve workflow execution failures

Fixed failures in injury_discovery, referee_discovery, betting_lines
workflows that were failing 11-12 times in last 7 days.

Root cause: [DESCRIBE WHAT YOU FOUND]
Fix: [DESCRIBE YOUR FIX]

Added retry logic with exponential backoff for transient failures.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## 📋 COMPLETE FIX CHECKLIST

Use this to track progress:

### **IMMEDIATE (Next 2 Hours)**
- [ ] Fix PlayerGameSummaryProcessor line 309
- [ ] Test fix on 2025-12-31 data
- [ ] Deploy Phase 3 processors
- [ ] Deploy data completeness checker
- [ ] Test completeness checker endpoint
- [ ] Update docs: Add fix summary to `2026-01-01-FIX-PROGRESS.md`

### **URGENT (Next 4 Hours)**
- [ ] Investigate injuries API (41 days stale!)
- [ ] Fix injuries scraper/API issue
- [ ] Backfill injuries data (11/22 - 01/01)
- [ ] Verify injuries in BigQuery
- [ ] Investigate nbac_team_boxscore scraper
- [ ] Backfill team boxscore data (12/27-12/31)
- [ ] Run team processors backfill
- [ ] Verify team analytics tables populated
- [ ] Update docs: Add backfill completion notes

### **HIGH PRIORITY (Next 8 Hours)**
- [ ] Commit BigQuery timeout improvements (85 files)
- [ ] Push to remote
- [ ] Deploy Phase 2 processors (BDL fix)
- [ ] Investigate workflow failures
- [ ] Fix API credentials or rate limiting
- [ ] Add retry logic to workflows
- [ ] Test workflows execute successfully
- [ ] Update docs: Add workflow fix summary

### **MEDIUM PRIORITY (Next 24 Hours)**
- [ ] Investigate 348K processor failures pattern
- [ ] Fix Cloud Run logging ("No message" issue)
- [ ] Review circuit breaker (954 locked players)
- [ ] Add auto-reset when upstream data available
- [ ] Document orchestration dual paths
- [ ] Update dashboard for same-day vs full pipeline views
- [ ] Update docs: Add monitoring improvements

### **VALIDATION (After All Fixes)**
- [ ] Run comprehensive validation: `PYTHONPATH=. python3 bin/validate_pipeline.py $(date -d 'yesterday' +%Y-%m-%d)`
- [ ] Check all services healthy
- [ ] Verify predictions generating for tonight's games
- [ ] Check Firestore orchestration state
- [ ] Monitor error logs for 1 hour
- [ ] Update docs: Add final validation results

---

## 📝 DOCUMENTATION REQUIREMENTS

**CRITICAL**: After each major fix, update documentation in:
`/home/naji/code/nba-stats-scraper/docs/08-projects/current/pipeline-reliability-improvements/`

### **Create New Doc: `2026-01-01-FIX-PROGRESS.md`**

Template:
```markdown
# Fix Progress - January 1, 2026

**Started**: [TIME]
**Status**: [IN PROGRESS / COMPLETE]

## Fixes Completed

### 1. PlayerGameSummaryProcessor Fix
- **Time**: [START] - [END]
- **Status**: ✅ COMPLETE / ⏳ IN PROGRESS / ❌ FAILED
- **Changes**: [describe]
- **Commit**: [hash]
- **Deployment**: [revision]
- **Testing**: [results]
- **Notes**: [any issues encountered]

### 2. Data Completeness Checker
[same format]

### 3. Injuries Data
[same format]

... etc for each fix ...

## Issues Encountered
[Document any unexpected problems]

## Next Steps
[What's remaining]
```

### **Update Existing Docs:**
1. Add fix completion notes to `2026-01-01-MASTER-FINDINGS-AND-FIX-PLAN.md`
2. Update `PIPELINE_SCAN_REPORT_2026-01-01.md` with resolution status
3. Create summary in `2026-01-01-SESSION-COMPLETE.md` when all done

---

## 🧪 TESTING PROCEDURES

### **After Each Fix:**

1. **Unit Test** (if applicable)
```bash
pytest tests/test_[component].py -v
```

2. **Integration Test**
```bash
# Run processor/scraper on test date
PYTHONPATH=. python3 [script] --date 2025-12-31
```

3. **Verify in BigQuery**
```sql
-- Check data was written
SELECT COUNT(*) FROM [table] WHERE game_date = '2025-12-31'
```

4. **Check Logs**
```bash
gcloud logging read \
  'resource.labels.service_name="[service]" AND severity>=ERROR' \
  --limit=10 --freshness=10m
```

### **After All Fixes:**

Run comprehensive validation:
```bash
# Run pipeline validation for yesterday
PYTHONPATH=. python3 bin/validate_pipeline.py $(date -d 'yesterday' +%Y-%m-%d)

# Check orchestration state
python3 bin/monitoring/check_orchestration_state.py $(date +%Y-%m-%d)

# Run daily health check
./bin/monitoring/daily_health_check.sh
```

---

## 🚨 IF SOMETHING GOES WRONG

### **Emergency Rollback Procedures:**

**Phase 2 Processors:**
```bash
# List recent revisions
gcloud run revisions list --service=nba-phase2-raw-processors --region=us-west2 --limit=5

# Rollback to previous revision
gcloud run services update-traffic nba-phase2-raw-processors \
  --region=us-west2 \
  --to-revisions=[PREVIOUS_REVISION]=100
```

**Phase 3 Processors:**
```bash
gcloud run revisions list --service=nba-phase3-analytics-processors --region=us-west2 --limit=5
gcloud run services update-traffic nba-phase3-analytics-processors \
  --region=us-west2 \
  --to-revisions=[PREVIOUS_REVISION]=100
```

**Git Revert:**
```bash
# Revert last commit
git revert HEAD
git push origin main
```

### **Emergency Contacts / Resources:**
- Pipeline validation script: `bin/validate_pipeline.py`
- Health check script: `bin/monitoring/daily_health_check.sh`
- Deployment scripts: `bin/[phase]/deploy/`
- Investigation docs: `docs/08-projects/current/pipeline-reliability-improvements/`

---

## 📊 SUCCESS CRITERIA

**You're done when:**
- [ ] PlayerGameSummaryProcessor success rate = 100% (was 60%)
- [ ] Team analytics coverage = 100% for last 7 days (was 0% for last 5 days)
- [ ] Injuries data freshness < 24 hours (was 41 days!)
- [ ] Workflow success rate > 95% (was 78-82%)
- [ ] All 6 missing tables populated
- [ ] Tonight's predictions generate successfully
- [ ] No critical errors in logs for 1 hour
- [ ] Comprehensive validation passes
- [ ] All documentation updated

---

## 💡 HELPFUL CONTEXT

### **System Architecture:**
- **Phase 1**: Scrapers (NBA.com, BDL, Odds API, BettingPros)
- **Phase 2**: Raw processors (parse JSON → BigQuery)
- **Phase 3**: Analytics processors (player/team summaries)
- **Phase 4**: Precompute processors (ML features, composite factors)
- **Phase 5**: Prediction coordinator + workers

### **Orchestration:**
- **Event-driven**: Phase N completion → Pub/Sub → Phase N+1 trigger
- **Time-driven**: Cloud Schedulers for same-day predictions (bypass orchestration)
- **Firestore**: Tracks completion state per phase per date

### **Key Tables:**
- `nba_raw.*`: Raw scraped data
- `nba_analytics.*`: Processed analytics
- `nba_predictions.*`: ML features + predictions
- `nba_orchestration.*`: Workflow tracking
- `nba_reference.*`: Processor run history

### **Current Git State:**
```
Branch: main
Latest commit: 4fba849 (docs only)
Uncommitted: 85 files (timeout improvements + BDL fix)
```

---

## 🎯 FINAL REMINDERS

1. **Read the master findings doc first**: `2026-01-01-MASTER-FINDINGS-AND-FIX-PLAN.md`
2. **Fix in priority order** - Don't skip ahead
3. **Test each fix** before moving to next
4. **Update docs after each major fix** in `/docs/08-projects/current/pipeline-reliability-improvements/`
5. **Commit frequently** with descriptive messages
6. **Monitor logs** after each deployment
7. **Run full validation** at the end

---

**Good luck! The system is already working, you're just making it better.** 🚀

**Questions? All investigation artifacts are in the docs directory.**

**Start with Issue 1.1 (PlayerGameSummaryProcessor) - it's a 5-minute quick win!**

---

**Last Updated**: 2026-01-01 15:45 ET
**Created By**: Investigation session (5 agents, 6.5M tokens)
**Status**: 🟢 READY FOR IMPLEMENTATION
