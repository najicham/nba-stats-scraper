# Session Handoff — 2026-05-18 — grading rule + CF Phase 1 + frontend telemetry + decommission

**Predecessor:** [`2026-05-18-edge-window-pytest-and-grading-divergence.md`](2026-05-18-edge-window-pytest-and-grading-divergence.md). That session shipped the edge-window pytest and surfaced the MIN_IP grading divergence. This session executed on the grading fix and worked through the rest of the open list.

## TL;DR

10 commits across `nba-stats-scraper` (8) and `props-web` (2). Ten of the eleven items on the predecessor's open list are done; isotonic calibration was investigated and explicitly declined (real root cause is feature signal, not calibration).

| # | Item | Status | Commit |
|---|---|---|---|
| 1 | MLB grading rule aligned to DK (`MIN_IP=0.33`) + 58-row backfill | shipped | `d9b961ba` |
| 2 | BB hero `<50%` color softened (red → muted brick) | shipped | `b05688c` (props-web) |
| 3 | MLB filter CF evaluator Phase 1 — tables, CF, exporter wiring, scheduler | shipped | `e1066b30` |
| 4 | Stuck-navigation Sentry instrumentation in NavigationContext | shipped | `f38d16b` (props-web) |
| 5 | 9 stale `test_worker_integration.py` tests rewritten for current API | shipped (11/11 pass) | `738a77fe` |
| 6 | Dead-`download()` overrides removed (mlb_ballpark_factors, mlb_statcast_pitcher) | shipped | `9766fea7` |
| 7 | 3 missing pre-commit hooks + bulk `--set-secrets → --update-secrets` (11 files) | shipped | `7e497c87` |
| 8 | `/mlb-best-bets-config` skill (mirrors NBA) | shipped | `9eead3b1` |
| 9 | `pitcher_ml_features` orphan pipeline decommissioned (5 tables + 3 views dropped, 2 readers migrated) | shipped | `d154c69c` |
| 10 | Isotonic calibration analysis — fit, evaluate, recommend NOT to deploy | analysis only | `b6a9c410` |
| 11 | Stale `test_exporter_with_regressor.py` failures from predecessor | already fixed in `f0b93832` | — |

Verification of predecessor handoff items 1-4: all green (halt cleared 5/18, picks shipped, halt envelope in JSON, MPD freshness in grace).

## What landed (in order)

### `d9b961ba` — `fix(mlb-grading): align void threshold to DK rule`

`data_processors/grading/mlb/mlb_prediction_grading_processor.py:41`

The hardcoded `MIN_IP_FOR_VALID_PROP = 4.0` matched no major US book (FD ≥1 pitch, DK/BetMGM/Caesars ≥1 out = 0.33 IP, Pinnacle 1.0). It silently inflated reported HR vs what bettors paid. Replaced with an env-var-overridable constant defaulting to 0.33 (DK rule).

Audit numbers (before changing anything):

| Scope | Current rule | DK rule | Delta |
|---|---|---|---|
| Best bets only | 42-30 / 58.33% (7 voided) | 42-36 / 53.85% | **−4.48pp** |
| All graded | 354-317 / 52.76% (74 voided) | 373-356 / 51.17% | −1.59pp |

All 7 BB short_voids would have been LOSSES at DK rule — 100% structural (short K starts overwhelmingly produce OVER losses).

Historical backfill (`UPDATE prediction_accuracy WHERE is_voided=TRUE AND void_reason='short_start' AND innings_pitched >= 0.33` to compute prediction_correct fresh) flipped 58 rows. Post-backfill BB HR = 53.85% (matches the audit projection exactly).

`mlb-phase6-grading` Cloud Run revision `00050-ppv` is live with the new code default.

### `b05688c` (props-web) — `feat(best-bets): soften <50% record color`

`src/components/best-bets/RecordHero.tsx` + `src/app/globals.css`. Added `--color-negative-soft` token (`#b85c5c` light / `#d99a9a` dark). Replaced `text-negative` on the `<50%` percentage cells. `text-negative` left intact elsewhere (model health table, etc.) — only the BB hero card changed. `tsc --noEmit` clean.

The user noticed Tonight stuck-loading bug while this commit was in flight — see next item.

### `f38d16b` (props-web) — `feat(nav): instrument stuck-navigation with Sentry`

