# Comprehensive Data Flow Documentation

**Last Updated**: 2026-02-02
**Purpose**: End-to-end data pipeline documentation
**Audience**: Developers, DevOps, Data Engineers

---

## Overview

The NBA Props Platform processes data through 5 phases from raw scraping to ML predictions.

```
Phase 1: Scraping ──▶ Phase 2: Raw Processing ──▶ Phase 3: Analytics ──▶
                                                                         │
Phase 5: Predictions ◀─── Phase 4: Precompute ◀────────────────────────┘
```

---

## Phase 1: Data Scraping

### Sources & Frequency

| Source | Data Type | Frequency | Service |
|--------|-----------|-----------|---------|
| NBA.com | Schedule, rosters, boxscores | Every 30 min | nba-scrapers |
| BettingPros | Betting lines | Every hour | nba-scrapers |
| Basketball Reference | Historical stats | Daily | nba-scrapers |
| BigDataBall | Play-by-play | Post-game | nba-scrapers |
| ESPN | Scoreboard, rosters | Every 30 min | nba-scrapers |

### Output Tables (Phase 1)

```
nba_raw.nbac_schedule              # Games schedule
nba_raw.nbac_player_boxscores      # Live game stats
nba_raw.nbac_gamebook_player_stats # Official stats (PDF)
nba_raw.bettingpros_player_points_props  # Betting lines
nba_raw.bigdataball_play_by_play   # Shot locations
nba_raw.espn_scoreboard            # Real-time scores
```

---

## Phase 2: Raw Data Processing

### Purpose
Transform raw scraped data into normalized, validated tables.

### Processors

| Processor | Input | Output | Frequency |
|-----------|-------|--------|-----------|
| ScheduleProcessor | nbac_schedule | nba_reference.nba_schedule | 15 min |
| BoxscoreProcessor | nbac_player_boxscores | nba_reference.player_boxscores | 30 min |
| PlayByPlayProcessor | bigdataball_play_by_play | nba_reference.play_by_play | Post-game |

### Data Quality Checks

```python
class RawDataValidator:
    def validate(self, record):
        # 1. Required fields present
        # 2. Data types correct
        # 3. Value ranges valid
        # 4. Referential integrity
        # 5. Duplicate detection
```

### Output Schema Example

```sql
-- nba_reference.nba_schedule (cleaned schedule)
CREATE TABLE nba_reference.nba_schedule AS SELECT
    game_id STRING,
    game_date DATE,
    home_team_tricode STRING,
    away_team_tricode STRING,
    game_status INT64,  -- 1=Scheduled, 2=InProgress, 3=Final
    home_score INT64,
    away_score INT64,
    processed_at TIMESTAMP
FROM nba_raw.nbac_schedule
WHERE game_date >= partition_filter;
```

---

## Phase 3: Analytics Processing

### Purpose
Aggregate and enrich data with advanced analytics.

### Critical Processor: PlayerGameSummaryProcessor

**Input Tables**:
- `nba_raw.nbac_gamebook_player_stats` (gold standard)
- `nba_raw.nbac_player_boxscores` (fallback for evening)
- `nba_raw.bigdataball_play_by_play` (shot zones)

**Output**: `nba_analytics.player_game_summary`

**Processing Logic**:
```
1. Source Selection:
   └─ Try nbac_gamebook_player_stats (PDF-sourced)
      └─ Fallback to nbac_player_boxscores if not available
         └─ Skip if neither available

2. Shot Zone Enrichment:
   └─ Join with bigdataball_play_by_play
   └─ Calculate paint/mid/three attempt rates
   └─ Set has_complete_shot_zones flag

3. Quality Validation:
   └─ Check minutes_played > 0
   └─ Validate stat ranges (points ≥ 0, etc.)
   └─ Flag suspicious values

4. Write to BigQuery:
   └─ Batch write (no single-row inserts)
   └─ Update processed_at timestamp
   └─ Emit Firestore heartbeat
```

**Evening Processing** (Session 73):
- Runs at 6 PM, 10 PM, 1 AM ET
- Uses boxscore fallback for same-night analytics
- Enables next-day predictions 12 hours earlier

**Example Output**:
```json
{
  "player_lookup": "jokic_nikola",
  "game_date": "2026-02-01",
  "points": 27,
  "rebounds": 14,
  "assists": 10,
  "minutes_played": 36,
  "has_complete_shot_zones": true,
  "paint_attempts": 12,
  "mid_range_attempts": 3,
  "three_attempts_pbp": 6,
  "primary_source_used": "nbac_gamebook"
}
```

