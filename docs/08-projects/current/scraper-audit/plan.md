# Scraper Audit Plan

**Created:** 2025-11-25
**Updated:** 2025-11-25
**Purpose:** Verify GCS has complete scraped data for all 4 seasons before Phase 2 processing

---

## Ground Truth: Expected Games

From `nbac_schedule`:

| Season | Games | Dates | First Game | Last Game |
|--------|-------|-------|------------|-----------|
| 2021-22 | 1,327 | 215 | 2021-10-19 | 2022-06-16 |
| 2022-23 | 1,324 | 214 | 2022-10-18 | 2023-06-12 |
| 2023-24 | 1,322 | 209 | 2023-10-24 | 2024-06-17 |
| 2024-25 | 1,326 | 215 | 2024-10-22 | 2025-06-22 |
| **Total** | **5,299** | **853** | | |

---

## Complete Scraper Inventory

### All Scrapers by Source

#### Odds API (6 scrapers)

| # | Scraper | GCS Path | Backfillable | Expected | Notes |
|---|---------|----------|--------------|----------|-------|
| 1 | `GetOddsApiEvents` | `odds-api/events/` | No | - | Current only |
| 2 | `GetOddsApiCurrentEventOdds` | `odds-api/player-props/` | No | - | Current only |
| 3 | `GetOddsApiCurrentGameLines` | `odds-api/game-lines/` | No | - | Current only |
| 4 | `GetOddsApiHistoricalEvents` | `odds-api/events-history/` | **Yes** | 853 dates | Full history |
| 5 | `GetOddsApiHistoricalEventOdds` | `odds-api/player-props-history/` | **Yes** | ~450 dates | May 2023+ API limit |
| 6 | `GetOddsApiHistoricalGameLines` | `odds-api/game-lines-history/` | **Yes** | 853 dates | Full history |

#### NBA.com (10 scrapers)

| # | Scraper | GCS Path | Backfillable | Expected | Notes |
|---|---------|----------|--------------|----------|-------|
| 7 | `GetNbaComPlayerList` | `nba-com/player-list/` | No | - | Current snapshot |
| 8 | `GetNbaComPlayerMovement` | `nba-com/player-movement/` | **Yes** | 4 years | By year |
| 9 | `GetNbaComRefereeAssignments` | `nba-com/referee-assignments/` | No | - | Day-before only |
| 10 | `GetNbaComScheduleApi` | `nba-com/schedule/` | **Yes** | 4 seasons | By season |
| 11 | `GetNbaComScheduleCdn` | `nba-com/schedule-metadata/` | No | - | Backup/monitoring |
| 12 | `GetNbaComInjuryReport` | `nba-com/injury-report-data/` | **Yes** | 853 dates | By date |
| 13 | `GetNbaComTeamBoxscore` | `nba-com/team-boxscore/` | **Yes** | 5,299 games | By game_id - **CRITICAL** |
| 14 | `GetNbaComPlayerBoxscore` | `nba-com/player-boxscores/` | **Yes** | 853 dates | By date |
| 15 | `GetNbaComPlayByPlay` | `nba-com/play-by-play/` | **Yes** | 5,299 games | By game_id |
| 16 | `GetNbaComGamebooks` | `nba-com/gamebooks-data/`, `gamebooks-pdf/` | **Yes** | 853 dates | By date - **CRITICAL** |

#### Ball Don't Lie (4 scrapers)

| # | Scraper | GCS Path | Backfillable | Expected | Notes |
|---|---------|----------|--------------|----------|-------|
| 18 | `BdlActivePlayersScraper` | `ball-dont-lie/active-players/` | No | - | Current only |
| 19 | `BdlInjuriesScraper` | `ball-dont-lie/injuries/` | No | - | Current only |
| 20 | `BdlBoxScoresScraper` | `ball-dont-lie/boxscores/` | **Yes** | 853 dates | By date - **CRITICAL** |
| 21 | `BdlStandingsScraper` | `ball-dont-lie/standings/` | **Yes** | 4 seasons | By season |

