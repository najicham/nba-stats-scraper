# Scraper → Processor Mapping

**File:** `docs/reference/scraper-to-processor-mapping.md`
**Created:** 2025-11-21 10:00 AM PST
**Last Updated:** 2025-11-21 10:00 AM PST
**Purpose:** Map scrapers to Phase 2 processors to identify active/inactive processors
**Status:** Current

---

## Overview

This document maps each scraper (Phase 1) to its corresponding Phase 2 raw processor. Used to identify which processors are active and should receive smart idempotency implementation.

**Source:** Scrapers from `docs/scrapers/parameter-formats-reference.md` (2025-11-13)

---

## Mapping Table

| Scraper | Phase 2 Processor | Table | Status | Hash Priority |
|---------|-------------------|-------|--------|---------------|
| **NBA.com Scrapers** |||||
| GetNbaComScheduleApi | nbac_schedule_processor.py | nba_raw.nbac_schedule | ✅ Active | 🟢 Low |
| GetNbaComScoreboardV2 | nbac_scoreboard_v2_processor.py | nba_raw.nbac_scoreboard_v2 | ⚠️ **INACTIVE?** | ⏸️ Skip |
| GetNbaComPlayByPlay | nbac_play_by_play_processor.py | nba_raw.nbac_play_by_play | ✅ Active | 🟡 Medium |
| GetNbaComPlayerBoxscore | nbac_player_boxscore_processor.py | nba_raw.nbac_player_boxscores | ✅ Active | 🟡 Medium |
| GetNbaComInjuryReport | nbac_injury_report_processor.py | nba_raw.nbac_injury_report | ✅ Active | 🔴 **CRITICAL** |
| GetNbaComPlayerList | nbac_player_list_processor.py | nba_raw.nbac_player_list_current | ✅ Active | 🟢 Low |
| GetNbaComPlayerMovement | nbac_player_movement_processor.py | nba_raw.nbac_player_movement | ✅ Active | 🟢 Low |
| GetNbaComTeamBoxscore | nbac_team_boxscore_processor.py | nba_raw.nbac_team_boxscore | ✅ Active | 🟡 Medium |
| GetNbaComRefereeAssignments | nbac_referee_processor.py | nba_raw.nbac_referee_game_assignments | ✅ Active | 🟢 Low |
| GetNbaComScheduleCdn | (Backup - no separate processor) | nba_raw.nbac_schedule | ✅ Active | N/A |
| GetNbaComGamebookPdf | nbac_gamebook_processor.py | nba_raw.nbac_gamebook_player_stats | ✅ Active | 🟡 Medium |
| GetNbaComTeamRoster | (No processor found) | - | ❓ Unknown | N/A |
| **Odds API Scrapers** |||||
| GetOddsApiEvents | (No processor - scraper only) | - | ✅ Active | N/A |
| GetOddsApiCurrentEventOdds | odds_api_props_processor.py | nba_raw.odds_api_player_points_props | ✅ Active | 🔴 **CRITICAL** |
| GetOddsApiCurrentGameLines | odds_game_lines_processor.py | nba_raw.odds_api_game_lines | ✅ Active | 🔴 **CRITICAL** |
| GetOddsApiHistorical* | (Same processors, historical mode) | Same tables | ✅ Active | 🔴 **CRITICAL** |
| **BettingPros Scrapers** |||||
| BettingProsEvents | (No processor - events only) | - | ✅ Active | N/A |
| BettingProsPlayerProps | bettingpros_player_props_processor.py | nba_raw.bettingpros_player_points_props | ✅ Active | 🔴 **CRITICAL** |
| **Ball Don't Lie Scrapers** |||||
| BdlGamesScraper | (No processor - schedule data) | - | ✅ Active | N/A |
| BdlBoxScoresScraper | bdl_boxscores_processor.py | nba_raw.bdl_player_boxscores | ✅ Active | 🟡 Medium |
| BdlActivePlayersScraper | bdl_active_players_processor.py | nba_raw.bdl_active_players_current | ✅ Active | 🟢 Low |
| BdlStandingsScraper | bdl_standings_processor.py | nba_raw.bdl_standings | ✅ Active | 🟢 Low |
| BdlInjuriesScraper | bdl_injuries_processor.py | nba_raw.bdl_injuries | ✅ Active | 🔴 **CRITICAL** |
| **ESPN Scrapers** |||||
| GetEspnScoreboard | espn_scoreboard_processor.py | nba_raw.espn_scoreboard | ✅ Active | 🟡 Medium |
| GetEspnBoxscore | espn_boxscore_processor.py | nba_raw.espn_boxscores | ✅ Active | 🟡 Medium |
| GetEspnTeamRoster | espn_team_roster_processor.py | nba_raw.espn_team_rosters | ✅ Active | 🟢 Low |
| **BigDataBall Scrapers** |||||
| BigDataBallPbpScraper | bigdataball_pbp_processor.py | nba_raw.bigdataball_play_by_play | ✅ Active | 🟢 Low |
| **Basketball Reference** |||||
| BasketballRefSeasonRoster | br_roster_processor.py | nba_raw.br_rosters_current | ✅ Active | 🟢 Low |

