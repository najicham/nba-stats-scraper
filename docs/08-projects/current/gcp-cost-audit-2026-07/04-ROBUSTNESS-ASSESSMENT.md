# 04 — Robustness Assessment

**Date:** 2026-07-21
**Method:** 5 Fable agents (red-team, fragility audit, validation strategy, correctness analysis, decision record) plus their sub-agents. Read-only throughout; repo HEAD unchanged at `3b8f448e`.
**Status:** Investigation complete. Nothing applied.
**Companions:** `00-FULL-ANALYSIS.md`, `01-WAVE-2-PIPELINE-EFFICIENCY.md`, `02-DECISION-RECORD.md`, `03-VALIDATION-PLAYBOOK.md`.

---

## 0. Why This Document Exists

The cost investigation (Waves 1–2) surfaced reliability defects as side findings. This assessment evaluates them as a coherent picture and answers a question the cost work could not: **is the system we are about to modify currently sound?**

**The answer is: the data core is sound; the safety layer is not.**

That inverts the work queue. Several safety fixes below are hours of work, independent of the cost program, and make every subsequent change measurable. They should land first.

---

## 1. The Headline Number Was Wrong — In Both Directions

Wave 2 reported **12.9% run success** for game-date 2026-03-10. That figure is roughly half measurement artifact.

`shared/processors/mixins/run_history_mixin.py:159-161` inserts a `running` row at start. Line `:245-246` inserts a **second row** at completion rather than updating the first — the code comments say so explicitly. `orchestration/cloud_functions/stale_running_cleanup/main.py:87-106` then UPDATEs every `running` row older than 4h to `failed`.

**Every completed run therefore acquires a phantom failure.** Verified: 71,354 of 71,363 distinct Feb–Mar runs carry a `stale_running_cleanup` phantom, including runs that succeeded in 6 seconds.

### Corrected baseline (dedup by `run_id`; success = any success row)

| Window | Naive | **True per-run** |
|---|---|---|
| Feb–Mar 2026 combined | ~25% | **41.1%** (29,347 / 71,363) |
| 2026-03-10 (the case date) | 12.9% | **22.9%** (731 / 3,185) |

Per-phase, Feb–Mar: phase_2_raw **20.0%**, phase_3 **47.4%** (41,962 runs — the volume king), phase_3_analytics **41.7%**, phase_4_precompute **66.7%**, phase_5_predictions **52.7%**.

### The real finding is worse than the number

**The ledger is unreadable in both directions.** Real failures hide among phantoms. And there are three ledgers giving three answers:

- `pipeline_event_log` Feb–Mar: 224,954 `processor_start`, 142,128 `processor_complete`, 19,779 `error` — **63,047 starts (28%) have no terminal event at all.** On 2026-03-10: 48% vanish.
- `PlayerGameSummaryProcessor` is **88.0% successful** per `analytics_processor_runs` and **~26%** per `processor_run_history` for the same period.
- `phase_completions` records **only success rows** — it has no failure semantics and cannot, by design, detect a failure.

> No future change is measurable against a baseline until this is fixed. That is the stated purpose of the audit, and it is currently unachievable.

---

## 2. Processors That Have NEVER Succeeded

≥10 runs, full ledger history:

| Processor | Runs | Successes | Window |
|---|---|---|---|
| **OddsGameLinesProcessor** | **720,630** | **0** | Apr 19 → **still failing 2026-07-20** |
| BasketballRefRosterBatchProcessor | 9,774 | 0 | Jan 7–23 |
| DimersProjectionsProcessor | 5,886 | 0 | Mar 5–11 |
| DailyFantasyFuelProjectionsProcessor | 5,726 | 0 | Mar 5–11 |
| HashtagBasketballDvpProcessor | 5,148 | 0 | Mar 5–11 |
| FantasyProsProjectionsProcessor | 5,118 | 0 | Mar 5–11 |
| TeamRankingsStatsProcessor | 5,328 | 1 | Mar 5 – Jun 9 |
| MlbBpHistoricalPropsProcessor | 42,924 | 69 (0.2%) | Apr 10 – Jun 16 |

