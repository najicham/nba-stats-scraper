# 2026-09-08 — Honest measurement, green CI, two inert gates closed, Pub/Sub topology

Successor to `2026-09-07-NEXT-SESSION-MENU.md`. Work done 2026-09-08; **committed and pushed
2026-09-13** (the owner reviewed it before pushing, which is why the dates differ).

**Opener 2026-10-20 (37 days from the push). First publishable pick ~2026-11-17.**

Menu items **C, A, D and E** are done. **B, F, G, H, I are untouched** — see §6.

Every claim below rests on a positive artifact: a row count, a test count, a quota error with
its own text, an exit code.

---

## 0. One paragraph

The headline is §1. `signal_best_bets_picks` now carries `is_backfilled`, and with it the
2025-26 record stops flattering the system: **69 genuinely live picks at 46.8% hit rate
against 134 retrospectively generated ones at 64.6%.** The right predicate turned out to be
tip-off rather than calendar date, and a second signal fell out of the data that nobody had
looked for — every one of the 45 rows carrying a line no sportsbook would offer (8.9, 30.9,
24.3) is retro, and every live row is a clean .0 or .5. CI went from 171 failures to zero,
and the process of getting there found that unit tests had been writing into the production
run-history table and running live BigQuery jobs on the owner's account. The Phase 5→6
completeness gate and the worker's dead-letter problem are both closed, though the second one
for a different reason than the menu assumed: `maxScale` is not a stale safe-mode value, it is
a hard regional quota ceiling, and concurrency is the only lever that costs nothing.

---

## 1. `is_backfilled` + `bet_key` — menu item C

> **Do not read a hit rate off `signal_best_bets_picks` without `is_backfilled = FALSE`.**

### 1.1 The predicate is tip-off, not date

A pick is dishonest when it was written after its outcome was knowable. Calendar date is a bad
proxy: a pick written at 22:42 ET on game day is the same UTC *date* as a pick written at
13:28 the next afternoon only half the time, and the ET-date rule and the UTC-date rule
disagree with each other (112 rows vs 126). Tip-off is the real line.

Tip-off lives in `nba_raw.nbac_schedule.game_date_est`. **That column is UTC despite its
name** — verified by its hour distribution, which clusters at 17:00–04:00 UTC, i.e. 12:00–23:00
ET tip-offs. The join is not the obvious one either: the picks table's `game_id` is
`YYYYMMDD_AWAY_HOME` while `nbac_schedule.game_id` is the NBA's `00225009xx` form, so the join
goes through `game_date` plus the tricodes parsed out of the picks id. That matched **203 of
203 rows**, no fallback needed.

```sql
-- the backfill, for the record
UPDATE `nba-props-platform.nba_predictions.signal_best_bets_picks` p
SET is_backfilled = (
      SELECT p.created_at >= MAX(s.game_date_est)
      FROM `nba-props-platform.nba_raw.nbac_schedule` s
      WHERE s.game_date = p.game_date
        AND s.away_team_tricode = SPLIT(p.game_id,"_")[SAFE_OFFSET(1)]
        AND s.home_team_tricode = SPLIT(p.game_id,"_")[SAFE_OFFSET(2)]
    )
WHERE p.game_date > "2020-01-01"
```

### 1.2 What it says

| | rows | graded | HR | rows with a non-book line |
|---|---|---|---|---|
| **live** (`created_at < tipoff`) | 69 | 62 | **46.8%** | **0** |
| **retro** (`created_at >= tipoff`) | 134 | 127 | 64.6% | **45** |

The line-value column is the part nobody had checked, and it is the strongest corroboration
available. Prop lines are whole or half numbers. **All 45 rows whose `line_value` is neither
(8.9, 30.9, 24.3, 34.4 …) are in the retro set; every live row is clean.** Those rows are
simulated, not recorded. Restricting the retro set to book-shaped lines drops its hit rate
from 64.6% to 60.2% — still inflated, and still not a number to plan against.

This is consistent with, and now more precisely measured than,
`published-picks-63pct-retro-2026-09-05`.

### 1.3 `bet_key`

`bet_key` = `{game_id}|{player_lookup}|{recommendation}|{line_value:.1f}`, deliberately
**excluding `system_id`**: three models nominating the same wager is one bet, not three.

