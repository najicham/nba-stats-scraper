# Scraper Backfill Checklist

**Updated:** 2025-11-26

---

## Critical Priority (Blocks Phase 3+)

- [x] **GetNbaComTeamBoxscore** - 5,293/5,299 (99.9%) ✅
  - Workers: 12
  - Duration: 6.5 hours
  - Gaps: 6 Play-In games (documented)

- [ ] **GetNbaComPlayerBoxscore** - 0/853 dates ❌ BLOCKED
  - Issue: Script uses wrong endpoint format
  - Fix required: Update to POST /scrape with game_id
  - Add workers support for parallelization
  - Estimated: 1-2 min with 12 workers (after fix)

---

## High Priority (Enables Fallbacks)

- [ ] **BdlStandingsScraper** - 2/4 seasons
  - Need: 2021, 2022, 2023
  - Estimated: 6 seconds (3 API calls)
  - No issues known
  - **Ready to run**

- [ ] **GetEspnBoxscore** - 1/5,299 games
  - Backup source for team boxscores
  - Estimated: 132 min single-threaded
  - With 12 workers: ~11 min
  - Defer until critical scrapers done

---

## Medium Priority (Nice to Have)

- [ ] **GetNbaComPlayByPlay** - 2/5,299 games
  - Enables shot charts, advanced features
  - Estimated: 88 min single-threaded
  - With 12 workers: ~7 min
  - Defer until critical scrapers done

- [ ] **GetOddsApiHistoricalGameLines** - 749/853 dates
  - Missing ~104 playoff dates
  - May be API limitation
  - Needs investigation
  - Defer for now

---

## Complete ✅

- [x] **BdlBoxScoresScraper** - 893 dates
- [x] **GetNbaComGamebooks** - 888 dates
- [x] **GetNbaComInjuryReport** - 922 dates
- [x] **GetEspnScoreboard** - 1,343 dates
- [x] **GetBettingProEvents** - 878 dates
- [x] **GetBettingProPlayerProps** - 865 dates
- [x] **GetOddsApiHistoricalEvents** - 848 dates
- [x] **GetOddsApiHistoricalEventOdds** - 447 dates (May 2023+)
- [x] **BasketballRefSeasonRoster** - 120 files

---

## Progress Summary

| Category | Scrapers | Status |
|----------|----------|--------|
| Complete | 9 | ✅ |
| In Progress | 1 | 🔄 (team boxscore done) |
| Blocked | 1 | ❌ (player boxscore needs fix) |
| Ready to Run | 1 | ⏳ (BDL standings) |
| Deferred | 3 | 📅 (ESPN, play-by-play, odds) |

**Overall:** 10/17 complete or in progress (59%)

---

## Next Actions

1. [ ] Fix player boxscore script endpoint format
2. [ ] Add workers support to player boxscore
3. [ ] Test player boxscore with 5 games
4. [ ] Run full player boxscore backfill
5. [ ] Run BDL standings backfill (6 sec)
6. [ ] Evaluate need for ESPN/play-by-play backfills

---

**Blocking Issue:** Player boxscore script must be fixed before proceeding
