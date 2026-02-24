# Session 334 Handoff — Prevention Improvements & System Hardening

**Date:** 2026-02-24
**Focus:** Build prevention mechanisms to catch the classes of bugs found in Sessions 332-333
**Status:** COMPLETE — all 8 items implemented

## Context — What Broke and Why

Session 333 fixed 8 issues that share a common theme: **things that should have been caught automatically but weren't**. Every issue was manual cleanup that could have been prevented by a pre-commit hook, a monitoring query, or a post-action validation step.

| Issue | Root Cause | Time to Detect | Should Have Been |
|-------|-----------|----------------|------------------|
| 4 models in GCS but not in registry | `quick_retrain.py` auto-register silently fails | ~7 days | Post-retrain verification gate |
| Duplicate enabled families in registry | No uniqueness constraint on `(model_family, enabled)` | Weeks | Registry consistency check |
| Hardcoded `catboost_v9` in 2 files | No scan for hardcoded model IDs | Since V12 promotion | Pre-commit hook |
| `v12_vegas_q43` misclassified as `v12_mae` | Pattern matching dict didn't handle naming variant | Since retrain | Unit tests for classify_system_id() |
| BDL workflows running for disabled scrapers | No link between scraper status and monitoring workflows | Months (96 errors/day) | Workflow-scraper dependency validation |
| CompletionTracker silently swallowing errors | Non-blocking error handlers, no alerting | 30+ days | Error-level logging + staleness alert |
| `validation-runner` no Cloud Build trigger | Never added when function was created | Since creation | Trigger audit script |
| `nba-grading-service` not in auto-deploy | Not added to workflow service list | Since creation | Auto-deploy consistency check |

## Current System State

| Property | Value |
|----------|-------|
| Champion Model | `catboost_v12` (interim, promoted Session 332) |
| Champion State | HEALTHY — 59.6% HR 7d (N=47) |
| Best Bets 30d | **34-16 (68.0% HR)** |
| Shadow Models | 7 enabled families, 4 freshly retrained (Jan 4–Feb 15) |
| Deployment Drift | ZERO — all services current as of Session 333 |
| BQ Permission Errors | ~0/day (was 110/day — BDL workflows disabled, SA roles granted) |

## Implementation Plan — Ordered by Impact

### 1. CRITICAL: Post-Retrain Model Verification Gate

**Problem:** `quick_retrain.py` has auto-register logic (line ~2873) but no verification that registration succeeded. Models can be trained, uploaded to GCS, and never appear in the registry.

**Files:**
- `ml/experiments/quick_retrain.py` — add verification after `auto_register_in_model_registry()`
- `bin/retrain.sh` — add post-retrain registry check

**Implementation:**
```python
# In quick_retrain.py, after auto_register_in_model_registry():
# Verify the model actually appears in registry
verify_query = f"""
SELECT model_id, enabled, status
FROM nba_predictions.model_registry
WHERE model_id = '{model_id}'
"""
result = bq_client.query(verify_query).result()
rows = list(result)
if not rows or not rows[0].enabled:
    raise RuntimeError(f"CRITICAL: Model {model_id} not found in registry after registration!")
logger.info(f"Verified: {model_id} registered with enabled={rows[0].enabled}, status={rows[0].status}")
```

In `retrain.sh`, add at end:
```bash
# Post-retrain registry consistency check
echo "Verifying registry consistency..."
DUPLICATES=$(bq query --use_legacy_sql=false --project_id=nba-props-platform --format=csv --quiet \
  "SELECT model_family, COUNT(*) as cnt FROM nba_predictions.model_registry WHERE enabled=TRUE GROUP BY 1 HAVING cnt > 1")
if [ -n "$DUPLICATES" ]; then
    echo "WARNING: Duplicate enabled models detected:"
    echo "$DUPLICATES"
fi

ORPHANS=$(bq query --use_legacy_sql=false --project_id=nba-props-platform --format=csv --quiet \
  "SELECT model_id FROM nba_predictions.model_registry WHERE enabled=TRUE AND gcs_path NOT IN (SELECT path FROM gcs_model_inventory)")
# ... etc
```

