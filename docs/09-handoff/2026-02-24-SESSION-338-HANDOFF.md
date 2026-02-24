# Session 338 Handoff — Phase 6 Fix, minScale Preservation, Infrastructure Hardening

**Date:** 2026-02-24
**Focus:** Fix Phase 6 SQL bug blocking best bets, prevent minScale drift on deploy, self-heal OOM fix, daily steering
**Status:** All issues resolved. Today's best bets file live on website.

---

## Current System State

| Property | Value |
|----------|-------|
| Champion Model | `catboost_v12` (interim) |
| Champion State | **WATCH/DEGRADING** — 54.5-55.6% HR 7d |
| Champion Edge 5+ | **LOSING — 41.7% HR 14d (N=12)** |
| Best Bets 7d | **7-3 (70.0% HR)** |
| Best Bets 30d | **34-16 (68.0% HR)** |
| V9_low_vegas | **HEALTHY 60.5% (carrying best bets)** |
| Pre-Game Signal | **RED** — UNDER_HEAVY (15.6% pct_over) |
| Today's Picks | 2 (Zion UNDER 23.5, Embiid UNDER 27.5) |
| Deployment Drift | CLEAN (all services at HEAD) |
| minScale | 5 critical services at 1, preserved on future deploys |

## What This Session Did

### 1. Fixed Phase 6 SQL Escape Bug (CRITICAL)

**Problem:** `shared/config/cross_model_subsets.py` line 152 had `'%\\_q4%'` — BigQuery rejects backslash-underscore as an illegal escape sequence. This blocked ALL Phase 6 exports since the code was deployed.

**Fix:** Changed to `'%_q4%'`. BigQuery LIKE patterns don't need underscore escaping.

**Impact:** Today's best bets file was missing from the website. After fix + manual Phase 6 trigger, file now live with 2 picks.

### 2. Preserved minScale on All Deploy Paths

**Problem:** Every `gcloud run deploy` (manual or Cloud Build auto-deploy) was silently resetting `minScale` to 0, causing cold start failures. 20+ "no available instance" errors on phase4-to-phase5 orchestrator.

**Fix (4 layers):**
1. **Live:** Set `minScale=1` on 5 services via `gcloud run services update`
2. **deploy-service.sh:** Added `get_min_instances()` function — orchestrators/prediction services → 1, others → 0
3. **hot-deploy.sh:** Same function
4. **cloudbuild.yaml:** Added `_MIN_INSTANCES` substitution variable (default: 0)
5. **Cloud Build triggers:** Updated prediction-worker and prediction-coordinator triggers to `_MIN_INSTANCES=1` via REST API

**Discovery:** `gcloud builds triggers update` doesn't support substitution changes for repository-event triggers. Must use REST API:
```bash
curl -X PATCH "https://cloudbuild.googleapis.com/v1/projects/PROJECT/locations/REGION/triggers/TRIGGER_ID" \
  -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  -d @trigger.json
```

### 3. Fixed self-heal-predictions OOM

- Increased memory from 512Mi → 1Gi via `gcloud run services update`
- Updated Cloud Build trigger to `_MEMORY=1Gi` for future deploys
- Empty error logs were symptomatic of OOM crashes

### 4. Daily Steering Report

**Key findings:**
- 3 models HEALTHY (v12_feb22 62.5%, v9_low_vegas 60.5%, v12_1102_1225 60.0%)
- 7 models BLOCKED (v12_q43_1225_0205 catastrophically at 14.3%)
- Market expanding (compression 1.246), edges growing
- Direction split perfectly balanced (OVER 66.7%, UNDER 66.7%)
- Residual bias minimal (-0.65)
- V9 Q43/Q45 at 30 days stale, URGENT retrain threshold

### 5. Verified ft_rate_bench_over Signal

Signal wiring confirmed correct. Signal subsets materialize (`signal_bench_under`, `signal_high_count` visible in `current_subset_picks`). `ft_rate_bench_over` has 0 qualifying picks today because UNDER_HEAVY regime suppresses OVER predictions with sufficient edge. Will fire on balanced days.

### 6. Error Log Scan

| Service | Errors | Severity | Notes |
|---------|--------|----------|-------|
| Phase 3 Analytics | 10 HTTP 500s | P3 | Recurring ~75min, retries succeed, investigate payload |
| Phase 4-to-5 Orchestrator | 20+ cold starts | FIXED | minScale=1 now set |
| Phase 4 Precompute | 1 DependencyError | P4 | Working as designed (dependency gating) |
| All others | Clean | - | No errors in 6h window |

---

## Outstanding Items (Next Session)

### Priority 1: Monitor V9 Q43/Q45 Staleness Decision

Both at 30 days (URGENT threshold). Options:
- **Decommission:** Disable predictions entirely (they're already `enabled=false` in registry but still generating predictions)
- **Retrain:** Run `/model-experiment` with fresh training window
- Q43 is BLOCKED (47.1% HR) — actively harmful
- Q45 is DEGRADING (53.8%) — barely above breakeven

### Priority 2: Champion V12 Edge 5+ Recovery

V12 is LOSING at edge 5+ (41.7% HR 14d, N=12). Best bets are profitable only because `v9_low_vegas` carries at 60%. If v9_low_vegas degrades too, best bets will fail. Consider:
- Fresh V12 retrain with newer training window
- Or accept multi-model diversity as the hedge

### Priority 3: Investigate Phase 3 HTTP 500s

10 recurring 500s with no application-level error text. Happens in bursts every ~75min. May be:
- Request deserialization failures before processor logic runs
- Instance health check failures
- Specific processor type failing

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase3-analytics-processors" AND httpRequest.status=500' \
  --project=nba-props-platform --limit=5 --format=json --freshness=12h
```

### Priority 4: Phase 6 Export Message Format Documentation

The `phase6-export` function accepts these message formats:
- `{"export_types": ["signal-best-bets"], "target_date": "2026-02-24"}` — runs specific exports
- `{"players": [...]}` — player profile export
- Anything else falls back to `yesterday` date with full export types

Not documented anywhere. Consider adding to runbook.

---

## Files Changed This Session

| File | Change |
|------|--------|
| `shared/config/cross_model_subsets.py` | Fixed `\_` → `_` in SQL LIKE pattern |
| `bin/deploy-service.sh` | Added `get_min_instances()` + `--min-instances` flag |
| `bin/hot-deploy.sh` | Same |
| `cloudbuild.yaml` | Added `_MIN_INSTANCES` substitution + deploy flag |
| `docs/02-operations/session-learnings.md` | Added minScale drift + SQL escape learnings |
| `CLAUDE.md` | Added 3 new common issues |
| `docs/09-handoff/2026-02-24-SESSION-338-HANDOFF.md` | This file |

## Key Insights

1. **Deploy scripts must be explicit about ALL settings** — Cloud Run revisions don't inherit annotations like minScale from previous revisions. Every deploy resets to defaults unless flags are passed.
2. **Cloud Build trigger REST API** — The gcloud CLI can't update substitutions on repository-event triggers. Use the REST API with full trigger export → modify → patch.
3. **BigQuery LIKE doesn't need backslash escaping** — Only `%` and `_` are special in LIKE. To match a literal underscore, use `ESCAPE` clause, not backslash.
4. **Phase 6 message format matters** — The function dispatches based on `export_types` and `players` keys. A message with only `game_date` falls through to a hardcoded yesterday path.
5. **RED signal days produce fewer picks** — UNDER_HEAVY regime (15.6% pct_over) means very few OVER predictions with edge. Only 2 picks today vs typical 3-5.