#### BigDataBall (1 scraper)

| # | Scraper | GCS Path | Backfillable | Expected | Notes |
|---|---------|----------|--------------|----------|-------|
| 22 | `BigDataBallPbpScraper` | `big-data-ball/{season}/{date}/` | **Yes** | 5,299 games | By game_id |

#### ESPN (3 scrapers)

| # | Scraper | GCS Path | Backfillable | Expected | Notes |
|---|---------|----------|--------------|----------|-------|
| 23 | `GetEspnScoreboard` | `espn/scoreboard/` | **Yes** | 853 dates | By date |
| 24 | `GetEspnBoxscore` | `espn/boxscores/` | **Yes** | 5,299 games | By game_id |
| 25 | `GetEspnTeamRoster` | `espn/rosters/` | No | - | Current roster only |

#### Basketball Reference (1 scraper)

| # | Scraper | GCS Path | Backfillable | Expected | Notes |
|---|---------|----------|--------------|----------|-------|
| 26 | `BasketballRefSeasonRoster` | `basketball-ref/season-rosters/` | **Yes** | 120 (30×4) | By team/year |

#### BettingPros (2 scrapers)

| # | Scraper | GCS Path | Backfillable | Expected | Notes |
|---|---------|----------|--------------|----------|-------|
| 27 | `GetBettingProEvents` | `bettingpros/events/` | **Yes** | 853 dates | By date |
| 28 | `GetBettingProPlayerProps` | `bettingpros/player-props/points/` | **Yes** | 853 dates | By date |

---

## Backfillable Scrapers Summary (17 total)

### Category A: Per-Game Scrapers (need 1 file per game = 5,299 files)

| # | Scraper | GCS Path | Priority | Notes |
|---|---------|----------|----------|-------|
| 1 | `GetNbaComTeamBoxscore` | `nba-com/team-boxscore/` | **CRITICAL** | Blocks Phase 3 |
| 2 | `GetNbaComPlayByPlay` | `nba-com/play-by-play/` | Medium | Have BigDataBall backup |
| 3 | `GetEspnBoxscore` | `espn/boxscores/` | Low | Backup only |
| 4 | `BigDataBallPbpScraper` | `big-data-ball/{season}/{date}/` | High | Shot zone analysis |

### Category B: Per-Date Scrapers (need files for 853 dates)

| # | Scraper | GCS Path | Priority | Notes |
|---|---------|----------|----------|-------|
| 5 | `BdlBoxScoresScraper` | `ball-dont-lie/boxscores/` | **CRITICAL** | Primary player stats |
| 6 | `GetNbaComGamebooks` | `nba-com/gamebooks-data/` | **CRITICAL** | DNP reasons |
| 7 | `GetNbaComPlayerBoxscore` | `nba-com/player-boxscores/` | Medium | Backup player stats |
| 8 | `GetNbaComInjuryReport` | `nba-com/injury-report-data/` | Medium | Injury history |
| 9 | `GetEspnScoreboard` | `espn/scoreboard/` | Medium | Game validation |
| 10 | `GetBettingProEvents` | `bettingpros/events/` | Medium | Odds backup |
| 11 | `GetBettingProPlayerProps` | `bettingpros/player-props/` | Medium | Props backup |

### Category C: Historical Odds (API-limited dates)

| # | Scraper | GCS Path | Priority | Date Range |
|---|---------|----------|----------|------------|
| 12 | `GetOddsApiHistoricalEvents` | `odds-api/events-history/` | High | Oct 2021 - Jun 2025 |
| 13 | `GetOddsApiHistoricalGameLines` | `odds-api/game-lines-history/` | High | Oct 2021 - Jun 2025 |
| 14 | `GetOddsApiHistoricalEventOdds` | `odds-api/player-props-history/` | High | **May 2023+** only |

### Category D: Per-Season/Reference (4 seasons × items)

