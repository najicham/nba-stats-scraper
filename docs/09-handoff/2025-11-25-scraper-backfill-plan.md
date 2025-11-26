# Scraper Backfill Plan Handoff

**Date:** 2025-11-25
**Status:** Ready to Execute
**Priority:** CRITICAL - Blocks Phase 3 predictions pipeline

---

## Executive Summary

We completed a comprehensive audit of all GCS scraped data for seasons 2021-22 through 2024-25. The audit identified 17 backfillable scrapers, with **GetNbaComTeamBoxscore being the CRITICAL blocker** - it has only 1 date of data but needs 5,299 games to enable Phase 3 processors (team_offense_game_summary, team_defense_game_summary).

All backfill scripts have been created, tested (dry run), and are ready to execute.

---

## Ground Truth

From `nbac_schedule` in BigQuery:
- **4 seasons:** 2021-22, 2022-23, 2023-24, 2024-25
- **5,299 total games** across 853 game dates
- Game IDs exported to: `backfill_jobs/scrapers/nbac_team_boxscore/game_ids_to_scrape.csv`

---

## Scrapers Needing Backfill

### ❌ CRITICAL - Empty (need full backfill)

| Scraper | Current | Need | Script Ready |
|---------|---------|------|--------------|
| **GetNbaComTeamBoxscore** | 1 date | 5,299 games | ✅ |
| GetNbaComPlayerBoxscore | 13 dates | 853 dates | ✅ |
| GetNbaComPlayByPlay | 2 dates | 5,299 games | ✅ |
| GetEspnBoxscore | 1 date | 5,299 games | ✅ |

### ⚠️ Partial (gaps identified)

| Scraper | Current | Gap | Script Ready |
|---------|---------|-----|--------------|
| GetOddsApiHistoricalGameLines | 749/853 | ~104 playoff dates | ✅ (existing) |
| BdlStandingsScraper | 2/4 seasons | 2021, 2022, 2023 | ✅ |

### ✅ Complete (verified)

| Scraper | Count |
|---------|-------|
| BdlBoxScoresScraper | 893 dates |
| GetNbaComGamebooks | 888 dates |
| GetNbaComInjuryReport | 922 dates |
| GetEspnScoreboard | 1,343 dates |
| GetBettingProEvents | 878 dates |
| GetBettingProPlayerProps | 865 dates |
| GetOddsApiHistoricalEvents | 848 dates |
| GetOddsApiHistoricalEventOdds | 447 dates (May 2023+) |
| BasketballRefSeasonRoster | 120 files |

---

## Backfill Scripts Location

```
backfill_jobs/scrapers/
├── nbac_team_boxscore/           # CRITICAL - Run first
│   ├── nbac_team_boxscore_scraper_backfill.py
│   └── game_ids_to_scrape.csv    # 5,299 games
├── nbac_player_boxscore/
│   ├── nbac_player_boxscore_scraper_backfill.py
│   └── game_dates_to_scrape.csv  # 853 dates
├── nbac_play_by_play/
│   ├── nbac_play_by_play_scraper_backfill.py
│   └── game_ids_to_scrape.csv
├── bdl_standings/
│   └── bdl_standings_scraper_backfill.py  # Hardcoded: 2021, 2022, 2023
├── espn_game_boxscore/
│   ├── espn_game_boxscore_scraper_backfill.py
│   └── game_ids_to_scrape.csv
└── odds_api_lines/               # Pre-existing, uses Schedule Service
    └── odds_api_lines_scraper_backfill.py
```

---

## Execution Commands

### Priority 1: CRITICAL (Run First)

```bash
# Team Boxscore - CRITICAL BLOCKER
# Estimated time: ~88 minutes (5,299 games at 1s rate limit)

# Dry run first
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --dry-run --limit=10

# Full backfill
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

# By season (for incremental testing)
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --season=2024
```

### Priority 2: Quick Wins

```bash
# BDL Standings - Only 3 API calls (~6 seconds)
python backfill_jobs/scrapers/bdl_standings/bdl_standings_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
```

### Priority 3: Medium

```bash
# Player Boxscore - ~14 minutes (853 dates)
python backfill_jobs/scrapers/nbac_player_boxscore/nbac_player_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

# Play-by-Play - ~88 minutes (5,299 games)
python backfill_jobs/scrapers/nbac_play_by_play/nbac_play_by_play_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
```

### Priority 4: Low (Backups)

```bash
# ESPN Boxscore - ~132 minutes (5,299 games, 1.5s rate limit)
python backfill_jobs/scrapers/espn_game_boxscore/espn_game_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
```

---

## Script Features

All scripts support:
- `--dry-run` - Show what would be processed without scraping
- `--limit=N` - Process only N items (for testing)
- `--season=YYYY` - Filter to specific season (e.g., 2024 for 2024-25)
- `--start-date=YYYY-MM-DD` - Start from specific date
- **Resume logic** - Checks GCS before scraping, skips existing data
- **Rate limiting** - 1-2 seconds between API calls

---

## After Backfill: Next Steps

1. **Verify GCS data completeness** - Re-run audit to confirm all dates filled
2. **Run Phase 2 processors** - Process GCS → BigQuery (nbac_team_boxscore raw table)
3. **Run Phase 3 processors** - team_offense_game_summary, team_defense_game_summary
4. **Run Phase 4 processors** - ml_feature_store_v2
5. **Test Phase 5** - Predictions should now work with real data

---

## Related Files

- **Audit Plan:** `docs/08-projects/current/scraper-audit/plan.md`
- **Checklist:** `docs/08-projects/current/scraper-audit/checklist.md`
- **Changelog:** `docs/08-projects/current/scraper-audit/changelog.md`
- **Scrapers Reference:** `docs/reference/01-scrapers-reference.md`

---

## Known Issues

1. **OddsAPI playoff gaps (~104 dates)** - May be API limitation, not a data collection issue
2. **BigDataBall missing 6 dates** - All-Star weekend dates (no regular games)
3. **ESPN boxscore** - Uses NBA.com game_ids; scraper may need to resolve to ESPN IDs

---

## Scraper Service URL

```
https://nba-scrapers-f7p3g7f6ya-wl.a.run.app
```

Can also be set via environment variable: `SCRAPER_SERVICE_URL`

---

## Quick Start for New Session

```bash
# 1. Start with the CRITICAL blocker
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app \
  --limit=10  # Test with 10 games first

# 2. If successful, run full backfill
python backfill_jobs/scrapers/nbac_team_boxscore/nbac_team_boxscore_scraper_backfill.py \
  --service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

# 3. Verify in GCS
gsutil ls gs://nba-scraped-data/nba-com/team-boxscore/ | wc -l
# Should show ~853 date folders after completion
```
