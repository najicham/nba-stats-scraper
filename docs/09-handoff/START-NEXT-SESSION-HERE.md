# Start Your Next Session Here

**Updated:** 2026-02-17 (Session 284 — Production Implementation of Replay Findings)
**Status:** ALL 6 replay findings deployed. Player blacklist, avoid-familiar, rel_edge removal, high-conviction angle, 42-day rolling window, 7-day cadence, V12 quantile edge>=4 — all LIVE in code. Ready for Feb 19 games.

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

### Session 284 — Production Implementation (DEPLOYED)

**Implemented from replay findings:**

| Change | P&L Impact | Status |
|--------|-----------|--------|
| Player blacklist (<40% HR, 8+ picks) | +$10,450 | DEPLOYED in aggregator |
| Avoid-familiar filter (6+ games vs opp) | +$1,780 | DEPLOYED in aggregator |
| Remove rel_edge>=30% filter | Positive (was blocking 62.8% HR) | DEPLOYED in aggregator |
| High-conviction edge>=5 angle | Labeling improvement | DEPLOYED in pick angles |
| `ALGORITHM_VERSION` | `v284_blacklist_familiar_reledge` | DEPLOYED |

**New files:**
- `ml/signals/player_blacklist.py` — `compute_player_blacklist()` queries season-to-date per-player stats
- `tests/unit/signals/test_player_blacklist.py` — 23 tests covering all new features

**Modified files:**
- `ml/signals/aggregator.py` — blacklist + avoid-familiar filters, rel_edge removal
- `data_processors/publishing/signal_best_bets_exporter.py` — blacklist + games_vs_opponent enrichment, JSON metadata
- `ml/signals/pick_angle_builder.py` — high-conviction edge>=5 angle
- `ml/signals/__init__.py` — new export

### Also Deployed (Commit 3)

| Change | P&L Impact | Status |
|--------|-----------|--------|
| 42-day rolling training window | +$5,370 | DEPLOYED in `bin/retrain.sh` |
| 7-day retrain cadence | +$7,670 | DEPLOYED in `retrain_reminder/main.py` |
| V12 quantile min edge to 4 | HR +5.1pp | DEPLOYED in `catboost_monthly.py` |

### Season Replay Summary (Sessions 280-283)

**Best config: Cad7 + Roll42 + BL40 + AvoidFam = +$92,470 combined P&L at 60.3% HR**

Full findings: `docs/08-projects/current/season-replay-analysis/00-FINDINGS.md`

### Pick Provenance (Session 279)
- **qualifying_subsets:** each best bet shows which Level 1/2 subsets it appeared in
- **algorithm_version:** tracking tag for scoring formula changes

### Smart Filters + Pick Angles (Session 278)
- **2 smart filters in aggregator:** feature quality floor (<85), bench UNDER block (line<12)
- **Removed:** relative edge cap (>=30%) — was blocking profitable picks
- **Added:** avoid-familiar (6+ games vs opponent), player blacklist (<40% HR)
- **Pick angles system:** up to 5 human-readable reasoning strings per pick, including high-conviction edge>=5

### Multi-Model Best Bets (Session 277)
- **3-layer architecture DEPLOYED:** per-model subsets, cross-model observation subsets, consensus scoring
- **V12 signals UNLOCKED:** `dual_agree` and `model_consensus_v9_v12` now fire in production

### Model State (Session 276 — Retrain Sprint)
- **V9 champion:** `catboost_v9_train1102_0205` — FRESH
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
- feature_3_value (points std dev) is mostly <5 in 2025-26 — may be a data/scale issue
- Phase B dimension features have narrow distributions — need investigation

---

## Strategic Priorities

