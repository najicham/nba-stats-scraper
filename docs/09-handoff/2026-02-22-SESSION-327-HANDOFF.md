# Session 327 Handoff — Ultra Bets Live HR, Internal Export, Full Backfill

**Date:** 2026-02-22
**Focus:** Live HR tracking, internal-only export, Jan 9 - Feb 21 backfill, monitoring strategy

## Summary

1. Renamed `hit_rate`/`sample_size` → `backtest_hr`/`backtest_n` with `backtest_period` and `backtest_date`
2. Added `compute_ultra_live_hrs()` — queries graded ultra picks after `BACKTEST_END`
3. Stripped ultra from public GCS JSON, added to admin picks export with full stats
4. Backfilled Jan 9 - Feb 21: **99 picks written, 93 graded, ultra classifications applied**
5. Re-graded all backfilled rows from `prediction_accuracy`

## Live Performance (Jan 9 - Feb 21)

### Best Bets vs Ultra

| Segment | Record | HR% | P&L |
|---------|--------|-----|-----|
| **All Best Bets** | 67-32 | 67.7% | +$3,180 |
| **Ultra Bets** | **25-8** | **75.8%** | **+$1,620** |
| Non-Ultra Best Bets | 42-24 | 63.6% | +$1,560 |

Ultra = 33% of picks, 51% of profit.

### Per-Criterion

| Criterion | Backtest | Live | Status |
|-----------|----------|------|--------|
| `v12_edge_6plus` | 100% (26) | **95.2% (20-1)** | VALIDATED |
| `v12_over_edge_5plus` | 100% (18) | **89.5% (17-2)** | VALIDATED |
| `v12_edge_4_5plus` | 77.2% (57) | **75.8% (25-8)** | VALIDATED |
| `consensus_3plus_edge_5plus` | 78.9% (18) | **0 picks** | DEAD |

### Direction Split — Critical Finding

| Direction | Ultra HR | Record | Non-Ultra HR |
|-----------|----------|--------|-------------|
| **OVER** | **89.5%** | **17-2** | 62.8% |
| UNDER | 57.1% | 8-6 | 65.2% |

**Ultra OVER is elite.** Ultra UNDER barely beats breakeven. 6 of 8 ultra losses are UNDER.

### Ultra Losses Breakdown

All 8 losses:
- 6 UNDER picks (Giannis, Luka x2, Trey Murphy, Brandon Williams, Tyrese Maxey) — V12 UNDER bias
- 2 OVER picks (Donovan Mitchell, LeBron James) — genuinely unpredictable games

### Weekly Stability

| Week | Ultra | Non-Ultra |
|------|-------|-----------|
| Jan 5 | 7-1 (87.5%) | 9-3 (75%) |
| Jan 12 | 3-3 (50%) | 5-7 (41.7%) |
| Jan 19 | 8-1 (88.9%) | 9-1 (90%) |
| Jan 26 | 4-0 (100%) | 6-3 (66.7%) |
| Feb 2 | 1-0 (100%) | 9-6 (60%) |
| Feb 9 | 0-1 (0%) | 3-3 (50%) |
| Feb 16 | 2-2 (50%) | 1-1 (50%) |

Jan 12 and Feb 9-16 are the weak spots. Feb is All-Star break (thin slates).

## Architecture

```
Aggregator (classify_ultra_pick)
    ↓
Signal Best Bets Exporter
    ├── compute_ultra_live_hrs() → merge live_hr/live_n
    ├── BQ write: full ultra data (backtest + live) ✓
    ├── Public JSON: ultra STRIPPED ✗
    └── Admin JSON: per-pick ultra + summary + live HRs ✓
```

### Admin JSON Shape

