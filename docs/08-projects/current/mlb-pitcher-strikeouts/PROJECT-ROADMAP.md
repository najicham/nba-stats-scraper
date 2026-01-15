# MLB Pitcher Strikeouts - Project Roadmap

**Created:** 2026-01-13
**Last Updated:** 2026-01-14 (Session 46)
**Status:** Phase 1 Complete, BettingPros Integration In Progress

---

## Executive Summary

The MLB Pitcher Strikeouts model is **validated and profitable**:

| Metric | Value | vs Target |
|--------|-------|-----------|
| **Hit Rate** | 67.27% | +12.27% |
| **Total Picks** | 7,196 | Target: 1,000+ |
| **Edge over Breakeven** | +14.89% | Highly profitable |
| **Implied ROI** | ~+28.5% | Excellent |

**Decision:** Proceed to V2 development with Champion-Challenger framework.

---

## Project Phases

| Phase | Description | Status |
|-------|-------------|--------|
| Phase 1 | Historical Backfill & Validation | ✅ **COMPLETE** |
| Phase 2 | BettingPros Integration | 🔄 **IN PROGRESS** |
| Phase 3 | V1.5 Model Training (BettingPros features) | Pending |
| Phase 4 | Champion-Challenger Deployment | Pending |
| Phase 5 | Live Season Validation | April 2026 |

---

## Phase 1: Historical Validation ✅ COMPLETE

### Results

| Metric | Value |
|--------|-------|
| Dates Scraped | 345/352 (98%) |
| Predictions Matched | 7,226 (88.9%) |
| Predictions Graded | 7,196 |
| **Hit Rate** | **67.27%** |
| MAE | 1.46 strikeouts |

### Key Findings

1. **Edge Correlation:** Higher edge = higher win rate
   - Edge 2.5+: 92.2% win rate
   - Edge 1.0-1.5: 79.2% win rate
   - Edge <0.5: 52.5% win rate

2. **UNDER > OVER:** UNDER wins 70% vs OVER 65%

3. **Model Drift:** Performance declined in Jul-Aug 2025 (56-59%)

4. **Pitcher Exclusions:** 8 pitchers below breakeven

### Documentation

- `2026-01-14-SESSION-40-HANDOFF-HIT-RATE-ANALYSIS.md` - Full analysis

---

## Phase 2: BettingPros Integration 🔄 IN PROGRESS

### Strategic Pivot (Session 46)

**Key Discovery:** BettingPros historical API provides more value than fixing BDL scrapers.

| Dimension | BDL Scrapers (Old) | BettingPros (New) |
|-----------|-------------------|-------------------|
| **Data Volume** | 1.5 years | **4 years** (2022-2025) |
| **Grading** | Complex joins | **Outcomes included** |
| **New Features** | Blocked | **Ready now** |
| **Dependencies** | Scraper fixes | **None** |

### BettingPros Features (New)

| Feature | Source | Description |
|---------|--------|-------------|
| projection_value | BettingPros API | Their model's prediction |
| projection_diff | line - projection | Market inefficiency signal |
| perf_last_5_over_pct | Performance data | Recent O/U trend |
| perf_season_over_pct | Performance data | Season O/U trend |

### Backfill Progress

```bash
# Check progress
python scripts/mlb/historical_bettingpros_backfill/check_progress.py
```

| Market | Status |
|--------|--------|
| pitcher-strikeouts | 🔄 ~20% |
| pitcher-earned-runs-allowed | 🔄 ~20% |
| batter-hits | Pending |
| batter-home-runs | Pending |

### Old V2 Features (Deprioritized)

These features are blocked by BDL scraper issues and are no longer priority:

| Feature | Source | Status |
|---------|--------|--------|
| f11_home_away_k_diff | pitcher_game_summary | ❌ Blocked |
| f12_is_day_game | pitcher_game_summary | Medium |
| f13_day_night_k_diff | pitcher_game_summary | Medium |
| f14_vs_opponent_k_rate | historical matchups | High |
| f15_opponent_team_k_rate | team batting stats | High |
| f16_opponent_obp | team batting stats | Medium |
| f17_ballpark_k_factor | reference table | High |
| f18_game_total_line | odds API | Medium |
| f27_platoon_advantage | lineup analysis | High |
| f34_matchup_edge | composite score | Medium |

### Data Availability

| Feature Category | Status |
|------------------|--------|
| Rolling K averages | ✅ 95% populated |
| Season stats | ✅ 95% populated |
| Home/away splits | ❌ Not populated |
| Opponent K rate | ❌ Not populated |
| Ballpark factors | ❌ Not populated |

### Tasks

1. **Populate missing analytics features**
   - Home/away K diff (SQL update)
   - Opponent team K rate (join with batting stats)
   - Ballpark K factor (reference table)

2. **Update feature processor**
   - Add new features to `pitcher_features_processor.py`
   - Populate `mlb_precompute.pitcher_ml_features`

---

## Phase 3: V2 Model Training

### Training Plan

| Split | Date Range | Records | Purpose |
|-------|------------|---------|---------|
| Train | 2024-04 to 2025-05 | ~5,500 | Model fitting |
| Validation | 2025-06 | ~700 | Hyperparameter tuning |
| Test | 2025-07 to 2025-09 | ~2,000 | Final evaluation |

### Algorithm: CatBoost

