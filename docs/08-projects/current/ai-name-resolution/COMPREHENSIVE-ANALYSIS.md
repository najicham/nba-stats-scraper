# AI-Assisted Player Name Resolution: Comprehensive System Analysis

**Created:** 2025-12-05
**Status:** Deep Analysis Complete - Ready for Implementation Planning

---

## Executive Summary

After a comprehensive analysis of the player name resolution system using parallel investigation agents, we've identified that:

1. **The current system is 90% complete** - excellent architecture for manual workflows
2. **Critical gap: No automated reprocessing** after names are resolved
3. **Critical gap: No impact tracking** linking unresolved names to affected records
4. **Schema gaps: 4 new tables needed** for full AI integration
5. **Architectural gaps: 5 issues identified** in the code flow

**Estimated Impact:**
- 719 pending unresolved names (603 unique)
- 94% from basketball_reference source
- Unknown number of skipped records (not tracked)
- Manual resolution taking significant human time

---

## Part 1: Current Data Flow Analysis

### Complete Pipeline

```
PHASE 1: SCRAPERS (7+ sources)
    ↓ NBA.com, ESPN, Basketball-Reference, BDL, etc.
    ↓ Raw names: "LeBron James", "K.J. Martin Jr."

PHASE 2: NORMALIZATION
    ↓ normalize_name_for_lookup()
    ↓ "LeBron James" → "lebronjames"

REFERENCE PROCESSORS (Registry Building)
    ↓ 1. Roster Registry Processor (runs first)
    ↓ 2. Gamebook Registry Processor (runs second)
    ↓ Creates nba_players_registry entries

PHASE 3: ANALYTICS PROCESSORS
    ↓ Uses RegistryReader (read-only, cached)
    ↓ get_universal_ids_batch(players)
    ↓ If not found → logged to unresolved_player_names
    ↓ Record SKIPPED (data lost!)

PHASE 4: PRECOMPUTE
    ↓ Uses analytics output
    ↓ Also affected by missing players

PHASE 5: PREDICTIONS
    ↓ Uses precompute output
```

### Critical Finding: Data Loss on Failure

When a player name fails to resolve in analytics processors:

```python
# player_game_summary_processor.py:810-814
universal_player_id = uid_map.get(player_lookup)
if universal_player_id is None:
    self.registry_stats['records_skipped'] += 1
    return None  # ← DATA LOST!
```

**Impact:** The entire player's game record is skipped, not just flagged. This means:
- Player stats not written to analytics tables
- Downstream precompute/predictions affected
- No way to automatically recover after resolution

---

## Part 2: Architectural Gaps Identified

### GAP #1: Race Condition in Universal ID Creation (HIGH RISK)

**Location:** `resolver.py:260-277`

```python
# Thread A: checks existing IDs, finds none
# Thread B: checks existing IDs, finds none (same!)
# Thread A: creates player_001
# Thread B: creates player_001 ← COLLISION!
```

**Impact:** Duplicate universal IDs in registry, analytics joins fail

**Fix Needed:** Distributed lock or BigQuery MERGE with uniqueness constraint

---

### GAP #2: No Retry Mechanism After Resolution (MEDIUM RISK)

**Current State:**
1. Player fails to resolve → record skipped
2. Name manually resolved (alias created)
3. **No trigger** to reprocess affected dates
4. Same player may accumulate more unresolved entries

**Fix Needed:** Post-resolution hook to trigger reprocessing

---

### GAP #3: No Game ID Context Tracking (MEDIUM RISK)

**Current State:**
```python
# Batch lookup - no context passed!
uid_map = self.registry.get_universal_ids_batch(unique_players)
# Context is None, so example_games array is empty
```

**Impact:** Can't identify which specific games need reprocessing

**Fix Needed:** Pass game context during batch lookups

---

### GAP #4: Temporal Ordering Not Enforced (MEDIUM RISK)

**Problem:**
- Registry built from Season 2023-24
- Analytics processing 2024-25 data
- Player traded mid-season → stale team assignment

**Fix Needed:** Validate registry freshness matches data being processed

---

### GAP #5: No Impact Tracking (HIGH RISK)

**Current State:**
- `unresolved_player_names` tracks names pending review
- **No link** to which records were skipped
- **No way to know** which dates need reprocessing

**Fix Needed:** New `unresolved_name_impacts` table

---

## Part 3: Backfill System Analysis

### Current Capabilities (What Works)

| Capability | Status | Notes |
|------------|--------|-------|
| Checkpoint-based resume | ✅ Implemented | Can resume after failure |
| Schedule-aware (skip off-days) | ✅ Implemented | 30% reduction in processing |
| Smart idempotency (hash-based) | ✅ Implemented | Only writes if data changed |
| Change detection (incremental) | ✅ Implemented | Process only changed entities |
| Force reprocess flag | ✅ Implemented | Manual trigger only |
| Processor run history | ✅ Implemented | Comprehensive tracking |

### Missing Capabilities (Critical Gaps)

