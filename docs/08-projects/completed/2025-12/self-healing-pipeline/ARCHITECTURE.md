# Self-Healing Pipeline Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Daily Pipeline Flow                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  10:30 AM ET          11:00 AM ET         11:30 AM ET        2:15 PM ET │
│  ┌─────────┐          ┌─────────┐         ┌─────────┐       ┌─────────┐ │
│  │ Phase 3 │ ──────▶  │ Phase 4 │ ──────▶ │ Phase 5 │ ───▶  │  Self   │ │
│  │Analytics│          │ ML Feat │         │ Predict │       │  Heal   │ │
│  └─────────┘          └─────────┘         └─────────┘       └─────────┘ │
│       │                    │                   │                  │      │
│       ▼                    ▼                   ▼                  ▼      │
│   Lenient              Skip Deps           Tiered           Auto-Fix     │
│   Checks               if needed          Quality          if missing    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Phase 3 Analytics (Lenient Dependency Check)

**Location:** `data_processors/analytics/analytics_base.py`

```python
# Before: Strict check blocked pipeline
exists = row_count >= expected_count_min  # e.g., 200

# After: Lenient check proceeds with warning
exists = row_count > 0  # Any data = exists
if exists and row_count < expected_count_min:
    logger.warning(f"Data exists but below threshold")
```

### 2. Prediction Worker (Tiered Quality)

**Location:** `predictions/worker/worker.py`

```python
# Tiered confidence system
if quality_score >= 70:
    confidence_level = 'high'      # Normal processing
elif quality_score >= 50:
    confidence_level = 'low'       # Proceed with warning
else:
    confidence_level = 'skip'      # Too unreliable
```

### 3. Self-Heal Cloud Function

**Location:** `orchestration/cloud_functions/self_heal/main.py`

```
┌─────────────────────────────────────────┐
│           self-heal-check               │
├─────────────────────────────────────────┤
│ 1. Check games scheduled for tomorrow   │
│ 2. Check predictions exist              │
│ 3. If missing:                          │
│    a. Clear stuck run_history           │
│    b. Trigger Phase 3 (backfill_mode)   │
│    c. Trigger Phase 4 (skip_deps)       │
│    d. Trigger Prediction Coordinator    │
│ 4. Report status                        │
└─────────────────────────────────────────┘
```

### 4. Cloud Scheduler

**Job:** `self-heal-predictions`
- Schedule: `15 14 * * *` (2:15 PM ET)
- Runs 45 minutes after same-day-predictions
- Gives time for normal pipeline, then auto-fixes

## Data Flow

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  Phase 1 │───▶│  Phase 2 │───▶│  Phase 3 │───▶│  Phase 4 │───▶│  Phase 5 │
│ Scrapers │    │   Raw    │    │ Analytics│    │Precompute│    │Predictions│
└──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │               │               │               │
     ▼               ▼               ▼               ▼               ▼
   GCS           BigQuery        BigQuery        ML Feature      Predictions
   Files        nba_raw.*     nba_analytics.*    Store v2         Table
```

## Failure Modes & Recovery

| Failure Mode | Detection | Recovery |
|--------------|-----------|----------|
| Phase 3 dependency check fails | No analytics data | Lenient check proceeds |
| Quality below 70% | Low quality score | Tiered threshold (50%) |
| Run history stuck | Entries > 4 hours old | Auto-cleanup |
| Predictions missing | Count = 0 for tomorrow | Full pipeline re-trigger |

## Service Account Permissions

**scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com**

| Permission | Purpose |
|------------|---------|
| `roles/run.invoker` | Call Phase 3, Phase 4, Coordinator |
| `roles/bigquery.dataViewer` | Check prediction counts |
| `roles/bigquery.jobUser` | Run queries |
| `roles/datastore.user` | Access Firestore run_history |
| `roles/iam.serviceAccountTokenCreator` | Generate identity tokens |
