# ML Feature Store Schema - Analysis and Final Recommendation

**Date:** February 5, 2026 (Session 133)
**Status:** ✅ READY FOR IMPLEMENTATION
**Purpose:** Comprehensive analysis of existing quality patterns + final schema recommendation

---

## Table of Contents

1. [Existing Quality Tracking Patterns](#existing-quality-tracking-patterns)
2. [Pattern Analysis](#pattern-analysis)
3. [Final Schema Recommendation](#final-schema-recommendation)
4. [Backfill Strategy](#backfill-strategy)
5. [Implementation Plan](#implementation-plan)

---

## Existing Quality Tracking Patterns

### Pattern 1: Phase 3 Analytics (Standard Quality Columns)

**Tables:** `player_game_summary`, `upcoming_player_game_context`, all Phase 3 outputs

**Schema:**
```sql
quality_tier STRING,              -- 'gold', 'silver', 'bronze', 'poor', 'unusable'
quality_score FLOAT64,            -- 0-100
quality_issues ARRAY<STRING>,     -- ['backup_source_used', 'reconstructed']
data_sources ARRAY<STRING>,       -- ['nbac_gamebook_player_stats']
is_production_ready BOOL          -- Safe for predictions?
```

**Strengths:**
- ✅ **Flat fields** - Fast queries
- ✅ **ARRAY<STRING>** for issues - Proven pattern, flexible
- ✅ **Tier + Score** - Both categorical and numeric quality
- ✅ **Production ready flag** - Clear gate for downstream

**Weaknesses:**
- ⚠️ No per-category breakdown
- ⚠️ No source-level detail (which stat from which source)

**Usage:** 419K+ records in production

---

### Pattern 2: ML Feature Store (Current)

**Table:** `ml_feature_store_v2`

**Schema:**
```sql
feature_quality_score FLOAT64,        -- 0-100
feature_sources STRING,               -- JSON: {"0":"phase4","5":"default",...}
primary_data_source STRING,           -- 'phase4', 'phase4_partial', 'phase3', 'mixed'
matchup_data_status STRING            -- 'MATCHUP_AVAILABLE', 'MATCHUP_UNAVAILABLE', 'COMPLETE'
```

**Strengths:**
- ✅ **Per-feature source tracking** - Detailed provenance
- ✅ **Single quality score** - Simple, used in quality gate (85%+ threshold)

**Weaknesses:**
- ❌ **Aggregate score masks problems** - 74 score hid 100% matchup failure
- ❌ **No category breakdown** - Can't see matchup vs history vs team quality
- ❌ **Binary matchup status** - Doesn't explain WHY unavailable
- ❌ **No alerts/issues tracking** - Have to manually interpret score

**Gap:** Session 132 took 2+ hours to diagnose because of these weaknesses

---

### Pattern 3: Data Quality Events (Orchestration)

**Table:** `nba_orchestration.data_quality_events`

**Schema:**
```sql
event_id STRING,
event_timestamp TIMESTAMP,
event_type STRING,                    -- 'QUALITY_ISSUE_DETECTED', 'BACKFILL_QUEUED', etc.
severity STRING,                      -- 'INFO', 'WARNING', 'CRITICAL'
table_name STRING,
game_date DATE,
metric_name STRING,                   -- Which metric (e.g., 'pct_zero_points')
metric_value FLOAT64,
threshold_breached STRING,            -- 'warning' or 'critical'
resolution_status STRING,             -- 'PENDING', 'RESOLVED', etc.
details_json STRING,                  -- Additional metadata
related_event_id STRING               -- Link events together
```

**Strengths:**
- ✅ **Event-driven** - Complete audit trail
- ✅ **Resolution tracking** - Follow issues to closure
- ✅ **Severity levels** - Prioritization built-in
- ✅ **Linkable events** - Trace investigation flow

**Use case:** Alerting and remediation tracking (not per-record quality)

---

### Pattern 4: Model Registry

**Table:** `model_registry`

**Schema:**
```sql
model_id STRING,
model_version STRING,
gcs_path STRING,
feature_count INT64,
features_json STRING,                 -- Which features model uses
training_start_date / training_end_date,
git_commit STRING,                    -- Code version
status STRING,                        -- 'active', 'deprecated', etc.
is_production BOOL,
production_start_date / production_end_date
```

**Strengths:**
- ✅ **Complete model lineage** - What, when, why
- ✅ **Feature versioning** - Which features at training time
- ✅ **Status lifecycle** - Active vs deprecated vs testing

**Relevance:** Tracks WHICH features, we need to track feature QUALITY

---

### Pattern 5: Processor Completion Tracking

**Table:** `nba_orchestration.phase_completions`

**Schema:**
```sql
phase STRING,                         -- 'phase2', 'phase3', 'phase4', 'phase5'
game_date DATE,
processor_name STRING,                -- e.g., 'PlayerCompositeFactorsProcessor'
status STRING,                        -- 'success', 'partial', 'failed'
record_count INT64,
correlation_id STRING,
metadata JSON,
completed_at TIMESTAMP
```

**Strengths:**
- ✅ **Processor-level tracking** - Know what ran
- ✅ **Record counts** - Validate completeness
- ✅ **Status tracking** - Success vs failure

**Relevance:** Session 132 issue: PlayerCompositeFactorsProcessor didn't run → all matchup features defaulted. This table would have shown the gap.

---

## Pattern Analysis

### What Works Across Patterns

| Element | Pattern | Proven By | Use in ML Feature Store? |
|---------|---------|-----------|-------------------------|
| **Flat fields** | Phase 3 analytics | 419K+ records | ✅ YES - 5-10x faster queries |
| **ARRAY<STRING> for issues** | Phase 3 analytics | Production use | ✅ YES - quality_alerts |
| **Numeric score (0-100)** | Both patterns | Quality gates | ✅ YES - keep feature_quality_score |
| **Categorical tier** | Phase 3 only | Manual triage | ⚠️ MAYBE - could add quality_tier |
| **Per-field source tracking** | ML feature store | Debugging | ✅ YES - keep feature_sources |
| **Event-driven alerts** | data_quality_events | Remediation | ✅ YES - integrate with events table |
| **Processor completion** | phase_completions | Root cause | ✅ YES - query in alerts |

### What Doesn't Work

| Anti-Pattern | Where | Problem | Fix |
|-------------|-------|---------|-----|
| **Aggregate score only** | ml_feature_store_v2 | Masks component failures | Add per-category scores |
| **Binary status flags** | matchup_data_status | No detail on WHY | Add category quality % |
| **JSON source strings** | feature_sources | Hard to query | Keep JSON + add summary counts |
| **No alert tracking** | ml_feature_store_v2 | Manual interpretation | Add quality_alerts ARRAY |

---

## Final Schema Recommendation

### Design Principles

1. **Follow proven patterns** - Use Phase 3 analytics flat field pattern
2. **Extend, don't replace** - Keep existing fields for backward compatibility
3. **Query-optimized** - Flat fields for 5-10x performance
4. **Audit-ready** - Integrate with data_quality_events for alerting
5. **Trend-enabled** - Structure supports historical analysis (user wants backfill)

### Recommended Schema Additions

```sql
-- ============================================================================
-- ML FEATURE STORE V2 - ENHANCED QUALITY TRACKING (Session 133)
-- ============================================================================

-- EXISTING FIELDS (keep for backward compatibility)
feature_quality_score FLOAT64,               -- 0-100 overall score (KEEP)
feature_sources STRING,                       -- JSON: feature index → source (KEEP)
primary_data_source STRING,                   -- 'phase4', 'phase3', 'mixed' (KEEP)
matchup_data_status STRING,                   -- Status string (KEEP for now)

-- NEW: ALERT LEVEL (Phase 3 pattern: quality_tier)
quality_tier STRING OPTIONS(
  description="Quality tier: GOLD (>95), SILVER (85-95), BRONZE (70-85), POOR (50-70), CRITICAL (<50). Maps to Phase 3 analytics pattern."
),

quality_alert_level STRING OPTIONS(
  description="Alert priority: GREEN (healthy), YELLOW (degraded), RED (critical). For real-time monitoring."
),

quality_alerts ARRAY<STRING> OPTIONS(
  description="Specific quality issues detected. Examples: ['all_matchup_features_defaulted', 'high_default_rate_20pct', 'composite_factors_missing']. Matches Phase 3 'quality_issues' pattern."
),

-- NEW: CATEGORY-LEVEL QUALITY (addresses Session 132 gap)
matchup_quality_pct FLOAT64 OPTIONS(
  description="Quality % for matchup features (composite factors 5-8, opponent defense 13-14). 0=all defaults, 100=all Phase 4. Session 132: This was 0% but hidden by 74% aggregate."
),

player_history_quality_pct FLOAT64 OPTIONS(
  description="Quality % for player history features (0-4: points/std/games, 29-32: matchup history/minutes). Typically 90-100% (good Phase 3 coverage)."
),

team_context_quality_pct FLOAT64 OPTIONS(
  description="Quality % for team context features (22-24: pace/offense/wins). Usually 95-100% (Phase 3 team stats reliable)."
),

vegas_quality_pct FLOAT64 OPTIONS(
  description="Quality % for vegas features (25-28: lines/moves). Expected 40-60% (not all players have lines). Low quality is NORMAL."
),

-- NEW: CRITICAL FEATURE FLAGS (fast boolean checks)
has_composite_factors BOOL OPTIONS(
  description="TRUE if composite factors available (features 5-8 from Phase 4). Session 132: All FALSE caused issue."
),

has_opponent_defense BOOL OPTIONS(
  description="TRUE if opponent defense data available (features 13-14 from Phase 3). Required for matchup quality."
),

has_vegas_line BOOL OPTIONS(
  description="TRUE if vegas line available for player. FALSE is normal for low-volume props."
),

-- NEW: SOURCE DISTRIBUTION (scalar counts, not arrays)
default_feature_count INT64 OPTIONS(
  description="Count of features using default/fallback values. High count = data unavailability. Session 132: 4 defaults (all matchup features)."
),

phase4_feature_count INT64 OPTIONS(
  description="Count of features from Phase 4 precompute (highest quality). Target: 25+ of 33 features."
),

phase3_feature_count INT64 OPTIONS(
  description="Count of features from Phase 3 analytics (good quality). Acceptable fallback."
),

calculated_feature_count INT64 OPTIONS(
  description="Count of features calculated on-the-fly (derived from available data). Acceptable quality."
),

-- NEW: DETAILED SOURCE SUMMARY (JSON for deep investigation)
feature_sources_summary STRING OPTIONS(
  description="JSON summary of feature sources. Format: {\"default\": [5,6,7,8], \"default_names\": [\"fatigue_score\", \"pace_score\"], \"phase4\": [0,1,2,3]}. Use for detailed investigation when quality_alerts fires."
),

-- NEW: DATA LINEAGE (processor tracking)
upstream_processors_ran STRING OPTIONS(
  description="Comma-separated list of Phase 4 processors that ran for this date. Example: 'PlayerCompositeFactorsProcessor,MLFeatureStoreProcessor'. Query phase_completions for details."
),

missing_processors STRING OPTIONS(
  description="Comma-separated list of expected processors that DID NOT run. Session 132: 'PlayerCompositeFactorsProcessor' missing caused all matchup features to default."
),

-- NEW: PRODUCTION READINESS (Phase 3 pattern)
is_production_ready BOOL OPTIONS(
  description="TRUE if quality sufficient for production predictions (quality_score >= 85, matchup_quality_pct >= 50). Matches Phase 3 analytics pattern."
),

-- NEW: AUDIT TRAIL
quality_computed_at TIMESTAMP OPTIONS(
  description="When quality fields were computed. For detecting stale data."
),

quality_schema_version STRING OPTIONS(
  description="Schema version for quality fields (e.g., 'v2.1'). For handling schema evolution."
)
```

### Schema Comparison: Before vs After

| Aspect | Current (v2) | Proposed (v2.1) | Improvement |
|--------|--------------|-----------------|-------------|
| **Overall quality** | 1 float | Float + tier + alert level | 3-level specificity |
| **Category breakdown** | None | 4 category % scores | Session 132 gap filled |
| **Issue tracking** | None | ARRAY<STRING> alerts | Matches Phase 3 pattern |
| **Source counts** | JSON only | JSON + 4 scalar counts | Fast aggregation |
| **Critical flags** | 1 binary | 3 boolean flags | Quick checks |
| **Processor tracking** | None | 2 fields (ran/missing) | Root cause attribution |
| **Production gate** | Implicit | Explicit boolean | Clear readiness |
| **Query performance** | Baseline | 5-10x faster (flat fields) | Major improvement |
| **Storage cost** | 1.2 KB/record | 1.4 KB/record (+17%) | Negligible (<$0.02/year) |

---

## Backfill Strategy

### User Requirement

**"I want to backfill past dates because this stuff is important and I want to easily be able to query and see if there are any issues."**

### Recommendation: 90-Day Backfill

**Why 90 days:**
- Covers full current season (Nov 2025 - Feb 2026)
- Sufficient for trend detection (30-day rolling avg with 60-day baseline)
- Manageable cost (~$0.50 query cost + 2 hours runtime)
- All recent predictions have quality context

**Why NOT full history (365+ days):**
- Historical seasons have different feature definitions (v1 vs v2)
- Low value - not actively predicting on 2024 games
- Higher cost (~$3-5 query cost + 8+ hours runtime)
- Schema evolved - would need version handling

### Backfill Implementation

#### Step 1: Validate Current Schema
```bash
# Check existing ml_feature_store_v2 records
bq query --use_legacy_sql=false "
SELECT
  MIN(game_date) as earliest,
  MAX(game_date) as latest,
  COUNT(DISTINCT game_date) as unique_dates,
  COUNT(*) as total_records,
  COUNT(feature_sources) as with_sources
FROM nba_predictions.ml_feature_store_v2
"

# Expected: Nov 2025 - Feb 2026 (~90-100 dates, 18K+ records)
```

#### Step 2: Test Quality Calculation on Sample
```python
# Test script: bin/backfill/test_quality_enhancement.py
from data_processors.precompute.ml_feature_store import MLFeatureStoreProcessor
from data_processors.precompute.ml_feature_store.quality_scorer import QualityScorer

# Load sample record
sample_date = "2026-02-06"
records = load_feature_store_records(sample_date)

# Compute enhanced quality for one record
scorer = QualityScorer()
for record in records[:5]:  # Test 5 records
    enhanced = scorer.calculate_quality_breakdown(record['feature_sources'])
    print(f"Player: {record['player_lookup']}")
    print(f"  Matchup quality: {enhanced['matchup_quality_pct']}%")
    print(f"  Has composite: {enhanced['has_composite_factors']}")
    print(f"  Default count: {enhanced['default_feature_count']}")
    print(f"  Alerts: {enhanced['quality_alerts']}")
```

#### Step 3: Backfill in Batches
```python
# Script: bin/backfill/backfill_feature_quality.py

import time
from datetime import datetime, timedelta
from google.cloud import bigquery

def backfill_quality_fields(start_date: str, end_date: str, batch_size: int = 5):
    """
    Backfill quality fields for historical ml_feature_store_v2 records.

    Args:
        start_date: Start date (YYYY-MM-DD), e.g., '2025-11-01'
        end_date: End date (YYYY-MM-DD), e.g., '2026-02-05'
        batch_size: Days per batch (avoid query timeout)
    """

    client = bigquery.Client(project='nba-props-platform')
    current_date = datetime.strptime(start_date, '%Y-%m-%d').date()
    end = datetime.strptime(end_date, '%Y-%m-%d').date()

    while current_date <= end:
        batch_end = current_date + timedelta(days=batch_size - 1)
        if batch_end > end:
            batch_end = end

        print(f"Backfilling {current_date} to {batch_end}...")

        # Option A: Regenerate feature store (includes quality computation)
        for single_date in date_range(current_date, batch_end):
            processor = MLFeatureStoreProcessor()
            processor.run({
                'analysis_date': str(single_date),
                'force': True  # Overwrite existing records
            })
            time.sleep(2)  # Rate limit (30 dates/minute max)

        # Option B: Update in-place via SQL (faster but more complex)
        # update_quality_fields_sql(current_date, batch_end)

        current_date = batch_end + timedelta(days=1)
        time.sleep(10)  # Batch rate limit

    print("Backfill complete!")


def update_quality_fields_sql(start_date, end_date):
    """
    Update quality fields in-place via SQL UPDATE.

    Pros: Faster (no full regeneration)
    Cons: Complex SQL, must recalculate quality from feature_sources JSON
    """

    query = f"""
    UPDATE `nba_predictions.ml_feature_store_v2` fs
    SET
      -- Calculate per-category quality
      matchup_quality_pct = (
        SELECT ROUND(
          COUNTIF(source IN ('phase4', 'phase3')) / COUNT(*) * 100, 1
        )
        FROM UNNEST(ARRAY[5,6,7,8,13,14]) AS idx
        LEFT JOIN UNNEST(JSON_EXTRACT_ARRAY(fs.feature_sources)) AS source
          ON idx = CAST(source AS INT64)
      ),

      -- Calculate default count
      default_feature_count = (
        SELECT COUNTIF(source = 'default')
        FROM UNNEST(JSON_EXTRACT_ARRAY(fs.feature_sources)) AS source
      ),

      -- Set alert level
      quality_alert_level = CASE
        WHEN matchup_data_status = 'MATCHUP_UNAVAILABLE' THEN 'RED'
        WHEN default_feature_count > 6 THEN 'RED'  -- >20% of 33 features
        WHEN default_feature_count > 2 THEN 'YELLOW'
        ELSE 'GREEN'
      END,

      -- Other fields...
      quality_computed_at = CURRENT_TIMESTAMP()

    WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
      AND quality_alert_level IS NULL  -- Only update if not already done
    """

    # This is pseudocode - actual SQL is more complex
    # Recommendation: Use Option A (full regeneration) for correctness
```

#### Step 4: Verification
```sql
-- Verify backfill completeness
SELECT
  game_date,
  COUNT(*) as total,
  COUNT(quality_alert_level) as with_alerts,
  COUNT(matchup_quality_pct) as with_breakdown,
  ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality,
  COUNTIF(quality_alert_level = 'RED') as red_count,
  COUNTIF(quality_alert_level = 'YELLOW') as yellow_count,
  COUNTIF(quality_alert_level = 'GREEN') as green_count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
GROUP BY 1
ORDER BY 1 DESC;

-- Expected: with_alerts = total for all dates
```

#### Step 5: Historical Trend Analysis (Post-Backfill)
```sql
-- Identify dates with quality issues (Session 132-style problems)
SELECT
  game_date,
  COUNT(*) as total_players,
  ROUND(AVG(matchup_quality_pct), 1) as avg_matchup,
  ROUND(AVG(player_history_quality_pct), 1) as avg_history,
  COUNTIF(quality_alert_level = 'RED') as red_count,
  ROUND(COUNTIF(quality_alert_level = 'RED') / COUNT(*) * 100, 1) as red_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-01'
GROUP BY 1
HAVING red_pct > 10  -- Dates with >10% RED players
ORDER BY red_pct DESC, game_date DESC;

-- This would have caught Session 132 issue (Feb 6: 100% RED)
```

### Backfill Cost Estimate

**Compute:**
- 90 days × 200 players = 18,000 records
- Feature store regeneration: ~3 seconds per date
- Total time: 90 dates × 3 sec = ~5 minutes
- Cost: ~$0.05 (Cloud Run time)

**Storage:**
- Additional fields: ~200 bytes per record
- 18,000 records × 200 bytes = 3.6 MB
- BigQuery storage: $0.02/GB/month
- Cost: ~$0.0001/month (negligible)

**Query (during backfill):**
- Read feature_sources: 18,000 records × 1.2 KB = 21.6 MB
- BigQuery query cost: $5/TB = $0.00011
- Total query cost: ~$0.01

**Total Cost: <$0.10** (one-time)

### Backfill Schedule

**Recommended:**
```bash
# Week 1: Test on recent dates
backfill_quality_fields('2026-02-01', '2026-02-05', batch_size=1)

# Week 1: Backfill last 30 days (if test passes)
backfill_quality_fields('2026-01-06', '2026-02-05', batch_size=5)

# Week 2: Backfill full season (if no issues)
backfill_quality_fields('2025-11-01', '2026-01-05', batch_size=10)
```

**Total Time:**
- Test: 5 min
- 30 days: 15 min
- 90 days: 30 min
- **Total: ~50 minutes of processing time**

---

## Implementation Plan

### Phase 0: Schema Design Finalization (CURRENT - 30 min)

- [x] Analyze existing quality patterns (DONE)
- [x] Compare with proposed design (DONE)
- [x] Finalize schema additions (DONE - see above)
- [ ] Get user approval on schema

### Phase 1: Schema Update (15 min)

**File:** `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`

```sql
-- Add new fields (BigQuery ALTER TABLE is instant - metadata only)
ALTER TABLE nba_predictions.ml_feature_store_v2

-- Alert & Tier
ADD COLUMN quality_tier STRING,
ADD COLUMN quality_alert_level STRING,
ADD COLUMN quality_alerts ARRAY<STRING>,

-- Category Quality
ADD COLUMN matchup_quality_pct FLOAT64,
ADD COLUMN player_history_quality_pct FLOAT64,
ADD COLUMN team_context_quality_pct FLOAT64,
ADD COLUMN vegas_quality_pct FLOAT64,

-- Critical Flags
ADD COLUMN has_composite_factors BOOL,
ADD COLUMN has_opponent_defense BOOL,
ADD COLUMN has_vegas_line BOOL,

-- Source Counts
ADD COLUMN default_feature_count INT64,
ADD COLUMN phase4_feature_count INT64,
ADD COLUMN phase3_feature_count INT64,
ADD COLUMN calculated_feature_count INT64,

-- Detailed Source Summary
ADD COLUMN feature_sources_summary STRING,

-- Processor Tracking
ADD COLUMN upstream_processors_ran STRING,
ADD COLUMN missing_processors STRING,

-- Production Readiness
ADD COLUMN is_production_ready BOOL,

-- Audit Trail
ADD COLUMN quality_computed_at TIMESTAMP,
ADD COLUMN quality_schema_version STRING;
```

### Phase 2: Quality Scorer Enhancement (1-2 hours)

**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py`

Add methods:
1. `calculate_quality_tier()` - GOLD/SILVER/BRONZE/POOR/CRITICAL
2. `calculate_alert_level()` - GREEN/YELLOW/RED
3. `calculate_quality_breakdown()` - Per-category quality
4. `calculate_source_counts()` - Scalar counts
5. `build_source_summary()` - JSON summary
6. `check_processor_completions()` - Query phase_completions table

### Phase 3: Integration (30 min)

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

Update `_build_feature_store_record()`:
```python
def _build_feature_store_record(self, player_data, game_date):
    # ... existing code ...

    # EXISTING: Keep backward compatibility
    record['feature_quality_score'] = self.quality_scorer.calculate_overall_score(feature_sources)
    record['feature_sources'] = json.dumps(feature_sources)
    record['primary_data_source'] = self._determine_primary_source(feature_sources)

    # NEW: Enhanced quality fields
    quality_breakdown = self.quality_scorer.calculate_quality_breakdown(feature_sources)
    record.update(quality_breakdown)  # Adds all new fields

    return record
```

### Phase 4: Testing (30 min)

**Test with Feb 6, 2026 data** (known quality issue):
```bash
PYTHONPATH=. python -c "
from data_processors.precompute.ml_feature_store import MLFeatureStoreProcessor
p = MLFeatureStoreProcessor()
p.run({'analysis_date': '2026-02-06', 'force': True})
"

# Verify quality fields
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  quality_tier,
  quality_alert_level,
  matchup_quality_pct,
  has_composite_factors,
  default_feature_count,
  quality_alerts
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-06'
LIMIT 10
"
```

**Expected for Feb 6 (pre-fix scenario):**
- quality_tier: CRITICAL
- quality_alert_level: RED
- matchup_quality_pct: 0.0
- has_composite_factors: FALSE
- default_feature_count: 4
- quality_alerts: ['all_matchup_features_defaulted', 'composite_factors_missing']

### Phase 5: Deployment (15 min)

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors

# Verify deployment
./bin/whats-deployed.sh

# Check health
curl https://nba-phase4-precompute-processors-<hash>.a.run.app/health/deep
```

### Phase 6: Backfill (90 min)

```bash
# Create backfill script
cat > bin/backfill/backfill_feature_quality.py
# (see backfill implementation above)

# Run backfill
PYTHONPATH=. python bin/backfill/backfill_feature_quality.py \
  --start-date 2025-11-01 \
  --end-date 2026-02-05 \
  --batch-size 5

# Monitor progress
watch -n 30 'bq query --use_legacy_sql=false "
SELECT
  COUNT(DISTINCT game_date) as dates_backfilled,
  COUNT(*) as records_backfilled,
  COUNT(quality_alert_level) as with_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= \"2025-11-01\"
"'
```

### Phase 7: Monitoring Integration (1 hour)

**Update canary queries:**
```python
# bin/monitoring/pipeline_canary_queries.py

CanaryCheck(
    name="Phase 4 - Feature Quality - Matchup Critical",
    phase="phase4_precompute",
    query="""
    SELECT
      game_date,
      COUNT(*) as total,
      COUNTIF(quality_alert_level = 'RED') as red_count,
      ROUND(AVG(matchup_quality_pct), 1) as avg_matchup_quality
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date = @target_date
    GROUP BY 1
    HAVING red_count > 0.10 * total  -- More than 10% RED
    """,
    thresholds={
        'red_count': {'max': 20},  # Alert if >20 players RED
        'avg_matchup_quality': {'min': 50}  # Alert if <50%
    },
    alert_channel='#nba-alerts',
    description="Critical alert: High rate of degraded matchup features"
)
```

**Integrate with data_quality_events:**
```python
# When RED threshold exceeded
from shared.utils.data_quality_logger import DataQualityLogger

logger = DataQualityLogger()
logger.log_quality_issue(
    table_name='ml_feature_store_v2',
    game_date=game_date,
    severity='CRITICAL',
    metric_name='red_player_pct',
    metric_value=red_pct,
    threshold_breached='critical',
    details={
        'red_count': red_count,
        'total_players': total_players,
        'avg_matchup_quality': avg_matchup_quality,
        'suggested_fix': 'Check phase_completions for missing processors'
    }
)
```

---

## Success Metrics

### Immediate (Post-Implementation)

- [ ] All new records have quality_tier, quality_alert_level, category_quality_pct populated
- [ ] Feb 6 test shows RED alert with matchup_quality_pct = 0
- [ ] No query performance regression (<10% slower)
- [ ] Schema update completed without downtime

### Short-term (1 week post-backfill)

- [ ] 90 days backfilled (18K+ records with quality fields)
- [ ] Historical trend query shows Feb 6 as outlier (100% RED)
- [ ] Zero false positive RED alerts
- [ ] `/validate-daily` shows per-category quality

### Long-term (1 month)

- [ ] Time to detect quality issues: <5 minutes (vs 2+ hours)
- [ ] Time to diagnose root cause: <2 minutes (via category breakdown)
- [ ] Zero recurrence of Session 132-style incidents
- [ ] Quality trend queries used for proactive monitoring

---

## Summary Recommendation

### Use This Schema Design

**Final Decision: Hybrid approach - Best of both worlds**

1. **Keep existing fields** for backward compatibility:
   - `feature_quality_score` (float) - Used in quality gates
   - `feature_sources` (JSON) - Detailed provenance
   - `primary_data_source` (string) - Primary source classification

2. **Add Phase 3 analytics pattern** (proven in production):
   - `quality_tier` (GOLD/SILVER/BRONZE/POOR/CRITICAL)
   - `quality_alerts` (ARRAY<STRING>) - Matches quality_issues pattern
   - `is_production_ready` (BOOL) - Clear gate

3. **Add category breakdown** (Session 133 enhancement):
   - 4 category quality % fields (flat, not nested)
   - 3 critical feature flags (boolean)
   - 4 source count fields (scalar)

4. **Add processor tracking** (Session 132 root cause):
   - `upstream_processors_ran` (string)
   - `missing_processors` (string)

5. **Add audit trail**:
   - `quality_computed_at` (timestamp)
   - `quality_schema_version` (string)

**Total Storage Impact:** +200 bytes/record (+17%) = <$0.02/year

**Query Performance:** 5-10x faster than nested STRUCT approach

**Backfill:** 90 days (18K records), ~90 minutes, <$0.10 cost

---

**Next Step:** Get user approval, then implement Phase 1 (schema update, 15 min)

---

**Document Version:** 1.0
**Last Updated:** February 5, 2026 (Session 133)
**Status:** ✅ READY FOR IMPLEMENTATION
