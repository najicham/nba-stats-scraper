# Session 289 Handoff — Phase 2 Data Backfill Complete, Feature Extraction Bugs Discovered

**Date:** 2026-02-18
**Focus:** Comprehensive Phase 2 data gap audit, historical backfills, feature source validation tool
**Status:** All Phase 2 data gaps filled. Feature validation tool discovered significant extraction bugs that MUST be fixed before retraining.
**Prior Session:** 288 (f47/f50 implementation, feature array migration)

---

## What Was Done

### 1. Comprehensive Phase 2 Data Gap Audit

Audited 102 game days (Nov 1 2025 - Feb 12 2026) across all raw tables. Found and fixed gaps.

### 2. Injury Report Historical Backfill (MAJOR)

**Discovery:** Nov-Dec GCS injury files were all empty `[]` — scraper ran but captured nothing. However, historical PDFs are still available on NBA.com CDN.

**Script:** `bin/backfill_injury_reports.py` (NEW) — downloads PDFs from `ak-static.cms.nba.com`, parses with pdfplumber + InjuryReportParser, loads directly to BigQuery.

**Results:**
- 6,354 records loaded for Nov 1 - Dec 31 (61 dates, all succeeded)
- Nov: 0 → 30 days (100%)
- Dec: 1 → 31 days (100%)
- URL format: old = `Injury-Report_YYYY-MM-DD_HHPM.pdf`, new (post Dec 23) = `Injury-Report_YYYY-MM-DD_HH_mmPM.pdf`

### 3. Team Boxscore Jan 22 Re-scraped

All 8 games (CHA@ORL, HOU@PHI, DEN@WAS, GSW@DAL, CHI@MIN, SAS@UTA, LAL@LAC, MIA@POR) re-scraped via Cloud Run scraper service and verified in BigQuery (16 rows).

### 4. Odds API Game Lines Backfill (Jan 19-22, 24)

Used existing historical backfill script at `backfill_jobs/scrapers/odds_api_lines/odds_api_lines_scraper_backfill.py`:
- 5 dates, 37 games, 100% success rate
- Data scraped to GCS, then processed to BigQuery via Phase 2 service HTTP calls
- All 5 dates verified: 296 total records in `nba_raw.odds_api_game_lines`

### 5. f47 Backfill for Nov-Dec

Updated `F47_EARLIEST` from `2026-01-01` to `2025-11-01` (injury data now exists). Ran backfill:
- 8,592 rows updated for Nov-Dec
- Nov: 0% → 56.3%, Dec: 0% → 64.6%
- Coverage is correct — f47 only fires when team has OUT/DOUBTFUL players

### 6. Feature Source Validation Tool (NEW)

**Script:** `bin/validate_feature_sources.py` — checks whether NULL features have source data that should have been extracted.

**How it works:** For each feature where `feature_N_value IS NULL`, JOINs back to the upstream source table to check if source data exists. Flags mismatches as bugs vs legitimate NULLs.

**Usage:**
```bash
PYTHONPATH=. python bin/validate_feature_sources.py --start-date 2025-11-04 --end-date 2026-02-17
PYTHONPATH=. python bin/validate_feature_sources.py --days 7
PYTHONPATH=. python bin/validate_feature_sources.py --days 30 --feature 18  # Deep dive one feature
PYTHONPATH=. python bin/validate_feature_sources.py --days 7 --format json  # JSON output
```

### 7. Phase 2 Coverage After All Backfills

| Month | Game Days | Gamebook | Boxscore | Injury | Odds Props | Odds Game |
|-------|-----------|----------|----------|--------|------------|-----------|
| Nov | 29 | **29** | **29** | **29** | **29** | **29** |
| Dec | 30 | **30** | **30** | **30** | **30** | **30** |
| Jan | 31 | **31** | **31** | 29 | 30 | **31** |
| Feb | 12 | **12** | **12** | **12** | **12** | **12** |

Nov and Dec are 100% across all tables. Jan has 2 minor injury gaps and 1 odds props gap.

---

## CRITICAL DISCOVERY: Feature Extraction Bugs

The validation tool found **significant bugs where source data exists but features are NULL**:

### TOP BUGS (must fix before retraining)

