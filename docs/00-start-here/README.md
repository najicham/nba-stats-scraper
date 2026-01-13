# NBA Props Platform Documentation

**Last Updated:** 2026-01-06
**Status:** Production (All 6 Phases Operational)

---

## AI Session Quick Start

**Starting a new Claude Code session? Start here:**

| Task | Guide |
|------|-------|
| **Daily orchestration check** | [DAILY-SESSION-START.md](DAILY-SESSION-START.md) |
| **Verify overnight/backfill data** | [BACKFILL-VERIFICATION-GUIDE.md](BACKFILL-VERIFICATION-GUIDE.md) |
| **Session prompt template** | [SESSION-PROMPT-TEMPLATE.md](SESSION-PROMPT-TEMPLATE.md) |
| **Latest session handoff** | [../09-handoff/](../09-handoff/) (most recent by date) |

**When you find issues or improvements:**

| What Happened | Document It Here |
|---------------|------------------|
| Found a bug/failure | [../08-projects/current/daily-orchestration-tracking/ISSUES-LOG.md](../08-projects/current/daily-orchestration-tracking/ISSUES-LOG.md) |
| Discovered useful query/check | [../08-projects/current/daily-orchestration-tracking/VALIDATION-IMPROVEMENTS.md](../08-projects/current/daily-orchestration-tracking/VALIDATION-IMPROVEMENTS.md) |
| See recurring pattern | [../08-projects/current/daily-orchestration-tracking/PATTERNS.md](../08-projects/current/daily-orchestration-tracking/PATTERNS.md) |
| Backfill-specific issue | [../08-projects/current/historical-backfill-audit/ISSUES-FOUND.md](../08-projects/current/historical-backfill-audit/ISSUES-FOUND.md) |

---

## Quick Start

| I need to... | Go here |
|--------------|---------|
| **Check system status** | [SYSTEM_STATUS.md](SYSTEM_STATUS.md) |
| **Understand the system** | [../01-architecture/quick-reference.md](../01-architecture/quick-reference.md) |
| **Run daily health check** | [DAILY-SESSION-START.md](DAILY-SESSION-START.md) |
| **Fix a production issue** | [../02-operations/troubleshooting-matrix.md](../02-operations/troubleshooting-matrix.md) |
| **Run a backfill** | [BACKFILL-VERIFICATION-GUIDE.md](BACKFILL-VERIFICATION-GUIDE.md) |
| **Monitor system health** | [../07-monitoring/unified-monitoring-guide.md](../07-monitoring/unified-monitoring-guide.md) |
| **Train ML model** | [../05-development/ml/training-procedures.md](../05-development/ml/training-procedures.md) |
| **Documentation guide** | [DOCUMENTATION-GUIDE.md](DOCUMENTATION-GUIDE.md) |
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

## Specialized Collections (non-numbered)
├── api/                # External-facing API documentation
├── lessons-learned/    # Cross-project retrospectives
├── playbooks/          # End-to-end complex workflows
└── validation-framework/  # Validation system documentation
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

- **Pipeline:** 6 phases (Scrape → Raw → Analytics → Precompute → Predictions → Publishing)
- **Status:** All 6 phases operational in production (Dec 2025)
- **Tech Stack:** GCP (BigQuery, Cloud Run, Pub/Sub, Cloud Scheduler), Python, XGBoost
- **Goal:** 55%+ accuracy on NBA player prop predictions
- **Automation:** 10+ Cloud Schedulers running daily pipeline automatically

---

## Files in This Directory

| File | Purpose |
|------|---------|
| [README.md](README.md) | This navigation guide |
| [SYSTEM_STATUS.md](SYSTEM_STATUS.md) | Current deployment status |
| [DOCUMENTATION-GUIDE.md](DOCUMENTATION-GUIDE.md) | How to organize docs (for new chats) |

## Specialized Documentation

Beyond the numbered directories, these specialized collections serve specific needs:

| Directory | Purpose | When to Use |
|-----------|---------|-------------|
| [api/](../api/) | External API docs | Frontend developers integrating with JSON API |
| [lessons-learned/](../lessons-learned/) | Organizational learning | Understanding recurring issues & solutions |
| [playbooks/](../playbooks/) | Complex workflows | Step-by-step guides for major tasks |
| [validation-framework/](../validation-framework/) | Validation system | Understanding data quality framework |

---

## Quick Operations

### Daily Tasks
- **Morning check**: [Unified Monitoring Guide](../07-monitoring/unified-monitoring-guide.md)
- **Backfill data**: [Backfill Master Guide](../02-operations/backfill/master-guide.md)
- **Train ML model**: [ML Training Procedures](../05-development/ml/training-procedures.md)

### When Things Break
- **Pipeline failure**: [Troubleshooting Matrix](../02-operations/troubleshooting-matrix.md) (if exists)
- **Data quality issue**: [Validation Framework](../validation-framework/README.md)
- **Recent incidents**: [Postmortems](../02-operations/postmortems/README.md)

---

