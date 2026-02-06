# Session 132 Part 2 - Feature Quality Visibility System

**Date:** February 5, 2026
**Status:** HANDOFF - Analysis Complete, Implementation Ready
**Session Type:** Design & Analysis

---

## Executive Summary

During Session 132, we discovered ALL 201 players had `MATCHUP_UNAVAILABLE` status for Feb 6 predictions due to a missing processor in the Cloud Scheduler job. This took 2+ hours to diagnose manually because **we have no visibility into ML feature quality at the individual feature level**. This document provides the analysis, recommended solution, and implementation plan for a Feature Quality Visibility System that would catch such issues within minutes instead of hours.

---

## Background: The Discovery

### Timeline of Events

| Time (UTC) | Event |
|------------|-------|
| ~18:00 | Feb 6 predictions generated with feature_quality_score ~74 (acceptable) |
| ~19:30 | Manual investigation reveals ALL players have `matchup_data_status = MATCHUP_UNAVAILABLE` |
| ~20:00 | Root cause identified: `PlayerCompositeFactorsProcessor` missing from `same-day-phase4-tomorrow` scheduler job |
| ~20:15 | Manual fix: Ran composite factors processor, regenerated feature store |
| ~20:45 | Feature quality improved: 73.92 -> 85.28 |

### What Went Wrong

1. **Scheduler Job Incomplete**: `same-day-phase4-tomorrow` only ran `MLFeatureStoreProcessor`, not `PlayerCompositeFactorsProcessor`
2. **Feature Store Degraded Silently**: Without composite factors, features 5-8 used defaults (40 quality points instead of 100)
3. **Aggregate Score Masked Problem**: `feature_quality_score` of 74 looked acceptable, hiding that ALL matchup data was missing
4. **No Automated Alert**: Nothing flagged that 100% of players had degraded matchup data

### Why This Matters

| Impact | Description |
|--------|-------------|
| **Time to Detect** | 2+ hours of manual investigation |
| **Prediction Quality** | Feb 2 similar issue caused 49.1% hit rate (Session 96) |
| **Business Cost** | Bad predictions = losing money on bets |
| **Pattern Recognition** | This is at least the 3rd time this type of issue occurred |

---

## Current State

### What's Working

- [x] Scheduler job fixed: Both processors now included
- [x] Feature store regenerated with correct data (85.28 quality)
- [x] Composite factors generated for Feb 6 (201 records)
- [x] Matchup data status now shows improvement

### What's NOT Working

- [ ] Original 86 predictions still use OLD degraded feature data (before fix)
- [ ] Prediction batch stuck at 0/93 (breakout classifier feature mismatch - separate issue)
- [ ] No automated alerts for feature quality degradation
- [ ] No per-feature visibility in `/validate-daily`

### Data Quality State (Feb 6)

| Metric | Before Fix | After Fix |
|--------|------------|-----------|
| Feature Quality Score | 73.92 | 85.28 |
| Matchup Data Status | 100% UNAVAILABLE | 0% UNAVAILABLE |
| Composite Factors Records | 0 | 201 |
| Active Predictions | 86 (degraded) | 86 (degraded) |

**Critical Note**: The 86 existing predictions still use degraded features. They need to be regenerated after worker issues are resolved.

---

## The Visibility Problem

### Specific Examples of What We Cannot See Today

**Example 1: Aggregate Score Hides Component Failures**
```sql
-- What we see:
feature_quality_score = 74.0  -- Looks OK!

-- What we don't see:
matchup_quality = 0%          -- ALL matchup features using defaults
player_history_quality = 95%  -- This is fine
team_context_quality = 40%    -- Using defaults
vegas_quality = 45%           -- Missing for many players
```

**Example 2: matchup_data_status is Binary**
```sql
-- Current: Either works or doesn't
matchup_data_status = 'MATCHUP_UNAVAILABLE'  -- But WHY? Which features?

-- Needed: Detailed breakdown
has_composite_factors = FALSE
has_opponent_defense = TRUE
composite_fallback_reason = 'processor_not_run'
```

**Example 3: No Historical Trend Detection**
```sql
-- Cannot answer: "Is feature quality degrading over time?"
-- Cannot answer: "Which features fail most often?"
-- Cannot answer: "What % of predictions use defaults?"
```

### Impact Assessment

