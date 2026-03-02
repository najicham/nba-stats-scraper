# Session 386 Recommendations — March 2, 2026

For the next session to review. Prioritized by impact. Based on comprehensive validation, fleet analysis, and fresh retrains completed this session.

---

## Current State Summary

- **Fleet:** 36 models tracked, 21 BLOCKED, 5 actively producing, 8 freshly registered (not yet producing)
- **Production champion (`catboost_v12`):** BLOCKED at 47% 7d HR / 51.8% 14d HR — losing money
- **Best bets (14d):** 15-10 (60.0% HR) on 27 picks. Very low volume (2.5 picks/day avg)
- **Direction split:** UNDER 66.7% >> OVER 53.8%. OVER collapse continues.
- **2 new shadow models deployed this session:** VW015 (76.9% backtest) and NOVEG (68.8% backtest)

---

## Priority 1: Fleet Triage (HIGH IMPACT)

**Problem:** Dead models polluting best bets selection. The champion is BLOCKED. Multiple models with <45% HR still have active predictions competing for per-player selection.

**Action — Disable these BLOCKED models:**

| Model | HR 14d | N | Why |
|-------|--------|---|-----|
| `catboost_v12_noveg_q43_train0104_0215` | 15.9% | 63 | Catastrophic. Worst in fleet. |
| `catboost_v12_noveg_q43_train1102_0125` | 40.4% | 89 | Dead. 35 days stale. |
| `catboost_v12_noveg_q45_train1102_0125` | 41.0% | 78 | Dead. 35 days stale. |
| `catboost_v12_noveg_mae_train0104_0215` | 42.3% | 26 | Below breakeven. |
| `catboost_v12_noveg_q55_tw_train0105_0215` | 42.9% | 7 | BLOCKED. |
| `catboost_v9_q43_train1102_0131` | 0 picks | 0 | Zombie. 35 days stale. |
| `catboost_v9_q45_train1102_0131` | 0 picks | 0 | Zombie. 35 days stale. |

**Commands (dry-run first):**
```bash
python bin/deactivate_model.py catboost_v12_noveg_q43_train0104_0215 --dry-run
python bin/deactivate_model.py catboost_v12_noveg_q43_train1102_0125 --dry-run
python bin/deactivate_model.py catboost_v12_noveg_q45_train1102_0125 --dry-run
# ... then remove --dry-run to execute
```

**Important:** Disabling in registry alone does NOT remove active predictions. Must also deactivate predictions (the script handles both). The disabled model filtering code deployed in commit `5eccddbe` provides defense-in-depth.

---

## Priority 2: Champion Promotion Evaluation

**Problem:** No model currently qualifies for champion status (need N>=25 with HR>=60%).

**Best candidates by live performance:**

| Model | HR 7d | N 7d | HR 14d | N 14d | State | Notes |
|-------|-------|------|--------|-------|-------|-------|
| `catboost_v12_q43_train1225_0205_feb22` | 83.3% | 6 | 50.0% | 20 | HEALTHY | Divergent 7d vs 14d — hot streak? |
| `lgbm_v12_noveg_train1201_0209` | 71.4% | 7 | 71.4% | 7 | HEALTHY | Consistent but tiny N |
| `catboost_v12_noveg_60d_vw025_train1222_0219` | 66.7% | 9 | 66.7% | 9 | HEALTHY | Our 60d window config |
| `catboost_v12_noveg_train0110_0220` | 58.3% | 12 | 58.3% | 12 | HEALTHY | Largest N among healthy models |

**New models (just deployed, no live data yet):**

| Model | Backtest HR 3+ | OVER | UNDER | Config |
|-------|---------------|------|-------|--------|
| `catboost_v12_train1228_0222` | 76.9% (n=13) | 100% | 62.5% | v12 + vegas=0.15, 56d window |
| `catboost_v12_noveg_train1228_0222` | 68.8% (n=16) | 71.4% | 66.7% | v12_noveg, 56d window |

**Recommendation:** Wait 2-3 weeks for N to reach 25+. The multi-model system IS working — shadow models sourced 100% HR picks while the champion sourced 25% HR picks in the last 14 days. HR-weighted selection (Session 365) naturally demotes underperforming models.

---

## Priority 3: Fix Failing Scheduler Jobs

3 jobs failing continuously:

| Job | Error | Frequency | Fix |
|-----|-------|-----------|-----|
| `nba-env-var-check-prod` | UNAVAILABLE | **Every 5 min** | Pause or delete — `/internal/check-env` endpoint doesn't exist on prediction-worker. Generating constant noise. |
| `self-heal-predictions` | DEADLINE_EXCEEDED | Daily | Increase `attemptDeadline` or redeploy the service |
| `monthly-retrain-job` | INTERNAL | Monthly (Mar 1) | Check service logs. Just fired and failed. |

**Quick fix:**
```bash
# Stop the constant noise
gcloud scheduler jobs pause nba-env-var-check-prod --location=us-west2 --project=nba-props-platform

# Check self-heal service
gcloud run services describe self-heal-predictions --region=us-west2 --project=nba-props-platform --format="value(status.url)"
```

---

## Priority 4: Signal Health Review

