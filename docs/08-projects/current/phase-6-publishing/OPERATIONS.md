# Phase 6: Operations Guide

**Last Updated:** 2025-12-10

This guide covers day-to-day operations for the Phase 6 Publishing system.

---

## Infrastructure

### GCS Bucket

| Property | Value |
|----------|-------|
| Bucket | `gs://nba-props-platform-api` |
| Location | us-central1 |
| Public | Yes (allUsers:objectViewer) |
| Versioning | Enabled |
| CORS | Enabled for nbaprops.com, localhost:3000 |

**Public URL Pattern:**
```
https://storage.googleapis.com/nba-props-platform-api/v1/{path}
```

### BigQuery Tables

| Table | Purpose |
|-------|---------|
| `nba_predictions.prediction_accuracy` | Source data (from Phase 5B) |
| `nba_predictions.system_daily_performance` | Pre-aggregated daily metrics |

---

## CLI Reference

All commands run from project root:

```bash
# Set PYTHONPATH
export PYTHONPATH=/home/naji/code/nba-stats-scraper

# Or prefix each command
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py [options]
```

### Export Single Date

```bash
# All export types for one date
python backfill_jobs/publishing/daily_export.py --date 2021-11-10

# Specific types only
python backfill_jobs/publishing/daily_export.py --date 2021-11-10 --only results
python backfill_jobs/publishing/daily_export.py --date 2021-11-10 --only results,best-bets,predictions
```

**Export types:** `results`, `performance`, `best-bets`, `predictions`

### Backfill All Dates

```bash
# All dates with graded predictions
python backfill_jobs/publishing/daily_export.py --backfill-all

# Date range
python backfill_jobs/publishing/daily_export.py --start-date 2021-11-01 --end-date 2021-12-31
```

### Export Player Profiles

```bash
# All players with 5+ games (default)
python backfill_jobs/publishing/daily_export.py --players

# Custom minimum games threshold
python backfill_jobs/publishing/daily_export.py --players --min-games 10
python backfill_jobs/publishing/daily_export.py --players --min-games 20
```

### Default Behavior (No Args)

```bash
# Exports yesterday's data
python backfill_jobs/publishing/daily_export.py
```

---

## JSON Schemas

### results/{date}.json

```json
{
  "game_date": "2021-11-10",
  "generated_at": "2025-12-10T05:00:00Z",
  "summary": {
    "total_predictions": 150,
    "total_recommendations": 120,
    "correct": 72,
    "incorrect": 48,
    "win_rate": 0.600,
    "avg_mae": 4.85
  },
  "results": [
    {
      "player_lookup": "lebronjames",
      "game_id": "0022100123",
      "team": "LAL",
      "opponent": "MIA",
      "predicted": 28.5,
      "actual": 32,
      "line": 26.5,
      "recommendation": "OVER",
      "result": "WIN",
      "error": 3.5,
      "confidence": 0.72
    }
  ],
  "highlights": {
    "biggest_hit": {...},
    "biggest_miss": {...}
  }
}
```

### best-bets/{date}.json

```json
{
  "game_date": "2021-11-10",
  "generated_at": "2025-12-10T05:00:00Z",
  "criteria": {
    "min_confidence": 0.65,
    "min_edge": 2.0
  },
  "summary": {
    "total_bets": 15,
    "over_count": 8,
    "under_count": 7,
    "avg_confidence": 0.73,
    "avg_edge": 3.2
  },
  "bets": [
    {
      "player_lookup": "stephencurry",
      "team": "GSW",
      "opponent": "LAC",
      "predicted": 32.1,
      "line": 28.5,
      "recommendation": "OVER",
      "edge": 3.6,
      "confidence": 0.78,
      "result": "WIN",
      "actual": 35
    }
  ]
}
```

### predictions/{date}.json

```json
{
  "game_date": "2021-11-10",
  "generated_at": "2025-12-10T05:00:00Z",
  "games": [
    {
      "game_id": "0022100123",
      "home_team": "LAL",
      "away_team": "MIA",
      "predictions": [
        {
          "player_lookup": "lebronjames",
          "team": "LAL",
          "predicted": 28.5,
          "line": 26.5,
          "recommendation": "OVER",
          "confidence": 0.72,
          "edge": 2.0
        }
      ]
    }
  ],
  "summary": {
    "total_games": 8,
    "total_predictions": 150,
    "over_count": 75,
    "under_count": 60,
    "pass_count": 15
  }
}
```

### systems/performance.json

```json
{
  "as_of_date": "2022-01-07",
  "generated_at": "2025-12-10T05:00:00Z",
  "systems": [
    {
      "system_id": "ensemble_v1",
      "display_name": "Ensemble",
      "description": "Weighted combination of all prediction systems",
      "is_primary": true,
      "ranking": 1,
      "windows": {
        "last_7_days": {
          "predictions": 850,
          "win_rate": 0.623,
          "mae": 4.52
        },
        "last_30_days": {
          "predictions": 3200,
          "win_rate": 0.615,
          "mae": 4.68
        },
        "season": {
          "predictions": 47355,
          "win_rate": 0.608,
          "mae": 4.85
        }
      }
    }
  ]
}
```