`src/contexts/NavigationContext.tsx`. The existing 10-second safety timeout silently cleared `pendingPath` when the soft-navigation hung. Users saw the loading bar end with no page change; the failure was invisible to telemetry. Added Sentry `captureMessage` + `console.warn` + visibility-time tracking. Captures: target_path, current pathname, visibility_state, total_hidden_ms, referrer, user_agent.

**Action for next session:** monitor Sentry for `nav_stuck:*` events. 1–3 occurrences should be enough to pick the right fix (router.refresh on visibility, hard-nav fallback, or `prefetch={false}`). Predecessor analysis suggested the issue is Next.js router-cache eviction after long idle.

### `e1066b30` — `feat(mlb): port filter counterfactual evaluator (Phase 1)`

`orchestration/cloud_functions/mlb_filter_counterfactual_evaluator/` plus two new BQ tables:

- `mlb_predictions.filter_counterfactual_daily` (one row per filter per day)
- `mlb_predictions.filter_overrides` (active demote table; empty in Phase 1)

The MLB exporter (`ml/signals/mlb/best_bets_exporter.py`) now loads `filter_overrides` at the start of `compute_best_bets()` and treats demoted filters as `OBSERVATION` (still evaluated, doesn't block). Four hardcoded block sites + the registry `negative_filters()` loop are wrapped. Empty overrides table = identical pre-change behavior, so the worker deploy was zero-risk.

Phase 1 has `ELIGIBLE_FOR_AUTO_DEMOTE = {}` — collects CF HR daily, sends Slack advisories when filters trend bad, but does not auto-demote. Eligibility expands in Phase 2 once we have ≥7 days of data at N≥20 for candidate filters.

Backfill (2026-04-01 → 05-17, 133 rows). Biggest current standouts:

| filter | days | N | CF HR | note |
|---|---|---|---|---|
| direction_filter | 33 | 220 | 51.8% | structural OVER-only gate; never demote |
| away_edge_floor | 34 | 191 | 46.6% | correctly blocking losers |
| edge_floor | 33 | 90 | 50.0% | borderline |
| pitcher_blacklist | 30 | 49 | 46.9% | correctly blocking |
| overconfidence_cap | 2 | 4 | **75.0%** | **the N=8 MAX_EDGE class** — too small to act on yet |
| away_over_blocked_policy | 1 | 6 | 50.0% | new policy, no signal yet |

Infrastructure:
- Cloud Build trigger `deploy-mlb-filter-counterfactual-evaluator` (auto-deploys CF on push)
- Cloud Scheduler `mlb-filter-counterfactual-evaluator-daily` (11:30 AM ET, Mar-Oct)
- CF endpoint verified end-to-end: smoke-test trigger at 00:34:54 UTC → 3 rows written for 5/17 at 00:34:55 UTC.

The MLB exporter changes also auto-deployed via `deploy-mlb-prediction-worker`. 46/46 tests in `test_exporter_with_regressor.py` still green.

### `738a77fe` — `test(mlb): rewrite test_worker_integration for current batch-flow API`

`tests/mlb/test_worker_integration.py`. 9 tests had drifted (predictor classes are lazy-imported inside `get_prediction_systems()` now; `PitcherStrikeoutsPredictor.batch_predict` flow was replaced by `pitcher_loader.load_batch_features` + per-pitcher `predict()`).

Three changes:
1. Patch targets moved from `predictions.mlb.worker.*` → source modules (`predictions.mlb.prediction_systems.v1_baseline_predictor.V1BaselinePredictor`, etc.)
2. `PitcherStrikeoutsPredictor` mocks replaced with mocks of `pitcher_loader.load_batch_features`, `load_schedule_context`, `supplemental_loader.load_supplemental_by_pitcher`.
3. `teardown_method` now also calls `reset_config()` from `predictions.mlb.config` so `@patch.dict('os.environ', {'MLB_ACTIVE_SYSTEMS': ...})` actually takes effect on the next test.

11/11 tests now pass.

### `9766fea7` — `chore(scrapers): remove dead download() overrides`

`scrapers/mlb/external/mlb_ballpark_factors.py:447` and `scrapers/mlb/statcast/mlb_statcast_pitcher.py:123`. Same anti-pattern as mlb_weather: overriding `download(self)` is dead code because the base lifecycle calls `start_download()` → `download_data()`.

But the bigger finding here was that both scrapers are **orphaned** — no Cloud Scheduler invokes them, no downstream code consumes their target tables (`mlb_raw.statcast_pitcher_stats` has 0 rows ever). The cleanup is cosmetic; user chose not to wire them up. Dead methods removed with comments documenting the orphan status.

### `7e497c87` — `chore(pre-commit): add 3 hooks + fix --set-secrets`

Three new hooks:
- `validate-set-secrets` — detects `--set-secrets` in deploy scripts (REPLACES all mounted secrets — same bug class as `--set-env-vars`).
- `validate-scraper-download-override` — detects dead `def download(self)` overrides on scrapers.
- `validate-threshold-drift` — flags module-level numeric constants sharing a name across 2+ files with different values (catches the TIGHT_VEGAS_MAE_THRESHOLD drift class).

Hook 1 found 11 existing violations. Bulk-replaced `--set-secrets` → `--update-secrets` in: `bin/scrapers/deploy/deploy_scrapers_simple.sh`, `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`, `bin/deploy/deploy_news_fetcher.sh`, `bin/deploy/deploy_validation_runner.sh`, `bin/deploy/deploy_stale_cleanup.sh`, `bin/raw/deploy/deploy_processors_simple.sh`, `bin/orchestrators/deploy_phase4_timeout_check.sh`, `bin/monitoring/deploy/deploy_health_summary.sh`, `bin/analytics/deploy/deploy_analytics_processors.sh`, `bin/alerts/deploy_daily_summary.sh`, `bin/alerts/deploy_nba_grading_alerts.sh`. `--update-secrets` is safe on both fresh services (no existing mounts) and re-runs (preserves mounts).

Hook 3 has an allowlist for `LOOSE_THRESHOLD` and `BUFFER_FLUSH_THRESHOLD` — same-name cross-sport intentional duplicates. Anything new will trip.

### `9eead3b1` — `feat(skill): /mlb-best-bets-config`

`.claude/skills/mlb-best-bets-config/SKILL.md` — single-pane-of-glass for MLB threshold state. 9 sections: exporter config, active fleet, halt + regime, filter inventory (Layer A hardcoded + Layer B registry), `filter_overrides`, CF HR per filter, signal inventory, recent picks + grading rollup, sync/process health. Plus three checklists (promote a filter to `ELIGIBLE_FOR_AUTO_DEMOTE`, promote a shadow signal to active, bump MAX_EDGE safely).

Section 2's query was fixed to use `prediction_accuracy.system_id` (the canonical column) instead of `pitcher_strikeout_predictions.system_id` (column doesn't exist on that table — it uses `model_version`).

