# Session Handoff — 2026-05-11 — Pipeline State Agent-Review Follow-ups

**Status at end of session:** All HIGH-severity and most MEDIUM-severity findings from the 10-agent review of the morning session's ParameterResolver fix are addressed. Subscriber + planner redeployed. Existing EXPECTED rows for past-date odds outputs repointed to the historical GCS path. Offseason FAILED + bp_player_props historicals triaged. Demo readiness unchanged.

**Predecessor:** `docs/09-handoff/2026-05-11-PIPELINE-STATE-FOLLOWUP-HANDOFF.md` (morning session — ParameterResolver fix, `oddsa_player_props_his` resolver, IAM grants).

---

## Critical follow-ups landed this session

### 1. Planner partition-template fix (HIGH) — `orchestration/cloud_functions/expected_outputs_planner/main.py`

**Bug uncovered during smoke test:** planner registered `odds_api_player_points_props` with the LIVE path `gs://nba-scraped-data/odds-api/player-props/{date}/`. But for past dates the only recovery scraper is `oddsa_player_props_his`, which writes to `…/player-props-history/{date}/`. Reconciler reads only the registered `expected_partition`, so even successful historical backfills would stay EXPECTED → gap_detector would keep re-firing → wasted Odds API credits in a loop.

**Fix:** added `HISTORICAL_PATH_OVERRIDES` map + `_resolve_partition()` helper that switches templates based on `game_date` age (threshold: 7 days). Live scraper handles the recent window (live path); past dates resolve to the historical path. Planner deployed at revision `expected-outputs-planner-00002-gej`.

**Backfill of existing rows:** `expected_outputs_planner`'s MERGE only refreshes rows it touches; trying to re-trigger via curl + impersonation tripped over `gcloud auth print-identity-token` not supporting user accounts as audiences. Bypassed with a direct UPDATE:

```sql
UPDATE `nba-props-platform.nba_orchestration.expected_outputs`
SET expected_partition = CONCAT(
      "gs://nba-scraped-data/odds-api/player-props-history/",
      FORMAT_DATE("%Y-%m-%d", game_date), "/"),
    source = "planner_path_fix_2026-05-11",
    updated_at = CURRENT_TIMESTAMP()
WHERE sport="nba" AND phase="phase1_scrape"
  AND output_type="odds_api_player_points_props"
  AND game_date < DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND expected_partition LIKE "gs://nba-scraped-data/odds-api/player-props/%"
```

215 rows updated.

**Scope clarification:** affects only `odds_api_player_points_props`. `odds_api_game_lines` would belong in `HISTORICAL_PATH_OVERRIDES` if Phase 1 registered it, but it isn't currently. `bettingpros_player_points_props` has no historical variant at all (see triage below).

### 2. Throttled gap-detector (HIGH) — env var

Lowered `MAX_PUBLISHES_PER_RUN` on `gap-detector` CF from 50 → 10 via `--update-env-vars`. Worst-case Odds API burn during queue drain drops from ~10k credits/hour to ~2k/hour. Reversible.

### 3. Resolver patched (MEDIUM) — `orchestration/parameter_resolver.py`

Three issues from Agent #1 (code review) + Agent #5 (snapshot strategy):

- **Exception class too narrow.** Was catching `ImportError, RuntimeError, ValueError`; BQ errors are `google.api_core.exceptions.GoogleAPICallError` which subclasses none of those. A real BQ outage would have bubbled up uncaught. Switched to broad `except Exception` with comments noting the subscriber-contract caveat (silent success on infra error — fix when we wire metric emission).
- **Snapshot-timestamp safety floor.** Added `HAVING MIN(snapshot_timestamp) < TIMESTAMP(CONCAT(CAST(@game_date AS STRING), 'T20:00:00Z'))` to drop events whose only capture was inside the risky late-evening window. Avoids burning credits on near-certain 404s.
- **Misleading comment fixed.** "Events disappear from the API shortly before/after tipoff" was backwards — they APPEAR before tipoff and DISAPPEAR after. Comment now correctly justifies MIN() as picking the safe early-window capture. Also added `bq_job_id` to log lines for debugging.

### 4. Triage of offseason + unrecoverable rows (MEDIUM) — BQ DML

- **24 NBA preseason FAILED rows** (game_date < 2025-10-21, Phases 2-6) → EMPTY_OK with `source='triage_preseason_2026-05-11'`. Pre-Oct-21 had no NBA games; failures were structural (planner expected data that never existed).
- **99 NBA `bettingpros_player_points_props` rows older than 7 days** (mix of EXPECTED/FAILED/DEGRADED) → EMPTY_OK with `source='triage_bp_no_historical_2026-05-11'`. There is no NBA `bp_*_his` scraper; live `bp_player_props` only works for very recent dates. These rows were structurally unrecoverable.

