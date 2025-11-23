# HANDOFF: Week 1 → Weeks 2-6 Completeness Checking Rollout

**Date:** 2025-11-22
**From:** Week 1 Session (team_defense_zone_analysis complete)
**To:** Next Session (rollout to remaining 6 processors)
**Status:** Ready to Continue

---

## What Was Completed (Week 1) ✅

### Infrastructure Created

1. **CompletenessChecker Service** ✅
   - File: `/shared/utils/completeness_checker.py`
   - 389 lines, fully tested (22 unit tests passing)
   - Batch checking (2 queries for all entities, not N queries)
   - Supports 'games' and 'days' window types

2. **Circuit Breaker Tracking Table** ✅
   - Schema: `/schemas/bigquery/orchestration/reprocess_attempts.sql`
   - Deployed to BigQuery: `nba_orchestration.reprocess_attempts`
   - Partitioned by analysis_date, clustered by processor/entity
   - 365-day retention

3. **Schema Updates** ✅
   - Updated: `/schemas/bigquery/precompute/team_defense_zone_analysis.sql`
   - Deployed 14 completeness columns to BigQuery
   - Total fields: 34 → 48

4. **First Processor Integration** ✅
   - File: `/data_processors/precompute/team_defense_zone_analysis/team_defense_zone_analysis_processor.py`
   - Added completeness checking (lines 537-635, 665-743)
   - Circuit breaker integration
   - 14 metadata fields in output (lines 813-840)

5. **Unit Tests** ✅
   - File: `/tests/unit/utils/test_completeness_checker.py`
   - 22 tests, all passing
   - Coverage: bootstrap, season boundary, backfill progress, completeness calc

### Documentation Created

1. `/docs/implementation/WEEK1_COMPLETE.md` - Comprehensive Week 1 summary
2. `/docs/implementation/11-phase3-phase4-completeness-implementation-plan.md` - Full implementation plan (107 new columns total)
3. `/docs/implementation/12-NEXT-STEPS-completeness-checking.md` - Quick start guide
4. `/docs/architecture/historical-dependency-checking-plan.md` - Opus AI plan (full design)

---

## What's Next (Weeks 2-6)

### Remaining Processors to Update

**Phase 4 Precompute (4 more):**
1. ✅ `team_defense_zone_analysis` - COMPLETE
2. ⏳ `player_shot_zone_analysis` - NEXT (Week 2)
3. ⏳ `player_daily_cache` - Week 3 (multi-window complexity)
4. ⏳ `player_composite_factors` - Week 4 (cascade dependencies)
5. ⏳ `ml_feature_store` - Week 4 (cascade dependencies)

**Phase 3 Analytics (2 more):**
6. ⏳ `upcoming_player_game_context` - Week 5 (date-based windows)
7. ⏳ `upcoming_team_game_context` - Week 6 (date-based windows)

**Total:** 6 processors remaining

---

## Before You Start: Read These Docs

### Essential Reading (15 min)

1. **Week 1 Summary** (5 min)
   - `/docs/implementation/WEEK1_COMPLETE.md`
   - Shows what was done, how it works, output examples

2. **Full Implementation Plan** (5 min)
   - `/docs/implementation/11-phase3-phase4-completeness-implementation-plan.md`
   - All 7 processors in scope, schema changes, timeline

3. **Opus Design Document** (5 min - skim)
   - `/docs/architecture/historical-dependency-checking-plan.md`
   - Circuit breaker, multi-window logic, monitoring

### Reference Docs

4. **Completeness Strategy** (optional)
   - `/docs/implementation/08-data-completeness-checking-strategy.md`
   - Why we chose schedule-based approach

5. **Phase Applicability** (optional)
   - `/docs/implementation/10-phase-applicability-assessment-CORRECTED.md`
   - Which processors need completeness checking

---

## Key Files You'll Work With

### Core Service (Already Complete)
- `/shared/utils/completeness_checker.py` - DON'T modify, it's done