**`OddsGameLinesProcessor` is a new finding** — absent from both cost documents. It ran a 720K-failure storm at ~178K/week inside `mlb-phase2-raw-processors` from Apr 19 to May 17, then settled into a residual 2/day crash (`AttributeError: 'list' object has no attribute 'get'`) still firing daily at 14:30 UTC. **Zero successes in three months.**

Three of the Mar 5–11 dead scrapers are on the October Wave-A restore list.

### Failing today, in the off-season

~250 starts/day, ~25 errors/day, all permanent:
- `nbac_play_by_play` — `Missing required option [game_id]` — 177 errors/14d
- `nbac_injury_report` — `Missing required option [hour]` — 177 errors/14d
- `OddsGameLinesProcessor` — 2/day

**The retry recycle is armed and ticking right now:** `failed_processor_queue` minted 92 new `failed_permanent` rows for those two processors in the last week, newest 2026-07-21, with 2 `pending` queued. Live confirmation that `failed_permanent` is not terminal.

---

## 3. The Systemic Mechanism Behind Silent Failure

**One root pattern, two reinforcing halves.**

**Half one** is an explicit repo-wide convention: anything that is not the product output is "non-fatal." Provenance, audit rows, state records, and alert sends are wrapped in log-and-continue `except` blocks so bookkeeping cannot break picks.

**Half two:** the reporting layer is built on the same convention. Reporter CFs "MUST return 200" (CLAUDE.md), and several return 200 *from their except blocks* — so the layer that would notice the swallowed writes also cannot fail.

**Closed loop.** Two compounding sub-patterns: **delete-then-swallow** (the DELETE commits, the re-write is swallowed → net data *destruction*, not a no-op) and **verifier/writer drift** (checks that verify something other than what was written).

Swallow-site census (non-test): `data_processors` ~1,039 `except Exception`, `scrapers` ~668, `orchestration` ~566+, `shared` ~500, `predictions` ~305, `ml` ~145. Only a handful re-raise on write error.

### The instances that matter most

1. **`shared/utils/bigquery_batch_writer.py:257-259`** — the shared batch writer **clears its buffer before I/O**. On flush failure (`:302-324`) the records are gone, every caller discards the returned `False`, and the only trace is an in-memory counter logged at shutdown. **This one bug silently loses records for run history, circuit-breaker state, and precompute telemetry simultaneously** — a strong candidate for why several "stopped writing" tables look the way they do.
2. **`predictions/worker/worker.py:2464-2470`** — the staging-write failure handler calls `type(e, exc_info=True).__name__`, which is **itself a `TypeError`**. The real error is never logged, the failure metric never emitted, and **the `return False` that would trigger Pub/Sub retry never executes.** Prediction-write failures are both unlogged and unretried.
3. **`data_processors/publishing/mlb/mlb_best_bets_exporter.py:473-479`** — an in-code confession of the mechanism in production: a MERGE "has been silently failing all season," so `all.json` showed a fake 3-0 season record on 2026-05-14.
4. **`signal_best_bets_exporter.py:1591-1596`** — the `model_bb_candidates` swallow site ("Non-fatal — don't fail export if candidates write fails") with `CREATE_NEVER` at `:1581`. **This is the provenance-loss mechanism.**
5. **`signal_best_bets_exporter.py:975-979`** — if the BigQuery pick write fails, the exporter **uploads the JSON to GCS anyway**. Picks published to users that can never be graded.
6. **`predictions/worker/worker.py:219`** — `_breakout_classifier = None` is the only assignment. The classifier silently never runs despite its env var being set; `breakout_shadow` is NULL forever.
7. **`shared/validation/continuous_validator.py:407-446`** — `historical_completeness` fails 89/89 days for four independent reasons: the threshold exceeds reality, the query **ignores `target_date`** (hardcoded `CURRENT_DATE()-14`), failure maps to WARNING not CRITICAL, and the alert path no-ops without a webhook env.
8. **Dead safety code:** `SmartIdempotencyMixin` — 41 processors mix it in, 36 pay the hash cost, **exactly one** calls `should_skip_write()`. `ENABLE_IDEMPOTENCY_KEYS` defaults false and is set **only in tests**, while `coordinator.py:2919` deliberately returns 500 to force redelivery *on the assumption idempotency is on*.

