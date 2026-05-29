# Handoff — System audit + BDB pipeline restoration + 15 new follow-up tasks

**Date:** 2026-05-29 · **Type:** session close-out / next-session brief
**Prior handoff:** `2026-05-24-1-nba-star-out-discovery.md` (star-OUT discovery; deferred to September per Agent 4 path)
**Commits this multi-day stretch:** `24eefefd`, `dd7b293a`, `8e207042`
**TaskCreate IDs in play:** #25 (deferred), #26–#40 (new), #22-#24 (completed)

---

## 0. Orientation — read this first

This handoff covers three threads that compounded across 2026-05-25 → 2026-05-29:

1. **BDB pipeline restoration.** Fixed a half-broken retry CF that had been silently marking rows `completed_bdb` while never actually re-running Phase 3. Added strict-mode verification. Discovered the scheduler was firing every 6h but doing nothing because of a `max_age_days=14` default vs 30+ day old data. **System is now genuinely draining at ~70 rows/day, with proper failure semantics.**

2. **The `three_pt_makes` regression** turned out to be the visible tip of a much bigger PBP-source iceberg. `nbac_play_by_play` FAILED 16 consecutive days in January 2026 + DEGRADED 86 rows since 2026-01-29. The box-score fallback (commit `24eefefd`) restored `three_pt_makes` specifically, but shot-zone columns (paint, mid_range, assisted_fg, and1, blocks-by-zone) are still 78-86% NULL in Mar-Apr 2026 among players who actually played. Needs a PBP backfill, not just continued BDB retry. (See Task #30.)

3. **Eight-agent system audit on 2026-05-29** surfaced 73 distinct findings across the codebase + GCP infra: **16 BLOCKERS, 33 MAJORS, 24 MINORS.** Key theme: the system has been operating with monitoring half-blind for 6+ weeks. Many schedulers were paused 2026-04-27 (intentional off-season) but never resumed. Others have been silently failing on stale GCP API paths since April. Production data quality issues went unflagged because off-season halt meant nobody was watching picks. The 15 highest-impact findings became Tasks #26-#40.

**The system is not on fire** — NBA is in off-season halt, MLB betting concluded as no-edge. But there's enough dead monitoring and silent data corruption that pre-season prep work needs to start now, not in September.

**Memory file updates landed this session:**
- `offseason-roadmap-2026-05.md` — corrected stale "60279b20 not deployed" claim
- (No other memory files modified)

---

## 1. What landed across the multi-day stretch

### Commits

| Commit | Subject | Date |
|---|---|---|
| `24eefefd` | `fix(nba): three_pt_makes Phase 3 fallback + activate check-date-comparisons hook` | 2026-05-26 |
| `dd7b293a` | `fix(nba): bdb_retry_processor HTTP-invokes Phase 3 instead of dead Pub/Sub topic` | 2026-05-26 |
| `8e207042` | `fix(nba): bdb_retry_processor verifies pgs enrichment + delete dead bdb_arrival_trigger` | 2026-05-26 |

### Deploys

| Service / CF | Revision | Trigger |
|---|---|---|
| `nba-phase3-analytics-processors` | latest from `24eefefd` build `66e75513` | Auto (Cloud Build) |
| `bdb-retry-processor` | `bdb-retry-processor-00005-nex` | Manual (`gcloud functions deploy`) |

### Data-plane changes

- **5,635 rows** in `nba_analytics.player_game_summary` backfilled (`three_pt_makes` + `three_pt_attempts`) for game_date 2026-02-25 → 2026-04-26. Population went from 0-6% → 57-64% (rest correctly DNP).
- **1,749 rows** in `nba_orchestration.pending_bdb_games` reset from `completed_bdb` → `pending_bdb` (falsely-completed rows where BDB IS available but no re-run actually happened).
- **367 rows** in `nba_orchestration.pending_bdb_games` cleaned up from zombie state (`pending_bdb` with `bdb_check_count >= 72`) → `failed_max_retries` with `resolution_type='zombie_over_max_retries'`.

### Infrastructure changes outside the repo

- **`bdb-retry-hourly` Cloud Scheduler message body** updated from `{"action":"retry"}` to `{"action":"retry","max_age_days":200}`. This was the root cause of the drain stalling — CF defaulted to `max_age_days=14` which excluded all 30+ day old rows. **Not committed anywhere** — scheduler config lives in GCP only, no IaC. If you redeploy via gcloud and don't pass `--message-body`, this reverts.
- **`bdb-retry-processor` CF** env var `LOG_LEVEL=INFO` added (was `WARNING`, suppressing all the useful INFO logs).
- **`bdb-retry-processor` CF** env var `PHASE3_SERVICE_URL=https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app` added (also has sensible default in code).

### Memory file update

- `~/.claude/projects/-home-naji-code-nba-stats-scraper/memory/offseason-roadmap-2026-05.md` — fixed the stale "commit 60279b20 committed locally, NOT pushed/deployed" claim. It IS on main + auto-deployed 2026-05-20 ~15:15 UTC.

---

## 2. Current operational state

### BDB drain queue (as of 2026-05-29 ~16:00 UTC)

| Status | Count |
|---|---|
| `pending_bdb` | 1,636 |
| `failed_max_retries` | 377 |
| `completed_bdb` | 162 |
| `failed_no_bdb_data` | 24 |

**Drain rate:** ~70 rows/day across 4 scheduled CF cycles at 6h cadence (every 0, 6, 12, 18 ET). At this rate the queue clears in ~23 days, but many will convert to `failed_max_retries` instead of `completed_bdb` due to Phase 3 partial-failures (see Task #25 / #30).

**`max_age_days` issue:** the CF query filter is `game_date >= today - max_age_days`. If you redeploy the scheduler without preserving the `max_age_days: 200` message body, it defaults to 14 and the drain re-stalls. **This is fragile.** A more robust fix is to change the CF default (in code) from 14 to 200, but that wasn't done this session.

**Strict-mode verification confirmed working** on two test cases:
- `2026-04-15` (Phase 3 partial-fail — play-in date with blank tricodes triggering 80% team-stats threshold): HTTP 200 + verify→False → rows stayed `pending_bdb`. No false positive.
- `2026-03-24` (clean schedule): HTTP 200 + verify→True → 4 rows marked `completed_bdb`.

### Halt state — both correctly halted

| Sport | `halt_active` | `halt_reason` |
|---|---|---|
| NBA | true | `predictions_inactive` (off-season) |
| MLB | true | `pick_drought` (concluded as no-edge per 2026-05-22 session) |

### What WAS NOT touched this session

- The 1,276+ dirty files in the working tree (prior session work — not mine to commit).
- `predictions/`, ML model artifacts, feature store schema.
- The star-OUT signal discovery (deferred to September per Agent 4 reasoning in `2026-05-24-1-nba-star-out-discovery.md`).
- The MLB pitcher-strikeout project (concluded as efficient market, info-only).

---

## 3. The eight-agent system audit (2026-05-29)

### How it was structured

Eight parallel agents, each with a distinct lens, told NOT to re-investigate already-fixed areas (BDB retry, three_pt_makes, check-date-comparisons hook, bdb_arrival_trigger):

| Agent | Lens |
|---|---|
| 1 | CF inventory + drift |
| 2 | Scheduler config drift |
| 3 | Dead monitoring + stale metrics |
| 4 | Pre-commit hook coverage |
| 5 | Schema vs code mismatches |
| 6 | Backfill + data quality gaps |
| 7 | Dead signals/filters/features |
| 8 | IAM + permissions drift |

### Headline findings — 16 BLOCKERS, 33 MAJORS, 24 MINORS

**The 6-week monitoring blackout story.** Multiple monitoring tables and schedulers went stale starting 2026-04-27 (a clear "off-season pause day") and were never resumed. Others have been silently failing on stale GCP v1 API paths since 2026-04-18/19. The off-season halt masked everything because no picks were being made.

**The hidden production data corruption story.** The just-fixed `three_pt_makes` was one column of a much wider problem: `nbac_play_by_play` source has been broken since January, taking 4+ shot-zone columns down with it. Vegas line features are 55% bad-quality in 2026. Two feature quality columns have wrong types in BQ (STRING vs FLOAT64).

**The dead-code story.** Multiple pre-commit hooks exist but aren't wired. Multiple CFs are deployed but never run. Multiple signals are registered but never fire. CLAUDE.md advertises features that don't exist in reality (`model_bb_candidates` "full 45-col provenance" is actually 30 cols).

---

## 4. The 15 follow-up tasks (#26–#40)

Listed by priority. Effort: XS=<30min, S=<2h, M=<1day, L=>1day.

### BLOCKERS — observability/safety dead

| # | Task | Effort | Why critical |
|---|---|---|---|
| **27** | Resume `filter-counterfactual-evaluator-daily` scheduler | XS | PAUSED 2026-04-27. `filter_counterfactual_daily` table empty since Apr 7. 23 active negative filters have zero CF-HR evidence — same class as Session 488 false-demote incident. One gcloud command. |
| **28** | Set `SLACK_WEBHOOK_URL_ALERTS` on `post-grading-export` CF | XS | Code at `main.py:457,481` logs "no SLACK_WEBHOOK_URL_ALERTS" every run. 66 NEVER_FIRED signals today would have alerted. CLAUDE.md + Session 411 promise Slack alerts — they don't fire. |
| **32** | Fix 2 dead pre-commit hooks (`validate-bq-sql-patterns`, `validate-sql-queries`) | XS | Same `types: [python, sql]` AND-bug as just-fixed `check-date-comparisons`. The first hook was built to catch Session 478's 6-day grading outage; both silently dead. `.pre-commit-config.yaml:122,130`. |
| **29** | Patch `post_grading_export` graded_count=0 branches | S | `model_performance_daily` stale since 2026-05-17 (12d). `league_macro_daily` stale since 2026-04-17 (42d). Same root cause: Session 474 patched signal_health branch only. NBA halt → 0 graded rows → tables stale → decay-detection blind, TIGHT-market regime gate using stale data. Lines 457, 481, 550. |
| **26** | Fix 17 silently-failing schedulers (stale GCP v1 API path) | M | All status=2 since 2026-04-18/19. Pipeline canaries, stall detectors, coverage validators, drift monitors all blind 40+ days. URI uses `us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/...` — needs migration to v2 + `roles/run.invoker` verification on `756957797294-compute` SA for each CR Job. |

### BLOCKERS — production data corruption

| # | Task | Effort | Why critical |
|---|---|---|---|
| **30** | Backfill `nbac_play_by_play` for 2026-01-12 → 2026-01-28 (16-day FAILED) | M | This is the deeper root cause of the three_pt_makes regression. Paint/mid_range/assisted_fg/and1 are 78-86% NULL in Mar-Apr among players who played. ~2,500 player-games need re-Phase-3 after PBP re-scrape. |
| **31** | Fix `feature_55_quality` + `feature_56_quality` column types (STRING in BQ, FLOAT64 in schema) | S | Silent data loss — any CAST/AVG returns garbage. Quality scorer truncates to 54 to avoid touching them. `feature_54_quality` + `feature_54_source` MISSING entirely. ALTER TABLE DROP + ADD, then backfill from `quality_scorer.build_quality_visibility_fields()`. |
| **33** | Investigate vegas line feature quality regression (f25/f26/f27/f50 at 55-67% bad quality) | M | ml_feature_store_v2 vegas line trio (feature_25/26/27) at 52-56% quality<50 in Jan-Apr 2026 (4,456 NULL of 8,071 rows in Jan). CLAUDE.md says "93%+ mid-season" — actually 45%. Critical: graduated signals `book_disagree_over` + `high_book_std_under_block` depend on f50, which is 60%+ NULL. |

### MAJORS — degraded but functional

| # | Task | Effort | Why |
|---|---|---|---|
| **34** | Wire 4 orphan pre-commit hooks (`validate_cloud_function_symlinks.py`, `validate_partition_filters.py`, `validate_code_quality.py`, `validate_all_schemas.py`) | S | Custom hooks exist on disk but not in `.pre-commit-config.yaml`. Running them NOW finds 5 missing CF symlinks (will break deploys) and 9 BQ partition-filter gaps (cause 400 errors). |
| **35** | Delete 7 dead CFs + 12 orphan source dirs | S | Dead CFs: `phase5-to-phase6` (zombie duplicate), `backfill-trigger` (Eventarc trigger missing since 2025-12-31), `dlq-monitor`/`self-heal-check`/`pipeline-dashboard`/`scraper-dashboard` (dead since 2026-03-25), `grading-delay-alert` (dead since 2026-05-04). Orphan code dirs in `orchestration/cloud_functions/`: `monthly_retrain`, `retrain_reminder`, `phase4_failure_alert`, `box_score_completeness_alert`, `prediction_monitoring`, `zero_workflow_monitor`, `system_performance_alert`, `upcoming_tables_cleanup`, `firestore_cleanup`, `mlb_pitcher_watchlist`, `mlb_phase3_to_phase4`, `mlb_phase4_to_phase5`, `mlb_phase5_to_phase6`. Update CLAUDE.md too. |
| **36** | Fix MLB schedulers running year-round (should be `3-10` month filter) | M | ~30 MLB schedulers (mlb-grading-daily, mlb-box-scores-daily, mlb-predictions-generate, mlb-events-morning, mlb-lineups-*, mlb-bp-props-*, mlb-statcast-daily, mlb-snapshot-daily, mlb-game-feed-daily, mlb-overnight-results, etc.) fire daily Nov-Feb wasting compute. Verify built-in date guards first, then add `3-10` to cron month field. Also: `mlb-signal-promotion-review` missing OIDC token (PERMISSION_DENIED every fire since 2026-05-15) — XS fix bundled in this task. |
| **37** | Remove `roles/editor` from `756957797294-compute` SA + add `mlb-phase2-raw-processors` Pub/Sub invoker IAM | M | Default compute SA is runtime identity for 61 of ~90 CFs + 3 Cloud Run services. `roles/editor` = read/write anything. Narrow to union of already-granted granular roles. Bundle with the Agent 8 BLOCKER fix: add `service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com` as invoker on mlb-phase2-raw-processors (silently 403s if subscription recreated). |
| **38** | Audit + cleanup dead signals/filters (Agent 7 findings) | M | Remove from BASE_SIGNALS: `day_of_week_over`, `predicted_pace_over`, `low_line_over` (tagged "noise"/"anti-signal" in aggregator.py:74-76, inflate real_sc). Unregister: `projection_disagreement` filter, `NegativeCLVFilter`, `PublicFadeFilter`, `denver_visitor_over`, `prop_line_drop_over`, `b2b_fatigue_under`. Mark removed: `rest_advantage_2d`, `sharp_book_lean_under`, `b2b_under`. ~15 signal files, 30 yaml lines. |
| **39** | Update `model_bb_candidates` writer to emit all 45 cols (currently 30, 15 silently NULL) | S | `signal_best_bets_exporter.py:1305-1336` writes 30 of 45 schema columns. NULL in BQ: `pipeline_hr_21d`, `feature_quality_score`, `combo_classification`, `combo_hit_rate`, `rank_in_pipeline`, `qualifying_subsets`, `filters_passed`, `filters_failed`, `observation_flags`, `player_line_tier`, `home_away`, `spread`, `over_rate_last_10`, `is_back_to_back`, `star_teammates_out`. CLAUDE.md "full 45-col provenance" misadvertised. |
| **40** | Regenerate `prediction_accuracy` + `model_bb_candidates` schema files | S | `schemas/bigquery/nba_predictions/prediction_accuracy.sql` is 13 cols behind live BQ. `model_bb_candidates` has no `.sql` DDL — only misplaced `schemas/model_bb_candidates.json`. Both are time-bombs for any environment recreation. |

### PENDING (deferred, separate from new tasks)

| # | Task | Status |
|---|---|---|
| **25** | Investigate stuck dates after BDB drain stabilizes | Pending. Reactivate ~2026-06-05. With Task #30 (PBP backfill) on the radar, this task may collapse into Task #30. |

---

## 5. The 30-minute priority order

If a fresh session has 30 minutes to do high-leverage work, do **Tasks 27, 28, 32** in this order:

1. **`gcloud scheduler jobs resume filter-counterfactual-evaluator-daily --location=us-west2 --project=nba-props-platform`** (Task #27) — 1 minute. Restores filter auto-demote loop.

2. **Find an existing Slack webhook (search `gcloud functions describe SLACK_WEBHOOK` across CFs, or `gcloud secrets list | grep slack`), then `gcloud functions deploy post-grading-export --update-env-vars=SLACK_WEBHOOK_URL_ALERTS=<url> --region=us-west2 --project=nba-props-platform`** (Task #28) — 5 minutes. Restores signal canary alerting to `#nba-betting-signals`.

3. **Edit `.pre-commit-config.yaml:122` and `:130` — change `types: [python, sql]` to `types_or: [python, sql]`** (Task #32) — 5 minutes. Activate two dead leak guards. Commit + push. Will trigger pre-existing-finding triage on future commits but doesn't break anything immediately.

If 2-3 hours: add Task #29 (patch graded_count=0 branches) and Task #34 (wire 4 orphan hooks).

If a full day: add Task #26 (17 broken schedulers — the biggest single observability win).

---

## 6. Context the system reminder won't tell you

### CLAUDE.md is partially stale

- "Cloud Functions (auto-deploy via cloudbuild-functions.yaml)" list mentions `retrain-reminder` and `monthly-retrain` — both are orphan dirs, never deployed. Mention `bdb-retry-processor` as NOT auto-deployed (it isn't).
- "TABLES: model_bb_candidates ... full provenance (45 cols)" — actually 30 cols + 15 NULL.
- "ml_feature_store_v2 clean rates 93%+ mid-season" — actually 45% for vegas line trio in 2026.
- "Filter auto-demote (Session 432): filter-counterfactual-evaluator CF daily 11:30 AM ET" — scheduler is PAUSED, has been since 2026-04-27.
- "Brier score calibration (Session 399): model_performance_daily has brier_score_7d/14d/30d" — table is stale since 2026-05-17.

A planned doc-cleanup pass would update these. Lower priority than the actual fixes.

### Schedulers paused 2026-04-27 (off-season pause day, no resume playbook)

These were likely intentionally paused for off-season but there's no checklist tracking what to resume:
- `decay-detection-daily` — auto-disable for model decay is off (`AUTO_DISABLE_ENABLED` env var is now dead code)
- `bias-decay-monitor-daily` (PAUSED 2026-05-16)
- `nba-grading-gap-detector`
- `weekly-retrain-trigger` — CLAUDE.md still advertises this as the canonical Monday 5 AM retrainer
- `signal-weight-report-weekly`
- `filter-counterfactual-evaluator-daily` (covered by Task #27)

Suggested: write `bin/resume-season-monitoring.sh` listing the resume commands. Add a CLAUDE.md note "off-season paused schedulers". Not a task per se but a sensible companion to Task #27.

### Things deliberately not bundled into tasks (worth knowing)

- **`mlb-game-lines-morning` `_DeadlockError`** on import of `scrapers.mlb.oddsapi.mlb_events`. Code bug, not config — blocks daily MLB game lines. Requires MLB scraper code work.
- **9 stale shadow signals at 90+ days observation**: `consistent_scorer_over` (71% N=7), `career_matchup_over` (0%), `minutes_load_over`, `over_trend_over`, `dvp_favorable_over`, `sharp_money_under`, `projection_consensus_under`, `3pt_bounce` (29% HR), `b2b_boost_over` (unclear status). Decide or delete each.
- **Empty per-secret IAM bindings** on most secrets (works only because of project-level `secretAccessor`). Defense-in-depth gap.
- **`feature_38` (game_total_line) bad-quality EXPLODED Jan-Feb** then self-recovered. Quality<50: Nov 3.3% → Jan 34.0% → Feb 22.3% → Mar 1.0%. ~3,800 rows backfill. Model trained on this window — may explain part of the 2025-26 anomaly.

---

## 7. Files modified outside the repo (won't show in git diff)

| Resource | Change | How to restore if needed |
|---|---|---|
| Cloud Scheduler `bdb-retry-hourly` | message body → `{"action":"retry","max_age_days":200}` | `gcloud scheduler jobs update pubsub bdb-retry-hourly --location=us-west2 --project=nba-props-platform --message-body='{"action":"retry","max_age_days":200}'` |
| Cloud Function `bdb-retry-processor` env | `LOG_LEVEL=INFO`, `PHASE3_SERVICE_URL=https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app` | `gcloud functions deploy bdb-retry-processor --region=us-west2 --project=nba-props-platform --source=orchestration/cloud_functions/bdb_retry_processor --gen2 --runtime=python311 --entry-point=bdb_retry_handler --trigger-topic=bdb-retry-trigger --update-env-vars="LOG_LEVEL=INFO,PHASE3_SERVICE_URL=https://nba-phase3-analytics-processors-f7p3g7f6ya-wl.a.run.app"` |
| BQ table `nba_orchestration.pending_bdb_games` | 1,749 rows reset completed_bdb→pending_bdb; 367 zombies moved pending_bdb→failed_max_retries | Idempotent — only matters if you want to undo, which you shouldn't |
| BQ table `nba_analytics.player_game_summary` | 5,635 rows backfilled three_pt_makes + three_pt_attempts | Idempotent |

**Working tree** has 1,356+ dirty files from prior session work. I did NOT touch those. If a future session wants to start fresh, that mess needs investigation — most are likely auto-generated (`__pycache__`) but some may be real WIP.

---

## 8. Things I deliberately did NOT do (and why)

- **Did not commit any of the 1,276+ pre-existing dirty files.** Not mine, scope unclear.
- **Did not start star-OUT signal work.** Per `2026-05-24-1-nba-star-out-discovery.md` and the user's choice on the 4-agent meta-review: deferred to September after first clean retrain.
- **Did not mass-reset all completed_bdb rows.** Only the 1,749 where BDB is genuinely available. Other completed_bdb rows are legitimately complete or genuinely failed.
- **Did not investigate `mlb-game-lines-morning` deadlock.** Out of scope for off-season work; flag for MLB pre-season prep.
- **Did not update CLAUDE.md** despite finding several stale claims. CLAUDE.md is read-mostly and changes deserve their own focused commit.
- **Did not commit scheduler config to repo.** No existing IaC pattern; one-off via `gcloud`.
- **Did not investigate ml_feature_store_v2 vegas line backfill cause.** Captured as Task #33. The fix needs careful root-cause analysis (Phase 4 attachment vs source data vs leak-fix backfill scope).
- **Did not delete dead signal files.** Captured as Task #38. Cleanup deserves a focused session with code review.

---

## 9. Verification commands (60-second smoke tests)

```bash
# Confirm three commits landed and are pushed
git log --oneline -3  # should show 8e207042, dd7b293a, 24eefefd

# Confirm bdb-retry-processor is on the right revision
gcloud run services describe bdb-retry-processor --region=us-west2 \
  --project=nba-props-platform \
  --format="value(status.traffic[0].revisionName)"
# expected: bdb-retry-processor-00005-nex

# Confirm scheduler message body fix is live
gcloud scheduler jobs describe bdb-retry-hourly --location=us-west2 \
  --project=nba-props-platform --format="value(pubsubTarget.data)" | base64 -d
# expected: {"action":"retry","max_age_days":200}

# BDB drain state
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT status, COUNT(*) AS n FROM `nba-props-platform.nba_orchestration.pending_bdb_games`
WHERE game_date >= "2026-01-01" GROUP BY status ORDER BY n DESC'

# Confirm three_pt_makes backfill is live
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT game_date,
  ROUND(100*COUNTIF(three_pt_makes IS NOT NULL)/COUNT(*), 1) AS pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date BETWEEN "2026-03-03" AND "2026-03-10"
GROUP BY game_date ORDER BY game_date'
# expected: each date at 57-64% (rest are correctly DNP)

# Confirm filter_counterfactual_daily is still empty (Task #27 not yet done)
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT MAX(game_date) AS last_date FROM `nba-props-platform.nba_predictions.filter_counterfactual_daily`'

# Confirm model_performance_daily is still stale (Task #29 not yet done)
bq query --use_legacy_sql=false --project_id=nba-props-platform '
SELECT MAX(game_date) AS last_date FROM `nba-props-platform.nba_predictions.model_performance_daily`'
# expected: 2026-05-17 (or whatever — if past that, Task #29 may have been done)
```

---

## 10. Out of scope (kept out, still out)

- Star-OUT signal — defer to September.
- MLB pitcher-strikeout betting — permanently halted (efficient market, no edge).
- The 1,276+ file working tree mess.
- Anything model-retraining-related — fleet is BLOCKED + halted, off-season.

---

## 11. Memory file index — what's stored

The auto-memory at `~/.claude/projects/-home-naji-code-nba-stats-scraper/memory/MEMORY.md` indexes all topic files. Particularly relevant for next session:

- `offseason-roadmap-2026-05.md` — 2026-05 engine roadmap progress, now corrected
- `2025-26-anomaly-rootcause.md` — diagnosis of the 2025-26 collapse (referenced by star-OUT discovery)
- `nba-feature-leak-audit.md` — the May 22 leak audit (vegas line saga, 16 fixes)
- `star-out-vacated-touches-signal.md` — the deferred signal discovery
- `nba-angles-tested-2026-05-23.md` — what was ruled out before star-OUT

**Worth adding next session:** a memory file for the 8-agent audit findings (capture the 73 findings, not just the 15 I escalated to tasks). The agent reports themselves are gone from this session — only the tasks remain.

---

**End of handoff.** Next session: read this, then check `TaskList` for #26-#40 + #25. Quickest wins are tasks 27, 28, 32 in that order.
