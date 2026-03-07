# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 431 — monitors scheduled, CI fully enforced, calendar regime analyzed)
**Status:** System hardened. All monitoring automated. All CI checks blocking. Calendar regime research complete.

---

## What Was Done (Session 431)

### 431a: Infrastructure + Research
- **3 Cloud Functions deployed and scheduled:**
  - `data-source-health-canary` → daily 7 AM ET
  - `signal-decay-monitor` → daily 12 PM ET
  - `signal-weight-report` → weekly Monday 10 AM ET
- Cloud Build triggers created for auto-deploy on push
- Fixed `cloudbuild-functions.yaml`: skip IAM step for HTTP triggers, copy `_impl` files for monitor CFs
- **Calendar regime deep dive:** combo_3way/combo_he_ms IMPROVE during toxic (85.7%). `blowout_recovery` collapses (75%→33%). Recommendation: NO regime system, one surgical fix.

### 431b: Signal Cleanup + CI Promotion
- **Demoted `sharp_book_lean_under`** to observation-only (zero fires in 2026)
- **Suppressed `blowout_recovery` during toxic window** — `detect_regime()` in `blowout_recovery.py`
- **All 5 CI pre-commit checks now BLOCKING:**
  - Fixed 45 deploy scripts (`--set-env-vars` → `--update-env-vars`)
  - Added 6 missing schema fields to `01_player_prop_predictions.sql`
  - Fixed hardcoded `catboost_v9` in enrichment processor, added MLB exclusion to validator
- Verified CF concurrency on Phase 3→4 and 4→5 orchestrators
- Updated SIGNAL-INVENTORY.md (27 active signals)

---

## What to Do Next

### Priority 1: Auto-Demote Filters (2 hr)
Design from Session 429 execution plan (Phase C2). Currently filters are manually demoted when HR drops. Automate this:
- Daily CF runs after grading
- Computes counterfactual HR for each active negative filter (what if the filter didn't block?)
- If CF HR >= 55% at N >= 20 for 7 consecutive days → auto-demote to observation + Slack alert
- **Needs:** BQ table for `filtered_picks` persistence (currently only in JSON exports)
- **Foundation:** `aggregator.py:_record_filtered()` already tracks every filtered pick. `bin/post_filter_eval.py` already grades counterfactual picks.
- **Reference:** Session 428 manually demoted 4 filters with CF HR 55-65%. This automation catches them earlier.

### Priority 2: MLB Pre-Season (Mar 24-25)
- Resume 22 scheduler jobs (`gcloud scheduler jobs resume ...`)
- Retrain CatBoost V1 on freshest data (current model ends Aug 2025)
- Health check all MLB Cloud Run services
- E2E smoke test with spring training data
- Complete batter backfill (108/550 dates done, through 2024-07-14)
- **Checklist:** `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md`
- **Backfill resume:** `PYTHONPATH=. python scripts/mlb/backfill_batter_stats.py --start 2024-07-14 --end 2025-09-28 --sleep 0.3 --skip-existing`

### Priority 3: SPOF Fallback Scrapers (strategic)
5 irrecoverable data SPOFs identified — no backup if primary fails:
- **NumberFire** (only projection source) — highest risk, FanDuel GraphQL API
- **RotoWire** (only projected minutes) — blocks `minutes_surge_over` signal
- **VSiN** (only public betting %) — `data.vsin.com`
- **Covers** (only referee stats) — weekly scrape
- **Hashtag Basketball** (only defense-vs-position) — `hashtagbasketball.com`

### Priority 4: Non-CatBoost Model Diversity (next quarter)
All 8 enabled models have r >= 0.95 (REDUNDANT). Need a structurally different model to break fleet correlation. Current fleet: all CatBoost/LightGBM/XGBoost with same V12_noveg features.

---

## System State

| Item | Status |
|------|--------|
| Fleet | 8 enabled models, AUTO_DISABLE live (decay-detection CF daily 11 AM ET) |
| Signals | 27 active + 26 shadow. sharp_book_lean_under→obs. blowout_recovery toxic-suppressed. |
| Algorithm | v429_signal_weight_cleanup |
| Monitors | 3 scheduled CFs: data source 7AM, signal decay 12PM, weight report Mon 10AM |
| CI | All 5 pre-commit checks BLOCKING (deploy safety, python syntax, schema, dockerfile, model refs) |
| Deployment | All services fresh. 3 commits pushed this session. |
| MLB | 20 days to opening day, all 22 schedulers paused |

## Key Commits (Session 431)

```
e6ab72a9 fix: resolve all 5 pre-commit CI violations — all checks now blocking (57 files)
2906ec54 docs: Session 431 handoff — monitors scheduled, CI active, calendar regime analyzed
1875e850 feat: scheduled monitoring CFs + CI pre-commit checks
```

## Key Files Changed

| File | Change |
|------|--------|
| `cloudbuild-functions.yaml` | IAM skip for HTTP + monitor _impl copy |
| `.github/workflows/pre-commit-checks.yml` | All 5 checks blocking |
| `orchestration/cloud_functions/{data_source_health_canary,signal_decay_monitor,signal_weight_report}/` | NEW — CF wrappers |
| `ml/signals/aggregator.py` | Removed sharp_book_lean_under from weights + rescue |
| `ml/signals/blowout_recovery.py` | Toxic window suppression via detect_regime() |
| `schemas/bigquery/predictions/01_player_prop_predictions.sql` | 6 fields added |
| `data_processors/enrichment/.../prediction_line_enrichment_processor.py` | catboost_v9 → get_champion_model_id() |
| `.pre-commit-hooks/validate_deploy_safety.py` | Smarter filtering (skip echo/archive) |
| `.pre-commit-hooks/validate_model_references.py` | MLB predictor exclusion |
| 45 `bin/**/*.sh` scripts | `--set-env-vars` → `--update-env-vars` |