### Provenance loss is worse than reported

`model_bb_candidates` holds **33 rows in all history** (9 March dates + 4 April dates) against 203 published picks Feb 23 – Apr 7. Not a two-month gap — **~99% provenance loss for the entire season.**

---

## 4. Fail-Open / Fail-Closed Map

The system's stated posture — zero tolerance, never publish on fabricated data — implies guards on the **pick path must fail closed**. Measured reality:

| Guard | Location | On failure | Verdict |
|---|---|---|---|
| **Quality gate — outer wrapper** | `coordinator.py:1505-1508` | **OPEN** — `except Exception: viable_requests = requests` ("publishing all") | ❌ **The worst hole in the codebase.** Any error in the gate machinery silently disables zero tolerance entirely |
| Quality gate — inner query | `quality_gate.py:220-223, 391-405` | CLOSED (empty scores → all blocked) | ✅ correct design |
| Worker defense-in-depth backstop | `worker.py:2074-2084` | OPEN — missing count treated as `0` = clean | ❌ the backstop defaults to "pass" |
| **`halt_state` in NBA exporters** | `signal_best_bets_exporter.py:474-481`; `best_bets_all_exporter.py:221` | **Annotation only** — `halt_active` written into JSON, `picks[]` still ships | ❌ **5 of 8 canonical halt reasons do not stop NBA picks.** MLB received the suppress fix (`mlb_best_bets_exporter.py:92-105`, commit `869fe4b8`); NBA never did |
| `halt_envelope()` on query error | `base_exporter.py:394-399` | OPEN (`halt_active=False`) — vs CLOSED on missing row (`:401-414`) | ❌ inconsistent; a BQ blip publishes through a real halt |
| Edge-based auto-halt | `regime_context.py:302-303`; `per_model_pipeline.py:1534-1540` | OPEN — the halt lifts itself on query failure | ❌ a halt that un-halts on error |
| Warmup conservative guard | `regime_context.py:28-71` | CLOSED (raises OVER floor, disables rescue) | ✅ **the pattern the others should copy** |
| Six context loaders (blacklist, UNDER suppression, direction affinity/health, model profiles) | `per_model_pipeline.py:1506-1555` | OPEN — each falls back to empty → filter inert | ❌ one BQ outage strips most negative filtering and output looks normal |
| Rescue health gate | `aggregator.py:758-775` | OPEN — no health data ⇒ every rescue signal eligible | ❌ gates pick *admission* |
| `filter_overrides` read | `per_model_pipeline.py:1387-1400` | OPEN → filters at full strength | ✅ open is conservative here |
| Decay auto-disable | `decay_detection/main.py:792-839` | CLOSED on every path; safety floor unbreachable | ✅ **best-behaved guard in the codebase** (but currently unscheduled) |
| **Phase2QualityGate** | `shared/validation/phase2_quality_gate.py:57` | fail-closed internally — **zero production callers** | ❌ the documented Phase 2→3 quality gate does not run |
| **Phase 3→4 / 4→5 orchestrator blocking** | `phase3_to_phase4/main.py:2024`, caller `:1464`; `phase4_to_phase5/main.py:1655` | outer `except → return None` swallows the deliberate `raise ValueError(...BLOCK...)`; caller then calls `mark_trigger_success()` and latches `_triggered=True` | ❌ **verified bug:** the gate blocks correctly, then reports success and permanently kills retries |
| Inter-phase coverage/readiness checks | `phase3_to_phase4/main.py:537,676,1808`; `phase4_to_phase5/main.py:735`; `phase5_to_phase6/main.py:150` | OPEN — literal `fail_open: True`, `quality_check_passed = True  # Fail-open` | ❌ every inter-phase quality check is advisory under error |
| Feature-store circuit breaker (+6 siblings) | `ml_feature_store_processor.py:1111-1132` | OPEN, and `attempts: 0` on read failure ⇒ trip threshold unreachable | ❌ self-disabling breaker |
| Worker fleet circuit breaker | `system_circuit_breaker.py:117-120, 243` | OPEN + queries 5 **decommissioned** system names | ❌ live fleet entirely unprotected |
| Worker model-registry TTL refresh | `worker.py:398-401` | OPEN — keeps stale list AND resets TTL | ❌ a disabled model keeps predicting ≥4h per failure |
| Disabled-model exclusion in BB SQL | `supplemental_data.py:127-142` | OPEN — empty registry excludes nothing | ❌ |
| `get_champion_model_id` fallback | `shared/config/model_selection.py:59-86` | OPEN → returns `catboost_v12` — **which is on the aggregator's `LEGACY_MODEL_BLOCKLIST`** | ❌ |
| DistributedLock | `distributed_lock.py:195-197` | CLOSED (raises) — but 3 of 4 grading callers catch and proceed ("Proceeding with grading WITHOUT lock", `prediction_accuracy_processor.py:1167-1170`) | ❌ correct lock, defeated by callers |
| `has_regular_season_games()` / `check_already_processed()` | `schedule_guard.py:36-41`; `run_history_mixin.py:697-700` | OPEN | ✅ acceptable — worst case is duplicate work |
| Phase 6 export readiness; ultra public gate; gamebook precedence; pre-write validator | various | CLOSED | ✅ |

