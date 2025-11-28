# Known Data Gaps

**Purpose:** Track data coverage gaps discovered during backfills and normal operations.
**Status:** Living document - update as gaps are discovered or resolved
**Owner:** Data Engineering Team

---

## Active Gaps (Unresolved)

### 1. Play-In Tournament Games - 2025 Season (6 games)

**Discovered:** 2025-11-26
**Severity:** Medium (0.1% of total games)
**Status:** All sources failed

#### Games Affected

| Game ID    | Date       | Teams | Status |
|------------|------------|-------|--------|
| 0052400101 | 2025-04-15 | TBD   | Final  |
| 0052400121 | 2025-04-15 | TBD   | Final  |
| 0052400111 | 2025-04-16 | TBD   | Final  |
| 0052400131 | 2025-04-16 | TBD   | Final  |
| 0052400201 | 2025-04-18 | TBD   | Final  |
| 0052400211 | 2025-04-18 | TBD   | Final  |

#### Source Coverage Attempt Results

| Source | Result | Notes |
|--------|--------|-------|
| NBA.com API (`nbac_team_boxscore`) | ❌ Empty | API returns 200 but empty data array |
| ESPN (`espn_boxscores`) | ❌ Not available | 0 games found |
| Ball Don't Lie (`bdl_player_boxscores`) | ❌ Not available | 0 games found |
| Reconstruction (from player stats) | ❌ Not possible | No player data available |

#### Root Cause

**Hypothesis:** NBA.com API does not provide `boxscoretraditionalv2` endpoint data for these specific Play-In Tournament games. Older Play-In games (2022-2024) scraped successfully, suggesting this may be a 2024-25 season-specific issue or API change.

**Evidence:**
- Backfill script tried 5,299 games
- 5,293 succeeded (99.9%)
- All 6 failures are Play-In Tournament games
- All share game_id pattern `00524xx` (Play-In prefix)
- game_status = 3 (Final) in schedule
- Dates are April 2025 (future relative to backfill date 2025-11-26)

#### Impact Assessment

**Blocked:**
- Team boxscore data for these 6 games
- Team offense/defense analytics derived from these games
- Predictions for future games using these as historical context (minimal impact - only 6 games)

**Not Blocked:**
- Remaining 5,293 games (99.9%) processing normally
- Player boxscore data (may exist independently)
- Current season predictions (can use different historical windows)

#### Resolution Options

| Option | Effort | Pros | Cons |
|--------|--------|------|------|
| **Accept gap** | 0 min | No work, document and move on | Permanent 6-game gap |
| **Manual website scrape** | 1-2 hours | Could get data | May not exist on website either |
| **Try alternate NBA.com endpoints** | 30-60 min | May find different API | Unknown if exists |
| **Wait for API fix** | Unknown | May resolve automatically | May never resolve |
| **Implement source coverage system** | 3-4 weeks | Proper long-term solution | Large project |

#### Recommended Action

**Immediate:** Accept gap, document, continue with other backfills
**Short-term:** Mark for investigation when implementing source coverage system
**Long-term:** Source coverage audit job will detect and track these automatically

#### Related Work

- Source coverage system design: `docs/architecture/source-coverage/`
- Backfill plan: `docs/09-handoff/2025-11-25-scraper-backfill-plan.md`
- Implementation handoff: `docs/09-handoff/2025-11-26-source-coverage-implementation.md`

---

## Resolved Gaps

_None yet_

---

## Gap Statistics

| Category | Count | % of Total |
|----------|-------|------------|
| Total games in scope (2021-2025) | 5,299 | 100% |
| Successfully scraped | 5,293 | 99.9% |
| Active gaps | 6 | 0.1% |
| Resolved gaps | 0 | 0% |

---

## Update History

| Date | Updated By | Change |
|------|------------|--------|
| 2025-11-26 | Claude/System | Initial creation, documented 6 Play-In games |

---

## Related Documentation

- **Data Coverage Tracker:** `docs/09-handoff/data-coverage-tracker.md` (ongoing tracking)
- **Source Coverage Design:** `docs/architecture/source-coverage/`
- **Backfill Plans:** `docs/09-handoff/2025-11-25-scraper-backfill-plan.md`
