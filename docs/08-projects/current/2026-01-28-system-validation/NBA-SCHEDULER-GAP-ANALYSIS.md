# NBA Scheduler Gap Analysis
**Date**: 2026-01-28
**Analyst**: Claude Sonnet 4.5
**Context**: Investigation tasks from Opus session handoff

---

## Executive Summary

**CRITICAL UPDATE**: The Opus handoff document stated "No NBA Odds Scheduler" as a critical gap. However, investigation reveals that **NBA props schedulers were created on 2026-01-28 at 16:38 PT** (just after the Opus session ended at 16:30 PT). The schedulers exist but haven't run yet.

### Key Findings
1. ✅ **NBA Props Schedulers NOW EXIST** - Created today, first run tomorrow
2. ⚠️ **Lineups**: No dedicated scheduler, but data exists (possibly from workflows)
3. ⚠️ **Schedule**: Uses workflow-based approach vs MLB's dedicated scheduler
4. ❌ **Missing Monitoring**: No NBA equivalents for gap detection, validation

---

## Detailed Scheduler Comparison: MLB vs NBA

### 1. Props/Odds Scraping ✅ NOW RESOLVED

| Aspect | MLB | NBA | Status |
|--------|-----|-----|--------|
| Morning scrape | `mlb-props-morning` (10:30 AM) | `nba-props-morning` (7 AM UTC) | ✅ Created 2026-01-28 |
| Midday scrape | `mlb-props-pregame` (12:30 PM) | `nba-props-midday` (12 PM UTC) | ✅ Created 2026-01-28 |
| Pregame scrape | - | `nba-props-pregame` (4 PM UTC) | ✅ Created 2026-01-28 |

**NBA Scheduler Details:**
```bash
# All created: 2026-01-28T16:38:04-08Z
nba-props-morning   → 0 7 * * *  (Etc/UTC)
nba-props-midday    → 0 12 * * * (Etc/UTC)
nba-props-pregame   → 0 16 * * * (Etc/UTC)

# Endpoint: https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props
# Payload: {"game_date": "today"}
# Service Account: 756957797294-compute@developer.gserviceaccount.com
```

**Next scheduled runs**: 2026-01-29

**Data Status:**
```sql
SELECT game_date, COUNT(DISTINCT player_lookup)
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= '2026-01-25'
GROUP BY 1;

-- Results:
-- 2026-01-25: 27 players
-- 2026-01-26: 88 players
-- 2026-01-27: 40 players
```

### 2. Lineups Scraping ⚠️ DIFFERENT APPROACH

| Aspect | MLB | NBA | Status |
|--------|-----|-----|--------|
| Morning lineups | `mlb-lineups-morning` (11 AM) | None | ⚠️ No dedicated scheduler |
| Pregame lineups | `mlb-lineups-pregame` (1 PM) | None | ⚠️ No dedicated scheduler |
| Scraper exists | ✅ `mlb_lineups` in registry | ❌ No NBA lineup scraper | 🟡 INVESTIGATE |

**NBA Lineup Data:**
- Table: `nba_raw.bigdataball_lineups` EXISTS
- Latest data: 2026-01-27 (4,156 records since Jan 2)
- Data is being collected despite no dedicated scheduler
- **Hypothesis**: Lineups extracted from play-by-play data or workflows

**MLB Approach:**
```python
# scrapers/mlb/mlbstatsapi/mlb_lineups.py
"mlb_lineups": ("scrapers.mlb.mlbstatsapi.mlb_lineups", "MlbLineupsScraper")
```

**NBA Registry**: No `nba_lineups` or lineup scraper found

**Recommendation**:
- ✅ Current approach working (lineups are fresh)
- 🔍 Document where lineups come from (likely BigDataBall workflow)
- 💡 Consider dedicated scraper if lineups needed earlier in day

### 3. Schedule Management ⚠️ WORKFLOW-BASED

| Aspect | MLB | NBA | Status |
|--------|-----|-----|--------|
| Schedule scraper | `mlb-schedule-daily` (10 AM) | None | ⚠️ Different approach |
| Schedule workflow | None | `daily-schedule-locker` (10 AM ET) | ✅ Working |
| Validation | `mlb-schedule-validator-daily` (11 AM) | None | ❌ Missing |

