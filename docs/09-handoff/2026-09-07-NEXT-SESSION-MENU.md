# 2026-09-07 — Menu for the next session

Companion to `2026-09-07-PHASE5-PROVEN-AND-THREE-P0S.md`, which records what happened. **This
document does not tell you what to do.** It is a menu with evidence, effort and risk attached to
each item, so you can choose. Read §1 and §5 first, then pick.

**Opener 2026-10-20 (43 days). First publishable pick ~2026-11-17.**

---

## 0. How to use this

Three decision rules that have repeatedly proven right on this codebase:

1. **A success report is weak evidence.** Every item below carries an artifact or is explicitly
   marked unverified. Do the same for whatever you conclude.
2. **Prefer removing a silent failure over adding a capability.** Every P0 found in the last
   three sessions was something that reported success while doing nothing.
3. **Absence of an error is not evidence of success.** Four traps, all still live: `/process-date`
   returns 200 `{"stats":{}}` while writing nothing; `logger.info` is discarded in every Gen2 CF;
   a `_Default` sink exclusion drops `severity=INFO` for ~30 services matching
   `monitor|check|health|reconcil|alert|summary`; `emit_metric` fails open. Use
   `region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT` — it is immune to all four.

---

## 1. Hard calendar constraints

| date | what | source |
|---|---|---|
| **2026-09-20** | Roster deadline flagged by the 5-agent review — **13 days away**. ⚠️ Re-verify what it actually gates before assuming it is urgent; it is the one dated item on the board. | `five-agent-review-2026-09-01` |
| 2026-10-20 | NBA opener. Everything in §2 must be true by then. | — |
| ~2026-11-03 | First date the feature store would surface a gap (bootstrap window ends day 14). | `2026-09-06-RESTORE-AND-REHEARSAL.md` §3.5 |
| ~2026-11-17 | First publishable pick. | 5-agent review |

The gap between opener and first pick is the real safety margin: **four weeks of live pipeline
with nothing published.** That is the window in which anything not proven now gets proven for
free — which is an argument for spending September on the things that window *cannot* prove.

---

## 2. What is now proven vs. still assumed

**Proven end-to-end, 2026-09-07, with artifacts:** Phase 4 write path, Phase 5 dispatch →
worker → staging → consolidation → 510 production rows, Phase 5→6 orchestration firing
automatically, Phase 6 running the full per-model pipeline and writing
`best_bets_filtered_picks` / `best_bets_filter_audit` / GCS JSON.

**Still assumed:**

- The `signal_best_bets_picks` INSERT. Last successful production run 2026-04-07. Unexercised
  since, and unexercisable on any historical date without loosening a threshold (the filter stack
  rejects 100%: 37/37, 37/37, 77/77 across three date/fleet combinations).
- That phases 3 and 4 will emit a Cloud Monitoring datapoint now that `google-cloud-monitoring` is
  installed. The package is verified present and importable *in the built image*; no phase-3 or
  phase-4 run has happened since.
- Everything about live GCP state after **2026-09-07 ~05:15Z** — HTTPS egress from the dev host
  dropped at that point (ICMP fine, TCP 443 timing out both v4 and v6). See §5.

---

## 3. The menu

Ordered by my estimate of value-per-hour, not by importance. Disagree freely.

### A. Finish the CI triage — the 09-06 framing was wrong, and it is cheaper than it looks

**Status:** open. CI is red on every PR (171 failed / 2,704 passed).

The standing belief is "~81 of those are `DefaultCredentialsError`; much of `tests/unit/` is not
hermetic; the next step is to make the suite hermetic." **That is only half right.** Measured
2026-09-07 by re-running the named clusters with `CLOUDSDK_CONFIG` and
`GOOGLE_APPLICATION_CREDENTIALS` pointed at nonexistent paths, i.e. CI conditions:

| cluster | failures | actual cause |
|---|---|---|
| `tests/unit/patterns/test_dependency_tracking.py` | 22 | **credentials** — `DefaultCredentialsError` raised directly |
| `tests/unit/mixins/test_run_history_mixin.py` | — | **credentials** — error swallowed by the code under test, surfaces as `mock.load_table_from_json` not called |
| `tests/unit/patterns/test_circuit_breaker_mixin.py` | — | **credentials**, same shape |
| `tests/unit/test_health_checker.py` | 23 | **API drift** — `HealthChecker.__init__() got an unexpected keyword argument 'project_id'`. Nothing to do with credentials. |
| `tests/unit/prediction_tests/test_execution_logger.py` | 17 | **assertion drift** — `assert len([]) == 1` |
| `tests/unit/clients/test_bigquery_client.py` | 1 | **assertion drift** — `get_client_count()` returns 0, expected 2 |

So it splits into two piles with different fixes: a conftest-level credential stub for one, and
ordinary stale-test triage for the other. `tests/conftest.py` and `tests/unit/conftest.py`
currently do **no** credential stubbing at all — an autouse fixture setting
`google.auth.credentials.AnonymousCredentials` plus `GOOGLE_CLOUD_PROJECT` is one small change
that plausibly clears the whole first pile.

Note the corollary, which is the reason to care beyond a green badge: `test_dependency_tracking`
fails 22/22 without ADC but only 2/22 with it. **Those 20 tests were doing real GCP work against
the owner's account whenever anyone ran the suite locally.**

- **Effort:** low for the credential pile, medium for the drift pile.
- **Risk:** low. Nothing production-facing.
- **Verify:** run each cluster with the two env vars pointed at nonexistent paths; that is a
  faithful CI emulation and it needs no network.
- **Trap:** do not "fix" the drift pile by loosening assertions. `test_health_checker` is
  asserting against a signature that production changed — decide which side is wrong.

### B. Prove the `signal_best_bets_picks` INSERT

**Status:** open, and it is the last unproven link in the money path.

Three options, in increasing order of how much you have to ask the owner for:

1. **Wait.** The Oct 20 → Nov 17 window proves it for free, and the code is unexercised rather
   than untested. Cost: if it is broken, you find out on a live slate.
2. **Owner-approved one-off relaxation** on a scratch date, immediately reverted. This is the only
   option that exercises the real write path before the opener. It requires touching
   `ml/signals/`, which is frozen, so it needs explicit sign-off — the freeze is a count
   (100 graded 2026-27 picks), not a date, so it will not lift on its own.
3. **A test that exercises the writer directly** against a test dataset, bypassing selection
   entirely. Proves the INSERT and the schema mapping, not the pipeline that feeds it. Cheapest,
   and does not touch frozen code.

Option 3 is probably the right first move and nobody has done it.

- **Effort:** low (3), medium (2).
- **Risk:** (2) touches frozen code and a live table; (3) is contained.

### C. `is_backfilled` + `bet_key` on `signal_best_bets_picks`

**Status:** open. Confirmed 2026-09-07 against `schemas/bigquery/nba_predictions/signal_best_bets_picks.sql`
— the table has `created_at` and **neither** `is_backfilled` nor `bet_key`.

Until the flag exists, **every hit-rate query on that table is wrong**: 63% of its rows were
generated after the outcomes they describe (live 70 picks @ 45.7%, retro 119 @ 66.4%). This is
the single biggest source of false confidence in the whole system, and it is a schema change plus
a backfill of a boolean derived from `created_at` vs `game_date`.

- **Effort:** low-medium.
- **Risk:** low, but get the backfill predicate right — `created_at > game_date + slate end` is
  not the same as `created_at::date > game_date`, and picks legitimately get written the morning
  of. Look at the actual `created_at` distribution before choosing a rule.
- **Value:** unlocks honest measurement everywhere downstream. Arguably this should be first.

### D. Close the two inert gates found on 2026-09-07

Both are "the guard exists and cannot fire", the failure mode this codebase keeps producing.

**D1 — Phase 5→6 completeness gate.** `orchestration/cloud_functions/phase5_to_phase6/main.py:202`
bypasses `MIN_COMPLETION_PCT = 80` whenever `status == 'success' and completed_predictions > 0`.
The coordinator reports `status='success'` for stall-completed **partial** batches, so the gate
can only ever block a batch with zero predictions. Observed publishing off 56.1% completion.

