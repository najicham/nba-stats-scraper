# Sonnet Investigation Complete - 2026-01-28

**Session**: Claude Sonnet 4.5
**Task**: Complete "Investigation Tasks for New Chat" from Opus handoff
**Status**: ✅ COMPLETE
**Time**: ~30 minutes

---

## What I Did

Completed all 5 investigation tasks from your handoff:

1. ✅ Checked lineups - Data exists, different approach than MLB
2. ✅ Checked schedule updates - Working via workflow
3. ✅ Checked for orphaned scrapers - None found
4. ✅ Audited NBA scheduler coverage vs MLB - Full comparison done
5. ✅ Identified missing schedulers - Found 2 critical gaps

---

## 🎯 Critical Discovery: Props Schedulers Exist!

**Your handoff said**: "No NBA odds scheduler - CRITICAL GAP"

**Reality**: **NBA props schedulers were created TODAY at 16:38 PT** (8 minutes after your session ended)

```bash
✅ nba-props-morning   (7 AM UTC)  - Created 2026-01-28T16:38:04Z
✅ nba-props-midday    (12 PM UTC) - Created 2026-01-28T16:38:06Z
✅ nba-props-pregame   (4 PM UTC)  - Created 2026-01-28T16:38:08Z
```

**Status**:
- ✅ All three schedulers ENABLED
- ⏱️ First run scheduled for tomorrow (Jan 29)
- 🎯 Endpoint: `https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props`
- 📦 Payload: `{"game_date": "today"}`

**Action needed**: Monitor tomorrow's execution to verify they work.

---

## Investigation Results Summary

### 1. Lineups ⚠️ Different Approach

**Checked**: Do we have lineup scraping? Is it scheduled?

**Found**:
- ❌ No dedicated lineup scraper in registry (MLB has `mlb_lineups`)
- ❌ No dedicated lineup scheduler (MLB has morning/pregame)
- ✅ BUT: `bigdataball_lineups` table has fresh data (4,156 records, latest: Jan 27)

**Conclusion**: Lineups extracted from BigDataBall workflow, not dedicated scraper. Working fine, but undocumented.

**Recommendation**: Document the source in operational runbook.

### 2. Schedule Updates ✅ Working

**Checked**: How does NBA schedule get updated?

**Found**:
- Scheduler: `daily-schedule-locker` at 10 AM ET (5 AM PT)
- Endpoint: `/generate-daily-schedule`
- 17 schedule tables in `nba_raw` (nbac_schedule_*)
- Different from MLB's direct scraper approach (workflow-based)

**Conclusion**: Working, but lacks validation (see gaps below).

### 3. Orphaned Scrapers ✅ None Found

**Checked**: Any scraper endpoints without schedulers?

**Found**:
- 37 scrapers available on `nba-scrapers` service
- 15 enabled workflows
- All appear to have triggers (schedulers or workflows)

**Conclusion**: No orphaned scrapers detected.

### 4. Scheduler Coverage Analysis ✅ Complete

**Checked**: Full MLB vs NBA comparison

**Results**:
- **MLB**: 20 schedulers with "mlb-" prefix
- **NBA**: 11 schedulers with "nba-" prefix + ~25 other jobs
- **Total system**: ~102 schedulers

**Key differences**:
- NBA uses workflow orchestration more than MLB
- NBA naming less consistent (mixed prefixes)
- Some MLB validators don't exist for NBA

### 5. Missing Schedulers ❌ Found 2 Critical Gaps

**Gap 1: No Gap Detection** 🔴
- MLB has: `mlb-gap-detection-daily` (runs 1 PM)
- NBA has: **NOTHING**
- Impact: No proactive detection of processing failures
- Would have caught props scheduler gap earlier!

**Gap 2: No Schedule Validation** 🔴
- MLB has: `mlb-schedule-validator-daily` (runs 11 AM)
- NBA has: **NOTHING**
- Impact: No validation of workflow-generated schedules
- Risk of schedule drift or errors going unnoticed

**Other Gaps** (Lower Priority):
- No prediction coverage validation (MLB has 4)
- No props quality monitoring (MLB has hourly)

---

## MLB-only Schedulers (No NBA Equivalent)

```
✅ mlb-freshness-checker-hourly    → NBA: nba-feature-staleness-monitor
❌ mlb-gap-detection-daily         → NBA: MISSING (CRITICAL)
⚠️  mlb-lineups-morning/pregame    → NBA: Different mechanism
✅ mlb-live-boxscores              → NBA: bdl-live-boxscores-*
❌ mlb-pitcher-props-validator     → NBA: No props validator
❌ mlb-prediction-coverage-*       → NBA: No coverage validation
✅ mlb-props-morning/pregame       → NBA: NOW EXISTS (created today)
⚠️  mlb-schedule-daily             → NBA: daily-schedule-locker
❌ mlb-schedule-validator-daily    → NBA: MISSING (CRITICAL)
✅ mlb-stall-detector-hourly       → NBA: stale-processor-monitor
```

**Legend**: ✅ Has equivalent | ⚠️ Different approach | ❌ Missing

---

## Action Items for Next Session

### P0 - Tomorrow Morning (Jan 29)

**Monitor new props schedulers**:
```bash
# 1. Check logs after 7 AM UTC
gcloud logging read \
  "resource.labels.service_name=nba-props-morning" \
  --limit=10

# 2. Verify data landed
bq query "SELECT game_date, COUNT(DISTINCT player_lookup)
FROM nba_raw.odds_api_player_points_props
WHERE game_date = '2026-01-29'
GROUP BY 1"

# 3. If failed, manually trigger
curl -X POST \
  "https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -d '{"game_date": "2026-01-29"}'
```

