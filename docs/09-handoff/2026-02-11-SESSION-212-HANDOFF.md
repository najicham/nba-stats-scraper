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

**Phase 0.65** updated with comments about expected grading subscription counts.

## What Changed

### Code Changes
```
.claude/skills/validate-daily/SKILL.md                                 # Dynamic IAM check, Phase 0.66, Phase 0.65 comments
bin/monitoring/grading_gap_detector.py                                  # Fixed grading % calculation
data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py  # Grade DNP as voided (100% coverage)
docs/08-projects/current/session-212-grading-coverage/ROOT-CAUSE-ANALYSIS.md # Updated with DNP fix
```

### Infrastructure Changes
```
8 Cloud Run services: added roles/run.invoker IAM binding
```

## Key Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Grading coverage (all predictions) | **100%** | 289 active + 36 voided = 325 total ✅ |
| Grading coverage (non-DNP) | **100%** | Every player who played gets graded ✅ |
| Voided predictions (DNP) | **10-12%** | Normal DNP rate, now tracked |
| Services with broken IAM | 8 → 0 | All fixed |
| Services now auto-monitored | **All** Pub/Sub targets | Dynamic discovery |

## Outstanding Work

### Investigate (Future Session)
1. **`auto-backfill-orchestrator`** — no Pub/Sub subscription found but exists as Cloud Function. May be unused/legacy. Verify.
2. **`unified-dashboard`** — no Pub/Sub subscription. Likely manual-only dashboard. Low priority.

### Low Priority
3. **Deploy grading_gap_detector as Cloud Function** — Scheduler job exists, just needs deployment
4. **Verify Phase 6 quality filtering deployment** from Session 211

## Key Learnings

1. **Hardcoded service lists drift** — The old Check 5 only verified 3 orchestrators. When new services were deployed, they weren't added to the check. Dynamic discovery solves this permanently.

2. **IAM failures are silent** — No errors in the target service logs. Pub/Sub gets 403s that go to dead-letter queues. Scheduler shows failures in its logs, but nobody checks those daily. The services appear healthy via `/health` checks since they're running fine — they just never receive requests.

3. **Backup mechanisms mask failures** — Grading had backup polling + scheduled queries, so IAM failure caused partial gaps (12/29 ungraded) instead of total failure. This made the problem look like a minor data quality issue rather than an infrastructure break.

4. **Audit broadly, fix surgically** — When you find one instance of a systemic issue, check ALL instances before fixing. The initial plan was to fix 2 grading services; the audit revealed 6 more.

## Related Documentation

- `docs/08-projects/current/session-212-grading-coverage/ROOT-CAUSE-ANALYSIS.md`
- `docs/09-handoff/2026-02-11-SESSION-211-HANDOFF.md` (orphan Eventarc cleanup)
- `docs/09-handoff/2026-02-11-SESSION-205-HANDOFF.md` (original orchestrator IAM discovery)

---

**Session completed:** 2026-02-11
**Next session:** Monitor that fixed services are now receiving invocations. Check `auto-backfill-orchestrator` usage.
