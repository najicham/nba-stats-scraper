# Defense in Depth - Additional Robustness Improvements

**Created:** 2026-01-25
**Purpose:** Edge case handling and long-term operational robustness
**Complements:** MASTER-IMPROVEMENT-PLAN.md, ADDITIONAL-RECOMMENDATIONS-V2.md

---

## Overview

This document covers "defense in depth" improvements that make the system more robust for edge cases, long-term operation, and unexpected scenarios. These complement the core validation improvements.

**Categories:**
1. Prediction Quality Monitoring
2. Data Freshness & Staleness
3. Message Processing Reliability
4. Cold Start & Edge Cases
5. Data Quality & Resolution
6. Infrastructure Resilience
7. Capacity & Cost Management

---

## 1. Prediction Quality Monitoring

### 1.1 Model Drift Detection

**Priority:** P1
**Gap:** No monitoring for whether the prediction model is degrading over time.

**Why It Matters:**
- Model could become less accurate without anyone noticing
- External factors (rule changes, play style shifts) affect predictions
- Need to know when to retrain

**Implementation:**

```python
# validation/validators/predictions/model_drift_validator.py
"""Detect prediction model drift over time."""

from datetime import date, timedelta
from typing import Dict, List
import statistics

class ModelDriftValidator:
    """Monitor prediction accuracy trends for model drift."""

    # Alert thresholds
    ACCURACY_DROP_WARNING = 0.05  # 5% drop from baseline
    ACCURACY_DROP_ERROR = 0.10   # 10% drop from baseline

    def check_model_drift(self, lookback_days: int = 30) -> Dict:
        """
        Compare recent accuracy to historical baseline.

        Returns drift metrics and alerts.
        """
        results = {
            "status": "healthy",
            "metrics": {},
            "alerts": []
        }

        # Get accuracy by week
        query = """
        SELECT
            DATE_TRUNC(game_date, WEEK) as week,
            AVG(CAST(prediction_correct AS FLOAT64)) as accuracy,
            COUNT(*) as predictions
        FROM `nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        AND NOT is_voided
        GROUP BY 1
        ORDER BY 1
        """

        weekly_accuracy = self._run_query(query, {"days": lookback_days})

        if len(weekly_accuracy) < 3:
            results["status"] = "insufficient_data"
            return results

        # Calculate baseline (first half) vs recent (second half)
        midpoint = len(weekly_accuracy) // 2
        baseline_weeks = weekly_accuracy[:midpoint]
        recent_weeks = weekly_accuracy[midpoint:]

        baseline_accuracy = statistics.mean([w.accuracy for w in baseline_weeks])
        recent_accuracy = statistics.mean([w.accuracy for w in recent_weeks])

        drift = baseline_accuracy - recent_accuracy
        drift_pct = drift / baseline_accuracy if baseline_accuracy > 0 else 0

        results["metrics"] = {
            "baseline_accuracy": baseline_accuracy,
            "recent_accuracy": recent_accuracy,
            "drift": drift,
            "drift_pct": drift_pct,
            "weeks_analyzed": len(weekly_accuracy)
        }

        # Check thresholds
        if drift_pct >= self.ACCURACY_DROP_ERROR:
            results["status"] = "error"
            results["alerts"].append({
                "severity": "error",
                "message": f"Model accuracy dropped {drift_pct:.1%} from baseline "
                          f"({baseline_accuracy:.1%} → {recent_accuracy:.1%})"
            })
        elif drift_pct >= self.ACCURACY_DROP_WARNING:
            results["status"] = "warning"
            results["alerts"].append({
                "severity": "warning",
                "message": f"Model accuracy trending down {drift_pct:.1%}"
            })

        return results

    def check_accuracy_by_prop_type(self, days: int = 14) -> Dict:
        """Check if certain prop types are underperforming."""

        query = """
        SELECT
            prop_type,
            AVG(CAST(prediction_correct AS FLOAT64)) as accuracy,
            COUNT(*) as predictions
        FROM `nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        AND NOT is_voided
        GROUP BY 1
        HAVING predictions >= 100
        ORDER BY accuracy ASC
        """

        by_prop = self._run_query(query, {"days": days})

        underperformers = []
        for prop in by_prop:
            if prop.accuracy < 0.45:  # Below 45% is concerning
                underperformers.append({
                    "prop_type": prop.prop_type,
                    "accuracy": prop.accuracy,
                    "predictions": prop.predictions
                })

        return {
            "by_prop_type": [dict(p._asdict()) for p in by_prop],
            "underperformers": underperformers
        }
```

