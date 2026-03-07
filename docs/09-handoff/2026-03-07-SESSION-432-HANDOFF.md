# Session 432 Handoff — Auto-Demote Filter System

**Date:** 2026-03-07
**Session:** 432
**Status:** Complete. Auto-demote filter system deployed and tested.

---

## What Was Done

### Auto-Demote Filter System (Priority 1 from Session 431b)

Built a fully automated system that detects when negative filters are blocking profitable picks and auto-demotes them to observation-only.

**Components:**

1. **BQ Table: `filter_counterfactual_daily`** (partition: game_date, cluster: filter_name)
   - Daily per-filter counterfactual HR from graded `best_bets_filtered_picks` data
   - Backfilled with existing data (4 game dates, 28 rows)

2. **BQ Table: `filter_overrides`** (cluster: filter_name)
   - Runtime filter overrides (active demotions read by aggregator at export time)
   - Currently empty — will populate when auto-demote criteria are met

3. **Cloud Function: `filter-counterfactual-evaluator`**
   - Scheduled: 11:30 AM ET daily via Cloud Scheduler
   - Queries graded filtered picks, computes per-filter CF HR
   - Writes daily results to `filter_counterfactual_daily`
   - Checks 7-day consecutive auto-demote criteria:
     - CF HR >= 55% for all 7 days
     - N >= 20 graded picks over 7 days
     - Filter must be in ELIGIBLE_FOR_AUTO_DEMOTE set
   - When triggered: writes to `filter_overrides` + Slack alert + service_errors audit log
   - Safety caps: max 2 demotions per run
   - Successfully tested via `gcloud functions call`

4. **Aggregator change: `runtime_demoted_filters` parameter**
   - 13 eligible filters gated: `if filter_name not in self._runtime_demoted: continue`
   - Demoted filters still record to `_record_filtered()` (counterfactual tracking continues)
   - Core safety filters (edge_floor, blacklist, quality_floor, signal_count, etc.) are NOT eligible

5. **Exporter change: `_query_filter_overrides()`**
   - Queries `filter_overrides WHERE active = TRUE` at export time
   - Passes set of demoted filter names to aggregator

**13 Eligible Filters for Auto-Demotion:**
```
med_usage_under, b2b_under_block, line_dropped_under,
opponent_under_block, opponent_depleted_under, q4_scorer_under_block,
friday_over_block, high_skew_over_block, high_book_std_under,
under_after_streak, under_after_bad_miss, familiar_matchup,
model_direction_affinity
```

**Core Safety Filters (NEVER auto-demote):**
```
blacklist, edge_floor, over_edge_floor, under_edge_7plus,
quality_floor, signal_count, sc3_over_block, signal_density,
starter_over_sc_floor, confidence, rescue_cap
```

### Test Updates
- Fixed 3 pre-existing test failures (mid_line_over tests from Session 428 demotion)
- Added `under_after_bad_miss` to expected filter keys
- Added `TestRuntimeDemotion` class with 5 tests (Friday demotion, core filter protection, B2B demotion, empty set)
- All 70 aggregator tests pass

### Infrastructure
- Cloud Build trigger: `deploy-filter-counterfactual-evaluator` (auto-deploy on push to main)
- Cloud Scheduler: `filter-counterfactual-evaluator-daily` (11:30 AM ET)
- CF uses MERGE (not DELETE+INSERT) to avoid BQ streaming buffer conflicts

---

## Commits

```
4a7d27cd feat: auto-demote filter system — CF evaluator + runtime overrides
1e47bda4 fix: filter CF streaming buffer fix + test updates
```

---

## System State After Session

| Item | Status |
|------|--------|
| Fleet | 8 enabled models, AUTO_DISABLE live |
| Signals | 27 active + 26 shadow |
| Filters | 19 active + 22 obs, 13 eligible for auto-demote |
| CI | All 5 pre-commit checks BLOCKING |
| Monitors | 4 scheduled CFs (data source 7AM, filter CF 11:30AM, signal decay 12PM, weight report Mon 10AM) |
| MLB | 17 days to opening day, schedulers paused |

---

## What to Do Next

### Priority 1: MLB Pre-Season (Mar 24-25)
- Resume 22 scheduler jobs
- Retrain CatBoost V1 on freshest data
- E2E smoke test with spring training data
- Complete batter backfill (108/550 dates)
- Checklist: `docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md`

### Priority 2: SPOF Fallback Scrapers (strategic)
NumberFire (only projection), RotoWire (only minutes), VSiN (only betting %), Covers (only referee), Hashtag (only DvP)

### Priority 3: Model Diversity (next quarter)
All 8 models r >= 0.95 redundant — need structurally different model.

### Priority 4: Slack Webhook for Filter CF
The `filter-counterfactual-evaluator` CF doesn't have a Slack webhook URL set. Add `SLACK_WEBHOOK_URL_WARNING` env var when ready:
```bash
gcloud functions deploy filter-counterfactual-evaluator --region=us-west2 --project=nba-props-platform --update-env-vars="SLACK_WEBHOOK_URL_WARNING=<url>"
```