### players/index.json

```json
{
  "generated_at": "2025-12-10T05:00:00Z",
  "total_players": 472,
  "players": [
    {
      "player_lookup": "buddyhield",
      "team": "SAC",
      "games_predicted": 32,
      "recommendations": 24,
      "mae": 5.59,
      "win_rate": 0.667,
      "bias": 0.22,
      "within_5_pct": 0.531
    }
  ]
}
```

### players/{lookup}.json

```json
{
  "player_lookup": "lebronjames",
  "generated_at": "2025-12-10T05:00:00Z",
  "summary": {
    "team": "LAL",
    "games_predicted": 22,
    "total_recommendations": 14,
    "correct": 13,
    "mae": 7.07,
    "win_rate": 0.929,
    "bias": -4.07,
    "avg_confidence": 0.70,
    "within_3_pct": 0.227,
    "within_5_pct": 0.318,
    "date_range": {
      "first": "2021-11-19",
      "last": "2022-01-07"
    }
  },
  "interpretation": {
    "bias": "We significantly under-predict this player (bias: -4.07)",
    "accuracy": "Excellent track record (93% win rate)",
    "sample_size": "Large sample size"
  },
  "recent_predictions": [
    {
      "game_date": "2022-01-07",
      "game_id": "0022100567",
      "opponent": "ATL",
      "predicted": 24.5,
      "actual": 32,
      "line": 25.5,
      "recommendation": "PASS",
      "result": "PASS",
      "error": 7.5,
      "confidence": 0.55
    }
  ],
  "by_recommendation": {
    "over": {"count": 8, "correct": 7, "win_rate": 0.875, "mae": 6.2},
    "under": {"count": 6, "correct": 6, "win_rate": 1.0, "mae": 5.8},
    "pass": {"count": 8, "correct": null, "win_rate": null, "mae": 8.1}
  }
}
```

---

## Verification Commands

### Check GCS Files

```bash
# List all files
gsutil ls -r gs://nba-props-platform-api/v1/

# Count files by type
gsutil ls gs://nba-props-platform-api/v1/results/*.json | wc -l
gsutil ls gs://nba-props-platform-api/v1/players/*.json | wc -l

# View file contents
gsutil cat gs://nba-props-platform-api/v1/results/latest.json | jq '.summary'
```

### Test Public URLs

```bash
# Results
curl -s https://storage.googleapis.com/nba-props-platform-api/v1/results/latest.json | jq '.summary'

# System performance
curl -s https://storage.googleapis.com/nba-props-platform-api/v1/systems/performance.json | jq '.systems[0].windows'

# Player index
curl -s https://storage.googleapis.com/nba-props-platform-api/v1/players/index.json | jq '.total_players'

# Specific player
curl -s https://storage.googleapis.com/nba-props-platform-api/v1/players/lebronjames.json | jq '.summary'
```

### Verify BigQuery Source

```bash
# Check prediction_accuracy data
bq query --use_legacy_sql=false "
SELECT
  MIN(game_date) as min_date,
  MAX(game_date) as max_date,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as records
FROM nba_predictions.prediction_accuracy"

# Check system_daily_performance
bq query --use_legacy_sql=false "
SELECT COUNT(*) as rows FROM nba_predictions.system_daily_performance"
```

---

## Troubleshooting

### Export Fails with "No data found"

Check that the date has predictions:
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) FROM nba_predictions.prediction_accuracy
WHERE game_date = '2021-11-10'"
```

### GCS Permission Denied

Ensure bucket is public:
```bash
gsutil iam get gs://nba-props-platform-api | grep allUsers
```

If missing:
```bash
gsutil iam ch allUsers:objectViewer gs://nba-props-platform-api
```

### Player Profile Missing

Check player has minimum games:
```bash
bq query --use_legacy_sql=false "
SELECT player_lookup, COUNT(DISTINCT game_date) as games
FROM nba_predictions.prediction_accuracy
WHERE player_lookup = 'someplayername'
GROUP BY 1"
```

### Cache Not Updating

GCS caches files based on Cache-Control header. Force refresh:
```bash
# Re-upload with updated timestamp
python backfill_jobs/publishing/daily_export.py --date 2021-11-10 --only results
```

---

## Daily Operations Checklist

For live operations (when processing current season):

1. **After games complete** (next morning):
   ```bash
   # Run grading first (Phase 5B)
   PYTHONPATH=. .venv/bin/python -c "
   from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import PredictionAccuracyProcessor
   processor = PredictionAccuracyProcessor()
   result = processor.process('YYYY-MM-DD')
   print(result)"

   # Then export
   python backfill_jobs/publishing/daily_export.py --date YYYY-MM-DD
   ```

2. **Weekly**: Refresh player profiles
   ```bash
   python backfill_jobs/publishing/daily_export.py --players --min-games 5
   ```

3. **Verify**: Check latest.json updated
   ```bash
   curl -s https://storage.googleapis.com/nba-props-platform-api/v1/results/latest.json | jq '.game_date'
   ```

---

## Future: Cloud Scheduler Automation

### When to Set Up

Cloud Scheduler automation is only needed when:
- Processing **live/current season** games daily
- You want hands-off operation

For historical backfills, manual CLI usage is sufficient.

### Architecture

```
Cloud Scheduler (cron) → Pub/Sub Topic → Cloud Function → daily_export.py → GCS
                                                ↓
                                         BigQuery (read)
