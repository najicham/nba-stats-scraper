# NBA.com Team Boxscore API Investigation - Handoff

**Date:** January 22, 2026
**Priority:** P1 - HIGH (Losing injury data on fallback)
**Status:** Investigation complete, fix needed

---

## Executive Summary

The NBA.com `stats.nba.com/stats/boxscoretraditionalv2` API has been returning **empty data** since December 27, 2025. This affects the `nbac_team_boxscore` scraper. While the system has a fallback mechanism using gamebook player stats, **the fallback loses critical injury information** that only the team boxscore provides.

**Key Issue:** When using fallback, we lose the ability to identify which players were injured for specific games. The NBA.com team boxscore includes injured player names in its response, but BDL and gamebook fallbacks do not.

---

## Your Mission

1. **Deep dive** into why the NBA.com API returns empty `TeamStats.rowSet`
2. **Add detailed logging** to capture the exact API response for debugging
3. **Test alternative approaches** (different endpoints, parameters, headers)
4. **Find a solution** to restore team boxscore scraping with injury data
5. **Document findings** for future reference

---

## Technical Details

### The Scraper

**File:** `/home/naji/code/nba-stats-scraper/scrapers/nbacom/nbac_team_boxscore.py`

```python
# Key configuration
BASE_URL = "https://stats.nba.com/stats/boxscoretraditionalv2"
header_profile = "stats"  # Uses modern Chrome 140 headers
proxy_enabled = True

# URL format
url = f"{BASE_URL}?GameID={game_id}&StartPeriod=0&EndPeriod=10&StartRange=0&EndRange=28800&RangeType=0"

# Validation expects 2 teams per game
if len(row_set) != 2:
    raise DownloadDataException(f"Expected 2 teams for game {game_id}, got {len(row_set)}")
```

### The Error

```
ERROR:scraper_base:Expected 2 teams for game 0022500571, got 0
scrapers.utils.exceptions.DownloadDataException: Expected 2 teams for game 0022500571, got 0
```

### What We Know

| Fact | Evidence |
|------|----------|
| Proxy works | Logs show "Proxy success: http://...@gate2.proxyfuel.com:2000, took=1.2s" |
| Request succeeds | HTTP 200 OK, valid JSON returned |
| Headers are modern | Chrome 140, Sec-Ch-Ua headers, Sept 2025 nba_api format |
| Response structure OK | Has `resultSets` array with `TeamStats` object |
| Data is empty | `TeamStats.rowSet = []` (0 teams instead of 2) |
| Started Dec 27, 2025 | 148 failures logged from that date |

### Headers Being Used

**File:** `/home/naji/code/nba-stats-scraper/scrapers/utils/nba_header_utils.py`

```python
def stats_nba_headers() -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Host": "stats.nba.com",
        "Origin": "https://www.nba.com",
        "Pragma": "no-cache",
        "Referer": "https://www.nba.com/",
        "Sec-Ch-Ua": '"Chromium";v="140", "Google Chrome";v="140", "Not;A=Brand";v="24"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
    }
```

---

## Recommended Investigation Steps

### Step 1: Add Detailed Response Logging

The scraper saves debug files but we need to see the actual content. Check:

```bash
# In the Cloud Run logs, these files are saved:
/tmp/debug_raw_<run_id>.html
/tmp/debug_decoded_<run_id>.json
```

**Add logging to capture:**
- Full response body (first 1000 chars)
- All resultSets names and their rowSet lengths
- Response headers from NBA.com
- Any error messages in the response

### Step 2: Test Different Approaches

**A) Try different game IDs:**
```bash
# Recent completed game
curl -X POST "https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "nbac_team_boxscore", "game_id": "0022500580", "game_date": "2026-01-22", "export_groups": "dev"}'
```

**B) Test the API directly (bypass scraper):**
```bash
curl -s "https://stats.nba.com/stats/boxscoretraditionalv2?GameID=0022500571&StartPeriod=0&EndPeriod=10&StartRange=0&EndRange=28800&RangeType=0" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36" \
  -H "Referer: https://www.nba.com/" \
  -H "Origin: https://www.nba.com" \
  | jq '.resultSets[] | {name: .name, rowCount: (.rowSet | length)}'
```

