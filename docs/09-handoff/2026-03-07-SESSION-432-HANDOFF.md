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
- Deleted `START-NEXT-SESSION-HERE.md` — causes confusion with parallel chats. Use dated handoffs only.

---

## Commits

```
4a7d27cd feat: auto-demote filter system — CF evaluator + runtime overrides
1e47bda4 fix: filter CF streaming buffer fix + test updates
52e892e7 docs: Session 432 handoff — auto-demote filter system complete
```

---

## System Health Snapshot (Mar 7 evening)

### Best Bets Performance (last 7 days)
| Date | Picks | W-L | HR |
|------|-------|-----|-----|
| Mar 7 | 10 (7O/3U) | ungraded | - |
| Mar 6 | 1 | 0-1 | 0.0% |
| Mar 5 | 13 (8O/5U) | 9-4 | 69.2% |
| Mar 4 | 9 (8O/1U) | 4-4 | 50.0% |
| Mar 1 | 2 | 2-0 | 100% |

### Model Fleet (as of Mar 6)
- **HEALTHY (9):** v12 (68.4%), v12_train0104_0222 (86.7%), v12_noveg_train0108_0215 (72.2%), v16_noveg_train1201_0215 (63.6%), v9_low_vegas (59.4%), xgb_s999 (68.8%), lgbm_train1201 (71.4%), v12_noveg_train0104_0215 (77.8%), v16_noveg_rec14 (58.8%)
- **WATCH (3):** v12_noveg_train0103_0227 (55.6%, dropped from 64.3%), lgbm_vw015 (57.1%, dropped from 66.7%), xgb_s42 (55.6%)
- **DEGRADING (1):** v12_noveg_train0110_0220 (53.3%)
- **BLOCKED (8+):** Several q55/q57, v13, older lgbm/xgb models. AUTO_DISABLE handles these.

### Signal Health Alerts
**Strong (14d HR > 70%):** high_scoring_environment_over 78.9% (N=19), sharp_line_drop_under 87.5% (N=8), line_rising_over 72.7% (N=11)

**Concerning:**
- `combo_3way` and `combo_he_ms` dropped to COLD — 42.9% (N=7). Historically 95%+ HR. Tiny sample, likely regime dip.
- `book_disagreement` dropped to COLD — 47.4% 7d (was 93% historically)
- `starter_under` at 37.5% (N=32) — persistently weak
- `blowout_risk_under` at 15.4% (N=13) — observation-only, confirming should stay obs

**System is in OVER-favorable regime.** UNDER signals broadly weak.

### Auto-Demote Filters (new system, accumulating data)
- `med_usage_under`: CF HR 25-33% — filter correctly blocking losers
- `line_dropped_under`: CF HR 0% — filter working
- `friday_over_block`: CF HR 100% (N=1) — too noisy, need more data
- Need 7 consecutive days before any auto-demotion triggers

---

## System State

| Item | Status |
|------|--------|
| Fleet | 9 HEALTHY, 3 WATCH, 1 DEGRADING, 8+ BLOCKED. AUTO_DISABLE live. |
| Signals | 27 active + 26 shadow. combo_3way/combo_he_ms/book_disagreement COLD. |
| Filters | 19 active + 22 obs, 13 eligible for auto-demote |
| CI | All 5 pre-commit checks BLOCKING |
| Monitors | 4 scheduled CFs (data source 7AM, filter CF 11:30AM, signal decay 12PM, weight report Mon 10AM) |
| MLB | Handled in separate chat |

---

## What to Do Next (NBA)

### Priority 1: Signal Health Investigation
`combo_3way`, `combo_he_ms`, and `book_disagreement` dropped to COLD regime. These were the top signals historically. Investigate:
- Are the 7 picks just noise? Query what they were.
- Did underlying conditions change (gamebook minutes, model health)?
- Is this a broader regime shift?
- Query: `SELECT * FROM signal_best_bets_picks WHERE game_date >= '2026-02-25' AND signal_tags LIKE '%combo_3way%'`

### Priority 2: WATCH Model Triage
Three models dropped HEALTHY -> WATCH on Mar 6. Determine if acute (one bad day) or trend:
- `catboost_v12_noveg_train0103_0227`: 64.3% -> 55.6%
- `lgbm_v12_noveg_vw015_train1215_0208`: 66.7% -> 57.1% (sources 80% BB HR picks!)
- `xgb_v12_noveg_s42_train1215_0208`: 60.0% -> 55.6%

### Priority 3: Slack Webhook for Filter CF (5 min)
```bash
gcloud functions deploy filter-counterfactual-evaluator \
  --region=us-west2 --project=nba-props-platform \
  --update-env-vars="SLACK_WEBHOOK_URL_WARNING=<get-url-from-slack-channels.py>"
```

### Priority 4: SPOF Fallback Scrapers (strategic)
NumberFire (only projection), RotoWire (only minutes), VSiN (only betting %), Covers (only referee), Hashtag (only DvP)

### Priority 5: Model Diversity (next quarter)
All enabled models r >= 0.95 redundant — need structurally different model.
