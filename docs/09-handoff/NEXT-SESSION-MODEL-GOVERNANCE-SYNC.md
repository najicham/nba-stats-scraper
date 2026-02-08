# Next Session: Model Governance Sync Infrastructure

**Recommended agent:** Sonnet (focused implementation, clear requirements)

## Copy-paste prompt:

```
Session: Model Governance Sync

Read the handoff: docs/09-handoff/2026-02-08-SESSION-164-HANDOFF.md
Read the project docs: docs/08-projects/current/model-governance/00-PROJECT-OVERVIEW.md
Read the current model registry script: bin/model-registry.sh
Read the GCS manifest: gsutil cat gs://nba-props-platform-models/catboost/v9/manifest.json

## Problem

We have 4 places that describe model metadata and they drift apart:
1. GCS manifest.json (source of truth — has correct training dates)
2. BQ model_registry table (had WRONG training_end_date, fixed in Session 164)
3. CLAUDE.md (manually maintained, can go stale)
4. Model filenames (use creation timestamp, not training dates)

Session 163 discovered a retrained model crashed hit rate from 71.2% to 51.2%. Future sessions could accidentally retrain the same model or deploy without proper checks.

## Tasks (implement all of these)

1. **Registry sync command**: Add `./bin/model-registry.sh sync` that reads the GCS manifest.json and upserts into BQ model_registry. This ensures BQ always matches GCS.

2. **Pre-training duplicate check**: In `ml/experiments/quick_retrain.py`, before training begins, query BQ model_registry to check if a model with the same training_start_date + training_end_date already exists. If it does, warn and require --force flag to proceed.

3. **Model naming convention**: Update `ml/experiments/quick_retrain.py` to save models with filename format: `catboost_v9_33f_train{start}-{end}_{timestamp}.cbm` (e.g., `catboost_v9_33f_train20251102-20260108_20260201T011018.cbm`). This makes training range visible in the filename.

4. **Registry validation in deploy**: Add to `bin/check-deployment-drift.sh` a check that compares the CATBOOST_V9_MODEL_PATH env var against the GCS manifest production_model field. Alert if they don't match.

5. **Auto-generate CLAUDE.md model section**: Add `./bin/model-registry.sh claude-md` that outputs a formatted snippet for CLAUDE.md's MODEL section, pulling from the BQ registry. Include: model file, training dates, hit rate, status, SHA256.

## Report back with:
- What was implemented
- Any issues encountered
- Updated model registry output (`./bin/model-registry.sh list`)
- The auto-generated CLAUDE.md snippet
- Whether any existing tests needed updating
```

## Why Sonnet

This is a focused implementation task with:
- Clear, well-defined requirements
- No complex debugging or investigation
- Straightforward shell scripting and Python changes
- All context is self-contained in the handoff + existing files

Opus would be overkill. Save it for the Pub/Sub backfill investigation which requires debugging live infrastructure.
