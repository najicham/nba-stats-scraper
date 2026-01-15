# Session 53 Complete Handoff: SwStr% & Red Flags Implementation

**Date**: 2026-01-15
**Duration**: ~2 hours
**Focus**: Implemented FanGraphs SwStr% features and red flag filter system
**Status**: Both features complete and integrated

---

## Executive Summary

This session implemented two major improvements to the MLB pitcher strikeouts prediction system:

1. **SwStr% Features** - Season-level swinging strike rate from FanGraphs
2. **Red Flag System** - Hard skips and soft confidence reducers

### Performance Impact

| Metric | Baseline | With SwStr% | Improvement |
|--------|----------|-------------|-------------|
| Overall Hit Rate | 55.5% | 56.2% | +0.7% |
| High Confidence | 59.2% | 60.0% | +0.8% |
| Very High Over | 60.7% | 62.5% | +1.8% |

Red flag system not yet validated (needs historical backtest).

---

## Part 1: SwStr% Implementation

### What Was Built

#### 1.1 FanGraphs Data Pipeline

**New Table**: `mlb_raw.fangraphs_pitcher_season_stats`
```sql
-- Key columns:
swstr_pct NUMERIC(5,4)    -- Swinging strike % (key predictor!)
csw_pct NUMERIC(5,4)      -- Called Strike + Whiff %
o_swing_pct NUMERIC(5,4)  -- Chase rate
contact_pct NUMERIC(5,4)  -- Contact rate
k_pct NUMERIC(5,3)        -- Strikeout percentage
```

**Backfill Script**: `scripts/mlb/backfill_fangraphs_stats.py`
- Uses `pybaseball.pitching_stats()` function
- Fetches from FanGraphs (free, no API key needed)
- 1,704 pitchers backfilled (2024-2025)

#### 1.2 Analytics Integration

**Modified**: `data_processors/analytics/mlb/pitcher_game_summary_processor.py`

Added FanGraphs CTE:
```sql
fangraphs_stats AS (
    SELECT DISTINCT player_lookup, season_year, swstr_pct, csw_pct, ...
    FROM mlb_raw.fangraphs_pitcher_season_stats
    WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM ...)
)
```

Added JOIN (with name normalization):
```sql
LEFT JOIN fangraphs_stats fg
    ON REPLACE(h.player_lookup, '_', '') = fg.player_lookup
    AND h.season_year = fg.season_year
```

**New Columns in pitcher_game_summary**:
- `season_swstr_pct`
- `season_csw_pct`
- `season_chase_pct`
- `season_contact_pct`

**Backfill Query** (already run):
```sql
MERGE mlb_analytics.pitcher_game_summary pgs
USING (deduped fangraphs data) fg
ON REPLACE(pgs.player_lookup, '_', '') = fg.player_lookup
  AND pgs.season_year = fg.season_year
WHEN MATCHED THEN UPDATE SET
  season_swstr_pct = CAST(fg.swstr_pct AS NUMERIC), ...
```

**Result**: 9,028 rows updated (92% coverage)

#### 1.3 Training Scripts Updated

**Modified Files**:
- `scripts/mlb/training/train_pitcher_strikeouts_classifier.py`
- `scripts/mlb/training/walk_forward_validation.py`

**New Features Added**:
```python
'f19_season_swstr_pct'    # Swinging strike %
'f19b_season_csw_pct'     # Called Strike + Whiff % (MOST IMPORTANT!)
'f19c_season_chase_pct'   # Chase rate
```

**Key Finding**: CSW% ranked #2 in feature importance (4.2%)

---

## Part 2: Red Flag System

### What Was Built

#### 2.1 RedFlagResult Class

**File**: `predictions/mlb/pitcher_strikeouts_predictor.py`

```python
class RedFlagResult:
    """Result of red flag evaluation"""
    def __init__(
        self,
        skip_bet: bool = False,
        confidence_multiplier: float = 1.0,
        flags: list = None,
        skip_reason: str = None
    ):
        ...
```

#### 2.2 Red Flag Rules Implemented

