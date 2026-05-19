# Session Handoff — 2026-05-18-3 — post-review hot fixes + strategic plan

**Predecessors:**
- [`2026-05-18-edge-window-pytest-and-grading-divergence.md`](2026-05-18-edge-window-pytest-and-grading-divergence.md) — opening handoff with the 11-item open list
- [`2026-05-18-2-grading-fix-cf-phase1-and-decommission.md`](2026-05-18-2-grading-fix-cf-phase1-and-decommission.md) — mid-session handoff after the 10 items shipped

This handoff supersedes the "First message for the next session" block in `2026-05-18-2`. After that handoff was written, a 3-agent review surfaced gaps in the decommission execution; this session knocked out those hot fixes and rewrote the next-session plan.

## TL;DR

- **5 hot fixes** shipped in `a51a5bb3` covering consumers the original decommission missed (Phase 4→5 orchestrator, lineup processor, 2 monitoring files, admin_dashboard, pre-commit hook glob bug).
- **3-agent review verdicts on yesterday's judgment calls**: grading rule change RIGHT/HIGH, decommissioning RIGHT/HIGH, declining isotonic RIGHT/MED-HIGH, --set-secrets bulk fix RIGHT/HIGH, CF Phase 1 with empty eligible set DEFENSIBLE-BUT-FRAGILE/MED.
- **Edge-0.38 anomaly answered**: 5/18 BB picks were all `signal_rescued=TRUE` with signal_count 3-8. Working as designed for TIGHT regime, not a bug.
- **Verification queries fire too early**: at 11:45 PM ET 5/18 (when this ran), grading hasn't run for 5/18 yet, CF evaluator fires at 11:30 AM ET 5/19, MPD populates after grading. Re-run them tomorrow morning.
- **Strategic plan**: Session 1 is now a SHORT cleanup sweep with a few remaining items; the real strategic question for Session 2+ is NBA grading audit (does NBA have hidden quality gates like MLB did?) or scoping a binary side-model for the regressor.

## Commits (post-decommission review)

| Commit | What |
|---|---|
| `a51a5bb3` | 6 hot fixes: Phase 4→5 orchestrator, lineup processor decommission, freshness/stall monitors, admin_dashboard firestore_service, pre-commit hook glob bug |

## Reviewer consensus

All three reviewers agreed yesterday's judgment calls hold. Verdicts:

| Decision | Verdict | Confidence | Note |
|---|---|---|---|
| Grading rule → DK (0.33 IP) | RIGHT | HIGH | All 7 voided BB picks were structurally losses — old rule was selectively suppressing losers |
| Decommission `pitcher_ml_features` | RIGHT | HIGH | 8/10 V1/V2 features hardcoded zero, no production code reads the table |
| Decline isotonic calibration | RIGHT | MED-HIGH | Constant-0.5 baseline beat every calibrator; rank-ordering carries near-zero signal |
| Bulk `--set-secrets` fix | RIGHT | HIGH | `--update-secrets` is additive on fresh services; closes a real footgun |
| CF Phase 1 with empty eligible set | **DEFENSIBLE-BUT-FRAGILE** | MED | At MLB volume (~4-6 picks/day) the N≥20-over-7-days bar is reachable for maybe 1 filter in 30 days |

**Meta-question raised by the critical reviewer**: yesterday's grading audit revealed reported MLB BB HR was 58.33% under the void rule and 53.85% under what bettors actually face — a 4.48pp inflation. NBA grading may have the same kind of hidden quality gates. Reported NBA BB HR is 63.8% on 654 picks; that number deserves the same audit before more model/filter decisions get made against it.

## Hot fixes shipped this session — what changed

### `orchestration/cloud_functions/mlb_phase4_to_phase5/main.py`

`EXPECTED_PROCESSORS` was `['pitcher_features', 'lineup_k_analysis']`. With Phase 4 producers both gone, `completed_count >= 2` is unreachable. Set to `[]`. The orchestrator becomes effectively dormant; Phase 5 fires via the direct `mlb-predictions-generate` Cloud Scheduler at 8 AM ET (13:00 UTC) and is on its own critical path.

### `data_processors/precompute/mlb/main_mlb_precompute_service.py`

`MlbLineupKAnalysisProcessor` removed from `MLB_PRECOMPUTE_PROCESSORS` and `MLB_PRECOMPUTE_TRIGGERS`. Its output table was dropped yesterday; the processor would fail every BQ write today. Input (`mlb_raw.mlb_lineup_batters`) has 8/14 days of coverage — already flagged as vapor. Class imports kept for revival.

### `monitoring/mlb/mlb_freshness_checker.py`

`pitcher_ml_features` entry removed. Was emitting permanent "stale" alerts after the table was dropped.

### `monitoring/mlb/mlb_stall_detector.py`

