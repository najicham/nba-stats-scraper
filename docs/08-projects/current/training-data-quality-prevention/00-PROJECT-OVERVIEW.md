# Training Data Quality Prevention

**Project:** Prevent training data contamination from recurring
**Sessions:** 157 (discovery + fix), 158 (prevention + backfill)
**Status:** Active (backfill in progress)

## Problem Statement

Session 157 discovered that **33.2% of V9 training data was contaminated** with default feature values. This occurred silently — the ML feature store wrote records with defaults when upstream Phase 4 processors (especially `PlayerCompositeFactorsProcessor`) didn't run or failed. The contamination degraded model accuracy because the training data included fabricated feature values.

## Root Cause Analysis

### How Contamination Happens

1. **Phase 4 processor failure** — One or more upstream processors (composite factors, shot zone, etc.) don't run for a date
2. **Feature store runs anyway** — MLFeatureStoreProcessor runs but can't find Phase 4 data, so it uses default values for missing features
3. **No quality gate at write time** — Data is written to `ml_feature_store_v2` without validating contamination levels
4. **Training picks it up** — ML training queries the feature store and trains on contaminated records
5. **Model learns noise** — The model learns default values as real patterns, degrading accuracy

### Why It Was Silent

- The `feature_quality_score` aggregate masked component failures (Session 134 insight)
- The `is_quality_ready` field existed but wasn't checked during training
- No monitoring of default rates across the training window
- Phase 4→5 orchestrator only checked row counts, not quality metrics

## Three-Layer Fix (Session 157)

### Layer 1: Shared Training Data Loader
- **File:** `ml/training/shared_data_loader.py`
- Filters out records with `required_default_count > 0` during training data loading
- Ensures only clean data is used for model training

### Layer 2: Quality Score Capping
- **File:** `data_processors/precompute/ml_feature_store/quality_scorer.py`
- Caps `feature_quality_score` when `required_default_count > 0`
- Prevents contaminated records from appearing "high quality"

### Layer 3: Historical Fix
- Backfill of all affected dates with corrected processor code
- Ensures existing data is clean, not just future data

## Prevention Mechanisms (Session 158)

### 1. Post-Write Validation in ML Feature Store Processor
- **File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- Method: `_validate_written_data()` — runs after every write
- Calculates contamination metrics on just-written data
- Sends Slack alert if `pct_with_defaults > 30%`
- Non-blocking (data is already written), but enables fast response

### 2. Phase 4→5 Quality Check
- **File:** `orchestration/cloud_functions/phase4_to_phase5/main.py`
- Extended `verify_phase4_data_ready()` to check quality metrics
- Logs WARNING if `pct_quality_ready < 40%`
- Informational only (Phase 5 quality gate already blocks bad predictions)

### 3. Training Data Contamination Monitor
- **File:** `bin/monitoring/check_training_data_quality.sh`
- Daily monitoring script for the V9 training window
- Monthly breakdown showing clean vs contaminated percentages
- Exit code 1 if contamination > 5%
- Integrated into `/validate-daily` as Phase 0.487

### 4. Spot-Check Enhancement
- **File:** `.claude/skills/spot-check-features/SKILL.md`
- Added Check #28: Training Data Contamination Check
- Queries for monthly contamination breakdown
- Root cause analysis showing which features default most
- Session 157 baseline comparison

## Contamination Timeline

| Date Range | Contamination % | Cause | Status |
|------------|-----------------|-------|--------|
| Nov 2025 | ~33% | Composite factors not running | Fixed (Session 158 backfill) |
| Dec 2025 | ~15% | Partial processor coverage | Fixed (Session 158 backfill) |
| Jan 2026 | ~8% | Improved but not fully clean | Fixed (Session 158 backfill) |
| Feb 2026+ | <5% target | Prevention mechanisms active | Monitoring |

## Backfill Scope

### Current Season (Nov 2025 - Feb 2026)
- ~96 game dates
- Estimated 4-4.5 hours
- Runs all 5 Phase 4 processors per date

### Past 4 Seasons (Oct 2021 - Jun 2025)
- ~853 game dates
- Estimated 7-9 hours
- Queued after current season completes

## Verification

After backfill completes:
1. Run `./bin/monitoring/check_training_data_quality.sh` — contamination should be < 5%
2. Run `/spot-check-features` with Check #28
3. Compare monthly breakdown against Session 157 baselines
4. Verify Phase 6 exports updated

## Key Files

| File | Role |
|------|------|
| `ml/training/shared_data_loader.py` | Layer 1: Training data filtering |
| `data_processors/precompute/ml_feature_store/quality_scorer.py` | Layer 2: Quality score capping |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Post-write validation |
| `orchestration/cloud_functions/phase4_to_phase5/main.py` | Quality check at orchestration |
| `bin/monitoring/check_training_data_quality.sh` | Daily contamination monitor |
| `.claude/skills/spot-check-features/SKILL.md` | Check #28 |
| `.claude/skills/validate-daily/SKILL.md` | Phase 0.487 |

## Lessons Learned

1. **Aggregate scores lie** — Always check component-level quality, not just the aggregate
2. **Write-time validation is critical** — Don't just write and hope; validate what you wrote
3. **Training data quality needs monitoring** — Not just prediction quality
4. **Backfill after fixes** — Fixing the code isn't enough; historical data must be cleaned too
5. **Prevention > detection > remediation** — Layer all three

---
*Created: Session 158 (2026-02-08)*
