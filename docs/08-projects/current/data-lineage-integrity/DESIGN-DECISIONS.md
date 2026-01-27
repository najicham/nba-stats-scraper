# Data Lineage Integrity: Design Decisions

**Date**: 2026-01-26
**Status**: Design Complete, Ready for Implementation
**Authors**: External Reviewers (Opus, Sonnet) + Implementation Agent

---

## Executive Summary

This document captures the design decisions for preventing and detecting cascade contamination in the NBA Props Platform data pipeline. It synthesizes recommendations from two independent external reviews and documents the trade-offs considered.

**The Core Problem**: 81% of this season's game data was backfilled late, causing downstream computed values (rolling averages, ML features, predictions) to be calculated with incomplete data windows.

**The Solution**: A prevention-first architecture that:
1. Blocks processing when dependencies are incomplete
2. Tags all records with quality metadata
3. Validates through recomputation comparison
4. Auto-remediates when late data arrives

---

## External Review Summary

### Reviewers

Two independent Claude instances reviewed our architecture via web chat:
- **Opus**: Focused on operational patterns, data contracts, cascade remediation
- **Sonnet**: Focused on structural rigor, quality tracking, validation frameworks

### Key Insight (Both Agreed)

> "The pipeline runs on a **clock** (scheduled times), but it should run on **data readiness**. When data arrives late, downstream phases shouldn't compute wrong values — they should either wait or produce explicit NULLs that get filled in later."

> "**A missing value is better than a wrong value.**"

### Full Review Documents

- Opus review: `docs/08-projects/current/data-lineage-integrity/reviews/opus-review.md`
- Sonnet review: `docs/08-projects/current/data-lineage-integrity/reviews/sonnet-review.md`

---

## Design Decisions

### Decision 1: Architecture Layers

**Options Considered**:

| Option | Description | Source |
|--------|-------------|--------|
| A | 4 layers: Prevention → Detection → Validation → Remediation | Opus |
| B | 3 layers: Prevention → Quality Tracking → Validation | Sonnet |
| C | Hybrid: Prevention → Quality Tracking → Validation → Remediation | Synthesis |

**Decision**: **Option C (Hybrid)**

**Rationale**:
- Opus's explicit remediation layer is valuable for auto-healing
- Sonnet's quality tracking layer provides better observability
- Combining both gives us prevention, tracking, validation, AND remediation

**Final Architecture**:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: PREVENTION (Processing Time)                                   │
│  ─────────────────────────────────────                                   │
│  • Window completeness checks before computing rolling averages          │
│  • Dependency verification before phase transitions                      │
│  • Processing gates that block on incomplete data                        │
│  • Fail fast: NULL > wrong value                                        │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 2: QUALITY TRACKING (Every Record)                                │
│  ────────────────────────────────────────                                │
│  • Quality scores (0-1 scale) on all computed records                   │
│  • Completeness flags (COMPLETE, PARTIAL, INCOMPLETE)                   │
│  • Processing context (daily, backfill, manual)                         │
│  • Upstream dependency metadata                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 3: VALIDATION (Batch)                                             │
│  ───────────────────────────                                             │
│  • /validate-daily (pipeline health)                                     │
│  • /validate-historical (completeness)                                   │
│  • /validate-lineage (correctness via recomputation)                    │
│  • Tiered approach: aggregate → sample → spot check                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 4: REMEDIATION (Automated)                                        │
│  ────────────────────────────────                                        │
│  • Late data detection triggers cascade reprocessing                    │
│  • Automatic downstream recomputation                                    │
│  • Version tracking for before/after comparison                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### Decision 2: Quality Metadata Schema

**Options Considered**:

| Option | Description | Complexity | Source |
|--------|-------------|------------|--------|
| A | Simple columns: `data_quality_flag` + `*_complete` booleans | Low | Opus |
| B | Full STRUCTs: `data_quality`, `processing_context`, `dependency_metadata` | High | Sonnet |
| C | Hybrid: Simple columns + lightweight quality score | Medium | Synthesis |

**Decision**: **Option C (Hybrid)**

**Rationale**:
- Option A is too simple for debugging complex issues
- Option B adds significant schema complexity and query overhead
- Option C provides actionable metadata without over-engineering

**Schema Design**:

