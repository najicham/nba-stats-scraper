# Start Your Next Session Here

**Updated:** 2026-02-17 (Session 286 — Features Array Migration Phases 1-4)
**Status:** All production/monitoring code migrated off `features` array (21 files). **NEXT: Complete Phases 5-8 (tools, dead features, array removal).**

---

## Quick Start

```bash
# 1. Morning steering report
/daily-steering

# 2. Check pipeline health
/validate-daily

# 3. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 4. Replay last 30 days
/replay
```

---

## IMMEDIATE PRIORITY: Re-Run Archetype Replays

Session 285 built 23 new archetype dimensions and fixed a feature store data gap (feature_N_value columns were empty Nov 28 → Feb 11). The initial replay run had invalid results due to the missing data. **Must re-run with backfilled data:**

```bash
# 2025-26 season
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2025-11-04 --season-end 2026-02-17 \
    --cadence 7 --rolling-train-days 42 --player-blacklist-hr 40 \
    --avoid-familiar \
    --save-json ml/experiments/results/replay_2526_archetypes_v2.json

# 2024-25 season
PYTHONPATH=. python ml/experiments/season_replay_full.py \
    --season-start 2024-11-06 --season-end 2025-04-13 \
    --cadence 7 --rolling-train-days 42 --player-blacklist-hr 40 \
    --avoid-familiar \
    --save-json ml/experiments/results/replay_2425_archetypes_v2.json
```

**Then analyze:** Compare HR + N for each new dimension across both seasons. Find STABLE winners (HR > 55% both seasons, N >= 20 each). See Session 285 handoff for full analysis instructions.

### What to Look For

**High-priority patterns to validate cross-season:**

| Pattern | 2425 HR (pre-backfill) | N | Potential |
|---------|----------------------|------|-----------|
| Low Usage UNDER | 65.9% | 660 | High volume + high HR |
| Star 3PT UNDER | 63.2% | 310 | Specific, actionable |
| bench_under + rest_adv combo | 61.7% | 661 | Signal combo synergy |
| Pace+Usage Combo | 69.5% | 59 | Player archetype edge |
| Consistent Star UNDER | 68.8% | 48 | Highest HR compound |

**Anti-patterns to confirm (block if stable across seasons):**

| Pattern | 2425 HR | Action |
|---------|---------|--------|
| 3PT Heavy OVER | 47.7% | Block in aggregator |
| Low Usage OVER | 37.2% | Block in aggregator |
| Volatile OVER | 42.0% | Block in aggregator |

---

## Current State

### Session 286 — Features Array Migration (Phases 1-4)

**21 files migrated** off `features` ARRAY to individual `feature_N_value` columns:
- Phase 1: Column-array consistency validation added (`check_column_array_consistency()`, Check 14)
- Phase 2: 3 P0 production files (results_exporter, ml_feature_store_processor, quick_retrain)
- Phase 3: 3 partially-migrated files (data_loaders, training_data_loader, season_replay_full)
- Phase 4: 12 validation/monitoring files (drift detector, audit, quality checks, SQL views)

**New helper:** `build_feature_array_from_columns(row)` in `shared/ml/feature_contract.py` — reconstructs feature list from columns for training/augmentation code.

**Remaining:** Phases 5-8 (tool scripts, dead features f47/f50, validation run, array column removal)

### Session 285 — Deployment Fixes + Feature Store Backfill + Archetypes

**Deployments fixed (5 services):**
- nba-grading-service, validate-freshness, reconcile, validation-runner — all on `014f7cf8`
- Model manifest synced: production = `catboost_v9_33f_train20251102-20260205_20260216_191144`

**Feature store backfill:**
- `feature_N_value` columns were empty Nov 28 → Feb 11 (dual-write code only added Feb 13)
- Backfilled 18,394 rows by extracting from `features` array blob
- All dates now at 85-93% population (matching healthy baseline)
- **No production impact** — model uses `features` blob which was always 100% healthy

**23 new archetype dimensions (dims 24-46):** Shooting Profile, Usage Tier, Consistency, Star 3PT, Role Trajectory, Star Teammate Out, Pace x Usage, Book Disagreement, Cold Streak, Line Pricing, Game Environment, Efficiency, Compound Archetypes, Signal Combos, PPM x Tier

### Session 284 — Production Implementation (DEPLOYED)

| Change | P&L Impact | Status |
|--------|-----------|--------|
| Player blacklist (<40% HR, 8+ picks) | +$10,450 | DEPLOYED |
| Avoid-familiar filter (6+ games vs opp) | +$1,780 | DEPLOYED |
| Remove rel_edge>=30% filter | Positive | DEPLOYED |
| 42-day rolling training window | +$5,370 | DEPLOYED |
| 7-day retrain cadence | +$7,670 | DEPLOYED |
| V12 quantile min edge to 4 | HR +5.1pp | DEPLOYED |
| `ALGORITHM_VERSION` | `v284_blacklist_familiar_reledge` | DEPLOYED |