```

### Step 1: Create Cloud Function

Create `cloud_functions/daily_export/main.py`:

```python
import functions_framework
from datetime import datetime, timedelta
import subprocess
import os

@functions_framework.cloud_event
def main(cloud_event):
    """Triggered by Pub/Sub message."""
    # Default to yesterday
    target_date = (datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d')

    # Run the export
    result = subprocess.run([
        'python', 'backfill_jobs/publishing/daily_export.py',
        '--date', target_date
    ], capture_output=True, text=True)

    print(f"Export for {target_date}: {result.returncode}")
    print(result.stdout)
    if result.stderr:
        print(f"Errors: {result.stderr}")

    return f"Exported {target_date}"
```

Create `cloud_functions/daily_export/requirements.txt`:

```
functions-framework==3.*
google-cloud-bigquery>=3.0.0
google-cloud-storage>=2.0.0
```

### Step 2: Deploy Infrastructure

```bash
# Create Pub/Sub topic
gcloud pubsub topics create daily-prediction-export

# Deploy Cloud Function
gcloud functions deploy daily-prediction-export \
  --gen2 \
  --runtime python310 \
  --region us-central1 \
  --trigger-topic daily-prediction-export \
  --entry-point main \
  --source ./cloud_functions/daily_export \
  --timeout 540s \
  --memory 512MB

# Create Cloud Scheduler job
# Runs at 10 AM UTC (5 AM ET) - after overnight games complete
gcloud scheduler jobs create pubsub daily-export-trigger \
  --location us-central1 \
  --schedule "0 10 * * *" \
  --topic daily-prediction-export \
  --message-body '{}' \
  --description "Daily prediction export to GCS"
```

### Step 3: Test

```bash
# Manual trigger
gcloud scheduler jobs run daily-export-trigger --location us-central1

# Check logs
gcloud functions logs read daily-prediction-export --region us-central1
```

### Step 4: Player Profile Refresh (Weekly)

Create separate scheduler for weekly player refresh:

```bash
gcloud scheduler jobs create pubsub weekly-player-export \
  --location us-central1 \
  --schedule "0 12 * * 0" \
  --topic daily-prediction-export \
  --message-body '{"players": true}' \
  --description "Weekly player profile refresh"
```

### Cost Estimate

- Cloud Scheduler: Free (up to 3 jobs)
- Cloud Functions: ~$0.01/day (minimal invocations)
- GCS Storage: ~$0.02/month (< 1GB)
- BigQuery: Free tier covers queries

**Total: < $1/month**

---

## Future Steps

### Phase 6.3: Cloud Scheduler (When Ready for Live)

1. Create Cloud Function wrapper (code above)
2. Deploy to GCP
3. Create scheduler jobs (daily + weekly)
4. Monitor first few runs
5. Set up alerting on failures

### Frontend Integration

When frontend is ready:

1. Update CORS config if needed for production domain
2. Implement TypeScript API client (example below)
3. Add error handling for missing dates
4. Consider caching layer (SWR/React Query)

### Data Expansion

When expanding to more data:

1. **More prediction systems** - Add to system_daily_performance
2. **More prop types** - Currently points only, could add assists/rebounds
3. **Live odds** - Could add sportsbook lines to predictions JSON
4. **Historical archive** - Current data is 2021-22 season only

### Monitoring (Future)

Consider adding:

1. **Cloud Monitoring dashboard** - Track export success/failure
2. **Alerting** - PagerDuty/Slack on export failures
3. **Data freshness check** - Alert if latest.json is stale

---

## Frontend Integration Example

```typescript
// lib/api.ts
const API_BASE = 'https://storage.googleapis.com/nba-props-platform-api/v1';

export async function getLatestResults() {
  const res = await fetch(`${API_BASE}/results/latest.json`);
  return res.json();
}

export async function getResultsByDate(date: string) {
  const res = await fetch(`${API_BASE}/results/${date}.json`);
  return res.json();
}

export async function getBestBets() {
  const res = await fetch(`${API_BASE}/best-bets/latest.json`);
  return res.json();
}

export async function getSystemPerformance() {
  const res = await fetch(`${API_BASE}/systems/performance.json`);
  return res.json();
}

export async function getPlayerIndex() {
  const res = await fetch(`${API_BASE}/players/index.json`);
  return res.json();
}

export async function getPlayerProfile(lookup: string) {
  const res = await fetch(`${API_BASE}/players/${lookup}.json`);
  return res.json();
}
```

---

**End of Operations Guide**
