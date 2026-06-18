# Improvement Backlog — 2026-06-17

From a 10-agent improvement sweep (31 agents incl. adversarial verification). NBA off-season (halted by design), MLB in-season (info-only, betting halted). Rankings reflect *post-verification* effort/impact.

## ✅ Executed this session

| Item | Detail |
|---|---|
| **`pipeline_event_log` → streaming inserts** | The durable fix for the 2026-06-16 partition-mod quota incident. `pipeline_logger` flushed via load jobs (1 partition-mod each) → exhausts the per-partition/day quota under load → silently drops audit events. Added opt-in `streaming=True` to `insert_bigquery_rows` (`bigquery_utils.py`) using `insert_rows_json`; wired ONLY from the `pipeline_event_log` flush (`pipeline_logger.py:195`). All other callers keep load-job behavior. Commit `717d5b43` (shared/ → rebuilds all services). *Not urgent — current failure rate was 0% post-storm-fix — but prevents recurrence when NBA resumes / any backfill runs.* |
| **7 DLQ monitor subscriptions** | 7 of 8 dead-letter topics had no subscription → poison messages dropped silently. Created `<topic>-monitor` pull subs (7d retention) on phase1/2/3/4 + backfill DLQs. **Follow-up:** add a `num_undelivered_messages>0` alert policy. |
| **MLB batter-props line scraping — ATTEMPTED, blocked (schedulers created + PAUSED)** | Created `mlb-oddsa-batter-props-morning`/`-pregame` cloning the pitcher config, but a live test-fire returned **400 INVALID_ARGUMENT**. Root cause: `mlb-phase1-scrapers` is **not auto-deployed** and the deployed image predates the `mlb_batter_props` registration (registry.py:272) and/or the `event_id` fan-out that the daily pitcher cron relies on isn't generic. Paused both to avoid daily 400s. **To actually enable:** redeploy `mlb-phase1-scrapers` via `./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`, confirm the `/scrape` event_id fan-out covers batter, test-fire, then resume. **Gated on the backtest go/no-go anyway** — the backtest uses 2024-25 historical lines (635K rows) and needs no new collection, so this is only worth doing if a subset clears the bar. |
| **Batter-props efficiency backtest → NO-GO** | `scripts/mlb/batter_subset_scan.py` (committed). 140,122 graded legs, 212 subset×direction hypotheses, total_bases + hits, locked ≥2pp/both-seasons/N≥300/bootstrap-CI/BH-FDR bar. **Zero subsets cleared.** The one borderline (Globe Life Field UNDER) failed bootstrap CI + FDR — the exact chance-level FP the bar rejects. Agent self-caught a critical bug first: ~51% of rows have NULL `under_price` → a copied breakeven helper defaulted them to −110 → 18 *spurious* GO subsets at 90%+ win rates; fixed (NaN for missing odds), NO-GO held with large N. And odds are optimistic (2-book best-of-2), so the true picture is *worse*. **Don't build batter plumbing.** |

## ⏭️ Deferred — recommended, with plan (need a focused pass or a decision)

- **Drop `prediction_grades` + migrate 4 readers (M).** Frozen since Jan; `daily_data_quality_check.sh:150/179` (Checks 4 & 5) still read it → **silently reporting all recent predictions as ungraded since January**. *Do the reader migration first* (→ `prediction_accuracy`/`_deduped`, map `margin_of_error`→`absolute_error`); also fix `verify_deployment.sh:138` EXPECTED_TABLES + `smoke_test.py:94` + `validate_historical_season.py:206`. Snapshot to GCS before `bq rm`. The table drop is the irreversible part — do it last, explicitly.
- **Stop the `PlayerShotZoneAnalysisProcessor` off-season retry loop (M).** 102K failures/2d, invoked ~1/min, ~58GB/day wasted scans + ~709 load jobs/day. **Do NOT pause `auto-retry-processor-trigger`/`stale-processor-monitor`** — they serve in-season MLB too. Correct fix: add the existing `has_regular_season_games()` guard (`shared/utils/schedule_guard.py`) to the precompute service entrypoint (it has none; Phase 3 already has it at `main_analytics_service.py:889`).

## Backlog by theme (the rest, ranked within theme)

