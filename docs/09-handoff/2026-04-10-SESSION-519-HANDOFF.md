# Session 519 Handoff — MLB Pipeline End-to-End + 12-Bug Fix Chain

**Date:** 2026-04-10
**Focus:** Session 518 punch list execution → discovered deeper root causes → comprehensive MLB pipeline fix + infrastructure recovery
**Commits:** `5fb1c731` through `acc874a8` (8 commits on `main`)

---

## TL;DR

- **MLB best bets pipeline is FULLY OPERATIONAL for the first time in 2026.** 3 picks persisted to BQ (jeffrey_springs Apr 9 manual, jt_ginn + keider_montero Apr 10 automated).
- **Session 518's "one-line game_pk fix" was wrong.** `game_id` was never in the prediction dict — `load_batch_features` queries pgs for PAST games only. Fixed by adding `load_schedule_context()` that queries `mlb_schedule` for today's game_pk/is_home/pitcher_name.
- **Team_abbr matching was fragile.** OAK→ATH rename broke jt_ginn's lookup. Fixed with pitcher-name normalization (strip non-alpha, lowercase).
- **is_home bug fixed.** max_meyer's 1.2 edge was wrongly blocked (NULL→treated as away→1.25 floor). Now correctly resolved from schedule.
- **scraper-gap-backfiller deployed** after 2+ months broken. Revisions 00003-00006 all failed on import chains. Fixed with lazy import + fallback.
- **Prediction duplication prevented.** `/best-bets` now checks if predictions exist before writing.
- **Post-grading analytics wired.** league_macro, model_performance, signal_health now compute after MLB grading.

---

## What Was Done

### Phase A — Verification
- `pitcher_strikeouts` Apr 9: 1500 (5x duplication from S518 retriggers)
- `signal_best_bets_picks`: empty for Apr 9+10 (game_pk REQUIRED constraint)
- 32 unbackfilled `scraper_failures` (24 from disabled `bdb_pbp_scraper`)

### Phase B — Manual Recovery
- Inserted jeffrey_springs Apr 9 best bet manually (game_pk=823565, ATH vs NYY)
- Deduped pitcher_strikeouts: Apr 6 (606→303), Apr 9 (1500→300), Apr 10 (600→300)

### Phase C+D — Schema Audit + Fix (merged — handoff's one-line fix was wrong)
- **Built full schema-drift table:** 47 BQ columns mapped against exporter code
- **3 structural NULLs fixed:** game_pk, is_home, pitcher_name — all from new `load_schedule_context()`
- **Team_abbr fragility fixed:** Pitcher-name matching (normalize to alpha-only) handles OAK→ATH and trades
- **game_pk guard:** Exporter skips picks without game_pk instead of failing entire batch
- **REPEATED fields:** warning_tags, agreeing_model_ids explicitly set to `[]`; source_model_id populated

### Phase E — Punch List (#3-#8)
| # | Item | Fix |
|---|---|---|
| 3 | supplemental_loader `total_line` | → `total_runs` (BQ column name) |
| 4 | 292 spurious BLOCKED rows | Added WHERE clause filtering pitchers without lines |
| 5 | staging-tagged revision | Removed tag + set `--to-latest` |
| 6 | scraper-gap-backfiller | Lazy import with fallback, deployed revision 00007 |
| 7 | validation-runner drift | FALSE POSITIVE — relevant files unchanged |
| 8 | parameter_resolver `date` | → `gamedate` in YYYYMMDD format |

### Phase F — New Tasks from 4-Agent Review
| # | Task | Status |
|---|---|---|
| 1 | MLB prediction duplication prevention | **Done** — skip write if exists |
| 2 | Deploy scraper-gap-backfiller | **Done** — revision 00007-tig |
| 3 | Dedup pitcher_strikeouts Apr 10 | **Done** — 627 rows removed |
| 4 | Wire MLB post-grading analytics | **Done** — new mlb_model_performance.py + grading hook |
| 5 | MLB Phase 6 all.json publishing | Pending |
| 6 | Orchestrator min-instances cost | Pending (CLAUDE.md warns against changing) |

---

## Commits

| SHA | What |
|---|---|
| `5fb1c731` | game_pk mapping from game_id (initial, incomplete) |
| `709de84f` | Full schema fix: schedule context loader, game_pk/is_home/pitcher_name |
| `f37e1b86` | Pitcher-name matching (OAK→ATH), game_pk guard in exporter |
| `5765dc82` | Punch list #3 (total_runs), #4 (loader scope), #8 (gamedate key) |
| `6b3c41d3` | scraper-gap-backfiller deploy script fix |
| `f589dee0` | MLB /best-bets skip raw prediction write if already exists |
| `c6cb1e5f` | scraper-gap-backfiller lazy import with fallback (deployed) |
| `acc874a8` | Wire MLB post-grading analytics (league_macro, model_performance, signal_health) |

---

## Current System State (2026-04-10 ~18:00 UTC)

### MLB Pipeline — FIRST FULLY OPERATIONAL DAY

| Component | Status |
|---|---|
| `mlb_raw.bp_pitcher_props` | 9 rows for Apr 9 (S518 fix), daily cron running |
| `mlb_predictions.pitcher_strikeouts` | Clean: ~300 rows/day, dedup prevention active |
| `mlb_predictions.signal_best_bets_picks` | 3 rows (Apr 9 manual + Apr 10 automated) |
| `mlb-prediction-worker` | Revision 00045-mgn, `latestRevision=True`, staging tag removed |
| Post-grading analytics | Wired but untested (needs first grading run) |
| scraper-gap-backfiller | Revision 00007-tig, ACTIVE, scheduler ENABLED every 4h |

