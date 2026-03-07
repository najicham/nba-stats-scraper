# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 429 — System Improvement Audit)
**Status:** NBA v429 deployed. Infrastructure hardened. MLB fully deployed (schedulers paused until Mar 24).

## What Happened This Session (429)

### Infrastructure Fixes (Phase A — ALL DONE)
- **Deactivated 3 BLOCKED models:** xgb_v12_noveg_train0107_0219, catboost_v12_noveg_train0107_0219, catboost_v16_noveg_train0105_0221. Fleet: 8 enabled models.
- **Created `nba_orchestration.service_errors` BQ table** — was silently missing, audit trail now works.
- **Fixed 3 bugs in decay-detection CF:** SQL GROUP BY with ARRAY_AGG, dataset mismatch, column schema mismatch.
- **Fixed same dataset bug in `deactivate_model.py`.**
- **Enabled `AUTO_DISABLE_ENABLED=true`** on decay-detection CF. BLOCKED models auto-disabled daily 11 AM ET.

### Code Quality (Phase B — ALL DONE)
- **Feature contract consolidated:** `catboost_v12.py` imports from `shared/ml/feature_contract.py` (killed 50-element hardcoded list).
- **Champion model from registry:** `get_champion_model_id()` queries `model_registry WHERE is_production=TRUE` (1hr cache, fallback).
- **HTTP handlers** added to `data_source_health_canary.py` and `signal_decay_monitor.py`.

### Signal Changes
- **Removed `mean_reversion_under`** from UNDER_SIGNAL_WEIGHTS (53.0% HR, below 54.3% baseline).
- **Built `bin/monitoring/signal_weight_report.py`** — first run flagged combo_3way (63.9% N=36) and combo_he_ms (70.8% N=24) for promotion.
- Algorithm version: `v429_signal_weight_cleanup`

---

## What to Do Next

### Priority 1: Validate v429 Pipeline (15 min)
```sql
-- Check picks exist with correct algorithm version
SELECT game_date, algorithm_version, recommendation, COUNT(*) as picks
FROM nba_predictions.signal_best_bets_picks
WHERE game_date >= '2026-03-07'
GROUP BY 1, 2, 3 ORDER BY 1, 2, 3;

-- Check new signal fires (bounce_back_over, CLV, under_after_bad_miss, volatile_starter_under, downtrend_under)
SELECT player_lookup, recommendation, signal_tags
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = CURRENT_DATE()
  AND (signal_tags LIKE '%bounce_back%' OR signal_tags LIKE '%clv%'
       OR signal_tags LIKE '%under_after_bad_miss%'
       OR signal_tags LIKE '%volatile_starter%' OR signal_tags LIKE '%downtrend%');
```

### Priority 2: Signal Promotion Decisions (15 min)
- **combo_3way:** 63.9% HR, N=36 — meets production threshold (HR>=60%, N>=30). Promote?
- **combo_he_ms:** 70.8% HR, N=24 — meets rescue threshold (HR>=65%, N>=15). Already rescue?
- Run: `PYTHONPATH=. python bin/monitoring/signal_weight_report.py --dry-run`

### Priority 3: Schedule Monitors (15 min)
HTTP handlers are ready. Create Cloud Scheduler jobs:
- data_source_health_canary → daily 7 AM ET
- signal_decay_monitor → daily 12 PM ET
- signal_weight_report → weekly Monday 10 AM ET

### Priority 4: CI Enforcement (20 min)
Create GitHub Actions workflow for 5 critical pre-commit hooks:
- validate-deploy-safety, validate-python-syntax, validate-schema-fields, validate-dockerfile-imports, validate-model-references

### Priority 5: Calendar Regime Research (30-45 min)
- Query prediction_accuracy Jan 15 - Mar 10 across 2025+2026
- Map HR by week — identify exact toxic window boundaries
- Per-signal HR during toxic vs non-toxic
- Would regime-aware multipliers improve toxic window by 5+pp?

### Priority 6: Filter Auto-Demotion Design (future)
Needs BQ table to persist filtered_picks data. Currently only in JSON exports.

### Priority 7: MLB Pre-Season (Mar 24-25)
- Resume scheduler jobs, retrain CatBoost V1, E2E smoke test

---

## System State

| Item | Status |
|------|--------|
| Fleet | 8 enabled models, AUTO_DISABLE live |
| Algorithm | v429_signal_weight_cleanup |
| Decay CF | Fixed + AUTO_DISABLE=true |
| service_errors | Table created, writers fixed |
| Champion model | Now from registry (is_production=TRUE) |
| Feature contract | Consolidated (SSOT in shared/ml/) |
| Deployment | All services fresh (3 commits pushed today) |

## Key Files Changed This Session
- `ml/signals/aggregator.py` — mean_reversion_under removed, version bump
- `orchestration/cloud_functions/decay_detection/main.py` — 3 bug fixes
- `bin/deactivate_model.py` — dataset/column fix
- `predictions/worker/prediction_systems/catboost_v12.py` — feature contract import
- `shared/config/model_selection.py` — champion from registry
- `bin/monitoring/signal_weight_report.py` — NEW

## Full Audit
- `docs/08-projects/current/system-improvement-audit/SYSTEM-AUDIT.md` — keyword map of every system component
- `docs/08-projects/current/system-improvement-audit/EXECUTION-PLAN.md` — prioritized plan from 3-agent consensus
