# Session 434 Handoff — Critical Bug Fixes + Signal Tuning + ESPN Scraper

**Date:** 2026-03-07
**Session:** 434
**Status:** Complete. 3 bug fixes, 3 signal changes, 1 new scraper, 1 scheduler job.

---

## What Was Done

### 1. CRITICAL BUG: Worker `required_default_count` Fix

**Root cause:** Worker's zero-tolerance quality gate used `default_feature_count` (counts ALL defaults including optional features 25-27, 47, 50, 53) instead of `required_default_count` (excludes optional). The worker query in `data_loaders.py` never fetched `required_default_count` from BigQuery, so it always fell back to `default_feature_count`.

**Impact:** 30-162 players blocked per day incorrectly. Mar 8 feature store showed 148/155 players would have been blocked without fix. Stars like Doncic, Jokic, Wembanyama, Durant, Edwards all affected. Feature 47 (`teammate_usage_available`) was the primary culprit — NULL for ~40% of players but classified as optional.

**Fix:** Two lines in `predictions/worker/data_loaders.py`:
1. Added `required_default_count` to the feature store SQL query (line 937)
2. Added `features['required_default_count'] = int(...)` to the dict population (line 1042)

**Coordinator was already correct** — its quality gate at `quality_gate.py:216` already reads `required_default_count`. Only the worker's defense-in-depth layer was misaligned.

**Commit:** `49b815b7`

### 2. CRITICAL BUG: Quality Scorer FEATURE_COUNT Cap

**Root cause:** `calculate_quality_score()` in `quality_scorer.py` used `num_features = len(feature_sources)` which could be 60 (features 0-59). But `OPTIONAL_FEATURES` only covers indices 0-53. Features 54-59 default for everyone and aren't in `OPTIONAL_FEATURES`, so they were falsely counted as "required defaults" → score capped at 69 → `is_quality_ready = false` for ~80+ players/day.

Meanwhile, `build_quality_visibility_fields()` correctly capped at `FEATURE_COUNT = 54`, so `required_default_count` was computed correctly. The mismatch was between the quality score (used by `is_quality_ready` gate) and the default count.

**Fix:** Changed line 225 from `num_features = len(feature_sources)` to `num_features = min(len(feature_sources), FEATURE_COUNT)`.

**Combined impact of bugs 1+2:** With both fixes, prediction volume should increase from ~75 to ~150+ per day. This is the intended "Coverage drops from ~180 to ~75" number in CLAUDE.md recovering to its proper level.

### 3. Signal Tuning — 3 Changes

**a) `book_disagreement` removed from rescue_tags**
- 47.4% HR at N=19 (7d) — actively rescuing sub-edge-floor picks that lose
- Was one of the highest-impact rescue signals at 93.0% HR historically, but current performance is below breakeven
- File: `ml/signals/aggregator.py` line 370

**b) `book_disagreement` UNDER weight reduced 2.5 → 1.0**
- Was joint-highest weighted UNDER signal, directly affecting which UNDER picks ranked highest
- At 47.4% HR, this was actively selecting poor UNDER picks as top-ranked
- File: `ml/signals/aggregator.py` line 75

**c) `blowout_risk_under` filter promoted from observation to active blocking**
- 15.4% HR at N=13 (7d) — catastrophic performance
- Observation filter already existed in aggregator (line 697-706), just needed `continue` statement
- Now blocks UNDER picks where `blowout_risk >= 0.40` and `line >= 15`
- Auto-demote system can revert if the filter starts blocking good picks

**Commit:** `c16e471b`

### 4. ESPN Fantasy Projections Scraper (SPOF Mitigation)

Built complete ESPN Fantasy API integration as second projection source:

**Files created (3):**
- `scrapers/projections/espn_projections.py` — Scraper class (ESPN Fantasy API, no auth required)
- `data_processors/raw/projections/espn_processor.py` — Phase 2 processor
- `schemas/espn_projections.json` — BQ table schema

**Files modified (6):**
- `scrapers/utils/gcs_path_builder.py` — Added GCS path template
- `scrapers/registry.py` — Added to NBA_SCRAPER_REGISTRY + projections group
- `data_processors/raw/main_processor_service.py` — Added processor to PROCESSOR_REGISTRY
- `data_processors/raw/path_extractors/external_extractors.py` — Added path extractor
- `data_processors/raw/path_extractors/__init__.py` — Registered extractor
- `ml/signals/supplemental_data.py` — FULL OUTER JOIN ESPN alongside NumberFire
- `ml/signals/projection_consensus.py` — Updated metadata for ESPN source