| Scenario | Current State | With Visibility |
|----------|---------------|-----------------|
| Matchup data missing | Discover after 2+ hours | Alert within 5 minutes |
| Vegas lines degraded | Never noticed | Dashboard shows 55% coverage |
| Single feature NULL | Hidden in aggregate | Specific feature flagged |
| Quality trending down | No detection | Weekly trend alerts |

### Comparison: Before vs After (Proposed)

**Before (Current):**
```json
{
  "feature_quality_score": 74.0,
  "matchup_data_status": "MATCHUP_UNAVAILABLE",
  "data_quality_issues": ["upstream_player_daily_cache_incomplete"]
}
```

**After (Proposed):**
```json
{
  "feature_quality_score": 74.0,
  "quality_alert_level": "RED",
  "quality_alerts": ["all_matchup_features_defaulted", "composite_factors_missing"],
  "feature_quality_breakdown": {
    "matchup_quality": 0.0,
    "player_history_quality": 95.0,
    "team_context_quality": 40.0,
    "vegas_quality": 45.0,
    "has_composite_factors": false,
    "has_opponent_defense": true,
    "degraded_feature_indices": [5, 6, 7, 8],
    "degraded_feature_names": ["fatigue_score", "shot_zone_mismatch_score", "pace_score", "usage_spike_score"]
  }
}
```

---

## Recommended Solution

### High-Level Approach

Implement a **two-phase solution** that provides both alerting and diagnostics:

1. **Phase 1: Quality Alert Thresholds** (1 hour)
   - Add `quality_alert_level` (GREEN/YELLOW/RED) to feature store records
   - Add Slack alerts when batch-level quality degrades
   - Integrate with existing monitoring infrastructure

2. **Phase 2: Feature Quality Breakdown Struct** (2-3 hours)
   - Add detailed per-category quality breakdown
   - Track which specific features are degraded
   - Enable root cause analysis without manual SQL

### Why This Approach

| Alternative | Pros | Cons | Decision |
|-------------|------|------|----------|
| Feature Quality Matrix Table | Full history | 2.7M rows/year, complex | Defer - overkill for now |
| Quality Alert Thresholds only | Simple, fast | No diagnostics | Insufficient alone |
| Full struct only | Rich data | No real-time alerts | Missing prevention |
| **Alerts + Struct (chosen)** | **Both prevention AND diagnostics** | **3-4 hours total** | **Best balance** |

### Trade-offs Accepted

- **Storage**: Breakdown struct adds ~500 bytes per record (~100KB/day) - acceptable
- **Complexity**: Two new fields vs. one - minimal maintenance burden
- **Query Impact**: Struct is nested JSON, slightly slower to query - acceptable for diagnostics

---

## Implementation Guide

### Phase 1: Quality Alert Thresholds (1 hour)

**Goal**: Detect feature quality issues within 5 minutes of batch completion.

#### Files to Modify

1. **`data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`**
   - Add `_calculate_alert_level()` method
   - Add `quality_alert_level` and `quality_alerts` to record

2. **`data_processors/precompute/ml_feature_store/quality_scorer.py`**
   - Add `calculate_alert_level()` method with threshold logic

3. **`predictions/coordinator/coordinator.py`** (or new endpoint)
   - Add `/check-feature-quality` endpoint OR integrate into existing `/check-stalled`
   - Query batch-level quality after feature store completion
   - Send Slack alert if RED level detected

#### Alert Thresholds

```python
def calculate_alert_level(feature_sources: Dict[int, str], matchup_status: str) -> tuple:
    """
    Calculate quality alert level based on feature source distribution.

    Returns:
        tuple: (alert_level: str, alerts: List[str])
    """
    alerts = []

    # Count defaults
    default_count = sum(1 for s in feature_sources.values() if s == 'default')
    default_pct = default_count / len(feature_sources) * 100

    # Critical features (5-8: composite, 13-14: defense)
    critical_indices = [5, 6, 7, 8, 13, 14]
    critical_defaults = sum(1 for i in critical_indices if feature_sources.get(i) == 'default')

    # Determine level
    if matchup_status == 'MATCHUP_UNAVAILABLE':
        alerts.append('all_matchup_features_defaulted')
        return 'RED', alerts

    if default_pct > 20:
        alerts.append(f'high_default_rate_{default_pct:.0f}pct')
        return 'RED', alerts

    if critical_defaults > 2:
        alerts.append(f'critical_features_missing_{critical_defaults}_of_6')
        return 'YELLOW', alerts

    if default_pct > 5:
        alerts.append(f'elevated_default_rate_{default_pct:.0f}pct')
        return 'YELLOW', alerts

    return 'GREEN', alerts
```

