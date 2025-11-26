# NBA Props Platform Documentation

**Last Updated:** 2025-11-25
**Status:** Production (Phases 1-4), Testing (Phase 5)

---

## Quick Start

| I need to... | Go here |
|--------------|---------|
| **Check system status** | [SYSTEM_STATUS.md](SYSTEM_STATUS.md) |
| **Understand the system** | [../01-architecture/quick-reference.md](../01-architecture/quick-reference.md) |
| **Run daily health check** | [../02-operations/](../02-operations/README.md) |
| **Fix a production issue** | [../02-operations/troubleshooting-matrix.md](../02-operations/troubleshooting-matrix.md) |
| **Run a backfill** | [../02-operations/backfill-guide.md](../02-operations/backfill-guide.md) |
| **Learn about a phase** | [../03-phases/](../03-phases/README.md) |
| **Quick processor lookup** | [../06-reference/processor-cards/](../06-reference/processor-cards/README.md) |

---

## Documentation Structure

```
docs/
├── 00-start-here/     # You are here - navigation & status
├── 01-architecture/   # System design & decisions
├── 02-operations/     # Daily ops, backfills, troubleshooting
├── 03-phases/         # Phase-specific documentation
│   ├── phase1-orchestration/
│   ├── phase2-raw/
│   ├── phase3-analytics/
│   ├── phase4-precompute/
│   ├── phase5-predictions/
│   └── phase6-publishing/
├── 04-deployment/     # Deployment status & guides
├── 05-development/    # How to build: guides, patterns, testing
├── 06-reference/      # Quick lookups: processor cards, data flow
├── 07-monitoring/     # Grafana, alerts, observability
├── 08-projects/       # Active work & completed projects
├── 09-handoff/        # Session handoffs
└── archive/           # Historical documentation
```

---

## Learning Paths

### New to the Project (30 min)
1. [SYSTEM_STATUS.md](SYSTEM_STATUS.md) - Current state (5 min)
2. [../01-architecture/quick-reference.md](../01-architecture/quick-reference.md) - Overview (5 min)
3. [../01-architecture/pipeline-design.md](../01-architecture/pipeline-design.md) - Full design (20 min)

### Operations / SRE
1. [../02-operations/](../02-operations/README.md) - Operations hub
2. [../07-monitoring/grafana/daily-health-check.md](../07-monitoring/grafana/daily-health-check.md) - Daily routine
3. [../02-operations/troubleshooting-matrix.md](../02-operations/troubleshooting-matrix.md) - When things break

### Developer
1. [../05-development/](../05-development/README.md) - Development guides
2. [../05-development/patterns/](../05-development/patterns/README.md) - Processing patterns
3. [../03-phases/](../03-phases/README.md) - Phase details

### AI Session Resuming
1. [../09-handoff/WELCOME_BACK.md](../09-handoff/WELCOME_BACK.md) - Context refresh
2. [../08-projects/](../08-projects/README.md) - Active work
3. [SYSTEM_STATUS.md](SYSTEM_STATUS.md) - Current state

---

## Key Facts

- **Pipeline:** 6 phases (Scrape -> Raw -> Analytics -> Precompute -> Predictions -> Publishing)
- **Status:** Phases 1-4 in production, Phase 5 testing, Phase 6 planned
- **Tech Stack:** GCP (BigQuery, Cloud Run, Pub/Sub), Python, XGBoost
- **Goal:** 55%+ accuracy on NBA player prop predictions

---

## Files in This Directory

| File | Purpose |
|------|---------|
| [README.md](README.md) | This navigation guide |
| [SYSTEM_STATUS.md](SYSTEM_STATUS.md) | Current deployment status |
| [NAVIGATION_GUIDE.md](NAVIGATION_GUIDE.md) | Detailed navigation help |

