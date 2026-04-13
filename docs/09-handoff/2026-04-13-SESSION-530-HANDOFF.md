# Session 530 Handoff — Per-pitch MLB pipeline + advanced arsenal panel

**Date:** 2026-04-13
**Focus:** Daily per-pitch MLB Stats API ingestion, true per-pitch-type arsenal metrics, advanced arsenal panel (putaway / velo fade / concentration), MLB signal correlation analysis
**Commits:**
  - `nba-stats-scraper`: `de8d9312`, `12a6b126` (2 commits) + Session 530 analysis
  - `props-platform-web`: `85fa946` (1 commit)

---

## TL;DR

Session 529 shipped the pitch-arsenal panel but with a caveat: `whiff_rate` and `avg_velocity` were pitcher-level (same value for every pitch type). This session closed that gap by building the per-pitch ingestion path from scratch — new daily scraper hitting MLB Stats API `/game/{pk}/feed/live`, new `mlb_raw.mlb_game_feed_pitches` table (one row per pitch), new processor, new scheduler at 3:15 AM ET. The `pitcher_pitch_arsenal_latest` view now returns true per-pitch-type metrics for any pitcher who's thrown in the last 5 starts (137 active pitchers on launch, 760 older pitchers fall back to statcast). Also added a second arsenal section to the UI — putaway pitch, late-game velo fade, arsenal concentration — all live on playerprops.io. Part B was an honest investigation: with only N=57 graded MLB predictions since Apr 1, signal correlation analysis is statistically premature. Built the reusable analysis tool for monthly re-evaluation.

---

## What Was Done

### 1. Per-pitch ingestion pipeline (commit `de8d9312`)

**New scraper:** `scrapers/mlb/mlbstatsapi/mlb_game_feed_daily.py`
- Iterates schedule for target date, fetches every Final game's `/api/v1.1/game/{pk}/feed/live`
- Emits one row per pitch with physics (velocity, spin, extension, zone) + `details.code`-based result classification (ball / called strike / swinging strike / foul / in-play / swing / whiff / chase / in-zone)
- Output: `mlb-stats-api/game-feed-daily/{date}/{timestamp}.json`
- Chose MLB Stats API (not Baseball Savant / pybaseball) because: available immediately after games end, no 4-12h Statcast indexing lag, richer play-event classification, no external dependency.

**New BQ table:** `mlb_raw.mlb_game_feed_pitches` — partitioned by `game_date`, clustered by `pitcher_lookup + pitch_type_code`. Dedup key `(game_pk, at_bat_index, pitch_number)`.

**New processor:** `data_processors/raw/mlb/mlb_game_feed_processor.py` — `MlbGameFeedPitchesProcessor`. APPEND with scoped DELETE per `(game_date, game_pk)` before insert. `--force` flag for backfills. Wired into `PROCESSOR_REGISTRY` at `mlb-stats-api/game-feed-daily`.

**New scheduler:** `mlb-game-feed-daily` at 3:15 AM ET (15 min after `mlb-statcast-daily`), scraper=`mlb_game_feed_daily`, date=`YESTERDAY`. Created via `./bin/schedulers/setup_mlb_schedulers.sh`. State: ENABLED.

**Scraper registry:** added `mlb_game_feed_daily` to `scrapers/registry.py` + `scrapers/mlb/mlbstatsapi/__init__.py`.

**Backfill:** Mar 28 – Apr 12 (16 dates, ~64K pitches total, 299 distinct pitchers). All 14 backfill dates processed 0 errors.

### 2. Arsenal view rewrite (commit `de8d9312`)

`mlb_analytics.pitcher_pitch_arsenal_latest` now has two-source logic:
- **Preferred** `source='game_feed_pitches'`: true per-pitch-type velocity (AVG over actual pitches of that type) and whiff rate (`whiffs/swings` on that type). 137 pitchers on launch.
- **Fallback** `source='statcast_pitcher_daily'`: pitcher-level metrics applied to each pitch type (old behavior). 760 older pitchers. Used when pitcher has no rows in the per-pitch table.

