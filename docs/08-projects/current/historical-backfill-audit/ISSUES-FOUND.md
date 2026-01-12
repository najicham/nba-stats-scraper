# Issues Found During Backfill Audit

**Last Updated:** January 12, 2026 (Session 22 - Extended)
**Total Issues:** 48+
**Fixed:** 21 (44%)
**Outstanding:** 27 (56%)

---

## P0 - Critical (Fix Immediately)

### 1. Slack Webhook Invalid (404)
- **Status:** OUTSTANDING
- **Impact:** ALL alerting functions non-functional
- **Affects:** daily-health-summary, phase4-timeout-check, live-freshness-monitor, grading-delay-alert
- **Fix:** Configure valid Slack webhook URL in Secret Manager

### 2. Player Normalization Backfill Pending
- **Status:** Code FIXED, SQL NOT RUN
- **Impact:** 78% of historical predictions used default line_value=20
- **Sessions:** S13B, S15
- **Files:**
  - Code fix: `data_processors/raw/espn/espn_team_roster_processor.py`
  - SQL patch: `bin/patches/patch_player_lookup_normalization.sql`
- **Fix:** Run backfill SQL, regenerate downstream analytics

### 3. Missing BDL Box Scores (Jan 10-11) - ✅ FIXED Session 21
- **Status:** ✅ RESOLVED
- **Impact:** Was cascading to team_defense_game_summary → PSZA → PCF → predictions
- **Details:**
  - Jan 10: 0/6 → 6/6 box scores ✅
  - Jan 11: 9/10 → 10/10 box scores ✅
  - 1,153 player records backfilled
- **Fixed:** Ran `bdl_boxscores_raw_backfill.py --dates=2026-01-10,2026-01-11,2026-01-12`

### 3a. Missing BDL Box Scores (Jan 7) - ⚠️ PARTIAL FIX Session 22
- **Status:** ⚠️ PARTIALLY RESOLVED (10/12 games)
- **Impact:** Minor - gamebook has all 12 games, only BDL source incomplete
- **Details:**
  - Before: 0/12 games in BigQuery
  - After: 10/12 games, 349 player records
  - Missing: MIL @ GSW, HOU @ POR (west coast games)
- **Root Cause:** Scraper timing issue
  - Final BDL scrape runs at 3:05 AM UTC (10:05 PM ET)
  - West coast games (10 PM ET tip-off) hadn't started yet
  - GCS file has 0-0 scores and 0 player data for these games
- **Fix Applied:** Ran `bdl_boxscores_raw_backfill.py --dates=2026-01-07`
- **Remaining Gap:** 2 games unrecoverable from BDL source - data never scraped
- **Mitigation:** `nbac_gamebook_player_stats` has all 12 games ✅

### 4. PSZA Upstream Issues (214 Players) - ✅ FIXED Session 21
- **Status:** ✅ RESOLVED
- **Sessions:** S20, S21
- **Details:**
  - Jan 8: 430 players processed ✅
  - Jan 9: 434 players processed ✅
  - Jan 11: 435 players processed ✅
  - Total: 1,299 players backfilled
- **Fixed:** Ran `player_shot_zone_analysis_precompute_backfill.py --dates=2026-01-08,2026-01-09,2026-01-11`

---

## P1 - High Priority (This Week)

### 5. BDL Validator Column Name Bug - ✅ FIXED Session 21
- **Status:** ✅ RESOLVED
- **File:** `validation/validators/raw/bdl_boxscores_validator.py`
- **Issue:** Was using `team_abbreviation` but actual column is `team_abbr`
- **Lines Fixed:** 219, 224, 245, 252, 260, 310, 320, 330 (8 occurrences)
- **Fixed:** Applied `replace_all` to change `team_abbreviation` → `team_abbr`

