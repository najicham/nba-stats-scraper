# Session Handoff — 2026-07-21 (Session 5, off-season)

**Branch:** `main`, clean. **System state:** OFF-SEASON, halted; opener ~Oct 21 2026.
**⚠️ NOTHING WAS APPLIED IN SESSION 5 (2026-07-21). Zero code, config, infra, or data changes. Read-only throughout.**

> **UPDATE 2026-07-23 (Session 6):** §3 **item 1 is now APPLIED** — the `prediction-request-prod` push subscription was recreated with a DLQ; Phase 5 fan-out is restored. Do **not** re-run the item-1 create (it exists). Corrections found while applying: the topic AND the `prediction-request-dlq` topic already existed (only the subscription was missing); real ack-deadline is **300s** (not 60s); dead-lettering also required a pubsub-agent `subscriber` grant on the new subscription (now in place). Contract verified end-to-end (worker `/predict` decodes the push envelope; coordinator publish shape matches). Items 2/3/4 still open. Full detail in `06-PLAN.md §3` and memory `gcp-cost-audit-item1-applied-2026-07-23`.

Owner asked to investigate a ~$1,000/month GCP bill. That expanded into a full cost + robustness + monitoring audit run across ~35 agents. Output is **six documents** and a plan awaiting approval.

---

## 0. TL;DR for whoever picks this up

1. **The cost problem largely solved itself.** June's $1,019 was ~$550 one-time events and already-fixed bugs. Current run rate ~$225/mo all projects.
2. **The real finding is a broken safety layer**, not cost.
3. **In-season 2026-27 forecast: ~$200–250/mo** (measured 2026-07-21, see §3).
4. **The big rewrite is closed permanently.** So is most batch-read optimization. See `06-PLAN.md` §6.
5. **August work is ~2–3 days**, not a month.
6. **Two audit findings were WRONG and were corrected** — see §5. Do not act on the original versions.
7. Next action: four items in `06-PLAN.md` §3, one of which only the owner can do.

---

## 1. Documents produced (all in `docs/08-projects/current/gcp-cost-audit-2026-07/`)

| File | Contents |
|---|---|
| `00-FULL-ANALYSIS.md` | Wave 1 — billing, infrastructure, multi-account picture, guardrails design |
| `01-WAVE-2-PIPELINE-EFFICIENCY.md` | Wave 2 — pipeline compute, root cause, named call sites, 14 non-cost findings, 13 refuted hypotheses |
| `02-DECISION-RECORD.md` | Tradeoffs, reversibility matrix, assumptions register, what-would-change-our-answer |
| `04-ROBUSTNESS-ASSESSMENT.md` | Safety-layer audit ⚠️ **contains one wrong recommendation — see §5** |
| `06-PLAN.md` | **The plan. Start here.** Supersedes `02`'s sequencing where they conflict |

**Gaps:** `03-VALIDATION-PLAYBOOK.md` and `05-MONITORING-DESIGN.md` were designed by agents but **never written to disk** — their content exists only in this session's transcript. If needed, they must be reconstructed. `06-PLAN.md` §5 carries the monitoring essentials.

---

## 2. What the money actually was

| Month | Net | Note |
|---|---|---|
| Feb 2026 | $568 | |
| Mar 2026 | $956 | seasonal peak + deploy churn |
| Apr 2026 | $695 | |
| May 2026 | $602 | |
| **Jun 2026** | **$1,025** (invoice $1,019.49) | **~$550 was bugs/one-offs** |
| Jul MTD | $189 | ~$7.40/day since a 2026-07-04 cliff |

**June's composition, verified:**
- ~$225 — an MLB Pub/Sub 404 redelivery storm (1.06M requests in 16 off-season days), fixed by `64315182`
- ~$232 — a one-off `nba-phase2-raw-processors` backfill (May 31 – Jun 16)
- ~$75–100 — an off-season backfill treadmill
- $336 — `infinitecase-backend` on `minScale=1` at 4 vCPU/16 GiB, **fixed by the owner 2026-07-03**; that project has billed $0.00/day for Cloud Run since

