# Self-Healing Pipeline Design
## Addressing Cascade Failures and Improving Observability

**Created:** 2026-01-23
**Status:** Design Document
**Priority:** High
**Triggered By:** Jan 23 cascade failure incident (TOR@POR predictions missing)

---

## Problem Statement

On January 23, 2026, a cascade failure prevented predictions from being generated for 2 teams (POR, SAC) out of 16 teams playing. The root cause was a stale "running" status in `processor_run_history` that blocked downstream processors due to dependency checks.

### Failure Chain
```
PlayerGameSummaryProcessor (Jan 22) stuck in "running" → marked failed after 4hrs
    ↓
PlayerDailyCacheProcessor (Jan 23) skipped - upstream dependency failed
    ↓
UpcomingPlayerGameContextProcessor - missing POR/SAC players
    ↓
MLFeatureStoreProcessor - incomplete features for TOR@POR
    ↓
PredictionCoordinator - TOR@POR predictions not generated
```

### Impact
- 2/16 teams missing from predictions (12.5% loss)
- Manual intervention required to recover
- No automated alerts until manual investigation

---

## Design Principles

1. **Fail Fast, Recover Faster** - Detect failures within minutes, not hours
2. **Graceful Degradation** - Generate predictions for available data, don't block everything
3. **Self-Healing** - Automatic retries with exponential backoff
4. **Observable by Default** - Every failure mode has a metric and alert
5. **No Silent Failures** - If something fails, someone knows immediately

---

## Proposed Solutions

### 1. Dependency Check Improvements

#### Current Problem
- Dependency checks use binary pass/fail logic
- A single upstream failure blocks all downstream processing
- No distinction between "partial data available" and "no data"

#### Solution: Soft Dependencies with Thresholds

```python
class DependencyConfig:
    """Configuration for dependency checking."""

    # Hard dependencies - must succeed or skip
    HARD_DEPENDENCIES = {
        'PredictionCoordinator': ['MLFeatureStoreProcessor'],
    }

    # Soft dependencies - proceed with warning if threshold met
    SOFT_DEPENDENCIES = {
        'PlayerDailyCacheProcessor': {
            'PlayerGameSummaryProcessor': {
                'min_coverage': 0.8,  # 80% of expected records
                'fallback': 'use_yesterday_data'
            }
        },
        'MLFeatureStoreProcessor': {
            'PlayerDailyCacheProcessor': {
                'min_coverage': 0.7,
                'fallback': 'skip_missing_players'
            }
        }
    }

def check_soft_dependency(self, upstream: str, config: dict) -> tuple[bool, float]:
    """
    Check if soft dependency meets threshold.

    Returns:
        (should_proceed, coverage_percentage)
    """
    expected_count = self._get_expected_records(upstream)
    actual_count = self._get_actual_records(upstream)
    coverage = actual_count / expected_count if expected_count > 0 else 0

    return coverage >= config['min_coverage'], coverage
```

#### Implementation Tasks
- [ ] Add `dependency_config.py` with soft/hard dependency definitions
- [ ] Modify `PrecomputeProcessorBase._run_defensive_checks()` to support soft deps
- [ ] Add coverage metrics to processor run history
- [ ] Create alert for "proceeding with degraded upstream"

---

### 2. Stale Run Detection and Auto-Recovery

#### Current Problem
- Processors can get stuck in "running" state
- Cleanup only happens after 4 hours
- No automatic retry after cleanup

#### Solution: Heartbeat-Based Health Monitoring

