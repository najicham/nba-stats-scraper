# Phase 6: Publishing & Exports

**Last Updated:** 2026-02-11 (Session 202: Added game scores to tonight exporter)
**Status:** Production
**Location:** `data_processors/publishing/`

---

## Overview

Phase 6 exports predictions, results, and live scoring data to GCS for website consumption. It runs automatically via Cloud Schedulers and event-driven triggers from Phase 5.

**Output Bucket:** `gs://nba-props-platform-api/v1/`

---

## Exporters (21 Total)

### Core Exports (Daily Results & Predictions)

| Exporter | Output Path | Schedule | Description |
|----------|-------------|----------|-------------|
| `results_exporter.py` | `results/{date}.json` | 5 AM | Daily prediction results with accuracy |
| `predictions_exporter.py` | `predictions/{date}.json` | 1 PM | All predictions grouped by game |
| `best_bets_exporter.py` | `best-bets/{date}.json` | 1 PM | Top 15 ranked picks |
| `system_performance_exporter.py` | `systems/performance.json` | Daily | 5 ML system metrics (7/30/season) |

### Tonight's Games (Homepage)

| Exporter | Output Path | Schedule | Description |
|----------|-------------|----------|-------------|
| `tonight_all_players_exporter.py` | `tonight/all-players.json` | Hourly | All players summary cards **+ game scores** (added Session 202) |
| `tonight_player_exporter.py` | `tonight/player/{lookup}.json` | Hourly | Individual player details (~300 files) |
| `tonight_trend_plays_exporter.py` | `trends/tonight-trend-plays.json` | Hourly | Trending plays for today |

### Trends (Analytics Dashboard)

| Exporter | Output Path | Schedule | Description |
|----------|-------------|----------|-------------|
| `whos_hot_cold_exporter.py` | `trends/whos-hot-v2.json` | Daily 6 AM | Hot/cold players (heat score 0-10) |
| `bounce_back_exporter.py` | `trends/bounce-back-v2.json` | Daily | Players likely to bounce back |
| `what_matters_exporter.py` | `trends/what-matters.json` | Weekly | Key prediction factors |
| `team_tendencies_exporter.py` | `trends/team-tendencies.json` | Bi-weekly | Team-level patterns |
| `quick_hits_exporter.py` | `trends/quick-hits.json` | Weekly | Notable patterns |
| `deep_dive_exporter.py` | `trends/deep-dive.json` | Monthly | In-depth analysis |

### Player Profiles

| Exporter | Output Path | Schedule | Description |
|----------|-------------|----------|-------------|
| `player_profile_exporter.py` | `players/{lookup}.json` | Weekly | Player accuracy profiles |
| `player_season_exporter.py` | API endpoint | On-demand | Season-long stats |
| `player_game_report_exporter.py` | API endpoint | On-demand | Game-by-game reports |
| `streaks_exporter.py` | `streaks/{date}.json` | Daily | OVER/UNDER streaks (4+ games) |

### Live Scoring (Challenge System)

| Exporter | Output Path | Schedule | Description |
|----------|-------------|----------|-------------|
| `live_scores_exporter.py` | `live/{date}.json` | Every 3 min | Real-time game scores |
| `live_grading_exporter.py` | `live-grading/{date}.json` | Every 3 min | Real-time prediction accuracy |
| `status_exporter.py` | `status.json` | Every 3 min | **NEW** Pipeline health for frontend |

---

## Schedulers

```bash
# List all Phase 6 schedulers
gcloud scheduler jobs list --location=us-west2 | grep -E "phase6|export|grading|live"
```

| Scheduler | Schedule | Purpose |
|-----------|----------|---------|
| `phase6-daily-results` | 5 AM PT | Export yesterday's results |
| `phase6-tonight-picks` | 1 PM ET | Export tonight's predictions |
| `phase6-hourly-trends` | Hourly 6AM-11PM | Export trend data |
| `phase6-player-profiles` | Weekly (Sunday 6 AM) | Export all player profiles |
| `grading-daily` | 11 AM ET | Grade yesterday's predictions |
| `live-export-evening` | Every 3 min **4-11 PM** | Live scores during games |
| `live-export-late-night` | Every 3 min 12-1 AM | Late night games |
| `bdl-live-boxscores-evening` | Every 3 min **4-11 PM** | Live boxscores scraper |
| `bdl-live-boxscores-late` | Every 3 min 12-1 AM | Late night boxscores |
| `live-freshness-monitor` | Every 5 min 4 PM-1 AM | **NEW** Self-healing monitor |

---

## Triggering

### Automatic (Event-Driven)
Phase 6 is triggered automatically when Phase 5 completes:
1. Phase 5 predictions complete → publishes to `nba-phase5-predictions-complete`
2. Phase 5→6 orchestrator receives message → publishes to `nba-phase6-export-trigger`
3. Phase 6 Cloud Function runs exporters

### Manual Trigger
```bash
# Trigger tonight's picks export
gcloud scheduler jobs run phase6-tonight-picks --location=us-west2

# Trigger daily results export
gcloud scheduler jobs run phase6-daily-results --location=us-west2

# Run specific exporter locally
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date 2025-12-27 --only tonight,predictions
```

---

## Output Format

All exports are JSON with cache control headers:

| Data Type | Cache TTL | Use Case |
|-----------|-----------|----------|
| Live (scores, grading) | 30 seconds | Real-time challenge grading |
| Tonight (players) | 5 minutes | Homepage player cards |
| Daily (results, picks) | 1 day | Historical data |
| Trends | 1 hour | Analytics dashboard |

---

## Troubleshooting

### Exports Not Running

```bash
# Check Cloud Function logs
gcloud logging read 'resource.type="cloud_run_revision" AND "phase6"' --limit=20 --freshness=2h

# Check scheduler job status
gcloud scheduler jobs describe phase6-tonight-picks --location=us-west2
```

### Live Scoring Not Updating

```bash
# Check live export logs
gcloud logging read 'resource.type="cloud_run_revision" AND "live_export"' --limit=10 --freshness=30m

# Verify GCS files are updating
gsutil ls -l "gs://nba-props-platform-api/v1/live/"
```

### Missing Player Files

```bash
# Check tonight's player exports
gsutil ls "gs://nba-props-platform-api/v1/tonight/player/" | wc -l

# Re-run player exports
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py --date $(date +%Y-%m-%d) --only tonight-players
```

---

## Architecture

```
Phase 5 Complete
      ↓
  Pub/Sub: nba-phase5-predictions-complete
      ↓
  Phase 5→6 Orchestrator (Cloud Function)
      ↓
  Pub/Sub: nba-phase6-export-trigger
      ↓
  Phase 6 Export Function
      ↓
  21 Exporters → GCS (nba-props-platform-api/v1/)
      ↓
  Pub/Sub: nba-phase6-export-complete
```

---

## Related Documentation

- [Daily Monitoring](../../02-operations/daily-monitoring.md) - Health checks
- [Troubleshooting](../../02-operations/troubleshooting.md) - Common issues
- [Orchestrators](../../01-architecture/orchestration/orchestrators.md) - Phase transitions