**Signals at or below breakeven (14d):**

| Signal | HR 14d | N 14d | Season HR | Concern |
|--------|--------|-------|-----------|---------|
| `rest_advantage_2d` | 25.0% | 4 | 50.0% | Small N but crashing. Was capped at week 15. |
| `high_edge` | 50.0% | 62 | 52.7% | At breakeven on large N. Core signal. |
| `edge_spread_optimal` | 50.0% | 62 | 52.7% | Same as high_edge — they overlap. |
| `bench_under` | 53.2% | 62 | 56.5% | WATCH status. Declining from season avg. |
| `book_disagreement` | 58.9% | 73 | 58.9% | WATCH. 7d down to 51.9%. |

**4 signals missing from `signal_health_daily`:**
- `fast_pace_over`, `line_rising_over`, `model_health`, `self_creation_over`
- These are listed as active in CLAUDE.md but not appearing in the health table
- **Investigate:** Are they not being tracked, not firing, or just not in this table?

**Recommendation:**
- Re-evaluate `rest_advantage_2d` — may need disabling if it continues below breakeven
- `high_edge` and `edge_spread_optimal` at 50% on N=62 is concerning — these are foundational signals. If they drop below 50% next week, investigate
- Investigate the 4 missing signals to ensure they're actually firing

---

## Priority 5: Best Bets Deep Dive

### Performance by Model Source (14d)

| Model | Picks | HR | Assessment |
|-------|-------|----|------------|
| `catboost_v12` (champion) | 4 | **25%** | Actively hurting. BLOCKED. |
| `v9_low_vegas_train0106_0205` | 3 | 100% | Top contributor |
| `v12_noveg_train0110_0220` | 2 | 100% | Strong |
| `v12_noveg_q45_train1102_0125` | 2 | 100% | Good picks despite BLOCKED status |
| `v12_noveg_q43_train0104_0215` | 4 | 50% | Mixed |

**Key insight:** Shadow models are carrying best bets while the champion drags. The filter stack + HR-weighted selection is compensating but not fully preventing champion picks from entering.

### Edge Band Anomaly

| Edge Band | Picks | HR | Note |
|-----------|-------|----|------|
| 7+ | 1 | 100% | Rare but profitable |
| 5-6.9 | 11 | 63.6% | **Carrying performance** |
| 3-4.9 | 4 | 25.0% | Worst band (small N) |
| <3 | 9 | 66.7% | **Should not exist** — edge floor is 3.0 |

**The <3 edge band having 9 picks is unexpected.** These may come from signal-density bypass (edge >=7 bypass removed in Session 352, but could there be another path?) or multi-model consensus scoring. Investigate how sub-3.0 edge picks enter best bets.

### Direction Split

| Direction | Picks | HR |
|-----------|-------|----|
| OVER | 13 | 53.8% |
| UNDER | 12 | 66.7% |

OVER at 53.8% is barely above breakeven. The Feb OVER collapse pattern persists. Consider whether additional OVER-side restrictions are warranted, or if the new models' training window (through Feb 22) will naturally recalibrate.

---

## Priority 6: Deploy Grading Service

`nba-grading-service` is 1 commit behind (profiling feature from Session 384). Non-critical since profiling is observation-only, but should be deployed to clear drift.

```bash
./bin/deploy-service.sh nba-grading-service
```

---

## Priority 7: Verify Session 386 Prevention System

The disabled model filtering and pick events code deployed in `5eccddbe` hasn't been exercised in production yet.

**On next game day, verify:**

1. `system_id` populated in `best_bets_published_picks`
2. `best_bets_pick_events` has rows for any drops
3. Cloud Run logs show "Filtered N picks from disabled models" if applicable
4. Published-only picks still get graded after games finish

---

## Items to Monitor

| Item | Current | Threshold to Act | Timeline |
|------|---------|-------------------|----------|
| New shadow models (VW015, NOVEG) | Just deployed, no data | N>=25 edge 3+ graded → promote candidate | ~2-3 weeks |
| `lgbm_v12_noveg_train1201_0209` | 71.4% HR, N=7 | N>=25 and HR>=60% → promote candidate | ~2 weeks |
| `book_disagreement` signal | 58.9% WATCH, 7d=51.9% | HR<50% on N>=30 → disable | ~1 week |
| `bench_under` signal | 53.2% WATCH | HR<50% on N>=30 → disable | ~1 week |
| OVER performance | 53.8% HR (14d) | Sustained <52.4% → OVER block expansion | Ongoing |
| Best bets volume | 2.5 picks/day | <1 pick/day sustained → loosen filters | Ongoing |
| Edge <3 picks in best bets | 9 picks (unexpected) | Any → investigate entry path | Next session |

---

## Quick Action Checklist

```
[ ] Deploy grading service: ./bin/deploy-service.sh nba-grading-service
[ ] Disable 7 dead models: bin/deactivate_model.py (dry-run first)
[ ] Pause nba-env-var-check-prod scheduler job
[ ] Investigate 4 missing signals in signal_health_daily
[ ] Investigate edge <3 picks entering best bets
[ ] Check self-heal-predictions timeout
[ ] Verify Session 386 prevention system on next game day
```
