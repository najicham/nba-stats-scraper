# Wave 2 — Pipeline Compute Efficiency

**Date:** 2026-07-21
**Question:** Can the NBA props pipeline run in-season for under $100/month without giving up capability?
**Answer:** **Yes — but not by turning things off. It requires consolidating Phases 2–4.**
**Method:** 13 parallel agents (10 general + 3 Fable) reading pipeline code, trigger topology, and `INFORMATION_SCHEMA`, not just billing.
**Status:** Investigation complete. Nothing applied.

Companion to `00-FULL-ANALYSIS.md` (Wave 1, infrastructure/billing). Wave 1 asked *where does the money go*. Wave 2 asks *can this pipeline do the same work for less compute*.

---

## 1. The Verdict

| Path | In-season | Off-season | Effort |
|---|---|---|---|
| Today (forward run rate) | **$424/mo** | $130/mo | — |
| Config only (min-instances, registry, schedulers) | $322/mo | ~$28/mo | ~3 days |
| **+ Phase 2–4 consolidation** | **$34–87/mo** | **~$8/mo** | 12–20 days |

**Config changes alone cannot reach the target.** The variable cost alone — 27 game-days × $10.88 = **$294/mo** — is nearly 3× the entire budget. Turning things off does not touch it.

With the consolidation, every scenario modeled clears $100:

| Scenario | CPU reduction | BQ reduction | $/game-day | In-season |
|---|---|---|---|---|
| Design target | 25× | 18× | $0.97 | **$34/mo** |
| Conservative | 10× | 8× | $1.60 | **$52/mo** |
| Pessimistic | 5× | 3× | $2.90 | **$87/mo** |

Confidence in the middle column comes from the shape of the problem: the largest single BigQuery line item is **one query executed 1,261 times**. That is not a tuning problem with diminishing returns — it is a 1,261× reduction available from lifting one `for` loop.

---

## 2. The Honest Forward Run Rate

All Wave 1 forecasting anchored on March 2026 ($825 NBA+shared). March was contaminated. Removing what is already fixed or discretionary:

| Item | March | Status |
|---|---|---|
| Cloud Logging | $68.30 | ✅ FIXED — now $0.34/mo (exclusions) |
| `prediction-worker` instance-based CPU | $69.76 | ✅ FIXED — $0 from April |
| Cloud Build (panic deploys) | $24.85 | ✅ April was $0.59 |
| Phase 3 retry storm | ~$113 | ✅ FIXED — commit `37c6f2b9`, 2026-04-08 |
| `nba-phase2` backfill spike | ~$46 | discretionary, episodic |
| `bigdataball-puller` BQ backfill | ~$13 | discretionary |
| Owner ad-hoc BigQuery | $12.73 | **7% of March BQ — not a lever** |

### Structure of the forward rate (NBA-attributable only)

**FIXED — $130/mo**, measured directly from a fully idle month (July 1–18, no games, no backfills, no deploys):

| Item | $/mo |
|---|---|
| `prediction-coordinator` min-instance idle | 35.85 |
| `phase4-to-phase5-orchestrator` min-instance | 13.75 |
| `phase3-to-phase4-orchestrator` min-instance | 13.68 |
| `phase5-to-phase6-orchestrator` min-instance | 13.59 |
| Cloud Scheduler (116 jobs) | 14.47 |
| Artifact Registry (~105 GB, 10 repos) | 14.33 |
| Cloud Run Jobs on `*/15` crons | 6.77 |
| `nba-scrapers` idle baseline | 3.59 |
| `backfill-pubsub-subscriber` | 3.52 |
| `prediction-worker` residual | 2.56 |
| GCS + misc CFs + Logging + Secrets | ~8.0 |

> **$76.87/mo — 59% of the fixed cost and 77% of the entire $100 target — is four containers idling.** `phase5-to-phase6-orchestrator` served **zero requests in 40 days** while running an instance 24/7.

