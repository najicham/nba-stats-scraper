# Canary Failure Response Runbook

**Layer 2 of Resilience System** - Session 135

## Overview

Automated end-to-end pipeline validation that runs every 30 minutes and alerts on data quality issues.

**Alert Channel:** `#canary-alerts`
**Schedule:** Every 30 minutes
**Data Source:** Yesterday's games (for stability)
**Detection Window:** ~30 minutes max

## Alert Format

```
🚨 *Pipeline Canary - Failures Detected*

❌ 2 failed | ✅ 4 passed

*Phase 2 - Raw Processing*
_Validates raw game data processing_
```
High NULL rate for player_name: 8.5%
Low player record count: 35 (expected ≥40)
```
Metrics:
  • games: 2
  • player_records: 35
  • null_player_names: 3
  • null_team_abbr: 0

*Phase 3 - Analytics*
_Validates analytics processing and possession tracking_
```
Low record count: 38 (expected ≥40)
Average possessions below threshold: 45.2 (expected ≥50)
```
Metrics:
  • records: 38
  • null_possessions: 0
  • avg_possessions: 45.2

*Investigation Steps:*
1. Check recent deployments: `./bin/whats-deployed.sh`
2. Review pipeline logs for affected phase
3. Run manual validation queries

_Canary queries run against yesterday's data for stability_
```

## Response Procedure by Phase

### Phase 1 - Scrapers

**Symptoms:**
- Source table count below threshold (<10 tables)

**Investigation:**
```bash
# Check scraper execution logs
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=nba-phase1-scrapers" \
  --limit 100 --project nba-props-platform

# Check which scrapers ran
bq query --use_legacy_sql=false "
  SELECT table_name, MAX(scrape_timestamp) as last_scrape
  FROM \`nba-props-platform.nba_raw.__TABLES__\`
  GROUP BY table_name
  ORDER BY last_scrape DESC
"
```

**Common Causes:**
- Scraper failures (CloudFront blocking, API changes)
- Scheduler not triggering
- Source website downtime

**Resolution:**
1. Check scraper error logs
2. Re-run failed scrapers manually if needed
3. Investigate source website issues

---

### Phase 2 - Raw Processing

**Symptoms:**
- Missing games (games < expected)
- Low player record count (<40 for 2 games)
- High NULL rates for critical fields (>5%)
- Stale data (>24 hours old)

**Investigation:**
```bash
# Check raw data for yesterday
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
  SELECT
    COUNT(DISTINCT game_id) as games,
    COUNT(*) as player_records,
    COUNTIF(player_name IS NULL) as null_player_names,
    COUNTIF(team_abbr IS NULL) as null_team_abbr,
    COUNTIF(points IS NULL) as null_points
  FROM \`nba-props-platform.nba_raw.nbac_player_boxscore\`
  WHERE game_date = '$GAME_DATE'
"

# Check which games were scheduled
bq query --use_legacy_sql=false "
  SELECT game_id, away_team_tricode, home_team_tricode, game_status
  FROM \`nba-props-platform.nba_reference.nba_schedule\`
  WHERE game_date = '$GAME_DATE'
"
```

**Common Causes:**
- Incomplete scraper data upstream
- Processor failures
- Data transformation errors
- NBA.com API issues

**Resolution:**
1. Check Phase 2 processor logs
2. Verify scraper data quality
3. Re-run processors if needed
4. Check Phase 2→3 quality gate logs

---

### Phase 3 - Analytics

**Symptoms:**
- Low record count (<40 players)
- NULL possessions for active players
- NULL critical fields (minutes, points)
- Low average possessions (<50)

**Investigation:**
```bash
# Check analytics data
GAME_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
  SELECT
    COUNT(*) as records,
    COUNTIF(possessions IS NULL AND is_dnp = FALSE) as null_possessions,
    COUNTIF(minutes_played IS NULL AND is_dnp = FALSE) as null_minutes,
    AVG(CASE WHEN is_dnp = FALSE THEN possessions END) as avg_possessions,
    MIN(CASE WHEN is_dnp = FALSE THEN possessions END) as min_possessions,
    MAX(CASE WHEN is_dnp = FALSE THEN possessions END) as max_possessions
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date = '$GAME_DATE'
"

# Check for specific games with issues
bq query --use_legacy_sql=false "
  SELECT
    game_id,
    COUNT(*) as players,
    COUNTIF(possessions IS NULL AND is_dnp = FALSE) as null_possessions
  FROM \`nba-props-platform.nba_analytics.player_game_summary\`
  WHERE game_date = '$GAME_DATE'
  GROUP BY game_id
  HAVING null_possessions > 0
"
```

**Common Causes:**
- Missing play-by-play data upstream
- Possession calculation errors
- Analytics processor failures
- Phase 2→3 quality gate issues

**Resolution:**
1. Check Phase 3 processor logs
2. Verify Phase 2 data quality
3. Check play-by-play data for affected games
4. Re-run analytics processors if needed

---

### Phase 4 - Precompute

**Symptoms:**
- Low player count (<200 players)
- Low average games played (<10)
- NULL aggregated stats

**Investigation:**
```bash
# Check precompute data
AS_OF_DATE=$(date -d "yesterday" +%Y-%m-%d)

bq query --use_legacy_sql=false "
  SELECT
    COUNT(DISTINCT player_lookup) as players,
    AVG(games_played) as avg_games,
    MIN(games_played) as min_games,
    COUNTIF(points_avg IS NULL) as null_avg_points
  FROM \`nba-props-platform.nba_analytics.player_season_averages\`
  WHERE season = '2025-26'
  AND as_of_date = '$AS_OF_DATE'
"
```