---

## Summary by Priority

### 🔴 Critical Priority (5 processors)
**Implement hash checking FIRST - High update frequency**

1. ✅ **nbac_injury_report_processor.py** - Updates 4-6x daily
2. ✅ **bdl_injuries_processor.py** - Updates 4-6x daily
3. ✅ **odds_api_props_processor.py** - Updates hourly
4. ✅ **bettingpros_player_props_processor.py** - Updates multiple times daily
5. ✅ **odds_game_lines_processor.py** - Updates hourly

### 🟡 Medium Priority (7 processors)
**Implement hash checking SECOND - Moderate update frequency**

1. **nbac_play_by_play_processor.py** - Per-game updates
2. **nbac_player_boxscore_processor.py** - Post-game updates
3. **nbac_team_boxscore_processor.py** - Post-game updates
4. **nbac_gamebook_processor.py** - Post-game updates
5. **bdl_boxscores_processor.py** - Post-game updates
6. **espn_scoreboard_processor.py** - Throughout game day
7. **espn_boxscore_processor.py** - Post-game updates

### 🟢 Low Priority (8 processors)
**Implement hash checking LAST - Infrequent updates or low impact**

1. **nbac_schedule_processor.py** - Weekly/seasonal updates
2. **nbac_player_list_processor.py** - Seasonal updates
3. **nbac_player_movement_processor.py** - Rare transaction updates
4. **nbac_referee_processor.py** - Daily, low downstream impact
5. **bdl_active_players_processor.py** - Daily, low impact
6. **bdl_standings_processor.py** - Daily, low impact
7. **espn_team_roster_processor.py** - Weekly updates
8. **bigdataball_pbp_processor.py** - Per-game, low usage
9. **br_roster_processor.py** - Seasonal updates

### ⏸️ Skip (1 processor)
**Inactive or deprecated**

1. ⚠️ **nbac_scoreboard_v2_processor.py** - User indicated inactive

---

## Action Items

### Immediate
- [ ] **Confirm nbac_scoreboard_v2_processor status** - Is it actually inactive?
- [ ] **Verify GetNbaComTeamRoster processor** - Does it exist? Where?

### Phase 1 Implementation
Focus on 5 critical processors only:
- [ ] nbac_injury_report_processor.py
- [ ] bdl_injuries_processor.py
- [ ] odds_api_props_processor.py
- [ ] bettingpros_player_props_processor.py
- [ ] odds_game_lines_processor.py

### Phase 2 Implementation
Add 7 medium-priority processors after Phase 1 validated

### Phase 3 Implementation
Add 8 low-priority processors after Phase 2 validated

---

## Notes

**Scrapers without processors:**
- GetOddsApiEvents - Events data used by props/lines processors
- BettingProsEvents - Events data used by props processor
- BdlGamesScraper - Schedule data, not processed to raw table
- GetNbaComScheduleCdn - Backup scraper, uses same processor as API version

**Missing processors to investigate:**
- GetNbaComTeamRoster → ??? (no processor found in initial scan)

---

**Last Updated:** 2025-11-21 10:00 AM PST
**Next Review:** After confirming scoreboard_v2 and team_roster status