**VARIABLE — $10.88/game-day**, medians over Feb 19 – Mar 31 (per-resource daily, so backfill spikes don't distort):

| Stage | $/game-day |
|---|---|
| `nba-phase3-analytics-processors` | 3.61 |
| BigQuery analysis (pipeline SAs only) | 3.81 |
| `nba-phase4-precompute-processors` | 1.98 |
| `nba-phase2-raw-processors` | 0.48 |
| `prediction-worker` | 0.34 |
| `nba-scrapers` incremental | 0.20 |
| Phase 5/6 CFs, grading, exports | 0.35 |
| GCS / egress / logging | 0.11 |

**In-season: $130 + 27 × $10.88 = ~$424/mo. Blended annual ~$3,620.**

### Reconciliation note

Component agents measured different months and overlapping scopes; their headline savings **must not be summed**. The $424 above is the only bottom-up figure built from a clean idle month plus per-game-day medians, and it is the anchor for every projection in this document. Component findings below are the **implementation spec**, not an additive ledger.

---

## 3. Root Cause — One Diagnosis, Many Symptoms

From `INFORMATION_SCHEMA.JOBS_BY_PROJECT`, **2026-03-10 (11 games)**:

```
528,000  BigQuery SELECT jobs in one game-day
372,356  of them (74%) were CACHE HITS — $0 bytes, full network round-trip each
    ~64  vCPU-HOURS of Cloud Run consumed
```

Cross-check: 400,000 round-trips × ~0.5s ≈ 55 container-hours. That reproduces the 64 vCPU-hours almost exactly.

> **The system does not spend money computing. It spends money paying 2-vCPU containers to sit blocked on half a million sequential BigQuery round-trips per day — three quarters of which return a cached answer to a question the pipeline already asked.**

Fleet-wide CPU utilization p95:

| Service | Concurrency | CPU p95 | Mem p95 | Mean request |
|---|---|---|---|---|
| nba-phase2-raw-processors | 1 | **3%** | 20% | 4.4s |
| nba-phase3-analytics-processors | 1 | **3%** | 18% | 28.9s |
| nba-phase4-precompute-processors | 1 | 13% | 23% (p99 **50%**) | 97.6s |
| prediction-worker | 1 | **1%** | 11% | 0.51s |
| prediction-coordinator | 8 | **1%** | 11% | 0.09s |

Per-request breakdown on `prediction-worker`: **model inference 2.4%, BigQuery reads 39%, BigQuery load job 48%.**

Both Phase 2 and prediction-worker run `gunicorn --workers 1 --threads 5` — the apps are built for 5 concurrent requests and Cloud Run throttles them to 1. **Four of five threads permanently idle.**

### Top query shapes, one game-day, service accounts only

| Query | Executions/day | Against |
|---|---|---|
| `espn_team_rosters` roster lookup | **113,748** | a 3.3 MB table |
| `processor_run_history` status poll | 89,392 | |
| per-team recent-games stats | 75,832 + 75,830 + 37,916 | |
| retry / circuit-breaker checks | 40,252 | |
| star-teammates-out lookup | 3,266,362 **per quarter** | |

**The per-entity point-query-in-a-loop pattern, not data volume, produces 500K jobs/day.**

### Where amplification concentrates

Overwhelmingly at the **Phase 2→3 boundary**, and it is *process* amplification, not data amplification.

The value chain's row counts are tight — 389 raw box rows → 387 summaries → 386 feature rows → 7 published picks. **No row explosion in the analytics core.** But Phase 2 publishes one completion message per file (66 team-boxscore files/day, *including 0-row runs* — `processor_base.py:563`), and Phase 3 answers every message with a full-date recompute at 55–65 BQ jobs each (`main_analytics_service.py:911-913` sets `start_date = end_date = game_date`; there is no delta path on the Pub/Sub route).

One date bought **~2,000 Phase 3 executions**, 87% of which failed or were swept.

Second concentration: **Phase 5→6**, where no state is handed across the boundary at all — the entire decision context (~36 queries) is re-derived 8–10×/day, plus 5–7 more times after grading.

---

## 4. The Control-Plane Inversion

For 2026-03-10:

| | Rows |
|---|---|
| Box score rows (the data) | 389 |
| `processor_run_history` | 5,656 (**13% success**) |
| `pipeline_event_log` | ~2,800 |
| `phase_completions` | 672 |
| `prediction_worker_runs` | ~1,000 |
| **Control-plane total** | **~10,100** |
| **Published picks (the product)** | **7** |

**Control-plane rows outnumber data rows 26:1 and outnumber the product 1,400:1.**

> This is the most important non-financial finding in the audit. **87% of recorded runs for a date are failures.** A run ledger where failure is the norm cannot signal anything — which is exactly how `model_bb_candidates` silently lost ~2 months of provenance without anyone noticing.

---

## 5. Ranked Action Plan

### Tier A — config only (~3 days, ~$102/mo, zero rewrite risk)

Do these regardless of what happens to Tier B. None becomes wasted work if the architecture changes.

| # | Action | $/mo | Risk |
|---|---|---|---|
| A1 | `min-instances=0` on `prediction-coordinator` + 3 orchestrator CFs | **$76.87** | LOW-MED |
| A2 | Artifact Registry cleanup + retention (105 GB → ~6 GB) | $13.50 | LOW |
| A3 | Scheduler consolidation: 116 jobs → ~10 | $12.00 | LOW |

**A1 caveat.** Orchestrator `min=1` was set after a Pub/Sub cold-start retry storm (commit `a18d88f3`), and `detect_config_drift.py` validates it. The correct fix is **enabling `--retry` on the Eventarc triggers** (currently `RETRY_POLICY_DO_NOT_RETRY`) plus raising the subscription ack deadline — then `min=0` is permanently safe, in-season included. Nothing in this pipeline has a sub-minute SLA; a 15s cold start on a transition that happens 3×/day is invisible.

**Reversion traps** (all verified): `bin/deploy-service.sh:51-62` hard-codes `minScale=1`; the Cloud Build triggers pass `_MIN_INSTANCES: 1` overriding the correct `'0'` default; `bin/raw/deploy/deploy_processors_simple.sh:116` still says `--concurrency=10` while live is 1. **Fix the source, not just the live config.**

### Tier B — the consolidation (12–20 days, off-season only)

One Cloud Run **Job**, three executions per game-day: morning (~30 min), pregame (~10 min), overnight grading (~15 min). 93 Cloud Run services → ~5.

Two facts make this work:
- **Cloud Run Jobs cost $2.16e-5/vCPU-s vs Services at $3.36e-5 — 36% cheaper** for identical CPU, and Jobs *structurally cannot have min-instances*, making the $76.87 idle bill impossible to reincur.
- One process = one set of dataframes. Every per-entity lookup becomes a dict/dataframe index. **Target: ≤25 BigQuery jobs per execution, down from ~170,000.** The 74% cache-hit population ceases to exist because the answer is already in memory.

**Retired:** phase2/3/4 processor services, coordinator, worker, the 3 orchestrator CFs, `phase6-export`, `phase5b-grading`, `live-export`, `auto-retry-processor`, `backfill-pubsub-subscriber`, `nba-pipeline-canary`, `nba-auto-batch-cleanup`, ~40 monitor CFs.
**Kept as a Service:** `nba-scrapers` — fanning out to 40 external endpoints with per-source retry is a genuine service workload, and it costs $3.59/mo.

**What is given up:** per-message retry granularity (replaced by checkpointed stage restart via the existing `expected_outputs`); independent per-service deploy; horizontal scale-out that is not used (8 games, 200 players is one container's work). **Nothing on the must-deliver list.**

**Regression oracle — ⚠️ CORRECTED.** An earlier draft of this document claimed that diffing `ml_feature_store_v2` row-for-row gives a "strict binary correctness signal" via the zero-tolerance rule. **That claim is insufficient and has been superseded.** It fails on five counts: (1) the gate reads 7 write-time scalars, not feature values, so a wrong-but-non-default value passes unchanged while altering predictions; (2) the oracle is itself corrupted — patch jobs have desynced `default_feature_count` from the quality columns (§9.2); (3) features are one of five layers — picks also flow through predictions, signals/filters/regime, ranking, and export; (4) bitwise diff false-positives on `processed_at`, run IDs, and float-accumulation-order differences between per-row SQL and set-based pandas; (5) off-season the diff validates an empty slate and is vacuously green.

**Use the 5-layer diff protocol instead** (L0 inputs → L1 features → L2 predictions → L3 BB candidates → **L4 published picks → L5 exported JSON**), with L4/L5 required bit-identical and upstream ε-exceedances accepted only when individually triaged and proven not to change a discrete decision. Diff against a **fresh legacy re-run in the same wall-clock window**, never against historical table contents — historical rows were produced against since-mutated satellite state (`signal_health_daily`, `filter_overrides`, model registry) and would confound code changes with state drift. Full protocol in `03-VALIDATION-PLAYBOOK.md`.

### Tier C — independent of the rewrite

These are worth doing whether or not Tier B happens, because they are correctness fixes that happen to save money.

| # | Action | $/mo | Note |
|---|---|---|---|
| C1 | Terminate the `failed_processor_queue` retry recycle | **$52–96** | see §6.1 |
| C2 | Partition `ml_feature_store_v2` + `player_prop_predictions` | ~$15–20 | restores their own DDL |
| C3 | Fix `source_file_path='unknown'` (kills the republish loop) | $25–40 | see §6.2 |
| C4 | Drop `tonight-players` from `TONIGHT_EXPORT_TYPES` | ~$46 | 11 runs/day → 2, one-line change |
| C5 | Batch the per-player circuit-breaker query | $5–8 | 31,466 jobs/day |
| C6 | Collapse dead/copy materializations (§7) | ~$10–15 | |
| C7 | Don't restore `fantasypros`/`dailyfantasyfuel`/`dimers` | $2–3 | dead scrapers, zero readers |

---

## 6. The Two Loops

### 6.1 The retry recycle — `pipeline_logger.py:598-620`

When a processor fails and an active queue row exists, the handler sets `status='pending', next_retry_at=now+15min` and **does not increment `retry_count`** — also overriding `auto_retry_processor`'s exponential backoff. The dedup lookup only matches `status IN ('pending','retrying')`, so once a row reaches `failed_permanent`, **the next failure mints a brand-new row with `retry_count=0`.** It cannot terminate.

`auto-retry-processor-trigger` runs `*/15` year-round with no season restriction.

Observed on 2026-07-03 (off-season, zero games): **433 `/process-date` calls/day**, 4–5 every 15 minutes, 60–232s each — **~650 container-minutes/day**, every one ending in `ValueError: No players found with games on 2026-05-03`. On 2026-07-02 the project executed **4,472 processor runs** for dead dates.

A trace date from March was **still being reprocessed 8×/day from June 23 to July 3** — four months later.

The same bug is live on Phase 2: `auto-retry-processor` POSTs a payload shape Phase 2 rejects with HTTP 400, 12 permanent failures/day, forever.

**Why it stopped on 2026-07-04 could not be determined.** No commit in that range touches the path. **Treat it as dormant, not fixed** — the March 9 backfill re-armed it once already and it billed three weeks of the season.

**Fix:** (1) dedup lookup matches all statuses so `failed_permanent` is terminal; (2) increment `retry_count`, never reset `next_retry_at` backwards; (3) classify "No players found" as non-retryable; (4) season-guard the trigger.

### 6.2 The republish loop — `source_file_path='unknown'`

`cleanup-processor` runs `*/15` with a 4-hour lookback (**16 republish opportunities per file**) and detects orphans by matching `scraper_execution_log.gcs_path` against `nba_raw.*.source_file_path`. **Every processor except `nbac_schedule` writes the literal string `'unknown'`** — one `bettingpros` date has exactly one distinct value across 486,463 rows. So every file looks permanently orphaned.

Phase 2 has no idempotency to catch the redelivery: `SmartIdempotencyMixin` computes a SHA256 `data_hash` for **37 processors** and **exactly one** (`nbac_team_boxscore_processor.py:579`) ever calls `should_skip_write()`. Compounding it, **10 Phase 2 processors use blind `WRITE_APPEND`** while `nba-phase2-raw-sub` has `maxDeliveryAttempts=5`, so redelivery duplicates rows today.

**Measured amplification:**

| Table | Rows written (Feb) | Unique keys | Distinct states | Amplification |
|---|---|---|---|---|
| `odds_api_player_points_props` | 4,209,240 | 104,644 | 36,720 | **115× end-to-end** |
| `bettingpros_player_points_props` | 8,029,017 | 86,698 | — | **92.6×** |

Zero value conflicts — every duplicate is byte-identical. One snapshot file on 2026-02-24 produced **15,648 rows**; the pre-regression average was 69 rows/file. For a single date, `odds_api_player_points_props` received **971,895 rows** — 5,855 rows per player-game to record one scalar.

**Two booby traps before enabling the hash skip:** `odds_api_props_processor.py:40-48` includes `snapshot_timestamp` in `HASH_FIELDS`, poisoning its own hash so it can never match; and `should_skip_write()` issues **one BigQuery query per record**, which on a 15K-row payload costs more than the write it avoids.

**Lowest-risk 80% fix: populate `source_file_path` properly.** It kills the loop at source without touching write semantics.

---

## 7. Materialization Map

**The chain itself is lean** — one row per player per stage, each with a distinct point-in-time or audit purpose. The waste is in re-execution, not storage.

### Collapse

| Table | Size | Why |
|---|---|---|
| `player_daily_cache` | 75 MB | Its **sole consumer already contains a complete inline reimplementation** (`feature_extractor.py:777-909`) fed by data fetched unconditionally. The cache saves zero queries. 34 of its 72 columns are verbatim UPCG copies. Registered under **two** triggers, so it re-runs every 2h with odds refreshes. |
| `player_shot_zone_analysis` | 178 MB / 417K rows / 48 cols | Every consumer reads the **same 3 ratio columns**, and `feature_extractor.py:880-888` already computes them inline. |
| `player_composite_factors` JSON cols | ~150 MB of 191 MB | `pace_context_json`, `shot_zone_context_json`, `usage_context_json` — **zero readers**. Keep the 5 scores (genuinely expensive 4-way matchup join). |

### Drop (fully dead)

`daily_game_context`, `daily_opponent_defense_zones` (schema-generated, no writer or reader, plus an orphan validation ruleset at `pre_write_validator.py:592-620` never dispatched), the `defense_zone_analytics` and `roster_history` processors (absent from `processor_map`, no triggers, no consumers), `prediction_grades` (deprecated).

### Add (should exist, don't)

| Table | Kills |
|---|---|
| `player_rolling_windows` keyed `(player_lookup, as_of_date)` | ~9 `player_game_summary` scans per feature-store run **and** ~25 independent window computations across Phase 6 exporters |
| `best_bets_daily_record` | 3× season-to-date `prediction_accuracy` join per export run, growing linearly all season |
| `star_players_daily` | the 3,266,362-run star-teammates pattern |

**Zero materialized views recommended.** 82% of jobs already hit the result cache; the dominant repeated aggregates bill at the 10 MB floor which an MV cannot reduce; and the top candidates are all *latest-row-per-key* patterns, which BigQuery MVs structurally cannot express. Ordinary rollup tables written at the end of Phase 3/grading are the right tool.

### Explicitly load-bearing — do not touch

Append-only raw snapshot layers (odds/injury history = CLV + point-in-time truth); `player_game_summary` and all `*_game_summary` (the point-in-time property **is** the leak-freedom guarantee); `prediction_accuracy` (immutable grading record, already correctly partitioned); `best_bets_published_picks` (the Session 468 fallback depends on it); `best_bets_filtered_picks` (counterfactual HR source); `model_bb_candidates` (provenance — currently broken; **fix the writer, don't remove the table**); daily snapshots; the 10-system prediction fan-out.

---

## 8. The Rewrite Spec — Named Call Sites

These are the specific sites that must become batch reads. This section is the implementation contract for Tier B.

### 8.1 `team_context.py` — the batch function exists and is bypassed

`data_processors/analytics/upcoming_player_game_context/team_context.py:43` defines `precompute_opponent_metrics()`, whose own docstring reads *"reduces BigQuery calls from O(players * metrics) to O(1)."*

`calculate_pace_differential()` at `:117` opens with a live per-call BigQuery round-trip and **never consults it.** ~15 sibling getters share the shape, each with an in-process memo cache that is dead on arrival because `containerConcurrency: 1` gives every message a fresh container.

There are ~30 teams. This processor is **90% of Phase 3 processor-hours** (121 of 135 in March), ran ~112×/day at **92.8s each** (p95 246s) = 10,404s/day of 2-vCPU wall time.

**Fix:** extend `precompute_opponent_metrics` to cover all ~15 getters' metrics; make each getter *require* the cache; call once per run. Output-preserving — but reproduce the per-team NULL/insufficient-history defaults exactly.

### 8.2 Coordinator fan-out — the 7× amplifier

`predictions/coordinator/coordinator.py:1436-1451`:

```python
# Session 191: Filter using aggregated viable players across ALL systems
# A player is viable if ANY system wants to predict on them
if player_lookup in all_viable_players:
```

The quality gate checks per `(player, system)`; the coordinator then **unions** the viable sets and publishes one message per *player*; the worker runs **all** systems. If any single system lacks a row for a player, that player and every model are recomputed.

**Verified:** on 2026-03-10, all 182 players ran exactly **7 times** — 12,740 predictions where 1,820 were needed (86% discarded). Across Mar 1–7 the mean was **25.2 re-predictions per player per day** (median 7, p95 86, max **1,246**).

Made worse by a consolidation defect: `is_active = TRUE` was set on only **1 of 10 systems**, so the gate returned zero rows for the other 9 forever.

**Fix:** put the list of systems actually missing for that player in the Pub/Sub message; run only those. Requires a matching fix so consolidation marks shadow-model rows `is_active=TRUE`.

### 8.3 Free fix — `quality_gate.py:263`

`coordinator.py:1345-1360` loops per system calling `apply_quality_gate`, which calls `get_feature_quality_scores(game_date, player_lookups)` — **a function whose signature takes no `system_id`.** The identical query runs ~11× per coordination cycle. Hoist above the loop.

### 8.4 `tonight_player_exporter` — N-player loop, twice daily

`export_all_players` (~`:985-1010`) loops over ~130–250 players; `generate_json` (~`:44-70`) runs ~7–10 serial queries per player. ~1,500–1,800 serial round-trips per run inside one `concurrency=1` container. It runs at least twice per game-day because `phase5_to_phase6/main.py:79` includes `tonight-players` in `TONIGHT_EXPORT_TYPES` *and* the 1 PM scheduler payload includes it.

Two independent bugs: `_query_game_context` uses an unbounded `report_date <= @target_date` against `nbac_injury_report` (scans all history, 107 MiB **per player**), and `_query_prediction` passes the partition filter as a *parameter*, defeating static pruning. `_query_defense_tier` is a per-**team** value called per-**player** — memoize (~30 distinct values).

**Quick win (10 minutes, ~$46/mo):** drop `tonight-players` from `TONIGHT_EXPORT_TYPES`; 11 runs/day → 2.

### 8.5 `build_shared_context` — a comment that is false

`ml/signals/per_model_pipeline.py:578` says *"Run satellite queries in parallel with row parsing."* They do not. Every satellite blocks on `.result(timeout=30)` sequentially at `:599, 628, 664, 697, 721, 745, 838, 863, 899, 919, 941`; steps 2–11 add ~10 more, including `get_regime_context` which is itself 4 serial queries (`regime_context.py:151, 199, 236, 273`). **~24 serial round-trips per run.**

**Fix:** `bq_client.query()` returns immediately — only `.result()` blocks. Submit all jobs, then collect. Zero semantic change.

**Confirmed TRUE:** CLAUDE.md's claim that shared context is computed once. `run_single_model_pipeline()` executes **zero** BigQuery queries. There is no N× per-model waste — do not spend effort there.

### 8.6 Per-entity check-then-write on orchestration state

`ml_feature_store_processor.py:1111` (`_check_circuit_breaker`, SELECT) and `:1134` (`_increment_reprocess_count` → re-calls the check at `:1139`, then `INSERT INTO` at `:1148`), invoked inside per-player loops at `:2639, 2673, 2705, 2792, 2824, 2857`.

On a 300-player slate: **~900 queries and ~300 single-row DML statements against one table in one run.** The race is real — two processors read the same `attempt_number` and both insert N+1, so the 3-strike threshold is unreliable. All interpolate `entity_id`/`skip_reason` via f-string with **no query parameters**.

Same pattern in five siblings: `player_shot_zone_analysis_processor.py:834/884`, `player_composite_factors_processor.py:793/816`, `upcoming_player_game_context_processor.py:804/845`, `upcoming_team_game_context_processor.py:837/870`, `team_defense_zone_analysis_processor.py:583/648`.

`player_daily_cache_processor.py` is partially fixed (`_check_circuit_breakers_batch` at `:799`) but the legacy per-entity path is still live at `:1565/:1589`, and the batch method's except-handler at `:1013-1020` falls back to a loop of single-row inserts.

### 8.7 Cold-start work on every invocation

- **`ml/signals/signal_health.py:39`** — `SYSTEM_ID = get_best_bets_model_id()` at module import constructs a `bigquery.Client` and runs a **synchronous registry query at import time**. Since `ml/signals/__init__.py` imports the aggregator, every publishing exporter touching `ml.signals` pays ~1–3s per cold start.
- **`predictions/coordinator/coordinator.py:196`** — Secret Manager RPC at import, before `/health` can serve.
- **`data_processors/raw/main_processor_service.py:66-111`** — ~45 processor classes imported at top, dragging pandas + pdfplumber into every cold start of the highest-frequency service.

**Container weight:** analytics and precompute images each ship **~175 MB of provably dead packages** (`scipy`, `scikit-learn`, `sqlalchemy`, `psycopg2-binary`, `orjson` — zero import sites). The worker carries ~110 MB of catboost plotting extras (matplotlib/plotly/graphviz, zero imports repo-wide) and 73 MB of `ml/experiments` via `COPY ml/`. 11 Cloud Functions install pandas/pyarrow they never import.

### 8.8 Schema — physical vs declared

`ml_feature_store_v2` and `player_prop_predictions` are physically unpartitioned and unclustered while their checked-in DDL declares `PARTITION BY game_date`.

**Root cause found:** the DDL contains `CLUSTER BY system_id, player_lookup, confidence_score DESC` — **`DESC` is not valid clustering syntax.** That `CREATE TABLE` can never have executed as written.

Every MERGE full-scans 666–680 MB to write one date. The MERGE **already carries the `target.game_date` predicate**, so partitioning activates pruning with **zero code change**.

```sql
CREATE TABLE `nba_predictions.ml_feature_store_v2_p`
PARTITION BY game_date
CLUSTER BY player_lookup, feature_version
AS SELECT * FROM `nba_predictions.ml_feature_store_v2`;
-- verify counts + checksums, then ALTER TABLE ... RENAME swap
```

> ⚠️ **Do NOT copy the DDL's `partition_expiration_days=365`.** The feature store holds 5 seasons of training data and `player_prop_predictions` holds multi-season history — applying it would silently purge them.
> ⚠️ **Do NOT enable `require_partition_filter` at all** — not just "not on day 1." Training reads and the `all.json` history fallback legitimately scan multi-season ranges, and the precedent is already set: `prediction_accuracy` is correctly partitioned *without* it. Separately, the line-enrichment MERGE (`prediction_line_enrichment_processor.py:254`, ON `prediction_id` with no `game_date`) and ~47 monitoring SELECTs would break under it.
>
> **Partitioning alone does not deliver the saving** — three MERGE statements must also gain date predicates or they will still full-scan: the coordinator's staging-consolidation MERGE, the line-refresh MERGE (add `AND target.game_date = @game_date`), and the feature-store MERGE (add `AND game_date IN (SELECT DISTINCT game_date FROM source)`).

**Verdict on the 180-column wide-feature design: KEEP IT.** The worker reads 60 value columns and **zero** quality/source columns; the zero-tolerance gate reads **7 materialized scalars**, not 60 quality columns (`quality_gate.py:184-196`, computed at write time in `quality_scorer.py:372-395`). Long/narrow would multiply rows ×60 and turn a scalar read into an aggregation. STRUCT/ARRAY would recreate the array-vs-column dual-semantics bug just escaped. The real pain is **schema evolution**, and the fix for that is generating DDL + views from `feature_contract.py` — not restructuring the table.

---

## 9. Non-Cost Findings

Ranked by severity. None of these are about money.

1. **Phase 5 fan-out is dead.** The push subscription for topic `prediction-request-prod` **does not exist** — 22 subscriptions in the project, none on that topic, only the orphaned `prediction-request-dlq-sub`. Predictions cannot run until it is recreated. Blocks opening night. Recreate with `deadLetterPolicy.maxDeliveryAttempts = 5`.
2. **The zero-tolerance guarantee has a hole.** Column-level patch jobs (`fix_spread_features.py`, `backfill_f47_f50.py`) rewrite feature triples **without recomputing `default_feature_count`/`required_default_count`**, so the gate can silently disagree with actual feature quality after any patch.
3. **Two patch jobs are silent no-ops.** `2026-01-29_patch_l5_l10_from_cache.sql` and `fix_team_win_pct.py` write **only the deprecated `features[]` array** while every consumer reads `feature_N_value`. The L5/L10 patch's own verification checks `feature_0_value`/`feature_1_value` — columns it never wrote.
4. **Version-string mismatch.** `FEATURE_VERSION = 'v2_54features'` (with `FEATURE_COUNT = 60`) at `ml_feature_store_processor.py:93-94` vs `feature_schema_version = 'v2_60features'` at `quality_scorer.py:586` — and the worker **filters** on `feature_version` at `data_loaders.py:943`.
5. **The fleet has no circuit-breaker protection.** `predictions/worker/system_circuit_breaker.py:243` hardcodes a 5-name allowlist of **decommissioned legacy systems**; the entire registry-driven fleet is unprotected, and each failure emits a DML INSERT per (model, player).
6. **Retry storm precedent.** An `AttributeError` on Mar 3–5 produced **19,100 failed invocations** (11,852 on Mar 4) because unclassified exceptions return 500 and Pub/Sub retried a deterministic code bug for three days.
7. **Four orphaned Cloud Functions fire daily with no source in the repo** — `box-score-completeness-alert`, `phase4-failure-alert`, `reconcile`, `validate-freshness`. Two fire from us-central1 schedulers at us-west1 gen1 URLs, invisible to us-west2 audits.
8. **Duplicate schedulers.** `scraper-gap-backfiller-schedule` and `-trigger` share identical cron/URI/body — a self-healing backfiller double-firing concurrently. `stalled-batch-cleanup` and `prediction-stall-check` hit the same endpoint with **conflicting thresholds** (90% vs 95%).
9. **`precompute_failures` has 2.17M duplicate rows** — one path streams, another DELETEs, so dedup silently no-ops against the streaming buffer.
10. **`_breakout_classifier` is declared and read but never assigned** — the breakout classifier silently never runs despite its env var being set.
11. **Full-table DML.** `nbac_gamebook_processor.py:1491` runs a string-interpolated `DELETE` with no partition filter on a partitioned table, ~15×/night. `nbac_play_by_play_processor.py:656` does it correctly — one-line fix.
12. **`proxy_circuit_breaker`: one MERGE DML per HTTP scrape request** on a 30-row table. `record_success` calls `_upsert_status` unconditionally.
13. **Observability gaps.** `nba_processing.processor_runs` is **completely empty**; `precompute_processor_runs` stopped writing 2026-01-29. Phase 2 has no duration telemetry at all.
14. **Crash-looping dead scrapers.** For one date: DimersProjections **774 runs / 0 successes**, DailyFantasyFuel 718/0, HashtagDvp 674/0, TeamRankings 656/0, FantasyPros 642/0. Three of these are scheduled for Wave A restore in October.

---

## 10. Refuted / Negative Results

Recorded so they are not re-investigated.

| Hypothesis | Verdict |
|---|---|
| "March's $182 BigQuery was largely ad-hoc research" | **REFUTED 3×.** Pipeline was **98%** of March, 97% of Feb. Ad-hoc is ~$3–5/mo — **do not throttle interactive analysis.** |
| "Cutting the 10-model fleet saves ~$100/mo" | **REFUTED.** Marginal cost is $0.50–1.00/model/month. 10→3 saves $5–10. Inference is 0.13s for the whole fleet. |
| "The per-model loop repeats BigQuery work N×" | **REFUTED.** `build_shared_context` genuinely runs once; `run_single_model_pipeline` issues zero queries. |
| "Model artifacts reload per request" | **REFUTED.** Module-level globals, 3 models totalling 1.55 MiB, loaded once per container. |
| "Cut the 4 daily feature-store rebuilds" | **REFUTED — and it would cost picks.** 12.7% of the morning edge-3 candidate pool churns by afternoon; 25.4% of multi-version rows flip direction. Freezing at morning changes **~70–130 published picks/season** to save ~$3/mo. The real cadence problem was 19.6 rebuilds/date from retry churn. |
| "GCS versioning amplification is a cost problem" | **REFUTED.** 1,695× on `v1/trends/` is real but totals 248 MiB ≈ **$0.01/mo.** Apply the lifecycle rule as hygiene only. A content-hash short-circuit wouldn't fire anyway — every payload carries a `generated_at` timestamp. |
| "Phase 3 costs $130/mo" | **STALE.** Was a retry storm, fixed 2026-04-08 (`37c6f2b9`). Now $12–15/mo. |
| "Phase 2 costs $60/mo steady-state" | **WRONG.** February was **$11.30**. March's $60 was 78% concentrated in Mar 5–12 — an episodic backfill. |
| "The exporter 730-DAY full-scan bug class matters" | **ECONOMICALLY DEAD.** `prediction_accuracy` is 0.12 GB; all 32,933 jobs across 3 months cost **$6.38**. The historical "$85/mo" is stale by an order of magnitude. |
| "Registry YAML is re-parsed per call" | **REFUTED.** `shared/registry/loader.py:57,80` are `@lru_cache(maxsize=1)`. |
| "O(n²) in the merger/aggregator" | **NOT FOUND.** One sort + single pass; aggregation linear per prediction. |
| "Monitoring is expensive" | **REFUTED.** ~$29–30/mo, ~$13–16 savable. It is **broken**, not expensive. |
| "Kalshi has no consumers" / "Kalshi has consumers" | **BOTH WRONG.** Two pure-passthrough consumers into a `features[]` slot; zero references in `ml/`, `shared/`, precompute, or publishing. Technically consumed, decisionally dead. |

---

## 11. Sequencing

| When | Do | Result |
|---|---|---|
| **This week** | Tier A1 + A2 | $424 → **$334/mo**. One day. Pure config. |
| **This week** | Recreate `prediction-request-prod` subscription with DLQ | unblocks opening night |
| **August** | Tier A3 + Tier C1/C2/C3/C4 | **~$250–290/mo** |
| **Aug–Sep** | Tier B build + shadow-run with row-for-row `ml_feature_store_v2` diffs | the whole thing |
| **October** | Cut over during the planned pre-season rehearsal | **$34–87/mo in-season, ~$8/mo off-season** |

**The off-season is the only safe window for Tier B, and roughly ten weeks remain.**

### Do not build an off-season mode

**$112 of the $130 idle floor is infrastructure that cannot tell whether basketball is being played.** A Cloud Run Job costs $0 when it does not run. After Tier B, seasonal logic collapses to a guard inside versioned code:

```python
if not season_active(today):
    write_halt_state(reason="off_season")
    return
```

The argument is this project's own history: the 94-job off-season purge is exactly that kind of manual seasonal intervention, and it is what silently killed weekly retraining (`weekly-retrain-trigger` deleted, CF HTTP-only with no invoker, fires never). **A season guard inside versioned code cannot delete a scheduler.**

---

## 12. Method and Confidence

13 agents, all read-only: fleet sizing · Phase 3 trigger topology · feature-store cadence · prediction-worker internals · BigQuery query attribution · publishing/export cadence · scraper cadence · monitoring proportionality · clean-sheet architecture · caching/concurrency topology · **Fable:** BigQuery schema design, algorithm hot paths, end-to-end write amplification.

Sources: `INFORMATION_SCHEMA.JOBS_BY_PROJECT` (region-us-west2), the resource-level billing export, Cloud Run metrics and logs, Cloud Audit Logs, `processor_run_history` / `analytics_processor_runs` / `prediction_worker_runs`, GCS object listings, and direct code reads with file:line citations.

**Known limits:**
- Cloud Monitoring retains ~6 weeks, so March CPU/latency distributions are gone. Utilization figures come from Jun 11 – Jul 21 (off-season). Billing-derived instance-seconds for March are consistent with the same I/O-bound profile.
- Concurrency savings are ranges, not point estimates — the benefit depends on burst shape, which could not be resolved.
- All Tier B "after" figures are DESIGNED, not measured. The bracket ($34/$52/$87) is the honest expression of that uncertainty.
- Phase 4 processor internals, ~35 publishing exporters, and worker feature-array assembly were **NOT AUDITED**.
- 2026-27 volume is assumed to resemble 2025-26.

---

*Generated 2026-07-21. Nothing applied. Every action above awaits approval.*
