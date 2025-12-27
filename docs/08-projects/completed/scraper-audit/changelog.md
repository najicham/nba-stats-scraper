# Scraper Audit Changelog

## 2025-11-25 - Initial Audit Complete

### Session Summary
Completed comprehensive audit of all GCS scraper data for seasons 2021-22 through 2024-25.

### Key Findings

**17 Backfillable Scrapers Identified:**
- 4 empty (need full backfill)
- 3 partial (specific gaps found)
- 10 complete (verified)

**Critical Blocker Found:**
- `GetNbaComTeamBoxscore` has only 1 date (needs 5,299 games)
- This blocks Phase 3 processors (team_offense/defense_game_summary)

### Detailed Results

**Empty Scrapers:**
| Scraper | Current | Need |
|---------|---------|------|
| GetNbaComTeamBoxscore | 1 date | 5,299 games |
| GetNbaComPlayerBoxscore | 13 dates | 853 dates |
| GetNbaComPlayByPlay | 2 dates | 5,299 games |
| GetEspnBoxscore | 1 date | 5,299 games |

**Partial Scrapers:**
| Scraper | Gap | Reason |
|---------|-----|--------|
| OddsAPI GameLines | ~104 dates | Playoffs missing (API limit?) |
| BigDataBall | 6 dates | All-Star weekends (expected) |
| BdlStandings | 2 seasons | Missing 2021-23 |

**Verified Complete:**
- BdlBoxScoresScraper (893 dates)
- GetNbaComGamebooks (888 dates, file counts verified)
- BigDataBallPbpScraper (847 dates, folder counts verified)
- GetEspnScoreboard (1,343 dates)
- BasketballRefSeasonRoster (120 files)
- All Odds/BettingPros historical scrapers
- Schedule and PlayerMovement scrapers

### Files Created
- `docs/08-projects/current/scraper-audit/plan.md` - Full audit plan
- `docs/08-projects/current/scraper-audit/checklist.md` - Task tracking
- `docs/08-projects/current/scraper-audit/changelog.md` - This file

### Next Steps
1. Export game_ids from nbac_schedule for per-game backfills
2. Run GetNbaComTeamBoxscore backfill (CRITICAL)
3. Address remaining backfills by priority
