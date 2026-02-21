# Session 314B Handoff — Best Bets Consolidation + Backfill Plan

**Date:** 2026-02-20
**Focus:** Consolidated 3 overlapping best bets systems, fixed live grading, planned subset backfill
**Status:** Code changes DONE (not committed). Backfill skill + execution pending.
**Prior sessions:** 314 (investigation), 312C (ANTI_PATTERN diagnosis), 313 (quality scorer fix)

---

## What Was Done (Code Changes)

All 5 workstreams from the Session 314 plan were implemented and tested. **18 tests pass, all imports clean.**

### Workstream 1: Removed ANTI_PATTERN entries from combo registry
**File:** `ml/signals/combo_registry.py`
- Deleted `high_edge` and `edge_spread_optimal+high_edge` ANTI_PATTERN entries from `_FALLBACK_REGISTRY`
- These fired on ALL edge 5+ picks by construction, blocking every candidate that didn't have a higher-cardinality SYNERGISTIC match
- The ANTI_PATTERN blocking logic in `aggregator.py:210-213` was NOT removed — it's correct behavior, just these two entries were wrong
- **BQ still needs cleanup:** `DELETE FROM nba_predictions.signal_combo_registry WHERE classification = 'ANTI_PATTERN'`

### Workstream 2: Extracted `query_games_vs_opponent()` to shared module
**Files:** `ml/signals/supplemental_data.py`, `data_processors/publishing/signal_best_bets_exporter.py`
- Moved the ~675K-row season scan from a private method on the exporter to a shared function in `supplemental_data.py`
- Added module-level `_gvo_cache` dict keyed by `target_date` — both the signal exporter and annotator can call it without duplicate BQ scans
- Exporter now imports and calls the shared version

### Workstream 3: Aligned annotator bridge with signal exporter
**File:** `data_processors/publishing/signal_annotator.py`
- Added imports for `compute_player_blacklist` and `query_games_vs_opponent`
- In `annotate()`: computes blacklist + enriches predictions with `games_vs_opponent` before calling bridge
- Added `player_blacklist` parameter to `_bridge_signal_picks()` and passes it to `BestBetsAggregator`
- **System 2 and System 3 now apply the same negative filters**
- NOT changed: `multi_model=True` (only signal exporter uses multi-model candidates; annotator bridge uses champion model)

### Workstream 4: Retired legacy BestBetsExporter
**File:** `backfill_jobs/publishing/daily_export.py`
- Removed `BestBetsExporter` import
- Removed `'best-bets'` from `EXPORT_TYPES` list
- Removed the `if 'best-bets' in export_types:` block
- The `best_bets_exporter.py` file still exists (not deleted — could be referenced elsewhere)

### Workstream 5: Fixed live grading export
**File:** `data_processors/publishing/live_grading_exporter.py`
- Removed `if games_final > 0 or games_in_progress > 0:` gate — BQ scores always fetched now
- Added stale schedule override: when `game_status == 'scheduled'` but `points is not None`, overrides to `'final'`
- Root cause: schedule scraper hadn't updated `game_status` from 1 (scheduled) to 3 (final) after All-Star break, so scores were never fetched

### Tests Added
**File:** `tests/unit/signals/test_aggregator.py`
- Added `TestComboRegistryNoAntiPattern` class with 3 tests asserting no ANTI_PATTERN entries in fallback registry

---

## What Was NOT Done (Remaining Work)

### 1. Subset Backfill (Jan 1 — Feb 19)

**Decision made:** Delete old rows for the date range, then re-materialize fresh. No schema changes.

**Why delete instead of version:**
- The `current_subset_picks` table is append-only. Old rows stay invisible via `MAX(version_id)` convention, but any new exporter or query that doesn't know this convention will double-count.
- Deleting is safer — any query works without needing hidden knowledge about version filtering.
- Data is fully reconstructable (derived from `player_prop_predictions` + `prediction_accuracy`).

**Backfill approach:**
```bash
# Step 1: Delete old rows for the date range
bq query --project_id=nba-props-platform --nouse_legacy_sql \
'DELETE FROM `nba_predictions.current_subset_picks`
 WHERE game_date BETWEEN "2026-01-01" AND "2026-02-19"'

bq query --project_id=nba-props-platform --nouse_legacy_sql \
'DELETE FROM `nba_predictions.signal_best_bets_picks`
 WHERE game_date BETWEEN "2026-01-01" AND "2026-02-19"'

bq query --project_id=nba-props-platform --nouse_legacy_sql \
'DELETE FROM `nba_predictions.pick_signal_tags`
 WHERE game_date BETWEEN "2026-01-01" AND "2026-02-19"'

# Step 2: Re-materialize all dates
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --start-date 2026-01-01 --end-date 2026-02-19 \
  --only subset-picks,signal-best-bets,live-grading
```

