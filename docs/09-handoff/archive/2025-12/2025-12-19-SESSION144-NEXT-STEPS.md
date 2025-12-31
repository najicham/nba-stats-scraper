# Session 144: Next Steps - Deployment & Production Readiness

**Date:** December 19, 2025
**Status:** Ready to Start
**Focus:** Get real data flowing to frontend

---

## Context

**What's Done:**
- ✅ All 7 backend API exporters complete
- ✅ 213 unit tests passing
- ✅ Frontend UI built with mock data

**What's Missing:**
- ❌ Exporters don't run on a schedule
- ❌ GCS bucket is empty (no JSON files)
- ❌ Frontend can't use real data yet
- ❌ No predictions for 2024-25 season

---

## Priority Todo List

### 🔴 P0: Critical Path (This Week)

#### 1. Deployment & Orchestration
**Status:** Not started
**Effort:** 2-4 hours
**Why:** BLOCKER - nothing else works until exporters run

**Tasks:**
- [ ] Choose deployment method (Cloud Functions vs Cloud Run Jobs)
- [ ] Create Cloud Function for each exporter (or batch runner)
- [ ] Set up Cloud Scheduler triggers:
  - [ ] `6:00 AM ET`: ResultsExporter, PlayerSeasonExporter batch
  - [ ] `Hourly 6AM-2AM ET`: WhosHotColdExporter, BounceBackExporter, TonightTrendPlaysExporter
- [ ] Test manual trigger works
- [ ] Verify JSON files appear in GCS bucket
- [ ] Set up IAM permissions for service account

**Files to create:**
```
cloud_functions/
├── publish_results/
│   └── main.py
├── publish_trends/
│   └── main.py
├── publish_player_data/
│   └── main.py
└── requirements.txt
```

**Or single orchestrator:**
```
cloud_functions/
└── exporter_orchestrator/
    ├── main.py
    └── requirements.txt
```

#### 2. Frontend Integration Test
**Status:** Not started
**Effort:** 1-2 hours
**Why:** Validate real data works with UI

**Tasks:**
- [ ] Point frontend to GCS bucket (instead of mock data)
- [ ] Test Trends page with real data
- [ ] Test Player Modal with real data
- [ ] Document any data format mismatches
- [ ] Fix any issues found

---

### 🟡 P1: Production Readiness (Next Week)

#### 3. Monitoring & Alerting
**Status:** Not started
**Effort:** 4-8 hours
**Why:** Know when things break

**Tasks:**
- [ ] Set up Cloud Monitoring for Cloud Functions
- [ ] Create alerts for:
  - [ ] Function failures
  - [ ] Data staleness (no update in X hours)
  - [ ] BigQuery errors
- [ ] Create simple dashboard showing:
  - [ ] Last successful run per exporter
  - [ ] Data freshness per endpoint
- [ ] Set up PagerDuty/Slack integration (optional)

#### 4. Error Handling & Retries
**Status:** Not started
**Effort:** 2-4 hours
**Why:** Graceful degradation

**Tasks:**
- [ ] Add retry logic to exporters for transient BQ failures
- [ ] Add dead letter queue for failed runs
- [ ] Ensure partial failures don't corrupt GCS data
- [ ] Add health check endpoint

---

### 🟢 P2: Full Functionality (Weeks 2-3)

#### 5. 2025-26 Prediction Pipeline
**Status:** Not started
**Effort:** 1-2 weeks
**Why:** Unblocks Results page, prop_hit_rates

**Investigation needed:**
- [ ] Understand existing ML models in `nba_predictions`
- [ ] Find prediction generation scripts
- [ ] Understand ensemble_v1 system
- [ ] Check if models need retraining or just inference

**Tasks (once understood):**
- [ ] Set up daily prediction generation for upcoming games
- [ ] Set up post-game grading to populate `prediction_accuracy`
- [ ] Backfill predictions for 2024-25 season (if possible)
- [ ] Test ResultsExporter with real predictions

#### 6. Results Page Integration
**Status:** Blocked by #5
**Effort:** 2-4 hours

**Tasks:**
- [ ] Verify ResultsExporter works with predictions
- [ ] Point Results page to real data
- [ ] Test breakdowns and filtering

---

### 🔵 P3: Polish (As Needed)

#### 7. Performance Optimization
**Status:** Not started
**Effort:** 2-4 hours
**Why:** Only if issues observed

**Potential tasks:**
- [ ] Profile slow queries
- [ ] Combine multiple BQ queries in PlayerSeasonExporter
- [ ] Add query result caching
- [ ] Optimize GCS upload (compression?)

#### 8. Additional Features
**Status:** Ideas only

**Ideas:**
- [ ] Player comparison endpoint
- [ ] Team-level aggregations
- [ ] Historical trends (week-over-week, month-over-month)
- [ ] Betting ROI tracking
- [ ] Push notifications for trend plays

---

## Other Items to Consider

### Data Quality

