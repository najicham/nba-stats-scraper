# MLB Pitcher Strikeouts - Current Status

**Last Updated**: 2026-01-15 (Session 58)
**Project Phase**: V1.6 Shadow Mode Testing + Line Timing Implementation

---

## Executive Summary

The MLB Pitcher Strikeouts prediction system has a **champion-challenger infrastructure** with V1.6 running in shadow mode alongside V1.4. Session 58 added parallel model testing and line timing analysis capabilities.

### Model Performance

| Model | Hit Rate | Very High OVER | High Conf OVER | Status |
|-------|----------|----------------|----------------|--------|
| **V1.4 (Champion)** | ~55% | ~62% | ~60% | Production |
| **V1.6 (Challenger)** | **63.25%** | **82.2%** | **75.8%** | Shadow Testing |

### What's Live
- **V1.4 Champion**: Production model (XGBoost classifier)
- **V1.6 Challenger**: Shadow mode parallel testing
- **Shadow Mode Runner**: Compares V1.4 vs V1.6 daily
- **Line Timing (v3.6)**: `line_minutes_before_game` tracking
- **Red Flag System**: IL detection, high variance, SwStr% signals

---

## V1.6 Strategy & Roadmap

### Phase 1: Shadow Testing (Current - 7+ Days)
**Goal**: Validate V1.6 outperforms V1.4 on live data

```bash
# Run daily shadow mode
PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py
```

**Success Criteria**:
- V1.6 hit rate > V1.4 hit rate by 3%+
- V1.6 closer to actual in 55%+ of predictions
- No regression on high-confidence bets

### Phase 2: Promotion Decision (After 7 Days)
**Query Performance**:
```sql
SELECT * FROM mlb_predictions.shadow_model_comparison
```

**If V1.6 Wins**:
```bash
# Promote to production
export MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
./bin/predictions/deploy/mlb/deploy_mlb_prediction_worker.sh
```

### Phase 3: Future V1.7+ Candidates
| Feature | Source | Hypothesis |
|---------|--------|------------|
| Opening line capture | Odds API | Line movement = sharp money signal |
| Weather x breaking ball | Weather API | Cold/humid reduces breaking ball effectiveness |
| Umpire K-rate | UmpScorecards | Some umps have 15%+ higher K rates |
| Lineup-specific K rates | BallDontLie | Bottom-up K expectation per batter |

---

## Shadow Mode Infrastructure

### How It Works

```
┌──────────────────────────────────────────────────────────────┐
│                    SHADOW MODE FLOW                          │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Daily Trigger ─────┐                                        │
│                     │                                        │
│                     ▼                                        │
│            ┌──────────────────┐                              │
│            │ shadow_mode_     │                              │
│            │ runner.py        │                              │
│            └────────┬─────────┘                              │
│                     │                                        │
│         ┌──────────┼───────────┐                             │
│         │          │           │                             │
│         ▼          ▼           ▼                             │
│    ┌─────────┐ ┌─────────┐ ┌─────────────────┐              │
│    │ V1.4    │ │ V1.6    │ │ pitcher_game_   │              │
│    │ Model   │ │ Model   │ │ summary         │              │
│    └────┬────┘ └────┬────┘ └────────┬────────┘              │
│         │           │               │                        │
│         └─────┬─────┘               │                        │
│               │                     │                        │
│               ▼                     │                        │
│    ┌─────────────────────┐          │                        │
│    │ shadow_mode_        │◀─────────┘                        │
│    │ predictions         │                                   │
│    │ ─────────────────── │                                   │
│    │ v1_4_predicted      │                                   │
│    │ v1_6_predicted      │                                   │
│    │ prediction_diff     │                                   │
│    │ recommendation_     │                                   │
│    │   agrees            │                                   │
│    └─────────────────────┘                                   │
│               │                                              │
│               ▼ (after games)                                │
│    ┌─────────────────────┐                                   │
│    │ Grading:            │                                   │
│    │ - actual_strikeouts │                                   │
│    │ - v1_4_correct      │                                   │
│    │ - v1_6_correct      │                                   │
│    │ - closer_prediction │                                   │
│    └─────────────────────┘                                   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Key Files
```
predictions/mlb/
├── shadow_mode_runner.py           # Run both models in parallel
├── pitcher_loader.py               # Query lines with timing
├── pitcher_strikeouts_predictor.py # Main predictor (both versions)
└── worker.py                       # Production worker

schemas/bigquery/mlb_predictions/
├── strikeout_predictions_tables.sql
└── shadow_predictions_tables.sql   # NEW: Shadow comparison table
```

### Key Queries
```sql
-- Weekly model comparison
SELECT * FROM mlb_predictions.shadow_model_comparison;

-- Daily breakdown
SELECT * FROM mlb_predictions.shadow_daily_comparison;