| Theme | Item | Effort | Impact |
|---|---|---|---|
| ML | Fleet diversity — **diagnosis done 2026-06-18, premise corrected** (see below) | — | — |
| ML | Fix bogus `brier_score` (it's `edge/15`, not a probability — anti-correlated with HR) | M | medium |
| ML | Implement low-line + low-variance UNDER signal (62% HR, N=819, 4/4 seasons; strictly pre-game) | S | medium |
| Signals | Demote `high_skew_over_block_obs` (73.3% CF HR, eligible, auto-demote never caught it) | S | medium |
| Signals | Season-cumulative auto-demote path for low-frequency filters (N≥30 catches 0/3 targets) | M | low |
| Signals | Retire large-N coin-flip observation filters (`signal_stack_2plus_obs` 48.7%, `mae_gap_obs` 44%) | S | low |
| Reliability | DLQ undelivered-count alert (pairs with the 7 new subs) | S | medium |
| Reliability | `auto_retry_processor` non-atomic claim → double-fire risk; claim-first UPDATE | M | medium |
| Cost | Partition expiration on `pipeline_event_log`/proxy/scraper log tables (never-expire today) | S | low |
| Cost | Partition filter on `dependency_mixin` `data_hash` scans (`player_game_summary` 318GB/7d) | S | medium |
| Observability | 3 monthly MLB jobs PERMISSION_DENIED — add OIDC (NOT IAM) or delete (tied to concluded pitcher-betting project) | S | medium |
| Observability | All 32 alert policies are NBA-only — add MLB grading-freshness + `zero_pick_reexport` coverage | M | medium |
| Observability | Add `google-cloud-monitoring` to coordinator/grading/phase6 CFs (Path-A metrics no-op there) | S | medium |
| Security | Default compute SA holds `roles/editor` + runs 78 services — least-privilege migration (documented Jan, never executed) | L | high |
| Security | Delete 2 stale `bigdataball-puller` keys; WIF for `github-actions-deploy` | M | medium |
| Frontend | Stale endpoints (`subsets.json` 4mo) render with no staleness banner; root cause = `graded_count==0` export gate | M | medium |
| Frontend | MLB `all.json` still exposes model `edge` on the halted info product (payload-only) | S | low |

## Dropped on verification (do NOT chase)

- **REFUTED — "3 alert policies fire on dead metrics":** descriptors exist + receive live data every 30 min (`overdue_count`, `halt_state_age_hours=0.0` today). The "0 descriptors" came from querying the wrong project (`jett-prod`).
- **Overstated — "Phase3/4 `emit_phase_completion` is a dark metric":** the series is alive (97K points) because `phase_completion_reconciler` co-emits with the lib. Lib gap is a consistency nit, not lost alerting.
- **Overstated — "`required_default_count` drift signal missing":** already computed + emitted (`quality_scorer.py:393`). Residual is repointing 4 dashboard queries.
- **Corrected — `pipeline_event_log` "half of events dropped right now":** that magnitude was storm-contaminated; post-fix failure rate is 0%. The fix above is durable prevention, not an active emergency.

## Fleet-diversity diagnosis (2026-06-18) — premise corrected

The backlog item "rebuild a diverse fleet via feature-set/cadence walk-forward" would **not work**. Pairwise correlation of all models that generated NBA predictions (Feb-Mar 2026):

- **Feature-set variation is a dead lever:** `catboost_v12` vs `catboost_v16_noveg` = r **0.99**.
- **GBDT algo-swap is near-dead:** CatBoost↔LGBM = **0.958**, CatBoost↔XGB = **0.929** — i.e. as correlated as CatBoost is to itself (0.938). All gradient-boosted trees converge on the same features/targets.
- **Only structurally-different models de-correlate:** `moving_average`/`zone_matchup_v1`/`similarity_balanced_v1`/`ensemble_v1` = r **0.795** to the GBDT mass.
- **But those de-correlated models are individually weak:** every one is *below* the 52.4% break-even at edge 5+ (45.8 / 47.7 / 48.9 / 47.9 / 27.0%).

**Conclusion:** the fleet is effectively 64 CatBoost clones (r≈0.94) + a few equally-correlated LGBM/XGB. Cross-model signals (`combo_3way`, `book_disagreement`) need models that genuinely *disagree*, which only the structurally-different family provides — but those aren't accurate enough to enable as standalone members. **Do NOT** train GBDT feature-set/algo grids (clones) or blindly enable the weak diverse models. The real off-season ML work is one of: (a) build a structurally-different model that is *both* de-correlated *and* accurate (distributional/quantile direction — cf. the MultiQuantile `CEIL_UNDER` thread); or (b) validate on historical data whether the cross-model signals actually extract value from the existing weak-but-diverse models before next season (read-only), then shadow-test. Cadence (7d vs 14d) is still worth settling but is independent of diversity.

## The strategic bet — RESOLVED: NO-GO

The gate ran and **failed cleanly**: zero of 212 batter-prop subsets beat the vig robustly across both seasons, even under optimistic 2-book odds (details above). Combined with pitcher-K already concluded efficient, **MLB betting avenues are now exhausted** — keep MLB as the info-only product, build no batter plumbing. This is exactly the high-value negative result the cheap gate was designed to produce: it saved a multi-session parallel-stack build (`market_type` column, `mlb_precompute`, batter predictors, hits/TB features) that would have ended in the same halt as pitcher-K.

**Revised off-season focus:** with both MLB betting paths closed and NBA halted-by-design, the highest-value off-season investment is **prep for next NBA season** — the ML/signal items in the backlog (rebuild a *diverse* fleet vs the current v12_noveg clones; settle 7d-vs-14d cadence on clean data; implement the low-line/low-variance UNDER signal at 62% HR / N=819 / 4-of-4 seasons; fix the bogus `brier_score`). These have an ~October payoff and no in-season risk to validate now. A batter v2 with handedness/day-night dims is possible but *low priority* given the adversarial NO-GO under optimistic odds.
