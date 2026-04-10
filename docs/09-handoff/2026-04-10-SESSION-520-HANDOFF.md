# Session 520 Handoff — MLB Pipeline Full Fix + Season Retrospective

**Date:** 2026-04-10
**Focus:** MLB grading (never worked), all.json publishing, deploy script fixes, NBA season retrospective
**Commits:** `a9c7b6e7` through `519906f1` (6 commits on `main`)

---

## TL;DR

- **MLB grading pipeline was completely non-functional since deployment.** 14 cascading bugs found and fixed. First-ever grading: 6-6 (50%) on 12 predictions.
- **MLB all.json now live** at `gs://nba-props-platform-api/v1/mlb/best-bets/all.json` with season record, weekly history, and pick results.
- **Post-grading pipeline fully wired:** grading → analytics (league_macro) → all.json re-export → all working on deployed service.
- **MLB schedule statuses fixed:** `SKIP_DEDUPLICATION = True` was never committed. Yesterday re-scrapes were silently blocked. All Apr 1-9 games now show Final.
- **Deploy scripts hardened:** All 3 manual scripts now include `update-traffic --to-latest`.
- **NBA season final:** 415-235 (63.8%). Edge 7+ UNDER: 18-0 (100%). Off-season priorities documented.

---

## What Was Done

### Phase 1 — System Evaluation (4 parallel agents)

| Agent | Findings |
|-------|----------|
| MLB pipeline health | Grading: 0 records ever. Post-grading tables empty. Scrapers working. |
| NBA season performance | 415-235 (63.8%). Jan 73.8%, Feb 63.3%, Mar 46.7%. Auto-halt active. |
| Infrastructure health | 1 drift (validation-runner, false positive). Builds passing. MLB services routing correctly. |
| Off-season research | Model architecture ceiling, assists/rebounds feasibility (2-3 week MVP), OVER overhaul needed. |

### Phase 2 — MLB Grading Fix (14 bugs)

| # | Bug | Root Cause | Fix |
|---|-----|------------|-----|
| 1 | `feature_quality_score` column doesn't exist | Column name mismatch in `_get_predictions()` | → `feature_coverage_pct` |
| 2 | `_resolve_date()` case-sensitive | Scheduler sends `YESTERDAY`, code matches lowercase only | `.lower()` comparison |
| 3 | `is_voided`/`void_reason` in MERGE | Columns don't exist in `pitcher_strikeouts` table | Removed from MERGE |
| 4 | Dockerfile missing `ml/` | Post-grading analytics imports fail | `COPY ml/` |
| 5 | Pub/Sub endpoint `/grade` | Flask app uses `/process` | gcloud subscription update |
| 6 | `confidence_score` NUMERIC(4,3) | Values like 13.82 exceed 9.999 limit | ALTER to full NUMERIC |
| 7 | `game_pk` REQUIRED but NULL | Older predictions have no game_id | Made NULLABLE |
| 8 | BQ streaming insert None values | Explicit None on INTEGER NULLABLE → "cannot be empty" | Strip None from dicts |
| 9 | `SKIP_DEDUPLICATION` never committed | Only existed in local working copy | Committed + deployed |
| 10 | `export_all()` queries wrong table | `pitcher_strikeouts` with confidence >= 70 (always empty) | → `signal_best_bets_picks` |
| 11 | `_get_best_bets()` queries wrong table | Same as #10 for daily export | → `signal_best_bets_picks` |
| 12 | Dockerfile missing `data_processors/publishing/` | Post-grading all.json import fails | `COPY data_processors/publishing/` |
| 13 | `league_macro` load_table_from_json | Inferred schema NULLABLE conflicts with REQUIRED | → `insert_rows_json` streaming |
| 14 | Deploy scripts missing traffic routing | 3 manual scripts don't route to latest | Added `update-traffic --to-latest` |

**Why grading was silent:** Exception caught in `_get_predictions()` → returns empty list → processor logs "No predictions found" → returns True → service returns 200. No errors. No alerts.

### Phase 3 — MLB Data Backfills

