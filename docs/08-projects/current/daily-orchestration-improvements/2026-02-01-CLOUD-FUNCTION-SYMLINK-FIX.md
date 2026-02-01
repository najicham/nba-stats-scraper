# Cloud Function Symlink Fix - Feb 1, 2026

**Date**: 2026-02-01
**Session**: 69
**Status**: FIXED AND DEPLOYED
**Impact**: P1 - Orchestrator crashes causing completion tracking failures

---

## Problem Summary

Phase 3 completion tracking showed only 3/5 processors in Firestore, despite all 5 processors successfully writing data to BigQuery. This prevented reliable Phase 4 auto-triggering.

---

## Root Cause

**Missing symlinks** for `phase3_data_quality_check.py` in all Cloud Functions' `shared/validation/` directories.

### Error Chain

1. `shared/validation/__init__.py` imports `phase3_data_quality_check` (lines 38-42)
2. Cloud Functions had symlinks for other validation modules but NOT this one
3. Orchestrator crashed on startup with:
   ```
   ModuleNotFoundError: No module named 'shared.validation.phase3_data_quality_check'
   ```
4. Messages arriving during crash windows were not processed
5. Result: Only 3/5 processors appeared in Firestore completion

### Evidence from Logs

```
E  2026-02-01 16:56:04.172  ModuleNotFoundError: No module named 'shared.validation.phase3_data_quality_check'
```

---

## Fix Applied

### 1. Created Missing Symlinks

Added `phase3_data_quality_check.py` symlinks to all 7 Cloud Functions:

```bash
# Command used to fix all Cloud Functions
for dir in orchestration/cloud_functions/*/shared/validation; do
  cd "$dir"
  ln -s ../../../../../shared/validation/phase3_data_quality_check.py phase3_data_quality_check.py
done
```

**Affected Cloud Functions:**
- `auto_backfill_orchestrator`
- `daily_health_summary`
- `phase2_to_phase3`
- `phase3_to_phase4`
- `phase4_to_phase5`
- `phase5_to_phase6`
- `self_heal`

### 2. Redeployed Orchestrator

```bash
gcloud functions deploy phase3-to-phase4-orchestrator \
  --gen2 --runtime=python311 --region=us-west2 \
  --source=orchestration/cloud_functions/phase3_to_phase4 \
  --entry-point=orchestrate_phase3_to_phase4 \
  --trigger-topic=nba-phase3-analytics-complete
```

**Note:** The entry point is `orchestrate_phase3_to_phase4`, NOT `phase3_to_phase4_orchestrator`.

### 3. Commit

```
Commit: 0e0f0958
Message: fix: Add missing phase3_data_quality_check.py symlinks to Cloud Functions
```

---

## Verification

After deployment, orchestrator startup succeeded:

```
I  2026-02-01 17:55:25.987  Default STARTUP TCP probe succeeded after 1 attempt for container "worker" on port 8080.
```

New revision: `phase3-to-phase4-orchestrator-00030-miy`

---

## Secondary Finding: `upcoming_team_game_context` Low Completions

| Processor | Jan 31 Completions |
|-----------|-------------------|
| player_game_summary | 208 |
| team_defense_game_summary | 87 |
| team_offense_game_summary | 87 |
| upcoming_player_game_context | 90 |
| **upcoming_team_game_context** | **2** |

This is **expected behavior**, not a bug. The processor is only triggered by `nbac_schedule` data which arrives once per day, while other processors are triggered multiple times by various data sources.

---

## Prevention Recommendations

### 1. Pre-commit Hook for Symlink Validation

Add a hook to validate all symlinks exist before committing:

```python
# .pre-commit-hooks/validate_cloud_function_symlinks.py
import os
import sys

SHARED_VALIDATION_FILES = [
    'phase3_data_quality_check.py',
    # Add other files that should be symlinked
]

CLOUD_FUNCTIONS = [
    'auto_backfill_orchestrator',
    'daily_health_summary',
    'phase2_to_phase3',
    'phase3_to_phase4',
    'phase4_to_phase5',
    'phase5_to_phase6',
    'self_heal',
]

def check_symlinks():
    missing = []
    for func in CLOUD_FUNCTIONS:
        for file in SHARED_VALIDATION_FILES:
            path = f'orchestration/cloud_functions/{func}/shared/validation/{file}'
            if not os.path.islink(path):
                missing.append(path)

    if missing:
        print("Missing symlinks:")
        for path in missing:
            print(f"  - {path}")
        sys.exit(1)

    print("All Cloud Function symlinks present")
    sys.exit(0)

if __name__ == '__main__':
    check_symlinks()
```

### 2. CI/CD Check

Add to `.github/workflows/`:

```yaml
- name: Validate Cloud Function symlinks
  run: |
    for func in auto_backfill_orchestrator daily_health_summary phase2_to_phase3 phase3_to_phase4 phase4_to_phase5 phase5_to_phase6 self_heal; do
      for file in phase3_data_quality_check.py; do
        path="orchestration/cloud_functions/$func/shared/validation/$file"
        if [ ! -L "$path" ]; then
          echo "ERROR: Missing symlink $path"
          exit 1
        fi
      done
    done
```

### 3. Deployment Script Enhancement

Update deploy scripts to verify symlinks before deploying:

```bash
# In deploy-cloud-function.sh
verify_symlinks() {
    local func=$1
    local validation_dir="orchestration/cloud_functions/$func/shared/validation"

    if [ ! -L "$validation_dir/phase3_data_quality_check.py" ]; then
        echo "ERROR: Missing phase3_data_quality_check.py symlink in $func"
        exit 1
    fi
}
```

---

## Files Changed

| File | Change |
|------|--------|
| `orchestration/cloud_functions/*/shared/validation/phase3_data_quality_check.py` | Added symlinks (7 files) |

---

## Deployment Commands Reference

### Deploy phase3-to-phase4-orchestrator

```bash
gcloud functions deploy phase3-to-phase4-orchestrator \
  --gen2 \
  --runtime=python311 \
  --region=us-west2 \
  --source=orchestration/cloud_functions/phase3_to_phase4 \
  --entry-point=orchestrate_phase3_to_phase4 \
  --trigger-topic=nba-phase3-analytics-complete \
  --memory=512MB \
  --timeout=540s \
  --set-env-vars=GCP_PROJECT_ID=nba-props-platform,ENVIRONMENT=production \
  --min-instances=0 \
  --max-instances=5
```

### Verify Deployment

```bash
gcloud functions logs read phase3-to-phase4-orchestrator --region=us-west2 --limit=10
```

---

## Related Documents

- **Investigation Doc**: `docs/09-handoff/2026-02-01-ORCHESTRATION-ISSUES-INVESTIGATION.md`
- **Issue Tracking**: `docs/08-projects/current/daily-orchestration-issues-2026-02-01.md`
- **CLAUDE.md**: Heartbeat System section

---

**Document Created**: 2026-02-01 10:00 PST
**Author**: Claude Opus 4.5
