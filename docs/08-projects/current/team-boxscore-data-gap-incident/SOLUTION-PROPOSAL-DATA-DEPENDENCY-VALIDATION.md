# Solution Proposal: Data Dependency Validation & Cascade Management
## Preventing Predictions With Incomplete Historical Data

**Created:** January 22, 2026
**Status:** Proposed
**Related:**
- `ARCHITECTURAL-ANALYSIS-DATA-DEPENDENCIES.md` (this directory)
- `/docs/09-handoff/2026-01-22-DATA-CASCADE-PROBLEM-HANDOFF.md`

---

## 1. Problem Summary

**Core Issue:** When historical data is missing, subsequent dates continue processing with BIASED rolling averages. Completeness checks pass because they only validate TODAY's data, not the historical window needed for calculations.

**Impact:**
- Rolling averages calculated with missing games (e.g., 8/10 games)
- Feature quality appears "100%" but is actually degraded
- Predictions made with stale/biased data
- No visibility into which predictions are affected

---

## 2. Solution Overview

Three-phase approach (aligns with handoff document):

| Phase | Solution | Timeline | Impact |
|-------|----------|----------|--------|
| **Phase 1** | Historical Window Validation | This week | Detect & warn |
| **Phase 2** | Feature Quality Metadata | 2 weeks | Track & flag |
| **Phase 3** | Cascade Dependency Graph | 1 month | Auto-remediate |

---

## 3. Phase 1: Historical Window Validation (IMMEDIATE)

### 3.1 New Validation Function

**File:** `shared/validation/historical_window_validator.py`

```python
"""
Historical Window Validator
Ensures rolling average calculations have complete data.
"""
from datetime import date, timedelta
from typing import Dict, List, Tuple
from google.cloud import bigquery

class HistoricalWindowValidator:
    """
    Validates that historical data windows are complete before processing.
    """

    # Configuration
    ROLLING_WINDOW_SIZE = 10  # games
    LOOKBACK_DAYS = 60  # days to search for games
    MIN_COMPLETENESS_PCT = 80  # minimum % of expected games

    def __init__(self, bq_client: bigquery.Client):
        self.client = bq_client

    def validate_player_window(
        self,
        player_lookup: str,
        target_date: date,
        window_size: int = 10
    ) -> Dict:
        """
        Check if a player has a complete rolling window.

        Returns:
            {
                'is_complete': bool,
                'games_found': int,
                'games_expected': int,
                'completeness_pct': float,
                'window_span_days': int,
                'oldest_game_date': date,
                'newest_game_date': date,
                'is_stale': bool  # True if window spans > 21 days
            }
        """
        query = f"""
        WITH player_games AS (
            SELECT
                game_date,
                ROW_NUMBER() OVER (ORDER BY game_date DESC) as game_num
            FROM nba_analytics.player_game_summary
            WHERE player_lookup = @player_lookup
              AND game_date < @target_date
              AND game_date >= DATE_SUB(@target_date, INTERVAL 60 DAY)
            ORDER BY game_date DESC
            LIMIT @window_size
        )
        SELECT
            COUNT(*) as games_found,
            MIN(game_date) as oldest_game,
            MAX(game_date) as newest_game,
            DATE_DIFF(MAX(game_date), MIN(game_date), DAY) as span_days
        FROM player_games
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("player_lookup", "STRING", player_lookup),
                bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
                bigquery.ScalarQueryParameter("window_size", "INT64", window_size),
            ]
        )

        result = list(self.client.query(query, job_config=job_config))[0]

        games_found = result.games_found or 0
        completeness_pct = (games_found / window_size) * 100
        span_days = result.span_days or 0

        return {
            'is_complete': completeness_pct >= self.MIN_COMPLETENESS_PCT,
            'games_found': games_found,
            'games_expected': window_size,
            'completeness_pct': completeness_pct,
            'window_span_days': span_days,
            'oldest_game_date': result.oldest_game,
            'newest_game_date': result.newest_game,
            'is_stale': span_days > 21,  # 10 games shouldn't span > 3 weeks
        }

    def validate_date_historical_completeness(
        self,
        target_date: date,
        critical_tables: List[str] = None,
        lookback_days: int = 7
    ) -> Dict:
        """
        Check if critical tables have data for recent historical dates.

        Returns:
            {
                'is_complete': bool,
                'tables': {
                    'table_name': {
                        'missing_dates': [date, ...],
                        'completeness_pct': float
                    }
                }
            }
        """
        if critical_tables is None:
            critical_tables = [
                'nba_raw.nbac_team_boxscore',
                'nba_analytics.player_game_summary',
                'nba_analytics.team_defense_game_summary',
            ]

        results = {'is_complete': True, 'tables': {}}

        for table in critical_tables:
            # Get expected dates from schedule
            expected_dates_query = f"""
            SELECT DISTINCT game_date
            FROM nba_raw.nbac_schedule
            WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL @lookback DAY)
              AND DATE_SUB(@target_date, INTERVAL 1 DAY)
              AND game_status = 3
            """

            # Get actual dates in table
            actual_dates_query = f"""
            SELECT DISTINCT game_date
            FROM {table}
            WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL @lookback DAY)
              AND DATE_SUB(@target_date, INTERVAL 1 DAY)
            """

            expected = set(row.game_date for row in self.client.query(
                expected_dates_query,
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
                    bigquery.ScalarQueryParameter("lookback", "INT64", lookback_days),
                ])
            ))

            actual = set(row.game_date for row in self.client.query(
                actual_dates_query,
                job_config=bigquery.QueryJobConfig(query_parameters=[
                    bigquery.ScalarQueryParameter("target_date", "DATE", target_date),
                    bigquery.ScalarQueryParameter("lookback", "INT64", lookback_days),
                ])
            ))

            missing = expected - actual
            completeness_pct = len(actual) / len(expected) * 100 if expected else 100

            results['tables'][table] = {
                'missing_dates': sorted(missing),
                'completeness_pct': completeness_pct,
                'is_complete': completeness_pct >= 80
            }

            if missing:
                results['is_complete'] = False

        return results
```

