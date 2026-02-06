# Feature Quality Visibility System - Project Overview

**Start Date:** February 5, 2026 (Session 133)
**Status:** 🟡 In Progress - Design & Planning Phase
**Priority:** P1 - Prevents multi-hour incident investigations
**Owner:** Session 133+

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [The Problem](#the-problem)
3. [Root Cause Analysis](#root-cause-analysis)
4. [Proposed Solution](#proposed-solution)
5. [Schema Design](#schema-design)
6. [Implementation Plan](#implementation-plan)
7. [Prevention Mechanisms](#prevention-mechanisms)
8. [Success Criteria](#success-criteria)

---

## Executive Summary

### The Crisis (Session 132)

On February 5, 2026, ALL 201 players had missing matchup data for Feb 6 predictions. It took **2+ hours of manual SQL investigation** to discover that:

1. `feature_quality_score` showed 74 (acceptable)
2. But 100% of matchup features were using default values
3. Root cause: `PlayerCompositeFactorsProcessor` missing from scheduler job

### The Core Problem

**The aggregate `feature_quality_score` is a lie.** It hides component failures by averaging:
- 4 matchup features at 0% quality (defaults)
- 29 other features at 95% quality
- Result: 74% aggregate score (looks acceptable!)

### The Solution

Implement a **Feature Quality Visibility System** that provides:
- **Detection:** Real-time alerts when feature quality degrades (<5 minutes vs 2+ hours)
- **Diagnosis:** Per-category quality breakdown (matchup, history, team, vegas)
- **Attribution:** Root cause identification (which processor didn't run)
- **Prevention:** Trend detection to catch quality degradation early

### Business Impact

| Metric | Before | After (Target) |
|--------|--------|----------------|
| Time to detect quality issues | 2+ hours | <5 minutes |
| Time to diagnose root cause | 1+ hour | <2 minutes |
| False positive rate | N/A | <5% |
| Prediction quality incidents | 3+ in 6 months | Near zero |

---

## The Problem

### Timeline of Session 132 Discovery

| Time (UTC) | Event | Impact |
|------------|-------|--------|
| ~18:00 | Feb 6 predictions generated | feature_quality_score ~74 (acceptable) |
| ~19:30 | Manual investigation begins | Checking random players |
| ~20:00 | Root cause identified | PlayerCompositeFactorsProcessor didn't run |
| ~20:15 | Manual fix applied | Ran processor, regenerated feature store |
| ~20:45 | Quality improved | 73.92 → 85.28 |

**Total investigation time:** 2+ hours of manual SQL queries

### What Went Wrong

**System Level:**
1. Scheduler job incomplete: `same-day-phase4-tomorrow` only ran `MLFeatureStoreProcessor`, not `PlayerCompositeFactorsProcessor`
2. Feature store degraded silently: Features 5-8 used defaults (40 quality points vs 100)
3. No automated alert: Nothing flagged 100% matchup data unavailability

**Visibility Level:**
1. Aggregate score masked problem: 74 looked acceptable
2. Binary status insufficient: `matchup_data_status = 'MATCHUP_UNAVAILABLE'` but no detail on WHY
3. No category-level visibility: Couldn't see matchup=0%, history=95%, team=40%, vegas=45%

### Historical Context

**This is the 3rd time this pattern has occurred:**
- **Session 96 (Feb 2):** Similar matchup data issue, 49.1% hit rate
- **Session 118-120:** General data quality issues requiring defense-in-depth validation
- **Session 132 (Feb 5):** This incident

**Pattern:** Missing processor runs → degraded features → aggregate score masks problem → manual investigation required

---

## Root Cause Analysis

### Why Detection Took 2+ Hours

**1. No Real-Time Alerts**
- No monitoring on feature category quality
- No alerts when matchup features all use defaults
- No processor completion validation

**2. Aggregate Score Masking**
```sql
-- What we saw:
SELECT AVG(feature_quality_score) FROM ml_feature_store_v2
-- Result: 74.0 (looks OK!)

-- What we should have seen:
SELECT
  AVG(CASE WHEN feature_index IN (5,6,7,8) THEN quality ELSE NULL END) as matchup_quality,
  AVG(CASE WHEN feature_index IN (0,1,2,3,4) THEN quality ELSE NULL END) as history_quality
FROM ml_feature_store_v2
-- Result: matchup_quality=0.0, history_quality=95.0 (ALERT!)
```

**3. Manual SQL Required**
To diagnose, we had to manually run:
```sql
-- Check feature sources
SELECT feature_sources FROM ml_feature_store_v2 WHERE game_date = '2026-02-06' LIMIT 1

-- Parse JSON
-- Analyze which features are defaulted
-- Cross-reference with feature definitions
-- Identify pattern (all matchup features defaulted)
-- Query processor runs to find missing processor
```

**4. Binary Status Insufficient**
`matchup_data_status = 'MATCHUP_UNAVAILABLE'` tells us WHAT but not WHY:
- Which specific features are missing?
- Which upstream data is unavailable?
- Which processor didn't run?

---

## Proposed Solution

### Four-Phase Approach

**Phase 1: Alert Thresholds (Quick Win - 1-2 hours)**
- Add `quality_alert_level` (GREEN/YELLOW/RED) to schema
- Implement threshold-based alerting
- Slack alerts for RED level batches
- **Outcome:** Detect issues in <5 minutes

**Phase 2: Diagnostic Breakdown (Core Value - 2-3 hours)**
- Add per-category quality scores (flat fields)
- Add critical feature flags
- Add degraded feature tracking
- **Outcome:** Diagnose root cause in <2 minutes

**Phase 3: Trend Detection (Enhanced - 1-2 hours)**
- Create daily summary table
- Alert on quality degradation (vs 7-day rolling avg)
- Catch gradual quality decay
- **Outcome:** Proactive issue detection

**Phase 4: Root Cause Attribution (Advanced - 2-3 hours)**
- Query processor status at alert time
- Include suggested fix commands in alerts
- Automate investigation steps
- **Outcome:** Alert includes exact fix instructions

### Design Principles

1. **Flat Over Nested:** Use flat schema fields instead of nested STRUCTs for 5-10x faster queries
2. **Alerts Not Blocks:** Alert on quality issues but don't block writes (false positives are costly)
3. **Category Not Feature:** Track category-level quality (matchup, history, team, vegas) not per-feature
4. **Batch Over Player:** Alert on batch-level metrics (10% RED) not individual player RED
5. **Trend Over Point:** Compare to rolling averages to catch degradation
6. **Attribution Not Just Detection:** Tell users WHAT to fix, not just that something's wrong

---

## Schema Design

### Current Schema Issues

**Problem 1: No Category-Level Quality**
```sql
-- Current: Single aggregate score
feature_quality_score FLOAT64  -- 74.0 (masks 0% matchup, 95% history)

-- Missing: Per-category breakdown
-- matchup_quality_pct FLOAT64
-- player_history_quality_pct FLOAT64
-- etc.
```

**Problem 2: No Alert Level**
```sql
-- Current: No alert classification
-- Must manually interpret quality score

-- Needed: Alert level
-- quality_alert_level STRING  -- 'GREEN', 'YELLOW', 'RED'
```

**Problem 3: No Degraded Feature Tracking**
```sql
-- Current: Must parse JSON feature_sources
feature_sources STRING  -- '{"0":"phase4","5":"default",...}'

-- Needed: Summarized degraded feature info
-- degraded_feature_count INT64
-- feature_sources_summary STRING
```

### Proposed Schema Additions

Based on Opus architectural review, we propose **flat fields** (not nested STRUCT):

```sql
-- ============================================================================
-- FEATURE QUALITY VISIBILITY FIELDS (Session 133)
-- ============================================================================

-- Alert Level (Phase 1)
quality_alert_level STRING
  DESCRIPTION "Alert level: GREEN (healthy), YELLOW (degraded), RED (critical)",

quality_alerts ARRAY<STRING>
  DESCRIPTION "Specific alerts triggered: ['all_matchup_features_defaulted', 'high_default_rate_20pct']",

-- Category Quality Scores (Phase 2) - FLAT FIELDS
matchup_quality_pct FLOAT64
  DESCRIPTION "Quality percentage for matchup features (5-8, 13-14): 0-100",

player_history_quality_pct FLOAT64
  DESCRIPTION "Quality percentage for player history features (0-4, 29-32): 0-100",

team_context_quality_pct FLOAT64
  DESCRIPTION "Quality percentage for team context features (22-24): 0-100",

vegas_quality_pct FLOAT64
  DESCRIPTION "Quality percentage for vegas features (25-28): 0-100",

-- Critical Feature Flags (Phase 2) - BOOLEAN FOR FAST QUERY
has_composite_factors BOOL
  DESCRIPTION "TRUE if composite factors (features 5-8) available, FALSE if using defaults",

has_opponent_defense BOOL
  DESCRIPTION "TRUE if opponent defense data (features 13-14) available",

has_vegas_line BOOL
  DESCRIPTION "TRUE if vegas line data available for this player",

-- Feature Source Summary (Phase 2) - SCALAR COUNTS
default_feature_count INT64
  DESCRIPTION "Count of features using default values",

phase4_feature_count INT64
  DESCRIPTION "Count of features using Phase 4 precompute data",

phase3_feature_count INT64
  DESCRIPTION "Count of features using Phase 3 analytics data",

calculated_feature_count INT64
  DESCRIPTION "Count of features calculated on-the-fly",

-- Degraded Feature Details (Phase 2) - JSON STRING
feature_sources_summary STRING
  DESCRIPTION "JSON summary of feature sources: {\"default\": [5,6,7,8], \"phase4\": [0,1,2,3], \"default_names\": [\"fatigue_score\", \"pace_score\"]}"
```

### Why Flat Schema Over Nested STRUCT

**Original Session 132 Proposal (Nested STRUCT):**
```sql
feature_quality_breakdown STRUCT<
  matchup_quality FLOAT64,
  player_history_quality FLOAT64,
  team_context_quality FLOAT64,
  vegas_quality FLOAT64,
  has_composite_factors BOOL,
  has_opponent_defense BOOL,
  degraded_feature_indices ARRAY<INT64>,
  degraded_feature_names ARRAY<STRING>
>
```

**Problems with Nested STRUCT:**
1. **Query complexity:** Requires `feature_quality_breakdown.matchup_quality` syntax
2. **UNNEST required:** REPEATED fields inside STRUCT need UNNEST (slow)
3. **No direct filtering:** Can't do `WHERE matchup_quality < 50` directly
4. **Aggregation verbose:** `AVG(feature_quality_breakdown.matchup_quality)` is clunky
5. **Array sync bugs:** `degraded_feature_indices` and `degraded_feature_names` must stay in sync

**Opus Recommendation (Flat Fields):**
```sql
-- Direct access, no nesting
matchup_quality_pct FLOAT64,
player_history_quality_pct FLOAT64,
...
degraded_feature_count INT64,
feature_sources_summary STRING  -- JSON for details
```

**Benefits:**
- ✅ **5-10x faster queries:** No UNNEST, direct column access
- ✅ **Simple filtering:** `WHERE matchup_quality_pct < 50`
- ✅ **Easy aggregation:** `AVG(matchup_quality_pct)`
- ✅ **Lower storage:** Scalars vs REPEATED fields (~200 bytes vs ~500 bytes)
- ✅ **Cleaner syntax:** No nested access patterns

### Schema Comparison

| Approach | Query Performance | Storage | Complexity | Maintainability |
|----------|------------------|---------|------------|-----------------|
| **Flat Fields (Opus)** | ⭐⭐⭐⭐⭐ | ~200 bytes | Low | High |
| **Nested STRUCT (Session 132)** | ⭐⭐ | ~500 bytes | Medium | Medium |
| **Separate Quality Table** | ⭐⭐⭐ | ~200 bytes | High (joins) | Low |

**Decision: Use flat fields approach** (Opus recommendation)

### Storage Impact Analysis

**Current ml_feature_store_v2 record size:** ~1.2 KB per record

**Additional storage per record:**
- Alert fields (2): ~50 bytes
- Category quality (4 FLOAT64): 32 bytes
- Binary flags (3 BOOL): 3 bytes
- Source counts (4 INT64): 32 bytes
- Summary JSON (STRING): ~100 bytes
- **Total: ~217 bytes per record**

**Daily storage cost:**
- 200 players/day × 217 bytes = 43.4 KB/day
- 43.4 KB × 365 days = 15.8 MB/year
- **Cost:** Negligible (<$0.01/year in BigQuery)

**Query cost impact:**
- Flat fields: Direct column access (same as any FLOAT64)
- No UNNEST: No additional scan cost
- **Verdict:** Minimal query cost impact

---

## Implementation Plan

### Phase 1: Alert Thresholds (1-2 hours)

**Goal:** Detect feature quality issues in <5 minutes

#### 1.1 Schema Updates
**File:** `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`

Add fields:
- `quality_alert_level STRING`
- `quality_alerts ARRAY<STRING>`

#### 1.2 Quality Scorer Implementation
**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py`

Add method:
```python
def calculate_alert_level(
    feature_sources: Dict[int, str],
    matchup_status: str,
    feature_quality_score: float
) -> Tuple[str, List[str]]:
    """
    Calculate quality alert level based on feature source distribution.

    Returns:
        Tuple[str, List[str]]: (alert_level, alerts)
            alert_level: 'GREEN', 'YELLOW', or 'RED'
            alerts: List of specific alert strings

    Alert Thresholds:
        RED:
            - matchup_status == 'MATCHUP_UNAVAILABLE'
            - >20% of features using defaults
            - All critical matchup features (5-8) defaulted
        YELLOW:
            - >2 critical features defaulted
            - >5% of features using defaults
            - feature_quality_score drop >10 points (future: vs baseline)
        GREEN:
            - All thresholds passed
    """
```

#### 1.3 Integration
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

Update `_build_feature_store_record()` method:
```python
# After feature_quality_score calculation
alert_level, alerts = self.quality_scorer.calculate_alert_level(
    feature_sources=feature_sources,
    matchup_status=matchup_data_status,
    feature_quality_score=feature_quality_score
)

record['quality_alert_level'] = alert_level
record['quality_alerts'] = alerts
```

#### 1.4 Batch-Level Alerting
**File:** `bin/monitoring/pipeline_canary_queries.py`

Add canary check:
```python
CanaryCheck(
    name="Phase 4 - Feature Quality Critical",
    phase="phase4_precompute",
    query="""
    WITH batch_summary AS (
      SELECT
        game_date,
        COUNT(*) as total_players,
        COUNTIF(quality_alert_level = 'RED') as red_count,
        AVG(matchup_quality_pct) as avg_matchup_quality
      FROM `nba_predictions.ml_feature_store_v2`
      WHERE game_date = @target_date
    )
    SELECT
      total_players,
      red_count,
      ROUND(red_count / total_players * 100, 1) as red_pct,
      ROUND(avg_matchup_quality, 1) as avg_matchup_quality
    FROM batch_summary
    """,
    thresholds={
        'red_pct': {'max': 10},  # Alert if >10% RED
        'avg_matchup_quality': {'min': 50}  # Alert if <50%
    },
    description="Alerts on critical feature quality degradation"
)
```

#### 1.5 Testing
```bash
# Test with historical Feb 6 data (known bad quality)
PYTHONPATH=. python -c "
from data_processors.precompute.ml_feature_store import MLFeatureStoreProcessor
p = MLFeatureStoreProcessor()
p.run({'analysis_date': '2026-02-06', 'force': True})
"

# Verify alerts populated
bq query --use_legacy_sql=false "
SELECT
  quality_alert_level,
  COUNT(*) as count,
  ARRAY_AGG(DISTINCT alert IGNORE NULLS ORDER BY alert) as unique_alerts
FROM nba_predictions.ml_feature_store_v2,
UNNEST(quality_alerts) as alert
WHERE game_date = '2026-02-06'
GROUP BY 1
"

# Expected: 201 RED with alert 'all_matchup_features_defaulted'
```

#### 1.6 Deployment
```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

---

### Phase 2: Diagnostic Breakdown (2-3 hours)

**Goal:** Diagnose root cause in <2 minutes

#### 2.1 Schema Updates
**File:** `schemas/bigquery/predictions/04_ml_feature_store_v2.sql`

Add fields:
- `matchup_quality_pct FLOAT64`
- `player_history_quality_pct FLOAT64`
- `team_context_quality_pct FLOAT64`
- `vegas_quality_pct FLOAT64`
- `has_composite_factors BOOL`
- `has_opponent_defense BOOL`
- `has_vegas_line BOOL`
- `default_feature_count INT64`
- `phase4_feature_count INT64`
- `phase3_feature_count INT64`
- `calculated_feature_count INT64`
- `feature_sources_summary STRING`

#### 2.2 Quality Scorer Implementation
**File:** `data_processors/precompute/ml_feature_store/quality_scorer.py`

Add method:
```python
# Feature category definitions
FEATURE_CATEGORIES = {
    'matchup': {
        'indices': [5, 6, 7, 8, 13, 14],
        'names': ['fatigue_score', 'shot_zone_mismatch_score', 'pace_score',
                  'usage_spike_score', 'opponent_def_rating', 'opponent_pace'],
        'critical': True
    },
    'player_history': {
        'indices': [0, 1, 2, 3, 4, 29, 30, 31, 32],
        'names': ['points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
                  'points_std_last_10', 'games_in_last_7_days', 'avg_points_vs_opponent',
                  'games_vs_opponent', 'minutes_avg_last_10', 'ppm_avg_last_10'],
        'critical': False
    },
    'team_context': {
        'indices': [22, 23, 24],
        'names': ['team_pace', 'team_off_rating', 'team_win_pct'],
        'critical': False
    },
    'vegas': {
        'indices': [25, 26, 27, 28],
        'names': ['vegas_points_line', 'vegas_opening_line', 'vegas_line_move', 'has_vegas_line'],
        'critical': False
    }
}

def calculate_quality_breakdown(
    feature_sources: Dict[int, str]
) -> Dict[str, Any]:
    """
    Calculate per-category quality breakdown with flat field structure.

    Returns:
        Dict with flat fields:
            matchup_quality_pct: float (0-100)
            player_history_quality_pct: float (0-100)
            team_context_quality_pct: float (0-100)
            vegas_quality_pct: float (0-100)
            has_composite_factors: bool
            has_opponent_defense: bool
            has_vegas_line: bool
            default_feature_count: int
            phase4_feature_count: int
            phase3_feature_count: int
            calculated_feature_count: int
            feature_sources_summary: str (JSON)
    """
```

#### 2.3 Integration
**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

Update `_build_feature_store_record()` method:
```python
# After alert level calculation
breakdown = self.quality_scorer.calculate_quality_breakdown(
    feature_sources=feature_sources
)

# Add all flat fields to record
record.update(breakdown)
```

#### 2.4 Validation Skill Integration
**File:** `skills/validate-daily/skill.py` (or create if doesn't exist)

Add feature quality summary:
```python
def check_feature_quality():
    """Add to daily validation output"""
    query = """
    SELECT
        game_date,
        COUNT(*) as total_players,
        ROUND(AVG(matchup_quality_pct), 1) as avg_matchup,
        ROUND(AVG(player_history_quality_pct), 1) as avg_history,
        ROUND(AVG(team_context_quality_pct), 1) as avg_team,
        ROUND(AVG(vegas_quality_pct), 1) as avg_vegas,
        COUNTIF(has_composite_factors = FALSE) as missing_composite,
        COUNTIF(quality_alert_level = 'RED') as red_count
    FROM nba_predictions.ml_feature_store_v2
    WHERE game_date >= CURRENT_DATE() - 1
    GROUP BY 1
    ORDER BY 1 DESC
    """
    # Display in validation output
```

#### 2.5 Testing
```bash
# Verify breakdown populated
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  feature_quality_score,
  quality_alert_level,
  matchup_quality_pct,
  player_history_quality_pct,
  has_composite_factors,
  default_feature_count,
  feature_sources_summary
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-06'
ORDER BY matchup_quality_pct ASC
LIMIT 10
"

# Expected for Feb 6 (pre-fix):
# - matchup_quality_pct = 0.0
# - has_composite_factors = FALSE
# - default_feature_count = 4
```

#### 2.6 Deployment
```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

---

### Phase 3: Trend Detection (1-2 hours)

**Goal:** Catch quality degradation proactively

#### 3.1 Daily Summary Table
**File:** `schemas/bigquery/predictions/feature_quality_daily.sql` (new)

Create table:
```sql
CREATE TABLE IF NOT EXISTS nba_predictions.feature_quality_daily (
  game_date DATE NOT NULL,

  -- Batch-level metrics
  total_players INT64,
  avg_feature_quality_score FLOAT64,

  -- Category averages
  avg_matchup_quality FLOAT64,
  avg_player_history_quality FLOAT64,
  avg_team_context_quality FLOAT64,
  avg_vegas_quality FLOAT64,

  -- Alert distribution
  red_count INT64,
  yellow_count INT64,
  green_count INT64,
  red_pct FLOAT64,

  -- Rolling averages (computed from historical data)
  matchup_quality_7day_avg FLOAT64,
  matchup_quality_delta FLOAT64,  -- vs 7-day avg

  -- Processor status (captured at summary time)
  composite_factors_ran BOOL,
  composite_factors_record_count INT64,

  -- Metadata
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
PARTITION BY game_date
OPTIONS(
  description="Daily feature quality summary for trend detection",
  partition_expiration_days=730  -- 2 years
);
```

#### 3.2 Summary Computation
**File:** `bin/monitoring/compute_feature_quality_daily.py` (new)

Create script:
```python
def compute_daily_summary(game_date: str):
    """
    Compute and store daily feature quality summary.

    Called after feature store completion for a game date.
    """

    # Query current day metrics
    current_metrics = query_feature_store_metrics(game_date)

    # Query 7-day rolling average
    rolling_avg = query_rolling_average(game_date, days=7)

    # Query processor status
    processor_status = query_processor_runs(game_date)

    # Compute delta
    delta = current_metrics['avg_matchup_quality'] - rolling_avg['matchup_quality']

    # Store summary
    store_summary(
        game_date=game_date,
        current_metrics=current_metrics,
        rolling_avg=rolling_avg,
        delta=delta,
        processor_status=processor_status
    )

    # Alert if delta < -30
    if delta < -30:
        send_slack_alert(...)
```

#### 3.3 Integration
Add to Phase 4 orchestrator completion hook or create new Cloud Scheduler job.

#### 3.4 Testing
```bash
# Backfill last 7 days
for date in $(seq -7 0); do
  target_date=$(date -d "$date days" +%Y-%m-%d)
  python bin/monitoring/compute_feature_quality_daily.py --date $target_date
done

# Verify summaries
bq query --use_legacy_sql=false "
SELECT
  game_date,
  avg_matchup_quality,
  matchup_quality_7day_avg,
  matchup_quality_delta,
  red_pct
FROM nba_predictions.feature_quality_daily
WHERE game_date >= CURRENT_DATE() - 7
ORDER BY game_date DESC
"
```

---

### Phase 4: Root Cause Attribution (2-3 hours)

**Goal:** Alert includes exact fix instructions

#### 4.1 Processor Status Query
**File:** `bin/monitoring/check_processor_status.py` (new or enhance existing)

Add function:
```python
def get_processor_status_for_date(game_date: str) -> Dict[str, Any]:
    """
    Query which processors ran successfully for a game date.

    Returns:
        {
            'player_composite_factors': {
                'ran': True/False,
                'last_run': timestamp,
                'record_count': int,
                'status': 'success'/'failed'/'not_run'
            },
            'ml_feature_store': {...},
            'team_defense_zone_analysis': {...}
        }
    """

    # Query nba_orchestration.processor_runs or equivalent
    # Check nba_precompute.player_composite_factors for record count
```

#### 4.2 Enhanced Alert Messages
**File:** `bin/monitoring/pipeline_canary_queries.py`

Enhance alert formatting:
```python
def format_feature_quality_alert(
    game_date: str,
    batch_metrics: Dict,
    processor_status: Dict
) -> str:
    """
    Format detailed alert with root cause and suggested fix.
    """

    alert = f"""
[RED] Feature Quality Alert - {game_date}

Summary:
- {batch_metrics['red_count']}/{batch_metrics['total_players']} players ({batch_metrics['red_pct']}%) have degraded features
- Average matchup quality: {batch_metrics['avg_matchup_quality']}% (expected: 95%)
- Quality delta: {batch_metrics['matchup_quality_delta']}% vs 7-day avg

Root Cause Detection:
"""

    # Check processor status
    if not processor_status['player_composite_factors']['ran']:
        alert += """
- player_composite_factors: DID NOT RUN
- Last successful run: {processor_status['player_composite_factors']['last_run']}
- Expected records: 200+, Found: {processor_status['player_composite_factors']['record_count']}

Suggested Fix:
1. Run composite factors processor:
   PYTHONPATH=. python -c "from data_processors.precompute.player_composite_factors import PlayerCompositeFactorsProcessor; p = PlayerCompositeFactorsProcessor(); p.run({{'analysis_date': '{game_date}'}})"

2. Regenerate feature store:
   PYTHONPATH=. python -c "from data_processors.precompute.ml_feature_store import MLFeatureStoreProcessor; p = MLFeatureStoreProcessor(); p.run({{'analysis_date': '{game_date}', 'force': True}})"

3. Verify quality improved:
   bq query --use_legacy_sql=false "SELECT AVG(matchup_quality_pct) FROM nba_predictions.ml_feature_store_v2 WHERE game_date = '{game_date}'"
"""

    return alert
```

#### 4.3 Testing
Test alert formatting with Feb 6 scenario.

---

## Prevention Mechanisms

### 1. Pre-Commit Schema Validation

**File:** `.pre-commit-hooks/validate_feature_quality_fields.py` (new)

Validate that:
- New features added to `FEATURE_CATEGORIES` in `quality_scorer.py`
- Category mappings stay in sync with feature definitions
- Schema changes include quality field updates

### 2. CI/CD Quality Checks

Add to deployment pipeline:
```bash
# Before deploying Phase 4 processors
python bin/tests/validate_quality_scorer.py

# Test cases:
# - All features mapped to exactly one category
# - Category indices match feature extractor
# - No duplicate feature indices
# - Quality breakdown adds up to 100%
```

### 3. Canary Queries (Every 30 min)

Already exists in `bin/monitoring/pipeline_canary_queries.py`, enhance with:
- Feature category quality checks
- Processor completion checks
- Quality trend checks

### 4. Daily Validation Skill

Enhance `/validate-daily` with feature quality section:
```
Feature Quality (Feb 6):
  Matchup:         0.0% ⚠️ CRITICAL
  Player History: 95.0% ✓
  Team Context:   40.0% ⚠️
  Vegas:          45.0% ⚠️

  RED alerts: 201/201 players (100%)
  Missing composite factors: 201 players

  Action: Check processor runs and regenerate feature store
```

### 5. Processor Dependency Validation

**File:** `orchestration/phase4_orchestrator.py`

Add validation before ML feature store processor:
```python
def validate_phase4_dependencies(game_date: str):
    """
    Validate all Phase 4 processors completed before ML feature store.
    """
    required_processors = [
        'PlayerCompositeFactorsProcessor',
        'TeamDefenseZoneAnalysisProcessor',
        # ... others
    ]

    for processor in required_processors:
        if not processor_completed(processor, game_date):
            raise DependencyNotMetError(f"{processor} not completed for {game_date}")
```

### 6. Scheduler Job Validation

**File:** `bin/tests/validate_scheduler_jobs.py` (new)

Test that Cloud Scheduler jobs include all required processors:
```python
def test_same_day_phase4_tomorrow_job():
    """Validate scheduler job includes all Phase 4 processors."""

    job_config = get_scheduler_job_config('same-day-phase4-tomorrow')
    processors = extract_processors_from_config(job_config)

    required = [
        'PlayerCompositeFactorsProcessor',
        'MLFeatureStoreProcessor',
        # ... others
    ]

    assert set(required).issubset(set(processors)), \
        f"Missing processors: {set(required) - set(processors)}"
```

---

## Success Criteria

### Detection Success Criteria

- [ ] RED alerts fire within 5 minutes of batch completion when critical quality issues occur
- [ ] Alerts fire on batch-level metrics (>10% RED) not individual player RED
- [ ] Zero false positives in first week of operation
- [ ] All alerts include actionable information (which category, which processor)

### Diagnostic Success Criteria

- [ ] Can identify root cause in <2 minutes without manual SQL
- [ ] Per-category quality visible in `/validate-daily` output
- [ ] Can query "show me all dates where matchup quality < 50%" in single SQL query
- [ ] Alert messages include suggested fix commands

### Trend Detection Success Criteria

- [ ] Can detect gradual quality degradation (>10% drop over 3 days)
- [ ] Daily summary table populated within 5 minutes of batch completion
- [ ] Can query 30-day quality trends with single SQL query
- [ ] Baseline comparison alerts work (vs 7-day rolling avg)

### Prevention Success Criteria

- [ ] Pre-commit hooks catch category mapping errors
- [ ] CI/CD validates quality scorer logic
- [ ] Canary queries run every 30 minutes
- [ ] Processor dependency validation prevents incomplete Phase 4 runs
- [ ] `/validate-daily` includes feature quality section

---

## Related Documentation

### Session Handoffs
- `docs/09-handoff/2026-02-05-SESSION-132-PART-2-FEATURE-QUALITY-VISIBILITY.md` - Original design (Session 132)
- `docs/09-handoff/2026-02-05-SESSION-133-BREAKOUT-CLASSIFIER-BLOCKER.md` - Breakout classifier issue (separate)

### Architecture Reviews
- Opus architectural review (Session 133) - Recommended flat schema over nested STRUCT

### Existing Systems
- `docs/02-operations/system-features.md` - Existing monitoring features
- `bin/monitoring/pipeline_canary_queries.py` - Existing canary system
- `skills/validate-daily/` - Existing validation skill

---

## Next Steps

### Immediate (This Session - Session 133)
1. **Review this document** with team/user
2. **Finalize schema design** - Confirm flat fields approach
3. **Create implementation tasks** - Break into discrete tasks
4. **Begin Phase 1 implementation** - Alert thresholds

### Short-term (Next 1-2 Sessions)
1. Complete Phase 1 + Phase 2 implementation
2. Deploy and test with historical data
3. Monitor for false positives
4. Document learnings

### Medium-term (Next Month)
1. Implement Phase 3 (trend detection)
2. Implement Phase 4 (root cause attribution)
3. Backfill daily summary table (30 days)
4. Create quality trend dashboards

### Long-term (Next Quarter)
1. Add automated remediation (auto-run missing processors)
2. Expand to other data quality metrics
3. Build quality SLOs and error budgets
4. Consider ML-based anomaly detection

---

**Document Version:** 1.0
**Last Updated:** February 5, 2026 (Session 133)
**Next Review:** After Phase 1 implementation