```sql
-- Phase 3: Analytics tables (source of downstream)
ALTER TABLE nba_analytics.player_game_summary
ADD COLUMN data_quality_flag STRING DEFAULT 'complete',
-- Values: 'complete', 'partial', 'incomplete', 'corrected'
ADD COLUMN quality_score FLOAT64 DEFAULT 1.0,
-- 0-1 scale, 1.0 = perfect
ADD COLUMN processing_context STRING DEFAULT 'daily';
-- Values: 'daily', 'backfill', 'manual', 'cascade'

-- Phase 4: Precompute tables (rolling calculations)
ALTER TABLE nba_precompute.player_composite_factors
ADD COLUMN quality_score FLOAT64 DEFAULT 1.0,
ADD COLUMN window_completeness FLOAT64 DEFAULT 1.0,
-- Ratio of actual/expected games in rolling window
ADD COLUMN points_last_5_complete BOOL DEFAULT true,
ADD COLUMN points_last_10_complete BOOL DEFAULT true,
ADD COLUMN points_last_15_complete BOOL DEFAULT true,
ADD COLUMN points_last_20_complete BOOL DEFAULT true,
ADD COLUMN upstream_quality_min FLOAT64 DEFAULT 1.0,
-- Minimum quality score of input records
ADD COLUMN processing_context STRING DEFAULT 'daily';

-- Phase 5: Predictions
ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN input_quality_score FLOAT64 DEFAULT 1.0,
-- Quality score of features used
ADD COLUMN confidence_level STRING DEFAULT 'HIGH';
-- Values: 'HIGH', 'MEDIUM', 'LOW' based on input quality
```

**Trade-offs Accepted**:
- Less detailed than Sonnet's full STRUCTs
- Easier to query and understand
- Can extend later if needed

---

### Decision 3: Processing Gate Behavior

**Options Considered**:

| Situation | Option A: Strict | Option B: Permissive | Decision |
|-----------|------------------|----------------------|----------|
| 0% data available | FAIL | FAIL | **FAIL** |
| 50% data available | FAIL | PROCEED_WITH_WARNING | **FAIL** |
| 80% data available | WAIT | PROCEED_WITH_WARNING | **PROCEED_WITH_WARNING** |
| 100% data, quality issues | PROCEED_WITH_WARNING | PROCEED | **PROCEED_WITH_WARNING** |
| 100% data, no issues | PROCEED | PROCEED | **PROCEED** |

**Decision**: **Moderate strictness with 80% threshold**

**Rationale**:
- Below 80% completeness, rolling averages are too unreliable
- Above 80%, we can proceed but must flag the quality
- Strict gating would cause too many pipeline delays
- Permissive gating would allow contamination

**Gate Logic**:

```python
def determine_status(completeness: float, hours_since_game: float) -> ReadinessStatus:
    # Perfect data
    if completeness >= 1.0:
        return ReadinessStatus.PROCEED

    # Within grace period (36 hours) - wait for more data
    if hours_since_game < 36 and completeness < 1.0:
        return ReadinessStatus.WAIT

    # Past grace period, acceptable completeness
    if completeness >= 0.8:
        return ReadinessStatus.PROCEED_WITH_WARNING

    # Past grace period, unacceptable completeness
    return ReadinessStatus.FAIL
```

**Configuration**:
- `MIN_COMPLETENESS_THRESHOLD`: 0.8 (80%)
- `GRACE_PERIOD_HOURS`: 36
- `ALLOW_OVERRIDE`: True for manual backfills

---

### Decision 4: Window Completeness Handling

**Options Considered**:

| Option | When Window Incomplete | Pros | Cons |
|--------|------------------------|------|------|
| A | Return NULL, don't compute | Clean data, easy to understand | Missing predictions for new players |
| B | Compute with available data, flag as incomplete | More coverage | Contaminated values exist |
| C | Compute with available data if >70% complete, else NULL | Balance | More complex logic |

**Decision**: **Option C (Threshold-based)**

**Rationale**:
- New players legitimately have <10 games - we still want predictions
- But <70% window completeness means the average is unreliable
- Flagging allows downstream to decide how to handle

**Implementation**:

```python
def compute_rolling_average(player_id, game_date, window_size=10):
    games = get_recent_games(player_id, before=game_date, limit=window_size)
    completeness = len(games) / window_size

    if completeness < 0.7:
        # Too incomplete - return NULL
        return {
            'value': None,
            'complete': False,
            'completeness': completeness,
            'games_used': len(games)
        }
    elif completeness < 1.0:
        # Partially complete - compute but flag
        return {
            'value': mean([g.points for g in games]),
            'complete': False,
            'completeness': completeness,
            'games_used': len(games)
        }
    else:
        # Fully complete
        return {
            'value': mean([g.points for g in games]),
            'complete': True,
            'completeness': 1.0,
            'games_used': len(games)
        }
```