| # | Scraper | GCS Path | Priority | Expected |
|---|---------|----------|----------|----------|
| 15 | `GetNbaComScheduleApi` | `nba-com/schedule/` | High | 4 seasons |
| 16 | `GetNbaComPlayerMovement` | `nba-com/player-movement/` | Low | 4 years |
| 17 | `BdlStandingsScraper` | `ball-dont-lie/standings/` | Low | 4 seasons |
| 18 | `BasketballRefSeasonRoster` | `basketball-ref/season-rosters/` | Medium | 120 team-seasons |
| 19 | `GetEspnTeamRoster` | `espn/rosters/` | Low | 120 team-seasons |

### Category E: Unknown/Deprecated

| # | Scraper | GCS Path | Status |
|---|---------|----------|--------|
| 20 | `?` (Scoreboard V2) | `nba-com/scoreboard-v2/` | May work for past seasons only |

---

## Non-Backfillable Scrapers (8 total)

| Scraper | Reason |
|---------|--------|
| `GetOddsApiEvents` | Current live events only |
| `GetOddsApiCurrentEventOdds` | Current live props only |
| `GetOddsApiCurrentGameLines` | Current live lines only |
| `GetNbaComPlayerList` | Current roster snapshot |
| `GetNbaComRefereeAssignments` | Published day before game |
| `GetNbaComScheduleCdn` | Backup/monitoring only |
| `BdlActivePlayersScraper` | Current active players |
| `BdlInjuriesScraper` | Current injuries |

---

## Audit Methodology

### For Per-Game Scrapers (Category A)

```sql
-- Get expected games per date from schedule
SELECT game_date, COUNT(*) as expected_games, ARRAY_AGG(game_id) as game_ids
FROM nbac_schedule
WHERE game_date BETWEEN '2021-10-01' AND '2025-06-30'
GROUP BY game_date
```

For each date:
1. List files in GCS: `gsutil ls gs://nba-scraped-data/{path}/{date}/`
2. Count files
3. Compare to expected_games
4. Flag if count < expected

### For Per-Date Scrapers (Category B)

1. Get all expected dates from schedule
2. Check if GCS folder exists for each date
3. Check if folder has at least 1 file
4. For gamebooks: check file count matches game count

### For Historical Odds (Category C)

1. Check date coverage matches expected range
2. Verify files exist for each date
3. Note: player-props only available May 2023+

---

## Audit Priority Order

### Priority 1: CRITICAL (Block Phase 3)
1. `GetNbaComTeamBoxscore` - **Almost empty, blocks team processors**
2. `BdlBoxScoresScraper` - Appears complete, verify
3. `GetNbaComGamebooks` - Appears complete, verify

### Priority 2: HIGH (Important for predictions)
4. `BigDataBallPbpScraper` - Shot zone analysis
5. `GetOddsApiHistoricalEvents` - Revenue/odds
6. `GetOddsApiHistoricalGameLines` - Revenue/odds
7. `GetOddsApiHistoricalEventOdds` - Revenue/odds (May 2023+)

### Priority 3: MEDIUM (Enrichment/Validation)
8. `GetNbaComPlayerBoxscore` - **Almost empty**
9. `GetNbaComPlayByPlay` - **Almost empty**
10. `GetNbaComInjuryReport` - Complete, verify
11. `GetEspnScoreboard` - Complete, verify
12. `GetEspnBoxscore` - **Almost empty**
13. `GetBettingProEvents` - Complete, verify
14. `GetBettingProPlayerProps` - Complete, verify
15. `BasketballRefSeasonRoster` - Name mapping

### Priority 4: LOW (Reference)
16. `GetNbaComScheduleApi` - Already have
17. `GetNbaComPlayerMovement` - Transactions
18. `BdlStandingsScraper` - Standings

---

## Current GCS Status (All Scrapers)

### Category A: Per-Game Scrapers