### Schemas to Update (6 remaining)

**Phase 4:**
```
/schemas/bigquery/precompute/player_shot_zone_analysis.sql
/schemas/bigquery/precompute/player_daily_cache.sql
/schemas/bigquery/precompute/player_composite_factors.sql
/schemas/bigquery/precompute/ml_feature_store.sql
```

**Phase 3:**
```
/schemas/bigquery/analytics/upcoming_player_game_context_tables.sql
/schemas/bigquery/analytics/upcoming_team_game_context_tables.sql
```

### Processors to Update (6 remaining)

**Phase 4:**
```
/data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py
/data_processors/precompute/player_daily_cache/player_daily_cache_processor.py
/data_processors/precompute/player_composite_factors/player_composite_factors_processor.py
/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
```

**Phase 3:**
```
/data_processors/analytics/upcoming_player_game_context/upcoming_player_game_context_processor.py
/data_processors/analytics/upcoming_team_game_context/upcoming_team_game_context_processor.py
```

---

## Step-by-Step Rollout Process

### For Each Processor (Repeat 6 Times)

#### Step 1: Update Schema (10 min)

**Add 14 columns to the table definition:**

```sql
-- In CREATE TABLE section (after existing fields)

-- ============================================================================
-- HISTORICAL COMPLETENESS CHECKING (14 fields)
-- ============================================================================

-- Completeness Metrics (4 fields)
expected_games_count INT64,
actual_games_count INT64,
completeness_percentage FLOAT64,
missing_games_count INT64,

-- Production Readiness (2 fields)
is_production_ready BOOLEAN,
data_quality_issues ARRAY<STRING>,

-- Circuit Breaker (4 fields)
last_reprocess_attempt_at TIMESTAMP,
reprocess_attempt_count INT64,
circuit_breaker_active BOOLEAN,
circuit_breaker_until TIMESTAMP,

-- Bootstrap/Override (4 fields)
manual_override_required BOOLEAN,
season_boundary_detected BOOLEAN,
backfill_bootstrap_mode BOOLEAN,
processing_decision_reason STRING,
```

**Add to ALTER TABLE section:**

```sql
-- In ALTER TABLE section

-- Historical completeness checking (14 fields)
ADD COLUMN IF NOT EXISTS expected_games_count INT64
  OPTIONS (description="Games expected from schedule"),
ADD COLUMN IF NOT EXISTS actual_games_count INT64
  OPTIONS (description="Games actually found in upstream table"),
ADD COLUMN IF NOT EXISTS completeness_percentage FLOAT64
  OPTIONS (description="Completeness percentage 0-100%"),
ADD COLUMN IF NOT EXISTS missing_games_count INT64
  OPTIONS (description="Number of games missing from upstream"),
ADD COLUMN IF NOT EXISTS is_production_ready BOOLEAN
  OPTIONS (description="TRUE if completeness >= 90%"),
ADD COLUMN IF NOT EXISTS data_quality_issues ARRAY<STRING>
  OPTIONS (description="Specific quality issues found"),
ADD COLUMN IF NOT EXISTS last_reprocess_attempt_at TIMESTAMP
  OPTIONS (description="When reprocessing was last attempted"),
ADD COLUMN IF NOT EXISTS reprocess_attempt_count INT64
  OPTIONS (description="Number of reprocess attempts"),
ADD COLUMN IF NOT EXISTS circuit_breaker_active BOOLEAN
  OPTIONS (description="TRUE if max reprocess attempts reached"),
ADD COLUMN IF NOT EXISTS circuit_breaker_until TIMESTAMP
  OPTIONS (description="When circuit breaker expires (7 days from last attempt)"),
ADD COLUMN IF NOT EXISTS manual_override_required BOOLEAN
  OPTIONS (description="TRUE if manual intervention needed"),
ADD COLUMN IF NOT EXISTS season_boundary_detected BOOLEAN
  OPTIONS (description="TRUE if date near season start/end"),
ADD COLUMN IF NOT EXISTS backfill_bootstrap_mode BOOLEAN
  OPTIONS (description="TRUE if first 30 days of season/backfill"),
ADD COLUMN IF NOT EXISTS processing_decision_reason STRING
  OPTIONS (description="Why record was processed or skipped");
```

