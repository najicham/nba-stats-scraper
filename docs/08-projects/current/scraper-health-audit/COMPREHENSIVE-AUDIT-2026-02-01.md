# Scraper Health Audit - February 1, 2026

**Date**: 2026-02-01
**Session**: 70 (continued)
**Trigger**: User reported NBA trade today - system didn't pick it up
**Status**: COMPLETE - Critical issues identified and documented

---

## Executive Summary

A comprehensive audit of all 35 NBA scrapers revealed **significant health issues** affecting roster tracking, betting data, and analytics pipelines.

### Key Findings

**Health Status:**
- ✅ **18 HEALTHY** (51%) - Data within 2 days
- ⚠️ **3 STALE** (9%) - Data 3-7 days old
- 🚨 **6 CRITICAL** (17%) - Data >7 days old
- ❓ **8 UNKNOWN** (23%) - Write to BigQuery directly

**Critical Issues:**
1. **Player movement not tracked** - 5+ months stale, no scheduler
2. **3 scheduled jobs failing** - br_roster (9d), espn_roster (3d), bdl_box_scores (7d)
3. **3 scrapers without schedulers** - bdl_games, bp_player_props, player_movement
4. **Monitoring gap** - validate-scrapers only checks betting data, not roster/context data

---

## Critical Issues Requiring Immediate Action

### 1. Player Movement Tracking (TODAY'S TRADE MISSED)

**Issue:** NBA trade happened today, system didn't detect it

| Metric | Value |
|--------|-------|
| Last data | August 21, 2025 |
| Days stale | 163 days (5+ months) |
| Scheduler job | ❌ NONE |
| Scraper status | EXISTS but not scheduled |
| Impact | Can't track trades, signings, waivers |

**Root Cause:**
- Scraper `nbac_player_movement` exists and is registered
- Config marks it as "Collected but not consumed"
- No Cloud Scheduler job to trigger it
- No monitoring for roster data freshness

**Impact:**
- Missing all 2025-26 season trades
- Can't validate player-team associations
- Prediction system may use wrong rosters

**Fix:**
```bash
# Create scheduler job
gcloud scheduler jobs create http nbac-player-movement-daily \
  --location=us-west2 \
  --schedule="0 8,14 * * *" \
  --uri="https://nba-scrapers-<hash>.run.app/nbac_player_movement" \
  --http-method=POST \
  --oidc-service-account-email=<service-account> \
  --description="Player movement/trades scraper (morning + afternoon)"

# Backfill since August
PYTHONPATH=. python scrapers/nbacom/nbac_player_movement.py --year 2025
```

---

### 2. Basketball Reference Roster (9 Days Stale)

**Issue:** Scheduled job exists but failing

| Metric | Value |
|--------|-------|
| Last data | January 23, 2026 04:08 UTC |
| Days stale | 9 days |
| Scheduler job | ✅ br-rosters-batch-daily (6:30 AM) |
| Status | JOB FAILING |

**Action Required:**
```bash
# Check job execution history
gcloud scheduler jobs describe br-rosters-batch-daily --location=us-west2

# Check recent logs
gcloud logging read 'resource.labels.job_name="br-rosters-batch-daily"' \
  --limit=10 --freshness=10d
```

---

### 3. BettingPros Player Props (19 Days Stale)

**Issue:** No scheduler, possibly replaced by Odds API

| Metric | Value |
|--------|-------|
| Last data | January 13, 2026 01:20 UTC |
| Days stale | 19 days |
| Scheduler job | ❌ NONE |
| Replacement | oddsa_player_props (HEALTHY) |

**Action Required:**
- Verify if bp_player_props is still needed
- If yes: Create scheduler
- If no: Mark as deprecated in registry

---

### 4. BDL Games (10 Days Stale)

**Issue:** No scheduler, unclear if needed

| Metric | Value |
|--------|-------|
| Last data | January 22, 2026 18:14 UTC |
| Days stale | 10 days |
| Scheduler job | ❌ NONE |
| Replacement | bdl_box_scores (HEALTHY) |

**Action Required:**
- Verify if bdl_games is deprecated
- If yes: Remove from registry
- If no: Create scheduler

---

## Stale Scrapers with Schedulers (Job Failures)

