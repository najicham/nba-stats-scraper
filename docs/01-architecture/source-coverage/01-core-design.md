# NBA Props Platform - Source Coverage System Design
## Part 1: Core Design & Architecture

**Created:** 2025-11-26
**Status:** Production Design - Consolidated
**Version:** 2.0 (Merged from collaborative design sessions)

**Related Documents:**
- [Part 2: Schema Reference](02-schema-reference.md)
- [Part 3: Implementation Guide](03-implementation-guide.md)
- [Part 4: Testing & Operations](04-testing-operations.md)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Design Philosophy](#design-philosophy)
3. [Terminology](#terminology)
4. [System Architecture](#system-architecture)
5. [Core Components](#core-components)
6. [Quality Tier System](#quality-tier-system)
7. [Decision Frameworks](#decision-frameworks)
8. [Implementation Roadmap](#implementation-roadmap)
9. [Cost Analysis](#cost-analysis)
10. [Key Design Decisions](#key-design-decisions)

---

## Executive Summary

### The Problem

The NBA Props Platform depends on data from 7+ external sources (NBA.com, ESPN, Ball Don't Lie, Odds API, etc.) flowing through a 5-phase pipeline. External sources have gaps for various reasons:

- **API failures:** NBA.com timeout, rate limits
- **Source data unavailable:** Play-In Tournament games missing from API
- **Partial coverage:** 8/10 players have data, 2 missing
- **New scenarios:** Rookie with no history, mid-season trade
- **Stale data:** Injury report 24 hours old

Without systematic tracking, these gaps either:
1. **Silently degrade prediction quality**, or
2. **Cause hard failures that block predictions**

### The Solution

A **two-layer source coverage system** that:

```
Layer 1: Event Log
  Single table tracking every source gap, fallback, reconstruction

Layer 2: Quality Propagation
  Standard quality columns on every Phase 3+ table
    Quality flows Phase 2 -> 3 -> 4 -> 5 -> Predictions
```

**Plus:** Daily audit job to catch silent failures (games never processed)

### Core Principles

| Principle | Implementation |
|-----------|----------------|
| **"Show must go on"** | Predictions run if prop lines exist; quality flags indicate confidence |
| **Event-driven, not state-driven** | Log what happened; derive current state via queries/views |
| **Visibility first** | Every gap visible; no silent failures |
| **Graceful degradation** | Bronze predictions > no predictions |
| **Reconstruction is valid** | Derived data acceptable but flagged |
| **Integrate, don't isolate** | Build into existing processors via mixins |

### What You Get

- **Visibility:** Query shows source coverage for any game/player
- **Automation:** Fallback and reconstruction handled automatically
- **Quality propagation:** Tier flows through entire pipeline
- **Alerting:** Critical gaps -> immediate Slack; others -> daily digest
- **Audit trail:** Complete history of every source event
- **Silent failure detection:** Daily job catches missed games
- **Production-ready:** Fully specified, cost-analyzed, tested patterns

**Cost:** ~$5-7/month additional (~9-13% increase from $55/month baseline)

---

## Design Philosophy

### Guiding Principles

**1. Start Simple, Evolve Deliberately**
> "Make the change easy, then make the easy change." - Kent Beck

- Begin with 80% solution that's 20% of complexity
- Add features when proven necessary via operational experience
- Prefer battle-tested patterns over novel architecture

**2. Actionable > Comprehensive**
- Every metric must drive a decision
- If you wouldn't alert on it or act on it, don't track it
- Quality data that sits unused is wasted effort
- "What are you going to do with this number?"

**3. Integrate, Don't Isolate**
- Build into existing processor patterns (mixins)
- Use existing notification infrastructure (Slack, Email)
- Extend current tables rather than parallel systems
- Follow established conventions

**4. Production-First Mindset**
- Design for 3 AM debugging scenarios
- Clear operational runbooks
- Graceful degradation always
- What happens when NBA.com is down for 2 days?

**5. Cost-Conscious**
- Every query optimized for BigQuery pricing
- Minimal storage overhead
- Batch operations over real-time when possible
- Detailed cost analysis before committing

### Design Trade-offs Made

| Trade-off | Choice | Rationale |
|-----------|--------|-----------|
| **State vs Events** | Events | Simpler, no state synchronization issues |
| **Tables vs Views** | Log table + views | Views avoid materialization overhead |
| **Centralized vs Distributed** | Hybrid | Log for audit trail, columns for performance |
| **Comprehensive vs Essential** | Essential | Start with must-haves, add rest later |
| **Real-time vs Batch** | Batch (with audit) | Cheaper, sufficient for use case |

---

## Terminology

### What "Source Coverage" Means

**Source Coverage** specifically tracks: *"Did external data sources provide the data we need?"*

**This system focuses on:**
- NBA.com API returning game data (or not)
- Odds API providing prop lines (or not)
- ESPN having backup boxscores (or not)
- Using fallback sources when primary fails
- Reconstructing data when all sources miss

**This system does NOT track:**
- Whether our scrapers worked (that's infrastructure monitoring)
- Whether our processors succeeded (that's processing validation)
- Whether downstream tables are ready (that's dependency readiness)
- Whether data is correct (that's data validation)

### The Three-System Model

The platform has three related but distinct systems ensuring data quality:

```
+-------------------------------------------------------------+
|                    DATA QUALITY ECOSYSTEM                    |
+-------------------------------------------------------------+
|                                                              |
|  +------------------+  +------------------+  +-------------+ |
|  | SOURCE COVERAGE  |  |   DEPENDENCY     |  |  PROCESSING | |
|  |   (this doc)     |  |   READINESS      |  |  VALIDATION | |
|  |                  |  |   (existing)     |  |  (existing) | |
|  |                  |  |                  |  |             | |
|  | "Did NBA.com     |  | "Is Phase 2      |  | "Did Phase 3| |
|  |  have data?"     |  |  ready for       |  |  processor  | |
|  |                  |  |  Phase 3?"       |  |  succeed?"  | |
|  +--------+---------+  +--------+---------+  +------+------+ |
|           |                     |                   |        |
|           +---------------------+-------------------+        |
|                              |                               |
|                    +---------v----------+                    |
|                    |  UNIFIED QUALITY   |                    |
|                    |  (tier + score)    |                    |
|                    +--------------------+                    |
+--------------------------------------------------------------+
```

| System | Question | When | Example Issue | Remediation |
|--------|----------|------|---------------|-------------|
| **Source Coverage** | Did external sources have data? | After scraping | NBA.com API returned empty | Use ESPN fallback |
| **Dependency Readiness** | Is upstream data ready? | Before processor | Phase 2 table empty | Wait or skip |
| **Processing Validation** | Did our code work? | After processor | Processor crashed | Debug, rerun |

---

## System Architecture

### High-Level Overview

```
+----------------------------------------------------------------+
|                        EXTERNAL SOURCES                         |
|  NBA.com | ESPN | Ball Don't Lie | Odds API | BettingPros |... |
+----------------------------+-----------------------------------+
                             |
                             v
         +------------------------------------+
         |    Phase 1: Scrapers (33 total)    |
         |    -> GCS JSON files               |
         +----------------+-------------------+
                          |
                          v
         +------------------------------------+
         |    Phase 2: Raw Processing         |
         |    -> nba_raw.* tables (21)        |
         |    [Processors log source status]  |
         +----------------+-------------------+
                          |
                          v
         +------------------------------------+
         |    Phase 3: Analytics              |
         |    -> nba_analytics.* (5 tables)   |
         |    [Add quality columns]           |
         +----------------+-------------------+
                          |
                          v
         +------------------------------------+
         |    Phase 4: Precompute/Features    |
         |    -> nba_precompute.* (6 tables)  |
         |    [Propagate quality]             |
         +----------------+-------------------+
                          |
                          v
         +------------------------------------+
         |    Phase 5: Predictions            |
         |    -> nba_predictions.*            |
         |    [Cap confidence by quality]     |
         +------------------------------------+

    +--------------------------------------------+
    |         SOURCE COVERAGE SYSTEM              |
    +--------------------------------------------+
    |                                             |
    |  Layer 1: Event Logging                    |
    |  +--------------------------------------+  |
    |  | source_coverage_log                  |  |
    |  | - Every gap, fallback, reconstruction|  |
    |  +--------------------------------------+  |
    |                                             |
    |  Layer 2: Quality Propagation              |
    |  +--------------------------------------+  |
    |  | Standard columns on Phase 3+ tables: |  |
    |  | - quality_tier                       |  |
    |  | - quality_score                      |  |
    |  | - quality_issues                     |  |
    |  | - data_sources                       |  |
    |  +--------------------------------------+  |
    |                                             |
    |  Layer 3: Silent Failure Detection         |
    |  +--------------------------------------+  |
    |  | Daily Audit Job                      |  |
    |  | - Compares schedule vs actual data   |  |
    |  | - Creates synthetic events for gaps  |  |
    |  +--------------------------------------+  |
    +--------------------------------------------+
```

### Data Flow Example: Handling Missing Source

```
Game X scheduled for 2024-12-15

1. Scraper runs (Phase 1)
   -> NBA.com API: timeout after 30s

2. Phase 2 processor (with FallbackSourceMixin)
   -> Try nbac_team_boxscore: FAIL
   -> Try espn_team_boxscore: SUCCESS
   -> Log event: {
       event_type: 'fallback_used',
       severity: 'info',
       primary_source: 'nbac_team_boxscore',
       resolution: 'used_fallback'
     }
   -> Load data with quality_tier='silver'

3. Phase 3 processor
   -> Reads data with quality_tier='silver'
   -> Processes normally
   -> Inherits quality_tier='silver' (or degrades further)

4. Phase 4 processor
   -> Aggregates 10 games: 9 gold, 1 silver
   -> Result quality_tier='silver' (worst of inputs)

5. Phase 5 predictions
   -> Feature quality_tier='silver'
   -> Confidence capped at 95% (silver ceiling)
   -> Prediction generated with reduced confidence

6. Daily audit (next day, 9 AM)
   -> Checks: Game X in schedule? YES
   -> Checks: Game X in coverage log? YES (fallback event)
   -> Checks: Game X in data tables? YES
   -> Status: NORMAL (no synthetic event needed)
```

### Where Source Coverage Lives

**Not a separate service** - integrated into existing processors via mixins:

```python
class PlayerGameSummaryProcessor(
    FallbackSourceMixin,    # Handles source fallback automatically
    QualityMixin,           # Calculates quality scores
    BaseProcessor           # Your existing base class
):
    """
    Phase 3 processor with integrated source coverage.
    No separate audit processor needed during normal flow.
    """
```

**Audit processor** runs separately once daily to catch edge cases.

---

## Core Components

### Component 1: Source Coverage Log (Event Store)

**Purpose:** Single source of truth for all source coverage events

**What it stores:**
- Every source gap detected
- Every fallback usage
- Every reconstruction attempt
- Every quality degradation

**What it's NOT:**
- Not for real-time quality lookups (too slow to query)
- Not for per-prediction quality (use table columns)
- Not a replacement for monitoring (use existing tools)

**When to query:**
- Daily quality reports
- Investigating specific game issues
- Trend analysis over time
- Alert generation

**Storage:** ~$0.002/month (negligible)

### Component 2: Quality Columns (Fast Lookups)

**Purpose:** Fast quality information on every data row

**Standard schema on every Phase 3+ table:**
```sql
quality_tier STRING           -- 'gold', 'silver', 'bronze', 'poor', 'unusable'
quality_score FLOAT64         -- 0-100 numeric score
quality_issues ARRAY<STRING>  -- ['missing_shot_zones', 'thin_sample']
data_sources ARRAY<STRING>    -- ['espn_backup', 'reconstructed']
quality_metadata JSON         -- Flexible additional context
```

**Why columns, not JOINs:**
- Fast filtering: `WHERE quality_tier = 'gold'`
- Quality-aware aggregations: `AVG(points * quality_score/100)`
- No JOIN overhead in queries
- Quality always travels with data

**Trade-off:**
- Storage overhead: ~5-10% increase
- Redundancy: Quality info in log AND columns
- Worth it for query performance

### Component 3: Processor Mixins (Reusable Logic)

**Purpose:** Consistent quality handling across all processors

**QualityMixin:**
- Calculates quality scores from data completeness
- Assigns quality tiers
- Logs events to coverage log
- Standard interface for all processors

**FallbackSourceMixin:**
- Tries sources in priority order
- Handles reconstruction attempts
- Logs fallback usage
- Returns data + sources used

**Why mixins:**
- DRY (Don't Repeat Yourself)
- Consistent behavior
- Easy to test in isolation
- Optional adoption (add to processors gradually)

### Component 4: Coverage Audit Job (Silent Failure Detection)

**Purpose:** Catch games that were never processed at all

**Problem it solves:**
```
Event log only knows what processors tell it.
If processor never runs -> No events logged -> Silent gap

Audit job compares:
  Schedule (what SHOULD exist)
  vs
  Coverage log + Data tables (what DOES exist)
```

**Runs:** Daily at 9 AM PT (after scrapers + processors complete)

**Cost:** ~$0.01/month (minimal)

### Component 5: Game Coverage Summary View

**Purpose:** Convenient game-level queries without maintaining state

**Why a view, not a table:**
- Always up-to-date (no refresh jobs)
- No storage cost
- Simple to modify (just DROP/CREATE)
- Derives from event log (single source of truth)

### Component 6: Alert Coordinator

**Purpose:** Smart alerting that reduces noise

**Two alert types:**

**1. Critical (Immediate)**
- Sent to: Slack channel + Email
- When: Predictions blocked or severe degradation

**2. Informational (Daily Digest)**
- Sent to: Email only
- When: Quality degraded but predictions continue

---

## Quality Tier System

### Tier Definitions

| Tier | Score Range | Criteria | Prediction Use | Confidence Cap |
|------|-------------|----------|----------------|----------------|
| **gold** | 95-100 | Primary sources only, complete data, cross-validated | Full confidence | 100% |
| **silver** | 75-94 | Backup source used OR minor reconstruction OR 1-2 games missing from window | Slight penalty | 95% |
| **bronze** | 50-74 | Heavy reconstruction OR thin sample (<5 games) OR multiple gaps | Moderate penalty | 80% |
| **poor** | 25-49 | Critical gaps, minimal data, multiple issues combined | Strong warning | 60% |
| **unusable** | 0-24 | Cannot generate meaningful prediction | Skip prediction | N/A |

### Tier Inheritance (Phase to Phase)

**Key principle:** Quality can only stay same or degrade, never improve

```
Phase 3 Input Quality -> Phase 4 Output Quality

10 Gold games -> Gold rolling average
9 Gold + 1 Silver -> Silver rolling average
8 Gold + 2 Bronze -> Bronze rolling average
Any Poor input -> Poor output
Any Unusable input -> Skip processing
```

---

## Decision Frameworks

### When to Stop vs Continue

| Condition | Action | Rationale |
|-----------|--------|-----------|
| **Prop line missing** | SKIP prediction | Nothing to predict against |
| **All historical data missing** | INCOMPLETE tier, predict with league avg | Some prediction > no prediction |
| **Primary source missing, backup available** | CONTINUE at Silver | Backup is valid data |
| **Team context missing** | CONTINUE at Bronze | Use league averages |
| **Player never seen** | INCOMPLETE tier | Flag as new player |
| **Registry lookup fails** | STOP, ALERT | Can't proceed without ID |

### Source Priority Order

**Team Boxscore:**
1. NBA.com (`nbac_team_boxscore`) - Official source -> Gold
2. ESPN (`espn_game_boxscore`) - Reliable backup -> Silver
3. Ball Don't Lie (`bdl_box_scores`) - API backup -> Silver
4. Reconstructed from player totals - Last resort -> Silver

**Player Boxscore:**
1. NBA.com Gamebook (`nbac_gamebook_player_stats`) - Official PDF -> Gold
2. Ball Don't Lie (`bdl_player_boxscores`) - Reliable API -> Silver
3. ESPN (`espn_game_boxscore`) - Backup -> Silver

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)

**Goal:** Can you see source coverage issues?

**Deliverables:**
- `source_coverage_log` table created
- Quality columns added to 1-2 critical tables
- Basic `QualityMixin` implemented and tested
- 10+ test games processed successfully

**Success Criteria:**
- Coverage log receiving events
- At least 1 processor writing quality columns

**Cost:** +$1-2/month

### Phase 2: Fallback & Propagation (Week 2)

**Goal:** Quality flows through pipeline; fallbacks work automatically

**Deliverables:**
- `FallbackSourceMixin` implemented
- Fallback working in player_game_summary
- Quality columns added to Phase 4 tables
- Quality propagation working Phase 3 -> 4

**Cost:** +$2-3/month

### Phase 3: Alerts & Monitoring (Week 3)

**Goal:** Automated notifications for critical issues

**Deliverables:**
- Alert logic implemented
- Slack notifications working
- Daily digest email generated
- Dashboard queries documented

**Cost:** +$1/month

### Phase 4: Audit & Historical (Week 4)

**Goal:** Silent failure detection; historical data quality

**Deliverables:**
- Coverage audit job implemented
- Game summary view created
- Historical backfill complete

**Cost:** +$1-2/month + $5 one-time backfill

---

## Cost Analysis

**Total Monthly Cost: ~$3-4/month actual**

**Conservative estimate: $5-7/month** (includes safety margin for playoff volume spikes)

Use conservative estimate for budgeting.

---

## Key Design Decisions

### Decision 1: Event Log vs State Table

**Chose:** Event log (what happened)
**Rejected:** State table (what is)

**Rationale:**
- Event log is simpler (no state synchronization)
- Event log provides audit trail automatically
- State can be derived via queries/views when needed

### Decision 2: Quality Columns vs JOINs

**Chose:** Quality columns on every Phase 3+ table
**Rejected:** JOIN to quality table for every query

**Rationale:**
- Query performance critical for predictions
- Storage is cheap (~5% increase)

### Decision 3: Mixins vs Inheritance Hierarchy

**Chose:** Mixin pattern
**Rejected:** Deep inheritance tree

**Rationale:**
- Mixins are composable
- Easier to test in isolation
- Gradual adoption

### Decision 4: Audit Job vs Real-Time Detection

**Chose:** Daily batch audit job
**Rejected:** Real-time detection after each processor

**Rationale:**
- Cheaper (batch vs continuous queries)
- Sufficient for use case

### Decision 5: View vs Materialized Table

**Chose:** View for game summary
**Rejected:** Materialized table with refresh job

**Rationale:**
- View always up-to-date
- No storage cost
- Simpler

---

## Summary

### What This Design Provides

- **Complete visibility** into external source availability
- **Automated handling** of gaps via fallback and reconstruction
- **Quality propagation** through entire pipeline to predictions
- **Smart alerting** (critical immediate, info batched)
- **Silent failure detection** via daily audit
- **Production-ready** patterns with testing and operations
- **Cost-effective** (~$5-7/month for comprehensive system)

### What This Design Does NOT Do

- **Replace infrastructure monitoring** (use existing tools)
- **Prevent all source gaps** (external APIs will still fail)
- **Guarantee data correctness** (coverage != validation)
- **Auto-fix everything** (some gaps need manual intervention)

---

## Next Steps

1. **Review this design document** - Approve architecture and decisions
2. **Reference detailed schemas** - See [Part 2: Schema Reference](02-schema-reference.md)
3. **Review implementation code** - See [Part 3: Implementation Guide](03-implementation-guide.md)
4. **Plan testing strategy** - See [Part 4: Testing & Operations](04-testing-operations.md)
5. **Begin Week 1 implementation** - Start with foundation (schema + basic mixin)

---

*End of Part 1: Core Design & Architecture*
