# NEXT STEPS: Phase 3 + Phase 4 Completeness Checking

**Date:** 2025-11-22
**Status:** Ready to Start
**Decision:** Include Phase 3 + Phase 4 (user confirmed: "I prefer we do it right and include phase 3")

---

## What We've Completed

### ✅ Analysis & Planning
1. **Phase 4 Dependencies Analyzed** - `/docs/implementation/05-phase4-historical-dependencies-complete.md`
   - 5 processors identified with L5/L10/L15 game windows
   - Bootstrap problem documented (Day 0-30 backfill)
   - Multi-window complexity (player_daily_cache: L5/L7/L10/L14)

2. **Completeness Strategy Defined** - `/docs/implementation/08-data-completeness-checking-strategy.md`
   - Schedule-based completeness checking (compare expected vs actual games)
   - Rejected schema-based change detection approach
   - User confirmed: "I want the quality of data to be high and that requires having the proper backfilled data present"

3. **Opus AI Review Completed** - `/docs/architecture/historical-dependency-checking-plan.md`
   - Comprehensive implementation plan from Opus AI
   - Circuit breaker pattern (max 3 attempts, 7-day gaps)
   - Multi-window ALL-complete logic
   - Concrete alert thresholds (Day 10: 30%, Day 20: 80%, Day 30: 95%)
   - Cost: ~$3.50/month

4. **Phase 3 Assessment Completed** - `/docs/implementation/10-phase-applicability-assessment-CORRECTED.md`
   - 2 of 5 Phase 3 processors need completeness checking:
     - `upcoming_player_game_context` (L5/L7/L10/L14/L30 windows)
     - `upcoming_team_game_context` (L7/L14/L30 windows)
   - User confirmed: "without history checking, phase 3 will mess up"

5. **Implementation Plan Created** - `/docs/implementation/11-phase3-phase4-completeness-implementation-plan.md`
   - 7 processors in scope (2 Phase 3 + 5 Phase 4)
   - Week-by-week timeline (10-12 weeks realistic)
   - CompletenessChecker service design
   - Circuit breaker implementation
   - Monitoring infrastructure (6 BigQuery views)

---

## The Problem (Quick Recap)

### Without Completeness Checking

**Phase 3 Example**: `upcoming_player_game_context`
```python
# Day 5 of backfill (only 5 days of history available)
if historical_data.empty:
    return {'games_in_last_7_days': 0}  # ⚠️ Writes 0

# Day 25 of backfill (25 days of history, player didn't play in L7)
if historical_data.empty:
    return {'games_in_last_7_days': 0}  # ⚠️ Also writes 0
```

**Can't distinguish between**:
- Day 5: `0` = "no historical data yet" (expected)
- Day 25: `0` = "player didn't play in last 7 days" (valid data)

### With Completeness Checking

**Day 5**:
```json
{
  "games_in_last_7_days": 0,
  "completeness_percentage": 33.3,
  "is_production_ready": false,
  "backfill_bootstrap_mode": true,
  "processing_decision_reason": "processed_with_partial_data"
}
```

**Day 25**:
```json
{
  "games_in_last_7_days": 0,
  "completeness_percentage": 100.0,
  "is_production_ready": true,
  "backfill_bootstrap_mode": false,
  "processing_decision_reason": "processed_successfully"
}
```

**Now we can tell the difference!**

---

## Scope Confirmed

### Phase 3 Analytics (2 processors)

| Processor | Historical Windows | Upstream Table |
|-----------|-------------------|----------------|
| **upcoming_player_game_context** | L5/L7/L10/L14 games<br>L30 days boxscore | `player_game_summary` |
| **upcoming_team_game_context** | L7/L14 days<br>L30 days schedule | `team_defense_game_summary` |

### Phase 4 Precompute (5 processors)

| Processor | Historical Windows | Min Games | Multi-Window? |
|-----------|-------------------|-----------|---------------|
| **team_defense_zone_analysis** | L15 games | 15 | No |
| **player_shot_zone_analysis** | L10/L20 games | 10 | No |
| **player_daily_cache** | L5/L7/L10/L14 | 10 | ✅ YES |
| **player_composite_factors** | Cascade from above | - | Cascade |
| **ml_feature_store** | Cascade from above | - | Cascade |

**Total**: 7 processors, 107 new schema columns

---

## Timeline (Realistic)

