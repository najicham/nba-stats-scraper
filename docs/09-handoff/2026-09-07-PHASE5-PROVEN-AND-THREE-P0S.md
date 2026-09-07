# 2026-09-07 — Phase 5 proven end-to-end, and three P0s found on the way

Successor to `2026-09-06-RESTORE-AND-REHEARSAL.md`. That document is correct except where
noted in §3.1 below.

**Opener 2026-10-20 (43 days). First publishable pick ~2026-11-17.**

Every claim below rests on a positive artifact — a row count that changed, an HTTP status with
a body, a log line, a query in `region-us-west2.INFORMATION_SCHEMA.JOBS_BY_PROJECT`.

---

## 0. One paragraph

The three assigned items are done and verified in production. Doing item 4 — the rehearsal —
turned up **the single worst defect found this off-season**: the Pub/Sub subscription that
carries worker completion events back to the coordinator did not exist, and because the worker
writes to *staging* tables that only batch completion consolidates, **Phase 5 would have
produced zero rows in `player_prop_predictions` on opening night**, silently, with the worker
reporting success. It also turned up that yesterday's champion-model fix silently cut the
prediction fleet from 3 models to 2. Both are fixed. Phase 5 has now run end to end for the
first time — 438 predictions written and consolidated, Phase 6 auto-triggered by the chain —
and the one link still unproven is the `signal_best_bets_picks` INSERT itself, because the
filter stack legitimately rejects 100% of candidates on every historical date available.

---

## 1. Assigned work — done

### 1.1 Coordinator past-date guard parameterised (item 1) — `3e52e0ff`
`validate_game_date()` hard-coded 90 days. Now `COORDINATOR_MAX_PAST_DAYS` /
`COORDINATOR_MAX_FUTURE_DAYS`, with a garbage-input fallback to the defaults.

The bigger half was the message. A new `check_game_date()` returns a reason string, and
`/start` returns **400** with it instead of a 404 that said "No players found" while the same
body reported 486 players. Proven live before the env var was set:

```
POST /start {"game_date":"2026-04-10", ...}
HTTP 400 {"status":"invalid_game_date",
          "message":"invalid_game_date: >90d in past (2026-04-10 is 150d ago)",
          "hint":"Set COORDINATOR_MAX_PAST_DAYS to widen the horizon for backfills/rehearsals"}
```

The same guard now fronts the two internal regeneration helpers, which previously returned
`status: success, requests_published: 0` on a rejected date. The residual 404 no longer claims
zero players when the summary says otherwise.

`COORDINATOR_MAX_PAST_DAYS=400` was set on `prediction-coordinator` for the rehearsal and
**removed afterwards** — the service is back on the 90-day code default (re-confirmed live).
Set it again when a historical backfill needs it.

