# Comprehensive Issue Analysis - January 29, 2026

**Date:** 2026-01-29
**Author:** Claude Opus 4.5
**Type:** Root Cause Analysis & Prevention Strategy
**Status:** Reference Document

---

## Executive Summary

This document provides a comprehensive analysis of all issues identified on January 29, 2026, including root causes, gaps in detection, and prevention strategies. Five distinct issues were identified, which fall into three systemic patterns:

1. **Timing/Ordering Issues** - Data processing order mismatches
2. **Validation Gaps** - Scripts not matching production behavior
3. **Infrastructure Misconfigurations** - Build context and schema issues

---

## Table of Contents

1. [Issue 1: MIA@CHI Missing Data](#issue-1-miachi-missing-data)
2. [Issue 2: Spot Check False Positives](#issue-2-spot-check-false-positives)
3. [Issue 3: Scraper Parameter Errors](#issue-3-scraper-parameter-errors)
4. [Issue 4: Prediction-worker Build Failure](#issue-4-prediction-worker-build-failure)
5. [Issue 5: MIA@CHI Predictions Not Generated](#issue-5-miachi-predictions-not-generated)
6. [Pattern Analysis](#pattern-analysis)
7. [Systemic Improvements](#systemic-improvements)
8. [Implementation Roadmap](#implementation-roadmap)

---

## Issue 1: MIA@CHI Missing Data

### What Happened (Symptom)
- The MIA@CHI game on 2026-01-29 had 0 players in the feature store
- Handoff documents initially stated data "cannot be recovered"
- 7 games instead of 8 were processed, reducing prediction coverage by ~12%

### Why It Happened (Root Cause)
**Primary Cause:** NBA.com reuses `game_id` values across different game dates.

The `game_id` `0022500529` appeared in two records:
- 2026-01-08: MIA@CHI (Final, status=3)
- 2026-01-29: MIA@CHI (Scheduled, status=1)

The view `v_nbac_schedule_latest` used deduplication logic:
```sql
-- BUGGY: Only partitioned by game_id
PARTITION BY game_id
ORDER BY game_status DESC, processed_at DESC
```

This caused the Final game (status=3) to "win" over the Scheduled game (status=1), hiding today's game.

**Secondary Cause:** View fix was deployed AFTER Phase 4 data processing had already run for the day. The feature store processor didn't see the MIA@CHI game because the view still had the old (buggy) data when it ran.

### Why Wasn't It Caught Earlier

| Gap | Description | Impact |
|-----|-------------|--------|
| No game count validation | No check comparing scheduled games vs processed games | MIA@CHI silently dropped |
| View deduplication not tested with real-world edge cases | NBA.com game_id reuse pattern unknown | Bug went undetected for months |
| Handoff docs missed recovery option | Re-triggering Phase 4 after view fix would have worked | Data wrongly marked as "unrecoverable" |

### How to Prevent (Specific Changes)

#### 1. Add Game Count Validation to Phase 4
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

```python
def _validate_game_coverage(self, game_date: date) -> None:
    """Verify all scheduled games have features generated."""

    # Count scheduled games from view
    scheduled_query = f"""
    SELECT COUNT(DISTINCT game_id) as scheduled
    FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
    WHERE game_date = '{game_date}' AND game_status = 1
    """

    # Count games in feature store
    processed_query = f"""
    SELECT COUNT(DISTINCT game_id) as processed
    FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
    WHERE game_date = '{game_date}'
    """

    scheduled = self._run_query(scheduled_query)[0]['scheduled']
    processed = self._run_query(processed_query)[0]['processed']

    if processed < scheduled:
        missing = scheduled - processed
        logger.error(f"GAME_COVERAGE_GAP: {missing} games missing from feature store")
        notify_warning(
            title="Game Coverage Gap Detected",
            message=f"{missing} scheduled games not in feature store for {game_date}",
            processor_name=self.__class__.__name__
        )
```

#### 2. Add game_id Collision Detection to Scraper
**File:** `scrapers/nbacom/nbac_scoreboard_v2.py`

```python
def _detect_game_id_collision(self, decoded_data: dict) -> None:
    """Alert when same game_id appears with different game_dates."""

    for game in decoded_data.get('scoreboard', {}).get('games', []):
        game_id = game.get('gameId')
        game_date = game.get('gameDate')

        # Check if this game_id exists with a different date
        query = f"""
        SELECT DISTINCT game_date
        FROM `{self.project_id}.nba_raw.nbac_scoreboard`
        WHERE game_id = '{game_id}'
          AND game_date != '{game_date}'
        """

        existing_dates = self._run_query(query)
        if existing_dates:
            logger.warning(
                f"GAME_ID_COLLISION: {game_id} exists for {existing_dates}, "
                f"new occurrence on {game_date}"
            )
```

### Resilience Improvements (Self-Healing)

1. **Automatic Re-trigger on View Changes**
   - Monitor view DDL changes in BigQuery audit logs
   - Auto-trigger affected downstream processors when views are updated

2. **End-of-Day Reconciliation Job**
   - Compare scheduled games vs processed games at 11:59 PM
   - Auto-trigger Phase 4 re-processing for any missing games

---

## Issue 2: Spot Check False Positives

### What Happened (Symptom)
The spot check script (`bin/spot_check_features.py`) flagged two players as having incorrect features:
- `kellyoubrejr`: Reported rolling average mismatch
- `jordanmclaughlin`: Reported points average mismatch

Upon investigation, both were false positives caused by script logic not matching production processor behavior.

### Why It Happened (Root Cause)

**Issue 2a: kellyoubrejr (DNP Game Filtering)**

The production processor (`ml_feature_store_processor.py`) filters out DNP (Did Not Play) games when calculating rolling averages. The spot check script queries raw `player_game_summary` without this filter.

```python
# Production processor (correct)
WHERE minutes_played > 0  # Excludes DNP games

# Spot check script (incorrect)
# No minutes filter - includes DNP games where points=0
```

When a player has a DNP game (minutes_played=0, points=0), including it in the average lowers the calculated value vs excluding it.

**Issue 2b: jordanmclaughlin (Decimal Precision)**

The spot check script uses rounded minutes from `player_game_summary`, while the production processor may use more precise decimal values from the source data.

```python
# Spot check: Uses ROUND(minutes_played) -> 32
# Production: Uses precise value -> 32.45

# This causes ~1.4% difference in calculations
```

### Why Wasn't It Caught Earlier

| Gap | Description | Impact |
|-----|-------------|--------|
| Script vs Processor logic divergence | Script was written independently | False positives undermine trust in validation |
| No unit tests comparing script to processor | Logic drift over time | Developers don't know when behavior differs |
| Documentation unclear on DNP handling | Different interpretations possible | Easy to implement differently |

### How to Prevent (Specific Changes)

#### 1. Fix DNP Filtering in Spot Check Script
**File:** `bin/spot_check_features.py`

```python
def get_raw_games(client, player_lookup: str, before_date: date, limit: int = 10) -> List[Dict]:
    """Get raw game data from player_game_summary.

    IMPORTANT: Must match production processor behavior by filtering out DNP games
    (games where minutes_played = 0 or minutes_played IS NULL).
    """
    query = f"""
    SELECT
        game_date,
        points,
        minutes_played,
        ft_makes,
        fg_attempts,
        paint_attempts,
        mid_range_attempts,
        three_pt_attempts
    FROM `nba-props-platform.nba_analytics.player_game_summary`
    WHERE player_lookup = '{player_lookup}'
      AND game_date < '{before_date}'
      AND minutes_played > 0  -- CRITICAL: Filter DNP games like processor does
    ORDER BY game_date DESC
    LIMIT {limit}
    """
    result = client.query(query).to_dataframe()
    return result.to_dict('records')
```

#### 2. Use Consistent Decimal Precision
**File:** `bin/spot_check_features.py`

```python
def calculate_expected_avg(games: List[Dict], field: str, count: int) -> Optional[float]:
    """Calculate expected average from raw games.

    Uses same precision as production processor (no rounding).
    """
    if len(games) < count:
        return None

    # Use raw float values, not rounded
    values = [float(g[field]) for g in games[:count] if g[field] is not None]
    if not values:
        return None

    # Return with same precision as processor
    return sum(values) / len(values)
```

#### 3. Add Shared Constants Module
**File:** `shared/constants/feature_calculation.py`

```python
"""
Shared constants for feature calculations.

These constants MUST be used by:
- data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
- bin/spot_check_features.py
- scripts/spot_check_data_accuracy.py

To ensure identical behavior across production and validation.
"""

# DNP threshold: games with minutes below this are excluded from averages
DNP_MINUTES_THRESHOLD = 0.0  # minutes_played > 0

# Rolling window sizes
ROLLING_WINDOW_5 = 5
ROLLING_WINDOW_10 = 10

# Tolerance for validation comparisons (% difference allowed)
VALIDATION_TOLERANCE = 0.01  # 1%
```

### Resilience Improvements (Self-Healing)

1. **Property-Based Testing**
   - Add tests that verify spot check script produces same results as processor
   - Run on CI for every PR touching either file

2. **Shared Calculation Module**
   - Extract rolling average calculation to shared module
   - Both processor and spot check import same code

---

## Issue 3: Scraper Parameter Errors

### What Happened (Symptom)
Scraper errors in BigQuery showing:
- Parameter resolver returns `'date'` instead of `'gamedate'` when no games are scheduled
- BigQuery INSERT fails because `game_date` gets NULL value instead of the expected date string

### Why It Happened (Root Cause)

The scraper's `set_additional_opts()` method (in `config_mixin.py`) derives the `date` opt from `gamedate`:

```python
# From config_mixin.py lines 141-167
def set_additional_opts(self):
    # Add Eastern date if not provided as parameter
    if "date" not in self.opts:
        # Derive from existing parameters first
        if "gamedate" in self.opts:
            gamedate = self.opts["gamedate"]
            # Convert YYYYMMDD to YYYY-MM-DD
            self.opts["date"] = f"{gamedate[:4]}-{gamedate[4:6]}-{gamedate[6:8]}"
```

When there are no games for a date:
1. The schedule scraper returns empty data
2. Parameter resolver doesn't set `gamedate` (no games to process)
3. `set_additional_opts()` falls through to Eastern timezone date
4. But BigQuery schema expects `game_date` field from the scraper opts
5. Field mismatch causes NULL value in required column

### Why Wasn't It Caught Earlier

| Gap | Description | Impact |
|-----|-------------|--------|
| No unit tests for "no games" scenario | Edge case not covered | Breaks on off-days |
| Parameter naming inconsistency | `gamedate` vs `game_date` vs `date` | Easy to use wrong name |
| Schema validation doesn't catch NULL dates | Validation runs after INSERT attempt | Error surfaces too late |

### How to Prevent (Specific Changes)

#### 1. Add Consistent Date Parameter Handling
**File:** `scrapers/mixins/config_mixin.py`

```python
def set_additional_opts(self):
    """Set derived options with consistent date handling."""

    # Normalize date parameters to both formats
    date_value = None

    # Try all known date parameter names
    for key in ['gamedate', 'game_date', 'date']:
        if key in self.opts and self.opts[key]:
            raw_date = self.opts[key]
            if len(raw_date) == 8 and raw_date.isdigit():
                date_value = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            else:
                date_value = raw_date
            break

    # Fallback to Eastern timezone current date
    if not date_value:
        try:
            import pytz
            eastern = pytz.timezone('US/Eastern')
            date_value = datetime.now(eastern).strftime("%Y-%m-%d")
        except (ImportError, KeyError):
            date_value = datetime.utcnow().strftime("%Y-%m-%d")

    # Set BOTH formats for downstream compatibility
    self.opts["date"] = date_value
    self.opts["game_date"] = date_value
    self.opts["gamedate"] = date_value.replace("-", "")

    logger.debug(f"Normalized date opts: date={date_value}")
```

#### 2. Add Pre-Insert Validation
**File:** `scrapers/exporters/bigquery_exporter.py`

```python
def _validate_required_fields(self, records: List[Dict], schema: dict) -> None:
    """Validate required fields before INSERT."""

    required_fields = [
        field.name for field in schema
        if field.mode == 'REQUIRED'
    ]

    for i, record in enumerate(records):
        for field in required_fields:
            if field not in record or record[field] is None:
                raise ValueError(
                    f"Record {i}: Required field '{field}' is missing or NULL"
                )
```

### Resilience Improvements (Self-Healing)

1. **Graceful "No Games" Handling**
   - When no games scheduled, log info and exit cleanly
   - Don't attempt BigQuery write with empty/incomplete data

2. **Date Parameter Validation Hook**
   - Add `validate_date_params()` in scraper base class
   - Raises clear error if date parameters missing on game days

---

## Issue 4: Prediction-worker Build Failure

### What Happened (Symptom)
Dockerfile for prediction-worker fails to build because it expects `shared/` module in build context, but deployment runs from `./predictions/worker` directory.

```dockerfile
# predictions/worker/Dockerfile line 27
COPY shared/ ./shared/
```

When running `gcloud run deploy` from the worker directory, `shared/` doesn't exist in the context.

### Why It Happened (Root Cause)

**Incorrect Build Context Assumption**

The Dockerfile was written assuming builds run from repository root:
```bash
# Expected (from repo root):
docker build -f predictions/worker/Dockerfile -t worker .

# Actual (from worker directory):
cd predictions/worker && gcloud run deploy
```

The Dockerfile comment even documents this requirement (line 4-5):
```dockerfile
# Build from repository root to include shared/ module:
#   docker build -f predictions/worker/Dockerfile -t worker .
```

But deployment automation didn't follow this pattern.

### Why Wasn't It Caught Earlier

| Gap | Description | Impact |
|-----|-------------|--------|
| Manual deployment process | Each deployer may use different commands | Inconsistent behavior |
| No CI/CD pipeline | No automated build verification | Build issues found late |
| Docker build context not documented in deployment runbook | Easy to run from wrong directory | Deployment failures |

### How to Prevent (Specific Changes)

#### 1. Add Build Context Verification
**File:** `predictions/worker/Dockerfile`

```dockerfile
# Verify build context includes shared/ module
RUN if [ ! -d "./shared" ]; then \
      echo "ERROR: Build context missing shared/ module."; \
      echo "Build from repository root:"; \
      echo "  docker build -f predictions/worker/Dockerfile -t worker ."; \
      exit 1; \
    fi
```

#### 2. Create Deployment Script
**File:** `bin/deploy-prediction-worker.sh`

```bash
#!/bin/bash
# Deploy prediction-worker with correct build context

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$REPO_ROOT"

echo "Building from repository root: $REPO_ROOT"
echo "Dockerfile: predictions/worker/Dockerfile"

# Build with correct context
docker build \
  -f predictions/worker/Dockerfile \
  -t us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest \
  --build-arg BUILD_COMMIT=$(git rev-parse HEAD) \
  --build-arg BUILD_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  .

# Push and deploy
docker push us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest

gcloud run deploy prediction-worker \
  --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/prediction-worker:latest \
  --region=us-west2
```

#### 3. Update Deployment Runbook
**File:** `docs/02-operations/deployment-runbook.md`

Add explicit section:
```markdown
## Prediction Worker Deployment

**IMPORTANT:** Must build from repository root, not worker directory.

### Correct Command
```bash
# From repo root
./bin/deploy-prediction-worker.sh
```

### Why
The worker Dockerfile copies `shared/` module from repo root. Building from
`predictions/worker/` directory fails because `shared/` is not in context.
```

### Resilience Improvements (Self-Healing)

1. **CI/CD Build Pipeline**
   - GitHub Actions workflow builds on every merge
   - Build failure blocks deployment

2. **Drift Detection for Dockerfiles**
   - Weekly check that all Dockerfiles build successfully
   - Alert if any build fails

---

## Issue 5: MIA@CHI Predictions Not Generated

### What Happened (Symptom)
After the view fix was deployed and feature store was supposedly populated for MIA@CHI:
- Feature store showed 0 players for MIA@CHI
- Predictions showed 7 games instead of 8
- The prediction job ran but didn't generate MIA@CHI predictions

### Why It Happened (Root Cause)

This is a **cascade failure** from Issue 1:

1. **Timing:** View fix deployed at ~11:30 PM
2. **Phase 4 ran earlier:** ML Feature Store processor ran at 12:00 AM (before view fix)
3. **Feature store empty:** No MIA@CHI features existed when prediction job ran
4. **Prediction job skipped:** No features = no predictions generated

The prediction job queries the feature store:
```sql
SELECT player_lookup, features, ...
FROM ml_feature_store_v2
WHERE game_date = '2026-01-29'
```

Since MIA@CHI had 0 rows, no predictions could be generated.

**Why Re-triggering Phase 4 Would Have Worked:**
If Phase 4 was re-run after the view fix:
1. View would now return MIA@CHI game (status=1)
2. Feature store would populate ~35 MIA+CHI players
3. Prediction job would generate predictions for those players

### Why Wasn't It Caught Earlier

| Gap | Description | Impact |
|-----|-------------|--------|
| No automatic dependency re-trigger | View fix doesn't trigger downstream reprocessing | Stale data persists |
| Handoff docs said "unrecoverable" | Led to abandoning recovery attempts | Missed easy fix |
| No data freshness validation | Predictions don't check if features are up-to-date | Stale predictions |

### How to Prevent (Specific Changes)

#### 1. Add Feature Store Freshness Check
**File:** `predictions/coordinator/coordinator.py`

```python
def _validate_feature_freshness(self, game_date: date) -> bool:
    """Verify feature store has recent data for all scheduled games."""

    # Get scheduled games
    scheduled_query = f"""
    SELECT DISTINCT game_id, home_team_abbr, away_team_abbr
    FROM `{self.project_id}.nba_raw.v_nbac_schedule_latest`
    WHERE game_date = '{game_date}' AND game_status = 1
    """
    scheduled_games = self._run_query(scheduled_query)

    # Get games in feature store
    feature_query = f"""
    SELECT DISTINCT game_id
    FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
    WHERE game_date = '{game_date}'
    """
    feature_games = set(r['game_id'] for r in self._run_query(feature_query))

    # Find missing games
    missing = []
    for game in scheduled_games:
        if game['game_id'] not in feature_games:
            missing.append(f"{game['away_team_abbr']}@{game['home_team_abbr']}")

    if missing:
        logger.error(f"FEATURE_STORE_GAP: Missing games: {missing}")
        notify_error(
            title="Feature Store Gap - Predictions Blocked",
            message=f"Cannot generate predictions for {len(missing)} games: {missing}",
            processor_name="PredictionCoordinator"
        )
        return False

    return True
```

#### 2. Add View Change Trigger
**File:** `.github/workflows/view-change-retrigger.yml`

```yaml
name: Re-trigger Downstream on View Changes

on:
  push:
    paths:
      - 'schemas/bigquery/raw/*.sql'

jobs:
  detect-and-retrigger:
    runs-on: ubuntu-latest
    steps:
      - name: Detect view changes
        id: detect
        run: |
          # Check if any view DDL files changed
          VIEWS=$(git diff --name-only HEAD~1 HEAD | grep 'schemas/bigquery/raw/')
          echo "changed_views=$VIEWS" >> $GITHUB_OUTPUT

      - name: Trigger Phase 4 reprocessing
        if: steps.detect.outputs.changed_views != ''
        run: |
          # Trigger Phase 4 via Cloud Scheduler
          gcloud scheduler jobs run phase4-ml-feature-store --location=us-west2
```

### Resilience Improvements (Self-Healing)

1. **Automatic Data Gap Recovery**
   - Hourly check for games with features but no predictions
   - Auto-trigger prediction job for missing games

2. **End-of-Day Reconciliation**
   - At 6 PM (before games start), verify all games have predictions
   - Alert + auto-reprocess if gaps found

---

## Pattern Analysis

### Common Themes Across Issues

| Pattern | Issues Affected | Root Cause |
|---------|-----------------|------------|
| **Timing/Ordering** | #1, #5 | Deployment/processing order not enforced |
| **Validation Gaps** | #2, #3 | Scripts don't match production behavior |
| **Build/Config** | #4 | Infrastructure assumptions not documented |

### Theme 1: Timing and Ordering Dependencies

**Issues:** MIA@CHI missing (#1), Predictions not generated (#5)

**Root Cause:** The system assumes a specific order of operations:
1. Views are updated first
2. Phase 4 runs next
3. Predictions run last

When this order is violated (view fix deployed AFTER Phase 4), the system breaks silently.

**Systemic Fix:** Implement dependency tracking that:
- Records when each component was last updated
- Blocks downstream processing if upstream is stale
- Auto-triggers re-processing when upstream changes

### Theme 2: Script vs Production Divergence

**Issues:** Spot check false positives (#2), Parameter resolver (#3)

**Root Cause:** Validation/utility scripts were written separately from production code, leading to behavioral differences.

**Systemic Fix:**
- Extract shared logic to common modules
- Both scripts and production code import same functions
- Unit tests verify identical behavior

### Theme 3: Infrastructure Assumptions

**Issues:** Docker build context (#4)

**Root Cause:** Infrastructure requirements documented in code comments but not enforced by tooling.

**Systemic Fix:**
- Self-documenting build scripts
- CI/CD that enforces correct patterns
- Build-time validation of assumptions

---

## Systemic Improvements

### 1. Dependency-Aware Processing (DAG)

**Problem:** Components run independently without checking upstream freshness.

**Solution:** Implement a lightweight DAG (Directed Acyclic Graph) for data dependencies:

```python
# shared/orchestration/dag.py

PROCESSING_DAG = {
    'v_nbac_schedule_latest': {
        'type': 'view',
        'depends_on': ['nbac_scoreboard'],
        'triggers': ['ml_feature_store_v2']
    },
    'ml_feature_store_v2': {
        'type': 'table',
        'depends_on': ['v_nbac_schedule_latest', 'player_daily_cache'],
        'triggers': ['player_prop_predictions']
    },
    'player_prop_predictions': {
        'type': 'table',
        'depends_on': ['ml_feature_store_v2'],
        'triggers': []
    }
}

def should_reprocess(table: str) -> bool:
    """Check if table needs reprocessing due to upstream changes."""
    deps = PROCESSING_DAG[table]['depends_on']
    table_updated = get_last_update(table)

    for dep in deps:
        dep_updated = get_last_update(dep)
        if dep_updated > table_updated:
            logger.info(f"{table} stale: {dep} updated at {dep_updated}")
            return True

    return False
```

### 2. Unified Validation Framework

**Problem:** Multiple validation scripts with divergent logic.

**Solution:** Single validation framework with shared calculation logic:

```
shared/
  validation/
    __init__.py
    calculations.py     # Shared formulas (rolling avg, etc.)
    constants.py        # Shared thresholds
    framework.py        # Base validator class

bin/
  spot_check_features.py    # Uses shared/validation/

scripts/
  spot_check_data_accuracy.py  # Uses shared/validation/

data_processors/
  precompute/
    ml_feature_store/
      feature_calculator.py  # Uses shared/validation/
```

### 3. Deployment Automation

**Problem:** Manual deployments lead to inconsistent results.

**Solution:** CI/CD pipeline that enforces correct patterns:

```yaml
# .github/workflows/deploy.yml

jobs:
  build:
    steps:
      - name: Build all Dockerfiles from repo root
        run: |
          for df in $(find . -name "Dockerfile"); do
            dir=$(dirname $df)
            service=$(basename $dir)
            docker build -f $df -t $service .
          done

  deploy:
    needs: build
    steps:
      - name: Deploy with drift detection
        run: |
          ./bin/deploy-with-drift-check.sh
```

### 4. Real-Time Data Quality Dashboard

**Problem:** Issues discovered reactively, often too late.

**Solution:** Dashboard showing:
- Scheduled games vs processed games (per phase)
- Feature store coverage (% of players with features)
- Prediction coverage (% of players with lines who have predictions)
- Data freshness (time since last update per table)

---

## Implementation Roadmap

### Phase 1: Immediate (This Week)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| Fix DNP filtering in spot check | P0 | 1 hour | `bin/spot_check_features.py` |
| Add game count validation | P0 | 2 hours | `ml_feature_store_processor.py` |
| Create deployment script | P1 | 1 hour | `bin/deploy-prediction-worker.sh` |
| Add date parameter normalization | P1 | 2 hours | `config_mixin.py` |

### Phase 2: Short-Term (Next 2 Weeks)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| Create shared validation module | P1 | 4 hours | `shared/validation/` |
| Add feature freshness check | P1 | 2 hours | `coordinator.py` |
| Implement game_id collision detection | P2 | 2 hours | `nbac_scoreboard_v2.py` |
| Add CI/CD build workflow | P2 | 4 hours | `.github/workflows/` |

### Phase 3: Medium-Term (Next Month)

| Task | Priority | Effort | Files |
|------|----------|--------|-------|
| Implement DAG-based reprocessing | P2 | 8 hours | `shared/orchestration/` |
| Create data quality dashboard | P2 | 8 hours | `monitoring/dashboard/` |
| Add property-based tests | P3 | 4 hours | `tests/property/` |

---

## Appendix: Issue Quick Reference

| Issue | Root Cause | Quick Fix | Systemic Fix |
|-------|-----------|-----------|--------------|
| MIA@CHI Missing | game_id reuse + view dedup | Re-run Phase 4 | DAG reprocessing |
| Spot Check FPs | DNP filter missing | Add `minutes_played > 0` | Shared calculations |
| Parameter Error | Inconsistent date names | Normalize all 3 formats | Single date handler |
| Build Failure | Wrong build context | Deploy script | CI/CD enforcement |
| No Predictions | Feature store empty | Re-run prediction job | Freshness validation |

---

*Document Created: 2026-01-29*
*Author: Claude Opus 4.5*
*For Session 24 and Future Reference*