---

### 2. CRITICAL: Pre-Commit Hook — Hardcoded Model ID Detection

**Problem:** When champion model changes (V9→V12), files with hardcoded `catboost_v9` aren't flagged. Found in `player_blacklist.py` and `signal_health.py`.

**File to create:** `.pre-commit-hooks/validate_model_references.py`

**Logic:**
```python
"""
Scan for hardcoded model system_ids in signal/prediction code.
Allowed locations: bin/, docs/, tests/, config files, retrain scripts.
Flagged locations: ml/signals/, predictions/, data_processors/
"""
import re, sys, glob

PATTERN = re.compile(r"""(?:system_id|SYSTEM_ID|model_id)\s*=\s*['"]catboost_v\d""")
ALLOWED_DIRS = {'bin/', 'docs/', 'tests/', 'ml/experiments/', 'shared/config/model_selection.py'}
SCAN_DIRS = ['ml/signals/', 'predictions/', 'data_processors/', 'orchestration/']

# Scan files, flag matches not in ALLOWED_DIRS
```

**Add to `.pre-commit-config.yaml`:**
```yaml
- id: validate-model-references
  name: Check for hardcoded model IDs
  description: Prevents hardcoded catboost_v* system_ids in signal/prediction code (Session 333)
  entry: python .pre-commit-hooks/validate_model_references.py
  language: python
  pass_filenames: false
  files: ^(ml/signals|predictions|data_processors|orchestration)/.*\.py$
  verbose: true
```

---

### 3. CRITICAL: Unit Tests for Cross-Model Pattern Classification

**Problem:** `classify_system_id()` in `cross_model_subsets.py` misclassified `catboost_v12_vegas_q43_*` as `v12_mae`. No tests existed.

**File to create:** `tests/unit/shared/test_cross_model_subsets.py`

**Test cases:**
```python
from shared.config.cross_model_subsets import classify_system_id

# Current production models
def test_v9_mae_classification():
    assert classify_system_id('catboost_v9') == 'v9_mae'
    assert classify_system_id('catboost_v9_50f_train20260104_20260215') == 'v9_mae'

def test_v12_mae_classification():
    assert classify_system_id('catboost_v12') == 'v12_mae'
    assert classify_system_id('catboost_v12_mae_train0104_0215') == 'v12_mae'

def test_v12_vegas_q43_classification():
    # This was the Session 333 bug
    assert classify_system_id('catboost_v12_vegas_q43_train0104_0215') == 'v12_vegas_q43'
    assert classify_system_id('catboost_v12_q43_train_something') == 'v12_vegas_q43'

def test_v12_noveg_classification():
    assert classify_system_id('catboost_v12_noveg_q43_train0104_0215') == 'v12_noveg_q43'

def test_v9_low_vegas_classification():
    assert classify_system_id('catboost_v9_low_vegas_train_something') == 'v9_low_vegas'

def test_no_ambiguous_classifications():
    """Every model in registry should classify to exactly one family."""
    # Query actual registry models if BQ available, or use known names
    known_models = [
        'catboost_v9', 'catboost_v12',
        'catboost_v12_vegas_q43_train0104_0215',
        'catboost_v12_noveg_q43_train0104_0215',
        'catboost_v12_noveg_mae_train0104_0215',
        'catboost_v12_mae_train0104_0215',
    ]
    for model in known_models:
        result = classify_system_id(model)
        assert result is not None, f"{model} classified as None!"
```

---

### 4. HIGH: Auto-Deploy Consistency Check

**Problem:** `check-deployment-drift.sh` monitors 15+ services. Auto-deploy workflow only deploys 6. Gap = silent drift.

**File to create:** `.pre-commit-hooks/validate_auto_deploy_consistency.py`

