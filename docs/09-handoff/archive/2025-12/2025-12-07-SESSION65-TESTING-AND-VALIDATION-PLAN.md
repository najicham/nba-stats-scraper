# Session 65: Completeness Checker Testing & Validation Plan

**Date:** 2025-12-07
**Previous Session:** 64 (Completeness Checker Optimization - IMPLEMENTED)
**Status:** Ready for Testing

---

## Executive Summary

Session 64 implemented optimizations to skip the slow completeness checker (600+ seconds) in backfill mode. This document provides a comprehensive testing and validation plan to verify the changes work correctly and don't introduce data quality issues.

**Changes Made in Session 64:**
1. Skip completeness check in backfill mode (PSZA, PCF, ML processors)
2. Fixed PSZA `assisted_rate` bug (now checks `total_att > 0 and total_makes > 0`)
3. Added new fast method `check_daily_completeness_fast()` for daily orchestration

---

## Part 1: Complete Testing Checklist

### 1.1 Syntax Validation (Already Passed)
- [x] `player_shot_zone_analysis_processor.py` - OK
- [x] `player_composite_factors_processor.py` - OK
- [x] `ml_feature_store_processor.py` - OK
- [x] `completeness_checker.py` - OK

### 1.2 Unit Tests to Run
```bash
# Run all processor tests
python -m pytest data_processors/precompute/player_shot_zone_analysis/tests/ -v
python -m pytest data_processors/precompute/player_composite_factors/tests/ -v
python -m pytest data_processors/precompute/ml_feature_store/tests/ -v

# Run completeness checker tests
python -m pytest shared/utils/tests/test_completeness_checker.py -v
```

### 1.3 Integration Test: Single Date Backfill
```bash
# Test with a known good date (has Phase 3 data)
# Use November 22, 2021 as test date

# Step 1: Verify Phase 3 data exists
python bin/backfill/preflight_check.py --date 2021-11-22 --phase 3 --verbose

# Step 2: Run Phase 4 processors in backfill mode
.venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
p = PlayerShotZoneAnalysisProcessor()
result = p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
print(f'PSZA Stats: {p.stats}')
print(f'Result: {result}')
"

# Step 3: Verify the log shows "BACKFILL MODE: Skipping completeness check"
```

### 1.4 Performance Validation
```bash
# Time the Phase 4 run with backfill mode
time .venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
p = PlayerShotZoneAnalysisProcessor()
p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
"

# Expected: Should complete in ~30-60 seconds (vs 600+ seconds before)
```

---

## Part 2: Preflight Checks (Run Before Processing)

### 2.1 Primary Preflight Script
**File:** `bin/backfill/preflight_check.py`

```bash
# Check single date
python bin/backfill/preflight_check.py --date 2021-11-22

# Check date range
python bin/backfill/preflight_check.py --start-date 2021-11-01 --end-date 2021-11-30

# Check specific phase with verbose output
python bin/backfill/preflight_check.py --date 2021-11-22 --phase 3 --verbose
python bin/backfill/preflight_check.py --date 2021-11-22 --phase 4 --verbose
```

**What it checks:**
- Phase 1: GCS scraped files exist
- Phase 2: Raw BigQuery tables have data
- Phase 3: Analytics tables populated
- Phase 4: Precompute tables populated

### 2.2 Phase 3→4 Verification
**File:** `bin/backfill/verify_phase3_for_phase4.py`

```bash
python bin/backfill/verify_phase3_for_phase4.py --start-date 2021-11-01 --end-date 2021-11-30
```

**What it checks:**
- All 5 Phase 3 tables have data for date range
- Record counts are reasonable
- No missing dates in analytics tables

### 2.3 Infrastructure Preflight (Full Backfill)
**File:** `bin/backfill/preflight_verification.sh`

```bash
# Full check (includes dry-runs)
./bin/backfill/preflight_verification.sh

# Quick check (skip time-consuming tests)
./bin/backfill/preflight_verification.sh --quick
```

**What it checks:**
- GCP authentication
- Cloud Run services deployed
- Pub/Sub topics configured
- BigQuery datasets exist
- Python dependencies installed

---

## Part 3: Risk Analysis - What We Lose by Skipping Completeness Checks

### 3.1 What Completeness Checker Validates
| Validation | Description | Covered by Preflight? |
|------------|-------------|----------------------|
| Game count vs schedule | Expected games from schedule vs actual | PARTIAL (existence only) |
| Per-entity completeness % | Each player/team has 90%+ games | NO |
| Upstream processor status | Did Phase 3 succeed? | NO |
| Date range gaps | Missing specific dates within range | NO |
| Bootstrap mode detection | Early season threshold adjustment | NO |

