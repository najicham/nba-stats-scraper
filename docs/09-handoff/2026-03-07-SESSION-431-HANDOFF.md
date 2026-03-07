# Session 431 Handoff — Monitor Scheduling, CI Enforcement, Calendar Regime

**Date:** 2026-03-07
**Session:** 431 (431a + 431b)
**Status:** All 5 priorities from Session 429 execution plan COMPLETE. System hardened.

---

## Summary

Executed the remaining work from Session 429's system improvement audit. All infrastructure is now automated and validated.

## What Was Done

### 431a: Infrastructure + Research

**3 Cloud Functions deployed and scheduled:**
- `data-source-health-canary` — daily 7 AM ET (freshness check for 7 data sources)
- `signal-decay-monitor` — daily 12 PM ET (signal HEALTHY/WATCH/DEGRADING/RECOVERED states)
- `signal-weight-report` — weekly Monday 10 AM ET (UNDER weight vs HR comparison, shadow promotion candidates)

**CF deployment details:**
- Each CF has a thin wrapper (`main.py`) that imports `{name}_impl.py` (the actual monitor script copied alongside)
- `cloudbuild-functions.yaml` updated to auto-copy `_impl` files and skip IAM step for HTTP triggers
- Cloud Build triggers created for auto-deploy on push to main
- Requirements: `functions-framework`, `google-cloud-bigquery`, `google-cloud-storage`, `pandas`, `requests`, `flask`
- Cloud Scheduler jobs: `data-source-health-canary-daily`, `signal-decay-monitor-daily`, `signal-weight-report-weekly`

**Calendar regime deep dive:**
- Toxic window is NOT calendar-fixed — driven by trade deadline + ASB dates which shift yearly
- 2026 acute damage: Feb 8-10 (post-deadline) + Feb 19-20 (post-ASB) = 7 high-damage days
- BB HR 61.0% during toxic vs 67.7% non-toxic — filter stack keeps system profitable
- combo_3way/combo_he_ms IMPROVE to 85.7% during toxic (model consensus is regime-proof)
- `blowout_recovery` collapses 75%→33% (-41.7pp) — roster changes invalidate recovery patterns
- Recommendation: NO regime-aware multiplier system. One surgical fix (implemented in 431b).

**CI enforcement (initial):**
- Created `.github/workflows/pre-commit-checks.yml`
- Initially: 2 blocking (python_syntax, dockerfile_imports) + 3 warning-only

**Signal weight report false positive fix:**
- `combo_3way` and `combo_he_ms` were flagged as shadow promotion candidates but are already active + in rescue
- Added to `known_active` set in `signal_weight_report.py`
- Updated stale HR numbers in `pick_angle_builder.py` (94.9%→70.8%, 78.1%→63.9%)

### 431b: Signal Cleanup + CI Promotion

**Signal changes:**
- Demoted `sharp_book_lean_under` to observation-only — removed from `UNDER_SIGNAL_WEIGHTS` and `rescue_tags` (zero production fires in 2026, market regime makes negative lean nonexistent)
- Suppressed `blowout_recovery` during toxic window — `detect_regime()` in `blowout_recovery.py` returns `_no_qualify()` when `regime.is_toxic`

**All 5 CI checks promoted to BLOCKING:**
- `validate_deploy_safety`: Fixed 45 deploy scripts (`--set-env-vars` → `--update-env-vars`). Updated validator to skip echo/comments/archive false positives.
- `validate_schema_fields`: Added 6 missing fields to `01_player_prop_predictions.sql` (feature_sources_json STRING, is_quality_ready BOOLEAN, low_quality_flag BOOLEAN, matchup_data_status STRING, scoring_tier STRING, tier_adjustment FLOAT64). Fixed BOOL→BOOLEAN for validator regex.
- `validate_model_references`: Fixed hardcoded `catboost_v9` in enrichment processor → `get_champion_model_id()`. Added MLB predictor exclusion to validator.

---

## Commits

```
644ac211 docs: final Session 431 handoff — all priorities complete
e6ab72a9 fix: resolve all 5 pre-commit CI violations — all checks now blocking (57 files)
2906ec54 docs: Session 431 handoff — monitors scheduled, CI active, calendar regime analyzed
1875e850 feat: scheduled monitoring CFs + CI pre-commit checks
```

---

## System State After Session

| Item | Status |
|------|--------|
| Fleet | 8 enabled models, AUTO_DISABLE live (decay-detection CF daily 11 AM ET) |
| Signals | 27 active + 26 shadow. sharp_book_lean_under→obs. blowout_recovery toxic-suppressed. |
| Algorithm | v429_signal_weight_cleanup |
| Monitors | 3 scheduled CFs: data source 7AM, signal decay 12PM, weight report Mon 10AM |
| CI | All 5 pre-commit checks BLOCKING |
| MLB | 20 days to opening day, all 22 schedulers paused |

---

## What to Do Next

1. **Auto-demote filters** (2 hr) — daily CF computes counterfactual HR for active filters, auto-demotes if CF HR >= 55% at N >= 20 for 7 consecutive days. Needs BQ table for filtered_picks.
2. **MLB pre-season** (Mar 24-25) — resume schedulers, retrain CatBoost V1, E2E smoke test, batter backfill.
3. **SPOF fallback scrapers** (strategic) — NumberFire, RotoWire, VSiN, Covers, Hashtag have no backup sources.
4. **Model diversity** (next quarter) — all 8 models r >= 0.95 redundant, need structurally different model.