**Infrastructure:**
- BQ table `nba_raw.espn_projections` created (day-partitioned)
- Cloud Scheduler `espn-projections-daily` at 14:45 UTC (10:45 AM ET)

**Key design decisions:**
- ESPN provides **season-average PPG** (stat[0]/stat[42]), not daily matchup-adjusted projections
- `MIN_SOURCES` stays at 1 — ESPN needs shadow validation before raising to 2
- 365 players with projections, filters out free agents (proTeamId=0)
- Same `normalize_player_name()` approach as NumberFire for player matching

**Commit:** `974d9170`

### 5. SPOF Assessment (Research)

Investigated all 4 remaining SPOF data sources:

| SPOF | Current Impact | Finding |
|------|---------------|---------|
| **NumberFire** | MEDIUM (only projection) | **NOW MITIGATED** — ESPN fallback deployed |
| RotoWire | ZERO | `projected_minutes` always NULL. Combo signals use gamebook data, not RotoWire |
| VSiN | ZERO | All dependent signals (sharp_money) are shadow |
| Covers | ZERO | No signal consumes referee data |

### 6. Investigations (Research, No Code Changes)

**a) Book disagreement drought (0 fires Mar 2-7):** Normal market behavior. Sportsbooks in tight agreement (max std < 1.5). Historical streaks of 9 days. Timing gap: Mar 7 raw odds showed 22 players with std >= 1.5, but feature store computed before late snapshot arrived.

**b) Mar 6 low BB volume (1 pick from 7 games):** Root caused to Bug #1 above. 14 star players blocked by optional feature defaults. Ironically, blocked players were 2/14 (14% HR) — bug accidentally saved system from a bad night.

**c) WATCH models (3 models):** catboost_v12_noveg_0103, lgbm_vw015, xgb_s42 — all WATCH from single bad day (Mar 6). lgbm_vw015 still 80% BB HR. Expected to auto-recover.

**d) q4_scoring_ratio data freshness:** BDL play-by-play table has data through Mar 6 (420K rows). q4_scorer_over signal is NOT stale. 0% HR at N=4 is small sample noise.

---

## Commits

```
49b815b7 fix: worker zero-tolerance gate now uses required_default_count
c16e471b fix: quality scorer FEATURE_COUNT cap + signal tuning
974d9170 feat: ESPN Fantasy projections scraper — NumberFire SPOF fallback
```

---

## Files Changed

```
# Bug Fix 1: required_default_count
predictions/worker/data_loaders.py                    — Query + populate required_default_count

# Bug Fix 2: Quality scorer cap
data_processors/precompute/ml_feature_store/quality_scorer.py — Cap num_features at FEATURE_COUNT

# Signal Tuning
ml/signals/aggregator.py                              — book_disagreement rescue/weight, blowout_risk_under active

# ESPN Scraper (new)
scrapers/projections/espn_projections.py              — NEW: ESPN Fantasy API scraper
data_processors/raw/projections/espn_processor.py     — NEW: Phase 2 processor
schemas/espn_projections.json                         — NEW: BQ schema

# ESPN Integration (modified)
scrapers/utils/gcs_path_builder.py                    — GCS path template
scrapers/registry.py                                  — Registry entry
data_processors/raw/main_processor_service.py         — Processor registry
data_processors/raw/path_extractors/external_extractors.py — Path extractor
data_processors/raw/path_extractors/__init__.py       — Extractor registration
ml/signals/supplemental_data.py                       — ESPN projection loading
ml/signals/projection_consensus.py                    — ESPN in signal metadata
```

---

## System State

| Item | Status |
|------|--------|
| Fleet | 9 HEALTHY, 4 WATCH, 1 DEGRADING, 8+ BLOCKED |
| BB HR (30d) | 58.3% (35-25) — profitable |
| Market Regime | All GREEN (compression 1.0, direction divergence 3.3pp) |
| Prediction Volume | Should increase significantly Mar 8 (both quality fixes) |
| Combo Signals | COLD (small-sample, MIN_EDGE 4.0 takes effect Mar 8) |
| ESPN Scraper | Deployed, scheduler active, first run Mar 8 14:45 UTC |
| book_disagreement | Removed from rescue, weight 2.5→1.0 |
| blowout_risk_under | Filter now active (was observation) |
| Tests | 70 aggregator tests pass, all syntax clean |

---

## What to Do Next

