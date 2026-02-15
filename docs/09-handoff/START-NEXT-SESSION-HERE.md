# Start Your Next Session Here

**Updated:** 2026-02-15 (Session 266 complete)
**Status:** All automation + monitoring features deployed. Games resume Feb 19. System ready.

---

## Quick Start

```bash
# 1. Read the latest handoff
cat docs/09-handoff/SESSION-259-262-COMPREHENSIVE-REVIEW.md

# 2. Check pipeline health
/validate-daily

# 3. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 4. Replay last 30 days
/replay
```

---

## Current State

- **Best bets model:** `catboost_v12` (56.0% edge 3+ HR, N=50, +6.9% ROI)
- **V12 confidence floor:** >= 0.90 (0.87 tier filtered — 41.7% HR)
- **Decay detection:** DEPLOYED + scheduled (11 AM ET daily). Slack alerts on state transitions + challenger outperformance + **cross-model crash detection**.
- **Meta-monitoring:** daily_health_check verifies model_performance_daily, signal_health_daily freshness + decay-detection scheduler recency
- **Directional concentration:** validate-daily Phase 0.57 flags >80% same direction on edge 3+ picks
- **model_performance_daily:** Auto-computed by post_grading_export after grading. 47 rows backfilled.
- **Replay engine:** BUILT — `ml/analysis/replay_cli.py` with 4 strategies + `--min-confidence` filter
- **Combo registry:** 7 combos (5 SYNERGISTIC, 2 ANTI_PATTERN). FROZEN — validate on post-Feb-19 data before changes.
- **Signal health weighting:** LIVE (HOT=1.2x, NORMAL=1.0x, COLD=0.5x)
- **Games resume:** Feb 19 (All-Star break ends)

## Known Issues

- **COLD model-dependent signals at 0.5x may be too generous** — Feb 2 data shows 5.9-8.0% HR. Consider 0.0x for model-dependent, keep 0.5x for behavioral.
- **Decay thresholds calibrated on one event** — V8 multi-season replay needed to validate 58/55/52.4
- ~~No meta-monitoring~~ — **RESOLVED Session 266** (Check 6 in daily_health_check CF)
- **Verify `google-cloud-scheduler`** in daily_health_check requirements.txt (meta-monitoring scheduler check needs it)
- latest.json not yet created — will generate on first game day (Feb 19)

---

## Strategic Priorities

### Priority 1: Feb 19 Readiness (Day-of)
- Run validate-daily on Feb 19 morning
- Verify V12 predictions generate
- Monitor first decay-detection Slack alert (should be "no alert needed" or INSUFFICIENT_DATA)

### Priority 2: Signal Hardening
- COLD model-dependent signals at 0.0x (add `is_model_dependent` flag to signal health)
- ~~Surface moving_average/V8 baselines in daily dashboard~~ — **DONE Session 266** (Phase 0.58 extension)
- ~~Directional concentration monitor~~ — **DONE Session 266** (Phase 0.57)

### Priority 3: Threshold Validation
- V8 multi-season replay to validate 58/55/52.4 thresholds across 4 seasons
- ~~Cross-model crash detector~~ — **DONE Session 266** (decay_detection CF)

### Priority 4: Review Feedback Items
- Freeze combo registry — validate on post-Feb-19 out-of-sample data before adding combos
- Calibrate INSUFFICIENT_DATA state for V12's lower pick volume
- ~~Add meta-monitoring~~ — **DONE Session 266** (daily_health_check Check 6)

---

## Replay Results (Session 262 Calibration)

| Strategy | HR | ROI | P&L |
|----------|-----|-----|------|
| **Threshold** | **69.1%** | **31.9%** | $3,400 |
| Conservative | 67.0% | 27.8% | $3,520 |
| Oracle | 62.9% | 20.0% | $3,680 |
| BestOfN | 59.5% | 13.6% | $2,360 |

Blocking bad days > picking best model. Standard thresholds are well-calibrated (pending V8 validation).

---

**Handoffs:**
- Session 266: `docs/09-handoff/2026-02-15-SESSION-266-HANDOFF.md`
- Comprehensive review: `docs/09-handoff/SESSION-259-262-COMPREHENSIVE-REVIEW.md`
- Session 262: `docs/09-handoff/2026-02-15-SESSION-262-HANDOFF.md`
**Project docs:**
- Replay framework: `docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md`
- Feb 2 crash: `docs/08-projects/current/signal-discovery-framework/SESSION-262-FEB2-CRASH-INVESTIGATION.md`