---

### 1.2 Confidence Calibration Check

**Priority:** P1
**Gap:** Confidence scores might not reflect actual probability of being correct.

**Why It Matters:**
- If 80% confidence predictions are only right 50% of the time, confidence is meaningless
- Users/systems rely on confidence for decision-making

**Implementation:**

```python
# validation/validators/predictions/confidence_calibration_validator.py
"""Validate that confidence scores are well-calibrated."""

class ConfidenceCalibrationValidator:
    """Check if confidence scores match actual accuracy."""

    def check_calibration(self, days: int = 30) -> Dict:
        """
        Compare confidence deciles to actual accuracy.

        Well-calibrated: decile 10 should be ~90% accurate,
        decile 5 should be ~50% accurate, etc.
        """

        query = """
        SELECT
            confidence_decile,
            AVG(CAST(prediction_correct AS FLOAT64)) as actual_accuracy,
            COUNT(*) as predictions,
            AVG(confidence_score) as avg_confidence
        FROM `nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        AND NOT is_voided
        AND confidence_decile IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """

        calibration = self._run_query(query, {"days": days})

        results = {
            "calibration_data": [],
            "calibration_error": 0,
            "is_calibrated": True,
            "issues": []
        }

        total_error = 0
        for row in calibration:
            expected_accuracy = row.avg_confidence
            actual_accuracy = row.actual_accuracy
            error = abs(expected_accuracy - actual_accuracy)
            total_error += error

            results["calibration_data"].append({
                "decile": row.confidence_decile,
                "expected": expected_accuracy,
                "actual": actual_accuracy,
                "error": error,
                "predictions": row.predictions
            })

            # Flag large calibration errors
            if error > 0.15:  # More than 15% off
                results["issues"].append(
                    f"Decile {row.confidence_decile}: expected {expected_accuracy:.1%}, "
                    f"actual {actual_accuracy:.1%} (error: {error:.1%})"
                )

        results["calibration_error"] = total_error / len(calibration) if calibration else 0
        results["is_calibrated"] = results["calibration_error"] < 0.10

        return results

    def check_overconfidence(self, days: int = 14) -> Dict:
        """Check if high-confidence predictions are actually accurate."""

        query = """
        SELECT
            CASE
                WHEN confidence_score >= 0.8 THEN 'very_high (80%+)'
                WHEN confidence_score >= 0.7 THEN 'high (70-80%)'
                WHEN confidence_score >= 0.6 THEN 'medium (60-70%)'
                ELSE 'low (<60%)'
            END as confidence_band,
            AVG(CAST(prediction_correct AS FLOAT64)) as accuracy,
            COUNT(*) as predictions
        FROM `nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL @days DAY)
        AND NOT is_voided
        GROUP BY 1
        ORDER BY 1
        """

        bands = self._run_query(query, {"days": days})

        overconfident = False
        for band in bands:
            if 'very_high' in band.confidence_band and band.accuracy < 0.70:
                overconfident = True

        return {
            "confidence_bands": [dict(b._asdict()) for b in bands],
            "is_overconfident": overconfident
        }
```

---

### 1.3 Prediction Distribution Monitoring

**Priority:** P2
**Gap:** All predictions going OVER or UNDER would indicate a bug.

**Implementation:**

```python
def check_prediction_distribution(game_date: str) -> Dict:
    """Verify predictions are reasonably distributed."""

    query = """
    SELECT
        recommendation,
        COUNT(*) as count,
        COUNT(*) * 100.0 / SUM(COUNT(*)) OVER() as pct
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = @game_date
    GROUP BY 1
    """

    distribution = run_query(query, {"game_date": game_date})

    # Should be roughly balanced (40-60% split is normal)
    issues = []
    for row in distribution:
        if row.pct > 70:
            issues.append(f"{row.recommendation} is {row.pct:.1f}% of predictions (expected 40-60%)")

    return {
        "distribution": [dict(d._asdict()) for d in distribution],
        "is_balanced": len(issues) == 0,
        "issues": issues
    }
```

---

## 2. Data Freshness & Staleness

### 2.1 Odds/Lines Staleness Detection

**Priority:** P1
**Gap:** Using stale betting lines invalidates predictions.

**Implementation:**