**D2 — worker capacity / DLQ.** `prediction-worker` is `maxScale=10`, `containerConcurrency=1`,
`cpu=1`. A 399-request slate put **107 requests (27%) into `prediction-request-dlq` in under two
minutes**, and nothing consumes that DLQ. November slates are the same order of magnitude.

D1 and D2 compound: a real slate can lose a quarter of its players and publish anyway with
nothing flagging the gap.

- **Effort:** low for D2 (scaling + retry backoff, both config). Medium for D1 — the *right*
  behaviour is a judgement call, since blocking Phase 6 on a partial slate can itself cause a
  drought. Consider a third state: publish, but stamp the payload with the completion percentage.
- **Risk:** D1 changes when picks publish. Owner call.

### E. The dead-letter and dead-topic sweep

`prediction-ready-prod` having no subscriber was the worst defect of the off-season, and it was
found by a two-line `comm` between topics and subscriptions. Six more topics that in-repo code
publishes to still have **no subscriber**:

| topic | publisher | consequence |
|---|---|---|
| `nba-phase3-trigger` | `bin/monitoring/bdb_{critical,pending,retry}_*.py` | **BDB retry re-processing is dead** |
| `boxscore-gaps-detected` | `orchestration/cloud_functions/backfill_trigger` | gap events go nowhere |
| `nba-scraper-trigger` | `data_processors/analytics/main_analytics_service.py` | — |
| `nba-predictions-trigger` | `phase4_to_phase5`, `phase4_timeout_check` | harmless: HTTP path also used |
| `nba-prediction-trigger` | `coordinator.py`, `bdb_retry_processor.py` | — |
| `nba-phase6-export-complete` | `phase6_export/main.py` | no consumer needed? confirm |

Plus: the DLQ topics (`nba-phase1-scrapers-complete-dlq`, `nba-phase2-raw-complete-dlq`,
`nba-phase3-analytics-complete-dlq`, `nba-phase4-precompute-complete-dlq`) — check whether
anything watches them, because dead-lettered pipeline messages accumulating unseen is the same
class of problem.

```bash
comm -23 <(gcloud pubsub topics list --project=nba-props-platform --format='value(name.basename())'|sort) \
         <(gcloud pubsub subscriptions list --project=nba-props-platform --format='value(topic.basename())'|sort -u)
```

- **Effort:** low to audit, variable to fix (each needs a decision: wire it up, or delete the
  publisher).
- **Risk:** low. Deleting a dead publisher is safer than leaving a lie in the code.

### F. Scheduler restore Wave C + the never-invoked functions

⚠️ **All of this is from the local snapshot `ops/scheduler-snapshots/scheduler-jobs-latest.json`,
dated 2026-08-22: 169 jobs, 95 PAUSED. This session resumed 18, so the live number differs.
Re-verify before acting.**

Known individually-named items, each needing live confirmation:

- `decay-detection` — has a scheduler but it is PAUSED, so BLOCKED models are **not** auto-disabled.
- Both pipeline canaries — PAUSED, so the documented 30-minute pick-drought alerting does not run.
- `weekly-retrain-trigger` — exists **PAUSED**. `resume`, do not re-create.
- `validation-runner`, `grading-readiness-monitor`, `grading-gap-detector` — deployed, no scheduler,
  no in-repo caller. Cost plus false confidence.
- `deploy-monthly-retrain` — **confirmed locally 2026-09-07**: `orchestration/cloud_functions/monthly_retrain/`
  does not exist, so this trigger is permanently red. Red noise trains people to ignore red. Delete it.
- `cloudbuild-precompute.yaml` — **confirmed locally 2026-09-07**: exists, and nothing references it.
- Four CFs with no Cloud Build trigger (`halt-state-writer`, `expected-outputs-planner`,
  `phase-completion-reconciler`, `gap-detector`) — a push does **not** deploy them. Use
  `./bin/deploy-function.sh <name>`.

