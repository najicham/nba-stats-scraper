# Phase 2 Completion Deadline Deployment

## Purpose
Enable Phase 2 completion deadline to prevent indefinite waits when processors fail.

## Problem Solved
- **Jan 20 Issue**: Only 2/6 Phase 2 processors ran, orchestrator waited indefinitely
- **Root Cause**: No timeout mechanism for processor completion
- **Impact**: Phase 3 never triggered, causing 24+ hour data gap

## Solution
Implement completion deadline that triggers Phase 3 after 30 minutes, even if some processors haven't completed.

## Configuration Changes

### Environment Variables (Phase 2→3 Orchestrator)

Add to `orchestration/cloud_functions/phase2_to_phase3`:

```bash
ENABLE_PHASE2_COMPLETION_DEADLINE=true
PHASE2_COMPLETION_TIMEOUT_MINUTES=30
```

### Deployment Steps

#### 1. Update Cloud Function Environment Variables

```bash
# Set environment variables
gcloud functions deploy phase2-to-phase3-orchestrator \
  --region=us-west2 \
  --update-env-vars ENABLE_PHASE2_COMPLETION_DEADLINE=true,PHASE2_COMPLETION_TIMEOUT_MINUTES=30 \
  --project=nba-props-platform

# Verify deployment
gcloud functions describe phase2-to-phase3-orchestrator \
  --region=us-west2 \
  --project=nba-props-platform \
  --format="value(environmentVariables)"
```

#### 2. Verify Configuration

```bash
# Check function logs for confirmation
gcloud logging read "resource.type=cloud_function
  AND resource.labels.function_name=phase2-to-phase3-orchestrator
  AND textPayload=~'ENABLE_PHASE2_COMPLETION_DEADLINE'" \
  --limit=10 \
  --project=nba-props-platform
```

## Testing

### Test Scenario: Simulate Missing Processor

1. **Setup**: Manually trigger Phase 2 with only 2/6 processors completing
2. **Expected**: After 30 minutes, Phase 3 should trigger with warning
3. **Verification**: Check Firestore `phase2_completion/{game_date}` for `_deadline_exceeded: true`

### Test Commands

```bash
# Check completion status for a game date
python orchestration/cloud_functions/phase2_to_phase3/main.py 2026-01-22

# Monitor deadline check in logs
gcloud logging read "resource.type=cloud_function
  AND resource.labels.function_name=phase2-to-phase3-orchestrator
  AND textPayload=~'DEADLINE EXCEEDED'" \
  --limit=10 \
  --format=json \
  --project=nba-props-platform
```

## Monitoring

### Key Metrics
- **Deadline Exceeded Count**: How often timeout triggers
- **Processors Completed at Deadline**: Average completion rate when deadline hits
- **Missing Processor Patterns**: Which processors consistently miss deadline

### Slack Alerts
When deadline exceeded, Slack alert includes:
- Game date
- Elapsed time
- Completed processors (X/6)
- Missing processors
- Action taken: "Phase 3 triggered with partial data"

### Log Queries

```bash
# Count deadline exceeded events (last 7 days)
gcloud logging read "resource.type=cloud_function
  AND resource.labels.function_name=phase2-to-phase3-orchestrator
  AND textPayload=~'DEADLINE EXCEEDED'
  AND timestamp>='$(date -d '7 days ago' --iso-8601)'" \
  --limit=1000 \
  --format=json \
  --project=nba-props-platform \
  | jq '. | length'

# Most commonly missing processors
gcloud logging read "resource.type=cloud_function
  AND resource.labels.function_name=phase2-to-phase3-orchestrator
  AND textPayload=~'Missing Processors'" \
  --limit=100 \
  --format=json \
  --project=nba-props-platform \
  | jq -r '.[] | .textPayload' \
  | grep -oP 'Missing Processors.*' \
  | sort | uniq -c | sort -rn
```

## Required/Optional Processor Logic

### Configuration

**Required Processors** (MUST complete):
- `bdl_player_boxscores` - Critical for player predictions
- `odds_api_game_lines` - Critical for betting lines
- `nbac_schedule` - Critical for game schedule
- `nbac_gamebook_player_stats` - Critical for post-game stats

**Optional Processors** (Nice to have):
- `bigdataball_play_by_play` - External dependency, may fail
- `br_rosters_current` - Only runs on roster changes

### Implementation Notes

Current implementation tracks all processors but doesn't enforce required/optional distinction at trigger time. This is OK because:

1. **Phase 2→3 is monitoring-only** (doesn't trigger Phase 3)
2. **Phase 3 is event-driven** (triggered by Pub/Sub subscription)
3. **Deadline provides safety net** (ensures Phase 3 eventually runs)

### Future Enhancement (Optional)

If we want to enforce required/optional logic:

```python
# In update_completion_atomic function
required_complete = all(proc in completed_processors for proc in REQUIRED_PROCESSORS)
if required_complete or deadline_exceeded:
    # Trigger Phase 3
    pass
```

## Rollback Plan

If issues occur, disable the deadline:

```bash
gcloud functions deploy phase2-to-phase3-orchestrator \
  --region=us-west2 \
  --update-env-vars ENABLE_PHASE2_COMPLETION_DEADLINE=false \
  --project=nba-props-platform
```

## Success Criteria

✅ Environment variables deployed
✅ Logs show deadline checking enabled
✅ Test simulation: Deadline triggers after 30 minutes
✅ Slack alerts received when deadline exceeded
✅ Phase 3 runs despite missing processors
✅ No false positives (deadline shouldn't trigger when all processors complete normally)

## Related Issues

- **Jan 20, 2026**: Phase 2 hung waiting for 4 missing processors
- **Week 1 Improvements**: Timeout-based reliability improvements
- **R-007 Validation**: Data freshness checks complement deadline

## Version History

- **v1.0** (2026-01-20): Initial implementation of completion deadline
- **v1.1** (2026-01-21): Added required/optional processor configuration
