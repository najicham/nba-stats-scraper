# NBA Props Platform - System Status

**Created:** 2025-11-15 10:00 PST
**Last Updated:** 2025-12-02 16:45 PST
**Purpose:** Single source of truth for current deployment status
**Audience:** Anyone asking "what's the current state of the system?"

---

## TL;DR - Current State

**Overall Status:** v1.0 DEPLOYED - Backfill In Progress
**Deployment Date:** 2025-11-29
**Current Focus:** Historical data backfill (Phase 3 complete, Phase 4 pending)

---

## Data Pipeline Coverage

| Phase | Dataset | Days with Data | Date Range | Status |
|-------|---------|----------------|------------|--------|
| **Phase 2 (Raw)** | `nba_raw` | 888 days | 2021-10-03 to 2025-06-22 | Complete |
| **Phase 3 (Analytics)** | `nba_analytics` | 524 days | 2021-10-20 to 2025-06-22 | ~60% Complete |
| **Phase 4 (Precompute)** | `nba_precompute` | 0 days | - | Pending Backfill |
| **Phase 5 (Predictions)** | `nba_predictions` | 0 days | - | Pending Backfill |

**Next Step:** Run Phase 4 backfill starting from Nov 2, 2021 (after 14-day bootstrap period)

---

## v1.0 Architecture

```
Phase 1: Scrapers (26+)
    | Pub/Sub: nba-phase1-scrapers-complete
    v
Phase 2: Raw Processors (21)
    | Pub/Sub: nba-phase2-raw-complete
    v
Phase 2->3 Orchestrator (Cloud Function)
    | Pub/Sub: nba-phase3-trigger
    v
Phase 3: Analytics (5 processors)
    | Pub/Sub: nba-phase3-analytics-complete
    v
Phase 3->4 Orchestrator (Cloud Function)
    | Pub/Sub: nba-phase4-trigger
    v
Phase 4: Precompute (5 processors)
    | Pub/Sub: nba-phase4-precompute-complete
    v
Phase 5: Predictions (Coordinator + Workers)
    | Pub/Sub: nba-phase5-predictions-complete
    v
Phase 6: Web App (Not started)
```

---

## Cloud Run Services (15 Deployed)

| Service | Phase | Status |
|---------|-------|--------|
| `nba-phase1-scrapers` | 1 | Running |
| `nba-phase2-raw-processors` | 2 | Running |
| `nba-phase3-analytics-processors` | 3 | Running |
| `nba-phase4-precompute-processors` | 4 | Running |
| `prediction-coordinator` | 5 | Running |
| `prediction-worker` | 5 | Running |
| `phase2-to-phase3-orchestrator` | 2->3 | Running |
| `phase3-to-phase4-orchestrator` | 3->4 | Running |
| `phase4-to-phase5-orchestrator` | 4->5 | Running |
| `pipeline-health-summary` | Monitor | Running |
| + 5 legacy services | - | Running |

---

## Phase Status Detail

| Phase | Status | Components | Notes |
|-------|--------|------------|-------|
| Phase 1 | Production | 26+ scrapers | Data collection operational |
| Phase 2 | Production | 21 processors | Raw data processing complete |
| Phase 2->3 | Production | Cloud Function | Orchestrator deployed |
| Phase 3 | Production | 5 processors | Analytics deployed, backfill 60% |
| Phase 3->4 | Production | Cloud Function | Orchestrator deployed |
| Phase 4 | Deployed | 5 processors | Needs backfill (0 days of data) |
| Phase 5 | Deployed | Coordinator + Workers | Needs Phase 4 data |
| Phase 6 | Not Started | - | Web app publishing |

---

## Key v1.0 Features

| Feature | Status |
|---------|--------|
| Event-Driven Pipeline | Deployed |
| Pub/Sub Orchestration | 8 topics active |
| Firestore State Management | 2 collections |
| Cloud Function Orchestrators | 2 deployed |
| Fallback Data Sources | Configured |
| Quality Tracking | Implemented |
| Validation System | Operational |
| Email Alerts | Configured |

---

## Recent Updates (2025-12-02)

- Validation system enhanced with:
  - Cross-phase consistency checks
  - Duplicate detection
  - Timeout handling improvements
  - NULL field tracking
- All Cloud Run services verified running
- Documentation review completed

---

## Backfill Priority

1. **Phase 4 Backfill** (Primary)
   - Start date: 2021-11-02 (after 14-day bootstrap)
   - End date: Present
   - Prerequisite: Phase 3 data must exist

2. **Phase 3 Gap Fill** (Secondary)
   - Missing: 2021-10-19 (day 1)
   - Current coverage: 524/~900 expected days

See: [Backfill Project](../08-projects/current/backfill/00-START-HERE.md)

---

## Quick Links

| Need | Link |
|------|------|
| Validation | `python3 bin/validate_pipeline.py YYYY-MM-DD` |
| Health check | `./bin/orchestration/quick_health_check.sh` |
| Backfill guide | [08-projects/current/backfill/](../08-projects/current/backfill/) |
| Architecture | [01-architecture/quick-reference.md](../01-architecture/quick-reference.md) |

---

## Cost Estimates (Monthly)

| Component | Cost |
|-----------|------|
| Cloud Run (all services) | ~$50 |
| Cloud Functions | ~$2 |
| BigQuery | ~$20 |
| Pub/Sub | Free tier |
| Firestore | Free tier |
| **Total** | **~$72/month** |

---

**Document Version:** 4.0
**Last Verification:** 2025-12-02 16:45 PST
**Next Review:** After Phase 4 backfill complete
