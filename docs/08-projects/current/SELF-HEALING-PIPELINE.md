# Self-Healing Pipeline System

**Created:** 2025-12-27
**Status:** IMPLEMENTED
**Session:** 178

---

## Overview

The NBA prediction pipeline has had recurring daily issues requiring manual intervention. This document describes the self-healing improvements implemented to make the pipeline more resilient.

## Problem Statement

Based on analysis of handoff docs from Sessions 150-177, these issues occurred repeatedly:

| Issue | Frequency | Impact | Root Cause |
|-------|-----------|--------|------------|
| Phase 3 dependency check false negatives | Very common | Blocks analytics | expected_count_min too strict |
| Quality threshold blocking predictions | Common | No predictions | 70% threshold too high |
| Stale run_history blocking reprocessing | Common | Blocks pipeline | No auto-cleanup |
| External API failures | Weekly | Missing data | No graceful degradation |
| Same-day vs next-day logic mismatch | Design | Wrong dates | Different processing modes |

---

## Solutions Implemented

### 1. Lenient Dependency Check

**File:** `data_processors/analytics/analytics_base.py`

**Before:**
```python
# Data only "exists" if row_count >= expected_count_min
# For gamebook data, expected_count_min = 200
# If only 50 rows exist, dependency check FAILS
exists = row_count >= expected_min
```

**After:**
```python
# Data "exists" if ANY rows are present
# Logs warning if below threshold, but proceeds
exists = row_count > 0  # LENIENT
sufficient = row_count >= expected_min
if exists and not sufficient:
    logger.warning(f"Data exists ({row_count}) but below expected ({expected_min})")
```

**Impact:** Pipeline proceeds with partial data instead of blocking completely.

---

### 2. Tiered Quality Threshold

**File:** `predictions/worker/worker.py`

**Before:**
- quality >= 70%: Generate predictions
- quality < 70%: Block all predictions

**After:**
- quality >= 70%: High confidence (normal)
- quality >= 50%: Low confidence (proceed with warning)
- quality < 50%: Skip (too unreliable)

```python
if quality_score >= 70:
    confidence_level = 'high'
elif quality_score >= 50:
    confidence_level = 'low'
    logger.warning(f"Low quality features for {player_lookup} ({quality_score:.1f}%)")
else:
    confidence_level = 'skip'
```

**Impact:** Predictions are generated for more players, with confidence level tracked.

---

### 3. Pipeline Scripts

Three new scripts in `bin/pipeline/`:

#### force_predictions.sh
Emergency bypass for all dependency checks. Use when normal pipeline fails.

```bash
./bin/pipeline/force_predictions.sh 2025-12-28
```

Steps:
1. Clears stuck run_history entries
2. Runs Phase 3 with `backfill_mode=true`
3. Runs Phase 4 with `skip_dependency_check=true`
4. Runs Prediction Coordinator
5. Verifies results

#### validate_tomorrow.sh
Health check for tomorrow's predictions. Run in morning for early warning.

```bash
./bin/pipeline/validate_tomorrow.sh
```

Checks:
1. Games scheduled for tomorrow
2. Predictions exist
3. Quality scores
4. Stuck processes
5. Today's analytics data

#### self_heal_check.sh
Auto-fixes issues after main pipeline. Set up as scheduler for 2:15 PM ET.

```bash
./bin/pipeline/self_heal_check.sh
```

Actions:
1. Checks if predictions exist for tomorrow
2. If not, triggers force_predictions.sh automatically
3. Clears stuck run_history entries
4. Reports quality score status

---

## Scheduler Setup

To enable automatic self-healing, add this Cloud Scheduler job:

```bash
gcloud scheduler jobs create http self-heal-predictions \
  --location=us-west2 \
  --schedule="15 14 * * *" \
  --time-zone="America/New_York" \
  --uri="https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/run-script" \
  --http-method=POST \
  --message-body='{"script": "bin/pipeline/self_heal_check.sh"}' \
  --description="Self-healing check 30 min after same-day-predictions"
```

Or run as cron on a VM:
```cron
15 14 * * * /path/to/nba-stats-scraper/bin/pipeline/self_heal_check.sh >> /var/log/self-heal.log 2>&1
```

---

## Current Scheduler Timeline

| Time (ET) | Job | Description |
|-----------|-----|-------------|
| 10:30 AM | `same-day-phase3` | Phase 3 analytics for today |
| 11:00 AM | `same-day-phase4` | ML Feature Store |
| 11:30 AM | `same-day-predictions` | Generate predictions |
| **2:15 PM** | `self-heal-check` | **Auto-fix if predictions missing** |
| 7 PM - midnight | `live-export-evening` | Every 3 min during games |

---

## Monitoring Commands

### Quick Health Check
```bash
./bin/pipeline/validate_tomorrow.sh
```

### Check Predictions
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() AND is_active = TRUE
GROUP BY game_date ORDER BY game_date"
```

### Check Quality Scores
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as features, ROUND(AVG(feature_quality_score), 2) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY game_date ORDER BY game_date DESC"
```

### Check Stuck Processes
```bash
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import firestore
from datetime import datetime, timedelta, timezone

db = firestore.Client()
now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=4)

for doc in db.collection('run_history').where('status', '==', 'running').stream():
    data = doc.to_dict()
    started = data.get('started_at')
    if started and started < cutoff:
        print(f'STUCK: {doc.id}')
"
```

---

## Troubleshooting

### Predictions missing for tomorrow

1. Run validation: `./bin/pipeline/validate_tomorrow.sh`
2. If games scheduled but no predictions: `./bin/pipeline/force_predictions.sh YYYY-MM-DD`

### Quality score too low

Quality below 70% indicates upstream data issues. Check:
1. Phase 3 analytics ran: Check `nba_analytics.player_game_summary`
2. Phase 4 precompute ran: Check `nba_predictions.ml_feature_store_v2`
3. Raw data exists: Check `nba_raw.bdl_player_boxscores`

If Phase 3/4 didn't run properly, use force_predictions.sh which bypasses checks.

### Stuck run_history entries

```bash
# Clear all stuck entries (>4 hours old)
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import firestore
from datetime import datetime, timedelta, timezone

db = firestore.Client()
now = datetime.now(timezone.utc)
cutoff = now - timedelta(hours=4)

for doc in db.collection('run_history').where('status', '==', 'running').stream():
    data = doc.to_dict()
    started = data.get('started_at')
    if started and started < cutoff:
        doc.reference.delete()
        print(f'Cleared: {doc.id}')
"
```

---

## Related Files

- `bin/pipeline/force_predictions.sh` - Emergency bypass
- `bin/pipeline/validate_tomorrow.sh` - Health check
- `bin/pipeline/self_heal_check.sh` - Auto-fix scheduler
- `data_processors/analytics/analytics_base.py` - Dependency check logic
- `predictions/worker/worker.py` - Quality threshold logic

---

## Commit History

- `0fd299d` - feat: Add self-healing pipeline improvements (2025-12-27)
