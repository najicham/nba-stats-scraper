# Session 212 Handoff - Grading Coverage Investigation + IAM Audit

**Date:** 2026-02-11
**Session:** 212
**Duration:** ~3 hours
**Status:** ✅ Complete

## Summary

Two-part session:
1. Investigated "grading gaps" (62-72% coverage) — discovered they're **NOT bugs** (NO_PROP_LINE excluded from grading). Fixed grading_gap_detector.
2. **Discovered and fixed systemic IAM failures** across 8 Cloud Run services, then upgraded validate-daily to prevent recurrence with dynamic Pub/Sub IAM discovery.

## Part 1: Grading Coverage Investigation

### Root Cause
All "ungraded" predictions have `line_source = 'NO_PROP_LINE'` — predictions for players without prop lines, made for research purposes. Intentionally excluded by grading processor.

**Further investigation:** The 88-90% coverage was from DNP predictions being skipped instead of voided.

### Fix Part A: grading_gap_detector.py
Updated to calculate `graded / gradable_predictions` instead of `graded / total_predictions`.

### Fix Part B: DNP Voiding (CRITICAL)
**DNP predictions now get graded as `is_voided=True`** instead of being skipped entirely.

**Before:**
- DNP predictions skipped (no record written)
- Coverage: 289/325 = 88.9%
- No audit trail for DNP predictions

**After:**
- DNP predictions graded with `is_voided=True, void_reason='dnp_*'`
- Coverage: 325/325 = **100%** (289 active + 36 voided)
- Complete audit trail with `graded_at` timestamp
- Matches sportsbook behavior (void the bet, track it)

**Changes to `prediction_accuracy_processor.py`:**
- `get_actuals_for_date()` - Include `is_dnp` field from boxscore
- `detect_dnp_voiding()` - Handle `actual_points=None`, accept `is_dnp` parameter
- `grade_prediction()` - Pass `is_dnp` flag to voiding detector
- `process_date()` - Remove skip for DNP, grade as voided instead

## Part 2: IAM Audit & Systemic Fix (NEW)

### Discovery
While fixing grading IAM (`phase3-to-grading`, `grading-coverage-monitor`), performed a full audit of all 70+ Cloud Run services. Found **8 services** with missing `roles/run.invoker`:

| Service | Invoked By | Impact |
|---------|-----------|--------|
| `phase3-to-grading` | Pub/Sub (`nba-phase3-analytics-complete`) | Event-driven grading broken |
| `grading-coverage-monitor` | Pub/Sub | Grading monitoring broken |
| `realtime-completeness-checker` | Pub/Sub (`nba-phase2-raw-complete`) | Phase 2 completeness monitoring broken |
| `backfill-trigger` | Pub/Sub (`boxscore-gaps-detected`) | Auto-backfill on gap detection broken |
| `auto-retry-processor` | Scheduler → Pub/Sub (`auto-retry-trigger`) | Auto-retry broken |
| `deployment-drift-monitor` | Scheduler → Pub/Sub (`deployment-drift-check`) | Drift monitoring broken |
| `scraper-availability-monitor` | Scheduler → direct HTTP | Scraper monitoring broken |
| `bdb-retry-processor` | Scheduler → Pub/Sub (`bdb-retry-trigger`) | Low impact (BDL disabled) |

### Fix Applied
All 8 services had `roles/run.invoker` added for `756957797294-compute@developer.gserviceaccount.com`.

### Root Cause
`gcloud functions deploy` with Eventarc does NOT preserve IAM policies. Redeployments silently wipe IAM bindings. The old validate-daily check only verified 3 hardcoded orchestrator names, so the other services were invisible.

### Validation Upgrade
**Phase 0.6 Check 5** upgraded from hardcoded 3-service list to **dynamic Pub/Sub discovery**:
- Enumerates ALL Pub/Sub push subscriptions → extracts target Cloud Run service names
- Enumerates ALL Cloud Scheduler HTTP targets → extracts target service names
- Checks `roles/run.invoker` on every discovered target
- New services are automatically covered without updating the check

**Phase 0.66** (Grading Infrastructure Health):
- IAM check consolidated into Check 5 (no longer duplicated)
- Check 1: Per-day grading completeness (per model, most recent game date)
- Check 2: Grading Cloud Function deployment state (ACTIVE check)

**Phase 0.67** (Cloud Scheduler Execution Health):
- Lists all ENABLED scheduler jobs, checks `status.code` from last execution
- Severity-classified: CRITICAL (PERMISSION_DENIED, UNAUTHENTICATED), HIGH (INTERNAL, UNAVAILABLE), MEDIUM (DEADLINE_EXCEEDED, NOT_FOUND), LOW (known-OK like BDL/MLB)
- Found 30/129 jobs failing silently on first run

