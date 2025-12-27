# Phase 6: Website Publishing - Implementation Guide

**Last Updated:** 2025-12-10
**Author:** Session 115 (Claude)

---

## Executive Summary

This guide provides practical implementation steps for Phase 6, building on the existing DESIGN.md. Phase 6 transforms `prediction_accuracy` data into JSON files for the React/Next.js website.

---

## Prerequisites

Before starting Phase 6, ensure:

1. **Phase 5B is complete** - `prediction_accuracy` table has data
2. **Backfill is done** - ~47,395 records across 62 dates
3. **GCS bucket exists** - Or will be created as first step

### Verify Prerequisites

```sql
-- Check prediction_accuracy has data
SELECT
  MIN(game_date) as min_date,
  MAX(game_date) as max_date,
  COUNT(DISTINCT game_date) as dates,
  COUNT(*) as records
FROM nba_predictions.prediction_accuracy;
```

---

## Step 1: Create GCS Bucket

```bash
# Create bucket
gsutil mb -l us-central1 gs://nba-props-platform-api

# Enable versioning (for rollback)
gsutil versioning set on gs://nba-props-platform-api

# Set CORS
cat > cors.json << 'EOF'
[
  {
    "origin": ["https://nbaprops.com", "http://localhost:3000"],
    "method": ["GET"],
    "responseHeader": ["Content-Type", "Cache-Control"],
    "maxAgeSeconds": 3600
  }
]
EOF
gsutil cors set cors.json gs://nba-props-platform-api

# Make bucket public (for CDN)
gsutil iam ch allUsers:objectViewer gs://nba-props-platform-api
```

---

## Step 2: Create BigQuery Aggregation Table

### system_daily_performance

This table pre-aggregates daily metrics for fast JSON export:

```sql
CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.system_daily_performance` (
  -- Keys
  game_date DATE NOT NULL,
  system_id STRING NOT NULL,

  -- Daily Metrics
  predictions_count INTEGER,
  recommendations_count INTEGER,
  correct_count INTEGER,
  incorrect_count INTEGER,

  -- Accuracy Metrics
  win_rate NUMERIC(4, 3),
  mae NUMERIC(5, 2),
  avg_bias NUMERIC(5, 2),

  -- OVER/UNDER Breakdown
  over_count INTEGER,
  over_correct INTEGER,
  over_win_rate NUMERIC(4, 3),
  under_count INTEGER,
  under_correct INTEGER,
  under_win_rate NUMERIC(4, 3),

  -- Confidence Analysis
  avg_confidence NUMERIC(4, 3),
  high_confidence_count INTEGER,
  high_confidence_correct INTEGER,

  -- Metadata
  computed_at TIMESTAMP
)
PARTITION BY game_date
CLUSTER BY system_id;
```

### Populate from prediction_accuracy

```sql
INSERT INTO `nba-props-platform.nba_predictions.system_daily_performance`
SELECT
  game_date,
  system_id,

  -- Daily Metrics
  COUNT(*) as predictions_count,
  COUNTIF(recommendation IN ('OVER', 'UNDER')) as recommendations_count,
  COUNTIF(prediction_correct) as correct_count,
  COUNTIF(NOT prediction_correct AND recommendation IN ('OVER', 'UNDER')) as incorrect_count,

  -- Accuracy Metrics
  ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(recommendation IN ('OVER', 'UNDER'))), 3) as win_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  ROUND(AVG(signed_error), 2) as avg_bias,

  -- OVER/UNDER Breakdown
  COUNTIF(recommendation = 'OVER') as over_count,
  COUNTIF(recommendation = 'OVER' AND prediction_correct) as over_correct,
  ROUND(SAFE_DIVIDE(COUNTIF(recommendation = 'OVER' AND prediction_correct), COUNTIF(recommendation = 'OVER')), 3) as over_win_rate,
  COUNTIF(recommendation = 'UNDER') as under_count,
  COUNTIF(recommendation = 'UNDER' AND prediction_correct) as under_correct,
  ROUND(SAFE_DIVIDE(COUNTIF(recommendation = 'UNDER' AND prediction_correct), COUNTIF(recommendation = 'UNDER')), 3) as under_win_rate,

  -- Confidence Analysis
  ROUND(AVG(confidence_score), 3) as avg_confidence,
  COUNTIF(confidence_score >= 0.7) as high_confidence_count,
  COUNTIF(confidence_score >= 0.7 AND prediction_correct) as high_confidence_correct,

  -- Metadata
  CURRENT_TIMESTAMP() as computed_at