**Important details:**
- Set `trigger_source='backfill_v314'` on backfilled rows for auditability (change in `subset_materializer.py` for the backfill run, or pass via CLI arg)
- ~50 dates, estimated 15-20 minutes
- All date-sensitive filters (blacklist, familiar matchup, signals) query raw data relative to `@target_date`, so historical dates get correct results
- Model health uses `CURRENT_DATE()` (not `@target_date`) but doesn't affect pick selection (always qualifies=True, health gate removed Session 270)

### 2. BQ Combo Registry Cleanup

Run after deploying the code changes:
```sql
DELETE FROM `nba-props-platform.nba_predictions.signal_combo_registry`
WHERE classification = 'ANTI_PATTERN'
```

### 3. Build Backfill Skill (Optional but Recommended)

A Claude skill that can:
1. Dry-run a single date and show what picks/subsets would be produced
2. Compare against existing subsets for that date
3. Run the actual backfill with delete + re-materialize

This gives confidence before bulk-deleting 50 days of subset data.

### 4. Add Threshold Validation to Retrain Pipeline

**Decision made:** Static thresholds with post-retrain governance gate.

Two independent agents reviewed and both agreed:
- Thresholds are market structure properties (how books set lines), not model parameters
- Sample sizes too small for dynamic recomputation (N=27 for UNDER 7+)
- Dynamic thresholds would have overfitted to the Feb 2 collapse (which was model staleness, not threshold drift)

**Implementation:** Add a 7th governance gate to `bin/retrain.sh` that validates edge bucket HRs after each retrain:
```sql
SELECT
  CASE
    WHEN recommendation = 'UNDER' AND ABS(predicted_points - line_value) >= 7 THEN 'under_edge_7plus'
    WHEN recommendation = 'UNDER' AND line_value < 12 THEN 'bench_under'
    WHEN ABS(predicted_points - line_value) >= 5 THEN 'edge_5plus'
  END as filter_group,
  COUNT(*) as n,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hr
FROM `nba_predictions.prediction_accuracy`
WHERE system_id = @new_model_id
  AND game_date BETWEEN @eval_start AND @eval_end
  AND is_voided = FALSE AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1
```
Gate passes if: `edge_5plus` HR >= 65% AND `under_edge_7plus` HR < 50%.

### 5. Commit + Deploy Code Changes

The code changes from this session need to be committed and pushed:
```bash
git add ml/signals/combo_registry.py ml/signals/supplemental_data.py \
  data_processors/publishing/signal_annotator.py \
  data_processors/publishing/signal_best_bets_exporter.py \
  data_processors/publishing/live_grading_exporter.py \
  backfill_jobs/publishing/daily_export.py \
  tests/unit/signals/test_aggregator.py
git commit -m "fix: consolidate best bets systems, fix live grading, remove ANTI_PATTERN"
git push origin main
```

### 6. BEST_BETS_MODEL_ID Env Var

Session 314 noted: the `phase6-export` Cloud Function has `BEST_BETS_MODEL_ID=catboost_v12` set. This means the signal annotator queries V12 predictions instead of V9. This was **not investigated or changed** in this session. It may explain some discrepancies. Next session should verify this is intentional or fix it.

---

## Edge Threshold Validation (Jan 1 — Feb 20)

Ran hit-rate-analysis queries. All thresholds confirmed stable:

| Edge Bucket | Direction | Bets | HR | Threshold Valid? |
|-------------|-----------|------|----|-----------------|
| 7+ | OVER | 58 | **84.5%** | Yes |
| 7+ | UNDER | 27 | **40.7%** | Yes — block is correct |
| 5-7 | OVER | 49 | **69.4%** | Yes |
| 5-7 | UNDER | 59 | **59.3%** | Yes |
| 3-5 | OVER | 175 | 54.9% | Marginal — below 5.0 floor |
| 3-5 | UNDER | 210 | 51.4% | Below breakeven — floor is correct |
| <3 | OVER | 715 | 49.4% | Coin flip |
| <3 | UNDER | 882 | 51.5% | Barely breakeven |

