# Session 25 Comprehensive Plan - January 12, 2026

**Date:** January 12, 2026
**Previous Sessions:** 20-24 (Data Recovery, Slack Fix, Deployments)
**Focus:** Complete System Health Restoration + Outstanding Issues

---

## Executive Summary

This plan consolidates all outstanding work from Sessions 20-24 and provides a prioritized action plan. The system is mostly healthy with recent critical fixes, but several items need attention.

### Current System State

| Component | Status | Notes |
|-----------|--------|-------|
| Slack Alerting | ✅ Fixed | Session 23 - webhook updated |
| Gamebook/TDGS | ✅ Healthy | Jan 10-11 complete |
| BDL Box Scores | ⚠️ Gap | West coast timing issue (P2) |
| BettingPros | ❌ Down | API returning no data for Jan 12 (P3) |
| Prediction Worker | ✅ v3.4 | Session 24 - injury flagging deployed |
| Daily Health Summary | ✅ v1.1 | Session 24 - deployed |
| Jan 12 Games | ⏳ Pending | 6 games to verify |

---

## Phase 1: Immediate Verification (10 min)

### 1.1 Verify Jan 12 Overnight Processing

```bash
# 1. Check Gamebook Coverage (Expected: 6 games)
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.nbac_gamebook_player_stats\`
WHERE game_date = '2026-01-12'
GROUP BY 1"

# 2. Check TDGS Coverage (Expected: 6 games, 12 records)
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games, COUNT(*) as records
FROM \`nba-props-platform.nba_analytics.team_defense_game_summary\`
WHERE game_date = '2026-01-12'
GROUP BY 1"

# 3. Check BDL Box Scores (Expected: 4-6 games - west coast may be missing)
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date = '2026-01-12'
GROUP BY 1"

# 4. Check Workflow Executions
bq query --use_legacy_sql=false "
SELECT workflow_name, status, execution_time
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE execution_time > '2026-01-12 20:00:00'
ORDER BY execution_time DESC
LIMIT 20"

# 5. Check GCS Files
gsutil ls "gs://nba-scraped-data/nba-com/gamebooks-pdf/2026-01-12/" | wc -l
gsutil ls "gs://nba-scraped-data/ball-dont-lie/live-boxscores/2026-01-12/" | wc -l
```

### Success Criteria Phase 1

| Source | Expected | Status |
|--------|----------|--------|
| Gamebook | 6 games | ⏳ |
| TDGS | 6 games | ⏳ |
| BDL | 4-6 games | ⏳ |
| Workflows | All completed | ⏳ |
| GCS Gamebooks | 6 PDFs | ⏳ |

---

## Phase 2: Fix BDL West Coast Gap (20 min) - P2

### Root Cause (Confirmed in Session 23)

1. Daily boxscores scraper runs at 3:05 AM UTC (10:05 PM ET) - too early
2. Live scraper uses current ET date for folder path, not game date
3. After midnight, files go to next day's folder
4. Processor only looks in game date folder

### Option A: Add Late Boxscores Scrape (Recommended)

```bash
# Create new scheduler job for 2:05 AM ET run
gcloud scheduler jobs create http nba-bdl-boxscores-late \
    --schedule='5 7 * * *' \
    --time-zone='UTC' \
    --uri='https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape' \
    --http-method=POST \
    --headers='Content-Type=application/json' \
    --message-body='{"scraper": "bdl_box_scores", "group": "gcs"}' \
    --location=us-west2 \
    --oidc-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
    --description='BDL boxscores late scrape for west coast games (2 AM ET)'
```

### Option B: Fix Live Scraper Folder Logic (Better Long-term)

**Files to modify:**
- `scrapers/balldontlie/bdl_live_box_scores.py` - Use game date from API
- `scrapers/scraper_base.py:1164` - Default date assignment

**Current behavior:**
```python
self.opts["date"] = eastern_now.strftime("%Y-%m-%d")
```

**Needed:** Extract game date from API response and use for folder path.

### Verification After Fix

```bash
# Next day with west coast games, verify data appears
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM \`nba-props-platform.nba_raw.bdl_player_boxscores\`
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1"
```

---

## Phase 3: Player Normalization Backfill (30 min) - P1

### Issue

- 78% of historical predictions used default line_value=20
- Code fixed in Sessions 13B/15
- SQL patch file exists but not run

### Files

- Code fix: `data_processors/raw/espn/espn_team_roster_processor.py`
- SQL patch: `bin/patches/patch_player_lookup_normalization.sql`

### Execution

```bash
# 1. Review the patch first
cat bin/patches/patch_player_lookup_normalization.sql

# 2. Run the backfill SQL
bq query --use_legacy_sql=false < bin/patches/patch_player_lookup_normalization.sql

# 3. Verify changes
bq query --use_legacy_sql=false "
SELECT COUNT(*) as total,
       COUNTIF(line_value != 20) as custom_lines,
       COUNTIF(line_value = 20) as default_lines
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= '2024-01-01'"
```

### Impact

- ~6,000+ predictions need prop line re-matching
- May need to regenerate downstream analytics

---

## Phase 4: BettingPros API Investigation (20 min) - P3

### Current Errors

1. "No events found for date: 2026-01-12" (24 errors)
2. JSON decode errors (empty responses)
3. UTF-8 decode failures