- **Effort:** low each, but there are many. Good candidate for one focused pass.
- **Risk:** resuming a scheduler starts spending money and mutating data. Measure cost first —
  the 09-06 session measured one Phase-4 chain at 5.6 GB ≈ $0.035, and a no-game day at 0 bytes.

### G. Security: the coordinator is open to the internet

`roles/run.invoker` includes `allUsers`, **and** `require_api_key` returns success for any string
after `Bearer ` without verifying it. Measured: `Bearer not-a-real-token` → HTTP 200 on `/status`;
no header → 401. `POST /start`, `/reset`, `/cleanup-duplicates`, `/cleanup-staging`,
`/check-stalled`, `/regenerate-pubsub`, `/regenerate-with-supersede`, `/line-update` are all
reachable.

Not changed this session because callers depend on the current setup: `phase4_to_phase5` calls
`/start` over HTTP, and the new `prediction-ready-prod-sub` posts to `/complete`. Both use service
accounts that already hold `run.invoker`, so removing `allUsers` is *probably* safe — confirm each
caller's SA first, then verify the OIDC token (audience + issuer) instead of trusting the prefix.

- **Effort:** low.
- **Risk:** medium — get it wrong and Phase 5 stops being triggerable. Do it with a rollback ready,
  and not on a day anything is running.
- **Owner decision.**

### H. Observability that would have caught all three of this week's P0s

None of the three would have been caught by an alert. Worth asking what the smallest set of checks
is that turns each into a page:

- "Phase 5 completed a batch but `player_prop_predictions` gained no rows" — catches the missing
  subscription, the consolidation path, and staging-table leaks in one assertion.
- "The number of distinct `system_id`s writing predictions today ≠ the number of enabled models" —
  catches both silent-invisibility traps (`is_production`, and the hardcoded allowlist in
  `build_system_id_sql_filter()`).
- "A topic that in-repo code publishes to has zero subscriptions" — catches §E as a test, not an audit.

The first two are BigQuery queries the existing `expected_outputs` machinery could carry. The third
is a pre-commit or CI check.

- **Effort:** medium.
- **Value:** this is the "fix the system, not the code" option. It is the only item here that
  reduces the rate of future P0s rather than clearing the current ones.

### I. Smaller, well-scoped leftovers

- Symlink validator into `pre-commit-checks.yml`.
- `check-deployment-drift.sh`: service map + `set -u` + `$SERVICES`.
- Grading `sportsbook` / `line_source_api` SELECT fix (two lines).
- `pipeline_reconciliation` swallowing exceptions.
- Injury check fails open.
- `INSUFFICIENT_DATA` floor `n7<5` → `n7>=30` — **required before any 4th model**, because
  `AUTO_DISABLE_ENABLED=true` on the deployed decay CF.
- `ml_feature_store_v2` is UNPARTITIONED (`part=NONE`) — every query full-scans it. Fix before
  season volume returns; ⚠️ could not re-confirm live today, verify first.
- `shared/utils/odds_preference.py:34` and `odds_player_props_preference.py:33` each call
  `bigquery.Client()` **at import time**. Nothing currently imports them, so this is latent, not
  active — but it is exactly the shape that breaks CI the moment someone does import them.
- `_obs` filter naming: `line_jumped_under_obs` **blocks** despite the suffix (deliberate, to
  preserve CF-HR history). Every reader misreads this. A comment is not enough; consider a
  registry field that says `blocking: true` independent of the name.
- `filter_summary.rejected` mixes units — `rescue_health_gate` counts signal *tags*, not picks.

---

## 4. Do NOT

Unchanged and still load-bearing:

- 🧊 **Code freeze on `ml/signals/`** until 100 graded 2026-27 picks exist. Bug fixes and
  observability are fine; anything that changes selection is not. Measured cost of the old cadence:
  **-7.8pp**.