**Update field summary:**
```sql
-- Update the field count in comments
-- Total fields: [OLD] → [OLD + 14]
```

#### Step 2: Deploy Schema to BigQuery (1 min)

```bash
bq query --use_legacy_sql=false --project_id=nba-props-platform "
ALTER TABLE \`nba-props-platform.nba_precompute.[TABLE_NAME]\`

ADD COLUMN IF NOT EXISTS expected_games_count INT64
  OPTIONS (description='Games expected from schedule'),
-- ... (all 14 columns)
"
```

**Verify:**
```bash
bq show --schema nba-props-platform:nba_precompute.[TABLE_NAME] | grep completeness_percentage
```

#### Step 3: Update Processor Code (20 min)

**3A. Add Import (top of file):**

```python
# Completeness checking (Week 1 - Phase 4 Historical Dependency Checking)
from shared.utils.completeness_checker import CompletenessChecker
```

**3B. Initialize in `__init__()` (after bq_client):**

```python
# Initialize completeness checker (Week 1 - Phase 4 Completeness Checking)
self.completeness_checker = CompletenessChecker(self.bq_client, self.project_id)
```

**3C. Add Circuit Breaker Methods (before calculate_precompute):**

```python
# ============================================================
# Completeness Checking Methods (Week 1 - Phase 4)
# ============================================================

def _check_circuit_breaker(self, entity_id: str, analysis_date: date) -> dict:
    """Check if circuit breaker is active for entity."""
    query = f"""
    SELECT
        attempt_number,
        attempted_at,
        circuit_breaker_tripped,
        circuit_breaker_until
    FROM `{self.project_id}.nba_orchestration.reprocess_attempts`
    WHERE processor_name = '{self.table_name}'
      AND entity_id = '{entity_id}'
      AND analysis_date = DATE('{analysis_date}')
    ORDER BY attempt_number DESC
    LIMIT 1
    """

    try:
        result = list(self.bq_client.query(query).result())

        if not result:
            return {'active': False, 'attempts': 0, 'until': None}

        row = result[0]

        if row.circuit_breaker_tripped:
            # Check if 7 days have passed
            if row.circuit_breaker_until and datetime.now(UTC) < row.circuit_breaker_until:
                return {
                    'active': True,
                    'attempts': row.attempt_number,
                    'until': row.circuit_breaker_until
                }

        return {
            'active': False,
            'attempts': row.attempt_number,
            'until': None
        }

    except Exception as e:
        logger.warning(f"Error checking circuit breaker for {entity_id}: {e}")
        return {'active': False, 'attempts': 0, 'until': None}

def _increment_reprocess_count(self, entity_id: str, analysis_date: date, completeness_pct: float, skip_reason: str) -> None:
    """Track reprocessing attempt and trip circuit breaker if needed."""
    circuit_status = self._check_circuit_breaker(entity_id, analysis_date)
    next_attempt = circuit_status['attempts'] + 1

    # Trip circuit breaker on 3rd attempt
    circuit_breaker_tripped = next_attempt >= 3
    circuit_breaker_until = None

    if circuit_breaker_tripped:
        circuit_breaker_until = datetime.now(UTC) + timedelta(days=7)
        logger.error(
            f"{entity_id}: Circuit breaker TRIPPED after {next_attempt} attempts. "
            f"Manual intervention required. Next retry allowed: {circuit_breaker_until}"
        )

    # Record attempt
    insert_query = f"""
    INSERT INTO `{self.project_id}.nba_orchestration.reprocess_attempts`
    (processor_name, entity_id, analysis_date, attempt_number, attempted_at,
     completeness_pct, skip_reason, circuit_breaker_tripped, circuit_breaker_until,
     manual_override_applied, notes)
    VALUES (
        '{self.table_name}',
        '{entity_id}',
        DATE('{analysis_date}'),
        {next_attempt},
        CURRENT_TIMESTAMP(),
        {completeness_pct},
        '{skip_reason}',
        {circuit_breaker_tripped},
        {'TIMESTAMP("' + circuit_breaker_until.isoformat() + '")' if circuit_breaker_until else 'NULL'},
        FALSE,
        'Attempt {next_attempt}: {completeness_pct:.1f}% complete'
    )
    """

    try:
        self.bq_client.query(insert_query).result()
        logger.debug(f"{entity_id}: Recorded reprocess attempt {next_attempt}")
    except Exception as e:
        logger.warning(f"Failed to record reprocess attempt for {entity_id}: {e}")
```