#### 9. Data Validation
**Status:** Not started
**Effort:** 4-8 hours
**Why:** Catch bad data before it reaches frontend

**Tasks:**
- [ ] Add schema validation to exported JSON
- [ ] Validate player_lookup values exist in registry
- [ ] Check for null/NaN values in critical fields
- [ ] Add data quality metrics to monitoring

#### 10. Backfill Historical Data
**Status:** Unknown
**Effort:** Unknown
**Why:** Historical data for trends, comparisons

**Questions:**
- [ ] How far back should trends go?
- [ ] Do we need historical JSON files in GCS?
- [ ] Should Player Modal show multi-season data?

### Security & Access

#### 11. GCS Bucket Configuration
**Status:** Unknown
**Effort:** 1-2 hours

**Tasks:**
- [ ] Verify bucket is public-read (for frontend)
- [ ] Set up CORS headers for frontend access
- [ ] Configure CDN/caching at bucket level
- [ ] Set up bucket lifecycle rules (delete old files?)

#### 12. API Rate Limiting
**Status:** Not applicable yet
**Effort:** 2-4 hours
**Why:** Only if serving directly (not via GCS)

**Note:** If frontend reads from GCS directly, rate limiting is handled by GCS. Only needed if we add a proxy API layer.

### Documentation

#### 13. Frontend Integration Guide
**Status:** Not started
**Effort:** 1-2 hours

**Content:**
- [ ] GCS bucket paths for all endpoints
- [ ] Expected response formats (JSON schemas)
- [ ] Cache durations and refresh times
- [ ] Error handling recommendations
- [ ] Example fetch code

#### 14. Runbook for Operations
**Status:** Not started
**Effort:** 2-4 hours

**Content:**
- [ ] How to manually trigger exporters
- [ ] How to debug failed runs
- [ ] How to backfill missing data
- [ ] Common issues and solutions
- [ ] Escalation procedures

---

## Quick Start for Next Session

### Option A: Start Deployment (Recommended)
```bash
# 1. Create cloud function directory
mkdir -p cloud_functions/exporter_orchestrator

# 2. Check existing cloud functions (if any)
gcloud functions list --project=nba-props-platform

# 3. Check existing schedulers
gcloud scheduler jobs list --project=nba-props-platform --location=us-west2
```

### Option B: Investigate Prediction Pipeline
```bash
# 1. Check prediction tables
bq show --schema nba-props-platform:nba_predictions.prediction_accuracy

# 2. Check existing prediction data
PYTHONPATH=. .venv/bin/python -c "
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT MIN(game_date) as earliest, MAX(game_date) as latest, COUNT(*) as total
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
'''
for r in client.query(query).result():
    print(f'Predictions: {r[\"earliest\"]} to {r[\"latest\"]} ({r[\"total\"]} rows)')"

# 3. Look for prediction generation scripts
find . -name "*predict*" -type f | head -20
```

---

## Dependencies Map

```
                    ┌──────────────────┐
                    │  1. Deployment   │
                    │  (Cloud Funcs)   │
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
              ▼              ▼              ▼
     ┌────────────┐  ┌────────────┐  ┌────────────┐
     │ 2. Frontend│  │ 3. Monitor │  │ 4. Error   │
     │   Test     │  │  & Alert   │  │  Handling  │
     └────────────┘  └────────────┘  └────────────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
                    ┌────────▼─────────┐
                    │  5. Prediction   │
                    │    Pipeline      │
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │  6. Results Page │
                    └──────────────────┘
```

---

## Estimated Timeline

| Week | Focus | Deliverable |
|------|-------|-------------|
| Week 1 | Deployment + Frontend Test | Trends page live with real data |
| Week 1 | Monitoring | Alerts for failures |
| Week 2 | Prediction Investigation | Understand ML pipeline |
| Week 2-3 | Prediction Pipeline | Daily predictions running |
| Week 3 | Results Integration | Full functionality |

---

## Reference

### Exporter Schedule Summary
| Exporter | Frequency | Time | Notes |
|----------|-----------|------|-------|
| ResultsExporter | Daily | 6 AM ET | After games complete |
| WhosHotColdExporter | Hourly | 6 AM - 2 AM | Game days |
| BounceBackExporter | Hourly | 6 AM - 2 AM | Game days |
| TonightTrendPlaysExporter | Hourly | 6 AM - 2 AM | Game days |
| SystemPerformanceExporter | Daily | 6 AM ET | |
| PlayerSeasonExporter | Daily | 6 AM ET | Batch for active players |
| PlayerGameReportExporter | On-demand | | Or batch after games |

### GCS Bucket Structure
```
gs://nba-props-platform-api/v1/
├── results/
│   └── {date}.json
├── trends/
│   ├── whos-hot-v2.json
│   ├── bounce-back.json
│   ├── tonight-plays.json
│   └── system-performance.json
└── players/
    └── {player_lookup}/
        ├── season/{season}.json
        └── game-report/{date}.json
```
