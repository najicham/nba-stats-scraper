# Start Your Next Session Here

**Updated:** 2026-03-07 (Session 430 — BDL retirement complete + audits)
**Status:** BDL fully retired. Batter backfill running (~20% → resuming). MLB schedulers still paused until Mar 24.

---

## What Was Done (Session 430)

### BDL Retirement — COMPLETE
- Deleted 4 Cloud Scheduler jobs (bdl-catchup-afternoon/evening/midday, bdl-injuries-hourly)
- Removed `bdl_injuries` from NBA registry, 13 BDL entries from both MLB registries
- Removed `ball_dont_lie` scraper group and `balldontlie` source mapping
- Removed BDL IL queries from MLB predictors (return empty set — prop lines filter IL)
- Removed BDL injury integration from NBA predictions (NBA.com sole source)
- Removed BDL pitcher splits query (dead data)
- Removed BDL triggers from MLB analytics service
- **KEPT** BDL in `batter_game_summary_processor.py` UNION (backfill at 108/550 dates)

### Proxy Audit — 3 MLB scrapers enabled
- `mlb_umpire_stats` (UmpScorecards web scrape) → proxy_enabled = True
- `mlb_ballpark_factors` (web scrape) → proxy_enabled = True
- `mlb_reddit_discussion` (Reddit) → proxy_enabled = True

### Data Source Audit — Vulnerability Assessment Complete
See "Data Source Vulnerabilities" section below.

---

## Three Tasks for Next Session

### Task 1: Monitor Batter Backfill Progress

The MLB batter stats backfill is running (started at 108 dates, resuming from 2024-07-14):

```bash
# Check progress
bq query --nouse_legacy_sql 'SELECT COUNT(*) as n, COUNT(DISTINCT game_date) as dates, MAX(game_date) as latest FROM mlb_raw.mlbapi_batter_stats WHERE game_date >= "2024-01-01"'

# When dates reaches ~365+, remove BDL from batter UNION query:
# File: data_processors/analytics/mlb/batter_game_summary_processor.py
# Remove the bdl_batter_stats CTE from unified_batter_stats
# Also update the circuit breaker check (get_upstream_data_check_query)
```

### Task 2: Address Data Source Single Points of Failure

**Critical vulnerabilities identified:**

| Source | Risk | Suggested Action |
|--------|------|-----------------|
| NumberFire | Only working projection source | Monitor FanDuel GraphQL API for changes; consider scraping ESPN projections as backup |
| RotoWire lineups | Only projected minutes source | `minutes_surge_over` signal permanently blocked without this |
| VSiN betting splits | Only public betting % source | Consider Action Network or Pregame.com as backup |
| Covers referee stats | Only referee O/U tendency source | Consider scraping NBA.com L2M reports |
| Hashtag DVP | Only defense-vs-position source | NBA.com tracking stats could approximate |

**Irrecoverable snapshot data** (lost after game day): NumberFire projections, RotoWire lineups, VSiN splits. These cannot be backfilled historically. If a scraper goes down for a day, that data is lost forever.

### Task 3: Clean Up Remaining BDL References (Low Priority)

450+ BDL references remain in codebase (comments, historical config, monitoring code, scraper source files). Most are harmless. Priority targets if cleaning up:

1. `orchestration/cloud_functions/scraper_availability_monitor/main.py` — extensive BDL tracking metrics
2. `orchestration/master_controller.py` — `_evaluate_bdl_catchup()` method
3. `data_processors/analytics/player_game_summary/` — disabled BDL fallback queries
4. `shared/utils/bdl_availability_logger.py` — entire module is dead code
5. `orchestration/cleanup_processor.py` — BDL table references in cleanup lists

These don't affect runtime behavior but create confusion for future developers.

---

## Background: Batter Backfill In Progress

```bash
# If it stopped, resume:
PYTHONPATH=. python scripts/mlb/backfill_batter_stats.py --start 2024-07-14 --end 2025-09-28 --sleep 0.3 --skip-existing
```

---

## System State

| Item | Status |
|------|--------|
| NBA | v430, 8 enabled models, running normally |
| MLB Worker | Deployed — catboost_v1, v1_6_rolling, ensemble_v1 all loading |
| MLB Schedulers | 24 jobs, ALL paused. Resume Mar 24-25. |
| BDL | **FULLY RETIRED** — scheduler jobs deleted, registry entries removed, code cleaned |
| Batter Backfill | Running — 108+ dates done, resuming from 2024-07-14 |
| Proxy | 3 MLB web scrapers now proxy-enabled (umpire_stats, ballpark_factors, reddit) |

## Key Files

| File | Purpose |
|------|---------|
| `data_processors/analytics/mlb/batter_game_summary_processor.py` | Still has BDL UNION — remove when backfill complete |
| `scrapers/registry.py` | Main scraper registry (NBA + MLB) — BDL entries removed |
| `scrapers/mlb/registry.py` | MLB-specific registry — BDL entries removed |
| `scripts/mlb/backfill_batter_stats.py` | MLB Stats API batter backfill |
