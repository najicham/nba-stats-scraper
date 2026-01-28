# Investigation Complete: NBA Scheduler Gap Analysis

**Date**: 2026-01-28
**Investigator**: Claude Sonnet 4.5
**Task**: Complete "Investigation Tasks for New Chat" from Opus handoff

---

## Executive Summary

✅ **Investigation Complete**

**Major Discovery**: The Opus handoff document stated there were "No NBA Odds Schedulers" - this was TRUE at the time of the Opus session (ended ~16:30 PT), but **NBA props schedulers were created at 16:38 PT on 2026-01-28**, just 8 minutes after the Opus session ended.

### Status at a Glance

| Component | Status | Notes |
|-----------|--------|-------|
| **Props Schedulers** | ✅ **RESOLVED** | Created 2026-01-28 at 16:38 PT |
| **Lineups** | ⚠️ **Different Approach** | Data exists, no dedicated scheduler |
| **Schedule** | ✅ **Working** | Workflow-based approach |
| **Gap Detection** | ❌ **MISSING** | MLB has it, NBA doesn't |
| **Schedule Validation** | ❌ **MISSING** | MLB has it, NBA doesn't |

---

## Investigation Results

### 1. Props/Odds Schedulers ✅ FOUND & CREATED

**Opus Handoff Stated**: "No NBA odds scheduler - critical gap"

**Reality**: Schedulers were created TODAY (2026-01-28) at 16:38:04 UTC

**Discovered Schedulers**:
```bash
nba-props-morning    # Schedule: 0 7 * * * (Etc/UTC)
nba-props-midday     # Schedule: 0 12 * * * (Etc/UTC)
nba-props-pregame    # Schedule: 0 16 * * * (Etc/UTC)
```

**Configuration**:
- Endpoint: `https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props`
- Payload: `{"game_date": "today"}`
- Service Account: `756957797294-compute@developer.gserviceaccount.com`
- Status: ENABLED
- Next Run: 2026-01-29 07:00:00 UTC

**Data Verification**:
```sql
-- Recent props data exists (but sparse)
SELECT game_date, COUNT(DISTINCT player_lookup)
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= '2026-01-25'
GROUP BY 1;
-- Results: Jan 25: 27 players, Jan 26: 88, Jan 27: 40
```

**Conclusion**: The schedulers now exist but haven't run yet (first run tomorrow). Some odds data exists from other triggers/manual runs.

### 2. Lineups ⚠️ DIFFERENT APPROACH

**Checked For**: Dedicated lineup schedulers (like MLB has)

**Found**:
- ❌ No NBA lineup scraper in registry
- ❌ No dedicated lineup scheduler
- ✅ BUT: `bigdataball_lineups` table HAS recent data

**Data Status**:
```sql
-- Lineups ARE being collected
SELECT COUNT(*), MAX(game_date), MIN(game_date)
FROM nba_raw.bigdataball_lineups
WHERE game_date >= '2026-01-01';
-- Result: 4,156 lineups, latest: 2026-01-27
```

**MLB Comparison**:
- MLB has `mlb_lineups` scraper in registry
- MLB has schedulers: `mlb-lineups-morning`, `mlb-lineups-pregame`

**Hypothesis**: NBA lineups are extracted from:
- BigDataBall play-by-play data (scraped via workflows)
- Different workflow-based approach vs MLB's dedicated scraper

**Conclusion**: Current approach is working (data is fresh). No immediate action needed, but should document the source.

### 3. Schedule Updates ✅ WORKING

**Checked For**: Dedicated schedule scraper/scheduler

**Found**:
- Scheduler: `daily-schedule-locker` at 10 AM ET (5 AM PT)
- Endpoint: `/generate-daily-schedule`
- Description: "Generate daily expected workflow schedule"
- 17 schedule-related tables in `nba_raw` (nbac_schedule_*)

**MLB Comparison**:
- MLB has `mlb-schedule-daily` scheduler
- MLB has dedicated scraper: `mlb_schedule` in registry

**Conclusion**: NBA uses workflow-based schedule generation vs MLB's direct scraper. Both approaches work, but NBA lacks validation (see #4).

### 4. Missing: Gap Detection ❌

**Checked For**: Daily gap detection job (like MLB)

