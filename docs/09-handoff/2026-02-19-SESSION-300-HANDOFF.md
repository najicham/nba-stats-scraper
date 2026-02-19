# Session 300-301 Handoff: Pipeline Fixes, UPCG Bug, Historical Odds Backfill, Multi-Book Architecture

**Date:** 2026-02-19
**Focus:** Post-ASB pipeline debugging, three critical bug fixes, historical 12-book odds backfill, multi-book feature architecture design.

## TL;DR

Found and fixed THREE critical pipeline bugs: (1) Phase 4→5 Pub/Sub publish broken (key mismatch), (2) UPCG async boxscores query using wrong column name (`rebounds` → `total_rebounds`), causing ALL 350 players to have NULL days_rest/performance stats, (3) 4 scheduler jobs with wrong Gen1 URLs + missing OIDC tokens. Ran full-season historical odds backfill (103 dates, 911 events) — BQ loader partially complete (5/16 weeks at 12 books). Started architecture discussion for multi-book line features.

## Session 301 Verification Update

**UPCG fix CONFIRMED WORKING:** Feb 19 UPCG now has 345/350 players with `days_rest` and 301/350 with `points_avg_last_5`. The `total_rebounds` fix resolved the async boxscores query.

**BUT predictions still at 6 per model:** Phase 4 hasn't re-run with the new UPCG data. Feature store still shows 153 players with only 6 clean (0 defaults). Phase 4 needs to re-trigger.

**Game lines batch lock persists:** Still only 1/10 games have game lines in BQ for Feb 19. This blocks features 38 (game_total), 41 (spread_magnitude), 42 (implied_team_total) for 9 games.

**Historical backfill:** BQ loader progressed to 5 weeks at 12 books (through Nov 23), then stopped. Needs restart from Nov 30 onward.

**Feb 20:** 9 games scheduled, 0 UPCG data yet — pipeline hasn't started for tomorrow.

## Critical Fixes (3)

### Fix 1: Phase 4→5 Pub/Sub Publish Bug
- **File:** `data_processors/precompute/base/precompute_base.py:622`
- **Bug:** Looked for `data_date`/`end_date` in opts, but actual key is `analysis_date`
- **Impact:** Phase 5 predictions NEVER triggered by Phase 4 orchestrator — only ran via backup scheduler at 4 PM ET
- **Fix:** `self.opts.get('analysis_date') or self.opts.get('data_date') or self.opts.get('end_date')`

### Fix 2: UPCG Async Boxscores — Wrong Column Name
- **File:** `data_processors/analytics/upcoming_player_game_context/async_upcoming_player_game_context_processor.py:445`
- **Bug:** Query used `rebounds` but `nbac_gamebook_player_stats` has `total_rebounds`. BQ returned 400 error, silently caught, ALL players got empty historical DataFrames.
- **Impact:** ALL 350 players had `days_rest=NULL`, `points_avg_last_5=NULL`, `games_in_last_7_days=0`. Every fatigue/performance feature was empty. Only IND@WAS got 6 predictions because those players passed quality gates on other features alone.
- **Fix:** `rebounds` → `total_rebounds as rebounds`
- **Note:** The sync version at `loaders/game_data_loaders.py:213` correctly uses `(pgs.offensive_rebounds + pgs.defensive_rebounds) as rebounds` against `player_game_summary`. The async version incorrectly queries `nba_raw.nbac_gamebook_player_stats` with wrong column name.

### Fix 3: 4 PERMISSION_DENIED Scheduler Jobs
| Job | Issue | Fix |
|-----|-------|-----|
| `daily-reconciliation` | Gen1 URL + no OIDC | Updated to `reconcile-f7p3g7f6ya-wl.a.run.app` + OIDC |
| `validate-freshness-check` | Gen1 URL + no OIDC | Updated to `validate-freshness-f7p3g7f6ya-wl.a.run.app` + OIDC |
| `nba-grading-gap-detector` | Gen1 URL + no OIDC | Updated to `grading-gap-detector-f7p3g7f6ya-wl.a.run.app` + OIDC |
| `validation-pre-game-final` | Missing OIDC only | Added OIDC token |

Service account: `756957797294-compute@developer.gserviceaccount.com`. Both `daily-reconciliation` and `grading-gap-detector` test-run verified working.

Note: `daily-reconciliation` has `ModuleNotFoundError: No module named 'shared'` for Slack alerts (non-blocking, needs separate fix).

## Historical Odds Backfill (12-Book)

