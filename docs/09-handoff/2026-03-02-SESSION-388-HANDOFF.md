# Session 388 Handoff — Emergency Fix: Auto-Deploy Cascade Failure

**Date:** 2026-03-02
**Status:** Pipeline restored. March 2 predictions generated (608). Signal fixes from Session 387 verified firing. Signal best bets = 0 picks (legitimate — legacy models dominate thin 4-game slate).

## What Was Done

### 1. Diagnosed & Fixed: Auto-Deploy Cascade Failure (4 Bugs)

Today's auto-deploy (triggered by docs commit ec08b64) picked up accumulated code changes from Sessions 379-387 that had never been deployed to Phase 4 or worker. This caused a cascading failure that blocked ALL predictions for March 2.

#### Bug 1: Feature Store BQ Write Failure
- **Symptom:** `No such field: feature_60_value` — 0 rows written to `ml_feature_store_v2` for March 2
- **Root cause:** V18 features (60-63) from Session 379 were extracted and written to record dict, but BQ schema only has columns `feature_0_value` through `feature_59_value`
- **Fix:** Truncate feature write loop: `features[:FEATURE_COUNT]` (line 1758)
- **File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

#### Bug 2: Quality Score Capped at 69 (Below 70% Threshold)
- **Symptom:** ALL clean players had `feature_quality_score = 69`, `quality_tier = poor` — nobody passed quality gate
- **Root cause:** `calculate_quality_score()` in quality_scorer.py uses `len(feature_sources)` (64 entries including V17/V18), NOT `FEATURE_COUNT` (54). Features 55-63 with source='missing' triggered `required_defaults >= 1` → quality capped at 69
- **Fix:** Truncate `feature_sources` to `FEATURE_COUNT` before passing to quality scorer
- **File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` (lines 1621-1628)

#### Bug 3: FEATURE_VERSION Mismatch
- **Symptom:** `CatBoost V8 requires feature_version in (v2_33features, ..., v2_54features), got 'v2_60features'`
- **Root cause:** FEATURE_VERSION constant was changed to `v2_60features` (matching 60-column schema) but worker's catboost_v8 whitelist only accepts up to `v2_54features`
- **Fix:** Set `FEATURE_VERSION = 'v2_54features'` (matching actual features used by models)
- **File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` (line 93)

#### Bug 4: Worker Crash-Loop (Missing PyYAML)
- **Symptom:** `ModuleNotFoundError: No module named 'yaml'` — worker couldn't boot
- **Root cause:** Import chain: `worker.py` → `shared.validation.__init__` → `scraper_config_validator` → `scraper_retry_config` → `import yaml`. PyYAML in `shared/requirements.txt` but NOT in worker's `requirements-lock.txt`
- **Fix:** Added `PyYAML==6.0.2` to `predictions/worker/requirements-lock.txt`
- **Key learning:** Worker Dockerfile uses `requirements-lock.txt`, NOT `requirements.txt`

### 2. Verified Session 387 Signal Fixes

Both revived signals confirmed firing on March 2:

| Signal | Fires | Status |
|--------|-------|--------|
| `line_rising_over` | 2 | CONFIRMED WORKING |
| `fast_pace_over` | 1 | CONFIRMED WORKING |

13 total distinct signals firing on March 2 (vs 13 on March 1 — but now includes the two previously dead signals).

### 3. Deploy Script Improvements

Added `--cpu-throttling` flag to both `deploy-service.sh` and `hot-deploy.sh` to ensure request-based billing on every deploy. Prevents services from silently reverting to instance-based billing.

## Deployments Made

| Service | Deploy Type | Time (UTC) | Fix |
|---------|------------|------------|-----|
| nba-phase4-precompute-processors | hot-deploy x3 | 22:35, 23:15, 23:40 | Bug 1, 2, 3 |
| prediction-worker | hot-deploy x2 | 23:07 (failed), 23:19 | Bug 4 |

## Pipeline State After Fixes

| Component | Status |
|-----------|--------|
| Feature store (March 2) | 72 players, 49 gold quality |
| Predictions (March 2) | 608 total (16 models × 40 players) |
| Signal tags (March 2) | 13 signals firing |
| Daily signals (March 2) | Written for all 16 models |
| Signal best bets (March 2) | 0 picks — legitimate (see Known Issues) |
| Signal canary | Deployed (Session 387) but not yet validated |

## Known Issues

### Signal Best Bets = 0 Picks (Legitimate)
- Export ran successfully after streaming buffer cleared, produced 0 qualifying picks
- **Filter breakdown (31 candidates):** 27 legacy_block (catboost_v9/v12 dead champions), 3 blacklist, 1 away_noveg
- Root cause: legacy champions still win model selection for most players (highest edge), but are blocked
- This is a thin 4-game day with only 40 players getting quality features — expected outcome
- **Systemic concern:** Legacy models (catboost_v9, catboost_v12) still dominating selection means newer models aren't generating competitive edges. Monitor on bigger game days.

### FEATURE_STORE_FEATURE_COUNT Inconsistency
- `ml_feature_store_processor.py` FEATURE_COUNT = 60
- `quality_scorer.py` FEATURE_COUNT = 54
- `FEATURE_NAMES` list has 60 entries but only 54 features are actually written to BQ
- **Not urgent** — the truncation fix handles this cleanly. But should be reconciled in a future session.

### V17/V18 Features Not Used
- Features 55-63 are extracted but truncated before writing and quality scoring
- MEMORY.md notes: "FEATURE_STORE_FEATURE_COUNT must stay 60 until BQ schema migration for features 60-63"
- V18 features are a dead end (Session 379: hurt HR when added to V12_NOVEG)
- **Consider:** Removing V17/V18 extraction code entirely to prevent future confusion

## Forward-Looking Items

### Next Session Priorities
1. **Verify signal best bets populated** for March 2 or March 3
2. **Monitor revived signals** — do they improve OVER HR? (target: OVER > 53.8%)
3. **Check train1228_0222 models** — accumulating data, check at N>=25
4. **Signal canary validation** — verify it runs in post_grading_export after grading
5. **Don't retrain** — wait for signal fix impact data (1-2 weeks)

### Deferred (Future Sessions)
- Auto-disable BLOCKED models (fleet lifecycle automation)
- Champion promotion pipeline
- Reconcile FEATURE_COUNT inconsistency (54 vs 60)
- Remove V17/V18 extraction code (dead-end features)
- Fix `shared/validation/__init__.py` transitive yaml import (add lazy import or restructure)
