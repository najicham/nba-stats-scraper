# Session Handoff: 2026-01-26 Betting Data Investigation

**Date:** 2026-01-26
**Time:** 11:25 AM ET
**Session Status:** ✅ ROOT CAUSE FOUND & FIXED, ⏳ Data Collection In Progress
**Next Session Priority:** Continue with data validation and Phase 3 triggering

---

## Executive Summary

**What Happened:**
The orchestration pipeline reported "0 records" for betting data on 2026-01-26, appearing as a repeat of the 2026-01-25 failure. Investigation revealed this was **NOT a technical failure** but a **workflow timing misconfiguration**.

**Root Cause:**
The `betting_lines` workflow was configured to start only 6 hours before games (1 PM for 7 PM games), but validation scripts and users expected betting data to be available by mid-morning.

**Fix Applied:**
Changed `config/workflows.yaml`: `window_before_game_hours: 6` → `window_before_game_hours: 12`
- Old schedule: Starts 1 PM, runs at 1/3/5/7 PM
- New schedule: Starts 7 AM, runs at 7/9/11 AM, 1/3/5/7 PM

**Current Status:**
- ✅ Root cause identified and documented
- ✅ Configuration fix implemented (local, not deployed)
- ✅ Manual data collection started for today
- ⏳ Scrapers currently running (14 scraper tasks × 7 games)
- ⏳ Need to verify data, trigger Phase 3, and deploy fix

---

## What We Discovered

### This Was NOT a Repeat of 2026-01-25

**2026-01-25 Issues (Real Technical Failures):**
- Play-by-play scraper IP blocked by cdn.nba.com
- GSW and SAC teams missing from player context
- TeamOffenseGameSummary parser errors

**2026-01-26 Issue (Configuration Problem):**
- Betting workflow simply hadn't started yet (not scheduled to)
- No technical failures
- System working as configured (just configured wrongly)

**Common Symptom:** Both showed "0 records" but for completely different reasons!

### Investigation Process

1. **Started with validation report** showing Phase 2/3/4/5 failures
2. **Checked scraper code** - all working correctly
3. **Verified API credentials** - ODDS_API_KEY properly configured
4. **Examined workflows.yaml** - found `window_before_game_hours: 6`
5. **Calculated timing:**
   - Current time: 11:02 AM ET
   - Games tonight: 7:00 PM ET
   - Window start (6h before): 1:00 PM ET
   - **Workflow hasn't started yet - it's 2 hours early!**

### Key Files Examined

**Scraper Code:**
- `scrapers/oddsapi/oddsa_events.py` - Retrieves game event IDs
- `scrapers/oddsapi/oddsa_player_props.py` - Player prop lines
- `scrapers/oddsapi/oddsa_game_lines.py` - Game spreads/totals
- All use `shared/utils/auth_utils.py::get_api_key()` to get ODDS_API_KEY

**Configuration:**
- `config/workflows.yaml` - Workflow scheduling (fixed in this session)
- `shared/config/orchestration_config.py` - Expected processors

**Documentation:**
- `docs/incidents/2026-01-25-REMEDIATION-COMPLETION-REPORT.md` - Previous incident
- `docs/validation/2026-01-26-DAILY-ORCHESTRATION-VALIDATION.md` - Validation report

---

## Changes Made

### 1. Configuration Fix (Not Deployed Yet)

**File:** `config/workflows.yaml`

```yaml
# Line 354 - Changed from 6 to 12
betting_lines:
  schedule:
    game_aware: true
    window_before_game_hours: 12  # CHANGED FROM 6
    business_hours:
      start: 8
      end: 20
    frequency_hours: 2
```

**Impact:**
- Betting data will be available starting 7 AM (vs 1 PM)
- Phase 3 can run by 10 AM (vs 4 PM)
- Users get predictions in morning (vs late afternoon)
- +63 API calls per day = ~$2/month additional cost (negligible)

**Status:** ✅ Changed locally, ⏳ Not committed or deployed

### 2. Documentation Created

**File:** `docs/incidents/2026-01-26-BETTING-DATA-TIMING-ISSUE-ROOT-CAUSE.md`

