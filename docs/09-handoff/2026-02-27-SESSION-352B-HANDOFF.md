# Session 352B Handoff — Daily Validation, Worker Deploy, Website Investigation

**Date:** 2026-02-27
**Status:** Pipeline healthy, prediction-worker deployed, two open issues to investigate

---

## What Was Done

### 1. Daily Validation (Yesterday's Results — 2026-02-26)

Ran full P1+P2 validation for yesterday's 10-game slate. All critical checks passed:

| Check | Result |
|-------|--------|
| Box Scores | 10/10 games, 369 records, 227 active players |
| Minutes Coverage | 99.6% |
| Usage Rate Coverage | 98.7% |
| Plus/Minus | 100% |
| Team Stats | 20/20 teams |
| Grading (7-day) | ~87% coverage for production models |
| Phase 6 Exports | signal-best-bets and tonight exports present |

### 2. Prediction-Worker Deployment

Deployed commit `e9e34051` ("fix: CI/CD stale image bug, LightGBM runtime, edge floor adjustment"):
- Revision: `prediction-worker-00288-qlq`
- All dependency tests passed (including LightGBM)
- All env vars preserved
- Edge floor now at 3.0 (Session 352 change)
- Algorithm version: `v352_edge_floor_3_density_bypass`

### 3. Today's Pipeline Validated (2026-02-27)

5-game slate (CLE@DET, BKN@BOS, NYK@MIL, MEM@DAL, DEN@OKC):
- 11 models each produced 66 predictions, all with ACTUAL_PROP lines
- ML Feature Store: 91 players, 89.2 avg quality
- Best bets: 2 picks generated (Jokic UNDER 28.5, Isaiah Joe OVER 9.5)
- Daily signal: RED across all models (UNDER_HEAVY, 5-game slate)

---

## Open Issues to Investigate

### ISSUE 1: Best Bets Not in `current_subset_picks` Table

**Problem:** The `current_subset_picks` BQ table has pick_angles, signal_tags, combo info columns — but no `signal_best_bets` subset_id exists for today. Subsets present: `all_picks`, `nova_*`, `low_vegas_*`, `xm_*`, `v12q43_*`, `v9_*`.

**Where best bets ARE stored:**
- GCS: `gs://nba-props-platform-api/v1/signal-best-bets/2026-02-27.json` — has full pick_angles, signal_tags, model_agreement, agreeing_models
- GCS: `gs://nba-props-platform-api/v1/signal-best-bets/latest.json` — same

**What to investigate:**
1. Is `signal_best_bets` supposed to be written to `current_subset_picks`? Check the exporter code:
   - `ml/signals/cross_model_scorer.py` — generates best bets
   - Look at Phase 6 export code for signal-best-bets — does it write to BQ or only GCS?
   - Check `shared/config/cross_model_subsets.py` for subset definitions
2. If it's supposed to be in BQ but isn't, find where the subset write was lost
3. The user may want the BQ table populated for downstream analytics — determine if this is a regression or by-design

### ISSUE 2: Best Bets Not Visible on playerprops.io Website

**Problem:** User reports picks not showing on the website despite data being exported.

**What IS exported (all present and fresh):**
- `gs://nba-props-platform-api/v1/signal-best-bets/2026-02-27.json` — 2 picks, 18:08 UTC
- `gs://nba-props-platform-api/v1/signal-best-bets/latest.json` — same
- `gs://nba-props-platform-api/v1/tonight/2026-02-27.json` — 177 players, 18:03 UTC
- `gs://nba-props-platform-api/v1/tonight/all-players.json` — same
- `gs://nba-props-platform-api/v1/status.json` — shows "2 best bets available", overall healthy

**What's NOT in the tonight export:**
- `tonight/2026-02-27.json` has NO `best_bets` key
- No players have `is_best_bet` or `best_bet` flag
- Tonight export top-level keys: `['game_date', 'generated_at', 'total_players', 'total_with_lines', 'games']`

**Likely root cause:** The best bets live in a SEPARATE GCS path (`signal-best-bets/`) from the tonight export (`tonight/`). If the website frontend is:
- Reading best bets from within the tonight JSON → it won't find them (they're not embedded)
- Reading from `signal-best-bets/latest.json` → data is there, could be a frontend rendering or caching issue

**What to investigate:**
1. Check the frontend code at `playerprops.io` — what GCS endpoints does it fetch best bets from?
2. Check if there's a CDN/cache layer between GCS and the website
3. Check browser network tab on the website to see which URLs it requests
4. Check if the best bets were previously embedded in the tonight export and this changed
5. Check if the Phase 6 `SignalBestBetsExporter` is supposed to also write into the tonight JSON
6. Key files to check:
   - Phase 6 export code (likely `data_processors/publishing/` or similar)
   - `SignalBestBetsExporter` class
   - Frontend repo for playerprops.io (if accessible)

---

## Model Fleet Status (Critical Context)

**ALL models are BLOCKED** (below 52.4% breakeven):

| Model | 7d HR | 7d N | State |
|-------|-------|------|-------|
| v9_low_vegas_train0106_0205 | 50.0-51.9% | 52-54 | BLOCKED (best) |
| catboost_v12 (champion) | 44.7-45.8% | 83-85 | BLOCKED |
| catboost_v9 | 35.0-38.9% | 18-20 | BLOCKED |
| v12_noveg_q43_train0104 | 14.8-16.7% | 48-54 | BLOCKED (catastrophic) |

Session 348/350 shadow models (LightGBM, q55_tw) just started accumulating data — need 2-3 more days.

## Scheduler Health

- 113 enabled, 1 failing: `self-heal-predictions` (DEADLINE_EXCEEDED) — low priority

## Key Files

- Best bets GCS: `gs://nba-props-platform-api/v1/signal-best-bets/`
- Tonight GCS: `gs://nba-props-platform-api/v1/tonight/`
- Cross-model scorer: `ml/signals/cross_model_scorer.py`
- Subset config: `shared/config/cross_model_subsets.py`
- Phase 6 exports: `data_processors/publishing/` (check for signal-best-bets exporter)
- Current subset picks table: `nba_predictions.current_subset_picks`

## Quick Verification Commands

```bash
# Check best bets export content
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/latest.json | python3 -m json.tool

# Check tonight export structure
gsutil cat gs://nba-props-platform-api/v1/tonight/all-players.json | python3 -c "import sys,json; print(list(json.load(sys.stdin).keys()))"

# Check what subsets exist in BQ for today
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT subset_id, COUNT(*) as picks
FROM nba_predictions.current_subset_picks
WHERE game_date = CURRENT_DATE()
GROUP BY 1 ORDER BY 1"

# Check deployment is current
./bin/check-deployment-drift.sh --verbose
```
