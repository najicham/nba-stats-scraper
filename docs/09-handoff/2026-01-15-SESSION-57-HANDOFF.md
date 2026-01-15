# Session 57 Handoff: V1.6 Challenger Model Complete

**Date**: 2026-01-15
**Focus**: Rolling Statcast Features + Champion-Challenger Setup
**Status**: V1.6 challenger trained and deployed to GCS

---

## Quick Start for New Chat

```bash
# Read this handoff
cat docs/09-handoff/2026-01-15-SESSION-57-HANDOFF.md

# Check current status
cat docs/08-projects/current/mlb-pitcher-strikeouts/CURRENT-STATUS.md

# Test V1.6 model loads
MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
p = PitcherStrikeoutsPredictor()
p.load_model()
print(f'V1.6 loaded: {p.model_metadata[\"model_id\"]}')
print(f'Accuracy: {p.model_metadata[\"test_accuracy\"]*100:.1f}%')
"
```

---

## What Was Accomplished (Session 57)

### 1. Fixed Critical Name Format Bug
- **Issue**: Statcast data had `lastname__firstname` format (e.g., `greene__hunter`)
- **Root Cause**: pybaseball returns "Lastname, Firstname" format
- **Fix**: Updated `normalize_name()` in `scripts/mlb/backfill_statcast_game_stats.py`
- **Result**: 39,918 records fixed, rolling view now JOINs correctly

### 2. Backtest Validated New Signals
| Signal | Games | Finding | Action |
|--------|-------|---------|--------|
| Velocity Drop >2.5mph | 4 | Too rare | Skipped |
| **SwStr% Trend +3%** | 381 | **54.6% OVER** | Added to predictor |
| **SwStr% Trend -3%** | 315 | **49.8% UNDER** | Added to predictor |

### 3. Added Rolling Features to Training
New features in walk-forward validation and V1.6 training:
- `f50_swstr_pct_last_3` - Per-game SwStr%
- `f51_fb_velocity_last_3` - Recent fastball velocity
- `f52_swstr_trend` - Hot/cold streak indicator
- `f53_velocity_change` - Velocity drop signal

### 4. Trained V1.6 Challenger Model
| Metric | V1.4 Champion | V1.6 Challenger |
|--------|---------------|-----------------|
| Test Hit Rate | ~55% | **63.25%** |
| Very High OVER (>65%) | ~62% | **82.2%** |
| High Conf OVER (>60%) | ~60% | **75.8%** |
| High Conf UNDER (<40%) | ~55% | **68.8%** |

### 5. Champion-Challenger Setup
```bash
# Default (V1.4 champion)
# No changes needed

# Enable V1.6 challenger
export MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json
```

---

## Files Modified

| File | Changes |
|------|---------|
| `scripts/mlb/backfill_statcast_game_stats.py` | Fixed `normalize_name()` for pybaseball format |
| `scripts/mlb/training/walk_forward_validation.py` | Added statcast_rolling CTE, 4 new features |
| `scripts/mlb/training/train_v1_6_rolling.py` | NEW: V1.6 training script |
| `predictions/mlb/pitcher_strikeouts_predictor.py` | Added env var support, SwStr% trend red flag |
| `docs/08-projects/.../CURRENT-STATUS.md` | Updated with V1.6 info |

---

## GCS Artifacts

```
gs://nba-scraped-data/ml-models/mlb/
├── mlb_pitcher_strikeouts_v1_4features_20260114_142456.json        # Champion
├── mlb_pitcher_strikeouts_v1_4features_20260114_142456_metadata.json
├── mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json        # Challenger (NEW)
└── mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149_metadata.json
```

---

## Background Tasks

### BettingPros Historical Backfill
- **Status**: Running (task `b77281f`)
- **Progress**: ~65% (5322/8140)
- **Monitor**: `tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output`

---

## Next Session Priorities

### HIGH PRIORITY

#### 1. Deploy V1.6 as Challenger in Production
- Update Cloud Function environment variable
- Run both models in parallel
- Track predictions with `model_version` field

#### 2. Add `line_minutes_before_game` for MLB
Follow NBA pattern from `predictions/coordinator/player_loader.py`:
```python
# NBA already has this - implement for MLB
line_minutes_before_game = (game_start - snapshot_time).total_seconds() / 60
```

This enables:
- Closing line analysis (< 60 min = sharper)
- Early line value detection (> 360 min = more edge potential)

#### 3. Monitor V1.6 Performance
- Run for 7+ days alongside V1.4
- Compare hit rates in production
- Promote to champion if outperforms

### MEDIUM PRIORITY

#### 4. Complete BettingPros Historical Backfill
- Let background task finish (~35% remaining)
- Will enable deeper backtesting across more seasons