---

## Phase 4: Precompute & Feature Engineering

### Purpose
Generate ML features and aggregations for predictions.

### Critical Processor: VegasLineSummaryProcessor

**Data Flow**:
```
bettingpros_player_points_props (raw)
        │
        ▼
VegasLineSummaryProcessor
        │ (Aggregates lines from multiple sportsbooks)
        ▼
vegas_line_summary
        │ (line_source: ACTUAL_PROP or NO_PROP_LINE)
        ▼
ML Feature Store Builder
        │ (Extracts vegas_points_line as feature[25])
        ▼
ml_feature_store_v2
        │ (33 features per player-game)
        ▼
Prediction Worker
```

**Vegas Line Processing**:
```python
# Aggregate multiple sportsbook lines
SELECT
  player_lookup,
  game_date,
  AVG(points_line) as consensus_line,
  COUNT(DISTINCT sportsbook) as num_books,
  STDDEV(points_line) as line_variance,
  'ACTUAL_PROP' as line_source
FROM bettingpros_player_points_props
WHERE points_line IS NOT NULL
GROUP BY player_lookup, game_date
```

**Completeness Tracking** (Phase 5):
```python
# Track data completeness for each player
{
  "expected_games_count": 10,  # Last 10 games
  "actual_games_count": 9,      # 1 missing
  "completeness_percentage": 90.0,
  "is_production_ready": True,  # ≥90%
  "data_quality_issues": ["missing_game_2026-01-25"]
}
```

---

## Phase 5: ML Predictions

### Prediction Flow

```
┌─────────────────────────────────────────────────────────┐
│                   Prediction Coordinator                 │
│  (Orchestrates batch prediction generation)             │
└────────────┬────────────────────────────────────────────┘
             │
             ├─▶ Load games scheduled for target date
             │   (from nba_reference.nba_schedule)
             │
             ├─▶ Load eligible players per game
             │   (from ml_feature_store_v2)
             │   Filter: completeness_percentage ≥ 90%
             │
             └─▶ Send batch requests to Prediction Worker
                     │
                     ▼
           ┌─────────────────────┐
           │  Prediction Worker  │
           │  (ML Inference)     │
           └──────────┬──────────┘
                      │
                      ├─▶ Load features (33 per player)
                      ├─▶ Load CatBoost model (V9)
                      ├─▶ Generate predictions
                      ├─▶ Calculate confidence scores
                      └─▶ Write to player_prop_predictions
                               │
                               ▼
                    ┌──────────────────────┐
                    │ player_prop_predictions │
                    │  (All predictions)      │
                    └──────────────────────┘
```

### Prediction Run Modes (Session 76)

| Mode | Time (ET) | Purpose | Line Type |
|------|-----------|---------|-----------|
| EARLY | 2:30 AM | Early predictions with real lines | REAL_LINES_ONLY |
| OVERNIGHT | 7:00 AM | Comprehensive predictions | ALL_PLAYERS |
| SAME_DAY | 11:30 AM | Catch stragglers | ALL_PLAYERS |

**REAL_LINES_ONLY Mode**:
- Only generates predictions for players with `line_source='ACTUAL_PROP'`
- Filters out `NO_PROP_LINE` players
- Results in ~140 predictions (vs ~200 for ALL_PLAYERS)
- Higher quality: Only players with betting markets

---

## Grading & Accuracy Tracking

### Grading Flow

```
┌──────────────────────┐
│ player_prop_predictions │  (Made before game)
└──────────┬─────────────┘
           │
           │ After game completes:
           ▼
┌──────────────────────┐
│ player_game_summary  │  (Actual results)
└──────────┬───────────┘
           │
           │ Join on (player_lookup, game_date)
           ▼
┌──────────────────────┐
│ Grading Service      │
│ (nba-grading-service)│
└──────────┬───────────┘
           │
           │ Calculate:
           │ - prediction_correct (OVER/UNDER match)
           │ - absolute_error
           │ - within_threshold (±3 points)
           │ - model_beat_vegas
           ▼
┌──────────────────────┐
│ prediction_accuracy  │  (Graded predictions)
└──────────────────────┘
```

