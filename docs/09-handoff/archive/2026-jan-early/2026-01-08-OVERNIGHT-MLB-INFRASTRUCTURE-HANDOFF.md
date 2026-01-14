# MLB Infrastructure & Dashboard Enhancement - Overnight Session Handoff

**Date:** 2026-01-08
**Session Duration:** Overnight
**Status:** Significant progress completed

---

## Summary

Extended the MLB pipeline with orchestration, monitoring, alerting, and dashboard support. The core backend infrastructure is complete; only UI template updates and final deployment remain.

---

## Completed Tasks (10/12)

### 1. BigQuery Grading Fields
**File:** `mlb_predictions.pitcher_strikeouts`
**Status:** DEPLOYED

Added columns to support grading:
- `actual_strikeouts INT64`
- `is_correct BOOL`
- `graded_at TIMESTAMP`

### 2. Email Alerting for MLB Services
**Files Updated:**
- `bin/analytics/deploy/mlb/deploy_mlb_analytics.sh`
- `bin/precompute/deploy/mlb/deploy_mlb_precompute.sh`
- `bin/phase6/deploy/mlb/deploy_mlb_grading.sh`
- `bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh`
- `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`

All 5 MLB deploy scripts now include Brevo SMTP email alerting configuration (matches NBA pattern).

### 3. MLB Health Check Script
**File:** `bin/monitoring/mlb_daily_health_check.sh`
**Status:** Created and executable

Checks:
- All 5 MLB service health endpoints
- Games scheduled
- Raw data (last 7 days)
- Analytics data (pitcher_game_summary)
- Precompute features (pitcher_ml_features)
- Predictions
- Grading results
- Recent errors
- Scheduler job status
- Pub/Sub subscription status

### 4. MLB Self-Heal Cloud Function
**Files Created:**
- `orchestration/cloud_functions/mlb_self_heal/main.py`
- `orchestration/cloud_functions/mlb_self_heal/requirements.txt`
- `bin/orchestrators/mlb/deploy_mlb_self_heal.sh`

Features:
- Checks TODAY and TOMORROW for missing predictions
- Auto-triggers Phase 3 → Phase 4 → Predictions if missing
- Clears stuck Firestore entries
- Quality validation

### 5. MLB Phase 3→4 Orchestrator
**Files Created:**
- `orchestration/cloud_functions/mlb_phase3_to_phase4/main.py`
- `orchestration/cloud_functions/mlb_phase3_to_phase4/requirements.txt`

Tracks completion of:
- `pitcher_game_summary`
- `batter_game_summary`

Triggers Phase 4 via `mlb-phase4-trigger` when complete.

### 6. MLB Phase 4→5 Orchestrator
**Files Created:**
- `orchestration/cloud_functions/mlb_phase4_to_phase5/main.py`
- `orchestration/cloud_functions/mlb_phase4_to_phase5/requirements.txt`

Tracks completion of:
- `pitcher_features`
- `lineup_k_analysis`

Features:
- **4-hour timeout** - triggers predictions with partial data if timeout reached
- HTTP call to mlb-prediction-worker `/predict-batch`

### 7. MLB Phase 5→6 Orchestrator
**Files Created:**
- `orchestration/cloud_functions/mlb_phase5_to_phase6/main.py`
- `orchestration/cloud_functions/mlb_phase5_to_phase6/requirements.txt`

Triggers grading after predictions complete.

### 8. Unified Orchestrator Deploy Script
**File:** `bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh`

Deploys all 4 MLB Cloud Functions in one command:
- mlb-phase3-to-phase4
- mlb-phase4-to-phase5
- mlb-phase5-to-phase6
- mlb-self-heal

### 9. Dashboard BigQuery Service - Sport-Aware
**File:** `services/admin_dashboard/services/bigquery_service.py`

Added:
- `sport` parameter to constructor
- `SPORT_DATASETS` mapping (nba/mlb)
- `get_mlb_daily_status()` - Pipeline status
- `get_mlb_games_detail()` - Game details with pitcher matchups
- `get_mlb_pipeline_history()` - Last N days
- `get_mlb_grading_status()` - Grading accuracy

### 10. Dashboard Firestore Service - Sport-Aware
**File:** `services/admin_dashboard/services/firestore_service.py`

Added:
- `sport` parameter to constructor
- `SPORT_COLLECTIONS` mapping
- `get_mlb_phase3_status()` - Tracks 2 processors
- `get_mlb_phase4_status()` - Tracks 2 processors

