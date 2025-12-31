# Live Data Pipeline - Comprehensive Analysis

**Date:** 2025-12-28
**Issue:** Live data showing yesterday's games instead of today's
**Status:** Root cause identified, immediate fix applied, improvements recommended

---

## Executive Summary

The live data endpoint (`/v1/live/latest.json`) was stuck showing December 27's games on December 28 because:

1. **Scheduler timing gap**: Live export runs 7 PM - 11 PM ET, but games started at 6 PM ET
2. **Late-night date mismatch**: At 1:57 AM ET, the system exported Dec 27's recently-finished games but labeled them as Dec 28
3. **No date validation**: The BDL `/live` API returns whatever is currently active, not date-filtered data

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        LIVE DATA PIPELINE                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   Cloud Scheduler                                                        │
│   ┌──────────────────────────────┐                                      │
│   │ live-export-evening          │──┐                                   │
│   │ */3 19-23 * * * (7-11PM ET)  │  │                                   │
│   ├──────────────────────────────┤  │                                   │
│   │ live-export-late-night       │  │   HTTP POST                       │
│   │ */3 0-1 * * * (12-1AM ET)    │──┼─────────────────┐                 │
│   └──────────────────────────────┘  │                 ▼                 │
│                                     │   ┌─────────────────────────┐     │
│   ┌──────────────────────────────┐  │   │   live-export           │     │
│   │ bdl-live-boxscores-evening   │──┤   │   Cloud Function        │     │
│   │ */3 19-23 * * * (7-11PM ET)  │  │   ├─────────────────────────┤     │
│   ├──────────────────────────────┤  │   │ 1. get_today_date()     │     │
│   │ bdl-live-boxscores-late      │  │   │    → "2025-12-28"       │     │
│   │ */3 0-1 * * * (12-1AM ET)    │──┘   │ 2. Call BDL /live API   │     │
│   └──────────────────────────────┘      │    → Returns ACTIVE     │     │
│                                         │      games (no date!)   │     │
│                                         │ 3. Export to GCS        │     │
│                                         └──────────────────────────┘    │
│                                                      │                   │
│                                                      ▼                   │
│   BDL API: /v1/box_scores/live                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ Returns games that are:                                          │   │
│   │  • Currently in progress, OR                                     │   │
│   │  • Recently finished (within ~1-2 hours)                        │   │
│   │                                                                  │   │
│   │ Does NOT filter by date - returns whatever is "live" NOW        │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                      │                   │
│                                                      ▼                   │
│   GCS Export                                                             │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │ gs://nba-props-platform-api/v1/live/                             │   │
│   │   ├── 2025-12-28.json  ← Date from get_today_date(), not BDL    │   │
│   │   └── latest.json      ← Copy of most recent export             │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Failure Modes Identified

### 1. Scheduler Timing Gap (PRIMARY ISSUE TODAY)

**Problem:** The scheduler window (7-11 PM ET) doesn't cover all game start times.

| Scenario | First Game | Scheduler Start | Gap |
|----------|-----------|-----------------|-----|
| Weekday | 7:00 PM ET | 7:00 PM ET | 0 min |
| Weekend/Holiday | 6:00 PM ET | 7:00 PM ET | **60 min** |
| Afternoon games | 3:30 PM ET | 7:00 PM ET | **3.5 hours** |
| Matinee (rare) | 12:00 PM ET | 7:00 PM ET | **7 hours** |

**Today's case:** PHI @ OKC started at 6:00 PM ET, scheduler starts at 7:00 PM ET.

### 2. Late-Night Date Mismatch

**Problem:** When the scheduler runs after midnight ET, `get_today_date()` returns the new day's date, but BDL returns the previous day's recently-finished games.

**Timeline of Dec 27-28 incident:**
```
11:57 PM Dec 27 ET  │  Last "evening" scheduler run
                    │  → BDL returns Dec 27 games (in progress)
                    │  → Exported as /live/2025-12-27.json ✓
────────────────────┼─────────────────────────────────────────
12:00 AM Dec 28 ET  │  Date flips to Dec 28
                    │
12:xx AM Dec 28 ET  │  "late-night" scheduler runs
                    │  → get_today_date() returns "2025-12-28"
                    │  → BDL returns Dec 27 games (just finished)
                    │  → Exported as /live/2025-12-28.json ✗ WRONG!
                    │  → latest.json updated with wrong data ✗
```