**Found**:
- MLB has: `mlb-gap-detection-daily` (runs 1 PM)
- NBA has: **NOTHING**
- Existing code: `monitoring/mlb/mlb_gap_detection.py` (can be adapted)

**Why This Matters**:
- Gap detection would have caught the missing props scheduler earlier
- Proactively alerts on processing failures
- Critical for production reliability

**Recommendation**: Create `nba-gap-detection-daily` job

### 5. Missing: Schedule Validation ❌

**Checked For**: Daily schedule validator (like MLB)

**Found**:
- MLB has: `mlb-schedule-validator-daily` (runs 11 AM)
- NBA has: **NOTHING**
- Existing code: `deployment/cloud-run/mlb/validators/mlb-schedule-validator.yaml`

**Why This Matters**:
- Validates schedule completeness and accuracy
- Catches schedule drift or errors
- Essential for workflow-based approach

**Recommendation**: Create `nba-schedule-validator-daily` job

### 6. Other Findings

**Monitoring Coverage**:
- ✅ NBA has: `nba-feature-staleness-monitor` (like MLB freshness checker)
- ✅ NBA has: `stale-processor-monitor` (like MLB stall detector)
- ❌ NBA lacks: Prediction coverage validation (MLB has 4 validators)

**Scraper Services**:
- `nba-scrapers` (f7p3g7f6ya-wl.a.run.app): 37 scrapers, 15 workflows
- `nba-phase1-scrapers` (756957797294.us-west2.run.app): Used by props schedulers

---

## Comparison: MLB vs NBA Schedulers

### Scheduler Count
- **MLB**: 20 schedulers with "mlb-" prefix
- **NBA**: 11 schedulers with "nba-" prefix + ~25 other NBA-related jobs
- **Total**: ~102 schedulers across both sports

### MLB Schedulers Not in NBA
```
✅ mlb-freshness-checker-hourly    → NBA: nba-feature-staleness-monitor
❌ mlb-gap-detection-daily         → NBA: MISSING
✅ mlb-grading-daily                → NBA: Different approach
⚠️  mlb-lineups-morning/pregame    → NBA: Different mechanism
✅ mlb-live-boxscores              → NBA: bdl-live-boxscores-*
✅ mlb-overnight-results           → NBA: Catchup jobs
❌ mlb-pitcher-props-validator     → NBA: No props validator
❌ mlb-prediction-coverage-*       → NBA: No coverage validation
✅ mlb-predictions-generate        → NBA: Workflow-based
✅ mlb-props-morning/pregame       → NBA: NOW EXISTS (created today)
⚠️  mlb-schedule-daily             → NBA: daily-schedule-locker
❌ mlb-schedule-validator-daily    → NBA: MISSING
⚠️  mlb-shadow-*                   → NBA: May not use shadow mode
✅ mlb-stall-detector-hourly       → NBA: stale-processor-monitor
```

**Legend**:
- ✅ NBA has equivalent
- ⚠️ NBA has different approach
- ❌ NBA is missing this

---

## Action Items

### P0 - Monitor New Schedulers (Tomorrow)

**Due**: 2026-01-29 morning

1. **Verify props schedulers ran successfully**
   ```bash
   # Check logs after 7 AM UTC
   gcloud logging read \
     "resource.type=cloud_run_revision AND resource.labels.service_name=nba-props-morning" \
     --limit=10 \
     --format=json
   ```

2. **Verify data landed in BigQuery**
   ```bash
   bq query --use_legacy_sql=false \
     "SELECT game_date, COUNT(DISTINCT player_lookup) as players
      FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
      WHERE game_date = '2026-01-29'
      GROUP BY 1"
   ```

3. **If schedulers failed**, manually trigger:
   ```bash
   curl -X POST \
     "https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"game_date": "2026-01-29"}'
   ```

### P1 - Create Missing Monitors (This Week)

**Due**: Within 1 week

4. **Create NBA Gap Detection Job**
   - Adapt `monitoring/mlb/mlb_gap_detection.py` for NBA
   - Configure NBA data sources (props, boxscores, lineups, etc.)
   - Deploy as Cloud Run Job
   - Create scheduler: `nba-gap-detection-daily` (1 PM PT)
   - Test with recent dates