- Do not backfill `model_performance_daily` (negative EV; its `if rows:` guard skips the worst dates).
- Do not delete signal rescue (rescued picks beat the same-day control by 17pp).
- Do not lower the OVER floor to 3.0 (49.0% on n=584, costs 12-14u/season).
- Do not ship the "two-line" BigDataBall fallback fix (it is five bugs).
- Do not add a 4th model before the `INSUFFICIENT_DATA` floor moves to n7≥30.
- Do not trust any hit rate from `signal_best_bets_picks` until `is_backfilled` exists (§C).
- Do not use `gcloud builds list` as a deploy oracle. Read the **serving** revision's env.
- Do not run `./bin/model-registry.sh sync` without checking the GCS manifest — its MERGE sets
  `is_production` from manifest status and will revert the champion.
- **New:** do not widen `model_bb_candidates` to include filter-rejected candidates — it would
  mislabel them `merge_rejected` and corrupt the C4 promotion tracker.
- **New:** do not read `filter_summary.rejected` as a pick-level histogram.
- **New:** do not re-add `is_production = FALSE` to any model-loading query.

---

## 5. First 20 minutes: re-verify, because the host lost network

HTTPS egress from the dev host dropped at ~2026-09-07 05:15Z (ICMP to 8.8.8.8 fine, TCP 443
timing out on both v4 and v6, `gcloud` failing with `Network is unreachable` on token refresh).
Everything in §3 marked "re-verify" is unconfirmed after that point. If `gcloud` still fails,
that is the host, not GCP — this environment has a documented history of it.

```bash
# 0. is the host actually online for HTTPS?
curl -4 -sS -o /dev/null -w "%{http_code}\n" --connect-timeout 10 https://oauth2.googleapis.com/

# 1. schedulers — expect 18 of the resumed set ENABLED
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform \
  --format="value(name.basename(),state)" | sort | awk '{print $2}' | uniq -c

# 2. fleet — expect exactly 3 enabled, catboost_v12_noveg_train1205_0403 is_production
bq query --project_id=nba-props-platform --use_legacy_sql=false \
 'SELECT model_id, enabled, is_production FROM `nba-props-platform.nba_predictions.model_registry` WHERE enabled OR is_production'

# 3. the subscription created 2026-09-07 — if this is empty, Phase 5 is broken again
gcloud pubsub subscriptions list --project=nba-props-platform \
  --format="value(name.basename(),topic.basename())" | grep prediction-ready

# 4. serving commits, not spec commits
for S in prediction-coordinator prediction-worker nba-phase3-analytics-processors \
         nba-phase4-precompute-processors nba-scrapers nba-grading-service; do
  r=$(gcloud run services describe $S --region=us-west2 --format="value(status.latestReadyRevisionName)")
  c=$(gcloud run services describe $S --region=us-west2 --format="value(status.latestCreatedRevisionName)")
  echo "$S ready=$r created=$c"
done

# 5. evidence base intact — expect 203 picks, 0 created today
bq query --project_id=nba-props-platform --use_legacy_sql=false \
 'SELECT COUNT(*) n, COUNTIF(DATE(created_at)=CURRENT_DATE()) today
  FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` WHERE game_date > "2020-01-01"'
```

Expected at handoff: 18 resumed jobs ENABLED · 3 enabled models · `prediction-ready-prod-sub`
present · all six services `ready == created` at `d62bb76` (coordinator, worker) or `3e52e0f`
(the other four) · 203 picks, 0 created today · no `_staging_*` tables.

Leftover snapshots, safe to drop: `nba_predictions_backups.rehearsal2_ppp_20260410_pre`,
`nba_predictions_backups.rehearsal2_dps_20260410_pre`.

---

## 6. If you want one recommendation

Do **§C (`is_backfilled`)** first. Everything else on this list is judged by numbers that come out
of that table, and right now those numbers are known to be wrong in a direction that flatters the
system. Fixing measurement before fixing anything measured is the cheapest way to avoid spending
September optimising against a 66% hit rate that was really 46%.

Then **§A**, because red CI on every PR is how the next silent regression gets merged, and it is
now known to be a smaller job than advertised.

But this is your call — that is the point of the document.