```python
# validation/validators/raw/odds_staleness_validator.py
"""Detect stale betting lines."""

class OddsStalenessValidator:
    """Validate betting lines are fresh before predictions."""

    MAX_LINE_AGE_HOURS = 6  # Lines older than 6h before game are stale

    def check_lines_freshness(self, game_date: str) -> Dict:
        """Check if betting lines are fresh enough for predictions."""

        query = """
        SELECT
            p.game_id,
            s.home_team,
            s.away_team,
            s.game_time_et,
            MAX(p.scraped_at) as latest_line_time,
            TIMESTAMP_DIFF(s.game_time_et, MAX(p.scraped_at), HOUR) as hours_before_game
        FROM `nba_raw.odds_api_props` p
        JOIN `nba_raw.v_nbac_schedule_latest` s
            ON p.game_id = s.game_id
        WHERE p.game_date = @game_date
        GROUP BY 1, 2, 3, 4
        """

        games = self._run_query(query, {"game_date": game_date})

        stale_games = []
        for game in games:
            if game.hours_before_game and game.hours_before_game > self.MAX_LINE_AGE_HOURS:
                stale_games.append({
                    "game_id": game.game_id,
                    "matchup": f"{game.away_team} @ {game.home_team}",
                    "line_age_hours": game.hours_before_game,
                    "latest_line": game.latest_line_time.isoformat() if game.latest_line_time else None
                })

        return {
            "total_games": len(games),
            "stale_games": len(stale_games),
            "stale_details": stale_games,
            "status": "error" if stale_games else "healthy"
        }

    def check_missing_lines(self, game_date: str) -> Dict:
        """Check for games with no betting lines at all."""

        query = """
        SELECT
            s.game_id,
            s.home_team,
            s.away_team,
            s.game_time_et
        FROM `nba_raw.v_nbac_schedule_latest` s
        LEFT JOIN (
            SELECT DISTINCT game_id
            FROM `nba_raw.odds_api_props`
            WHERE game_date = @game_date
        ) p ON s.game_id = p.game_id
        WHERE s.game_date = @game_date
        AND s.game_status NOT IN ('Postponed', 'Cancelled')
        AND p.game_id IS NULL
        """

        missing = self._run_query(query, {"game_date": game_date})

        return {
            "games_missing_lines": len(missing),
            "missing_details": [
                {"game_id": m.game_id, "matchup": f"{m.away_team} @ {m.home_team}"}
                for m in missing
            ]
        }
```

---

### 2.2 Source Data Lag Detection

**Priority:** P2
**Gap:** Detecting when source APIs are delayed.

**Implementation:**

```python
def check_source_data_lag(game_date: str) -> Dict:
    """Check if source data is arriving on time."""

    # Expected: boxscores within 30 min of game end
    query = """
    SELECT
        s.game_id,
        s.game_status,
        s.game_time_et,
        MIN(b.created_at) as first_boxscore_time,
        TIMESTAMP_DIFF(MIN(b.created_at), s.game_time_et, MINUTE) as minutes_after_start
    FROM `nba_raw.v_nbac_schedule_latest` s
    LEFT JOIN `nba_raw.bdl_player_boxscores` b
        ON s.game_id = b.game_id
    WHERE s.game_date = @game_date
    AND s.game_status = 'Final'
    GROUP BY 1, 2, 3
    """

    games = run_query(query, {"game_date": game_date})

    delayed = []
    for game in games:
        # Game is ~2.5 hours, so boxscore should arrive ~180 min after start
        expected_arrival = 180  # minutes after game start
        if game.minutes_after_start and game.minutes_after_start > expected_arrival + 60:
            delayed.append({
                "game_id": game.game_id,
                "delay_minutes": game.minutes_after_start - expected_arrival
            })

    return {
        "delayed_games": len(delayed),
        "details": delayed
    }
```

---

## 3. Message Processing Reliability

### 3.1 Pub/Sub Idempotency

**Priority:** P1
**Gap:** Pub/Sub delivers at-least-once; same message could be processed multiple times.

**Implementation:**

