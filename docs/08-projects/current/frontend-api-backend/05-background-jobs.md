# Background Jobs Specification

**Created:** December 17, 2024
**Purpose:** Define scheduled jobs needed for frontend API backend

---

## Overview

The frontend API backend requires several background jobs to keep data fresh:

| Job | Schedule | Purpose |
|-----|----------|---------|
| Prediction Result Updater | Every 30 min (game nights) | Update predictions with actual results |
| Archetype Classifier | Daily 6 AM ET | Refresh player archetypes |
| Heat Score Calculator | Daily 6 AM ET | Refresh player temperature |
| Bounce-Back Detector | Daily 6 AM ET | Identify bounce-back candidates |
| Trends Exporter | Various | Generate JSON for Trends page |

---

## 1. Prediction Result Updater

### Purpose
After games complete, match predictions to actual results and update the `result_*` fields.

### Schedule
- **When:** Every 30 minutes from 7:00 PM to 2:00 AM ET (game nights)
- **Days:** Tue, Wed, Thu, Fri, Sat, Sun (NBA game days)
- **Cron:** `*/30 19-23,0-2 * * 2-7` (ET)

### Implementation

```python
"""
Prediction Result Updater

Updates pending predictions with actual game results from player_game_summary.
"""

from datetime import date, datetime, timedelta
from typing import Optional
from google.cloud import bigquery

class PredictionResultUpdater:
    """Updates prediction results after games complete."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id

    def process(self, game_date: Optional[date] = None) -> dict:
        """
        Update predictions for a given date with actual results.

        Args:
            game_date: Date to process (defaults to today)

        Returns:
            dict with processing statistics
        """
        if game_date is None:
            game_date = date.today()

        # Get pending predictions
        pending_count = self._get_pending_count(game_date)

        if pending_count == 0:
            return {
                "game_date": str(game_date),
                "pending": 0,
                "updated": 0,
                "status": "no_pending_predictions"
            }

        # Execute update
        updated_count = self._update_results(game_date)

        return {
            "game_date": str(game_date),
            "pending": pending_count,
            "updated": updated_count,
            "status": "success"
        }

    def _get_pending_count(self, game_date: date) -> int:
        """Count pending predictions for date."""
        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{self.project_id}.nba_predictions.player_prop_predictions`
        WHERE game_date = @game_date
          AND result_status = 'pending'
          AND is_active = TRUE
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )
        result = self.client.query(query, job_config=job_config).result()
        return list(result)[0].cnt

    def _update_results(self, game_date: date) -> int:
        """Update predictions with actual results."""
        query = f"""
        UPDATE `{self.project_id}.nba_predictions.player_prop_predictions` pred
        SET
          result_status = 'final',
          actual_value = actual.points,
          result_margin = actual.points - pred.current_points_line,
          result_hit = CASE
            WHEN pred.recommendation = 'OVER' AND actual.points > pred.current_points_line THEN TRUE
            WHEN pred.recommendation = 'UNDER' AND actual.points < pred.current_points_line THEN TRUE
            WHEN pred.recommendation IN ('OVER', 'UNDER') THEN FALSE
            ELSE NULL
          END,
          result_updated_at = CURRENT_TIMESTAMP()
        FROM (
          SELECT
            player_lookup,
            game_date,
            points
          FROM `{self.project_id}.nba_analytics.player_game_summary`
          WHERE game_date = @game_date
            AND points IS NOT NULL
            AND is_active = TRUE
        ) actual
        WHERE pred.player_lookup = actual.player_lookup
          AND pred.game_date = actual.game_date
          AND pred.result_status = 'pending'
          AND pred.is_active = TRUE
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
            ]
        )
        result = self.client.query(query, job_config=job_config).result()
        return result.num_dml_affected_rows

    def backfill(self, start_date: date, end_date: date) -> dict:
        """
        Backfill results for a date range.

        Useful for catching up after outages or for historical data.
        """
        results = []
        current_date = start_date

        while current_date <= end_date:
            result = self.process(current_date)
            results.append(result)
            current_date += timedelta(days=1)

        total_updated = sum(r["updated"] for r in results)
        return {
            "start_date": str(start_date),
            "end_date": str(end_date),
            "days_processed": len(results),
            "total_updated": total_updated
        }


# Cloud Run Job Entry Point
def main():
    """Entry point for Cloud Run Job."""
    import os

    updater = PredictionResultUpdater()

    # Process today and yesterday (catch late games)
    today = date.today()
    yesterday = today - timedelta(days=1)

    results = []
    for d in [yesterday, today]:
        result = updater.process(d)
        results.append(result)
        print(f"Processed {d}: {result}")

    return results


if __name__ == "__main__":
    main()
```

### Cloud Scheduler Configuration

```yaml
# cloud-scheduler/prediction-result-updater.yaml
name: prediction-result-updater
description: Update prediction results after games complete
schedule: "*/30 19-23,0-2 * * 2-7"  # Every 30 min, 7PM-2AM ET, Tue-Sun
time_zone: "America/New_York"
http_target:
  uri: "https://prediction-result-updater-xxxxx.run.app"
  http_method: POST
  headers:
    Content-Type: "application/json"
retry_config:
  retry_count: 3
  min_backoff_duration: "30s"
  max_backoff_duration: "300s"
```

### Monitoring

| Metric | Alert Threshold |
|--------|-----------------|
| Update failures | > 2 consecutive |
| Pending predictions (>24h old) | > 100 |
| Update latency | > 60 seconds |

---

## 2. Daily Archetype Classifier

### Purpose
Refresh player archetype classifications based on recent performance data.

### Schedule
- **When:** 6:00 AM ET daily
- **Cron:** `0 6 * * *` (ET)

### Implementation

This job executes the scheduled query defined in `04-schema-changes.md` Section 3.

```python
"""
Daily Archetype Classifier