**Threshold Configuration**:
- `WINDOW_COMPLETENESS_THRESHOLD`: 0.7 (70%)
- Below threshold: Return NULL
- Above threshold: Compute but flag as incomplete

---

### Decision 5: Expected Games Source of Truth

**Options Considered**:

| Option | Source | Pros | Cons |
|--------|--------|------|------|
| A | New `game_schedule` reference table | Single source of truth, explicit | Requires new scraper, maintenance |
| B | Odds data (`odds_api_player_props`) | Already exists, reliable | Missing games without odds |
| C | Historical game counts | No new infrastructure | Inaccurate for unusual days |

**Decision**: **Option B initially, migrate to Option A later**

**Rationale**:
- Odds data already tells us which games are scheduled
- Creating a new scraper adds scope and delay
- Can migrate to dedicated schedule table in Phase 2

**Implementation**:

```sql
-- Get expected games for a date (using odds as proxy)
SELECT DISTINCT game_id
FROM nba_raw.odds_api_player_props
WHERE game_date = @game_date
  AND game_id IS NOT NULL;

-- Fallback to bdl_games if no odds
SELECT DISTINCT game_id
FROM nba_raw.bdl_games
WHERE game_date = @game_date;
```

**Future**: Create `nba_reference.game_schedule` table in Week 2-3.

---

### Decision 6: Data Contracts

**Options Considered**:

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A | YAML-based contracts with query assertions | Declarative, version-controlled | Learning curve, new pattern |
| B | Python-based validation functions | Familiar, flexible | Scattered logic, harder to audit |
| C | No formal contracts, rely on processing gates | Simpler | Less explicit, harder to debug |

**Decision**: **Option A (YAML contracts)** for Phase 2

**Rationale**:
- Declarative contracts are self-documenting
- Easy to audit and modify
- Matches industry patterns (dbt, Great Expectations)
- Can start simple and expand

**Contract Structure**:

```yaml
# contracts/phase2_to_phase3.yaml
contract:
  name: raw_to_analytics
  version: "1.0"

  pre_conditions:
    - name: all_games_have_data
      description: "Every game in schedule has player boxscores"
      query: |
        SELECT COUNT(*) as missing
        FROM expected_games e
        LEFT JOIN nba_raw.bdl_player_boxscores b ON e.game_id = b.game_id
        WHERE b.game_id IS NULL AND e.game_date = '{date}'
      assertion: "missing == 0"
      severity: "blocking"

    - name: minimum_players_per_game
      description: "Each game has at least 10 players"
      query: |
        SELECT game_id, COUNT(DISTINCT player_id) as cnt
        FROM nba_raw.bdl_player_boxscores
        WHERE game_date = '{date}'
        GROUP BY game_id
        HAVING cnt < 10
      assertion: "row_count == 0"
      severity: "warning"
```

**Timeline**: Implement in Week 2-3, not Week 1.

---

### Decision 7: Cascade Reprocessing Strategy

**Options Considered**:

| Option | Trigger | Scope | Pros | Cons |
|--------|---------|-------|------|------|
| A | Automatic on late data detection | Full cascade from affected date | Self-healing | Could cause cascading load |
| B | Manual trigger after review | Selected dates only | Controlled | Requires human intervention |
| C | Scheduled nightly reprocessing | All dates with quality issues | Predictable | Delays fixes, wasteful |

**Decision**: **Option A with safeguards**

**Rationale**:
- Self-healing reduces operational burden
- Safeguards prevent runaway cascades
- Can disable for maintenance windows

**Safeguards**:
1. **Rate limiting**: Max 5 cascade reprocesses per hour
2. **Scope limiting**: Max 30 days in single cascade
3. **Circuit breaker**: Disable if >3 failures in 1 hour
4. **Notification**: Alert on every cascade trigger

**Implementation**:

```python
class CascadeTrigger:
    MAX_CASCADES_PER_HOUR = 5
    MAX_DAYS_PER_CASCADE = 30

    def on_late_data_arrival(self, affected_date: date):
        # Check rate limit
        if self.cascades_this_hour >= self.MAX_CASCADES_PER_HOUR:
            logger.warning("Rate limit reached, queuing cascade")
            self.queue_cascade(affected_date)
            return

        # Check scope
        days_to_reprocess = (date.today() - affected_date).days
        if days_to_reprocess > self.MAX_DAYS_PER_CASCADE:
            logger.warning(f"Cascade too large ({days_to_reprocess} days), needs manual review")
            self.alert_for_manual_review(affected_date)
            return

        # Trigger cascade
        self.trigger_reprocess(affected_date)
```