**Pattern:** guards on the *work-scheduling* path fail open (defensible — duplicate work is cheap). Guards on the *pick-quality* path **also** fail open (indefensible for this system). The closed guards are the newer, deliberately-designed ones; the open ones are `except`-wrapped retrofits.

---

## 5. Load-Bearing Invariants — Enforcement Status

### 5.1 Zero-tolerance feature quality

Three real enforcement layers exist and are tested. **Three holes:**

1. The `coordinator.py:1508` fail-open bypass (§4).
2. **8 of 9 non-processor write paths bypass `quality_scorer` entirely.** `quality_scorer.py:343-610` is the only place `default_feature_count` (L537) and `required_default_count` (L538) are computed. `quality_gate.py:184-196` gates on exactly 7 scalars and reads **no** `feature_N_*` column.

| Write path | Scope | Recomputes counters? |
|---|---|---|
| `ml_feature_store_processor.py` + `batch_writer.py:338-432` | full-row MERGE | **YES** — the only correct path |
| `backfill_jobs/precompute/.../ml_feature_store_precompute_backfill.py` | delegates to above | YES |
| `backfill_jobs/feature_store/fix_spread_features.py:231-245, 253-265` | f41/f42 value+quality+source; **step 2 sets `source='missing'`** | **NO** |
| `backfill_jobs/feature_store/fix_team_win_pct.py:285-291` | `features[]` only (idx 24) | **NO** |
| `bin/backfill_f47_f50.py:111-147, 261-274` | f47/f50; converts default→real | **NO** |
| `schemas/bigquery/patches/2026-01-29_patch_l5_l10_from_cache.sql:86-107` | `features[]` only (idx 0,1); **verifies columns it never wrote** | **NO** |
| `scripts/backfill_vegas_leak_fix.py:255-284` | f25/f27/f50/f54 **value only**, no source/quality | **NO** |
| **`scripts/backfill_feature_store_vegas.py:102-171`** | **DELETE + 8-column re-INSERT — nulls all 37 `feature_N_value`, all quality/source, `default_feature_count`, `required_default_count`, `is_quality_ready`, every category counter** | **NO — actively destroys them** |
| `ml/archive/backfill_feature_store_v33.py:167-275` | whole-table swap | NO (archived) |