```python
# shared/utils/idempotency.py
"""Idempotent message processing."""

from google.cloud import bigquery
from datetime import datetime, timedelta
import hashlib

class IdempotencyChecker:
    """Ensure messages are only processed once."""

    TABLE = "nba_orchestration.processed_messages"

    def __init__(self):
        self.bq_client = bigquery.Client()

    def get_idempotency_key(self, message_data: dict) -> str:
        """Generate unique key for a message."""
        # Create deterministic hash of message content
        content = str(sorted(message_data.items()))
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def is_already_processed(self, idempotency_key: str) -> bool:
        """Check if message was already processed."""
        query = f"""
        SELECT 1 FROM `{self.TABLE}`
        WHERE idempotency_key = @key
        AND processed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        LIMIT 1
        """

        result = list(self.bq_client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("key", "STRING", idempotency_key)
                ]
            )
        ).result())

        return len(result) > 0

    def mark_as_processed(self, idempotency_key: str, processor: str, message_id: str = None):
        """Record that message was processed."""
        query = f"""
        INSERT INTO `{self.TABLE}`
        (idempotency_key, processor, message_id, processed_at)
        VALUES (@key, @processor, @message_id, CURRENT_TIMESTAMP())
        """

        self.bq_client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("key", "STRING", idempotency_key),
                    bigquery.ScalarQueryParameter("processor", "STRING", processor),
                    bigquery.ScalarQueryParameter("message_id", "STRING", message_id),
                ]
            )
        ).result()

    def process_idempotently(self, message_data: dict, processor_name: str, process_func):
        """
        Process message only if not already processed.

        Usage:
            checker = IdempotencyChecker()
            result = checker.process_idempotently(
                message_data={"game_id": "123", "date": "2026-01-25"},
                processor_name="boxscore_processor",
                process_func=lambda: process_boxscore(message_data)
            )
        """
        key = self.get_idempotency_key(message_data)

        if self.is_already_processed(key):
            logger.info(f"Message already processed (key={key}), skipping")
            return {"status": "skipped", "reason": "duplicate"}

        # Process the message
        result = process_func()

        # Mark as processed
        self.mark_as_processed(key, processor_name)

        return result


# Table schema
"""
CREATE TABLE IF NOT EXISTS `nba_orchestration.processed_messages` (
    idempotency_key STRING NOT NULL,
    processor STRING NOT NULL,
    message_id STRING,
    processed_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(processed_at)
OPTIONS (
    partition_expiration_days = 7  -- Auto-cleanup after 7 days
);
"""
```

---

### 3.2 Message Processing Metrics

**Priority:** P2
**Gap:** No visibility into message processing health.

**Implementation:**

```python
def get_message_processing_metrics(hours: int = 24) -> Dict:
    """Get metrics on message processing."""

    query = """
    SELECT
        processor,
        COUNT(*) as total_messages,
        COUNTIF(status = 'success') as successful,
        COUNTIF(status = 'failed') as failed,
        COUNTIF(status = 'skipped') as skipped_duplicates,
        AVG(processing_time_ms) as avg_processing_ms
    FROM `nba_orchestration.message_processing_log`
    WHERE processed_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
    GROUP BY 1
    """

    return run_query(query, {"hours": hours})
```

---

## 4. Cold Start & Edge Cases

### 4.1 New Season Handling

**Priority:** P2
**Gap:** Season start has no historical data for rolling windows.

**Implementation:**

```python
# validation/validators/precompute/cold_start_validator.py
"""Handle cold start scenarios for new seasons/players."""

class ColdStartValidator:
    """Identify and handle cold start scenarios."""

    MIN_GAMES_FOR_FEATURES = 5
    MIN_GAMES_FOR_PREDICTIONS = 10

    def check_cold_start_players(self, game_date: str) -> Dict:
        """Find players with insufficient history."""

        query = """
        WITH player_history AS (
            SELECT
                player_lookup,
                player_name,
                COUNT(DISTINCT game_date) as games_played
            FROM `nba_analytics.player_game_summary`
            WHERE game_date < @game_date
            AND season_year = EXTRACT(YEAR FROM DATE(@game_date))
            GROUP BY 1, 2
        ),
        todays_players AS (
            SELECT DISTINCT player_lookup, player_name
            FROM `nba_raw.bdl_player_boxscores`
            WHERE game_date = @game_date
        )
        SELECT
            t.player_lookup,
            t.player_name,
            COALESCE(h.games_played, 0) as games_played,
            CASE
                WHEN COALESCE(h.games_played, 0) < @min_features THEN 'insufficient_for_features'
                WHEN COALESCE(h.games_played, 0) < @min_predictions THEN 'insufficient_for_predictions'
                ELSE 'sufficient'
            END as status
        FROM todays_players t
        LEFT JOIN player_history h USING (player_lookup)
        WHERE COALESCE(h.games_played, 0) < @min_predictions
        ORDER BY games_played ASC
        """

        cold_start_players = self._run_query(query, {
            "game_date": game_date,
            "min_features": self.MIN_GAMES_FOR_FEATURES,
            "min_predictions": self.MIN_GAMES_FOR_PREDICTIONS
        })

        return {
            "cold_start_players": len(cold_start_players),
            "insufficient_for_features": len([p for p in cold_start_players if p.status == 'insufficient_for_features']),
            "insufficient_for_predictions": len([p for p in cold_start_players if p.status == 'insufficient_for_predictions']),
            "players": [
                {
                    "player": p.player_name,
                    "games": p.games_played,
                    "status": p.status
                }
                for p in cold_start_players[:20]  # Top 20
            ]
        }

    def check_season_start(self, game_date: str) -> Dict:
        """Check if we're in early season with limited data."""

        query = """
        SELECT
            MIN(game_date) as season_start,
            DATE_DIFF(DATE(@game_date), MIN(game_date), DAY) as days_into_season,
            COUNT(DISTINCT game_date) as games_played
        FROM `nba_raw.v_nbac_schedule_latest`
        WHERE season_year = EXTRACT(YEAR FROM DATE(@game_date))
        AND game_status = 'Final'
        """

        result = self._run_query(query, {"game_date": game_date})

        if result:
            row = result[0]
            is_early_season = row.days_into_season < 30 if row.days_into_season else True

            return {
                "season_start": row.season_start.isoformat() if row.season_start else None,
                "days_into_season": row.days_into_season,
                "games_completed": row.games_played,
                "is_early_season": is_early_season,
                "recommendation": "Use conservative confidence scores" if is_early_season else None
            }

        return {"is_early_season": True, "recommendation": "Insufficient data"}
```