**C) Try alternative endpoints:**
- `boxscoresummaryv2` - Different endpoint, might work
- `boxscoreadvancedv2` - Advanced stats version
- `boxscoreplayertrackv2` - Player tracking version

**D) Test with nba_api library:**
```python
# Install: pip install nba_api
from nba_api.stats.endpoints import boxscoretraditionalv2
box = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id="0022500571")
print(box.get_dict())
```

### Step 3: Check Cloud Run Logs

```bash
# Get recent logs with full detail
gcloud run services logs read nba-phase1-scrapers --region=us-west2 --limit=100 2>&1 | grep -E "team_boxscore|TeamStats|rowSet|Expected|Error"

# Check for any rate limiting or blocking
gcloud run services logs read nba-phase1-scrapers --region=us-west2 --limit=100 2>&1 | grep -E "429|403|blocked|rate"
```

### Step 4: Compare Working vs Broken Scrapers

**Working scrapers (use same proxy/headers):**
- `bdl_games_scraper` - BallDontLie API ✅
- `nbac_gamebook_pdf` - NBA.com gamebook PDFs ✅

**Broken scrapers (stats.nba.com):**
- `nbac_team_boxscore` - Team box scores ❌
- `nbac_player_boxscore` - Player box scores ❌ (also failing)
- `nbac_scoreboard_v2` - Scoreboard ❌

This suggests the entire `stats.nba.com` API tier is affected.

---

## Why This Matters: Injury Data

**Critical context the user provided:**

> The NBA.com gamebook boxscore is important because it has injured player names in it. BDL doesn't have that, so whenever we use the fallback, we lose valuable information that a player was injured for a specific game and we can mark it in the DB as injured.

### Data Comparison

| Source | Has Injury Data | Team Stats | Player Stats |
|--------|-----------------|------------|--------------|
| `nbac_team_boxscore` | ✅ YES | ✅ Direct | ❌ No |
| `nbac_gamebook_player_stats` | ⚠️ Partial | ❌ Aggregate only | ✅ Yes |
| `bdl_player_boxscores` | ❌ NO | ❌ Aggregate only | ✅ Yes |

### Impact of Using Fallback

When we fall back to gamebook/BDL:
1. ✅ Team stats can be reconstructed by aggregating player stats
2. ❌ **Injury information is LOST** - we don't know who was injured
3. ❌ Can't properly mark players as injured in the database
4. ❌ Affects downstream injury-aware predictions

---

## Current Workaround Status

The backfill completed successfully using fallback:

| Table | Records | Quality |
|-------|---------|---------|
| team_offense_game_summary | 372 (26 dates) | Silver (fallback) |
| team_defense_game_summary | 372 (26 dates) | Silver (fallback) |
| player_prop_predictions (Jan 21) | 869 | Working |

**But we're missing injury data for all games Dec 27 - Jan 21.**

---

## Files to Study

### Scraper Code
- `/home/naji/code/nba-stats-scraper/scrapers/nbacom/nbac_team_boxscore.py` - Main scraper
- `/home/naji/code/nba-stats-scraper/scrapers/scraper_base.py` - Base class with download logic
- `/home/naji/code/nba-stats-scraper/scrapers/utils/nba_header_utils.py` - Headers

### Related Scrapers (for comparison)
- `/home/naji/code/nba-stats-scraper/scrapers/nbacom/nbac_player_boxscore.py` - Also broken
- `/home/naji/code/nba-stats-scraper/scrapers/nbacom/nbac_gamebook_pdf.py` - Working
- `/home/naji/code/nba-stats-scraper/scrapers/balldontlie/bdl_box_scores.py` - Working

### Backfill Scripts
- `/home/naji/code/nba-stats-scraper/backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py`
- `/home/naji/code/nba-stats-scraper/backfill_jobs/scrapers/nbac_team_boxscore/game_ids_to_scrape.csv` - 100 games queued

### Processor Fallback Logic
- `/home/naji/code/nba-stats-scraper/data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py`
  - Look for `_reconstruct_team_from_players()` method
