# Phase 1 Scraper Inventory

**Last Updated:** 2026-02-05 (Session 127B)

Complete catalog of all 30+ production scrapers organized by data type and source.

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

### bdl_injuries (Ball Don't Lie)
- **Source:** Ball Don't Lie API
- **URL:** `https://api.balldontlie.io/v1/player_injuries`
- **Coverage:** ~95% (daily updates)
- **BigQuery Table:** `nba_raw.bdl_injuries`
- **File:** `scrapers/balldontlie/bdl_injuries.py`
- **Status:** ✅ Production
- **Use Case:** Fallback if NBA.com unavailable
- **Note:** Known reliability issues with other BDL data

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

### bdl_player_box_scores (Ball Don't Lie)
- **Source:** Ball Don't Lie API
- **BigQuery Table:** `nba_raw.bdl_player_box_scores`
- **Use Case:** Fallback for missing gamebook data
- **File:** `scrapers/balldontlie/bdl_player_box_scores.py`

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

## Table Naming Conventions

| Prefix | Source | Example |
|--------|--------|---------|
| `nbac_*` | NBA.com (official) | `nbac_injury_report` |
| `bdl_*` | Ball Don't Lie | `bdl_injuries` |
| `odds_api_*` | The Odds API | `odds_api_game_lines` |
| `bettingpros_*` | BettingPros | `bettingpros_player_points_props` |
| `bbref_*` | Basketball Reference | `bbref_player_stats` |
| `bigdataball_*` | BigDataBall | `bigdataball_defense` |

---

## Quick Decision Guide

### "Which source should I use for...?"

**Injury Data:**
- ✅ PRIMARY: `nbac_injury_report` (NBA.com official)
- 🔄 FALLBACK: `bdl_injuries` (Ball Don't Lie)

**Player Stats:**
- ✅ PRIMARY: `nbac_gamebook_player_stats` (official)
- 🔄 FALLBACK: `bdl_player_box_scores`

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
├── balldontlie/      # Ball Don't Lie (bdl_*)
├── theoddsapi/       # The Odds API (odds_api_*)
├── bettingpros/      # BettingPros (bettingpros_*)
├── basketballref/    # Basketball Reference (bbref_*)
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
