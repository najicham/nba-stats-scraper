# Phase 3 Completion Tracking - Expected Behaviors

**Document Status:** Operational Guide
**Created:** 2026-02-11
**Last Updated:** 2026-02-11
**Related:** Session 208 Investigation

## Overview

Phase 3 completion tracking via Firestore may show "incomplete" status even when the pipeline is working correctly. This document explains why and how to interpret Firestore completion documents.

## Key Concept: Mode-Aware Orchestration

The Phase 3→4 orchestrator uses **mode-aware orchestration** (implemented in Session 128) to adapt processor requirements based on the time of day and data available.

### Three Orchestration Modes

| Mode | Trigger Time | Purpose | Expected Processors |
|------|--------------|---------|---------------------|
| **overnight** | 6-8 AM ET | Process yesterday's completed games | 5 processors (all) |
| **same_day** | 10:30 AM ET | Process today's upcoming games | 1-2 processors |
| **tomorrow** | 5:00 PM ET | Process tomorrow's upcoming games | 1-2 processors |

### Mode-Specific Requirements

#### Overnight Mode (Post-Game Processing)
**Expected:** 5 processors
**Critical (must have):**
- `player_game_summary` - Historical game data
- `upcoming_player_game_context` - Tomorrow's predictions

**Optional (nice to have):**
- `team_defense_game_summary`
- `team_offense_game_summary`
- `upcoming_team_game_context`

**Trigger Logic:**
- Ideal: All 5 complete → trigger
- Graceful: Critical + 60% optional (3/5 total) → trigger

#### Same-Day Mode (Pre-Game Processing)
**Expected:** 1 processor minimum
**Critical (must have):**
- `upcoming_player_game_context` - Today's game predictions

**Optional (nice to have):**
- `upcoming_team_game_context`

**Not Expected:**
- Historical game processors (no games have been played yet)

**Trigger Logic:**
- If `total_complete >= 1` → trigger with "all_complete"

#### Tomorrow Mode (Next-Day Processing)
**Expected:** 1-2 processors
**Critical (must have):**
- `upcoming_player_game_context`

**Optional:**
- `upcoming_team_game_context`

**Trigger Logic:**
- Same as same_day mode

## Why Firestore May Show "Incomplete"

### Reason 1: Mode-Aware Triggering

**Example from 2026-02-11:**
```
Firestore Document (phase3_completion/2026-02-11):
  Processors: 3/5 complete
  Mode: same_day
  Triggered: True
  Trigger Reason: all_complete
```

**Why this is correct:**
- Same-day mode only requires 1 processor (`upcoming_player_game_context`)
- 3 processors completed (more than minimum)
- Orchestrator correctly triggered Phase 4

**Validation:**
- ✅ Check `_triggered = True`
- ✅ Check `_trigger_reason = "all_complete"` or `"critical_plus_majority_60pct"`
- ❌ Don't count raw processor numbers without checking mode

### Reason 2: Backfill Mode Processors

Processors run in **backfill mode** intentionally skip Firestore updates to avoid duplicate triggers.

**Log Pattern:**
```
INFO:analytics_base:⏸️  Skipping downstream trigger (backfill mode) -
Phase 4 will not be auto-triggered for {processor_name}
```

**When This Happens:**
- Manual backfill jobs
- Scheduled historical data corrections
- Testing/debugging runs with `skip_downstream_trigger=True`

**What to Expect:**
- BigQuery tables have data ✅
- Firestore does NOT have completion record ✅ (by design)
- Pipeline continues normally ✅

**Example:** 2026-02-11 investigation found `upcoming_team_game_context` ran in backfill mode at 2:05 PM PT, creating 28 records but not updating Firestore.

### Reason 3: Late Processors (Post-Trigger)

Processors may complete **after** the orchestrator already triggered Phase 4.

**Timeline Example:**
```
11:25 AM PT: Phase 3→4 triggered (3 processors complete)
 2:05 PM PT: upcoming_team_game_context runs (backfill)
 3:00 PM PT: evening analytics runs (same-day mode)
```

**Firestore Shows:**
- Snapshot at trigger time (3 processors)
- Does NOT update for late arrivals

**This is Correct Behavior:**
- Phase 4 already ran with sufficient data
- Late processors are supplementary (often backfills)

## How to Validate Phase 3 Completion

### ❌ WRONG Approach
```python
# DON'T DO THIS - Ignores mode context
processors_complete = len([k for k in data.keys() if not k.startswith('_')])
if processors_complete < 5:
    print("⚠️ WARNING: Only {}/5 processors complete")
```

### ✅ CORRECT Approach
```python
# Check trigger status AND reason
triggered = data.get('_triggered', False)
trigger_reason = data.get('_trigger_reason', 'N/A')
mode = data.get('_mode', 'unknown')
completed_count = len([k for k in data.keys() if not k.startswith('_')])

if triggered:
    print(f"✅ Phase 4 triggered successfully")
    print(f"   Mode: {mode}")
    print(f"   Reason: {trigger_reason}")
    print(f"   Processors: {completed_count}")
else:
    # Now check if it SHOULD have triggered
    if mode == 'same_day' and completed_count >= 1:
        print("⚠️ Should have triggered but didn't")
    elif mode == 'overnight' and completed_count >= 3:
        print("⚠️ Should have triggered but didn't")
```