### Investigation Steps

```bash
# 1. Check if data recovered for Jan 13
gsutil ls "gs://nba-scraped-data/bettingpros/events/2026-01-13/" | wc -l

# 2. Test API directly
curl -v "https://api.bettingpros.com/v3/events?sport=NBA&date=2026-01-13"

# 3. Check proxy configuration
grep -r "proxy" scrapers/bettingpros/

# 4. Check header profile
cat shared/utils/nba_header_utils.py | grep -A20 "bettingpros"

# 5. Check recent Cloud Logs
gcloud logging read 'resource.type="cloud_run_revision" AND "bettingpros"' --limit=20

# 6. Check for recent code changes
git log --oneline -10 -- scrapers/bettingpros/
```

### Potential Fixes

| Cause | Fix |
|-------|-----|
| Rate Limited | Add exponential backoff, reduce frequency |
| Proxy Issue | Test without proxy, rotate IPs |
| API Changed | Update endpoint/parsing |

### Impact Assessment

- **Severity:** P3 (secondary source)
- **Alternative:** Odds API is primary and working
- **Decision:** Monitor, fix if time permits

---

## Phase 5: ESPN Roster Scraper (45 min) - P1 Recurring

### Issue

- Only scrapes 2-3 teams instead of 30 on some days
- Blocks entire prediction pipeline
- Recurring: Sessions S7, S10, S12, S16

### Root Cause

Unknown - suspected ESPN API rate limiting or response issues.

### Investigation

```bash
# Check recent failures
gcloud logging read 'resource.type="cloud_run_revision" AND "espn" AND "roster"' --limit=50

# Check scraper code
cat scrapers/espn/espn_team_roster.py
```

### Recommended Fixes

1. **Add exponential backoff** - Handle rate limiting gracefully
2. **Add completeness validation** - Don't log "success" with 3/30 teams
3. **Add retry logic** - Retry failed teams
4. **Add fallback** - Use `nba_players_registry` if ESPN fails

### Files to Modify

- `scrapers/espn/espn_team_roster.py`
- Possibly `scrapers/scraper_base.py`

---

## Phase 6: Medium Priority Items (If Time)

### 6.1 Upcoming Context Fallbacks

- Current: 42% coverage when primary sources fail
- Need: Fallback chain for schedule and roster

```python
# Schedule fallback chain
nbac_schedule -> nba_reference.nba_schedule

# Roster fallback chain
espn_rosters -> nba_players_registry -> nbac_player_list
```

### 6.2 Circuit Breaker Lockout Duration

- Current: 7-day lockout after failures
- Recommended: 24 hours
- File: Check orchestration config

### 6.3 Live Export Staleness Alert

- Create Cloud Function to check if `today.json` is >4 hours old during game hours

---

## Known Accepted Gaps (No Action Needed)

| Gap | Reason |
|-----|--------|
| Play-In Tournament Games | 6 games (0.1%), all sources failed |
| 2021-22 Season Odds | Historical data never scraped, unrecoverable |
| West Coast BDL Games (Pre-Fix) | Will be fixed going forward |

---

## Deferred Features (Not Bugs)

These fields are **always 0 by design**:
- `opponent_strength_score`
- `pace_score`
- `usage_spike_score`
- `referee_adj`, `look_ahead_adj`, `travel_adj`

Active fields working:
- `fatigue_score` - 100% populated
- `shot_zone_mismatch_score` - 79% populated

---

## Session Completion Checklist

### Must Complete
- [ ] Jan 12 verification (Phase 1)
- [ ] Update handoff doc with results

### Should Complete
- [ ] BDL west coast gap fix (Phase 2)
- [ ] Player normalization backfill (Phase 3)

### Nice to Have
- [ ] BettingPros investigation (Phase 4)
- [ ] ESPN roster investigation (Phase 5)

---

## Quick Reference Commands

```bash
# Daily health check
curl https://daily-health-summary-f7p3g7f6ya-wl.a.run.app/

# Check prediction worker health
curl https://prediction-worker-f7p3g7f6ya-wl.a.run.app/health

# List all Cloud Scheduler jobs
gcloud scheduler jobs list --location=us-west2 --format='table(name,schedule,timeZone)'

# Check recent workflow executions
bq query --use_legacy_sql=false "
SELECT workflow_name, status, COUNT(*) as cnt
FROM \`nba-props-platform.nba_orchestration.workflow_executions\`
WHERE execution_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
GROUP BY 1, 2
ORDER BY 1"
```

---

## Related Documentation

- Session 23: `docs/09-handoff/2026-01-12-SESSION-23-HANDOFF.md`
- Session 24: `docs/09-handoff/2026-01-12-SESSION-24-HANDOFF.md`
- BDL Issue: `docs/09-handoff/2026-01-12-ISSUE-BDL-WEST-COAST-GAP.md`
- BettingPros Issue: `docs/09-handoff/2026-01-12-ISSUE-BETTINGPROS-API.md`
- Jan 12 Verification: `docs/09-handoff/2026-01-12-ISSUE-JAN12-VERIFICATION.md`
- Historical Audit: `docs/08-projects/current/historical-backfill-audit/`

---

*Created: January 12, 2026*
*Session: 25*