**Phase 0.68** (Zero-Invocation Detection):
- Discovers all Cloud Run services targeted by Pub/Sub push subscriptions
- Queries Cloud Logging (`--limit=1 --freshness=24h`) for each to verify actual traffic
- Flags services with 0 requests as WARNING (not CRITICAL — may be normal on no-game days)
- Excludes known seasonal (mlb-*, bdl-*) and manual-only services (dashboards)
- Fills the gap: Check 5 verifies "can be invoked" → Phase 0.68 verifies "was actually invoked"

**Phase 0.65** updated with comments about expected grading subscription counts.

## What Changed

### Code Changes
```
.claude/skills/validate-daily/SKILL.md     # Dynamic IAM check (Check 5), Phase 0.66 grading health,
                                           # Phase 0.67 scheduler health, Phase 0.68 invocation check,
                                           # Phase 0.65 comments
bin/monitoring/grading_gap_detector.py     # Fixed grading % calculation
```

### Infrastructure Changes
```
8 Cloud Run services: added roles/run.invoker IAM binding
  - phase3-to-grading, grading-coverage-monitor (grading pipeline)
  - realtime-completeness-checker, backfill-trigger (Phase 2 monitoring)
  - auto-retry-processor, deployment-drift-monitor (operational monitoring)
  - scraper-availability-monitor (scraper monitoring)
  - bdb-retry-processor (low priority, BDL disabled)
```

## Key Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Grading coverage (all predictions) | **100%** | 289 active + 36 voided = 325 total ✅ |
| Grading coverage (non-DNP) | **100%** | Every player who played gets graded ✅ |
| Voided predictions (DNP) | **10-12%** | Normal DNP rate, now tracked |
| Services with broken IAM | 8 → 0 | All fixed |
| Services now auto-monitored | **All** Pub/Sub targets | Dynamic discovery |
| Scheduler jobs failing | **30 of 129** | Detected by new Phase 0.67 |

## Outstanding Work

### High Priority
1. **Triage 30 failing scheduler jobs** — Phase 0.67 now detects them. Key categories:
   - 3 PERMISSION_DENIED (incl. `scraper-availability-daily` — IAM just fixed, should resolve)
   - 14 INTERNAL (500 errors from targets — need service-level investigation)
   - 1 UNAUTHENTICATED (`trigger-health-check` — auth config broken)
   - 5 DEADLINE_EXCEEDED (prediction/props jobs timing out)

### Investigate (Future Session)
2. **`auto-backfill-orchestrator`** — no Pub/Sub subscription found but exists as Cloud Function. May be unused/legacy. Verify.
3. **`unified-dashboard`** — no Pub/Sub subscription. Likely manual-only dashboard. Low priority.

### Low Priority
4. **Deploy grading_gap_detector as Cloud Function** — Scheduler job exists, just needs deployment
5. **Verify Phase 6 quality filtering deployment** from Session 211

## Key Learnings

1. **Hardcoded service lists drift** — The old Check 5 only verified 3 orchestrators. When new services were deployed, they weren't added to the check. Dynamic discovery solves this permanently.

2. **IAM failures are silent** — No errors in the target service logs. Pub/Sub gets 403s that go to dead-letter queues. Scheduler shows failures in its logs, but nobody checks those daily. The services appear healthy via `/health` checks since they're running fine — they just never receive requests.

3. **Backup mechanisms mask failures** — Grading had backup polling + scheduled queries, so IAM failure caused partial gaps (12/29 ungraded) instead of total failure. This made the problem look like a minor data quality issue rather than an infrastructure break.

4. **Audit broadly, fix surgically** — When you find one instance of a systemic issue, check ALL instances before fixing. The initial plan was to fix 2 grading services; the audit revealed 6 more.

5. **Defense in depth for infrastructure monitoring** — No single check catches everything:
   - Check 5 (IAM) answers: "Can the service be invoked?"
   - Phase 0.67 (Scheduler) answers: "Did the scheduler try to invoke?"
   - Phase 0.68 (Invocations) answers: "Did the service actually receive requests?"
   - Each catches a different failure mode. Together they form a complete detection chain.

## New Validation Phases Summary

| Phase | What It Checks | Catches |
|-------|---------------|---------|
| 0.6 Check 5 | IAM on all Pub/Sub/Scheduler targets | Missing `roles/run.invoker` |
| 0.65 | Duplicate Pub/Sub subscriptions | Orphan Eventarc triggers |
| 0.66 | Grading completeness + function state | Grading gaps, broken functions |
| 0.67 | Scheduler job execution status | Failed/auth-broken scheduler jobs |
| 0.68 | Cloud Run zero-invocation detection | Services never receiving traffic |

## Related Documentation

- `docs/08-projects/current/session-212-grading-coverage/ROOT-CAUSE-ANALYSIS.md`
- `docs/09-handoff/2026-02-11-SESSION-211-HANDOFF.md` (orphan Eventarc cleanup)
- `docs/09-handoff/2026-02-11-SESSION-205-HANDOFF.md` (original orchestrator IAM discovery)

---

**Session completed:** 2026-02-11
**Next session:** Monitor that fixed services are now receiving invocations. Check `auto-backfill-orchestrator` usage.