5. **Create NBA Schedule Validator**
   - Adapt MLB schedule validator for NBA
   - Validate workflow-generated schedules
   - Deploy as Cloud Run Job
   - Create scheduler: `nba-schedule-validator-daily` (11 AM PT)
   - Test with today's schedule

### P2 - Documentation (This Week)

**Due**: Within 1 week

6. **Document Lineup Source**
   - Investigate BigDataBall workflow
   - Document how lineups are extracted
   - Add to operational runbook
   - Decide if dedicated scraper is needed

7. **Update Operational Runbook**
   - List all NBA schedulers
   - Document workflow-based approaches
   - Add scheduler audit checklist
   - Document prevention framework

8. **Create Scheduler Audit Script**
   - Script to compare MLB vs NBA schedulers
   - Auto-detect missing equivalents
   - Run quarterly to catch gaps

### P3 - Long-term Improvements (Future)

9. **Prediction Coverage Validation**
   - Create pregame/postgame coverage validators
   - Alert on missing predictions
   - Track coverage metrics

10. **Props Quality Monitoring**
    - Hourly props validator (like MLB)
    - Check for stale lines, missing players
    - Quality alerts

11. **Unified Scheduler Naming**
    - Standardize all NBA schedulers with "nba-" prefix
    - Update documentation
    - Easier to audit and manage

---

## Files Investigated

### Scraper Configuration
- `scrapers/registry.py` - NBA scraper registry (36 scrapers)
- `scrapers/mlb/registry.py` - MLB scraper registry (28 scrapers)

### Existing Monitoring
- `monitoring/mlb/mlb_gap_detection.py` - MLB gap detector (can adapt)
- `monitoring/processors/gap_detection/` - Generic gap detection framework
- `deployment/cloud-run/mlb/validators/` - MLB validator configs

### BigQuery Tables
- `nba_raw.odds_api_player_points_props` - Props data
- `nba_raw.bigdataball_lineups` - Lineup data
- `nba_raw.nbac_schedule_*` - Schedule tables (17 total)

---

## Prevention Framework

### Pre-deployment Checklist
For every new scraper/processor:
- [ ] Cloud Run service deployed
- [ ] Pub/Sub trigger configured (if event-driven)
- [ ] **Cloud Scheduler job created** (if time-based) ← This was missing
- [ ] Monitoring/alerting configured
- [ ] Listed in operational runbook
- [ ] Added to gap detection checks

### Periodic Audit Command
Run quarterly:
```bash
# Find MLB schedulers without NBA equivalents
comm -23 \
  <(gcloud scheduler jobs list --format="value(name)" | grep "^mlb-" | sed 's/mlb-//' | sort) \
  <(gcloud scheduler jobs list --format="value(name)" | grep "^nba-" | sed 's/nba-//' | sort)
```

### Documentation Requirements
- Operational runbook must list ALL schedulers
- Each scraper must document its scheduler (if any)
- Workflow orchestration must be clearly documented
- Differences from MLB approach must be noted

---

## Related Documents

- **Detailed Analysis**: `NBA-SCHEDULER-GAP-ANALYSIS.md`
- **Opus Handoff**: `../../09-handoff/2026-01-28-OPUS-SESSION-HANDOFF.md`
- **Validation Report**: `VALIDATION-REPORT.md`

---

## Summary for User

**What I Found**:
1. ✅ NBA props schedulers **DO EXIST** - created today at 16:38 PT (8 min after Opus session)
2. ⚠️ Lineups work differently in NBA - data exists but no dedicated scheduler
3. ✅ Schedule updates working via workflow approach
4. ❌ Gap detection is **MISSING** (MLB has it)
5. ❌ Schedule validation is **MISSING** (MLB has it)

**What Needs to Be Done**:
1. **Tomorrow**: Monitor props schedulers' first run
2. **This week**: Create gap detection and schedule validation jobs
3. **This week**: Document lineup source and update runbook

**What Doesn't Need to Be Done**:
- ❌ Don't create props schedulers (they exist now)
- ❌ Don't create lineup schedulers (different approach working)
- ❌ Don't create schedule scrapers (workflow approach working)

**Key Takeaway**: The system is mostly healthy. The props scheduler gap was resolved today. The main missing pieces are **monitoring/validation jobs** to catch future gaps early.

---

**Investigation Status**: ✅ COMPLETE
