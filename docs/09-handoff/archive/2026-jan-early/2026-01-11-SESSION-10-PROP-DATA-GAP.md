# Session 10 Handoff: Prop Data Gap Incident Resolution

**Date:** January 11, 2026
**Session Duration:** ~2 hours
**Status:** IN PROGRESS - Backfill running

---

## Executive Summary

Discovered and began resolving a **2-month prop data gap** (Oct 22 - Dec 19, 2025) that prevented predictions from having Vegas lines. The gap occurred because:
1. Prop scrapers ran and saved data to GCS
2. The processor to load GCS → BigQuery never ran
3. No monitoring detected this silent failure

**Key Accomplishments:**
- Fixed YESTERDAY bug in Phase 3 analytics (deployed)
- Created prop backfill script and started recovery
- Added NO_LINE alerting to prediction health monitor
- Enabled prop gap detection in processor monitoring
- Created prop freshness diagnostic tool

---

## Current State

### Backfill Status (RUNNING)

```bash
# Background task b3b5832 is running:
python scripts/backfill_odds_api_props.py --start-date 2025-11-15 --end-date 2025-12-31 --parallel 3 --delay 0.3
```

**Progress as of handoff:**
| Metric | Value |
|--------|-------|
| Dates in GCS | 46 |
| Dates in BigQuery | 17 (was 13) |
| Remaining | ~29 dates |
| Estimated time | 15-30 more minutes |

**To check progress:**
```bash
# Check BigQuery coverage
bq query --use_legacy_sql=false "
SELECT COUNT(DISTINCT game_date) as dates, COUNT(*) as records
FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
WHERE game_date >= '2025-11-14' AND game_date <= '2025-12-31'
"

# Check if backfill process is running
ps aux | grep backfill_odds | grep -v grep

# Check backfill output
tail -50 /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b3b5832.output
```

### Data Gap Details

| Period | GCS Status | BigQuery Status | Action Needed |
|--------|------------|-----------------|---------------|
| Oct 21, 2025 | ✅ Has data | ✅ Loaded | None |
| Oct 22 - Nov 13 | ❌ Missing | ❌ Missing | Historical scrape (Odds API) |
| Nov 14 - Dec 19 | ✅ Has data | 🔄 Loading | Backfill in progress |
| Dec 20 - Jan 11 | ✅ Has data | ✅ Loaded | None |

---

## Completed Tasks

### 1. YESTERDAY Bug Fix ✅ DEPLOYED

**File:** `data_processors/analytics/main_analytics_service.py`

The `/process-date-range` endpoint only handled `TODAY` and `TOMORROW`, not `YESTERDAY`. This caused the daily-yesterday-analytics scheduler job to fail silently.

**Fix deployed to Cloud Run:**
- Revision: `nba-phase3-analytics-processors-00053-tsq`
- Commit: `af2de62`

**Verification:** Tomorrow's 6:30 AM ET job will correctly process today's games.

### 2. Pick Subset Tracking Schema ✅ CREATED

Created multi-model aware performance tracking in BigQuery:

```sql
-- Tables created
nba_predictions.pick_subset_definitions  -- Subset definitions with system_id
nba_predictions.published_picks          -- Track website-shown picks
nba_predictions.v_subset_performance     -- Daily performance by subset
nba_predictions.v_subset_performance_summary  -- Aggregated summary
```

**Subsets defined:**
- `actionable_filtered` - OVER/UNDER excluding 88-90% problem tier (PRIMARY)
- `actionable_unfiltered` - All OVER/UNDER picks
- `very_high_confidence` - 90%+ confidence only
- `problem_tier_shadow` - 88-90% tier (for monitoring)
- `over_picks`, `under_picks` - By recommendation type

### 3. NO_LINE Alerting ✅ ADDED

**File:** `orchestration/cloud_functions/prediction_health_alert/main.py`

Added detection for prop data gaps:
- **WARNING:** >10% of predictions have NO_LINE
- **CRITICAL:** >50% of predictions have NO_LINE

Query includes new field: `no_line_predictions`