### 3. No Date Validation in Export Logic

**Problem:** `live_scores_exporter.py` doesn't validate that games from BDL match the target date.

```python
# Current code (simplified):
def generate_json(self, target_date: str):
    live_data = self._fetch_live_box_scores()  # No date param!
    return {
        'game_date': target_date,  # From get_today_date()
        'games': self._transform_games(live_data)  # Could be any date!
    }
```

**Result:** Whatever BDL returns gets labeled with the current ET date, regardless of the actual game date.

### 4. DST Handling Issue (Latent Bug)

**Problem:** `get_today_date()` uses hardcoded EST offset.

```python
# Current code:
et_offset = timedelta(hours=-5)  # EST only!
```

During EDT (March-November), this would be off by 1 hour, potentially causing:
- Wrong date label near midnight
- 1-hour shift in all date calculations

### 5. Gap Between Scheduler Windows

**Problem:** No coverage from 11 PM - 12 AM ET (1 hour gap).

```
Evening:    7 PM ─────────── 11 PM
Late-night:                       12 AM ─ 1 AM
            ▲                 ▲
            │                 └── 1 hour gap (11-12 PM)
            └── 1+ hour gap before first game
```

### 6. BDL API Reliability

**Problem:** The `/live` endpoint behavior is not well-documented and may:
- Return empty array between games
- Include games from multiple dates during crossover
- Have delays in updating final game status

---

## Solutions

### Immediate Fix (Applied)

Manually triggered the live export function:
```bash
curl -X POST "https://us-west2-nba-props-platform.cloudfunctions.net/live-export" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"target_date": "today"}'
```

### Short-Term Fixes (< 1 day effort each)

#### Fix 1: Expand Scheduler Window

Update schedulers to cover more game times:

```bash
# Evening scheduler: Start earlier (4 PM ET instead of 7 PM)
gcloud scheduler jobs update http live-export-evening \
  --location=us-west2 \
  --schedule="*/3 16-23 * * *"

# Also update BDL scraper scheduler
gcloud scheduler jobs update http bdl-live-boxscores-evening \
  --location=us-west2 \
  --schedule="*/3 16-23 * * *"
```

**Rationale:** Covers afternoon games (rare but happen), costs ~$0.10/month more in Cloud Function invocations.

#### Fix 2: Close the 11 PM - 12 AM Gap

Extend evening window to cover until late-night starts:

```bash
# Option A: Extend evening to midnight
gcloud scheduler jobs update http live-export-evening \
  --location=us-west2 \
  --schedule="*/3 16-23,0 * * *"  # 4 PM - midnight

# Option B: Start late-night at 11 PM
gcloud scheduler jobs update http live-export-late-night \
  --location=us-west2 \
  --schedule="*/3 23,0-1 * * *"  # 11 PM - 1 AM
```

#### Fix 3: Fix DST Handling

Update `get_today_date()` to use proper timezone:

```python
def get_today_date() -> str:
    """Get today's date in ET timezone (DST-aware)."""
    from zoneinfo import ZoneInfo
    et_now = datetime.now(ZoneInfo('America/New_York'))
    return et_now.strftime('%Y-%m-%d')
```

### Medium-Term Fixes (1-3 day effort)

#### Fix 4: Add Date Validation to Live Export

Modify `live_scores_exporter.py` to validate games match target date:

```python
def _transform_games(self, live_data: List[Dict], target_date: str) -> List[Dict]:
    games = []
    for box in live_data:
        game_date = box.get("date", "")[:10]  # "2025-12-28"
        if game_date != target_date:
            logger.warning(f"Skipping game from {game_date}, target is {target_date}")
            continue
        # ... rest of transformation
```

**Benefits:**
- Prevents date mismatch bugs
- Logs when mismatches occur for debugging
- More predictable behavior

#### Fix 5: Add "No Games Today" Handling

When BDL returns no games for today, export an explicit "no games" state:

```python
def generate_json(self, target_date: str):
    live_data = self._fetch_live_box_scores()

    # Filter to only today's games
    today_games = [g for g in live_data if g.get("date", "")[:10] == target_date]

    if not today_games and live_data:
        # BDL returned games but none are for today
        logger.info(f"BDL has {len(live_data)} games but none for {target_date}")
        return {
            'game_date': target_date,
            'status': 'pre_game',  # New field!
            'message': 'Games have not started yet',
            'games': []
        }
```

