# Scheduler-Job Restore Manifest — 2026-07-03 deletion event

**Produced by the 4-fable-agent path-forward review (2026-07-03). This is the curated
input for `scripts/nba_offseason_restore_jobs.sh` (to be built — spec at bottom).**

**Source of truth:** `gs://nba-bigquery-backups/scheduler-jobs-backup/scheduler_jobs_backup_2026-07-03.json`
(204 jobs, full configs incl. OIDC, headers, bodies, retryConfig, timeZone).
**Diff vs live at curation time:** 110 live, **94 deleted** — **65 non-MLB** (curated below),
29 MLB-prefixed (all pre-PAUSED; noted at bottom, not curated).
**URL freshness:** every deleted non-MLB job's URI uses the current
`https://{service}-f7p3g7f6ya-wl.a.run.app` format and every target service exists and matches
live `status.url`. Zero stale-URL jobs. Pub/Sub targets (`nba-grading-trigger`,
`nba-phase6-export-trigger`) both exist. `player-movement-registry-job` Cloud Run job exists.

## VERDICT: RESTORE (58 jobs) — all restore-as **PAUSED**, resume in waves before Oct 21 opener

### Wave A — resume T-14 to T-10 (data collection warms feature history)

| Job | Schedule (tz) | Target | Evidence/notes |
|---|---|---|---|
| execute-workflows | `5 0-23 * * *` (ET) | POST nba-scrapers `/execute-workflows` | Route verified `scrapers/routes/orchestration.py:149`. **Resume PAIRED with `master-controller-hourly`** (currently ENABLED writing decisions nothing executes — pause it now, resume both together) |
| nba-props-morning | `0 7 * * *` (UTC) | nba-scrapers `/execute-workflow` body `betting_lines` | CLV baseline (P1.2) freshness math assumes these kicks |
| nba-props-midday | `0 12 * * *` (UTC) | same | |
| nba-props-pregame | `0 16 * * *` (UTC) | same | |
| nba-props-evening-closing | `0 22 * * *` (UTC) | same, `snapshot_type:"closing"` | Already points at nba-scrapers. Complementary to — NOT replaced by — the NEW `nba-closing-lines-sweep` T-30 job (`bin/deploy/deploy_closing_lines_scheduler.sh`, not in backup, create separately `--paused`) |
| rotowire-lineups-daily | `0 21 * * *` (UTC) | nba-scrapers `/scrape` rotowire_lineups | Scraper in registry.py ✓ |
| nba-tracking-stats-daily | `0 10 * * *` (UTC) | `/scrape` nba_tracking_stats | **Resume only after verifying commit `7d1a3f9b` (drives-zero fix) is deployed; check first run's drive values ≠ 0.0** |
| hashtagbasketball-dvp-daily | `0 9 * * *` (UTC) | `/scrape` hashtagbasketball_dvp | Scraper ✓ |
| vsin-betting-splits-daily | `0 18 * * *` (UTC) | `/scrape` vsin_betting_splits | Scraper ✓ |
| numberfire-projections-daily | `30 14 * * *` (UTC) | `/scrape` numberfire_projections | Projection-consensus input |
| fantasypros-projections-daily | `30 14 * * *` (UTC) | `/scrape` fantasypros_projections | |
| dailyfantasyfuel-projections-daily | `30 14 * * *` (UTC) | `/scrape` dailyfantasyfuel_projections | |
| dimers-projections-daily | `45 14 * * *` (UTC) | `/scrape` dimers_projections | |
| espn-projections-daily | `45 14 * * *` (UTC) | `/scrape` espn_projections | Consumed by supplemental_data + per_model_pipeline (projection consensus) |
| covers-referee-stats-weekly | `0 10 * * 1` (UTC) | `/scrape` covers_referee_stats | |
| nbac-player-movement-daily | `0 8,14 * * *` (ET) | `/scrape` nbac_player_movement | ⚠️ Body hardcodes `"year":"2026"` — verify year-param semantics at restore; script must NOT blindly replay this body across year boundaries |
| player-movement-registry-morning / -afternoon | `10 13` / `10 19 * * *` (UTC) | run.googleapis.com jobs/`player-movement-registry-job`:run | Cloud Run job exists ✓ (2 jobs) |
| odds-sweep-nightly | `0 6 * * *` (UTC) | nba-phase2-raw-processors `/sweep-odds` | Route verified `main_processor_service.py:236` |

### Wave B — resume T-7 (pipeline backstops + feature store)