FROM `nba-props-platform.nba_predictions.prediction_accuracy`
GROUP BY game_date, system_id;
```

---

## Step 3: Implement JSON Exporters

### File Structure

```
data_processors/publishing/
├── __init__.py
├── base_exporter.py           # Common functionality
├── results_exporter.py        # results/{date}.json
├── system_performance_exporter.py  # systems/performance.json
├── gcs_uploader.py            # Upload to GCS
```

### Base Exporter

```python
# data_processors/publishing/base_exporter.py
from abc import ABC, abstractmethod
from google.cloud import bigquery
from google.cloud import storage
import json
from datetime import datetime

class BaseExporter(ABC):
    def __init__(self):
        self.bq_client = bigquery.Client()
        self.gcs_client = storage.Client()
        self.bucket_name = 'nba-props-platform-api'

    @abstractmethod
    def generate_json(self, target_date: str) -> dict:
        """Generate JSON content for export."""
        pass

    def upload_to_gcs(self, json_data: dict, path: str, cache_control: str = 'public, max-age=300'):
        """Upload JSON to GCS with cache headers."""
        bucket = self.gcs_client.bucket(self.bucket_name)
        blob = bucket.blob(f'v1/{path}')
        blob.upload_from_string(
            json.dumps(json_data, indent=2, default=str),
            content_type='application/json'
        )
        blob.cache_control = cache_control
        blob.patch()
        return f'gs://{self.bucket_name}/v1/{path}'

    def query_to_dict(self, query: str) -> list:
        """Execute query and return list of dicts."""
        result = self.bq_client.query(query).result()
        return [dict(row) for row in result]
```

### Results Exporter (MVP Priority #1)

```python
# data_processors/publishing/results_exporter.py
from .base_exporter import BaseExporter
from datetime import datetime

class ResultsExporter(BaseExporter):
    """Export daily prediction results to JSON."""

    def generate_json(self, target_date: str) -> dict:
        query = f"""
        SELECT
          player_lookup,
          game_id,
          team_abbr,
          opponent_team_abbr,
          predicted_points,
          actual_points,
          line_value,
          recommendation,
          prediction_correct,
          absolute_error,
          signed_error,
          confidence_score,
          minutes_played
        FROM nba_predictions.prediction_accuracy
        WHERE game_date = '{target_date}'
          AND system_id = 'ensemble_v1'
        ORDER BY ABS(signed_error) DESC
        """
        results = self.query_to_dict(query)

        # Build summary
        total = len(results)
        recommendations = [r for r in results if r['recommendation'] in ('OVER', 'UNDER')]
        correct = sum(1 for r in recommendations if r['prediction_correct'])

        return {
            'game_date': target_date,
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'summary': {
                'total_predictions': total,
                'total_recommendations': len(recommendations),
                'correct': correct,
                'incorrect': len(recommendations) - correct,
                'win_rate': round(correct / len(recommendations), 3) if recommendations else 0,
                'avg_mae': round(sum(r['absolute_error'] for r in results) / total, 2) if total else 0
            },
            'results': [
                {
                    'player_lookup': r['player_lookup'],
                    'game_id': r['game_id'],
                    'team': r['team_abbr'],
                    'opponent': r['opponent_team_abbr'],
                    'predicted': float(r['predicted_points']),
                    'actual': r['actual_points'],
                    'line': float(r['line_value']) if r['line_value'] else None,
                    'recommendation': r['recommendation'],
                    'result': 'WIN' if r['prediction_correct'] else 'LOSS',
                    'error': float(r['absolute_error']),
                    'confidence': float(r['confidence_score']) if r['confidence_score'] else None
                }
                for r in results
            ],
            'highlights': self._get_highlights(results)
        }

    def _get_highlights(self, results: list) -> dict:
        if not results:
            return {}

        # Best prediction (smallest error)
        best = min(results, key=lambda r: r['absolute_error'])
        # Worst prediction (largest error)
        worst = max(results, key=lambda r: r['absolute_error'])

        return {
            'biggest_hit': {
                'player': best['player_lookup'],
                'predicted': float(best['predicted_points']),
                'actual': best['actual_points'],
                'error': float(best['absolute_error'])
            },
            'biggest_miss': {
                'player': worst['player_lookup'],
                'predicted': float(worst['predicted_points']),
                'actual': worst['actual_points'],
                'error': float(worst['absolute_error'])
            }
        }

    def export(self, target_date: str) -> str:
        """Generate and upload results JSON."""
        json_data = self.generate_json(target_date)
        path = f'results/{target_date}.json'
        gcs_path = self.upload_to_gcs(json_data, path, 'public, max-age=86400')

        # Also update latest.json
        self.upload_to_gcs(json_data, 'results/latest.json', 'public, max-age=300')

        return gcs_path