It is unique across all 203 rows, which settles something. The 3.7x inflation in the
"415-235" figure did **not** come from duplication inside this table — it came from the
*join* to `prediction_accuracy` being unscoped. `bet_key` exists so that join has one correct
key. The Python and SQL forms must stay byte-identical; both live in
`shared/utils/bet_key.py`, with the SQL form in its docstring.

### 1.4 What changed in code

- `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql` — both columns, documented.
- `signal_best_bets_exporter._write_to_bigquery` stamps them per export. It resolves tip-offs
  with one partition-filtered query per run. **`is_backfilled` is NULL, not FALSE, when the
  tip-off cannot be resolved** — "we don't know" must never read as "this was live".
- `best_bets_record_exporter` filters `is_backfilled IS NOT TRUE` in all three of its queries.
  Zero effect on 2026-27 numbers today (no rows yet); it exists so that a re-exported
  historical date cannot silently enter the published record mid-season.

### 1.5 Still open — an owner decision, not a bug

The **public** record still reports the contaminated figure for 2025-26. Filtering it makes
the site retroactively show 46.8% where it showed 64.6%. That is a product decision and it was
deliberately not made here.

---

## 2. CI — menu item A

**171 failed / 22 errors → 0. 2,704 → 2,930 passed.** Stable across three full runs with
randomised ordering. Reproduce CI faithfully, offline, with:

```bash
env CLOUDSDK_CONFIG=/nonexistent/gcloud GOOGLE_APPLICATION_CREDENTIALS=/nonexistent/adc.json \
  PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -q --tb=line \
  --ignore=tests/unit/scrapers/ --ignore=tests/unit/services/ --timeout=60
```

### 2.1 The credential pile — and what it was hiding

93 failures were `DefaultCredentialsError` raised directly, plus several more where the code
under test swallowed the error and the test then failed on a baffling downstream assertion
(`'MockProcessor' object has no attribute '_run_start_time'`, `assert False`).

The fix is `install_anonymous_credentials()` in `tests/conftest.py`, called from autouse
fixtures in `tests/unit/conftest.py` and the new `tests/cloud_functions/conftest.py`. It is
**not** global: `tests/integration/` legitimately wants real ADC.

The reason to care is not the badge. Anonymous credentials are forced *even when ADC is
present*, and that stopped three things nobody had noticed:

1. **`tests/unit/patterns/test_dependency_tracking.py` failed 22/22 without ADC but only 2/22
   with it.** The 20-test difference was real BigQuery work, against the owner's project,
   every time anyone ran the unit suite.
2. **Unit tests were writing into production.** `bigquery_batch_writer` keeps a process-global
   singleton registry with an `atexit` hook that flushes buffered records. Tests exercising
   `RunHistoryMixin` left rows in that buffer, and with credentials present the hook wrote them
   into `nba_reference.processor_run_history`. `tests/unit/conftest.py` now drains the
   registry around every test.
3. `tests/unit/prediction_tests/coordinator/test_firestore_arrayunion_limits.py` issued live
   Firestore RPCs — visible as `403 SERVICE_DISABLED` for a project literally named
   `test-project`. It patched the module's lazy `_get_firestore` loader, but
   `BatchStateManager.__init__` gets its client from `shared.clients.get_firestore_client`,
   which was never patched.

### 2.2 The drift pile

Every one was "production changed, the test didn't" — with one exception worth stating
plainly.

**`tests/unit/test_health_checker.py` tested an API that has never existed.** The test and
`shared/endpoints/health.py` arrived in the *same merge* (`a7a8fb83`) with different
signatures; `git show a7a8fb83:shared/endpoints/health.py` confirms it. All 23 tests have
failed continuously since that day, which means the module six orchestrator Cloud Functions
mount their `/health` endpoints from has had **zero** effective coverage. It is rewritten
against the real API: 31 tests over `HealthChecker`, `CachedHealthChecker`,
`create_health_blueprint` and the dependency-checker factories.

The rest, briefly:

| test | what production did |
|---|---|
| `test_execution_logger` (17) | writes buffer via `get_batch_writer` since the 2026-01-28 partition-quota fix; tests asserted immediate insert. Also `system_errors` is a BQ **JSON** column, so the writer passes a dict — the test demanded a pre-serialised `str`, which would double-encode. |
| `test_batch_staging_writer_race_conditions` (30) | `predictions/coordinator/{distributed_lock,batch_staging_writer}.py` are now **shims**; patch targets must be `predictions.shared.*`. Also `INSERT ROW` → explicit column list (Session 39), a second active-duplicate gate (Session 495), and `cleanup_orphaned_staging_tables` returning a dict. |
| `test_firestore_arrayunion_limits` (13) | dual-write is **transactional**; the test counted two `doc_ref.update()` calls that no longer happen. |
| `test_run_history_mixin`, `test_circuit_breaker_mixin` | both moved to the batch writer; neither touches `processor.bq_client` any more. |

### 2.3 Three traps worth remembering

- **`dict.get(k, Mock(spec=bigquery.Client))` evaluates its default eagerly.** Once
  `bigquery.Client` is patched, that constructs `Mock(spec=<MagicMock>)` and raises
  `InvalidSpecError` on *every* call, key present or not. Every thread in the pool
  thread-safety test died in there, so `get_client_count()` read 0.
- **A hardcoded date turned a test into a time bomb.** `test_dependency_tracking` passed
  `'2024-11-20'`, and `check_dependencies()` deliberately *skips* the freshness check for dates
  older than `max_age_hours_fail`. Those two tests stopped exercising staleness the moment that
  date aged past 72 hours. They use `date.today()` now.
- **A no-op `time.sleep` does not make a wall-clock loop fast.** `test_retry_delay_between_attempts`
  stubbed sleep while the retry loop bounds itself on `time.time()`, producing a 15-second busy
  spin — 623,400 attempts — slow enough to trip the 60s timeout under load.

### 2.4 Two production fixes that fell out

- `predictions/shared/batch_staging_writer.py` reported *any* schema-validation failure as
  `"SCHEMA MISMATCH: Worker output has 0 fields not in BQ table: []"`. A 403 or a timeout
  therefore sent the operator to `ALTER TABLE` for a problem that had nothing to do with the
  schema. It now names the real error.
- `_check_for_active_duplicates` returns `-1` when its own query fails, and the caller tested
  `> 0` — so an unverifiable check read as "no duplicates" and went on to **delete the staging
  tables**, destroying the only evidence of a possible duplicate incident. It now keeps the
  consolidation successful (the MERGE has committed) but never cleans up on an unverified
  result. Both have regression tests.

### 2.5 Known gap

⚠️ **`tests/cloud_functions/` is not run by CI.** `.github/workflows/test.yml` collects only
`tests/unit/`. Nine tests in `test_phase5_to_phase6_handler.py` were failing unnoticed; that
file is fixed (33/33) and the directory now has a conftest, but adding it to CI is blocked by a
**collection-time** error in `test_phase3_orchestrator.py` — a module-level GCP client, which
no fixture can intercept.

---

## 3. The two inert gates — menu item D

### 3.1 D1 — Phase 5→6 completeness

`MIN_COMPLETION_PCT = 80.0` could never block anything. The override immediately above it
fired whenever `status == 'success' and completed_predictions > 0 and completion_pct <
MIN_COMPLETION_PCT`, and the coordinator reports `success` for stall-completed **partial**
batches. So the only batch the gate could reject was one with zero predictions — which the
`> 0` clause already excluded. A slate published off 56.1% completion.

The override was written for a real case: manually re-triggered batches never call
`start_batch`, so `run_history` has no expected count and the coordinator reports `0.0`. That
case is *unknown*, not *low*. The condition is now `<= 0`.

A genuine partial still publishes. Blocking Phase 6 trades a visible gap for an invisible
drought, and droughts have cost this system more. But it is no longer silent:

- logged at `CRITICAL`,
- emits the `phase6_partial_slate` metric,
- stamps `partial_slate` and `upstream_completion_pct` onto the Phase 6 trigger message —
  `None`, never a fabricated 100, when completion is unknown.

`PHASE6_BLOCK_ON_LOW_COMPLETION=true` makes the threshold blocking. That is an owner decision
and the default is deliberately the non-blocking one.

> Adding `emit_metric` required adding `google-cloud-monitoring` to that function's
> `requirements.txt` — and **the repo's own test caught the omission**
> (`tests/unit/observability/test_pipeline_state_metrics.py`). That is
> `observability-emitter-fails-open-2026-08-24` working exactly as designed.

### 3.2 D2 — the menu's diagnosis was wrong