**HARD SKIP (do not bet)**:
| Rule | Condition | Reason |
|------|-----------|--------|
| First Start | `is_first_start=True` OR `season_games_started=0` | No historical data |
| Bullpen/Opener | `ip_avg_last_5 < 4.0` | Not a traditional starter |
| MLB Debut | `rolling_stats_games < 2` | Too little career data |

**SOFT REDUCE (confidence multiplier)**:
| Rule | Condition | Multiplier | Applies To |
|------|-----------|------------|------------|
| Early Season | `season_games_started < 3` | 0.7x | All bets |
| Extreme Variance | `k_std_last_10 > 5` | 0.6x | All bets |
| High Variance | `k_std_last_10 > 4` | 0.8x | All bets |
| Short Rest | `days_rest < 4` | 0.7x | OVER only |
| High Workload | `games_last_30_days > 6` | 0.85x | OVER only |
| Low SwStr% | `season_swstr_pct < 0.08` | 0.8x | OVER only |

#### 2.3 Integration

The `predict()` method now:
1. Calculates base prediction and confidence
2. Checks red flags
3. If hard skip → returns `recommendation: 'SKIP'`
4. If soft flags → multiplies confidence, may change recommendation to PASS

**New Fields in Prediction Output**:
```python
{
    'recommendation': 'OVER' | 'UNDER' | 'PASS' | 'SKIP',
    'confidence': 65.0,          # Adjusted confidence
    'base_confidence': 85.0,     # Before red flag adjustment
    'red_flags': ['REDUCE: Early season (2 starts)'],
    'confidence_multiplier': 0.7,
    'skip_reason': 'First start of season - no historical data'  # if SKIP
}
```

---

## Part 3: Files Changed

### Created
| File | Purpose |
|------|---------|
| `schemas/bigquery/mlb_raw/fangraphs_pitcher_season_stats_tables.sql` | BigQuery schema for FanGraphs data |
| `scripts/mlb/backfill_fangraphs_stats.py` | Backfill FanGraphs data via pybaseball |
| `docs/08-projects/current/mlb-pitcher-strikeouts/PHASE1-IMPLEMENTATION-PLAN.md` | Implementation plan |
| `docs/09-handoff/2026-01-15-SESSION-53-HANDOFF.md` | Initial handoff (partial) |

### Modified
| File | Changes |
|------|---------|
| `data_processors/analytics/mlb/pitcher_game_summary_processor.py` | Added FanGraphs CTE, JOIN, new columns |
| `schemas/bigquery/mlb_analytics/pitcher_game_summary_tables.sql` | Added SwStr% columns |
| `scripts/mlb/training/train_pitcher_strikeouts_classifier.py` | Added f19_swstr features |
| `scripts/mlb/training/walk_forward_validation.py` | Added f19_swstr features |
| `predictions/mlb/pitcher_strikeouts_predictor.py` | Added RedFlagResult class, _check_red_flags(), integrated into predict() |

---

## Part 4: Commands Reference

```bash
# 1. Backfill FanGraphs data (already done)
PYTHONPATH=. python scripts/mlb/backfill_fangraphs_stats.py --seasons 2024 2025

# 2. Update pitcher_game_summary with SwStr% (already done via MERGE)
# See BigQuery query in Part 1.2

# 3. Train classifier with new features
PYTHONPATH=. python scripts/mlb/training/train_pitcher_strikeouts_classifier.py

# 4. Run walk-forward validation
PYTHONPATH=. python scripts/mlb/training/walk_forward_validation.py

# 5. Test predictor with red flags
PYTHONPATH=. python -c "
from predictions.mlb.pitcher_strikeouts_predictor import PitcherStrikeoutsPredictor

predictor = PitcherStrikeoutsPredictor()

# Test with early season pitcher
features = {
    'k_avg_last_5': 6.0,
    'season_games_started': 2,
    'ip_avg_last_5': 5.5,
    'season_swstr_pct': 0.10,
    'k_std_last_10': 2.5,
    'days_rest': 5,
}
result = predictor.predict('test_pitcher', features, strikeouts_line=5.5)
print(result)
"
```

---

## Part 5: Future Feature Wishlist

### HIGH PRIORITY - Need Data First

