# Session 170 Prompt

Copy everything below this line into a new chat:

---

## Session 170 — Verify Vegas Line Fix, Add Monitoring, Clean Up Subset Leaks

**Start by reading these files (in order):**

1. `docs/09-handoff/2026-02-09-SESSION-169-HANDOFF.md` — Full root cause analysis and fix details
2. `predictions/worker/worker.py` lines 1091-1140 — The Vegas line recovery fix (Session 169)
3. `predictions/worker/worker.py` lines 2107-2162 — Expanded features_snapshot (all 33 features)
4. `shared/notifications/subset_picks_notifier.py` lines 145-210 — The model_version leak (unfixed)
5. `docs/08-projects/current/vegas-line-source-tracking/00-PROJECT-PLAN.md` — Vegas source tracking project plan (not yet implemented)

**Context:**

Session 169 (Feb 9, 2026) found and fixed the **root cause of the UNDER bias crisis** — the model's most important feature (#25 vegas_points_line) was NULL for all pre-game (FIRST-run) predictions because:

1. Coordinator loads `actual_prop_line` from Phase 3's stale `current_points_line` (NULL for early predictions)
2. Coordinator separately finds fresh `line_values` from real-time odds queries (has data)
3. Worker's Vegas override depended on `actual_prop_line` (NULL), not `line_values` (available)
4. Result: Model predicted WITHOUT Vegas anchor → systematic UNDER bias (avg_pvl = -3.84 on Feb 9)

**Fix deployed:** Commit `0fb76d06`, deployed to Cloud Run at ~17:55 UTC Feb 9. Worker now recovers Vegas from median of `line_values` when `actual_prop_line` is NULL but `has_prop_line=True`.

**Also completed in Session 169:**
- 1,395 stale predictions deactivated (v9_current_season: 412, v9_36features: 17, catboost_v9_2026_02: 966)
- Disabled broken monthly model `catboost_v9_2026_02` in `catboost_monthly.py:55`
- Expanded features_snapshot from ~17 to all 33 model input features
- Added `fs_vegas_points_line` / `fs_has_vegas_line` to track pre-override values

### Priority Tasks

**P0: VERIFY the Vegas line fix is working (Feb 10 FIRST-run predictions)**
```sql
-- Check that pre-game predictions now have Vegas lines
SELECT player_lookup, prediction_run_mode,
  JSON_VALUE(TO_JSON_STRING(features_snapshot), '$.vegas_points_line') as model_vegas,
  JSON_VALUE(TO_JSON_STRING(features_snapshot), '$.fs_vegas_points_line') as fs_vegas,
  JSON_VALUE(TO_JSON_STRING(features_snapshot), '$.has_vegas_line') as has_vegas,
  current_points_line, predicted_points,
  predicted_points - current_points_line as pvl
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-10'
  AND system_id = 'catboost_v9'
  AND model_version = 'v9_20260201_011018'
  AND prediction_run_mode = 'FIRST'
  AND is_active = TRUE
ORDER BY player_lookup LIMIT 20
```
Expected: `model_vegas` should be non-null, avg_pvl near 0 (not -3.84).

**P1: Add avg_pvl monitoring alert**
When a prediction batch has avg_pvl < -2.0 or > +2.0, it should alert. This would have caught the crisis immediately. Consider adding to the coordinator's batch completion logic or as a post-prediction validation step.

**P2: Add model_version filter to subset queries**
`shared/notifications/subset_picks_notifier.py` lines 152 and 202 filter `WHERE p.system_id = d.system_id` but do NOT filter on `model_version`. This caused stale predictions from wrong models to leak into subsets. Add `AND p.model_version = '{production_model_version}'` to both queries.

**P3: Fix coordinator actual_prop_line at the source**
Long-term fix: the coordinator should set `actual_prop_line` from its fresh odds query (source #2), not the stale Phase 3 table (source #1). Current worker fix is defense-in-depth. Look at `predictions/coordinator/player_loader.py` around line 418.

**P4: Evaluate shadow models**
Two shadow models in GCS have NULL evaluation metrics:
- `catboost_v9_33f_train20251102-20260108_20260208_170526` (same dates, different seed)
- `catboost_v9_33f_train20251102-20260131_20260208_170613` (extended through Jan 31)
Use `/model-experiment` to evaluate on holdout data.

**P5: Feb 4 backfill**
After P0 verification, backfill Feb 4:
```bash
POST /start {"game_date":"2026-02-04","prediction_run_mode":"BACKFILL"}
```

### Context That Was NOT Done (Session 169 ran out of context before completing)
- Project docs were NOT updated (the `/validate-daily` and `/spot-check-features` skills were launched as background agents but results were never read)
- The NEXT-SESSION-PROMPT.md was NOT updated (this file replaces the stale Session 168 version)
- No validation checks were reviewed from the background agents

### Key Files Modified in Session 169

| File | Lines | What Changed |
|------|-------|-------------|
| `predictions/worker/worker.py` | 1095-1117 | Vegas line recovery fix + fs_original tracking |
| `predictions/worker/worker.py` | 2107-2162 | Expanded features_snapshot to all 33 features |
| `predictions/worker/prediction_systems/catboost_monthly.py` | 55-56 | Disabled catboost_v9_2026_02 |
| `docs/09-handoff/2026-02-09-SESSION-169-HANDOFF.md` | Full file | Session 169 handoff |

### Production Model
- System: `catboost_v9`
- Model: `catboost_v9_33features_20260201_011018`
- Model version: `v9_20260201_011018`
- Deployed commit: `0fb76d06`
- Hit rate (edge 3+): 71.2% (holdout Jan 9-31)
