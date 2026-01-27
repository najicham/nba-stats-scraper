# External Review: Opus (Web Chat)

**Date**: 2026-01-26
**Reviewer**: Claude Opus (Web Chat)
**Document**: Data Validation Architecture & Cascade Prevention

---

## Executive Summary

The NBA Props Platform has a cascade contamination problem: **81% of this season's game data was backfilled late**, causing downstream computed values (rolling averages, ML features, predictions) to be calculated with incomplete data windows.

The current validation skills (`/validate-daily`, `/validate-historical`, `/validate-lineage`) detect problems *after* they happen. The correct solution is **preventing contamination in the first place** through dependency-aware processing.

**Core Insight**: The pipeline runs on a **clock** (6 AM, 6:30 AM, etc.), but it should run on **data readiness**. When data arrives late, downstream phases shouldn't compute wrong values — they should either wait or produce explicit NULLs that get filled in later.

---

## Problem Analysis

### Root Cause

The pipeline processes phases sequentially by time, but data arrives asynchronously:

```
6:00 AM → Scrape yesterday's data (may fail)
6:30 AM → Process raw data
7:00 AM → Compute analytics
7:30 AM → Compute rolling averages (using whatever data exists)  ← CONTAMINATION
```

If scraping fails at 6 AM, the 7:30 AM job still runs with incomplete data. The rolling average is calculated with a partial window, producing a **silently wrong value**.

### The Cascade Effect

```
Day 1: Game A played
Day 2: Game A data MISSING (scraper failed)
Day 3: Phase 4 computes "last 10 games avg" for Player X
        └── Uses games 2-11 instead of 1-10 (Game A missing)
        └── Rolling average is WRONG (but stored as if correct)
Day 4: Phase 5 generates prediction using wrong rolling avg
        └── Prediction is WRONG
Day 5: Game A data finally arrives (backfilled)
Day 6: Phase 4 reprocesses... but old wrong values still exist for Day 3-4
```

### Key Insight

**A missing value is better than a wrong value.**

If you can't compute a correct rolling average, don't compute one at all. Store NULL instead. Downstream systems can handle NULLs (use fallbacks, skip player, etc.). They cannot handle silently wrong data.

---

## Recommended Architecture

### Four-Layer Data Quality System

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    DATA QUALITY ARCHITECTURE                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  LAYER 1: PREVENTION (Processing Time)                                   │
│  ─────────────────────────────────────                                   │
│  • Window completeness checks before computing rolling averages          │
│  • Dependency verification before phase transitions                      │
│  • Data contracts at phase boundaries                                    │
│  • Fail fast: NULL > wrong value                                        │
│                                                                          │
│  LAYER 2: DETECTION (Near Real-Time)                                     │
│  ────────────────────────────────────                                    │
│  • Freshness monitoring (alert if data too old)                         │
│  • Record count monitoring (alert on sudden drops)                       │
│  • Anomaly detection on computed values                                  │
│  • Schema validation (unexpected nulls, type mismatches)                │
│                                                                          │
│  LAYER 3: VALIDATION (Batch)                                             │
│  ───────────────────────────                                             │
│  • /validate-daily (pipeline health)                                     │
│  • /validate-historical (completeness)                                   │
│  • /validate-lineage (correctness)                                       │
│  • Periodic full recomputation comparison                                │
│                                                                          │
│  LAYER 4: REMEDIATION (Automated)                                        │
│  ────────────────────────────────                                        │
│  • Auto-reprocess when late data arrives                                 │
│  • Cascade triggers for downstream recomputation                         │
│  • Versioned outputs for before/after comparison                         │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Current state**: You have Layer 3 (validation skills). You're missing Layers 1, 2, and 4.

**Priority**: Layer 1 (Prevention) has the highest impact. Prevent contamination instead of detecting it after the fact.

---

## Layer 1: Prevention (Highest Priority)

### 1.1 Window Completeness Checks

The most impactful single change. Before computing any rolling average, verify the window is complete.

#### Concept

```python
# WRONG: Compute with whatever data exists
def compute_rolling_average(player_id, game_date, window=10):
    games = get_recent_games(player_id, before=game_date, limit=window)
    return sum(g.points for g in games) / len(games)  # Could be 7/10 games!

# RIGHT: Verify window completeness first
def compute_rolling_average(player_id, game_date, window=10):
    games = get_recent_games(player_id, before=game_date, limit=window)

    if len(games) < window:
        # Don't compute a partial average
        return None  # Or raise InsufficientDataError

    return sum(g.points for g in games) / len(games)
```