| Feature | Description | Why Important | Data Needed |
|---------|-------------|---------------|-------------|
| **Rolling SwStr%** | 3/5-game SwStr% vs season baseline | Catches "unlucky" pitchers with elite stuff but bad recent results | Per-game statcast data |
| **Velocity Trends** | FB velocity vs season baseline | Early injury/fatigue detection, market adjusts late | Per-game velocity from statcast |
| **IL Return Detection** | First start after IL stint | High variance, pitch count limits | Injuries table (currently empty) |
| **Line Movement** | Opening line vs current line | Detect sharp money disagreeing with model | Opening line capture |

### MEDIUM PRIORITY - Can Implement Soon

| Feature | Description | Why Important | Data Status |
|---------|-------------|---------------|-------------|
| **Weather x Breaking Ball** | Cold weather + high breaking ball % | Physics-based (cold reduces spin/movement) | Need weather API integration |
| **Umpire K-Rate** | Umpire's historical K/9 | Table stakes, but interactions add value | UmpScorecards scraper needed |
| **Opponent 7-Day Trend** | Team K-rate last 7 days vs season | Teams go through slumps | Derivable from batter_game_summary |

### LOWER PRIORITY - Future

| Feature | Description | Why Important |
|---------|-------------|---------------|
| **Actual Lineup K-Rates** | Calculate K expectation from actual 9 batters | Timing edge (lineups 2-3hr pre-game) |
| **Catcher Framing** | Elite framers steal called strikes | +0.3-0.5 K effect |
| **2026 Challenge Rule** | Ball/strike challenges reduce umpire impact | Downweight umpire features in 2026 |

### Rolling SwStr% Implementation Notes

The key edge from rolling SwStr% is identifying **regression candidates**:

```python
# Pitcher with elite stuff but bad recent results
if swstr_last_3 > 0.13 and k_avg_last_3 < betting_line:
    signal = "VALUE_OVER"  # Great stuff, likely to regress upward

# Pitcher with declining stuff but good recent results
if swstr_delta < -0.02 and k_avg_last_3 >= betting_line:
    signal = "FADE_OVER"  # Weakening stuff, expect regression down
```

**Implementation Path**:
1. Use pybaseball `statcast_pitcher()` to get pitch-level data
2. Aggregate per-game: swinging_strikes / total_pitches
3. Store in new table: `mlb_raw.statcast_pitcher_game_stats`
4. Calculate rolling stats in pitcher_game_summary processor

**Challenge**: pybaseball is slow for bulk data. Would need ~9,000 API calls for 2024-2025 backfill.

---

## Part 6: Validation TODO

The red flag system needs validation:

### Backtest Required
1. Query historical predictions where red flags would have triggered
2. Compare hit rate on skipped bets vs bets taken
3. Expected: Skipped bets should have <50% hit rate

### Validation Query (to run)
```sql
SELECT
  -- Check: What % of bets would be skipped?
  COUNTIF(is_first_start OR season_games_started = 0 OR ip_avg_last_5 < 4.0) as would_skip,
  COUNT(*) as total,

  -- Check: Hit rate on "would skip" bets
  AVG(CASE
    WHEN is_first_start OR season_games_started = 0 OR ip_avg_last_5 < 4.0
    THEN IF(strikeouts > strikeouts_line, 1.0, 0.0)
  END) as skip_bet_hit_rate,

  -- Check: Hit rate on kept bets
  AVG(CASE
    WHEN NOT (is_first_start OR season_games_started = 0 OR ip_avg_last_5 < 4.0)
    THEN IF(strikeouts > strikeouts_line, 1.0, 0.0)
  END) as kept_bet_hit_rate

FROM mlb_analytics.pitcher_game_summary
WHERE strikeouts_line IS NOT NULL
  AND game_date >= '2024-01-01'
```

**Expected Results**:
- Skip 5-15% of bets
- Skip bet hit rate < 48%
- Kept bet hit rate > skip bet hit rate

---

## Part 7: Known Issues / Technical Debt

### Name Matching
Different systems use different name formats:
- `mlb_pitcher_stats`: `merrill_kelly` (underscores)
- `fangraphs`: `merrillkelly` (no underscores)
- `bp_pitcher_props`: `merrillkelly` (no underscores)