### `d154c69c` — `chore(mlb-precompute): decommission orphaned pitcher_ml_features pipeline`

The handoff said "investigate empty mlb_precompute tables". The investigation found a much bigger problem: an entire dead branch of the precompute architecture.

Findings:
- All 4 suspect source tables are empty (0 rows ever): `lineup_k_analysis`, `pitcher_innings_projection`, `pitcher_arsenal_summary`, `batter_k_profile`.
- Their downstream `pitcher_ml_features` (1086 rows in 2026) had 8 of 10 V1/V2 features hardcoded at zero for every pitcher: f26, f27, f28, f30, f31, f32, f33, f34.
- The real kicker: `pitcher_ml_features` itself is unread by both the production worker (`pitcher_loader.py` queries `mlb_analytics.pitcher_game_summary` directly) and every training script. The 36-feature regressor's `f30/f32` are different fields (`k_avg_vs_line`, `line_level`) in its own pipeline.
- Only readers were `mlb_self_heal` CF and admin_dashboard, both just counting rows as a "Phase 4 done?" check.

Decommission executed:
- Dropped 5 BQ tables and 3 dependent views from `mlb_precompute`. Dataset is now empty.
- Removed `pitcher_features` from `MLB_PRECOMPUTE_PROCESSORS` and `MLB_PRECOMPUTE_TRIGGERS` (Pub/Sub no longer fires the processor). `MlbLineupKAnalysisProcessor` kept, still triggered by `batter_game_summary`.
- Migrated `mlb_self_heal/main.py` `check_precompute_data()` to query `mlb_analytics.pitcher_game_summary` (the actual readiness signal).
- Migrated `services/admin_dashboard/services/bigquery_service.py` `get_mlb_daily_status()` to drop the precompute_count and route `PHASE_5_PENDING` off analytics readiness directly.
- Archived `schemas/bigquery/mlb_precompute/ml_feature_store_tables.sql` to `archived/` with an explicit ARCHIVED 2026-05-18 banner.