### 11. Dashboard Main - Sport-Aware Backend
**File:** `services/admin_dashboard/main.py`

Added:
- `SUPPORTED_SPORTS = ['nba', 'mlb']`
- `get_sport_from_request()` - Gets `?sport=` parameter
- `get_service_for_sport()` - Returns sport-specific services
- Sport-aware `SERVICE_URLS` for Cloud Run calls
- Updated `/dashboard` route to use sport parameter
- Updated `/api/status` endpoint for sport support
- Health endpoint shows `supported_sports`

---

## Remaining Tasks (2/12)

### 1. Update Dashboard Templates
**Status:** Not started
**Effort:** 1-2 hours

Need to add sport selector tabs to:
- `templates/base.html` - Add sport tabs in header
- `templates/dashboard.html` - Display sport-specific data
- Update status cards for MLB terminology (pitchers vs players)

### 2. Deploy Updated Dashboard
**Status:** Not started
**Effort:** 15 minutes

```bash
# After template updates
cd services/admin_dashboard
./deploy.sh
```

---

## Files Created This Session

```
orchestration/cloud_functions/
├── mlb_self_heal/
│   ├── main.py
│   └── requirements.txt
├── mlb_phase3_to_phase4/
│   ├── main.py
│   └── requirements.txt
├── mlb_phase4_to_phase5/
│   ├── main.py
│   └── requirements.txt
└── mlb_phase5_to_phase6/
    ├── main.py
    └── requirements.txt

bin/orchestrators/mlb/
├── deploy_mlb_self_heal.sh
└── deploy_all_mlb_orchestrators.sh

bin/monitoring/
└── mlb_daily_health_check.sh
```

---

## Files Modified This Session

```
bin/analytics/deploy/mlb/deploy_mlb_analytics.sh
bin/precompute/deploy/mlb/deploy_mlb_precompute.sh
bin/phase6/deploy/mlb/deploy_mlb_grading.sh
bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh

services/admin_dashboard/services/bigquery_service.py
services/admin_dashboard/services/firestore_service.py
services/admin_dashboard/main.py
```

---

## Not Yet Deployed

The following are created but not deployed to GCP:

1. **MLB Orchestrator Cloud Functions** - Ready to deploy
   ```bash
   ./bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh
   ```

2. **Updated Dashboard** - Needs template work first

---

## Testing Commands

```bash
# Check MLB health
./bin/monitoring/mlb_daily_health_check.sh

# Test dashboard API with MLB
curl "https://nba-admin-dashboard-xxx.run.app/api/status?sport=mlb&key=YOUR_KEY"

# Deploy orchestrators
./bin/orchestrators/mlb/deploy_all_mlb_orchestrators.sh
```

---

## Architecture Overview

```
MLB Pipeline (now with orchestration)
======================================

Phase 1 (Scrapers)
     ↓ [Pub/Sub]
Phase 2 (Raw Processors)
     ↓ [mlb-phase2-raw-complete]
Phase 3 (Analytics) ← Direct Pub/Sub subscription
     ↓ [mlb-phase3-analytics-complete]
     ↓
[mlb-phase3-to-phase4 orchestrator] ← NEW
     ↓ [mlb-phase4-trigger]
Phase 4 (Precompute)
     ↓ [mlb-phase4-precompute-complete]
     ↓
[mlb-phase4-to-phase5 orchestrator] ← NEW (with 4h timeout)
     ↓ [HTTP to prediction worker]
Phase 5 (Predictions)
     ↓ [mlb-phase5-predictions-complete]
     ↓
[mlb-phase5-to-phase6 orchestrator] ← NEW
     ↓ [HTTP to grading]
Phase 6 (Grading)

Self-Heal (12:45 PM ET daily) ← NEW
     ↓
Checks predictions → Triggers healing if missing
```

---

## Next Steps for Morning

1. **Quick Win:** Update dashboard templates with sport selector (1-2 hrs)
2. **Deploy:** Run `deploy_all_mlb_orchestrators.sh`
3. **Test:** Use health check script to verify everything
4. **Optional:** Deploy updated dashboard

---

## Notes

- All MLB scheduler jobs remain PAUSED (off-season)
- Orchestrators ready to deploy but not deployed yet
- Dashboard backend is fully sport-aware
- Only UI templates need updating
- Email alerting configured but requires BREVO env vars to be set
