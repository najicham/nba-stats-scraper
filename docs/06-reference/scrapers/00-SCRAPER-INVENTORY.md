# Phase 1 Scraper Inventory

**Last Updated:** 2026-06-29 (Session — bluesky_nba_news Jetstream listener added)

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

### nba_injury_snapshots (nbainjuries) — NARRATIVE COLLECTION
- **Source:** NBA.com official injury report PDFs (same source as nbac_injury_report)
- **URL:** `https://ak-static.cms.nba.com/referee/injury/`
- **Coverage:** Daily snapshot — one scrape per game day (~5 PM ET pre-game report)
- **BigQuery Table:** `nba_raw.nba_injury_snapshots`
- **File:** `scrapers/external/nba_injury_snapshots.py`
- **Schema:** `schemas/nba_injury_snapshots.json`
- **Status:** Shadow/forward-collection (2026-06-29)
- **Use Case:** Narrative forward-collection for backtesting. Captures who is Out/Questionable/Doubtful pre-game. NOT a Phase 5 signal source — accumulates data for future analysis of injury context vs prop outcomes.
- **Package:** `nbainjuries` (pip install nbainjuries) — parses PDF via tabula/Java
- **Note:** Off-season returns 0 players (403 from NBA.com). Default report time is 17:00 ET; override with --hour/--minute for different snapshots.

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

> **⚠️ SPOF WARNING:** NumberFire is the only working projection source. FantasyPros (Playwright timeout), DailyFantasyFuel (DFS points only), and Dimers (generic non-date-specific projections) are all non-functional. If FanDuel changes the NumberFire GraphQL API, projection features will be unavailable.

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

### vsin_betting_splits (VSiN) — PAYWALLED / DEFUNCT
- **Source:** VSiN.com public betting splits (DraftKings-sourced)
- **URL:** `https://data.vsin.com/nba/betting-splits/` → redirects to Piano-paywalled page
- **BigQuery Table:** `nba_raw.vsin_betting_splits`
- **File:** `scrapers/external/vsin_betting_splits.py`
- **Schedule:** Daily 2:00 PM ET (`nba-vsin-betting-splits`) — still running but producing 0 records
- **Status:** ❌ DEFUNCT — VSiN moved betting splits behind Piano subscription paywall ~2026-03-28. Data table no longer served without credentials. Last data in BQ: 2026-03-28.
- **Use Case:** Public betting percentages for sharp money signal (`sharp_money_over/under` — both shadow)
- **Options:** (1) VSiN subscription + session cookie auth, (2) alternative source (Covers.com, ActionNetwork), (3) accept loss until replacement found

### espn_nba_news (ESPN) — FORWARD COLLECTION
- **Source:** ESPN public JSON API
- **URL:** `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=100`
- **BigQuery Table:** `nba_raw.espn_nba_news`
- **File:** `scrapers/external/espn_nba_news.py`
- **Schema:** `schemas/bigquery/nba_raw/espn_nba_news.json`
- **Schedule:** Daily 8:00 AM ET (to be configured) — recommend once/day pre-game
- **Status:** ✅ Built (2026-06-29) — forward collection only, no live signals yet
- **Use Case:** Capture news headlines/blurbs mentioning players pre-game for future narrative signals (bounce-back, revenge games, milestone proximity, coach rest quotes). Per article: headline, description, published_at, athlete_ids, athlete_names, topic_tags.
- **API Notes:** Public endpoint, no auth. `?dates=YYYYMMDD` filters to a calendar date. Returns 20-30 articles/day during the season. Athlete associations extracted from ESPN `categories` array (type=athlete entries include `athleteId` + name). Player-specific `/athletes/{id}/news` endpoint works but returns empty for historical dates — bulk endpoint is the right choice.