---

### 4.2 Roster Change Detection

**Priority:** P2
**Gap:** Trades, injuries, and roster changes affect predictions.

**Implementation:**

```python
def detect_roster_changes(game_date: str, lookback_days: int = 7) -> Dict:
    """Detect recent roster changes that might affect predictions."""

    # New players (first appearance in last N days)
    query_new = """
    SELECT
        player_lookup,
        player_name,
        team_abbreviation,
        MIN(game_date) as first_appearance
    FROM `nba_raw.bdl_player_boxscores`
    WHERE game_date BETWEEN DATE_SUB(@game_date, INTERVAL @days DAY) AND @game_date
    GROUP BY 1, 2, 3
    HAVING first_appearance >= DATE_SUB(@game_date, INTERVAL @days DAY)
    """

    new_players = run_query(query_new, {"game_date": game_date, "days": lookback_days})

    # Players who changed teams
    query_trades = """
    WITH recent_games AS (
        SELECT
            player_lookup,
            player_name,
            team_abbreviation,
            game_date,
            LAG(team_abbreviation) OVER (
                PARTITION BY player_lookup
                ORDER BY game_date
            ) as prev_team
        FROM `nba_raw.bdl_player_boxscores`
        WHERE game_date BETWEEN DATE_SUB(@game_date, INTERVAL @days DAY) AND @game_date
    )
    SELECT DISTINCT
        player_lookup,
        player_name,
        prev_team,
        team_abbreviation as new_team,
        game_date as trade_date
    FROM recent_games
    WHERE prev_team IS NOT NULL
    AND prev_team != team_abbreviation
    """

    trades = run_query(query_trades, {"game_date": game_date, "days": lookback_days})

    return {
        "new_players": [
            {"name": p.player_name, "team": p.team_abbreviation}
            for p in new_players
        ],
        "traded_players": [
            {"name": t.player_name, "from": t.prev_team, "to": t.new_team}
            for t in trades
        ],
        "has_changes": len(new_players) > 0 or len(trades) > 0
    }
```

---

## 5. Data Quality & Resolution

### 5.1 Player Name Resolution Quality

**Priority:** P2
**Gap:** Name mismatches between sources cause lost coverage.

**Implementation:**

