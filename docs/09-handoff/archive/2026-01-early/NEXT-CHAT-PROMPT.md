# Prompt for Next Chat Session

Copy and paste everything below the line into a new Claude Code session:

---

## Context: Pipeline Reliability & Test Environment Project

I've been working on pipeline reliability improvements for my NBA stats scraper. The previous session completed 25 of 26 items and created documentation for a new Pipeline Replay/Test Environment system.

### What Was Done (Previous Session)
- Completed 25 reliability improvements (security, performance, monitoring)
- All changes are **committed but NOT deployed**
- Created comprehensive test environment documentation
- Created handoff document with deployment instructions

### What Needs To Be Done Now

**Priority 1: Deploy all committed changes**
The code is ready, just needs deployment. This includes:
- Coordinator authentication (needs new `COORDINATOR_API_KEY` env var)
- Worker performance improvements (batch loading, timeouts)
- Cloud function updates (Phase 4→5 timeout, Phase 5→6 validation)
- New DLQ monitor and backfill trigger functions
- Admin dashboard (rate limiting, audit trail)

**Priority 2: Build the test environment**
I want a Pipeline Replay system that lets me run the full pipeline (Phases 2-6) against any historical date in a test environment. This enables:
- Speed testing (measure latency at each phase)
- Error detection (catch bugs before production)
- Data validation (verify record counts, check for duplicates)

The design docs are ready, implementation is not started.

**Priority 3: Secrets migration (P0-SEC-2)**
Move 7 secrets from `.env` to Google Secret Manager.

---

## Key Files to Read

### Start Here (Handoff Document)
```
/home/naji/code/nba-stats-scraper/docs/08-projects/current/session-handoffs/2025-12/HANDOFF-DEC31-SESSION3.md
```
Contains: Session summary, deployment commands, what's completed, what's remaining.

### Test Environment Documentation
```
/home/naji/code/nba-stats-scraper/docs/08-projects/current/test-environment/README.md
/home/naji/code/nba-stats-scraper/docs/08-projects/current/test-environment/ARCHITECTURE.md
/home/naji/code/nba-stats-scraper/docs/08-projects/current/test-environment/USAGE-GUIDE.md
/home/naji/code/nba-stats-scraper/docs/08-projects/current/test-environment/IMPLEMENTATION-PLAN.md
```
Contains: Design decisions, how the replay system works, step-by-step implementation plan.

### Full Reliability TODO (Reference)
```
/home/naji/code/nba-stats-scraper/docs/08-projects/current/pipeline-reliability-improvements/COMPREHENSIVE-TODO-DEC30.md
```
Contains: 200+ item audit of all issues found in the codebase.

---

## Recent Git History

```
e875f44 docs: Add test environment design and session handoff
c123028 feat: Complete 25 pipeline reliability improvements
867eb71 feat: Add 9 pipeline reliability improvements
```

All changes are committed to `main` branch but not pushed/deployed.

---

## Quick Reference: Test Environment Design

The test environment uses a **Hybrid Local Replay** approach:
- `DATASET_PREFIX=test_` routes BigQuery writes to `test_nba_analytics`, etc.
- Direct processor calls (skip Pub/Sub for speed)
- Same code paths, isolated test data
- ~10-13 hours to implement fully

Key insight: We test the **processor logic** (where bugs occur), not the cloud orchestration (which is simple glue code).

---

## Files Modified in Previous Session

### New Components Created
```
orchestration/cloud_functions/dlq_monitor/          # DLQ monitoring
orchestration/cloud_functions/backfill_trigger/     # Auto-backfill on gaps
monitoring/pipeline_latency_tracker.py              # E2E latency tracking
shared/utils/env_validation.py                      # Startup env var validation
tests/unit/publishing/test_*.py                     # 6 exporter tests
bin/validation/*.sh                                 # 7 implemented scripts
```

### Key Modified Files
```
services/admin_dashboard/main.py       # Rate limiting, audit trail, auth fixes
predictions/coordinator/coordinator.py  # Authentication, Pub/Sub retries
predictions/worker/worker.py            # 500 on empty predictions, env validation
predictions/worker/batch_staging_writer.py  # MERGE NULL-safe fixes
orchestration/cloud_functions/*/main.py # Health checks, validation, timeouts
scrapers/scraper_base.py               # 12 bare except handlers fixed
```

---

## What I'd Like You To Do

1. **Read the handoff document** first to understand the current state
2. **Deploy the committed changes** following the deployment commands in the handoff
3. **Start building the test environment** following the implementation plan
4. Use parallel agents where possible to speed things up

Please start by reading the handoff document and confirming you understand the current state.