| Week | Focus | Deliverable |
|------|-------|-------------|
| **1-2** | Core infrastructure | CompletenessChecker service + 1 processor working |
| **3-4** | Phase 4 rollout | All 5 Phase 4 processors |
| **5-6** | Phase 3 rollout | All 2 Phase 3 processors (date-based windows) |
| **7-8** | Monitoring | 6 BigQuery views + daily monitoring job |
| **9-10** | Historical backfill | 4 years of data with completeness metadata |
| **11-12** | Production hardening | Edge cases, testing, documentation |

**Realistic Completion**: 10-12 weeks (2.5-3 months)

---

## Cost Estimate

- **Completeness queries**: ~$2.60/month (Phase 4) + ~$0.90/month (Phase 3)
- **Monitoring views**: ~$1.50/month
- **Reprocess tracking**: ~$0.50/month
- **Historical backfill** (one-time): ~$1.00

**Total Ongoing**: ~$3.50-4.00/month

---

## Immediate Next Steps (Week 1)

### Decision Point: Confirm Scope

Before starting implementation, confirm:

**✅ Scope**:
- [ ] All 7 processors (2 Phase 3 + 5 Phase 4)? ← **User already confirmed**
- [ ] Or staged approach (Phase 4 first, then Phase 3)?

**✅ Timeline**:
- [ ] 10-12 weeks realistic?
- [ ] Can block other work or parallel development?

**✅ Priority**:
- [ ] Start with Phase 3 or Phase 4 first?
  - **Recommendation**: Phase 4 first (more complex, learn from it)
  - Then apply learnings to simpler Phase 3 (date-based windows)

---

## Week 1 Tasks (If Approved)

### Day 1-2: Core Service
- [ ] Create `/common/services/completeness_checker.py`
  - `check_completeness_batch()` method
  - Schedule query builder (expected games)
  - Upstream query builder (actual games)
  - Completeness calculation logic

### Day 3: Tracking Table
- [ ] Create `nba_orchestration.reprocess_attempts` table
  - Track reprocessing attempts per entity/date
  - Circuit breaker logic (max 3 attempts, 7-day gaps)

### Day 4-5: First Processor (Pilot)
- [ ] Update `team_defense_zone_analysis` schema (14 new columns)
- [ ] Integrate CompletenessChecker into processor
- [ ] Add circuit breaker checking
- [ ] Add bootstrap mode detection
- [ ] Write completeness metadata to output

### Day 6-7: Testing
- [ ] Integration test with 1 month of data
- [ ] Verify completeness calculations accurate
- [ ] Verify production-ready flag set correctly (90% threshold)
- [ ] Verify bootstrap mode handling (Day 1-30)

**Week 1 Deliverable**: 1 processor with working completeness checking

---

## Key Implementation Patterns

### Pattern 1: CompletenessChecker Service

```python
from common.services.completeness_checker import CompletenessChecker

class TeamDefenseZoneAnalysisProcessor(BaseProcessor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.completeness_checker = CompletenessChecker(
            self.bq_client, self.project_id
        )

    def calculate_precompute(self):
        all_teams = self._get_all_teams()

        # Batch completeness check (2 queries total, not 30)
        completeness_results = self.completeness_checker.check_completeness_batch(
            entity_ids=all_teams,
            entity_type='team',
            analysis_date=self.opts['analysis_date'],
            upstream_table='nba_analytics.team_defense_game_summary',
            upstream_entity_field='defending_team_abbr',
            lookback_window=15,  # games
            window_type='games',
            season_start_date=self.opts['season_start_date']
        )

        for team_abbr in all_teams:
            completeness = completeness_results[team_abbr]

            # Check circuit breaker
            if self._circuit_breaker_active(team_abbr):
                self._track_skip('circuit_breaker_active', completeness)
                continue

            # Check production readiness (90% threshold)
            if not completeness['is_production_ready']:
                logger.warning(
                    f"{team_abbr}: {completeness['completeness_pct']}% complete "
                    f"({completeness['actual_count']}/{completeness['expected_count']} games)"
                )
                self._increment_reprocess_count(team_abbr)
                self._track_skip('incomplete_upstream_data', completeness)
                continue

            # Process with complete data
            metrics = self._calculate_zone_metrics(team_abbr)
            self._write_output(team_abbr, metrics, completeness)
```

### Pattern 2: Multi-Window Processor