```python
# validation/validators/raw/name_resolution_validator.py
"""Validate player name resolution across sources."""

class NameResolutionValidator:
    """Check for player name resolution failures."""

    def check_unresolved_players(self, game_date: str) -> Dict:
        """Find players that exist in one source but not another."""

        # Players in boxscores but not in props
        query_boxscore_only = """
        SELECT DISTINCT
            b.player_name as boxscore_name,
            b.player_lookup,
            b.team_abbreviation
        FROM `nba_raw.bdl_player_boxscores` b
        LEFT JOIN `nba_raw.odds_api_props` p
            ON b.player_lookup = p.player_lookup
            AND b.game_date = p.game_date
        WHERE b.game_date = @game_date
        AND p.player_lookup IS NULL
        AND b.minutes > 10  -- Only players who actually played
        """

        boxscore_only = self._run_query(query_boxscore_only, {"game_date": game_date})

        # Players in props but not matched to boxscore
        query_props_only = """
        SELECT DISTINCT
            p.player_name as props_name,
            p.player_lookup
        FROM `nba_raw.odds_api_props` p
        LEFT JOIN `nba_raw.bdl_player_boxscores` b
            ON p.player_lookup = b.player_lookup
            AND p.game_date = b.game_date
        WHERE p.game_date = @game_date
        AND b.player_lookup IS NULL
        """

        props_only = self._run_query(query_props_only, {"game_date": game_date})

        return {
            "in_boxscore_not_props": len(boxscore_only),
            "in_props_not_boxscore": len(props_only),
            "boxscore_only_players": [
                {"name": p.boxscore_name, "team": p.team_abbreviation}
                for p in boxscore_only[:10]
            ],
            "props_only_players": [
                {"name": p.props_name}
                for p in props_only[:10]
            ],
            "potential_lost_coverage": len(props_only)  # Props we can't grade
        }

    def check_name_variations(self) -> Dict:
        """Find potential duplicate players with different name formats."""

        query = """
        SELECT
            a.player_name as name_a,
            b.player_name as name_b,
            a.player_lookup as lookup_a,
            b.player_lookup as lookup_b
        FROM (
            SELECT DISTINCT player_name, player_lookup
            FROM `nba_raw.bdl_player_boxscores`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        ) a
        JOIN (
            SELECT DISTINCT player_name, player_lookup
            FROM `nba_raw.bdl_player_boxscores`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        ) b
        ON a.player_lookup != b.player_lookup
        AND (
            -- Same last name, similar first name
            SPLIT(a.player_name, ' ')[SAFE_OFFSET(1)] = SPLIT(b.player_name, ' ')[SAFE_OFFSET(1)]
            AND SUBSTR(a.player_name, 1, 1) = SUBSTR(b.player_name, 1, 1)
        )
        LIMIT 50
        """

        potential_dupes = self._run_query(query)

        return {
            "potential_duplicates": [
                {"name_a": d.name_a, "name_b": d.name_b}
                for d in potential_dupes
            ]
        }
```

---

### 5.2 Data Consistency Checks

**Priority:** P2
**Gap:** Impossible values that slip through (negative points, etc.)

**Implementation:**

```python
def check_impossible_values(game_date: str) -> Dict:
    """Find statistically impossible values in boxscores."""

    checks = [
        {
            "name": "negative_stats",
            "query": """
                SELECT player_name, 'negative points' as issue, points as value
                FROM `nba_raw.bdl_player_boxscores`
                WHERE game_date = @game_date AND points < 0
                UNION ALL
                SELECT player_name, 'negative rebounds', rebounds
                FROM `nba_raw.bdl_player_boxscores`
                WHERE game_date = @game_date AND rebounds < 0
                UNION ALL
                SELECT player_name, 'negative assists', assists
                FROM `nba_raw.bdl_player_boxscores`
                WHERE game_date = @game_date AND assists < 0
            """
        },
        {
            "name": "impossible_shooting",
            "query": """
                SELECT player_name, 'FGM > FGA' as issue, fg_made as value
                FROM `nba_raw.bdl_player_boxscores`
                WHERE game_date = @game_date AND fg_made > fg_attempted
                UNION ALL
                SELECT player_name, '3PM > 3PA', fg3_made
                FROM `nba_raw.bdl_player_boxscores`
                WHERE game_date = @game_date AND fg3_made > fg3_attempted
                UNION ALL
                SELECT player_name, 'FTM > FTA', ft_made
                FROM `nba_raw.bdl_player_boxscores`
                WHERE game_date = @game_date AND ft_made > ft_attempted
            """
        },
        {
            "name": "impossible_minutes",
            "query": """
                SELECT player_name, 'minutes > 60' as issue, minutes as value
                FROM `nba_raw.bdl_player_boxscores`
                WHERE game_date = @game_date AND minutes > 60
                UNION ALL
                SELECT player_name, 'minutes < 0', minutes
                FROM `nba_raw.bdl_player_boxscores`
                WHERE game_date = @game_date AND minutes < 0
            """
        }
    ]

    all_issues = []
    for check in checks:
        results = run_query(check["query"], {"game_date": game_date})
        all_issues.extend([
            {"player": r.player_name, "issue": r.issue, "value": r.value}
            for r in results
        ])

    return {
        "impossible_values_found": len(all_issues),
        "issues": all_issues,
        "status": "error" if all_issues else "healthy"
    }
```

---

## 6. Infrastructure Resilience

