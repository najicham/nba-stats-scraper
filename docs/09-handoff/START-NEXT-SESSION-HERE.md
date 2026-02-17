# Start Your Next Session Here

**Updated:** 2026-02-16 (Session 275 — Signal cleanup + combo registry update)
**Status:** Signal system optimized (18 signals, 73.9% aggregator HR). All services deployed at `f4fcf8bd`. Both models BLOCKED — retrain URGENT before Feb 19. Games resume Feb 19.

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

### Signal System (Session 275)
- **18 active signals** (10 removed — 4 below breakeven, 6 never-fire)
- **Aggregator HR: 73.9%** (up from 60.3% pre-cleanup)
- **Direction balance fixed:** 5 OVER + 6 UNDER + 7 BOTH (was 5 OVER, 0 UNDER)
- **Top standalone signal:** `bench_under` (76.9% HR, N=156, PRODUCTION)
- **Combo registry:** 10 entries (8 SYNERGISTIC, 2 ANTI_PATTERN) — 3 new UNDER entries added
- **Biggest removal impact:** `hot_streak_2` (N=416, 45.8% HR) — eliminated largest false qualifier

### Model State
- **Best bets model:** `catboost_v12` (56.0% edge 3+ HR, N=50, +6.9% ROI)
- **V12 confidence floor:** >= 0.90 (0.87 tier filtered — 41.7% HR)
- **V9 champion:** DECAYING (39.9% HR, 39+ days stale — URGENT retrain)

### Monitoring & Automation
- **Decay detection:** DEPLOYED (11 AM ET daily, Slack alerts on state transitions)
- **Meta-monitoring:** daily_health_check verifies freshness + scheduler recency
- **Directional concentration:** validate-daily Phase 0.57 flags >80% same direction
- **model_performance_daily:** Auto-computed by post_grading_export after grading
- **Health gate:** REMOVED (Session 270). 2-signal minimum provides quality filtering.
- **Signal health weighting:** LIVE (HOT=1.2x, NORMAL=1.0x, COLD behavioral=0.5x, COLD model-dependent=0.0x)
- **Retrain reminders:** Weekly Mon 9 AM ET, Slack + SMS when model >= 10 days old

### Infrastructure
- **Model management:** DB-driven loading, auto-register from training, multi-family retrain (Session 273)
- **Replay engine:** `ml/analysis/replay_cli.py` + `ml/analysis/steering_replay.py`
- **Games resume:** Feb 19 (All-Star break ends)

---

## Known Issues

- latest.json not yet created — will generate on first game day (Feb 19)
- V9 champion model stale (39+ days) — retrain URGENT
- `dual_agree` and `model_consensus_v9_v12` at 45.5% HR (W4 only data) — monitor post-Feb-19

---

## Strategic Priorities

### Priority 0: Retrain Models (URGENT — do during All-Star break)
Both models BLOCKED. All-Star break (Feb 16-18) is ideal window before Feb 19 games.
- [ ] V9: 40 days stale, 44.1% 7d HR — `./bin/retrain.sh --promote --train-end 2026-02-12`
- [ ] V12: 17 days stale, 48.3% 7d HR — `./bin/retrain.sh --family v12_noveg_mae --train-end 2026-02-12`
- Both must pass governance gates. Walkforward: 14d cadence = 68.8% HR, +31.3% ROI.

### Priority 1: Feb 19 Readiness (Day-of)
Blocked by: retrain completion + deployment
- [ ] Run `/validate-daily` on Feb 19 morning
- [ ] Verify predictions generate for all 10 games
- [ ] Check signal tags do NOT include removed signals (hot_streak_2, etc.)
- [ ] Verify `bench_under` appears in pick_signal_tags
- [ ] Check `picks/{date}.json` has Best Bets subset (id=26) with signal tags
- [ ] Monitor first decay-detection Slack alert
- [ ] Verify latest.json gets created

### Priority 2: Post-Break Signal Monitoring (Feb 19-28)
First week of live data after signal cleanup.
- [ ] Track aggregator top-5 HR daily (target: 73.9% from backtest)
- [ ] Validate `bench_under` standalone HR (backtest: 76.9%)
- [ ] Confirm UNDER signals appear in top-5 picks (new direction coverage)
- [ ] Check signal tag distribution (no removed signals)
- [ ] Monitor signal health regime transitions (HOT/COLD/NORMAL)