```python
# player_daily_cache (requires ALL windows complete)
windows = [
    ('l5', 5, 'games'),
    ('l10', 10, 'games'),
    ('l7d', 7, 'days'),
    ('l14d', 14, 'days')
]

completeness_by_window = {}
for window_name, lookback, window_type in windows:
    completeness_by_window[window_name] = \
        self.completeness_checker.check_completeness_batch(
            entity_ids=all_players,
            entity_type='player',
            upstream_table='nba_analytics.player_game_summary',
            lookback_window=lookback,
            window_type=window_type
        )

# ALL windows must be production-ready (conservative approach)
for player_lookup in all_players:
    all_windows_ready = all([
        completeness_by_window['l5'][player_lookup]['is_production_ready'],
        completeness_by_window['l10'][player_lookup]['is_production_ready'],
        completeness_by_window['l7d'][player_lookup]['is_production_ready'],
        completeness_by_window['l14d'][player_lookup]['is_production_ready']
    ])

    if not all_windows_ready:
        # Skip - not all windows complete
        continue

    # Process with all windows complete
```

### Pattern 3: Circuit Breaker

```python
def _check_circuit_breaker(self, entity_id, analysis_date):
    """Check if entity has exceeded max reprocess attempts."""

    query = f"""
    SELECT attempt_number, circuit_breaker_tripped, circuit_breaker_until
    FROM `nba_orchestration.reprocess_attempts`
    WHERE processor_name = '{self.processor_name}'
      AND entity_id = '{entity_id}'
      AND analysis_date = DATE('{analysis_date}')
    ORDER BY attempt_number DESC
    LIMIT 1
    """

    result = self.bq_client.query(query).to_dataframe()

    if result.empty:
        return {'active': False, 'attempts': 0}

    last_attempt = result.iloc[0]

    if last_attempt['circuit_breaker_tripped']:
        # Check if 7 days have passed
        if datetime.now(timezone.utc) < last_attempt['circuit_breaker_until']:
            return {'active': True, 'until': last_attempt['circuit_breaker_until']}

    return {'active': False, 'attempts': last_attempt['attempt_number']}

def _increment_reprocess_count(self, entity_id, analysis_date):
    """Track reprocessing attempt, trip circuit breaker on 3rd attempt."""

    circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
    next_attempt = circuit_status['attempts'] + 1

    # Trip circuit breaker on 3rd attempt
    if next_attempt >= 3:
        circuit_breaker_until = datetime.now(timezone.utc) + timedelta(days=7)
        logger.error(
            f"{entity_id}: Circuit breaker TRIPPED (attempt {next_attempt}). "
            f"Manual intervention required. Retry after: {circuit_breaker_until}"
        )

    # Record attempt
    self._insert_reprocess_attempt(entity_id, analysis_date, next_attempt)
```

---

## Schema Changes (Per Processor Table)

### Standard Columns (14 per table)

```sql
-- Completeness Metrics
expected_games_count INT64,
actual_games_count INT64,
completeness_percentage FLOAT64,
missing_games_count INT64,

-- Production Readiness
is_production_ready BOOLEAN,
data_quality_issues ARRAY<STRING>,

-- Circuit Breaker
last_reprocess_attempt_at TIMESTAMP,
reprocess_attempt_count INT64,
circuit_breaker_active BOOLEAN,
circuit_breaker_until TIMESTAMP,

-- Bootstrap/Override
manual_override_required BOOLEAN,
season_boundary_detected BOOLEAN,
backfill_bootstrap_mode BOOLEAN,
processing_decision_reason STRING
```

### Multi-Window Columns (9 additional for player_daily_cache)

```sql
-- Per-Window Completeness
l5_completeness_pct FLOAT64,
l5_is_complete BOOLEAN,
l10_completeness_pct FLOAT64,
l10_is_complete BOOLEAN,
l7d_completeness_pct FLOAT64,
l7d_is_complete BOOLEAN,
l14d_completeness_pct FLOAT64,
l14d_is_complete BOOLEAN,

-- Multi-Window Logic
all_windows_complete BOOLEAN
```

---

## Monitoring (Week 7-8)

### View 1: Completeness Summary
```sql
-- Daily completeness by processor
SELECT
    processor_name,
    analysis_date,
    AVG(completeness_percentage) as avg_completeness,
    COUNTIF(is_production_ready) as production_ready_count,
    COUNTIF(circuit_breaker_active) as blocked_count
FROM all_processors
GROUP BY processor_name, analysis_date
ORDER BY analysis_date DESC;
```

### View 2: Incomplete Entities (Action Required)
```sql
-- Which entities need attention?
SELECT
    processor_name,
    entity_id,
    completeness_percentage,
    missing_games_count,
    reprocess_attempt_count,
    circuit_breaker_active
FROM all_processors
WHERE NOT is_production_ready
  AND analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY circuit_breaker_active DESC, completeness_percentage ASC;
```

