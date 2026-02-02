# Evening Analytics Processing Gap - Current State Analysis

**Created**: February 2, 2026
**Session**: 72
**Status**: Analysis Complete

---

## Executive Summary

We identified a significant gap in our orchestration pipeline: **completed games are not processed until the next morning**, causing 6-18 hour delays in:
- Prediction grading
- Signal validation
- Performance metric updates
- Hit rate analysis

This is especially problematic for **weekend early games** (1 PM, 3:30 PM matinees) which complete by 3-6 PM ET but aren't processed until 6 AM the next day.

---

## Discovery Context

### Session 72 Observation (Feb 1, 2026 ~10:20 PM ET)

During validation, we found:

| Data Layer | Feb 1 Status | Issue |
|------------|--------------|-------|
| Raw boxscores (`nbac_player_boxscores`) | 152 records, 7 games | Data exists |
| Analytics (`player_game_summary`) | **0 records** | Not processed |
| Game status | 1 Final, 4 In Progress, 5 Scheduled | MIL@BOS complete |

**The BOS vs MIL game was FINAL** with full boxscore data, but `player_game_summary` had zero records because Phase 3 analytics hadn't run.

---

## Current Architecture

### Scheduled Jobs (Phase 3 Analytics)

| Job | Schedule (ET) | Purpose |
|-----|---------------|---------|
| `overnight-analytics-6am-et` | 6:00 AM | Process yesterday's completed games |
| `same-day-phase3` | 10:30 AM | Process today's upcoming context |
| `same-day-phase3-tomorrow` | 5:00 PM | Process tomorrow's upcoming context |

### Boxscore Scraping (Frequent)

| Job | Schedule (ET) | Purpose |
|-----|---------------|---------|
| `bdl-live-boxscores-evening` | Every 3 min, 4-11 PM | Live game boxscores |
| `bdl-live-boxscores-late` | Every 3 min, 12-1 AM | Late game boxscores |

### The Gap

```
4:00 PM  ──────────────────────────────────────────────────> 6:00 AM
         │                                                    │
         │  Boxscores scraped every 3 minutes                 │
         │  Games complete throughout evening                 │
         │  Raw data available in BigQuery                    │
         │                                                    │
         │  [NO ANALYTICS PROCESSING]                         │
         │                                                    │
         └────────────────────────────────────────────────────┘
                     6-18 HOUR DELAY
```

---

## Impact Analysis

### Affected Workflows

1. **Prediction Grading**
   - Cannot grade predictions until `player_game_summary` exists
   - Actual points needed to compare against predicted points
   - Delayed grading = delayed performance analysis

2. **Signal Validation**
   - RED/GREEN signal accuracy can't be validated same-night
   - Feb 1 RED signal (10.6% pct_over) can't be validated until Feb 2 morning
   - Reduces feedback loop for signal tuning

3. **Model Monitoring**
   - Hit rate trends delayed by 6-18 hours
   - Model drift detection delayed
   - Weekly performance reports miss same-day data

4. **Operational Awareness**
   - Can't verify predictions performed well/poorly same night
   - Morning validation finds issues from 12+ hours ago

### Weekend Early Games (Worst Case)

| Game Start | Game End | Current Processing | Delay |
|------------|----------|-------------------|-------|
| 1:00 PM Sun | ~3:30 PM | 6:00 AM Mon | **14.5 hours** |
| 3:30 PM Sun | ~6:00 PM | 6:00 AM Mon | **12 hours** |
| 6:00 PM Sun | ~8:30 PM | 6:00 AM Mon | **9.5 hours** |
| 7:00 PM Sun | ~9:30 PM | 6:00 AM Mon | **8.5 hours** |
| 10:00 PM Sun | ~12:30 AM | 6:00 AM Mon | **5.5 hours** |

---

## Game Volume by Day

Analysis of last 30 days:

| Day | Games | Notes |
|-----|-------|-------|
| Sunday | 42 | Heavy schedule, early starts common |
| Saturday | 36 | Mix of afternoon and evening |
| Friday | 33 | Mostly evening games |
| Wednesday | 35 | Mostly evening games |
| Monday | 30 | Mostly evening games |
| Thursday | 28 | Mostly evening games |
| Tuesday | 27 | Mostly evening games |

**Sundays have the most games** and often the earliest start times.

---

## Root Cause

### Why This Gap Exists

1. **Historical Design**: System was built for overnight batch processing
2. **Phase 3 Triggers**: Only triggered by Phase 2 completion events OR scheduled jobs
3. **No Evening Scheduler**: No scheduled job between 5 PM and 6 AM next day
4. **Event-Driven Gap**: Phase 2 raw processors run, but no downstream trigger for same-day analytics

### What Would Fix It

**Option A**: Add evening scheduled triggers (simple)
**Option B**: Event-driven game completion detection (optimal)

---

## Data Flow Analysis

### Current Event-Driven Flow

```
Phase 2 Raw Processor completes
    ↓
Publishes to: nba-phase2-raw-complete
    ↓
Subscription: nba-phase3-analytics-sub
    ↓
Phase 3 Analytics Processors triggered
    ↓
Writes to: player_game_summary, etc.
```

### Why This Doesn't Help Same-Day

The event-driven flow works for **overnight processing** because:
1. Boxscore scrapers run overnight
2. Phase 2 processors run on that data
3. Phase 3 is triggered by Phase 2 completion

But for **same-day games**:
1. Boxscores are scraped during games (live)
2. Phase 2 processors may not run again
3. No trigger for Phase 3 to reprocess

---

## Trigger Mapping

Current `ANALYTICS_TRIGGERS` in `main_analytics_service.py`:

```python
ANALYTICS_TRIGGERS = {
    'nbac_gamebook_player_stats': [PlayerGameSummaryProcessor, ...],
    'nbac_team_boxscore': [TeamDefenseGameSummaryProcessor, ...],
    'nbac_schedule': [UpcomingTeamGameContextProcessor],
    'nbac_injury_report': [PlayerGameSummaryProcessor],
    'odds_api_player_points_props': [UpcomingPlayerGameContextProcessor],
}
```

**Key Insight**: `PlayerGameSummaryProcessor` is triggered by:
- `nbac_gamebook_player_stats` (gamebook PDF parsing)
- `nbac_injury_report` (injury updates)

But NOT by:
- `nbac_player_boxscores` (live boxscores)
- Game completion events

---

## Questions for Implementation

1. **How quickly does NBA.com update game_status to Final?**
   - Need to measure latency from game end to status update
   - May need alternative source for faster detection

2. **What's the simplest reliable trigger?**
   - Scheduled jobs: Simple but not real-time
   - Game status polling: More timely but needs monitoring
   - Boxscore-triggered: Couples scraping with analytics

3. **Should we process individual games or full dates?**
   - Current: Date-level processing (all players for a date)
   - Alternative: Game-level processing (only affected players)

---

## Related Documentation

- [Pre-Game Signals Strategy](../pre-game-signals-strategy/)
- [Session 71 Handoff](../../09-handoff/2026-02-02-SESSION-71-SIGNALS-COMPLETE.md)
- [Orchestration Architecture](../../01-architecture/orchestration/)

---

## Next Steps

See: [IMPLEMENTATION-PLAN.md](./IMPLEMENTATION-PLAN.md)