### espn_injuries (ESPN) — FORWARD COLLECTION / GAME-DAY HOURLY
- **Source:** ESPN public JSON API
- **URL:** `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries`
- **BigQuery Table:** `nba_raw.espn_injuries`
- **File:** `scrapers/external/espn_injuries.py`
- **Schema:** `schemas/bigquery/nba_raw/espn_injuries.json`
- **Schedule:** Hourly on game days (to be configured) — critical window 90-30 min before tip-off
- **Status:** ✅ Built (2026-06-29) — forward collection only, no live signal yet
- **Use Case:** Capture timestamped injury status snapshots to detect GTD→Out flips before tip-off. Each hourly run appends a new snapshot row (timestamped GCS path). Downstream query compares `fantasy_status` across hourly `scraped_at` values to find same-day status changes. Foundation for future "teammate OVER when star just went GTD→Out" signal.
- **Key Fields:** `fantasy_status` (GTD/OUT/O/Q), `status` (Day-To-Day/Out/Questionable), `reported_at` (ESPN timestamp), `scraped_at` (collection timestamp), `return_date`.
- **API Notes:** Public endpoint, no auth. Returns all currently reported injuries across all NBA teams. Off-season returns 0 entries (expected). Each run's output is a full snapshot — use `scraped_at` + `espn_injury_id` to reconstruct status timeline.

### bluesky_nba_news (Bluesky Jetstream) — REAL-TIME FORWARD COLLECTION
- **Source:** Bluesky Jetstream WebSocket API (no auth required for public posts)
- **WebSocket:** `wss://jetstream1.us-east.bsky.network/subscribe?wantedCollections=app.bsky.feed.post&wantedDids=...`
- **Handle Resolution:** `https://public.api.bsky.app/xrpc/com.atproto.identity.resolveHandle`
- **BigQuery Table:** `nba_raw.bluesky_nba_news`
- **File:** `scrapers/external/bluesky_nba_news.py`
- **Schema:** `schemas/bigquery/nba_raw/bluesky_nba_news.json`
- **Schedule:** Cloud Run Job — launch at noon ET on game days, run 6 hours. NOT a Cloud Scheduler HTTP scraper. Must be triggered as a long-lived container job.
- **Status:** ✅ Built (2026-06-29) — forward collection only, no live signal yet
- **Use Case:** Real-time capture of beat writer posts about player injury/status changes.
  Captures practice participation language ("limited in practice", "game-time decision",
  "won't play tonight") before official NBA reports propagate. Foundation for future
  "cascade reprice" signal: star player out → teammate OVER opportunity (book repricing
  takes 30-90 min after Bluesky post).
- **Beat Writers Monitored (10):**
  Chris Haynes (ESPN), Marc Stein (Independent), Zach Lowe (ESPN),
  Sam Amick (The Athletic), Jake Fischer (Yahoo), Anthony Slater (ESPN Warriors),
  Dan Woike (The Athletic Lakers), Fred Katz (The Athletic Knicks),
  Jon Krawczynski (The Athletic Wolves), Tim Reynolds (AP)
- **Signal Keywords:** `questionable`, `limited`, `scratch`, `GTD`, `game-time`, `won't play`,
  `out tonight`, `ruled out`, `reduced minutes`, `bounce back`, `called out`,
  `won't start`, `coming off bench`
- **Key Fields:** `post_uri` (dedup key), `did`, `handle`, `author_name`, `post_text`,
  `created_at`, `keywords_matched`, `keyword_count`, `rkey`
- **Package:** `atproto>=0.0.50` (pip) + `websockets>=12.0` — for Jetstream WebSocket
- **Design Notes:** Standalone script (NOT a ScraperBase subclass). Buffers matching posts in
  memory and flushes to GCS + BQ every 5 minutes. SIGTERM triggers graceful drain + final
  flush. Handles WebSocket reconnection with exponential backoff.

