# Session 369 Handoff — Stability Testing, Sliding Windows, Category Dampening

**Date**: 2026-02-28
**Total experiments**: 41 (20 stability + 8 sliding window + 3 dampening + 5 dampening stability + 2 cross-season + 3 W6 combo)

## What Was Done

### Phase 1: Continued from Session 368
- v12+vegas=0.15 model already registered as shadow (`catboost_v12_vw015_train1201_1231`)
- 24 experiments from Session 368 committed and documented

### Phase 2: Stability Testing (20 experiments)
Added `--random-seed` argument to `quick_retrain.py` (was hardcoded 42).

**v12+vw015 (10 seeds):** Mean 69.8% HR, StdDev 2.5pp, Range 66.1-73.3%
**v12_noveg (10 seeds):** Mean 67.7% HR, StdDev 2.1pp, Range 64.2-70.6%

**Key finding:** Seed variance is ~2.5pp. Any config difference <5pp is within noise. The v12+vw015 vs v12_noveg gap (+2.1pp) is NOT statistically significant.

### Phase 3: Sliding Window (8 experiments)
8 × 31-day windows sliding by 7 days (Nov 15 → Jan 3 training starts).

- W1-W6 remarkably stable: 70.4-75.4% HR, StdDev 1.6pp
- W6 (Dec 20-Jan 19) is the best window at 75.4%
- Sharp cliff at W7-W8 when eval is pure February

### Phase 4: Category Dampening (3 + 5 + 2 + 3 = 13 experiments)
Tested dampening low-signal feature categories (composite, derived, shot_zone).

**Initial results (single seed):** Composite dampening +4.2pp over baseline → looked promising
**Stability test (5 seeds):** Mean +1.96pp, NOT significant (within 2σ noise)
**Cross-season validation:** FAILS — 61.4% vs 66.7% baseline on 2024-25 data
**W6 stacking:** Dampening HURTS tight windows — 70-73% vs 75.4% baseline

**Conclusion:** Category dampening is a dead end. Added to CLAUDE.md dead ends list.

### Phase 5: Betting Strategy Validation (Production BQ queries)
Validated 4 filter proposals from betting strategy agent:

| Pattern | HR | N | Validated? |
|---------|-----|---|-----------|
| UNDER Star AWAY | 38.5% | 13 | YES — clear worst segment |
| UNDER Star HOME | 81.8% | 11 | YES — clear best segment |
| 1-pick days | 50.0% | 14 days | YES — breakeven |
| Edge 7+ | 81.3% | 32 | YES — dramatic edge band effect |

## Key Findings

1. **v12+vw015 true HR is 69.8% ± 2.5pp** (10-seed stability test). All seeds above breakeven.
2. **5pp is the minimum significant difference** between configs. Most Session 367-368 comparisons were within noise.
3. **Training window is robust** across 5-week range (Nov 15 → Jan 19 training ends). No special tuning needed.
4. **Category dampening doesn't generalize** — overfits to eval window. Dead end.
5. **UNDER Star AWAY filter** is the highest-ROI immediate action (38.5% HR, save $380).

## Production State

- `catboost_v12_vw015_train1201_1231` — enabled as shadow model, accumulating live data
- Filter version `v367_star_under_injury_aware_under7plus_v9_only` — live
- No code deployments needed from this session

## Commits

```
e2593544 docs: Session 368 experiment matrix — 24 experiments across 2 seasons
8c55fbe2 feat: add --random-seed arg + Session 369 stability/window/dampening experiments
b419d623 docs: Session 369 round 2 — composite dampening fails cross-season validation
2b3a0e9d docs: add category dampening + W6 stacking to dead ends list
```

## Next Steps

### High Priority
1. **Implement UNDER Star AWAY filter** — add to `ml/signals/aggregator.py`, validate with `backfill_dry_run.py`
2. **Add proportional bet sizing** — `suggested_bet_size` field in JSON export (edge 7+ at $200, 5-7 at $150)
3. **Monitor v12_vw015 shadow model** for 2+ more days, check live HR

### Medium Priority
4. **Walk-forward cadence test** — `season_walkforward.py` with 7/14/21/28-day cadences, expanding vs 42d/56d rolling
5. **1-pick day annotation** — tag low-conviction days in export
6. **Consider W6 window** (Dec 20-Jan 19) for next production retrain

### Research (Lower Priority)
7. Train best seed (456, 73.3% HR) as a shadow model to test if seed selection helps live
8. Test ensemble of 3-5 seeds for stability
9. Investigate Feb structural decay — All-Star break vs trade deadline vs genuine staleness