**The billing account carries 5 projects** (nba-props-platform, infinite-case, urcwest, memberradar-prod, props-platform-web) and **there are 5 billing accounts / 17 projects total**. Two open accounts have **no billing export** and were never analyzed — see §7.

---

## 3. The measured baseline (do not re-derive — this was measured 2026-07-21)

Earlier forecasts of **$424/mo** used Feb 19 – Mar 31 medians. **That window predates the 2026-04-08 retry-storm fix** (commit `37c6f2b9`).

Direct measurement, same billing export:

| Service | Mar 10 (11 games, storm active) | Apr 10 (15 games, post-fix) |
|---|---|---|
| `nba-phase2-raw-processors` | $6.82 | **$0.16** |
| `nba-phase3-analytics-processors` | $4.54 | **$0.46** |
| BigQuery | $7.04 | **$0.63** |
| `nba-phase4-precompute` | $2.29 | $1.07 |

**The per-game-day framing was wrong. Cost is floor-dominated:**

| Date | Games | Total |
|---|---|---|
| 2026-04-11 | **0** | $9.65 |
| 2026-04-10 | **15** | $11.10 |
| 2026-04-12 | **15** | $12.18 |

> **The marginal cost of a 15-game slate is ~$0.73–2.33.** The April fixed floor was ~$9.65/day ≈ **$290/mo**.

Zero-game-day composition (2026-04-11):

| Component | $/day | $/mo |
|---|---|---|
| prediction-coordinator idle | 1.21 | 36 |
| 3 orchestrators idle | 1.44 | 43 |
| prediction-worker idle (removed 2026-07-05) | 0.93 | 28 |
| phase4 retry loop | 0.99 | 30 |
| broken canary | 0.66 | 20 |
| **`nba-bigquery-backups`** | 1.04 | **31 — UNDIAGNOSED** |
| Scheduler + BQ + rest | 3.38 | 101 |