Refreshes player_archetypes table with latest classification.
"""

from google.cloud import bigquery

class ArchetypeClassifier:
    """Refreshes player archetype classifications."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id

    def process(self) -> dict:
        """Run archetype classification refresh."""

        # The SQL is defined in schema-changes.md Section 3
        # This triggers the scheduled query or runs it directly

        query = """
        -- Full archetype classification query from schema-changes.md
        -- (See Section 3 for complete SQL)
        """

        job = self.client.query(query)
        result = job.result()

        return {
            "status": "success",
            "rows_affected": result.num_dml_affected_rows
        }
```

### Alternative: BigQuery Scheduled Query

Instead of a Python job, configure this as a BigQuery scheduled query:

1. Go to BigQuery Console > Scheduled Queries
2. Create new query with SQL from Section 3
3. Schedule: Daily at 6:00 AM ET
4. Destination: `nba_analytics.player_archetypes` (MERGE)

---

## 3. Daily Heat Score Calculator

### Purpose
Calculate and refresh heat scores for all players with prop betting history.

### Schedule
- **When:** 6:00 AM ET daily (after archetype classifier)
- **Cron:** `0 6 * * *` (ET)
- **Dependency:** Run after archetype classifier

### Implementation

Execute the scheduled query from `04-schema-changes.md` Section 5.

Recommend using BigQuery Scheduled Queries for this job.

---

## 4. Daily Bounce-Back Detector

### Purpose
Identify players who are bounce-back candidates based on recent underperformance.

### Schedule
- **When:** 6:15 AM ET daily (after heat score)
- **Cron:** `15 6 * * *` (ET)

### Implementation

```python
"""
Bounce-Back Detector

Identifies players due for regression after underperforming.
"""

from datetime import date
from google.cloud import bigquery