```python
class ProcessorHeartbeat:
    """
    Heartbeat system for detecting stuck processors.

    - Processors emit heartbeat every 60 seconds while running
    - Missing heartbeat for 5 minutes triggers investigation
    - Missing heartbeat for 15 minutes triggers auto-recovery
    """

    HEARTBEAT_INTERVAL = 60  # seconds
    STALE_THRESHOLD = 300    # 5 minutes - investigate
    DEAD_THRESHOLD = 900     # 15 minutes - auto-recover

    def __init__(self, processor_name: str, run_id: str):
        self.processor_name = processor_name
        self.run_id = run_id
        self.firestore = firestore.Client()

    async def start_heartbeat(self):
        """Start background heartbeat emission."""
        while self._is_running:
            await self._emit_heartbeat()
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)

    def _emit_heartbeat(self):
        """Write heartbeat to Firestore."""
        self.firestore.collection('processor_heartbeats').document(self.run_id).set({
            'processor_name': self.processor_name,
            'last_heartbeat': datetime.now(timezone.utc),
            'status': 'running',
            'progress': self._get_progress()
        })

class StaleProcessorMonitor:
    """
    Cloud Function that runs every 5 minutes to detect stuck processors.
    """

    def check_for_stale_processors(self):
        """Find and handle stale processors."""
        stale_runs = self._find_stale_runs()

        for run in stale_runs:
            if run['stale_duration'] > self.DEAD_THRESHOLD:
                self._auto_recover(run)
            elif run['stale_duration'] > self.STALE_THRESHOLD:
                self._send_investigation_alert(run)

    def _auto_recover(self, run: dict):
        """Automatically recover a dead processor."""
        # 1. Mark as failed
        self._mark_run_failed(run['run_id'], 'auto_recovery_stale')

        # 2. Clear any locks
        self._clear_processor_locks(run['processor_name'], run['data_date'])

        # 3. Trigger retry
        self._trigger_retry(run['processor_name'], run['data_date'])

        # 4. Alert on recovery action
        self._send_recovery_alert(run)
```

#### Implementation Tasks
- [ ] Create `shared/monitoring/processor_heartbeat.py`
- [ ] Add heartbeat emission to all processor base classes
- [ ] Create `stale-processor-monitor` Cloud Function (runs every 5 min)
- [ ] Add auto-recovery logic with configurable retry limits
- [ ] Create Firestore collection `processor_heartbeats`

---

### 3. Game Coverage Monitoring

#### Current Problem
- No real-time visibility into which games have predictions
- Discovered missing TOR@POR only through manual investigation

#### Solution: Game Coverage Dashboard and Alerts

```sql
-- Create materialized view for game coverage monitoring
CREATE OR REPLACE VIEW `nba_monitoring.prediction_coverage_live` AS
WITH scheduled_games AS (
    SELECT
        game_date,
        game_id,
        home_team_tricode,
        away_team_tricode
    FROM `nba_reference.nba_schedule`
    WHERE game_date >= CURRENT_DATE()
),
prediction_coverage AS (
    SELECT
        game_date,
        game_id,
        COUNT(DISTINCT player_lookup) as players_with_predictions,
        COUNT(*) as total_predictions
    FROM `nba_predictions.player_prop_predictions`
    WHERE is_active = TRUE
    GROUP BY game_date, game_id
),
feature_coverage AS (
    SELECT
        game_date,
        game_id,
        COUNT(*) as players_with_features
    FROM `nba_predictions.ml_feature_store_v2`
    GROUP BY game_date, game_id
)
SELECT
    s.game_date,
    s.game_id,
    s.home_team_tricode,
    s.away_team_tricode,
    COALESCE(f.players_with_features, 0) as feature_count,
    COALESCE(p.players_with_predictions, 0) as prediction_player_count,
    COALESCE(p.total_predictions, 0) as total_predictions,
    CASE
        WHEN p.players_with_predictions IS NULL THEN 'NO_PREDICTIONS'
        WHEN p.players_with_predictions < 10 THEN 'LOW_COVERAGE'
        ELSE 'OK'
    END as coverage_status
FROM scheduled_games s
LEFT JOIN feature_coverage f ON s.game_id = f.game_id AND s.game_date = f.game_date
LEFT JOIN prediction_coverage p ON s.game_id = p.game_id AND s.game_date = p.game_date;
```

```python
class GameCoverageAlert:
    """
    Alert when game coverage falls below threshold.
    Runs 2 hours before first game of the day.
    """

    MIN_PLAYERS_PER_GAME = 8
    ALERT_HOURS_BEFORE_GAME = 2

    def check_coverage(self, game_date: date) -> list[dict]:
        """Check coverage for all games on date."""
        query = """
        SELECT * FROM `nba_monitoring.prediction_coverage_live`
        WHERE game_date = @game_date
          AND coverage_status != 'OK'
        """

        issues = list(self.bq_client.query(query, params={'game_date': game_date}))

        if issues:
            self._send_coverage_alert(game_date, issues)

        return issues
```

#### Implementation Tasks
- [ ] Create `nba_monitoring.prediction_coverage_live` view
- [ ] Create `game-coverage-alert` Cloud Function (2 hrs before first game)
- [ ] Add Slack/email integration for coverage alerts
- [ ] Build simple dashboard showing coverage by game