### Status
- **GCS scrape:** COMPLETE — 103 dates (Nov 2 → Feb 12), 931 events, 911 props scraped, 20 failed (97.8%)
- **BQ loader:** PARTIALLY COMPLETE — stopped after ~5 weeks. Needs restart from Nov 30.
- **Progress (Session 301 verified):** 5 weeks at 12 books, rest still at 2.

```
Week         | Books | Players | Lines   | Status
2025-10-26   |  12   |  142    |  8,987  | ✅ loaded
2025-11-02   |  12   |  284    | 11,967  | ✅ loaded
2025-11-09   |  12   |  279    | 10,372  | ✅ loaded
2025-11-16   |  12   |  274    | 11,739  | ✅ loaded
2025-11-23   |  12   |  269    |  4,924  | ✅ loaded
2025-11-30   |   2   |  274    |  4,896  | ❌ needs restart
2025-12-07   |   2   |  251    |  2,553  | ❌ needs restart
...
2026-01-25   |   2   |  220    |  3,170  | ❌ needs restart
2026-02-01   |   2   |  231    |  4,798  | ❌ needs restart
2026-02-08   |  12   |  245    | 40,949  | ✅ already had 12 books (live)
```

### Restart BQ loader (pick up from Nov 30):
```bash
# Restart from where it stopped:
PYTHONPATH=. python scripts/backfill_odds_api_props.py \
  --start-date 2025-11-30 --end-date 2026-02-07 --historical

# Verify coverage:
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT DATE_TRUNC(game_date, WEEK) as week,
  COUNT(DISTINCT bookmaker) as books,
  COUNT(DISTINCT player_lookup) as players,
  COUNT(*) as lines
FROM nba_raw.odds_api_player_points_props
WHERE game_date >= '2025-11-01' AND points_line IS NOT NULL
GROUP BY 1 ORDER BY 1"
```

### Script created this session:
`scripts/backfill_historical_props_direct.py` — lean direct-API backfill script that calls Odds API without scraper infrastructure overhead (no SES, no subprocess). 10x faster. Uses `requests` + `google-cloud-storage` directly.

## Pipeline State (Feb 19, verified Session 301)

| Component | Status | Details |
|-----------|--------|---------|
| UPCG Fix | ✅ VERIFIED | 345/350 players have `days_rest`, 301/350 have `points_avg_last_5` |
| Feature Store | ⚠️ STALE | Still 153 players, 6 clean — Phase 4 hasn't re-run with updated UPCG |
| Predictions | ⚠️ | Still only 6 per model (12 systems × 6 = 72 total) |
| Game Lines BQ | ⚠️ | Still 1/10 games — batch lock persists |
| Phase 4→5 Fix | ✅ Deployed | `analysis_date` key fix ready for next Phase 4 run |
| Schedulers | ✅ Fixed | All 4 jobs updated with Gen2 URLs + OIDC |
| Feb 19 Grading | ❌ | No grading data yet (games tonight, not yet played) |

**Blocking issue:** Phase 4 needs to re-run to pick up the fixed UPCG data. AND game lines need to load for all 10 games (batch lock). Games are tonight ~7 PM ET — there's time if the next scraper cycle resolves the batch lock.

**To force re-trigger Phase 4 for Feb 19:**
```bash
# Option 1: Manually trigger Phase 3→4 orchestrator
gcloud pubsub topics publish nba-phase3-analytics-complete \
  --project=nba-props-platform \
  --message='{"game_date": "2026-02-19", "source": "manual_retrigger"}'

# Option 2: Wait for next scheduled scraper cycle → Phase 2 → 3 → 4 → 5 chain
```

## Commits This Session

```
fc663f0b fix: UPCG async boxscores query — rebounds column not found in raw table
4ecc9613 docs: Session 300 handoff
27c173cd fix: Phase 4→5 publish bug — use analysis_date key, add direct backfill script
```

## Files Changed

| File | Change |
|------|--------|
| `data_processors/precompute/base/precompute_base.py` | Phase 4→5 publish key fix |
| `data_processors/analytics/upcoming_player_game_context/async_upcoming_player_game_context_processor.py` | `rebounds` → `total_rebounds as rebounds` |
| `scripts/backfill_historical_props_direct.py` | NEW: Direct API backfill script |
| `scripts/backfill_historical_props.py` | Events timeout 120→300s |

## Next Session Priorities

### P0: URGENT — Get Feb 19 Predictions Working Before Games Tonight
UPCG data is correct but Phase 4/5 hasn't re-run. Two blockers:

1. **Force Phase 4 re-trigger** — manually publish to `nba-phase3-analytics-complete` or wait for next scraper cycle
2. **Game lines batch lock** — 9/10 games missing game lines in BQ. Either fix the batch handler lock or manually re-trigger Phase 2 for those GCS files