**3D. Modify `calculate_precompute()` - Add Batch Completeness Check:**

**After getting entity list, before loop:**

```python
# Get all entities
all_entities = [...]  # However processor gets entities
analysis_date = self.opts['analysis_date']

# ============================================================
# NEW (Week 1): Batch completeness checking
# ============================================================
logger.info(f"Checking completeness for {len(all_entities)} entities...")

completeness_results = self.completeness_checker.check_completeness_batch(
    entity_ids=list(all_entities),
    entity_type='team',  # or 'player' for player processors
    analysis_date=analysis_date,
    upstream_table='nba_analytics.[UPSTREAM_TABLE]',  # e.g., 'player_game_summary'
    upstream_entity_field='[ENTITY_FIELD]',  # e.g., 'player_lookup'
    lookback_window=self.min_games_required,  # e.g., 10, 15
    window_type='games',  # or 'days' for Phase 3
    season_start_date=self.season_start_date
)

# Check bootstrap mode
is_bootstrap = self.completeness_checker.is_bootstrap_mode(
    analysis_date, self.season_start_date
)
is_season_boundary = self.completeness_checker.is_season_boundary(analysis_date)

logger.info(
    f"Completeness check complete. Bootstrap mode: {is_bootstrap}, "
    f"Season boundary: {is_season_boundary}"
)
# ============================================================
```

**3E. Inside Entity Loop - Add Checks:**

**At start of loop, before processing:**

```python
for entity_id in all_entities:
    try:
        # ============================================================
        # NEW (Week 1): Get completeness for this entity
        # ============================================================
        completeness = completeness_results.get(entity_id, {
            'expected_count': 0,
            'actual_count': 0,
            'completeness_pct': 0.0,
            'missing_count': 0,
            'is_complete': False,
            'is_production_ready': False
        })

        # Check circuit breaker
        circuit_breaker_status = self._check_circuit_breaker(entity_id, analysis_date)

        if circuit_breaker_status['active']:
            logger.warning(
                f"{entity_id}: Circuit breaker active until "
                f"{circuit_breaker_status['until']} - skipping"
            )
            failed.append({
                'entity_id': entity_id,
                'reason': f"Circuit breaker active until {circuit_breaker_status['until']}",
                'category': 'CIRCUIT_BREAKER_ACTIVE',
                'can_retry': False
            })
            continue

        # Check production readiness (skip if incomplete, unless in bootstrap mode)
        if not completeness['is_production_ready'] and not is_bootstrap:
            logger.warning(
                f"{entity_id}: Completeness {completeness['completeness_pct']}% "
                f"({completeness['actual_count']}/{completeness['expected_count']} games) "
                f"- below 90% threshold, skipping"
            )

            # Track reprocessing attempt
            self._increment_reprocess_count(
                entity_id, analysis_date,
                completeness['completeness_pct'],
                'incomplete_upstream_data'
            )

            failed.append({
                'entity_id': entity_id,
                'reason': (
                    f"Incomplete data: {completeness['completeness_pct']}% "
                    f"({completeness['actual_count']}/{completeness['expected_count']} games)"
                ),
                'category': 'INCOMPLETE_DATA',
                'can_retry': True
            })
            continue
        # ============================================================

        # Continue with normal processing...
```