#### Implementation: Window Completeness Checker

```python
"""
Window completeness validation for rolling calculations.

Path: shared/validation/window_completeness.py
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, List, Tuple
from google.cloud import bigquery
import logging

logger = logging.getLogger(__name__)


@dataclass
class WindowValidationResult:
    """Result of window completeness check."""
    is_complete: bool
    required_games: int
    available_games: int
    missing_dates: List[date]
    message: str

    @property
    def completeness_ratio(self) -> float:
        if self.required_games == 0:
            return 1.0
        return self.available_games / self.required_games


class WindowCompletenessChecker:
    """
    Validates that rolling calculation windows have complete data.

    Before computing a "last N games" average, this checker verifies
    that we actually have N games of data available. If not, it returns
    a failed validation result, allowing the caller to decide whether
    to skip the calculation (returning NULL) or raise an error.

    Usage:
        checker = WindowCompletenessChecker()

        result = checker.check_player_window(
            player_id="12345",
            as_of_date=date(2026, 1, 26),
            window_size=10,
            source_table="nba_analytics.player_game_summary"
        )

        if not result.is_complete:
            logger.warning(f"Incomplete window: {result.message}")
            return None  # Don't compute contaminated value
    """

    def __init__(self, bq_client: Optional[bigquery.Client] = None):
        self._bq = bq_client or bigquery.Client()

    def check_player_window(
        self,
        player_id: str,
        as_of_date: date,
        window_size: int,
        source_table: str = "nba_analytics.player_game_summary",
        quality_filter: bool = True
    ) -> WindowValidationResult:
        """
        Check if a player has enough games for a rolling window calculation.

        Args:
            player_id: The player's universal ID
            as_of_date: Calculate window as of this date (exclusive)
            window_size: Number of games required (e.g., 10 for last-10 avg)
            source_table: Table to check for game records
            quality_filter: If True, only count 'complete' quality records

        Returns:
            WindowValidationResult with completeness status and details
        """
        quality_clause = ""
        if quality_filter:
            quality_clause = "AND data_quality_flag = 'complete'"

        query = f"""
            WITH player_games AS (
                SELECT
                    game_date,
                    ROW_NUMBER() OVER (ORDER BY game_date DESC) as game_num
                FROM `{source_table}`
                WHERE player_id = @player_id
                  AND game_date < @as_of_date
                  {quality_clause}
                ORDER BY game_date DESC
                LIMIT @window_size
            )
            SELECT
                COUNT(*) as available_games,
                ARRAY_AGG(game_date ORDER BY game_date DESC) as game_dates
            FROM player_games
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_id", "STRING", player_id),
                bigquery.ScalarQueryParameter("as_of_date", "DATE", as_of_date),
                bigquery.ScalarQueryParameter("window_size", "INT64", window_size),
            ]
        )

        result = self._bq.query(query, job_config=job_config).result()
        row = list(result)[0]

        available_games = row.available_games
        game_dates = row.game_dates or []

        is_complete = available_games >= window_size

        # Find missing dates (gaps in the sequence)
        missing_dates = []
        if not is_complete:
            # For incomplete windows, we don't know exactly which dates are missing
            # Just report the shortfall
            missing_dates = []

        if is_complete:
            message = f"Window complete: {available_games}/{window_size} games available"
        else:
            message = (
                f"Window incomplete: {available_games}/{window_size} games available. "
                f"Cannot compute accurate rolling average."
            )

        return WindowValidationResult(
            is_complete=is_complete,
            required_games=window_size,
            available_games=available_games,
            missing_dates=missing_dates,
            message=message
        )

    def check_multiple_windows(
        self,
        player_id: str,
        as_of_date: date,
        window_sizes: List[int],
        source_table: str = "nba_analytics.player_game_summary"
    ) -> dict[int, WindowValidationResult]:
        """
        Check multiple window sizes at once (e.g., last 5, 10, 15, 20).

        More efficient than calling check_player_window multiple times.
        """
        max_window = max(window_sizes)

        # Get all games up to max window
        query = f"""
            SELECT game_date
            FROM `{source_table}`
            WHERE player_id = @player_id
              AND game_date < @as_of_date
              AND data_quality_flag = 'complete'
            ORDER BY game_date DESC
            LIMIT @max_window
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_id", "STRING", player_id),
                bigquery.ScalarQueryParameter("as_of_date", "DATE", as_of_date),
                bigquery.ScalarQueryParameter("max_window", "INT64", max_window),
            ]
        )

        result = self._bq.query(query, job_config=job_config).result()
        game_dates = [row.game_date for row in result]
        available_count = len(game_dates)

        results = {}
        for window_size in window_sizes:
            is_complete = available_count >= window_size
            results[window_size] = WindowValidationResult(
                is_complete=is_complete,
                required_games=window_size,
                available_games=min(available_count, window_size),
                missing_dates=[],
                message=(
                    f"Window complete: {window_size} games" if is_complete
                    else f"Window incomplete: {available_count}/{window_size} games"
                )
            )

        return results

    def get_computable_players(
        self,
        as_of_date: date,
        window_size: int,
        source_table: str = "nba_analytics.player_game_summary"
    ) -> Tuple[List[str], List[str]]:
        """
        Get lists of players who can/cannot have rolling averages computed.

        Returns:
            Tuple of (computable_player_ids, incomplete_player_ids)
        """
        query = f"""
            WITH player_game_counts AS (
                SELECT
                    player_id,
                    COUNT(*) as game_count
                FROM `{source_table}`
                WHERE game_date < @as_of_date
                  AND data_quality_flag = 'complete'
                GROUP BY player_id
            )
            SELECT
                player_id,
                game_count,
                game_count >= @window_size as is_computable
            FROM player_game_counts
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("as_of_date", "DATE", as_of_date),
                bigquery.ScalarQueryParameter("window_size", "INT64", window_size),
            ]
        )

        result = self._bq.query(query, job_config=job_config).result()

        computable = []
        incomplete = []

        for row in result:
            if row.is_computable:
                computable.append(row.player_id)
            else:
                incomplete.append(row.player_id)

        logger.info(
            f"Window completeness check for {as_of_date}, window={window_size}: "
            f"{len(computable)} computable, {len(incomplete)} incomplete"
        )

        return computable, incomplete
```