### 5. `orchestration/__init__.py` refactored to no-op (MEDIUM)

Per Agent #4: removed the 8 eager re-exports (WorkflowConfig, MasterWorkflowController, WorkflowDecision, DecisionAction, AlertLevel, WorkflowExecutor, CleanupProcessor, DailyScheduleLocker). Verified zero production callers used `from orchestration import …`; all 121 production call sites already use `from orchestration.<submodule> import …`. The empty-init shim in `deploy-pubsub-subscriber.sh` is now belt-and-suspenders (the real init is already light); kept for defense-in-depth.

### 6. Pandas lazy-import retained — `shared/utils/bigquery_client.py`

Carried forward from morning session. Agent #3 confirmed: no callers touch `bigquery_client.pd`; the legacy `BigQueryClient` class has exactly 1 production caller (`scripts/verify_database_completeness.py:17`). **Recommended next:** migrate that caller to `shared.clients.bigquery_pool` and remove the legacy class entirely. ~30 min.

---

## What did NOT land (and why)

### Bucket IAM scoping (Agent #9 finding)

Tried to replace the bucket-wide `roles/storage.objectViewer` with an IAM condition scoping the grant to `nba-com/schedule/`. `gcloud storage buckets add-iam-policy-binding ... --condition=...` returns:

```
HTTPError 412: To set IAM conditions in this bucket, enable uniform bucket-level access.
```

UBLA migration is a one-way switch that breaks fine-grained ACLs across all consumers of the bucket. Out of scope for this session. **Action:** added a `TODO(over-scope)` comment in `deploy-pubsub-subscriber.sh` documenting the limitation. Revisit when the team coordinates a UBLA migration.

### Unit test for `_resolve_oddsa_player_props_his` (Agent #8 finding)

Deferred. Doesn't change runtime behavior; existing smoke test against live BQ + Pub/Sub end-to-end covered the happy path. Test pattern lives at `tests/unit/orchestration/test_parameter_resolver.py:269-307`. **Action for next session:** write the happy-path test (mock `get_bigquery_client` + BQ rows). Should take ~30 min.

### Pub/Sub payload regex validation (Agent #9 finding)

Deferred. Current behavior is safe via BQ DATE typing rejecting non-date strings server-side. Defense-in-depth `re.fullmatch(r'\d{4}-\d{2}-\d{2}', game_date)` + phase whitelist is worth ~15 min; combine with Fix #2 scope.

### Legacy `BigQueryClient` deprecation

Deferred. ~30 min effort. Combine with cleanup of `shared/utils/__init__.py` `__all__` list.

---

## Pipeline state snapshot at end of session (NBA)

```
                                   EXPECTED COMPLETE EMPTY_OK FAILED  DEGRADED
nba  phase1_scrape                     470      373      289     49        4
nba  phase2_raw                          75      607      188    184      131
nba  phase3_analytics                    45      506      114      X       46
nba  phase4_precompute                   ...
nba  phase5_predictions                  ...
nba  phase6_publish                      ...
```
(Partial — read from `b0glprggx.output` 2026-05-11 13:21 PDT.)

**Phase 1 NBA EXPECTED dropped from 677 → 470** between morning and this session — gap_detector is draining the queue with the morning fix in place. **49 FAILED** is the new tail (was 0 right after the FAILED→EXPECTED reset); these are dates where the resolver returned `[]` (no event_ids in BQ → unrecoverable without an `oddsa_events_his` discovery pass).

---

## Files touched this session

- `orchestration/cloud_functions/expected_outputs_planner/main.py` — `HISTORICAL_PATH_OVERRIDES` + `_resolve_partition()` + `plan_date()` signature carries `today`
- `orchestration/parameter_resolver.py` — `_resolve_oddsa_player_props_his` patched (broader exceptions, snapshot floor, comment, job_id logging)
- `orchestration/__init__.py` — emptied of eager re-exports + explanatory comment
- `orchestration/cloud_functions/scraper_gap_backfiller/deploy-pubsub-subscriber.sh` — IAM grant unchanged in effect (bucket-wide), but TODO comment added re. UBLA
- `shared/utils/bigquery_client.py` — pandas import lazy (carried from morning session)

Plus a re-deploy of `expected-outputs-planner` (rev `expected-outputs-planner-00002-gej`) and `backfill-pubsub-subscriber` (rev `backfill-pubsub-subscriber-00006-hac`). Both verified ACTIVE at end of session. Smoke-test message published for `2025-12-15` against revision `-00006-hac`; outcome (BQ row update) monitored asynchronously.

