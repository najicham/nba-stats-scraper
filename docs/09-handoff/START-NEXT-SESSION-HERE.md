# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 431b — sharp_book_lean_under demoted, blowout_recovery toxic suppression)
**Status:** Signal cleanup complete. Blowout recovery suppressed during toxic window. CI workflow active.

---

## What Was Done (Session 431)

### Session 431a: Monitor Scheduling, CI, Calendar Regime
- 3 Cloud Functions deployed and scheduled (data source 7AM, signal decay 12PM, weight report Mon 10AM)
- CI enforcement: 2 blocking + 3 warning-only pre-commit checks
- Calendar regime analysis: combo_3way/combo_he_ms resilient, blowout_recovery fragile

### Session 431b: Signal Cleanup + Blowout Recovery Suppression
- **Demoted `sharp_book_lean_under`** to observation-only — removed from `UNDER_SIGNAL_WEIGHTS` and `rescue_tags` (zero production fires in 2026, market regime makes negative lean nonexistent)
- **Suppressed `blowout_recovery` during toxic window** — added `detect_regime()` check in `blowout_recovery.py`. Signal returns `_no_qualify()` when `regime.is_toxic`. Prevents 75%→33% collapse near trade deadline + ASB.
- Verified CF concurrency on Phase 3→4 and 4→5 orchestrators (both correct: maxInstances=3, concurrency=1)
- Updated SIGNAL-INVENTORY.md (27 active signals, sharp_book_lean_under→OBSERVATION, blowout_recovery notes)

---

## What to Do Next

### Priority 1: Promote Warning-Only CI Checks (1 hr)
Clean up existing violations so all 5 pre-commit checks can block:
- `validate_deploy_safety`: 40+ `--set-env-vars` in legacy `bin/deploy/` scripts → change to `--update-env-vars`
- `validate_schema_fields`: 6 fields in worker code not in schema → add to schema
- `validate_model_references`: 2 hardcoded system_ids → use `get_champion_model_id()`

### Priority 1: Auto-Demote Filters (2 hr)
Design from Session 429 execution plan (Phase C2):
- Daily CF runs after grading
- Computes counterfactual HR for each active filter
- If CF HR >= 55% at N >= 20 for 7 consecutive days → auto-demote to observation
- Needs BQ table for `filtered_picks` persistence

### Priority 2: MLB Pre-Season (Mar 24-25)
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
| Signals | 27 active, sharp_book_lean_under→obs, blowout_recovery toxic-suppressed |
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
| `ml/signals/aggregator.py` | Removed sharp_book_lean_under from UNDER_SIGNAL_WEIGHTS + rescue_tags |
| `ml/signals/blowout_recovery.py` | Added toxic window suppression via detect_regime() |
| `ml/signals/signal_health.py` | Updated sharp_book_lean_under comment to observation |
| `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` | 27 active signals, updated sharp_book_lean_under + blowout_recovery |