| Feature | Bug Count | Bug % | Source Table | Issue |
|---------|-----------|-------|-------------|-------|
| **f18 (pct_paint)** | 14,603 | 67.7% | player_shot_zone_analysis | Source exists within 14d but extractor doesn't find it |
| **f19 (pct_mid_range)** | 14,697 | 65.4% | player_shot_zone_analysis | Same |
| **f20 (pct_three)** | 14,603 | 67.7% | player_shot_zone_analysis | Same |
| **f32 (ppm_avg_last_10)** | 6,084 | 66.0% | player_daily_cache | Cache has data but extractor misses it |
| **f4 (games_in_7_days)** | 4,302 | 90.4% | player_daily_cache | Cache has data but extractor misses it |
| **f22 (team_pace)** | 3,263 | 43.2% | player_daily_cache | Same |
| **f23 (team_off_rating)** | 3,263 | 43.2% | player_daily_cache | Same |
| **f0 (points_avg_last_5)** | 2,450 | 42.9% | player_daily_cache | Same |
| **f13 (opponent_def_rating)** | 2,269 | 36.5% | team_defense_zone_analysis | Source exists within 7d but extractor misses |
| **Calculated (f9-f17,f21,f24,f28,f30)** | 363 each | 100% | N/A | 363 rows where entire pipeline failed |

### CLEAN Features

- **f25-27 (vegas lines)**: All 15,402 NULLs are legitimate — bench players without prop lines.

### Root Cause Investigation Needed

**Priority 1 — Shot zones (f18-20): 14K bugs**
- `player_shot_zone_analysis` has data within 14 days, but the extractor in `feature_extractor.py` (`_batch_extract_shot_zones`) doesn't find it
- Likely: JOIN key mismatch (player_lookup normalization?) or date window logic
- File: `data_processors/precompute/ml_feature_store/feature_extractor.py`

**Priority 2 — Daily cache (f0-f4, f22-23, f31-32): 2K-6K bugs each**
- `player_daily_cache` has rows within 14 days, but `_batch_extract_player_stats` misses them
- f32 (ppm) has 66% bug rate vs f0 (43%) — may be additional conditions for ppm calculation
- f4 (games_in_7_days) has 90% bug rate — suspicious, probably a different computation path

**Priority 3 — 363 fully-NULL rows**
- Every calculated feature has exactly 363 NULLs
- These are rows where the feature store was populated but NO features were extracted
- Likely: UPCG (upcoming_player_game_context) entries without matching Phase 3/4 data

### Investigation Steps

```bash
# 1. Check one specific bug case for shot zones
bq query --use_legacy_sql=false "
SELECT fs.player_lookup, fs.game_date,
  fs.feature_18_value, fs.feature_18_source,
  psz.player_lookup as source_exists, psz.analysis_date
FROM nba_predictions.ml_feature_store_v2 fs
LEFT JOIN nba_precompute.player_shot_zone_analysis psz
  ON fs.player_lookup = psz.player_lookup
  AND psz.analysis_date BETWEEN DATE_SUB(fs.game_date, INTERVAL 14 DAY) AND fs.game_date
WHERE fs.game_date = '2026-01-15'
  AND fs.feature_18_value IS NULL
  AND psz.player_lookup IS NOT NULL
LIMIT 10"

# 2. Check the extractor's actual query for shot zones
# Read: data_processors/precompute/ml_feature_store/feature_extractor.py
# Search for: _batch_extract_shot_zones

# 3. Check what the 363 fully-NULL rows look like
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as cnt
FROM nba_predictions.ml_feature_store_v2
WHERE feature_9_value IS NULL AND feature_15_value IS NULL
  AND game_date >= '2025-11-04'
GROUP BY 1 ORDER BY 1"

# 4. Run the validation tool for just one feature
PYTHONPATH=. python bin/validate_feature_sources.py --days 30 --feature 18
```

---

## IMMEDIATE NEXT STEPS (Priority Order)

### Priority 1: Fix Feature Extraction Bugs

**This is the #1 blocker.** The model is training on data with 14K+ shot zone bugs and 6K+ cache bugs. Fixing these before retraining will improve model quality.

