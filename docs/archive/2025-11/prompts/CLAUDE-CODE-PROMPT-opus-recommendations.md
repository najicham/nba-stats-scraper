# Prompt for New Claude Code Session

I need your help reviewing and validating Claude Opus's strategic recommendations for our pub/sub architecture optimization.

## Background

We have a 6-phase event-driven NBA stats pipeline that currently uses **date-level Pub/Sub messages**. This means a single player injury update triggers reprocessing of all 450 players - wasteful but simple.

We sent a comprehensive prompt to Claude Opus asking for **strategic guidance** on:
1. What to build NOW vs LATER (phased approach)
2. How to MEASURE when optimization is needed (metrics, thresholds)
3. How to DESIGN for future evolution (message structure, architecture)

Opus has provided recommendations. I need you to review them with full context of our system.

## Your Task

### Step 1: Understand the Context

Please review these files in order:

**Must read:**
1. `docs/prompts/HANDOFF-pubsub-architecture-recommendations.md` - Full context and background
2. `docs/prompts/pubsub-architecture-analysis-v2.md` - The actual prompt we sent to Opus

**Should skim:**
3. `docs/architecture/06-change-detection-and-event-granularity.md` - Design patterns we shared with Opus
4. `docs/architecture/04-event-driven-pipeline-architecture.md` - 6-phase pipeline overview

**Current implementation (for reference):**
5. `shared/utils/pubsub_publishers.py` - Current Phase 2→3 publishing
6. `data_processors/analytics/analytics_base.py` - Base class with dependency tracking v4.0

### Step 2: Confirm Understanding

After reviewing those files, let me know:
- ✅ You understand our current system state (date-level only, no entity-level support)
- ✅ You understand what we asked Opus (strategic guidance, not code implementation)
- ✅ You understand our philosophy (ship simple, measure, optimize based on data)
- ✅ You're ready to review the Opus recommendations

### Step 3: Review Opus Recommendations

I'll then paste the Opus recommendations for you to:
- Validate against our system architecture
- Identify what to implement in Phase 1 (monitoring infrastructure)
- Design `pipeline_execution_log` schema based on recommendations
- Create actionable implementation checklist
- Flag any concerns or conflicts

## Key Context

**Current state:**
- ✅ Dependency Tracking v4.0 fully implemented (`track_source_usage()`, `check_dependencies()`)
- ✅ Phase 2→3 Pub/Sub connection being implemented now
- ❌ No entity-level support anywhere (no `player_ids` parameters)
- ❌ No change detection (Phase 2 DELETE+INSERT all records)
- ❌ No monitoring infrastructure (`pipeline_execution_log` doesn't exist)

**What we're okay with NOW:**
- Date-level processing (simple, works)
- Overprocessing (not urgent to optimize)
- 30-second processing times (acceptable)

**What we need for FUTURE:**
- Monitoring to know WHEN to optimize
- Architecture that CAN support entity-level (even if we don't use it yet)
- Clear decision criteria (metrics + thresholds)

## Philosophy

We want **strategic planning**, not premature optimization:
- ✅ Ship simple first, measure everything, optimize based on data
- ✅ Design for evolution (no rewrites later)
- ❌ Don't build entity-level until metrics show it's needed

## Success Criteria

You'll help me:
1. Validate Opus recommendations make sense for our system
2. Identify Phase 1 tasks (what to implement NOW)
3. Design monitoring infrastructure (`pipeline_execution_log` schema, metrics)
4. Define metric thresholds for decision-making
5. Create implementation checklist

## Ready?

Please start by reviewing the handoff doc and prompt, then let me know when you're ready to see the Opus recommendations.
