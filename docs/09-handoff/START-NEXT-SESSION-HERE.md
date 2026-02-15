# Start Your Next Session Here

**Updated:** 2026-02-15 (Session 268 — daily steering skill + backfill)
**Status:** All automation + monitoring features deployed. Games resume Feb 19. System ready.

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

- **Best bets model:** `catboost_v12` (56.0% edge 3+ HR, N=50, +6.9% ROI)
- **V12 confidence floor:** >= 0.90 (0.87 tier filtered — 41.7% HR)
- **Decay detection:** DEPLOYED + scheduled (11 AM ET daily). Slack alerts on state transitions + challenger outperformance + **cross-model crash detection**.
- **Meta-monitoring:** daily_health_check verifies model_performance_daily, signal_health_daily freshness + decay-detection scheduler recency
- **Directional concentration:** validate-daily Phase 0.57 flags >80% same direction on edge 3+ picks
- **model_performance_daily:** Auto-computed by post_grading_export after grading. 47 rows backfilled.
- **Replay engine:** BUILT — `ml/analysis/replay_cli.py` with 4 strategies + `--min-confidence` filter
- **Combo registry:** 7 combos (5 SYNERGISTIC, 2 ANTI_PATTERN). FROZEN — validate on post-Feb-19 data before changes.
- **Signal health weighting:** LIVE (HOT=1.2x, NORMAL=1.0x, COLD behavioral=0.5x, COLD model-dependent=0.0x)
- **Games resume:** Feb 19 (All-Star break ends)

## Known Issues

- ~~COLD model-dependent signals at 0.5x may be too generous~~ — **RESOLVED Session 264** (0.0x for model-dependent, 0.5x for behavioral)
- ~~Decay thresholds calibrated on one event~~ — **RESOLVED Session 265** (V8 multi-season replay: 0.13% false positive rate across 780 healthy game days, thresholds validated)
- ~~No meta-monitoring~~ — **RESOLVED Session 266** (Check 6 in daily_health_check CF)
- ~~Verify `google-cloud-scheduler`~~ — **RESOLVED Session 267** (added to daily_health_check requirements.txt)
- latest.json not yet created — will generate on first game day (Feb 19)
- ~~Signal annotator query broken~~ — **FIXED Session 268** (`player_name`, `team_abbr`, `position`, `line_value` columns didn't exist in `player_prop_predictions`)

---

## Strategic Priorities

### Priority 1: Feb 19 Readiness (Day-of)
- Run validate-daily on Feb 19 morning
- Verify V12 predictions generate (check BEST_BETS_MODEL_ID env var)
- Monitor first decay-detection Slack alert (should be "no alert needed" or INSUFFICIENT_DATA)
- Check `picks/{date}.json` has Best Bets subset (id=26) with signal tags

### Priority 2: Post-Break Validation (was Priority 4)
- Validate combo registry on post-Feb-19 out-of-sample data (still FROZEN)
- Calibrate INSUFFICIENT_DATA state for V12's lower pick volume
- Decide: switch BEST_BETS_MODEL_ID from V9 to V12?
- Monitor signal best bets performance (track daily for first week)

### Priority 3: Optional Enhancements
- Optional: `v1/systems/combo-registry.json` for combo explanations

### Completed Priorities
- ~~COLD model-dependent signals at 0.0x~~ — **DONE Session 264**
- ~~Surface moving_average/V8 baselines in daily dashboard~~ — **DONE Session 266**
- ~~Directional concentration monitor~~ — **DONE Session 266**
- ~~V8 multi-season replay~~ — **DONE Session 265** (0.13% FP rate, thresholds validated)
- ~~Cross-model crash detector~~ — **DONE Session 266**
- ~~Meta-monitoring~~ — **DONE Session 266**
- ~~google-cloud-scheduler dependency~~ — **DONE Session 267**
- ~~Backfill best bets subset~~ — **DONE Session 268** (Jan 9 - Feb 14 backfilled to `current_subset_picks` + `pick_signal_tags`)
- ~~Backfill signal-best-bets GCS files~~ — **DONE Session 268** (Jan 9 - Feb 14 JSON files to GCS)
- ~~Build signal-health export~~ — **DONE Session 267** (`v1/systems/signal-health.json`)
- ~~Build model-health export~~ — **DONE Session 267** (`v1/systems/model-health.json`)
- ~~Build daily steering skill~~ — **DONE Session 268** (`/daily-steering`)
- ~~Fix signal annotator query~~ — **DONE Session 268** (`query_predictions_with_supplements` was broken since Session 254)

---

## Replay Results (Session 262 Calibration)

| Strategy | HR | ROI | P&L |
|----------|-----|-----|------|
| **Threshold** | **69.1%** | **31.9%** | $3,400 |
| Conservative | 67.0% | 27.8% | $3,520 |
| Oracle | 62.9% | 20.0% | $3,680 |
| BestOfN | 59.5% | 13.6% | $2,360 |

Blocking bad days > picking best model. Thresholds **validated** across V8's 4-season history (Session 265): 0.13% false positive rate, 780 healthy game days.

---

**Handoffs:**
- Session 268: `/daily-steering` skill, signal annotator fix, best bets backfill
- Session 267: `docs/08-projects/current/signal-discovery-framework/SESSION-267-FORWARD-PLAN.md` **(comprehensive forward plan)**
- Session 265: `docs/08-projects/current/signal-discovery-framework/V8-MULTI-SEASON-REPLAY-RESULTS.md`
- Session 264: `docs/09-handoff/2026-02-15-SESSION-264-HANDOFF.md`
- Session 266: `docs/09-handoff/2026-02-15-SESSION-266-HANDOFF.md`
- Comprehensive review: `docs/09-handoff/SESSION-259-262-COMPREHENSIVE-REVIEW.md`
**Project docs:**
- **Steering playbook:** `docs/02-operations/runbooks/model-steering-playbook.md`
- **Forward plan:** `docs/08-projects/current/signal-discovery-framework/SESSION-267-FORWARD-PLAN.md`
- Replay framework: `docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md`
- Feb 2 crash: `docs/08-projects/current/signal-discovery-framework/SESSION-262-FEB2-CRASH-INVESTIGATION.md`
