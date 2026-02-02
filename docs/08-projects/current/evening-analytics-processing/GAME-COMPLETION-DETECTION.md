# Game Completion Detection - Investigation & Options

**Created**: February 2, 2026
**Session**: 72
**Status**: Investigation Needed

---

## The Core Question

> How do we know when a game is finished so we can trigger analytics processing?

Currently, we don't detect game completion in real-time. We rely on overnight batch processing.

---

## Current Data Sources

### 1. NBA.com Schedule API (`nbac_schedule`)

**Endpoint**: `https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json`

**Fields**:
- `gameStatus`: 1 = Scheduled, 2 = In Progress, 3 = Final
- `gameStatusText`: "7:00 pm ET", "Q3 5:42", "Final"

**Scraper**: `scrapers/nbacom/nbac_schedule_api.py`

**Unknown**: How quickly does `gameStatus` change to 3 after final buzzer?

### 2. BallDontLie API (`bdl_box_scores`)

**Endpoint**: `https://api.balldontlie.io/v1/games`

**Fields**:
- `status`: "Final", "In Progress", etc.

**Scraper**: `scrapers/balldontlie/bdl_box_scores.py`

**Note**: BDL is currently DISABLED for quality issues, but could be used for status detection only.

### 3. NBA.com Boxscores (`nbac_player_boxscores`)

**Observation**: When boxscores are complete (all players have stats), the game is likely final.

**Heuristic**: If `SUM(minutes) > 0` for both teams and player count matches roster, game is complete.

---

## Detection Strategy Options

### Option A: Poll NBA.com Schedule API

```python
# Pseudo-code
while True:
    schedule = fetch_nba_schedule(today)
    for game in schedule:
        if game.status == 3 and game.id not in processed_games:
            trigger_phase3(game.date)
            mark_processed(game.id)
    sleep(300)  # 5 minutes
```

**Pros**:
- Uses existing scraper infrastructure
- Simple to implement
- Reliable source

**Cons**:
- Unknown latency (need to measure)
- 5-minute polling interval = 0-5 min detection delay
- Polling overhead

**Implementation**:
- Cloud Scheduler: Run every 5 min during game hours (6 PM - 1 AM ET)
- Cloud Function: Check for new Final games, trigger Phase 3

### Option B: Boxscore Completeness Heuristic

```python
# Detect completion based on boxscore data
def is_game_complete(game_id):
    boxscores = query_boxscores(game_id)

    # Heuristic: Game is complete if:
    # 1. Both teams have 5+ players with minutes > 0
    # 2. Total minutes played is reasonable (200-290 per team)
    # 3. No player has exactly 0 minutes (DNP excluded)

    home_players = [p for p in boxscores if p.team == 'home' and p.minutes > 0]
    away_players = [p for p in boxscores if p.team == 'away' and p.minutes > 0]

    return len(home_players) >= 5 and len(away_players) >= 5
```

**Pros**:
- Leverages existing live boxscore scraping (every 3 min)
- Doesn't depend on API status field
- Works even if status update is delayed

**Cons**:
- Heuristic could have false positives (overtime not started yet)
- More complex logic
- Couples scraping with detection

### Option C: Multiple Source Correlation

```python
# Require agreement from multiple sources
def is_game_definitely_complete(game_id):
    nba_status = get_nba_schedule_status(game_id)
    boxscore_complete = is_boxscore_complete(game_id)
    bdl_status = get_bdl_status(game_id)  # If available

    # Require at least 2 sources to agree
    signals = [
        nba_status == 3,
        boxscore_complete,
        bdl_status == 'Final'
    ]

    return sum(signals) >= 2
```

**Pros**:
- Most reliable
- Handles individual source delays/errors

**Cons**:
- Most complex
- Multiple API calls

### Option D: ESPN as Primary Source

ESPN is known for fast game status updates. Consider adding ESPN scraper for status only.

**Endpoint**: `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard`

**Fields**:
- `status.type.completed`: true/false
- `status.type.description`: "Final", "In Progress"

**Pros**:
- Typically fastest updates
- Free API
- Reliable

**Cons**:
- New scraper to build
- Additional API dependency

---

## Investigation Tasks

### Task 1: Measure NBA.com Latency

**Goal**: Determine how long after game ends until `gameStatus = 3`

**Method**:
1. Pick a game with known end time (watch live or use ESPN)
2. Poll NBA.com schedule API every 30 seconds
3. Record when `gameStatus` changes from 2 to 3
4. Calculate latency from actual game end

