# Session 428 — MLB Sprint 3 Handoff

**For:** The MLB chat session
**From:** Session 428 (NBA filter cleanup session)
**Date:** 2026-03-06

## What's Ready

### Statcast Backfill Script — BUILT & TESTED

`scripts/mlb/backfill_statcast.py` — direct pybaseball → BQ writer, bypasses GCS/Pub/Sub.

**Tested (dry-run):**
```bash
PYTHONPATH=. python scripts/mlb/backfill_statcast.py --start 2025-07-01 --end 2025-07-03 --dry-run --sleep 1
# Result: 325 pitcher records across 3 game days, 0 errors
```

**To run the full backfill:**
```bash
PYTHONPATH=. python scripts/mlb/backfill_statcast.py --start 2025-07-01 --end 2025-09-28 --sleep 3
```

- ~90 days, ~3-10 seconds per day (pybaseball fetch + BQ write)
- Estimated runtime: ~10-15 minutes
- Writes directly to `mlb_raw.statcast_pitcher_daily`
- Deduplication via DELETE + APPEND (safe to re-run)
- pybaseball caching enabled

### What the script does:
1. Fetches ALL pitch data for each date via `pybaseball.statcast()`
2. Aggregates per-pitcher metrics (same logic as `MlbStatcastDailyScraper`): velocity, spin, swstr%, csw%, whiff_rate, zone%, chase_rate, pitch mix
3. Normalizes pitcher names to `player_lookup` format
4. Writes batch to `mlb_raw.statcast_pitcher_daily` with dedup

### Dependencies verified:
- `pybaseball` installed and working
- `mlb_raw.statcast_pitcher_daily` BQ table exists (empty, schema ready)
- Phase 2 processor exists: `data_processors/raw/mlb/mlb_statcast_daily_processor.py`

## Sprint 3 Next Steps (After Backfill)

1. **Run backfill** (command above)
2. **Verify data**: `SELECT COUNT(*), MIN(game_date), MAX(game_date) FROM mlb_raw.statcast_pitcher_daily`
3. **Run walk-forward simulation**: `scripts/mlb/training/walk_forward_simulation.py`
4. **Analyze results** (training window, edge threshold, signal effectiveness)
5. **Train CatBoost V1** from best config
6. **Deploy** before Mar 27

## Key Files

| File | Purpose |
|------|---------|
| `scripts/mlb/backfill_statcast.py` | NEW — direct BQ backfill script |
| `scrapers/mlb/statcast/mlb_statcast_daily.py` | Daily scraper (for production, not backfill) |
| `data_processors/raw/mlb/mlb_statcast_daily_processor.py` | Phase 2 processor (GCS → BQ) |
| `scripts/mlb/training/walk_forward_simulation.py` | Walk-forward sim (needs Statcast data) |
| `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md` | Sprint 2 status |
| `docs/08-projects/current/mlb-pitcher-strikeouts/2026-03-MLB-MASTER-PLAN.md` | Full plan |

## NBA Changes in This Session

4 harmful filters demoted to observation in `ml/signals/aggregator.py`:
- `neg_pm_streak`, `line_dropped_over`, `flat_trend_under`, `mid_line_over`
- Algorithm version: `v428_filter_cleanup`
- All services deployed and building