### 1.2 `model_bb_candidates` — the premise was wrong, the writer is fine (item 2) — `3e52e0ff`
The 09-06 finding ("77 candidates flowed through 7 pipelines and it wrote ZERO ROWS; the writer
emits nothing") is **incorrect**. `PipelineResult.candidates` is the return value of
`BestBetsAggregator.aggregate()`, i.e. predictions that **passed** the negative-filter stack.
Filter-rejected candidates are recorded in `best_bets_filtered_picks`. Zero survivors ⇒ zero
rows, correctly.

Proof, `nba_predictions`, every day since 2026-03-01:

| game_date | mbc rows | was_selected | published picks | filtered picks |
|---|---|---|---|---|
| 2026-04-07 | 2 | 1 | 1 | 22 |
| 2026-04-06 | — | — | — | 11 |
| 2026-03-25 | 12 | 7 | 7 | 29 |
| 2026-03-22 | — | — | — | 2 |

`COUNTIF(was_selected)` equals the published pick count on **every** day with rows; 0-pick days
have no rows while `best_bets_filtered_picks` has 2–29. This is exactly how
`v_bb_candidate_signal_stream` consumes the table: leg 3 = `merge_rejected`, leg 2 = `filtered`.

**Do not "fix" this by widening it.** `merge_rejected` outranks `filtered` in that view's
disposition dedup, so filtered candidates written here would be mislabeled and would corrupt
the C4 promotion tracker.

The writer also emits **all 47 schema columns** — the older "30 of 47 NULL" framing is stale
too. The real defect was that the zero case returned silently, and Gen2 CFs discard
`logger.info`, so "no rows" was indistinguishable from "writer failed". It now says so at
WARNING. Observed live at 04:42:37Z:

```
model_bb_candidates: 0 rows for 2026-04-10 — no candidate survived the negative-filter stack
in ANY model pipeline. This is expected on a 0-pick day; filter-rejected candidates are
recorded in best_bets_filtered_picks, not here.
```

A load-job row-count mismatch is now reported too.

### 1.3 `google-cloud-monitoring` on 5 services (item 3) — `3e52e0ff`
Added to both `requirements.txt` and `requirements-lock.txt` for prediction-coordinator,
nba-phase3-analytics-processors, nba-phase4-precompute-processors, nba-scrapers and
nba-grading-service. Pinned `==2.27.2`, which spans **both** protobuf regimes in the fleet
(4.25.8 on coordinator/scrapers/grading, 6.33.5 on phase3/phase4) — 2.27.2 requires
`protobuf>=3.20.2,<7.0.0`.

All five lock files verified with `pip install --dry-run` (exit 0). Then verified in the built
artifact, not just the manifest:

```
$ docker run --entrypoint python <coordinator:3e52e0f> -c "..."
google-cloud-monitoring 2.27.2
protobuf 4.25.8
google-api-core 2.29.0
client ctor path importable OK
```

All five serve `3e52e0f`, read off `status.latestReadyRevisionName` (not the service spec).

---

## 2. Three defects found while doing item 4

### 2.1 ⚠️⚠️ P0 — Phase 5 could never finish: `prediction-ready-prod` had no subscribers
`gcloud pubsub subscriptions list | grep prediction-ready` returned **nothing**, while the
worker publishes completions to that topic (`PUBSUB_READY_TOPIC=prediction-ready-prod`, read
off the serving revision).

This is not cosmetic, because the worker does **not** write to `player_prop_predictions`. It
writes one staging table per worker (`nba_predictions._staging_{batch}_{worker}`), and only the
coordinator's `BatchConsolidator` MERGEs staging → production — which runs **only** when the
batch is marked complete, which happens **only** in `/complete`, which is fed **only** by a push
subscription on `prediction-ready-prod`.

So the chain was: requests published → worker predicts → staging write OK → completion event
published to a subscriber-less topic (**Pub/Sub still returns a message id**) → coordinator
never learns → batch never completes → **no MERGE, no production rows** → no
`nba-phase5-predictions-complete` publish → `phase5_to_phase6` never fires.

`/check-stalled` is not a fallback: it completes a batch only above `min_completion_pct`
(default 95), and with zero completion events a batch sits at 0%.

Observed directly mid-rehearsal: 219 staging tables present, `player_prop_predictions` for the
target date = **0 rows**.

**Fixed** — created `prediction-ready-prod-sub` (push → coordinator `/complete`, OIDC as
`prediction-coordinator@`, ack 60s, 7d retention, `--expiration-period=never`). Verified
working: batch progress moved 0 → 19 → 292 completions within seconds of the first request.

This is the same failure class as the 2026-09-02 31-day TTL deletion, where only
`prediction-request-prod` was restored and the ready leg was missed. **Durable rule: after any
Pub/Sub incident, audit both legs of every request/response pair.**

Other topics that in-repo code publishes to with **no subscriber** (lower severity — all have a
working alternate path, but each is a silent no-op): `nba-phase3-trigger` (this is how the BDB
retry processors re-run Phase 3 — that path is dead), `boxscore-gaps-detected`,
`nba-scraper-trigger`, `nba-predictions-trigger`, `nba-prediction-trigger`,
`nba-phase6-export-complete`.

### 2.2 ⚠️ P0 — yesterday's champion promotion silently removed the model from the fleet — `a7231e01`
`get_enabled_models_from_registry()` filtered `AND is_production = FALSE`, left over from when
the champion loaded via the separate legacy `CatBoostV12` path. That path is gated behind
`ENABLE_LEGACY_V12`, which is **false** in production, so after
`catboost_v12_noveg_train1205_0403` was promoted on 09-06 **nothing loaded it at all**.

Measured on the 399-player batch before the fix:

```
worker: Loaded 2 monthly model(s) (2 from registry, 0 from dict):
        ['lgbm_v12_noveg_train0206_0402','xgb_v12_noveg_train0206_0402']
worker: CatBoost V12 legacy model SKIPPED (ENABLE_LEGACY_V12=false)
```
and 20 sampled staging tables contained only lgbm + xgb rows.

So the 09-06 fix that made `get_champion_model_id()` resolve also made the champion produce
nothing, and cut the effective fleet 3 → 2. Fixed by dropping the `is_production` filter —
`enabled = TRUE` is now the whole contract. `get_enabled_monthly_models()` already dedupes by
model_id, so a model reachable from both paths still loads once.

### 2.3 Travel-context query has violated the `nbac_schedule` partition filter since 2026-06-30 — `d62bb760`
Every Phase 6 export logs:

```
Failed to query travel context: 400 Cannot query over table
'nba-props-platform.nba_raw.nbac_schedule' without a filter over column(s) 'game_date'
```

`ml/signals/supplemental_data.py` put the date range in the **ON clause of a LEFT JOIN**, which
BigQuery does not accept as partition elimination. The caller catches and continues, so
`westward_road_trip_under` and `b2b_long_haul_under` have been evaluating against an empty
travel map for ten weeks. Both are SHADOW signals, so they do not feed `real_sc` and this
changes no selection — which is why the fix is safe under the `ml/signals/` freeze. Verified
with a BigQuery dry run (accepted, 63,962 bytes).

---

## 3. The rehearsal

Target date **2026-04-10**: 117 clean feature-store rows, 159 players with odds, and — critically
— **zero** existing picks/filtered-picks/candidates, so every row written was additive and
attributable.

| stage | result |
|---|---|
| **Phase 5 dispatch** | ✅ `POST /start` → **HTTP 202**, batch `batch_2026-04-10_1788755749`, 399 requests published. |
| **Worker → coordinator** | ✅ Completions flowed for the first time (§2.1). 292/399 completed, 0 failed. |
| **Consolidation** | ✅ 219 staging tables MERGEd and dropped; **438 rows** written to `player_prop_predictions`. |
| **Phase 5 → Phase 6** | ✅ Chain fired automatically: `phase5-to-phase6-orchestrator` logged the completion and published to `nba-phase6-export-trigger`. |
| **Phase 6** | ✅ Ran the full per-model pipeline (≈40 queries visible in `JOBS_BY_PROJECT`), wrote `best_bets_filtered_picks` 46, `best_bets_filter_audit` 1, and a 48,774-byte `signal-best-bets/2026-04-10.json`. |
| **`signal_best_bets_picks`** | ❌ **0 rows — still the one unproven link.** |

### 3.1 Why there is still no pick row
The filter stack rejects **100%** of candidates on every historical date reachable, and this is
consistent behaviour, not breakage — both dates produced 0 picks live too.

| date | fleet | candidates | passed | picks |
|---|---|---|---|---|
| 2026-04-10 (Phase 5 re-generated) | 2 models | 37 | 0 | 0 |
| 2026-04-12 (native in-season predictions) | 3 models incl. catboost | 37 | 0 | 0 |
| 2026-03-12 (09-06 session) | 7 models | 77 | 0 | 0 |

2026-04-12 blockers: `over_edge_floor` 9, `line_jumped_under_obs` 9,
`blowout_risk_under_block` 8, `bench_under` 5, `opponent_depleted_under` 5, `flat_trend_under`
4, `q4_scorer_under_block` 3, `blacklist` 2, plus three singletons.

**Producing a pick requires loosening a threshold, which the `ml/signals/` freeze forbids.**
Options, owner's call:
1. Accept that the INSERT proves itself on the first live slate (it last ran successfully in
   production on 2026-04-07, so it is not untested code — just unexercised since).
2. Approve a one-off, immediately-reverted threshold relaxation on a scratch date purely to
   exercise the write.

### 3.2 Two `_obs` questions from 09-06, resolved
- `line_jumped_under_obs` **DOES block** (`continue` after `_record_filtered`). The `_obs`
  suffix was deliberately kept when it was promoted to active on 2026-05-15, "to preserve CF HR
  history continuity" (`aggregator.py:522`). Intentional, but the name misleads every reader.
- `signal_stack_2plus_obs` does **not** block — counterfactual recording only.

### 3.3 `filter_summary.rejected` mixes two units
`rescue_health_gate` counts **signal tags removed from rescue eligibility**, not picks
rejected (`aggregator.py:1009`). It was the top "blocker" on both dates. Do not read the
rejection dict as a pick-level histogram.

### 3.4 ⚠️ Worker capacity: 27% of a 399-request slate was dead-lettered in under 2 minutes
`prediction-worker` runs `maxScale=10`, `containerConcurrency=1`, `cpu=1`. Pub/Sub push
delivered all 399 requests immediately; Cloud Run returned "no available instance"; the
subscription's `maxDeliveryAttempts=5` with default backoff exhausted within ~2 minutes and
107 requests landed in `prediction-request-dlq`. Confirmed by sampling the DLQ:
`CloudPubSubDeadLetterSourceDeliveryCount=5`, source `prediction-request-prod`.

**Nothing consumes that DLQ** — `prediction-request-dlq-sub` is a pull subscription with no
consumer, so those players simply get no prediction. A November slate is the same order of
magnitude. Recommend raising `maxScale`, lengthening the retry backoff, or both, and putting
something on the DLQ — but that is a capacity decision, not applied here.

### 3.5 Containment
Pre-mutation snapshots: `nba_predictions_backups.rehearsal2_ppp_20260410_pre` (768 rows),
`rehearsal2_dps_20260410_pre` (3 rows); 181 GCS objects for 2026-04-10 and 475 for 2026-04-12
copied locally with paths preserved, plus the nine aggregate export prefixes (1,118 files).
Cleanup and the post-cleanup verification are recorded in §5.

---

## 4. ⚠️ Security: the coordinator is open to the internet

```
curl -H "Authorization: Bearer not-a-real-token" $COORD/status   -> 200
curl                                             $COORD/status   -> 401
```

Two gates, both open. `roles/run.invoker` includes **`allUsers`**, so Cloud Run checks no
identity; and `require_api_key` short-circuits on the *prefix* —
`if auth_header.startswith('Bearer '): return f(...)` — never verifying the token. The comment
says "Trust GCP identity tokens (Cloud Run validates these)", which is only true when IAM is
actually enforcing.

Exposed: `POST /start`, `/reset`, `/cleanup-duplicates`, `/cleanup-staging`, `/check-stalled`,
`/regenerate-pubsub`, `/regenerate-with-supersede`, `/line-update`.

**Not changed — needs your decision**, because `phase4_to_phase5` calls `/start` over HTTP and
the new `prediction-ready-prod-sub` posts to `/complete`. Both authenticate with service
accounts that already hold `run.invoker`, so removing `allUsers` is *probably* safe, but each
caller's SA should be confirmed first. Ideally do both: remove `allUsers`, and verify the OIDC
token (audience + issuer) instead of trusting the prefix.

---

## 5. Cleanup and final state — verified

| check | value |
|---|---|
| `player_prop_predictions` created today, **any** date | **0** |
| `player_prop_predictions` 2026-04-10 | **768** — exactly the pre-run snapshot, `MAX(created_at)` back to 2026-04-10 20:02:12 |
| `player_prop_predictions` 2026-04-12 | 1164 — never written to |
| `signal_best_bets_picks` | **203 total, 0 created today** — evidence base untouched |
| `best_bets_filtered_picks` / `_filter_audit` / `model_bb_candidates`, both dates | 0 |
| `daily_prediction_signals` 2026-04-10 | 3 — restored from snapshot (the run had added a 4th) |
| `_staging_*` tables | 0 |
| GCS 2026-04-10 (181 objects) + 2026-04-12 (475) | restored; `gsutil rsync -n` reports **0** differences, and the three files that mattered are byte-identical to the pre-run copies |
| Nine aggregate export prefixes (1,118 files) | restored; residual rsync flags are mtime metadata only, content identical |
| `COORDINATOR_MAX_PAST_DAYS` | **removed** from the service — the 90-day default is back, re-confirmed live (`HTTP 400 invalid_game_date: >90d in past`) |
| Fleet | exactly 3 enabled models, `catboost_v12_noveg_train1205_0403` still `is_production` |

Snapshots kept (safe to drop): `nba_predictions_backups.rehearsal2_ppp_20260410_pre`,
`nba_predictions_backups.rehearsal2_dps_20260410_pre`.

⚠️ **Reusable containment lesson:** `gsutil cp -r` with a `**` glob **flattens** the result and
silently loses same-named objects in different directories — 181 objects became 171. Build an
explicit URL→local-path plan and copy per file.

### 5.1 One more inert gate, found in the orchestrator's own log
`phase5_to_phase6/main.py:202` bypasses `MIN_COMPLETION_PCT = 80` whenever
`status == 'success' and completed_predictions > 0`:

```
[60ce03d5] completion_pct=56.1% is below threshold but status=success with 224 predictions
— overriding to 100.0% (likely re-triggered batch with incomplete run_history tracking)
```

The coordinator reports `status='success'` for a stall-completed **partial** batch too, so the
80% gate can only ever block a batch with *zero* predictions. Combined with §3.4, a real slate
could publish picks off ~73% of players with nothing flagging the gap. Not changed — the right
behaviour is a judgement call (blocking Phase 6 on a partial slate can itself cause a drought).

---

## 6. Open decisions (unchanged from 09-06 unless noted)

1. **CI**: 171 failed / 2,704 passed, ~81 `DefaultCredentialsError`. Make hermetic, quarantine,
   or leave red?
2. **`v1/admin/*` cutover**: private bucket exists, exporter honours `ADMIN_BUCKET_NAME`,
   frontend `/admin` must be repointed first. When?
3. **Retrain before the opener?** The fleet trains through Apr 2–3, carrying the late-season
   contamination the CF cap exists to prevent.
4. **NEW — coordinator auth** (§4).
5. **NEW — worker capacity / DLQ** (§3.4).
6. **NEW — how to prove the `signal_best_bets_picks` INSERT** (§3.1).
7. ~~keep `COORDINATOR_MAX_PAST_DAYS=400`?~~ — **removed**, default 90 restored (§5).
8. **NEW — the Phase 5→6 completeness gate is inert** (§5.1). Fix, or accept partial publishing?

## Do NOT
Unchanged: no `model_performance_daily` backfill; do not delete signal rescue; do not lower the
OVER floor to 3.0; do not ship the BDB "two-line fix"; no 4th model before the n7≥30 floor; do
not use `gcloud builds list` as a deploy oracle; do not trust `/process-date` or `/start` status
text. Plus, new: **do not widen `model_bb_candidates` to include filter-rejected candidates**
(§1.2), and **do not read `filter_summary.rejected` as a pick-level histogram** (§3.3).
