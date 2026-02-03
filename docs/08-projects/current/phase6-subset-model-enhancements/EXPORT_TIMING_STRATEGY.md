# Subset Picks Export Timing Strategy

**Date:** 2026-02-03
**Context:** How often to push subset picks to Phase 6

## Current Phase 6 Timing Patterns

### Existing Export Frequencies

| Export Type | Trigger | Frequency | Latency |
|-------------|---------|-----------|---------|
| Tonight's picks | Event-driven (Phase 5→6) | Once per day (~7 AM ET) | Immediate |
| Results | Scheduled | Daily 5 AM ET | 18-24 hours |
| Best bets | Event-driven + scheduled | After predictions + 5 AM | Immediate |
| Trends | Scheduled | Hourly (6 AM - 11 PM) | N/A |
| Live scores | Scheduled | Every 3 min during games | 30 seconds |
| Player profiles | Scheduled | Weekly (Sunday 6 AM) | N/A |

---

## Grading System Timing

### When Predictions Get Graded

**Daily batch at 7:30 AM ET (NOT real-time):**

```
Timeline:
6:30 AM → Phase 3 analytics starts (player_game_summary)
7:15 AM → Analytics complete
7:30 AM → Grading service runs
7:35 AM → prediction_accuracy table updated
5:00 AM → Next day, results exported to website
```

**Key Point:** Grading is NOT incremental as games complete. It's a single daily batch.

### Grading Data Sources

**Method A: Official grading table (batch)**
- Table: `prediction_accuracy`
- Latency: 18-24 hours after game
- Coverage: Production picks only (ACTUAL_PROP lines)
- Best for: Historical analysis, finalized metrics

**Method B: Real-time JOIN (same-night)**
- Tables: `player_prop_predictions` + `player_game_summary`
- Latency: 4-6 hours after game (when analytics completes)
- Coverage: All picks (includes NO_PROP_LINE)
- Best for: Same-night updates, early results

---

## Subset Picks Grading Availability

### Current State ✅

**`v_dynamic_subset_performance` view includes grading:**
- Joins with `player_game_summary` (real-time approach)
- Computes: `graded_picks`, `wins`, `hit_rate`, `mae`
- 30-day rolling window
- **Data is ready to export** - no additional work needed

**Existing notifier (`subset_picks_notifier.py`):**
- Already queries picks with historical performance
- Uses 23-day lookback
- Computes win rates via JOIN
- Sends to Slack/Email (not GCS yet)

---

## Recommended Export Strategy

### Option A: Simple Batch (Recommended for Testing) ✅

**Schedule:**
1. **After predictions** (~7 AM ET) → Export today's picks
2. **Next day 5 AM ET** → Re-export with updated stats

**What gets pushed:**

**File 1: `/picks/2026-02-03.json` (generated 7 AM on Feb 3)**
```json
{
  "date": "2026-02-03",
  "generated": "2026-02-03T12:00:00Z",
  "model": "926A",
  "groups": [
    {
      "id": "1",
      "name": "Top 5",
      "picks": [ /* 5 picks for TODAY (Feb 3) - not graded yet */ ],
      "stats": {
        "hit_rate": 75.0,  // Historical (Feb 1-31)
        "roi": 9.1,
        "days": 30
      }
    }
  ]
}
```

**File 2: `/picks/2026-02-02.json` (re-exported 5 AM on Feb 3)**
```json
{
  "date": "2026-02-02",
  "generated": "2026-02-03T10:00:00Z",
  "model": "926A",
  "groups": [
    {
      "id": "1",
      "name": "Top 5",
      "picks": [ /* 5 picks from YESTERDAY (Feb 2) - now graded */ ],
      "stats": {
        "hit_rate": 75.2,  // Now includes Feb 2 games
        "roi": 9.3,
        "days": 30
      }
    }
  ]
}
```