### 3.2 Integration Points

**Add to `ml_feature_store_processor.py`:**

```python
from shared.validation.historical_window_validator import HistoricalWindowValidator

class MLFeatureStoreProcessor:
    def __init__(self, ...):
        self.window_validator = HistoricalWindowValidator(self.bq_client)

    def process_player(self, player_lookup, game_date):
        # NEW: Validate historical window before processing
        window_status = self.window_validator.validate_player_window(
            player_lookup, game_date, window_size=10
        )

        if not window_status['is_complete']:
            self.logger.warning(
                f"Incomplete historical window for {player_lookup} on {game_date}: "
                f"{window_status['games_found']}/{window_status['games_expected']} games "
                f"({window_status['completeness_pct']:.1f}%)"
            )
            # Store metadata with feature record
            self.feature_metadata['historical_completeness'] = window_status

        if window_status['is_stale']:
            self.logger.warning(
                f"Stale window for {player_lookup}: "
                f"10 games span {window_status['window_span_days']} days"
            )
```

### 3.3 Pre-Flight Check for Daily Pipeline

**Add to `bin/validate_pipeline.py`:**

```python
def check_historical_dependencies(game_date):
    """
    Before running Phase 4, ensure historical data is complete.
    """
    validator = HistoricalWindowValidator(get_bq_client())

    result = validator.validate_date_historical_completeness(
        target_date=game_date,
        lookback_days=7  # Check last 7 days
    )

    if not result['is_complete']:
        print("⚠️  HISTORICAL DATA GAPS DETECTED:")
        for table, status in result['tables'].items():
            if status['missing_dates']:
                print(f"  {table}: Missing {len(status['missing_dates'])} dates")
                for d in status['missing_dates'][:5]:
                    print(f"    - {d}")
        return False

    return True
```

---

## 4. Phase 2: Feature Quality Metadata (SHORT-TERM)

### 4.1 Schema Addition

**Add to `ml_feature_store_v2` table:**

```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN historical_completeness STRUCT<
    games_found INT64,
    games_expected INT64,
    completeness_pct FLOAT64,
    window_span_days INT64,
    is_reliable BOOL,
    missing_dates ARRAY<DATE>
>;
```

### 4.2 Populate During Feature Generation

```python
def build_feature_record(self, player_lookup, game_date, features):
    window_status = self.window_validator.validate_player_window(
        player_lookup, game_date
    )

    return {
        # Existing features
        'player_lookup': player_lookup,
        'game_date': game_date,
        'points_avg_last_10': features['points_avg_last_10'],
        # ... other features ...

        # NEW: Completeness metadata
        'historical_completeness': {
            'games_found': window_status['games_found'],
            'games_expected': window_status['games_expected'],
            'completeness_pct': window_status['completeness_pct'],
            'window_span_days': window_status['window_span_days'],
            'is_reliable': window_status['is_complete'] and not window_status['is_stale'],
            'missing_dates': [],  # Could populate with specific dates
        }
    }
```

### 4.3 Filter Unreliable Predictions

**In prediction coordinator:**

