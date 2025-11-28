# NBA Props Platform - Source Coverage System Design
## Part 4: Testing & Operations

**Created:** 2025-11-26
**Parent Document:** [Part 1: Core Design & Architecture](01-core-design.md)

---

## Table of Contents

1. [Testing Strategy](#testing-strategy)
2. [Operational Procedures](#operational-procedures)
3. [Monitoring & Dashboards](#monitoring--dashboards)
4. [Troubleshooting Guide](#troubleshooting-guide)
5. [Performance Tuning](#performance-tuning)

---

## Testing Strategy

### Unit Tests

#### File: `/tests/unit/test_quality_mixin.py`

```python
"""
Unit tests for QualityMixin
"""

import pytest
import pandas as pd
from datetime import date
from shared_services.processors.quality_mixin import QualityMixin
from shared_services.constants.source_coverage import QualityTier


class TestQualityMixin:

    @pytest.fixture
    def mixin(self):
        """Create test instance"""
        class TestProcessor(QualityMixin):
            REQUIRED_FIELDS = ['points', 'rebounds']
            OPTIONAL_FIELDS = ['plus_minus', 'shot_zones']
            FIELD_WEIGHTS = {
                'points': 10.0,
                'rebounds': 8.0,
                'plus_minus': 3.0,
                'shot_zones': 5.0
            }

        return TestProcessor()

    def test_complete_data_gold_tier(self, mixin):
        """Test perfect data gets gold tier"""
        data = pd.DataFrame({
            'points': [25, 30, 18],
            'rebounds': [8, 10, 5],
            'plus_minus': [5, -2, 3],
            'shot_zones': ['paint', 'perimeter', 'midrange']
        })

        quality = mixin.assess_quality(
            data=data,
            sources_used=['primary'],
            reconstruction_applied=False
        )

        assert quality['tier'] == QualityTier.GOLD
        assert quality['score'] >= 95
        assert len(quality['issues']) == 0

    def test_missing_required_unusable(self, mixin):
        """Test missing required field = unusable"""
        data = pd.DataFrame({
            'points': [25, 30],
            # Missing 'rebounds' (required)
            'plus_minus': [5, -2]
        })

        quality = mixin.assess_quality(
            data=data,
            sources_used=['primary']
        )

        assert quality['tier'] == QualityTier.UNUSABLE
        assert quality['score'] == 0.0
        assert 'missing_required:rebounds' in quality['issues']

    def test_backup_source_degrades_to_silver(self, mixin):
        """Test backup source usage degrades tier"""
        data = pd.DataFrame({
            'points': [25],
            'rebounds': [8],
            'plus_minus': [5],
            'shot_zones': ['paint']
        })

        quality = mixin.assess_quality(
            data=data,
            sources_used=['espn_backup'],  # Not primary
            reconstruction_applied=False
        )

        assert quality['tier'] == QualityTier.SILVER
        assert quality['score'] >= 75

    def test_thin_sample_bronze(self, mixin):
        """Test thin sample = bronze tier"""
        data = pd.DataFrame({
            'points': [25, 30],  # Only 2 samples
            'rebounds': [8, 10]
        })

        quality = mixin.assess_quality(
            data=data,
            sources_used=['primary'],
            context={'expected_sample_size': 10}
        )

        assert quality['tier'] == QualityTier.BRONZE
        assert 'thin_sample:2/10' in quality['issues']

    def test_early_season_relaxed_threshold(self, mixin):
        """Early season accepts smaller samples without bronze"""
        data = pd.DataFrame({
            'points': [25, 30, 18],  # Only 3 games
            'rebounds': [8, 10, 5]
        })

        # First week of season
        early_date = date(2024, 10, 25)

        quality = mixin.assess_quality(
            data=data,
            sources_used=['primary'],
            game_date=early_date
        )

        # Should NOT be bronze because early season expects small samples
        assert quality['tier'] in [QualityTier.GOLD, QualityTier.SILVER]
        assert quality['metadata']['early_season'] == True

    def test_mid_season_normal_threshold(self, mixin):
        """Mid-season applies normal thresholds"""
        data = pd.DataFrame({
            'points': [25, 30, 18],  # Only 3 games
            'rebounds': [8, 10, 5]
        })

        # Mid-season (January)
        mid_date = date(2025, 1, 15)

        quality = mixin.assess_quality(
            data=data,
            sources_used=['primary'],
            game_date=mid_date
        )

        # Should be bronze due to thin sample
        assert quality['tier'] == QualityTier.BRONZE
        assert quality['metadata']['early_season'] == False


class TestQualityMixinEdgeCases:
    """Edge case tests"""

    @pytest.fixture
    def mixin(self):
        class TestProcessor(QualityMixin):
            REQUIRED_FIELDS = ['points', 'rebounds']
            OPTIONAL_FIELDS = ['plus_minus']
        return TestProcessor()

    def test_empty_dataframe(self, mixin):
        """Handle empty DataFrame gracefully"""
        data = pd.DataFrame(columns=['points', 'rebounds'])

        quality = mixin.assess_quality(
            data=data,
            sources_used=['primary']
        )

        # Empty data should still assess
        assert quality['metadata']['sample_size'] == 0

    def test_all_null_optional_fields(self, mixin):
        """Handle all nulls in optional fields"""
        data = pd.DataFrame({
            'points': [25, 30, 18],
            'rebounds': [8, 10, 5],
            'plus_minus': [None, None, None]  # All nulls
        })

        quality = mixin.assess_quality(
            data=data,
            sources_used=['primary']
        )

        # Should degrade due to high null rate
        assert quality['score'] < 95

    def test_reconstruction_caps_at_silver(self, mixin):
        """Reconstructed data can never be gold"""
        data = pd.DataFrame({
            'points': [25, 30, 18, 22, 28, 20, 24, 26, 19, 21],
            'rebounds': [8, 10, 5, 7, 9, 6, 8, 11, 4, 7]
        })

        # Perfect data but reconstructed
        quality = mixin.assess_quality(
            data=data,
            sources_used=['reconstructed'],
            reconstruction_applied=True
        )

        # Even with perfect score, reconstruction caps at silver
        assert quality['tier'] == QualityTier.SILVER
```

### Integration Tests

> **⚠️ IMPLEMENTATION REQUIRED**
>
> These tests are placeholders. **Do not deploy without implementing real tests.**
>
> **Required test coverage before production:**
> 1. Fallback cascade (primary fails → backup succeeds → quality=silver)
> 2. Quality propagation Phase 3 → 4 → 5
> 3. Audit job detecting missing games
> 4. Alert deduplication (verify no alert storm)
> 5. Event buffering (verify single batch load, not per-event)

#### File: `/tests/integration/test_source_coverage_flow.py`

```python
"""
Integration tests for full source coverage flow

STATUS: IMPLEMENTATION REQUIRED
These are skeleton tests that MUST be implemented before deployment.
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch


class TestSourceCoverageFlow:

    @pytest.fixture
    def test_db(self):
        """Create test database fixture with isolated dataset"""
        # TODO: Implement test database setup
        # Options:
        # 1. Use BigQuery test dataset with cleanup
        # 2. Use SQLite for local testing
        # 3. Mock BigQuery client
        raise NotImplementedError("Test fixture required")

    def test_end_to_end_with_fallback(self, test_db):
        """
        Test full pipeline with fallback source.

        Scenario:
        1. Primary source (NBA.com) returns empty
        2. Fallback source (ESPN) has data
        3. Result should have quality_tier='silver'
        4. Event should be logged with event_type='fallback_used'
        """
        # TODO: Implement
        # 1. Setup: Mock primary source to return empty DataFrame
        # 2. Setup: Mock fallback source to return valid data
        # 3. Run Phase 3 processor
        # 4. Assert: quality_tier == 'silver'
        # 5. Assert: Event logged to source_coverage_log
        raise NotImplementedError("Test implementation required")

    def test_quality_propagates_phase3_to_phase5(self, test_db):
        """
        Test quality propagates through pipeline.

        Scenario:
        1. Phase 3 has 10 games: 9 gold, 1 bronze
        2. Phase 4 aggregates them
        3. Result should be bronze (worst wins)
        """
        # TODO: Implement
        # 1. Insert test data into Phase 3 with mixed quality
        # 2. Run Phase 4 processor
        # 3. Assert: Phase 4 output quality_tier == 'bronze'
        raise NotImplementedError("Test implementation required")

    def test_audit_catches_silent_failure(self, test_db):
        """
        Test audit job detects missing game.

        Scenario:
        1. Game in schedule
        2. Game NOT in any data tables
        3. Audit should create synthetic event
        """
        # TODO: Implement
        # 1. Insert game into schedule table
        # 2. Do NOT process the game
        # 3. Run audit processor
        # 4. Assert: Synthetic event created with is_synthetic=True
        raise NotImplementedError("Test implementation required")

    def test_alert_deduplication(self, test_db):
        """
        Test that duplicate alerts are suppressed.

        Scenario:
        1. First event for source_missing → alert sent
        2. Second event (same type, same source) → alert NOT sent
        """
        # TODO: Implement
        # This is CRITICAL to prevent alert storms during outages
        raise NotImplementedError("Test implementation required")

    def test_event_buffering_batches_correctly(self, test_db):
        """
        Test that events are buffered and written in single batch.

        Scenario:
        1. Process game with 13 players
        2. Should result in 1 BigQuery load job, not 13
        """
        # TODO: Implement
        # 1. Mock BigQuery client
        # 2. Process game
        # 3. Assert: load_table_from_json called once, not 13 times
        raise NotImplementedError("Test implementation required")
```

**Recommended test implementation order:**
1. `test_alert_deduplication` - Prevents production alert storms
2. `test_end_to_end_with_fallback` - Core functionality
3. `test_audit_catches_silent_failure` - Catches edge cases
4. `test_quality_propagates_phase3_to_phase5` - Validates design
5. `test_event_buffering_batches_correctly` - Performance validation

---

## Operational Procedures

### Daily Operations

#### Morning Check (7 AM PT)

```sql
-- Quick quality distribution check for yesterday
SELECT
  quality_tier,
  COUNT(*) as game_count,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
FROM nba_analytics.player_game_summary
WHERE game_date = CURRENT_DATE() - 1
GROUP BY quality_tier
ORDER BY
  CASE quality_tier
    WHEN 'gold' THEN 1
    WHEN 'silver' THEN 2
    WHEN 'bronze' THEN 3
    WHEN 'poor' THEN 4
    ELSE 5
  END;

-- Expected results:
-- gold:   80-90%
-- silver: 10-20%
-- bronze: <5%
-- poor:   0%
```

**If Bronze > 10% or any Poor:**
1. Check source status (is NBA.com down?)
2. Review coverage log for patterns
3. Investigate affected games

#### Unresolved Issues Check

```sql
-- Check for unresolved critical issues
SELECT
  game_id,
  game_date,
  event_type,
  description,
  TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), event_timestamp, HOUR) as hours_open
FROM nba_reference.source_coverage_log
WHERE severity = 'critical'
  AND is_resolved = FALSE
  AND DATE(event_timestamp) >= CURRENT_DATE() - 7
ORDER BY event_timestamp DESC;
```

### Weekly Review (Every Monday)

#### 1. Quality Trends

```sql
-- Weekly quality distribution
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  quality_tier,
  COUNT(*) as games
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY week, quality_tier
ORDER BY week DESC, quality_tier;
```

#### 2. Source Reliability

```sql
-- Which sources are most reliable?
SELECT
  UNNEST(data_sources) as source,
  COUNT(*) as uses,
  AVG(quality_score) as avg_quality,
  COUNTIF(quality_tier = 'gold') as gold_count
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY source
ORDER BY uses DESC;
```

#### 3. Top Issues

```sql
-- Most common quality issues
SELECT
  UNNEST(quality_issues) as issue,
  COUNT(*) as occurrences
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 7
  AND ARRAY_LENGTH(quality_issues) > 0
GROUP BY issue
ORDER BY occurrences DESC
LIMIT 10;
```

### Handling Critical Alerts

#### Alert: "Missing team boxscore for game X"

**Step 1: Check Source Status**
```bash
# Is NBA.com accessible?
curl https://stats.nba.com/stats/boxscoretraditionalv2?GameID=X

# Response codes:
# 200: API working, data issue
# 4xx: Request problem
# 5xx: API down
```

**Step 2: Try Manual Alternatives**
- ESPN website
- Basketball Reference
- NBA.com game page (non-API)

**Step 3: Decision Tree**
```
Can get data manually?
  YES -> Manual entry to raw table -> Reprocess
  NO  -> Check if game is recent
    Recent (< 7 days) -> Try again in 24h
    Old (> 7 days)    -> Accept gap, mark 'wont_fix'

Are predictions blocked?
  YES -> High priority, escalate
  NO  -> Log and monitor
```

**Step 4: Document Resolution**
```sql
UPDATE nba_reference.source_coverage_log
SET
  is_resolved = TRUE,
  resolved_at = CURRENT_TIMESTAMP(),
  resolution_method = 'manual_entry',
  resolved_by = 'your_username',
  resolution_details = 'Manually scraped from NBA.com website'
WHERE event_id = '<event_id>';
```

### Monthly Maintenance

#### 1. Review Alert Thresholds

- Are we getting too many alerts? Tune thresholds
- Are we missing issues? Lower thresholds
- Check alert response times

#### 2. Update Audit Tables List

If new tables added to pipeline:

```python
# In source_coverage_audit.py
AUDIT_CHECK_TABLES = [
    # Add new tables here
    ('nba_new_table', 'game_id'),
    # ...
]
```

---

## Reprocessing Cascade Workflow

> **⚠️ CRITICAL PROCEDURE**
>
> When you backfill or reprocess upstream data (Phase 3), downstream quality (Phase 4/5)
> becomes **stale**. This procedure detects and fixes stale quality.

### When Reprocessing Is Needed

| Trigger | Action |
|---------|--------|
| Phase 3 backfill completed | Check Phase 4/5 staleness |
| Source coverage improved (bronze → gold) | Consider downstream reprocess |
| Historical data quality upgrade | Reprocess affected date ranges |
| Bug fix in quality calculation | Full reprocess of affected tables |

### Step 1: Detect Stale Downstream Quality

```sql
-- Find Phase 4 rows where upstream Phase 3 quality improved
-- These rows have stale quality that should be recalculated

WITH upstream_quality AS (
  SELECT
    universal_player_id,
    game_date,
    quality_tier,
    quality_score,
    quality_calculated_at
  FROM nba_analytics.player_game_summary
  WHERE game_date >= CURRENT_DATE() - 30  -- Adjust range as needed
),

downstream_quality AS (
  SELECT
    player_id,
    game_date,
    quality_tier,
    quality_score,
    quality_calculated_at
  FROM nba_precompute.player_rolling_averages
  WHERE game_date >= CURRENT_DATE() - 30
)

SELECT
  d.player_id,
  d.game_date,
  d.quality_tier as downstream_tier,
  d.quality_calculated_at as downstream_calc_time,
  COUNT(*) as upstream_games_newer,
  MIN(u.quality_tier) as best_upstream_tier
FROM downstream_quality d
JOIN upstream_quality u
  ON d.player_id = u.universal_player_id
  AND u.game_date BETWEEN DATE_SUB(d.game_date, INTERVAL 10 DAY) AND d.game_date
WHERE u.quality_calculated_at > d.quality_calculated_at  -- Upstream is newer
GROUP BY d.player_id, d.game_date, d.quality_tier, d.quality_calculated_at
HAVING COUNT(*) >= 3  -- At least 3 upstream games are newer
ORDER BY upstream_games_newer DESC;
```

**Interpreting Results:**
- `upstream_games_newer > 5`: High priority reprocess
- `upstream_games_newer 3-5`: Medium priority
- Rows where `best_upstream_tier > downstream_tier`: Quality may improve

### Step 2: Decision Framework

```
Stale rows detected?
  NO  -> Done, no action needed
  YES -> Check scope

Scope?
  < 100 rows -> Reprocess immediately
  100-1000 rows -> Schedule batch reprocess
  > 1000 rows -> Evaluate cost vs benefit

Quality improvement expected?
  bronze -> gold likely -> Reprocess (improves predictions)
  bronze -> bronze likely -> Skip (no benefit)

Predictions affected?
  YES (active prop lines) -> High priority
  NO (historical only) -> Lower priority, batch later
```

### Step 3: Execute Reprocessing

**Option A: Single Player Reprocess**
```bash
# Reprocess specific player's rolling averages
python -m data_processors.precompute.player_rolling_averages \
  --player_id "lebron_james_123" \
  --start_date "2024-12-01" \
  --end_date "2024-12-15"
```

**Option B: Date Range Reprocess**
```bash
# Reprocess all players for date range
python -m data_processors.precompute.player_rolling_averages \
  --start_date "2024-12-01" \
  --end_date "2024-12-15" \
  --force_recalculate
```

**Option C: Full Table Reprocess (Rare)**
```bash
# Only for major quality calculation changes
# WARNING: Expensive, run during off-hours
python -m data_processors.precompute.player_rolling_averages \
  --full_reprocess \
  --start_date "2024-10-01"
```

### Step 4: Verify Reprocessing

```sql
-- Verify downstream quality was updated
SELECT
  player_id,
  game_date,
  quality_tier,
  quality_calculated_at,
  quality_score
FROM nba_precompute.player_rolling_averages
WHERE player_id = 'lebron_james_123'
  AND game_date BETWEEN '2024-12-01' AND '2024-12-15'
ORDER BY game_date;

-- Check: quality_calculated_at should be recent
-- Check: quality_tier should reflect upstream quality
```

### Automation (Future Enhancement)

Currently: Manual detection + manual trigger
Future: Automatic detection + manual approval + automatic execution

```python
# Future: Add to daily audit job
def check_stale_quality():
    """Detect stale downstream quality and create reprocess recommendations."""
    stale_rows = run_staleness_query()

    if stale_rows > 100:
        notify_info(
            title="Stale Quality Detected",
            message=f"{stale_rows} downstream rows have stale quality",
            details={'query': 'Run staleness detection query for details'}
        )
```

---

## Monitoring & Dashboards

### Key Metrics to Track

#### 1. Daily Quality Score

```sql
-- Average quality score over time
SELECT
  game_date,
  AVG(quality_score) as avg_score,
  MIN(quality_score) as min_score,
  COUNT(*) as game_count
FROM nba_analytics.player_game_summary
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY game_date
ORDER BY game_date DESC;
```

**Dashboard:** Line chart showing avg_score over time
**Alert:** If avg_score < 80 for 3 consecutive days

#### 2. Source Availability Rate

```sql
-- Success rate per source
WITH source_attempts AS (
  SELECT
    primary_source,
    COUNTIF(resolution = 'used_fallback' OR resolution = 'failed') as failures,
    COUNT(*) as total_attempts
  FROM nba_reference.source_coverage_log
  WHERE DATE(event_timestamp) >= CURRENT_DATE() - 7
    AND primary_source IS NOT NULL
  GROUP BY primary_source
)
SELECT
  primary_source,
  total_attempts,
  failures,
  ROUND((total_attempts - failures) * 100.0 / total_attempts, 2) as success_rate
FROM source_attempts
ORDER BY success_rate;
```

**Dashboard:** Bar chart of success rates
**Alert:** If success_rate < 90% for any primary source

#### 3. Alert Volume

```sql
-- Alert trends
SELECT
  DATE(event_timestamp) as alert_date,
  severity,
  COUNT(*) as alert_count
FROM nba_reference.source_coverage_log
WHERE requires_alert = TRUE
  AND DATE(event_timestamp) >= CURRENT_DATE() - 30
GROUP BY alert_date, severity
ORDER BY alert_date DESC, severity;
```

**Alert:** If critical_count > 5 per day

#### 4. Unresolved Issue Age

```sql
-- How long are issues staying open?
SELECT
  severity,
  COUNT(*) as unresolved_count,
  AVG(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), event_timestamp, HOUR)) as avg_age_hours,
  MAX(TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), event_timestamp, HOUR)) as max_age_hours
FROM nba_reference.source_coverage_log
WHERE is_resolved = FALSE
  AND requires_alert = TRUE
GROUP BY severity;
```

**Alert:** If max_age_hours > 72 for critical

---

## Troubleshooting Guide

### Issue: High Bronze Rate (>10%)

**Symptoms:**
- Many games with bronze quality tier
- Predictions have reduced confidence

**Common Causes:**
1. Thin sample sizes (early season)
2. Multiple sources degraded
3. Heavy reconstruction usage

**Investigation:**
```sql
-- What's causing bronze tier?
SELECT
  UNNEST(quality_issues) as issue,
  COUNT(*) as count
FROM nba_analytics.player_game_summary
WHERE quality_tier = 'bronze'
  AND game_date >= CURRENT_DATE() - 7
GROUP BY issue
ORDER BY count DESC;
```

**Solutions:**
- If early season: Expected, document and accept
- If source issues: Investigate API reliability
- If reconstruction: Check why primary sources failing

### Issue: Audit Detecting Many Silent Failures

**Symptoms:**
- Daily audit finds games with no data
- `is_synthetic = TRUE` events increasing

**Common Causes:**
1. Scheduler not triggering processors
2. Processors crashing before logging
3. Upstream dependency failures

**Investigation:**
```bash
# Check Cloud Run processor logs
gcloud logging read "resource.type=cloud_run_revision" \
  --project=nba-props-platform \
  --limit=50
```

**Solutions:**
- Fix scheduler configuration
- Add error handling to processors
- Improve dependency checks

### Issue: Fallback Sources Frequently Used

**Symptoms:**
- Many 'fallback_used' events
- Primary source success rate < 90%

**Investigation:**
```sql
-- When is primary source failing?
SELECT
  DATE(event_timestamp) as fail_date,
  primary_source,
  COUNT(*) as failure_count
FROM nba_reference.source_coverage_log
WHERE event_type = 'fallback_used'
  AND DATE(event_timestamp) >= CURRENT_DATE() - 7
GROUP BY fail_date, primary_source
ORDER BY fail_date DESC;
```

**Solutions:**
- Add retry logic with backoff
- Consider promoting reliable backup to primary

---

## Performance Tuning

### Query Optimization

#### Always Use Partition Filters

```sql
-- GOOD - Uses partition filter
SELECT * FROM source_coverage_log
WHERE DATE(event_timestamp) >= '2024-12-01'
  AND severity = 'critical';

-- BAD - Full scan (expensive!)
SELECT * FROM source_coverage_log
WHERE severity = 'critical';
```

**Cost difference:** 100x on large tables

#### Leverage Clustering

```sql
-- Queries filter by clustered columns first
-- Cluster order: severity, event_type, game_id

-- GOOD - Follows cluster order
WHERE severity = 'critical'
  AND event_type = 'source_missing'
  AND game_id = 'XXX';

-- OK but less optimal
WHERE game_id = 'XXX'
  AND severity = 'critical';
```

### BigQuery Best Practices

#### 1. Avoid SELECT *

```sql
-- BAD - Scans all columns
SELECT * FROM source_coverage_log WHERE ...;

-- GOOD - Only needed columns
SELECT event_id, game_id, severity, description
FROM source_coverage_log WHERE ...;
```

#### 2. Use Views for Common Aggregations

```sql
-- Create a view for frequently-used aggregations
CREATE OR REPLACE VIEW daily_quality_summary AS
SELECT
  game_date,
  AVG(quality_score) as avg_score,
  COUNT(*) as game_count
FROM player_game_summary
GROUP BY game_date;
```

### Cost Monitoring

#### Track Query Costs

```sql
-- Most expensive queries in last 7 days
SELECT
  user_email,
  query,
  total_bytes_billed / POW(10, 9) as gb_billed,
  total_bytes_billed / POW(10, 12) * 5 as cost_usd
FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
  AND statement_type = 'SELECT'
ORDER BY total_bytes_billed DESC
LIMIT 20;
```

---

## Summary

This guide provides:

- **Comprehensive testing** - Unit, integration, and edge case tests
- **Daily procedures** - Morning checks, weekly reviews
- **Alert handling** - Step-by-step response procedures
- **Monitoring** - Key metrics and dashboard queries
- **Troubleshooting** - Common issues and solutions
- **Performance tuning** - BigQuery optimization patterns

**System is production-ready** with complete operational documentation.

---

*End of Part 4: Testing & Operations*

**This completes the Source Coverage System Design documentation.**

**All Parts:**
- [Part 1: Core Design & Architecture](01-core-design.md)
- [Part 2: Schema Reference](02-schema-reference.md)
- [Part 3: Implementation Guide](03-implementation-guide.md)
- [Part 4: Testing & Operations](04-testing-operations.md) <- You are here