-- Pending grading
SELECT * FROM mlb_predictions.shadow_pending_grading;
```

---

## Line Timing Feature (v3.6)

### What It Tracks
`line_minutes_before_game` captures how many minutes before game start a betting line was scraped.

### Timing Buckets
| Bucket | Minutes Before | Hypothesis |
|--------|---------------|------------|
| `VERY_EARLY` | >240 (4+ hours) | Lines less efficient, more edge potential |
| `EARLY` | 60-240 (1-4 hours) | Moderate efficiency |
| `CLOSING` | <60 (<1 hour) | Most efficient, all info priced in |

### Data Flow
```
Odds API ──┐ commence_time
           │ snapshot_time
           ▼
┌────────────────────────────┐
│ mlb_pitcher_props_         │
│ processor.py               │
│ ─────────────────────────  │
│ minutes_before_tipoff =    │
│ (commence_time - snapshot) │
│   .total_seconds() / 60    │
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│ oddsa_pitcher_props        │
│ + game_start_time          │
│ + minutes_before_tipoff    │
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│ pitcher_loader.py          │
│ - queries with timing      │
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│ worker.py                  │
│ - passes timing to BQ      │
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│ pitcher_strikeouts         │
│ + line_minutes_before_game │
└──────────────┬─────────────┘
               │
               ▼
┌────────────────────────────┐
│ grading_processor.py       │
│ - analyze_timing()         │
│ - get_timing_summary()     │
└────────────────────────────┘
```

### Analysis Query
```sql
SELECT
  CASE
    WHEN line_minutes_before_game > 240 THEN 'VERY_EARLY'
    WHEN line_minutes_before_game > 60 THEN 'EARLY'
    WHEN line_minutes_before_game > 0 THEN 'CLOSING'
  END as timing_bucket,
  COUNT(*) as predictions,
  COUNTIF(is_correct) as correct,
  ROUND(COUNTIF(is_correct) * 100.0 / COUNT(*), 1) as accuracy
FROM mlb_predictions.pitcher_strikeouts
WHERE is_correct IS NOT NULL
  AND line_minutes_before_game IS NOT NULL
GROUP BY timing_bucket
ORDER BY accuracy DESC
```

---

## Champion-Challenger Setup

### Switching Models

```bash
# V1.4 Champion (default)
# No changes needed - default in predictor

# V1.6 Challenger
export MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
```

### Model Versions

| Version | Features | Key Additions | Status |
|---------|----------|---------------|--------|
| V1.4 | 25 | Opponent K rate, ballpark factor | Champion (Production) |
| V1.6 | 35 | Rolling SwStr%, velocity trend | Challenger (Shadow) |

### GCS Paths
```
gs://nba-scraped-data/ml-models/mlb/
├── mlb_pitcher_strikeouts_v1_4features_20260114_142456.json      # Champion
├── mlb_pitcher_strikeouts_v1_4features_20260114_142456_metadata.json
├── mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json      # Challenger
└── mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json
```

---

## Data Infrastructure

### BigQuery Tables

| Dataset | Table | Records | Purpose |
|---------|-------|---------|---------|
| mlb_raw | statcast_pitcher_game_stats | 39,918 | Per-game Statcast metrics |
| mlb_raw | fangraphs_pitcher_season_stats | 1,704 | Season-level SwStr% |
| mlb_raw | bdl_injuries | 222 | IL tracking |
| mlb_raw | bp_pitcher_props | 100K+ | Historical betting lines |
| mlb_raw | oddsa_pitcher_props | - | Live Odds API props + timing |
| mlb_analytics | pitcher_game_summary | 9,800+ | Rolling stats, season stats |
| mlb_analytics | pitcher_rolling_statcast | VIEW | Rolling SwStr%, velocity |
| mlb_predictions | pitcher_strikeouts | - | Production predictions |
| mlb_predictions | shadow_mode_predictions | - | V1.4 vs V1.6 comparison |

### Schema Additions (Session 58)
```sql
-- oddsa_pitcher_props
game_start_time TIMESTAMP,
minutes_before_tipoff INT64

