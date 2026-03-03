# Model Management, Monitoring & Retraining Audit

> **Session:** 389 | **Date:** 2026-03-02
> **Goal:** Audit the full model lifecycle — fleet management, best bets selection, monitoring, and retraining — identify gaps, and fix the highest-priority ones.

---

## What's Working Well

### Model Fleet Management (7-Layer Defense)
The system has evolved into a genuinely robust 7-layer defense-in-depth:

1. **Pre-commit hooks** catch hardcoded model references before they ship
2. **Model registry** is the single source of truth with status tracking, GCS paths, SHA256 integrity
3. **Worker startup** validates model availability with lazy loading and version tracking
4. **Per-prediction quality gate** enforces zero-tolerance defaults (blocks ~60% of predictions intentionally)
5. **Aggregator sanity guard** blocks models with >95% same-direction predictions (caught XGBoost version mismatch in Session 378c)
6. **Model profiling** tracks per-model HR across 6 dimensions (direction, tier, line range, edge band, home/away, signal) on 14-day rolling windows
7. **Decay detection** state machine (HEALTHY → WATCH → DEGRADING → BLOCKED) runs daily at 11 AM ET with Slack alerts

The cascading deactivation tool (`deactivate_model.py`) is excellent — a single command disables across registry, predictions, signal picks, and logs an audit trail. This was born from Session 386's lesson about disabled models leaking into best bets.

### Best Bets Selection System
The selection pipeline is mature and battle-tested across 100+ sessions:

- **Edge-first architecture** (Session 297 pivot) — edge IS the signal, not a composite score. This was a breakthrough that lifted projected HR from 59.8% to 71%.
- **25+ negative filters** covering direction, tier, model family, opponent, line movement, signal density, and model-direction affinity. Each filter was validated with BQ data and has a documented HR and session origin.
- **Edge-tiered signal count** (Session 388) — SC >= 4 for edge < 7, SC >= 3 for edge >= 7. This fixed the SC=3 weakness at moderate edges (51.3% HR → 70.6% with SC=4).
- **3-layer disabled model defense** — registry check, exporter filter, published-picks tracking. No single point of failure.
- **Ultra bets** internal layer tracking at 75.8% HR (25-8), with a conservative public exposure gate (N >= 50, HR >= 80%).
- **Natural sizing** (Session 370) — no artificial cap on daily picks. Filters determine volume.

### Monitoring Infrastructure
Strong coverage across the full pipeline:

- `model_performance_daily` tracks rolling HR (7d/14d/30d) with best bets splits (bb_hr_14d/21d) and directional breakdowns
- `signal_health_daily` classifies each signal's regime (HOT/NORMAL/COLD) across 4 timeframes
- Signal firing canary (Session 387) detects dead/degrading signals by comparing recent vs historical firing rates
- Pipeline canary runs every 30 minutes validating all 6 phases
- Daily health check validates 7 dimensions (services, orchestrators, predictions, quota, exports, completions)

### Retraining Infrastructure
The tooling is comprehensive:

- `quick_retrain.py` (4,400+ lines) with 5 hard governance gates (HR >= 60%, N >= 25, vegas bias ± 1.5, tier bias ± 5, directional balance)
- Multi-family support from registry — train any family, `--all` for fleet-wide
- Auto-upload + auto-register with SHA256 integrity verification
- `retrain-reminder` CF fires Monday 9 AM with per-family urgency levels

---

## Gaps & Action Items

### P0: Best Bets HR Alert (no automated alerting on the metric that matters most)

**Problem:** `bb_hr_21d` is tracked in `model_performance_daily` but has NO automated threshold alert. Best bets could drop below breakeven for days without anyone knowing unless they manually query BQ.

**Fix:** Extend `decay_detection` CF to include a best bets HR check:
- Alert when `bb_hr_21d` < 55% for 2+ consecutive days (WATCH)
- Alert when `bb_hr_21d` < 52.4% for any day (CRITICAL — below breakeven)
- Include in existing Slack alert payload

**Files:** `orchestration/cloud_functions/decay_detection/main.py`
**Effort:** ~30 minutes

### P1: Auto-Disable BLOCKED Models

**Problem:** Decay detection identifies BLOCKED models (7d HR < 52.4%) but does NOT auto-disable them. They continue generating predictions and can leak through filter gaps into best bets. Requires manual `deactivate_model.py` intervention.

**Fix:** Add auto-disable logic to decay detection CF:
- When a model transitions to BLOCKED state, call deactivation logic
- Safeguards: never disable champion, require N >= 15 graded picks, allow 48h recovery window before permanent disable
- Log all auto-disables to audit trail
- Slack alert on every auto-disable action

**Files:** `orchestration/cloud_functions/decay_detection/main.py`, reuse logic from `bin/deactivate_model.py`
**Effort:** ~1-2 hours

### P2: Filter Effectiveness Audit

**Problem:** 25+ filters were validated at creation time (Sessions 278-388) but there's no ongoing validation that they're still working. Filters could be blocking profitable picks or passing losers as market conditions shift.

**Fix:** Run `bin/monitoring/filter_health_audit.py` and analyze results. Specifically check:
- Are any filters blocking picks that would have won? (false positive rate)
- Are any filters passing picks that consistently lose? (false negative rate)
- Have any filter thresholds drifted from their original validation?

