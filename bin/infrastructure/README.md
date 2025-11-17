# Infrastructure Scripts

This directory contains scripts for managing GCP infrastructure (Pub/Sub topics, subscriptions, etc.).

## Pub/Sub Topic Management

### Topic Naming Convention

All topics follow the pattern: `nba-phase{N}-{content}-{type}`

- **Sport prefix**: `nba-` (future: `mlb-`, `nfl-`)
- **Phase number**: `1-6` (pipeline position)
- **Content type**: `scrapers`, `raw`, `analytics`, `precompute`, `predictions`
- **Type**: `complete` (main events), `complete-dlq` (dead letter queue), `fallback-trigger` (time-based)

**Examples:**
- `nba-phase1-scrapers-complete`
- `nba-phase2-raw-complete-dlq`
- `nba-phase3-fallback-trigger`

### Configuration

All topic names are centralized in:
```
shared/config/pubsub_topics.py
```

**Always import from this file** - never hardcode topic names!

```python
from shared.config.pubsub_topics import TOPICS

# Good ✅
publisher.publish(TOPICS.PHASE2_RAW_COMPLETE, message)

# Bad ❌
publisher.publish("nba-phase2-raw-complete", message)
```

## Scripts

### 1. Create Phase 2→3 Topics

Creates all infrastructure needed for Phase 3 deployment.

```bash
./bin/infrastructure/create_phase2_phase3_topics.sh
```

**Creates:**
- `nba-phase2-raw-complete` (main event topic)
- `nba-phase2-raw-complete-dlq` (dead letter queue)
- `nba-phase3-fallback-trigger` (time-based safety net)
- Subscriptions for Phase 3 analytics service

See script for full details and usage.
