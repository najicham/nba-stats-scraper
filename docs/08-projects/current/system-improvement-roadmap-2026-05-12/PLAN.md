# System Improvement Roadmap — 2026-05-12

Synthesis of a 16-agent review fired this session (15 + 1 history-backfill spot-check), plus an investigation it triggered. Single source of truth for what to do next.

Predecessors:
- `docs/09-handoff/2026-05-11-EVENING-SPORT-LEAKAGE-MLB-IMPROVEMENT.md`
- `docs/08-projects/current/sport-leakage-elimination/PLAN.md`
- `docs/08-projects/current/mlb-improvements-2026-05/PLAN.md`

## What shipped earlier this session

| Commit | Repo | Subject |
|--------|------|---------|
| `43b30cc` | props-web | `fix(calendar): sport-gate useGameCounts so MLB pages don't snap to NBA's last game date` |
| `cc05044d` | nba-stats-scraper | `feat(mlb): add history-only mode to pitcher exporter + backfill script` (388 history files backfilled 2024-04-09 → 2026-05-03) |
| `65b60ce` | props-web | `ci(e2e): add GitHub Actions CI gate + tighten sport-render accept-state` |
| `df10b62f` | nba-stats-scraper | `fix(health-check): monitor MLB pitcher leaderboard + best-bets freshness` |

## Investigation finding (P0 — discovered by Agent 16 + verified)

**~13 days of MLB predictions with wrong team/opponent attribution.** 2026-03-28 through 2026-04-09. Predictions table contains ~290 rows/day, all with NULL `pitcher_name`. Most are `BLOCKED`. The ~9 OVER/UNDER picks per day have names but **wrong team/opponent fields**:

- `Davis Martin (CWS vs NYY)` — actual schedule: Davis Martin is CWS, opponent MIA
- `Chris Paddack (DET vs BOS)` — actual schedule: Chris Paddack is MIA, opponent CWS
- `Tomoyuki Sugano (BAL vs NYY)` — actual schedule: Tomoyuki Sugano is TOR, opponent COL

