# 06 — The Plan

**Date:** 2026-07-21
**Status:** Proposed. Nothing applied.
**Supersedes** the sequencing in `02-DECISION-RECORD.md` where they conflict.

Companions: `00-FULL-ANALYSIS.md` (billing), `01-WAVE-2-PIPELINE-EFFICIENCY.md` (pipeline), `02-DECISION-RECORD.md` (tradeoffs), `04-ROBUSTNESS-ASSESSMENT.md` (safety layer), `07-PLAN-REVIEW-2026-07-24.md` (solidity review + Session-7 addendum), **`08-AUGUST-EXECUTION-PREP.md` (turnkey §4 diffs)**.

---

## 1. What we're doing and why

**The cost problem largely solved itself.** The $1,019 June invoice was ~$550 one-time events and already-fixed bugs. Current run rate is ~$225/mo across all projects.

**The investigation's real yield is a broken safety layer** — gates that fail open, monitors that alert nowhere, a mutable grading record, ~99% provenance loss, and a live look-ahead leak. Those are worth more attention than the remaining dollars.

**The plan is deliberately smaller than the evidence would support.** Across ~35 investigation agents, one pattern held without exception: **acting on a finding before reading the adjacent surface produced a specifically-wrong action.** Collapse the table that turned out to have ten readers. Batch the query whose fallback semantics are already inconsistent. Cut the redundancy that was silently doing line-synchronization. Flip a dedup that was deliberate and correct.

So: four things this week, a small set in August, and an explicit list of what we are recording but not acting on.

---

## 2. The measured baseline (revised 2026-07-21)

Earlier forecasts said **$424/mo in-season**, built from Feb 19 – Mar 31 medians. That window predates the 2026-04-08 retry-storm fix. Direct measurement of the post-fix period:

| Service | Mar 10 (11 games, storm) | Apr 10 (15 games, post-fix) |
|---|---|---|
| `nba-phase2-raw-processors` | $6.82 | **$0.16** |
| `nba-phase3-analytics-processors` | $4.54 | **$0.46** |
| BigQuery | $7.04 | **$0.63** |
| `nba-phase4-precompute` | $2.29 | $1.07 |

**A bigger slate for a fraction of the cost.** The fix removed roughly $18/day.

### The per-game-day framing was wrong

| Date | Games | Cost |
|---|---|---|
| 2026-04-11 | **0** | $9.65 |
| 2026-04-10 | **15** | $11.10 |
| 2026-04-12 | **15** | $12.18 |

**The marginal cost of a 15-game slate is ~$0.73–2.33.** Not $10.88/game-day. Not the $3.80/game-day this document previously claimed. **Cost is almost entirely a fixed floor** — ~$9.65/day (~$290/mo) in April.

What sits in a zero-game day:

| Component | $/day | $/mo |
|---|---|---|
| prediction-coordinator (idle min-instance) | 1.21 | 36 |
| 3 orchestrators (idle min-instances) | 1.44 | 43 |
| prediction-worker (idle; removed 2026-07-05) | 0.93 | 28 |
| **phase4 retry loop** | 0.99 | 30 |
| **broken canary** | 0.66 | 20 |
| **`nba-bigquery-backups`** | 1.04 | 31 |
| Scheduler + BQ + remainder | 3.38 | 101 |

> **~~New finding: `nba-bigquery-backups` … ~$31/mo~~ — REFUTED (Session 6, §3 item 4): PHANTOM, no such line item. The $1.04 was a single zero-game-day attribution, not a sustained SKU. Ignore this row.**

### Caveat on the measurement