#### Schema Changes

Add to `ml_feature_store_v2` schema:
```json
{
  "name": "quality_alert_level",
  "type": "STRING",
  "mode": "NULLABLE",
  "description": "GREEN/YELLOW/RED based on feature quality thresholds"
},
{
  "name": "quality_alerts",
  "type": "STRING",
  "mode": "REPEATED",
  "description": "List of specific quality alerts triggered"
}
```

#### Testing

```bash
# After implementation, regenerate feature store for test date
PYTHONPATH=. python -c "
from data_processors.precompute.ml_feature_store import MLFeatureStoreProcessor
p = MLFeatureStoreProcessor()
p.run({'analysis_date': '2026-02-06', 'force': True})
"

# Verify alerts
bq query --use_legacy_sql=false "
SELECT
  quality_alert_level,
  COUNT(*) as count,
  ARRAY_AGG(DISTINCT alert IGNORE NULLS) as unique_alerts
FROM nba_predictions.ml_feature_store_v2,
UNNEST(quality_alerts) as alert
WHERE game_date = '2026-02-06'
GROUP BY 1
"
```

#### Deployment

```bash
./bin/deploy-service.sh nba-phase4-precompute-processors
```

---

### Phase 2: Feature Quality Breakdown Struct (2-3 hours)

**Goal**: Provide detailed diagnostics when quality issues occur.

#### Files to Modify

1. **`data_processors/precompute/ml_feature_store/quality_scorer.py`**
   - Add `calculate_quality_breakdown()` method
   - Define feature category mappings

2. **`data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`**
   - Call breakdown calculator
   - Add `feature_quality_breakdown` to record

3. **`predictions/worker/data_loaders.py`**
   - Load breakdown from feature store
   - Pass to worker for logging/decisions

#### Feature Category Definitions

```python
FEATURE_CATEGORIES = {
    'matchup': {
        'indices': [5, 6, 7, 8, 13, 14],  # Composite factors + opponent defense
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

def calculate_quality_breakdown(feature_sources: Dict[int, str]) -> Dict:
    """Calculate per-category quality breakdown."""
    breakdown = {}
    degraded_indices = []
    degraded_names = []

    for category, config in FEATURE_CATEGORIES.items():
        category_sources = [feature_sources.get(i, 'default') for i in config['indices']]
        high_quality = sum(1 for s in category_sources if s in ('phase4', 'calculated'))
        total = len(config['indices'])
        quality_pct = high_quality / total * 100 if total > 0 else 0

        breakdown[f'{category}_quality'] = round(quality_pct, 1)

        # Track degraded features
        for i, idx in enumerate(config['indices']):
            if feature_sources.get(idx, 'default') == 'default':
                degraded_indices.append(idx)
                degraded_names.append(config['names'][i])

    # Add binary flags for critical features
    breakdown['has_composite_factors'] = all(
        feature_sources.get(i) != 'default' for i in [5, 6, 7, 8]
    )
    breakdown['has_opponent_defense'] = all(
        feature_sources.get(i) != 'default' for i in [13, 14]
    )

    breakdown['degraded_feature_indices'] = degraded_indices
    breakdown['degraded_feature_names'] = degraded_names

    return breakdown
```

#### Schema Changes

Add to `ml_feature_store_v2` schema:
```json
{
  "name": "feature_quality_breakdown",
  "type": "RECORD",
  "mode": "NULLABLE",
  "fields": [
    {"name": "matchup_quality", "type": "FLOAT64"},
    {"name": "player_history_quality", "type": "FLOAT64"},
    {"name": "team_context_quality", "type": "FLOAT64"},
    {"name": "vegas_quality", "type": "FLOAT64"},
    {"name": "has_composite_factors", "type": "BOOL"},
    {"name": "has_opponent_defense", "type": "BOOL"},
    {"name": "degraded_feature_indices", "type": "INT64", "mode": "REPEATED"},
    {"name": "degraded_feature_names", "type": "STRING", "mode": "REPEATED"}
  ]
}
```

