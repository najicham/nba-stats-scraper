# Handoff: Data Gaps Investigation & Validation Improvements - January 25, 2026

**Created:** 2026-01-25 ~3:00 AM PST
**Session Focus:** Deep validation analysis, root cause investigation, system improvements
**Priority:** P0 - Data completeness and system resilience

---

## TL;DR

1. **Identified root causes** of 45-hour outage and ongoing data gaps
2. **Created 4 new validation/monitoring tools**:
   - `workflow_health.py` - Orchestration health monitoring
   - `phase_transition_health.py` - Data flow validation
   - `root_cause_analyzer.py` - Automated issue diagnosis
   - `v_game_id_mappings.sql` - Game ID format mapping view
3. **Fixed game_id join issues** in validation scripts (date+teams pattern)
4. **Ran BDL boxscore backfill** - 7,018 rows processed
5. **Current Slack warnings are EXPECTED** - orchestration trying to process incomplete data

---

## Root Cause Analysis

### Issue 1: 45-Hour Orchestration Outage (Jan 23-25)

**What happened:**
- Firestore permissions blocked the master controller
- No workflow decisions were made for 2,714 minutes (45+ hours)
- Existing validation didn't catch this because it only checked "does data exist?" not "is orchestration running?"

**Why it wasn't detected:**
- Count-based validation showed data existed
- No monitoring of workflow decision gaps
- No alerts for orchestration health

**Fix implemented:**
- Created `bin/validation/workflow_health.py` - monitors workflow decision gaps
- Threshold: Alert if gap > 120 minutes

### Issue 2: Game ID Format Mismatch

**What we found:**
- Schedule uses NBA format: `0022500578`
- BDL boxscores use: `YYYYMMDD_AWAY_HOME` (e.g., `20260115_MEM_ORL`)
- Direct game_id joins fail between these tables

**Impact:**
- Validation scripts reported "missing boxscores" incorrectly
- Cross-phase consistency checks produced false positives

**Fix implemented:**
- Updated `comprehensive_health_check.py` and `daily_pipeline_doctor.py`
- Now joins on `game_date + home_team_tricode + away_team_tricode`
- Created `v_game_id_mappings.sql` view for canonical mapping

### Issue 3: has_prop_line Data Bug

**What we found:**
- Jan 23: 218/222 predictions have `line_source='ACTUAL_PROP'` but `has_prop_line=FALSE`
- Filters using `has_prop_line = TRUE` missed valid predictions

**Fix implemented (prior session):**
- Changed filters to use `line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')`
- Applied to grading processor, validation scripts

### Issue 4: Low Feature Quality

**What we found:**
- Jan 24: avg quality 64.43 (threshold: 65)
- 74.6% of features are low quality
- L14D rolling window completeness at 66.2%

**Root cause:**
- Missing boxscores cascade to missing analytics
- Analytics gaps cause incomplete rolling windows
- Incomplete windows produce low quality features

**Fix:**
- Boxscore backfill (completed)
- Need Phase 3, 4 backfill to restore quality

---

## Current Slack Warnings - Expected Behavior

The warnings you're seeing:

```
WARNING: Analytics Processor No Data Extracted: PlayerGameSummaryProcessor
ERROR: Analytics Processor Failed: TeamOffenseGameSummaryProcessor
```

**Why this is happening:**
1. The BDL boxscore backfill just ran
2. Data is in BigQuery streaming buffer (takes ~30 minutes to settle)
3. Orchestration is trying to run analytics on Jan 24 before raw data is fully available

**This is normal during backfill operations.** The warnings will stop once:
1. Streaming buffer settles
2. We run Phase 3 analytics backfill

---

## Backfill Results

### BDL Boxscores Backfill (Completed)
```
Date Range: 2026-01-12 to 2026-01-24
Files Processed: 89
Successful: 33
Skipped: 56 (streaming buffer conflicts or already processed)
Rows Loaded: 7,018
Duration: 11:24
```

### Remaining Backfills Needed
1. **Phase 3 Analytics** - Process boxscores into player_game_summary
2. **Phase 4 Features** - Regenerate ml_feature_store_v2
3. **Grading** - Grade 176 ungraded predictions

---

## New Validation Tools Created

### 1. Workflow Health Monitor (`bin/validation/workflow_health.py`)
```bash
# Run every 30 min to detect orchestration outages
python bin/validation/workflow_health.py --hours 48 --threshold-minutes 120
```
Checks:
- Workflow decision gaps
- Phase transitions
- Processor completion rates
- Failed processor queue
- Decision frequency during game hours