### 1. ESPN Roster (3 Days Stale)

| Metric | Value |
|--------|-------|
| Last data | January 29, 2026 11:08 UTC |
| Days stale | 3 days |
| Scheduler job | ✅ espn-roster-processor-daily (7:30 AM) |
| Status | JOB FAILING |

### 2. BDL Player Box Scores (7 Days Stale)

| Metric | Value |
|--------|-------|
| Last data | January 25, 2026 02:41 UTC |
| Days stale | 7 days |
| Scheduler jobs | ✅ 3x catchup jobs (10 AM, 2 PM, 6 PM) |
| Status | CATCHUP LOGIC NOT WORKING |

---

## False Alarms Resolved

### Schedule Scrapers (nbac_schedule, nbac_schedule_api, nbac_schedule_cdn)

**GCS Status:** 79 days stale (appears CRITICAL)
**BigQuery Status:** ✅ HEALTHY (updated today 2026-02-01 20:30:05)

**Explanation:**
- Scrapers now write directly to BigQuery
- GCS intermediate storage bypassed
- GCS metrics misleading

**Action:** Update monitoring to check BigQuery timestamps, not just GCS

---

## Unknown Status Scrapers (8 total)

These may write directly to BigQuery without GCS:

| Scraper | BigQuery Table | Needs Investigation |
|---------|----------------|---------------------|
| bdl_injuries | nba_raw.bdl_injuries | Check BQ timestamp |
| nbac_roster | nba_raw.nbac_roster | Check BQ timestamp |
| nbac_player_list | nba_raw.nbac_player_list | Check BQ timestamp |
| nbac_player_movement | nba_raw.nbac_player_movement | ✅ CONFIRMED STALE |
| nbac_scoreboard_v2 | nba_raw.nbac_scoreboard_v2 | Check BQ timestamp |
| espn_scoreboard | nba_raw.espn_scoreboard | Check BQ timestamp |
| espn_game_boxscore | nba_raw.espn_game_boxscore | Check BQ timestamp |
| oddsa_team_players | nba_raw.odds_api_team_players | Check BQ timestamp |

---

## Monitoring Framework Gaps

### Current State

**What We Monitor:**
- ✅ Betting data (validate-scraped-data skill)
  - Odds API game lines
  - Odds API player props
  - BettingPros props
  - Coverage: Oct 2025 - Present

**What We DON'T Monitor:**
- ❌ Player movement/transactions
- ❌ Injury reports (config exists but no skill)
- ❌ Roster data
- ❌ Context data (standings, referees, etc.)

### Why Player Movement Wasn't Caught

**validate-scrapers skill:**
- Scope: Betting/odds data ONLY
- Checks: Coverage %, bookmaker availability
- Does NOT check: Roster, transactions, injuries

**validate-daily skill:**
- Checks: Game/analytics pipeline health
- Does NOT check: Scraper data freshness

**Result:** 5+ months of stale player movement data went undetected

---

## Root Cause Analysis

| Issue | Root Cause | Prevention |
|-------|------------|------------|
| Player movement stale | No scheduler job | Create job, add monitoring |
| Scheduled jobs failing | No failure alerts | Add job failure monitoring |
| Monitoring gaps | Skills focused on betting data | Create 3-tier monitoring |
| GCS vs BQ confusion | Some scrapers bypass GCS | Document write patterns |

---

## Prevention Mechanisms

### 1. Three-Tier Monitoring Architecture

**Tier 1: Betting Data (EXISTING)**
- validate-scraped-data skill
- Monitors: Odds API, BettingPros
- Frequency: On-demand

**Tier 2: Roster & Player Data (NEW)**
- validate-roster-data skill (to be created)
- Monitors: player_movement, rosters, injuries
- Frequency: Daily
- Thresholds: <7 days = OK, 7-30 = WARNING, >30 = CRITICAL

**Tier 3: Context Data (NEW)**
- validate-context-data skill (to be created)
- Monitors: standings, referees, schedule
- Frequency: Weekly
- Thresholds: <14 days = OK, 14-60 = WARNING, >60 = CRITICAL

### 2. Scheduler Job Monitoring

**Add to validate-daily skill:**