### Validation Decision Tree

```
Is _triggered = True?
├─ YES → Check _trigger_reason
│         ├─ "all_complete" → ✅ OK (ideal case)
│         ├─ "critical_plus_majority_60pct" → ✅ OK (graceful degradation)
│         └─ Other/None → ⚠️ Investigate trigger logic
└─ NO → Check if SHOULD trigger
          ├─ Mode = same_day + count >= 1 → 🔴 BUG (should have triggered)
          ├─ Mode = overnight + count >= 3 → 🔴 BUG (should have triggered)
          └─ Otherwise → ⏳ Waiting for processors (OK)
```

## Common Scenarios

### Scenario A: Same-Day Mode with 3/5 Processors
```
Firestore: 3/5 complete, mode=same_day, triggered=True
Status: ✅ EXPECTED
Reason: Only needs 1 processor, got 3
Action: None
```

### Scenario B: Overnight Mode with 3/5 Processors
```
Firestore: 3/5 complete, mode=overnight, triggered=True, reason=critical_plus_majority_60pct
Status: ✅ EXPECTED (graceful degradation)
Reason: Critical processors + 60% threshold met
Action: Monitor, verify critical processors present
```

### Scenario C: Backfill Processor Missing
```
BigQuery: upcoming_team_game_context has 28 rows
Firestore: upcoming_team_game_context NOT listed
Logs: "Skipping downstream trigger (backfill mode)"
Status: ✅ EXPECTED
Reason: Backfill mode intentionally skips Firestore
Action: None
```

### Scenario D: Trigger Failed
```
Firestore: 3/5 complete, mode=overnight, triggered=False
Status: 🔴 CRITICAL
Reason: Should have triggered with 60% threshold
Action: Manually trigger Phase 4, investigate orchestrator
```

## Firestore Document Structure

### Complete Example
```json
{
  // Processor completion fields (non-metadata)
  "player_game_summary": {
    "status": "complete",
    "timestamp": "2026-02-11T18:20:15Z"
  },
  "upcoming_player_game_context": {
    "status": "complete",
    "timestamp": "2026-02-11T18:22:30Z"
  },
  "team_defense_game_summary": {
    "status": "complete",
    "timestamp": "2026-02-11T18:21:05Z"
  },

  // Metadata fields (start with _)
  "_completed_count": 3,
  "_mode": "same_day",
  "_trigger_reason": "all_complete",
  "_triggered": true,
  "_triggered_at": "2026-02-11T18:25:46Z",
  "_last_update": "2026-02-11T18:25:49Z"
}
```

### Key Metadata Fields

| Field | Type | Purpose |
|-------|------|---------|
| `_triggered` | boolean | Has Phase 4 been triggered? |
| `_trigger_reason` | string | Why did it trigger? |
| `_mode` | string | Orchestration mode (overnight/same_day/tomorrow) |
| `_completed_count` | int | Number of processors complete |
| `_triggered_at` | timestamp | When Phase 4 was triggered |
| `_last_update` | timestamp | Last Firestore update |

## Troubleshooting

### Investigation Checklist

When you see "incomplete" Firestore completion:

1. **Check trigger status** - Is `_triggered = True`?
2. **Check mode** - What mode was detected?
3. **Check reason** - Why did it trigger (or not)?
4. **Verify critical processors** - Are mode-specific critical processors present?
5. **Check BigQuery** - Do tables have data even if Firestore doesn't?
6. **Check logs** - Look for "backfill mode" or "skip downstream trigger"

### Manual Trigger Commands

If orchestrator didn't trigger when it should have:

```bash
# Phase 3→4
gcloud scheduler jobs run phase3-to-phase4 --location=us-west2

# Phase 4→5
gcloud scheduler jobs run phase4-to-phase5 --location=us-west2

# Phase 5→6
gcloud scheduler jobs run phase5-to-phase6 --location=us-west2
```

## Reference

**Code Locations:**
- Orchestrator: `/orchestration/cloud_functions/phase3_to_phase4/main.py`
- Mode detection: `detect_orchestration_mode()` function (line 125)
- Trigger logic: `should_trigger_phase4()` function (line 207)
- Mode expectations: `get_mode_expectations()` function (line 165)

**Key Commits:**
- Session 128: Mode-aware orchestration implementation
- Session 205: phase2-to-phase3 orchestrator removal
- Session 208: Firestore tracking investigation

**Related Documentation:**
- `docs/02-operations/runbooks/phase3-orchestration.md` - Operational procedures
- `docs/09-handoff/2026-02-11-SESSION-208-HANDOFF.md` - Investigation findings
- Session 128 handoff - Mode-aware orchestration design

## Summary

**Key Takeaway:** Firestore completion documents show a **trigger-time snapshot**, not final state. Incomplete documents are normal and expected with mode-aware orchestration and backfill processors.

**Validation Rule:** Always check `_triggered` and `_trigger_reason` fields, not just raw processor counts.

**When to Worry:** Only worry if `_triggered = False` when it should be `True` based on mode and completion.
