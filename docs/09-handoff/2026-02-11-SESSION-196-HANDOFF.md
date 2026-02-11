# Session 196 Handoff — created_at, Investigation Findings, Deploy Gap

**Date:** 2026-02-11 (12:00 AM ET)
**Commits:** `17494aae` feat: Add per-pick created_at timestamp to daily and season picks JSON
**Status:** Complete — code merged, deploy pending

---

## What Was Done

### 1. Per-Pick `created_at` Timestamp (Committed, NOT Deployed)

Added `created_at` ISO 8601 UTC timestamp to every pick in:
- `picks/{date}.json` — both materialized and on-the-fly export paths
- `subsets/season.json` — season-wide pick history

**Implementation:** JOINs `player_prop_predictions.created_at` via `prediction_id` in the exporter queries. No BigQuery schema changes needed — uses existing `prediction_id` in `current_subset_picks` to look up the original prediction creation time.

**Files changed:**
| File | Change |
|------|--------|
| `data_processors/publishing/all_subsets_picks_exporter.py` | Added JOIN + `created_at` in materialized query, on-the-fly query, and both pick-building paths |
| `data_processors/publishing/season_subset_picks_exporter.py` | Added JOIN + `created_at` in season query and `_group_picks_by_model` |

**NOT deployed yet** — see Deploy Gap below.

### 2. Investigation: Feb 10 Prediction Gap (59 quality-ready, 20 predicted)

**Finding: NOT a bug — working as designed.**

Pipeline: 79 players in feature store → 29 pass coordinator filters → 20 get predictions.

- **79→29:** `player_loader.py` filters out bench players (<15 min + no prop line), injured (OUT/DOUBTFUL), and non-production-ready players. Intentional.
- **29→20:** `disable_estimated_lines=True` (Session 74) blocks 9 players without real betting lines. Intentional — real lines only mode.
- **quality_scorer.py:** Correctly handles optional vegas features (25-27). `is_quality_ready=true` with `default_feature_count=3` is correct when only vegas features are defaulted (`required_default_count=0`).
- **quality_gate.py:** Correctly uses `required_default_count`, not `default_feature_count`.

**Optimization opportunity:** Phase 4 computes features for 50 players (63%) that will never be predicted. Could apply coordinator filters earlier.

### 3. Investigation: Feb 11 Feature Defaults (79/192 blocked)

**Finding: Two distinct issues identified.**

1. **Vegas features (25-27) defaulted for all 192 players** — Expected pre-game, excluded from quality gate (optional features since Session 145).

2. **28 star players (Tatum, Lillard, Haliburton, etc.) systematically missing from `player_daily_cache`** — Not just Feb 11, but across ALL recent dates. The 14-day fallback query finds zero rows for these players. Features affected: 0,1,3,4,22,23,31 (player history + team context).

3. **62 players missing shot zone features (18-20)** — `player_shot_zone_analysis` has no data for Feb 11 (Phase 4 dependent).

4. **50 players missing PPM (feature 32)** — Insufficient 30-day history (rookies/two-way players).

**Root cause for the 28 stars:** Unknown — needs investigation of `player_daily_cache` processor to understand why stars are excluded. This is the highest-impact finding.

### 4. Deploy Gap Discovered: Phase 6 Export Function

The `phase6-export` Cloud Function has **no Cloud Build auto-deploy trigger**. Changes to `data_processors/publishing/` are NOT auto-deployed. The existing triggers only cover:
- Cloud Run: coordinator, worker, phase2/3/4, scrapers
- Cloud Functions: grading, phase2→3, phase3→4, phase4→5, phase5→6 orchestrator

The phase6 **exporter** (`orchestration/cloud_functions/phase6_export/`) is missing from this list.

Additionally, `phase6_export/main.py` has a **pre-existing syntax error** on line 484 (`exc_info` keyword repeated), which blocks manual deployment.

### 5. QUANT Volume Status

Feb 10: Only 2 predictions each (Q43/Q45) — confirmed timing issue, not a bug. Worker was redeployed mid-day; QUANT only available for the 21:01 UTC LAST_CALL run when only 2 new players were viable.

Feb 11 morning run (~8 AM ET) is the real test for QUANT volume.

### 6. Tonight Page Empty

