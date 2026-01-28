# Next Session Handoff - Fix Orchestrator + Observability

**Date**: 2026-01-28
**Commit**: (pending - docs update)

---

## Copy This Prompt to Start Next Session

```
Continue data quality work from 2026-01-28 session.

## What Was Done
Session 1 (Jan 27):
- Fixed Phase 4 trigger_source extraction
- Added 16 new schema columns for data quality tracking
- Created monitoring queries and validation skills

Session 2 (Jan 28):
- Deployed BigQuery schema changes (13 + 3 columns)
- Deployed Phase 4 precompute service to Cloud Run
- Ran validation, found pipeline stalled since Jan 25

## Critical Issue Found
The phase3-to-phase4-orchestrator has a ModuleNotFoundError:
  File: orchestration/shared/utils/bigquery_utils.py:23
  Error: No module named 'shared.utils'

This is blocking Phase 4 and Phase 5 from running. Predictions stopped after Jan 25.

## Immediate Fix Needed
1. Fix import in bigquery_utils.py OR redeploy orchestrator with shared module
2. Redeploy phase3-to-phase4-orchestrator
3. Manually trigger Phase 4 for Jan 26, 27 to backfill predictions

## Observability Improvements Identified
See: docs/08-projects/current/2026-01-27-data-quality-investigation/SESSION-2-FINDINGS.md

1. Create service_errors table for centralized error logging
2. Create pipeline_health_summary view
3. Add Phase execution gap check to /validate-daily
4. Add Cloud Monitoring alert for stale phases

## Key Files
- orchestration/shared/utils/bigquery_utils.py (needs import fix)
- .claude/skills/validate-daily/SKILL.md (needs gap check)
```

---

## Quick Fix Commands

### Option 1: Fix the Import Path

Check `orchestration/shared/utils/bigquery_utils.py` line 23:
```python
# Current (broken):
from shared.utils.retry_with_jitter import retry_with_jitter

# Fix (use relative or copy the function):
from orchestration.shared.utils.retry_utils import retry_with_jitter
# OR inline the retry logic
```

### Option 2: Redeploy with Shared Module

```bash
# Check current orchestrator Dockerfile
cat orchestration/cloud_functions/phase3_to_phase4/Dockerfile

# Ensure shared/ is copied in the build
# Then redeploy:
gcloud run deploy phase3-to-phase4-orchestrator \
  --source=orchestration/cloud_functions/phase3_to_phase4 \
  --region=us-west2
```

### Backfill Commands (After Fix)

```bash
# Manually trigger Phase 4 for Jan 26
curl -X POST "https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-01-26", "trigger_source": "manual_backfill"}'

# Repeat for Jan 27
curl -X POST "https://nba-phase4-precompute-processors-756957797294.us-west2.run.app/process-date" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"analysis_date": "2026-01-27", "trigger_source": "manual_backfill"}'
```

---

## Session 2 Summary

| Task | Status |
|------|--------|
| Deploy schema changes | ✅ Complete |
| Deploy Phase 4 service | ✅ Complete |
| Push commits | ✅ Complete |
| Run validation | ✅ Complete |
| Investigate issues | ✅ Complete |
| Fix orchestrator | ⏳ Next session |
| Backfill predictions | ⏳ Next session |
| Observability improvements | ⏳ Future |

---

## Reference Documents

- `docs/08-projects/current/2026-01-27-data-quality-investigation/SESSION-2-FINDINGS.md` - Full investigation
- `docs/08-projects/current/2026-01-27-data-quality-investigation/IMPLEMENTATION-PROGRESS.md` - Implementation details
- `docs/08-projects/current/2026-01-27-data-quality-investigation/DEPLOYMENT-COMMANDS.md` - Deploy commands
