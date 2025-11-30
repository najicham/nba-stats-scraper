# Orchestration Cloud Functions

Cloud Functions for coordinating phase transitions in the NBA Props Platform pipeline.

## Overview

These Cloud Functions track processor completions and trigger the next phase when all upstream processors have finished. They use Firestore for state management and atomic transactions to prevent race conditions.

```
Phase 2 (21 processors) ──→ phase2_to_phase3 ──→ Phase 3 (5 processors)
                                                        │
Phase 3 (5 processors)  ──→ phase3_to_phase4 ──→ Phase 4 (5 processors)
```

## Functions

| Function | Listens To | Triggers | Tracks |
|----------|------------|----------|--------|
| `phase2_to_phase3` | `nba-phase2-raw-complete` | `nba-phase3-trigger` | 21 Phase 2 processors |
| `phase3_to_phase4` | `nba-phase3-analytics-complete` | `nba-phase4-trigger` | 5 Phase 3 processors |

## Deployment

```bash
# Deploy Phase 2→3 orchestrator
./bin/orchestrators/deploy_phase2_to_phase3.sh

# Deploy Phase 3→4 orchestrator
./bin/orchestrators/deploy_phase3_to_phase4.sh
```

## Key Features

1. **Atomic Transactions** - Firestore transactions prevent race conditions when multiple processors complete simultaneously
2. **Idempotency** - Handles duplicate Pub/Sub messages safely
3. **Correlation ID Tracking** - Preserves trace IDs through the entire pipeline
4. **Entity Aggregation** (Phase 3→4) - Combines `entities_changed` from all analytics processors

## Firestore State

| Collection | Document | Purpose |
|------------|----------|---------|
| `phase2_completion` | `{game_date}` | Tracks Phase 2 processor completions |
| `phase3_completion` | `{game_date}` | Tracks Phase 3 processor completions |

## Related Documentation

- [Orchestrators Architecture](../../docs/01-architecture/orchestration/orchestrators.md)
- [Pub/Sub Topics](../../docs/01-architecture/orchestration/pubsub-topics.md)
- [Orchestrator Monitoring](../../docs/02-operations/orchestrator-monitoring.md)