---

### Decision 8: Validation Approach for Existing Contamination

**Options Considered**:

| Option | Method | Cost | Accuracy |
|--------|--------|------|----------|
| A | Full recomputation of all records | High (hours) | 100% |
| B | Tiered: aggregate → sample → spot | Medium | ~95% |
| C | Metadata-only (check timestamps) | Low | ~70% |

**Decision**: **Option B (Tiered)**

**Rationale**:
- Full recomputation is too expensive for initial assessment
- Metadata-only misses records computed with partial data
- Tiered approach balances cost and accuracy

**Tiered Validation**:

```
Tier 1: Aggregate Validation (All Dates)
─────────────────────────────────────────
For each date:
  stored_avg = AVG(composite_score) from stored data
  computed_avg = AVG(recomputed_composite_score) from upstream

  If |stored_avg - computed_avg| / stored_avg > 1%:
    Flag date for Tier 2

Cost: ~100 queries (one per date)
Time: ~2 minutes

Tier 2: Sample Validation (Flagged Dates Only)
──────────────────────────────────────────────
For each flagged date:
  Sample 50 random player records
  Recompute each from upstream
  Compare to stored value

  If >5% of samples differ significantly:
    Mark date as CONTAMINATED

Cost: ~50 queries per flagged date
Time: ~10 minutes total

Tier 3: Spot Check (Random Sample)
──────────────────────────────────
Random 100 records from "clean" dates
Verify no systematic issues missed by Tier 1

Cost: ~100 queries
Time: ~5 minutes
```

---

### Decision 9: Implementation Timeline

**Options Considered**:

| Option | Approach | Risk | Time to Value |
|--------|----------|------|---------------|
| A | Big bang: Build everything, deploy at once | High | 4 weeks |
| B | Incremental: Prevention first, then detection | Low | 1 week for prevention |
| C | Parallel: Multiple teams on different layers | Medium | 2 weeks |

**Decision**: **Option B (Incremental)**

**Rationale**:
- Prevention stops new contamination immediately
- Can validate prevention works before building detection
- Lower risk of deployment issues
- Faster time to value

**Timeline**:

```
Week 1: Prevention (Stop New Contamination)
├── Day 1-2: WindowCompletenessChecker
├── Day 2-3: DependencyChecker + ProcessingGate
├── Day 3-4: Schema migrations for quality columns
└── Day 4-5: Integration with Phase 4 processors

Week 2: Expected Data + Contracts
├── Day 6-7: Game schedule reference (or odds-based)
├── Day 8-9: Data contracts YAML
└── Day 10: Contract validation integration

Week 3: Quantify + Remediate
├── Day 11-12: RecomputeValidator
├── Day 13: Run contamination analysis
├── Day 14-15: Full season reprocessing

Week 4: Monitoring + Documentation
├── Day 16-17: Quality dashboard
├── Day 18-19: Alerting
└── Day 20: Documentation + training
```

---

## Alternatives Not Chosen

### 1. Third-Party Data Quality Tools

**Considered**: Great Expectations, dbt tests, Monte Carlo

**Why Not Chosen (Now)**:
- Adds infrastructure complexity
- Learning curve for team
- Our needs are specific to sports data patterns
- Can adopt later (Weeks 5-8) after core system works

**Future Consideration**: Evaluate after Week 4 if homegrown solution proves insufficient.

### 2. Event-Driven Architecture

**Considered**: Replace scheduled jobs with event-driven processing

**Why Not Chosen**:
- Major architectural change
- Current schedule-based system works well for daily processing
- Prevention layer achieves same goal with less disruption

**Future Consideration**: Consider for next major refactor.

### 3. Full Data Versioning

**Considered**: Keep all versions of every record, never update in place

**Why Not Chosen**:
- Significant storage cost increase
- Query complexity increases
- Not needed if prevention works well

**Future Consideration**: Implement for audit-critical tables only.

### 4. Real-Time Validation

**Considered**: Validate every record as it's written

**Why Not Chosen**:
- Adds latency to processing
- Most issues are systematic, not record-level
- Batch validation catches same issues cheaper

**Future Consideration**: Add for critical paths (predictions) only.

---

## Open Questions

### Resolved