Weekly trend showed edge 5+ went from 84% (mid-Jan) to 30% (Feb 2, stale model) to recovery after ASB retrain. Feb 19 was 16-4 (80%) for best bets.

---

## Architecture After This Session

### Best Bets Flow (Consolidated)

```
Predictions (BQ) ──→ Signal Exporter (System 2) ──→ signal-best-bets/{date}.json (GCS)
                  │                                   ↳ signal_best_bets_picks (BQ)
                  │                                   ↳ 4 signal subsets (BQ)
                  │
                  └─→ Annotator Bridge (System 3) ──→ current_subset_picks (subset_id=best_bets)
                                                      ↳ pick_signal_tags (BQ)

Legacy System 1 (BestBetsExporter) ── REMOVED from daily_export.py
```

Both System 2 and System 3 now use:
- Same `BestBetsAggregator` with same filters
- Same `player_blacklist` (from `compute_player_blacklist()`)
- Same `games_vs_opponent` enrichment (from shared `query_games_vs_opponent()`)
- System 2 additionally uses `multi_model=True` (picks highest edge across all 6 CatBoost models)

### Date-Sensitive Filters (For Backfill Correctness)

| Filter | Data Source | Date-Relative? | Backfill-Safe? |
|--------|------------|----------------|----------------|
| Player blacklist | Season-to-date HR from `prediction_accuracy` | Yes (`game_date < @target_date`) | Yes |
| Familiar matchup | Season-to-date counts from `player_game_summary` | Yes (`game_date < @target_date`) | Yes |
| Signal qualification | Rolling 3-game stats | Yes (relative to target date) | Yes |
| Neg +/- streak | Last 3 games' plus/minus | Yes | Yes |
| Prop line delta | Previous game's prop line | Yes | Yes |
| Model health | `CURRENT_DATE()` | No — always uses today | Doesn't affect selection |
| Signal health | `signal_health_daily` table | Doesn't affect selection | N/A |

All selection-affecting filters use `@target_date` correctly. Backfill produces accurate historical picks.

---

## Key Files Modified

| File | Change |
|------|--------|
| `ml/signals/combo_registry.py` | Removed 2 ANTI_PATTERN entries from fallback registry |
| `ml/signals/supplemental_data.py` | Added shared `query_games_vs_opponent()` with module-level cache |
| `data_processors/publishing/signal_annotator.py` | Added blacklist + games_vs_opponent to bridge path |
| `data_processors/publishing/signal_best_bets_exporter.py` | Uses shared `query_games_vs_opponent()`, removed private method |
| `data_processors/publishing/live_grading_exporter.py` | Removed schedule gate, added stale game_status override |
| `backfill_jobs/publishing/daily_export.py` | Removed legacy BestBetsExporter import + export block |
| `tests/unit/signals/test_aggregator.py` | Added 3 ANTI_PATTERN removal tests |

---

## Next Session Prompt

> **Context:** Session 314B consolidated 3 overlapping best bets systems and fixed live grading. Code changes are done but NOT committed/deployed. See `docs/09-handoff/2026-02-20-SESSION-314B-HANDOFF.md`.
>
> **Remaining work (in order):**
> 1. **Commit and push** the code changes (see files list in handoff). Auto-deploys via Cloud Build.
> 2. **Delete ANTI_PATTERN from BQ:** `DELETE FROM nba_predictions.signal_combo_registry WHERE classification = 'ANTI_PATTERN'`
> 3. **Verify deployment:** Check that `phase6-export` Cloud Function picks up the new code. Run `./bin/check-deployment-drift.sh --verbose`.
> 4. **Backfill subsets Jan 1 — Feb 19:** Delete old rows from `current_subset_picks`, `signal_best_bets_picks`, and `pick_signal_tags` for the date range, then re-materialize with `daily_export.py --start-date 2026-01-01 --end-date 2026-02-19 --only subset-picks,signal-best-bets,live-grading`. Consider building a backfill skill first for dry-run confidence.
> 5. **Add threshold governance gate** to `bin/retrain.sh` — validate edge bucket HRs post-retrain. Static thresholds, just monitoring.
> 6. **Investigate `BEST_BETS_MODEL_ID=catboost_v12`** env var on `phase6-export` CF. May need to be `catboost_v9` (champion).
>
> **Key decisions already made:**
> - Delete old subset rows before backfill (no schema changes, no versioning columns)
> - Static thresholds with post-retrain governance gate (not dynamic)
> - Both best bets systems (signal exporter + annotator bridge) now share the same filters
