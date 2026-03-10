# Session 462 Handoff — BB Simulator Validated Signals/Filters

**Date:** 2026-03-10
**Focus:** Implement 5-season cross-validated findings from BB pipeline simulator
**Previous:** Session 461 (BB simulator findings), Session 460 (MLB)
**Algorithm:** `v462_simulator_validated`

## What Changed

### Filters Demoted to Observation (blocking winners)
| Filter | CF HR (5-season) | N | Action |
|--------|-----------------|---|--------|
| `familiar_matchup` | 54.4% | 1,151 | → observation |
| `b2b_under_block` | 54.0% | 2,060 | → observation |
| `ft_variance_under` | 56.0% | 1,001 | → observation |

### New Active Filters (promoted from observation same session)
| Filter | Blocked HR | N | Mechanism |
|--------|-----------|---|-----------|
| `cold_fg_under` | 38.5% | 457 | UNDER when FG% last_3 is 10%+ below season — bounce-back |
| `cold_3pt_under` | 45.6% | 735 | UNDER when 3PT% last_3 is 10%+ below season — bounce-back |

### Harmful Signals Removed
| Signal | HR (5-season) | Action |
|--------|--------------|--------|
| `starter_away_overtrend_under` | 48.2% | → SHADOW, removed from UNDER_SIGNAL_WEIGHTS |
| `sharp_book_lean_over` | 41.7% | → SHADOW, removed from OVER_SIGNAL_WEIGHTS + rescue |
| `over_streak_reversion_under` | 51.6% | Removed from registry (kept in SHADOW for tracking) |

### New Shadow Signals (accumulating BB data)
| Signal | HR | N | Source |
|--------|-----|---|--------|
| `hot_3pt_under` | 62.5% | 670 | supplemental['three_pt_stats'] |
| `cold_3pt_over` | 60.2% | 123 | supplemental['three_pt_stats'] |
| `line_drifted_down_under` | 59.8% | 336 | pred['bp_line_movement'] (BettingPros) |

### New Observation Filter
| Filter | Blocked HR | N | Notes |
|--------|-----------|---|-------|
| `over_line_rose_heavy_obs` | 38.9% | 54 | N too thin for active — accumulate data |

### Data Pipeline Additions
- BettingPros line movement query added to `supplemental_data.py` + `per_model_pipeline.py`
- Shooting stats (`fg_pct_last_3`, `fg_pct_season`, `three_pct_last_3`, `three_pct_season`) now in pred dict

## Expected Impact

**Immediate (filter removals):**
- More picks passing through (3 fewer blocking filters)
- HR should improve — these filters were blocking 54-56% CF HR picks

**Immediate (new active filters):**
- `cold_fg_under` and `cold_3pt_under` will block UNDER picks on cold shooters
- These have strong evidence: blocking 38-46% HR picks = clearly value-destroying

**Gradual (new shadow signals):**
- Will accumulate BB-level data over next 7+ days
- Graduation criteria: HR >= 60% + N >= 30 at BB level

## Monitoring

- **Day 1:** Check Cloud Run logs for BettingPros query success
- **Day 1:** Verify new signal tags appearing in `signal_best_bets_picks`
- **Day 3:** Check filter_counts for cold_fg_under/cold_3pt_under firing
- **Day 7:** Query `signal_health_daily` for new signals' fire rates and HR
- **Ongoing:** Watch observation filter counts for familiar_matchup/b2b/ft_variance

## Files Changed

| File | Changes |
|------|---------|
| `ml/signals/aggregator.py` | Demoted 3 filters, promoted 2 new, removed 3 signal weights, added 6 shadow/obs |
| `ml/signals/registry.py` | Removed 1 signal, added 3 new |
| `ml/signals/supplemental_data.py` | BettingPros query + shooting stats to pred dict |
| `ml/signals/per_model_pipeline.py` | Same (parallel path) |
| `ml/signals/pipeline_merger.py` | Version bump, removed sharp_book_lean from rescue |
| `ml/signals/pick_angle_builder.py` | 3 new angles, removed 1 |
| `ml/signals/hot_3pt_under.py` | NEW signal class |
| `ml/signals/cold_3pt_over.py` | NEW signal class |
| `ml/signals/line_drifted_down_under.py` | NEW signal class |
| Tests (5 files) | 236 tests passing |
| `SIGNAL-INVENTORY.md` | Updated counts, entries, demotions |

## Next Steps

### P1: Monitor deployment
- Verify builds succeed and services are healthy
- Check BettingPros query fires correctly in production

### P2: Signal graduation (7+ days)
- Check `hot_3pt_under`, `cold_3pt_over`, `line_drifted_down_under` fire rates
- Promote to active if HR >= 60% + N >= 30 at BB level

### P3: Continue signal discovery
- FT rate anomaly UNDER (recent FTA 50%+ above season avg)
- Minutes trend decline UNDER (last_3 < season * 0.85)
- Game total environment boost (high O/U → OVER)

### P4: Weekly retrain
- Models may be stale — check `weekly-retrain` CF status
- Stale models are the #1 HR decay factor (more than signal changes)