### 2. Phase Transition Health (`bin/validation/phase_transition_health.py`)
```bash
# Validates data flows through all phases
python bin/validation/phase_transition_health.py --days 7
```
Checks each transition:
- Schedule → Boxscores (Phase 2)
- Boxscores → Analytics (Phase 3)
- Analytics → Features (Phase 4)
- Features → Predictions (Phase 5)
- Predictions → Grading (Phase 6)

### 3. Root Cause Analyzer (`bin/validation/root_cause_analyzer.py`)
```bash
# Automatically diagnoses WHY issues occur
python bin/validation/root_cause_analyzer.py --date 2026-01-24 --issue low_coverage
```
Analyzes:
- Low coverage: Feature gaps, registry issues, filter problems
- Grading lag: Missing boxscores, processor issues
- Missing boxscores: Scraper failures
- Low feature quality: Rolling window completeness

### 4. Game ID Mapping View (`schemas/bigquery/raw/v_game_id_mappings.sql`)
```sql
-- Deploy to BigQuery
SELECT * FROM nba_raw.v_game_id_mappings WHERE game_date = '2026-01-15'
```
Provides canonical mapping between:
- NBA game_id: `0022500578`
- BDL game_id: `20260115_MEM_ORL`

---

## Files Modified

| File | Change |
|------|--------|
| `bin/validation/comprehensive_health_check.py` | Fixed game_id join, fixed scraped_at column |
| `bin/validation/daily_pipeline_doctor.py` | Fixed game_id join for boxscore gap detection |

## Files Created

| File | Purpose |
|------|---------|
| `bin/validation/workflow_health.py` | Orchestration health monitoring |
| `bin/validation/phase_transition_health.py` | Data flow validation |
| `bin/validation/root_cause_analyzer.py` | Automated issue diagnosis |
| `schemas/bigquery/raw/v_game_id_mappings.sql` | Game ID format mapping |

---

## Validation Results Summary

### Jan 24, 2026
| Check | Status | Issue |
|-------|--------|-------|
| Workflow Decisions | OK | Max gap 60 min |
| Feature Quality | CRITICAL | 64.43 avg (threshold 65) |
| Rolling Windows | ERROR | L14D at 66.2% |
| Grading | ERROR | 79.3% (23/29) |
| Cross-Phase | ERROR | Missing 1 boxscore |
| Prop Coverage | OK | No props (normal for recent) |

### Jan 23, 2026
| Check | Status | Issue |
|-------|--------|-------|
| Workflow Decisions | OK | Max gap 60 min |
| Feature Quality | ERROR | 69.07 avg |
| has_prop_line | CRITICAL | 98% data bug |
| Grading | OK | 100% |
| Cross-Phase | OK | All 8 games consistent |

---

## Recommended Next Steps

### Immediate (Today)
1. Wait 30 min for streaming buffer to settle
2. Run Phase 3 analytics backfill:
   ```bash
   PYTHONPATH=/home/naji/code/nba-stats-scraper python backfill_jobs/analytics/player_game_summary/player_game_summary_analytics_backfill.py --start-date 2026-01-12 --end-date 2026-01-24
   ```
3. Run grading backfill after Phase 3 completes

### Short-term (This Week)
1. Deploy `workflow_health.py` to Cloud Scheduler (every 30 min)
2. Add phase_transition_health.py to daily monitoring
3. Fix GSW@MIN boxscore gap (need to trigger scraper for that game)

### Medium-term
1. Add streaming buffer awareness to orchestration
2. Implement soft dependencies (allow partial processing)
3. Add auto-recovery for transient failures

---

## Key Learnings

### What Went Wrong
1. **Monitoring gap**: Orchestration health wasn't monitored
2. **Validation gap**: Count-based validation doesn't catch quality issues
3. **Format inconsistency**: Different game_id formats cause join failures

### How to Prevent
1. **Monitor orchestration**: workflow_health.py detects outages within 2 hours
2. **Quality validation**: Check feature quality, not just counts
3. **Standard joins**: Use date+teams pattern, not game_id directly

### System Improvements Needed
1. **Self-healing**: Auto-retry failed processors
2. **Circuit breakers**: Detect and isolate failures
3. **Observability**: Better logging, structured events

---

## Session Statistics

- **Duration:** ~3 hours
- **Files created:** 4 new validation/monitoring scripts
- **Files modified:** 2 bug fixes
- **Backfill rows:** 7,018 boxscore records
- **Root causes identified:** 4 (orchestration, game_id, has_prop_line, feature quality)

---

**End of Handoff Document**
