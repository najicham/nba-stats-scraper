# MLB Pitcher Strikeouts - Current Status

**Last Updated**: 2026-01-07 (Evening)
**Project Phase**: 2024 Season Collection In Progress

---

## Executive Summary

The MLB Pitcher Strikeouts prediction system has been **validated with real data** and is now collecting full 2024 season data.

### Current Session Progress (2026-01-07)

| Step | Status | Result |
|------|--------|--------|
| Baseline validation | ✅ Complete | MAE: 1.92, Within 2K: 60.4% |
| Data source research | ✅ Complete | MLB Stats API + pybaseball work |
| Platoon splits | ✅ Complete | K% vs LHP/RHP from Statcast |
| Collection script | ✅ Complete | `scripts/mlb/collect_2024_season.py` |
| 2024 season collection | 🔄 In Progress | Collecting to BigQuery |

### Baseline Validation Results (182 pitcher starts)

| Metric | Value | Target |
|--------|-------|--------|
| **MAE** | 1.92 | < 1.5 |
| **Within 1K** | 31.3% | > 40% |
| **Within 2K** | 60.4% | > 70% |
| **Bias** | +0.17 | ≈ 0 |

**Verdict**: Formula works. ML training should improve by 15-25%.

**What's Complete:**
- **28 scrapers** implemented and tested (ahead of NBA's 27)
- **27 BigQuery tables** created (22 in mlb_raw, 3 in mlb_reference, 5 in mlb_precompute)
- **35-feature vector** implemented (V2)
- **Bottom-up K model** validated (MAE 1.92)
- **31 unit tests** for feature processors
- **Baseline validation script** (`scripts/mlb/baseline_validation.py`)
- **Season collection script** (`scripts/mlb/collect_season.py`) - supports 2024 & 2025
- **Platoon splits loading** (K% vs LHP/RHP from Statcast)

**What's In Progress:**
- **2025 season data collection** (186 dates, ~4,800 starts) - PRIORITY
- **2024 season data collection** (additional training data)

**What's Next:**
- **ML training script** (after collection complete)
- **Prediction systems** (3-5 systems like NBA)
- **Grading pipeline** (accuracy tracking)

### Data Collection Plan

**OPEN QUESTION**: Should we collect 2024 or 2025 first?

Some features may depend on prior season data:
- Rolling averages at season start need prior year
- "Season baseline" stats for early 2025 need 2024 data

**Next session should**:
1. Read `pitcher_features_processor.py` to understand dependencies
2. Decide collection order based on findings
3. See handoff doc: `docs/09-handoff/2026-01-07-MLB-SEASON-COLLECTION-HANDOFF.md`

**BLOCKER REMOVED**: Data access confirmed working (MLB Stats API + pybaseball).

---

## Layer Status

### Layer 1: Scrapers (28 total) - COMPLETE

| Source | Count | Scrapers |
|--------|-------|----------|
| Ball Don't Lie | 13 | pitcher_stats, batter_stats, games, active_players, season_stats, injuries, player_splits, standings, box_scores, live_box_scores, team_season_stats, player_versus, teams |
| MLB Stats API | 3 | schedule, lineups, game_feed |
| Odds API | 8 | events, game_lines, pitcher_props, batter_props + 4 historical variants |
| Statcast | 1 | statcast_pitcher (via pybaseball) |
| External | 3 | umpire_stats, ballpark_factors, weather |

### Layer 2: Raw Processors (8 total) - COMPLETE

| Processor | Source Table | Target Table |
|-----------|--------------|--------------|
| MlbPitcherStatsProcessor | GCS | mlb_raw.bdl_pitcher_stats |
| MlbBatterStatsProcessor | GCS | mlb_raw.bdl_batter_stats |
| MlbScheduleProcessor | GCS | mlb_raw.mlb_schedule |
| MlbLineupsProcessor | GCS | mlb_raw.mlb_game_lineups, mlb_lineup_batters |
| MlbEventsProcessor | GCS | mlb_raw.oddsa_events |
| MlbGameLinesProcessor | GCS | mlb_raw.oddsa_game_lines |
| MlbPitcherPropsProcessor | GCS | mlb_raw.oddsa_pitcher_props |
| MlbBatterPropsProcessor | GCS | mlb_raw.oddsa_batter_props |

### Layer 3: Analytics Processors (2 total) - COMPLETE

| Processor | Source | Target |
|-----------|--------|--------|
| MlbPitcherGameSummaryProcessor | mlb_raw.bdl_pitcher_stats | mlb_analytics.pitcher_game_summary |
| MlbBatterGameSummaryProcessor | mlb_raw.bdl_batter_stats | mlb_analytics.batter_game_summary |

### Layer 4: Feature Processor - COMPLETE (V2)

**Feature Version**: `v2_35features`

| Component | Status |
|-----------|--------|
| pitcher_features_processor.py | Complete, 35 features |
| lineup_k_analysis_processor.py | Complete, bottom-up K model |
| pitcher_ml_features table | Created with all columns |
| lineup_k_analysis table | Created |
| Unit tests | 31 tests passing |

#### V1 Original Features (f00-f24):
- f00-f04: Recent performance (K averages, std dev, IP)
- f05-f09: Season baseline (K/9, ERA, WHIP, games, total K)
- f10-f14: Split adjustments (home/away, day/night, vs opponent)
- f15-f19: Matchup context (team K rate, OBP, ballpark, game total, implied runs)
- f20-f24: Workload/fatigue (days rest, games last 30, pitch count, IP, postseason)

#### V1 MLB-Specific Features (f25-f29) - NEW:
| Feature | Name | Description |
|---------|------|-------------|
| f25 | bottom_up_k_expected | **THE KEY**: Sum of individual batter K probabilities |
| f26 | lineup_k_vs_hand | Lineup K rate vs pitcher's handedness |
| f27 | platoon_advantage | LHP vs RHH advantage (+/-) |
| f28 | umpire_k_factor | Umpire K adjustment (+/-) |
| f29 | projected_innings | Expected IP |

#### V2 Advanced Features (f30-f34) - NEW:
| Feature | Name | Description |
|---------|------|-------------|
| f30 | velocity_trend | Velocity change from baseline |
| f31 | whiff_rate | Overall swing-and-miss rate |
| f32 | put_away_rate | K rate with 2 strikes |
| f33 | lineup_weak_spots | Count of high-K batters (>0.28) |
| f34 | matchup_edge | Composite advantage (-3 to +3) |

### Layer 5: ML Training - NOT STARTED

- No training script exists
- Need: `ml/train_pitcher_strikeouts_xgboost.py`
- Blocked by: No historical data

### Layer 6: Predictions - NOT STARTED

- No prediction workers exist
- Need: Coordinator, workers, grading

---

## BigQuery Tables

### mlb_raw (15 tables)

| Table | Status |
|-------|--------|
| bdl_pitcher_stats | Created |
| bdl_batter_stats | Created |
| bdl_pitchers | Created (for handedness) |
| bdl_batter_splits | Created |
| bdl_games | Created |
| bdl_active_players | Created |
| bdl_injuries | Created |
| bdl_pitcher_season_stats | Created |
| bdl_pitcher_splits | Created |
| mlb_schedule | Created |
| mlb_game_lineups | Created |
| mlb_lineup_batters | Created |
| oddsa_events | Created |
| oddsa_game_lines | Created |
| oddsa_pitcher_props | Created |
| umpire_game_assignment | **Created (V1)** |

### mlb_analytics (2 tables)

| Table | Status |
|-------|--------|
| pitcher_game_summary | Created |
| batter_game_summary | Created |

### mlb_precompute (5 tables)

| Table | Status | Purpose |
|-------|--------|---------|
| pitcher_ml_features | Created | 35-feature vector |
| lineup_k_analysis | **Created (V1)** | Bottom-up K calculation |
| pitcher_innings_projection | **Created (V1)** | Expected IP |
| pitcher_arsenal_summary | **Created (V2)** | Velocity, whiff rates |
| batter_k_profile | **Created (V2)** | Batter K vulnerability |

### mlb_reference (3 tables)

| Table | Status |
|-------|--------|
| ballpark_factors | Created |
| team_lookup | Created |
| player_lookup | Created |

---

## Key Architecture Insight

### Bottom-Up K Model (The MLB Advantage)

**NBA**: "Player X averages Y points against defenses like this" (probabilistic)

**MLB**: "Pitcher X faces batters A-I, each with K rates. Sum = expected Ks" (deterministic)

The **bottom-up model** (`f25_bottom_up_k_expected`) sums individual batter K probabilities based on the known lineup order. This is unique to MLB because:
- We KNOW the exact 9 batters before the game
- We KNOW their K rates vs LHP/RHP
- We can CALCULATE expected Ks, not just estimate

---

## Processors Created

### Precompute Processors

| Processor | File | Purpose |
|-----------|------|---------|
| MlbPitcherFeaturesProcessor | pitcher_features_processor.py | 35-feature vector |
| MlbLineupKAnalysisProcessor | lineup_k_analysis_processor.py | Bottom-up K |

---

## Unit Tests

Location: `tests/processors/precompute/mlb/`

| Test File | Tests | Status |
|-----------|-------|--------|
| lineup_k_analysis/test_unit.py | 9 tests | Passing |
| pitcher_features/test_unit.py | 22 tests | Passing |
| **Total** | **31 tests** | **All passing** |

### Test Coverage:
- Processor initialization
- Bottom-up K calculation accuracy
- Platoon advantage calculation
- Lineup quality tier classification
- Weak spots counting
- Matchup edge calculation
- Feature vector construction (35 elements)
- V1/V2 feature integration

---

## Next Steps (Prioritized)

### Immediate (Ready to Implement)
1. Create processor for pitcher_arsenal_summary (from Statcast data)
2. Create processor for batter_k_profile (from batter_game_summary)
3. Create processor for pitcher_innings_projection

### Short-term (Before MLB Season)
1. Run sample historical backfill to test pipeline
2. Create ML training script for pitcher strikeouts
3. Train initial XGBoost model

### Medium-term
1. Create prediction coordinator/workers
2. Create grading pipeline
3. Deploy to production

---

## File Locations

```
scrapers/mlb/
├── balldontlie/     (13 scrapers)
├── mlbstatsapi/     (3 scrapers)
├── oddsapi/         (8 scrapers)
├── statcast/        (1 scraper)
└── external/        (3 scrapers)

data_processors/
├── raw/mlb/         (8 processors)
├── analytics/mlb/   (2 processors)
└── precompute/mlb/  (2 processors)  <-- Updated

schemas/bigquery/
├── mlb_raw/         (10 schema files)
├── mlb_analytics/   (2 schema files)
├── mlb_precompute/  (1 schema file)
├── mlb_predictions/ (1 schema file)
└── mlb_reference/   (1 schema file)

tests/processors/precompute/mlb/
├── lineup_k_analysis/test_unit.py   (9 tests)
└── pitcher_features/test_unit.py    (22 tests)
```

---

## Verification Commands

```bash
# Verify all 28 scrapers import
SPORT=mlb PYTHONPATH=. .venv/bin/python -c "
import scrapers.mlb as m
print(f'Scrapers: {len(m.__all__)}')
"

# Verify precompute processors
PYTHONPATH=. .venv/bin/python -c "
from data_processors.precompute.mlb.pitcher_features_processor import MlbPitcherFeaturesProcessor
from data_processors.precompute.mlb.lineup_k_analysis_processor import MlbLineupKAnalysisProcessor
print('pitcher_features:', MlbPitcherFeaturesProcessor().feature_version)
print('lineup_k_analysis:', MlbLineupKAnalysisProcessor().target_table)
"

# Run unit tests
PYTHONPATH=. python -m pytest tests/processors/precompute/mlb/ -v

# Check table schema
bq show --schema nba-props-platform:mlb_precompute.pitcher_ml_features | python3 -c "
import json,sys
cols = json.load(sys.stdin)
features = [c['name'] for c in cols if c['name'].startswith('f')]
print(f'Feature columns: {len(features)}')
print(f'Last feature: {sorted(features)[-1]}')
"
```
