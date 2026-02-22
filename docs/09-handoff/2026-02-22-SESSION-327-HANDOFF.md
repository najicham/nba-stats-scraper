# Session 327 Handoff — Ultra Bets Live HR Tracking + Internal-Only Export

**Date:** 2026-02-22
**Focus:** Add live HR tracking for Ultra Bets, make ultra internal-only (BQ + admin), strip from public JSON

## Summary

1. Renamed `hit_rate`/`sample_size` → `backtest_hr`/`backtest_n` with `backtest_period` and `backtest_date` metadata
2. Added `compute_ultra_live_hrs()` — queries graded ultra picks after `BACKTEST_END` for real-world tracking
3. Stripped `ultra_tier`, `ultra_criteria`, `ultra_bets`, `ultra_bets_count` from public GCS JSON
4. Added ultra fields to admin picks export (`v1/admin/picks/{date}.json`) with full stats + live HRs
5. Updated `pick_angle_builder.py` to show both backtest and live HR when available
6. Updated `backfill_dry_run.py --write` to enrich ultra criteria with live HRs before BQ write

## Architecture

```
Aggregator (classify_ultra_pick)
    ↓
Signal Best Bets Exporter
    ├── compute_ultra_live_hrs() → merge live_hr/live_n into ultra_criteria
    ├── BQ write: ultra_tier + ultra_criteria (full backtest + live data) ✓
    ├── Public JSON: ultra STRIPPED ✗
    └── Admin JSON: ultra_tier + ultra_criteria inline on each pick ✓
                    + top-level ultra summary (count + live_hrs) ✓
```

### Data Flow

| Destination | Ultra Data | Notes |
|------------|-----------|-------|
| `signal_best_bets_picks` (BQ) | Full: backtest + live HRs | Internal monitoring |
| `v1/signal-best-bets/{date}.json` (public) | **None** — stripped | Until live-validated |
| `v1/admin/picks/{date}.json` (admin) | Full: per-pick inline + summary | Admin dashboard |
| Pick angles (BQ only) | Backtest + live HR text | Internal annotations |

### Admin JSON Shape (per frontend request)

```json
{
  "picks": [
    {
      "player": "Jayson Tatum",
      "direction": "OVER",
      "edge": 7.2,
      "ultra_tier": true,
      "ultra_criteria": [
        {
          "id": "v12_edge_6plus",
          "description": "V12+vegas model, edge >= 6",
          "backtest_hr": 100.0,
          "backtest_n": 26,
          "backtest_period": "2026-01-09 to 2026-02-21",
          "backtest_date": "2026-02-22",
          "live_hr": 85.7,
          "live_n": 7
        }
      ],
      "result": "WIN"
    },
    {
      "player": "Non-Ultra Player",
      "ultra_tier": false,
      "ultra_criteria": []
    }
  ],
  "ultra": {
    "ultra_count": 1,
    "live_hrs": {
      "v12_edge_6plus": {
        "live_hr": 85.7,
        "live_n": 7,
        "backtest_date": "2026-02-22"
      }
    }
  }
}
```

### Key Constant

`BACKTEST_END = '2026-02-21'` in `ml/signals/ultra_bets.py` — live HR queries start after this date. Update after re-validation backtests.

### Frontend Agreement

- Admin: gold left-border + "ULTRA" badge on ultra rows, live vs backtest HR comparison in expandable detail
- Public (future): inline badge/highlight within picks list, not a separate section
- No separate `ultra_picks` array — ultra_tier/ultra_criteria live on each pick, no cross-referencing

## Files Modified

| File | Change |
|------|--------|
| `ml/signals/ultra_bets.py` | Rename fields, add `BACKTEST_END`, add `compute_ultra_live_hrs()` |
| `ml/signals/pick_angle_builder.py` | Update field names, show live HR when available |
| `data_processors/publishing/signal_best_bets_exporter.py` | Wire live HR, strip ultra from JSON, keep in BQ |
| `data_processors/publishing/admin_picks_exporter.py` | Add ultra per-pick + top-level summary with live HRs |
| `bin/backfill_dry_run.py` | Add live HR merge for `--write` mode |
| `CLAUDE.md` | Update Ultra Bets section |

## Pending: Backfill

After commit + push + deploy:

```bash
# 1. Backfill picks with ultra classifications (Feb 19-21)
PYTHONPATH=. python bin/backfill_dry_run.py --start 2026-02-19 --end 2026-02-21 --write --verbose

# 2. Re-grade backfilled rows
bq query --use_legacy_sql=false "
UPDATE \`nba-props-platform.nba_predictions.signal_best_bets_picks\` sbp
SET actual_points = pa.actual_points, prediction_correct = pa.prediction_correct
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\` pa
WHERE sbp.player_lookup = pa.player_lookup
  AND sbp.game_id = pa.game_id AND sbp.game_date = pa.game_date
  AND pa.system_id = sbp.system_id
  AND sbp.game_date BETWEEN '2026-02-19' AND '2026-02-21'
  AND pa.prediction_correct IS NOT NULL"
```

## Next Steps

- Monitor live ultra HRs as graded picks accumulate (check `v1/admin/picks/` daily)
- Once live N >= 20 per criterion and HRs validated, expose ultra to public JSON (re-add fields to picks_json loop in signal_best_bets_exporter.py)
- Update `BACKTEST_END` after next retrain + re-validation backtest
- Frontend: wire up gold border + ULTRA badge in admin dashboard, live vs backtest color coding