**Logic:**
- Parse `SERVICE_SOURCES` from `bin/check-deployment-drift.sh`
- Parse Cloud Run services from auto-deploy workflow (`.github/workflows/` or `cloudbuild*.yaml`)
- For each Cloud Run service in SERVICE_SOURCES (exclude Cloud Functions — they use `cloudbuild-functions.yaml`):
  - Verify it has a corresponding Cloud Build trigger
- Flag: "nba-grading-service is monitored for drift but has no auto-deploy trigger"

**Also create:** `bin/validation/audit_cloud_build_triggers.sh`
```bash
#!/bin/bash
# Compare services in check-deployment-drift.sh vs actual Cloud Build triggers
# Run: ./bin/validation/audit_cloud_build_triggers.sh

echo "=== Cloud Build Trigger Audit ==="

# Cloud Run services in drift check
echo "Services monitored for drift:"
grep -oP '\["[^"]+"\]' bin/check-deployment-drift.sh | tr -d '[]"' | sort

echo ""
echo "Cloud Build triggers:"
gcloud builds triggers list --region=us-west2 --project=nba-props-platform \
  --format="value(name)" | sort

echo ""
echo "Cloud Functions in repo (need triggers):"
ls -d orchestration/cloud_functions/*/ | xargs -I{} basename {} | sort

echo ""
echo "Missing triggers (manual comparison needed):"
# Diff the lists
```

---

### 5. HIGH: CompletionTracker Error Escalation

**Problem:** `shared/utils/completion_tracker.py` catches all exceptions with `logger.warning()` and continues. Failures are invisible.

**Files:**
- `shared/utils/completion_tracker.py` — change `logger.warning` to `logger.error` for write failures
- `orchestration/cloud_functions/daily_health_check/main.py` — add completion staleness check

**Implementation in completion_tracker.py:**
```python
# Change from:
except Exception as e:
    logger.warning(f"Firestore write failed: {e}")
    pass

# To:
except Exception as e:
    logger.error(f"COMPLETION_TRACKER_FAILURE: Firestore write failed for phase={phase}, game_date={game_date}: {e}")
    # Still attempt BigQuery fallback, but error is now visible in Cloud Logging
```

**Add to daily-health-check (monitoring query):**
```sql
-- Completion tracking staleness check
SELECT
  'completion_tracking' as check_name,
  MAX(completed_at) as last_write,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(completed_at), HOUR) as hours_stale,
  CASE WHEN TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(completed_at), HOUR) > 24
       THEN 'ALERT' ELSE 'OK' END as status
FROM nba_orchestration.phase_completions
```

---

### 6. MEDIUM: Model Registry Consistency Monitor

**Problem:** Duplicate enabled models per family, stale entries, orphaned GCS models.

**File to create:** `bin/validation/validate_model_registry.py`

**Checks:**
1. No duplicate enabled models per family: `SELECT model_family, COUNT(*) ... HAVING cnt > 1`
2. All enabled models have valid GCS paths: `gsutil stat {gcs_path}` for each
3. All GCS models in `monthly/` dir have registry entries
4. Production model is the one in `model_selection.py`
5. No enabled model has `status = 'deprecated'`

**Run frequency:** Daily (add to `daily-health-check`) + after every retrain

---

### 7. MEDIUM: Disabled Scraper Workflow Validation

**Problem:** BDL scrapers disabled but monitoring workflows kept running.

**File to create:** `bin/validation/validate_workflow_dependencies.py`

**Logic:**
- Parse `shared/config/scraper_retry_config.yaml` for `enabled: false` scrapers
- Parse `.github/workflows/*.yml` for references to disabled scraper table names (e.g., `bdl_*`, `bdb_*`)
- Flag: "bdb-pbp-monitor.yml references bdl_ tables but bdl scrapers are disabled"

---

### 8. LOW: Cloud Build Trigger for validation-runner

