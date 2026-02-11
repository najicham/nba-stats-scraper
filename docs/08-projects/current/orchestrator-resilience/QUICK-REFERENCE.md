# Orchestrator Resilience - Quick Reference

**Session 199** | **Date:** 2026-02-11 | **Status:** Awaiting Opus Review

## The Problem (1 sentence)

Phase 2→3 orchestrator failure went undetected for 3 days because all processors completed but `_triggered=True` was never set in Firestore, and no alerts fired.

## The Solution (1 sentence)

Multi-layer detection system (logging + 30-min canary + 15-min dedicated monitor) catches stuck orchestrators in 15 minutes instead of 3 days, with optional auto-healing.

## Impact

| Metric | Before | After |
|--------|--------|-------|
| **Detection time** | 72 hours | 15 minutes |
| **Improvement** | - | **96x faster** |
| **Manual intervention** | Required | Optional (auto-heal) |

## 3 Layers of Defense

### Layer 1: Enhanced Logging (20 min effort)
**What:** Add checkpoints, dual-write to BigQuery, timeout warnings
**Benefit:** Enables post-mortem diagnosis + real-time monitoring
**Files:** `orchestration/cloud_functions/phase2_to_phase3/main.py`

### Layer 2: Pipeline Canary (30 min effort)
**What:** Add orchestrator trigger check to existing 30-min canaries
**Benefit:** Leverages existing alert infrastructure
**Files:** `bin/monitoring/pipeline_canary_queries.py`

### Layer 3: Dedicated Monitor (45 min effort)
**What:** New script runs every 15 min, checks Firestore, can auto-heal
**Benefit:** Fastest detection + optional auto-recovery
**Files:** `bin/monitoring/orchestrator_health_monitor.py`

## Total Effort

- **Implementation:** 95 minutes
- **Testing:** 60 minutes
- **Total:** ~2.5 hours

## Key Questions for Opus

1. **Auto-heal default:** Disabled or enabled? (Recommend: disabled initially)
2. **Alert threshold:** >= 5 or >= 6 processors? (Recommend: >= 5)
3. **Monitor frequency:** 15 min or 30 min? (Recommend: 15 min)
4. **Scope:** Just Phase 2→3 or all orchestrators? (Recommend: start with 2→3)

## Rollback Plan

All changes are non-blocking and can be disabled via:
- Revert Cloud Function deployment
- Pause Cloud Scheduler jobs
- Disable auto-heal env var

## Success Criteria (30 days)

- ✅ Zero orchestrator failures go undetected >30 minutes
- ✅ MTTD < 30 minutes
- ✅ MTTR < 2 hours

## Full Documentation

See `00-PROJECT-PLAN.md` for complete implementation details.