`precompute` stage entry removed. The `predictions` stage's `depends_on` chain updated: was `'precompute'`, now `'analytics'` (since precompute is gone from the critical path).

### `services/admin_dashboard/services/firestore_service.py`

`get_mlb_phase4_status` previously listed `pitcher_features` and `lineup_k_analysis` as required. Now returns `required_processors = []` and `is_complete = True` always. The dashboard would have shown false negatives indefinitely otherwise.

### `.pre-commit-hooks/validate_set_secrets.py`

Glob handling bug: the `('.', 'cloudbuild*.yaml')` PATTERN entry was hitting the literal filename equality branch (because the pattern doesn't start with `*`). **None of the 6 root cloudbuild files were actually scanned.** Switched to `fnmatch.fnmatch` when any glob character is present. Hook now checks 355 files (was 346). No new violations surfaced — the bulk replace earlier got everything.

## What the reviewers didn't fix

Tech reviewer's MED-severity finding that I'm intentionally leaving for next session:

**`away_over_blocked_policy` demotion produces double-audit-row.** In `ml/signals/mlb/best_bets_exporter.py:714`, when AOB is demoted to OBSERVATION the pick falls through to `away_edge_floor` which then BLOCKs it (most away picks have edge < 1.25). So a demoted AOB pick still doesn't reach edge_eligible — it just gets re-blocked one step later, producing two audit rows for the same pick. CF math is correct (joins on `filter_name`), but the OBSERVATION evidence for AOB demotion will be near-zero, meaning we can't ever validate the demotion. Worth addressing if/when `away_over_blocked_policy` becomes a Phase 2 auto-demote candidate. Fix would be to skip the away_edge_floor block when AOB is demoted, or to lower AWAY_EDGE_FLOOR alongside an AOB demotion.

## Strategic plan — Session 1+ priorities (from the Plan agent)

### Session 1 (next): verification + finish cleanup (~30 min)

1. **Re-run verification queries** — they were too early last night. Run again tomorrow morning:
   - MPD for `catboost_mlb_v2_regressor_36f_20260517` (grace through 5/22)
   - `filter_counterfactual_daily` rows for 5/18 (CF fires 11:30 AM ET)
   - 5/18 grading short_start void check (should be 0 voids with IP ≥ 0.33)
   - Sentry `nav_stuck:*` events from props-web telemetry

2. **NEW: spot-check the grading backfill HR continuity in dashboards.** The 4.48pp HR shift between pre-/post-backfill is a real cliff in any dashboard that compares "this week vs last month". Either annotate the boundary in `/daily-steering` and `/mlb-best-bets-config`, or add a flag to skip pre-backfill dates from rolling comparisons. ~15 min.

3. **5/22 calendar reminder**: `fleet_in_transition` grace for `catboost_mlb_v2_regressor_36f_20260517` expires. If the regressor hasn't accumulated MPD rows passing health gates by then, picks halt. Set a reminder to check halt_state on 5/23 morning.

### Session 2 — pick ONE thread

**Path A (Recommended): NBA grading audit.** Critical reviewer's meta-question. Same kind of audit we did for MLB: search NBA grading for hidden quality gates that void picks book-grade outcomes would have paid (DNP voids on minutes thresholds, etc.). If NBA HR is also inflated by 3-5pp, that re-baselines every week-old model/filter decision. ~2 hours.

**Path B: CF evaluator MLB-volume tuning.** At ~4-6 BB picks/day, the N≥20-over-7-days bar is too high for MLB. Lower it specifically for the MLB evaluator (e.g., N≥10 over 5 days, OR rolling cumulative N≥30). Keep the NBA hook's bar unchanged. ~1 hour analysis + ~30 min code.

### Session 3+ — binary side-model for the regressor

Per the isotonic findings, the regressor's raw edge has near-zero binary predictive power (45.2% HR at edge 1.0-1.5 OVER, sigmoid claims 67%). Calibrators can't add signal — only a side-model with new features can.

Spec:
- Inputs: `predicted_K, edge, line_level, opponent_k_rate, batter_k_rate, weather, park_factor` (and whatever else `pitcher_loader.py` already serves)
- Target: `prediction_correct` (binary)
- Model: small XGBoost or logistic regression
- Train on 729 graded picks (2026 season); shadow-only until N≥100 BB-level CF HR confirms signal

Reuse data-prep from `scripts/mlb/isotonic_calibration_analysis.py`. Multi-session.

## Explicit defers

| Item | Revisit trigger |
|---|---|
| `halt_overrides` writer fix | An incident requires a manual override that gets clobbered |
| MPD recovery lag (24h+ floor) | After binary side-model lands; current mitigations work |
| Frontend nav fix | 3+ Sentry `nav_stuck:*` events with consistent payload |
| Isotonic calibration | N≥2000 graded AND a regressor retrain that targets calibration |
| Phase 2 CF auto-demote enablement | After NBA audit + MLB eligibility bar fix |
| NBA work (broader) | Off-season; out of scope per project memory |
| Orphan scrapers (`mlb_ballpark_factors`, `mlb_statcast_pitcher`) | A model experiment actually wants their features |

## First message for the next session

```
Read docs/09-handoff/2026-05-18-3-post-review-hot-fixes-and-strategic-plan.md.

Verification first (these should now have data — re-run from yesterday's 11:45 PM ET attempt):

1. MPD freshness for the new regressor:
   bq query --use_legacy_sql=false 'SELECT game_date, model_id, decay_state, hr_7d, n_7d FROM `nba-props-platform.mlb_predictions.model_performance_daily` WHERE game_date >= CURRENT_DATE()-7 AND model_id LIKE "catboost_mlb_v2_regressor%20260517" ORDER BY game_date DESC LIMIT 3'

2. CF evaluator rows for 5/18 (fired at 11:30 AM ET 5/19):
   bq query --use_legacy_sql=false 'SELECT filter_name, blocked_count, wins, losses, counterfactual_hr FROM `nba-props-platform.mlb_predictions.filter_counterfactual_daily` WHERE game_date = "2026-05-18" ORDER BY blocked_count DESC'

3. 5/18 grading at the new DK threshold (first real-world run under MIN_IP=0.33):
   bq query --use_legacy_sql=false 'SELECT void_reason, COUNT(*) AS n, MIN(innings_pitched) AS min_ip, MAX(innings_pitched) AS max_ip FROM `nba-props-platform.mlb_predictions.prediction_accuracy` WHERE game_date = "2026-05-18" GROUP BY 1 ORDER BY n DESC'

4. Sentry: search for `nav_stuck:*` events. Any landed? Each `extra` block has target_path, visibility_state, hidden_total_ms.

Then two short cleanup items (~30 min total):

(a) Spot-check that yesterday's grading backfill HR cliff isn't surfacing in /daily-steering or /mlb-best-bets-config dashboards. The 53.85% post-backfill BB HR replaces the previously-cached 58.33%; if any rolling comparisons span the boundary they'll show a fake 4.48pp drop. Annotate the boundary if it shows.

(b) Calendar reminder for 5/22: fleet_in_transition grace for catboost_mlb_v2_regressor_36f_20260517 expires. Check halt_state on 5/23 morning — if the regressor hasn't accumulated passing MPD rows by then, picks may halt.

Then the strategic Session 2 question — pick ONE thread:

Path A (Recommended): NBA grading audit. Reported NBA BB HR is 63.8% on 654 graded picks. The MLB MIN_IP audit revealed a 4.5pp HR inflation from a "quality gate" no book honors. Run the same audit on NBA grading. If NBA is also inflated, every model/filter decision needs re-baselining. ~2h.

Path B: Lower the CF evaluator's MLB eligibility bar. At MLB volume (4-6 picks/day) N≥20-over-7-days is unreachable; CF Phase 1 will collect dust. Drop to N≥10-over-5-days OR rolling cumulative N≥30, MLB-only. ~1.5h.

Session 3+ is the binary side-model thread (regressor probability quality) — only worth starting when Path A or B is done.

Defers and revisit triggers in the handoff doc.
```

## Session totals (cumulative across both 5/18 sessions)

11 commits in `nba-stats-scraper` + 2 in `props-web`. All 11 items from the original open list closed or explicitly deferred with reasoning. The reviewer post-mortem caught 5 follow-on issues that we also closed this session.

| # | Item | Status |
|---|---|---|
| 1 | MLB grading rule → DK (0.33 IP) + 58-row backfill | shipped + verified |
| 2 | BB hero `<50%` color (red → muted brick) | shipped (props-web) |
| 3 | MLB filter CF evaluator Phase 1 | shipped + scheduled |
| 4 | Stuck-nav Sentry telemetry | shipped (props-web) |
| 5 | 9 stale `test_worker_integration.py` tests rewritten | shipped, 11/11 pass |
| 6 | Dead-`download()` overrides removed (2 MLB scrapers) | shipped |
| 7 | 3 new pre-commit hooks + 11-file --set-secrets fix | shipped (hook glob bug fixed in 3rd handoff) |
| 8 | `/mlb-best-bets-config` skill | shipped |
| 9 | `pitcher_ml_features` orphan pipeline decommissioned | shipped + follow-on hot fixes |
| 10 | Isotonic calibration — analysis only, recommended NOT to deploy | analysis shipped |
| 11 | Phase 4→5 orchestrator + monitoring + admin_dashboard cleanup | shipped this session |

What's left for next session is verification + ~30 min of small cleanup, then the strategic NBA grading audit OR CF eligibility bar tuning.
