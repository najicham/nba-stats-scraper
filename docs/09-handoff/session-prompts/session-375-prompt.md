# Session 375 Handoff — Feature Distribution Health Validation

## What Was Done

Session 375 implemented comprehensive feature store distribution validation — 5 components designed to catch "plausible but wrong" bugs like Feature 41 (spread_magnitude) being ALL ZEROS for 4 months. All code is written and tested against live data but **NOT yet committed or deployed**.

## Changes (all uncommitted)

### 1. NEW: `bin/validation/feature_distribution_health.py`
Standalone CLI tool that audits all 57 features for distribution health. Runs two BQ queries (current period + 4-week baseline), then evaluates each feature against per-feature health profiles.

**5 checks per feature:** constant-value detection, zero-rate anomaly, NULL-rate anomaly, distribution drift (>3 sigma shift), source cross-validation (Features 25, 41 vs raw tables).

**Tested against live data:** PASS on 2026-02-28 (56 features checked, 1 skipped). Feature 41 confirmed healthy (stddev=4.244, 27 distinct values, source values match raw spreads within 0.3).

```bash
python bin/validation/feature_distribution_health.py --date 2026-02-28 --verbose
```

### 2. `ml_feature_store_processor.py` — Write-time prevention expanded
- `FEATURE_VARIANCE_THRESHOLDS`: 10 → 20 features (added 3, 13, 14, 32, 38, **41**, 42, 43, 47, 48)
- Feature 47 `ML_FEATURE_RANGES`: Fixed from `(0, 0)` → `(0, 100)` — it's NOT dead (avg=44)

### 3. `.claude/skills/spot-check-features/SKILL.md` — Added Distribution Health Audit section
References the new CLI script with command, expected output, investigation steps.

### 4. `.claude/skills/validate-feature-drift/SKILL.md` — Comprehensive rewrite
- Replaced ALL `features[OFFSET(N)]` → `feature_N_value` columns (deprecated array)
- Removed all `ARRAY_LENGTH(features) >= 33` filters
- Expanded monitored features (added 41, 42, 8, 31, 22, 38)
- Added Check 3B: Constant-Value Detection with BQ query
- References CLI tool for comprehensive checks

### 5. `.claude/skills/validate-daily/SKILL.md` — Added Phase 0.493
Inserted between Phase 0.49 and Phase 0.495. Calls the CLI script, documents PASS/WARN/FAIL thresholds, investigation steps.

## What Needs to Happen Next

1. **Commit and push** all changes (auto-deploys processor via Cloud Build)
2. **Deploy processor** if Cloud Build doesn't cover it: `./bin/deploy-service.sh nba-phase4-precompute-processors`
3. **Run `/daily-steering`** to check current model health and pipeline status
4. **Verify deployment** didn't introduce regressions: `./bin/check-deployment-drift.sh --verbose`

## Key Files Modified

| File | Status |
|------|--------|
| `bin/validation/feature_distribution_health.py` | NEW (untracked) |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Modified |
| `.claude/skills/spot-check-features/SKILL.md` | Modified |
| `.claude/skills/validate-feature-drift/SKILL.md` | Modified |
| `.claude/skills/validate-daily/SKILL.md` | Modified |

## Also Uncommitted (from prior sessions)

- `ml/experiments/quick_retrain.py` — has uncommitted changes from prior sessions
- `backfill_jobs/feature_store/fix_spread_features.py` — spread fix backfill script
- `results/session_373/` and `results/session_374_e2/` — experiment results

## Known Calibration Decisions

Feature 8 (`usage_spike_score`) is set to `min_stddev=0.0, min_distinct=1` because it legitimately collapses to all zeros in Feb+ (Session 370 adversarial validation confirmed this is seasonal, not a bug). If this feature gets revived or starts varying again in a future season, the thresholds should be tightened.

Vegas-related features (25-28, 50, 53-54) have `expected_null_pct` set to 0.55-0.60 because ~50% of players don't have prop lines (bench/role players).