The menu proposed raising `maxScale`. It cannot be raised:

```
CpuAllocPerProjectRegion requested: 50000 allowed: 20000
MemAllocPerProjectRegion requested: 107374182400 allowed: 42949672960
```

`prediction-worker` sits at `maxScale=10` because us-west2 is **at its regional Cloud Run
quota ceiling**, shared across ~95 services. `--max-instances=50` is refused outright. This
also revises the standing assumption that the live 10/1 was a stale "emergency safe mode"
value left over from January — it is a ceiling, not a leftover.

**Concurrency is the lever that costs no quota.** Applied live 2026-09-08:

| change | before | after |
|---|---|---|
| `prediction-worker` `containerConcurrency` | 1 | **5** (10 × 5 = 50 in flight, same allocation) |
| `prediction-request-prod` `retryPolicy` | *none* | **30s–600s** |
| `prediction-request-prod` `maxDeliveryAttempts` | 5 | **20** |

Concurrency is safe here because `get_worker_id()` mints a fresh UUID per *call*, so
concurrent requests on one instance still write separate staging tables. `bin/predictions/deploy/deploy_prediction_worker.sh`
has specified concurrency 5 for prod since January 2026; live simply never matched it, because
**neither `bin/deploy-service.sh` nor `cloudbuild.yaml` passed `--concurrency` or
`--max-instances`**. That is how a hand-set value becomes permanent and invisible — the same
shape as the Session 338 minScale bug. `bin/deploy-service.sh` now pins it via
`get_concurrency()`, mirroring the existing `get_min_instances()`.

If more worker capacity is ever genuinely needed, the options are a regional quota increase,
or reclaiming allocation from the halted MLB stack (`mlb-phase4-precompute-processors` alone
reserves 10 × 8Gi) and the two known permanent strays (`analytics-processor`,
`nba-reference-service`).

---

## 4. Pub/Sub topology — menu item E

Publishing to a topic with no subscription **succeeds**. A message id comes back, the caller
logs "triggered", the message is discarded. This has now caused three separate incidents
(`pubsub-ttl-deleted-dispatch-2026-09-02`, `prediction-ready-prod` on 09-07, and the below), so
it is now a standing check rather than an audit:

```bash
PYTHONPATH=. python bin/validation/validate_pubsub_topology.py        # exit 1 if any dead target
PYTHONPATH=. python bin/validation/validate_pubsub_topology.py --json
```

It reads the live topic list, so it needs no hardcoded inventory. It distinguishes code that
**publishes** from code that merely **mentions** a topic, and requires the name to appear as a
string literal — otherwise every docstring explaining a dead topic re-reports it and the exit
code stops meaning anything. Dead-letter sinks are allow-listed with reasons.

Current reading: **49 topics, 20 with at least one subscription, 10 dead publish targets.**

### 4.1 The menu was out of date on BDB

> "`nba-phase3-trigger` … BDB retry re-processing is dead"

Half right. The **live** path was already fixed: `bdb-retry-hourly` → `bdb-retry-trigger` →
the `bdb_retry_processor` Cloud Function, which POSTs a Phase-2 envelope to Phase 3's
`/process` endpoint over HTTP and even documents why. What was still dead:

- the three `bin/monitoring/bdb_{retry_processor,pending_monitor,critical_monitor}.py`
  operator tools, which logged `✅ Triggered Phase 3 re-run` while publishing into nothing.
  They now call the extracted `shared/utils/phase3_trigger.trigger_phase3_rerun()`.
- `auto_backfill_orchestrator`, which has the same bug but **no subscription and no
  scheduler** — so its breakage is latent. It is another entry for the
  deployed-but-never-invoked list in menu item F.

**Phase 3 is triggered over HTTP**, at `nba-phase3-analytics-processors/process`.
`nba-phase3-trigger` has had no subscribers since the Phase 2→3 migration. Note Phase 3
returns **200 even on partial failure**, so a 200 means "accepted", not "the data is correct" —
callers needing the stronger guarantee must verify the output table, as the CF does.

---

## 5. What is live vs what shipped in this push

**Already live before the push** (applied directly 2026-09-08, no deploy required):
BigQuery columns + backfill on `signal_best_bets_picks`; worker `containerConcurrency` 1→5;
`prediction-request-prod` retry policy and delivery attempts.