**3F. In Output Record - Add Metadata:**

**After source tracking, before processed_at:**

```python
# Source tracking (v4.0 - one line via base class method!)
**self.build_source_tracking_fields(),

# ============================================================
# NEW (Week 1): Completeness Checking Metadata (14 fields)
# ============================================================
# Completeness Metrics
'expected_games_count': completeness['expected_count'],
'actual_games_count': completeness['actual_count'],
'completeness_percentage': completeness['completeness_pct'],
'missing_games_count': completeness['missing_count'],

# Production Readiness
'is_production_ready': completeness['is_production_ready'],
'data_quality_issues': [],  # Populate if specific issues found

# Circuit Breaker
'last_reprocess_attempt_at': None,  # Would need separate query
'reprocess_attempt_count': circuit_breaker_status['attempts'],
'circuit_breaker_active': circuit_breaker_status['active'],
'circuit_breaker_until': (
    circuit_breaker_status['until'].isoformat()
    if circuit_breaker_status['until'] else None
),

# Bootstrap/Override
'manual_override_required': False,
'season_boundary_detected': is_season_boundary,
'backfill_bootstrap_mode': is_bootstrap,
'processing_decision_reason': 'processed_successfully',
# ============================================================

# Processing metadata
'processed_at': datetime.now(UTC).isoformat()
```

#### Step 4: Test (5 min)

**Run unit tests:**
```bash
pytest tests/unit/utils/test_completeness_checker.py -v
```

**Integration test** (when data available):
```bash
python -m data_processors.precompute.[PROCESSOR_NAME] \
  --analysis_date 2024-11-15
```

**Verify schema deployment:**
```bash
bq query --use_legacy_sql=false "
SELECT completeness_percentage, is_production_ready, backfill_bootstrap_mode
FROM \`nba-props-platform.nba_precompute.[TABLE_NAME]\`
WHERE analysis_date = '2024-11-15'
LIMIT 3
"
```

---

## Processor-Specific Notes

### player_shot_zone_analysis (Week 2 - Next)

**Differences from team_defense_zone_analysis:**
- Entity type: `'player'` (not 'team')
- Upstream table: `'nba_analytics.player_game_summary'`
- Entity field: `'player_lookup'`
- Lookback window: 10 games (not 15)
- Has L10 and L20 windows (but completeness check uses min_games_required = 10)

**Key Changes:**
```python
completeness_results = self.completeness_checker.check_completeness_batch(
    entity_ids=list(all_players),
    entity_type='player',  # CHANGED
    analysis_date=analysis_date,
    upstream_table='nba_analytics.player_game_summary',  # CHANGED
    upstream_entity_field='player_lookup',  # CHANGED
    lookback_window=10,  # CHANGED (min_games_required)
    window_type='games',
    season_start_date=self.season_start_date
)
```

---

### player_daily_cache (Week 3 - Multi-Window)

**Special Case**: This processor has **multiple windows** (L5, L7d, L10, L14d)

**According to Opus plan**: ALL windows must be 90% complete for production-ready

**Additional Schema Columns** (9 more):
```sql
-- Multi-Window Completeness (9 additional fields)
l5_completeness_pct FLOAT64,
l5_is_complete BOOLEAN,
l10_completeness_pct FLOAT64,
l10_is_complete BOOLEAN,
l7d_completeness_pct FLOAT64,
l7d_is_complete BOOLEAN,
l14d_completeness_pct FLOAT64,
l14d_is_complete BOOLEAN,
all_windows_complete BOOLEAN
```