**NBA Schedule Approach:**
```yaml
daily-schedule-locker:
  schedule: 0 10 * * *  # 10 AM ET = 5 AM PT
  timezone: America/New_York
  endpoint: /generate-daily-schedule
  description: "Generate daily expected workflow schedule"
```

**Schedule Tables:**
- 17 schedule-related tables in `nba_raw` (nbac_schedule_*)
- Latest: `nbac_schedule_source_daily`
- Approach: Workflow-based vs direct scraper

**MLB Schedule Scraper:**
```python
"mlb_schedule": ("scrapers.mlb.mlbstatsapi.mlb_schedule", "MlbScheduleScraper")
```

**Recommendation**:
- ✅ NBA workflow approach appears working
- ❌ Missing validation (see #4 below)

### 4. Monitoring & Validation ❌ CRITICAL GAPS

| Category | MLB Scheduler | NBA Equivalent | Gap |
|----------|--------------|----------------|-----|
| Gap Detection | `mlb-gap-detection-daily` | None | ❌ MISSING |
| Schedule Validation | `mlb-schedule-validator-daily` | None | ❌ MISSING |
| Freshness Checking | `mlb-freshness-checker-hourly` | `nba-feature-staleness-monitor` | ✅ Exists |
| Stall Detection | `mlb-stall-detector-hourly` | `stale-processor-monitor` | ✅ Exists |

**Critical Missing Monitors:**

#### 4.1 Gap Detection
MLB has daily job to detect missing data. NBA lacks this.

**MLB Implementation:**
```yaml
mlb-gap-detection-daily:
  schedule: 0 13 * * *  # 1 PM
  type: Cloud Run Job
```

**Recommendation**: Create `nba-gap-detection-daily` following MLB pattern

#### 4.2 Schedule Validator
MLB validates schedule daily. NBA has no equivalent.

**MLB Implementation:**
```yaml
mlb-schedule-validator-daily:
  schedule: 0 11 * * *  # 11 AM
  type: Cloud Run Job
```

**Recommendation**: Create `nba-schedule-validator-daily` to validate workflow-generated schedules

### 5. Prediction & Grading ✅ ADEQUATE COVERAGE

| Category | MLB | NBA | Status |
|----------|-----|-----|--------|
| Prediction Generation | `mlb-predictions-generate` | `morning-predictions`, `same-day-predictions` | ✅ Covered |
| Grading | `mlb-grading-daily` | `grading-daily`, `grading-morning` | ✅ Covered |
| Coverage Validation | `mlb-prediction-coverage-*` (4 jobs) | None | ⚠️ Consider adding |

**NBA Has:**
- `morning-predictions` (not visible in scheduler list - may be workflow-based)
- `same-day-predictions` (not visible - may be workflow-based)
- Grading alerts: `nba-grading-alerts-daily`

**Note**: NBA may use workflow orchestration vs dedicated schedulers

### 6. Live Data ✅ ADEQUATE COVERAGE

| Category | MLB | NBA | Status |
|----------|-----|-----|--------|
| Live Boxscores | `mlb-live-boxscores` | `bdl-live-boxscores-evening`, `bdl-live-boxscores-late` | ✅ Covered |
| Overnight Results | `mlb-overnight-results` | Catchup jobs | ✅ Covered |

---

## Complete Scheduler Inventory

### NBA Schedulers (8 visible with "nba-" prefix + many others)
```
nba-bdl-boxscores-late
nba-confidence-drift-monitor
nba-daily-summary-prod
nba-daily-summary-scheduler
nba-env-var-check-prod
nba-feature-staleness-monitor
nba-grading-alerts-daily
nba-monitoring-alerts
nba-props-morning         ← CREATED TODAY
nba-props-midday          ← CREATED TODAY
nba-props-pregame         ← CREATED TODAY
```

### Other NBA-related Schedulers (not prefixed with "nba-")
```
bdl-boxscores-yesterday-catchup
bdl-catchup-afternoon
bdl-catchup-evening
bdl-catchup-midday
bdl-injuries-hourly
bdl-live-boxscores-evening
bdl-live-boxscores-late
boxscore-completeness-check
br-rosters-batch-daily
cleanup-processor
daily-data-completeness-check
daily-health-check-8am-et
daily-pipeline-health-summary
daily-reconciliation
daily-schedule-locker
daily-yesterday-analytics
espn-roster-processor-daily
execute-workflows
fix-stale-schedule
game-coverage-alert
grading-delay-alert-job
line-quality-self-heal-job
live-export-evening
live-export-late-night
live-freshness-monitor
master-controller-hourly
missing-prediction-check
ml-feature-store-daily
```

**Total NBA-related schedulers: ~35+**

### MLB Schedulers (20 total)
```
mlb-freshness-checker-hourly
mlb-gap-detection-daily
mlb-grading-daily
mlb-lineups-morning
mlb-lineups-pregame
mlb-live-boxscores
mlb-overnight-results
mlb-pitcher-props-validator-4hourly
mlb-prediction-coverage-postgame
mlb-prediction-coverage-pregame
mlb-prediction-coverage-validator-postgame
mlb-prediction-coverage-validator-pregame
mlb-predictions-generate
mlb-props-morning
mlb-props-pregame
mlb-schedule-daily
mlb-schedule-validator-daily
mlb-shadow-grading-daily
mlb-shadow-mode-daily
mlb-stall-detector-hourly
```

---

## Scraper Services

### NBA Services
1. **nba-scrapers** (`https://nba-scrapers-f7p3g7f6ya-wl.a.run.app`)
   - 37 scrapers available
   - Orchestration with 15 enabled workflows
   - Version 2.3.0
   - Workflows include: `betting_lines`, `injury_discovery`, `morning_operations`, etc.

2. **nba-phase1-scrapers** (`https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app`)
   - Dedicated scraper service
   - Used by props schedulers

### MLB Services
1. **mlb-phase1-scrapers** (`https://mlb-phase1-scrapers-f7p3g7f6ya-wl.a.run.app`)
   - Used by lineups, props, schedule scrapers

---

## Scraper Registry Analysis

### NBA Scrapers (36 total in registry)
- Odds API: 7 scrapers
- Ball Don't Lie: 7 scrapers (including live boxscores)
- NBA.com: 13 scrapers
- ESPN: 3 scrapers
- BettingPros: 2 scrapers
- Basketball Reference: 1 scraper
- BigDataBall: 2 scrapers

**Notable**: No dedicated lineup scraper in registry

### MLB Scrapers (28 total in registry)
- Ball Don't Lie: 13 scrapers
- MLB Stats API: 3 scrapers (schedule, **lineups**, game_feed)
- Odds API: 8 scrapers
- External: 3 scrapers (weather, ballpark, umpires)
- Statcast: 1 scraper

**Key Difference**: MLB has dedicated `mlb_lineups` scraper

---

## Identified Gaps

### 🔴 Critical (Action Required)

**NONE** - Props schedulers were created today

### 🟡 High Priority (Investigate)

1. **NBA Lineups Source**
   - Data exists and is fresh
   - No dedicated scraper or scheduler
   - Need to document the source (workflow vs scraper)

2. **NBA Gap Detection**
   - MLB has daily gap detection
   - NBA lacks systematic gap detection
   - Could have caught props scheduler gap earlier

3. **NBA Schedule Validation**
   - MLB validates schedule daily
   - NBA workflow generates schedule but no validation
   - Risk of schedule drift or errors

### 🟠 Medium Priority (Consider)

4. **Prediction Coverage Validation**
   - MLB has 4 validation jobs
   - NBA has none
   - May help catch prediction gaps earlier

5. **Props-specific Monitoring**
   - MLB has `mlb-pitcher-props-validator-4hourly`
   - NBA could benefit from similar props quality monitoring

---

## Recommendations

### Immediate Actions (P0)

1. **Monitor New Props Schedulers**
   ```bash
   # Check tomorrow (Jan 29) that schedulers ran successfully
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-props-morning" --limit=5

   # Verify data landed
   bq query "SELECT game_date, COUNT(DISTINCT player_lookup) FROM nba_raw.odds_api_player_points_props WHERE game_date = '2026-01-29' GROUP BY 1"
   ```

2. **Manually trigger props scrape for today** (if needed for Jan 28 games)
   ```bash
   curl -X POST "https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape-odds-api-props" \
     -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     -H "Content-Type: application/json" \
     -d '{"game_date": "2026-01-28"}'
   ```

### Short-term Actions (P1)

3. **Create Gap Detection Job**
   - Follow MLB pattern
   - Create Cloud Run Job: `nba-gap-detection-daily`
   - Schedule: Daily at 1 PM PT
   - Check for missing: boxscores, props, lineups, predictions

4. **Create Schedule Validator**
   - Validate workflow-generated schedules
   - Create Cloud Run Job: `nba-schedule-validator-daily`
   - Schedule: Daily at 11 AM PT
   - Verify game counts, dates, team matchups

5. **Document Lineup Source**
   - Investigate BigDataBall workflow
   - Document in operational runbook
   - Decide if dedicated scraper needed

### Long-term Improvements (P2)

6. **Prediction Coverage Validation**
   - Create pregame/postgame coverage validators
   - Alert on missing predictions
   - Track coverage metrics over time

7. **Props Quality Monitoring**
   - Hourly props validator (like MLB pitcher props)
   - Check for stale lines, missing players
   - Alert on quality issues

8. **Unified Scheduler Naming**
   - NBA uses mixed naming (some with "nba-" prefix, some without)
   - MLB consistently uses "mlb-" prefix
   - Consider standardizing for easier management

---

## Prevention Framework

### Pre-deployment Checklist

For every new scraper/processor:
- [ ] Cloud Run service deployed
- [ ] Pub/Sub trigger configured (if event-driven)
- [ ] **Cloud Scheduler job created** (if time-based)
- [ ] Monitoring/alerting configured
- [ ] Listed in operational runbook
- [ ] Added to gap detection checks

### Periodic Audit Command

Run quarterly to check for scheduler gaps:
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

---

## MLB-only Schedulers (Not in NBA)

These MLB schedulers have no direct NBA equivalent:
```
freshness-checker-hourly          → NBA uses nba-feature-staleness-monitor
gap-detection-daily               → ❌ MISSING
grading-daily                     → NBA has different grading approach
lineups-morning                   → ⚠️ NBA lineups via different mechanism
lineups-pregame                   → ⚠️ NBA lineups via different mechanism
live-boxscores                    → NBA has bdl-live-boxscores-evening/late
overnight-results                 → NBA has catchup jobs
pitcher-props-validator-4hourly   → ❌ NBA could use similar
prediction-coverage-*             → ❌ NBA has no coverage validation
predictions-generate              → NBA likely workflow-based
schedule-daily                    → NBA uses daily-schedule-locker workflow
schedule-validator-daily          → ❌ MISSING
shadow-grading-daily              → NBA may not use shadow mode
shadow-mode-daily                 → NBA may not use shadow mode
stall-detector-hourly             → NBA has stale-processor-monitor
```

---

## Next Steps

1. ✅ **DONE**: Audit NBA scheduler coverage (this document)
2. **TODO**: Monitor tomorrow's props scheduler runs
3. **TODO**: Create gap detection job
4. **TODO**: Create schedule validator job
5. **TODO**: Document lineup data source
6. **TODO**: Update operational runbook with all findings

---

## Appendix: Investigation Queries

### Check Lineup Data Freshness
```sql
SELECT
  COUNT(*) as lineup_count,
  MAX(game_date) as latest_game,
  MIN(game_date) as earliest_game
FROM `nba-props-platform.nba_raw.bigdataball_lineups`
WHERE game_date >= '2026-01-01';

-- Result: 4,156 lineups, latest 2026-01-27
```

### Check Props Data
```sql
SELECT
  game_date,
  COUNT(DISTINCT player_lookup) as player_count
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date >= '2026-01-25'
GROUP BY 1
ORDER BY 1;
```

### List All Schedulers
```bash
gcloud scheduler jobs list --location=us-west2 --format="table(name,schedule,httpTarget.uri)"
```

### Check Scraper Service Health
```bash
curl -s "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"
```

---

**End of Analysis**