The history backfill faithfully wrote these to GCS. Estimated ~250 OU predictions in BQ with wrong attribution. Root cause is upstream (likely stale 2025 probables echoed into 2026 worker on early-season days). Low user blast radius today (most users don't navigate back to those specific dates) but real data garbage.

**Action options:**
1. Targeted re-export: write empty `tonight.starters` for 2026-03-28 → 2026-04-09 history files. Frontend renders clean empty state instead of wrong data. (~30 min)
2. Investigate root cause in prediction worker (probables-feed scraper, MLB schedule join) (~2-4 hr)
3. Frontend filter: hide BLOCKED + wrong-attribution picks (robust, ~1 hr)

## Priority ranking — full agent findings

### P0 — Critical, ship next session

| # | Finding | Source | Effort |
|---|---------|--------|--------|
| 1 | **MLB feature store half-dead.** `f00_k_avg_last_3, f01_k_avg_last_5, f02_k_avg_last_10, f03_k_std_last_10, f04_ip_avg_last_5, f05_season_k_per_9, f06_season_era, f07_season_whip, f15_opponent_team_k_rate` are **100% NULL** in `mlb_precompute.pitcher_ml_features` for 2026 season. `f11_home_away_k_diff, f13_day_night_k_diff, f14_vs_opponent_k_rate, f18_game_total_line, f19_team_implied_runs, f24_is_postseason` are 100% **literal-zero** (constants — CatBoost learns to ignore). Source data exists in `mlb_analytics.pitcher_game_summary` (1,062 rows / 225 pitchers for 2026) and `mlb_raw.bdl_pitcher_splits`. Single SQL aggregate in the precompute writer fixes `f05_season_k_per_9`. | Agent 1 | 1 day |
| 2 | **Morning empty-publish blackout** (3:45-10:45 AM PDT daily). 4-line guard in `mlb_pitcher_exporter.export()` to skip live `leaderboard.json` upload when `tonight.starters` is empty (still write date-keyed history sidecar). Frontend continues showing last good leaderboard until 10 AM PDT prediction run lands. | Agent 6 | 30 min |
| 3 | **MLB `is_home` column missing** on `mlb_predictions.signal_best_bets_picks` BQ schema (47 cols, only `team_abbr` / `opponent_team_abbr`). Exporter `mlb_best_bets_exporter.py:227` reads `bool(row.get('is_home'))` → always False. Silent data corruption on every home/away pick analysis. Files: `mlb_best_bets_exporter.py:227`, `ml/signals/mlb/best_bets_exporter.py:1074-1104`, `schemas/bigquery/mlb_predictions/signal_best_bets_picks.json`. | Agents 5, 7 | 1 hr |
| 4 | **2026-03-28 → 2026-04-09 MLB predictions corrupted** (~13 days, wrong opponents, NULL pitcher_name, mostly BLOCKED). Backfill correctly reflected this upstream bug. See investigation above. | Agent 16 + verification | 30 min - 4 hr |
| 5 | **Sentry `stuck_loading:mlb` → NO Slack route.** Sentry events firing into the void today. Sentry console rule: `event.tags.stuck_loading CONTAINS ":mlb"` → `#nba-alerts`. | Agent 10 | 30 min |

### P1 — High-impact, this week

| # | Finding | Effort |
|---|---------|--------|
| 6 | **`mlb-oddsa-pitcher-props-pregame` fires 4 hours early** (cron `30 12 UTC` = 8:30 AM ET; other pregame jobs run 12:30 PM ET). Same bug class as Session 515 timezone fix. Fix: `gcloud scheduler jobs update http mlb-oddsa-pitcher-props-pregame --location=us-west2 --time-zone="America/New_York" --schedule="30 12 * * *"` | 1 cmd |
| 7 | **21 MLB schedulers unrestricted to season window.** Should have `* 3-10 *` month restriction like `mlb-pitcher-export-pregame` does. Currently fires year-round (waste invocations + alert noise). | 1 day |
| 8 | **`/mlb/results` page fully broken.** 4 compounded NBA-implicit fetches: `fetchResultsByDate` (lib/api.ts:305), `fetchSystemPerformance` (lib/api.ts:340), `fetchYesterdayBestBets` (lib/api.ts:293), plus already-fixed `useGameCounts`. Every MLB user hitting `/mlb/results` sees NBA picks + NBA system performance + NBA recap. | 1 day |
| 9 | **NBA prediction grading silently broken.** `prediction_accuracy.prediction_correct` is NULL on 80-95% of gradable rows for Apr 12 (e.g. 428 gradable_but_ungraded out of 748). Pipeline stopped grading mid-April. Affects every downstream HR analysis, decay state machine, filter CF HR, retrain governance. No alert today. | Investigate + fix |
| 10 | **MLB edge-based auto-halt port** (NBA's `regime_context.py`). Reviewer 4 design: separate `ml/signals/mlb_regime_context.py` (not shared module), thresholds `avg_edge < 0.50 AND pct_0.75+ < 10% AND days_sampled >= 5`, ship in observation mode first, write `mlb_orchestration.halt_state` table (doesn't exist yet). | 4-6 hr |
| 11 | **PitcherModal eager-loaded** at `src/app/providers.tsx:21` → recharts (~293 KB) ships to every `/nba/*` page. Pattern is already proven for PlayerModal — `lazy(() => import("./PitcherModal"))` + `<Suspense>` cuts ~290 KB off NBA bundle. | 30 min |
| 12 | **Wire Playwright into `.github/workflows/ci.yml`.** 10 e2e specs in `e2e/*.spec.ts` already exist, `playwright.config.ts` configured, `@playwright/test` installed. Just need a CI job that runs against `npm run build && npm start` (or against Vercel preview URL — separate workflow). | 2 hr |
| 13 | **Stuck-loading watchdog stale-closure bug.** `armStuckLoadingWatchdog("mlb-leaderboard:…")` at `src/app/[sport]/page.tsx:177` uses stale closure over `mlbLeaderboard` — the `hasDataRef` callback captures `mlbLeaderboard` from the render that armed the watchdog, which is always `null` (just set on line 172). Fires false-positive Sentry warnings. Same bug at line 161 for NBA. Fix: ref pattern. | 30 min |
| 14 | **5 zeroed-constant MLB features have data already.** `f11_home_away_k_diff` and `f13_day_night_k_diff` exist in `mlb_raw.bdl_pitcher_splits` (972 pitcher-season rows). `f18_game_total_line` and `f19_team_implied_runs` come from `mlb_raw.oddsa_game_lines`. Wiring these restores 4 dead features. | 1 day |

### P2 — Sprint scope

| # | Finding | Effort |
|---|---------|--------|
| 15 | **MLB LightGBM 2nd model** — `predictions/mlb/prediction_systems/lightgbm_v1_regressor_predictor.py` exists, sharing v2's 36-feature contract verbatim. `scripts/mlb/training/train_lightgbm_v1.py` exists. Train with `--training-start 2024-04-01 --training-end 2026-04-15` (Session 524 April-bias fix), deploy with `MLB_ACTIVE_SYSTEMS=catboost_v2_regressor,lightgbm_v1_regressor`. NOTE: combo signals like `combo_3way` are NOT cross-model in NBA either — they fire single-model. To get cross-model value, author `mlb_model_disagree_under` separately after N≥30 dual-model pitcher-games accumulate. | 2 days |
| 16 | **3 new MLB signals using existing Statcast data** (`mlb_analytics.pitcher_advanced_arsenal_latest`, `pitcher_expected_arsenal_latest` — already published to frontend, never wired into a signal): `putaway_pitch_elite_over` (`putaway_whiff_rate >= 0.45 AND putaway_usage_pct_on_2k >= 0.30 AND starts_l5 >= 3`), `whiff_underperform_under` (`whiff_vs_expected_pp <= -3.0 AND starts_sampled >= 5 AND is_reliable=TRUE`), `velo_fade_under` (`velo_fade_mph >= 1.5 AND fb_n_inning_5_plus >= 50`). Register as SHADOW first. | 1-2 days |
| 17 | **MLB decay-detection CF.** Parameterize NBA `decay_detection/main.py` by sport. Without it, stale/regressing MLB models stay enabled, no HEALTHY→BLOCKED gate. April-bias retrain bug (Session 524) would have been caught. | 1-2 days |
| 18 | **Sport-aware fetch layer.** Build `apiFor(sport).fetchX()` interface in `src/lib/sport-api.ts`. Root cause of 14 frontend sport-leakage bugs. Forces SPORT_META expansion (capability flags) + path-symmetry contract. | 3-5 days |
| 19 | **MLB governance gates incomplete.** `train_regressor_v2.py` has 4 gates (`mae`, `over_hr`, `n`, `bias`). NBA `quick_retrain.py` has 6 — missing duplicate-check + tier-bias. | 4 hr |
| 20 | **MLB model-cache TTL.** NBA worker auto-refreshes registry every 4h (Session 474). MLB worker has no equivalent — registry changes need a redeploy. | 4 hr |

### P3 — Foundation/meta

| # | Finding | Effort |
|---|---------|--------|
| 21 | **Untrack `.hypothesis/` + `.benchmarks/`.** `.hypothesis/` is already in `.gitignore`. `.benchmarks/` is not. Both pollute every `git status` (7+ M lines today). One commit, zero behavioral risk: `git rm --cached -r .hypothesis .benchmarks && echo .benchmarks/ >> .gitignore`. | 5 min |
| 22 | **Auto-unblock decay status CF.** Prevents Session 477's "Registry Status Stale After Model Re-Enable" — BB pipeline silently producing 0 picks for 2+ days. Run daily after `decay_detection` and `UPDATE` `model_registry.status='active'` when `(enabled=TRUE AND status='blocked' AND model_performance_daily.hr_30d >= 55% AND picks_7d >= 5)`. Bounded (max 1/run, Slack-emit, dry-run gate). | 1 day |
| 23 | **Cloud Build failure alerts.** Auto-deploy is the deploy mechanism — silent build fail = stale code in prod with no signal until 2h drift check. No alert policy today. | 2 hr |
| 24 | **Cloud Run crash loop alerts.** No policy on `run.googleapis.com/container/instance_count` flapping or `request_count` 5xx ratio. Service can recycle for hours. | 2 hr |
| 25 | **Fangraphs 2026 data 31 days stale** (Apr 11 → today). `mlb_raw.fangraphs_pitcher_season_stats` table 737h stale. Adjacent: `mlb_pitcher_stats` 1537h, `catcher_framing` 1504h, `mlb_weather` 1550h. Source scraper failed silently. `elite_peripherals_over` signal already dead from this. | Investigate scraper |
| 26 | **`useGameCounts.test.ts`.** Catches the bug we just fixed. Pattern for other untested hooks (`useEffectiveDate`, `useLiveUpdates`, `usePreferences`). | 30 min |
| 27 | **Lineup-weighted opponent K-vulnerability feature** (biggest analytical gap per Agent 1). `mlb_raw.mlb_lineup_batters` + `mlb_analytics.batter_game_summary` already populated. `f14_vs_opponent_k_rate` is the placeholder slot, currently zeroed. | 1-2 days |
| 28 | **NBA `ml_feature_store_v2` quality scorer alert.** 65-75% block rate is the daily norm — meaning predictions are highly self-selected. No alert when clean_rate < 25%. Worth understanding which features are forcing the defaults. | Investigate + alert |
| 29 | **Redundant scraper-gap-backfiller pair drifting apart.** `scraper-gap-backfiller-schedule` (UTC) targets Gen1 CF, `scraper-gap-backfiller-trigger` (ET) targets Cloud Run. Same job, drift by 4-7h. Delete one. | 30 min |
| 30 | **35+ UTC/Etc/UTC schedulers** — invisible DST drift. Standardize to `America/New_York` or `America/Los_Angeles`. | 1 day |

### Notable but lower-rank

- **Cross-model signals NOT cross-model in NBA either** (Agent 3 verification). `combo_3way` + `book_disagreement` are single-model. To get cross-model value in MLB, must author separately.
- **`ml/archive/` (41 files, 636 KB)** — pure historical reference. Zero imports from active code.
- **1,270 handoff docs (27 MB) in `docs/09-handoff/`** — archival opportunity (move Jan-Feb 2026 to `archive/2026-q1/`). No urgency.
- **`monthly_retrain` CF** still in repo — DEPRECATED per CLAUDE.md, replaced by `weekly_retrain`. Not in `cloudbuild-functions.yaml`.
- **`scripts/smoke_test.py` and `scripts/validate_historical_season.py`** still query deprecated `prediction_grades` table.
- **Legacy `nba-phase1-scrapers` topic/sub names** in 4 files. Risky to rename (live Pub/Sub infrastructure).

## Recommended sequencing

**Next session (single PR scope):**
1. P0 #2 Empty-publish guard (30 min, high UX visibility)
2. P0 #5 Sentry → Slack (30 min, user side)
3. P1 #6 MLB-oddsa scheduler fix (1 gcloud cmd)
4. P3 #21 Untrack noise (5 min)
5. P0 #4 Empty-out the corrupted 2026-03-28 → 2026-04-09 history files (30 min — re-run backfill with a `WHERE pitcher_name IS NOT NULL` guard, which yields empty leaderboards)

Bundle 1-4 + 5 as 2 PRs (1 props-web, 1 nba-stats-scraper). All low-risk, high-clarity.

**Following session (model-affecting):**
- P0 #1 MLB feature store fix (start with `f05_season_k_per_9`) — needs its own session with proper backtest + governance gates before deploying.

**Following weeks:**
- P1 #10 MLB edge-based auto-halt (with observation mode)
- P1 #8 `/mlb/results` page (sport-thread `fetchResultsByDate`, `fetchSystemPerformance`, `fetchYesterdayBestBets`)
- P2 #15 MLB LightGBM 2nd model

## Open questions

1. **Corrupted 2026-03-28 → 2026-04-09 predictions:** root-cause investigate, or just patch the history files? Root cause likely worthwhile (suggests probables-feed regression that could recur next season).
2. **NBA grading gap:** when did `prediction_correct` start going NULL? Is the grading worker dead or just slow? Investigation can be done read-only via BQ.
3. **MLB feature store `f05_*` fix:** can we backfill the feature store for historical dates, or only forward? Affects whether retrained models can use the fix.
4. **Playwright in CI:** run against `npm start` (slow, ~5 min/PR) or Vercel preview URL (faster but needs token wiring)?
