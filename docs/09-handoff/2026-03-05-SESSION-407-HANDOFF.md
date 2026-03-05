# Session 407 Handoff — Verification + Feature Experiment

**Date:** 2026-03-05
**Type:** Verification, analysis, planning
**Algorithm:** `v406_scraper_fixes_combo_edge3` (unchanged)

---

## What This Session Did

### 1. Verified All Session 406 Scraper Fixes in BQ

All 9 scraper sources confirmed with Mar 4 data in BQ:

| Source | Records | Status |
|--------|---------|--------|
| NumberFire | 63 unique valid | WORKING |
| VSiN | 14 games | WORKING |
| NBA Tracking | 1638 players | WORKING |
| TeamRankings | 450 rows | WORKING (TODAY bug fixed) |
| FantasyPros | 4065 rows, 0 valid pts | STILL BROKEN (DFS FPTS) |
| Dimers | 6 unique valid pts | LIMITED (top scorers only) |
| RotoWire | 14400 rows | WORKING (play_probability added) |
| Covers | 1140 rows | WORKING |
| Hashtag DVP | 510 rows | WORKING |

### 2. Fixed Two Bugs

- **TeamRankings `TODAY` literal**: Scraper missing `set_additional_opts()` — GCS path had `/TODAY/` instead of date. Fixed.
- **RotoWire `play_probability`**: BQ schema had no column for the new field. Added INTEGER column + updated Phase 2 processor.

### 3. Evaluated Negative Filter Performance

Filters add **+13.7pp** value (52.2% unfiltered → 65.9% post-filter). Top rejectors on Mar 4:
- `line_jumped_under`: 3 rejections
- `bench_under`: 2
- `line_dropped_under`: 2

**Conclusion:** Filters are working well. Don't remove.

### 4. Ran Feature Experiment: NBA Tracking Stats

5-seed CatBoost experiment adding season-level tracking features (usage_pct, ppg, pct_pts, fga) to V12_noveg:

| Metric | Base | + Tracking | Delta |
|--------|------|------------|-------|
| MAE | 5.228 | 5.209 | -0.019 |
| HR 3+ | 53.6% | 53.9% | +0.3pp (noise) |
| HR 5+ | 67.4% | 66.0% | -1.5pp (noise) |

**Conclusion:** Season-level static features don't help. Need per-game features or daily-varying data (projections, sharp money).

### 5. Assessed Backfill Feasibility

- **Can't backfill**: Projections (live pages only), VSiN (live only)
- **Can backfill**: TeamRankings (one scrape = full season), NBA Tracking (nba_api season data)
- **Per-game tracking** (touches, drives) blocked — NBA.com rate limits cloud IPs

---

## Shadow Signals — NOT YET VERIFIED

Pipeline hadn't run for Mar 5 at time of session. Expected results when it does:

| Signal | Expected | Dependency |
|--------|----------|------------|
| projection_consensus | ~3 fires/day | NF (63) + Dimers (6) overlap |
| sharp_money | 1-4 fires/day | VSiN 14 games |
| dvp_favorable | 1-2 fires/day | DVP rank computed |
| combo_3way/he_ms | Resume firing | MIN_EDGE 3.0 |
| predicted_pace | Continue (2 fires Mar 4) | TeamRankings |

---

## Fleet Health (as of Mar 2)

- 4 HEALTHY models: lgbm_train1201, catboost_60d_vw025, catboost_v16_noveg (×2)
- 2 DEGRADING: lgbm_train1102, catboost_train0110
- 15 BLOCKED (mostly quantile + legacy)
- Best bets: 14d 8-4 (66.7%), 30d 13-12 (52.0%)
- Volume: 2-5 picks/day

---

## Code Changes

```
fix: TeamRankings TODAY literal + RotoWire play_probability in Phase 2
  scrapers/external/teamrankings_stats.py     — added set_additional_opts()
  data_processors/raw/external/rotowire_lineups_processor.py — added play_probability field
```

BQ schema change (not in code): `nba_raw.rotowire_lineups` gained `play_probability INTEGER` column.

---

## Session 408 Plan — Experiment Feature Table + Signal Verification

### Priority 1: Verify Shadow Signals (5 min)
```sql
-- Run after pipeline completes (~10 AM ET)
SELECT signal_tag, COUNT(*) FROM nba_predictions.signal_best_bets_picks,
UNNEST(signal_tags) AS signal_tag
WHERE game_date = '2026-03-05'
AND signal_tag IN ('projection_consensus_over', 'sharp_money_over', 'dvp_favorable_over', 'combo_3way')
GROUP BY 1
```

### Priority 2: Create Experiment Feature Table (30 min)

**Goal:** A sandbox BQ table (`ml_feature_store_experiment`) where we can test new features without touching production. The `/model-experiment` skill joins this table during training.

**Design:**
```sql
CREATE TABLE nba_predictions.ml_feature_store_experiment (
  player_lookup STRING NOT NULL,
  game_date DATE NOT NULL,
  experiment_id STRING NOT NULL,
  -- 20 flexible feature slots
  exp_feature_0_name STRING, exp_feature_0_value FLOAT64,
  exp_feature_1_name STRING, exp_feature_1_value FLOAT64,
  ...
  exp_feature_19_name STRING, exp_feature_19_value FLOAT64,
  created_at TIMESTAMP
) PARTITION BY game_date CLUSTER BY player_lookup, experiment_id;
```

**Populate with:**
1. Season-level NBA Tracking (touches, drives, catch_shoot_pct, pull_up_pct, paint_touches, usage_pct) — static per player
2. TeamRankings team pace/efficiency — static per team
3. DVP rank normalized — changes daily
4. Sharp money divergence (handle% - ticket%) — changes daily (needs accumulation)
5. Projection consensus delta (avg projection - line) — changes daily (needs accumulation)

**Key insight:** Static features already tested = WASH. The features with real potential change DAILY (projection delta, sharp money). These need 30+ days of accumulation before we can test.

### Priority 3: Backfill Script for Experiment Features (20 min)

Write `bin/backfill_experiment_features.py`:
- Reads from raw scraper tables + nba_api
- Computes all 12 candidate features
- Writes to `ml_feature_store_experiment`
- Can be run daily after Phase 2 to keep features fresh

### Priority 4: Modify `/model-experiment` for Experiment Features (15 min)

Add `--experiment-features EXPERIMENT_ID` flag to quick_retrain.py:
- Joins `ml_feature_store_experiment` with main feature store
- Appends experiment features to the training matrix
- Standard 5-seed evaluation

---

## Don't Do

- Don't add features to production `ml_feature_store_v2` — use experiment table
- Don't promote shadow signals yet — need N >= 30 graded
- Don't retrain models — 12 in fleet, focus on evaluation
- Don't remove negative filters — they add +13.7pp value
- Don't try to fix `minutes_surge_over` — permanently blocked

---

## Key Metrics to Track

| Metric | Current | Target |
|--------|---------|--------|
| Pick volume | 2-5/day | 4-8/day |
| Best bets HR 14d | 66.7% | > 60% |
| Shadow signals firing | 1 (predicted_pace) | 5+ |
| Experiment features tested | 4 (all WASH) | 12 |
| Days of daily-varying data | 1 | 30+ for testing |
