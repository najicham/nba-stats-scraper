# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 431 — Monitor scheduling, CI enforcement, calendar regime research)
**Status:** All 5 priorities from Session 429 plan DONE. 3 monitors scheduled. CI workflow active. Calendar regime analyzed.

---

## What Was Done (Session 431)

### Priority 1: Pipeline Validation
- 9 picks with `v429_signal_weight_cleanup` — pipeline healthy
- combo_3way/combo_he_ms firing on OVER picks (Horford, Duren)
- No CLV/bounce_back/volatile_starter/downtrend fires yet (expected — need specific conditions)

### Priority 2: Signal Promotions
- combo_3way + combo_he_ms already active + in rescue — **no promotion needed**
- Fixed false positive in `signal_weight_report.py` (missing from `known_active`)
- Updated stale HR numbers in `pick_angle_builder.py` (94.9%→70.8%, 78.1%→63.9%)

### Priority 3: Monitor Scheduling — COMPLETE
3 Cloud Functions deployed and scheduled:
- **data-source-health-canary** → daily 7 AM ET (scheduler: `data-source-health-canary-daily`)
- **signal-decay-monitor** → daily 12 PM ET (scheduler: `signal-decay-monitor-daily`)
- **signal-weight-report** → weekly Monday 10 AM ET (scheduler: `signal-weight-report-weekly`)

Cloud Build triggers created for auto-deploy on push to main.
Fixed `cloudbuild-functions.yaml`: skip IAM step for HTTP triggers + copy `_impl` monitor files.

### Priority 4: CI Enforcement — COMPLETE
`.github/workflows/pre-commit-checks.yml`:
- **Blocking:** `validate_python_syntax`, `validate_dockerfile_imports`
- **Warning-only:** `validate_deploy_safety`, `validate_schema_fields`, `validate_model_references` (existing violations)

### Priority 5: Calendar Regime Deep Dive — COMPLETE
- **Do NOT build regime-aware multiplier system** — 61% BB HR during toxic is already profitable
- **Resilient signals:** combo_3way/combo_he_ms IMPROVE to 85.7% during toxic
- **Fragile signal:** `blowout_recovery` collapses 75%→33% (-41.7pp) during roster disruption
- **Targeted fix:** Suppress `blowout_recovery` 5d post-trade-deadline + 3d post-ASB return

---

## What to Do Next

### Priority 1: Suppress blowout_recovery Near Deadline/ASB (30 min)
The only signal that collapses during toxic window. Implement in aggregator:
- Define trade deadline + ASB dates per season
- If game_date within 5d of deadline or 3d of ASB return → skip blowout_recovery evaluation
- This would have prevented 2-3 losses in the toxic window

### Priority 2: Promote Warning-Only CI Checks (1 hr)
Clean up existing violations so all 5 pre-commit checks can block:
- `validate_deploy_safety`: 40+ `--set-env-vars` in legacy `bin/deploy/` scripts → change to `--update-env-vars`
- `validate_schema_fields`: 6 fields in worker code not in schema → add to schema
- `validate_model_references`: 2 hardcoded system_ids → use `get_champion_model_id()`

### Priority 3: Auto-Demote Filters (2 hr)
Design from Session 429 execution plan (Phase C2):
- Daily CF runs after grading
- Computes counterfactual HR for each active filter
- If CF HR >= 55% at N >= 20 for 7 consecutive days → auto-demote to observation
- Needs BQ table for `filtered_picks` persistence

### Priority 4: MLB Pre-Season (Mar 24-25)
- Resume 22 scheduler jobs
- Retrain CatBoost V1 on freshest data
- E2E smoke test
- Complete batter backfill (108/550 dates)

### Priority 5: SPOF Fallback Scrapers (strategic)
5 irrecoverable data SPOFs identified:
- NumberFire (only projection) — highest risk
- RotoWire (only minutes), VSiN (only betting %), Covers (only referee), Hashtag (only DvP)

---

## System State

| Item | Status |
|------|--------|
| Fleet | 8 enabled models, AUTO_DISABLE live |
| Algorithm | v429_signal_weight_cleanup |
| Monitors | 3 scheduled CFs (data source 7AM, signal decay 12PM, weight report Mon 10AM) |
| CI | Pre-commit checks active (2 blocking, 3 warning) |
| Deployment | All services fresh, cloudbuild IAM fix deployed |
| MLB | 20 days to opening day, schedulers paused |

## Key Files Changed

| File | Change |
|------|--------|
| `cloudbuild-functions.yaml` | IAM skip for HTTP + monitor _impl copy |
| `.github/workflows/pre-commit-checks.yml` | NEW — CI enforcement |
| `orchestration/cloud_functions/data_source_health_canary/` | NEW — CF wrapper |
| `orchestration/cloud_functions/signal_decay_monitor/` | NEW — CF wrapper |
| `orchestration/cloud_functions/signal_weight_report/` | NEW — CF wrapper |
| `bin/monitoring/signal_weight_report.py` | Fixed false positive (combo_3way/he_ms in known_active) |
| `ml/signals/pick_angle_builder.py` | Updated stale HR numbers |