| Capability | Status | Impact |
|------------|--------|--------|
| Track records skipped due to unresolved names | ❌ Missing | Can't identify reprocessing scope |
| Auto-reprocess after name resolution | ❌ Missing | Manual intervention required |
| Link unresolved names to affected records | ❌ Missing | Can't measure business impact |
| Skip reason "unresolved_names" | ❌ Missing | Can't filter/query these failures |
| Reprocessing queue | ❌ Missing | No automated workflow |

### What Happens After Name Resolution (Current)

1. User resolves name via CLI
2. Creates alias in `player_aliases`
3. Marks `unresolved_player_names` as 'resolved'
4. **Nothing else happens**
5. Historical data remains incomplete
6. No automated reprocessing

---

## Part 4: Schema Analysis

### Existing Tables Assessment

| Table | Current State | AI Readiness |
|-------|--------------|--------------|
| `nba_players_registry` | Strong baseline | Missing AI origin tracking |
| `unresolved_player_names` | Good for manual workflow | Missing AI suggestion fields, impact tracking |
| `player_aliases` | Minimal but functional | Missing AI origin, quality tracking |
| `unresolved_resolution_log` | Very minimal | Needs complete redesign |
| `processor_run_history` | Excellent | Missing AI integration fields |

### New Tables Required

#### 1. `ai_resolution_log` (CRITICAL)

Central audit table for all AI decisions.

```sql
CREATE TABLE ai_resolution_log (
    decision_id STRING NOT NULL,
    decision_timestamp TIMESTAMP,

    -- Input
    unresolved_lookup STRING,
    original_name STRING,
    team_abbr STRING,
    season STRING,

    -- AI Analysis
    model_name STRING,
    prompt_hash STRING,
    confidence FLOAT64,
    decision_type STRING,  -- create_alias, create_registry, invalid, unknown
    target_lookup STRING,
    reasoning STRING,

    -- Execution
    input_tokens INT64,
    output_tokens INT64,
    cost_usd FLOAT64,

    -- Outcome
    decision_applied BOOLEAN,
    human_reviewed BOOLEAN,
    review_outcome STRING,

    -- Reprocessing
    reprocess_triggered BOOLEAN,
    affected_records_count INT64
);
```

#### 2. `unresolved_name_impacts` (CRITICAL)

Links unresolved names to affected records.

```sql
CREATE TABLE unresolved_name_impacts (
    impact_id STRING NOT NULL,
    unresolved_lookup STRING NOT NULL,

    -- Affected Record
    affected_table STRING,
    affected_game_id STRING,
    affected_game_date DATE,

    -- Impact
    impact_type STRING,  -- record_skipped, incomplete_data
    impact_severity STRING,

    -- Recovery
    resolved BOOLEAN,
    reprocessed BOOLEAN,
    recovered_at TIMESTAMP
);
```

#### 3. `name_resolution_reprocess_queue` (HIGH)

Coordinates automated reprocessing.

```sql
CREATE TABLE name_resolution_reprocess_queue (
    queue_id STRING,
    resolution_id STRING,

    affected_table STRING,
    game_dates ARRAY<DATE>,

    status STRING,  -- pending, running, completed, failed
    priority INT64,

    records_recovered INT64
);
```

#### 4. `ai_resolution_metrics` (MEDIUM)

Daily aggregated metrics for monitoring.

```sql
CREATE TABLE ai_resolution_metrics (
    metric_date DATE,
    total_decisions INT64,
    avg_confidence FLOAT64,
    approval_rate FLOAT64,
    total_cost_usd FLOAT64,
    records_recovered INT64
);
```

### Field Additions to Existing Tables

**`unresolved_player_names` - Add:**
```sql
ai_decision_id STRING,
ai_suggestion_status STRING,
ai_confidence_score FLOAT64,
affected_records_count INT64,
affected_tables ARRAY<STRING>,
has_been_reprocessed BOOLEAN,
reprocess_status STRING
```

**`player_aliases` - Add:**
```sql
ai_resolution_id STRING,
creation_method STRING,  -- manual, ai_auto, ai_assisted
ai_confidence_at_creation FLOAT64,
is_verified BOOLEAN
```

---

## Part 5: Proposed Solution Architecture

### Complete AI Resolution Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. DETECTION                                                 │
│    unresolved_player_names: status='pending'                │
│    Calculate affected_records_count                          │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│ 2. IMPACT ANALYSIS                                           │
│    Populate unresolved_name_impacts                          │
│    Link to affected records in analytics tables              │
│    Calculate business impact score                           │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│ 3. AI ANALYSIS (Claude API)                                  │
│    Build context: registry matches, roster, aliases          │
│    Request decision + confidence                             │
│    Store in ai_resolution_log                                │
└────────────────────────┬────────────────────────────────────┘
                         │
           ┌─────────────┴─────────────┐
           │                           │
    Confidence ≥ 0.95            Confidence < 0.95
           │                           │
