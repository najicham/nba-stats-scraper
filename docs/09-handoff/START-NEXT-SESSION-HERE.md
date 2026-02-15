# Start Your Next Session Here

**Updated:** 2026-02-15 (Session 262 complete)
**Status:** All priorities built. V12 confidence filter, replay engine, decay monitoring all ready. Push to deploy.

---

## Quick Start

```bash
# 1. Read the latest handoff
cat docs/09-handoff/2026-02-15-SESSION-262-HANDOFF.md

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
- **Replay engine:** BUILT — `ml/analysis/replay_cli.py` with 4 strategies
- **model_performance_daily:** BUILT + backfilled (47 rows, Nov 2025 – Feb 2026)
- **Decay detection CF:** BUILT — needs deploy trigger after push
- **Combo registry:** 7 combos (deduplicated)
- **Games resume:** Feb 19 (All-Star break ends)
- **V12 pipeline:** Verified ready for Feb 19

## Known Issues

- Decay detection CF not yet deployed (needs Cloud Build trigger + Scheduler job)
- model_performance_daily needs to be wired into post-grading pipeline for auto-population
- latest.json not yet created — will generate on first game day (Feb 19)

---

## Strategic Priorities

### Priority 1: Deploy + Verify (Before Feb 19)
- Push to main (auto-deploys Cloud Run services with confidence filter)
- Create Cloud Build trigger for decay-detection CF (see handoff for command)
- Create Cloud Scheduler job for decay-detection
- Run validate-daily on Feb 19

### Priority 2: Wire Daily Automation
- Add model_performance_daily compute to post-grading pipeline
- Wire decay_detection CF to model_performance_daily compute trigger
- Add challenger-beats-champion alerts

### Priority 3: Deeper Analysis
- Investigate Feb 2 crash (see `docs/09-handoff/session-prompts/SESSION-261-FEB2-INVESTIGATION.md`)
- Consider COLD model-dependent signals at 0.0x (investigation suggests warranted)
- Directional concentration monitor (>80% same direction = flag)

---

## Replay Results (Session 262 Calibration)

Threshold strategy (58/55/52.4) **dominates** on ROI:

| Strategy | HR | ROI | P&L |
|----------|-----|-----|------|
| **Threshold** | **69.1%** | **31.9%** | $3,400 |
| Conservative | 67.0% | 27.8% | $3,520 |
| Oracle | 62.9% | 20.0% | $3,680 |
| BestOfN | 59.5% | 13.6% | $2,360 |

Blocking bad days > picking best model. Standard thresholds are well-calibrated.

---

**Handoffs:**
- Session 262: `docs/09-handoff/2026-02-15-SESSION-262-HANDOFF.md`
- Session 261: `docs/09-handoff/2026-02-15-SESSION-261-HANDOFF.md`
**Project docs:**
- Replay framework: `docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md`