```bash
# Check if pipeline self-recovered:
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT system_id, COUNT(*) as total
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-02-19' AND system_id = 'catboost_v9'
GROUP BY 1"
# Expected: should be >>6 if Phase 4/5 re-ran

# Check game lines:
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT COUNT(DISTINCT game_id) as games FROM nba_raw.odds_api_game_lines
WHERE game_date = '2026-02-19'"
# Expected: should be 10 (currently 1)
```

### P1: Restart Historical Odds BQ Load
BQ loader stopped at Nov 23. Restart from Nov 30:
```bash
PYTHONPATH=. python scripts/backfill_odds_api_props.py \
  --start-date 2025-11-30 --end-date 2026-02-07 --historical
```

### P2: Investigate Game Lines Batch Lock (Root Cause)
`data_processors/raw/handlers/oddsapi_batch_handler.py` has date-level locking. When one instance processes 1 game, all other games for that date are rejected with "already being processed". Should use per-game locking.

### P3: Multi-Book Line Feature Architecture (see below)

### P4: Retrain Shadow Models
Wait for 2-3 days of post-ASB graded data. V12, Q43, Q45 all stale/BLOCKED.

### P5: Grade Feb 19 Games
After tonight's games finish, check grading and fresh model performance:
```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform "
SELECT game_date, COUNT(*) as graded,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) as hit_rate,
  COUNTIF(predicted_margin >= 3) as edge3_n,
  ROUND(100.0 * COUNTIF(predicted_margin >= 3 AND prediction_correct = TRUE) /
    NULLIF(COUNTIF(predicted_margin >= 3), 0), 1) as edge3_hr
FROM nba_predictions.prediction_accuracy
WHERE game_date = '2026-02-19' AND system_id = 'catboost_v9'
GROUP BY 1"
```

## Multi-Book Line Feature Architecture (Design Discussion)

### What We Have Now
- **Raw data:** `nba_raw.odds_api_player_points_props` — one row per (player, bookmaker, snapshot_timestamp)
- **Columns:** `bookmaker`, `points_line`, `over_price`, `under_price`, `over_price_american`, `under_price_american`, `snapshot_timestamp`, `bookmaker_last_update`
- **Coverage:** 12 sportsbooks (draftkings, fanduel, betmgm, williamhill_us, betrivers, bovada, espnbet, hardrockbet, betonlineag, fliff, betparx, ballybet)
- **Current feature:** f50 (`multi_book_line_std`) = STDDEV of points_line across books. Requires 2+ books.

### What the Data Shows (Nov 2 example)
```
SGA:          26.5 - 32.5 (6.0 spread, std=1.54) — Bovada outlier at 26.5
Devin Booker: 24.5 - 29.5 (5.0 spread, std=1.38)
Victor Wemb:  23.5 - 28.5 (5.0 spread, std=1.47)
```
Most books cluster around a consensus. 1-2 outlier books create the spread. Bovada frequently deviates.