### 3.2 Risk Matrix

| Risk | Severity | Likelihood | Impact if Missed |
|------|----------|------------|------------------|
| Silent incomplete windows (missing dates) | HIGH | MEDIUM | 10-20% data missing silently |
| Cascade processor failures | HIGH | LOW | Garbage in → garbage out |
| Per-entity gaps (some players incomplete) | HIGH | HIGH | Some entities 60-70% complete |
| Multi-team player edge cases | MEDIUM | MEDIUM | Duplicate/conflicting records |
| Early season threshold issues | MEDIUM | MEDIUM | False alerts or missed issues |

### 3.3 Mitigations Already in Place

1. **Preflight checks** - Verify data exists at date level
2. **Upstream completeness query** - Still runs in PCF/ML processors (lines 858, 797)
3. **Bootstrap mode** - Early season dates (first 30 days) have lower thresholds
4. **Quality columns** - Track source coverage in output tables

### 3.4 Recommended Additional Safeguards (Future)

1. Add upstream processor status check (query `processor_run_history`)
2. Add date-range continuity check (detect gaps)
3. Per-entity threshold at 75% during backfill (vs 90% production)
4. Track backfill progress with milestone alerts

---

## Part 4: Validation Scripts (Run After Processing)

### 4.1 Pipeline Validation
**File:** `bin/validate_pipeline.py`

```bash
# Validate full pipeline for a date
python bin/validate_pipeline.py 2021-11-22

# Verbose with missing details
python bin/validate_pipeline.py 2021-11-22 --verbose --show-missing

# Validate specific phase
python bin/validate_pipeline.py 2021-11-22 --phase 4
```

**What it checks:**
- Phase 1-5 data presence
- Cross-table consistency
- Processor run history
- Player universe completeness

### 4.2 GCS → BigQuery Completeness
**File:** `bin/validation/validate_gcs_bq_completeness.py`

```bash
# Validate Phase 1→2 flow
python bin/validation/validate_gcs_bq_completeness.py 2021-11-22

# Date range
python bin/validation/validate_gcs_bq_completeness.py 2021-11-01 2021-11-30 --format json
```

**What it checks:**
- Orphaned GCS files (scraped but not processed)
- Processing gaps
- Record count ratios

### 4.3 Backfill Range Verification
**File:** `bin/backfill/verify_backfill_range.py`

```bash
python bin/backfill/verify_backfill_range.py --start-date 2021-11-01 --end-date 2021-11-30 --verbose
```

**What it checks:**
- Phase 3 analytics tables have data
- Phase 4 precompute tables have data
- Bootstrap periods properly skipped
- Coverage percentages

### 4.4 Phase-Specific Validators
```bash
# Phase 3 validation
python -c "
from shared.validation.validators.phase3_validator import Phase3Validator
v = Phase3Validator()
v.validate_date('2021-11-22')
"

# Phase 4 validation
python -c "
from shared.validation.validators.phase4_validator import Phase4Validator
v = Phase4Validator()
v.validate_date('2021-11-22')
"
```

---

## Part 5: Log Checking & Monitoring

### 5.1 What to Look For in Logs

**Success indicators:**
```
⏭️ BACKFILL MODE: Skipping completeness check for XXX players
Completeness check complete in 0.00s
```

**Warning indicators:**
```
WARNING: Low completeness percentage
WARNING: Missing upstream data
```

**Error indicators:**
```
ERROR: DependencyError
ERROR: Data quality threshold not met
```

### 5.2 BigQuery Execution Log Queries

```sql
-- Check recent processor runs
SELECT
  scraper_name,
  status,
  triggered_at,
  duration_seconds,
  error_message
FROM `nba_orchestration.scraper_execution_log`
WHERE DATE(triggered_at) = '2021-11-22'
  AND scraper_name LIKE '%shot_zone%' OR scraper_name LIKE '%composite%'
ORDER BY triggered_at DESC;

-- Check for failures
SELECT *
FROM `nba_orchestration.scraper_execution_log`
WHERE status = 'failed'
  AND DATE(triggered_at) >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY triggered_at DESC;
```

### 5.3 Monitoring Commands

```bash
# Quick health check
./bin/orchestration/quick_health_check.sh

# Validation system health
./bin/validation/validation_health_check.sh

# Check Pub/Sub health
./bin/orchestration/check_pubsub_health.sh

# Monitor backfill progress
./bin/infrastructure/monitoring/monitor_backfill.sh
```