```

### System Performance Exporter (MVP Priority #2)

```python
# data_processors/publishing/system_performance_exporter.py
from .base_exporter import BaseExporter
from datetime import datetime, timedelta

class SystemPerformanceExporter(BaseExporter):
    """Export system performance metrics to JSON."""

    def generate_json(self, as_of_date: str) -> dict:
        # Get rolling windows
        windows = self._get_rolling_windows(as_of_date)

        return {
            'as_of_date': as_of_date,
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'systems': [
                {
                    'system_id': 'ensemble_v1',
                    'display_name': 'Ensemble',
                    'description': 'Weighted combination of all prediction systems',
                    'is_primary': True,
                    'windows': windows.get('ensemble_v1', {}),
                    'ranking': 1
                }
            ]
        }

    def _get_rolling_windows(self, as_of_date: str) -> dict:
        query = f"""
        WITH base AS (
          SELECT
            system_id,
            game_date,
            predictions_count,
            correct_count,
            recommendations_count,
            mae,
            over_win_rate,
            under_win_rate
          FROM nba_predictions.system_daily_performance
          WHERE game_date <= '{as_of_date}'
        )
        SELECT
          system_id,
          -- Last 7 days
          SUM(CASE WHEN game_date > DATE_SUB('{as_of_date}', INTERVAL 7 DAY) THEN predictions_count END) as last_7_predictions,
          ROUND(SAFE_DIVIDE(
            SUM(CASE WHEN game_date > DATE_SUB('{as_of_date}', INTERVAL 7 DAY) THEN correct_count END),
            SUM(CASE WHEN game_date > DATE_SUB('{as_of_date}', INTERVAL 7 DAY) THEN recommendations_count END)
          ), 3) as last_7_win_rate,
          ROUND(AVG(CASE WHEN game_date > DATE_SUB('{as_of_date}', INTERVAL 7 DAY) THEN mae END), 2) as last_7_mae,

          -- Last 30 days
          SUM(CASE WHEN game_date > DATE_SUB('{as_of_date}', INTERVAL 30 DAY) THEN predictions_count END) as last_30_predictions,
          ROUND(SAFE_DIVIDE(
            SUM(CASE WHEN game_date > DATE_SUB('{as_of_date}', INTERVAL 30 DAY) THEN correct_count END),
            SUM(CASE WHEN game_date > DATE_SUB('{as_of_date}', INTERVAL 30 DAY) THEN recommendations_count END)
          ), 3) as last_30_win_rate,
          ROUND(AVG(CASE WHEN game_date > DATE_SUB('{as_of_date}', INTERVAL 30 DAY) THEN mae END), 2) as last_30_mae,

          -- Season
          SUM(predictions_count) as season_predictions,
          ROUND(SAFE_DIVIDE(SUM(correct_count), SUM(recommendations_count)), 3) as season_win_rate,
          ROUND(AVG(mae), 2) as season_mae

        FROM base
        GROUP BY system_id
        """
        results = self.query_to_dict(query)

        return {
            r['system_id']: {
                'last_7_days': {
                    'predictions': r['last_7_predictions'],
                    'win_rate': r['last_7_win_rate'],
                    'mae': r['last_7_mae']
                },
                'last_30_days': {
                    'predictions': r['last_30_predictions'],
                    'win_rate': r['last_30_win_rate'],
                    'mae': r['last_30_mae']
                },
                'season': {
                    'predictions': r['season_predictions'],
                    'win_rate': r['season_win_rate'],
                    'mae': r['season_mae']
                }
            }
            for r in results
        }

    def export(self, as_of_date: str) -> str:
        """Generate and upload system performance JSON."""
        json_data = self.generate_json(as_of_date)
        path = 'systems/performance.json'
        return self.upload_to_gcs(json_data, path, 'public, max-age=3600')