### 6.1 Graceful Degradation Strategy

**Priority:** P2
**Gap:** No defined behavior when components fail.

**Documentation:**

```markdown
## Graceful Degradation Matrix

| Component Failed | Impact | Automatic Response | Manual Intervention |
|-----------------|--------|-------------------|---------------------|
| **BDL API** | No boxscores | Retry 3x, then NBA.com fallback | Alert if both fail |
| **Odds API** | No prop lines | Skip predictions for affected games | Monitor, usually temporary |
| **BigQuery** | Everything broken | Fail loudly, no degradation possible | Page on-call immediately |
| **Feature Store Read** | No predictions | Use cached features if <6h old | Rebuild features |
| **Feature Store Write** | Features not saved | Queue for retry, proceed with predictions | Check disk space |
| **Prediction Model** | No predictions | Use baseline model (50% confidence) | Investigate model health |
| **Grading** | Delayed accuracy | Queue for later, no user impact | Will auto-resolve |
| **Slack/PagerDuty** | No alerts | Log to BigQuery, secondary email | Check integration |

## Fallback Chain

```
Primary Source → Secondary Source → Cached Data → Baseline/Skip
```

### Example: Boxscore Fallback
```python
def get_boxscore_with_fallback(game_id: str, game_date: str):
    # Try BDL (fast, reliable)
    try:
        return fetch_bdl_boxscore(game_id)
    except BDLError:
        logger.warning(f"BDL failed for {game_id}, trying NBA.com")

    # Try NBA.com (slower, rate limited)
    try:
        return fetch_nba_com_boxscore(game_id)
    except NBAComError:
        logger.warning(f"NBA.com failed for {game_id}, trying cache")

    # Try cache (might be stale)
    cached = get_cached_boxscore(game_id)
    if cached and cached.age_hours < 24:
        logger.warning(f"Using cached boxscore for {game_id} (age: {cached.age_hours}h)")
        return cached.data

    # All sources failed
    logger.error(f"All boxscore sources failed for {game_id}")
    raise AllSourcesFailedError(game_id)
```
```

---

### 6.2 API Rate Limit Monitoring

**Priority:** P2
**Gap:** Rate limit hits not tracked or monitored.

**Implementation:**

```python
# shared/utils/rate_limit_monitor.py
"""Track and monitor API rate limit events."""

def log_rate_limit_event(
    source: str,
    endpoint: str,
    retry_after: int = None,
    response_code: int = 429
):
    """Log rate limit event to BigQuery for monitoring."""

    query = """
    INSERT INTO `nba_orchestration.rate_limit_events`
    (source, endpoint, response_code, retry_after_seconds, occurred_at)
    VALUES (@source, @endpoint, @code, @retry, CURRENT_TIMESTAMP())
    """

    run_query(query, {
        "source": source,
        "endpoint": endpoint,
        "code": response_code,
        "retry": retry_after
    })


def get_rate_limit_summary(hours: int = 24) -> Dict:
    """Get summary of rate limit events."""

    query = """
    SELECT
        source,
        COUNT(*) as events,
        MAX(occurred_at) as last_event,
        AVG(retry_after_seconds) as avg_retry_seconds
    FROM `nba_orchestration.rate_limit_events`
    WHERE occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @hours HOUR)
    GROUP BY 1
    ORDER BY events DESC
    """

    return run_query(query, {"hours": hours})


# Table schema
"""
CREATE TABLE IF NOT EXISTS `nba_orchestration.rate_limit_events` (
    source STRING,
    endpoint STRING,
    response_code INT64,
    retry_after_seconds INT64,
    occurred_at TIMESTAMP
)
PARTITION BY DATE(occurred_at);
"""
```

---

## 7. Capacity & Cost Management

### 7.1 Playoff Capacity Planning

**Priority:** P2
**Gap:** System might not scale for playoff volume.

**Checklist:**

```markdown
## Pre-Playoff Capacity Checklist

### Load Estimation
- Regular season: ~12 games/day, ~300 predictions/day
- Playoffs Round 1: Up to 8 games/day, ~200 predictions/day
- Finals: 1 game but 10x betting volume, more prop types

### BigQuery
- [ ] Check slot usage at peak times
- [ ] Consider reserved slots for predictable cost
- [ ] Verify partition pruning is working
- [ ] Test query performance with 2x data

### Cloud Functions
- [ ] Review memory limits (currently 256MB?)
- [ ] Check concurrent execution limits
- [ ] Test cold start times
- [ ] Consider min instances for critical functions

### Cloud Run
- [ ] Review CPU/memory allocation
- [ ] Check autoscaling settings
- [ ] Verify request timeout settings
- [ ] Test with load generator

### Pub/Sub
- [ ] Check subscription backlog during peak
- [ ] Verify ack deadline is appropriate
- [ ] Test DLQ is working

### Monitoring
- [ ] Create playoff-specific dashboard
- [ ] Set up capacity alerts (80% of limits)
- [ ] Verify alerting works at high volume
```