**Solution Applied**: `REPLACE(player_lookup, '_', '')` in JOINs

**Better Solution (future)**: Use `universal_player_id` from registry consistently

### FanGraphs Data is Season-Level
Current SwStr% is season aggregate, not rolling.
- Captures "this pitcher has elite stuff"
- Does NOT capture "this pitcher's stuff is declining recently"

Rolling SwStr% (per-game) would catch the regression signal.

### Injuries Table Empty
`mlb_raw.bdl_injuries` has schema but 0 rows.
- Cannot detect IL returns
- Need to populate via Ball Don't Lie API injuries endpoint

---

## Part 8: Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA FLOW                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │
│  │  FanGraphs   │     │ Ball Don't   │     │ BettingPros  │        │
│  │  (pybaseball)│     │   Lie API    │     │    API       │        │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘        │
│         │                    │                    │                │
│         ▼                    ▼                    ▼                │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐        │
│  │ fangraphs_   │     │mlb_pitcher_  │     │bp_pitcher_   │        │
│  │ pitcher_     │     │   stats      │     │   props      │        │
│  │ season_stats │     │              │     │              │        │
│  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘        │
│         │                    │                    │                │
│         └────────────┬───────┴────────────────────┘                │
│                      │                                             │
│                      ▼                                             │
│              ┌──────────────────┐                                  │
│              │  pitcher_game_   │  ◄─── Phase 3 Analytics          │
│              │     summary      │       - Rolling K stats          │
│              │                  │       - Season stats             │
│              │  + SwStr% cols   │       - SwStr% (NEW!)            │
│              └────────┬─────────┘                                  │
│                       │                                            │
│                       ▼                                            │
│              ┌──────────────────┐                                  │
│              │  Predictor       │  ◄─── Phase 5 Predictions        │
│              │  (XGBoost +      │       - Model prediction         │
│              │   Red Flags)     │       - Red flag check (NEW!)    │
│              │                  │       - Confidence adjustment    │
│              └────────┬─────────┘                                  │
│                       │                                            │
│                       ▼                                            │
│              ┌──────────────────┐                                  │
│              │   Output:        │                                  │
│              │   - prediction   │                                  │
│              │   - confidence   │                                  │
│              │   - recommendation│                                 │
│              │   - red_flags    │                                  │
│              │   - skip_reason  │                                  │
│              └──────────────────┘                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part 9: Environment Requirements

```bash
# Required packages
pip install pybaseball      # For FanGraphs data
pip install xgboost         # For model
pip install pandas numpy    # Data processing
pip install google-cloud-bigquery google-cloud-storage  # GCP

# Environment variables
export SPORT=mlb            # For sport config
export GCP_PROJECT_ID=nba-props-platform
```

---

## Part 10: Next Session Priorities

### 1. Validate Red Flags (HIGHEST PRIORITY)
Run backtest query to confirm red flags actually improve performance.

### 2. Rolling SwStr% (HIGH PRIORITY - HIGH EFFORT)
- Requires per-game statcast backfill
- ~9,000 API calls
- Consider incremental approach: 2025 season only first

### 3. Populate Injuries Table (MEDIUM PRIORITY)
- Enable IL return detection
- Need to run injuries scraper

### 4. Deploy to Production (MEDIUM PRIORITY)
- Current predictor has red flags but isn't deployed
- Need to update production model path

---

## Checklist

- [x] FanGraphs data backfilled (1,704 pitchers)
- [x] pitcher_game_summary updated with SwStr% (9,028 rows)
- [x] Training scripts updated with SwStr% features
- [x] Walk-forward validation run (56.2% / 60.0% high conf)
- [x] Red flag system implemented in predictor
- [x] Hard skip rules: first start, bullpen, debut
- [x] Soft rules: early season, variance, short rest, workload, low SwStr%
- [ ] Red flag backtest validation
- [ ] Rolling SwStr% (needs per-game data)
- [ ] Velocity trends (needs per-game data)
- [ ] Production deployment

---

**Session 53 Complete**

*Total Lines of Code Changed: ~400*
*New Features: 2 (SwStr%, Red Flags)*
*Performance Lift: +0.8% on high confidence bets*
