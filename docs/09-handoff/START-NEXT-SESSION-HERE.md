# Start Your Next Session Here

**Updated:** 2026-02-15 (Session 261 complete)
**Status:** Fully deployed. catboost_v12 driving best bets. Historical replay complete.

---

## Quick Start

```bash
# 1. Read the latest handoff
cat docs/09-handoff/2026-02-15-SESSION-261-HANDOFF.md

# 2. Check pipeline health
/validate-daily

# 3. Check deployment drift
./bin/check-deployment-drift.sh --verbose
```

---

## Current State

- **Best bets model:** `catboost_v12` (56.0% edge 3+ HR, N=50, +6.9% ROI)
- **Env var:** `BEST_BETS_MODEL_ID=catboost_v12` on phase6-export + post-grading-export
- **Sessions 259+260+261:** All deployed (DDLs, Cloud Build, CF, backfills)
- **Signal health weighting:** LIVE (HOT 1.2x, COLD 0.5x)
- **Combo registry:** 7 combos, BQ-driven scoring
- **Games resume:** Feb 19 (All-Star break ends)

## Known Issues

- Combo registry has duplicate rows (14 → should be 7). Clean up with dedup query in handoff.
- latest.json not yet created — will generate on first game day (Feb 19)
- Need to verify V12 shadow model will produce predictions for Feb 19

---

## Strategic Priorities

### Priority 1: Pre-Game-Day (Before Feb 19)
- Verify V12 prediction pipeline active for Feb 19
- Clean combo registry duplicates
- Run validate-daily

### Priority 2: Build Automated Monitoring
- `model_performance_daily` BQ table
- Decay detection Cloud Function (WATCH 58%, ALERT 55%, BLOCK 52.4%)
- Slack alerting for model state changes
- `validate-daily` Phase 0.58

### Priority 3: Replay Tool
- Build `ml/analysis/replay_engine.py` + strategies + CLI
- Build `/replay` Claude skill
- Run V8 multi-season replay to calibrate thresholds
- Design documented in project doc

### Priority 4: Investigation
- Feb 2 week collapse root cause (see parallel chat prompt)
- Subset analysis: edge x confidence x prop type across models
- V12 confidence tier analysis (like V8's 88-90% gap)

---

## Parallel Chat Available

**Feb 2 Investigation:** `docs/09-handoff/session-prompts/SESSION-261-FEB2-INVESTIGATION.md`
- Why did picks crash the week of Feb 1-7?
- Root cause, counterfactual analysis, early warning indicators

---

**Handoffs:**
- Session 261: `docs/09-handoff/2026-02-15-SESSION-261-HANDOFF.md`
- Session 260: `docs/09-handoff/2026-02-15-SESSION-260-HANDOFF.md`
- Session 259: `docs/09-handoff/2026-02-15-SESSION-259-HANDOFF.md`
**Project docs:** `docs/08-projects/current/signal-discovery-framework/SESSION-261-HISTORICAL-REPLAY-AND-DECISION-FRAMEWORK.md`