- `/home/naji/code/nba-stats-scraper/data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`

### Documentation
- `/home/naji/code/nba-stats-scraper/docs/08-projects/current/team-boxscore-data-gap-incident/` - Incident reports

---

## Commands to Test

### Test the Scraper Service
```bash
# Health check
curl -s "https://nba-phase1-scrapers-756957797294.us-west2.run.app/health" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)"

# Test team boxscore scraper
curl -s -X POST "https://nba-phase1-scrapers-756957797294.us-west2.run.app/scrape" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "nbac_team_boxscore", "game_id": "0022500571", "game_date": "2026-01-21", "export_groups": "prod"}'
```

### Check BigQuery Data
```sql
-- Check team boxscore raw data (should be empty for gap period)
SELECT game_date, COUNT(*) as records
FROM `nba-props-platform.nba_raw.nbac_team_boxscore`
WHERE game_date BETWEEN '2025-12-27' AND '2026-01-21'
GROUP BY game_date ORDER BY game_date;

-- Check gamebook data (fallback source, should have data)
SELECT game_date, COUNT(DISTINCT game_id) as games, COUNT(*) as players
FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
WHERE game_date BETWEEN '2025-12-27' AND '2026-01-21'
GROUP BY game_date ORDER BY game_date;

-- Check if team stats were reconstructed
SELECT game_date, COUNT(*) as records
FROM `nba-props-platform.nba_analytics.team_offense_game_summary`
WHERE game_date BETWEEN '2025-12-27' AND '2026-01-21'
GROUP BY game_date ORDER BY game_date;
```

### View Cloud Run Logs
```bash
gcloud run services logs read nba-phase1-scrapers --region=us-west2 --limit=50
```

---

## Potential Solutions to Explore

### Solution 1: Fix the stats.nba.com Scraper
- Add more detailed logging to see exact response
- Try different URL parameters
- Test if certain game IDs work vs others
- Check if there's a rate limit or IP block

### Solution 2: Alternative NBA.com Endpoints
- `boxscoresummaryv2` - May have team data
- `boxscoreadvancedv2` - Advanced stats
- Check nba_api library for other endpoints

### Solution 3: Different Proxy Configuration
- Try without proxy to see if that's the issue
- Try different proxy endpoints
- Check if residential vs datacenter IP matters

### Solution 4: Scrape from nba.com Website
- The website still shows box scores
- Could parse HTML instead of API
- More brittle but might work

### Solution 5: Hybrid Approach
- Use gamebook for player stats
- Separately scrape injury reports
- Merge data in processor

---

## Questions to Answer

1. **Is the API returning empty data for ALL games or just some?**
2. **Does the NBA website still show the data?** (If yes, API is just blocked)
3. **Are there any successful calls in recent logs?**
4. **What does the full API response look like?** (Need to see actual content)
5. **Does nba_api Python library have the same issue?**
6. **Is there an injury report endpoint we could use separately?**

---

## Context From Previous Session

### What Was Done
1. ✅ Ran team boxscore backfill - ALL 100 GAMES FAILED with "Expected 2 teams, got 0"
2. ✅ Verified proxy works (logs show successful proxy connection)
3. ✅ Verified headers are modern (Chrome 140, Sept 2025 format)
4. ✅ Ran Phase 3 processors with fallback - 372 team records created
5. ✅ Ran Phase 4 precompute - All tables populated
6. ✅ Verified predictions exist for Jan 21 - 869 predictions

### What Was NOT Done
- ❌ Did not see the actual API response content
- ❌ Did not test alternative endpoints
- ❌ Did not add enhanced logging
- ❌ Did not test with nba_api library
- ❌ Did not find root cause of empty rowSet

---

## Success Criteria

1. **Understand** exactly why the API returns empty data
2. **Either fix** the scraper to get team boxscore data with injury info
3. **Or document** a workaround that preserves injury data
4. **Add monitoring** to detect this issue faster in future

---

**Document Status:** Ready for new chat to continue investigation
**Estimated Effort:** 2-4 hours of investigation and testing
