# Session 91 Start Prompt

Copy everything below the line into a new chat:

---

## Context: Session 91 - Verification & Phase 6 Deployment

### Previous Session Summary

Session 88 fixed the model attribution NULL bug:
- **Bug:** `model_file_name` and related fields were NULL in BigQuery
- **Root cause:** Nested metadata access was wrong in `worker.py:1812`
- **Fix:** Commit `4ada201f` - access `prediction['metadata']['metadata']` instead of `prediction['metadata']`
- **Deployed:** `prediction-worker-00087-8nb`

### Priority 1: Verify Model Attribution Fix

Run this query to check if the fix worked:

```bash
bq query --use_legacy_sql=false "
SELECT model_file_name, model_training_start_date, COUNT(*) as cnt
FROM nba_predictions.player_prop_predictions
WHERE created_at >= TIMESTAMP('2026-02-03 10:00:00')
  AND system_id = 'catboost_v9'
GROUP BY 1, 2"
```

**Expected:** `model_file_name = 'catboost_v9_feb_02_retrain.cbm'`
**If NULL:** Need to add debug logging to trace the issue

### Priority 2: Daily Validation

Run `/validate-daily` to check system health. Previous validation (hit context limit) showed:
- Phase 3: 3/5 processors (may be mode-aware, check `_mode` field)
- Hit rates: 22-39% (verify edge filtering applied)
- Minutes coverage: 59.2%

### Priority 3: Deploy Phase 6 Exporters

Session 90 created 4 new exporters but didn't commit/deploy. Files are ready:

```bash
# Check untracked files
git status --short | grep "^??"

# Key files to commit:
# - data_processors/publishing/*_exporter.py (4 new exporters)
# - shared/config/subset_public_names.py
# - backfill_jobs/publishing/daily_export.py (modified)
# - orchestration/cloud_functions/phase5_to_phase6/main.py (modified)
```

See `docs/09-handoff/2026-02-03-SESSION-90-HANDOFF.md` for full deployment steps.

### Reference Docs

- `docs/09-handoff/2026-02-03-SESSION-88-MODEL-ATTRIBUTION-FIX.md` - Bug fix details
- `docs/09-handoff/2026-02-03-SESSION-90-HANDOFF.md` - Phase 6 exporter implementation

### Quick Start

1. Verify model attribution: Run the bq query above
2. If working: Run `/validate-daily` for system health check
3. Then: Commit and deploy Phase 6 exporters