**Script**:
```python
import time
import requests
from datetime import datetime

def measure_nba_status_latency(game_id, known_end_time):
    """
    Poll NBA.com and measure when game_status changes to Final.

    Args:
        game_id: NBA game ID (e.g., "0022500702")
        known_end_time: datetime when game actually ended (from TV/ESPN)
    """
    url = "https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json"

    print(f"Monitoring game {game_id}...")
    print(f"Known end time: {known_end_time}")

    while True:
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()

            for game in data.get('scoreboard', {}).get('games', []):
                if game.get('gameId') == game_id:
                    status = game.get('gameStatus')
                    status_text = game.get('gameStatusText')
                    now = datetime.utcnow()

                    print(f"[{now.isoformat()}] Status: {status} ({status_text})")

                    if status == 3:
                        latency = (now - known_end_time).total_seconds()
                        print(f"\n=== GAME FINAL ===")
                        print(f"Detection time: {now.isoformat()}")
                        print(f"Latency: {latency:.0f} seconds ({latency/60:.1f} minutes)")
                        return latency

        except Exception as e:
            print(f"Error: {e}")

        time.sleep(30)  # Poll every 30 seconds
```

### Task 2: Compare ESPN vs NBA.com

**Goal**: Determine if ESPN is faster for status updates

**Method**:
1. Monitor same game on both sources
2. Record when each shows "Final"
3. Compare timestamps

### Task 3: Evaluate BDL Status Reliability

**Goal**: Can we use BDL for status even though boxscore data is unreliable?

**Method**:
1. Check if BDL status matches NBA.com status
2. Measure any latency difference
3. Determine if status field is trustworthy

---

## Recommended Approach

### Immediate (This Week)

1. **Implement scheduled triggers** (Phase 1 from implementation plan)
2. **Run latency measurement** during next game night

### Based on Findings

| If NBA.com Latency Is... | Recommendation |
|--------------------------|----------------|
| < 2 minutes | Use NBA.com polling (Option A) |
| 2-10 minutes | Use boxscore heuristic (Option B) |
| > 10 minutes | Add ESPN source (Option D) |

### Long-Term

Build a dedicated game completion monitor that:
1. Polls NBA.com every 3 minutes during game hours
2. Falls back to boxscore heuristic if status is stale
3. Tracks detection latency for monitoring
4. Triggers Phase 3 immediately on detection

---

## Data Model for Tracking

```sql
-- Track game completion detection performance
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_orchestration.game_completion_events` (
  game_id STRING NOT NULL,
  game_date DATE NOT NULL,

  -- Schedule info
  scheduled_start_time TIMESTAMP,
  home_team STRING,
  away_team STRING,

  -- Detection timestamps (UTC)
  nba_status_final_at TIMESTAMP,        -- When NBA.com showed status=3
  boxscore_complete_at TIMESTAMP,       -- When boxscore heuristic triggered
  espn_final_at TIMESTAMP,              -- If we add ESPN source
  bdl_final_at TIMESTAMP,               -- If we use BDL

  -- Actual end time (for calibration)
  actual_game_end_at TIMESTAMP,         -- Manual entry from TV/trusted source

  -- Phase 3 trigger
  phase3_triggered_at TIMESTAMP,        -- When we triggered processing
  phase3_completed_at TIMESTAMP,        -- When processing finished

  -- Calculated metrics
  detection_source STRING,              -- Which source triggered detection
  detection_latency_seconds INT64,      -- From actual end to detection
  processing_latency_seconds INT64,     -- From detection to Phase 3 complete

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY game_id;
```

---

## Open Questions

1. **Does NBA.com update status during overtime before it ends?**
   - Need to monitor an OT game to verify

2. **Are there regional differences in API updates?**
   - Test from different locations if possible

3. **What happens during postponements/cancellations?**
   - How does status change?
   - Do we need special handling?

4. **How does All-Star break affect this?**
   - Different game formats (skills, 3pt contest)
   - May need special handling

---

## Next Steps

1. [ ] Run latency measurement script during next game night (Feb 2 has 4 games)
2. [ ] Document findings in this file
3. [ ] Decide on detection approach based on data
4. [ ] Implement chosen approach

---

## References

- [NBA.com Stats API Documentation](https://github.com/swar/nba_api)
- [ESPN API (Unofficial)](https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b)
- [BallDontLie API Docs](https://docs.balldontlie.io/)