### View 3: Backfill Progress
```sql
-- Are we on track? (Day 10: 30%, Day 20: 80%, Day 30: 95%)
SELECT
    analysis_date,
    DATE_DIFF(analysis_date, season_start, DAY) as days_since_start,
    AVG(completeness_percentage) as avg_completeness,
    CASE
        WHEN DATE_DIFF(analysis_date, season_start, DAY) >= 30 THEN 95
        WHEN DATE_DIFF(analysis_date, season_start, DAY) >= 20 THEN 80
        WHEN DATE_DIFF(analysis_date, season_start, DAY) >= 10 THEN 30
        ELSE 0
    END as expected_threshold
FROM nba_precompute.team_defense_zone_analysis
WHERE backfill_bootstrap_mode = TRUE
GROUP BY analysis_date, season_start
ORDER BY analysis_date;
```

---

## Phase 3 vs Phase 4 Differences

| Aspect | Phase 3 | Phase 4 |
|--------|---------|---------|
| **Window Type** | Date-based (L7 days, L14 days) | Game-count (L10 games, L15 games) |
| **Query Pattern** | `WHERE game_date BETWEEN date - 30 AND date` | `WHERE game_rank <= 15` (ROW_NUMBER) |
| **Completeness Check** | `window_type='days'` | `window_type='games'` |
| **Complexity** | Simpler (date ranges) | More complex (ROW_NUMBER partitioning) |

**Recommendation**: Start with Phase 4 (harder problem), then apply learnings to Phase 3 (simpler).

---

## Success Criteria

### Week 2 (After First Processor)
- [x] Completeness percentage accurate (matches manual count)
- [x] Production-ready flag set correctly (90% threshold)
- [x] Bootstrap mode handling works (Day 1-30)

### Week 6 (After All Processors)
- [x] All 7 processors have completeness checking
- [x] Multi-window logic works (player_daily_cache)
- [x] Cascade dependencies handled (player_composite_factors)

### Week 10 (After Backfill)
- [x] 4 years of data backfilled
- [x] Alert thresholds working (Day 10: 30%, Day 20: 80%, Day 30: 95%)
- [x] Circuit breaker triggered appropriately (max 3 attempts)
- [x] Reprocessing queue identified (incomplete entities)

### Week 12 (Production)
- [x] Zero false positives (no alerts for expected gaps)
- [x] High confidence in data quality signals
- [x] Manual intervention only when truly needed

---

## Documents Created

1. **Phase 4 Dependencies**: `/docs/implementation/05-phase4-historical-dependencies-complete.md`
2. **Completeness Strategy**: `/docs/implementation/08-data-completeness-checking-strategy.md`
3. **Opus Review Input**: `/docs/for-review/OPUS_REVIEW_historical-dependency-checking.md`
4. **Opus Plan (Full)**: `/docs/architecture/historical-dependency-checking-plan.md`
5. **Phase 3 Assessment**: `/docs/implementation/10-phase-applicability-assessment-CORRECTED.md`
6. **Implementation Plan**: `/docs/implementation/11-phase3-phase4-completeness-implementation-plan.md`
7. **This Document**: `/docs/implementation/12-NEXT-STEPS-completeness-checking.md`

---

## Open Questions

1. **Start with Phase 3 or Phase 4?**
   - **Recommendation**: Phase 4 first (more complex, sets the pattern)

2. **Multi-Window Strictness**: Is requiring ALL windows at 90% too conservative?
   - **Opus Plan**: Yes, ALL windows must be complete (conservative approach)
   - **Alternative**: Allow "best effort" with partial windows?

3. **Backfill Coordination**: When Phase 3 reprocesses, should Phase 4 auto-reprocess?
   - **Opus Plan**: Manual reprocessing for historical, auto for recent (60 days)

4. **Manual Override Process**: What's the workflow when circuit breaker trips?
   - **Opus Plan**: Track in `manual_override_required` flag
   - **Need**: Define Slack notification or admin UI workflow

---

## Ready to Start?

**If you approve the scope and timeline, we can start Week 1 tasks immediately:**

1. Create CompletenessChecker service
2. Create reprocess_attempts tracking table
3. Update team_defense_zone_analysis schema
4. Integrate completeness checking
5. Test with 1 month of data

**Timeline**: 10-12 weeks to full production with all 7 processors

**Cost**: ~$3.50-4.00/month ongoing

**Next**: Your approval to proceed, or questions/adjustments to the plan.