```python
def filter_reliable_features(self, features_df):
    """Only generate predictions for reliable feature sets."""
    reliable = features_df[
        features_df['historical_completeness.is_reliable'] == True
    ]

    unreliable_count = len(features_df) - len(reliable)
    if unreliable_count > 0:
        self.logger.warning(
            f"Skipping {unreliable_count} players with unreliable features"
        )

    return reliable
```

---

## 5. Phase 3: Cascade Dependency Graph (MEDIUM-TERM)

### 5.1 New Table: Feature Lineage

```sql
CREATE TABLE nba_precompute.feature_lineage (
    lineage_id STRING NOT NULL,

    -- Target record
    target_player_lookup STRING NOT NULL,
    target_game_date DATE NOT NULL,
    target_table STRING NOT NULL,  -- 'ml_feature_store_v2'

    -- Contributing data
    contributing_game_dates ARRAY<DATE>,  -- Dates used in rolling window
    contributing_player_game_ids ARRAY<STRING>,  -- Specific game records

    -- Metadata
    window_type STRING,  -- 'last_10_games', 'last_5_games', etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),

    PRIMARY KEY (lineage_id)
)
PARTITION BY target_game_date
CLUSTER BY target_player_lookup;
```

### 5.2 Populate Lineage During Processing

```python
def record_lineage(self, player_lookup, target_date, contributing_games):
    """Record which games contributed to a feature calculation."""
    lineage_record = {
        'lineage_id': f"{player_lookup}_{target_date}_last_10",
        'target_player_lookup': player_lookup,
        'target_game_date': target_date,
        'target_table': 'ml_feature_store_v2',
        'contributing_game_dates': [g['game_date'] for g in contributing_games],
        'contributing_player_game_ids': [g['game_id'] for g in contributing_games],
        'window_type': 'last_10_games',
    }
    self.lineage_writer.write(lineage_record)
```

### 5.3 Cascade Detection Query

```sql
-- Find all feature records affected by backfilling a specific date
SELECT DISTINCT
    target_game_date,
    target_player_lookup
FROM nba_precompute.feature_lineage
WHERE @backfilled_date IN UNNEST(contributing_game_dates)
ORDER BY target_game_date;
```

### 5.4 Automated Cascade Reprocessor

**File:** `bin/backfill/cascade_reprocessor.py`

```python
"""
Cascade Reprocessor
Automatically identifies and reprocesses records affected by a backfill.
"""

class CascadeReprocessor:
    def __init__(self, bq_client):
        self.client = bq_client

    def find_affected_records(self, backfilled_date: date) -> List[Dict]:
        """
        Find all feature store records that used the backfilled date
        in their rolling window calculation.
        """
        query = """
        SELECT DISTINCT
            target_game_date,
            target_player_lookup,
            target_table
        FROM nba_precompute.feature_lineage
        WHERE @backfilled_date IN UNNEST(contributing_game_dates)
        ORDER BY target_game_date
        """
        return list(self.client.query(query, parameters=[
            bigquery.ScalarQueryParameter("backfilled_date", "DATE", backfilled_date)
        ]))

    def calculate_affected_range(self, backfilled_date: date) -> Tuple[date, date]:
        """
        Calculate the date range affected by a backfill.

        Logic: Backfilled date affects target dates from:
        - Start: backfilled_date + 1 day
        - End: backfilled_date + lookback_window (60 days)

        But practically, it mainly affects:
        - End: backfilled_date + 10 games worth (~14-21 days)
        """
        affected_start = backfilled_date + timedelta(days=1)
        affected_end = backfilled_date + timedelta(days=21)  # ~10 games
        return affected_start, affected_end

    def reprocess_cascade(self, backfilled_date: date, dry_run: bool = True):
        """
        Reprocess all records affected by a backfill.
        """
        affected_start, affected_end = self.calculate_affected_range(backfilled_date)

        print(f"Backfill of {backfilled_date} affects: {affected_start} to {affected_end}")

        if dry_run:
            print("DRY RUN - would reprocess:")

        # Get affected records
        affected = self.find_affected_records(backfilled_date)

        # Group by date for batch processing
        by_date = defaultdict(list)
        for record in affected:
            by_date[record['target_game_date']].append(record['target_player_lookup'])

        for target_date in sorted(by_date.keys()):
            players = by_date[target_date]
            print(f"  {target_date}: {len(players)} players")

            if not dry_run:
                # Trigger reprocessing
                self.trigger_feature_reprocess(target_date, players)
```

---

## 6. Cascade Scope Calculation

### 6.1 Forward Impact Window

When data for date D is backfilled:

```
D = Backfilled date (e.g., Jan 1)

Impact on feature calculations:
├── D+1: Last 10 games now includes D
├── D+2: Last 10 games now includes D
├── ...
├── D+14: Last 10 games may include D (if player played ~every other day)
├── D+21: Last 10 games unlikely to include D (if player played every game)

Safe assumption: D affects D+1 through D+21 (3 weeks)
```

### 6.2 Cascade Reprocessing Scope

**For team boxscore backfill (Dec 27 - Jan 21):**

| Backfilled Date | Affects Through | Scope |
|-----------------|-----------------|-------|
| Dec 27 | Jan 17 | 21 days |
| Dec 28 | Jan 18 | 21 days |
| ... | ... | ... |
| Jan 21 | Feb 11 | 21 days |

**Total reprocessing scope:** Dec 28 through Feb 11 (46 days)

### 6.3 Simplified Cascade Rule

```python
def get_reprocess_range(backfill_start: date, backfill_end: date) -> Tuple[date, date]:
    """
    Calculate the date range that needs reprocessing after a backfill.
    """
    # Reprocess starts the day after backfill starts
    reprocess_start = backfill_start + timedelta(days=1)

    # Reprocess ends 21 days after backfill ends
    reprocess_end = backfill_end + timedelta(days=21)

    return reprocess_start, reprocess_end

# Example:
# Backfill: Dec 27 - Jan 21
# Reprocess: Dec 28 - Feb 11
```

---

## 7. Implementation Checklist

### Phase 1: This Week

- [ ] Create `shared/validation/historical_window_validator.py`
- [ ] Add warning logging to `ml_feature_store_processor.py`
- [ ] Add historical check to `bin/validate_pipeline.py`
- [ ] Create monitoring query for incomplete windows
- [ ] Document in runbook

### Phase 2: Next 2 Weeks

- [ ] Add `historical_completeness` column to feature store
- [ ] Update feature generation to populate metadata
- [ ] Add `is_reliable` filtering option to predictions
- [ ] Create dashboard for feature reliability

### Phase 3: Next Month

- [ ] Create `feature_lineage` table
- [ ] Update processors to record lineage
- [ ] Build cascade detection queries
- [ ] Create `cascade_reprocessor.py`
- [ ] Automate backfill → cascade reprocess flow

---

## 8. Configuration Recommendations

### 8.1 Completeness Thresholds

```yaml
# shared/config/validation_config.yaml
historical_validation:
  rolling_window:
    min_games: 10
    min_completeness_pct: 80  # At least 8/10 games
    max_span_days: 21  # 10 games shouldn't span > 3 weeks

  historical_tables:
    lookback_days: 7
    min_completeness_pct: 80

  behavior:
    on_incomplete: "warn"  # Options: "warn", "flag", "block"
    log_level: "WARNING"
```

### 8.2 Cascade Processing

```yaml
# shared/config/cascade_config.yaml
cascade:
  forward_impact_days: 21  # How far forward a backfill affects
  batch_size: 100  # Players to reprocess at once
  dry_run_default: true

  auto_cascade:
    enabled: false  # Require manual trigger for now
    max_affected_records: 10000  # Safety limit
```

---

## 9. Monitoring & Alerting

### 9.1 New Metrics

```python
# Metrics to track
METRICS = {
    'feature_completeness_pct': 'Gauge',  # Average completeness across players
    'incomplete_window_count': 'Counter',  # Players with <80% windows
    'stale_window_count': 'Counter',  # Players with >21 day spans
    'cascade_reprocess_count': 'Counter',  # Records reprocessed due to cascade
}
```

### 9.2 Alert Rules

```yaml
alerts:
  - name: high_incomplete_windows
    condition: incomplete_window_count > 50
    severity: WARNING
    message: "More than 50 players have incomplete rolling windows"

  - name: historical_data_gap
    condition: historical_completeness < 80
    severity: ERROR
    message: "Historical data gap detected in critical tables"
```

---

## 10. Summary

| Problem | Solution | Phase |
|---------|----------|-------|
| Completeness only checks today | Add historical window validation | 1 |
| No visibility into window quality | Store completeness metadata | 2 |
| Can't identify cascade impact | Build dependency graph | 3 |
| Manual cascade identification | Automated cascade reprocessor | 3 |
| Predictions with bad data | Filter unreliable features | 2 |

**Key Principle:** Don't just check if TODAY's data exists. Check if the DATA YOU'RE ABOUT TO USE exists.

---

**Document Status:** Proposed
**Next Steps:** Review and prioritize implementation
**Owner:** TBD
