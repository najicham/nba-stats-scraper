# Documentation Directory Structure

**Version:** 4.0
**File:** `docs/05-development/docs-organization.md`
**Created:** 2025-11-15
**Last Updated:** 2025-12-27
**Purpose:** Define top-level documentation directory organization
**Status:** Current
**Audience:** Engineers and AI assistants organizing documentation

---

## Quick Reference

```
docs/
├── 00-start-here/         # Entry points & navigation
├── 00-orchestration/      # Legacy orchestration reference
├── 01-architecture/       # System design & decisions
├── 02-operations/         # Daily ops, troubleshooting, backfills
├── 03-configuration/      # Configuration documentation
├── 03-phases/             # Phase-specific docs (1-6)
├── 04-deployment/         # Deployment guides & checklists
├── 05-development/        # Developer guides & patterns
├── 06-reference/          # Quick reference (processor cards, etc.)
├── 07-monitoring/         # Grafana, alerting, observability
├── 08-projects/           # Active & completed project tracking
├── 09-handoff/            # Session handoff documents
├── 10-prompts/            # AI prompt templates
└── archive/               # Historical documentation
```

---

## Directory Purposes

### `00-start-here/` - Entry Point

**Focus:** Navigation hub for new users and AI assistants

**Contains:**
- `SYSTEM_STATUS.md` - Current system state (single source of truth)
- `NAVIGATION_GUIDE.md` - How to find documentation
- `README.md` - Quick start guide

**Start here when:** You're new to the project or resuming after a break

---

### `00-orchestration/` - Legacy Orchestration Reference

**Focus:** Historical orchestration documentation and postmortems

**Contains:**
- `services.md` - Service overview
- `monitoring.md` - Monitoring notes
- `troubleshooting.md` - Common issues
- `postmortems/` - Incident postmortems

**Note:** Main orchestration docs are now in `01-architecture/orchestration/`

---

### `01-architecture/` - System Design

**Focus:** System architecture, design decisions, patterns

**Contains:**
- `quick-reference.md` - At-a-glance overview
- `pipeline-design.md` - Complete pipeline vision
- `data-readiness-patterns.md` - Safety patterns (strict_mode, etc.)
- `orchestration/` - Pub/Sub, orchestrators, Firestore
  - `pubsub-topics.md`
  - `orchestrators.md`
  - `firestore-state-management.md`
- `change-detection/` - Change detection patterns
- `decisions/` - Architecture decision records

**Start here when:** Understanding system design or planning changes

---

### `02-operations/` - Daily Operations

**Focus:** Running and maintaining the system

**Contains:**
- `troubleshooting.md` - Common issues and fixes
- `troubleshooting-matrix.md` - Symptom → fix lookup
- `daily-monitoring.md` - Daily health checks
- `backfill/` - Backfill procedures and guides
  - `backfill-guide.md`
  - `backfill-validation-checklist.md`
  - `runbooks/` - Backfill-specific runbooks
- `runbooks/` - Operational runbooks

**Start here when:** Something is broken or you're doing daily maintenance

---

### `03-phases/` - Phase-Specific Documentation

**Focus:** Detailed docs for each pipeline phase

**Structure:**
```
03-phases/
├── phase1-orchestration/  # Scrapers & scheduling
├── phase2-raw/            # Raw data processors
├── phase3-analytics/      # Analytics processors
├── phase4-precompute/     # ML feature generation
├── phase5-predictions/    # Prediction system
│   ├── tutorials/         # Getting started
│   ├── operations/        # Deployment, troubleshooting
│   └── architecture/      # Worker design
└── phase6-publishing/     # Website exports
```

**Start here when:** Deep diving into a specific phase

---

### `04-deployment/` - Deployment

**Focus:** Deployment guides, status, and verification

**Contains:**
- `deployment-verification-checklist.md` - Post-deploy checks
- `v1.0-deployment-guide.md` - Main deployment guide
- `status.md` - Deployment status
- `history/` - Historical deployment records

**Start here when:** Deploying or verifying deployments

---

### `05-development/` - Developer Guides

**Focus:** How-to guides for developers

**Contains:**
- `docs-organization.md` - This file
- `documentation-standards.md` - Doc writing standards
- `patterns/` - Processing patterns
  - `early-exit.md`
  - `completeness-checking.md`
- `guides/` - Development how-tos
- `templates/` - Documentation templates
- `testing/` - Testing guides

**Start here when:** Building new features or writing docs

---