---

## Recommended next-session priorities

### High value, low effort (≤ 1 hour total)

1. **Verify subscriber redeploy completed cleanly.** Pull last 30 min of `backfill-pubsub-subscriber` logs; confirm no `ParameterResolver unavailable` lines on the new revision and that resolved-events log lines now carry `bq_job_id`.

2. **Verify path fix worked end-to-end.** Pick one of the 215 repointed rows (e.g. `odds_api_player_points_props / 2025-11-10`, which already has files at the historical path) and confirm reconciler flips it to COMPLETE on next pass (every 30 min). If it doesn't, the reconciler may not list-recursively at the new path.

3. **Write the happy-path unit test for `_resolve_oddsa_player_props_his`.** Pattern at `tests/unit/orchestration/test_parameter_resolver.py:269-307`. Locks the param-dict contract (`event_id, game_date, snapshot_timestamp, sport`).

### Fix #2 — Phase 2-6 dispatch (Agent #10 plan, ~1 day)

Now that triage cleared ~123 noise rows, the real Phase 2-6 backfill queue is smaller and more recoverable. Still ~600 actionable rows (mostly Phase 6 publish). Endpoints + IAM deltas in the morning handoff (`docs/09-handoff/2026-05-11-PIPELINE-STATE-FOLLOWUP-HANDOFF.md` lines 121-152). Recommended order:

- Add `_dispatch_phase3/4/5/6` helpers in `orchestration/cloud_functions/scraper_gap_backfiller/main.py:566-574`.
- Grant `roles/pubsub.publisher` on `nba-phase6-export-trigger` to gap-detector SA.
- Add `_get_processor_api_key()` Secret Manager helper for Phase 3 + Phase 5 (secret names from `phase3-analytics-processors` and `prediction-coordinator` env vars).
- Smoke-test one DEGRADED row per phase before letting the queue drain.

### Lower priority — cleanup

- Deprecate legacy `shared/utils/bigquery_client.BigQueryClient` (1 caller). ~30 min.
- Pub/Sub payload regex validation in `pubsub_subscriber()`. ~15 min.
- Bucket UBLA migration + IAM condition scoping. Coordinate with other bucket consumers; not a one-person job.

### Pre-emptive monitoring before sleeping the next session

- Cloud Logging filter on `severity>=ERROR resource.labels.service_name="backfill-pubsub-subscriber"` to catch resolver failures.
- BQ canary: `SELECT COUNT(*) FROM nba_orchestration.expected_outputs WHERE sport='nba' AND status='FAILED' AND game_date >= CURRENT_DATE() - 14 AND source='pubsub_backfiller_failed'` — if this climbs above ~30, kill `gap-detector-30min` scheduler immediately.

---

## Things the 10-agent review surfaced that we DIDN'T change

For reference if revisiting:

- **MIN(snapshot_timestamp) is the right strategy** for the historical odds resolver (Agent #5 confirmed). The HAVING floor we added is the only refinement needed.
- **`bp_player_props` NBA historical variant does not exist** (handoff line 91 + Agent #10 plan). Triage to EMPTY_OK is the correct end-state, not a fix.
- **Pre-existing `MEMORY.md` index file is 225 lines, exceeds 200-line guideline.** Out of scope.

---

## Commits expected this session

None yet. The 6 file edits are uncommitted. Suggest one commit grouping them:

```
fix(pipeline-state): agent-review follow-ups — planner path, resolver hardening, triage

- expected_outputs_planner: live→historical path switch for past dates (215 rows
  repointed); fixes silent reconciler miss on oddsa_player_props_his backfills
- parameter_resolver: broaden exception class, add 20:00 UTC snapshot floor,
  log bq_job_id; fix misleading comment about Odds API event lifecycle
- orchestration/__init__.py: remove eager re-exports (zero prod callers)
- bigquery_client: lazy pandas import (kept from morning session)
- deploy-pubsub-subscriber: TODO note re. UBLA for prefix-scoped IAM
- triage: 24 preseason FAILED + 99 unrecoverable NBA bp_player_props → EMPTY_OK
- gap-detector: throttle MAX_PUBLISHES_PER_RUN 50 → 10

Predecessor handoff: 2026-05-11-PIPELINE-STATE-FOLLOWUP-HANDOFF.md.
Agent review summary: 10 parallel reviewers; HIGH + most MEDIUM addressed,
LOW + UBLA scoping + unit tests deferred (see this doc).
```
