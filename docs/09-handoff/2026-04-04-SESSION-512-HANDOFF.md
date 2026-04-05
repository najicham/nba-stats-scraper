# Session 512 Handoff — Deep Dive + MLB Pipeline Fixes

**Date:** 2026-04-04
**Focus:** Multi-angle deep dive into NBA prediction decline, MLB pipeline unblocking, edge 3-5 leak fix
**Commits:** `3dbb3f58` (MLB 7 fixes), `8c8b96b3` (NBA edge-tier + deploy fix)

---

## What Was Done This Session

### 1. MLB Pipeline — 7 Code Fixes Deployed
The MLB prediction system was 97-100% BLOCKED due to 5 interconnected upstream issues. All fixed:

| Fix | File | Status |
|-----|------|--------|
| Proxy secrets on `mlb-phase1-scrapers` | `deploy_mlb_scrapers.sh` | Deployed + verified |
| TODAY literal in GCS path | `mlb_events.py` | Committed, auto-deploying |
| ExportMode.RAW -> DATA | `mlb_events.py` | Committed, auto-deploying |
| NoneType guard in bp_events.py | `bp_events.py` | Committed, auto-deploying |
| game_id AS game_pk | `mlb_prediction_grading_processor.py` | Committed, auto-deploying |
| status_detailed AS game_status | `mlb_prediction_grading_processor.py` | Committed, auto-deploying |
| Resolve YESTERDAY in /grade-date | `main_mlb_grading_service.py` | Committed, auto-deploying |

**3 Schedulers Created/Updated:**
- `mlb-box-scores-daily` — 8 AM ET, `{"scraper": "mlb_box_scores_mlbapi", "date": "YESTERDAY"}` (was MISSING)
- `mlb-schedule-yesterday` — 8 AM ET, `{"scraper": "mlb_schedule", "date": "YESTERDAY"}` (was MISSING)
- `mlb-statcast-daily` — moved from 3 AM ET to 8 AM ET for data availability

### 2. NBA Edge 3-5 Leakage Fix
`under_low_rsc` filter in `aggregator.py` is now edge-tiered:
- Edge < 5.0: requires `real_sc >= 3` (was >= 2). Blocks 36.4% HR tier (N=11).
- Edge 5-7: keeps `real_sc >= 2` (unchanged).
- Edge 7+: bypass (unchanged).

### 3. Deep Dive into NBA Decline (findings below)

---

## Deep Dive Findings: Why NBA Picks Collapsed in March

**Season record: 104-70 (59.8%).** Jan 73.1% -> Feb 56.3% -> Mar 47.4%.

### Root Cause 1: Model Edge Compression (Primary)
- Jan BB avg edge: **7.0-10.3**. March BB avg edge: **3.6-4.9**.
- Every model lifecycle: HEALTHY 1-5 days -> BLOCKED within a week.
- March 8 was the cliff: 3 models hit BLOCKED simultaneously.
- Models trained on Jan-Mar data absorb low-variance March data (load management, rest games) -> compressed predicted edges.
- The `train0126_0323` pair went BLOCKED within **2 days** of deployment.

### Root Cause 2: Blowout Surge
- Blowout rate (20+ pt margin): **19% Dec-Jan -> 28% March -> 38.5% April**.
- Starters pulled early -> suppressed stat lines the model can't anticipate pre-game.
- Model MAE gap vs Vegas: **-0.01 in Jan -> +0.78 in March** (model degraded, not Vegas sharpening).

### Root Cause 3: `home_under` Signal Collapse
- **75% HR (N=8) in Feb -> 44% HR (N=79) in March** — 31pp drop at 10x volume.
- Primary gateway signal for UNDER `real_sc=1`. Its failure cascaded into entire UNDER portfolio.
- Regime system still classifies it NORMAL despite sustained sub-50%.

### Root Cause 4: Role-Player OVER Toxicity
- Role players (<18 line) OVER: **46.2% HR** with blowout misses (scoring 2-9 on lines 5.5-15.5).
- AWAY OVER: **38.1%** vs HOME OVER: **70.0%** — extreme venue split.
- Worst offenders: Sensabaugh (scored 7 on 15.5 line), Isaiah Joe (4 on 9.5), Scoot Henderson (8 on 13.5), Nolan Traore (2 on 9.5).