View output contract is unchanged — same columns, same shape. Exporter and frontend needed no changes for this upgrade. Session 529's `_fetch_pitch_arsenal` method and `PitcherPitchType` interface still work as-is.

Example — Taijuan Walker:
- Before (Session 529): every pitch showed whiff=25.4%, velo=93.0 (pitcher-level average)
- After (Session 530): Cutter 33.3% whiff / 86.0 mph · Four-seam 0% whiff / 90.8 mph · Splitter 6.3% / 86.2 · Sinker 16.7% / 91.3 — real per-pitch-type stats

### 3. Advanced arsenal panel (commit `12a6b126` + web `85fa946`)

**New view:** `mlb_analytics.pitcher_advanced_arsenal_latest` — one row per pitcher with three families of metrics:

| Metric | Window | Notes |
|---|---|---|
| `putaway_pitch_code/desc/whiff_rate/usage_pct_on_2k/2k_pitches` | L3 starts, 2-strike counts | Most-thrown 2-strike pitch + its whiff rate (whiffs/swings). Whiff rate NULL when fewer than 5 swings. |
| `velo_inning_1/inning_5_plus/fade_mph` | L5 starts, fastballs only (FF/SI/FC) | NULL when fewer than 5 pitches in either bucket. Handles relievers cleanly. |
| `arsenal_concentration/effective_pitch_count` | L5 starts, all pitch types | Herfindahl (0–1, higher = concentrated). Effective = `1/H`. NULL if < 30 total pitches. |

**Exporter update:** `_fetch_advanced_arsenal()` added to `mlb_pitcher_exporter.py`. Profile JSON now has `advanced_arsenal` object (or `null`).

**Frontend:** New `AdvancedArsenal` component below the pitch-mix panel. Three sub-sections (putaway / late-game velo / arsenal spread), each hides independently when its sub-metric is NULL. Label thresholds:
- Whiff color: ≥25% positive, 15-25% neutral, <15% muted
- Fade: ≥1.5 mph strong, 0.5-1.5 modest, ~0 "Holds velo", negative "Builds"
- Concentration: H>0.40 Concentrated, 0.25-0.40 Balanced, <0.25 Diverse

**Re-exported all 299 pitcher profiles** locally using current code; new JSON is live in GCS before auto-deploy of `phase6-export` Cloud Function completes.

### 4. MLB signal correlation analysis (Part B)

**Goal:** decide whether per-pitch metrics (putaway whiff, velo fade) should become MLB production signals.

**Tool:** `scripts/mlb/analysis/arsenal_signal_correlation.py` — reusable, parameterized by `--since`. For each graded prediction, computes as-of arsenal metrics using *only* per-pitch data prior to the pick date (no leakage), then stratifies hit rate by metric tier.

**Results on current data (N=57 graded since Apr 1):**

Putaway whiff tier × recommendation:
- OVER weak: 55.6% (N=18) · good: 50.0% (N=10) · elite: 37.5% (N=8)
- UNDER weak: 75.0% (N=8) · good: 66.7% (N=6) · elite: 50.0% (N=4)

Velo fade tier × recommendation: all OVER buckets 46-56% (N=4-15), UNDER buckets 0-83% with heavy N=1.

**Conclusion:** inconclusive at this sample size. The patterns are also counterintuitive (elite putaway correlating with *lower* HR) which reinforces they're noise. Need ~300 graded picks (~50 per bucket × 6 buckets) for reliable stratified analysis. Re-run monthly.

**Did NOT add signal classes.** Writing `BaseMLBSignal` subclasses for patterns that don't show up in data is speculative infrastructure. Better to wait until the data justifies.

---

## System State