**Create trigger:**
```bash
gcloud builds triggers create cloud-source-repositories \
  --name=deploy-validation-runner \
  --region=us-west2 \
  --project=nba-props-platform \
  --repo=nba-stats-scraper \
  --branch-pattern='^main$' \
  --build-config=cloudbuild-functions.yaml \
  --included-files='orchestration/cloud_functions/validation_runner/**,shared/**' \
  --substitutions="_FUNCTION_NAME=validation-runner,_FUNCTION_DIR=orchestration/cloud_functions/validation_runner,_ENTRY_POINT=validate_pipeline"
```

Or add `validation-runner` to the `cloudbuild-functions.yaml` matrix if it supports multiple functions.

---

## Implementation Results

All 8 items implemented in commit `43e93d05`.

| # | Item | Status | Files |
|---|------|--------|-------|
| 1 | Post-retrain verification gate | DONE | `ml/experiments/quick_retrain.py` |
| 2 | Pre-commit: hardcoded model IDs | DONE | `.pre-commit-hooks/validate_model_references.py`, `.pre-commit-config.yaml` |
| 3 | Unit tests: classify_system_id() | DONE | `tests/unit/shared/test_cross_model_subsets.py` (69 tests) |
| 4 | Auto-deploy: nba-grading-service | DONE | `.github/workflows/auto-deploy.yml` |
| 5 | Completion staleness monitor | DONE | `orchestration/cloud_functions/daily_health_check/main.py` |
| 6 | Model registry consistency | DONE | `bin/validation/validate_model_registry.py` |
| 7 | Workflow dependency validator | DONE | `bin/validation/validate_workflow_dependencies.py` |
| 8 | Cloud Build trigger | DONE | Created `deploy-validation-runner` trigger in GCP |

### Bonus: Fixed 6 More Hardcoded V9 References

The new pre-commit hook found 10 violations. 4 were legitimate (prediction system class identity, excluded from hook). The other 6 were real bugs — still referencing V9 after V12 promotion:

| File | Was | Now |
|------|-----|-----|
| `subset_materializer.py` | `CHAMPION_SYSTEM_ID = 'catboost_v9'` | `get_champion_model_id()` |
| `all_subsets_picks_exporter.py` | `CHAMPION_SYSTEM_ID = 'catboost_v9'` | `get_champion_model_id()` |
| `season_subset_picks_exporter.py` | `CHAMPION_SYSTEM_ID = 'catboost_v9'` | `get_champion_model_id()` |
| `quality_gate.py` (2 methods) | `system_id: str = 'catboost_v9'` | `system_id: str = None` → dynamic |
| `signal_calculator.py` | `system_id: str = 'catboost_v9'` | `system_id: str = None` → dynamic |

### Key Design Decisions

1. **CompletionTracker code was already correct** — it uses `logger.error()` with retry. The handoff doc's analysis was wrong. The real gap was monitoring staleness, not code changes.

2. **Pre-commit hook excludes prediction system classes** — `predictions/worker/prediction_systems/` files legitimately define `SYSTEM_ID = "catboost_v9"` etc. as class identity. Also excludes `worker.py` which labels V12 predictions in its main loop.

3. **36-hour staleness threshold** — accounts for off-days with no games. 24h would false-positive on days without games.

4. **Model registry validator uses `google.cloud.bigquery`** — not `bq` CLI, so it works in Cloud Functions. GCS check is optional (`--skip-gcs`).

## What's NOT in this session (being handled elsewhere)

- **Orchestrator cold-start fixes** (Phase 3→4 "no available instance") — other chat handling minScale=1
- **Shadow model evaluation** — need 2-3 days of data first (check Feb 25-26)
- **Champion promotion** — after shadow data, top candidates: v12_vegas_q43 (66.7% eval HR), v12_noveg_q43 (65.7%)

## Quick Start for New Chat

```bash
# 1. Verify shadow models are generating predictions (should see 4 new model IDs)
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date = '2026-02-24' AND system_id LIKE '%train0104_0215%' GROUP BY 1"

# 2. Run daily steering
/daily-steering

# 3. Run the new validators
python bin/validation/validate_model_registry.py
python bin/validation/validate_workflow_dependencies.py
```