### P1 - This Week

**Create missing monitors**:

1. **NBA Gap Detection Job**
   - Adapt `monitoring/mlb/mlb_gap_detection.py`
   - Configure NBA sources (props, boxscores, schedule, lineups)
   - Deploy as Cloud Run Job
   - Create scheduler: `nba-gap-detection-daily` at 1 PM PT
   - See: `CREATE-MISSING-MONITORS.md` for step-by-step

2. **NBA Schedule Validator Job**
   - Create `monitoring/nba/nba_schedule_validator.py`
   - Validate workflow-generated schedules
   - Deploy as Cloud Run Job
   - Create scheduler: `nba-schedule-validator-daily` at 11 AM PT
   - See: `CREATE-MISSING-MONITORS.md` for details

3. **Documentation**
   - Document lineup data source (BigDataBall workflow)
   - Update operational runbook with all findings
   - Add scheduler audit checklist

---

## Data Verification Queries

### Check Props Data
```sql
-- Recent props (sparse but exists)
SELECT game_date, COUNT(DISTINCT player_lookup) as players
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date >= '2026-01-25'
GROUP BY 1
ORDER BY 1;

-- Results found:
-- 2026-01-25: 27 players
-- 2026-01-26: 88 players
-- 2026-01-27: 40 players
```

### Check Lineup Data
```sql
-- Lineups are current
SELECT
  COUNT(*) as lineup_count,
  MAX(game_date) as latest_game,
  MIN(game_date) as earliest_game
FROM `nba-props-platform.nba_raw.bigdataball_lineups`
WHERE game_date >= '2026-01-01';

-- Result: 4,156 lineups, latest: 2026-01-27
```

### Check Schedule Tables
```sql
-- Schedule tables exist (17 total)
SELECT table_id
FROM nba_raw.__TABLES__
WHERE table_id LIKE '%schedule%';
```

---

## Documents Created

I created 3 comprehensive documents in `docs/08-projects/current/2026-01-28-system-validation/`:

1. **NBA-SCHEDULER-GAP-ANALYSIS.md** (400+ lines)
   - Complete MLB vs NBA scheduler comparison
   - Detailed analysis of each component
   - All investigation queries documented
   - Prevention framework included

2. **INVESTIGATION-COMPLETE-SUMMARY.md**
   - Executive summary with findings
   - Action items prioritized (P0/P1/P2/P3)
   - Quick reference for what's working vs missing
   - Next steps clearly outlined

3. **CREATE-MISSING-MONITORS.md**
   - Step-by-step guide to create gap detection
   - Step-by-step guide to create schedule validator
   - Deployment commands
   - Testing procedures
   - Maintenance guidelines

---

## Key Statistics

| Metric | Count |
|--------|-------|
| Total schedulers (NBA + MLB) | ~102 |
| NBA schedulers with "nba-" prefix | 11 |
| Other NBA-related schedulers | ~25 |
| MLB schedulers | 20 |
| NBA scrapers in registry | 36 |
| MLB scrapers in registry | 28 |
| NBA schedule tables | 17 |

---

## Files Referenced

### Existing Code (Can Be Adapted)
- `monitoring/mlb/mlb_gap_detection.py` - MLB gap detector
- `monitoring/processors/gap_detection/` - Generic framework
- `deployment/cloud-run/mlb/validators/` - MLB validator configs
- `scrapers/registry.py` - NBA scraper registry

### BigQuery Tables Verified
- `nba_raw.odds_api_player_points_props` - Props data
- `nba_raw.bigdataball_lineups` - Lineup data
- `nba_raw.nbac_schedule_*` - Schedule tables (17)

---

## Prevention Framework

To avoid future scheduler gaps:

### Pre-deployment Checklist
- [ ] Cloud Run service deployed
- [ ] Pub/Sub trigger configured (if event-driven)
- [ ] **Cloud Scheduler job created** (if time-based) ← This was the gap
- [ ] Monitoring/alerting configured
- [ ] Listed in operational runbook
- [ ] Added to gap detection checks

### Quarterly Audit Command
```bash
# Find MLB schedulers without NBA equivalents
comm -23 \
  <(gcloud scheduler jobs list --format="value(name)" | grep "^mlb-" | sed 's/mlb-//' | sort) \
  <(gcloud scheduler jobs list --format="value(name)" | grep "^nba-" | sed 's/nba-//' | sort)
```

---

## Bottom Line

**What Changed Since Your Session**:
- Props schedulers were created (8 min after you ended)
- They haven't run yet (first run tomorrow)

**What's Working**:
- Props schedulers exist ✅
- Lineups data current ✅
- Schedule updates working ✅
- No orphaned scrapers ✅

**What's Missing**:
- Gap detection job ❌ (critical)
- Schedule validator ❌ (critical)
- Some monitoring coverage ⚠️ (nice to have)

**What to Do Next**:
1. Tomorrow: Monitor props schedulers
2. This week: Create gap detection + schedule validator
3. This week: Document lineup source

**Investigation Status**: ✅ COMPLETE

---

## Questions for You

1. **Props schedulers**: Did you create these, or did someone else? They appeared right after your session.

2. **Lineups**: Should we create a dedicated lineup scraper like MLB, or is the BigDataBall workflow approach preferred?

3. **Priorities**: Agree with P0/P1 prioritization? Or should we tackle gap detection immediately?

4. **Deployment**: Should I proceed with creating the gap detection and schedule validator jobs, or do you want to review the approach first?

---

**Ready for handoff back to you or ready to implement missing monitors.**