- Matches NBA approach (proven success)
- Better categorical handling
- Handles missing values well

### Model Files

```
gs://nba-scraped-data/ml-models/mlb/
├── mlb_pitcher_strikeouts_v1_20260107.json    # Current champion
├── mlb_pitcher_strikeouts_v2_YYYYMMDD.cbm     # V2 challenger
└── pitcher_strikeouts_v2_metadata.json        # V2 metadata
```

---

## Phase 4: Champion-Challenger Framework

### Architecture

```
                    ┌─────────────────┐
                    │  Game Schedule  │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              │                             │
     ┌────────▼────────┐          ┌────────▼────────┐
     │  V1 (Champion)  │          │  V2 (Challenger)│
     │  19 features    │          │  29 features    │
     │  XGBoost        │          │  CatBoost       │
     │  67.27% hit rate│          │  Target: 70%+   │
     └────────┬────────┘          └────────┬────────┘
              │                             │
              └──────────────┬──────────────┘
                             │
                    ┌────────▼────────┐
                    │  Predictions    │
                    │  (both tracked) │
                    └─────────────────┘
```

### Tracking

```sql
-- Both models write to same table with model_version
INSERT INTO mlb_predictions.pitcher_strikeouts
(prediction_id, game_date, pitcher_lookup, predicted_strikeouts, model_version, ...)
VALUES
('uuid-v1', '2026-04-01', 'degrom-jacob', 7.2, 'v1', ...),
('uuid-v2', '2026-04-01', 'degrom-jacob', 7.5, 'v2', ...);
```

### Promotion Criteria

V2 becomes champion if (after 100+ picks):

| Metric | Threshold |
|--------|-----------|
| Hit Rate | >= 67.27% (match V1) |
| MAE | <= 1.46 (match V1) |
| High Edge Win Rate | >= 85% |
| Duration | 7+ days of data |

---

## Phase 5: Live Season Validation (April 2026)

### BettingPros Scraper Ready

- **Market ID:** 285 (pitcher strikeouts)
- **Endpoint:** `/v3/props`
- **File:** `scrapers/bettingpros/bp_mlb_player_props.py`

### Pre-Season Checklist

- [ ] V2 model trained and deployed
- [ ] BettingPros scraper tested with live data
- [ ] Both V1 and V2 running in parallel
- [ ] Comparison dashboard live
- [ ] Slack alerts configured

### Weekly Review Process

1. Compare V1 vs V2 performance
2. Check for model drift
3. Review pitcher-specific performance
4. Adjust thresholds if needed

---

## Technical Infrastructure

### Completed ✅

| Component | Status | Location |
|-----------|--------|----------|
| V1 Prediction Model | ✅ | `predictions/mlb/pitcher_strikeouts_predictor.py` |
| Historical Backfill | ✅ | `scripts/mlb/historical_odds_backfill/` |
| BettingPros Scraper | ✅ | `scrapers/bettingpros/bp_mlb_player_props.py` |
| MLB Utilities | ✅ | `shared/utils/mlb_*.py` |
| BigQuery Tables | ✅ | `mlb_analytics`, `mlb_predictions` |

### To Build

| Component | Priority | Phase |
|-----------|----------|-------|
| V2 Feature Processor | P1 | Phase 2 |
| V2 Training Script | P1 | Phase 3 |
| V2 Predictor Class | P1 | Phase 3 |
| Comparison Dashboard | P2 | Phase 4 |
| Performance Alerts | P2 | Phase 5 |

---

## Timeline

| Week | Activity |
|------|----------|
| **Current** | Phase 1 complete, V2 plan confirmed |
| **Week 1** | Feature engineering (populate missing features) |
| **Week 2** | V2 model training and validation |
| **Week 3** | Champion-Challenger deployment |
| **Pre-Season** | Testing and dry runs |
| **April 2026** | Live season begins |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-14 | Proceed to V2 development | 67.27% hit rate validates model |
| 2026-01-14 | Use Champion-Challenger framework | Safe comparison, mirrors NBA |
| 2026-01-14 | Target 29 features for V2 | Balance improvement vs complexity |
| 2026-01-14 | Use CatBoost for V2 | NBA success, better categoricals |

---

## Key Files

### Documentation

- `2026-01-14-SESSION-40-HANDOFF-HIT-RATE-ANALYSIS.md` - Hit rate results
- `MODEL-UPGRADE-STRATEGY.md` - V2 strategy details
- `MLB-UTILITIES-REFERENCE.md` - Utility functions

### Code

- `predictions/mlb/pitcher_strikeouts_predictor.py` - V1 predictor
- `predictions/mlb/pitcher_strikeouts_predictor_v2.py` - V2 predictor (to create)
- `scrapers/bettingpros/bp_mlb_player_props.py` - BettingPros scraper

---

## Next Session Tasks

1. **Populate missing analytics features**
   - Run SQL updates for home_away_k_diff, opponent_team_k_rate
   - Load ballpark K factors from reference

2. **Create V2 predictor skeleton**
   - Follow NBA CatBoost pattern
   - Track model_version in predictions

3. **Extract training data**
   - Query features with actual strikeouts
   - Split into train/validation/test

4. **Train V2 model**
   - CatBoost with 29 features
   - Validate on test set

5. **Set up comparison infrastructure**
   - Both models run in parallel
   - Daily comparison query