### Model State
- **V9 champion:** `catboost_v9_33f_train20251102-20260205_20260216_191144` — FRESH
- **6 models total**, all active, all registered in manifest + BQ

### Games resume Feb 19 (10-game slate)

---

## Known Issues

- Quantile model confidence is INVERTED (0.95 = worst tier). Needs separate calibration.
- `dual_agree` and `model_consensus_v9_v12` have no post-fix production data yet (starts Feb 19)
- **Dimensions 35-36 (Book Disagreement):** Uses feature_50 which is dead (always NaN). Remove or replace.
- **feature_47 (teammate_usage_available):** Also dead. Compound archetypes using it won't fire.

---

## Strategic Priorities

### Priority 0: Complete Features Array Migration (Phases 5-8)

Session 286 completed Phases 1-4. Remaining work:

- [ ] **Phase 5:** Migrate 4 backfill/tool scripts (`bin/spot_check_features.py`, `bin/backfill-challenger-predictions.py`, `bin/backfill-v12-predictions.py`, `bin/backfill-v9-no-line-predictions.py`)
- [ ] **Phase 6:** Implement dead features — f47 `teammate_usage_available` (SUM usage_rate for OUT teammates) and f50 `multi_book_line_std` (STDDEV of prop lines across books). Update `feature_contract.py` source mappings.
- [ ] **Phase 7:** Comprehensive validation — run `feature_store_validator --days 90`, `audit_feature_store.py`, spot checks. Verify f47/f50 populated for recent dates.
- [ ] **Phase 8:** Remove array column (after 2+ weeks stable) — stop dual-writing, drop `features`/`feature_names` columns, remove `EXPECTED_FEATURE_COUNT`

See `docs/09-handoff/2026-02-17-SESSION-286-HANDOFF.md` for full details.

### Priority 1: Archetype Replay Analysis — IN PROGRESS
- [ ] Re-run both season replays with backfilled feature data (commands above)
- [ ] Cross-season analysis: find stable winners (HR > 55% both seasons, N >= 20)
- [ ] Identify signal combos worth operationalizing
- [ ] Confirm anti-patterns (Volatile OVER, Low Usage OVER, 3PT Heavy OVER)
- [ ] Remove dead dimensions (35-36 Book Disagreement, fix feature_47 references)

### Priority 2: Feb 19 Validation (Day-of)
- [ ] Run `/validate-daily` on Feb 19 morning
- [ ] Verify all 6 models generate predictions for 10 games
- [ ] Verify `player_blacklist` field in signal-best-bets JSON
- [ ] Check `dual_agree` and `model_consensus_v9_v12` in signal evaluations
- [ ] Check `xm_*` cross-model subsets generate picks
- [ ] Verify `consensus_bonus` and `pick_angles` in JSON output

### Priority 3: Implement Archetype Findings
- [ ] Add confirmed stable winners as new signals or aggregator filters
- [ ] Add confirmed anti-patterns as aggregator blocks
- [ ] Update `ALGORITHM_VERSION` with new filters

### Priority 4: Further Experiments
- [ ] Adaptive direction gating
- [ ] Per-model edge thresholds (V12 Q43 at edge>=4, V9 MAE at edge>=5)
- [ ] Min training days sweep (14d/21d with 7d cadence)
- [ ] High conviction tier in API

### Completed Priorities
- ~~Deployment drift~~ — **DONE Session 285** (5 services fixed)
- ~~Feature store backfill~~ — **DONE Session 285** (18,394 rows)
- ~~Archetype dimensions~~ — **DONE Session 285** (23 new dims built)
- ~~ALL replay findings~~ — **DONE Session 284**
- ~~Parameter sweeps~~ — **DONE Session 283**
- ~~Experiment filters~~ — **DONE Session 282**
- ~~Full season replay~~ — **DONE Session 280**

---

## Key Session References

- **Session 286:** Features array migration Phases 1-4 (21 files, 843 insertions). Handoff: `docs/09-handoff/2026-02-17-SESSION-286-HANDOFF.md`
- **Session 285:** Deployment fixes, feature store backfill (18K rows), 23 archetype dimensions. Handoff: `docs/09-handoff/2026-02-17-SESSION-285-HANDOFF.md`
- **Session 284:** Production implementation — blacklist, avoid-familiar, rel_edge removal. Handoff: `docs/09-handoff/2026-02-17-SESSION-284-HANDOFF.md`
- **Session 283:** 40 experiments — Cad7+Roll42+BL40+AvoidFam = +$92,470, 60.3% HR
- **Session 280-282:** Season replay engine + experiment filters + cross-season validation

**Project docs:**
- **Season replay findings:** `docs/08-projects/current/season-replay-analysis/00-FINDINGS.md`
- **Multi-model architecture:** `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