┌──────────▼───────────┐    ┌─────────▼────────────────┐
│ 4a. AUTO-APPLY       │    │ 4b. HUMAN REVIEW         │
│ Create alias         │    │ Queue with AI suggestion │
│ Mark resolved        │    │ Show confidence + reason │
│ Trigger reprocess    │    │ Wait for approval        │
└──────────┬───────────┘    └─────────┬────────────────┘
           │                          │
           └──────────┬───────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│ 5. REPROCESSING                                              │
│    Queue affected dates to name_resolution_reprocess_queue   │
│    Trigger processor runs for affected tables                │
│    Track recovered records                                   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│ 6. VALIDATION                                                │
│    Update ai_resolution_metrics                              │
│    Monitor accuracy, cost, recovery rates                    │
│    Alert on anomalies                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Part 6: Implementation Roadmap

### Phase 1: Foundation (Week 1)

**Schema Changes:**
- [ ] Create `ai_resolution_log` table
- [ ] Add AI fields to `unresolved_player_names`
- [ ] Add AI fields to `player_aliases`
- [ ] Restructure `unresolved_resolution_log`

**Code Changes:**
- [ ] Create `shared/utils/player_registry/ai_resolver.py`
- [ ] Add Anthropic SDK to requirements
- [ ] Set up API key in Secret Manager

### Phase 2: Impact Tracking (Week 2)

**Schema Changes:**
- [ ] Create `unresolved_name_impacts` table
- [ ] Add impact fields to `unresolved_player_names`

**Code Changes:**
- [ ] Modify `RegistryReader` to pass game context
- [ ] Create impact population logic
- [ ] Add "unresolved_names" to skip_reason enum

### Phase 3: AI Integration (Week 3)

**Code Changes:**
- [ ] Implement Claude API integration
- [ ] Build context gathering (registry, roster, aliases)
- [ ] Implement batch processing script
- [ ] Add confidence-based routing

### Phase 4: Automation (Week 4)

**Schema Changes:**
- [ ] Create `name_resolution_reprocess_queue` table
- [ ] Add reprocess tracking fields

**Code Changes:**
- [ ] Implement post-resolution hook
- [ ] Create reprocessing trigger logic
- [ ] Integrate with orchestration system

### Phase 5: Monitoring (Week 5)

**Schema Changes:**
- [ ] Create `ai_resolution_metrics` table

**Code Changes:**
- [ ] Build daily aggregation logic
- [ ] Create Grafana dashboard
- [ ] Set up alerts

---

## Part 7: Questions for Future Investigation

### Questions to Research Later

1. **Race Condition Fix:** Should we use BigQuery MERGE or distributed lock (Redis)?

2. **Real-time vs Batch:** For daily operations, is 100-500ms latency per API call acceptable?

3. **Confidence Tuning:** After initial deployment, how should we adjust thresholds based on accuracy data?

4. **Cost Optimization:** Should we use Haiku for low-impact names and Sonnet for high-impact?

5. **Historical Backfill:** Should we AI-resolve all 600 pending names at once, or process by season?

### Tasks for Future Sessions

- [ ] Research best practice for BigQuery atomic operations
- [ ] Study how processors handle partial failures
- [ ] Investigate Pub/Sub integration for reprocessing triggers
- [ ] Design Grafana dashboard for AI resolution metrics

---

## Part 8: Cost & ROI Analysis

### Current Cost (Manual)

- ~600 unique pending names
- Estimated 2-5 minutes per name manual review
- 20-50 hours of human time for backlog

### AI Resolution Cost

| Scenario | Volume | API Cost | Time Saved |
|----------|--------|----------|------------|
| Clear backlog | 600 names | ~$6-10 | 20-50 hours |
| Per-season backfill | 50-100 names | ~$0.50-1.00 | 2-5 hours |
| Daily operations | 1-5 names | <$0.01/day | 10-30 min/day |

### ROI

- Break-even: First batch run
- Ongoing: 10-30 minutes saved per day
- Quality: Faster data availability, fewer manual errors

---

## Appendix A: Key File Locations

### Registry System
- `shared/utils/player_registry/reader.py` - Read-only access
- `shared/utils/player_registry/resolver.py` - Universal ID resolution
- `tools/player_registry/resolve_unresolved_names.py` - CLI tool

### Schemas
- `schemas/bigquery/nba_reference/nba_players_registry_table.sql`
- `schemas/bigquery/nba_reference/unresolved_player_names_table.sql`
- `schemas/bigquery/nba_reference/player_aliases_table.sql`
- `schemas/bigquery/processing/processing_tables.sql`

### Processors
- `data_processors/reference/player_reference/roster_registry_processor.py`
- `data_processors/reference/player_reference/gamebook_registry_processor.py`
- `data_processors/analytics/player_game_summary/player_game_summary_processor.py`

---

## Appendix B: Session Log

| Date | Session | Notes |
|------|---------|-------|
| 2025-12-05 | Initial | Created project doc, basic analysis |
| 2025-12-05 | Deep Analysis | 3 parallel agents: code flow, backfill, schemas. Comprehensive gaps identified. |
