# Scraper Backfill Project

**Created:** 2025-11-26
**Status:** In Progress
**Priority:** Critical - Blocks Phase 3+ analytics pipeline

---

## Project Goal

Backfill historical NBA data for 4 seasons (2021-2025) across 17 scrapers to enable full analytics and predictions pipeline.

---

## Scope

### Data Coverage
- **Seasons:** 2021-22, 2022-23, 2023-24, 2024-25
- **Total games:** 5,299 games across 853 unique dates
- **Scrapers:** 17 needing backfill (see checklist.md)

### Success Criteria
- ✅ Critical scrapers: 100% coverage (team/player boxscores)
- ✅ High priority: 95%+ coverage (standings, backup sources)
- ✅ Medium priority: 90%+ coverage (play-by-play, optional data)

---

## Current Status

### Completed ✅
| Scraper | Status | Coverage | Notes |
|---------|--------|----------|-------|
| GetNbaComTeamBoxscore | ✅ Done | 5,293/5,299 (99.9%) | 6 Play-In games missing (see known-data-gaps.md) |

### Blocked/Issues 🚫
| Scraper | Status | Issue | Resolution |
|---------|--------|-------|------------|
| GetNbaComPlayerBoxscore | ❌ BLOCKED | HTTP 404 - wrong endpoint format | **FIX REQUIRED** - Script using GET with gamedate, should use POST /scrape with game_id |

### Pending ⏳
| Scraper | Priority | Estimated Time |
|---------|----------|----------------|
| BdlStandingsScraper | 🟡 High | 6 seconds |
| GetNbaComPlayByPlay | 🟢 Medium | 88 min (or faster with workers) |
| GetEspnBoxscore | 🟢 Medium | 132 min |

---

## Key Issues Discovered

### Issue #1: Player Boxscore Endpoint Mismatch
**Problem:** Player boxscore backfill script uses wrong API format
- Script calls: `GET /nbac_player_boxscore?gamedate=YYYYMMDD`
- Should call: `POST /scrape` with `{"scraper": "nbac_player_boxscore", "game_id": "...", ...}`
- Result: 100% HTTP 404 failure rate

**Root Cause:** Script was written for an old/different scraper service API

**Fix Options:**
1. Update script to match team boxscore pattern (POST /scrape with game_id)
2. Check if nbac_player_boxscore needs game_id or game_date
3. May need to iterate over games-per-date like team boxscore does

**Priority:** 🔴 CRITICAL - Blocks Phase 3 analytics

### Issue #2: No Worker Support in Player Boxscore Script
**Problem:** Player boxscore script is single-threaded
- Team boxscore used 12 workers → 6.5 hours for 5,299 games
- Player boxscore single-threaded → would take 14+ minutes for 853 dates
- But with 12 workers could be ~1-2 minutes

**Fix:** Add --workers flag like team boxscore script

**Priority:** 🟡 HIGH - Performance optimization

### Issue #3: 6 Play-In Tournament Games Missing
**Problem:** All sources (NBA.com, ESPN, BDL) return empty for 6 games
- Documented in `docs/09-handoff/known-data-gaps.md`
- Source coverage cascade applied
- Resolution: Accept gap, track for future source coverage system

**Priority:** 🟢 LOW - Only 0.1% of total games

---

## Dependencies

### Blocks These Systems
- Phase 3 Analytics (player_game_summary, team_offense/defense_summary)
- Phase 4 Features (ml_feature_store_v2)
- Phase 5 Predictions (prop predictions)

### Prerequisite For
- Source Coverage Implementation
- Production predictions pipeline
- Historical analysis features

---

## Project Structure

```
docs/08-projects/current/scraper-backfill/
├── overview.md          # This file - project summary
├── checklist.md         # Scraper-by-scraper status
├── changelog.md         # Session-by-session updates
└── issues.md            # Detailed issue tracking
```

---

## Related Documentation

- **Original Plan:** `docs/09-handoff/2025-11-25-scraper-backfill-plan.md`
- **Live Tracker:** `docs/09-handoff/data-coverage-tracker.md`
- **Known Gaps:** `docs/09-handoff/known-data-gaps.md`
- **Game Plan:** `docs/09-handoff/GAME-PLAN-2025-11-26.md`

---

## Next Steps

1. **Fix player boxscore script** - Update endpoint format to match team boxscore
2. **Add worker support** - Parallel processing for speed
3. **Test with 5 games** - Verify fix works
4. **Run full backfill** - 853 dates with workers
5. **Continue with BDL standings** - Quick win
6. **Update tracker** - Mark progress

---

**Last Updated:** 2025-11-26
**Next Review:** After player boxscore fix