### stokastic_dfs_ownership (Stokastic.com) — FORWARD COLLECTION
- **Source:** Stokastic.com DFS ownership projections (unauthenticated Azure backend API)
- **API:** `https://app-api-dfs-prod-main.azurewebsites.net/api/slatedata/projections?SlateId={id}`
- **BigQuery Table:** `nba_raw.stokastic_dfs_ownership`
- **File:** `scrapers/external/stokastic_dfs_ownership.py`
- **Schema:** `schemas/bigquery/nba_raw/stokastic_dfs_ownership.json`
- **Schedule:** Daily 2:00 PM ET (after early lineup news), optional 5 PM ET re-scrape after confirmed lineups
- **Status:** ✅ Built (2026-06-29) — forward collection only, backtest in early 2027 once a season of data accumulates
- **Signal Hypothesis:** High DFS ownership (top-10% of slate, typically 30%+) = public/recreational attention → sportsbooks shade prop lines upward to balance action → UNDER value. Backtest query: for players in top-10% ownership on their game date, what is the UNDER hit rate vs the rest of the slate?
- **Two-Phase Scrape:**
  1. GET `/api/contests/getPreContestSlateInfo?app=DATAHUB&sport=NBA` → find today's DK Main slate ID
  2. GET `/api/slatedata/projections?SlateId={id}` → per-player ownership, salary, projections
- **API Notes:** No authentication required. `ownership` field is decimal 0.0–1.0 (converted to 0–100 pct in BQ). Off-season returns no NBA slates (expected). API is shared with tools.stokastic.com (Stokastic's lineup optimizer SPA), Azure backend `app-api-dfs-prod-main.azurewebsites.net`.
- **Key Fields:** `projected_ownership_pct` (0-100), `projected_salary`, `projected_points`, `projection_std_dev`, `dk_value`, `injury_status`, `confirmed_lineup`, `contest_type` (DK/FD), `slate_id`
- **Pairing with prop lines:** Join on `player_name` + `game_date` to `nba_raw.odds_api_player_points_props` to test ownership vs prop line relationship.

### rotowire_nba_news (RotoWire) — FORWARD COLLECTION
- **Source:** RotoWire public RSS 2.0 feed
- **URL:** `https://www.rotowire.com/rss/news.php?sport=NBA`
- **BigQuery Table:** `nba_raw.rotowire_nba_news`
- **File:** `scrapers/external/rotowire_nba_news.py`
- **Schema:** `schemas/bigquery/nba_raw/rotowire_nba_news.json`
- **Schedule:** Daily 8:00 AM ET (to be configured) — or more frequently during the season to avoid missing items that rotate off the feed
- **Status:** ✅ Built (2026-06-29) — forward collection only, no live signals yet
- **Use Case:** Capture beat-writer reports, injury updates, practice notes, and transaction news from RotoWire for future narrative signals. Complements `espn_nba_news` with a different editorial voice. Per item: player name, action headline, description blurb, published timestamp, RotoWire player ID.
- **Feed Notes:** Public RSS, no auth. Feed returns the ~5-20 most recent items (rotating window — run at least daily to avoid gaps). Title format is reliably `"Player Name: Action"` — player name extraction from the colon separator is consistent. No team abbreviation in the feed; player-to-team mapping requires joining on player name or RotoWire player ID. `<link>` points to the player profile page, not a standalone article.
- **Key Fields:** `player_name` (from title before `:`), `action_text` (title after `:`), `description` (blurb, footer stripped), `published_at` (UTC), `rotowire_player_id` (from URL path).

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
| `rotowire_*` | RotoWire | `rotowire_lineups`, `rotowire_nba_news` |
| `covers_*` | Covers | `covers_referee_stats` |
| `nba_tracking_*` | NBA.com Tracking | `nba_tracking_stats` |
| `vsin_*` | VSiN | `vsin_betting_splits` |
| `espn_nba_*` | ESPN (news/narrative) | `espn_nba_news` |
| `bluesky_*` | Bluesky Jetstream (beat writers) | `bluesky_nba_news` |
| `stokastic_*` | Stokastic.com (DFS ownership) | `stokastic_dfs_ownership` |

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