| # | Scraper | GCS Path | Count | Expected | Status |
|---|---------|----------|-------|----------|--------|
| 1 | `GetNbaComTeamBoxscore` | `nba-com/team-boxscore/` | **1 date** | 853 dates | ❌ **CRITICAL - EMPTY** |
| 2 | `GetNbaComPlayByPlay` | `nba-com/play-by-play/` | **2 dates** | 853 dates | ❌ **EMPTY** |
| 3 | `GetEspnBoxscore` | `espn/boxscores/` | **1 date** | 853 dates | ❌ **EMPTY** |
| 4 | `BigDataBallPbpScraper` | `big-data-ball/` | 847 dates | 853 dates | ✅ ~99% |

### Category B: Per-Date Scrapers

| # | Scraper | GCS Path | Count | Expected | Status |
|---|---------|----------|-------|----------|--------|
| 5 | `BdlBoxScoresScraper` | `ball-dont-lie/boxscores/` | 893 dates | 853 dates | ✅ Complete |
| 6 | `GetNbaComGamebooks` | `nba-com/gamebooks-data/` | 888 dates | 853 dates | ✅ Complete |
| 7 | `GetNbaComPlayerBoxscore` | `nba-com/player-boxscores/` | **13 dates** | 853 dates | ❌ **EMPTY** |
| 8 | `GetNbaComInjuryReport` | `nba-com/injury-report-data/` | 922 dates | 853 dates | ✅ Complete |
| 9 | `GetEspnScoreboard` | `espn/scoreboard/` | 1,343 dates | 853 dates | ✅ Overcomplete |
| 10 | `GetBettingProEvents` | `bettingpros/events/` | 878 dates | 853 dates | ✅ Complete |
| 11 | `GetBettingProPlayerProps` | `bettingpros/player-props/points/` | 865 dates | 853 dates | ✅ Complete |

### Category C: Historical Odds

| # | Scraper | GCS Path | Count | Expected | Status |
|---|---------|----------|-------|----------|--------|
| 12 | `GetOddsApiHistoricalEvents` | `odds-api/events-history/` | 848 dates | 853 dates | ✅ ~99% |
| 13 | `GetOddsApiHistoricalGameLines` | `odds-api/game-lines-history/` | 749 dates | 853 dates | ⚠️ ~88% |
| 14 | `GetOddsApiHistoricalEventOdds` | `odds-api/player-props-history/` | 447 dates | ~450 (May 2023+) | ✅ ~99% |

### Category D: Per-Season/Reference

| # | Scraper | GCS Path | Count | Expected | Status |
|---|---------|----------|-------|----------|--------|
| 15 | `GetNbaComScheduleApi` | `nba-com/schedule/` | 6 seasons | 4 seasons | ✅ Complete |
| 16 | `GetNbaComPlayerMovement` | `nba-com/player-movement/` | 6 years | 4 years | ✅ Complete |
| 17 | `BdlStandingsScraper` | `ball-dont-lie/standings/` | 2 seasons | 4 seasons | ⚠️ ~50% |
| 18 | `BasketballRefSeasonRoster` | `basketball-ref/season-rosters/` | 120 files | 120 team-seasons | ✅ Complete |

---

## Summary: Scrapers Needing Backfill

### ❌ Empty/Critical (need full backfill)

| Scraper | Current | Expected | Gap |
|---------|---------|----------|-----|
| `GetNbaComTeamBoxscore` | 1 date | 853 dates | **852 dates** |
| `GetNbaComPlayerBoxscore` | 13 dates | 853 dates | **840 dates** |
| `GetNbaComPlayByPlay` | 2 dates | 853 dates | **851 dates** |
| `GetEspnBoxscore` | 1 date | 853 dates | **852 dates** |

### ⚠️ Partial (need gap analysis)

| Scraper | Current | Expected | Gap |
|---------|---------|----------|-----|
| `GetOddsApiHistoricalGameLines` | 749 dates | 853 dates | ~104 dates |
| `BigDataBallPbpScraper` | 847 dates | 853 dates | ~6 dates (All-Star) |
| `BdlStandingsScraper` | 2 seasons | 4 seasons | 2 seasons |

### ✅ Complete (verify file counts per date)

