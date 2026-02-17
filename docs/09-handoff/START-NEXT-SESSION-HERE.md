# Start Your Next Session Here

**Updated:** 2026-02-16 (Session 277 — Multi-Model Best Bets + Deep Model Analysis)
**Status:** 3-layer multi-model architecture DEPLOYED. Critical findings: 0.92 confidence bug, bench-UNDER catastrophe, pick angles system designed. Next: implement smart filters + pick angles before Feb 19 game day.

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

### Multi-Model Best Bets (Session 277) — NEW
- **3-layer architecture DEPLOYED:** per-model subsets, cross-model observation subsets, consensus scoring
- **V12 signals UNLOCKED:** `dual_agree` and `model_consensus_v9_v12` now fire in production (were broken since creation)
- **5 cross-model subsets:** `xm_consensus_3plus`, `xm_consensus_5plus`, `xm_quantile_agreement_under`, `xm_mae_plus_quantile_over`, `xm_diverse_agreement`
- **Consensus bonus:** max 0.36 added to aggregator composite_score (formula: agreement_base * diversity_mult + quantile_bonus)
- **New files:** `ml/signals/cross_model_scorer.py`, `shared/config/cross_model_subsets.py`, `data_processors/publishing/cross_model_subset_materializer.py`
- **See:** `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md`

### CRITICAL FINDINGS (Session 277 Analysis)

**0.92 Confidence Bug:**
The confidence formula `75 + quality_bucket + std_bucket` produces 9 discrete values. The 0.92 tier = "consistent bench players" = 47.5% HR (316 picks). The 0.95 tier for quantile models = 39-42% HR (fully inverted). Root cause: confidence rewards low volatility + high quality, which selects bench players that are hardest to predict.

**Worst Segments to BLOCK:**
| Segment | Picks | HR | Action |
|---------|-------|----|--------|
| Bench UNDER (line < 12) | 37 | **35.1%** | BLOCK in aggregator |
| UNDER, Edge 7+ | 26 | **38.5%** | BLOCK in aggregator |
| UNDER, 2+ Days Rest | 82 | **32.9%** | BLOCK in aggregator |
| Feature quality < 85 | 50 | **24.0%** | BLOCK in aggregator |

**Best Segments to BOOST:**
| Segment | Picks | HR | Action |
|---------|-------|----|--------|
| OVER, Edge 7+ | 11 | **72.7%** | Signal boost |
| UNDER, Stars (25+) | 44 | **65.9%** | Signal boost |
| V12 disagrees (V12=OVER when V9=UNDER) | 32 | **65.6%** | Already captured by consensus |
| B2B picks | 19 | **~79%** | Already captured by b2b_fatigue_under |
| OVER, Bench/Home | 81 | **58.0%** | Good volume |

**Combined filter impact:** 3 filters (quality < 85, bench UNDER, rel_edge >= 30%) → 195 picks at 56.4% HR (from 395 at 52.2%)

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

### Priority 0: Smart Filters + Pick Angles (Session 278) — NEXT
**Plan:** `docs/08-projects/current/multi-model-best-bets/01-NEXT-SESSION-PLAN.md`

**Part 1: Smart Filters (30 min, +4% HR)**
- [ ] Block quality < 85 picks (24% HR, 50 picks eliminated)
- [ ] Block bench UNDER (line < 12, 35.1% HR, 37 picks)
- [ ] Block relative edge >= 30% (49.7% HR, 175 picks)
- All in `ml/signals/aggregator.py`

**Part 2: Pick Angles System (1-2 hours)**
- [ ] Create `ml/signals/pick_angle_builder.py` — generates human-readable reasons per pick
- [ ] Each pick gets up to 4 angles: confidence context, direction+tier HR, cross-model consensus, signal-specific
- [ ] Warning angles for anti-patterns (bench UNDER, 0.92 confidence)
- [ ] Wire into `signal_best_bets_exporter.py` and JSON output
- [ ] Add `pick_angles ARRAY<STRING>` to BQ schema

**Part 3: Confidence Overhaul (future session)**
- [ ] Replace `75 + quality_bucket + std_bucket` with calibrated lookup
- [ ] Separate calibration for quantile models
- [ ] A/B shadow test before promoting

### Priority 1: Feb 19 Validation (Day-of)
- [ ] Run `/validate-daily` on Feb 19 morning
- [ ] Verify all 6 models generate predictions for 10 games
- [ ] Check `dual_agree` and `model_consensus_v9_v12` appear in signal evaluations
- [ ] Check `xm_*` cross-model subsets generate picks
- [ ] Verify `consensus_bonus` appears in signal-best-bets JSON
- [ ] Monitor first decay-detection Slack alert for new models

### Priority 2: Post-Break Monitoring (Feb 19-28)
- [ ] Track aggregator top-5 HR daily (target: 73.9%)
- [ ] Validate cross-model subset hit rates (need N >= 30)
- [ ] Compare retrained model HRs on live data
- [ ] Monitor confidence tier performance with new models

### Priority 3: Model-Specific Routing (after 14 days)
- [ ] V9 for OVER picks (stars, home, high edge)
- [ ] V12/Q45 for UNDER picks (role players, general)
- [ ] Team blocklist (MEM, MIA, PHX, LAC, HOU)
- [ ] Requires 50+ edge 3+ graded picks per model

### Completed Priorities
- ~~Multi-model best bets architecture~~ — **DONE Session 277** (3 layers deployed)
- ~~V12 signal data gap~~ — **DONE Session 277** (dual_agree/model_consensus now fire)
- ~~Model retrain sprint~~ — **DONE Session 276** (6 models, all gates passed)
- ~~Signal cleanup~~ — **DONE Session 275** (10 removed, aggregator 60.3% → 73.9%)
- ~~Health gate removal~~ — **DONE Session 270** (+$1,110 recovered)

---

## Key Session References

- **Session 277:** Multi-model best bets, 0.92 confidence bug found, model profiling
- **Session 276:** Model retrain sprint — 6 models trained, V12+quantile first ever
- **Session 275:** Signal cleanup (10 removed), combo registry (3 added)
- **Session 274:** 5 market-pattern UNDER signals
- **Session 273:** Model management overhaul

**Project docs:**
- **Multi-model architecture:** `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md`
- **Next session plan:** `docs/08-projects/current/multi-model-best-bets/01-NEXT-SESSION-PLAN.md`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **Steering playbook:** `docs/02-operations/runbooks/model-steering-playbook.md`