**Completeness Checking (4 separate checks):**
```python
# Check each window separately
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
            entity_ids=list(all_players),
            entity_type='player',
            analysis_date=analysis_date,
            upstream_table='nba_analytics.player_game_summary',
            upstream_entity_field='player_lookup',
            lookback_window=lookback,
            window_type=window_type,
            season_start_date=self.season_start_date
        )

# Check ALL windows (conservative approach)
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
```

---

### player_composite_factors & ml_feature_store (Week 4 - Cascade)

**Special Case**: These depend on OTHER Phase 4 processors

**According to Opus plan**: Track upstream completeness, don't cascade-fail

**Example for player_composite_factors:**
```python
# Get opponent defense data
opponent_defense = get_opponent_defense(team_abbr, analysis_date)

if opponent_defense is None:
    factors['matchup_difficulty'] = None
    factors['upstream_complete'] = False
elif opponent_defense['is_production_ready']:
    factors['matchup_difficulty'] = calculate_matchup(...)
    factors['upstream_complete'] = True
else:
    # Calculate with low-quality upstream, but flag it
    factors['matchup_difficulty'] = calculate_matchup(...)
    factors['upstream_complete'] = False

# Our production readiness depends on BOTH
factors['is_production_ready'] = (
    player_complete and
    factors.get('upstream_complete', False)
)
```

---

### upcoming_player_game_context & upcoming_team_game_context (Weeks 5-6 - Phase 3)

**Key Differences from Phase 4:**
- Window type: `'days'` (not 'games')
- Date-based lookback (L7 days, L14 days, L30 days)
- Multiple windows (like player_daily_cache)

**Example for upcoming_player_game_context:**
```python
# Has multiple windows: L5 games, L7 days, L10 games, L14 days, L30 days
windows = [
    ('l5_games', 5, 'games'),
    ('l10_games', 10, 'games'),
    ('l7_days', 7, 'days'),
    ('l14_days', 14, 'days'),
    ('l30_days', 30, 'days')
]

# Check each window
completeness_by_window = {}
for window_name, lookback, window_type in windows:
    completeness_by_window[window_name] = \
        self.completeness_checker.check_completeness_batch(
            entity_ids=list(all_players),
            entity_type='player',
            analysis_date=analysis_date,
            upstream_table='nba_analytics.player_game_summary',
            upstream_entity_field='player_lookup',
            lookback_window=lookback,
            window_type=window_type,  # 'days' or 'games'
            season_start_date=self.season_start_date
        )
```

**Note**: Phase 3 processors are in `/data_processors/analytics/` (not `/precompute/`)

---

## Common Patterns Reference

### Pattern 1: Standard Single-Window Processor
Used by: team_defense_zone_analysis, player_shot_zone_analysis

1. Batch completeness check (1 window)
2. Check circuit breaker per entity
3. Check production readiness
4. Process or skip
5. Write 14 metadata fields

### Pattern 2: Multi-Window Processor
Used by: player_daily_cache, upcoming_player_game_context, upcoming_team_game_context

1. Batch completeness check (N windows)
2. Check ALL windows complete (conservative)
3. Write 14 + 9*N metadata fields

### Pattern 3: Cascade Dependencies
Used by: player_composite_factors, ml_feature_store

1. Check own completeness
2. Check upstream completeness
3. Calculate anyway, but flag upstream quality
4. Production readiness = own AND upstream

---

## Testing Checklist Per Processor

### After Each Integration

- [ ] Unit tests pass (service tests)
- [ ] Schema deployed successfully
- [ ] Processor runs without errors
- [ ] Output includes all 14 completeness fields
- [ ] Circuit breaker table has entries (if any skips)

### SQL Validation Queries