### 5a. Team Defense Game Summary PRIMARY_KEY_FIELDS Bug - ✅ FIXED Session 21
- **Status:** ✅ RESOLVED
- **File:** `data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py`
- **Issue:** `PRIMARY_KEY_FIELDS = ['game_id', 'team_abbr']` but table uses `defending_team_abbr`
- **Impact:** MERGE operations failing with "Name team_abbr not found"
- **Fixed:** Changed to `PRIMARY_KEY_FIELDS = ['game_id', 'defending_team_abbr']`

### 6. ESPN Roster Scraper Unreliable
- **Status:** RECURRING
- **Sessions:** S7, S10, S12, S16
- **Symptom:** Only scrapes 2-3 teams instead of 30 on some days
- **Impact:** Blocks entire prediction pipeline
- **Root Cause:** ESPN API rate limiting or scraper bug
- **Fix Needed:** Add exponential backoff, retry logic, completeness validation

### 7. Registry System - RESOLVED Session 20
- **Status:** ✅ RESOLVED (backlog cleared)
- **Sessions:** S10, S17, S20
- **Details:**
  - Was: 2,099 unresolved names pending
  - Now: 0 pending, 2,830 resolved, 2 snoozed
  - Session 17: Fixed IAM permissions
  - Session 20: Confirmed backlog fully cleared
- **Remaining:** Consider adding monitoring for pending queue size

### 5. Upcoming Context Missing Fallbacks
- **Status:** OUTSTANDING
- **Sessions:** S10, S16
- **Impact:** 42% coverage when primary sources fail (should be 95%)
- **Current:** Only uses `nbac_schedule` + `espn_team_rosters`
- **Fix Needed:** Add fallback chain:
  - Schedule: `nbac_schedule` → `nba_reference.nba_schedule`
  - Roster: `espn_rosters` → `nba_players_registry` → `nbac_player_list`

### 6. PlayerGameSummary No Retry
- **Status:** OUTSTANDING
- **Sessions:** S10, S13C
- **Issue:** Failed once, no automatic retry mechanism
- **Fix Needed:** Add self-healing retry logic

### 7. 2021-22 Season Missing Odds Data
- **Status:** ACCEPTED GAP (unrecoverable)
- **Impact:** Only 29% prediction coverage for that season
- **Root Cause:** Historical Odds API data never scraped, cannot be retrieved
- **Decision:** Accept gap or find alternative data source

---

## P2 - Medium Priority (This Sprint)

### 8. Live Export Staleness Alert Missing
- **Status:** OUTSTANDING
- **Sessions:** S13C
- **Issue:** No alert if `today.json` is >4 hours old during game hours
- **Fix Needed:** Cloud Function to check GCS file modification time

### 9. NBA.com Player List Stale
- **Status:** OUTSTANDING
- **Sessions:** S10
- **Details:** `nbac_player_list_current` last updated October 1, 2025
- **Fix Needed:** Add Cloud Scheduler job or deprecate

### 10. DLQ Monitoring Limited
- **Status:** BASIC
- **Sessions:** S14
- **Issue:** Dead-letter queues exist but monitoring insufficient
- **Fix Needed:** Add sample message content to alerts, automatic retry suggestions

### 11. Circuit Breaker Lockout Too Long
- **Status:** OUTSTANDING
- **Sessions:** S10
- **Current:** 7-day lockout after failures
- **Recommendation:** Reduce to 24 hours

### 12. Registry Automation Monitoring Missing
- **Status:** OUTSTANDING
- **Sessions:** S17, S19
- **Issue:** No daily monitoring of pending name count
- **Fix Needed:** Add metric/alert for pending queue size

---

## P3 - Low Priority (Backlog)

### 13. Play-In Tournament Games Missing
- **Status:** ACCEPTED GAP
- **Details:** 6 games (0.1% of total), all sources failed
- **Decision:** Documented, accepted

### 14. Coordinator Endpoints Missing Auth
- **Status:** OUTSTANDING
- **Sessions:** S14
- **Issue:** `/start` and `/complete` endpoints were unauthenticated
- **Note:** May have been fixed in later sessions

