# Phase 1 Scraper Inventory

**Last Updated:** 2026-03-07 (Session 430 — BDL retired, projections status updated)

Complete catalog of all 40+ production scrapers organized by data type and source.

---

## Injury Data Sources

### nbac_injury_report (NBA.com) ⭐ OFFICIAL
- **Source:** NBA.com official injury report PDFs
- **URL:** `https://ak-static.cms.nba.com/referee/injury/`
- **Coverage:** Published multiple times daily (15-min intervals)
- **Accuracy:** 99-100% with confidence scoring
- **BigQuery Table:** `nba_raw.nbac_injury_report`
- **File:** `scrapers/nbacom/nbac_injury_report.py`
- **Status:** ✅ Production (v16 - 2025-10-15)
- **Use Case:** PRIMARY source for injury data
- **Note:** Requires PDF parsing with pdfplumber

### ~~bdl_injuries (Ball Don't Lie)~~ — RETIRED
- **Status:** ❌ RETIRED (Session 430, 2026-03-07)
- **Reason:** BDL subscription cancelled. Data unreliable (222 rows from single date).
- **Replacement:** None needed — NBA.com `nbac_injury_report` is sole source.

---

## Schedule Data Sources

### nbac_schedule (NBA.com) ⭐ PRIMARY
- **Source:** NBA.com schedule API
- **BigQuery Table:** `nba_raw.nbac_schedule`
- **Coverage:** 100% (official source)
- **File:** `scrapers/nbacom/nbac_schedule.py`

### nbac_schedule_cdn (NBA.com CDN)
- **Source:** NBA.com CDN endpoint
- **Use Case:** Faster alternative to main API
- **File:** `scrapers/nbacom/nbac_schedule_cdn.py`

---

## Player Stats Sources

### nbac_gamebook_player_stats (NBA.com) ⭐ PRIMARY
- **Source:** NBA.com gamebook PDFs
- **BigQuery Table:** `nba_raw.nbac_gamebook_player_stats`
- **Coverage:** Official play-by-play stats
- **File:** `scrapers/nbacom/nbac_gamebook_pdf.py`

### ~~bdl_player_box_scores (Ball Don't Lie)~~ — RETIRED
- **Status:** ❌ RETIRED (Session 151, confirmed Session 430)
- **Reason:** BDL subscription cancelled. NBA.com gamebook is sole source.

---

## Betting Lines Sources

### odds_api_* (The Odds API) ⭐ PRIMARY
- **Source:** TheOddsAPI.com
- **Tables:**
  - `nba_raw.odds_api_game_lines` - Game lines (spread, total, moneyline)
  - `nba_raw.odds_api_player_props` - Player prop lines
- **Coverage:** 10+ sportsbooks
- **Files:** `scrapers/theoddsapi/`
- **Note:** Requires API key

### bettingpros_* (BettingPros)
- **Source:** BettingPros.com
- **Tables:**
  - `nba_raw.bettingpros_player_points_props`
  - `nba_raw.bettingpros_player_rebounds_props`
  - `nba_raw.bettingpros_player_assists_props`
- **Coverage:** Consensus lines across books
- **Files:** `scrapers/bettingpros/`

---

## Play-by-Play Data

### nbac_play_by_play (NBA.com) ⭐ PRIMARY
- **Source:** NBA.com play-by-play API
- **BigQuery Table:** `nba_raw.nbac_play_by_play`
- **Coverage:** Every possession, every game
- **File:** `scrapers/nbacom/nbac_play_by_play.py`

---

## Team Stats Sources

### nbac_team_boxscore (NBA.com) ⭐ PRIMARY
- **Source:** NBA.com boxscore API
- **BigQuery Table:** `nba_raw.nbac_team_boxscore`
- **File:** `scrapers/nbacom/nbac_team_boxscore.py`

---

## Other Data Sources

### Referee Assignments
- **nbac_referee_assignments** (NBA.com)
- **Table:** `nba_raw.nbac_referee_assignments`

### Player Movement
- **nbac_player_movement** (NBA.com)
- **Table:** `nba_raw.nbac_player_movement`
- **Coverage:** Trades, signings, waivers

### Rosters
- **nbac_roster** (NBA.com)
- **Table:** `nba_raw.nbac_roster`

### Player Lists
- **nbac_player_list** (NBA.com)
- **Table:** `nba_raw.nbac_player_list`

