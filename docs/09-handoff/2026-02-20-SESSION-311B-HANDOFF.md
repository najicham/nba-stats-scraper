# Session 311B Handoff — Stale Subset Fix, Layer Architecture Doc

**Date:** 2026-02-20
**Focus:** Fix stale subset definitions (P0), architecture documentation

## What Was Done

### 1. Fixed Stale Subset Definitions (P0)

**Problem:** `dynamic_subset_definitions` had 15 rows with stale `system_id` values. Q43 defs referenced `*_train1102_0131` but predictions use `*_train1102_0125`. Q43/Q45 subsets silently produced 0 picks.

**Fix:** Family-based resolution in `SubsetMaterializer.materialize()` (Session 311):
- Added `_query_active_system_ids()` — queries today's distinct prediction system_ids
- Added `_resolve_stale_system_ids()` — classifies both definition and active system_ids into families via `classify_system_id()`, replaces stale definitions with active ones
- Logs every resolution: `"Resolved stale system_id 'X' → 'Y' (family=v9_q43) for subset 'Z'"`
- No BQ table changes — definitions stay as-is, runtime resolution handles staleness
- Survives future retrains automatically

**File changed:** `data_processors/publishing/subset_materializer.py`

### 2. Layer Architecture Document

**Created:** `docs/08-projects/current/best-bets-v2/08-LAYER-ARCHITECTURE.md`

Documents:
- 3-layer architecture (L1 per-model, L2 cross-model, L3 signal) + best bets output
- Each layer's materializer, system_id, write strategy, table
- Orchestration flow
- DB naming rationale (why `signal_health_daily` stays as-is)
- Frontend grouping design (3-tab layout: Model View, Cross-Model View, Signal View)
- Pick badges design
- Complete file reference

### 3. DB Table Naming — No Action (Documented)

Decision: Do NOT rename `signal_health_daily`. The naming difference reflects real semantics (model decay states vs signal health regimes). 162+ references, 4 CFs, frontend URLs would break. Rationale documented in architecture doc.

## What Was NOT Done

### Retrain (All Models Overdue)
- Champion: 13 days stale (OVERDUE)
- Q43/Q45: 24 days stale (URGENT)
- V12 variants: 13-24 days stale
- **Action:** User should run `./bin/retrain.sh --promote` per model family. Fix stale defs (done above) ensures retrained models' subsets materialize correctly.

### Best Bets Verification
- Best bets still need to be verified after next daily pipeline run
- The stale subset fix will take effect on next export run
- Signal subsets (L3) will materialize on next `SignalBestBetsExporter` run

## Verification After Deploy

```bash
# 1. Deploy (push to main triggers auto-deploy)
git push origin main

# 2. After daily pipeline runs, verify Q43/Q45 subsets appear
bq query --nouse_legacy_sql "
SELECT subset_id, system_id, COUNT(*) as picks
FROM nba_predictions.current_subset_picks
WHERE game_date = CURRENT_DATE()
  AND (subset_id LIKE 'q43%' OR subset_id LIKE 'q45%')
GROUP BY 1, 2
ORDER BY 1"

# 3. Check logs for resolution messages
# Look for: "Resolved stale system_id" in Cloud Run logs
```

## Files Changed

| File | Change |
|------|--------|
| `data_processors/publishing/subset_materializer.py` | Added stale system_id resolution (3 methods + import) |
| `docs/08-projects/current/best-bets-v2/08-LAYER-ARCHITECTURE.md` | New: Layer architecture + frontend grouping doc |
| `docs/09-handoff/2026-02-20-SESSION-311B-HANDOFF.md` | New: This handoff |

## Next Steps

1. **Deploy** — Push to main, verify auto-build
2. **Retrain champion** — `./bin/retrain.sh --promote` (13 days stale)
3. **Retrain quantile models** — `./bin/retrain.sh --family v9_q43 --promote` etc.
4. **Verify best bets resume** — Check `signal_best_bets_picks` after daily pipeline
5. **Frontend implementation** — Build 3-tab subset admin page (frontend-only, backend data ready)