```python
# Check for failed scheduler jobs
failed_jobs = check_failed_scheduler_jobs(hours=24)
if failed_jobs:
    for job in failed_jobs:
        logger.warning(f"Scheduler job failed: {job.name}")
```

### 3. Scraper Health Dashboard

Create unified view showing:
- Scraper name
- Last successful run
- Days since data
- Scheduler status
- Health score

### 4. Automated Alerts

**Slack/Email alerts for:**
- Scheduled job failures
- Data staleness >7 days
- Missing scheduler jobs for active scrapers

---

## Documentation Gaps Identified

### What Exists (GOOD)

- ✅ `scrapers/README.md` - Architecture and design
- ✅ `docs/06-reference/scrapers.md` - Comprehensive reference (26 scrapers)
- ✅ `docs/06-reference/scraper-processor-mapping.md` - Scraper-to-processor mapping
- ✅ `docs/03-phases/phase1-orchestration/` - How orchestration works

### What's Missing (GAPS)

- ❌ **Scraper Operations Runbook** - How to deploy, troubleshoot, monitor
- ❌ **Scraper Troubleshooting Guide** - Common errors and fixes
- ❌ **GCS Path Documentation** - Storage patterns and conventions
- ❌ **Real-time Monitoring Guide** - How to monitor scraper health
- ❌ **Scheduler Job Registry** - Which jobs trigger which scrapers

---

## Immediate Action Plan

### Phase 1: Critical Fixes (Today)

1. ✅ **Document findings** - This document
2. ⏳ **Create player_movement scheduler** - Fix today's trade issue
3. ⏳ **Investigate 3 failing jobs** - br_roster, espn_roster, bdl_box_scores
4. ⏳ **Update validate-daily skill** - Add roster data checks

### Phase 2: Monitoring (This Week)

1. ⏳ **Create validate-roster-data skill** - Monitor player movement, rosters, injuries
2. ⏳ **Add scheduler job monitoring** - Alert on failures
3. ⏳ **Query UNKNOWN scrapers** - Verify BigQuery status
4. ⏳ **Document write patterns** - Which scrapers use GCS vs direct BQ

### Phase 3: Documentation (This Sprint)

1. ⏳ **Create scraper operations runbook** - Deploy, monitor, troubleshoot
2. ⏳ **Create scheduler registry** - Map all jobs to scrapers
3. ⏳ **Document GCS patterns** - Storage conventions
4. ⏳ **Update CLAUDE.md** - Add scraper health checks

### Phase 4: Long-term Improvements

1. ⏳ **Unified health dashboard** - All scrapers in one view
2. ⏳ **Automated alerting** - Slack/email for failures
3. ⏳ **Self-healing** - Auto-retry failed jobs
4. ⏳ **Deprecation process** - Formal way to sunset old scrapers

---

## Files Generated

| File | Purpose |
|------|---------|
| `/tmp/claude-scraper-inventory.md` | Full 256-line inventory (35 scrapers) |
| This document | Comprehensive audit and action plan |
| (Next) `validate-roster-data` skill | New monitoring tier |
| (Next) Scheduler job fixes | Create missing jobs |

---

## Key Learnings

1. **Monitoring scope matters** - Betting-focused monitoring missed roster issues
2. **Scheduled ≠ Running** - Jobs can be scheduled but fail silently
3. **GCS ≠ BigQuery** - Some scrapers bypass GCS, metrics misleading
4. **Documentation prevents drift** - Need operations runbooks, not just reference docs
5. **Automated testing needed** - Would catch scheduler/scraper disconnects

---

## Related Sessions

- **Session 70** - Discovered espn_roster config bug (disabled scraper still queried)
- **Session 70** - Created 3-layer config validation (pre-commit, runtime, skip disabled)
- **Session 70** - Comprehensive scraper audit (this document)

---

## Next Steps for Human Review

**Decisions Needed:**
1. Are bdl_games and bp_player_props deprecated? (If yes, remove from registry)
2. Should we invest in unified health dashboard? (High value, ~2-3 sessions)
3. Priority for monitoring tiers? (Roster data most critical)

**Approvals Needed:**
1. Create 4 new scheduler jobs (player_movement + 3 to be determined)
2. Update validate-daily skill with roster checks
3. Create validate-roster-data skill

---

*Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>*