1. Read `feature_extractor.py` — focus on `_batch_extract_shot_zones`, `_batch_extract_player_stats`
2. Compare the extractor's SQL JOIN logic with the validation tool's JOIN logic
3. Identify the mismatch (likely: player_lookup normalization, date window, or missing fallback)
4. Fix the extraction logic
5. Re-run validation to confirm fixes
6. Backfill the fixed features for the full season

### Priority 2: Retrain All Models

Both models BLOCKED (V9: 39 days stale, V12: 16 days). Games resume Feb 19.

```bash
# After feature bugs fixed:
./bin/retrain.sh --promote --eval-days 14
./bin/retrain.sh --family v12_noveg_mae --promote --eval-days 14
```

### Priority 3: Archetype Replay Re-Run

Session 285 ran with empty feature columns — results invalid. Now that data is backfilled AND features fixed, re-run both season replays.

### Priority 4: Validation Skill Improvements

From the audit, these gaps should be added to existing skills:

| Gap | Where to Add |
|-----|-------------|
| Per-feature coverage tracking (all 33 V9 features) | `spot-check-features` |
| Phase 2 raw data completeness vs schedule | `validate-daily` |
| GCS content validation (empty files) | `validate-daily` or `reconcile-yesterday` |
| Feature temporal gaps (0% for months) | `spot-check-features` |

### Priority 5: Experiments (after data is solid)

| Experiment | Expected Gain | Effort |
|-----------|---------------|--------|
| Per-model edge thresholds (V9 edge>=5, V12 edge>=4) | +$2-8K | 4 hrs |
| Min training days sweep (21d/28d vs 42d) | Unknown | 6 hrs |
| Adaptive direction gating | +$1-5K | 3 hrs |
| High conviction tier in API (edge>=5) | UX | 2 hrs |

---

## Dead Ends — Do Not Revisit

- Edge Classifier (Model 2) — AUC < 0.50 (Session 230)
- Tier-specific models — hurts generalization (Session 282)
- Day-of-week filters — patterns invert between seasons (Session 282)
- CHAOS model — less stable than MAE + quantile (Session 233)
- Residual mode / two-stage pipeline — no improvement (Session 230)
- Relative edge >= 30% filter — blocks 62.8% HR picks (Session 284)

---

## Key Files

| File | Purpose |
|------|---------|
| `bin/validate_feature_sources.py` | **NEW** — Feature source validation tool |
| `bin/backfill_injury_reports.py` | **NEW** — Historical injury PDF backfill |
| `bin/backfill_f47_f50.py` | Updated F47_EARLIEST to Nov 2025 |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | **FIX NEEDED** — shot zone + cache extraction bugs |
| `data_processors/precompute/ml_feature_store/feature_calculator.py` | Derived feature calculations |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Feature assembly |
| `shared/ml/feature_contract.py` | Feature names, source map, model contracts |
| `backfill_jobs/scrapers/odds_api_lines/odds_api_lines_scraper_backfill.py` | Odds API historical backfill (used for Jan 19-24) |

---

## What NOT to Do

- Do NOT retrain before fixing feature extraction bugs (14K+ bad rows = garbage in)
- Do NOT remove `features` array column yet (Phase 8 deferred 2+ weeks)
- Do NOT relax zero-tolerance default thresholds
- Do NOT deploy retrained model without ALL governance gates passing
- Do NOT revisit dead ends listed above

---

## Session Summary

| Item | Status |
|------|--------|
| Phase 2 data gap audit | DONE — comprehensive |
| Injury report backfill (Nov-Dec) | DONE — 6,354 records, 61 dates |
| Team boxscore Jan 22 | DONE — 8 games verified |
| Odds API game lines (5 dates) | DONE — 37 games, 296 records |
| f47 backfill Nov-Dec | DONE — 8,592 rows |
| Feature validation tool | DONE — `bin/validate_feature_sources.py` |
| Feature extraction bug discovery | DONE — 14K shot zone + 6K cache bugs found |
| **Fix extraction bugs** | **TODO — Priority 1** |
| **Retrain models** | **TODO — Priority 2 (after bugs fixed)** |
| **Archetype replay re-run** | **TODO — Priority 3** |
| **Validation skill improvements** | **TODO — Priority 4** |
