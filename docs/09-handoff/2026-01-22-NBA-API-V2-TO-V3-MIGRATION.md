# NBA.com API V2 to V3 Migration Tracker

**Date:** January 22, 2026
**Last Updated:** January 22, 2026
**Status:** Complete - Monitoring for future deprecations
**Priority:** Reference document for quick response if V2 endpoints fail

---

## Executive Summary

NBA deprecated `boxscoretraditionalv2` for the 2025-26 season (stopped returning data Dec 27, 2025). We migrated `nbac_team_boxscore` to V3.

Other V2 endpoints still work but have V3 alternatives available. This document tracks endpoint status for quick migration if needed.

---

## Endpoint Status Tracker

### QUICK REFERENCE: If a scraper breaks, check here first

| Scraper | Current Endpoint | V2 Status | V3 Available | Action if V2 Fails |
|---------|------------------|-----------|--------------|-------------------|
| `nbac_team_boxscore` | `boxscoretraditionalv3` | DEPRECATED | ✅ **USING** | Already on V3 |
| `nbac_scoreboard_v2` | `scoreboardV2` | ✅ Working | ✅ Ready | See migration guide below |
| `nbac_player_boxscore` | `leaguegamelog` | ✅ Working | ❌ None | No V3 alternative |
| `nbac_schedule_api` | `scheduleleaguev2int` | ✅ Working | ❌ None | No V3 alternative |
| `nbac_player_list` | `playerindex` | ✅ Working | ❌ None | No V3 alternative |
| `nbac_play_by_play` | `cdn.nba.com` | N/A | N/A | Different API (CDN) |

**Last tested:** January 22, 2026

---

## Completed Migration

### nbac_team_boxscore ✅ MIGRATED

**Problem:** `boxscoretraditionalv2` returns empty data for 2025-26 season (since Dec 27, 2025).

**Solution:** Migrated to `boxscoretraditionalv3`.

**Commit:** `e57aa33f` - "fix: Migrate nbac_team_boxscore from V2 to V3 API endpoint"

**Backfill:** 199 games (Dec 27 - Jan 21) backfilled successfully.

---

## Ready to Migrate (If Needed)

### nbac_scoreboard_v2 - V3 READY

**File:** `scrapers/nbacom/nbac_scoreboard_v2.py`

**Current:** Uses `scoreboardV2`, converts response to V3 format internally.

**V3 Alternative:** `scoreboardv3` - works, tested Jan 22, 2026.

**Migration Steps (if V2 breaks):**

1. Update `set_url()` to use `BASE_V3` instead of `BASE_V2`:
```python
def set_url(self) -> None:
    """Set URL to V3 endpoint (V2 as fallback)"""
    mmddyyyy = self._mm_dd_yyyy()
    # Try V3 first
    self.url = f"{self.BASE_V3}?GameDate={mmddyyyy}&LeagueID=00"
    logger.info("NBA.com Scoreboard V3 URL: %s", self.url)
```

2. Update `download_and_decode()` to handle native V3 response (no conversion needed).

3. Keep V2 conversion logic as fallback.

**Note:** Scraper already has `BASE_V3` defined, just not used as primary.

---

## No V3 Alternative Available

These scrapers use endpoints with NO V3 equivalent. If they break, we need different solutions.

### nbac_player_boxscore
- **Endpoint:** `leaguegamelog`
- **Status:** Working
- **If breaks:** Would need to aggregate from `boxscoretraditionalv3` player data

### nbac_schedule_api
- **Endpoint:** `scheduleleaguev2int`
- **Status:** Working
- **If breaks:** Check `cdn.nba.com` schedule feeds as alternative

### nbac_player_list
- **Endpoint:** `playerindex`
- **Status:** Working
- **If breaks:** Check `commonallplayers` endpoint as alternative

---

## Not Affected by V2/V3 Migration

These scrapers don't use `stats.nba.com` API:

| Scraper | API Used | Notes |
|---------|----------|-------|
| `nbac_play_by_play` | `cdn.nba.com` | CDN feed, different system |
| `nbac_gamebook_pdf` | NBA.com PDFs | PDF downloads |
| `nbac_injury_report` | NBA.com PDFs | PDF parsing |
| `bdl_*` scrapers | BallDontLie API | Third-party API |
| `bp_*` scrapers | BettingPros API | Third-party API |
| `oddsa_*` scrapers | OddsAPI | Third-party API |

---

## V3 Response Structures (Reference)

### boxscoretraditionalv3 (team boxscore)
```json
{
  "boxScoreTraditional": {
    "gameId": "0022500571",
    "homeTeam": {
      "teamId": 1610612754,
      "teamTricode": "IND",
      "statistics": { "points": 101, "assists": 26, ... },
      "players": [{ "comment": "DND - Injury/Illness", ... }]
    },
    "awayTeam": { ... }
  }
}
```

### scoreboardv3 (daily games)
```json
{
  "scoreboard": {
    "games": [
      {
        "gameId": "0022500571",
        "homeTeam": { "teamTricode": "IND", "score": 101 },
        "awayTeam": { "teamTricode": "TOR", "score": 115 },
        "gameStatus": 3
      }
    ]
  }
}
```

---

## Testing Script

Use this to quickly test if endpoints are working:

```python
# test_nba_endpoints.py
import warnings
warnings.filterwarnings('ignore')
from nba_api.stats.endpoints import (
    boxscoretraditionalv2, boxscoretraditionalv3,
    scoreboardv2, scoreboardv3,
    leaguegamelog, playerindex
)

test_date = '2026-01-21'
test_game = '0022500571'

print('Endpoint Status Check')
print('=' * 50)

# Test each endpoint
tests = [
    ('boxscoretraditionalv2', lambda: boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=test_game)),
    ('boxscoretraditionalv3', lambda: boxscoretraditionalv3.BoxScoreTraditionalV3(game_id=test_game)),
    ('scoreboardv2', lambda: scoreboardv2.ScoreboardV2(game_date=test_date)),
    ('scoreboardv3', lambda: scoreboardv3.ScoreboardV3(game_date=test_date)),
    ('leaguegamelog', lambda: leaguegamelog.LeagueGameLog(season='2025-26')),
    ('playerindex', lambda: playerindex.PlayerIndex(season='2025-26')),
]

for name, test_fn in tests:
    try:
        result = test_fn()
        data = result.get_dict()
        print(f'  {name}: ✅ Working')
    except Exception as e:
        print(f'  {name}: ❌ {str(e)[:40]}')
```

---

## Historical Notes

- **Dec 27, 2025:** `boxscoretraditionalv2` stopped returning data for 2025-26 season games
- **Jan 22, 2026:** Migrated `nbac_team_boxscore` to V3, backfilled 199 games
- **Jan 22, 2026:** Confirmed `scoreboardv2` still works, V3 ready as backup

---

**Document Purpose:** Quick reference for API endpoint status and migration paths. Update this when endpoints change or break.
