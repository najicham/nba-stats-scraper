# Prop Data Gap Incident Analysis & Remediation

**Date:** January 11, 2026
**Severity:** HIGH
**Status:** IN PROGRESS

---

## Executive Summary

A 2-month gap in prop line data (Oct 22 - Dec 19, 2025) went undetected, resulting in predictions being generated without Vegas lines during this period. This document details the root cause analysis, immediate fixes, and long-term monitoring improvements.

---

## Incident Timeline

| Date | Event |
|------|-------|
| Oct 21, 2025 | Season opener - prop scraper ran for 1 day |
| Oct 22, 2025 | **Prop scraper started failing silently** |
| Nov 14, 2025 | Prop scraper resumed (data in GCS but not loaded to BQ) |
| Dec 20, 2025 | Props finally loaded to BigQuery |
| Jan 11, 2026 | Gap discovered during performance analysis |

---

## What Went Wrong

### 1. The Scraper Ran But Processor Didn't

```
Scraper runs → Data saved to GCS ✅
                    ↓
            Processor should run → Data to BigQuery ❌ (FAILED SILENTLY)
```

**GCS Data Available:**
- Nov 14 - Dec 31, 2025: 47 dates with player props in GCS
- This data was never loaded to BigQuery

**Missing Period (not scraped):**
- Oct 22 - Nov 13, 2025: ~3 weeks with no GCS data

### 2. YESTERDAY Bug in Analytics Processor

**File:** `data_processors/analytics/main_analytics_service.py`

The `/process-date-range` endpoint only handled `TODAY` and `TOMORROW`, not `YESTERDAY`:

```python
# BEFORE (bug):
if start_date == "TODAY":
    start_date = today_et
elif start_date == "TOMORROW":
    start_date = tomorrow_et
# MISSING: YESTERDAY handling!

# AFTER (fixed):
if start_date == "TODAY":
    start_date = today_et
elif start_date == "YESTERDAY":
    start_date = yesterday_et  # Added
elif start_date == "TOMORROW":
    start_date = tomorrow_et
```

**Impact:** The `daily-yesterday-analytics` scheduler job sent `"YESTERDAY"` but it was treated as a literal string, causing Phase 3 analytics to fail.

### 3. Silent Degradation in Prediction Pipeline

**File:** `predictions/worker/worker.py` (lines 141-148)

```python
PERMANENT_SKIP_REASONS = {
    'no_prop_lines',  # Classified as PERMANENT - returns 204 OK, no alert!
}
```

When prop lines were missing, the worker marked predictions as `NO_LINE` and continued - **no alert, no escalation**.

### 4. Missing Monitoring

| What Should Exist | Status |
|-------------------|--------|
| Prop table freshness monitor | ❌ Missing |
| GCS ↔ BigQuery sync check | ❌ Missing |
| NO_LINE prediction spike alert | ❌ Missing |
| Processor execution log | ❌ Missing |
| Coverage degradation alert | ❌ Missing |

---

## Fixes Implemented

### 1. YESTERDAY Bug Fix ✅

**Commit:** af2de62
**Deployed:** Jan 11, 2026 @ 10:55 AM ET
**Service:** nba-phase3-analytics-processors (revision 00053-tsq)

### 2. Pick Subset Tracking Schema ✅

Created multi-model aware subset tracking:
- `nba_predictions.pick_subset_definitions` - Subset definitions with system_id
- `nba_predictions.published_picks` - Track which picks shown to users
- `nba_predictions.v_subset_performance` - Performance by subset and model
- `nba_predictions.v_subset_performance_summary` - Aggregated summary

### 3. Performance Analysis Documentation ✅

Created: `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md`

---

## Data Recovery Plan

### Phase 1: Load GCS Data to BigQuery (47 dates)

Data exists in GCS for Nov 14 - Dec 31, 2025 but was never processed to BigQuery.

```bash
# Run the props processor backfill for existing GCS data
gcloud run jobs execute odds-api-props-backfill \
  --args="--start-date,2025-11-14,--end-date,2025-12-19" \
  --region=us-west2
```

### Phase 2: Historical Scrape (Oct 22 - Nov 13)

~3 weeks of data was never scraped. Need to use historical API:

```bash
# For each missing date, scrape events first
python scrapers/oddsapi/oddsa_events_his.py \
  --game_date 2025-10-22 \
  --snapshot_timestamp 2025-10-22T18:00:00Z

# Then scrape props with those event IDs
python scrapers/oddsapi/oddsa_player_props_his.py \
  --game_date 2025-10-22 \
  --event_id <from_events> \
  --snapshot_timestamp 2025-10-22T18:00:00Z
```

### Phase 3: Re-run Predictions & Grading

After prop data is loaded:
1. Re-generate predictions for recovered dates
2. Run grading pipeline
3. Verify coverage metrics