class BounceBackDetector:
    """Identifies bounce-back candidates."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.client = bigquery.Client(project=project_id)
        self.project_id = project_id

    def process(self) -> dict:
        """Detect bounce-back candidates for today."""

        query = f"""
        INSERT INTO `{self.project_id}.nba_analytics.bounce_back_candidates`
        WITH recent_games AS (
          SELECT
            player_lookup,
            game_date,
            points,
            points_line,
            over_under_result,
            margin,
            opponent_team_abbr,
            ROW_NUMBER() OVER (
              PARTITION BY player_lookup
              ORDER BY game_date DESC
            ) as game_num
          FROM `{self.project_id}.nba_analytics.player_game_summary`
          WHERE points_line IS NOT NULL
            AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        ),
        last_game AS (
          SELECT *
          FROM recent_games
          WHERE game_num = 1
        ),
        streak_info AS (
          SELECT
            player_lookup,
            SUM(CASE WHEN over_under_result = 'UNDER' THEN 1 ELSE 0 END) as misses_l5,
            -- Count consecutive misses from most recent
            (SELECT COUNT(*)
             FROM recent_games rg2
             WHERE rg2.player_lookup = recent_games.player_lookup
               AND rg2.game_num <= 10
               AND rg2.over_under_result = 'UNDER'
               AND rg2.game_num <= (
                 SELECT MIN(game_num) - 1
                 FROM recent_games rg3
                 WHERE rg3.player_lookup = recent_games.player_lookup
                   AND rg3.over_under_result != 'UNDER'
               )
            ) as consecutive_misses,
            AVG(CASE WHEN over_under_result = 'UNDER' THEN margin END) as avg_miss_margin
          FROM recent_games
          WHERE game_num <= 5
          GROUP BY player_lookup
        ),
        season_baseline AS (
          SELECT
            player_lookup,
            SAFE_DIVIDE(
              SUM(CASE WHEN over_under_result = 'OVER' THEN 1 ELSE 0 END),
              COUNT(*)
            ) as season_hit_rate,
            AVG(points) as season_avg,
            COUNT(*) as season_games
          FROM recent_games
          WHERE game_num <= 30
          GROUP BY player_lookup
        ),
        tonight_schedule AS (
          SELECT
            home_team_tricode as team_abbr,
            away_team_tricode as opponent,
            TRUE as is_home,
            game_status_text as game_time
          FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date = CURRENT_DATE()
          UNION ALL
          SELECT
            away_team_tricode as team_abbr,
            home_team_tricode as opponent,
            FALSE as is_home,
            game_status_text as game_time
          FROM `{self.project_id}.nba_raw.nbac_schedule`
          WHERE game_date = CURRENT_DATE()
        )
        SELECT
          lg.player_lookup,
          CURRENT_DATE() as computed_date,
          'points' as prop_type,
          lg.game_date as last_game_date,
          lg.points as last_game_result,
          lg.points_line as last_game_line,
          lg.margin as last_game_margin,
          lg.opponent_team_abbr as last_game_opponent,
          NULL as last_game_context,  -- TODO: Detect foul trouble, blowout
          COALESCE(si.consecutive_misses, 0) as consecutive_misses,
          si.misses_l5 as misses_of_last_5,
          si.avg_miss_margin,
          sb.season_hit_rate,
          sb.season_avg,
          sb.season_games,
          ts.opponent as tonight_opponent,
          NULL as tonight_opponent_defense_rank,  -- TODO: Join defense rank
          NULL as tonight_line,  -- TODO: Join current prop line
          ts.game_time as tonight_game_time,
          ts.is_home as tonight_home,
          ts.opponent IS NOT NULL as is_playing_tonight,

          -- Signal strength
          CASE
            WHEN COALESCE(si.consecutive_misses, 0) >= 3 THEN 'strong'
            WHEN lg.margin <= -0.4 * lg.points_line AND sb.season_hit_rate >= 0.65 THEN 'strong'
            WHEN COALESCE(si.consecutive_misses, 0) >= 2 AND sb.season_hit_rate >= 0.60 THEN 'moderate'
            WHEN si.misses_l5 >= 3 THEN 'moderate'
            ELSE NULL
          END as signal_strength,

          -- Qualification
          CASE
            WHEN sb.season_hit_rate >= 0.55
              AND (COALESCE(si.consecutive_misses, 0) >= 2 OR si.misses_l5 >= 3)
            THEN TRUE
            WHEN sb.season_hit_rate >= 0.60
              AND lg.margin <= -0.2 * lg.points_line
            THEN TRUE
            ELSE FALSE
          END as is_qualified,

          CASE
            WHEN COALESCE(si.consecutive_misses, 0) >= 2 THEN 'consecutive_misses'
            WHEN si.misses_l5 >= 3 THEN 'misses_of_last_5'
            WHEN lg.margin <= -0.2 * lg.points_line THEN 'significant_miss'
            ELSE 'other'
          END as qualification_reason,

          CURRENT_TIMESTAMP() as computed_at

        FROM last_game lg
        JOIN streak_info si USING (player_lookup)
        JOIN season_baseline sb USING (player_lookup)
        LEFT JOIN (
          SELECT DISTINCT player_lookup, team_abbr
          FROM `{self.project_id}.nba_analytics.player_game_summary`
          WHERE game_date = (SELECT MAX(game_date) FROM `{self.project_id}.nba_analytics.player_game_summary`)
        ) pt USING (player_lookup)
        LEFT JOIN tonight_schedule ts ON pt.team_abbr = ts.team_abbr
        WHERE sb.season_hit_rate >= 0.55
          AND sb.season_games >= 10
          AND (
            COALESCE(si.consecutive_misses, 0) >= 2
            OR si.misses_l5 >= 3
            OR (lg.margin <= -0.2 * lg.points_line AND sb.season_hit_rate >= 0.60)
          )
        """

        job = self.client.query(query)
        result = job.result()

        return {
            "status": "success",
            "candidates_found": result.num_dml_affected_rows,
            "computed_date": str(date.today())
        }
```

---

## 5. Trends Page Exporter

### Purpose
Generate JSON files for each Trends page section and write to Firestore or GCS.

### Schedule

| Section | Schedule | Cron (ET) |
|---------|----------|-----------|
| Who's Hot/Cold | Daily 6:30 AM | `30 6 * * *` |
| Bounce-Back | Daily 6:30 AM | `30 6 * * *` |
| What Matters Most | Monday 6:30 AM | `30 6 * * 1` |
| Team Tendencies | Monday 6:30 AM (bi-weekly) | `30 6 1,15 * *` |
| Quick Hits | Wednesday 8:00 AM | `0 8 * * 3` |

### Implementation

```python
"""
Trends Page Exporter