### BigQuery
- `mlb_raw.mlb_game_feed_pitches` — **new**, ~64K rows across 16 dates (Mar 28 – Apr 12 2026). Partitioned by `game_date`, clustered by `pitcher_lookup + pitch_type_code`.
- `mlb_analytics.pitcher_pitch_arsenal_latest` — **rewritten**, feed-preferred / statcast-fallback. Contract unchanged.
- `mlb_analytics.pitcher_advanced_arsenal_latest` — **new**, one row per pitcher with advanced metrics.

### GCS API
- `v1/mlb/pitchers/{pitcher_lookup}.json` — now includes `advanced_arsenal` object (may be `null` for old / inactive pitchers). 299 files re-uploaded this session.
- `v1/mlb/pitchers/leaderboard.json` — schema unchanged.

### Cloud Run
- `nba-phase2-raw-processors` — auto-deployed `de8d9312` (dispatches game_feed_daily processor).
- `mlb-phase1-scrapers` — manually deployed (revision `mlb-phase1-scrapers-00015-r5p`, traffic=latest). New scraper `mlb_game_feed_daily` registered.

### Cloud Functions (auto-deployed on push)
- `phase6-export` — pending auto-deploy of `12a6b126`. Until it cycles, daily exports via CF will *not* include `advanced_arsenal` — but we re-exported manually so GCS is already current.

### Daily pipeline (live as of Session 530)
- 8:05 AM ET: `mlb-statcast-daily` scraper → GCS (existing)
- 3:15 AM ET: **`mlb-game-feed-daily` scraper** → GCS → `nba-phase2-raw-processors` → `mlb_raw.mlb_game_feed_pitches` *(new)*
- 10:45 AM / 1 PM ET: pitcher export schedulers re-export profiles with fresh arsenal + advanced metrics

---

## What To Work On Next

### Option A: Historical backfill for 2025 season (unlocks training + analysis)

The per-pitch pipeline is live for 2026+. To enable proper signal eval and future model retraining, backfill 2025 season (~2430 games × 1 HTTP call each, ~2-3 hours of runtime). Workflow:

1. Write a date-range variant of `/tmp/backfill_mlb_game_feed.sh`
2. Run for every date 2025-03-27 through 2025-10-31
3. Be mindful of rate limits — add sleep between dates
4. Result: ~550K pitch rows, enabling full-season analysis and feature engineering

With 2025 data loaded, `pitcher_pitch_arsenal_latest` would return real per-type metrics for nearly every pitcher, not just recent starters.

### Option B: Advanced arsenal enrichment — expected K% by arsenal

Once historical data exists, compute "expected K% if pitcher's arsenal were faced by league-average batters" as a pitcher-quality metric. Join arsenal composition to league-wide whiff-by-pitch-type baselines. Surfaces as a site stat and potentially a model feature.

### Option C: Re-run signal correlation monthly

Monthly cron or manual: `python scripts/mlb/analysis/arsenal_signal_correlation.py`. When N reaches 300+ and a tier shows persistent >5pp HR deviation, promote to a shadow signal in `ml/signals/mlb/signals.py`.

### Option D: NBA off-season work or assists/rebounds models

Unrelated to MLB but both still viable. Assists/rebounds data clock now 1 week in; still need 3+ weeks before dedicated models are trainable.

**Recommend A first** — unblocks everything else and is the biggest force multiplier.

---

## Files Changed

### `nba-stats-scraper`

