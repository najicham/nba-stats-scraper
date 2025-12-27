# Phase 6 Design - Web Publishing

**Created:** 2025-12-02
**Status:** Design Phase (Pre-Implementation)
**Last Updated:** 2025-12-02

---

## Overview

Phase 6 publishes predictions from BigQuery to a web-accessible format for end users.

```
Phase 5 (BigQuery)              Phase 6 (Web)
┌─────────────────────┐         ┌─────────────────────┐
│ player_prop_        │   →     │ Firestore/API       │
│ predictions         │         │ + Web UI            │
└─────────────────────┘         └─────────────────────┘
```

---

## Current State

### What We Have (Phase 5 Output)

| Field | Type | Sample Value |
|-------|------|--------------|
| `player_lookup` | STRING | `stephen_curry` |
| `game_date` | DATE | `2025-11-25` |
| `game_id` | STRING | `20251125_GSW_NOP` |
| `system_id` | STRING | `ensemble` |
| `predicted_points` | FLOAT | `29.0` |
| `confidence_score` | FLOAT | `72.5` |
| `recommendation` | STRING | `OVER` / `UNDER` / `PASS` |
| `current_points_line` | FLOAT | `25.5` |
| `line_margin` | FLOAT | `3.5` |

### Sample Data Available

- **40 predictions** from Nov 25, 2025 (test run)
- All currently PASS (low confidence during testing)
- 5 systems: moving_average, zone_matchup_v1, similarity, xgboost_v1, ensemble

### Blockers for Implementation

1. **Phase 4 needs backfill** (currently 0 days of data)
2. **Phase 5 needs real predictions** (not just test data)
3. **No XGBoost model trained** yet

---

## Design Documents

| Document | Purpose |
|----------|---------|
| [01-requirements.md](./01-requirements.md) | User requirements and use cases |
| [02-architecture.md](./02-architecture.md) | Technical architecture options |
| [03-data-model.md](./03-data-model.md) | Firestore/API schema design |
| [04-implementation-plan.md](./04-implementation-plan.md) | Implementation steps |

---

## Quick Summary

### Target Users

1. **Bettors** - Want OVER/UNDER recommendations
2. **Analysts** - Want to see model confidence and reasoning
3. **Developers** - Want API access for integrations

### Key Features

1. Today's predictions (primary use case)
2. Historical accuracy tracking
3. Model comparison
4. Real-time updates when lines change

### Technical Approach (Proposed)

```
BigQuery                    Firestore                 Web UI
┌─────────────┐   publish   ┌─────────────┐   read   ┌─────────────┐
│ predictions │ ─────────→  │ predictions │ ───────→ │ React/Vue   │
│ (source)    │             │ (cache)     │          │ (display)   │
└─────────────┘             └─────────────┘          └─────────────┘
        ↑                                                   │
        │                   Cloud Functions                 │
        └──────────────────────────────────────────────────┘
                              (schedule)
```

---

## Timeline

| Milestone | Prerequisite | Status |
|-----------|--------------|--------|
| Phase 6 Design | None | **In Progress** |
| Phase 4 Backfill | Design complete | Pending |
| Phase 5 Real Data | Phase 4 data | Pending |
| Phase 6 Implementation | Real Phase 5 data | Not Started |

---

## Next Steps

1. Complete design documents
2. Run Phase 4 backfill
3. Validate Phase 5 produces OVER/UNDER recommendations
4. Implement Phase 6 publishing
5. Build web UI

---

## Related Documentation

- [Phase 5 Operations](../../docs/03-phases/phase5-predictions/operations.md)
- [System Status](../../00-start-here/SYSTEM_STATUS.md)