### 15. Cleanup Processor Non-Functional
- **Status:** FIXED (earlier session)
- **Issue:** Was logging instead of publishing recovery messages

---

## Fixed Issues (Reference)

| # | Issue | Fixed In | Notes |
|---|-------|----------|-------|
| 1 | Player Name Normalization (code) | S13B | SQL backfill still pending |
| 2 | Phase 4→5 Timeout Alerting | S17, S18 | Cloud functions deployed |
| 3 | Sportsbook Fallback Query Bug | S19 | Wrong table name fixed |
| 4 | Schedule Scraper Non-Functional | S10 | Bulk backfill applied |
| 5 | Pub/Sub Topic Mismatch | S14 | prediction-ready-prod |
| 6 | CatBoost Model Path Missing | S14 | Env var added |
| 7 | Grading NO_LINE Bug | S10 | Exclusion list fixed |
| 8 | Grading Missing Authentication | S10 | Bearer token added |
| 9 | Injury Data Integration | S7 | Extraction implemented |
| 10 | Prop Data Gap Oct 22 - Nov 13 | S11 | Loaded to BigQuery |
| 11 | Same-Day Cache TTL | S13 | 5 min TTL added |
| 12 | Coverage Alias Resolution | S7 | - |
| 13 | DNP/Voided Bet Treatment | S7 | - |
| 14 | Cleanup Processor | Earlier | Now publishes correctly |

---

## Recurring Patterns

### Pattern 1: ESPN Roster Scraper Issues
- **Frequency:** Multiple times per week
- **Sessions:** S7, S10, S12, S16
- **Root Cause:** Unknown (rate limiting suspected)
- **Mitigation Needed:** Robust retry + fallback

### Pattern 2: Missing Fallbacks
- **Frequency:** Whenever primary source fails
- **Impact:** Pipeline-wide failures
- **Examples:** Schedule, roster, prop lines
- **Mitigation Needed:** Multi-source fallback chains

### Pattern 3: Configuration Drift
- **Frequency:** Each deployment
- **Examples:** Pub/Sub topics, model paths, webhook URLs
- **Mitigation Needed:** Configuration validation in CI/CD

### Pattern 4: BDL Scraper West Coast Game Gap
- **Frequency:** Any day with late west coast games (10 PM ET tip-off)
- **Root Cause:** Final BDL scrape runs at 3:05 AM UTC (10:05 PM ET), before west coast games finish
- **Examples:** Jan 7 (MIL@GSW, HOU@POR), potentially others
- **Impact:** Minor - gamebook has complete data, only BDL source affected
- **Mitigation Options:**
  1. Add later scrape run (6:05 AM UTC / 1:05 AM ET)
  2. Accept gap since gamebook is complete
  3. Implement "next-day" backfill job for west coast games

---

## Issue Discovery Timeline

| Date | Session | Key Issues Found |
|------|---------|------------------|
| Jan 10 | S7-S8 | ESPN roster, schedule scraper, injury data |
| Jan 11 | S10-S11 | Registry stale, grading bugs, prop data gap |
| Jan 12 | S13-S14 | Name normalization (78% default lines), Pub/Sub mismatch |
| Jan 12 | S15-S16 | True performance analysis, sportsbook fallback code |
| Jan 12 | S17-S19 | Registry IAM, timeout alerting, sportsbook query bug |
| Jan 12 | S20 | BDL box scores missing (Jan 10-11), PSZA upstream errors, BDL validator bug, registry cleared |
| Jan 12 | S21 | Fixed BDL validator, team defense PRIMARY_KEY_FIELDS, backfilled Jan 10-11 |
| Jan 12 | S22 | Jan 7 BDL gap investigation, scraper timing pattern identified, backfilled 10/12 games |

---

## Session 20 New Findings Summary

**Issues Added:**
- P0: Missing BDL Box Scores (Jan 10: 6 games, Jan 11: 1 game)
- P0: PSZA Upstream Issues (214 players across 3 dates)
- P1: BDL Validator Column Name Bug