| File | Change |
|---|---|
| `scrapers/mlb/mlbstatsapi/mlb_game_feed_daily.py` | **New** — daily per-pitch scraper |
| `scrapers/mlb/mlbstatsapi/__init__.py` | Export `MlbGameFeedDailyScraper` |
| `scrapers/registry.py` | Register `mlb_game_feed_daily` |
| `data_processors/raw/mlb/mlb_game_feed_processor.py` | **New** — `MlbGameFeedPitchesProcessor` |
| `data_processors/raw/mlb/__init__.py` | Export processor |
| `data_processors/raw/main_processor_service.py` | `PROCESSOR_REGISTRY` entry for `mlb-stats-api/game-feed-daily` |
| `schemas/bigquery/mlb_raw/mlb_game_feed_pitches_tables.sql` | **New** — partitioned per-pitch table |
| `schemas/bigquery/mlb_analytics/pitcher_pitch_arsenal_tables.sql` | Rewritten: feed-preferred, statcast-fallback |
| `schemas/bigquery/mlb_analytics/pitcher_advanced_arsenal_tables.sql` | **New** — putaway / velo fade / concentration |
| `data_processors/publishing/mlb/mlb_pitcher_exporter.py` | `_fetch_advanced_arsenal()` + `advanced_arsenal` on profile |
| `bin/schedulers/setup_mlb_schedulers.sh` | Added `mlb-game-feed-daily` cron entry |
| `scripts/mlb/analysis/arsenal_signal_correlation.py` | **New** — reusable signal correlation tool |

### `props-platform-web`

| File | Change |
|---|---|
| `src/lib/pitchers-types.ts` | `PitcherAdvancedArsenal` + sub-types; `advanced_arsenal` field on profile |
| `src/app/pitchers/[slug]/page.tsx` | `AdvancedArsenal` component + insertion below `PitchArsenal` |

---

## Lessons / Guardrails

- **MLB Stats API `/feed/live` is the right source for per-pitch**, not Baseball Savant via pybaseball. Immediate availability, richer classification, no cloud-IP blocking. Use it for anything daily/near-realtime.
- **`details.code` classification is canonical** — see the `_BALL_CODES` / `_SWINGING_STRIKE_CODES` / etc. frozensets in `mlb_game_feed_daily.py`. Don't parse `details.description` strings. "Swinging Strike (Blocked)" has code `W` / `Q`, not `S`.
- **Lookup format split persists** (`pitcher_game_summary` uses underscores, per-pitch data does not). The arsenal view + `_fetch_pitch_arsenal`/`_fetch_advanced_arsenal` exporter methods both normalize by stripping underscores. When joining any per-pitch table to anything else, remember the normalization step.
- **`BigQuery ARRAY_AGG(STRUCT ORDER BY ... LIMIT 1)[OFFSET(0)]` inside a GROUP BY is invalid** — "Multi-level aggregation requires the enclosing aggregate function to have one or more GROUP BY modifiers". Use `ROW_NUMBER()` + a `WHERE rn = 1` filter instead.
- **Don't build signal infrastructure before data validates the signal.** Adding 3 shadow `BaseMLBSignal` subclasses "just in case" would be ~100 lines of speculative code. The correlation analysis on N=57 said "inconclusive"; the right response was to package the analysis, not the signals.
- **The `scraper_cost_metrics` BQ table doesn't exist** in this project. Scraper runs emit 404 errors from `bigquery_batch_writer` on every run. Harmless but noisy — would be nice to either create the table or silence the write path.

---

## Memory Updates

Worth storing:
- `mlb_raw.mlb_game_feed_pitches` is the source of truth for per-pitch data (dedup key: `game_pk, at_bat_index, pitch_number`)
- `mlb_analytics.pitcher_advanced_arsenal_latest` exists — one row per pitcher, three metric families
- Per-pitch data only exists for 2026-03-28 onward; historical backfill needed for training/eval
- MLB signal correlation analysis tool: `scripts/mlb/analysis/arsenal_signal_correlation.py` — re-run as data accumulates
- Arsenal view dual-source: `source='game_feed_pitches'` (true per-type) OR `'statcast_pitcher_daily'` (pitcher-level fallback) — column tells you which

---

## Model Recommendation for Next Session

**Sonnet.** If continuing with Option A (2025 historical backfill), all decisions are made — it's just a long-running loop. If pivoting to Option B or C, Sonnet handles those well too. Save Opus for the eventual model retraining once historical per-pitch data is in place.