---

## Projection Data Sources (Session 401)

### numberfire_projections (NumberFire/FanDuel) — WORKING
- **Source:** FanDuel Research GraphQL API (formerly NumberFire)
- **URL:** `fdresearch-api.fanduel.com/graphql`
- **BigQuery Table:** `nba_raw.numberfire_projections`
- **File:** `scrapers/projections/numberfire_projections.py`
- **Schedule:** Daily 10:15 AM ET (`nba-numberfire-projections`)
- **Status:** ✅ Production — 120 valid pts/day. ONLY working projection source.
- **Use Case:** Player point projections for consensus signal
- **SPOF Warning:** Single point of failure — no backup projection source

### fantasypros_projections (FantasyPros) — DEAD
- **Status:** ❌ DEAD — Playwright timeout, scraping DFS season totals not daily
- **Use Case:** Was consensus projected points. Not producing usable data.

### dailyfantasyfuel_projections (DailyFantasyFuel) — DEAD
- **Status:** ❌ DEAD — Returns DFS fantasy points only, not scoring projections

### dimers_projections (Dimers) — DEAD
- **Status:** ❌ DEAD — Page shows generic projections, NOT game-date-specific

---

## External Analytics Sources (Session 401)

### teamrankings_pace (TeamRankings) — WORKING
- **Source:** TeamRankings.com team pace ratings
- **URL:** `https://www.teamrankings.com/nba/stat/possessions-per-game`
- **BigQuery Table:** `nba_raw.teamrankings_pace`
- **File:** `scrapers/external/teamrankings_pace.py`
- **Schedule:** Daily 10:35 AM ET (`nba-teamrankings-pace`)
- **Status:** ✅ Production (30 records)
- **Use Case:** Team pace data for `predicted_pace_over` signal

### hashtagbasketball_dvp (Hashtag Basketball) — WORKING
- **Source:** HashtagBasketball.com Defense vs Position
- **URL:** `https://hashtagbasketball.com/nba-defense-vs-position`
- **BigQuery Table:** `nba_raw.hashtagbasketball_dvp`
- **File:** `scrapers/external/hashtagbasketball_dvp.py`
- **Schedule:** Daily 10:40 AM ET (`nba-hashtagbasketball-dvp`)
- **Status:** ✅ Production (34 records)
- **Use Case:** DvP rankings for `dvp_favorable_over` signal

### rotowire_lineups (RotoWire) — WORKING
- **Source:** RotoWire.com expected lineups and minutes
- **URL:** `https://www.rotowire.com/basketball/nba-lineups.php`
- **BigQuery Table:** `nba_raw.rotowire_lineups`
- **File:** `scrapers/external/rotowire_lineups.py`
- **Schedule:** Daily 10:45 AM ET (`nba-rotowire-lineups`)
- **Status:** ✅ Production (480 records)
- **Use Case:** Projected minutes and lineup status confirmation

### covers_referee_stats (Covers) — WORKING
- **Source:** Covers.com referee statistics
- **URL:** `https://www.covers.com/sport/basketball/nba/referee-stats`
- **BigQuery Table:** `nba_raw.covers_referee_stats`
- **File:** `scrapers/external/covers_referee_stats.py`
- **Schedule:** Daily 10:50 AM ET (`nba-covers-referee-stats`)
- **Status:** ✅ Production (76 records)
- **Use Case:** Referee O/U tendencies for game-level context

### nba_tracking_stats (NBA.com) — FAILING
- **Source:** NBA.com player tracking stats (via nba_api or direct HTTP)
- **Endpoint:** `stats.nba.com/stats/leaguedashplayerstats?MeasureType=Usage`
- **BigQuery Table:** `nba_raw.nba_tracking_stats`
- **File:** `scrapers/external/nba_tracking_stats.py`
- **Schedule:** Daily 10:55 AM ET (`nba-tracking-stats`)
- **Status:** ❌ FAILING — `nba_api` not in requirements, HTTP fallback times out (cloud IP blocked)
- **Use Case:** Touch-based usage data (drives, catch-and-shoot, paint touches)