---

## Monitoring Improvements Required

### P0 - Critical (Implement This Week)

#### 1. Enable Prop Gap Detection

**File:** `monitoring/processors/gap_detection/config/processor_config.py`

```python
# Currently disabled - ENABLE:
'odds_api_player_points_props': {
    'enabled': True,  # Change from False
    'table': 'nba_raw.odds_api_player_points_props',
    'date_field': 'game_date',
    'expected_frequency_hours': 24,
    'min_records_per_day': 100,
}
```

#### 2. Add NO_LINE Alerting

**File:** `orchestration/cloud_functions/prediction_health_alert/main.py`

Add to health checks:
```python
# Check for excessive NO_LINE predictions
no_line_count = count_where("recommendation = 'NO_LINE'", game_date)
total_count = count_all(game_date)
no_line_pct = no_line_count / total_count * 100

if no_line_pct > 10:
    alert("WARNING: {no_line_pct}% of predictions have NO_LINE")
if no_line_pct > 50:
    alert("CRITICAL: {no_line_pct}% of predictions have NO_LINE - prop data issue!")
```

#### 3. GCS ↔ BigQuery Sync Monitor

Create new monitor that compares:
- Dates with data in GCS `gs://nba-scraped-data/odds-api/player-props/`
- Dates with data in BigQuery `odds_api_player_points_props`
- Alert when GCS has data that isn't in BigQuery

### P1 - High (Implement Next 2 Weeks)

#### 4. Prop Freshness Monitor

Create dedicated monitoring for prop table freshness:
- Check `odds_api_player_points_props` last update time
- Check `bettingpros_player_points_props` last update time
- Alert if stale for > 4 hours during game days
- Integrate with existing notification system

#### 5. Pre-Prediction Validation Gate

Before generating predictions, validate data freshness:
```python
def validate_data_freshness(game_date: date) -> DataQualityReport:
    checks = {
        'odds_api_props': check_freshness('odds_api_player_points_props', max_hours=8),
        'bettingpros_props': check_freshness('bettingpros_player_points_props', max_hours=12),
    }

    if any(check.is_stale for check in checks.values()):
        notify_warning(f"Generating predictions with stale data: {checks}")
```

#### 6. Prediction Quality Metadata

Add to `player_prop_predictions` table:
- `data_quality_score` - 0-1 score based on data freshness
- `prop_line_source` - 'LIVE', 'STALE_4H', 'ESTIMATED', 'NONE'
- `prop_line_age_hours` - How old the prop line was
- `data_completeness_flags` - Array of issues

### P2 - Medium (Implement Next Month)

#### 7. Weekly Health Report

Automated email every Monday:
- Data coverage by source
- Prediction quality breakdown
- Alerts from the week
- Recommendations

#### 8. Processor Execution Log

Create `processor_execution_log` table:
- Track every processor run
- Log rows_inserted, success/fail, timestamps
- Enable historical analysis of processor health

---

## Root Cause Summary

| Failure Point | Why It Wasn't Caught | Fix |
|---------------|---------------------|-----|
| Prop processor didn't run | Not in gap detector | Enable monitoring |
| NO_LINE predictions | Treated as normal | Add threshold alert |
| GCS data not in BQ | No sync check | Add sync monitor |
| YESTERDAY bug | No date validation tests | Fixed + add tests |
| Silent degradation | No coverage alerts | Add coverage monitor |

---

## Files Modified

| File | Change |
|------|--------|
| `data_processors/analytics/main_analytics_service.py` | Added YESTERDAY handling |
| `schemas/bigquery/predictions/04_pick_subset_definitions.sql` | New table + system_id column |
| `schemas/bigquery/predictions/05_published_picks.sql` | New table for tracking |
| `schemas/bigquery/predictions/views/v_subset_performance.sql` | Multi-model performance view |
| `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md` | New guide |

---

## Next Steps

1. [ ] Run props processor backfill for Nov 14 - Dec 19, 2025
2. [ ] Enable prop gap detection in processor_config.py
3. [ ] Add NO_LINE alerting to prediction_health_alert
4. [ ] Create prop freshness monitor
5. [ ] Historical scrape for Oct 22 - Nov 13 (if API allows)
6. [ ] Re-run predictions and grading for recovered dates

---

## Lessons Learned

1. **"Graceful degradation" without alerting is invisible failure**
   - The system was designed to continue when data was missing
   - But no one was notified, so the problem persisted for months

2. **Monitor data, not just processes**
   - We monitored if scrapers ran, but not if data was complete
   - Need to check actual table freshness, not just process success

3. **Every stage needs validation**
   - GCS → BigQuery step had no monitoring
   - Predictions should validate inputs before running

4. **Predictions need quality metadata**
   - Users should know when predictions are based on stale/missing data
   - Quality scores enable informed decisions
