# Session 384 Handoff — Per-Model Performance Profiling System

**Date:** 2026-03-01
**Status:** Phase 0+1 implemented and backfilled. Observation mode active. No picks affected.

## What Was Done

### Per-Model Performance Profiling (Phase 0+1)

Built a data-driven per-model filtering infrastructure that profiles each individual model across 6 dimensions, replacing coarse family-level filters with per-model granularity.

**Problem solved:** The pipeline applies the same filters to all models. Only 5 of 25+ filters are model-aware, and those operate at the family level (4 groups for 11+ models). A model that's 90% OVER but 30% UNDER gets the same treatment as a balanced one.

**Architecture:**

| Component | File | Purpose |
|-----------|------|---------|
| BQ Schema | `schemas/bigquery/nba_predictions/model_profile_daily.sql` | Partitioned table, ~220 rows/day |
| Computation | `ml/analysis/model_profile.py` | Single BQ query, UNION ALL across 6 dimensions |
| Post-grading | `post_grading_export/main.py` (step 5b) | Auto-compute daily after grading |
| Loader | `ml/signals/model_profile_loader.py` | O(1) `is_blocked()` lookups, fallback chain |
| Observation | `ml/signals/aggregator.py` | Logs `model_profile_would_block` without filtering |
| Wiring | `signal_best_bets_exporter.py`, `signal_annotator.py` | Load + pass to aggregator |
| Monitor | `bin/monitoring/model_profile_monitor.py` | Daily alerting for drift/stale blocks |

**6 Dimensions tracked per model:**
1. **Direction** (OVER/UNDER)
2. **Tier** (bench/role/starter/star)
3. **Line range** (0_12, 12_15, 15_20, 20_25, 25_plus)
4. **Edge band** (3_5, 5_7, 7_plus)
5. **Home/Away** (HOME/AWAY)
6. **Signal** (per signal tag effectiveness)

**Blocking threshold:** HR < 45% AND N >= 15 (same as model_direction_affinity).
**Fallback chain:** model-level → affinity-group-level → 52.4% default.

### Backfill Results

30-day backfill: **3,911 rows across 24 dates, 33 models, up to 64 blocked slices/day.**

Known patterns confirmed:
- V9 UNDER consistently blocked (37-41% HR)
- V9 AWAY blocked (33-44% HR)
- v12_noveg AWAY blocked on specific models
- Bench tier blocked on multiple V12 models
- Star tier blocked on V12+vegas models

### Also Included

Session 383 model family classification fixes (uncommitted from prior session):
- `v12_noveg_mae` catch-all family added to `cross_model_subsets.py`
- V16 noveg families (`v16_noveg_mae`, `v16_noveg_rec14_mae`) added
- Affinity group mapping updated for V16 noveg models

## What's NOT Changed

- **No picks affected** — observation mode only logs what WOULD be blocked
- **Existing hardcoded filters unchanged** — model_direction_affinity, away_noveg, starter_v12_under all still active
- Phase 2 (active blocking) requires 5+ days of observation data
- Phase 4 (profile-weighted selection) is future work

## Next Steps

1. **Monitor observation logs** for 5+ days — compare `model_profile_would_block` count vs existing filter counts
2. **Phase 2 activation** — flip observation to active blocking, replace hardcoded filters
3. **Phase 3 Cloud Function** — deploy `model-profile-monitor` on Cloud Scheduler at 11:30 AM ET
4. **Phase 4 investigation** — should different models get different signal sets and filter stacks?

## Key Files

```
schemas/bigquery/nba_predictions/model_profile_daily.sql  # DDL
ml/analysis/model_profile.py                               # Computation + CLI
ml/signals/model_profile_loader.py                         # Runtime loader
ml/signals/aggregator.py                                   # Observation logging
data_processors/publishing/signal_best_bets_exporter.py    # Wiring
data_processors/publishing/signal_annotator.py             # Wiring
orchestration/cloud_functions/post_grading_export/main.py  # Step 5b
bin/monitoring/model_profile_monitor.py                    # Daily monitor
```

## Commands

```bash
# Single-date profile computation
PYTHONPATH=. python ml/analysis/model_profile.py --date 2026-03-01

# Monitor check
PYTHONPATH=. python bin/monitoring/model_profile_monitor.py --date 2026-02-28

# Backfill (already done Jan 30 - Feb 28)
PYTHONPATH=. python ml/analysis/model_profile.py --backfill --start 2026-01-30
```