### 5.4 Alert Configuration

Alerts are sent via:
- **Email:** SendGrid/Brevo/AWS SES (configured via env vars)
- **Slack:** Webhook to #nba-alerts channel
- **BigQuery:** Logged to `nba_orchestration.scraper_execution_log`

Check alert manager settings:
```python
from shared.alerts.alert_manager import get_alert_manager
alert_mgr = get_alert_manager(backfill_mode=True)
print(f"Rate limit: {alert_mgr.rate_limit_minutes} minutes")
print(f"Max alerts per category: {alert_mgr.max_alerts_per_category}")
```

---

## Part 6: Full Testing Plan (Step by Step)

### Phase A: Pre-Test Verification
```bash
# 1. Verify all files modified correctly
git diff --stat

# 2. Run syntax checks
python -m py_compile data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py
python -m py_compile data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
python -m py_compile data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
python -m py_compile shared/utils/completeness_checker.py

# 3. Run unit tests
python -m pytest shared/utils/tests/test_completeness_checker.py -v
```

### Phase B: Single Date Test (2021-11-22)
```bash
# 1. Run preflight check
python bin/backfill/preflight_check.py --date 2021-11-22 --verbose

# 2. Run PSZA processor
.venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
p = PlayerShotZoneAnalysisProcessor()
p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
print(f'Stats: {p.stats}')
"

# 3. Run TDZA processor
.venv/bin/python -c "
from datetime import date
from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor
p = TeamDefenseZoneAnalysisProcessor()
p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
print(f'Stats: {p.stats}')
"

# 4. Run PCF processor
.venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_composite_factors.player_composite_factors_processor import PlayerCompositeFactorsProcessor
p = PlayerCompositeFactorsProcessor()
p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
print(f'Stats: {p.stats}')
"

# 5. Run ML Feature Store processor
.venv/bin/python -c "
from datetime import date
from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
p = MLFeatureStoreProcessor()
p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
print(f'Stats: {p.stats}')
"

# 6. Validate results
python bin/validate_pipeline.py 2021-11-22 --phase 4 --verbose
```

### Phase C: Date Range Test (November 2021)
```bash
# 1. Use Phase 4 backfill orchestrator
./bin/backfill/run_phase4_backfill.sh --start-date 2021-11-01 --end-date 2021-11-30 --dry-run

# 2. If dry-run passes, run actual backfill
./bin/backfill/run_phase4_backfill.sh --start-date 2021-11-01 --end-date 2021-11-30

# 3. Verify results
python bin/backfill/verify_backfill_range.py --start-date 2021-11-01 --end-date 2021-11-30 --verbose
```

### Phase D: Post-Test Validation
```bash
# 1. Run full pipeline validation
python bin/validate_pipeline.py 2021-11-22 --verbose

# 2. Check BigQuery for data
bq query --use_legacy_sql=false '
SELECT
  analysis_date,
  COUNT(*) as player_count,
  AVG(completeness_pct) as avg_completeness
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date BETWEEN "2021-11-01" AND "2021-11-30"
GROUP BY analysis_date
ORDER BY analysis_date
'

# 3. Check for any quality issues
bq query --use_legacy_sql=false '
SELECT *
FROM `nba_precompute.player_shot_zone_analysis`
WHERE analysis_date = "2021-11-22"
  AND (paint_rate IS NULL OR total_shots IS NULL)
LIMIT 10
'
```

---

## Part 7: Processor Dependency Chain

### 7.1 Phase 4 Execution Order