| Data | Dates | Method |
|------|-------|--------|
| `mlbapi_pitcher_stats` | Apr 5-8 | Triggered `mlb_box_scores_mlbapi` scraper + direct BQ insert |
| `mlb_schedule` statuses | Apr 1-9 | Direct BQ load from latest GCS files (all Final) |
| `prediction_accuracy` | Apr 1-9 | Local grading run: 12 predictions graded (6-6) |
| `league_macro_daily` | Apr 9 | First-ever MLB row via deployed grading service |

### Phase 4 — Deploy Script Hardening

All 3 manual deploy scripts now include `gcloud run services update-traffic --to-latest`:
- `bin/deploy-service.sh`
- `bin/hot-deploy.sh`
- `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh`

Cloud Build YAMLs were already fixed in Session 516.

---

## Current System State (2026-04-10 ~23:15 UTC)

### MLB Pipeline — FULLY OPERATIONAL

| Component | Status | Revision |
|-----------|--------|----------|
| `mlb-phase6-grading` | Healthy, all subsystems working | 00010-6qw |
| `mlb-phase2-raw-processors` | SKIP_DEDUPLICATION deployed | 00008-pqc |
| `mlb_predictions.prediction_accuracy` | 17 rows (some duplicates from streaming buffer) |
| `mlb_predictions.league_macro_daily` | 1 row (Apr 9, first ever) |
| `mlb_predictions.signal_best_bets_picks` | 3 rows (Apr 9 manual + Apr 10 automated) |
| `mlb/best-bets/all.json` | Live, 4 picks, 2-0 graded record |
| Schedule statuses | Apr 1-9 all Final, Apr 10 Scheduled (correct) |

### NBA Pipeline

- Auto-halt active (avg edge ~1.5 vs 5.0 threshold)
- Season ends ~Apr 13 (3 days)
- **Final record: 415-235 (63.8%)**

---

## Commits

| SHA | What |
|-----|------|
| `a9c7b6e7` | MLB grading 5-bug fix + deploy script traffic routing |
| `825eabb4` | MLB grading strip None values for BQ streaming insert |
| `5c4ce1e5` | MLB all.json exports from signal_best_bets_picks |
| `ec8b1cc3` | MLB schedule re-scrape dedup + post-grading all.json + daily export |
| `2cfec496` | MLB grading Dockerfile + league_macro None serialization |
| `519906f1` | MLB league_macro use streaming insert instead of load job |

---

## Key Discoveries (Carry Forward)

### 1. BQ streaming insert vs load_table_from_json
- `insert_rows_json`: Uses table's existing schema. Treats missing keys as NULL. But explicit `None` on INTEGER fields errors with "cannot be empty". Fix: strip None from dicts.
- `load_table_from_json`: Infers schema from data. If a REQUIRED field is absent (stripped None), inferred schema says NULLABLE → conflicts with table's REQUIRED mode. Don't use for partial rows.

### 2. Silent grading failure pattern
`_get_predictions()` catches BQ errors and returns `[]`. The processor interprets empty predictions as "no games today" and returns success. No errors logged, no alerts fired. **Every new BQ query in a grading pipeline should log the SQL error, not swallow it.**

### 3. `SKIP_DEDUPLICATION` is critical for re-scrape processors
Without it, `ProcessorBase.check_already_processed()` finds the first successful run and blocks all subsequent runs for the same date. The "yesterday" re-scrape pattern (common for schedule/scores) requires `SKIP_DEDUPLICATION = True`.

### 4. Cloud Run services sharing images still need separate deploys
`mlb-phase2-raw-processors` uses the same Docker image as `nba-phase2-raw-processors`, but Cloud Build only deploys the NBA service. MLB needs manual redeployment after each build, or a separate Cloud Build trigger.

---

## NBA 2025-26 Season Retrospective

### Final Numbers

| Period | Picks | HR% |
|--------|-------|-----|
| January | 229 | **73.8%** |
| February | 297 | **63.3%** |
| March | 120 | 46.7% |
| April | 4 | 50.0% |
| **Season** | **650** | **63.8%** |