### Root Cause 5: Filters Blocking Winners
- `friday_over_block`: **85.7% CF HR** (blocking 12 of 14 winners)
- `bench_under_obs`: **81.3% CF HR** (blocking 26 of 32 winners)
- `high_skew_over_block_obs`: **88.9% CF HR** (blocking 8 of 9 winners)
- `under_low_rsc`: **54.1% CF HR**, worsening to 62.8% in late March
- `blacklist`: **78.6% CF HR** (blocking profitable players)

### Root Cause 6: Broken Signals Contributing Bad real_sc
- `mean_reversion_under`: **12.5% HR** (season) — garbage signal inflating real_sc.
- `extended_rest_under`: **28.6% HR** (season) — same problem.
- Both contribute to real_sc, helping bad UNDER picks pass the `real_sc >= 2` gate.

### What Was NOT a Factor
- Vegas lines did NOT get sharper (MAE stable ~4.7-5.1)
- Feature 53 did NOT converge to zero (spread actually increased in March)
- Scoring environment was stable across months

---

## Actionable Fixes (Prioritized for Next Session)

### Priority 1: Demote Value-Destroying Filters

These filters are actively blocking winners. Write demotions to `filter_overrides` table.

| Filter | CF HR | N | Action |
|--------|-------|---|--------|
| `friday_over_block` | 85.7% | 14 | **Demote immediately** — blocking 12 of 14 winners |
| `high_skew_over_block_obs` | 88.9% | 9 | Observation-only, but if it were active it would be devastating |
| `bench_under_obs` | 81.3% | 32 | Observation-only — DO NOT promote |
| `blacklist` | 78.6% | 14 | Review which players are blacklisted — may need cleanup |
| `high_spread_over_would_block` | 63.6% -> 77.3% | 33 | Getting worse — review |

**How to demote `friday_over_block`:**
```sql
INSERT INTO nba_predictions.filter_overrides (filter_name, override_type, reason, created_at, expires_at)
VALUES ('friday_over_block', 'demote_to_observation', 'Session 512: CF HR 85.7% (12/14 winners blocked)', CURRENT_TIMESTAMP(), TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 30 DAY))
```

### Priority 2: Remove Broken Signals from Active

| Signal | Season HR | Action |
|--------|-----------|--------|
| `mean_reversion_under` | 12.5% (N=8) | Move to SHADOW_SIGNALS — stop contributing to real_sc |
| `extended_rest_under` | 28.6% (N=7) | Move to SHADOW_SIGNALS — stop contributing to real_sc |

These are in `aggregator.py` signal config. Moving them to `SHADOW_SIGNALS` prevents them from inflating `real_sc` while keeping data collection.

### Priority 3: Add DNP Voiding to Best Bets

**Current problem:** KAT (Apr 3) UNDER 21.5 shows as ungraded. He was DNP. Sportsbooks void DNP props.

**What needs to happen:**
- Grading pipeline should detect DNP via `player_game_summary.is_dnp = TRUE` and mark picks as voided
- Frontend/export should show "Voided - DNP" instead of pending/ungraded
- Check `phase6_export/` and `ml/signals/` for where picks are surfaced

### Priority 4: Investigate AWAY OVER Filter

AWAY OVER: **38.1% HR** (8-13) vs HOME OVER: **70.0% HR** (7-3) in March.