```sql
-- Check completeness metadata populated
SELECT
  [ENTITY_FIELD],
  analysis_date,
  completeness_percentage,
  is_production_ready,
  expected_games_count,
  actual_games_count,
  missing_games_count,
  backfill_bootstrap_mode,
  circuit_breaker_active,
  processing_decision_reason
FROM `nba-props-platform.[DATASET].[TABLE_NAME]`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
ORDER BY analysis_date DESC, [ENTITY_FIELD]
LIMIT 10;

-- Check circuit breaker attempts
SELECT *
FROM `nba-props-platform.nba_orchestration.reprocess_attempts`
WHERE processor_name = '[TABLE_NAME]'
ORDER BY attempted_at DESC
LIMIT 10;

-- Check completeness distribution
SELECT
  analysis_date,
  AVG(completeness_percentage) as avg_completeness,
  MIN(completeness_percentage) as min_completeness,
  MAX(completeness_percentage) as max_completeness,
  COUNTIF(is_production_ready) as production_ready_count,
  COUNT(*) as total_entities
FROM `nba-props-platform.[DATASET].[TABLE_NAME]`
WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
GROUP BY analysis_date
ORDER BY analysis_date DESC;
```

---

## Timeline Estimate

**Per Processor** (with experience):
- Schema update: 10 min
- Deploy schema: 1 min
- Processor code: 20 min
- Testing: 5 min
- **Total: ~35-40 min per processor**

**6 Remaining Processors**:
- Week 2: player_shot_zone_analysis (40 min)
- Week 3: player_daily_cache (60 min - multi-window complexity)
- Week 4: player_composite_factors (50 min - cascade)
- Week 4: ml_feature_store (50 min - cascade)
- Week 5: upcoming_player_game_context (60 min - multi-window + Phase 3)
- Week 6: upcoming_team_game_context (50 min - Phase 3)

**Total: 5-6 hours of focused work** (or 1-2 hours per day for a week)

---

## Success Criteria (When All Complete)

- [ ] All 7 processors have completeness checking
- [ ] All 7 schemas deployed with 14+ columns
- [ ] Unit tests passing (22/22)
- [ ] No errors during processing
- [ ] Completeness metadata visible in BigQuery
- [ ] Circuit breaker tracking working
- [ ] Documentation updated

---

## Quick Start for Next Session

**Immediate next steps**:

1. Read Week 1 summary: `/docs/implementation/WEEK1_COMPLETE.md`

2. Start with player_shot_zone_analysis:
   ```bash
   # 1. Update schema
   vim schemas/bigquery/precompute/player_shot_zone_analysis.sql

   # 2. Deploy schema
   bq query --use_legacy_sql=false < [schema file with ALTER TABLE]

   # 3. Update processor
   vim data_processors/precompute/player_shot_zone_analysis/player_shot_zone_analysis_processor.py

   # 4. Test
   pytest tests/unit/utils/test_completeness_checker.py -v
   ```

3. Use team_defense_zone_analysis as reference:
   - Schema: Compare before/after in git diff
   - Processor: Look at lines 537-635 (circuit breaker methods) and 665-743 (completeness checking)

4. Copy patterns, adjust for entity type and upstream table

5. Repeat for remaining 5 processors

---

## Questions? Issues?

**If stuck on**:
- **Multi-window logic** → See player_daily_cache notes above
- **Cascade dependencies** → See player_composite_factors notes above
- **Phase 3 differences** → Window type = 'days' (not 'games')
- **Circuit breaker not working** → Check table_name matches processor name exactly

**Key insight**: The CompletenessChecker service is already complete and tested. You're just:
1. Adding schema columns (copy-paste)
2. Calling the service (copy-paste pattern)
3. Writing metadata to output (copy-paste)

**Pattern established**: team_defense_zone_analysis is your template. Reference it liberally!

---

## Good Luck! 🚀

You have everything you need:
- ✅ Service ready
- ✅ Pattern proven
- ✅ Tests passing
- ✅ Documentation complete

Just apply the pattern 6 more times and you're done!

**Estimated completion**: 5-6 hours of focused work across Weeks 2-6.
