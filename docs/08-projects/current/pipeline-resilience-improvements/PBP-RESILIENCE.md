# Play-by-Play Data Resilience

## Problem: 2/7 Games Missing PBP Data (Jan 27, 2026)

### Root Cause Analysis

1. **BigDataBall releases files at variable times** (sometimes hours after game ends)
2. **Scraper runs once** at post-game window with **no retry logic**
3. **If file isn't uploaded yet**, game is permanently missed
4. **BDB PBP monitor detects gaps** but doesn't trigger re-scraping

### Current Architecture

```
Game Ends (~10 PM ET)
        ↓
Scraper Runs (~10:15 PM ET)
        ↓
BDB File Not Ready? → Game Missed (no retry)
        ↓
Monitor Detects Gap (next day)
        ↓
Manual Investigation Required
```

### Proposed Architecture

```
Game Ends (~10 PM ET)
        ↓
Scraper Runs (Window 1: 10:15 PM ET)
        ↓
BDB File Not Ready? → Queue for Retry
        ↓
Retry Window 2 (1:00 AM ET)
        ↓
Still Missing? → Try NBA.com PBP Fallback
        ↓
Retry Window 3 (4:00 AM ET - final)
        ↓
Still Missing? → Alert + Mark for Manual Review
```

## NBA.com PBP as Fallback

### Comparison: BigDataBall vs NBA.com PBP

| Feature | BigDataBall | NBA.com |
|---------|-------------|---------|
| **Availability** | Variable (hours delay) | Fast (~15 min after game) |
| **Lineup Data** | ✅ Full 10-player tracking | ❌ Not included |
| **Shot Coordinates** | ✅ Dual coordinate systems | ❌ Not included |
| **Timing Data** | ✅ elapsed_time, play_length | ❌ Not included |
| **Reliability** | Variable | High |

### Recommendation

**Use NBA.com PBP as supplementary source** during BDB delays:
- ✅ Can provide basic play-by-play for analytics
- ✅ More reliable availability
- ❌ Missing lineup data (critical for some analytics)

**Implementation:**
1. If BDB fails, try NBA.com PBP
2. Store with `data_source = 'nbacom'` marker
3. Phase 3 processors use BDB if available, else NBA.com

## Implementation Plan

### Step 1: Add Retry Logic to BDB Scraper

```python
# In scrapers/bigdataball/bigdataball_pbp.py
MAX_RETRIES = 3
RETRY_DELAYS = [30, 60, 120]  # seconds

def scrape_with_retry(self, game_id, game_date):
    for attempt, delay in enumerate(RETRY_DELAYS):
        try:
            data = self.scrape_game(game_id, game_date)
            if data:
                return data
        except GameNotFoundError:
            if attempt < len(RETRY_DELAYS) - 1:
                logger.info(f"Game {game_id} not found, retrying in {delay}s")
                time.sleep(delay)
            else:
                raise
```

### Step 2: Add Staggered Scraping Windows

```yaml
# In config/workflows.yaml
bigdataball_pbp:
  windows:
    - name: immediate
      trigger: post_game + 15min
      retry_on_miss: true
    - name: delayed
      trigger: post_game + 3h
      only_if: games_missing
    - name: final
      trigger: post_game + 6h
      only_if: games_missing
      fallback: nbacom_pbp
```

### Step 3: Add NBA.com Fallback

```python
# In data_processors/raw/bigdataball_pbp_processor.py
def process(self, game_id, game_date):
    # Try BDB first
    bdb_data = self.fetch_bdb_data(game_id, game_date)
    
    if bdb_data:
        return self.transform_bdb(bdb_data)
    
    # Fallback to NBA.com
    logger.warning(f"BDB missing for {game_id}, using NBA.com fallback")
    nbacom_data = self.fetch_nbacom_pbp(game_id)
    
    if nbacom_data:
        return self.transform_nbacom(nbacom_data, source='nbacom_fallback')
    
    raise DataNotAvailableError(f"No PBP data for {game_id}")
```

### Step 4: Monitor Trigger Re-Scraping

```python
# In bin/monitoring/bdb_pbp_monitor.py
def check_and_recover(self, game_date):
    gaps = self.find_gaps(game_date)
    
    for gap in gaps:
        if gap.age_hours < 6:
            # Recent gap - trigger retry
            self.trigger_scraper_retry(gap.game_id)
        elif gap.age_hours < 24:
            # Delayed gap - try fallback
            self.trigger_fallback_scrape(gap.game_id)
        else:
            # Old gap - escalate
            self.escalate_to_slack(gap)
```

## Metrics to Track

| Metric | Target | Current |
|--------|--------|---------|
| BDB coverage (first attempt) | 90%+ | ~70% |
| BDB coverage (after retries) | 98%+ | N/A |
| Total PBP coverage (BDB + fallback) | 99%+ | ~70% |
| Time to detect gap | <15 min | 12+ hours |
| Time to recover gap | <3 hours | Manual |

## Files to Modify

1. `scrapers/bigdataball/bigdataball_pbp.py` - Add retry logic
2. `config/workflows.yaml` - Add staggered windows
3. `bin/monitoring/bdb_pbp_monitor.py` - Add auto-retry trigger
4. `data_processors/raw/bigdataball_pbp_processor.py` - Add fallback