Generates JSON files for Trends page sections.
"""

import json
from datetime import date, datetime
from typing import Any, Dict, List
from google.cloud import bigquery, firestore

class TrendsExporter:
    """Exports trends data to Firestore."""

    def __init__(self, project_id: str = "nba-props-platform"):
        self.bq_client = bigquery.Client(project=project_id)
        self.fs_client = firestore.Client(project=project_id)
        self.project_id = project_id

    def export_whos_hot(self) -> dict:
        """Export Who's Hot/Cold section."""

        query = f"""
        SELECT
          player_lookup,
          (SELECT player_full_name
           FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
           WHERE pgs.player_lookup = pcf.player_lookup
           LIMIT 1) as player_full_name,
          (SELECT team_abbr
           FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
           WHERE pgs.player_lookup = pcf.player_lookup
           ORDER BY game_date DESC
           LIMIT 1) as team_abbr,
          heat_score,
          temperature,
          hit_rate_l10 as hit_rate,
          games_with_props_l10 as hit_rate_games,
          streak_count as current_streak,
          streak_direction,
          avg_margin_l10 as avg_margin
        FROM `{self.project_id}.nba_analytics.player_current_form` pcf
        WHERE computed_date = (
          SELECT MAX(computed_date)
          FROM `{self.project_id}.nba_analytics.player_current_form`
        )
        ORDER BY heat_score DESC
        """

        result = list(self.bq_client.query(query).result())

        # Top 10 hot, bottom 10 cold
        hot_players = [self._row_to_dict(r) for r in result[:10]]
        cold_players = [self._row_to_dict(r) for r in result[-10:]]

        data = {
            "as_of_date": str(date.today()),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "hot_players": hot_players,
            "cold_players": cold_players
        }

        # Write to Firestore
        doc_ref = self.fs_client.collection("trends").document("whos-hot-v2")
        doc_ref.set(data)

        return {"status": "success", "hot_count": len(hot_players), "cold_count": len(cold_players)}

    def export_bounce_back(self) -> dict:
        """Export Bounce-Back Watch section."""

        query = f"""
        SELECT
          player_lookup,
          (SELECT player_full_name
           FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
           WHERE pgs.player_lookup = bbc.player_lookup
           LIMIT 1) as player_full_name,
          (SELECT team_abbr
           FROM `{self.project_id}.nba_analytics.player_game_summary` pgs
           WHERE pgs.player_lookup = bbc.player_lookup
           ORDER BY game_date DESC
           LIMIT 1) as team_abbr,
          prop_type,
          last_game_date,
          last_game_result,
          last_game_line,
          last_game_margin,
          last_game_opponent,
          last_game_context,
          consecutive_misses,
          misses_of_last_5,
          avg_miss_margin,
          season_hit_rate,
          season_avg,
          tonight_opponent,
          tonight_opponent_defense_rank,
          tonight_line,
          tonight_game_time,
          tonight_home,
          signal_strength
        FROM `{self.project_id}.nba_analytics.bounce_back_candidates` bbc
        WHERE computed_date = CURRENT_DATE()
          AND is_qualified = TRUE
        ORDER BY signal_strength DESC, season_hit_rate DESC
        LIMIT 20
        """

        result = list(self.bq_client.query(query).result())
        candidates = [self._format_bounce_back(r) for r in result]

        data = {
            "as_of_date": str(date.today()),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "candidates": candidates,
            "filters": {
                "min_season_hit_rate": 0.55,
                "min_miss_margin_pct": 0.20,
                "min_consecutive_misses": 2
            }
        }

        doc_ref = self.fs_client.collection("trends").document("bounce-back")
        doc_ref.set(data)

        return {"status": "success", "candidate_count": len(candidates)}

    def export_what_matters(self) -> dict:
        """Export What Matters Most section (archetype-based)."""

        # Rest impact by archetype
        rest_query = f"""
        SELECT
          pa.archetype,
          pa.archetype_label,
          COUNT(DISTINCT pa.player_lookup) as player_count,
          AVG(CASE WHEN pgr.days_rest >= 3 THEN pgs.points END) as with_rest_avg,
          AVG(CASE WHEN pgr.days_rest < 3 THEN pgs.points END) as without_rest_avg,
          AVG(CASE WHEN pgr.days_rest >= 3 THEN pgs.points END) -
            AVG(CASE WHEN pgr.days_rest < 3 THEN pgs.points END) as impact,
          SAFE_DIVIDE(
            SUM(CASE WHEN pgr.days_rest >= 3 AND pgs.over_under_result = 'OVER' THEN 1 ELSE 0 END),
            NULLIF(SUM(CASE WHEN pgr.days_rest >= 3 THEN 1 ELSE 0 END), 0)
          ) as over_rate_with_rest,
          SUM(CASE WHEN pgr.days_rest >= 3 THEN 1 ELSE 0 END) as sample_size
        FROM `{self.project_id}.nba_analytics.player_archetypes` pa
        JOIN `{self.project_id}.nba_analytics.player_game_summary` pgs
          ON pa.player_lookup = pgs.player_lookup
        JOIN `{self.project_id}.nba_analytics.player_game_rest` pgr
          ON pgs.player_lookup = pgr.player_lookup AND pgs.game_date = pgr.game_date
        WHERE pgs.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 365 DAY)
          AND pgs.points_line IS NOT NULL
        GROUP BY pa.archetype, pa.archetype_label
        HAVING COUNT(DISTINCT pa.player_lookup) >= 5
        ORDER BY impact DESC
        """

        rest_result = list(self.bq_client.query(rest_query).result())

        data = {
            "as_of_date": str(date.today()),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "factors": [
                {
                    "factor_id": "rest",
                    "factor_label": "Rest Impact",
                    "factor_icon": "couch",
                    "insight": "Veteran stars benefit most from rest - young legs don't need it as much",
                    "archetypes": [self._format_archetype_factor(r) for r in rest_result]
                }
                # TODO: Add home_away and b2b factors
            ]
        }

        doc_ref = self.fs_client.collection("trends").document("what-matters")
        doc_ref.set(data)

        return {"status": "success"}

    def _row_to_dict(self, row) -> dict:
        """Convert BigQuery row to dict."""
        return dict(row.items())

    def _format_bounce_back(self, row) -> dict:
        """Format bounce-back candidate for JSON."""
        return {
            "player_lookup": row.player_lookup,
            "player_full_name": row.player_full_name,
            "team_abbr": row.team_abbr,
            "prop_type": row.prop_type,
            "last_game": {
                "result": float(row.last_game_result) if row.last_game_result else None,
                "line": float(row.last_game_line) if row.last_game_line else None,
                "margin": float(row.last_game_margin) if row.last_game_margin else None,
                "opponent": row.last_game_opponent,
                "context": row.last_game_context
            },
            "streak": {
                "consecutive_misses": row.consecutive_misses,
                "avg_miss_margin": float(row.avg_miss_margin) if row.avg_miss_margin else None
            },
            "baseline": {
                "season_hit_rate": float(row.season_hit_rate) if row.season_hit_rate else None,
                "season_avg": float(row.season_avg) if row.season_avg else None
            },
            "tonight": {
                "opponent": row.tonight_opponent,
                "opp_defense_rank": row.tonight_opponent_defense_rank,
                "current_line": float(row.tonight_line) if row.tonight_line else None,
                "game_time": row.tonight_game_time,
                "home": row.tonight_home
            } if row.tonight_opponent else None,
            "signal_strength": row.signal_strength
        }

    def _format_archetype_factor(self, row) -> dict:
        """Format archetype factor for JSON."""
        return {
            "archetype": row.archetype,
            "archetype_label": row.archetype_label,
            "player_count": row.player_count,
            "with_factor_avg": float(row.with_rest_avg) if row.with_rest_avg else None,
            "without_factor_avg": float(row.without_rest_avg) if row.without_rest_avg else None,
            "impact": float(row.impact) if row.impact else None,
            "over_rate": float(row.over_rate_with_rest) if row.over_rate_with_rest else None,
            "sample_size": row.sample_size
        }