**Issues Resolved:**
- Registry backlog cleared (was 2,099 pending, now 0)

**Deferred Features Documented (NOT bugs):**
- `opponent_strength_score` = 0 by design
- `pace_score` = 0 by design
- `usage_spike_score` = 0 by design

---

## Session 21 Fixes Summary

**Bugs Fixed:**
1. BDL Validator Column Name Bug - `team_abbreviation` → `team_abbr` (8 occurrences)
2. Team Defense Game Summary PRIMARY_KEY_FIELDS Bug - `team_abbr` → `defending_team_abbr`

**Data Backfills Completed:**
1. BDL Box Scores: Jan 10-11 (1,153 records)
2. Team Defense Game Summary: Jan 4, 8-11 (74 records)
3. Player Shot Zone Analysis: Jan 8, 9, 11 (1,299 players)

**Current Coverage (Post-Fix):**
- Jan 10: 6/6 games, 434 players ✅
- Jan 11: 10/10 games, 435 players ✅

---

## Session 22 Fixes Summary

### Part 1: Jan 7 BDL Gap Investigation

**Investigation Completed:**
- Jan 7 BDL gap root cause identified: Scraper timing issue (not processor failure)
- GCS files existed but final scrape ran before west coast games finished
- Confirmed `nbac_gamebook_player_stats` has all 12 games

**Data Backfill Completed:**
- BDL Box Scores: Jan 7 (349 records, 10 games)
- Team Defense Game Summary: Jan 7 (24 records)
- PSZA: Jan 7 (429 players)
- Remaining 2 BDL games (MIL@GSW, HOU@POR) unrecoverable - never scraped

**New Pattern Documented:**
- Pattern 4: BDL Scraper West Coast Game Gap

### Part 2: Priority-Based Recovery

**Priority Analysis (Ultrathink):**
- P1: Jan 8 MIA@CHI - most recent gap
- P2: Jan 1 gamebook - historical completeness for ML training

**Jan 8 Recovery Attempt:**
- Ran gamebook backfill - 3/3 games recovered (IND@CHA, CLE@MIN, DAL@UTA)
- **MIA@CHI: 404 from NBA.com** - PDF never published, permanent gap
- Re-ran TDGS: 6 records

**Jan 1 Recovery - FULL SUCCESS:**
- Ran gamebook backfill - **5/5 games recovered!** (HOU@BKN, MIA@DET, PHI@DAL, BOS@SAC, UTA@LAC)
- Re-ran TDGS: 8 records → now 5/5 games (was 3/5)

### Final Data Coverage (Post Session 22)

| Date | Scheduled | Gamebook | TDGS | Status |
|------|-----------|----------|------|--------|
| Jan 1 | 5 | **5** | **5** | ✅ FIXED |
| Jan 2 | 10 | 10 | 10 | ✅ |
| Jan 3 | 8 | 8 | 8 | ✅ |
| Jan 4 | 8 | 8 | 8 | ✅ |
| Jan 5 | 8 | 8 | 8 | ✅ |
| Jan 6 | 6 | 6 | 6 | ✅ |
| Jan 7 | 12 | 12 | 12 | ✅ FIXED |
| Jan 8 | 4 | 3 | 3 | ⚠️ MIA@CHI 404 |
| Jan 9 | 10 | 10 | 10 | ✅ |
| Jan 10 | 6 | 6 | 6 | ✅ |
| Jan 11 | 10 | 10 | 10 | ✅ |

**Permanent Gaps (Unrecoverable):**
1. **Jan 8 MIA@CHI** - NBA.com PDF returns 404 (never published)
2. **BDL west coast games** - Data never scraped due to timing

**BDL Coverage (for reference - not critical since gamebook is complete):**
- Jan 1-3, 5-8: 60-83% (west coast gaps)
- Jan 4, 9-11: 100% ✅

---

*Last Updated: January 12, 2026 (Session 22 - Extended)*
