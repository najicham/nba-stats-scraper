# Session 328 Handoff — Admin Dashboard Picks Funnel + Public Best Bets Polish

**Date:** 2026-02-22
**Previous Session:** 327 — Ultra Bets live HR tracking, internal-only export, full backfill

## What Was Done

### 1. Admin Dashboard — subsets + model_candidates_summary (Commit 6028f7a9)
- **`subsets: string[]`** on each pick in `dashboard.json` — flat list of qualifying subset IDs
- **`model_candidates_summary`** — new top-level field: per-model candidate funnel (total_candidates, edge_5_plus, picks_selected, avg_edge, max_edge)
- **Confirmed:** `model_health[]` uses `model_id` (not `system_id`)

**File:** `data_processors/publishing/admin_dashboard_exporter.py`

### 2. Public Best Bets — ultra gate + game_time + stat (Commit 01a10e2f)
- **`ultra_tier`** on public OVER picks: auto-activates when gate met (N>=50 OVER at HR>=80%). `check_ultra_over_gate()` in `ml/signals/ultra_bets.py`
- **`stat: "PTS"`** on all picks in both `signal-best-bets/{date}.json` and `best-bets/all.json`
- **`game_time`** ISO 8601 from `nbac_schedule` via team tricode JOIN. Today's picks only.

**Files:** `ml/signals/ultra_bets.py`, `data_processors/publishing/signal_best_bets_exporter.py`, `data_processors/publishing/best_bets_all_exporter.py`

### 3. Backfill angles bug found and fixed (Committed, NOT re-run)
- **Root cause:** `bin/backfill_dry_run.py --write` ran earlier today (Session 327 ultra backfill) and overwrote ALL BQ pick data (Jan 9 - Feb 21). The script calls the aggregator directly but **skips `build_pick_angles()`**, writing `pick_angles: []` for every row.
- **Fix committed:** Added `build_pick_angles()` + `CrossModelScorer` to `simulate_date()` in the backfill script.
- **Needs re-run** next session.

**File:** `bin/backfill_dry_run.py`

## Follow-Up Required (Next Session)

### P1: Re-run backfill to restore angles in BQ
```bash
PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-01-09 --end 2026-02-21 --write
```
~10 min. Then re-export:
```bash
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["best-bets-all", "admin-dashboard", "admin-picks"], "target_date": "2026-02-23", "update_latest": true}'
```

### P2: Investigate BEST_BETS_MODEL_ID env var drift
Dashboard shows `best_bets_model: catboost_v12` but code defaults to `catboost_v9`. Deployed phase6-export CF likely has `BEST_BETS_MODEL_ID=catboost_v12` env var.
```bash
gcloud functions describe phase6-export --region=us-west2 --project=nba-props-platform --format="yaml(serviceConfig.environmentVariables)"
```
If set to `catboost_v12`, either remove it or update to match current champion.

### P3: Verify angles restored
After P1 backfill completes, verify:
```sql
SELECT game_date, COUNTIF(ARRAY_LENGTH(pick_angles) > 0) as has_angles, COUNT(*) as total
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-01-09'
GROUP BY 1 ORDER BY 1 DESC LIMIT 10
```

## Key Findings

- **0 picks on 2026-02-22:** Max edge 4.9 across all models. Edge floor (5.0) rejected all 44 candidates. Post-All-Star thin slate. System working correctly.
- **Ultra trending down recently:** Last 2 weeks 2-3 (40%) on 5 graded picks. Before that: 14-1.
- **Ultra OVER gate:** 17-2 (89.5% HR, N=19). Need 50 for public exposure. ~10 weeks at current pace.
- **GCS JSON files have angles** (e.g. Feb 7, Feb 8, Feb 11) — the generation works. Only BQ lost them from the backfill.

## Builds
All 6 builds SUCCESS after push. Phase 6 manual re-export confirmed new fields in live GCS files.