**Load Test Script:**

```python
# bin/testing/load_test_predictions.py
"""Simulate playoff load for capacity testing."""

import concurrent.futures
from datetime import date

def simulate_playoff_load(games_per_day: int = 8, predictions_per_game: int = 100):
    """
    Simulate playoff prediction load.

    Default: 8 games × 100 predictions = 800 predictions
    """

    test_date = date.today().isoformat()

    def process_game(game_num: int):
        """Simulate processing one game's predictions."""
        # Don't actually write to prod - use test tables
        for player_num in range(predictions_per_game):
            # Simulate prediction generation
            pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [
            executor.submit(process_game, i)
            for i in range(games_per_day)
        ]
        concurrent.futures.wait(futures)

    print(f"Simulated {games_per_day * predictions_per_game} predictions")
```

---

### 7.2 Cost Spike Alerts

**Priority:** P2
**Gap:** GCP costs could spike without notice.

**Implementation:**

```bash
#!/bin/bash
# bin/monitoring/setup_cost_alerts.sh
"""Set up GCP budget alerts."""

PROJECT_ID="nba-props-platform"
BILLING_ACCOUNT=$(gcloud billing projects describe $PROJECT_ID --format="value(billingAccountName)")

# Daily budget alert
gcloud billing budgets create \
  --billing-account=$BILLING_ACCOUNT \
  --display-name="NBA Pipeline Daily Alert" \
  --budget-amount=50USD \
  --calendar-period=month \
  --threshold-rule=percent=0.50,basis=current-spend \
  --threshold-rule=percent=0.75,basis=current-spend \
  --threshold-rule=percent=0.90,basis=current-spend \
  --threshold-rule=percent=1.00,basis=current-spend \
  --all-updates-rule \
  --notification-channels="projects/$PROJECT_ID/notificationChannels/CHANNEL_ID"

echo "Budget alert created"
```

**BigQuery Cost Query:**

```sql
-- Daily cost breakdown by service
SELECT
  DATE(usage_start_time) as date,
  service.description as service,
  SUM(cost) as cost_usd
FROM `billing_export.gcp_billing_export_v1_XXXXX`
WHERE project.id = 'nba-props-platform'
AND DATE(usage_start_time) >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

---

## 8. Summary: Priority Matrix

| # | Item | Priority | Effort | Category |
|---|------|----------|--------|----------|
| 1.1 | Model drift detection | P1 | Medium | Prediction Quality |
| 1.2 | Confidence calibration | P1 | Low | Prediction Quality |
| 1.3 | Prediction distribution | P2 | Low | Prediction Quality |
| 2.1 | Odds staleness detection | P1 | Low | Data Freshness |
| 2.2 | Source data lag detection | P2 | Low | Data Freshness |
| 3.1 | Pub/Sub idempotency | P1 | Medium | Message Reliability |
| 3.2 | Message processing metrics | P2 | Low | Message Reliability |
| 4.1 | New season handling | P2 | Medium | Cold Start |
| 4.2 | Roster change detection | P2 | Low | Cold Start |
| 5.1 | Name resolution quality | P2 | Medium | Data Quality |
| 5.2 | Impossible value detection | P2 | Low | Data Quality |
| 6.1 | Graceful degradation docs | P2 | Low | Resilience |
| 6.2 | Rate limit monitoring | P2 | Low | Resilience |
| 7.1 | Playoff capacity planning | P2 | Medium | Capacity |
| 7.2 | Cost spike alerts | P2 | Low | Capacity |

---

## 9. Implementation Recommendations

### Immediate (Before Next Season Start)
1. Model drift detection (1.1)
2. Confidence calibration (1.2)
3. Odds staleness detection (2.1)
4. Pub/Sub idempotency (3.1)

### Before Playoffs
5. Playoff capacity planning (7.1)
6. Graceful degradation documentation (6.1)
7. Cost spike alerts (7.2)

### Ongoing Improvements
8. Remaining items based on observed issues

---

**Document Version:** 1.0
**Created:** 2026-01-25
**Type:** Defense in Depth / Edge Case Handling
