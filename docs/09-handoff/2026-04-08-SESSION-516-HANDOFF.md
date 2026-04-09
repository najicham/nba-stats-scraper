# Session 516 Handoff — Auto-Halt Fix, Traffic Routing Discovery, Error Audit

**Date:** 2026-04-07 to 2026-04-08
**Focus:** Fixed auto-halt deployment bug, discovered systemic Cloud Run traffic routing issue (all 21 services stale), comprehensive error log audit + 8 fixes
**Commits:** `d3b3d070` through `37c6f2b9` (8 commits)

---

## What Was Done This Session

### 1. Auto-Halt Bug Fix (TWO bugs)

**Bug 1: Missing import** (`d3b3d070`)
- `regime_context.py` line 193: `QueryJobConfig` and `ScalarQueryParameter` not imported in the halt query try block. Every other try block in the function had a local import — this one was missed in Session 515.
- Effect: Halt query threw `NameError` every run, caught silently. `bb_auto_halt_active` stayed `False`.

**Bug 2: Cloud Run traffic routing** (`420d0f98`)
- ALL 21 Cloud Run services were routing to stale revisions. Cloud Build deploys create new revisions but don't auto-route traffic.
- Phase6-export was routing to revision `00311-wab` (pre-Session-515) instead of `00320-kev` (with halt fix).
- Fixed: `gcloud run services update-traffic SERVICE --to-latest` for all 21 services.
- Prevention: Added `--to-latest` step to `cloudbuild.yaml`, `cloudbuild-mlb-worker.yaml`, and `cloudbuild-functions.yaml`.
- Detection: Added traffic routing check to `check-deployment-drift.sh`.

**Result:** Auto-halt now working in production — JSON returns `halt_active: true`, avg edge 1.42.

### 2. Edge Compression Governance Gate (`9bfa3293`)

Soft warning in `quick_retrain.py` when retrained model produces avg edge < 3.0. Includes edge distribution stats (median, p75, p90, edge-5+ rate) in model card JSON. Doesn't block — just warns since edge depends partly on market conditions.

### 3. Error Log Audit — 8 Issues Found and Fixed

#### 3a. `timedelta` Scoping Bug (`107391a4`)
- **File:** `predictions/coordinator/coordinator.py:931`
- **Impact:** Every hourly coordinator run failed analytics quality check
- **Root cause:** Local `from datetime import timedelta` at line 931 (inside TOMORROW branch) shadowed module-level import. Python 3.12+ treats this as a local binding — unbound when TOMORROW branch isn't taken.
- **Fix:** Removed redundant local import.

#### 3b. Phase 3 Pub/Sub Amplification Loop (`83313760`)
- **File:** `data_processors/analytics/main_analytics_service.py:891-985`
- **Impact:** 500+ HTTP 500 errors/day for 7 days
- **Root cause:** MEM had TWO home games on April 1. DAL@MEM gamebook data never existed. Completeness check found 9/10 games → returned 500 → triggered re-scrape → re-scrape published new Phase 2 message → Phase 3 returned 500 again → infinite loop. Each message also got 5 DLQ retries, but NEW messages kept spawning.
- **Fix:** Two bypass conditions: (1) Coverage >= 80% → proceed with available data, (2) Date 2+ days old → stop retrying. Configurable via `COMPLETENESS_COVERAGE_THRESHOLD` and `COMPLETENESS_STALENESS_DAYS` env vars. Pub/Sub backlog purged via `gcloud pubsub subscriptions seek`.

#### 3c. Scraper BQ BadRequest — TODAY Sentinel (`37c6f2b9`)
- **Files:** `scrapers/scraper_base.py:339-355`, `shared/utils/pipeline_logger.py:61-68`
- **Impact:** BQ write error every 1-2 hours
- **Root cause:** `pipeline_event_log.game_date` column is DATE type. Scrapers with `date="TODAY"` logged the literal string "TODAY" before `ConfigMixin.set_additional_opts()` resolved it.
- **Fix:** Resolve TODAY/YESTERDAY in scraper_base before BQ write + defense-in-depth validation in pipeline_logger.

#### 3d. Cleanup Processor 100% False Positive Storm (`37c6f2b9`)
- **File:** `orchestration/cleanup_processor.py`
- **Impact:** 293,120 unnecessary Pub/Sub republishes since Jan 9, 2026 (every 15 min, 24/7)
- **Root cause:** Two bugs: (1) `scraper_execution_log.gcs_path` stores `gs://bucket/path` but Phase 2 `source_file_path` stores just `path` — never match. (2) Most Phase 2 tables write `source_file_path = "unknown"`.
- **Fix:** Path normalization + `TRACKABLE_SCRAPERS` filter (only `nbac_schedule_api` has real paths). Skips untrackable scrapers instead of false-positive republishing.

#### 3e. Duplicate Ultra Enrichment Code (`fb554035`)
- **File:** `data_processors/publishing/signal_best_bets_exporter.py:334-350`
- Steps 3b/3c were exact duplicates of 6c/6d. Removed, saving 2 BQ queries per export.

#### 3f. Unmonitored Critical Data Sources (`fb554035`)
- **File:** `bin/monitoring/data_source_health_canary.py`
- Added: `bettingpros_props` (CRITICAL), `odds_api_props` (CRITICAL), `espn_projections` (WARNING).

#### 3g. BQ Error Logging Opaque (`37c6f2b9`)
- **File:** `shared/utils/bigquery_utils.py:239-249`
- Now logs `load_job.errors` detail before re-raising. Previously said "look into errors[]" but never logged them.

### 4. Monday Retrain Verified

`weekly-retrain` CF fired 5 AM ET April 7. Model BLOCKED by governance: UNDER HR 50.91% < 52.4%. No new models produced. System remains in auto-halt.