---

### 4. Automatic Backfill Trigger

#### Current Problem
- When processors fail, manual intervention needed to backfill
- No automatic retry mechanism

#### Solution: Smart Backfill Orchestrator

```python
class BackfillOrchestrator:
    """
    Automatically detects and backfills missing data.
    Runs every 30 minutes during active hours (6 AM - 2 AM ET).
    """

    def run(self):
        """Main orchestration loop."""
        # 1. Check for missing/incomplete data
        gaps = self._detect_data_gaps()

        # 2. Prioritize by urgency (today's games > yesterday > older)
        prioritized_gaps = self._prioritize_gaps(gaps)

        # 3. Trigger backfills for top N gaps
        for gap in prioritized_gaps[:5]:  # Max 5 concurrent backfills
            if not self._is_backfill_in_progress(gap):
                self._trigger_backfill(gap)

    def _detect_data_gaps(self) -> list[DataGap]:
        """Find missing or incomplete data."""
        gaps = []

        # Check each critical table
        for table_config in CRITICAL_TABLES:
            expected = self._get_expected_records(table_config)
            actual = self._get_actual_records(table_config)

            if actual < expected * table_config['min_coverage']:
                gaps.append(DataGap(
                    table=table_config['name'],
                    date=table_config['date'],
                    expected=expected,
                    actual=actual,
                    urgency=self._calculate_urgency(table_config)
                ))

        return gaps

    def _trigger_backfill(self, gap: DataGap):
        """Trigger processor with backfill_mode=True."""
        processor_name = TABLE_TO_PROCESSOR_MAP[gap.table]

        # Publish to backfill topic
        self.publisher.publish(
            topic='nba-backfill-trigger',
            data={
                'processor': processor_name,
                'target_date': gap.date.isoformat(),
                'backfill_mode': True,
                'triggered_by': 'auto_backfill_orchestrator',
                'gap_info': gap.to_dict()
            }
        )
```

#### Implementation Tasks
- [ ] Create `backfill-orchestrator` Cloud Function
- [ ] Define `CRITICAL_TABLES` configuration
- [ ] Add backfill tracking to prevent duplicate runs
- [ ] Create `nba-backfill-trigger` Pub/Sub topic
- [ ] Add metrics for backfill frequency and success rate

---

### 5. Enhanced Observability

#### Current Problem
- Difficult to understand pipeline state at a glance
- Logs scattered across multiple services
- No centralized dashboard

#### Solution: Pipeline Health Dashboard

```python
# Cloud Function: pipeline-health-metrics
def emit_pipeline_health_metrics():
    """
    Emit structured metrics every 5 minutes for dashboarding.
    """
    metrics = {
        'timestamp': datetime.now(timezone.utc).isoformat(),

        # Processor health
        'processors': {
            'running': count_running_processors(),
            'failed_last_hour': count_failed_processors(hours=1),
            'stuck_count': count_stuck_processors(),
        },

        # Data freshness
        'data_freshness': {
            'player_game_summary_age_hours': get_table_age('player_game_summary'),
            'ml_feature_store_age_hours': get_table_age('ml_feature_store_v2'),
            'predictions_age_hours': get_table_age('player_prop_predictions'),
        },

        # Coverage
        'prediction_coverage': {
            'games_today': count_games_today(),
            'games_with_predictions': count_games_with_predictions(),
            'coverage_pct': calculate_coverage_percentage(),
        },

        # Alerts
        'active_alerts': get_active_alerts(),
    }

    # Write to monitoring table
    write_to_bigquery('nba_monitoring.pipeline_health_metrics', metrics)

    # Emit to Cloud Monitoring for dashboards
    emit_to_cloud_monitoring(metrics)
```

#### Dashboard Components
1. **Pipeline Status Overview**
   - Traffic light indicators for each phase (Phase 2-5)
   - Running/Failed/Pending processor counts

2. **Today's Game Coverage**
   - List of games with prediction counts
   - Color-coded by coverage status (red/yellow/green)

3. **Data Freshness Timeline**
   - Hours since last successful update per table
   - Alert threshold indicators

4. **Recent Alerts & Actions**
   - Last 10 alerts with resolution status
   - Auto-recovery actions taken