Sonnet chat investigating `tonight/all-players.json` showing 0 players despite 2 games present. Findings not yet received.

---

## Files Changed

| File | Change | Deployed? |
|------|--------|-----------|
| `data_processors/publishing/all_subsets_picks_exporter.py` | Per-pick `created_at` via prediction_id JOIN | NO — needs Phase 6 function deploy |
| `data_processors/publishing/season_subset_picks_exporter.py` | Per-pick `created_at` via prediction_id JOIN | NO — needs Phase 6 function deploy |

---

## Sonnet Chat Outputs (in docs/09-handoff/)

| File | Content |
|------|---------|
| `SESSION-195-ROOT-CAUSE.md` | Hidden betting line filter analysis |
| `SESSION-195-COORDINATOR-GAP-ANALYSIS.md` | Full coordinator pipeline analysis |
| `SESSION-195-FINAL-SUMMARY.md` | Summary: all filtering is by design |
| `SESSION-195-INVESTIGATION-FEB11-DEFAULTS.md` | Feature defaults + cache gap for 28 stars |
| `SESSION-195-PHASE4-OPTIMIZATION.md` | Phase 4 optimization recommendations |
| `SESSION-195-NEXT-ACTIONS.md` | Prioritized action items |

---

## Quick Start for Next Session

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-11-SESSION-196-HANDOFF.md

# 2. CHECK QUANT VOLUME (most important — should be 50-100+ after morning run)
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE system_id LIKE '%q4%' AND game_date >= '2026-02-11'
GROUP BY 1, 2 ORDER BY 2 DESC, 1"

# 3. Fix Phase 6 deploy gap (two things):
#    a. Fix syntax error in orchestration/cloud_functions/phase6_export/main.py:484
#    b. Add Cloud Build trigger for phase6-export

# 4. Deploy Phase 6 function (after fixing syntax error)
./bin/deploy/deploy_phase6_function.sh ""

# 5. Investigate star players missing from player_daily_cache
bq query --use_legacy_sql=false "
SELECT cache_date, COUNT(*) as records
FROM nba_precompute.player_daily_cache
WHERE player_lookup = 'jaysontatum' AND cache_date >= '2026-01-01'
ORDER BY cache_date DESC LIMIT 20"

# 6. Run daily validation
/validate-daily
```

---

## Priorities for Next Session

### Priority 1: Deploy Phase 6 Function
- Fix syntax error in `orchestration/cloud_functions/phase6_export/main.py:484` (repeated `exc_info` kwarg)
- Deploy function: `./bin/deploy/deploy_phase6_function.sh ""`
- This deploys the `created_at` changes to production
- Also add a Cloud Build trigger to prevent future deploy gaps

### Priority 2: Verify QUANT Full Volume
After Feb 11 morning predictions (~8 AM ET):
- Q43/Q45 should produce 50-100+ predictions with 14 games
- If still low, check coordinator logs for quality gate per-system results
- Compare Q43/Q45 volume to champion volume

### Priority 3: Investigate Star Players Missing from Cache
28 star players (Tatum, Lillard, Haliburton, etc.) are systematically missing from `player_daily_cache` across ALL recent dates. This causes feature defaults → zero tolerance blocks → lost predictions.
- Read `data_processors/precompute/player_daily_cache_processor.py`
- Check what filtering excludes these players
- Fix or adjust to ensure stars are always cached

### Priority 4: Tonight Page Empty
Check Sonnet chat findings for `tonight/all-players.json` showing 0 players. May be related to the same `player_game_summary` / `upcoming_player_game_context` pattern as Session 193's materializer fix.

### Priority 5: QUANT Performance Assessment
Once QUANT has 2-3 days of full-volume data:
- Compare Q43/Q45 hit rates vs champion
- If HR 60%+ at edge 3+, begin promotion planning

---

## Context for Future Sessions

- **Champion model is 41 days stale** — below breakeven (43.8% HR edge 3+ for Feb 8 week)
- **QUANT Q43 is the designed replacement** — 65.8% HR when fresh in backtests
- **No code bugs found** in quality_scorer, quality_gate, or coordinator filtering — all working as designed
- **Phase 4 wastes 63%** of feature computation on players that will never be predicted — optimization opportunity but not urgent
- **`created_at` code is merged** to main but not deployed to the Phase 6 Cloud Function
