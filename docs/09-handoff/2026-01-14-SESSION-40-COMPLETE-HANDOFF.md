# Session 40 Complete Handoff: Monitoring Improvements & Pipeline Validation

**Date:** 2026-01-14
**Session:** 40
**Status:** Complete - Multiple Issues Fixed, One New Issue Discovered

---

## Executive Summary

This session resolved all open items from Session 39's monitoring improvements and performed comprehensive pipeline validation. We discovered and fixed the root cause of the Phase 3 404 errors, fixed timezone issues in NBA and MLB scrapers, and identified a new issue: **betting lines are not being joined to predictions**.

---

## Commits Made This Session

| Commit | Description |
|--------|-------------|
| `d78d57b` | fix(scrapers): Use Eastern Time for BDL boxscore date calculation |
| `0613a02` | fix(scrapers): Use Pacific Time for MLB scraper date calculations |
| `08c83dd` | docs(monitoring): Add Session 40 handoff and project tracking |
| `9c2afa8` | fix(phase3): Add Procfile to prevent wrong Flask app deployment |

---

## Issues Resolved

### 1. West Coast Date Logic (NBA)
**Problem:** BDL boxscores used UTC-based "yesterday" causing west coast games to be missed.

**Fix:** Changed to Eastern Time in `scrapers/balldontlie/bdl_box_scores.py`
```python
from scrapers.utils.date_utils import get_yesterday_eastern
self.opts["date"] = get_yesterday_eastern()
```

### 2. West Coast Date Logic (MLB)
**Problem:** 5 MLB scrapers had same UTC date issue.

**Fix:** Added `get_yesterday_pacific()` and updated all 5 scrapers:
- `scrapers/mlb/balldontlie/mlb_box_scores.py`
- `scrapers/mlb/balldontlie/mlb_games.py`
- `scrapers/mlb/balldontlie/mlb_pitcher_stats.py`
- `scrapers/mlb/balldontlie/mlb_batter_stats.py`
- `scrapers/mlb/statcast/mlb_statcast_pitcher.py`

### 3. Phase 3 404 Root Cause
**Problem:** `/process-date-range` endpoint returning 404 on revision 00055.

**Root Cause Analysis:**
```
Revision 00054: 14.5 MB source (correct - analytics only)
Revision 00055: 492.5 MB source (WRONG - entire repo uploaded)
```

The repo root Procfile runs predictions service, not analytics. When 00055 was deployed from wrong directory, it started the wrong Flask app.

**Fix:** Created `data_processors/analytics/Procfile`:
```
web: gunicorn --bind :$PORT --workers 1 --threads 5 --timeout 600 main_analytics_service:app
```

### 4. Stuck Processors
**Action:** Cleaned 25 stuck processors via `cleanup_stuck_processors.py --execute`

### 5. Auth Error Monitoring
**Status:** Log-based metric `cloud_run_auth_errors` exists. Alert policy needs manual Cloud Console setup.

---

## NEW ISSUE: Betting Lines Not Joined to Predictions

### Problem Description

Predictions are being generated but **do not have betting lines attached**. This means:
- Hit rate cannot be calculated for grading
- The `line_value` column in `prediction_accuracy` is NULL
- The `current_points_line` column in `player_prop_predictions` is NULL

### Evidence

```sql
-- Predictions have no lines
SELECT game_date, COUNT(*) as predictions,
       COUNTIF(current_points_line IS NULL) as null_line
FROM nba_predictions.player_prop_predictions
WHERE game_date >= "2026-01-12"
GROUP BY game_date;

+------------+-------------+-----------+
| game_date  | predictions | null_line |
+------------+-------------+-----------+
| 2026-01-14 |         358 |       358 |  -- ALL NULL
| 2026-01-13 |         295 |       295 |  -- ALL NULL
| 2026-01-12 |          82 |        82 |  -- ALL NULL
+------------+-------------+-----------+
```

```sql
-- But betting props DO exist!
SELECT game_date, COUNT(*) as props, COUNT(DISTINCT player_name) as players
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= "2026-01-12"
GROUP BY game_date;

+------------+-------+---------+
| game_date  | props | players |
+------------+-------+---------+
| 2026-01-14 |   504 |      85 |
| 2026-01-13 |  1539 |     100 |  -- Data exists!
| 2026-01-12 |  1281 |      85 |
+------------+-------+---------+
```

### Impact

| Date | Graded | Has Actual | Has Line | Hit Rate |
|------|--------|------------|----------|----------|
| Jan 13 | 271 | ✅ | ❌ NULL | N/A |
| Jan 12 | 72 | ✅ | ❌ NULL | N/A |
| Jan 11 | 587 | ✅ | ✅ | 44.6% |
| Jan 10 | 905 | ✅ | ✅ | 64.8% |

The system worked correctly until Jan 11, then stopped joining lines.

### Investigation Areas