| Job | Schedule (tz) | Target | Evidence/notes |
|---|---|---|---|
| overnight-analytics-6am-et | `0 6 * * *` (ET) | phase3 `/process-date-range` YESTERDAY, 5 processors | Grading-data backstop |
| evening-analytics-6pm-et | `0 18 * * 0,6` (ET) | phase3, TODAY PlayerGameSummary | Weekend matinee catch (`bin/orchestrators/setup_evening_analytics_schedulers.sh` exists) |
| evening-analytics-10pm-et | `0 22 * * *` (ET) | phase3, TODAY | Catches 7 PM games |
| overnight-phase4 | `0 6 * * *` (ET) | phase4 `/process-date` TODAY, 5 processors | ⚠️ Near-duplicate of next row (TODAY vs YESTERDAY) — restore both, they serve different dates; see DECIDE #2 |
| overnight-phase4-7am-et | `0 7 * * *` (ET) | phase4, YESTERDAY, 5 processors | |
| ml-feature-store-daily | `30 23 * * *` (**PT**) | phase4 MLFeatureStoreProcessor AUTO | Note America/Los_Angeles tz — script must preserve per-job tz |
| ml-feature-store-7am-et / -10am-et / -1pm-et | `0 7/10/13 * * *` (ET) | phase4 MLFeatureStoreProcessor | Feature freshness per prediction run (3 jobs) |
| player-composite-factors-daily | `0 23 * * *` (**PT**) | phase4 PlayerCompositeFactors AUTO | |
| player-composite-factors-upcoming | `0 5 * * *` (ET) | phase4, TODAY | Session 95 |
| player-daily-cache-daily | `15 23 * * *` (**PT**) | phase4 PlayerDailyCache AUTO | |
| same-day-phase4 | `0 11 * * *` (ET) | phase4 MLFeatureStore TODAY | same-day chain currently decapitated (live `same-day-phase3` fires into nothing). `setup_same_day_schedulers.sh` covers phase3/4/predictions but NOT -tomorrow variants — backup restore is more complete |
| same-day-predictions | `0 11 * * *` (ET) | prediction-coordinator `/start` RETRY | |
| same-day-phase3-tomorrow | `0 17 * * *` (ET) | phase3 Upcoming*Context TOMORROW | |
| same-day-phase4-tomorrow | `30 17 * * *` (ET) | phase4 TOMORROW | |
| same-day-predictions-tomorrow | `0 20 * * *` (ET) | coordinator PRE_GAME TOMORROW | |
| boxscore-completeness-check | `0 6 * * *` (ET) | phase2 `/monitoring/boxscore-completeness` | Route verified `main_processor_service.py:319` (distinct from removed orphan CF) |
| phase4-timeout-check-job | `*/15 * * * *` (ET) | phase4-timeout-check CF | Service ✓ |

### Wave C — resume T-3 to opening night (prediction engine + exports + model ops)

| Job | Schedule (tz) | Target | Evidence/notes |
|---|---|---|---|
| **weekly-retrain-trigger** | `0 5 * * 1` (ET) | POST weekly-retrain CF | **#1 CRITICAL — weekly retraining is silently dead without it** (CF verified `eventTrigger: None`, HTTP-only, no other invoker). CLAUDE.md's "fires every Monday" is currently FALSE |
| **decay-detection-daily** | `0 16 * * *` (UTC) | decay-detection CF | HTTP-only CF; without it no decay state machine / auto-disable |
| overnight-predictions | `0 8 * * *` (ET) | coordinator `/start` FIRST | |
| predictions-9am / predictions-12pm | `0 9` / `0 12` (ET) | coordinator RETRY | (2 jobs) |
| morning-predictions | `0 10 * * *` (ET) | coordinator RETRY | |
| predictions-final-retry | `0 13 * * *` (ET) | coordinator FINAL_RETRY | 80% quality threshold |
| predictions-last-call | `0 16 * * *` (ET) | coordinator LAST_CALL | Backup description stale — Session 139 made LAST_CALL a 70% threshold (`quality_gate.py:48`); mode legit, restore |
| self-heal-predictions | `45 12 * * *` (ET) | self-heal-predictions CF | Service ✓ |
| missing-prediction-check | `0 19 * * *` (ET) | check-missing CF, TOMORROW | Service ✓ |
| phase6-tonight-picks-morning | `0 11 * * *` (ET) | PUBSUB `nba-phase6-export-trigger` | Topic + eventarc→phase6-export verified. Live 1 PM job covers midday only |
| phase6-tonight-picks-pregame | `0 17 * * *` (ET) | PUBSUB same, incl. signal-best-bets | Correct message format ✓ |
| live-export-evening | `*/3 16-23 * * *` (ET) | live-export CF | In-game scores |
| live-export-late-night | `*/3 0-1 * * *` (ET) | live-export CF | |
| grading-readiness-check | `*/15 22-23,0-2 * * *` (ET) | grading-readiness-monitor CF | Complements (not duplicates) completion-driven grading |
| nba-grading-gap-detector | `0 9 * * *` (ET) | grading-gap-detector CF `{"days":14}` | Documented in CLAUDE.md monitoring |
| bias-decay-monitor-daily | `30 11 * * *` (ET) | bias-decay-monitor CF | LOST_EDGE/LOSING_BAD alerts |
| signal-weight-report-weekly | `0 10 * * 1` (ET) | signal-weight-report CF | The promotion-tracker's only delivery vehicle |
| validation-post-overnight | `0 6 * * *` (ET) | GET validation-runner `?schedule=post_overnight` | (3 validation jobs) |
| validation-pre-game-prep | `0 8 * * *` (ET) | `?schedule=pre_game_prep` | |
| validation-pre-game-final | `0 18 * * *` (ET) | `?schedule=pre_game_final` | |