### vsin_betting_splits (VSiN) — WORKING
- **Source:** VSiN.com public betting splits (DraftKings-sourced)
- **URL:** `https://data.vsin.com/nba/betting-splits/`
- **BigQuery Table:** `nba_raw.vsin_betting_splits`
- **File:** `scrapers/external/vsin_betting_splits.py`
- **Schedule:** Daily 2:00 PM ET (`nba-vsin-betting-splits`)
- **Status:** ✅ Production — data is server-rendered at data.vsin.com (not AJAX)
- **Use Case:** Public betting percentages for sharp money signal
- **SPOF Warning:** Only public betting % source — no backup

---

## Table Naming Conventions

| Prefix | Source | Example |
|--------|--------|---------|
| `nbac_*` | NBA.com (official) | `nbac_injury_report` |
| ~~`bdl_*`~~ | ~~Ball Don't Lie~~ | RETIRED (Session 430) |
| `odds_api_*` | The Odds API | `odds_api_game_lines` |
| `bettingpros_*` | BettingPros | `bettingpros_player_points_props` |
| `bbref_*` | Basketball Reference | `bbref_player_stats` |
| `bigdataball_*` | BigDataBall | `bigdataball_defense` |
| `numberfire_*` | NumberFire/FanDuel | `numberfire_projections` |
| `fantasypros_*` | FantasyPros | `fantasypros_projections` |
| `dailyfantasyfuel_*` | DailyFantasyFuel | `dailyfantasyfuel_projections` |
| `dimers_*` | Dimers | `dimers_projections` |
| `teamrankings_*` | TeamRankings | `teamrankings_pace` |
| `hashtagbasketball_*` | Hashtag Basketball | `hashtagbasketball_dvp` |
| `rotowire_*` | RotoWire | `rotowire_lineups` |
| `covers_*` | Covers | `covers_referee_stats` |
| `nba_tracking_*` | NBA.com Tracking | `nba_tracking_stats` |
| `vsin_*` | VSiN | `vsin_betting_splits` |

---

## Quick Decision Guide

### "Which source should I use for...?"

**Injury Data:**
- ✅ PRIMARY: `nbac_injury_report` (NBA.com official, sole source)

**Player Stats:**
- ✅ PRIMARY: `nbac_gamebook_player_stats` (official, sole source)

**Schedule:**
- ✅ PRIMARY: `nbac_schedule` (100% coverage)

**Betting Lines:**
- ✅ PRIMARY: `odds_api_*` (real-time, multi-book)
- 🔄 FALLBACK: `bettingpros_*` (consensus)

**Play-by-Play:**
- ✅ PRIMARY: `nbac_play_by_play` (only source)

---

## Implementation Notes

### Why Multiple Sources for Same Data?

1. **Reliability:** Primary can fail, fallback ensures continuity
2. **Validation:** Cross-reference for data quality
3. **Historical:** Some sources added later, both kept
4. **Coverage:** Different sources may have different games

### Phase 1 vs Phase 2

- **Phase 1 (Scrapers):** Extract from external sources → GCS JSON
- **Phase 2 (Raw):** Load JSON → BigQuery raw tables
- **Not all Phase 1 scrapers have Phase 2 tables**

Example: `nbac_injury_report` scraper exists but BDL used in Phase 2 for simplicity.

---

## Finding Scraper Code

All scrapers in: `/home/naji/code/nba-stats-scraper/scrapers/`

```
scrapers/
├── nbacom/           # NBA.com official sources (nbac_*)
├── balldontlie/      # Ball Don't Lie (RETIRED — code remains, scrapers removed from registry)
├── theoddsapi/       # The Odds API (odds_api_*)
├── bettingpros/      # BettingPros (bettingpros_*)
├── basketballref/    # Basketball Reference (bbref_*)
├── projections/      # External projections (numberfire, fantasypros, dff, dimers)
├── external/         # External analytics (teamrankings, hashtag, rotowire, covers, vsin, nba_tracking)
└── registry.py       # Scraper registration (programmatic)
```

---

## See Also

- **Coverage Matrix:** `docs/06-reference/data-sources/01-coverage-matrix.md`
- **Fallback Strategies:** `docs/06-reference/data-sources/02-fallback-strategies.md`
- **Pipeline Design:** `docs/01-architecture/pipeline-design.md`
- **Phase 1 Overview:** `docs/03-phases/phase1-orchestration/overview.md`

---

*Created: 2026-02-05 (Session 127B) - Root cause analysis after discovering NBA.com injury scraper was not documented*