#### Implementation Tasks
- [ ] Create `pipeline-health-metrics` Cloud Function
- [ ] Create BigQuery table `nba_monitoring.pipeline_health_metrics`
- [ ] Set up Cloud Monitoring dashboard
- [ ] Add alerting policies for critical thresholds
- [ ] Create simple web dashboard (optional)

---

### 6. ESPN Roster Scraper Improvements

#### Current Problem
- ESPN roster data was 9 days stale (Jan 14 for Jan 23 games)
- Missing roster data caused POR/SAC to be excluded

#### Solution: Daily Roster Freshness Check

```python
class RosterFreshnessChecker:
    """
    Ensure roster data is fresh before prediction generation.
    """

    MAX_ROSTER_AGE_DAYS = 3

    def check_roster_freshness(self, teams: list[str]) -> dict:
        """Check roster freshness for teams playing today."""
        query = """
        SELECT
            team_abbr,
            MAX(roster_date) as latest_roster,
            DATE_DIFF(CURRENT_DATE(), MAX(roster_date), DAY) as age_days
        FROM `nba_raw.espn_team_rosters`
        WHERE team_abbr IN UNNEST(@teams)
          AND roster_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
        GROUP BY team_abbr
        """

        results = {}
        for row in self.bq_client.query(query, params={'teams': teams}):
            results[row['team_abbr']] = {
                'latest_roster': row['latest_roster'],
                'age_days': row['age_days'],
                'is_stale': row['age_days'] > self.MAX_ROSTER_AGE_DAYS
            }

        # Check for missing teams
        for team in teams:
            if team not in results:
                results[team] = {
                    'latest_roster': None,
                    'age_days': None,
                    'is_stale': True,
                    'is_missing': True
                }

        return results

    def trigger_roster_refresh(self, stale_teams: list[str]):
        """Trigger roster scraper for stale teams."""
        self.publisher.publish(
            topic='nba-roster-refresh-trigger',
            data={
                'teams': stale_teams,
                'triggered_by': 'freshness_check',
                'priority': 'high'
            }
        )
```

#### Implementation Tasks
- [ ] Add roster freshness check to `UpcomingPlayerGameContextProcessor`
- [ ] Create on-demand roster refresh trigger
- [ ] Add roster freshness metrics to monitoring
- [ ] Alert when roster age exceeds threshold

---

## Implementation Priority

### Phase 1: Quick Wins (This Week)
1. Game Coverage Monitoring view and alert
2. Stale processor detection (reduce from 4hr to 15min)
3. Roster freshness check

### Phase 2: Core Resilience (Next 2 Weeks)
4. Soft dependency implementation
5. Heartbeat-based health monitoring
6. Automatic backfill orchestrator

### Phase 3: Observability (Following 2 Weeks)
7. Pipeline health dashboard
8. Enhanced metrics and alerting
9. Centralized log aggregation

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Time to detect failure | 4+ hours | < 15 minutes |
| Manual interventions per week | 3-5 | < 1 |
| Prediction coverage per game day | ~85% | > 98% |
| Mean time to recovery | Hours | < 30 minutes |
| False positive alerts | N/A | < 5% |

---

## Appendix: Root Cause Analysis - Jan 23 Incident

### Timeline
- **Jan 22 ~10:00 PM UTC**: PlayerGameSummaryProcessor starts, gets stuck
- **Jan 23 ~02:00 AM UTC**: 4-hour timeout, marked as failed
- **Jan 23 ~11:00 AM UTC**: PlayerDailyCacheProcessor skips Jan 23 (upstream failed)
- **Jan 23 ~3:00 PM UTC**: UpcomingPlayerGameContextProcessor runs, missing POR/SAC
- **Jan 23 ~9:50 PM UTC**: Manual investigation discovers missing TOR@POR
- **Jan 23 ~11:30 PM UTC**: Manual backfill initiated

### Root Causes
1. **No early warning** - First indication was 4 hours after processor stuck
2. **Binary dependency check** - Partial upstream success blocked everything
3. **Stale roster data** - ESPN rosters not refreshed since Jan 14
4. **No coverage monitoring** - Missing game not detected until manual check

### Lessons Learned
1. Need heartbeat-based processor health, not just status field
2. Dependencies should have thresholds, not just pass/fail
3. Daily roster freshness validation required
4. Game-level coverage monitoring essential before tip-off
