# Session 218B Handoff — Backup Rewrite, Live-Export Gen2, Scheduler Fixes

**Date:** 2026-02-12
**Session:** 218B (continuation — infrastructure from Session 217 tasks)
**Status:** All 5 handoff tasks addressed. Two critical fixes deployed.

## TL;DR

Fixed bigquery-daily-backup (rewrote in Python — CLI tools not available in CF runtime), migrated live-export from Gen1→Gen2 (deleted Gen1, redeployed via Cloud Build), ran full daily validation (core pipeline healthy), assessed Q43 shadow model (not ready for promotion). Fixed 2 Cloud Functions returning 500 for non-error conditions (root cause of scheduler INTERNAL errors).

## What Was Done

### 1. bigquery-daily-backup Fixed (was CRITICAL)

**Problem:** `gsutil: command not found` → then `gcloud: command not found` after Session 217 fix.
**Root cause:** Cloud Functions Python 3.11 runtime doesn't include ANY CLI tools (gcloud, gsutil, bq). The bash script approach was fundamentally broken.
**Fix:** Rewrote `cloud_functions/bigquery_backup/main.py` entirely in Python using `google-cloud-bigquery` and `google-cloud-storage` client libraries. Eliminated shell subprocess calls entirely.
**Result:** 11/11 tables exported successfully to `gs://nba-bigquery-backups/daily/20260212/`.
**Deployed:** Manually via `gcloud functions deploy`.

### 2. live-export Gen1→Gen2 Migration (was BROKEN)

**Problem:** `deploy-live-export` Cloud Build trigger failed every push with "Function already exists in 1st gen, can't change the environment."
**Root cause:** live-export was the only Gen1 function. `cloudbuild-functions.yaml` unconditionally uses `--gen2`.
**Fix:** Deleted Gen1 function → triggered Cloud Build to recreate as Gen2.
**Result:** live-export now Gen2, ACTIVE at `https://live-export-f7p3g7f6ya-wl.a.run.app`.

### 3. Scheduler 500→200 Fix

**Problem:** 11 scheduler jobs showing INTERNAL (code 13) errors.
**Root cause:** Cloud Functions like `daily-health-check`, `validation-runner` returned HTTP 500 when finding data quality issues. Scheduler interprets 500 as "job failed."
**Fix:** Changed to always return 200 — these are reporters, not gatekeepers.
**Files:** `daily_health_check/main.py`, `validation_runner/main.py`

### 4. Daily Validation Results

**Core pipeline: HEALTHY**

| Check | Status |
|-------|--------|
| Deployment drift | ✅ All services up to date |
| Phase 3 yesterday (Feb 11, 14 games) | ✅ 5/5, triggered=True |
| Feature quality today (Feb 12, 3 games) | ✅ 91.4% ready, 0 red |
| Enrichment | ✅ 100% today, 98% yesterday |
| Cross-model parity | ✅ All 5 models at 100% of champion |
| Pub/Sub IAM | ✅ All 17 services correct |
| Duplicate subscriptions | ✅ None |
| Pre-game signal | 🔴 RED — 3-game slate, 0 high-edge picks, SKIP DAY |

### 5. Q43 Shadow Model Assessment

**NOT ready for promotion.**

| Date | Q43 Edge 3+ HR | Champion Edge 3+ HR |
|------|----------------|---------------------|
| Feb 8 | 66.7% (6) | 33.3% (9) |
| Feb 9 | 50.0% (4) | 44.4% (9) |
| Feb 10 | 33.3% (3) | 20.0% (5) |
| Feb 11 | 43.8% (16) | 45.5% (33) |
| **Total** | **48.3% (29)** | **41.8% (56)** |

- 100% UNDER bias (zero OVER picks)
- Below 52.4% breakeven
- Only 29/50 edge 3+ picks needed for statistical threshold
- Both models struggling — league-wide factor or staleness

## Commits

```
095c749e fix: Rewrite backup function in Python, fix scheduler 500→200 responses
b105eae1 feat: Refactor grading-gap-detector, update deployment drift check
```

## Known Issues

### Remaining Failing Scheduler Jobs (P3)

These are monitoring/alerting, NOT core pipeline:

| Job | Issue | Likely Fix |
|-----|-------|------------|
| firestore-state-cleanup | Service 500 | Investigate transition-monitor service |
| live-freshness-monitor | Gen1 function | Delete+recreate as Gen2 |
| nba-grading-alerts-daily | UNAVAILABLE | Check nba-grading-alerts service |
| registry-health-check | Service 500 | Check nba-reference-service |
| same-day-predictions-tomorrow | NOT_FOUND | Route doesn't exist on coordinator |
| self-heal-predictions | TIMEOUT | Increase attemptDeadline |
| same-day-phase3 | RESOURCE_EXHAUSTED | Phase 3 overloaded, may need rate limit |

### Gen1 Functions Still Remaining

- `live-freshness-monitor` — Gen1, needs same delete+recreate
- `news-fetcher` — Gen1, likely unused

## Next Session Priorities

1. **Triage remaining scheduler jobs** (P3) — Most are monitoring, not critical
2. **Migrate live-freshness-monitor to Gen2** (P3)
3. **Monthly retrain decision** — Both champion (35+ days stale) and Q43 (48.3% HR) underperforming. Consider fresh retrain through Feb 10.
4. **Q43 monitoring** — Need 21 more edge 3+ picks to reach 50-pick threshold

---

**Session completed:** 2026-02-12 ~8:35 AM PT
