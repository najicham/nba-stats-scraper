# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 429 — BDL retirement + data source audit)
**Status:** MLB fully deployed. BDL subscription being cancelled. Batter backfill running (~20% done).

---

## Three Tasks for This Session

### Task 1: Fully Disable BDL (NBA + MLB)

BDL (Ball Don't Lie) subscription is being cancelled. ALL BDL data is unreliable:
- MLB pitcher stats: 15 rows (dead)
- MLB batter stats: 97K rows but no game-level granularity (`game_id = "DATE_UNK_UNK"`)
- MLB injuries: 222 rows from 1 date (useless)
- NBA BDL: Already decommissioned for everything except `bdl_injuries` (Session 151)
- 24 other BDL MLB tables: completely empty

**Full analysis:** `docs/08-projects/current/mlb-pitcher-strikeouts/BDL-RETIREMENT-PLAN.md`

#### What to remove/disable:

**Scheduler jobs (4 paused BDL jobs — DELETE them):**
```bash
gcloud scheduler jobs list --location=us-west2 --project=nba-props-platform | grep bdl
# bdl-catchup-afternoon, bdl-catchup-evening, bdl-catchup-midday, bdl-injuries-hourly
# All already PAUSED. Safe to delete.
```

**NBA main registry (`scrapers/registry.py`):**
- Line 77: `bdl_injuries` scraper entry → REMOVE
- Lines 482-488: `ball_dont_lie` source grouping → REMOVE

**MLB registries:**
- `scrapers/mlb/registry.py` lines 33-88: 13 BDL MLB scraper entries → REMOVE
- `scrapers/mlb/registry.py` line 241-248: `balldontlie` source grouping → REMOVE
- `scrapers/registry.py` lines 262-274: 13 BDL MLB scraper entries → REMOVE

**Analytics processors:**
- `data_processors/analytics/mlb/batter_game_summary_processor.py`: Remove BDL from UNION query (keep mlbapi-only). **Wait until batter backfill completes** — check: `SELECT COUNT(DISTINCT game_date) FROM mlb_raw.mlbapi_batter_stats` should be ~365.
- `data_processors/analytics/mlb/main_mlb_analytics_service.py` line 68: Remove `bdl_pitcher_stats` trigger
- `data_processors/analytics/mlb/main_mlb_analytics_service.py` line 70: Remove `bdl_batter_stats` trigger

**Prediction code:**
- `predictions/mlb/base_predictor.py:119`: `bdl_injuries` query — REMOVE (see BDL-RETIREMENT-PLAN.md Option C: prop lines already filter IL pitchers)
- `predictions/mlb/pitcher_strikeouts_predictor.py:245`: Same `bdl_injuries` query — REMOVE

**NBA code to check:**
```bash
# Find any remaining NBA bdl_ references
grep -rn "bdl_" data_processors/ predictions/ orchestration/ shared/ --include="*.py" | grep -v ".pyc" | grep -v mlb | grep -v __pycache__
```

---

### Task 2: Data Source Audit — Coverage & Backup Check

Audit every active data source. For each: does it have a backup? Can we backfill historical?

**Full current inventory:** `docs/08-projects/current/mlb-pitcher-strikeouts/DATA-SOURCES.md`

#### NBA Data Sources (check these)

| Source | Scraper | proxy_enabled | Backup? | Historical? |
|--------|---------|:---:|---------|-------------|
| NBA.com stats | `nbac_*` (10 scrapers) | YES (most) | No backup | Yes — stats.nba.com endpoints |
| Odds API | `oddsa_*` | NO | No backup | Yes — historical endpoint ($) |
| BettingPros | `bp_*` | YES | No backup | Partial (props scraper) |
| NumberFire | `numberfire_projections` | NO | No backup | No — daily snapshots only |
| FantasyPros | `fantasypros_projections` | YES | No backup | No — DEAD (Playwright timeout) |
| Dimers | `dimers_projections` | YES | No backup | No — DEAD (generic projections) |
| DailyFantasyFuel | `dailyfantasyfuel_projections` | YES | No backup | No — DEAD (DFS only) |
| TeamRankings | `teamrankings_stats` | YES | No backup | No — current season snapshot |
| Hashtag Basketball | `hashtagbasketball_dvp` | YES | No backup | No — current season |
| RotoWire | `rotowire_lineups` | YES | No backup | No — daily lineups |
| VSiN | `vsin_betting_splits` | YES | No backup | No — daily splits |
| Covers | `covers_referee_stats` | YES | No backup | No — current season |
| NBA Tracking | `nba_tracking_stats` | YES | No backup | Yes — stats.nba.com |

#### MLB Data Sources

| Source | Scraper | proxy_enabled | Backup? | Historical? |
|--------|---------|:---:|---------|-------------|
| MLB Stats API | `mlb_schedule`, `mlb_lineups`, `mlb_box_scores_mlbapi`, `mlb_umpire_assignments` | NO | N/A — free official API | Yes |
| BettingPros | `bp_pitcher_props` | NO | No backup | Partial |
| Odds API | `mlb_pitcher_props`, `mlb_game_lines` | NO | No backup | Yes — historical ($) |
| Statcast (pybaseball) | `mlb_statcast_*` | NO | No backup | Yes — pybaseball |
| FanGraphs | `fangraphs_pitcher_season_stats` | NO | No backup | Yes — web scrape |
| UmpScorecards | `mlb_umpire_stats` | NO | No backup | Yes — web scrape |
| Weather | `mlb_weather` | NO | OpenWeatherMap | Yes — Open-Meteo |
| Reddit | `mlb_reddit_discussion` | NO | No backup | No — daily |

**Key questions to answer:**
1. Which scrapers could we lose tomorrow and not recover? (No historical backfill possible)
2. Which have single points of failure? (Only 1 source, no backup)
3. Which are we NOT collecting that we should be? (Game lines empty, weather empty, umpire assignments empty)

---

### Task 3: Proxy Audit — Ensure All Scrapers Use Proxies

Many scrapers have `proxy_enabled = False` that probably should use proxies, especially web scrapers hitting sites that block cloud IPs.

**Proxy architecture:** `scrapers/scraper_base.py` line 219 — default is `False`. Each scraper overrides.

#### Scrapers currently WITHOUT proxy that may need it:

**NBA — probably fine without proxy:**
- `nbac_schedule_cdn` — CDN, unlikely to block
- `nbac_player_movement` — NBA.com, low volume
- `numberfire_projections` — GraphQL API (FanDuel)

**MLB — need proxy review:**
- ALL MLB external scrapers (`proxy_enabled = False`):
  - `mlb_umpire_stats` — UmpScorecards web scrape
  - `mlb_weather` — OpenWeatherMap API (probably fine, has API key)
  - `mlb_reddit_discussion` — Reddit (cloud IPs often blocked)
  - `mlb_ballpark_factors` — web scrape
- ALL MLB Odds API scrapers — API key auth, probably fine
- ALL MLB Stats API scrapers — free official API, cloud-friendly
- `mlb_statcast_*` — pybaseball, uses different HTTP library (not our proxy system)
- `fangraphs_pitcher_season_stats` — web scrape, SHOULD use proxy

**Questions:**
1. What proxy service do we use? Check env vars: `PROXY_URL`, `PROXY_URLS`
2. Are proxies healthy? Run: `PYTHONPATH=. python -c "from scrapers.utils.proxy_utils import get_proxy_health_summary; print(get_proxy_health_summary())"`
3. Which scrapers have failed due to blocking? Check Cloud Run logs for 403/429 errors

---

## Background: Batter Stats Backfill In Progress

```bash
# Check progress (should reach ~365 dates / ~97K records)
bq query --nouse_legacy_sql 'SELECT COUNT(*) as n, COUNT(DISTINCT game_date) as dates, MAX(game_date) as latest FROM mlb_raw.mlbapi_batter_stats WHERE game_date >= "2024-01-01"'

# If it stopped, resume from where it left off:
PYTHONPATH=. python scripts/mlb/backfill_batter_stats.py --start 2024-03-28 --end 2025-09-28 --sleep 0.3 --skip-existing
```

Once backfill reaches ~365 dates, the BDL batter table can be dropped from the UNION query.

---

## System State

| Item | Status |
|------|--------|
| NBA | v429_signal_weight_cleanup, 8 enabled models, running normally |
| MLB Worker | Deployed — catboost_v1, v1_6_rolling, ensemble_v1 all loading |
| MLB Schedulers | 24 jobs, ALL paused. Resume Mar 24-25. |
| CatBoost V1 | Enabled in BQ registry (is_production=TRUE) |
| Batter Backfill | Running — ~23K records, ~98 dates done (of ~550) |
| BDL | 4 scheduler jobs PAUSED. 13+13 registry entries to remove. Subscription being cancelled. |

## Key Files

| File | Purpose |
|------|---------|
| `docs/08-projects/current/mlb-pitcher-strikeouts/BDL-RETIREMENT-PLAN.md` | Full BDL analysis + removal plan |
| `docs/08-projects/current/mlb-pitcher-strikeouts/DATA-SOURCES.md` | All MLB data sources + gaps |
| `scrapers/registry.py` | Main scraper registry (NBA + MLB) |
| `scrapers/mlb/registry.py` | MLB-specific scraper registry |
| `scrapers/scraper_base.py:219` | Proxy default (False) |
| `scrapers/utils/proxy_utils.py` | Proxy rotation + health tracking |
| `scripts/mlb/backfill_batter_stats.py` | MLB Stats API batter backfill |