**Deployment needed:** Cloud Function needs redeployment to activate.

### 4. Prop Gap Detection ✅ ENABLED

**File:** `monitoring/processors/gap_detection/config/processor_config.py`

Added `odds_api_player_props` configuration with:
- `enabled: True`
- `tolerance_hours: 8`
- `priority: critical`
- `revenue_impact: True`

### 5. Props Backfill Script ✅ CREATED

**File:** `scripts/backfill_odds_api_props.py`

Usage:
```bash
# Dry run
python scripts/backfill_odds_api_props.py --start-date 2025-11-14 --end-date 2025-11-14 --dry-run

# Actual run with parallelism
python scripts/backfill_odds_api_props.py --start-date 2025-11-14 --end-date 2025-12-31 --parallel 3
```

### 6. Prop Freshness Monitor ✅ CREATED

**File:** `tools/monitoring/check_prop_freshness.py`

Diagnostic tool to check prop data coverage:
```bash
# Check last 7 days
python tools/monitoring/check_prop_freshness.py

# Check specific range
python tools/monitoring/check_prop_freshness.py --start-date 2025-11-01 --end-date 2025-12-31

# JSON output
python tools/monitoring/check_prop_freshness.py --output json
```

### 7. Documentation ✅ UPDATED

- `docs/08-projects/current/pipeline-reliability-improvements/2026-01-11-PROP-DATA-GAP-INCIDENT.md`
- `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md`
- `docs/08-projects/current/pipeline-reliability-improvements/MASTER-TODO.md`

---

## Remaining Tasks

### Immediate (When Backfill Completes)

1. **Verify Backfill Completion**
   ```bash
   # Should show ~46 dates
   bq query --use_legacy_sql=false "
   SELECT COUNT(DISTINCT game_date) as dates
   FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\`
   WHERE game_date >= '2025-11-14' AND game_date <= '2025-12-31'
   "
   ```

2. **Re-run Predictions for Recovered Dates**
   ```bash
   # Use prediction backfill job
   python backfill_jobs/prediction/player_prop_predictions_backfill.py \
     --start-date 2025-11-14 \
     --end-date 2025-12-19
   ```

3. **Re-run Grading for New Predictions**
   ```bash
   python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \
     --start-date 2025-11-14 \
     --end-date 2025-12-19
   ```

### Short Term

4. **Deploy NO_LINE Alert Cloud Function**
   ```bash
   gcloud functions deploy prediction-health-alert \
     --gen2 \
     --runtime python311 \
     --region us-west2 \
     --source orchestration/cloud_functions/prediction_health_alert \
     --entry-point check_prediction_health \
     --trigger-http
   ```

5. **Create GCS ↔ BigQuery Sync Monitor**
   - Detect when GCS has data that isn't loaded to BigQuery
   - Alert before predictions run with stale data

6. **Historical Scrape for Oct 22 - Nov 13**
   - ~3 weeks of data never scraped
   - Needs Odds API historical endpoint
   - May have API cost implications

---

## Key Files Modified

| File | Change |
|------|--------|
| `data_processors/analytics/main_analytics_service.py` | Added YESTERDAY handling |
| `orchestration/cloud_functions/prediction_health_alert/main.py` | Added NO_LINE alerting |
| `monitoring/processors/gap_detection/config/processor_config.py` | Enabled prop monitoring |
| `scripts/backfill_odds_api_props.py` | New backfill script |
| `tools/monitoring/check_prop_freshness.py` | New diagnostic tool |
| `schemas/bigquery/predictions/04_pick_subset_definitions.sql` | New schema |
| `schemas/bigquery/predictions/05_published_picks.sql` | New schema |
| `schemas/bigquery/predictions/views/v_subset_performance.sql` | New view |

---

## Root Cause Analysis

### Why the Gap Occurred

1. **Scraper ran successfully** → Data saved to GCS ✅
2. **Processor never ran** → Data never loaded to BigQuery ❌
3. **Silent degradation** → Predictions made without lines, marked as NO_LINE
4. **No alerting** → System treated NO_LINE as normal state