#### Testing

```bash
# Verify breakdown is populated
bq query --use_legacy_sql=false "
SELECT
  player_lookup,
  feature_quality_score,
  feature_quality_breakdown.matchup_quality,
  feature_quality_breakdown.has_composite_factors,
  ARRAY_LENGTH(feature_quality_breakdown.degraded_feature_names) as degraded_count
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-06'
LIMIT 10
"
```

---

## Success Criteria

- [ ] Quality alerts fire within 5 minutes of batch completion when RED threshold hit
- [ ] Can identify which specific features are degraded without manual SQL
- [ ] Slack alerts include actionable information (which features, suggested fix)
- [ ] `/validate-daily` shows feature quality breakdown summary
- [ ] Time to diagnose issues reduced from 2+ hours to <10 minutes

---

## Open Questions

1. **Should quality_alert_level block predictions?**
   - Current thinking: No, just alert. Business decides whether to proceed.
   - Alternative: RED level could pause prediction generation pending review.

2. **Where should batch-level alerts be checked?**
   - Option A: New `/check-feature-quality` endpoint called after feature store completes
   - Option B: Integrate into existing `/check-stalled` endpoint
   - Recommendation: Option A for cleaner separation of concerns

3. **Should we backfill breakdown data for historical records?**
   - Useful for trend analysis but adds complexity
   - Recommendation: Start fresh, don't backfill unless trends become important

---

## Immediate Actions for Next Session

### Priority 1: Fix Blocking Issues (Before Visibility Work)

1. **Fix breakout classifier feature mismatch** preventing worker predictions
   - Root cause: v2_37features vs v2_39features incompatibility
   - Location: Worker model loading logic

2. **Regenerate Feb 6 predictions** once workers are fixed
   - Current 86 predictions use degraded feature data
   - New predictions will use fixed feature store (85.28 quality)

### Priority 2: Implement Feature Quality Visibility

3. **Phase 1**: Quality Alert Thresholds (1 hour)
   - Follow implementation guide above
   - Deploy to Phase 4 processors
   - Test with Feb 6 data

4. **Phase 2**: Feature Quality Breakdown (2-3 hours)
   - Follow implementation guide above
   - Integrate with `/validate-daily`
   - Create documentation

---

## References

### Related Session Handoffs
- `2026-02-05-SESSION-132-HANDOFF.md` - Worker health check fixes
- `2026-02-05-SESSION-132-AUTOMATED-BATCH-CLEANUP.md` - Stalled batch automation
- `2026-02-05-SESSION-132-PREVENTION-IMPROVEMENTS.md` - Silent failure prevention

### Key Files
- `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`
- `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/quality_scorer.py`
- `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/feature_extractor.py`
- `/home/naji/code/nba-stats-scraper/predictions/worker/data_loaders.py`

### Useful Queries

```sql
-- Check current feature quality distribution
SELECT
  game_date,
  matchup_data_status,
  COUNT(*) as players,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  ROUND(MIN(feature_quality_score), 1) as min_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 7
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- Find players with degraded matchup data
SELECT player_lookup, feature_quality_score, matchup_data_status, data_quality_issues
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = '2026-02-06'
  AND matchup_data_status = 'MATCHUP_UNAVAILABLE'
ORDER BY feature_quality_score;

-- Check composite factors coverage
SELECT
  DATE(analysis_date) as date,
  COUNT(*) as records
FROM nba_precompute.player_composite_factors
WHERE analysis_date >= CURRENT_DATE() - 3
GROUP BY 1
ORDER BY 1 DESC;
```

---

## Next Session Checklist

- [ ] Review this handoff document
- [ ] Run `./bin/check-deployment-drift.sh --verbose` to verify deployment state
- [ ] Check if worker issues (breakout classifier) are resolved
- [ ] Regenerate Feb 6 predictions if workers are fixed
- [ ] Begin Phase 1 implementation (Quality Alert Thresholds)
- [ ] Test alerts with current data before deploying
- [ ] Document any deviations from this plan

---

**Session End:** 2026-02-05
**Estimated Next Session Work:** 4-5 hours (fix blocking issues + Phase 1 + Phase 2)
**Key Insight:** The aggregate feature_quality_score is a lie - it hides component failures. Per-category visibility is essential for operational reliability.
