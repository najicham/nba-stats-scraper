# Session 27 Handoff - Comprehensive Fixes & Data Quality Investigation

**Date:** 2026-01-30
**Duration:** Extended session
**Focus:** Wrong-code deployment fix, prevention mechanisms, data discrepancy investigation

---

## Session Summary

This session addressed the critical scraper wrong-code deployment incident and implemented comprehensive prevention mechanisms. Also conducted full data quality investigation across all pipeline phases.

---

## Critical Fixes Applied

### 1. Scraper Wrong-Code Deployment Fixed

**Problem:** Both `nba-scrapers` and `nba-phase1-scrapers` were running analytics-processor code instead of scraper code for 3+ days.

**Root Cause:**
- No dedicated `scrapers/Dockerfile` existed
- Root Dockerfile defaulted to analytics-processor when SERVICE env var not set
- Manual `gcloud run deploy --source .` picked up wrong Dockerfile

**Fixes Applied:**
| Fix | Commit | File |
|-----|--------|------|
| Created scrapers Dockerfile | 7da5b95d | `scrapers/Dockerfile` |
| Added orchestration/config dirs | d531925c | `scrapers/Dockerfile` |
| Fixed syntax errors (25 files) | fa270438 | `scrapers/**/*.py` |

**Deployment Status:**
```
nba-scrapers: Revision 00108-np4 ✅ Verified
nba-phase1-scrapers: Revision 00020-jjd ✅ Verified
```

### 2. Root Dockerfile Safety Fix

**Problem:** Root Dockerfile silently defaulted to analytics-processor.

**Fix:** Now exits with clear error listing correct Dockerfiles.

```dockerfile
# Before: Silent default to analytics
else \
  exec gunicorn ... data_processors.analytics...

# After: Explicit error
else \
  echo "ERROR: SERVICE must be set to 'phase2' or 'analytics'" >&2; \
  exit 1; \
```

### 3. Orphaned Docker Directory Archived

**Problem:** 20 orphaned Dockerfiles in `/docker/` could be picked up by accident.

**Fix:** Moved to `docs/archive/docker-deprecated/`

---

## Prevention Mechanisms Added

### Cloud Monitoring Alerts (5 new)

| Alert | Trigger | Purpose |
|-------|---------|---------|
| [CRITICAL] NBA Scrapers - HTTP 404 | >3 404s in 5 min | Catches wrong code |
| [CRITICAL] Cloud Scheduler Failures | >5 errors in 10 min | Catches silent failures |
| [CRITICAL] Wrong Code Deployed | Uptime check fails | Validates "nba-scrapers" in response |
| [CRITICAL] Phase 6 Export Failures | >5 5xx errors | Catches export issues |
| [WARNING] DLQ Has Messages | Any messages in DLQ | Catches processing failures |

### Uptime Check

- **NBA Scrapers - Service Identity Check**
- Runs every 5 minutes
- Validates response contains "nba-scrapers"

### Code-Level Prevention

| Mechanism | File | Purpose |
|-----------|------|---------|
| Post-deploy verification | `bin/deploy-service.sh` | Verifies /health returns expected service |
| Pre-commit hook | `.pre-commit-hooks/validate_dockerfiles.py` | Blocks commits if Dockerfile missing |
| Startup verification | All services | Logs expected vs actual module at startup |

---

## Reliability Improvements

### New Files Created

| File | Purpose |
|------|---------|
| `shared/utils/firestore_retry.py` | Retry decorator for Firestore operations |
| `shared/utils/phase_validation.py` | Schema validation at phase boundaries |
| `tests/unit/utils/test_phase_validation.py` | 44 tests for validation |

### Service Improvements

| Improvement | Services | Details |
|-------------|----------|---------|
| Startup verification | 5 services | analytics, precompute, raw, coordinator, scrapers |
| Firestore retry | coordinator | Exponential backoff on state operations |
| Structured logging | All Cloud Run | Auto-enabled when K_SERVICE detected |

### BigQuery Views Deployed

5 views updated to use `prediction_accuracy` instead of deprecated `prediction_grades`:
- `confidence_calibration`
- `player_insights_summary`
- `player_prediction_performance`
- `prediction_accuracy_summary`
- `roi_simulation`

---

## Data Discrepancy Investigation

### Full Report Location
```
docs/08-projects/current/season-validation-2024-25/DATA-DISCREPANCY-INVESTIGATION.md
```

### Key Findings

| Issue | Severity | Status |
|-------|----------|--------|
| Model accuracy degradation | 🔴 CRITICAL | Needs investigation |
| Rolling average cache bug | 🟡 HIGH | Root cause identified, fix deployed |
| Player name normalization | 🟡 MEDIUM | Fix needed |
| Feature store NULL values | 🟡 MEDIUM | Cleanup needed |
| DNP voiding gaps | 🟢 LOW | Fix needed |

### Model Accuracy Degradation (CRITICAL)

catboost_v8 dropped from 74.3% to 60.5% accuracy:

| Week | Accuracy | Over-Prediction |
|------|----------|-----------------|
| Jan 4 | 61.8% | +0.5 pts |
| Jan 11 | 41.5% | +0.1 pts |
| Jan 18 | 54.4% | +2.5 pts |
| Jan 25 | **49.0%** | **+6.7 pts** |