| Question | Decision |
|----------|----------|
| What's the minimum completeness threshold? | 80% for processing, 70% for window calculations |
| How long to wait for late data? | 36 hours grace period |
| Should we use STRUCT types? | No, use simple columns for now |
| Where to get expected games? | Odds data initially, dedicated table later |

### Deferred

| Question | Deferred Until | Notes |
|----------|----------------|-------|
| Should we adopt Great Expectations? | Week 5 | Evaluate after core system works |
| Do we need full data versioning? | Week 8 | Depends on audit requirements |
| Should predictions show confidence to users? | Week 4 | Product decision needed |

### Needs User Input

| Question | Options | Impact |
|----------|---------|--------|
| Alert routing | Slack only vs Slack + PagerDuty | Ops responsiveness |
| Reprocessing approval | Auto vs manual for >7 days | Automation vs control |
| Quality dashboard access | Team only vs public | Transparency |

---

## Success Metrics

### Week 1 (Prevention)

| Metric | Target | Measurement |
|--------|--------|-------------|
| New contaminated records | 0 | Count records with quality_score < 0.7 created after deployment |
| Processing gate blocks | Track | Count of FAIL/WAIT decisions |
| Quality metadata coverage | 100% | % of new records with quality columns populated |

### Week 2-3 (Detection + Remediation)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Contamination rate identified | <10% | % of 2025-26 records flagged as contaminated |
| Reprocessing completion | 100% | All contaminated dates reprocessed |
| Post-reprocess quality | >95% high quality | % of records with quality_score > 0.9 |

### Week 4+ (Ongoing)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Data freshness | <24h | Time from game to processed data |
| Quality score average | >0.95 | Mean quality_score across all tables |
| Cascade reprocesses | <5/week | Count of automatic cascades triggered |
| Manual interventions | <1/week | Count of manual quality fixes needed |

---

## References

### Internal Documents

- Problem discovery: `docs/08-projects/current/data-lineage-integrity/README.md`
- External review request: `docs/08-projects/current/data-lineage-integrity/EXTERNAL-REVIEW-REQUEST.md`
- Validate-lineage skill: `.claude/skills/validate-lineage.md`

### External Review Documents

- Opus review: `docs/08-projects/current/data-lineage-integrity/reviews/opus-review.md`
- Sonnet review: `docs/08-projects/current/data-lineage-integrity/reviews/sonnet-review.md`

### Industry Patterns Referenced

- dbt data tests
- Great Expectations
- Data contracts (PayPal, GoCardless patterns)
- Airflow data-aware scheduling

---

## Appendix: Component Summary

### Components to Build

| Component | Layer | Priority | Source |
|-----------|-------|----------|--------|
| `WindowCompletenessChecker` | Prevention | P0 - Week 1 | Opus |
| `DependencyChecker` | Prevention | P0 - Week 1 | Sonnet |
| `ProcessingGate` | Prevention | P0 - Week 1 | Sonnet |
| `DataQuality` model | Quality Tracking | P0 - Week 1 | Both |
| Quality schema migrations | Quality Tracking | P0 - Week 1 | Both |
| `GameScheduleTable` | Prevention | P1 - Week 2 | Opus |
| `DataContractValidator` | Prevention | P1 - Week 2 | Opus |
| `RecomputeValidator` | Validation | P1 - Week 2 | Sonnet |
| `CascadeTrigger` | Remediation | P2 - Week 3 | Opus |
| `LateDataDetector` | Remediation | P2 - Week 3 | Opus |
| `FreshnessMonitor` | Detection | P2 - Week 3 | Opus |
| Quality Dashboard | Monitoring | P3 - Week 4 | Sonnet |

### Files to Create

```
shared/validation/
├── window_completeness.py      # WindowCompletenessChecker
├── dependency_checker.py       # DependencyChecker
├── processing_gate.py          # ProcessingGate
├── data_contracts.py           # DataContractValidator
└── recompute_validator.py      # RecomputeValidator

shared/models/
└── data_quality.py             # DataQuality, ProcessingContext

shared/monitoring/
├── freshness_monitor.py        # FreshnessMonitor
└── late_data_detector.py       # LateDataDetector

shared/orchestration/
└── cascade_trigger.py          # CascadeTrigger

contracts/
├── phase2_to_phase3.yaml
├── phase3_to_phase4.yaml
└── phase4_to_phase5.yaml

migrations/
├── 001_add_quality_columns_analytics.sql
├── 002_add_quality_columns_precompute.sql
└── 003_add_quality_columns_predictions.sql
```

---

**Document Status**: Complete
**Next Step**: Begin Week 1 implementation with `WindowCompletenessChecker`
