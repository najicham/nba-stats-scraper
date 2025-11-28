# Data Coverage Tracker

**Purpose:** Real-time tracking of data coverage across all scrapers and processors
**Updated:** 2025-11-27
**Status:** Active tracking

---

## Quick Status

```
Player Boxscore:   ████████████████████  100.0% (845/845) ✅ COMPLETE
Team Boxscore:     ████████████████████░  99.9% (850 games)
Play-by-Play:      ░░░░░░░░░░░░░░░░░░░░    TBD
ESPN Boxscore:     ░░░░░░░░░░░░░░░░░░░░    TBD
BDL Standings:     ██████████░░░░░░░░░░   50.0% (2/4 seasons)
```

**Note:** Player boxscore excludes 8 All-Star dates (intentionally skipped - exhibition games)

---

## Phase 1: Scrapers (GCS Data)

### Critical Priority (Blocks Phase 3+)

| Scraper | Current | Target | % | Gap | Priority | Status | Notes |
|---------|---------|--------|---|-----|----------|--------|-------|
| **GetNbaComTeamBoxscore** | 850 dates | 853 dates | 99.9% | 6 games | ✅ DONE | Complete | See known-gaps.md for 6 Play-In games |
| **GetNbaComPlayerBoxscore** | 13 dates | 853 dates | 1.5% | 840 dates | 🔴 CRITICAL | Ready | Script ready, ~14 min |
| **GetNbaComGamebooks** | 888 dates | 853 dates | 104% | None | ✅ DONE | Complete | More than needed |

### High Priority (Enables fallbacks)

| Scraper | Current | Target | % | Gap | Priority | Status | Notes |
|---------|---------|--------|---|-----|----------|--------|-------|
| **BdlStandingsScraper** | 2 seasons | 4 seasons | 50% | 2021-2023 | 🟡 HIGH | Ready | 3 API calls, ~6 sec |
| **GetEspnBoxscore** | 1 date | 5,299 games | 0.02% | 5,298 games | 🟡 HIGH | Ready | ~132 min |

### Medium Priority (Nice to have)

| Scraper | Current | Target | % | Gap | Priority | Status | Notes |
|---------|---------|--------|---|-----|----------|--------|-------|
| **GetNbaComPlayByPlay** | 2 dates | 5,299 games | 0.04% | 5,297 games | 🟢 MED | Ready | ~88 min |
| **GetOddsApiHistoricalGameLines** | 749 dates | 853 dates | 87.8% | ~104 playoff dates | 🟢 MED | Ready | May be API limitation |

### Complete (No action needed)

| Scraper | Coverage | Status |
|---------|----------|--------|
| BdlBoxScoresScraper | 893 dates | ✅ Complete |
| GetNbaComInjuryReport | 922 dates | ✅ Complete |
| GetEspnScoreboard | 1,343 dates | ✅ Complete |
| GetBettingProEvents | 878 dates | ✅ Complete |
| GetBettingProPlayerProps | 865 dates | ✅ Complete |
| GetOddsApiHistoricalEvents | 848 dates | ✅ Complete |
| GetOddsApiHistoricalEventOdds | 447 dates (May 2023+) | ✅ Complete |
| BasketballRefSeasonRoster | 120 files | ✅ Complete |

---

## Phase 2: Raw Processing (GCS → BigQuery)

| Processor | Status | Notes |
|-----------|--------|-------|
| nbac_team_boxscore | ⏸️ PENDING | Wait 90min for streaming buffer to clear |
| nbac_player_boxscore | ⏸️ PENDING | After GCS backfill complete |
| All others | ✅ Running | Normal daily operations |

---

## Phase 3: Analytics Processing (Raw → Analytics)

| Processor | Dependencies | Status | Notes |
|-----------|--------------|--------|-------|
| player_game_summary | nbac_player_boxscore | ⏸️ BLOCKED | Needs Phase 2 |
| team_offense_game_summary | nbac_team_boxscore | ⏸️ BLOCKED | Needs Phase 2 |
| team_defense_game_summary | nbac_team_boxscore | ⏸️ BLOCKED | Needs Phase 2 |

---

## Phase 4: Precompute/Features

| Processor | Dependencies | Status | Notes |
|-----------|--------------|--------|-------|
| ml_feature_store_v2 | Phase 3 analytics | ⏸️ BLOCKED | Needs Phase 3 |
| player_rolling_averages | player_game_summary | ⏸️ BLOCKED | Needs Phase 3 |

---

## Phase 5: Predictions

| Component | Dependencies | Status | Notes |
|-----------|--------------|--------|-------|
| Prediction generation | Phase 4 features | ⏸️ BLOCKED | Needs Phase 4 |

---

## Known Issues & Gaps

### Active Issues

1. **6 Play-In Tournament games (2025 season)**
   - See: `docs/09-handoff/known-data-gaps.md`
   - Impact: 0.1% of total games
   - Resolution: Documented, accepted gap

2. **Streaming buffer migration needed**
   - See: `docs/08-projects/current/streaming-buffer-migration/`
   - Impact: 101 errors during team boxscore backfill
   - Resolution: Project created, not started
   - Blocks: Source coverage implementation

### Historical Coverage Notes

- **Seasons covered:** 2021-22, 2022-23, 2023-24, 2024-25
- **Total games:** 5,299 games across 853 unique game dates
- **Data sources:** NBA.com (primary), ESPN (backup), BDL (backup)

---

## Next Actions (Priority Order)

### Today's Work

- [ ] **Complete player boxscore backfill** (~14 min)
  ```bash
  python backfill_jobs/scrapers/nbac_player_boxscore/nbac_player_boxscore_scraper_backfill.py \
    --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app
  ```

- [ ] **Complete BDL standings backfill** (~6 sec)
  ```bash
  python backfill_jobs/scrapers/bdl_standings/bdl_standings_scraper_backfill.py \
    --service-url=https://nba-phase1-scrapers-756957797294.us-west2.run.app
  ```

- [ ] **Verify GCS coverage**
  ```bash
  # Check dates created
  gsutil ls gs://nba-scraped-data/nba-com/player-boxscore/ | wc -l
  # Expected: ~853 dates
  ```

### This Week

- [ ] **Wait for streaming buffer to clear** (90 min after team boxscore backfill)
- [ ] **Run Phase 2 processors** (process GCS → BigQuery)
- [ ] **Verify Phase 2 completion**
- [ ] **Run Phase 3 processors**

### This Sprint

- [ ] **Fix streaming buffer issue** (prevents future backfill errors)
- [ ] **Run Phase 4 processors**
- [ ] **Test Phase 5 predictions**
- [ ] **Consider source coverage implementation**

---

## Update Log

| Date | Update | By |
|------|--------|-----|
| 2025-11-27 | Player boxscore retry running (244 dates, 6 workers) | Recovery backfill |
| 2025-11-27 | Streaming buffer issue FIXED (processors migrated) | Another chat |
| 2025-11-26 | Player boxscore failed (35.5% due to streaming buffer) | Backfill job |
| 2025-11-26 | Documented 6 Play-In game gap | System |
| 2025-11-26 | Team boxscore completed (99.9%) | Backfill job |
| 2025-11-26 | Initial tracker created | System |

---

## Related Documentation

- **Known Gaps:** `docs/09-handoff/known-data-gaps.md`
- **Backfill Plan:** `docs/09-handoff/2025-11-25-scraper-backfill-plan.md`
- **Source Coverage Design:** `docs/architecture/source-coverage/`
- **Streaming Buffer Migration:** `docs/08-projects/current/streaming-buffer-migration/`