Comprehensive root cause analysis covering:
- Timeline of investigation
- Why this is NOT a repeat of 2026-01-25
- Detailed root cause explanation
- Lessons learned
- Prevention measures
- Monitoring improvements needed

**Status:** ✅ Complete, ready for review

### 3. Manual Data Collection Started

**Triggered Scrapers:**

```bash
# Step 1: Events (COMPLETED) ✅
python3 scrapers/oddsapi/oddsa_events.py \
  --sport basketball_nba \
  --game_date 2026-01-26 \
  --group prod

# Result: 7 events retrieved, saved to GCS
# File: gs://nba-scraped-data/odds-api/events/2026-01-26/20260126_160319.json

# Event IDs:
# 1. 4030222f... - IND @ ATL
# 2. d2ffa3af... - PHI @ CHA
# 3. a5157a5c... - ORL @ CLE
# 4. 00747f87... - POR @ BOS
# 5. 508b6db7... - LAL @ CHI
# 6. a1550da0... - MEM @ HOU
# 7. 2468f90b... - GSW @ MIN

# Step 2: Props & Lines (IN PROGRESS) ⏳
# Running 14 scrapers in parallel:
#   - oddsa_player_props for 7 events
#   - oddsa_game_lines for 7 events
# Background task ID: b0926bb
# Status: Running (started ~15 minutes ago, may need 5-10 more minutes)
```

**Status:** ⏳ In progress, check task `b0926bb` for completion

---

## Current State

### What's Working ✅
1. Schedule data: 7 games loaded for 2026-01-26
2. Roster data: 615 players across 30 teams (updated 2026-01-26)
3. Injury reports: 2,565 records current
4. Events scraper: Successfully retrieved 7 event IDs
5. API credentials: ODDS_API_KEY working correctly
6. Scraper infrastructure: All systems operational