## VERDICT: SKIP-SUPERSEDED (3)

| Job | Superseding mechanism (verified) |
|---|---|
| grading-morning (`0 7` ET) | Completion-driven grading: `phase3-to-grading` (live ✓) → `nba-grading-trigger` topic (✓) → eventarc sub → `phase5b-grading` (live ✓). Backstops: grading-readiness-check + nba-grading-gap-detector (both RESTORE) |
| grading-daily (`0 11` ET) | same |
| grading-latenight (`30 2` ET) | same |

**⚠️ Wrong-verdict-the-other-way risk:** restoring these would risk double-grading/aggregation
races on top of the eventarc path. Skip is correct ONLY because the two backstops are restored.

## VERDICT: SKIP-OBSOLETE (2)

| Job | Why |
|---|---|
| nba-playoffs-shadow-activate | One-shot reminder `0 9 14 4 *` (Apr 14, 2026) — date passed |
| nba-playoffs-shadow-review | One-shot `0 9 1 5 *` (May 1, 2026) — date passed |

## VERDICT: DECIDE (2)

| Job | Question |
|---|---|
| kalshi-props-scraper (`0 7` UTC → `/scrape` kalshi_player_props) | Scraper + phase2 processor exist end-to-end but ZERO consumers in ml/, shared/, precompute, publishing — raw ingestion only. Restore (cheap optionality, unbroken kalshi history) or skip (dead-end data)? Default lean: restore PAUSED, decide at Wave A |
| overnight-phase4 vs overnight-phase4-7am-et dedup | Both restored (TODAY vs YESTERDAY targets), but confirm the 6 AM TODAY run isn't redundant with `player-composite-factors-upcoming` (5 AM) + orchestrator-driven Phase 4 — consolidation candidate, not a blocker |

## Counts

Backup 204 → live 110 → deleted 94 → **non-MLB 65**: **RESTORE 58** (all PAUSED; waves
A=19, B=18, C=21), **SKIP-SUPERSEDED 3**, **SKIP-OBSOLETE 2**, **DECIDE 2**.

MLB (29 deleted, all pre-PAUSED): 13 one-shot reminders with passed dates; the rest duplicate
nothing live, but MLB is halted per strategy — correctly dead. If MLB resumes, curate separately.
⚠️ `mlb-live-boxscores` + `mlb-oddsa-pitcher-props-burst-*` target `mlb-phase1-scrapers`
(manual-deploy-only service).

## Top 5 jobs where a wrong verdict hurts most

1. **weekly-retrain-trigger** — skip = fleet stale by week 2, "confidently wrong" high-edge picks.
2. **decay-detection-daily** — skip = no HEALTHY→BLOCKED state machine; decayed model pollutes best bets silently.
3. **execute-workflows** — skip = most Phase-1 scraping silently never runs (upstream of everything).
4. **grading-morning/daily/latenight** — restoring them (wrong the other way) risks double-grading races.
5. **nba-props-evening-closing + phase6-tonight-picks-pregame** — skip = CLV capture chain + 5 PM export break; closes un-backfillable.

## Restore-script spec (`scripts/nba_offseason_restore_jobs.sh` or `.py`)

- **Inputs:** (1) backup JSON path/GCS URI, (2) this manifest as machine-readable sidecar
  (job → verdict/wave), (3) flags: `--dry-run` (default ON), `--wave A|B|C|all`, `--job NAME`,
  `--paused` (default TRUE — always create paused regardless of backup state).
- **Per RESTORE job:** idempotent — `describe` first; skip if exists (or `--force-update`).
  Create from backup preserving schedule, **timeZone (3 jobs are America/Los_Angeles — do NOT
  normalize)**, httpMethod, URI, headers, **body verbatim** (base64-decode → `--message-body`),
  **oidcToken audience + serviceAccountEmail** (`756957797294-compute@developer.gserviceaccount.com`),
  attemptDeadline, retryConfig. Pub/Sub jobs: `jobs create pubsub` with topic + data.
- **Exclusions enforced in-script:** never create SKIP-*; DECIDE requires `--include-decide`.
- **Special cases:** `nbac-player-movement-daily` — warn on hardcoded `"year":"2026"`;
  `nba-tracking-stats-daily` — print drives≠0.0 verification reminder; print reminder that
  `nba-closing-lines-sweep` is NOT in the backup — run `deploy_closing_lines_scheduler.sh --paused`.
- **Output:** summary table (created/skipped-exists/excluded) + post-run diff vs manifest;
  non-zero exit if any RESTORE job failed.
- **Companion actions (not jobs):** pause live `master-controller-hourly` now, resume with
  execute-workflows; unpause the paused-not-deleted set (REB/AST jobs, espn-injuries-hourly,
  rotowire-nba-news-*, nba-pipeline-canary-* [AFTER image fix], nba-deployment-drift-alerter-trigger)
  per `docs/02-operations/runbooks/season-resume-2026-27.md`.
