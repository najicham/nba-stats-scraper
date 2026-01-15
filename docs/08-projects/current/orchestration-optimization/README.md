# Orchestration Optimization Project

**Status**: Active
**Started**: 2026-01-15
**Focus**: Reduce latency in grading and predictions through smarter scheduling and event-driven triggers

---

## Problem Statement

The NBA predictions pipeline had significant timing inefficiencies:

1. **Grading delay**: 13+ hours between games ending and grading running
2. **Predictions timing**: Morning predictions (7 AM) run before odds are available (~8 AM)
3. **Time-based only**: All triggers are scheduled, not data-driven

---

## Solutions Implemented

### Phase 1: Additional Scheduled Jobs (Completed 2026-01-15)

Added more frequent grading and prediction runs:

| Job | Schedule (ET) | Purpose | Status |
|-----|---------------|---------|--------|
| `grading-latenight` | 2:30 AM | Grade immediately after most games | ✅ Created |
| `grading-morning` | 6:30 AM | Catch West Coast/OT games | ✅ Created |
| `morning-predictions` | 10:00 AM | First predictions with real odds | ✅ Created |

**Impact**: Reduced grading delay from 13 hrs → 1.5-4.5 hrs

### Phase 2: Event-Driven Grading (In Progress)

Polling-based monitor that triggers grading when all games are complete:

**Component**: `grading-readiness-monitor` Cloud Function

**Schedule**: Every 15 min from 10 PM - 3 AM ET

**Logic**:
```
1. Check scheduled games for yesterday
2. Check games with final boxscores
3. Check if already graded
4. If all complete AND not graded → trigger grading
```

**Impact**: Reduces grading delay from 1.5-4.5 hrs → 0-15 minutes

---

## Architecture

### New Schedule (After Optimization)

```
Game Day Timeline (e.g., Jan 14 → Jan 15)
═══════════════════════════════════════════

Jan 14 (Game Day)
├── 7:00 PM    Games start
├── ~10:00 PM  Most games finish
└── ~1:00 AM   Late games finish (West Coast)

Jan 15 (Overnight)
├── 10:15 PM   Readiness monitor: "Waiting 3/5 games"
├── 10:30 PM   Readiness monitor: "Waiting 4/5 games"
├── 10:45 PM   Readiness monitor: "All complete → TRIGGER GRADING" ✨
├── ~10:50 PM  Grading runs (event-driven!)
├── 2:30 AM    grading-latenight (safety net, likely no-ops)
└── 6:30 AM    grading-morning (safety net)

Jan 15 (Morning)
├── 7:00 AM    overnight-predictions (ESTIMATED lines)
├── 10:00 AM   morning-predictions (with odds) ✨
├── 11:00 AM   grading-daily (final safety net)
└── 11:30 AM   same-day-predictions (refresh)
```

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│              GRADING READINESS MONITOR                           │
│         Cloud Function (HTTP trigger)                           │
│         Schedule: */15 22-23,0-2 * * * (ET)                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Inputs:                                                        │
│  ├── nba_raw.nbac_schedule (game count)                        │
│  ├── nba_raw.bdl_player_boxscores (completion)                 │
│  └── nba_predictions.prediction_accuracy (graded status)       │
│                                                                 │
│  Output:                                                        │
│  └── Pub/Sub: nba-grading-trigger (if ready)                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              GRADING FUNCTION (phase5b-grading)                  │
│         Existing Cloud Function (Pub/Sub trigger)               │
│         Topic: nba-grading-trigger                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Files

| File | Purpose |
|------|---------|
| `orchestration/cloud_functions/grading_readiness_monitor/main.py` | Readiness monitor function |
| `orchestration/cloud_functions/grading/main.py` | Existing grading function |

---

## Scheduler Jobs

### Grading Jobs

| Job | Schedule | Topic/URL | Status |
|-----|----------|-----------|--------|
| `grading-latenight` | 2:30 AM ET | nba-grading-trigger | ✅ Active |
| `grading-morning` | 6:30 AM ET | nba-grading-trigger | ✅ Active |
| `grading-daily` | 11:00 AM ET | nba-grading-trigger | ✅ Active |
| `grading-readiness-monitor` | */15 22-23,0-2 ET | HTTP | 🔄 Pending |

### Prediction Jobs

| Job | Schedule | Expected Line Source |
|-----|----------|---------------------|
| `overnight-predictions` | 7:00 AM ET | ESTIMATED |
| `morning-predictions` | 10:00 AM ET | ODDS_API |
| `same-day-predictions` | 11:30 AM ET | ODDS_API |
| `same-day-predictions-tomorrow` | 6:00 PM ET | ODDS_API |

---

## Monitoring

### Check Readiness Monitor Logs

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="grading-readiness-monitor"' --limit=20
```

### Check Grading Trigger Sources

```sql
-- See which source triggered grading
SELECT
  game_date,
  MIN(graded_at) as first_graded,
  COUNT(*) as graded_count
FROM nba_predictions.prediction_accuracy
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC
```

### Verify Schedule is Working

```bash
gcloud scheduler jobs list --location=us-west2 | grep -E "grading|prediction"
```

---

## Future Enhancements

1. **Odds availability trigger**: Trigger predictions when odds are first available for today's games
2. **Boxscore completion webhook**: Push-based trigger instead of polling
3. **Dashboard integration**: Real-time visibility into pipeline timing

---

## Related Documentation

- [Session 50 Handoff](../../09-handoff/2026-01-15-SESSION-50-HANDOFF.md)
- [Daily Orchestration Tracking](../daily-orchestration-tracking/)
- [Pipeline Reliability Improvements](../pipeline-reliability-improvements/)