**Caveat:** April had the edge-based auto-halt active since ~Mar 28 — **zero picks published**, only 3 systems (768 predictions vs March's 2,640 across 10). The fleet *is* currently 3 models, so that part is representative, but full pick publishing will add load.

**Forecast: in-season ~$200–250/mo after the §4 fixes. Annual average ~$130–150/mo.**

> The in-season number has been revised **$880 → $650 → $424 → $150 → $200–250** across this session as measurement replaced inference. Treat it as best-available, not settled.

---

## 4. Do these first (`06-PLAN.md` §3)

| # | Action | Who |
|---|---|---|
| 1 | Recreate the **`prediction-request-prod` Pub/Sub subscription** with `deadLetterPolicy.maxDeliveryAttempts=5` → `prediction-request-dlq`. **It does not exist — Phase 5 fan-out is dead.** Blocks opening night *and* any test harness | assistant, on approval |
| 2 | `gcloud sql instances patch infinitecase-db --project=infinite-case --backup-start-time=09:00 --retained-backups-count=7` — **zero backups exist today** | assistant, on approval |
| 3 | Console → Billing → Credits page on `012771-2FDDA2-05C7DB` and `017067-5DE13C-479720` | **OWNER ONLY** |
| 4 | Diagnose `nba-bigquery-backups` ($0.01/day Mar → $1.04/day Apr, ~$31/mo) | assistant, read-only |

---

## 5. ⚠️ CORRECTIONS — two audit findings were wrong

### 5.1 DO NOT flip the grading dedup

`04-ROBUSTNESS-ASSESSMENT.md` §9 item 4 says to change `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py:573` from `ORDER BY created_at DESC` to prefer the earliest pre-game row. **This is wrong and would be harmful.**

The code carries versioned intent (`:566-577`):
```sql
-- v5.0: Deduplicate by business key, keeping the latest prediction
-- v5.5: Removed line_value from partition — one row per (player, game, model)
ROW_NUMBER() OVER (PARTITION BY player_lookup, game_id, system_id ORDER BY created_at DESC)
```

Keeping the **latest** is correct — the system re-predicts as lines move, and the final pre-game prediction against the closing line is what you'd actually have bet. Flipping it would grade the 8 AM prediction instead of the 4 PM one: **less accurate, and it would change every historical performance number in the project**, including the 60%+ BB hit rate.

The genuine narrower risk is a **post-tip** row winning the dedup (the consolidation MERGE overwrites values while preserving `created_at`). Correct fix: a `WHERE created_at < tip` filter. Scope separately.

### 5.2 The zero-tolerance hole is 0.1%, not a crisis

The assessment says `coordinator.py:1505-1508`'s `except Exception: viable_requests = requests` silently disables zero tolerance. Verified nuance:

- The worker backstop at `predictions/worker/worker.py:2077` **does still block** whenever `required_default_count` is present.
- The actual fail-open is `predictions/worker/data_loaders.py:1042`:
  ```python
  features['required_default_count'] = int(getattr(row, 'required_default_count', 0) or 0)
  ```
  The `or 0` converts NULL → 0 → clean.
- **Measured exposure: 44 NULL rows of 40,564 (0.1%)** in `ml_feature_store_v2` since 2025-10-01.

Still worth ~1 hour to fix both. Not the emergency the assessment implies.

---

## 6. August work — scoped by direct code reading (~2–3 days total)

Full detail in `06-PLAN.md` §4.

| Fix | Effort | Notes |
|---|---|---|
| Zero-tolerance fail-open (`coordinator.py:1508` + `data_loaders.py:1042`) | ~1h | see §5.2 |
| **Halts that don't halt** | 1–2h | Port `mlb_best_bets_exporter.py:92-105` (8 self-contained lines) to `signal_best_bets_exporter.py` + `best_bets_all_exporter.py`. NBA writes `halt_active` into JSON but still ships `picks[]`. Also make `base_exporter.py:394-399` fail closed |
| **Worker logging typo** | 15 min | `worker.py:2467` — `type(e, exc_info=True).__name__`. `type()` takes 1 or 3 args, never 2 → raises TypeError **inside the except handler**, so the error is never logged and the `return False` that triggers Pub/Sub retry never runs |
| Batch-writer buffer ordering | ~2h | `bigquery_batch_writer.py:257-259` clears the buffer before I/O |
| **Retry recycle** | ~half day | `pipeline_logger.py:598-620`. Worth **$30/mo measured**. ⚠️ `auto_retry_processor` is **manual-deploy only** |
| **min-instances → 0** | ~1 day | Worth **$79/mo measured**. ⚠️ Enable Eventarc `--retry` FIRST. Three reversion vectors must change in the same commit: `bin/deploy-service.sh:51-62`, Cloud Build `_MIN_INSTANCES: 1`, and **`bin/validation/detect_config_drift.py` which validates `min=1`** |
| 100× shot-zone scale bug | ~2h + investigation | `feature_extractor.py:880-888` computes ratios (0–1); the table stores percentages (0–100); `ml_feature_store_processor.py:1852-1854` divides by 100 unconditionally. **Measure historical blast radius before fixing** |

---

## 7. Open / unresolved

1. **Two billing accounts never analyzed** — `012771-2FDDA2-05C7DB` (jett-prod, urcw-prod, urcw-staging, appius-demo, gen-lang-client) and `017067-5DE13C-479720` (dmhr-platform, jig-hq-demo). No billing export exists on either. **`jett-prod` serves `api.jetthq.com` on `minScale=1` + `cpu-throttling: false`** — the exact config that cost $321/mo on InfiniteCase. Possible free-trial cliff.
2. **`nba-bigquery-backups`** — ~$31/mo, appeared April, undiagnosed.
3. **The phase4 retry loop's 2026-07-04 stop was never explained.** Dormant, not proven fixed. It re-armed once already (2026-03-09 backfill).
4. **Three conflicting `feature_version` strings**; the worker's `SELECT DISTINCT ... LIMIT 1` at `data_loaders.py:141-183` has **no `ORDER BY`** and the result is a hard filter. 70 of 163 game dates carry two versions. **Fix before October.**
5. **Live look-ahead leak** — `team_defense_zone_analysis_processor.py:478` uses inclusive `BETWEEN ... AND analysis_date`. Unchanged since Oct 2025. Silent in production, **active in backfill → train/serve skew**.
6. **`expected_by` anchored to midnight UTC of `game_date`** — NBA tips 00:00–03:00 UTC on `game_date+1`, so post-game deadlines elapse before tip-off. Plausibly Loop-B fuel. Fix at October restore.
7. **Never read by any agent:** ~35 of 44 publishing exporters, Phase 4 processor internals, and **`ml/signals/aggregator.py`** — where the entire betting edge lives. At $0.73 marginal per slate they cannot hide meaningful cost, but they could hide correctness bugs.

---

## 8. Environment gotchas (cost this session real time)

- **Billing export is partitioned on `_PARTITIONTIME`, NOT `usage_start_time`**, and `requirePartitionFilter` is off — filtering only on `usage_start_time` silently scans all 3.45 GB. Pad `_PARTITIONTIME` ~4 days wider than the usage window.
- **Credits are a NEGATIVE nested ARRAY** — `cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)`. UNNEST and **ADD**, never subtract.
- **Cross-region:** the billing export is in **US**; `nba_*` datasets are in **us-west2**. A single query joining them fails with *"Dataset not found in location US."* Run separately; pass `--location=us-west2` for the NBA datasets.
- **`gcloud`/`bq` default project is wrong** (was `urcwest` this session) — always pass `--project=nba-props-platform` / `--project_id=nba-props-platform`.
- Billing export lags ~1 day; the most recent day is partial. Use **D-2** for comparisons.
- **The subagent runtime failed repeatedly late in this session** — 6 agents stalled with "no progress for 600s," across different briefs and reading budgets. If agents stall, do the work directly rather than relaunching; two relaunches also failed.

---

## 9. Decisions closed — do not re-litigate

Full table with reopen conditions in `06-PLAN.md` §6. Headlines:

- **The Tier B consolidation** (93 services → ~5, one Cloud Run Job) — **closed permanently**, not deferred. Red-teamed and rejected: MLB breaks 4 ways (`mlb-phase2-raw-processors` has no build of its own — it deploys from the NBA phase2 image), the `expected_outputs` checkpointing claim is unimplementable (`RUNNING` is never written by any code path), ~60 callers, nothing to shadow off-season, 35–75 days not 12–20. And at $0.73 marginal per slate its cash case is gone.
- **Most §8 batch-read work** — measured, not inferred: you cannot batch your way to savings on a $0.73 slate. Also the most dangerous change class (per-entity fallback semantics are already inconsistent — `team_context.py:65,78` vs `:420` compute rebounding two different ways *today*).
- **Hash-skip on feature-store rebuilds** — the build reads live odds at run time. Include odds → hash never matches. Exclude → skips while lines move, and nothing would notice.
- **Collapsing `player_daily_cache` / `player_shot_zone_analysis`** — "sole consumer" was false; shot-zone has ~10 readers including `player_composite_factors`, which produces feature-store features 5–8.
- **Cutting the 4 daily feature-store rebuilds** — 12.7% of the morning edge-3 pool churns by afternoon; ~70–130 picks/season to save ~$3/mo.
- **Cutting the model fleet for cost** — $0.50–1.00/model/mo, and the fleet is already 3, not the "10+" CLAUDE.md claims.
- **Throttling ad-hoc research** — $3–5/mo, 7% of March BigQuery. Refuted three times.
- **Budget-triggered billing disable** — destroys resources on a false positive.

---

## 10. Suggested first message for the new chat

> Read `docs/08-projects/current/gcp-cost-audit-2026-07/06-PLAN.md` and `docs/09-handoff/2026-07-21-SESSION-5-HANDOFF.md`. Nothing has been applied. Start with §3 of the plan — the four this-week items. Note §5 of the handoff: two recommendations in `04-ROBUSTNESS-ASSESSMENT.md` are wrong and were corrected.

---

*Handoff 2026-07-21. Read-only session. Repo HEAD unchanged at `3b8f448e`.*