1. **Prediction Generation Code**
   - Where does the prediction system get betting lines?
   - Is there a join that's failing?
   - Check `predictions/coordinator/` and `predictions/worker/` code

2. **Timing Issue**
   - Are predictions generated before lines are scraped?
   - Check scheduler timing for props scraping vs prediction generation

3. **Data Pipeline**
   - Is there a processor that enriches predictions with lines?
   - Check if there's a separate "line enrichment" step

4. **Schema Changes**
   - Did something change in the props table schema?
   - Check if player name matching is failing

### Key Tables to Investigate

| Table | Purpose | Status |
|-------|---------|--------|
| `nba_raw.odds_api_player_points_props` | Raw betting lines | ✅ Has data |
| `nba_predictions.player_prop_predictions` | Generated predictions | ⚠️ Missing lines |
| `nba_predictions.prediction_accuracy` | Graded results | ⚠️ Missing lines |
| `nba_precompute.player_composite_factors` | ML features | Check if lines included |

### Relevant Code Locations

```
predictions/
├── coordinator/
│   └── coordinator.py         # Orchestrates prediction generation
├── worker/
│   └── worker.py              # Generates individual predictions
└── systems/
    └── *.py                   # Different prediction models

data_processors/
└── precompute/
    └── ml_feature_store/      # May include line data
```

---

## Pipeline Validation Results (Jan 13, 2026)

### Data Completeness

| Source | Expected | Actual | Status |
|--------|----------|--------|--------|
| Schedule | 7 games | 7 Final | ✅ |
| Gamebook Stats | 7 games | 7 games (350 rows) | ✅ |
| BDL Boxscores | 7 games | 5 games (174 rows) | ⚠️ Gap (fixed) |
| BDL Live Boxscores | 7 games | 7 games (735 rows) | ✅ |
| Player Game Summary | 7 games | 7 games (458 rows) | ✅ |
| Game Lines | 7 games | 7 games (176 rows) | ✅ |
| Player Props | - | 1539 props | ✅ |

### Prediction Status

| Date | Predictions | Status |
|------|-------------|--------|
| Jan 14 (today) | 358 | ✅ Ready for tonight |
| Jan 13 | 295 | ✅ Generated (no lines) |

---

## Remaining Manual Tasks

### 1. Cloud Monitoring Alert Policy (5 minutes)

The log-based metric exists. Create alert policy in Cloud Console:

1. Go to: Cloud Console > Monitoring > Alerting > Create Policy
2. Add condition:
   - Metric: `logging.googleapis.com/user/cloud_run_auth_errors`
   - Threshold: > 10 in 5 minutes
3. Add notification channel
4. Save

### 2. Slack Webhook for Health Alerts (Optional)

The `system_health_check.py` already supports Slack. Just need:
```bash
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
python scripts/system_health_check.py --slack
```

---

## Verification Commands

```bash
# Quick health check
python scripts/system_health_check.py --hours=1 --skip-infra

# Check stuck processors
python scripts/cleanup_stuck_processors.py

# Verify predictions for today
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as predictions,
       COUNTIF(current_points_line IS NOT NULL) as has_line
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
GROUP BY game_date'

# Check if props exist for today
bq query --use_legacy_sql=false '
SELECT game_date, COUNT(*) as props
FROM nba_raw.odds_api_player_points_props
WHERE game_date = CURRENT_DATE()
GROUP BY game_date'
```

---

## Files Changed This Session

| File | Change |
|------|--------|
| `scrapers/utils/date_utils.py` | Added ET/PT timezone utilities |
| `scrapers/balldontlie/bdl_box_scores.py` | Use Eastern Time |
| `scrapers/mlb/balldontlie/*.py` | Use Pacific Time (4 files) |
| `scrapers/mlb/statcast/mlb_statcast_pitcher.py` | Use Pacific Time |
| `data_processors/analytics/Procfile` | NEW - prevents wrong deployment |
| `docs/08-projects/current/monitoring-improvements/*` | Project docs |
| `docs/09-handoff/2026-01-14-SESSION-40-*.md` | Handoff docs |

---

## Priority for Next Session

1. **HIGH: Investigate betting lines join issue**
   - This is breaking grading/accuracy tracking
   - Started failing after Jan 11

2. **MEDIUM: Cloud Monitoring alert policy**
   - 5 minutes manual setup
   - Provides auth error alerting

3. **LOW: Slack webhook setup**
   - Optional but useful for proactive alerts

---

## Context for New Chat

The monitoring improvements project (Sessions 38-40) is essentially complete. The main outstanding issue is the **betting lines not being joined to predictions**, which is a separate data pipeline issue that started after Jan 11, 2026.

Key questions to answer:
1. What changed between Jan 11 and Jan 12 that broke the line join?
2. Where in the prediction pipeline should lines be joined?
3. Is this a timing issue (predictions generated before lines scraped)?
4. Is this a matching issue (player names not matching)?

The odds data EXISTS - it's just not being used by the prediction system.
