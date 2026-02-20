# Session 311C Handoff — Full Session Review + Verification Needed

**Date:** 2026-02-20
**Commits:** `031f548`, `ecd3777`, `f2e85ba` (all pushed to main, auto-deploying)
**Next session priority:** Verify today's predictions, subsets, and best bets are complete and correct

---

## What Was Done This Session (4 commits total)

### 1. Fixed Stale Subset Definitions (P0) — `031f548`

**Problem:** 7 Q43/Q45 subset definitions referenced stale system_ids (`*_train1102_0131`) while predictions use `*_train1102_0125`. These subsets silently produced 0 picks.

**Fix:** Family-based runtime resolution in `SubsetMaterializer.materialize()`:
- Queries today's active prediction system_ids
- Classifies both definitions and active system_ids into model families via `classify_system_id()`
- Resolves mismatches automatically, logging each resolution
- Survives future retrains — no BQ table changes needed

**File:** `data_processors/publishing/subset_materializer.py`

**Verified working:** Today's `current_subset_picks` shows Q43 (4 picks) and Q45 (3 picks) materializing correctly.

### 2. Three Pipeline Improvements — `ecd3777`

**a) Shared model discovery:** `discover_models()` called once in `daily_export.py`, passed to both SubsetMaterializer and CrossModelSubsetMaterializer. Saves 1 redundant BQ query per export run.
- Files: `backfill_jobs/publishing/daily_export.py`, `data_processors/publishing/subset_materializer.py`, `data_processors/publishing/cross_model_subset_materializer.py`

**b) AllSubsetsPicksExporter fallback fix:** The `_build_json_on_the_fly()` fallback path now resolves stale system_ids, matching SubsetMaterializer behavior.
- File: `data_processors/publishing/all_subsets_picks_exporter.py`

**c) retrain.sh auto-update:** After training each family, automatically updates `dynamic_subset_definitions` to point to the new model's system_id. Root cause fix — the runtime resolver is now a safety net.
- File: `bin/retrain.sh`

### 3. V12 Retrain Bug Fix — `f2e85ba`

**Problem:** `augment_v11_features()` (and V12/V13/V14 variants) in `quick_retrain.py` wrote to `df['features']` column which no longer exists after Session 286-287 column migration. Caused `KeyError: 'features'` crash during V12+ model retraining.

**Fix:** Removed all 4 `df.at[..., 'features']` writes. Functions now write only to individual `feature_N_value` columns (which `prepare_features()` reads). Added `feature_N_value` column updates to V13/V14 augmentors that previously only wrote to the array.

**File:** `ml/experiments/quick_retrain.py`

### 4. Architecture Documentation — `031f548`

**Created:** `docs/08-projects/current/best-bets-v2/08-LAYER-ARCHITECTURE.md`
- 3-layer architecture (L1 per-model, L2 cross-model, L3 signal) + best bets output
- Frontend grouping design (3-tab layout)
- DB naming rationale (`signal_health_daily` stays as-is)

---

## Current State (as of session end, ~evening Feb 20)

### Predictions
- **13 models** producing 55 predictions each (694 total) for Feb 20
- All predictions have real prop lines (100% `with_real_lines`)
- 9 games tonight, all status=1 (scheduled)

### Subset Picks (Layer 1 + Layer 2)
- **24 subsets** materialized in `current_subset_picks` for today
- **Q43/Q45 now working** — `q43_all_picks` (4), `q45_all_picks` (3), `q43_all_predictions` (36), `q45_all_predictions` (36)
- Cross-model (L2): `xm_consensus_3plus` (4), `xm_consensus_4plus` (1), `xm_diverse_agreement` (5)
- **Signal subsets (L3) NOT yet materialized** — requires SignalBestBetsExporter to run

### Best Bets
- **Empty since Feb 18** — `signal_best_bets_picks` has 0 rows for Feb 19-20
- Expected to resume when daily export pipeline runs for tonight's games
- All provenance columns exist: `source_model_id`, `source_model_family`, `qualifying_subsets`, `pick_angles`, `signal_tags`, `algorithm_version` (37 columns total)

### Retrain Status
- **All models overdue** — champion 13d, Q43/Q45 24d stale
- **Cannot retrain yet** — All-Star break (Feb 13-18) created a grading gap. Eval window needs 7 days of graded data. Currently only Feb 12 + Feb 19 have grading.
- **Earliest retrain:** ~Feb 26 (when Feb 19-25 are all graded)
- **Command when ready:** `./bin/retrain.sh --all --train-end 2026-02-18 --validate-filters` then `./bin/retrain.sh --family v9_mae --promote`
- V12 `features` bug is now fixed — V12 retraining will work

---

## VERIFICATION CHECKLIST FOR NEXT SESSION

### Priority 1: Confirm best bets resumed

```bash
# Check if signal_best_bets_picks has rows for today
bq query --nouse_legacy_sql "
SELECT game_date, COUNT(*) as picks,
  COUNT(DISTINCT source_model_id) as distinct_models,
  COUNTIF(signal_count > 0) as with_signals,
  COUNTIF(qualifying_subsets IS NOT NULL) as with_subsets
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-02-20'
GROUP BY 1 ORDER BY 1"
```

