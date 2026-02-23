# Session 329 Handoff — V12+Vegas Fix Verified, Coordinator Timeout Fixed

**Date:** 2026-02-22
**Previous Session:** 328 — V12+Vegas Docker Cache Bug Found & Fixed

## What Was Done

### 1. Diagnosed V12+Vegas backfill failure from Session 328

Session 328 hot-deployed the coordinator at 22:52 UTC and triggered a backfill at ~23:02 UTC. Investigation found:

- Two batches started (bdd0104e at 23:02:25, 682a2d09 at 23:03:38) — double-triggered
- Both loaded 365 players but **never reached quality gate or Pub/Sub dispatch**
- Root cause: **Coordinator Cloud Run timeout (540s)** is too short for 365-player player loader on an 11-game day
- Player loader emits per-player line diagnostic messages (NO_PROP_LINE, LINE_SOURCE, LINE_SANITY_REJECT) each involving BQ lookups — takes ~13+ minutes for 365 players
- Both batches silently died at the timeout boundary

### 2. Increased coordinator timeout 540s → 900s

```bash
gcloud run services update prediction-coordinator --region=us-west2 --timeout=900
```

Deployed as revision `prediction-coordinator-00273-t5h`.

### 3. Successfully re-triggered V12+Vegas backfill for Feb 22

- Batch b191a2e4 started at 23:44:23 UTC
- Player loader completed, quality gate passed: **52/365 viable players**
- Published 52 requests to Pub/Sub in 3.0s
- Batch completed: 52/52 players at 23:58:39 UTC
- Phase 5 completion published at 23:58:57 UTC
- HTTP 504 returned (response exceeded 900s) but batch completed server-side

**New predictions in BQ:**
| System ID | Count | Max Edge |
|-----------|-------|----------|
| catboost_v12_train1225_0205 (V12+vegas MAE) | 52 | 4.8 |
| catboost_v12_train1225_0205_feb22 (fresh retrain) | 52 | 4.1 |
| catboost_v12_q43_train1225_0205 (V12+vegas Q43) | 52 | 8.2 |
| catboost_v12_q43_train1225_0205_feb22 (fresh Q43) | 52 | 7.8 |
| catboost_v12_train1102_0125 (replay Jan 26-Feb 5) | 52 | — |
| catboost_v12_train1102_1225 (replay Jan 1-25) | 52 | — |
| catboost_v9_train1225_0205 (V9 fresh retrain) | 52 | — |

### 4. Re-exported best bets — 0 picks (correct)

- 8 model families discovered (including v12_vegas_q43)
- 44 candidates all had multi-model consensus edge < 5.0
- Individual V12 models had edges up to 9.0, but cross-model disagreement pulled consensus below floor
- **0 picks is correct output** — genuinely tight-line day

### 5. Backfill angles restored + env var drift fixed (earlier in session)

- Re-ran backfill to restore pick_angles in BQ (Jan 9 - Feb 21): 105/105 picks now have angles
- Removed stale `BEST_BETS_MODEL_ID=catboost_v12` from phase6-export and post-grading-export CFs

### 6. Documentation updated

- `session-learnings.md`: Added coordinator backfill timeout entry, backfill angles entry, env var drift entry
- `CLAUDE.md`: Added coordinator backfill timeout to Common Issues table

## Follow-Up (Next Session)

### P1: Investigate non-fatal errors in coordinator

1. **`name 'bigquery' is not defined`** in post-consolidation quality checks (23:58:51 UTC). Non-fatal but indicates a missing import in coordinator code. Check `coordinator.py` for the post-consolidation quality check function.

2. **`Decimal` JSON serialization error** in best bets export. The exporter hit `TypeError: Object of type Decimal is not JSON serializable` when writing to GCS. Non-fatal (export completed) but should be fixed with `default=str` or explicit conversion.

### P2: Investigate unrecognized model

`catboost_v9_50f_noveg_train20251225-20260205_20260221_211702` appeared with 42 predictions for Feb 22. This model ID doesn't match any entry in `MONTHLY_MODELS` dict — likely loaded from `model_registry` BQ table. Investigate:
- Is it intentionally registered? Check `model_registry` table
- Should it be in the MONTHLY_MODELS fallback dict?
- Why only 42 predictions (vs 48-52 for other models)?

### P3: Coordinator timeout — consider further optimization

The 900s timeout barely fits. The batch completed at ~14:34 elapsed, and the HTTP response timed out at 15:00. On a 15-game day, it could still fail. Options:
- Increase to 1200s (20 min) for more headroom
- Optimize player_loader line diagnostics — batch BQ lookups instead of per-player queries
- Make `/start` return immediately and process async (spawn background task)

### P4: Monitor V12+Vegas performance

V12+vegas is now generating predictions. Track:
- Daily hit rates via `model_performance_daily` table
- Compare V12+vegas vs V9 champion performance
- V12+vegas had 62.7% HR edge 3+ historically (vs V9 48.3%)
- If V12+vegas sustains advantage, consider promotion to champion

### P5: Model health check

- V9 champion HR: 5-16% over Feb 19-21 (terrible stretch)
- V12+vegas is the only model near breakeven (51-55%)
- Monitor if V9 recovery or if retraining needed

### Optional

- Ultra OVER gate progress: 17-2 (89.5%, N=19). Need 50 for public exposure. ~10 weeks at current pace.
- Admin dashboard missing `ultra_gate` field (Session 327 intended but not implemented)

## Architecture Notes

### Coordinator Dispatch Flow
1. `/start` → Postponement check → PlayerLoader creates prediction requests (365 players, ~13 min)
2. Historical games batch-loaded for optimization
3. Quality gate filters to viable players (52/365 on Feb 22)
4. Pub/Sub publish to worker (3.0s for 52 requests)
5. Worker loads all monthly models via `get_enabled_monthly_models()` and generates predictions
6. Batch summary published to Firestore

### Key: Player loader is the bottleneck
The line diagnostic phase (NO_PROP_LINE, LINE_SOURCE, LINE_SANITY_REJECT) does per-player BQ lookups across multiple odds sources. For 365 players, this alone takes ~13 minutes. The rest of the pipeline (quality gate + dispatch + completion) takes only ~2 minutes.

## Key Files Changed

| File | Change |
|------|--------|
| `CLAUDE.md` | Added coordinator backfill timeout to Common Issues |
| `docs/02-operations/session-learnings.md` | Added 3 new entries (timeout, angles, env var) |
| `docs/09-handoff/2026-02-22-SESSION-329-HANDOFF.md` | This file |

## Infrastructure Changes

| Change | Details |
|--------|---------|
| Coordinator timeout | 540s → 900s (revision 00273-t5h) |
| Coordinator revision | 00273-t5h (deployed 23:33 UTC Feb 22) |
| Worker revision | 00258-4c7 (unchanged, deployed 19:43 UTC Feb 22) |