---

## Current System State

### NBA
- **Season: 415-235 (63.8%)** — Jan 73.8%, Feb 63.3%, Mar 46.7%, Apr 2-2
- **Auto-halt ACTIVE** (working in production): avg edge 1.42, 1.3% edge-5+
- **4 enabled models**, all producing avg edge 1.3-1.5
- **All 21 services routing to latest revisions** (traffic routing fixed)
- **All Cloud Build configs now include `--to-latest` step**

### MLB
- **300 predictions/day, ALL BLOCKED** (missing line features)
- **Odds API pipeline working** end-to-end
- **BettingPros MLB events dead** (API doesn't support MLB)

### New Markets
- **Assists:** 34-68K records/day, 63-109 players
- **Rebounds:** 48-102K records/day, 81-131 players

### Data Quality
- All Phase 3/4/5 tables current
- All CRITICAL data sources current
- **VSiN dead since Mar 28** (shadow source, WARNING severity)

---

## What Needs Verification After Deploy

1. **Traffic routing persists** — builds triggered by this push should include the `--to-latest` step. Verify with:
   ```bash
   ./bin/check-deployment-drift.sh --verbose  # Should show "All services routing to latest"
   ```

2. **Phase 3 500s stopped** — the Pub/Sub backlog was purged and the code fix prevents new storms:
   ```bash
   gcloud logging read \
     'resource.labels.service_name="nba-phase3-analytics-processors" AND severity>=ERROR AND timestamp>="2026-04-09T00:00:00Z"' \
     --project=nba-props-platform --limit=10 --format='table(timestamp,severity)'
   ```

3. **Scraper BQ errors stopped** — TODAY sentinel fix should prevent BadRequest errors:
   ```bash
   gcloud logging read \
     'resource.labels.service_name="nba-scrapers" AND textPayload:"BadRequest" AND timestamp>="2026-04-09T00:00:00Z"' \
     --project=nba-props-platform --limit=5
   ```

4. **Cleanup processor republishes dropped** — should go from 21-35 per run to 0-1:
   ```bash
   gcloud logging read \
     'textPayload:"republished" AND resource.labels.service_name="nba-scrapers" AND timestamp>="2026-04-09T00:00:00Z"' \
     --project=nba-props-platform --limit=5
   ```

5. **Coordinator timedelta error gone** — analytics quality check should succeed:
   ```bash
   gcloud logging read \
     'textPayload:"timedelta" AND resource.labels.service_name="prediction-coordinator" AND timestamp>="2026-04-09T00:00:00Z"' \
     --project=nba-props-platform --limit=5
   ```

---

## Key Files Changed

| Purpose | File |
|---------|------|
| Auto-halt import fix | `ml/signals/regime_context.py` |
| Auto-halt debug logging | `data_processors/publishing/signal_best_bets_exporter.py` |
| Traffic routing (Cloud Build) | `cloudbuild.yaml`, `cloudbuild-mlb-worker.yaml`, `cloudbuild-functions.yaml` |
| Traffic routing (drift check) | `bin/check-deployment-drift.sh` |
| Edge governance gate | `ml/experiments/quick_retrain.py` |
| timedelta scoping fix | `predictions/coordinator/coordinator.py` |
| Phase 3 amplification fix | `data_processors/analytics/main_analytics_service.py` |
| TODAY sentinel fix | `scrapers/scraper_base.py`, `shared/utils/pipeline_logger.py` |
| Cleanup false positive fix | `orchestration/cleanup_processor.py` |
| BQ error detail logging | `shared/utils/bigquery_utils.py` |
| Duplicate code removal | `data_processors/publishing/signal_best_bets_exporter.py` |
| Data source canary expansion | `bin/monitoring/data_source_health_canary.py` |

---

## Next Session Priorities

| Priority | Task | Effort | Notes |
|----------|------|--------|-------|
| **P0** | Verify all 8 fixes deployed and working | 15 min | Run the 5 verification commands above |
| **P1** | Investigate cleanup processor — consider disabling entirely | 30 min | Has never worked correctly (100% false positive since Jan 9). May be dead code. |
| **P1** | Phase 3 Pub/Sub subscription: update push endpoint URL | 5 min | Agent updated to `f7p3g7f6ya` format but verify it persisted |
| **P2** | Fix Phase 2 processors to track real `source_file_path` | 2 hours | Most write "unknown" — would let cleanup processor actually work |
| **P2** | Recalibrate `sharp_consensus_under` by book source | 2 hours | Needs separate thresholds for Odds API vs BettingPros |
| **P2** | Fix BettingPros MLB props to bypass events endpoint | 1 hour | Use `/v3/props` with `event_id=ALL` |

---

## Strategic Notes

1. **The traffic routing issue was the biggest find.** ALL Session 515 changes (auto-halt, MLB fixes, signal reverts) were never live until Session 516 fixed it. The Cloud Build `--to-latest` step prevents this going forward, and `check-deployment-drift.sh` now detects it.

2. **The cleanup processor has been generating 293K unnecessary Pub/Sub messages since Jan 9.** Consider disabling it entirely — Phase 2 Pub/Sub delivery is reliable, and the processor has never successfully detected a real gap.

3. **The Phase 3 amplification loop pattern is systemic** — any permanently missing data (game postponement, API outage, etc.) will create the same infinite retry storm. The coverage threshold + staleness bypass should prevent future occurrences, but worth monitoring.

4. **The coordinator `timedelta` bug means analytics quality checks have NEVER worked** in the Python 3.12+ environment. Now that it's fixed, verify the quality gate is actually providing value (it might flag issues that were silently skipped before).