#### 5. Update Main Training Script
- `train_pitcher_strikeouts_classifier.py` still missing rolling features
- V1.6 training script has them, but main script should too for consistency

#### 6. Opening Line Capture
- Track line when first captured
- Track line movement (current - opening)
- Strong signals: line moved >1.0 K in either direction

### LOWER PRIORITY

#### 7. Weather x Breaking Ball
- Need weather API integration
- Hypothesis: Breaking balls less effective in cold/humid conditions

#### 8. Umpire K-Rate
- Need UmpScorecards scraper
- Some umps have significantly higher/lower K rates

---

## Data Model Reference

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     MLB STRIKEOUTS V1.6 DATA FLOW                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────────┐     ┌──────────────┐            │
│  │  FanGraphs   │     │  pybaseball      │     │ Ball Don't   │            │
│  │  (season)    │     │  (per-game)      │     │   Lie API    │            │
│  └──────┬───────┘     └──────┬───────────┘     └──────┬───────┘            │
│         │                    │                        │                     │
│         ▼                    ▼                        ▼                     │
│  ┌──────────────┐     ┌──────────────────┐     ┌──────────────┐            │
│  │ fangraphs_   │     │statcast_pitcher_ │     │bdl_pitcher_  │            │
│  │ pitcher_     │     │  game_stats      │     │   stats      │            │
│  │ season_stats │     │  (39,918 rows)   │     │              │            │
│  │ (1,704)      │     └──────┬───────────┘     └──────┬───────┘            │
│  └──────┬───────┘            │                        │                     │
│         │                    ▼                        │                     │
│         │            ┌──────────────────┐             │                     │
│         │            │pitcher_rolling_  │             │                     │
│         │            │statcast (VIEW)   │             │                     │
│         │            │ - swstr_last_3   │             │                     │
│         │            │ - fb_velo_last_3 │             │                     │
│         │            │ - swstr_trend    │             │                     │
│         │            └──────┬───────────┘             │                     │
│         │                   │                         │                     │
│         └─────────┬─────────┴─────────────────────────┘                     │
│                   │                                                         │
│                   ▼                                                         │
│           ┌──────────────────┐                                              │
│           │  pitcher_game_   │                                              │
│           │     summary      │                                              │
│           │  + rolling stats │                                              │
│           └────────┬─────────┘                                              │
│                    │                                                        │
│                    ▼                                                        │
│           ┌──────────────────┐     ┌──────────────────┐                    │
│           │    V1.6 Model    │     │   Red Flags      │                    │
│           │  (35 features)   │────▶│  - IL check      │                    │
│           │  - f50-f53 NEW   │     │  - SwStr% trend  │                    │
│           └──────────────────┘     │  - High variance │                    │
│                                    └──────────────────┘                    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Commands

```bash
# Test V1.6 model
MLB_PITCHER_STRIKEOUTS_MODEL_PATH=gs://nba-scraped-data/ml-models/mlb/mlb_pitcher_strikeouts_v1_6_rolling_20260115_131149.json \
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor
p = PitcherStrikeoutsPredictor()
p.load_model()
print('Model:', p.model_metadata['model_id'])
print('Features:', p.model_metadata['feature_count'])
"

# Run walk-forward validation
PYTHONPATH=. python scripts/mlb/training/walk_forward_validation.py

# Check rolling view data
bq query --nouse_legacy_sql "
SELECT
  COUNT(*) as total,
  COUNT(CASE WHEN swstr_pct_last_3 IS NOT NULL THEN 1 END) as with_swstr,
  COUNT(CASE WHEN fb_velocity_last_3 IS NOT NULL THEN 1 END) as with_velo
FROM mlb_analytics.pitcher_rolling_statcast
WHERE statcast_games_count >= 3
"

# Monitor BettingPros backfill
tail -f /tmp/claude/-home-naji-code-nba-stats-scraper/tasks/b77281f.output
```

---

## Session 57 Summary

1. **Fixed critical bug** enabling rolling features integration
2. **Backtest validated** SwStr% trend as strongest new signal
3. **Trained V1.6** achieving 82.2% on very high confidence OVER
4. **Set up champion-challenger** with easy environment variable switching
5. **Updated documentation** with current state

**Key Result**: V1.6 challenger ready for production testing with significant improvement over V1.4 champion.

---

## Ideas for Future Sessions

1. **A/B Test V1.6 vs V1.4** in production for 7+ days
2. **Line timing feature** (`line_minutes_before_game`) - proven valuable in NBA
3. **Ensemble approach**: Combine V1.4 + V1.6 predictions
4. **Batter prop models**: Apply similar rolling features approach
5. **Real-time velocity monitoring**: Alert if pitcher velocity drops mid-game
6. **Cross-sport learnings**: What from NBA model improves MLB?

---

**Session 57 Handoff Complete**