| Scraper | Current | Expected |
|---------|---------|----------|
| `BdlBoxScoresScraper` | 893 dates | 853 dates |
| `GetNbaComGamebooks` | 888 dates | 853 dates |
| `GetNbaComInjuryReport` | 922 dates | 853 dates |
| `GetEspnScoreboard` | 1,343 dates | 853 dates |
| `GetBettingProEvents` | 878 dates | 853 dates |
| `GetBettingProPlayerProps` | 865 dates | 853 dates |
| `GetOddsApiHistoricalEvents` | 848 dates | 853 dates |
| `GetOddsApiHistoricalEventOdds` | 447 dates | ~450 (May 2023+) |
| `GetNbaComScheduleApi` | 6 seasons | 4 seasons |
| `GetNbaComPlayerMovement` | 6 years | 4 years |
| `BasketballRefSeasonRoster` | 120 files | 120 (30×4 seasons) |

---

## Detailed Audit Results (2025-11-25)

### ✅ Verified Complete

| Scraper | Dates | Files/Date | Notes |
|---------|-------|------------|-------|
| `BdlBoxScoresScraper` | 893 | 1 per date | All games in single file per date |
| `GetNbaComGamebooks` | 888 | Matches expected | 2-11 files/date matching game count |
| `BigDataBallPbpScraper` | 847 | Matches expected | Missing 6 All-Star dates (expected) |
| `GetEspnScoreboard` | 1,343 | 1 per date | Complete + pre-season dates |
| `BasketballRefSeasonRoster` | 120 | 30 per season | All 4 seasons complete |

### ⚠️ Partial - Specific Gaps Found

**BigDataBall Missing Dates (6 - All-Star Weekend):**
- 2022-02-18, 2022-02-20 (All-Star 2022)
- 2023-02-17, 2023-02-19 (All-Star 2023)
- 2024-02-16, 2024-02-18 (All-Star 2024)
- 2025-02-14, 2025-02-16 (All-Star 2025)

**OddsAPI Game Lines Missing Dates (104):**
- All-Star weekends: 6 dates
- 2023 Playoffs (May-June): ~40 dates
- 2024 Playoffs (May-June): ~55+ dates
- Pattern: Historical API may not cover playoffs

**BdlStandingsScraper:**
- Has: 2024-25, 2025-26
- Missing: 2021-22, 2022-23, 2023-24

### ❌ Empty - Need Full Backfill

| Scraper | Current | Need | Priority |
|---------|---------|------|----------|
| `GetNbaComTeamBoxscore` | 1 date | 5,299 games | **CRITICAL** |
| `GetNbaComPlayerBoxscore` | 13 dates | 853 dates | Medium |
| `GetNbaComPlayByPlay` | 2 dates | 5,299 games | Medium |
| `GetEspnBoxscore` | 1 date | 5,299 games | Low |

---

## Backfill Action Plan

### Phase 1: CRITICAL (Unblocks Phase 3)
1. **`GetNbaComTeamBoxscore`** - Run for all 5,299 games
   - Required for: team_offense_game_summary, team_defense_game_summary
   - Estimated: ~5,299 API calls

### Phase 2: HIGH (Improves predictions)
2. **`GetOddsApiHistoricalGameLines`** - Fill playoff gaps if API allows
   - Missing ~100 playoff dates
   - May be API limitation

### Phase 3: MEDIUM (Nice to have)
3. **`GetNbaComPlayerBoxscore`** - 840 dates
4. **`GetNbaComPlayByPlay`** - 851 dates
5. **`BdlStandingsScraper`** - 3 seasons

### Phase 4: LOW (Backups)
6. **`GetEspnBoxscore`** - 852 dates (backup only)

---

## Next Steps

1. [x] **Verify "complete" scrapers** - Done
2. [x] **Analyze partial scrapers** - Done
3. [ ] **Run GetNbaComTeamBoxscore backfill** - PRIORITY
4. [ ] **Execute remaining backfills**
5. [ ] **Re-audit after backfill**