### Priority 3: Model Selection Decision (after 1 week)
- [ ] Decide: switch BEST_BETS_MODEL_ID from V9 to V12?
- [ ] Compare retrained model HRs on live data
- [ ] Calibrate INSUFFICIENT_DATA state for V12's lower pick volume

### Priority 4: Re-evaluate WATCH Signals (after 2+ weeks)
6 signals in WATCH: self_creator_under (61.8%), volatile_under (60.0%), high_usage_under (58.7%), blowout_recovery (56.9%), minutes_surge (53.7%), dual_agree/model_consensus (45.5%)
- [ ] Promote to CONDITIONAL if stable above 60%
- [ ] Remove if consistently below breakeven
- [ ] dual_agree and model_consensus need more sample (W4 only)

### Priority 5: Multi-Model Aggregation (longer term)
- [ ] Route UNDER signals to Q43/Q45 for model-aware scoring
- [ ] Per-family signal profiles (option C from Session 273)
- [ ] Requires Q43/Q45 retrain first
- [ ] `v1/systems/combo-registry.json` API endpoint

### Completed Priorities
- ~~Signal system OVER bias~~ — **DONE Session 274-275** (6 UNDER signals added)
- ~~Remove underperforming signals~~ — **DONE Session 275** (10 removed, aggregator 60.3% → 73.9%)
- ~~Health gate policy decision~~ — **DONE Session 270** (gate removed, +$1,110 recovered)
- ~~COLD model-dependent signals at 0.0x~~ — **DONE Session 264**
- ~~Model management overhaul~~ — **DONE Session 273** (DB-driven loading, auto-register)
- ~~Market pattern discovery~~ — **DONE Session 274** (5 cross-season validated patterns)
- ~~Meta-monitoring~~ — **DONE Session 266**
- ~~Cross-model crash detector~~ — **DONE Session 266**
- ~~Daily steering skill~~ — **DONE Session 268**
- ~~Signal annotator query fix~~ — **DONE Session 268**
- ~~Best bets backfill~~ — **DONE Session 268** (Jan 9 - Feb 14)

---

## Replay Results

### Steering Replay — Full Signal Pipeline (Session 269)

| Strategy | Picks | W-L | HR% | P&L | ROI |
|----------|-------|-----|-----|-----|-----|
| **Steering (production)** | 93 | 53-40 | 57.0% | **$+900** | +8.8% |
| **No health gate** | 165 | 96-69 | 58.2% | **$+2,010** | +11.1% |
| **V12 only** | 36 | 21-15 | 58.3% | **$+450** | +11.4% |

### Post-Cleanup Backtest (Session 275)

| Window | Picks | HR | ROI |
|--------|-------|----|-----|
| W2 (Jan 5-18) | 50 | **80.0%** | +52.7% |
| W3 (Jan 19-31) | 65 | **78.5%** | +49.8% |
| W4 (Feb 1-13) | 57 | **63.2%** | +20.6% |
| **AVG** | — | **73.9%** | — |

---

## Key Session References

- **Session 275:** Signal cleanup (10 removed), combo registry (3 added), backtest validation
- **Session 274:** 5 market-pattern UNDER signals implemented + backtested
- **Session 273:** Model management overhaul (DB-driven loading, multi-family retrain)
- **Session 270:** Health gate removed from signal best bets
- **Session 268:** `/daily-steering` skill, signal annotator fix, best bets backfill
- **Session 267:** `docs/08-projects/current/signal-discovery-framework/SESSION-267-FORWARD-PLAN.md`
- **Comprehensive review:** `docs/09-handoff/SESSION-259-262-COMPREHENSIVE-REVIEW.md`

**Project docs:**
- **Signal inventory:** `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md`
- **Steering playbook:** `docs/02-operations/runbooks/model-steering-playbook.md`
- **Forward plan:** `docs/08-projects/current/signal-discovery-framework/SESSION-267-FORWARD-PLAN.md`