### `06-reference/` - Quick Reference

**Focus:** Scannable reference documentation

**Contains:**
- `processor-cards/` - Per-processor quick facts
  - Phase 3, 4, 5 processor cards
  - Workflow diagrams
- `data-flow/` - Field transformations
- `data-sources/` - Data source documentation
- `scrapers.md` - Scraper reference
- `analytics-processors.md` - Analytics reference

**Start here when:** Need quick facts about a component

---

### `07-monitoring/` - Observability

**Focus:** Monitoring, alerting, dashboards

**Contains:**
- `grafana/` - Dashboard documentation
  - `dashboards/` - Query files
  - `daily-health-check.md`
- `alerting/` - Alert configuration
- `run-history-guide.md` - Processor run history
- `completeness-monitoring.md` - Completeness checks

**Start here when:** Setting up monitoring or checking system health

---

### `08-projects/` - Project Tracking

**Focus:** Active and completed project documentation

**Structure:**
```
08-projects/
├── current/      # 10 active projects
├── completed/    # 18 archived projects
├── backlog/      # Future work
└── archive/      # Legacy projects
```

**Contains:**
- Project READMEs with status
- Implementation plans
- Design documents

**Start here when:** Checking project status or starting new work

---

### `09-handoff/` - Session Handoffs

**Focus:** Session-to-session continuity

**Contains:**
- `YYYY-MM-DD-*.md` - Daily handoff documents
- Session summaries and progress updates
- Next steps for following sessions

**Naming:** `2025-12-27-SESSION173-topic.md`

**Start here when:** Resuming work from a previous session

---

### `10-prompts/` - AI Prompts

**Focus:** Prompt templates for AI-assisted work

**Contains:**
- Analysis prompts
- Design prompts
- Audit prompts

---

### `archive/` - Historical Documentation

**Focus:** Old documentation preserved for reference

**Contains:**
- Date-organized archives (2024-10, 2025-08, etc.)
- Legacy documentation
- Superseded docs

---

## Decision Tree: Where Does My Doc Go?

```
What is your documentation about?

├─ System status or entry point
│  └─ 00-start-here/
│
├─ Architecture, design, or patterns
│  └─ 01-architecture/
│
├─ Operations, troubleshooting, backfills
│  └─ 02-operations/
│
├─ Specific pipeline phase (1-6)
│  └─ 03-phases/phase{N}-{name}/
│
├─ Deployment procedures or status
│  └─ 04-deployment/
│
├─ Development guides or patterns
│  └─ 05-development/
│
├─ Quick reference or lookup
│  └─ 06-reference/
│
├─ Monitoring, dashboards, alerts
│  └─ 07-monitoring/
│
├─ Project tracking (active or completed)
│  └─ 08-projects/
│
├─ Session handoff or progress notes
│  └─ 09-handoff/
│
└─ AI prompts or templates
   └─ 10-prompts/
```

---

## Naming Conventions

### Directory Prefixes
- `00-` through `10-` indicate reading/navigation order
- Lower numbers = more foundational/entry-point
- Higher numbers = more specialized

### File Names
- Use `kebab-case` for file names: `daily-monitoring.md`
- Use descriptive names: `deployment-verification-checklist.md`
- Prefix with numbers for reading order within a directory

### Handoff Files
- Format: `YYYY-MM-DD-description.md`
- Example: `2025-12-27-SESSION173-docs-cleanup.md`

---

## Cross-References

When docs relate across directories, add a "Related Documentation" section:

```markdown
## Related Documentation

- [Architecture Overview](../01-architecture/quick-reference.md)
- [Troubleshooting](../02-operations/troubleshooting.md)
- [Processor Cards](../06-reference/processor-cards/)
```

---

## Best Practices

1. **Keep directories focused** - Each has ONE clear purpose
2. **Use cross-references** - Link related docs liberally
3. **Update READMEs** - When adding docs, update the directory README
4. **Archive don't delete** - Move outdated docs to archive/

---

## Version History

### v4.0 (2025-12-27)
- Complete rewrite to reflect actual numbered directory structure
- Documents actual structure: 00-start-here through 10-prompts
- Removed references to non-existent directories (deployment/, reference/, guides/, handoff/ at root)
- Added decision tree for current structure
- Updated naming conventions

### v3.0 (2025-11-22)
- Added planned directories (never fully implemented)

### v2.0 (2025-11-15)
- Major reorganization proposal

---

**Guide Status:** Current (v4.0)
**Next Review:** After major reorganization
