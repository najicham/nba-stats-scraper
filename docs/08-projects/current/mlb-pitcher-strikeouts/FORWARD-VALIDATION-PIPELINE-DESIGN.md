# Forward Validation Pipeline Design

**Created:** 2026-01-13
**Status:** Design Phase - Ready for Implementation

## Purpose

The forward validation pipeline tracks MLB pitcher strikeout predictions in real-time,
comparing them against actual betting lines and results to measure ongoing model performance.

This differs from historical backfill in that it:
- Captures lines at prediction time (not retroactively)
- Tracks line movement between prediction and game time
- Enables real-time performance monitoring
- Supports live betting decisions

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FORWARD VALIDATION PIPELINE                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │ Daily Odds   │───>│ Prediction   │───>│ Results Grading      │  │
│  │ Collector    │    │ Tracker      │    │ (Post-Game)          │  │
│  └──────────────┘    └──────────────┘    └──────────────────────┘  │
│         │                   │                      │                │
│         v                   v                      v                │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    BigQuery Tables                            │  │
│  │  • mlb_raw.oddsa_pitcher_props (live lines)                  │  │
│  │  • mlb_predictions.pitcher_strikeouts_tracked                │  │
│  │  • mlb_analytics.forward_validation_results                  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                    Monitoring Dashboard                       │  │
│  │  • Rolling 7-day hit rate                                    │  │
│  │  • ROI tracking                                              │  │
│  │  • Alert on performance degradation                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Daily Odds Collector

**Schedule:** Every 30 minutes, 8 AM - 8 PM ET on game days

**Function:**
- Fetch current pitcher strikeout lines from Odds API
- Store snapshots with timestamps
- Track line movement over time

**Output Table:** `mlb_raw.oddsa_pitcher_props`

**Key Fields:**
- `snapshot_time` - When line was captured
- `game_date` - Game date
- `player_lookup` - Normalized pitcher name
- `point` - Strikeout line
- `over_price` / `under_price` - Odds
- `bookmaker` - Source bookmaker

### 2. Prediction Tracker

**Trigger:** After daily predictions are generated

**Function:**
- Capture prediction at generation time
- Record current betting line at prediction time
- Calculate predicted edge
- Determine recommendation (OVER/UNDER/PASS)

**Output Table:** `mlb_predictions.pitcher_strikeouts_tracked`

**Schema:**
```sql
CREATE TABLE mlb_predictions.pitcher_strikeouts_tracked (
    -- Keys
    game_date DATE NOT NULL,
    pitcher_lookup STRING NOT NULL,
    prediction_timestamp TIMESTAMP NOT NULL,

    -- Prediction
    predicted_strikeouts FLOAT64,
    recommendation STRING,  -- OVER, UNDER, PASS

    -- Line at prediction time
    line_at_prediction FLOAT64,
    line_source STRING,

    -- Calculated edge
    edge_at_prediction FLOAT64,

    -- For CLV analysis (filled post-game)
    closing_line FLOAT64,

    -- Grading (filled post-game)
    actual_strikeouts INT64,
    is_correct BOOL,

    -- Metadata
    processed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY pitcher_lookup, recommendation;
```

### 3. Results Grader

**Schedule:** Daily, 6 AM ET (after all West Coast games complete)

**Function:**
- Fetch actual strikeouts from Ball Don't Lie API
- Compare predictions to results
- Grade OVER/UNDER outcomes
- Calculate closing line value (CLV)

**Process:**
1. Get yesterday's tracked predictions
2. Fetch actual strikeouts for each game
3. Update `is_correct` field
4. Calculate CLV if closing line available

### 4. Performance Monitor

**Schedule:** Real-time + Daily summary

**Metrics:**
- Rolling 7-day hit rate
- Rolling 30-day hit rate
- ROI at standard -110 odds
- CLV (Closing Line Value)
- Edge decay analysis

**Alerts:**
- Hit rate drops below 50% over 50+ bets
- 5+ consecutive losses
- Significant edge degradation

## Implementation Plan

### Phase 1: Basic Pipeline (Week 1)

```bash
# Scripts to create
scripts/mlb/forward_validation/
├── track_daily_predictions.py      # Capture predictions with lines
├── grade_results.py                 # Grade after games complete
└── calculate_rolling_stats.py       # Performance metrics
```

### Phase 2: Monitoring (Week 2)

```bash
scripts/mlb/forward_validation/
├── monitor_performance.py           # Alert system
└── generate_daily_report.py         # Email/Slack report
```

### Phase 3: Dashboard (Week 3)

- Looker Studio dashboard
- Real-time hit rate chart
- ROI tracker
- Pitcher-level performance

## Data Flow

### Morning (9 AM ET)

1. Predictions generated for today's games
2. `track_daily_predictions.py` captures:
   - Each prediction
   - Current betting line
   - Calculated edge
   - Recommendation

### Throughout Day

1. Odds collector captures line movement
2. Track opening → closing line changes

### Next Morning (6 AM ET)

1. `grade_results.py` runs:
   - Fetches actual strikeouts
   - Grades each prediction
   - Updates tracked predictions table

### Continuous

1. `calculate_rolling_stats.py`:
   - Updates rolling hit rates
   - Calculates ROI
   - Triggers alerts if needed

## Key Queries

### Rolling Hit Rate

```sql
SELECT
    DATE_TRUNC(game_date, WEEK) as week,
    COUNT(*) as total_bets,
    SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) / COUNT(*) * 100, 1) as hit_rate
FROM mlb_predictions.pitcher_strikeouts_tracked
WHERE recommendation IN ('OVER', 'UNDER')
  AND is_correct IS NOT NULL
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1
ORDER BY 1 DESC;
```

### CLV Analysis

```sql
SELECT
    CASE
        WHEN closing_line > line_at_prediction THEN 'Got Better Line'
        WHEN closing_line < line_at_prediction THEN 'Line Moved Against'
        ELSE 'No Movement'
    END as clv_status,
    COUNT(*) as count,
    AVG(CASE WHEN is_correct THEN 1.0 ELSE 0.0 END) as hit_rate
FROM mlb_predictions.pitcher_strikeouts_tracked
WHERE closing_line IS NOT NULL
GROUP BY 1;
```

## Success Criteria

### Minimum Requirements

- [ ] Daily predictions tracked with lines
- [ ] Results graded within 24 hours
- [ ] Rolling stats available
- [ ] Basic alerting operational

### Stretch Goals

- [ ] Real-time line tracking
- [ ] CLV analysis
- [ ] Pitcher-level dashboard
- [ ] Automated bet recommendations

## Dependencies

### External APIs

1. **Odds API** - Live betting lines ($500/month for MLB)
2. **Ball Don't Lie** - Game results (free tier sufficient)

### Internal Systems

1. Prediction pipeline (exists)
2. BigQuery infrastructure (exists)
3. Cloud Scheduler (exists)

## Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Phase 1 | 3-5 days | Basic tracking + grading |
| Phase 2 | 2-3 days | Monitoring + alerts |
| Phase 3 | 3-5 days | Dashboard |

**Total:** 8-13 days for full implementation

## Next Steps

1. Create BigQuery tables for forward validation
2. Implement `track_daily_predictions.py`
3. Implement `grade_results.py`
4. Set up Cloud Scheduler jobs
5. Create Looker Studio dashboard

## Related Documentation

- `PLAYER-NAME-MATCHING-GUIDE.md` - Name normalization
- `ENHANCED-ANALYSIS-SCRIPTS.md` - Historical analysis
- `EXECUTION-PLAN-PHASES-2-5.md` - Backfill execution plan