### Why It Wasn't Detected

| Gap | Why Missed |
|-----|------------|
| GCS → BQ sync | No monitoring on processor execution |
| NO_LINE spike | Classified as "permanent skip" - no alert |
| Coverage check | `check_prediction_coverage.py` exists but not automated |
| Prop freshness | Not in gap detector (was disabled in config) |

### The Hidden Failure Chain

```
Scraper runs → Data in GCS ✅
                    ↓
            Processor should run → Data in BigQuery ❌ (SILENT FAILURE)
                                        ↓
                            Predictions use stale/no lines ❌
                                        ↓
                            Model gives NO_LINE recommendation ❌
                                        ↓
                            Grading shows predictions but has_prop_line = FALSE
```

---

## Verification Queries

### Check Prop Coverage
```sql
SELECT
  game_date,
  COUNT(*) as records,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(DISTINCT bookmaker) as bookmakers
FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
WHERE game_date >= '2025-11-01'
GROUP BY game_date
ORDER BY game_date;
```

### Check NO_LINE Predictions
```sql
SELECT
  game_date,
  COUNTIF(has_prop_line = false) as no_line,
  COUNT(*) as total,
  ROUND(COUNTIF(has_prop_line = false) / COUNT(*) * 100, 1) as no_line_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = 'catboost_v8' AND game_date >= '2025-11-01'
GROUP BY game_date
ORDER BY game_date;
```

### Check Subset Performance
```sql
SELECT * FROM `nba-props-platform.nba_predictions.v_subset_performance_summary`
WHERE system_id = 'catboost_v8'
ORDER BY subset_id;
```

---

## Context for Next Session

### User's Original Questions (From Session Start)

1. "Can you tell me how yesterday's picks performed?" → Answered: 58.3% win rate (14-10)
2. "Verify grading for this season" → Found gap: Oct-Dec 2025 missing props
3. "Should we make a doc about grading?" → Created PERFORMANCE-ANALYSIS-GUIDE.md
4. "Does subset tracking keep track of model?" → Yes, added system_id column

### Season Performance Summary (Graded Period: Dec 20 - Jan 7)

| Subset | Picks | Win Rate | MAE |
|--------|-------|----------|-----|
| Actionable (Filtered) | 44,751 | 75.6% | 3.99 |
| Very High (90%+) | 35,412 | 75.8% | 3.56 |
| Problem Tier (88-90%) | 2,753 | 61.8% | 5.29 |

### 88-90% Problem Tier Root Cause

- UNDER picks predict only 51% of line (vs 71-76% in healthy tiers)
- Extreme predictions for stars (e.g., Giannis line 25 → predicted 6.2)
- 85% of losses were under-predictions
- **Recommendation:** Keep filter (is_actionable = false for 88-90%)

---

## Important Notes

1. **Backfill is still running** - Check task b3b5832 or BigQuery before continuing
2. **Cloud Function not deployed** - NO_LINE alerting code is ready but not deployed
3. **Oct 22 - Nov 13 still missing** - Needs historical API scrape (separate effort)
4. **YESTERDAY fix is live** - Tomorrow's analytics should work correctly

---

## Quick Start for Next Session

```bash
# 1. Check if backfill completed
bq query --use_legacy_sql=false "SELECT COUNT(DISTINCT game_date) FROM \`nba-props-platform.nba_raw.odds_api_player_points_props\` WHERE game_date BETWEEN '2025-11-14' AND '2025-12-31'"
# Expected: ~46 dates

# 2. If not complete, check process
ps aux | grep backfill_odds

# 3. If complete, run predictions backfill
python backfill_jobs/prediction/player_prop_predictions_backfill.py --start-date 2025-11-14 --end-date 2025-12-19

# 4. Then run grading
python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py --start-date 2025-11-14 --end-date 2025-12-19

# 5. Deploy NO_LINE alert function
cd orchestration/cloud_functions/prediction_health_alert
gcloud functions deploy prediction-health-alert --gen2 --runtime python311 --region us-west2 --entry-point check_prediction_health --trigger-http
```