April is not a fully clean window. The edge-based auto-halt had been active since ~Mar 28, so **zero picks were published**, and only 3 systems ran (768 predictions vs March's 2,640 across 10). The fleet *is* currently 3 models, so that part is representative — but full pick publishing and a denser schedule will add load.

### Honest forecast

| | $/mo |
|---|---|
| April actual (nba-props-platform) | ~$371 |
| − min-instances (coordinator + 3 orchestrators) | −79 |
| − phase4 retry loop | −30 |
| − broken canary | −20 |
| ~~− `nba-bigquery-backups` (pending diagnosis)~~ | ~~−31?~~ **STRIKE — PHANTOM (§3 item 4)** |
| + full pick publishing, denser schedule | +? |
| **In-season 2026-27 estimate** | **~$200–250/mo** |

Annual average lands nearer **$130–150/mo** than the $100 previously claimed.

---

## 3. This week — four items

> **STATUS 2026-07-23 (Session 6):** Item 1 **DONE**. Item 2 premise **CONFIRMED** (backups off), patch not yet applied. Item 4 premise **LIKELY REFUTED** — see note under the table. Item 3 still owner-only.
> **STATUS 2026-07-24 (Session 7):** Item 2 **DONE** — backups enabled on `infinitecase-db` (verified `enabled=True`, `startTime=09:00`, `retainedBackups=7`, instance stayed `RUNNABLE`, online, no restart). §3 is now closed except item 3 (owner-only). Session 7 also **re-ran the 10-agent review on a working runtime** (9/10 agents succeeded; prior host's stalls were WSL-local) — plan re-confirmed solid. New finding: the **`prediction-request-dev` topic no longer exists** (verified live) — it is a prerequisite for §4.9; see §4.9.

| # | Action | Why | Status |
|---|---|---|---|
| 1 | ~~Recreate the `prediction-request-prod` Pub/Sub subscription with a DLQ~~ | Phase 5 fan-out was dead (topic had 0 subscriptions). | ✅ **DONE 2026-07-23.** Push sub → `…/predict`, OIDC SA `prediction-worker@…`, **ack 300s** (not 60), DLQ `prediction-request-dlq` maxDeliveryAttempts=5, pubsub-agent subscriber grant applied. Contract verified end-to-end. **Correction:** topic + DLQ topic already existed; only the subscription was missing. |
| 2 | **Enable backups on `infinitecase-db`** — `gcloud sql instances patch infinitecase-db --project=infinite-case --backup-start-time=09:00 --retained-backups-count=7` | Zero backups on a Postgres 15 instance. ~$0.20/mo. Backup-config change is online (no restart). | ✅ **DONE 2026-07-24 (Session 7).** Applied with owner approval. Verified `enabled=True`, `startTime=09:00`, `retainedBackups=7`; instance stayed `RUNNABLE` (online, no restart). Command hung on response on the WSL host but succeeded server-side (`Updated [...instances/infinitecase-db]`, EXIT=0). |
| 3 | **Check the Credits page** on billing accounts `012771-2FDDA2-05C7DB` and `017067-5DE13C-479720` | `jett-prod` runs the exact `minScale=1` + `cpu-throttling:false` config that cost $321/mo on InfiniteCase, on an account with no export and no budget. Possible trial cliff. | **OWNER ONLY** — CLI cannot see trial-credit state. |
| 4 | **Diagnose `nba-bigquery-backups`** — claimed $0.01/day → $1.04/day in April, ~$31/mo | Read-only. | Diagnosed 2026-07-23 — see below. |

> **Item 4 finding (2026-07-23):** No project, service, or SKU named `nba-bigquery-backups` exists in the billing export. The 5 exported projects are `infinite-case`, `memberradar-prod`, `nba-props-platform`, `props-platform-web`, `urcwest`. nba-props-platform's entire April BigQuery cost is **$49.57 of query Analysis + ~$0.20/mo storage** — there is no backup SKU near $31/mo. The `$31/mo` was extrapolated from a single-day `$1.04` attribution on 2026-04-11; it is **not a real sustained line item on nba-props-platform.** (Pending: confirm no GCS "backups" bucket carries it.) Treat as the third over-broad audit premise (after the grading dedup and the zero-tolerance severity).

The 180-day `INFORMATION_SCHEMA.JOBS` reader census is **no longer urgent** — it existed to justify table drops, and those recommendations were refuted (§6).

---

## 4. August — safety fixes + config

Scoped by direct code reading on 2026-07-21. **Two of the six were mischaracterized by the audit.**

### 4.1 Fix the zero-tolerance fail-open — ~1 hour, LOWER severity than reported

`coordinator.py:1505-1508` has `except Exception: viable_requests = requests` with the comment *"Non-fatal: If quality gate fails, fall back to publishing all requests."* Change to `viable_requests = []`.

**But the real fail-open is elsewhere.** `predictions/worker/data_loaders.py:1042`:
```python
features['required_default_count'] = int(getattr(row, 'required_default_count', 0) or 0)
```
The `or 0` converts NULL → 0 → clean. The worker's backstop at `worker.py:2077` then reads that value and blocks correctly — so the coordinator bypass is **not** a total bypass; the worker still catches it whenever the value is present.

**Measured exposure: 44 NULL `required_default_count` rows out of 40,564 (0.1%).** Real, worth fixing, but not the emergency the assessment implied.

### 4.2 Make halts halt — ~1–2 hours

`mlb_best_bets_exporter.py:92-105` is 8 self-contained lines using `self.halt_envelope()`, already on the base class. Its own comment records the rationale: *"Without this, halt_state was advisory only — picks shipped with a halt flag."* Port to `signal_best_bets_exporter.py` and `best_bets_all_exporter.py`. Also make `base_exporter.py:394-399` fail closed on query error, matching its own missing-row behavior at `:401-414`.

The frontend contract was already solved for MLB — the exporter still emits the stable schema with an empty `best_bets` array.

> **⚠️ Session 7 — premise PARTLY STALE (verified). See `08-AUGUST-EXECUTION-PREP.md §4.2`.** `mlb_best_bets_exporter.py` **no longer exists** (can't port from it), and **both NBA exporters already call `halt_envelope`** (`signal_best_bets_exporter.py:119/164/474/797`, `best_bets_all_exporter.py:214`) — the "advisory-only" framing is outdated. The genuine residual is the second half only: `base_exporter.py`'s query-error `except` path (~`:394-399`) sets `halt_reason` but **not** `halt_active=True`, so a halt_state query failure fail-*opens* (the adjacent missing-row path `:407-413` correctly fail-closes). Action: verify the two exporters suppress picks on `halt_active`, then apply the one-spot `base_exporter.py` fail-closed fix.

### 4.3 The worker logging typo — 15 minutes, genuine one-liner

`predictions/worker/worker.py:2467`:
```python
logger.error(f"STAGING WRITE EXCEPTION for {player_lookup}: {type(e, exc_info=True).__name__}: {e} ...")
```
`type()` takes 1 or 3 arguments, never 2. This raises `TypeError` **inside the except handler**, so the original error is never logged, the metric never emitted, and the `return False` that triggers Pub/Sub retry never executes. Prediction-write failures are silently dropped.

Fix: `type(e).__name__`, with `exc_info=True` as a logger kwarg.

### 4.4 Batch-writer buffer ordering — ~2 hours

`shared/utils/bigquery_batch_writer.py:257-259` clears its buffer before I/O; on flush failure the records are gone and every caller discards the returned `False`. Fix: clear after success, surface `total_flush_failures` as a metric. Requires checking callers for anything relying on silent tolerance.

### 4.5 Terminate the retry recycle — ~half a day

`shared/utils/pipeline_logger.py:598-620` sets `status='pending', next_retry_at=now+15min` without incrementing `retry_count`; the dedup lookup matches only `('pending','retrying')` so `failed_permanent` re-mints a fresh row. Worth **~$30/mo measured** (the phase4 line on a zero-game day) and it restores meaning to the run ledger.

⚠️ `auto_retry_processor` is **manual-deploy only** — the fix does not reach it via push to main.

### 4.6 Config: min-instances → 0 — ~1 day

**Order matters.** Enable Eventarc `--retry` on the 3 orchestrator triggers *first* (they are `RETRY_POLICY_DO_NOT_RETRY`; min-instances is an expensive workaround for that), then set `min-instances=0`. Worth **$79/mo measured**.

Three reversion vectors must change in the same commit or it silently reverts:
- `bin/deploy-service.sh:51-62` hard-codes `minScale=1`
- Cloud Build triggers pass `_MIN_INSTANCES: 1`
- **`bin/validation/detect_config_drift.py` validates `min=1`** — your own validator will fight the change

> **Session 7 refinements (re-verified from source):**
> - **The Cloud Build vector is trigger config, not a repo file.** `cloudbuild.yaml:131` and `cloudbuild-functions.yaml:190` default `_MIN_INSTANCES: '0'` in-repo (comment at `cloudbuild.yaml:88`: *"Override per-trigger via _MIN_INSTANCES substitution (default: 0)"*). Any `=1` lives in **per-trigger GCP substitution config** — fix it with `gcloud builds triggers describe/update`, not a commit.
> - **The drift detector does NOT pin the coordinator.** `detect_config_drift.py` pins only the **3 CF orchestrators** to `min=1` (with high-severity escalation when actual < expected); `prediction-coordinator` is `EXPECTED_CLOUD_RUN` `min_instances: 0`. So for a **coordinator** min=0 change, only `deploy-service.sh:51-62` (which returns `"1"` for `prediction-coordinator`) would revert it — the drift detector won't even flag the drop. For the **orchestrators**, both `deploy-service.sh` and the drift detector must be updated.

### 4.7 The 100× shot-zone scale bug — ~2 hours + investigation

`player_shot_zone_analysis` stores percentages (0–100); the inline fallback `feature_extractor.py:880-888` computes ratios (0–1); `ml_feature_store_processor.py:1852-1854` divides by 100 unconditionally. Confirmed at source level. **Open question: how many historical rows are affected** — the fallback fires only on cache miss (`feature_extractor.py:1941-1949`). Measure before fixing; if historical features are wrong, backtests built on them need revalidation.

> **✅ Session 7 — MEASURED (resolves §8 uncertainty #5).** No per-row flag records fallback-vs-cache, so measured via a value-range proxy (shot-zone features in `(0, 0.01)`). Feature 19 (mid_range, the reliable tell) = **2,223 of 147,340 rows ≈ 1.5%**, present all seasons (this season ~0.3-0.4%). **Small blast radius** → fix is worth doing but backtests are only marginally contaminated (no revalidation emergency). Affected features `[18,19,20]`. Exact mechanism, real file paths (`data_processors/precompute/ml_feature_store/…`), the proxy query, and the recommended fix (normalize the fallback to 0-100 before the divide) are in **`08-AUGUST-EXECUTION-PREP.md §4.7`**.

### ❌ 4.8 Do NOT flip the grading dedup — the audit's recommendation was wrong

`04-ROBUSTNESS-ASSESSMENT.md` §9 item 4 recommends flipping `prediction_accuracy_processor.py:573` from `ORDER BY created_at DESC` to prefer the earliest pre-game row. **Do not do this.**

The code carries versioned intent:
```sql
-- v5.0: Deduplicate by business key, keeping the latest prediction
-- v5.5: Removed line_value from partition — one row per (player, game, model)
ROW_NUMBER() OVER (PARTITION BY player_lookup, game_id, system_id ORDER BY created_at DESC)
```

Keeping the **latest** prediction is correct. The system re-predicts as lines move; the final pre-game prediction against the closing line is what you would actually have bet. Flipping to earliest would grade the 8 AM prediction instead of the 4 PM one — **less accurate, and it would change every historical performance number in the project.**

The genuine narrower risk is a *post-tip* row winning the dedup, which the consolidation MERGE can create (it overwrites values while preserving `created_at`). The correct fix is a `WHERE created_at < tip` filter, not a reversal. Scope separately.

### 4.9 Pre-season smoke test of the restored fan-out path — ~1 hour, NEW (Session 6)

Item 1 recreated the fan-out plumbing, but its first real exercise would otherwise be opening night, against a `min-instances=0` worker taking a cold-start burst. Before Oct 21: publish **one synthetic message via `prediction-request-dev`** (NOT prod — publishing to prod triggers a real prediction) and confirm it reaches a staging write. Converts "item 1 should work" into "a message was seen traversing it." The coordinator already paces publishes at ~50/sec for cold start (`coordinator.py:3608`), so the path should absorb the opener burst — but verify, don't assume. Highest-regret gap otherwise.

> **⚠️ Session 7 — the premise needs REDESIGN (verified live 2026-07-24). Supersedes the "recreate the dev topic" note.** The `prediction-request-dev` topic is gone AND so is its whole sandbox: the **`nba-props-platform-dev` project does not exist** (`gcloud projects list` → only `nba-props-platform`; describing the dev project errors "not found"). The dev environment `test_prediction_worker.sh:19-25` / README `:80-175` reference — dev project, dev topic, `prediction-worker-dev`, dev subscription — is entirely absent. So there is **no dev sandbox to smoke-test against**; recreating just the topic is insufficient (it would belong to a non-existent project).
>
> **Redesign (recommended):** publish **one synthetic message to `prediction-request-prod`** for a throwaway player/game, confirm topic → sub → cold worker → staging write, then **delete the row**. This exercises the real opener path; off-season + halted makes a lone synthetic prediction low-harm. **Run AFTER §4.6** sets min=0 (else it tests a warm worker). Full options + rationale in **`08-AUGUST-EXECUTION-PREP.md §4.9`**.

### 4.10 Fix `feature_version` non-determinism — ~15 min, NEW (Session 6), pulled forward from §7

`predictions/worker/data_loaders.py:159-164` runs `SELECT DISTINCT feature_version … WHERE game_date=@d LIMIT 1` with **no `ORDER BY`**, while its own docstring claims *"Tries v2_39features first (newer), falls back to v2_37features."* The SQL does not implement that — on a two-version date (70 of 163 dates carry two) it picks non-deterministically, a train/serve skew risk. One-line fix: `ORDER BY feature_version DESC` (or encode the try-newer-first intent explicitly). Cheap enough to do in August rather than defer to October.

**August total: roughly 2–3 days**, not the month the assessment's framing implied.

---

## 5. September — monitoring that can be validated now

Build only what has inputs today:

| Item | Why now |
|---|---|
| Cost anomaly detector (`bin/monitoring/cost_anomaly_detector.py`) | Backtested: catches 2026-03-22 on day one and the June ramp 25 days early. ~$0.08/yr |
| Table-freshness monitor (`__TABLES__.last_modified_time`) | Costs $0, and **flags six known-dead tables today** — a green result would prove it broken |
| Budget restructure + BigQuery quota override | Per-project budgets with forecast thresholds → Slack. Kill the $40 always-firing budget |
| `shared/registry/monitors.yaml` + heartbeat meta-check | Makes silent monitor death and silent scheduler purges structurally impossible |
| DDL dry-run pre-commit hook | Would have caught `CLUSTER BY ... confidence_score DESC` the day it was committed |
| **Read `ml/signals/aggregator.py` for defects** (pulled from §8 #4) | Only Lens 8 *scanned* it (found no broad excepts / no stale allowlist). It's where the entire betting edge lives and September is the last quiet window to read it fully before game-day load returns. |

**Defer to October** (needs game-day data): pipeline SLOs, the pick-distribution monitor, live invariant checks.

---

## 6. Explicitly not doing

| Decision | Reason | Reopen if |
|---|---|---|
| **The Tier B consolidation** — permanently, not deferred | Red-team rejected it as specced (MLB breaks 4 ways, checkpointing unimplementable, ~60 callers, nothing to shadow off-season, 35–75 days not 12–20). And with a measured $0.73 marginal slate cost, its cash case is gone. The robustness case also weakened once the 12.9% failure rate proved half measurement artifact | Never on cost grounds |
| **Most §8 batch-read work** | **Measured:** a 15-game slate's entire marginal cost is $0.73. Batching cannot save meaningful money, and a correctness audit found it is the most dangerous change class — per-entity fallback semantics are already inconsistent today (`team_context.py:65,78` vs `:420` compute rebounding differently) | If a single batching target is measured >$20/mo |
| **Hash-skip on feature-store rebuilds** | The build reads live odds at run time. Include odds in the hash → never matches. Exclude → skips while lines move, and nothing would notice | Never |
| **Collapsing `player_daily_cache` / `player_shot_zone_analysis`** | "Sole consumer" premise was false — shot-zone has ~10 readers including `player_composite_factors` which produces feature-store features 5–8 | Never as scoped |
| **Cutting the 4 daily feature-store rebuilds** | 12.7% of the morning edge-3 pool churns by afternoon; would change ~70–130 picks/season to save ~$3/mo | If measured churn approaches zero |
| **Cutting the model fleet for cost** | $0.50–1.00/model/mo. Fleet is already 3, not the 10+ CLAUDE.md claims | Only for modeling reasons |
| **Scheduler consolidation as standalone** | $12/mo, and it is the silent-death failure class that killed weekly retraining | Only inside a larger change |
| **Throttling ad-hoc research** | $3–5/mo. 7% of March BigQuery. Refuted three times | Never |
| **A monitoring fleet** | ~40 monitors exist; `healing_events` has 1 row in all history | Never |
| **Flipping the grading dedup** | See §4.8 — the current behavior is correct | Never |

---

## 7. Recorded but not acted on

Real, understood, deliberately parked.

| Finding | Why parked |
|---|---|
| `OddsGameLinesProcessor` — 720,630 runs, 0 successes since Apr 19, still failing daily | Costs ~nothing; fix or delete during October restore |
| **`nbac_play_by_play` + `nbac_injury_report` mint ~12 `failed_permanent`/day since 2026-07-04** (measured Session 7 in `nba_orchestration.failed_processor_queue`; 141 rows each over 24 dates) | Terminal, not the runaway recycle (0 fresh re-mints — the §4.5 recycle is confirmed STOPPED). Trivial cost. Likely benign off-season (no games), but these are **core in-season sources** — **MUST verify green at October restore.** Also: `succeeded` rows in this ledger stopped exactly 2026-07-04, partly explaining §8 #2's unexplained stop. |
| ~99% `model_bb_candidates` provenance loss (33 rows all-time) | Writer fixed in `8449f4e3`; verify at season open rather than backfill |
| Live look-ahead leak — `team_defense_zone_analysis_processor.py:478` inclusive `BETWEEN ... AND analysis_date` | **Real and should be fixed**, but needs measurement of backfill impact first. Add a BETWEEN rule to `check_date_comparisons.py` |
| `best_bets_published_picks` is `WRITE_TRUNCATE`, not the append-only ledger its docstring claims; holds 89 rows vs 203 picks | Affects history reconstruction, not live picks |
| `expected_by` anchored to midnight UTC of `game_date` — post-game deadlines elapse before tip-off | Fix during October restore; it is plausibly Loop-B fuel |
| Four orphaned CFs firing daily with no repo source | Delete during October cleanup; download source archives first |
| `system_circuit_breaker.py:243` hardcodes decommissioned systems — live fleet unprotected | No pick incident traced to it |
| `_breakout_classifier` declared, never assigned — silently never runs | Fix or delete the code path; do not monitor a corpse |
| Three conflicting `feature_version` strings; worker's `SELECT DISTINCT ... LIMIT 1` has no `ORDER BY` | 70 of 163 dates carry two versions. Non-deterministic. **Fix before October** |
| GCS: 802,041 object versions, `v1/tonight/all-players.json` alone has 43,282 | Entire bucket is <$1/mo. Apply the lifecycle rule as hygiene, carving out the five pick prefixes |

---

## 8. What we're uncertain about

1. **The in-season estimate ($200–250/mo) rests on April data taken during an active halt.** No fully clean in-season measurement exists, and none will until November.
2. **The phase4 retry loop's July 4 stop was never explained.** Its $30/mo is measured; whether the fix holds is not. **Session 7 partial:** the runaway recycle is confirmed STOPPED (0 fresh `retry_count=0` re-mints since 07-04 in `failed_processor_queue`), and `succeeded` rows in that ledger also stopped exactly 2026-07-04 — so *something* changed globally on 07-04. What remains is a benign ~12/day terminal-failure floor from two scrapers (§7). The recycle cost is gone; the trigger of the 07-04 change is still unexplained.
3. ~~**`nba-bigquery-backups` is undiagnosed** — ~$31/mo that appeared in April.~~ **RESOLVED Session 6: PHANTOM — no such line item (§3 item 4). Not an uncertainty.**
4. **~35 publishing exporters, Phase 4 internals, and `ml/signals/aggregator.py` remain unread.** Given a $0.73 marginal slate, none can hide meaningful *cost* — but the aggregator is where the entire betting edge lives, and nobody has read it for defects.
5. ~~**The 100× shot-zone bug's historical blast radius is unmeasured.**~~ **RESOLVED Session 7: ~1.5% of feature-store rows (2,223/147,340), small.** See §4.7 / `08-AUGUST-EXECUTION-PREP.md`.
6. **This document's own history.** The in-season figure has been revised $880 → $650 → $424 → $150 → $200–250 as measurement replaced inference. Treat the current number as the best available, not as settled.

---

## 9. Sequence

| When | What |
|---|---|
| **This week** | §3 items 1–4 |
| **August** | §4.1–4.10 (~2–3 days) — **turnkey diffs ready in `08-AUGUST-EXECUTION-PREP.md`.** Apply order: trivial batch (§4.3/4.10/4.1/4.5/4.4) → §4.6 coordinated → §4.7 (fix approach chosen) → §4.9 redesigned |
| **September** | §5 monitors |
| **October** | Restore per manifest with corrections: strike the 3 dead scrapers, hold the canary until its image fix is verified deployed, fix the `expected_by` anchor, fix the `feature_version` non-determinism |

---

*Plan 2026-07-21. Nothing applied. Every item awaits approval.*