### Priority 1: Verify Mar 8 Prediction Volume
The two quality fixes should dramatically increase prediction volume. Check:
```sql
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-03-07'
  AND system_id = 'catboost_v12'
GROUP BY 1 ORDER BY 1
```
Expected: ~150+ players (up from ~75). If still ~75, investigate whether the quality scorer fix deployed correctly to Phase 4 (nba-phase4-precompute-processors).

### Priority 2: Monitor Combo Signal Fire Rate Under MIN_EDGE 4.0
Mar 8 is the first pipeline run with MIN_EDGE 4.0 (Session 433 code deployed Mar 7 evening).
```sql
WITH deduped AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY game_date, player_lookup, system_id ORDER BY evaluated_at DESC) as rn
  FROM nba_predictions.pick_signal_tags WHERE game_date >= '2026-03-08'
)
SELECT game_date,
  COUNTIF(EXISTS(SELECT 1 FROM UNNEST(signal_tags) t WHERE t = 'combo_3way')) as combo_3way,
  COUNTIF(EXISTS(SELECT 1 FROM UNNEST(signal_tags) t WHERE t = 'combo_he_ms')) as combo_he_ms
FROM deduped WHERE rn = 1 GROUP BY 1 ORDER BY 1
```
Baseline (MIN_EDGE 3.0): 1-4 fires/day. If 0 fires for 3+ days, edge compression may require revisiting.

### Priority 3: Verify ESPN Scraper First Run
First scheduled run: Mar 8 at 14:45 UTC (10:45 AM ET).
```sql
SELECT game_date, COUNT(*) as players, MIN(projected_points) as min_pts, MAX(projected_points) as max_pts
FROM nba_raw.espn_projections
WHERE game_date >= '2026-03-08'
GROUP BY 1
```
Expected: ~365 players with projections. If 0, check Cloud Run logs for `nba-scrapers`.

### Priority 4: WATCH Model Recovery
Check Mar 8-9 performance — should auto-promote back to HEALTHY.
```sql
SELECT model_id, state, rolling_hr_7d, rolling_n_7d
FROM nba_predictions.model_performance_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.model_performance_daily)
  AND model_id IN ('catboost_v12_noveg_train0103_0227', 'lgbm_v12_noveg_vw015_train1215_0208', 'xgb_v12_noveg_s42_train1215_0208')
```

### Priority 5: Monitor blowout_risk_under Filter Impact
Now active — check if it's blocking picks and whether those picks would have lost:
```sql
SELECT game_date, COUNT(*) as blocked,
  COUNTIF(prediction_correct = TRUE) as would_have_won,
  COUNTIF(prediction_correct = FALSE) as would_have_lost
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_reason = 'blowout_risk_under_block_obs'
  AND game_date >= '2026-03-08'
GROUP BY 1 ORDER BY 1
```

### Priority 6: Future Work
- **Retrain `catboost_v9_low_vegas`** — 25d stale, approaching 30d
- **Raise `MIN_SOURCES` to 2** after ESPN validated (~1 week shadow)
- **Evaluate tier edge caps** for bench/role OVER (bench edge 7+ = 34.1% HR)
- **pick_signal_tags historical dedup** — one-time cleanup SQL
- **catboost_v12 edge 5+ investigation** — 47.6% HR at edge 5+ is concerning

---

## Daily Steering Summary (Mar 7)

```
MODEL HEALTH: 9 HEALTHY, 4 WATCH, 1 DEGRADING
  Top: catboost_v12_train0104_0222 86.7% (N=15)
  Watch: lgbm_vw015 57.1% (N=28) — still 80% BB HR, do NOT deactivate
  Degrading: catboost_v12_noveg_train0110_0220 53.3% (N=15)

EDGE 5+ HEALTH:
  PROFITABLE: v12_noveg_0108 (66.7%), v9_low_vegas (65.0%)
  LOSING: catboost_v12 (47.6%, N=21) — primary model anti-correlated at high edge

MARKET REGIME: All GREEN
  Compression: 1.000 | Max edge 7d: 6.4 | Direction: OVER 55% / UNDER 58.3%

SIGNAL HEALTH:
  COLD: combo_3way (42.9%, N=7), combo_he_ms (42.9%, N=7), book_disagreement (47.4%, N=19)
  Top: sharp_line_drop_under 87.5%, scoring_cold_streak_over 83.3%, HSE_over 78.9%

BEST BETS: 7d 61.1% (11-7) | 14d 56.3% (18-14) | 30d 58.3% (35-25)

RISK: None detected. Full schedule through Mar 15 (5-11 games/day).
```