#### Fix 6: Add Self-Healing Check

Create a Cloud Function that runs at 6 PM ET daily to verify live data is ready:

```python
def check_live_data_ready():
    """Run at 6 PM ET to ensure live export is ready for games."""
    # 1. Check if there are games today
    # 2. If yes, trigger live-export
    # 3. Verify latest.json has today's date
    # 4. Alert if mismatch
```

### Long-Term Improvements (1+ week effort)

#### Improvement 1: Dynamic Scheduler Based on Game Schedule

Instead of fixed scheduler windows, dynamically create schedulers based on actual game times:

```python
# Pseudo-code for daily scheduler setup
def setup_daily_schedulers():
    games = get_todays_schedule()
    if not games:
        return

    first_game_time = min(g.start_time for g in games)
    last_game_time = max(g.start_time for g in games)

    # Start 30 min before first game, end 3 hours after last
    scheduler.update(
        start=first_game_time - 30min,
        end=last_game_time + 3hours
    )
```

**Benefits:**
- Perfect coverage every day
- No wasted runs on days without games
- Adapts to schedule changes (delays, etc.)

#### Improvement 2: Use BigQuery as Source of Truth

Instead of calling BDL API directly in the export function, use the `bdl_live_boxscores` table which already stores the scraped data with proper timestamps:

```python
def generate_json(self, target_date: str):
    query = """
    SELECT * FROM nba_raw.bdl_live_boxscores
    WHERE game_date = @target_date
    ORDER BY poll_timestamp DESC
    LIMIT 1000  -- Latest poll's data
    """
    # Use already-scraped and validated data
```

**Benefits:**
- Single source of truth
- Already has game_date column
- No duplicate API calls
- Better error handling

#### Improvement 3: Event-Driven Live Export

Instead of polling every 3 minutes, trigger live export when:
- BDL scraper completes successfully
- Game status changes (start, end, halftime)

```
BDL Scraper → Pub/Sub: "live-data-updated" → Live Export Function
```

**Benefits:**
- Real-time updates
- No wasted runs
- Guaranteed freshness

---

## Recommended Implementation Order

| Priority | Fix | Effort | Impact |
|----------|-----|--------|--------|
| 1 | Expand scheduler to 4 PM | 5 min | Prevents today's issue |
| 2 | Close 11 PM gap | 5 min | Prevents late-game gaps |
| 3 | Fix DST handling | 15 min | Prevents future bugs |
| 4 | Add date validation | 1 hour | Prevents date mismatch |
| 5 | Add pre-game status | 2 hours | Better UX |
| 6 | Self-healing check | 4 hours | Automated recovery |
| 7 | Dynamic scheduler | 1-2 days | Optimal coverage |
| 8 | BigQuery source | 1-2 days | Single source of truth |
| 9 | Event-driven | 3-5 days | Real-time, efficient |

---

## Commands for Immediate Fixes

```bash
# 1. Expand evening scheduler to 4 PM
gcloud scheduler jobs update http live-export-evening \
  --location=us-west2 \
  --schedule="*/3 16-23 * * *" \
  --description="Live scores export during games (4 PM - midnight ET)"

gcloud scheduler jobs update http bdl-live-boxscores-evening \
  --location=us-west2 \
  --schedule="*/3 16-23 * * *" \
  --description="BDL live box scores during games (4 PM - midnight ET)"

# 2. Verify the update
gcloud scheduler jobs describe live-export-evening --location=us-west2 --format="get(schedule)"

# 3. Manually trigger to get current data
curl -X POST "https://us-west2-nba-props-platform.cloudfunctions.net/live-export" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"target_date": "today"}'
```

---

## Monitoring Recommendations

Add these checks to daily monitoring:

```bash
# Check live data freshness
gsutil stat gs://nba-props-platform-api/v1/live/latest.json | grep Updated

# Verify date matches
gsutil cat gs://nba-props-platform-api/v1/live/latest.json | jq '.game_date'

# Check scheduler last run
gcloud scheduler jobs describe live-export-evening --location=us-west2 --format="get(lastAttemptTime)"
```

---

## Related Documentation

- [Phase 6 Publishing](../../../03-phases/phase6-publishing/README.md)
- [Daily Monitoring](../../../02-operations/daily-monitoring.md)
- [Self-Healing Pipeline](../self-healing-pipeline/README.md)