-- pitcher_strikeouts
line_minutes_before_game INT64
```

---

## Model Features (V1.6)

### Original Features (f00-f44)
- Recent K performance (f00-f04)
- Season baseline (f05-f09)
- Context (f10-f18)
- Season SwStr% (f19a-c)
- Workload (f20-f24)
- Line-relative (f30-f32)
- BettingPros (f40-f44)

### NEW Rolling Statcast Features (f50-f53)
| Feature | Description | Backtest Result |
|---------|-------------|-----------------|
| f50_swstr_pct_last_3 | Per-game SwStr% (last 3 starts) | - |
| f51_fb_velocity_last_3 | Fastball velocity (last 3 starts) | Top 10 importance |
| f52_swstr_trend | Recent - season SwStr% | +3% = 54.6% OVER |
| f53_velocity_change | Season - recent velocity | Moderate signal |

---

## Red Flag System

### Hard Skip Rules
| Rule | Condition | Reason |
|------|-----------|--------|
| Currently on IL | Pitcher in bdl_injuries | No valid props |
| First Start | season_games = 0 | No data |
| Bullpen/Opener | ip_avg < 4.0 | Not starter |
| MLB Debut | career_starts < 2 | Too little data |

### Soft Multipliers (Backtest Validated)
| Rule | Condition | OVER Mult | UNDER Mult |
|------|-----------|-----------|------------|
| High Variance | k_std > 4 | 0.4x | 1.1x |
| Elite SwStr% | swstr > 12% | 1.1x | 0.8x |
| Low SwStr% | swstr < 8% | 0.85x | 1.05x |
| Hot Streak | trend > +3% | 1.08x | 0.92x |
| Cold Streak | trend < -3% | 0.92x | 1.05x |
| Short Rest + OVER | days_rest < 4 | 0.7x | - |
| High Workload + OVER | games_30d > 6 | 0.85x | - |

---

## Backfills Status

| Backfill | Status | Progress |
|----------|--------|----------|
| BettingPros Historical | Running | ~70% |
| Statcast 2025 | Complete | 2024-03-28 to 2025-06-28 |

---

## Key Files

### Training Scripts
```
scripts/mlb/training/
├── train_pitcher_strikeouts_classifier.py  # V1.4
├── train_v1_6_rolling.py                   # V1.6
└── walk_forward_validation.py              # Validation
```

### Prediction
```
predictions/mlb/
├── pitcher_strikeouts_predictor.py         # Main predictor (V1)
├── pitcher_strikeouts_predictor_v2.py      # CatBoost alternative
├── shadow_mode_runner.py                   # V1.4 vs V1.6 comparison (NEW)
├── pitcher_loader.py                       # Line queries with timing (NEW)
└── worker.py                               # Production worker
```

### Data Processing
```
data_processors/
├── raw/mlb/mlb_pitcher_props_processor.py  # Props with timing
└── grading/mlb/mlb_prediction_grading_processor.py  # + timing analysis
```

---

## Future Roadmap

### Short-term (1-2 Weeks)
1. **Complete shadow testing** - 7+ days of V1.4 vs V1.6 comparison
2. **Promote V1.6** if it outperforms (expected: 5-8% improvement)
3. **Analyze line timing** - Do closing lines predict better than early lines?
4. **Complete BettingPros backfill** - Historical line data for backtesting

### Medium-term (1-2 Months)
1. **Opening line capture** - Track line when first posted for movement analysis
2. **V1.7 with line movement** - Add `line_moved` feature (current - opening)
3. **Weather integration** - Test breaking ball x cold/humid hypothesis
4. **Umpire K-rate** - Add umpire strikeout tendency feature

### Long-term (3+ Months)
1. **Ensemble model** - Combine V1.4 + V1.6 + line movement
2. **Live velocity monitoring** - Alert if pitcher velocity drops mid-game
3. **Batter prop models** - Apply same approach to hits, HRs
4. **Cross-sport learnings** - Apply NBA model improvements to MLB

---

## Verification Commands

```bash
# Test V1.4 champion
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
p = PitcherStrikeoutsPredictor()
p.load_model()
print(f'V1.4: {p.model_metadata[\"model_id\"]}')
"

# Test V1.6 challenger
MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
p = PitcherStrikeoutsPredictor()
p.load_model()
print(f'V1.6: {p.model_metadata[\"model_id\"]}')
"

# Run shadow mode (dry run)
PYTHONPATH=. python predictions/mlb/shadow_mode_runner.py --dry-run

# Test pitcher loader
PYTHONPATH=. python predictions/mlb/pitcher_loader.py --date 2025-06-15

# Check shadow comparison
bq query --nouse_legacy_sql "SELECT * FROM mlb_predictions.shadow_daily_comparison"
```

---

## Session History

### Session 58 (Current)
1. **Created shadow mode runner** - V1.4 vs V1.6 parallel comparison
2. **Implemented line timing** - `line_minutes_before_game` full pipeline
3. **Applied schema updates** - BigQuery tables for timing and shadow
4. **Created pitcher loader** - Timing-aware line queries
5. **Added timing analysis** - Grading processor methods

### Session 57
1. **Fixed Critical Bug**: Statcast name format
2. **Validated Signals**: SwStr% trend backtest
3. **Added Rolling Features**: f50-f53
4. **Trained V1.6**: 63.25% test accuracy
5. **Champion-Challenger Setup**: Environment variable switching