**Common Causes:**
- Missing Phase 3 data
- Aggregation calculation errors
- Processor failures

**Resolution:**
1. Check Phase 4 processor logs
2. Verify Phase 3 data completeness
3. Check processing gates
4. Re-run precompute processors if needed

---

### Phase 5 - Predictions

**Symptoms:**
- Low prediction count (<50 predictions)
- Low player count (<20 players)
- NULL predicted values or edge values

**Investigation:**
```bash
# Check predictions for today
bq query --use_legacy_sql=false "
  SELECT
    COUNT(*) as predictions,
    COUNT(DISTINCT player_lookup) as players,
    COUNT(DISTINCT game_id) as games,
    COUNTIF(predicted_value IS NULL) as null_predictions,
    COUNTIF(edge_percent IS NULL) as null_edge,
    AVG(edge_percent) as avg_edge
  FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
  WHERE game_date = CURRENT_DATE()
  AND is_active = TRUE
"

# Check quality gate status
bq query --use_legacy_sql=false "
  SELECT *
  FROM \`nba-props-platform.nba_orchestration.quality_gate_results\`
  WHERE game_date = CURRENT_DATE()
  AND phase = 'phase5'
  ORDER BY check_timestamp DESC
  LIMIT 10
"
```

**Common Causes:**
- Missing feature store data
- Model loading failures
- Quality gate blocks
- Insufficient upstream data

**Resolution:**
1. Check prediction coordinator logs
2. Check prediction worker logs
3. Verify feature store data
4. Check quality gate results

---

### Phase 6 - Publishing

**Symptoms:**
- Missing signal records
- NULL signal values
- NULL pct_over values

**Investigation:**
```bash
# Check signals for today
bq query --use_legacy_sql=false "
  SELECT *
  FROM \`nba-props-platform.nba_predictions.daily_prediction_signals\`
  WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v9'
"

# Check GCS exports
gsutil ls gs://nba-props-platform-api/predictions/$(date +%Y-%m-%d)/
```

**Common Causes:**
- Missing predictions upstream
- Signal calculation errors
- Publishing job failures

**Resolution:**
1. Check publishing job logs
2. Verify predictions exist
3. Re-run publishing job if needed

## General Investigation Steps

### 1. Check Recent Deployments

```bash
# See what's deployed
./bin/whats-deployed.sh

# Check for drift
./bin/check-deployment-drift.sh --verbose
```

### 2. Review Error Logs

```bash
# Check all services for errors in last hour
gcloud logging read "severity>=ERROR \
  AND timestamp>\"$(date -u -d '1 hour ago' --iso-8601=seconds)\"" \
  --limit 100 --project nba-props-platform
```

### 3. Check Orchestration Status

```bash
# Check Phase 2 completion
python bin/maintenance/check_phase2_completion.py --date $(date -d "yesterday" +%Y-%m-%d)

# Check Phase 3 completion
./bin/monitoring/phase3_health_check.sh
```

### 4. Run Manual Validation

```bash
# Re-run all canaries manually
python bin/monitoring/pipeline_canary_queries.py

# Check specific phase
python -c "
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')

# Example: Check Phase 2
query = '''
  SELECT
    COUNT(DISTINCT game_id) as games,
    COUNT(*) as player_records
  FROM \`nba-props-platform.nba_raw.nbac_player_boxscore\`
  WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
'''

result = list(client.query(query).result())
print(result[0])
"
```

## Escalation

### Critical Issues (Escalate Immediately)

- All phases failing
- Zero predictions generated
- Zero games processed
- Data corruption detected

**Action:** Page on-call engineer

### High Priority (Resolve Within 2 Hours)

- 2+ phases failing
- <50% expected data coverage
- Prediction quality degradation

**Action:** Investigate immediately, notify team

### Medium Priority (Resolve Same Day)

- 1 phase failing
- Minor data quality issues
- Expected coverage 70-90%

**Action:** Investigate during business hours

### Low Priority (Monitor)

- Warnings but passing
- Expected coverage 90-100% but with issues
- Non-critical NULL values

**Action:** Log issue, investigate if pattern emerges

## Tuning Thresholds

**If getting false positives:**

Edit `bin/monitoring/pipeline_canary_queries.py` and adjust thresholds:

```python
CANARY_CHECKS = [
    CanaryCheck(
        name="Phase 3 - Analytics",
        # ...
        thresholds={
            'records': {'min': 40},  # Lower if avg games/day decreases
            'avg_possessions': {'min': 50}  # Adjust based on season avg
        }
    ),
    # ...
]
```

Redeploy after changes:
```bash
./bin/monitoring/setup_pipeline_canary_scheduler.sh
```

## Metrics

**Track:**
- Canary failure rate by phase
- False positive rate
- Mean time to detection (MTTD)
- Mean time to resolution (MTTR)

**Success Criteria:**
- MTTD < 30 minutes: 100%
- False positive rate: <5%
- All phases validated: 100%

## Related Documentation

- [Deployment Monitoring](deployment-monitoring.md)
- [Phase 3 Orchestration](phase3-orchestration.md)
- [Useful Queries](../useful-queries.md)

## History

- **2026-02-05:** Initial implementation (Session 135)
- Implements Layer 2 of 6-layer resilience system
- 30-minute end-to-end validation