**The model is systematically over-predicting points.**

### Rolling Average Cache Bug

- **Root Cause:** Backfill used `<=` instead of `<` in date filter
- **Impact:** Feb-Jun 2025 cache values off by ~5 points
- **Status:** Fix deployed (commit f5e249c8), production not affected

---

## Project Documentation Locations

### Main Documentation
```
docs/
├── 01-architecture/         # System design, data flow
├── 02-operations/           # Runbooks, troubleshooting
├── 03-phases/               # Phase-specific docs
├── 04-deployment/           # Deployment guides
├── 05-development/          # Dev practices
├── 08-projects/             # Active projects
│   └── current/
│       └── season-validation-2024-25/
│           ├── README.md
│           ├── PROGRESS.md
│           ├── DATA-DISCREPANCY-INVESTIGATION.md  # NEW
│           ├── DATA-LINEAGE-VALIDATION.md
│           ├── DATA-QUALITY-METRICS.md
│           └── VALIDATION-FRAMEWORK.md
└── 09-handoff/              # Session handoffs
    ├── 2026-01-29-POSTMORTEM-SCRAPER-WRONG-DEPLOYMENT.md
    ├── 2026-01-29-SESSION-25-HISTORICAL-VALIDATION.md
    └── 2026-01-30-SESSION-27-COMPREHENSIVE-FIXES.md  # THIS FILE
```

### Key Reference Files
- `CLAUDE.md` - Project instructions and conventions
- `bin/deploy-service.sh` - Deployment script with verification
- `bin/monitoring/daily_health_check.sh` - Health check script

---

## Commits This Session (7 total)

```
f90ff213 - docs: Add comprehensive data discrepancy investigation report
fa270438 - fix: Fix syntax errors in scraper notify stub functions (25 files)
a3c4f97a - feat: Add comprehensive reliability and validation improvements
1942a6b3 - fix: Archive orphaned docker directory and fix root Dockerfile default
cc2dc1fc - docs: Add Session 25/26 documentation and validation artifacts
d531925c - fix: Add prevention mechanisms for scraper wrong-code deployment
```

---

## Next Session Priorities

### P1 - Critical (Immediate)

1. **Investigate model drift**
   - catboost_v8 over-predicting by 6.7 points average
   - Check feature store data quality
   - Consider retraining model
   - Query to start:
   ```sql
   SELECT DATE_TRUNC(game_date, WEEK) as week,
     ROUND(AVG(predicted_value - actual_value), 1) as avg_error
   FROM nba_predictions.prediction_accuracy
   WHERE system_id = 'catboost_v8' AND game_date >= '2025-12-01'
   GROUP BY 1 ORDER BY 1
   ```

2. **Fix DNP voiding**
   - 532 predictions with actual_points=0 not voided
   - These are counted as losses unfairly
   - Location: Grading logic in predictions/

### P2 - High (This Sprint)

3. **Fix player name normalization**
   - 15-20% gap between analytics and cache
   - Create canonical lookup table
   - Examples: `boneshyland` vs `nahshonhyland`

4. **Clean feature store**
   - 187 duplicate records (2026-01-09)
   - 30% NULL historical_completeness in Jan 2026
   - Investigate 2025-12-21 anomaly

### P3 - Medium (Backlog)

5. **Historical validation** - 2023-24, 2022-23 seasons
6. **Re-backfill cache** - Feb-Jun 2025 (optional)

---

## Quick Commands

```bash
# Daily validation
/validate-daily

# Check scraper health
curl -s https://nba-scrapers-756957797294.us-west2.run.app/health | jq .service

# Check deployment drift
./bin/check-deployment-drift.sh --verbose

# Deploy a service
./bin/deploy-service.sh nba-scrapers

# Run spot checks
python scripts/spot_check_data_accuracy.py --samples 5

# Check model accuracy
bq query --use_legacy_sql=false "
SELECT system_id,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as accuracy
FROM nba_predictions.prediction_accuracy
WHERE game_date >= '2026-01-01'
GROUP BY 1 ORDER BY 2 DESC"
```

---

## Environment Status

| Service | Status | Revision |
|---------|--------|----------|
| nba-scrapers | ✅ Healthy | 00108-np4 |
| nba-phase1-scrapers | ✅ Healthy | 00020-jjd |
| prediction-coordinator | ✅ Running | Current |
| prediction-worker | ✅ Running | Current |

| Alert | Status |
|-------|--------|
| Scraper 404 Alert | ✅ Active |
| Scheduler Failure Alert | ✅ Active |
| Wrong Code Alert | ✅ Active |
| Phase 6 Export Alert | ✅ Active |
| DLQ Depth Alert | ✅ Active |

---

## Key Learnings

1. **Every service needs a dedicated Dockerfile** - Root Dockerfile defaults are dangerous
2. **Post-deployment verification is essential** - Catches wrong code immediately
3. **Model drift can happen silently** - Need monitoring for prediction accuracy
4. **Player name normalization is fragile** - Multiple variants cause data gaps
5. **Feature store quality varies by month** - Historical data may be unreliable

---

*Session 27 handoff complete. Critical fixes deployed, prevention mechanisms active, investigation documented.*