```

---

## Step 4: Create Daily Export Job

```python
# backfill_jobs/publishing/daily_export.py
from data_processors.publishing.results_exporter import ResultsExporter
from data_processors.publishing.system_performance_exporter import SystemPerformanceExporter
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_daily_export(target_date: str = None):
    """Run daily export of prediction results."""
    if target_date is None:
        # Default to yesterday (grading happens overnight)
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    logger.info(f"Starting daily export for {target_date}")

    # Export results
    results_exporter = ResultsExporter()
    results_path = results_exporter.export(target_date)
    logger.info(f"Results exported to: {results_path}")

    # Export system performance
    performance_exporter = SystemPerformanceExporter()
    performance_path = performance_exporter.export(target_date)
    logger.info(f"Performance exported to: {performance_path}")

    logger.info("Daily export complete")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', help='Target date (YYYY-MM-DD)')
    args = parser.parse_args()
    run_daily_export(args.date)
```

---

## Step 5: Backfill Historical Data

```bash
# Backfill all historical dates
PYTHONPATH=. .venv/bin/python -c "
from datetime import datetime, timedelta
from backfill_jobs.publishing.daily_export import run_daily_export

# Get all dates with graded predictions
from google.cloud import bigquery
client = bigquery.Client()
query = '''
SELECT DISTINCT game_date
FROM nba_predictions.prediction_accuracy
ORDER BY game_date
'''
dates = [row['game_date'].strftime('%Y-%m-%d') for row in client.query(query).result()]

print(f'Backfilling {len(dates)} dates...')
for i, date in enumerate(dates):
    print(f'[{i+1}/{len(dates)}] {date}')
    run_daily_export(date)
print('Done!')
"
```

---

## Step 6: Set Up Cloud Scheduler

```bash
# Create Cloud Function for daily export
gcloud functions deploy daily-prediction-export \
  --runtime python310 \
  --trigger-topic daily-export \
  --source ./cloud_functions/daily_export \
  --entry-point main

# Create Cloud Scheduler job (runs at 3 AM daily)
gcloud scheduler jobs create pubsub daily-export-trigger \
  --schedule "0 3 * * *" \
  --topic daily-export \
  --message-body "{}"
```

---

## Testing

### Local Test

```bash
# Export single date
PYTHONPATH=. .venv/bin/python backfill_jobs/publishing/daily_export.py --date 2021-11-10

# Check output
gsutil cat gs://nba-props-platform-api/v1/results/2021-11-10.json | head -50
```

### Verify JSON Format

```bash
# Fetch and validate
curl -s https://storage.googleapis.com/nba-props-platform-api/v1/results/latest.json | jq '.summary'
```

---

## Frontend Integration

The frontend can fetch data like:

```typescript
// React/Next.js example
const API_BASE = 'https://storage.googleapis.com/nba-props-platform-api/v1';

export async function getResults(date: string) {
  const response = await fetch(`${API_BASE}/results/${date}.json`);
  return response.json();
}

export async function getSystemPerformance() {
  const response = await fetch(`${API_BASE}/systems/performance.json`);
  return response.json();
}
```

---

## Open Decisions for Implementer

1. **Display names** - How to convert player_lookup to display name? Options:
   - Include in JSON (requires player table lookup)
   - Let frontend handle it (separate players.json)

2. **Game grouping** - Should results be grouped by game_id?
   - Current: flat list sorted by error
   - Alternative: nested by game

3. **Historical depth** - How many days to keep?
   - Suggestion: Keep all historical JSON (storage is cheap)
   - Set cache-control for old files to 1 day

4. **Error handling** - What if a date has no predictions?
   - Suggestion: Generate empty JSON with summary showing 0 predictions

5. **Incremental vs full** - Should we regenerate all JSON daily?
   - Suggestion: Only regenerate latest.json and current date
   - Historical files are immutable

---

## Related Documents

- `docs/08-projects/current/phase-6-publishing/DESIGN.md` - Full design spec
- `docs/08-projects/current/phase-5c-ml-feedback/STATUS-AND-RECOMMENDATIONS.md` - Phase 5B/5C status

---

**End of Document**