**Pros:**
- ✅ Simple - matches existing Phase 6 patterns
- ✅ Clean separation: today's picks vs yesterday's results
- ✅ No complexity around partial grading
- ✅ Easy to test

**Cons:**
- ⏳ 18-24 hour latency for grading (acceptable for testing)

---

### Option B: Hybrid (Same-Night Updates)

**Schedule:**
1. **After predictions** (~7 AM ET) → Export today's picks
2. **6 PM ET same day** → Export with partial grading (evening games done)
3. **Next day 5 AM ET** → Export final grading

**What gets pushed:**

**Update 1: 7 AM - Pre-game**
```json
{
  "date": "2026-02-03",
  "groups": [{
    "picks": [ /* today's picks */ ],
    "stats": { "hit_rate": 75.0 }  // Historical
  }]
}
```

**Update 2: 6 PM - Partial grading**
```json
{
  "date": "2026-02-03",
  "groups": [{
    "picks": [ /* same picks, some games completed */ ],
    "stats": { "hit_rate": 76.2 }  // Updated with early games
  }]
}
```

**Update 3: 5 AM next day - Final**
```json
{
  "date": "2026-02-03",
  "groups": [{
    "picks": [ /* same picks, all games completed */ ],
    "stats": { "hit_rate": 74.8 }  // Final with all games
  }]
}
```

**Pros:**
- ✅ Same-night updates (4-6 hour latency)
- ✅ Better user experience (see results same evening)

**Cons:**
- ⚠️ More complex (3 exports per day vs 1)
- ⚠️ Requires JOIN with player_game_summary (not prediction_accuracy)
- ⚠️ Partial data can be confusing

---

### Option C: Real-Time (NOT Recommended)

**Schedule:** Every 3 minutes during games (like live scores)

**Why NOT to do this:**
- ❌ Way too frequent for subset picks
- ❌ Users don't need live subset updates
- ❌ Adds complexity without value
- ❌ Increases GCS write volume
- ❌ Cache thrashing (30-second TTL not useful for picks)

Live updates make sense for:
- ✅ Scores (game progress)
- ✅ Leaderboards (challenge systems)

But NOT for:
- ❌ Subset pick lists (static after generation)
- ❌ Performance metrics (changes slowly)

---

## Recommended Implementation: Option A

### Why Simple Batch Works Best

For testing purposes, Option A is ideal:

1. **Matches user expectations**
   - Morning: See today's picks
   - Next morning: See yesterday's results

2. **Matches existing Phase 6 patterns**
   - Predictions after Phase 5
   - Results at 5 AM daily

3. **Simple to implement**
   - One exporter class
   - One orchestration trigger
   - No partial grading complexity

4. **Easy to test**
   - Generate picks at 7 AM
   - Verify JSON structure
   - Next day, verify grading included

5. **Can upgrade later**
   - Start simple for testing
   - Add same-night updates if users want faster results
   - No need to build complex system upfront

---

## Implementation Details

### Trigger Configuration

**In `orchestration/cloud_functions/phase5_to_phase6/main.py`:**

Add subset picks to event-driven exports:
```python
EXPORT_TYPES = [
    'tonight',
    'tonight-players',
    'predictions',
    'best-bets',
    'streaks',
    'subset-picks',  # NEW
]
```

**In `bin/schedulers/setup_phase6_schedulers.sh`:**

Add to 5 AM results export:
```bash
gcloud scheduler jobs create pubsub phase6-daily-results \
  --schedule="0 5 * * *" \
  --time-zone="America/Los_Angeles" \
  --topic="nba-phase6-export-trigger" \
  --message-body='{"export_types": ["results", "performance", "best-bets", "predictions", "subset-picks"], "target_date": "yesterday", "update_latest": true}'
```

### Data Query