### What's Still Missing ⏳
1. **Betting props data** - Currently being collected (task b0926bb)
2. **Game lines data** - Currently being collected (task b0926bb)
3. **Phase 3 analytics** - 0 records (blocked by missing betting data)
4. **Phase 4 precompute** - Stale from previous runs
5. **Phase 5 predictions** - 0 predictions for today
6. **API exports** - Showing 2026-01-25 (need today's data)

### Known Issues
1. **BigQuery Quota Warning** - `pipeline_event_log` table hitting partition modification quota (non-critical, just logging)
2. **Cost Metrics Table Missing** - `nba_orchestration.scraper_cost_metrics` table doesn't exist (non-critical)

---

## Next Steps (Priority Order)

### IMMEDIATE (Next 30 Minutes)

#### 1. Check Scraper Completion
```bash
# Check if background scrapers finished
cat /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b0926bb.output

# OR use TaskOutput
# (Already in context, task_id: b0926bb)

# Expected output: 14 lines showing success/failure for each scraper
# Should see ~200-300 rows of player props
# Should see ~70-140 rows of game lines
```

#### 2. Verify Data in BigQuery
```bash
# Check props data
bq query --use_legacy_sql=false --location=us-west2 "
SELECT COUNT(*) as prop_count
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date = '2026-01-26'
"
# Expected: 200-300 records

# Check game lines
bq query --use_legacy_sql=false --location=us-west2 "
SELECT COUNT(*) as lines_count
FROM \`nba-props-platform.nba_raw.odds_api_game_lines\`
WHERE game_date = '2026-01-26'
"
# Expected: 70-140 records
```

#### 3. Trigger Phase 3 Analytics Processors

**Option A: Automatic (via Pub/Sub)**
The scrapers should have published to `nba-phase2-raw-complete` topic, which should trigger Phase 3 automatically. Check Firestore to see if Phase 3 started:

```bash
# Check orchestration state
# (Use Firestore client to check phase3_status for 2026-01-26)
```

**Option B: Manual Trigger (if automatic didn't work)**
```bash
# Use the orchestration manual trigger tool
python orchestration/manual_trigger_phase3.py --date 2026-01-26

# OR trigger individual processors
python data_processors/analytics/upcoming_player_game_context/trigger.py \
  --date 2026-01-26 \
  --mode daily

python data_processors/analytics/upcoming_team_game_context/trigger.py \
  --date 2026-01-26 \
  --mode daily
```

**Expected Results:**
- `upcoming_player_game_context`: 200-300 records (all players with games tonight)
- `upcoming_team_game_context`: 14 records (2 per game, home+away view)

### SHORT TERM (Next 2 Hours)

#### 4. Validate Full Pipeline
```bash
# Run validation again
python scripts/validate_tonight_data.py --date 2026-01-26

# Expected improvements:
# - Props: 200-300 records (was 0)
# - Lines: 70-140 records (was 0)
# - Player context: 200-300 records (was 0)
# - Team context: 14 records (was 0)
```

#### 5. Commit Configuration Fix
```bash
# Review the change
git diff config/workflows.yaml

# Commit with descriptive message
git add config/workflows.yaml
git commit -m "fix: Change betting_lines workflow to start 12h before games

Root cause: betting_lines workflow was configured to start only 6 hours
before games (1 PM for 7 PM games), but users expect betting data and
predictions available in the morning.

Fix: Changed window_before_game_hours from 6 to 12, enabling betting
data collection starting at 7 AM for 7 PM games.

Impact:
- Betting data available all day (7 AM - 8 PM)
- Phase 3 can run by 10 AM (was 4 PM)
- Users get morning predictions (was late afternoon)
- +63 API calls/day = ~\$2/month additional cost (negligible)

Incident: 2026-01-26 appeared as repeat of 2026-01-25 failure, but
was actually just timing misconfiguration, not technical failure.

Related: docs/incidents/2026-01-26-BETTING-DATA-TIMING-ISSUE-ROOT-CAUSE.md

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# Push to remote
git push origin main
```

#### 6. Deploy Configuration to Production

**Deployment Method:** (Check with team for correct process)
```bash
# If using Cloud Build
gcloud builds submit --config cloudbuild.yaml

# OR if manual deployment
# Copy config/workflows.yaml to production environment
# Restart master_controller service
```

### MEDIUM TERM (Next Week)

#### 7. Update Validation Script Logic

**File:** `scripts/validate_tonight_data.py`

Add logic to distinguish:
- ❌ Workflow ran and failed (CRITICAL)
- ⏳ Workflow hasn't started yet (INFO with next run time)
- ✅ Workflow succeeded

**Suggested check:**
```python
# Check if betting_lines workflow window has started
current_time = datetime.now(eastern)
first_game_time = get_first_game_time(date)
window_start = first_game_time - timedelta(hours=12)

if current_time < window_start:
    # Window hasn't started yet
    return ValidationResult(
        status="info",
        message=f"Betting data not available yet. Window starts at {window_start:%I:%M %p}"
    )
```

#### 8. Add Monitoring & Alerting

**Create alerts for:**

1. **Workflow Window Not Started**
   ```yaml
   alert: betting_lines_not_started
   condition: validation_time < (first_game_time - 12h)
   severity: INFO
   message: "Betting workflow starts at {window_start}"
   ```

2. **Betting Data Late**
   ```yaml
   alert: betting_data_late
   condition: current_time > (window_start + 2h) AND prop_count == 0
   severity: WARNING
   message: "Betting data not collected 2h after window start"
   ```

3. **Phase 3 Blocked**
   ```yaml
   alert: phase3_blocked_by_betting_data
   condition: phase3_should_run AND betting_data_missing
   severity: HIGH
   message: "Phase 3 cannot run - missing betting data"
   ```

#### 9. Update Documentation

**Files to update:**
- `README.md` - Add note about workflow timing
- `docs/architecture/orchestration-system-study.md` - Update betting_lines timing
- `config/workflows.yaml` - Add timing comments for clarity

### LONG TERM (Next Month)

#### 10. Architectural Improvements

1. **Graceful Degradation**
   - Allow Phase 3 to run without betting data (with warnings)
   - Set `has_prop_line = FALSE` for all players if props missing
   - Generate predictions with lower confidence when betting data missing

2. **Self-Healing**
   - If betting data missing at Phase 3 time, trigger immediate collection
   - Add automatic retry logic for failed scraper runs
   - Implement circuit breaker for repeated failures

3. **Dynamic Scheduling**
   - Calculate optimal window_before_game_hours based on actual game times
   - Adjust frequency based on line movement patterns
   - Skip redundant runs if lines haven't changed

---

## Troubleshooting Guide

### If Scrapers Failed

**Check logs:**
```bash
# View scraper output
cat /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b0926bb.output

# Common issues:
# - API key missing: Check ODDS_API_KEY in environment or Secret Manager
# - API quota exceeded: Check Odds API dashboard
# - Network timeout: Retry individual scrapers
# - 403 Forbidden: API key invalid or rate limited
```

**Retry individual scrapers:**
```bash
# Get event IDs from /tmp/event_ids.txt
EVENT_ID="4030222f70e9378b52f52597c7cc89a1"

# Retry props
python3 scrapers/oddsapi/oddsa_player_props.py \
  --event_id $EVENT_ID \
  --game_date 2026-01-26 \
  --group prod

# Retry lines
python3 scrapers/oddsapi/oddsa_game_lines.py \
  --event_id $EVENT_ID \
  --game_date 2026-01-26 \
  --group prod
```

### If Phase 3 Doesn't Trigger

**Check Pub/Sub:**
```bash
# Check if completion message was published
gcloud pubsub topics list-subscriptions nba-phase2-raw-complete

# Check subscription backlog
gcloud pubsub subscriptions describe nba-phase3-analytics-sub

# Pull messages (don't ack)
gcloud pubsub subscriptions pull nba-phase3-analytics-sub --auto-ack=false --limit=10
```

**Manual trigger:**
```bash
# Publish Phase 2 completion message manually
gcloud pubsub topics publish nba-phase2-raw-complete \
  --message='{"date": "2026-01-26", "status": "complete", "processor": "manual_trigger"}'

# OR trigger Phase 3 directly
python orchestration/manual_trigger_phase3.py --date 2026-01-26
```

### If Data Doesn't Appear in BigQuery

**Check GCS:**
```bash
# Props should be here
gsutil ls -lh gs://nba-scraped-data/odds-api/player-props/2026-01-26/

# Lines should be here
gsutil ls -lh gs://nba-scraped-data/odds-api/game-lines/2026-01-26/

# If files exist but not in BigQuery, trigger processors manually
python data_processors/raw/oddsapi/odds_api_props_processor.py --date 2026-01-26
```

---

## Testing Checklist

Before marking this incident as fully resolved:

- [ ] Scraper task b0926bb completed successfully
- [ ] Betting props data in BigQuery (200-300 records)
- [ ] Game lines data in BigQuery (70-140 records)
- [ ] Phase 3 upcoming_player_game_context populated (200-300 records)
- [ ] Phase 3 upcoming_team_game_context populated (14 records)
- [ ] Phase 4 player_daily_cache has today's data
- [ ] Phase 5 predictions generated for tonight's games
- [ ] API exports updated with 2026-01-26 timestamp
- [ ] Configuration change committed
- [ ] Configuration change deployed to production
- [ ] Validation script no longer shows false alarms
- [ ] Monitoring alerts added for timing issues
- [ ] Documentation updated

---

## Key Learnings

### 1. "0 Records" Can Mean Many Things

Don't assume "0 records" always means failure. It could mean:
- ✅ Workflow hasn't started yet (timing)
- ✅ No games scheduled (off-season)
- ❌ Scraper failed (technical issue)
- ❌ API down (external dependency)
- ❌ Credentials invalid (configuration)

**Lesson:** Improve validation logic to distinguish these cases.

### 2. Configuration Is Code

Workflow timing configurations are just as important as code:
- Should be version controlled (✅ already is)
- Should have tests (❌ missing)
- Should have documentation (❌ minimal)
- Should be validated against business requirements (❌ not done)

**Lesson:** Treat configuration with same rigor as code.

### 3. Business Requirements Drive Technical Configuration

The 6-hour window was technically correct but didn't meet user needs:
- Technical: "Collect betting data before games"
- Business: "Users want predictions by 10 AM"

**Lesson:** Always validate technical configs against business SLAs.

### 4. Timing is Critical in Orchestration

The pipeline has tight dependencies:
```
Morning → Betting Data → Analytics → Precompute → Predictions → Exports
7 AM        7-9 AM          10 AM        11 PM        6 AM         1 PM
```

If betting data starts at 1 PM, everything downstream is delayed.

**Lesson:** Map out timing dependencies and validate end-to-end latency.

---

## Files Modified

### Configuration
- `config/workflows.yaml` - Changed `window_before_game_hours: 6` → `12`

### Documentation Created
- `docs/incidents/2026-01-26-BETTING-DATA-TIMING-ISSUE-ROOT-CAUSE.md` - Full incident analysis
- `docs/sessions/2026-01-26-BETTING-DATA-INVESTIGATION-HANDOFF.md` - This file

### Files to Review/Update (Not Changed Yet)
- `scripts/validate_tonight_data.py` - Needs timing-aware validation logic
- `shared/config/orchestration_config.py` - May need timing validation
- `docs/architecture/orchestration-system-study.md` - Update with new timing

---

## Contact & References

### Related Incidents
- **2026-01-25:** Play-by-play IP blocking, GSW/SAC missing - DIFFERENT root cause
- **2026-01-26:** This incident - Workflow timing misconfiguration

### Key Documents
- Root cause analysis: `docs/incidents/2026-01-26-BETTING-DATA-TIMING-ISSUE-ROOT-CAUSE.md`
- Validation report: `docs/validation/2026-01-26-DAILY-ORCHESTRATION-VALIDATION.md`
- Yesterday's incident: `docs/incidents/2026-01-25-REMEDIATION-COMPLETION-REPORT.md`

### Task Tracking

Current task list (use `TaskList` to check):
- #1: ✅ Investigate odds_api scrapers (COMPLETED)
- #2: ⏳ Fix root cause (IN PROGRESS - config changed, awaiting data)
- #3: ⏳ Trigger Phase 3 processors (PENDING - waiting for data)
- #4: ⏳ Verify pipeline completion (PENDING)
- #5: ⏳ Add monitoring/alerting (PENDING)
- #6: ⏳ Document incident (MOSTLY DONE - root cause doc created)

---

## Quick Start for Next Session

```bash
# 1. Check scraper completion
cat /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b0926bb.output

# 2. Verify data in BigQuery
bq query --location=us-west2 "SELECT COUNT(*) FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\` WHERE game_date = '2026-01-26'"

# 3. If data present, trigger Phase 3
python orchestration/manual_trigger_phase3.py --date 2026-01-26

# 4. Validate pipeline
python scripts/validate_tonight_data.py --date 2026-01-26

# 5. Commit configuration fix
git add config/workflows.yaml docs/
git commit -m "fix: betting_lines timing + incident documentation"
git push
```

---

## Success Criteria

**Immediate (Today):**
- ✅ Root cause identified
- ✅ Configuration fix implemented
- ⏳ Betting data collected for today
- ⏳ Phase 3 analytics complete
- ⏳ Predictions available for tonight's games

**Short Term (This Week):**
- Configuration deployed to production
- Validation scripts updated
- Monitoring alerts added

**Long Term (This Month):**
- No more false alarm failures
- Predictions consistently available by 10 AM
- Graceful degradation implemented

---

**Session End Time:** 2026-01-26 11:25 AM ET
**Next Session Start:** Continue after reviewing scraper results
**Session Context:** 126k/200k tokens (63% used)

**Status Summary:**
- 🟢 Investigation: COMPLETE
- 🟢 Root Cause: IDENTIFIED
- 🟢 Configuration Fix: READY
- 🟡 Data Collection: IN PROGRESS
- 🔴 Deployment: NOT STARTED
- 🔴 Validation: NOT STARTED

**Handoff Complete** ✅