### What Worked
- BB pipeline adds +7-12pp above raw model (53% → 64%)
- UNDER is the stable profit center (57-58% across 5 seasons)
- Edge 7+ UNDER: **18-0 (100%)**
- Combo signals: `combo_3way` 95.5%, `book_disagree_over` 79.6%
- Negative filters add +13.7pp
- Auto-halt correctly stopped March/April bleeding

### What Didn't Work
- OVER collapsed Jan→Mar (80%→47%), net-negative in 4/5 seasons at edge 3-5
- Adding features consistently hurts (80+ dead ends)
- March training data compresses edge
- Retrain governance blocks recovery during auto-halt (chicken-and-egg)

### Off-Season Priorities (Ranked)
1. **Model architecture** — Quantile as signal (Option A, low-cost), ensemble diversity
2. **Assists/rebounds expansion** — 72% features reusable, ~2-3 week MVP
3. **OVER strategy overhaul** — Higher floor (6-7), archetype targeting, regime restriction
4. **Retrain governance recovery** — Separate gates for "first model after halt"
5. **Book-count-aware thresholds** — Rehabilitate std-based signals for 12+ book regime
6. **MLB auto-deploy for grading** — Add Cloud Build trigger

---

## Outstanding Work

### Ready to Build
1. **MLB auto-deploy trigger for grading service** — Add Cloud Build trigger watching `data_processors/grading/mlb/**`
2. **MLB Phase 2 auto-deploy trigger** — Or add MLB service to existing `deploy-nba-phase2-raw-processors` trigger

### Monitor
3. **Post-grading analytics** — league_macro working. model_performance/signal_health need more graded data.
4. **MLB schedule re-scrape** — `SKIP_DEDUPLICATION` now committed. Tomorrow's 8 AM re-scrape should update today's games to Final.
5. **prediction_accuracy duplicates** — Streaming buffer collisions from rapid re-grading. Will resolve after buffer flush (~30 min). The DELETE-before-INSERT pattern handles idempotent re-grading.

### Deferred
6. **Off-season NBA improvements** — See priorities list above
7. **MLB weekly auto-retrain** — Not urgent until more graded data

---

## Files Changed

| Purpose | File |
|---------|------|
| Grading processor fixes | `data_processors/grading/mlb/mlb_prediction_grading_processor.py` |
| Grading service (date resolution, post-grading wiring) | `data_processors/grading/mlb/main_mlb_grading_service.py` |
| Grading Dockerfile (ml/, publishing/) | `data_processors/grading/mlb/Dockerfile` |
| all.json + daily export fix | `data_processors/publishing/mlb/mlb_best_bets_exporter.py` |
| Schedule SKIP_DEDUPLICATION | `data_processors/raw/mlb/mlb_schedule_processor.py` |
| League macro streaming insert | `ml/analysis/mlb_league_macro.py` |
| Deploy script traffic routing | `bin/deploy-service.sh`, `bin/hot-deploy.sh`, `bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh` |

## Infrastructure Operations

| Operation | Detail |
|-----------|--------|
| BQ ALTER | `prediction_accuracy.confidence_score` NUMERIC(4,3) → NUMERIC |
| BQ ALTER | `prediction_accuracy.game_pk` REQUIRED → NULLABLE |
| BQ INSERT | `mlbapi_pitcher_stats` backfill Apr 5-8 (511 rows) |
| BQ LOAD | `mlb_schedule` Apr 1-9 (115 games with Final status) |
| BQ INSERT | `prediction_accuracy` Apr 1-9 (12 graded predictions) |
| BQ INSERT | `league_macro_daily` Apr 9 (first MLB row) |
| Pub/Sub | `mlb-phase6-grading-sub` endpoint `/grade` → `/process` |
| Cloud Run | `mlb-phase6-grading` → revision 00010-6qw (manual build+deploy) |
| Cloud Run | `mlb-phase2-raw-processors` → revision 00008-pqc (manual deploy) |
| IAM | Added `nchammas@gmail.com` as invoker on `mlb-phase2-raw-processors` |
| GCS | `mlb/best-bets/all.json` published (first working version) |