**For historical stats (last 30 days):**
```sql
SELECT
  subset_id,
  SUM(graded_picks) as picks,
  SUM(wins) as wins,
  ROUND(100.0 * SUM(wins) / NULLIF(SUM(graded_picks), 0), 1) as hit_rate,
  ROUND(SUM(CASE WHEN wins > 0 THEN wins * 0.909 ELSE -(graded_picks - wins) END) / NULLIF(SUM(graded_picks), 0) * 100, 1) as roi
FROM nba_predictions.v_dynamic_subset_performance
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY subset_id
```

**For today's picks:**
```sql
-- Query predictions, filter by subset criteria, rank by composite_score
-- See IMPLEMENTATION_UPDATE.md for full query
```

---

## Export Orchestration Flow

### Current Flow (Predictions)
```
Phase 5 Complete (7 AM)
    ↓
Phase 5→6 Orchestrator
    ↓
Pub/Sub: nba-phase6-export-trigger
    ↓
Phase 6 Export Function
    ↓
Exporters: tonight, predictions, best-bets
    ↓
GCS: /v1/predictions/2026-02-03.json
```

### New Flow (Subset Picks)
```
Phase 5 Complete (7 AM)
    ↓
Phase 5→6 Orchestrator
    ↓
Pub/Sub: nba-phase6-export-trigger
    ↓
Phase 6 Export Function
    ↓
AllSubsetsPicksExporter  ← NEW
    ↓
Query v_dynamic_subset_performance (historical stats)
Query player_prop_predictions (today's picks)
Apply subset filters
Rank by composite_score
Map to clean names (1, 2, 3 or Top 5, etc.)
    ↓
GCS: /v1/picks/2026-02-03.json
```

---

## Testing Plan

### Day 1 (Feb 3, 7 AM):
1. Predictions complete
2. Phase 6 export triggered
3. Verify `/picks/2026-02-03.json` created
4. Verify contains 9 groups with today's picks
5. Verify stats show last 30 days (NOT including today)

### Day 2 (Feb 4, 5 AM):
1. Scheduled results export runs
2. Yesterday's file re-exported (optional)
3. Today's file created: `/picks/2026-02-04.json`
4. Verify Feb 3 games NOW included in 30-day stats

### Verification Queries:

```bash
# Check file exists
gsutil ls gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json

# Check structure
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  jq '{date, model, groups: (.groups | length)}'
# Expected: {"date": "2026-02-03", "model": "926A", "groups": 9}

# Check stats are NOT real-time (today's games not in stats yet)
gsutil cat gs://nba-props-platform-api/v1/picks/$(date +%Y-%m-%d).json | \
  jq '.groups[0].stats.days'
# Expected: 30 (rolling window)

# Next day: Verify stats updated
gsutil cat gs://nba-props-platform-api/v1/picks/$(date -d yesterday +%Y-%m-%d).json | \
  jq '.groups[0].stats.hit_rate'
# Should change if yesterday's games added to rolling window
```

---

## Future Enhancements

If users want faster grading visibility:

### Phase 2: Add Same-Night Export (Optional)

Add 6 PM ET scheduler:
```bash
gcloud scheduler jobs create pubsub phase6-evening-subset-update \
  --schedule="0 18 * * *" \
  --time-zone="America/New_York" \
  --topic="nba-phase6-export-trigger" \
  --message-body='{"export_types": ["subset-picks"], "target_date": "today"}'
```

Modify exporter to use player_game_summary JOIN for same-night grading.

---

## Summary

**Recommended: Option A (Simple Batch)**

| Timing | Export |
|--------|--------|
| After predictions (~7 AM) | Today's picks with historical stats |
| Next day 5 AM | Results export (optional re-export) |

**Grading data is ready:**
- ✅ `v_dynamic_subset_performance` includes all grading metrics
- ✅ No schema changes needed
- ✅ Can use 30-day rolling window for stats

**No real-time needed:**
- ❌ Don't push every time a pick is graded
- ✅ Daily batch sufficient for testing
- ✅ Can add same-night updates later if needed