> **`fix_spread_features.py` sets a feature's source to `'missing'` without incrementing the default counters. A genuinely-defaulted player can therefore pass all three zero-tolerance layers.**

Also: `bin/backfill_f47_f50.py` writes off-vocabulary source strings (`'vegas'`, `'injury_context'`) absent from `SOURCE_TYPE_CANONICAL`.

3. The worker's version fallback on query error is the nonexistent `'v2_39features'` (`data_loaders.py:183,188`) → silent total blackout. The `DISTINCT ... LIMIT 1` with no `ORDER BY` is non-deterministic under mixed versions.

### 5.2 Point-in-time / leak-freedom

Enforced by convention plus a lexical pre-commit hook (`check_date_comparisons.py`). No code abstraction, no runtime check, and `cache_lineage_validation.sql` has no caller.

> **LIVE VIOLATION:** `team_defense_zone_analysis_processor.py:478` uses an inclusive `BETWEEN ... AND analysis_date` on defense summaries — **it reads the day being predicted.** Unchanged since October 2025. Missed by the Session-458 sweep because the hook has no BETWEEN rule. Silent in production, **active in backfill → train/serve skew.**

The hook is not in CI, has self-certifying escape hatches, and is already red on 4 MLB lines — a normalized failure.

### 5.3 Pick immutability

**Held by luck, not structure.** One WHERE clause (`signal_best_bets_exporter.py:842-852`) plus a `delete_succeeded` gate. Nine other paths hold raw DELETEs on `signal_best_bets_picks`. `best_bets_published_picks` is written via WRITE_TRUNCATE partition — the docstring claiming MERGE is wrong (`best_bets_all_exporter.py:1350, 1427-1432`).

