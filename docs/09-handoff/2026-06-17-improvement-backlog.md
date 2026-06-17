# Improvement Backlog — 2026-06-17

From a 10-agent improvement sweep (31 agents incl. adversarial verification). NBA off-season (halted by design), MLB in-season (info-only, betting halted). Rankings reflect *post-verification* effort/impact.

## ✅ Executed this session

| Item | Detail |
|---|---|
| **`pipeline_event_log` → streaming inserts** | The durable fix for the 2026-06-16 partition-mod quota incident. `pipeline_logger` flushed via load jobs (1 partition-mod each) → exhausts the per-partition/day quota under load → silently drops audit events. Added opt-in `streaming=True` to `insert_bigquery_rows` (`bigquery_utils.py`) using `insert_rows_json`; wired ONLY from the `pipeline_event_log` flush (`pipeline_logger.py:195`). All other callers keep load-job behavior. Commit `717d5b43` (shared/ → rebuilds all services). *Not urgent — current failure rate was 0% post-storm-fix — but prevents recurrence when NBA resumes / any backfill runs.* |
| **7 DLQ monitor subscriptions** | 7 of 8 dead-letter topics had no subscription → poison messages dropped silently. Created `<topic>-monitor` pull subs (7d retention) on phase1/2/3/4 + backfill DLQs. **Follow-up:** add a `num_undelivered_messages>0` alert policy. |
| **MLB batter-props line scraping re-enabled** | `oddsa_batter_props` stopped 2025-09-28 (scheduler never existed; scraper `mlb_batter_props` + processor do). Created `mlb-oddsa-batter-props-morning` (10:35 UTC) + `-pregame` (12:35 ET), month 3-10, cloning the pitcher props config. Each idle day was un-backfillable 2026 line history. |
| **Batter-props efficiency backtest** | Running as the go/no-go gate (see Strategic bet). `scripts/mlb/batter_subset_scan.py` (uncommitted), total_bases + hits, stratified by real dims, pre-registered ≥2pp/both-seasons/N≥300/BH-FDR bar. |

## ⏭️ Deferred — recommended, with plan (need a focused pass or a decision)

- **Drop `prediction_grades` + migrate 4 readers (M).** Frozen since Jan; `daily_data_quality_check.sh:150/179` (Checks 4 & 5) still read it → **silently reporting all recent predictions as ungraded since January**. *Do the reader migration first* (→ `prediction_accuracy`/`_deduped`, map `margin_of_error`→`absolute_error`); also fix `verify_deployment.sh:138` EXPECTED_TABLES + `smoke_test.py:94` + `validate_historical_season.py:206`. Snapshot to GCS before `bq rm`. The table drop is the irreversible part — do it last, explicitly.
- **Stop the `PlayerShotZoneAnalysisProcessor` off-season retry loop (M).** 102K failures/2d, invoked ~1/min, ~58GB/day wasted scans + ~709 load jobs/day. **Do NOT pause `auto-retry-processor-trigger`/`stale-processor-monitor`** — they serve in-season MLB too. Correct fix: add the existing `has_regular_season_games()` guard (`shared/utils/schedule_guard.py`) to the precompute service entrypoint (it has none; Phase 3 already has it at `main_analytics_service.py:889`).

## Backlog by theme (the rest, ranked within theme)

| Theme | Item | Effort | Impact |
|---|---|---|---|
| ML | Rebuild a *diverse* fleet (currently 3× v12_noveg clones) via multi-cycle walk-forward; settle 7d-vs-14d cadence on clean data | M | medium (~Oct) |
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

## The strategic bet

**Collect MLB batter lines now (done) + run the cheap conditional-subset backtest as a hard go/no-go gate — build nothing until a subset clears it.** We already learned the expensive way that pitcher-K is efficient (built the full pipeline, then halted). Batter plumbing is a confirmed full parallel stack (no `market_type`, empty `mlb_precompute`, all 7 predictors pitcher-keyed). A decisive "no edge" result is itself high-value — it saves a multi-session build. NBA being halted means no competing in-season fire.