### 1.2 Data Quality Flag

Add a quality indicator to source records so downstream can filter appropriately.

#### Schema Change

```sql
-- Add to player_game_summary
ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN data_quality_flag STRING DEFAULT 'complete';

-- Values:
-- 'complete' - Full stats available
-- 'partial' - Only roster data, no stats (points=0, etc.)
-- 'estimated' - Some values estimated/imputed
-- 'corrected' - Stats were corrected after initial load
```

### 1.3 Game Schedule Reference Table

The pipeline doesn't currently know how many games *should* exist. Add a schedule table.

#### Schema

```sql
CREATE TABLE nba_reference.game_schedule (
    game_id STRING NOT NULL,
    game_date DATE NOT NULL,
    home_team_id STRING NOT NULL,
    away_team_id STRING NOT NULL,
    scheduled_time TIMESTAMP,
    status STRING NOT NULL,  -- 'scheduled', 'in_progress', 'completed', 'postponed', 'cancelled'
    season STRING NOT NULL,  -- '2025-26'
    season_type STRING NOT NULL,  -- 'regular', 'playoffs', 'preseason'

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

    PRIMARY KEY (game_id)
)
PARTITION BY game_date
CLUSTER BY status, season;
```

### 1.4 Data Contracts at Phase Boundaries

Formalize expectations between phases. Check contracts before proceeding.

#### Contract Definition

```yaml
# contracts/phase2_to_phase3.yaml

contract:
  name: raw_to_analytics
  version: "1.0"
  producer: phase2_raw_processors
  consumer: phase3_analytics

  # Check these before Phase 3 starts
  pre_conditions:
    - name: all_scheduled_games_have_data
      description: "Every completed game has player boxscore data"
      query: |
        SELECT
          s.game_date,
          COUNT(DISTINCT s.game_id) as expected,
          COUNT(DISTINCT b.game_id) as actual
        FROM nba_reference.game_schedule s
        LEFT JOIN nba_raw.bdl_player_boxscores b ON s.game_id = b.game_id
        WHERE s.status = 'completed' AND s.game_date = '{date}'
        GROUP BY s.game_date
      assertion: "expected == actual"
      severity: "blocking"  # Don't proceed if fails

    - name: minimum_players_per_game
      description: "Each game has at least 10 players with stats"
      query: |
        SELECT game_id, COUNT(DISTINCT player_id) as player_count
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date = '{date}'
        GROUP BY game_id
        HAVING player_count < 10
      assertion: "row_count == 0"
      severity: "blocking"

    - name: stats_are_reasonable
      description: "No player has more than 60 points"
      query: |
        SELECT player_id, points
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date = '{date}' AND points > 60
      assertion: "row_count == 0"
      severity: "warning"  # Log but proceed
```

