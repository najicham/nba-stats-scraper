# Start Your Next Session Here

**Updated:** 2026-02-16 (Session 279 — Pick Provenance + Hierarchical Layers)
**Status:** Pick provenance DEPLOYED. Each best bet now includes `qualifying_subsets` (which Level 1/2 subsets the player appeared in) + `algorithm_version` for scoring traceability. Phase 1: observation only. Ready for Feb 19 game day.

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

## Current State

### Pick Provenance (Session 279) — NEW
- **qualifying_subsets:** each best bet now shows which Level 1/2 subsets the player-game appeared in (e.g., "V9 Top Pick", "Cross-Model 5+ Agree")
- **algorithm_version:** `v279_qualifying_subsets` tag for scoring traceability
- **Pick angles updated:** new angle priority 2 — "Appears in N subsets: ..."
- **Phase 1:** observation only — store and display, don't score on subset membership
- **New file:** `ml/signals/subset_membership_lookup.py`
- **BQ columns added:** `qualifying_subsets STRING`, `qualifying_subset_count INT64`, `algorithm_version STRING` to both `signal_best_bets_picks` and `current_subset_picks`

### Smart Filters + Pick Angles (Session 278)
- **3 smart filters in aggregator:** feature quality floor (<85), bench UNDER block (line<12), relative edge cap (>=30%)
- **Expected impact:** ~395 picks → ~195 picks, 52.2% → 56.4% HR
- **Pick angles system:** each pick gets up to 5 human-readable reasoning strings
- **Angle categories:** confidence tier context, subset membership, direction+player tier HR, cross-model consensus, signal-specific, warnings

### Multi-Model Best Bets (Session 277)
- **3-layer architecture DEPLOYED:** per-model subsets, cross-model observation subsets, consensus scoring
- **V12 signals UNLOCKED:** `dual_agree` and `model_consensus_v9_v12` now fire in production (were broken since creation)
- **5 cross-model subsets:** `xm_consensus_3plus`, `xm_consensus_5plus`, `xm_quantile_agreement_under`, `xm_mae_plus_quantile_over`, `xm_diverse_agreement`
- **Consensus bonus:** max 0.36 added to aggregator composite_score (formula: agreement_base * diversity_mult + quantile_bonus)
- **See:** `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md`

### Signal System (Session 275)
- **18 active signals** (10 removed — 4 below breakeven, 6 never-fire)
- **Aggregator HR: 73.9%** (up from 60.3% pre-cleanup)
- **Top standalone signal:** `bench_under` (76.9% HR, N=156, PRODUCTION)
- **Combo registry:** 10 entries (8 SYNERGISTIC, 2 ANTI_PATTERN)

### Model State (Session 276 — Retrain Sprint)
- **V9 champion:** `catboost_v9_train1102_0205` — FRESH
- **V12 shadow:** `catboost_v12_noveg_train1102_0205` — FRESH
- **V9 Q43/Q45:** ALL GATES PASSED (62.6%/62.9% HR 3+)
- **V12 Q43/Q45:** FIRST EVER V12+quantile, ALL GATES PASSED (61.6%/61.2% HR 3+)
- **6 models total**, all active

### Monitoring & Automation
- **Decay detection:** DEPLOYED (11 AM ET daily)
- **Retrain reminders:** Weekly Mon 9 AM ET
- **Games resume:** Feb 19 (10-game slate)

---

## Known Issues

- `nba-grading-service` stale deployment (pre-existing, not blocking Thursday)
- `reconcile` 1 commit behind (All-Star break session)
- Quantile model confidence is INVERTED (0.95 = worst tier). Needs separate calibration.
- `dual_agree` and `model_consensus_v9_v12` have no post-fix production data yet (will start Feb 19)

---

## Strategic Priorities

### Priority 0: Feb 19 Validation (Day-of)
- [ ] Run `/validate-daily` on Feb 19 morning
- [ ] Verify all 6 models generate predictions for 10 games
- [ ] Check `dual_agree` and `model_consensus_v9_v12` appear in signal evaluations
- [ ] Check `xm_*` cross-model subsets generate picks
- [ ] Verify `consensus_bonus` appears in signal-best-bets JSON
- [ ] Verify `pick_angles` appear in signal-best-bets JSON output
- [ ] Verify `qualifying_subsets` appear in signal-best-bets JSON output
- [ ] Monitor first decay-detection Slack alert for new models
- [ ] Confirm smart filters are blocking poison picks (check logs for skipped counts)

### Priority 1: Post-Break Monitoring (Feb 19-28)
- [ ] Track aggregator top-5 HR daily (target: 73.9%)
- [ ] Validate cross-model subset hit rates (need N >= 30)
- [ ] Compare retrained model HRs on live data
- [ ] Monitor confidence tier performance with new models
- [ ] Validate smart filter impact (before/after pick counts and HR)
- [ ] Observe qualifying_subset_count distribution — how many picks have 2+ subsets?

### Priority 2: Phase 2 — Subset Membership Scoring (after 30 days)
- [ ] Backtest qualifying_subset_count vs hit rate
- [ ] If correlated: add `subset_membership_bonus` to composite_score (+0.05 per subset beyond 2)
- [ ] Include subset W-L records in best bets JSON for each qualifying subset

### Priority 3: Confidence Overhaul (future session)
- [ ] Replace `75 + quality_bucket + std_bucket` with calibrated lookup
- [ ] Separate calibration for quantile models
- [ ] A/B shadow test before promoting

### Priority 4: Model-Specific Routing (after 14 days)
- [ ] V9 for OVER picks (stars, home, high edge)
- [ ] V12/Q45 for UNDER picks (role players, general)
- [ ] Team blocklist (MEM, MIA, PHX, LAC, HOU)
- [ ] Requires 50+ edge 3+ graded picks per model

### Completed Priorities
- ~~Pick provenance + hierarchical layers~~ — **DONE Session 279** (qualifying_subsets, algorithm_version)
- ~~Smart filters + pick angles~~ — **DONE Session 278** (3 filters, angle builder)
- ~~Multi-model best bets architecture~~ — **DONE Session 277** (3 layers deployed)
- ~~V12 signal data gap~~ — **DONE Session 277** (dual_agree/model_consensus now fire)
- ~~Model retrain sprint~~ — **DONE Session 276** (6 models, all gates passed)
- ~~Signal cleanup~~ — **DONE Session 275** (10 removed, aggregator 60.3% → 73.9%)
- ~~Health gate removal~~ — **DONE Session 270** (+$1,110 recovered)

---

## Key Session References

- **Session 279:** Pick provenance (qualifying_subsets, algorithm_version), hierarchical layers
- **Session 278:** Smart filters (3 poison blocks), pick angles system
- **Session 277:** Multi-model best bets, 0.92 confidence bug found, model profiling
- **Session 276:** Model retrain sprint — 6 models trained, V12+quantile first ever
- **Session 275:** Signal cleanup (10 removed), combo registry (3 added)
- **Session 274:** 5 market-pattern UNDER signals
- **Session 273:** Model management overhaul

**Project docs:**
- **Multi-model architecture:** `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **Steering playbook:** `docs/02-operations/runbooks/model-steering-playbook.md`