```
┌─────────────────────────────────────────────────────────────┐
│  PARALLEL PHASE (No dependencies between #1 and #2)        │
│  ┌─────────────────────┐  ┌─────────────────────┐          │
│  │ #1 TDZA            │  │ #2 PSZA            │          │
│  │ team_defense_zone   │  │ player_shot_zone   │          │
│  │ 11:00 PM           │  │ 11:15 PM           │          │
│  └─────────────────────┘  └─────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  SEQUENTIAL PHASE (Must run in order)                      │
│  ┌─────────────────────┐                                   │
│  │ #3 PCF              │ ← Depends on #1, #2               │
│  │ player_composite    │                                   │
│  │ 11:30 PM           │                                   │
│  └─────────────────────┘                                   │
│            │                                               │
│            ▼                                               │
│  ┌─────────────────────┐                                   │
│  │ #4 PDC              │ ← Depends on #1, #2, #3           │
│  │ player_daily_cache  │                                   │
│  │ 11:45 PM           │                                   │
│  └─────────────────────┘                                   │
│            │                                               │
│            ▼                                               │
│  ┌─────────────────────┐                                   │
│  │ #5 ML               │ ← Depends on ALL                  │
│  │ ml_feature_store    │                                   │
│  │ 12:00 AM           │                                   │
│  └─────────────────────┘                                   │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Processors Modified (Session 64)

| Processor | File | Lines Modified | Change |
|-----------|------|----------------|--------|
| PSZA | `player_shot_zone_analysis_processor.py` | 580-610, 1133-1134 | Skip completeness + bug fix |
| PCF | `player_composite_factors_processor.py` | 824-855 | Skip completeness |
| ML | `ml_feature_store_processor.py` | 763-795 | Skip completeness |

### 7.3 Processors NOT Modified

| Processor | File | Reason |
|-----------|------|--------|
| TDZA | `team_defense_zone_analysis_processor.py` | Team-level, different completeness pattern |
| PDC | `player_daily_cache_processor.py` | Already has optimized completeness handling |

---

## Part 8: Quick Reference Commands

### Start Testing
```bash
# Quick single-date test
python bin/backfill/preflight_check.py --date 2021-11-22 && \
.venv/bin/python -c "
from datetime import date
from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
p = PlayerShotZoneAnalysisProcessor()
p.run({'analysis_date': date(2021, 11, 22), 'backfill_mode': True, 'skip_downstream_trigger': True})
print('SUCCESS' if p.stats.get('processed', 0) > 0 else 'FAILED')
"
```

### Full Phase 4 Backfill
```bash
./bin/backfill/run_phase4_backfill.sh --start-date 2021-11-01 --end-date 2021-11-30
```

### Check Results
```bash
python bin/backfill/verify_backfill_range.py --start-date 2021-11-01 --end-date 2021-11-30 --verbose
```

### Monitor Progress
```bash
./bin/infrastructure/monitoring/monitor_backfill.sh
```

---

## Part 9: Files Modified in Session 64

| File | Status | Description |
|------|--------|-------------|
| `data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py` | Modified | Skip completeness + bug fix |
| `data_processors/precompute/player_composite_factors/player_composite_factors_processor.py` | Modified | Skip completeness |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Modified | Skip completeness |
| `shared/utils/completeness_checker.py` | Modified | Added `check_daily_completeness_fast()` |
| `docs/09-handoff/2025-12-07-SESSION64-COMPLETENESS-CHECKER-OPTIMIZATION.md` | Modified | Updated status |

---

## Part 10: Expected Outcomes

### Success Criteria
1. Phase 4 processors complete in ~30-60 seconds (vs 600+ seconds before)
2. Logs show "BACKFILL MODE: Skipping completeness check"
3. Data quality unchanged (same records produced)
4. No new errors introduced
5. Validation scripts pass

### Performance Targets
| Metric | Before | After | Target |
|--------|--------|-------|--------|
| PSZA processing time | 600+ seconds | ~30-60 seconds | <120 seconds |
| PCF processing time | 600+ seconds | ~30-60 seconds | <120 seconds |
| ML processing time | 600+ seconds | ~30-60 seconds | <120 seconds |
| Full Phase 4 (1 date) | 30+ minutes | ~5 minutes | <10 minutes |

---

## Part 11: Rollback Plan

If issues are discovered:

```bash
# 1. Revert changes
git checkout HEAD~1 -- data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py
git checkout HEAD~1 -- data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
git checkout HEAD~1 -- data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
git checkout HEAD~1 -- shared/utils/completeness_checker.py

# 2. Verify revert
git diff

# 3. Re-run processing
./bin/backfill/run_phase4_backfill.sh --start-date 2021-11-22 --end-date 2021-11-22
```

---

## Part 12: Next Steps (Future Sessions)

1. **Test the changes** using the plan above
2. **Run full November 2021 backfill** to verify at scale
3. **Monitor data quality** after backfill completes
4. **Consider adding** upstream processor status check (safeguard)
5. **Consider adding** date-range continuity check (safeguard)
6. **Update daily orchestration** to use `check_daily_completeness_fast()`

---

**Document Created:** 2025-12-07
**Author:** Session 65 (Claude)
**Previous Session:** [Session 64 - Completeness Checker Optimization](./2025-12-07-SESSION64-COMPLETENESS-CHECKER-OPTIMIZATION.md)