---

## Layer 2: Detection (Near Real-Time)

### 2.1 Freshness Monitoring

Alert when data is stale.

```python
class FreshnessMonitor:
    """
    Monitors data freshness and alerts on stale data.
    """

    DEFAULT_CONFIGS = [
        FreshnessConfig("nba_raw.bdl_player_boxscores", 6, "slack"),
        FreshnessConfig("nba_analytics.player_game_summary", 12, "slack"),
        FreshnessConfig("nba_precompute.player_composite_factors", 12, "slack"),
        FreshnessConfig("nba_predictions.player_prop_predictions", 24, "slack"),
    ]
```

### 2.2 Record Count Monitoring

Alert on unexpected drops in record counts.

---

## Layer 4: Remediation (Automated)

### 4.1 Cascade Reprocessing

When late data arrives, automatically trigger downstream reprocessing.

```python
class CascadeTrigger:
    """
    Triggers downstream reprocessing when source data changes.

    When late data arrives for date D:
    1. Reprocess Phase 3 for date D
    2. Reprocess Phase 4 for dates D through today
       (rolling averages from D forward are affected)
    3. Reprocess Phase 5 predictions for affected dates
    """

    def on_late_data_arrival(
        self,
        source_table: str,
        affected_date: date,
        affected_players: List[str] = None
    ):
        today = date.today()

        # Determine affected date range
        affected_dates = []
        current = affected_date
        while current <= today:
            affected_dates.append(current)
            current += timedelta(days=1)

        # Trigger Phase 3 reprocessing for the late date
        self._publish_reprocess_request(
            phase="phase3",
            dates=[affected_date],
            reason=f"Late data arrival in {source_table}"
        )

        # Trigger Phase 4 reprocessing for affected range
        self._publish_reprocess_request(
            phase="phase4",
            dates=affected_dates,
            reason=f"Cascade from late data in {source_table} on {affected_date}"
        )
```

### 4.2 Late Data Detection

Detect when backfilled data arrives and trigger cascade.

---

## Implementation Priority

### Phase 1: Stop the Bleeding (Week 1)

| Task | Impact | Effort |
|------|--------|--------|
| Window completeness checks in Phase 4 | HIGH | 2 days |
| Add `data_quality_flag` to player_game_summary | MEDIUM | 1 day |
| Add `*_complete` columns to precompute tables | MEDIUM | 1 day |

**Outcome**: New processing won't create contaminated data.

### Phase 2: Know What's Expected (Week 2)

| Task | Impact | Effort |
|------|--------|--------|
| Create game_schedule table | HIGH | 1 day |
| Add game schedule scraper | HIGH | 2 days |
| Add expected vs actual validation | MEDIUM | 1 day |

### Phase 3: Contracts & Detection (Week 3)

| Task | Impact | Effort |
|------|--------|--------|
| Implement data contracts | MEDIUM | 2 days |
| Add freshness monitoring | MEDIUM | 1 day |
| Add record count monitoring | LOW | 1 day |

### Phase 4: Auto-Remediation (Week 4)

| Task | Impact | Effort |
|------|--------|--------|
| Implement cascade trigger | HIGH | 2 days |
| Implement late data detector | HIGH | 1 day |
| Test end-to-end cascade flow | HIGH | 1 day |

---

## Summary

The core problem is that your pipeline processes phases on a clock, but data arrives asynchronously. The solution is:

1. **Prevention**: Don't compute wrong values. Check window completeness, use data contracts, produce NULLs instead of contaminated estimates.

2. **Detection**: Know when data is late, stale, or anomalous. Monitor freshness, record counts, and contract compliance.

3. **Validation**: Your existing skills, enhanced with contamination detection and recomputation comparison.

4. **Remediation**: When late data arrives, automatically cascade reprocessing through all affected downstream tables.

The most impactful single change is **window completeness checks in Phase 4**. This immediately stops new contamination from occurring.

---

**End of Review**