Options:
- Add `away_over_block` filter (most aggressive — blocks all away OVER)
- Add `away_over_penalty` to composite score (softer — demotes but doesn't block)
- Run 5-season simulator to validate if this is March-specific or structural

Historical finding from Session 417: "Bounce-back OVER is AWAY-only — Bad miss + AWAY = 56.2% (N=379). Home = 47.8%." This was for bounce-back specifically, but the March data shows a broader away OVER weakness.

### Priority 5: Role-Player OVER Floor

Players with line < 18 OVER had 46.2% HR with frequent blowout misses. Options:
- Add minimum line floor for OVER picks (e.g., line >= 15 or >= 18)
- Add higher edge requirement for low-line OVER (e.g., edge >= 7 for line < 18)
- Run simulator to calibrate the threshold

### Priority 6: Fix Regime Detection Speed

`home_under` at 44% HR is still NORMAL. `extended_rest_under` at 28% is still NORMAL. The regime detection thresholds are too loose. Check `ml/signals/signal_health.py` for COLD threshold logic.

### Priority 7: Deep Dive Extension

Run these additional analyses to complete the picture:
- Walk-forward HR across prior seasons for March specifically (is late-season decline structural?)
- Filter counterfactual: if we removed all 6 value-destroying filters, what would March HR have been?
- Model correlation: are the 4 enabled models too correlated to provide diversity?

---

## Monitoring Checklist (April 5-6)

### April 5 Morning
- [ ] Did Feb-anchored models produce predictions overnight? Check avg edge.
- [ ] Did `decay-detection` CF auto-disable the two BLOCKED `train0126_0323` models at 11 AM ET?
- [ ] MLB: Did `mlb-box-scores-daily` scheduler fire at 8 AM ET? Check `mlb_raw.mlbapi_pitcher_stats` for April 4 data.
- [ ] MLB: Did `mlb-schedule-yesterday` fire? Check `mlb_raw.mlb_schedule` for `is_final = TRUE` on April 4.
- [ ] MLB: Did BettingPros scraper work with proxy creds? Check logs for `bp_events` / `bp_mlb_player_props`.

### Monday April 6
- [ ] `weekly-retrain` CF fires at 5 AM ET. Does `cap_to_last_loose_market_date()` prevent training through March?
- [ ] If retrain includes March data, manually retrain with `--train-end 2026-02-28`.
- [ ] Check if new models pass governance gates (HR >= 53% at edge 3+, N >= 15).

---

## Full Backlog (40 items)

### NBA — Critical (6 items)
1. **Feb-anchored model monitoring** — Just enabled, avg edge 1.37-1.38 (disappointing). Monitor 2-3 days.
2. **March-trained model auto-disable** — Verify `decay-detection` handles BLOCKED `*_train0126_0323` models.
3. **Monday auto-retrain risk** — May produce compressed-edge models if it trains through March.
4. **Demote `friday_over_block`** — 85.7% CF HR. Blocking winners. (Priority 1 above)
5. **Remove `mean_reversion_under` + `extended_rest_under`** — 12.5% and 28.6% HR. (Priority 2 above)
6. **Add DNP voiding** — KAT Apr 3, Coulibaly Mar 30, Allen Mar 30 all ungraded. (Priority 3 above)

### NBA — Medium (8 items)
7. Signal graduation blocked — `book_disagree_over`, `sharp_consensus_under` at N=1 live. Need N>=30.
8. `quick_retrain.py` hardcoded to `catboost_v9` — use `--no-production-lines` workaround.
9. Quality scorer FEATURE_COUNT mismatch (54 vs 60).
10. End-of-season strategy — 8 game days left, load management increasing.
11. `line_vs_season_avg` (feature 53) structural fix for next season.
12. Walk-forward analysis: is late-season decline structural across all prior seasons?
13. AWAY OVER filter investigation (38.1% HR). (Priority 4 above)
14. Role-player OVER floor (46.2% HR on <18 line). (Priority 5 above)

### MLB — Critical (9 items)
15. **Verify MLB pipeline end-to-end** — Code fixes deployed, schedulers created. Need to confirm data flows Apr 5.
16. **Statcast Cloud IP blocking** — `pybaseball.statcast()` returns empty for 2026 dates. May need proxy or `nba_api`-style workaround.
17. **Phase 3/4 stale** — `pitcher_game_summary` latest 2026-03-27. Will auto-fix once game results flow.
18. **Backfill GCS `TODAY/` files** — 8 files at wrong path from before TODAY fix.
19. **Phase 2 path extractor** — `TODAY/` regex doesn't match. Files at correct paths should work now, but verify.
20. **Grading backfill** — 0 of 35 actionable predictions graded since March 28. Trigger manual grading after results flow.
21. **MLB auto-deploy gap** — Worker and scrapers NOT auto-deployed. Must use manual scripts.
22. **MLB best bets pipeline** — Not built yet. Currently predictions-only, no signal/filter system.
23. **Multi-book odds JOIN mismatch** — oddsa vs bp player_lookup format differs. 0 matches.

### MLB — Medium (4 items)
24. Only 4 negative filters (NBA has 19+). No auto-demote. No daily model performance tracking.
25. FanGraphs player_lookup 0% match rate.
26. No public API publishing for MLB.
27. No data source freshness alerting for MLB.

### Infrastructure (13 items)
28. Publishing exporter BQ scans — `best_bets_exporter`, `results_exporter`, `trends_tonight_exporter` need partition filters. ~$85/mo.
29. Phase 3 fires 10-13x/day — 6 Pub/Sub sources + 7 schedulers, no dedup. $125/mo.
30. Scheduler audit — 116-job gap between GCP (167) and local code. $5-10/mo.
31. Orchestrator min-instances 1->0 — $13-20/mo, HIGH RISK (42+ cold-start failures previously).
32. Silent failures return None/False — `bigquery_utils.py:92`, `verify_phase2_for_phase3.py:78`.
33. Distributed lock race conditions untested.
34. No processor execution logging — needs `processor_execution_log` table.
35. No schema constraints on `player_prop_predictions`.
36. Batch name lookups — `player_name_resolver.py:146`, saves 2.5 min/day.
37. GCS lifecycle policies — saves ~$4,200/year.
38. Remove dual Pub/Sub publishing — saves ~$1,200/year.
39. Connection pooling — `bigquery_client.py`, saves 5-15 min/day.
40. Terraform remote state backend — GCS bucket doesn't exist, terraform not installed.

---

## Quick Start for Next Session

```bash
# 1. Check if Feb-anchored models are producing picks
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT system_id, game_date, COUNT(*) as n,
       ROUND(AVG(ABS(predicted_points - current_points_line)), 2) as avg_edge,
       COUNTIF(ABS(predicted_points - current_points_line) >= 5) as edge5plus
FROM nba_predictions.player_prop_predictions
WHERE game_date >= CURRENT_DATE() - 1
GROUP BY 1, 2 ORDER BY 2, 1"

# 2. Check if BLOCKED models were auto-disabled
./bin/model-registry.sh list

# 3. Check MLB pipeline health
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT table_id, row_count, TIMESTAMP_MILLIS(last_modified_time) as last_modified
FROM mlb_raw.__TABLES__ WHERE table_id IN ('mlbapi_pitcher_stats', 'mlb_schedule', 'oddsa_events', 'bp_pitcher_props')
ORDER BY table_id"

# 4. Check filter CF HRs (to confirm friday_over_block demotion is warranted)
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT filter_name,
       COUNT(*) as blocked,
       ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct = TRUE), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as cf_hr
FROM nba_predictions.best_bets_filtered_picks
WHERE game_date >= '2026-03-01' AND prediction_correct IS NOT NULL
GROUP BY 1 HAVING COUNT(*) >= 5
ORDER BY cf_hr DESC"

# 5. Check signal health for broken signals
bq --project_id=nba-props-platform query --nouse_legacy_sql "
SELECT signal_name, regime, hr_7d, hr_30d, n_30d
FROM nba_predictions.signal_health_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.signal_health_daily)
  AND signal_name IN ('mean_reversion_under', 'extended_rest_under', 'home_under', 'friday_over_block')
ORDER BY signal_name"
```

---

## Key Files

| Purpose | File |
|---------|------|
| BB aggregator (filters + signals) | `ml/signals/aggregator.py` |
| Signal health computation | `ml/signals/signal_health.py` |
| Filter counterfactual evaluator | `cloud_functions/filter_counterfactual_evaluator/main.py` |
| Per-model pipeline | `ml/signals/per_model_pipeline.py` |
| BB simulator (5-season) | `scripts/nba/training/bb_enriched_simulator.py` |
| Signal inventory | `docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md` |
| MLB grading processor | `data_processors/grading/mlb/mlb_prediction_grading_processor.py` |
| MLB deploy script | `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh` |
| Deep dive plan | `docs/09-handoff/2026-04-04-DEEP-DIVE-PLAN.md` |

---

## Reference
- **Session 512 deep dive plan:** `docs/09-handoff/2026-04-04-DEEP-DIVE-PLAN.md`
- **Session 511 handoff:** `docs/09-handoff/2026-04-04-SESSION-511-DEEP-DIVE-HANDOFF.md`
- **Session 508 (pick drought):** memory `session-508.md`
- **Session 509 (GCP costs):** memory `session-509.md`
- **Model dead ends:** `docs/06-reference/model-dead-ends.md`
- **Cost reduction plan:** `docs/08-projects/current/gcp-cost-optimization/03-COST-REDUCTION-PLAN-2026-04-02.md`