### Priority 0: Replay Implementations — ALL DONE
- [x] **Player blacklist** — `ml/signals/player_blacklist.py` + aggregator pre-filter
- [x] **Avoid-familiar filter** — 6+ games vs opponent → skip
- [x] **Remove rel_edge>=30% filter** — was blocking 62.8% HR picks
- [x] **High-conviction edge>=5 angle** — pick angle builder
- [x] **42-day rolling training window** — `bin/retrain.sh` ROLLING_WINDOW_DAYS=42
- [x] **7-day retrain cadence** — `retrain_reminder` thresholds 7/10/14
- [x] **V12 quantile min edge to 4** — `catboost_monthly.py`

### Priority 1: Feb 19 Validation (Day-of)
- [ ] Run `/validate-daily` on Feb 19 morning
- [ ] Verify all 6 models generate predictions for 10 games
- [ ] Verify `player_blacklist` field appears in signal-best-bets JSON
- [ ] Check `dual_agree` and `model_consensus_v9_v12` appear in signal evaluations
- [ ] Check `xm_*` cross-model subsets generate picks
- [ ] Verify `consensus_bonus` and `pick_angles` in JSON output
- [ ] Monitor first decay-detection Slack alert for new models

### Priority 2: Post-Break Monitoring (Feb 19-28)
- [ ] Track aggregator top-5 HR daily (target: 62%+ with new filters)
- [ ] Validate cross-model subset hit rates (need N >= 30)
- [ ] Monitor blacklisted players — are they truly performing below 40%?
- [ ] Check avoid-familiar filter is blocking expected players
- [ ] Compare retrained model HRs on live data

### Priority 3: Further Experiments (Next Session)
- [ ] **Adaptive direction gating** — suppress OVER-only signals when rolling HR < 50%
- [ ] **Min training days sweep** — currently 28d minimum, test 14d/21d
- [ ] **Per-model edge thresholds** — V12 Q43 at edge>=4, V9 MAE at edge>=5
- [ ] **Blacklist within consensus only** — more targeted: only blacklist in xm_consensus_3plus
- [ ] **High conviction tier** — Surface edge>=5 picks separately in API
- [ ] Investigate feature_3_value (pts_std) narrow distribution

### Completed Priorities
- ~~ALL replay findings~~ — **DONE Session 284** (blacklist, avoid-familiar, rel_edge removal, rolling window, 7d cadence, V12 edge>=4)
- ~~Parameter sweeps + combo optimization~~ — **DONE Session 283**
- ~~Experiment filters + cross-season validation~~ — **DONE Session 282**
- ~~Adaptive mode + rolling training~~ — **DONE Session 281**
- ~~Full season replay~~ — **DONE Session 280**
- ~~Pick provenance + hierarchical layers~~ — **DONE Session 279**
- ~~Smart filters + pick angles~~ — **DONE Session 278**
- ~~Multi-model best bets architecture~~ — **DONE Session 277**
- ~~Model retrain sprint~~ — **DONE Session 276**
- ~~Signal cleanup~~ — **DONE Session 275**

---

## Key Session References

- **Session 284:** Production implementation — blacklist, avoid-familiar, rel_edge removal, high-conviction angle. Handoff: `docs/09-handoff/2026-02-17-SESSION-284-HANDOFF.md`
- **Session 283:** 40 experiments — Cad7+Roll42+BL40+AvoidFam = +$92,470, 60.3% HR
- **Session 282:** Experiment filters — player blacklist (+$10,450), 5 experiments rejected
- **Session 281:** Adaptive mode + rolling training — rolling 56d is +$9,550
- **Session 280:** Full season replay — 6 models, 2 seasons, V9 Q43 champion
- **Session 279:** Pick provenance (qualifying_subsets, algorithm_version)
- **Session 278:** Smart filters (3 poison blocks), pick angles system
- **Session 277:** Multi-model best bets, V12 signal data gap fix
- **Session 276:** Model retrain sprint — 6 models trained

**Project docs:**
- **Season replay findings:** `docs/08-projects/current/season-replay-analysis/00-FINDINGS.md`
- **Multi-model architecture:** `docs/08-projects/current/multi-model-best-bets/00-ARCHITECTURE.md`
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **Steering playbook:** `docs/02-operations/runbooks/model-steering-playbook.md`
