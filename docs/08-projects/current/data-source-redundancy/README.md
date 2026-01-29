# Data Source Redundancy Project

**Status**: ✅ Phase 1 Complete | 🟡 Phase 2 In Progress
**Started**: 2026-01-28
**Last Updated**: 2026-01-28

## Overview

This project establishes a comprehensive data redundancy and quality monitoring system to ensure the NBA stats pipeline never fails due to a single data source going down or returning bad data.

## Documents in This Directory

| Document | Purpose |
|----------|---------|
| [PROJECT-PLAN.md](./PROJECT-PLAN.md) | Full project plan with all phases |
| [IMPLEMENTATION-COMPLETE.md](./IMPLEMENTATION-COMPLETE.md) | What was built and how to use it |
| [BIGDATABALL-PBP-MONITOR.md](./BIGDATABALL-PBP-MONITOR.md) | BDB PBP monitor design and status |
| [QUICK-REFERENCE.md](./QUICK-REFERENCE.md) | Commands quick reference |

## Quick Status

### Data Sources
| Source | Status | Table |
|--------|--------|-------|
| NBA.com Gamebook | ✅ Primary | `nba_raw.nbac_gamebook_player_stats` |
| Basketball Reference | ✅ Backup | `nba_raw.bref_player_boxscores` |
| NBA API BoxScoreV3 | ✅ Backup | `nba_raw.nba_api_player_boxscores` |
| BDL API | ⚠️ Disabled | `nba_raw.bdl_player_boxscores` |

### Monitoring
| System | Status | Schedule |
|--------|--------|----------|
| Cross-source validation | ✅ Active | Daily 11 AM UTC |
| BDL quality monitor | ✅ Active | Daily 10 AM UTC |
| BDB PBP monitor | ✅ Active | Every 30 min |
| GCS backups | ✅ Active | Weekly Sundays |

## Key Commands

```bash
# Morning health check (includes source health)
./bin/monitoring/morning_health_check.sh

# Cross-source validation
python bin/monitoring/cross_source_validator.py --date 2026-01-27

# BDB PBP gap check
python bin/monitoring/bdb_pbp_monitor.py --date 2026-01-27

# Scrape backup sources
python scrapers/basketball_reference/bref_boxscore_scraper.py --date 2026-01-27
python scrapers/nba_api_backup/boxscore_traditional_scraper.py --date 2026-01-27
```

## Related Handoffs

- [Session 8 Final Handoff](../../09-handoff/2026-01-28-SESSION-8-FINAL-HANDOFF.md)