**Shipped by the push:** everything else. Note that adding two files under `shared/utils/`
fans the build out to ~25 triggers at once, which is the exact condition behind
`deploy-fanout-quota-silent-cf-failure` — and the project is now known to be *at* its regional
quota ceiling. Deploy verification for this push is recorded in §7.

---

## 6. Untouched menu items

| item | one line |
|---|---|
| **B** | Prove the `signal_best_bets_picks` INSERT. Option 3 — a direct writer test against a scratch dataset — is cheapest and does not touch frozen `ml/signals/`. Nobody has done it. |
| **F** | Scheduler Wave C, plus the never-invoked functions. Add `auto_backfill_orchestrator` to that list (§4.1). |
| **G** | `prediction-coordinator` is `allUsers`-invocable and accepts any string after `Bearer `. Owner decision. |
| **H** | The three assertions that would have caught this week's P0s. §4's validator is the third one, now built. |
| **I** | Small leftovers, including the unpartitioned `ml_feature_store_v2`. |

---

## 7. Deploy verification — done 2026-09-13

**All 24 services and functions touched by this push serve `851f811`.** Verified by reading
each one's *serving* revision's `BUILD_COMMIT`, not by build status. `latestReady ==
latestCreated` on every core service; no half-failed revisions left behind.

It did not get there in one go, and the way it failed is worth recording.

Adding two files under `shared/utils/` fanned the deploy out to ~25 Cloud Build triggers
simultaneously, and the project is at its regional Cloud Run CPU ceiling (§3.2). Several
builds died with:

```
ERROR: (gcloud.run.deploy) Quota exceeded for total allowable CPU per project per region.
… Quota-blocked (attempt 3/3); ERROR: still quota-blocked after 3 attempts.
```

This is `deploy-fanout-quota-silent-cf-failure` recurring — **except it was not silent this
time.** `cloudbuild.yaml`'s quota-aware retry wrapper tried three times with backoff and then
failed the build loudly, so the affected services went on serving their previous revision
rather than going green on a deploy that never landed. That wrapper earned its keep here.

The recovery is the documented one: **re-run the trigger, never re-push**, and do it
**serially** — firing them all again just re-exhausts the same quota. Eight services needed a
second pass (`prediction-worker`, `nba-phase3-analytics-processors`,
`nba-phase4-precompute-processors`, `phase6-export`, `phase4-to-phase5-orchestrator`,
`phase3-to-phase4-orchestrator`, `bias-decay-monitor`, `mlb-prediction-worker`,
`filter-counterfactual-evaluator`); each succeeded first time once it had the quota to itself.

Note `phase4-to-phase5-orchestrator` and `phase3-to-phase4-orchestrator` were found stale at
`1e44991` / `a3f3466` — they had been stale *before* this push, from the 09-06 session. Worth
assuming nothing about a service's deployed state without reading it.

Live config survived the redeploys, which was not guaranteed: `cloudbuild.yaml` passes neither
`--concurrency` nor `--max-instances`, so `gcloud run deploy` preserved
`containerConcurrency=5` and `maxScale=10`. `prediction-request-prod` still carries the
30s–600s retry policy and 20 delivery attempts.

### How to verify it yourself next time


Do not use `gcloud builds list` as a deploy oracle — it paginates misleadingly, and a build
can go green while its revision never becomes ready. Read the **serving** revision's
`BUILD_COMMIT`:

```bash
COMMIT=$(git rev-parse --short HEAD)
for S in prediction-coordinator prediction-worker nba-phase3-analytics-processors \
         nba-phase4-precompute-processors nba-scrapers nba-grading-service; do
  R=$(gcloud run services describe $S --region=us-west2 --project=nba-props-platform \
        --format="value(status.latestReadyRevisionName)")
  B=$(gcloud run revisions describe $R --region=us-west2 --project=nba-props-platform \
        --format="value(spec.containers[0].env.filter(\"name:BUILD_COMMIT\").extract(\"value\"))")
  echo "$S  serving=$R  BUILD_COMMIT=$B  (want $COMMIT)"
done
```

Known permanent strays that will never match: `analytics-processor`, `nba-reference-service`,
`prediction-coordinator-dev`. If a build failed, re-run **that trigger**
(`gcloud builds triggers run <name> --branch=main`) — never re-push.