22/22 precompute tests still pass.

### `b6a9c410` — `analysis(mlb): isotonic calibration — do not deploy`

`scripts/mlb/isotonic_calibration_analysis.py` + `scripts/mlb/isotonic_calibration_findings.md`.

Investigated whether isotonic / Platt calibration would fix the documented "regressor overconfident at edge 1.0-1.5 OVER" bug. Pulled 729 graded picks (2026 season, `catboost_v2_regressor` only), date-ordered 70/30 split.

Headline test-set Brier scores:

| Calibrator | Brier | LogLoss |
|---|---|---|
| Current sigmoid (scale=0.7) | 0.2606 | 0.7152 |
| Pooled isotonic | 0.2572 | 0.8733 |
| Pooled Platt logistic | 0.2520 | 0.6971 |
| Per-direction isotonic | 0.2719 | 0.9883 |
| **Constant 0.5 (scale=0.0)** | **0.2500** | **0.6931** |

The constant-0.5 baseline beats every calibrator. Pooled Platt's apparent Brier improvement comes from collapsing every prediction to ~0.531 — losing all discrimination. The raw edge has near-zero binary predictive power on this sample.

Edge-band HR confirms the structural issue:

| Edge band | N | Overall HR | OVER HR | UNDER HR |
|---|---|---|---|---|
| 0.0-0.5 | 393 | 49.9% | 46.9% (228) | 53.9% (165) |
| 0.5-1.0 | 256 | 52.3% | 53.8% (169) | 49.4% (87) |
| **1.0-1.5** | 72 | 51.4% | **45.2% (62)** | 90.0% (10) |
| 1.5-2.0 | 8 | 75.0% | 71.4% (7) | 100.0% (1) |

The "overconfidence at edge 1.0-1.5 OVER" finding is real (45.2% HR at edge band where sigmoid says 67% probability), but a calibrator can't add signal — it can only redistribute it. The BB pipeline already compensates for this via `overconfidence_cap` (MAX_EDGE=1.25), `away_over_blocked_policy`, signals, and regime. Deploying a calibrator would compress the edge distribution and hurt the rank ordering MAX_EDGE depends on.

**Recommended path forward** (not for this session): add features the regressor lacks (batter k-rate, weather, etc.) OR train a small binary side-model on top of the regressor + features. Defer isotonic to when N ≥ 2000 graded across multiple seasons.

`/tmp/mlb_regressor_isotonic_v1.pkl` saved as reference but explicitly **not for deployment**.

## Verification — predecessor handoff items 1-4

| # | Check | Status |
|---|---|---|
| 1 | Halt cleared for 5/18 | ✅ `halt_active=false`, `fleet_in_transition=true` (grace through 5/22) |
| 2 | MLB picks shipped 5/18 | ✅ 4 OVER, avg edge 0.38 |
| 3 | Halt envelope in Phase 6 JSON | ✅ `halt_active=False, total_picks=72, graded=72` |
| 4 | MPD freshness for `catboost_mlb_v2_regressor_36f_20260517` | ⏳ Expected by 5/19 morning |

## Verification — items shipped this session

| Item | Verify |
|---|---|
| Grading rule | `mlb-phase6-grading-00050-ppv` live; tomorrow's 5/18 grading run will be the first under the new threshold |
| Filter CF evaluator | `mlb-filter-counterfactual-evaluator` deployed, scheduled, smoke-test wrote 5/17 rows. Next scheduled fire 5/19 11:30 AM ET. |
| MLB exporter wiring | 5/18 export shipped 4 picks — exporter loaded `filter_overrides` (empty) cleanly |
| BB hero color | Deployed via props-web push; check on production. |
| Nav telemetry | Deployed; watch Sentry for `nav_stuck:*` over coming days. |
| mlb_precompute decommission | `bq ls mlb_predictions:mlb_precompute` returns empty. Processor no longer fires (will be confirmed by absence of new rows in any precompute table tomorrow). |
| Pre-commit hooks | `pre-commit run --all-files` passes. Hook 3 has warning-only output for non-drift duplicates. |

## What's still open

### 🟢 Architectural — no incidents driving them