```json
{
  "picks": [
    {"player": "...", "ultra_tier": true, "ultra_criteria": [
      {"id": "v12_edge_6plus", "backtest_hr": 100.0, "live_hr": 95.2, "live_n": 21}
    ]},
    {"player": "...", "ultra_tier": false, "ultra_criteria": []}
  ],
  "ultra": {"ultra_count": 1, "live_hrs": {"v12_edge_6plus": {"live_hr": 95.2, "live_n": 21, "backtest_date": "2026-02-22"}}}
}
```

## Files Modified

| File | Change |
|------|--------|
| `ml/signals/ultra_bets.py` | Rename fields, `BACKTEST_END`, `compute_ultra_live_hrs()` |
| `ml/signals/pick_angle_builder.py` | New field names, live HR in angle text |
| `data_processors/publishing/signal_best_bets_exporter.py` | Live HR enrichment, strip ultra from JSON |
| `data_processors/publishing/admin_picks_exporter.py` | Ultra per-pick + summary with live HRs |
| `bin/backfill_dry_run.py` | Live HR merge for `--write` mode |
| `CLAUDE.md` | Full ultra section with live data, monitoring plan |

## Monitoring Plan

### Weekly Checks

1. **Ultra OVER HR** — flag if drops below 75% (currently 89.5%)
2. **Ultra UNDER HR** — flag if drops below 52.4% breakeven (currently 57.1%)
3. **Per-criterion divergence** — flag if live HR diverges >15% from backtest
4. **`consensus_3plus_edge_5plus`** — dead criterion, 0 picks. Consider removing or lowering threshold

### Daily (Automated)

- V12 model decay detection (existing `decay-detection` CF at 11 AM ET)
- Pipeline canary auto-heal (existing, every 30 min)

### After Each Retrain

1. Re-run backtest: `PYTHONPATH=. python bin/backfill_dry_run.py --start <new_train_end> --end <today> --verbose`
2. Update `BACKTEST_END` in `ml/signals/ultra_bets.py`
3. Update `backtest_hr`, `backtest_n`, `backtest_period`, `backtest_date` in `ULTRA_CRITERIA`
4. If any criterion drops below 60% on fresh backtest, disable it

### Decision Triggers

| Trigger | Action |
|---------|--------|
| Ultra OVER N >= 50, HR >= 80% | Expose ultra to public JSON |
| Ultra UNDER HR < 52.4% for 2+ weeks | Remove UNDER from `v12_edge_4_5plus` |
| `consensus_3plus_edge_5plus` still 0 picks after 2 weeks | Remove criterion |
| V12 model decay alert | Pause ultra, recalibrate after retrain |
| Model retrain | Re-validate all criteria on fresh holdout |

## Strategic Recommendations

### Should we change ultra criteria?

**Not yet.** All 3 active criteria validated live. But watch for:
- **`v12_edge_4_5plus` UNDER** is dragging overall ultra HR down. Future option: split into `v12_over_edge_4_5plus` (keep) and raise UNDER floor to edge 6+.
- **`consensus_3plus_edge_5plus`** never fires — likely because multi-model agreement at edge 5+ is extremely rare. Consider lowering to 2+ models or edge 4+, or remove entirely.

### Should we change best bets creation?

**No.** 67.7% HR and +$3,180 P&L is strong. The edge-first architecture (Session 297) is working. Ultra is additive labeling, not a separate selection mechanism.

### When to expose ultra publicly?

**Gate:** Ultra OVER must hit N >= 50 graded picks AND maintain HR >= 80%.
- Currently: 17-2 OVER (89.5%), need ~31 more graded OVER ultra picks
- At ~3 ultra OVER picks/week → **mid-March 2026** validation target
- Start with OVER-only ultra badge; hold UNDER until separately validated

## Next Steps

- [ ] Monitor ultra performance weekly via admin dashboard
- [ ] After next retrain: re-validate criteria, update BACKTEST_END
- [ ] At N=50 OVER ultra: decision on public exposure
- [ ] Consider removing `consensus_3plus_edge_5plus` (dead criterion)
- [ ] Consider splitting `v12_edge_4_5plus` by direction
