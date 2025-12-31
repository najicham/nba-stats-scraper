# Pipeline Replay & Test Environment

## Overview

The Pipeline Replay System allows running the complete NBA data pipeline (Phases 2-6) against any historical date in a controlled test environment. This enables:

- **Speed Testing**: Measure latency at each phase, detect performance regressions
- **Error Detection**: Catch bugs before production, test edge cases
- **Data Validation**: Verify record counts, check for duplicates, ensure completeness
- **Development**: Debug issues locally without affecting production

## Quick Start

```bash
# Create test datasets (one-time setup)
./bin/testing/setup_test_datasets.sh

# Replay yesterday's data (dry run first)
PYTHONPATH=. python bin/testing/replay_pipeline.py --dry-run

# Replay a specific date
PYTHONPATH=. python bin/testing/replay_pipeline.py 2024-12-15

# Replay starting from Phase 4
PYTHONPATH=. python bin/testing/replay_pipeline.py 2024-12-15 --start-phase=4

# Validate replay outputs
PYTHONPATH=. python bin/testing/validate_replay.py 2024-12-15
```

## Architecture Decision

We chose a **Hybrid Local Replay** approach over full environment isolation:

| Approach | Pros | Cons | Chosen? |
|----------|------|------|---------|
| **Dataset Prefix** | Minimal changes, easy comparison | Shares quota | ✅ Yes |
| **Full Isolation** | Complete separation | Expensive, complex | ❌ No |
| **Local Execution** | Fast, controllable | Skips cloud orchestration | ✅ Yes |

**Key Insight**: The cloud orchestration (Pub/Sub, Cloud Functions) is glue code. Bugs and performance issues occur in the **processor logic**, which we test fully.

## What Gets Tested

| Component | Tested in Replay | Notes |
|-----------|------------------|-------|
| Processor business logic | ✅ Yes | Full coverage |
| BigQuery queries | ✅ Yes | Against test datasets |
| Data transformations | ✅ Yes | Same code paths |
| GCS read/write | ✅ Yes | With path prefix |
| Pub/Sub orchestration | ❌ No | Not needed - direct calls |
| Cloud Function triggers | ❌ No | Not needed - direct calls |

## Directory Structure

```
bin/testing/
├── replay_pipeline.sh      # Main replay script
├── validate_replay.py      # Validation framework
├── compare_outputs.py      # Compare test vs production
└── setup_test_datasets.sh  # Create test BigQuery datasets

docs/08-projects/current/test-environment/
├── README.md               # This file
├── ARCHITECTURE.md         # Design decisions
├── USAGE-GUIDE.md          # Detailed usage
└── IMPLEMENTATION-PLAN.md  # Build steps
```

## Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| Test dataset setup | ✅ Complete | `bin/testing/setup_test_datasets.sh` |
| Replay script | ✅ Complete | `bin/testing/replay_pipeline.py` |
| Validation framework | ✅ Complete | `bin/testing/validate_replay.py` |
| Dataset prefix support | 🟡 Partial | Scripts built, processors need update |
| GCS prefix support | 🔴 Not Started | Environment variable needed |
| Documentation | ✅ Complete | This folder |

**Note**: The replay script uses HTTP calls to Cloud Run services. For full
isolation (writing to test datasets), the processor services need to accept
a `dataset_prefix` parameter. See IMPLEMENTATION-PLAN.md for details.

## Related Documentation

- [Architecture Details](./ARCHITECTURE.md)
- [Usage Guide](./USAGE-GUIDE.md)
- [Implementation Plan](./IMPLEMENTATION-PLAN.md)
- [Pipeline Reliability Improvements](../pipeline-reliability-improvements/)