### Today's MLB Best Bets (Apr 10)

| Pitcher | Rec | Edge | Ultra | game_pk | is_home |
|---|---|---|---|---|---|
| jt_ginn | OVER 3.5 | +1.53 | No | 823643 | Away (ATH@NYM) |
| keider_montero | OVER 3.5 | +1.28 | Yes | 824297 | Home (MIA@DET) |

tomoyuki_sugano (edge 1.21) correctly dropped — now identified as AWAY (COL), edge < 1.25 away floor.

### NBA Pipeline
- Same as Session 518 — auto-halt active, all 4 models BLOCKED
- Regular season ends ~Apr 13 (3 days). No action needed.

---

## Key Discoveries (Carry Forward)

### 1. `load_batch_features` returns PAST game data only
The query has `WHERE pgs.game_date < @game_date`. This means `team_abbr`, `opponent_team_abbr`, and `is_home` from features are from the pitcher's LAST game, not today's. `game_id` was never selected. Today's game context comes from `load_schedule_context()` which queries `mlb_schedule`.

### 2. Pitcher-name normalization for schedule matching
- Features: `jt_ginn` (underscore-separated)
- Schedule: `J.T. Ginn` (full name with dots)
- Normalization: strip all non-alpha, lowercase → `jtginn` matches `jtginn`
- This handles dots, underscores, hyphens, spaces, accents

### 3. Cloud Function import chains are treacherous
`orchestration.parameter_resolver` → `shared.utils.schedule` → `shared.utils.__init__` → `bigquery_client` → ... The entire `shared/` dependency tree must be available or the import fails. Lazy imports with fallbacks are the only practical pattern for Cloud Functions that need repo modules.

### 4. `signal_best_bets_picks` has 47 columns but exporter writes ~27
20+ columns are NBA multi-model concepts (composite_score, consensus_bonus, model_agreement_count, etc.) not applicable to MLB's single-model setup. These stay NULL — not a bug.

---

## Outstanding Work (Prioritized)

### Ready to Build
1. **MLB Phase 6 all.json publishing** — Single-date export exists; need all.json with season record, streak, weekly history for frontend. Medium effort.

### Investigate Before Acting
2. **Orchestrator min-instances cost** — 3 CFs at min-instances=1. CLAUDE.md warns against changing (Feb 23 cold-start incident). Investigate impact before setting to 0.

### Monitor
3. **Post-grading analytics** — Wired but untested. First grading run (tomorrow morning for Apr 10 games) will exercise the new code. Check logs for errors.
4. **scraper-gap-backfiller** — Deployed with lazy import fallback. Parameter resolver won't load in CF runtime, so backfills use simple `{'date': ..., 'gamedate': ...}` params. Fine for date-based scrapers, may not work for game-specific ones.
5. **MLB prediction counts** — Apr 10 should have ~300 rows (loader scope filter now active). If count is much lower, the `COALESCE(bp.bp_over_line, oddsa.oddsa_line) IS NOT NULL` filter may be too aggressive.

### Deferred
6. **MLB weekly auto-retrain** — NBA has weekly-retrain CF. MLB has manual only. Not urgent until more graded data accumulates.
7. **MLB Phase 6 frontend integration** — Requires all.json (item 1 above) + frontend work.

---

## Infrastructure Operations

| Operation | Detail |
|---|---|
| BQ INSERT | jeffrey_springs Apr 9 best bet (manual) |
| BQ DELETE | Dedup pitcher_strikeouts Apr 6 (303 rows), Apr 9 (1200 rows), Apr 10 (627 rows) |
| Cloud Run traffic | mlb-prediction-worker → 00045-mgn (latestRevision=True, staging tag removed) |
| Cloud Function deploy | scraper-gap-backfiller → revision 00007-tig (first working since Jan 24) |
| Cloud Scheduler | scraper-gap-backfiller-trigger recreated with correct OIDC auth |
| Auto-deploys triggered | 8 commits × multiple triggers (mlb-prediction-worker, prediction-worker, etc.) |

---

## Files Changed

| Purpose | File |
|---|---|
| Schedule context loader | `predictions/mlb/pitcher_loader.py` (load_schedule_context, _normalize_pitcher_name) |
| Worker metadata population | `predictions/mlb/worker.py` (game_id, is_home, pitcher_name + dedup prevention) |
| Exporter schema fixes | `ml/signals/mlb/best_bets_exporter.py` (game_pk mapping, guard, REPEATED fields) |
| Supplemental SQL fix | `predictions/mlb/supplemental_loader.py` (total_line → total_runs) |
| Parameter resolver fix | `orchestration/parameter_resolver.py` (date → gamedate) |
| Gap backfiller fix | `orchestration/cloud_functions/scraper_gap_backfiller/main.py` (lazy import + fallback) |
| Gap backfiller deploy | `bin/orchestrators/deploy_scraper_gap_backfiller.sh` (staging dir, entry point) |
| Gap backfiller deps | `orchestration/cloud_functions/scraper_gap_backfiller/requirements.txt` (pyyaml, pytz, gcs) |
| MLB model performance | `ml/analysis/mlb_model_performance.py` (NEW — rolling HR, decay state) |
| MLB grading hook | `data_processors/grading/mlb/main_mlb_grading_service.py` (post-grading analytics) |