Failure modes: **partition wipe on a swallowed read error** (`_query_published_picks` returns `[]` on any exception at `:1046-1048` → TRUNCATE with only today's picks destroys locked history); any historical re-export **duplicates every pick**; re-export resurrects `retracted_clv` picks as `'active'`; MLB never got the `delete_succeeded` gate.

### 5.4 Grading integrity

**`prediction_accuracy` is not immutable.** Whole-partition DELETE + WRITE_APPEND (`prediction_accuracy_processor.py:1021-1047`), lock fails open (`:1167-1170`), 8+ re-entry points including a public `/grade-date` endpoint.

> **The dedup is anti-invariant.** `ORDER BY created_at DESC` (`:573`) keeps the **latest** prediction, then discards `created_at` (`:579`). A post-game prediction outranks the pre-game one, and a regrade destroys the original. Project memory records "clean rows = `created_at` pre-game" as the key rule; it is enforced **only** in the calibrator's own loader, nowhere in grading. The table has no prediction-creation column at all — only `graded_at`.

All grading monitors are coverage-ratio based, so **duplicates make a corrupted date look healthier.**

### 5.5 Model governance

Implemented in both trainers and correctly fail-closed on missing data — but **advisory end-to-end**:

- `bin/retrain.sh:330-338` hardcodes `--force` → the duplicate gate is permanently dead on the primary path
- `quick_retrain.py` has **zero `sys.exit` calls** → gate failure exits 0 → `retrain.sh` proceeds to promotion
- The worker's registry query **accepts `status='blocked'`** (`catboost_monthly.py:299-302`)
- `weekly_retrain` declares `max_tier_bias` at `main.py:105` and never reads it, has no duplicate check, and auto-registers `enabled=True` with **no shadow period** — the automated path has fewer gates than the manual one
- The registry has no governance column, so nothing downstream *can* check

### 5.6 Signal/filter registry

`is_known_signal` / `is_known_filter` (`shared/registry/loader.py:98,107`) have **zero runtime callers** — CLAUDE.md's claim that code imports them is false. The pre-commit hook validates **docs only** (its `files:` pattern includes no `.py`) and skips silently on import error.

---

## 6. What Is Actually Monitored

**Genuinely live and sound — the only fully-live detection loop in the system:** `expected_outputs` → gap-detector (hourly) → reconciler (*/30) → `overdue_count` custom metric → deployed `expected-output-overdue` policy.

Also live: daily-health-check, deployment-drift CF, phase-completion-reconciler, halt-state-writer, data-quality-alerts, filter-counterfactual-evaluator, morning-deployment-check, and nba-monitoring-alerts (its `ml_nba`/`is_correct` bugs are fixed in source; residual: `TARGET_SYSTEM_ID` defaults to retired `catboost_v8`, so 2 of 5 checks silently return NO_DATA).

**Scheduled but alerting NOWHERE (~12 monitors):** live-freshness-monitor, signal-decay-monitor, gcs-freshness-monitor, dlq-monitor, prediction-health-alert, daily-health-summary, grading-delay-alert, scraper-availability-monitor, data-source-health-canary, pipeline-reconciliation, and (via a missing module) stale-processor-monitor and game-coverage-alert. They run, execute their checks, then log `"SLACK_WEBHOOK_URL not configured, skipping."`

**`transition-monitor` is worse:** its trigger topic `phase-transition-monitor-trigger` has **zero subscriptions** — 144 publishes/day into a void.

**Dead entirely:** decay-detection (**double-dead** — no scheduler since the purge AND its input `model_performance_daily` stopped being written **2026-05-18**), validation-runner (last write 2026-04-26), grading-gap-detector (unscheduled + hardcoded stale coordinator URL), self-heal-predictions, weekly-retrain, pipeline canary.

> **A mathematically dead alert policy:** `halt-state-stale`. Its only emitter is `halt_state_writer`, which emits a constant `0` on success and nothing on failure. The deployed policy is `GT 36` with **no `conditionAbsent`**. A gauge that is only ever 0 can never exceed 36. **This policy cannot fire under any circumstance**, including the exact failure it exists for.

**Table liveness — STOPPED:** `model_performance_daily` (2026-05-18), `service_errors` (2026-07-04), `filter_counterfactual_daily` (2026-04-10), `best_bets_filtered_picks` (2026-04-08), `league_macro_daily` (2026-06-20), `healing_events` (1 row ever). **NEVER WRITTEN (0 rows):** `self_heal_log`, `validation_alerts`, `daily_scorecard`, `grading_coverage_daily`, `bigquery_retry_metrics`, `phase_execution_log`, `quota_usage_log`, `scraper_data_arrival`, and effectively the whole `nba_monitoring` dataset.

**Failure classes with NO live detector:** model decay, grading gaps, halt-state staleness, cost runaway, **scheduler deletion** (structurally undetectable — the job-failure policy needs the job to exist, and nothing diffs live jobs against a manifest; this is the exact mechanism that killed weekly-retrain), and feature-quality degradation.

**Alert fatigue is measurable:** of genuine (non-phantom) failure rows, `alert_sent=TRUE` on ~20% in-season (3,710/18,226). Off-season it was 66% — meaning **the June MLB storm alerted loudly for 16 days and nobody stopped it.**

**The meta-problem:** `daily-health-check` *is* the monitor-of-monitors, *is* scheduled, *ran today*, and explicitly checks `model_performance_daily` freshness — which has been stale for **64 days**. Either its Slack alert arrives daily and is ignored, or its send path is silently degraded. Both readings are damning.

---

## 7. Two More Live Correctness Bugs

**A 100× scale error.** `player_shot_zone_analysis` stores percentages (0–100, `_calculate_zone_metrics_static:133-135`). The inline fallback `feature_extractor.py:880-888` computes ratios (0–1). `ml_feature_store_processor.py:1852-1854` divides by 100.0 **unconditionally**. **Whenever the fallback fires, features 18/19/20 are emitted 100× too small.** The denominator also differs (`paint+mid+three` vs `fg_attempts`), and the table emits `None` on incomplete zones (caught by `quality_scorer.py:103-104`) while inline emits a plausible number from NaN-as-zero with no validation — corrupting instead of nulling.

**A batch-vs-per-entity divergence.** `team_context.py` rebounding rate: batch (`:65,78`) computes `AVG(rebounds/NULLIF(possessions,0))` at 4dp; per-entity (`:420`) computes `AVG(rebounds)/NULLIF(AVG(possessions),0)` at 2dp. **Mean-of-ratios vs ratio-of-means — different value and precision depending on whether the cache hit.**

---

## 8. Corrections to Earlier Recommendations

| Earlier claim | Status |
|---|---|
| "Collapse `player_shot_zone_analysis` — every consumer reads the same 3 columns" | **REFUTED.** ~10 production readers, including `player_composite_factors_processor.py:456,507,626,890` which produces **feature-store features 5–8**. It is *upstream* of both `player_daily_cache` and composite factors. Collapsing breaks features 5–8. |
| "Collapse `player_daily_cache` — its sole consumer reimplements it inline" | **REFUTED as scoped.** Many readers incl. `ml/features/breakout_features.py:159,209,253` and three gating uses in `ml_feature_store_processor.py:701,929,1198`. The inline path also diverges: 60-day window vs full season, no season filter, `None`→`0.0` on 1-game samples, and `points_avg_season` includes DNP zeros. |
| "Diff `ml_feature_store_v2` row-for-row = binary correctness oracle" | **REFUTED.** Superseded by the 5-layer protocol in `03-VALIDATION-PLAYBOOK.md`. |
| "12.9% run success" | **Half artifact.** True figure 22.9% for that date, 41.1% Feb–Mar. |
| "`model_bb_candidates` lost ~2 months" | **Understated.** 33 rows in all history — ~99% season loss. |

---

## 9. Ranked Reliability Fix List

Cost ignored. Items 1–4 are small, surgical, and independent of the cost program.

**1. Close the zero-tolerance bypass.** Delete the `except → viable_requests = requests` fallback at `coordinator.py:1505-1508` (fail closed: no gate, no predictions). Flip the worker backstop at `worker.py:2074-2084` to block when the count is missing. *Two tiny changes guarding the system's #1 stated invariant.*

**2. Make halts halt.** Port the 6-line MLB pick-suppression (`mlb_best_bets_exporter.py:92-105`) into `signal_best_bets_exporter.py` and `best_bets_all_exporter.py`. Make `halt_envelope()` fail closed on query error (`base_exporter.py:394-399`). Make the edge auto-halt and `get_regime_context` failure paths default to halted/conservative, matching the warmup guard.

**3. Fix the two shared-code bugs with fleet-wide blast radius.** `bigquery_batch_writer.py:257-259` — do not clear the buffer until flush succeeds; surface `total_flush_failures` as a metric. `worker.py:2464-2470` — fix the `type(e, exc_info=True)` typo, restoring both failure logging and Pub/Sub retry.

**4. Repair the grading substrate.** Add a prediction-`created_at` provenance column to `prediction_accuracy`. Flip the dedup at `prediction_accuracy_processor.py:573` to prefer the **earliest pre-game** row. Make the 3 fail-open lock callers respect `LockAcquisitionError`. Add one idempotency test. *Every performance claim, calibration, and signal validation rests on this table.*

**5. Make the run ledger mean something.** Fix the two-row phantom design (the sweeper must skip run_ids that already have a terminal row, or completion must update in place). Make `failed_permanent` terminal and classify `"No players found"` / `"Missing required option"` as non-retryable (`pipeline_logger.py:598-620`). Kill the three standing crash loops.

**6. Make governance enforceable.** `sys.exit(1)` on gate failure in `quick_retrain.py`. Remove the hardcoded `--force` from `retrain.sh:330-338`. Exclude `status='blocked'` from the worker registry query. Wire `max_tier_bias`, a duplicate check, and a shadow period into `weekly_retrain`. Add a `gates_passed` column to the registry.

**7. Monitoring triage — fix or delete, no third state.** Re-create the decay-detection scheduler **and** restore the `model_performance_daily` writer (both halves needed). Mount webhooks on the ~12 alert-nowhere monitors or delete them. Replace `halt-state-stale` with a `conditionAbsent` policy. Delete the 4 orphan CFs and the void `phase-transition-monitor-trigger` topic. Make shims return 500 on import failure. **Add a scheduler-manifest diff to `daily-health-check`** — the only defense against the deletion class that killed weekly-retrain. Confirm whether daily-health-check's Slack actually delivers.

**8. Zero-tolerance patch hygiene.** Make every column-level patch job recompute `default_feature_count`/`required_default_count`. Add a nightly cross-check (recomputed counts vs `feature_N_source='missing'`). Quarantine `scripts/backfill_feature_store_vegas.py` — it nulls the entire quality-visibility column set.

**9. Point-in-time.** Fix `team_defense_zone_analysis_processor.py:478` (`BETWEEN` → `<`). Add a BETWEEN-endpoint rule to `check_date_comparisons.py`. Add the hook to CI. Clear the 4 red MLB lines so the hook is green-by-default.

**10. Fix the 100× shot-zone scale bug** in `feature_extractor.py:880-888` — match the writer's percent scale and `paint+mid+three` denominator.

**11. Orchestrator swallow-and-latch.** Fix `phase3_to_phase4/main.py:2024` and `phase4_to_phase5/main.py:1655` so a blocking `ValueError` reaches its `except ValueError` handler instead of being converted into `mark_trigger_success()`.

---

## 10. What Is Genuinely Robust

Deserved credit, all VERIFIED:

- **The staging + MERGE write path** (`batch_staging_writer.py`) — per-worker staging tables, one consolidating MERGE, correct dedup keys. Repeatedly praised by separate agents as what the rest of the system should look like.
- **`halt_state_writer`** — current through today, robust.
- **The `expected_outputs` → gap-detector → metric → policy loop** — the only fully-live detection loop.
- **Decay auto-disable's guard design** — fail-closed on every path, safety floor unbreachable.
- **The warmup conservative guard** (`regime_context.py:28-71`) — the pattern the other guards should copy.
- **The ultra public-exposure gate**, Phase 6 export readiness validations, gamebook precedence — all fail closed.
- **Grading's row-level math** — ~1,640 lines of test coverage.
- **BigQuery snapshot backups.**
- **The zero-tolerance gate's inner design.**

**The bones of a correct system exist** — concentrated in the newest code (Sessions 458–515 era). The failures concentrate in retrofitted `except` wrappers and in anything written before the pipeline-state redesign.

---

## 11. Bottom Line

The system is **sound in a narrower way than the headline number implied, and rotten in exactly the layer a modification campaign leans on.**

The data core, write path, and newest control-plane components are solid. The honest failure rate is ~59% of executions — half what the raw ledger says — and most of it is concentrated in known, enumerable crash loops.

The dangerous part is the safety layer: **gates that fail open, monitors that alert nowhere, a grading record that mutates, provenance that is 99% absent, and a live look-ahead leak.**

> Items 1–4 above are hours of work and independent of every cost decision. Doing them **first** means every subsequent change is validated against enforcement and ledgers that actually mean something.

---

*Assessment 2026-07-21. Read-only. Nothing applied.*