**Files:** `bin/monitoring/filter_health_audit.py`, `ml/signals/aggregator.py`
**Effort:** ~1 hour (run + analyze + adjust if needed)

### P3: Retrain Staleness

**Problem:** Champion model was 27+ days stale as of Feb 27. Retraining is entirely manual — `retrain-reminder` alerts on Mondays but nobody executes. Shadow fleet is rebuilding but no systematic cadence is enforced.

**Fix (short-term):** Query current fleet staleness and identify which families need immediate retraining. Execute retrain for the most critical families.

**Fix (long-term):** Convert `retrain-reminder` from alert-only to alert+execute for URGENT families (15+ days stale). Start with a single family as pilot.

**Files:** `ml/experiments/quick_retrain.py`, `bin/retrain.sh`, `orchestration/cloud_functions/retrain_reminder/main.py`
**Effort:** Short-term ~30 minutes, long-term ~4 hours

### P4: Signal Deploy Gap

**Problem:** `prediction-coordinator` Cloud Build trigger watches `predictions/coordinator/**` but NOT `ml/signals/`. Signal changes require manual deploy.

**Fix:** Add `ml/signals/**` to the coordinator's Cloud Build trigger path. This ensures signal changes auto-deploy with the coordinator.

**Files:** `cloudbuild.yaml` (coordinator trigger section)
**Effort:** ~15 minutes

### P5: Best Bets HR in Frontend

**Problem:** `bb_hr_14d`/`bb_hr_21d` exists in `model_performance_daily` but isn't surfaced in any export. Frontend has no visibility into best bets performance.

**Fix:** Add best bets HR metrics to `signal-health.json` Phase 6 export.

**Files:** `data_processors/publishing/` (signal health exporter)
**Effort:** ~30 minutes

---

## Implementation Order

| # | Item | Priority | Effort | Dependencies |
|---|------|----------|--------|--------------|
| 1 | Best bets HR alert in decay detection | P0 | 30 min | None |
| 2 | Auto-disable BLOCKED models | P1 | 1-2 hrs | None |
| 3 | Filter effectiveness audit | P2 | 1 hr | None |
| 4 | Fleet staleness check + retrain | P3 | 30 min | None |
| 5 | Signal deploy gap | P4 | 15 min | None |
| 6 | Best bets HR in frontend export | P5 | 30 min | None |

Items 1-2 are the highest impact. Item 3 is diagnostic (may reveal further work). Items 4-6 are improvements.

---

## Success Criteria

- [x] Best bets HR has automated alerting with WATCH/CRITICAL thresholds
- [x] BLOCKED models are auto-disabled with safeguards
- [x] Filter stack validated — no filters blocking profitable picks or passing consistent losers
- [ ] Fleet staleness assessed — critical families retrained if needed
- [ ] Signal changes auto-deploy (or documented reason why not)

---

## Session 389 Progress

### P0: Best Bets HR Alerting — DONE
Added `get_aggregate_best_bets_hr()` and `build_best_bets_alert()` to `decay_detection/main.py`.
- Queries `signal_best_bets_picks` joined with `prediction_accuracy` for 21-day rolling HR
- Thresholds: WATCH < 55%, CRITICAL < 52.4% (breakeven)
- Includes OVER/UNDER directional splits in alert
- Min N=10 graded picks before alerting
- Added to local testing output (`__main__`)

### P1: Auto-Disable BLOCKED Models — DONE
Added `auto_disable_blocked_models()` to `decay_detection/main.py`.
- Disables models in registry (`enabled=FALSE, status='blocked'`) when decay state = BLOCKED
- **Safeguards:** Never disables champion model, requires N >= 15, checks if already disabled
- Skips during cross-model crash (market disruption, not model fault)
- Logs audit trail to `service_errors` table
- Sends Slack alert listing all auto-disabled models

### P2: Filter Effectiveness Audit — DONE (No Action Needed)
Ran `filter_health_audit.py` for 21 days (Feb 9 - Mar 1). Results:
- `bench_under`: 35.1% → 39.0% (+3.9pp, N=205) — OK
- `star_under`: 51.3% → 50.4% (-0.9pp, N=230) — OK
- `starter_v12_under`: 46.7% → 40.8% (-5.9pp, N=125) — OK (working better)
- **DRIFT:** `under_edge_7plus_non_v12`: 40.7% → 52.4% (+11.7pp, N=42) — at breakeven but small N
- **DRIFT:** `v9_under_5plus`: 30.7% → 44.4% (+13.7pp, N=36) — improved but still below breakeven
- **Verdict:** No filters are blocking profitable picks. Both drifted filters are in the coin-flip zone (52.4%, 44.4%) with small N. No changes needed.

### P4: Signal Auto-Deploy — DOCUMENTED
Cloud Build trigger for `deploy-prediction-coordinator` uses 2nd-gen GitHub connection — cannot update via gcloud CLI. Must be done in GCP Console:
1. Go to Cloud Build > Triggers > `deploy-prediction-coordinator` > Edit
2. Add `ml/signals/**` to includedFiles list
3. Save