### Key Finding: More Books ≠ More Players
All 12 books offer props for the **same ~10-12 starters/key rotation players** per game. The value is **price diversity** (12 opinions on each player's line), not more player coverage.

### Proposed Features to Study

**Category 1: Cross-Book Disagreement (expand f50)**
```sql
-- Already have: STDDEV across books
-- NEW ideas:
-- f_line_range: MAX(line) - MIN(line) across books (more intuitive than std)
-- f_outlier_count: How many books deviate >1.0 from median
-- f_our_line_vs_consensus: |our_prediction - consensus_median| (true edge measure)
-- f_book_agreement_ratio: books within ±0.5 of median / total books
```

**Category 2: Sharp vs Soft Book Signals**
```sql
-- Identify "sharp" books (Pinnacle-adjacent: bovada, betonlineag)
-- vs "soft" retail books (DraftKings, FanDuel, BetMGM)
-- f_sharp_soft_delta: sharp_book_avg - soft_book_avg
--   Positive = sharps think OVER, negative = sharps think UNDER
-- f_sharp_is_outlier: 1 if sharp book is >1.5 from median (sharp money signal)
```

**Category 3: Line Movement (requires multiple snapshots per game)**
```sql
-- Currently we have 1-2 snapshots per game (historical = 1, live = multiple)
-- Need: opening line (earliest snapshot) vs closing line (latest pre-game)
-- f_line_movement: closing - opening (positive = line moved up)
-- f_consensus_movement: change in median across books over time
-- f_movement_velocity: how fast did the line move? (pts / hour)
-- NOTE: Historical backfill only has 1 snapshot (18:00 UTC).
-- Live scraper gets multiple. Future backfill at different times could help.
```

**Category 4: Book-Specific Edge Signals**
```sql
-- Track which book's line best predicts actual points
-- f_best_book_line: line from the historically most accurate book for this player
-- f_dk_fanduel_spread: |DK_line - FanDuel_line| (two biggest markets disagreeing)
```

**Category 5: Juice/Vig Signals (over_price + under_price)**
```sql
-- We have over_price_american and under_price_american per book
-- f_avg_over_juice: average over price across books (negative = bookmakers lean UNDER)
-- f_juice_asymmetry: abs(avg_over_price) - abs(avg_under_price)
--   Books charge more for the side they expect to hit
-- f_max_over_price: best available over price (best odds for OVER bettors)
-- f_best_line_over: highest line where over price is still favorable
```

### Storage Architecture Options

**Option A: Precomputed Summary Table (recommended)**
```sql
-- New table: nba_predictions.player_line_summary
-- One row per (player_lookup, game_date)
-- Computed by Phase 4 precompute processor
CREATE TABLE nba_predictions.player_line_summary (
  player_lookup STRING,
  game_date DATE,

  -- Consensus
  consensus_line FLOAT64,        -- median across books
  line_std FLOAT64,              -- STDDEV (current f50)
  line_range FLOAT64,            -- max - min
  book_count INT64,              -- how many books offered

  -- Sharp vs Soft
  sharp_book_avg FLOAT64,        -- bovada, betonlineag avg
  soft_book_avg FLOAT64,         -- DK, FanDuel, BetMGM avg
  sharp_soft_delta FLOAT64,      -- sharp - soft

  -- Juice
  avg_over_juice FLOAT64,        -- avg over price (american)
  avg_under_juice FLOAT64,       -- avg under price (american)
  juice_asymmetry FLOAT64,       -- which side books favor

  -- Movement (when multi-snapshot available)
  opening_line FLOAT64,          -- earliest snapshot consensus
  closing_line FLOAT64,          -- latest snapshot consensus
  line_movement FLOAT64,         -- closing - opening

  -- Metadata
  computed_at TIMESTAMP,
  snapshot_count INT64            -- how many snapshots we had
);
```

**Option B: Keep in feature store only**
Just add more `feature_N_value` columns to `ml_feature_store_v2`. Simpler but less queryable for analysis.

**Recommendation:** Option A for research + Option B for production features. Build the summary table first, study patterns, then promote the best signals to feature store columns.

### Research Queries to Run First
```sql
-- 1. Does high line_std correlate with model accuracy?
WITH line_data AS (
  SELECT player_lookup, game_date,
    STDDEV(points_line) as line_std
  FROM nba_raw.odds_api_player_points_props
  WHERE points_line IS NOT NULL
  GROUP BY 1, 2
  HAVING COUNT(DISTINCT bookmaker) >= 5
)
SELECT
  CASE WHEN ld.line_std > 1.5 THEN 'high_disagreement'
       WHEN ld.line_std > 0.5 THEN 'medium'
       ELSE 'low_disagreement' END as disagreement,
  COUNT(*) as n,
  ROUND(100.0 * COUNTIF(pa.bet_result = 'WIN') / COUNT(*), 1) as hit_rate
FROM line_data ld
JOIN nba_predictions.prediction_accuracy pa
  ON ld.player_lookup = pa.player_lookup AND ld.game_date = pa.game_date
WHERE pa.system_id = 'catboost_v9'
GROUP BY 1 ORDER BY 1;

-- 2. Sharp vs soft book signal
-- 3. Does bovada-outlier predict direction?
-- 4. Juice asymmetry vs actual result
```

### Implementation Order
1. **Now:** Verify backfill loaded, run research queries
2. **Phase 1:** Build `player_line_summary` table + Phase 4 processor
3. **Phase 2:** Run backtest — which features improve hit rate at edge 3+?
4. **Phase 3:** Add best features to feature store as f55, f56, etc.
5. **Phase 4:** Retrain model with new features

## Infrastructure Notes

- **UPCG has two code paths:** sync (`loaders/game_data_loaders.py` queries `player_game_summary`) and async (`async_upcoming_player_game_context_processor.py` queries `nbac_gamebook_player_stats`). The async path is what runs in production (Cloud Run). They should be aligned.
- **Game lines batch lock:** Date-level lock in `oddsapi_batch_handler` means one instance processing 1 game locks out all other games for that date. Should be per-game locking.
- **Historical backfill has 1 snapshot per game (18:00 UTC).** Line movement features need multiple snapshots. Live scraper captures multiple. Consider running a second historical backfill at 04:00 UTC to get opening vs closing lines.
- **Backfill used ~10K API quota out of 4.99M.** Plenty of room for additional snapshot times.