```

---

## Job Dependencies

```
6:00 AM  [archetype_classifier] ────┐
                                    │
6:00 AM  [heat_score_calculator] ───┼──> 6:30 AM [whos_hot_exporter]
                                    │
6:15 AM  [bounce_back_detector] ────┴──> 6:30 AM [bounce_back_exporter]

7:00 PM - 2:00 AM [prediction_result_updater] (every 30 min)
```

---

## Error Handling

All jobs should implement:

1. **Retry Logic**: 3 retries with exponential backoff
2. **Dead Letter Queue**: Failed jobs logged to separate table
3. **Alerting**: PagerDuty/Slack notification on consecutive failures
4. **Idempotency**: Safe to re-run without duplicate data

```python
# Example retry decorator
from functools import wraps
import time

def retry_with_backoff(retries=3, backoff_factor=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    wait_time = backoff_factor ** attempt
                    print(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
            raise last_exception
        return wrapper
    return decorator
```

---

## Monitoring Queries

```sql
-- Check prediction result update coverage
SELECT
  game_date,
  COUNT(*) as total_predictions,
  COUNTIF(result_status = 'final') as with_results,
  COUNTIF(result_status = 'pending') as pending,
  ROUND(COUNTIF(result_status = 'final') * 100.0 / COUNT(*), 1) as coverage_pct
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY game_date
ORDER BY game_date DESC;

-- Check archetype freshness
SELECT
  MAX(computed_at) as last_refresh,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(computed_at), HOUR) as hours_stale,
  COUNT(*) as player_count
FROM `nba-props-platform.nba_analytics.player_archetypes`
WHERE season = '2024-25';

-- Check heat score freshness
SELECT
  MAX(computed_date) as last_refresh,
  DATE_DIFF(CURRENT_DATE(), MAX(computed_date), DAY) as days_stale,
  COUNT(*) as player_count
FROM `nba-props-platform.nba_analytics.player_current_form`;
```