**Grading Logic**:
```python
def grade_prediction(prediction, actual):
    # 1. Prediction correct?
    if prediction.recommendation == 'OVER':
        correct = actual.points > prediction.line_value
    else:
        correct = actual.points < prediction.line_value

    # 2. Model beat Vegas?
    pred_error = abs(prediction.predicted_points - actual.points)
    vegas_error = abs(prediction.line_value - actual.points)
    model_beat_vegas = pred_error < vegas_error

    return {
        'prediction_correct': correct,
        'absolute_error': pred_error,
        'model_beat_vegas': model_beat_vegas
    }
```

---

## Critical Data Quality Paths

### 1. Vegas Line Coverage (90%+ required)

```
BettingPros scraper MUST run hourly
     └─ If fails: Coverage drops within 6 hours
         └─ Detected by: unified-health-check.sh
             └─ Alert: Slack webhook
                 └─ Action: Investigate scraper logs
```

### 2. Shot Zone Data (Session 53 fix)

```
BigDataBall play-by-play availability
     └─ ~60-70% of games have play-by-play
         └─ When missing: has_complete_shot_zones = FALSE
             └─ ML training: Filter by has_complete_shot_zones = TRUE
```

### 3. Grading Completeness (80%+ required)

```
Predictions generated (Phase 5)
     └─ Games complete (game_status = 3)
         └─ player_game_summary available (Phase 3)
             └─ Grading service runs
                 └─ Check: ≥80% of predictions graded
                     └─ If <80%: Session 68 scenario
                         └─ Hit rate analysis invalid
```

---

## Monitoring Integration Points

### 1. Heartbeat System

```python
# Every processor emits heartbeats to Firestore
from shared.monitoring.processor_heartbeat import ProcessorHeartbeat

heartbeat = ProcessorHeartbeat(
    processor_name="PlayerGameSummaryProcessor",
    data_date="2026-02-01",
    run_id="abc123"
)

# Document ID = processor_name (ONE doc per processor)
heartbeat.emit(
    status="running",
    progress={"current": 50, "total": 100}
)
```

**Critical**: ONE document per processor (Session 61 fix)
- Old: `{processor_name}_{date}_{run_id}` → 106k docs
- New: `{processor_name}` → 30 docs

### 2. Completion Events

```python
# Processors publish completion to Pub/Sub
from shared.orchestration.completion_publisher import CompletionPublisher

publisher = CompletionPublisher()
publisher.publish_completion(
    phase="phase3",
    processor_name="player_game_summary",
    game_date="2026-02-01",
    record_count=285
)
```

### 3. Health Check Integration

```bash
# unified-health-check.sh queries:
# 1. BigQuery for data completeness
# 2. Firestore for processor heartbeats
# 3. GCloud for deployment status
# 4. Calculated health score (0-100)
```

---

## Performance Characteristics

| Pipeline Stage | Latency | Throughput | Bottleneck |
|----------------|---------|------------|------------|
| Phase 1 (Scraping) | 5-30 min | 10 games/min | API rate limits |
| Phase 2 (Raw) | 1-5 min | 100 games/min | BigQuery writes |
| Phase 3 (Analytics) | 5-15 min | 50 games/min | Play-by-play joins |
| Phase 4 (Precompute) | 10-30 min | 30 games/min | Feature calculations |
| Phase 5 (Predictions) | 5-10 min | 200 players/min | ML inference |

**Critical Path** (game → prediction):
- **Best case**: 30 minutes (evening processing with boxscores)
- **Typical**: 12 hours (overnight processing with gamebooks)
- **Worst case**: 24 hours (missing data, reprocessing needed)

---

## Error Recovery Patterns

### 1. Graceful Degradation

```
Primary source unavailable ──▶ Use fallback source
├─ Gamebook PDF missing ──▶ Use boxscores
├─ Play-by-play missing ──▶ Set has_complete_shot_zones=FALSE
└─ Vegas line missing ──▶ Use NO_PROP_LINE + estimated line
```

### 2. Circuit Breaker (Phase 5)

```python
if reprocess_attempt_count > 3:
    circuit_breaker_active = True
    circuit_breaker_until = now + 24 hours
    manual_override_required = True
```

### 3. Backfill Mode

```python
# For historical data gaps
if backfill_bootstrap_mode:
    # Relax completeness requirements
    # Allow partial feature sets
    # Mark predictions with backfill flag
```

---

## References

- [Prevention & Monitoring Architecture](./prevention-monitoring-architecture.md)
- [Phase Documentation](../03-phases/)
- Session 76: Vegas line coverage drop
- Session 73: Evening processing
- Session 68: Grading completeness
- Session 53: Shot zone data fix
- Session 61: Heartbeat proliferation fix