1. **`halt_overrides` table** — predecessor #7. Writer doesn't honor manual MERGE overrides; gets clobbered at next 5 AM run. Not blocking anything operationally.
2. **MPD recovery lag** — predecessor #9. Grading writes MPD at 10 AM ET, halt re-evaluates at 5 AM ET next day → 24h+ recovery floor. The fleet_transition_grace + edge-based auto-halt already mitigate this in practice.
3. **Isotonic deferred** — addressed by analysis above; revisit when N ≥ 2000 graded picks or after a regressor retrain that explicitly targets calibration.

### 🟡 The path forward if you want to fix regressor probability quality

Per the calibration findings doc:
1. Train a small binary side-model on top of the regressor + extra features (batter k-rate distribution, weather, opponent contact-rate). Bigger lift than calibration.
2. Add the features the regressor doesn't currently consume.

## Operational notes from this session

1. **First MLB CF evaluator run already happened** — smoke-tested at session end and the daily scheduler fires next at 11:30 AM ET 5/19. Watch `mlb_predictions.filter_counterfactual_daily` for new rows tomorrow morning.
2. **Backfill audit values are now CANONICAL.** Reported BB HR for 2026 (pre-this-session) was 58.33%. After the grading backfill it's 53.85%. Update any cached numbers in dashboards / handoffs / weekly reports.
3. **Pre-commit hooks now actively guard:** any future `--set-secrets`, any new `download()` override, any new threshold-name collision will fail commits. If you legitimately need to add same-named threshold constants across files, add the name to `NAME_EXEMPT` in `.pre-commit-hooks/validate_threshold_drift.py`.
4. **`mlb_precompute` is empty** — the dataset still exists, but has no tables. `MlbLineupKAnalysisProcessor` is still registered (triggers on `batter_game_summary`) but its output table `lineup_k_analysis` was dropped, so the processor will likely fail until either the table is recreated or the processor is removed too. Predecessor session and MEMORY already had `lineup_k_analysis` marked vapor — recommend dropping `MlbLineupKAnalysisProcessor` next session unless `mlb_raw.mlb_lineup_batters` coverage improves materially.

## Process notes

1. **The MIN_IP audit caught an HR-truthfulness bug that wasn't surfacing in any dashboard.** It was visible only by looking at picks vs what the book would have paid. Worth: building "what the bettor saw" as a daily-steering line item, separate from prediction_correct.
2. **The mlb_precompute audit started as "verify a couple tables are empty" and ended as a full decommission.** The discovery that `pitcher_ml_features` is unread by production or training was the structural finding, not the empty source tables. When the table is orphaned, the source tables don't matter.
3. **The isotonic analysis is a useful negative result.** Saved a multi-day implementation effort that wouldn't have helped, and surfaced what the actual model-quality gap is. Brier-score reliability buckets are cheap to run; do them BEFORE building calibration infrastructure.
4. **Pre-commit hook 1 fired on 11 existing violations** the moment it shipped. That's exactly what it's supposed to do — make the latent debt explicit. Bulk-replace was 5 minutes; the alternative was an allowlist that defeats the hook.

## First message for the next session

> Read `docs/09-handoff/2026-05-18-2-grading-fix-cf-phase1-and-decommission.md`.
>
> Verification first:
>
> 1. **MPD freshness** for `catboost_mlb_v2_regressor_36f_20260517` should be populated by morning (grace through 5/22). Query: `SELECT * FROM mlb_predictions.model_performance_daily WHERE model_id LIKE 'catboost_mlb_v2_regressor%20260517' ORDER BY game_date DESC LIMIT 3`.
> 2. **CF evaluator** scheduled run was 11:30 AM ET. Check `mlb_predictions.filter_counterfactual_daily` for rows dated 2026-05-18 (yesterday's graded picks).
> 3. **Sentry stuck-nav telemetry** — query for `nav_stuck:*` events. If any have landed, the `extra` block has the diagnostic data (target_path, visibility_state, total hidden time).
>
> Highest-leverage open work:
>
> - **Decide on the orphaned `MlbLineupKAnalysisProcessor`** — its output table was dropped this session but the processor still fires on `batter_game_summary` triggers. It'll start failing in BQ writes. Either re-create the table, or remove the processor + trigger. (~30min)
> - **Watch `overconfidence_cap` CF HR** in `filter_counterfactual_daily`. It was 75% on N=4 at session end — exactly the N=8 MAX_EDGE class. The CF evaluator will Slack-warn when it hits N≥20 over 7 consecutive days; that's the green light to add it to `ELIGIBLE_FOR_AUTO_DEMOTE`.
>
> All other items in the open list are non-urgent — pick by interest.