If empty: the daily export may not have run yet. Check Cloud Scheduler / Pub/Sub triggers.

### Priority 2: Verify all 3 subset layers populated

```bash
# Check all layers by system_id type
bq query --nouse_legacy_sql "
SELECT
  CASE
    WHEN system_id = 'cross_model' THEN 'L2_cross_model'
    WHEN system_id = 'signal_subset' THEN 'L3_signal'
    ELSE 'L1_per_model'
  END as layer,
  COUNT(DISTINCT subset_id) as subsets,
  COUNT(*) as total_picks
FROM nba_predictions.current_subset_picks
WHERE game_date = CURRENT_DATE()
  AND version_id = (
    SELECT MAX(version_id) FROM nba_predictions.current_subset_picks
    WHERE game_date = CURRENT_DATE()
  )
GROUP BY 1 ORDER BY 1"
```

**Expected:** L1 ~20 subsets, L2 ~3-5 subsets, L3 ~4 subsets (signal_combo_he_ms, signal_combo_3way, signal_bench_under, signal_high_count)

### Priority 3: Verify Q43/Q45 stale fix is working in production

```bash
# Check Q43/Q45 subsets have picks (were previously 0)
bq query --nouse_legacy_sql "
SELECT subset_id, system_id, COUNT(*) as picks
FROM nba_predictions.current_subset_picks
WHERE game_date = CURRENT_DATE()
  AND (subset_id LIKE 'q43%' OR subset_id LIKE 'q45%')
  AND version_id = (
    SELECT MAX(version_id) FROM nba_predictions.current_subset_picks
    WHERE game_date = CURRENT_DATE()
  )
GROUP BY 1, 2 ORDER BY 1"
```

**Expected:** Q43 and Q45 subsets with picks > 0

### Priority 4: Check best bets provenance fields

```bash
# Spot-check a best bet pick has full provenance
bq query --nouse_legacy_sql "
SELECT
  player_lookup, recommendation, ROUND(edge, 1) as edge,
  source_model_id, source_model_family,
  signal_tags, signal_count,
  qualifying_subsets, qualifying_subset_count,
  pick_angles, algorithm_version
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE()
ORDER BY edge DESC LIMIT 3"
```

**Expected:** Each pick has `source_model_id` (which model produced it), `signal_tags` (which signals fired), `qualifying_subsets` (which L1/L2 subsets it appeared in), `pick_angles` (human-readable reasoning).

### Priority 5: Verify GCS exports exist

```bash
# Check GCS for today's exports
gsutil ls gs://nba-props-platform-api/v1/picks/2026-02-20.json
gsutil ls gs://nba-props-platform-api/v1/signal-best-bets/2026-02-20.json
```

### Priority 6: Check deployment drift

```bash
./bin/check-deployment-drift.sh --verbose
gcloud builds list --region=us-west2 --project=nba-props-platform --limit=5
```

---

## Known Issues

| Issue | Status | Impact |
|-------|--------|--------|
| All models overdue for retrain | Blocked by ASB grading gap | No immediate impact on predictions |
| Best bets empty since Feb 18 | Expected to self-resolve | Will populate on next daily export |
| `v9_q43`/`v9_q45` stale definitions in BQ | **PATCHED** at runtime | Runtime resolver handles it; retrain.sh will fix root cause |
| V12 `features` column bug | **FIXED** | V12 retraining now works |
| Only 3 families in `--all` (not 4) | Q43/Q45 not in registry as enabled families | Retrain Q43/Q45 individually: `./bin/retrain.sh --family v9_q43` |

---

## Champion Model Decision

**Decision: Keep the champion concept.** Session 307 already decoupled picks (all models contribute via multi-source best bets). The champion (`catboost_v9`) serves as:
- Cloud Run env var (`CATBOOST_V9_MODEL_PATH`) — single production model
- Daily signal anchor (one canonical GREEN/YELLOW/RED per day)
- Decay monitoring reference (HEALTHY→BLOCKED state machine)
- Slack alert dedup (avoids 13 models spamming)
- Retrain baseline for challenger comparisons

No code changes needed — the current hybrid works (champion for ops, all models for picks).

---

## Files Changed This Session

| File | Change |
|------|--------|
| `data_processors/publishing/subset_materializer.py` | Stale system_id resolution + accept pre-discovered active_system_ids |
| `data_processors/publishing/all_subsets_picks_exporter.py` | Stale resolution in fallback path |
| `data_processors/publishing/cross_model_subset_materializer.py` | Accept pre-discovered models |
| `backfill_jobs/publishing/daily_export.py` | Shared model discovery across materializers |
| `bin/retrain.sh` | Auto-update subset definitions post-training |
| `ml/experiments/quick_retrain.py` | Fix deprecated `features` array writes in V11-V14 augmentors |
| `docs/08-projects/current/best-bets-v2/08-LAYER-ARCHITECTURE.md` | New: Layer architecture + frontend grouping |
| `docs/09-handoff/2026-02-20-SESSION-311B-HANDOFF.md` | Session 311B handoff |
| `docs/09-handoff/2026-02-20-SESSION-311C-HANDOFF.md` | This handoff |
