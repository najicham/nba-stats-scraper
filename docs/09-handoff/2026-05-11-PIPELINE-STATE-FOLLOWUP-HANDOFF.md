# Session Handoff — 2026-05-11 — Pipeline State Redesign Follow-ups

**Status at end of session:** 2 of 3 priority follow-ups shipped + scoped. Fix #3 (uptime alerting) is live. Fix #1 (scraper-name mapping) is live but unmasked a deeper bug (ParameterResolver unavailable in CF runtime — see "Unmasked issue" below). Fix #2 (Phase 2-6 backfill dispatch) is fully scoped, not started.

**Demo readiness:** unchanged. ~3 weeks runway. Pipeline state architecture is in place. Public uptime alerts now page Slack on failure.

---

## What shipped this session

### Fix #3 — Public uptime check alert policy (commit `bab619f3`)

The 3 GCP uptime checks for `playerprops.io/`, `/mlb`, `/nba/best-bets` had no alert policy attached — failures were silent. Phase G already shipped the 3 *pipeline-state* alert policies with Slack channel `NBA Platform Alerts` (`#alerts`, `13444328261517403081`); this closes the public-uptime gap.

- New: `monitoring/alert-policies/uptime-check-failed.yaml`. Filters on the 3 specific `check_id`s (`playerprops-root-PouB7pmhlPg`, `playerprops-mlb-t9XeXir8-8E`, `playerprops-nba-best-bets-QQqlrZdT6wk`), `REDUCE_COUNT_FALSE > 1` over 5 min (>= 2 of 3 regional probes failed).
- Edited: `monitoring/alert-policies/deploy-alert-policies.sh:48` brace expansion now includes `uptime-check-failed`.
- Live policy: `projects/nba-props-platform/alertPolicies/2340587281059739929` (`[NBA Pipeline] Public uptime check failed (Critical)`).
- Notification channel attached at create-time (the deploy script's old comment claiming gcloud strips channels at create is stale — the existing 3 Phase-G policies all show channels attached).

### Fix #1 — Scraper-name mapping correction (commit `8ef42145`)

`PHASE1_OUTPUT_TO_SCRAPER` in `orchestration/cloud_functions/scraper_gap_backfiller/main.py` had output_type names copy-pasted as scraper_names. None of the 4 hot paths existed in `scrapers/registry.py`. Every subscriber call returned HTTP 400 with the available_scrapers list.

Mismatches corrected:
- `odds_api_player_points_props` → `oddsa_player_props_his`
- `bettingpros_player_points_props` → `bp_player_props` (no NBA `_his` variant in registry — historical NBA BP unrecoverable)
- `nbac_gamebook_player_stats` → `nbac_gamebook_pdf`
- `mlb_box_scores` → `mlb_box_scores_mlbapi`

Other 4 entries (`nbac_injury_report`, `nbac_play_by_play`, `mlb_schedule`, `bp_mlb_player_props`) already matched registry.

Subscriber redeployed manually (`./orchestration/cloud_functions/scraper_gap_backfiller/deploy-pubsub-subscriber.sh`) — Gen2 revision @ 2026-05-11 14:39:47 UTC. Verified by pulling deployed source from `gs://gcf-v2-sources-756957797294-us-west2/backfill-pubsub-subscriber/function-source.zip` and grepping the dict.

Reset 450 FAILED Phase 1 NBA rows to EXPECTED + attempts=0:
```sql
UPDATE `nba-props-platform.nba_orchestration.expected_outputs`
SET status='EXPECTED', attempts=0, last_error=NULL,
    source='fix1_reset_after_scraper_name_correction',
    updated_at=CURRENT_TIMESTAMP()
WHERE status='FAILED' AND phase='phase1_scrape' AND sport='nba'
```
(Count was 150 at coverage snapshot; grew to 450 by reset time as reconciler escalated more rows. Post-reset: 0 FAILED, 677 EXPECTED for phase1 NBA.)

**Live verification at 14:46 UTC:** subscriber received messages from gap_detector (:45 cycle), routed via corrected mapping, **HTTP 400s gone**. But every call now returns HTTP 500 — see Unmasked issue.

---

## Unmasked issue — ParameterResolver unavailable in CF runtime

Fix #1 confirmed the *mapping* works. The next layer down doesn't.

### Symptoms

In `backfill-pubsub-subscriber` Gen2 logs (`gcloud functions logs read backfill-pubsub-subscriber --gen2 --region=us-west2 --project=nba-props-platform --limit=80`):

```
2026-05-11 14:46:44  ParameterResolver unavailable (No module named 'orchestration'), using simple fallback
2026-05-11 14:46:33  ❌ Backfill failed: oddsa_player_props_his / 2025-10-24
2026-05-11 14:46:33  Scraper oddsa_player_props_his returned HTTP 500: {"message":"oddsa_player_props_his failed","run_id":"c897a84d","status":"error"}
```

Pattern: every NBA Phase 1 scraper (`nbac_gamebook_pdf`, `nbac_play_by_play`, `nbac_injury_report`, `oddsa_player_props_his`, `bp_player_props`) returns HTTP 500 because the simple fallback `{date, gamedate}` doesn't satisfy per-game / per-event scrapers.

### Root cause

`scraper_gap_backfiller/main.py:54` lazy-imports `from orchestration.parameter_resolver import ParameterResolver` after manipulating `sys.path` to a 3-levels-up `_repo_root`. In the CF Gen2 runtime, source is staged flat at `/workspace/`, so `_repo_root` resolves to `/` and the import fails. `get_parameter_resolver()` catches and logs the warning, then `resolve_scraper_parameters()` returns the simple-fallback dict at line 273.

Deploy script (`deploy-pubsub-subscriber.sh`) currently ships:
- `main.py`
- `requirements.txt`
- `shared/` (via `rsync -aL`)

It does NOT ship `orchestration/` or `config/`.

### Fix path (size: 0.5 day, NOT 30 min)

1. **Deploy script changes:**
   - Copy `orchestration/parameter_resolver.py` to `${STAGE_DIR}/orchestration/parameter_resolver.py`.
   - Write an **empty** `orchestration/__init__.py` to `${STAGE_DIR}/` (the real `orchestration/__init__.py` eagerly imports `MasterWorkflowController`, `WorkflowExecutor`, etc. — heavy modules whose transitive deps aren't in `requirements.txt`).
   - Copy `config/scraper_parameters.yaml` to `${STAGE_DIR}/config/`. (Also `config/workflows.yaml` since `_validate_workflow_date_config` opens it — non-blocking but spams logs.)

2. **Verify NBAScheduleService works in CF runtime:**
   - `shared.utils.schedule.NBAScheduleService` constructs at `ParameterResolver.__init__`. It needs BQ + GCS read access. The gap-detector SA has BQ already (used by reconciler/planner); needs GCS read to `nba-props-platform-api` or wherever schedules live.

3. **Add `oddsa_player_props_his` to `complex_resolvers`:**
   - Existing resolvers cover `oddsa_player_props` (live), `oddsa_events`, `oddsa_game_lines`. Historical variant needs per-event_id iteration over a date range using `oddsa_events_his`. New helper or alias.

4. **`bp_player_props` for historical dates:**
   - No NBA historical variant exists. Live scraper will only succeed for very recent dates. The 678 EXPECTED rows for Oct 2025 – Apr 2026 will mostly fail. Options:
     - Accept the loss — let attempts exhaust and FAILED status documents it.
     - Bulk-mark older NBA `bettingpros_player_points_props` rows as `EMPTY_OK` since the data is fundamentally unrecoverable.

5. **Smoke test** against one date before letting gap_detector loose on the 678-row queue.

### Secondary log noise (not blocking)

Also seen: `The request was aborted because there was no available instance` from `nba-scrapers` Cloud Run. Cause: gap_detector publishes 50 messages/cycle; subscriber processes in parallel; `nba-scrapers` Cloud Run service hits concurrency limit. Not Fix-#1's problem. If it persists once params are correct, raise `nba-scrapers` `--max-instances` or lower `gap_detector.MAX_PUBLISHES_PER_RUN` from 50.

---

## Fix #2 — Phase 2-6 backfill extension (NOT STARTED, fully scoped)

See `docs/09-handoff/2026-05-09-PIPELINE-STATE-REDESIGN-HANDOFF.md` for the original ask. Scope confirmed by parallel verification agent this session.

### Work inventory (BQ snapshot ~14:42 UTC)

| sport | phase              | FAILED | DEGRADED |
|-------|--------------------|--------|----------|
| nba   | phase2_raw         | 187    | 136      |
| nba   | phase3_analytics   | 6      | 46       |
| nba   | phase4_precompute  | 15     | 7        |
| nba   | phase5_predictions | 16     | 15       |
| nba   | phase6_publish     | 396    | 87       |
| mlb   | phase6_publish     | 4      | 135      |
| **TOTAL** |               | **624** | **426** |

**1,050 stuck rows** in Phases 2-6 that the subscriber today silently skips. ~600 of the NBA Phase 6 FAILED rows are Oct-Nov 2025 (offseason); those likely belong as `EMPTY_OK` rather than retries — triage before turning the dispatch on.

### Architecture

Extend the subscriber dispatch at `orchestration/cloud_functions/scraper_gap_backfiller/main.py:566-574`:

```python
if phase == 'phase1_scrape': existing path
elif phase == 'phase2_raw': _dispatch_phase2(...)
elif phase == 'phase3_analytics': _dispatch_phase3(...)
elif phase == 'phase4_precompute': _dispatch_phase4(...)
elif phase == 'phase5_predictions': _dispatch_phase5(...)
elif phase == 'phase6_publish': _dispatch_phase6_pubsub(...)
```

Endpoints (verified live):

| phase | service | URL | payload |
|-------|---------|-----|---------|
| phase2_raw | `nba-phase2-raw-processors` | `https://nba-phase2-raw-processors-f7p3g7f6ya-wl.a.run.app` | POST `/process` — Pub/Sub-shaped envelope, **no clean date-range API**. Recommend SKIPPING Phase 2 in dispatch; Phase 1 re-scrape cascades naturally. |
| phase3_analytics | `nba-phase3-analytics-processors` | same host stub | POST `/process-date-range` + `X-API-Key` header. Body: `{start_date, end_date, processors?, backfill_mode: true}` |
| phase4_precompute | `nba-phase4-precompute-processors` | same | POST `/process-date`. Body: `{analysis_date, processors?, backfill_mode?: true}` |
| phase5_predictions | `prediction-coordinator` | same | POST `/start` + API key. Body: `{game_date, prediction_run_mode?: "BACKFILL", correlation_id?}` |
| phase6_publish | `phase6-export` (CF) | Pub/Sub topic `nba-phase6-export-trigger` | Publish `{export_types, target_date, sport?}` |

### IAM delta

| phase | grant needed |
|-------|--------------|
| phase2-5 | none — all 4 Cloud Run services have `allUsers` invoker (precedented, not changing) |
| phase6_publish | **NEW:** grant `roles/pubsub.publisher` on topic `nba-phase6-export-trigger` to `gap-detector@nba-props-platform.iam.gserviceaccount.com` |

### Secret Manager integration

Phase 3 + Phase 5 require API keys. Subscriber currently doesn't fetch secrets. Add a `_get_processor_api_key()` helper backed by Secret Manager (`secretmanager` is already imported and `get_secret()` is defined). Identify the right secret names from `phase3-analytics-processors` and `prediction-coordinator` env vars.

### Recommended order

1. Triage NBA Oct-Nov 2025 Phase 2-6 FAILED rows — likely bulk-mark `EMPTY_OK`. Query first:
   ```sql
   SELECT phase, MIN(game_date), MAX(game_date), COUNT(*)
   FROM nba_orchestration.expected_outputs
   WHERE sport='nba' AND status='FAILED' AND phase != 'phase1_scrape'
     AND game_date < '2025-11-15'
   GROUP BY phase
   ```
2. Add 4 dispatch helpers (skip Phase 2; Phase 1 cascade handles it).
3. Pub/Sub topic IAM grant.
4. Deploy + smoke test one DEGRADED row per phase.
5. Watch reconciler close the loop.

Effort: **1 day total** if ParameterResolver is fixed beforehand (Phase 1 needs to work first for the Phase 2 cascade story); otherwise allocate 1.5 days.

---

## What's safe to assume between sessions

- All 5 pipeline CFs are ACTIVE. 4 schedulers ENABLED. 4 alert policies live with Slack (`Expected outputs overdue`, `halt_state_writer stale`, `Phase error rate`, `Public uptime check failed`).
- `nba_orchestration.halt_state` today: NBA `between_rounds`, MLB healthy.
- `nba_orchestration.expected_outputs` coverage:
  | sport | phase | EXPECTED | COMPLETE | EMPTY_OK | FAILED | DEGRADED |
  |-------|-------|----------|----------|----------|--------|----------|
  | nba   | phase1_scrape | 677 | 318 | 190 | 0 | — |
  | nba   | phase2_raw    | 70  | 607 | 180 | 187 | 136 |
  | nba   | phase3_analytics | 42 | 506 | 108 | 6 | 46 |
  | nba   | phase4_precompute | 14 | 163 | 37 | 15 | 7 |
  | nba   | phase5_predictions | 14 | 154 | 37 | 16 | 15 |
  | nba   | phase6_publish | 85 | 665 | 183 | 396 | 87 |
  | mlb   | phase1_scrape | 177 | — | 531 | — | — |
  | mlb   | phase6_publish | 42 | — | 527 | 4 | 135 |
- Gap detector runs at :15/:45; reconciler at :00/:30. Each gap_detector pass publishes ≤50 messages.
- Current burn rate: subscriber will exhaust the 677 EXPECTED Phase 1 NBA rows within ~14 hours at 50/cycle * 2/hour, but every call currently fails HTTP 500 (ParameterResolver). Backfill is effectively halted until that's fixed.

## Recommended next-session priorities

1. **ParameterResolver fix** (0.5 day) — unblocks all 677 Phase 1 NBA rows. Without it the FAILED → EXPECTED reset I did this session burns 3 attempts/row over 1.5 hours and ends right back at FAILED.
2. **Triage Oct-Nov 2025 FAILED rows** (≤1 hour) — bulk `EMPTY_OK` the offseason noise before Fix #2 dispatch ever fires.
3. **Fix #2 dispatch** (1 day) — Phase 3/4/5/6 helpers + Pub/Sub IAM.
4. Optional: bulk-mark NBA `bettingpros_player_points_props` historical rows as `EMPTY_OK` (no recoverable scraper).

## Files touched this session

- `monitoring/alert-policies/uptime-check-failed.yaml` (new) — Fix #3
- `monitoring/alert-policies/deploy-alert-policies.sh` (line 48) — Fix #3
- `orchestration/cloud_functions/scraper_gap_backfiller/main.py` (lines 447-470) — Fix #1
- This handoff doc

## Commits

- `bab619f3` fix(monitoring): attach alert policy to 3 public uptime checks
- `8ef42145` fix(subscriber): correct 4 scraper-name mismatches in PHASE1_OUTPUT_TO_SCRAPER
