# System Features Reference

Detailed documentation for major system features. For quick reference, see CLAUDE.md.

---

## Table of Contents

1. [Heartbeat System](#heartbeat-system)
2. [Evening Analytics Processing](#evening-analytics-processing)
3. [Early Prediction Timing](#early-prediction-timing)
4. [Model Attribution Tracking](#model-attribution-tracking)
5. [Enhanced Notifications](#enhanced-notifications)

---

## Heartbeat System

**Purpose:** Processors emit periodic heartbeats to Firestore to track health and progress in the unified dashboard.

**Implementation:** `shared/monitoring/processor_heartbeat.py`

### How It Works

1. **Each processor has ONE Firestore document** identified by `processor_name`
2. **Heartbeats update this single document** with current status, progress, timestamp
3. **Dashboard queries Firestore** to show health score and recent activity

**Document structure:**
```python
{
    "processor_name": "PlayerGameSummaryProcessor",
    "status": "running",  # or "completed", "failed"
    "last_heartbeat": timestamp,
    "progress": {"current": 50, "total": 100},
    "data_date": "2026-02-01",
    "run_id": "abc123"
}
```

### Critical Design: One Document Per Processor

**Correct implementation:**
```python
@property
def doc_id(self) -> str:
    return self.processor_name  # ONE document per processor
```

**Anti-pattern (WRONG):**
```python
def doc_id(self) -> str:
    return f"{self.processor_name}_{self.data_date}_{self.run_id}"  # Creates unbounded growth!
```

### Cleanup Script

Run `bin/cleanup-heartbeat-docs.py` if:
- Dashboard health score is unexpectedly low (<50/100)
- Firestore collection has >100 documents (should be ~30)

```bash
# Preview
python bin/cleanup-heartbeat-docs.py --dry-run

# Execute
python bin/cleanup-heartbeat-docs.py
```

### Verification

```bash
# Check dashboard health score (should be 70+/100)
curl https://unified-dashboard-f7p3g7f6ya-wl.a.run.app/api/services/health
```

**References:** Session 61 handoff, `shared/monitoring/processor_heartbeat.py`

---

## Evening Analytics Processing

**Purpose:** Process completed games same-night instead of waiting until 6 AM next day.

**Added:** Session 73

### Evening Schedulers

| Job | Schedule (ET) | Purpose |
|-----|---------------|---------|
| `evening-analytics-6pm-et` | 6 PM Sat/Sun | Weekend matinees |
| `evening-analytics-10pm-et` | 10 PM Daily | 7 PM games |
| `evening-analytics-1am-et` | 1 AM Daily | West Coast games |
| `morning-analytics-catchup-9am-et` | 9 AM Daily | Safety net |

### Boxscore Fallback

`PlayerGameSummaryProcessor` normally requires `nbac_gamebook_player_stats` (from PDF parsing, available next morning). For evening processing, it falls back to `nbac_player_boxscores` (scraped live during games).

**Flow:**
```
Check nbac_gamebook_player_stats → Has data? → Use gamebook (gold)
                                      ↓ No
Check nbac_player_boxscores (Final) → Has data? → Use boxscores (silver)
                                      ↓ No
                                Skip processing
```

**Configuration:** `USE_NBAC_BOXSCORES_FALLBACK = True` in `player_game_summary_processor.py`

**Verify source used:**
```sql
SELECT game_date,
  COUNTIF(primary_source_used = 'nbac_boxscores') as from_boxscores,
  COUNTIF(primary_source_used = 'nbac_gamebook') as from_gamebook
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY game_date ORDER BY game_date DESC
```

**References:** Session 73 handoff, `docs/08-projects/current/evening-analytics-processing/`

---

## Early Prediction Timing

**Purpose:** Generate predictions earlier (2:30 AM ET) using REAL_LINES_ONLY mode, instead of waiting until 7 AM.

**Added:** Session 74

### Background

Vegas lines are available at ~2:00 AM ET (from BettingPros), but predictions were running at 7:00 AM. This 5-hour delay meant predictions might miss optimal timing for user consumption.

### Prediction Schedulers

| Job | Schedule (ET) | Mode | Expected Players |
|-----|---------------|------|-----------------|
| `predictions-early` | 2:30 AM | REAL_LINES_ONLY | ~140 |
| `overnight-predictions` | 7:00 AM | ALL_PLAYERS | ~200 |
| `same-day-predictions` | 11:30 AM | ALL_PLAYERS | Catch stragglers |

### REAL_LINES_ONLY Mode

The `require_real_lines` parameter filters out players without real betting lines:

```bash
curl -X POST https://prediction-coordinator-f7p3g7f6ya-wl.a.run.app/start \
  -H "Content-Type: application/json" \
  -d '{"game_date": "TODAY", "require_real_lines": true, "force": true}'
```

**How it works:**
- Players with `line_source='ACTUAL_PROP'` are included
- Players with `line_source='NO_PROP_LINE'` are filtered out
- Results in ~140 high-quality predictions at 2:30 AM

### Verify Line Availability

```sql
-- Check lines available for today
SELECT COUNT(DISTINCT player_lookup) as players_with_lines
FROM nba_raw.bettingpros_player_points_props
WHERE game_date = CURRENT_DATE() AND points_line IS NOT NULL;
```

**References:** Session 74 handoff, `predictions/coordinator/player_loader.py`

---

## Model Attribution Tracking

**Purpose:** Track which exact model file generated which predictions for debugging, A/B testing, and compliance.

**Added:** Session 84

### Schema Fields (in `player_prop_predictions`)

| Field | Type | Example |
|-------|------|---------|
| `model_file_name` | STRING | `catboost_v9_feb_02_retrain.cbm` |
| `model_training_start_date` | DATE | `2025-11-02` |
| `model_training_end_date` | DATE | `2026-01-31` |
| `model_expected_mae` | FLOAT64 | `4.12` |
| `model_expected_hit_rate` | FLOAT64 | `74.6` |
| `model_trained_at` | TIMESTAMP | `2026-02-02T10:15:00Z` |

### Verification

```bash
./bin/verify-model-attribution.sh --game-date YYYY-MM-DD
```

### Query Performance by Model

```sql
SELECT model_file_name, COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND model_file_name IS NOT NULL
  AND ABS(predicted_points - line_value) >= 5
GROUP BY model_file_name
ORDER BY mae ASC
```

**References:** Session 84/85, `docs/08-projects/current/model-attribution-tracking/`

---

## Enhanced Notifications

**Purpose:** Daily subset picks notifications include model attribution metadata.

**Added:** Session 85

### Slack Format

```
🏀 Today's Top Picks - 2026-02-04

🟢 GREEN SIGNAL (35.5% OVER)
✅ Normal confidence - bet as usual

🤖 Model: V9 Feb 02 Retrain (MAE: 4.12, HR: 74.6%)

Top 5 Picks:
1. Player Name - OVER 25.5 pts
   Edge: 6.5 | Conf: 89%
```

**Implementation:** `shared/notifications/subset_picks_notifier.py`

**Backward Compatible:** Gracefully handles predictions without attribution (pre-Feb 4)

**References:** Session 83 Task #4, Session 85
