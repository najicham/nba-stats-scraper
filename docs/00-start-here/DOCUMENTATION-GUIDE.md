# Documentation Organization Guide

**Purpose**: Guide for maintaining documentation structure
**Audience**: AI assistants, future developers, documentation maintainers
**Last Updated**: January 6, 2026

---

## Quick Reference: Where Does This Go?

| I'm creating... | Put it in... | Example |
|----------------|--------------|---------|
| **Current procedure/how-to** | Numbered docs (00-10) | `02-operations/backfill/master-guide.md` |
| **Active project work** | `08-projects/current/{project}/` | `08-projects/current/website-ui/` |
| **Completed project** | `08-projects/completed/{year-month}/` | `08-projects/completed/2026-01/backfill-system-analysis/` |
| **Session handoff** | `09-handoff/` | `09-handoff/2026-01-06-MORNING.md` |
| **Lessons learned** | `lessons-learned/` | `lessons-learned/BACKFILL-LESSONS-2026.md` |
| **API documentation** | `api/` | `api/FRONTEND_API_REFERENCE.md` |
| **Complex workflow guide** | `playbooks/` | `playbooks/ML-TRAINING-PLAYBOOK.md` |
| **Postmortem** | `02-operations/postmortems/{year}/` | `02-operations/postmortems/2025/gamebook-incident.md` |

---

## Core Philosophy: Dual-Track Architecture

Our documentation follows a **dual-track model**:

### Track 1: Numbered Docs (00-10) = "How to do it NOW"
**Purpose**: Current, authoritative procedures

**Characteristics**:
- ✅ Maintained and kept up-to-date
- ✅ Single source of truth for procedures
- ✅ Cross-referenced to projects for examples
- ❌ No session logs or historical timelines
- ❌ No outdated content (archive old versions)

**Example**: "How do I run a backfill today?"
→ Read `02-operations/backfill/master-guide.md`

### Track 2: Projects = "What happened and why"
**Purpose**: Historical context, execution logs, decisions made

**Characteristics**:
- ✅ Complete narrative of project execution
- ✅ Timeline, decisions, issues, performance data
- ✅ Preserved intact after completion
- ✅ Cross-references to numbered docs for procedures
- ❌ Not maintained after project completion
- ❌ Not used as procedural guide

**Example**: "What happened during Jan 2026 backfill?"
→ Read `08-projects/completed/2026-01/complete-pipeline-backfill/`

---

## Numbered Directory Structure (00-10)

```
docs/
├── 00-start-here/          # Navigation hub, system status
├── 01-architecture/        # System design, architecture decisions
├── 02-operations/          # Daily ops, runbooks, troubleshooting
├── 03-phases/             # Phase-specific documentation
├── 04-deployment/          # Deployment guides, checklists
├── 05-development/         # Dev guides, patterns, testing
├── 06-reference/           # Quick lookups, data sources
├── 07-monitoring/          # Monitoring, alerts, observability
├── 08-projects/            # Active and historical projects
├── 09-handoff/             # Session transitions
└── 10-prompts/             # AI prompts
```

### 00-start-here/
**Purpose**: Entry point for all documentation

**What goes here**:
- README.md (navigation, learning paths)
- SYSTEM_STATUS.md (current deployment state)
- DOCUMENTATION-GUIDE.md (this file)

**Maintenance**: Update when major structure changes

### 01-architecture/
**Purpose**: System design and architectural decisions

**What goes here**:
- Pipeline design documentation
- Data flow diagrams
- Architecture Decision Records (ADRs)
- Dependency maps
- Self-healing patterns

**Maintenance**: Update when architecture changes (rare)

**Example**:
```
01-architecture/
├── pipeline-design.md
├── data-flow.md
├── pipeline-dependencies.md
└── decisions/
    ├── 001-event-driven-orchestration.md
    └── 002-batch-staging-pattern.md
```

### 02-operations/
**Purpose**: Daily operations, troubleshooting, runbooks

**What goes here**:
- Operational procedures
- Runbooks for common tasks
- Troubleshooting guides
- Monitoring procedures
- Postmortems
- Infrastructure reports

**Maintenance**: Update frequently as procedures improve

**Example**:
```
02-operations/
├── README.md
├── daily-health-check.md
├── backfill/
│   ├── master-guide.md          ← Authoritative backfill procedure
│   ├── troubleshooting.md
│   ├── checklists/
│   └── runbooks/
├── monitoring/
│   └── daily-monitoring.md
├── postmortems/
│   ├── 2025/
│   └── 2026/
└── reports/
```

### 03-phases/
**Purpose**: Documentation specific to each pipeline phase

**What goes here**:
- Phase-specific guides
- Data schemas for each phase
- Common issues per phase

**Maintenance**: Update when phase changes

### 04-deployment/
**Purpose**: Deployment guides and procedures

**What goes here**:
- Deployment checklists
- Environment configuration
- Rollback procedures
- Implementation status tracking

**Maintenance**: Update with each deployment

### 05-development/
**Purpose**: Development guides, patterns, testing

**What goes here**:
- Code patterns
- Development setup
- Testing procedures
- ML training procedures
- Templates

**Maintenance**: Update as patterns evolve

**Example**:
```
05-development/
├── patterns/
│   ├── merge-pattern.md         ← Proper BigQuery MERGE
│   └── checkpoint-recovery.md
├── ml/
│   ├── training-procedures.md   ← How to train models
│   └── data-quality-requirements.md
└── testing/
    └── testing-strategy.md
```

### 06-reference/
**Purpose**: Quick lookups, reference material

**What goes here**:
- Processor cards (quick reference sheets)
- Data source documentation
- Model performance history
- API reference (internal)

**Maintenance**: Append-only (historical record)

### 07-monitoring/
**Purpose**: Monitoring, alerts, observability

**What goes here**:
- Unified monitoring guide
- Grafana dashboards
- Cloud Logging queries
- Alert procedures

**Maintenance**: Update as monitoring evolves

### 08-projects/
**Purpose**: Project work tracking (active and completed)

**Structure**:
```
08-projects/
├── current/            # Active projects (< 10 at a time)
│   ├── website-ui/
│   ├── test-environment/
│   └── pipeline-reliability-improvements/
└── completed/          # Historical projects
    ├── 2025-12/
    └── 2026-01/
```

**See detailed section below**

### 09-handoff/
**Purpose**: Session state transitions

**Structure**:
```
09-handoff/
├── 2026-01-06-MORNING.md       # Current handoff
├── 2026-01-05-COMPLETE.md      # This week
├── maintenance-playbook.md     # Permanent utility
├── session-prompt.md           # Permanent utility
└── archive/                    # Old handoffs by month
    ├── 2025-11/
    ├── 2025-12/
    └── 2026-01-early/
```

**See detailed section below**

### 10-prompts/
**Purpose**: AI prompts and templates

**What goes here**:
- Prompt templates
- AI interaction patterns

---

## Project Organization (08-projects/)

### Creating a New Project

1. **Create in current/**:
```bash
mkdir -p docs/08-projects/current/{project-name}
cd docs/08-projects/current/{project-name}
```

2. **Create README.md**:
```markdown
# Project Name

**Status**: Active
**Started**: YYYY-MM-DD
**Owner**: Team/Person
**Goal**: One-sentence description

## Quick Start
Brief context for someone jumping in

## Current Procedure
For the current procedure, see: [Link to numbered docs]

## Progress
- [ ] Task 1
- [ ] Task 2

## Structure
- README.md - This file
- TODO.md - Action items
- findings/ - Investigation results
- decisions/ - Why we chose X over Y
- execution/ - Implementation logs
```

3. **Organize content**:
```
{project-name}/
├── README.md              # Project overview
├── TODO.md                # Action items
├── findings/              # What we discovered
│   ├── investigation-1.md
│   └── investigation-2.md
├── decisions/             # Why we chose X over Y
│   ├── decision-1.md
│   └── decision-2.md
└── execution/             # Implementation logs
    ├── execution-log-1.md
    └── performance-results.md
```

### Completing a Project

1. **Update README status**:
```markdown
**Status**: Completed
**Completed**: 2026-01-05
**Outcome**: Brief summary of results
```

2. **Add cross-reference to numbered docs**:
```markdown
## Current Procedure
This project documented a historical execution.
For the current procedure, see: [Master Guide](../../02-operations/backfill/master-guide.md)
```

3. **Move to completed/**:
```bash
mv docs/08-projects/current/{project-name} \
   docs/08-projects/completed/$(date +%Y-%m)/
```

4. **Extract lessons learned**:
- If significant learnings, create doc in `lessons-learned/`
- Update relevant guides in numbered docs with improvements

### When to Archive a Project

**Archive (move to completed/) when**:
- ✅ All tasks completed
- ✅ Changes deployed to production
- ✅ No more active work planned
- ✅ Lessons extracted to numbered docs

**Keep active when**:
- ⏸️ On hold but will resume
- ⏸️ Ongoing maintenance work
- ⏸️ Waiting for external dependencies

**Rule of Thumb**: If you haven't touched it in 2 weeks, probably completed

---

## Handoff Organization (09-handoff/)

### Purpose
Session handoffs track state transitions between work sessions. They're **short-term memory**, not permanent documentation.

### Lifecycle

1. **Creation**: End of each session
2. **Active**: Current week (7 days)
3. **Archive**: After 7 days, move to archive/{year-month}/

### Naming Convention
```
{YYYY}-{MM}-{DD}-{DESCRIPTION}.md

Examples:
2026-01-06-MORNING-HANDOFF.md
2026-01-05-BACKFILL-COMPLETE.md
2026-01-04-BUG-FIX-DEPLOYED.md
```

### Content Structure
```markdown
# Session Handoff - Date

**Status**: Current state summary
**Next Actions**: What to do next

## What Happened
Brief summary of session activities

## Key Decisions
Important choices made

## Open Items
- [ ] Task 1
- [ ] Task 2

## Context for Next Session
Links to:
- Active projects: docs/08-projects/current/
- Current procedures: docs/02-operations/
- Relevant completed work: docs/08-projects/completed/
```

### Maintenance

**Weekly** (every Monday):
```bash
# Archive last week's handoffs
cd docs/09-handoff
find . -maxdepth 1 -name "202*.md" -mtime +7 \
  -exec mv {} archive/$(date -d "last week" +%Y-%m)/ \;
```

**Keep Permanently**:
- maintenance-playbook.md
- session-prompt.md
- known-data-gaps.md
- Other utility files (not dated)

**Archive by Month**:
- Simple chronological organization
- No topic categorization (too much work)
- Searchable if needed with grep

---

## Non-Numbered Directories

### api/
**Purpose**: External-facing API documentation

**Why separate**: Different audience (frontend developers, not internal ops)

**What goes here**:
- API endpoint reference
- Authentication guides
- Data format specifications

### lessons-learned/
**Purpose**: Cross-project retrospectives

**Why separate**: Synthesizes multiple projects, organizational learning

**Structure**:
```
lessons-learned/
├── README.md                            # Index
├── DATA-QUALITY-JOURNEY-JAN-2026.md    # Major incident/discovery
├── BACKFILL-LESSONS-2026.md            # Consolidated from multiple projects
└── PHASE5-DEPLOYMENT-LESSONS-2025-11.md
```

**When to create**:
- After major incidents
- When pattern emerges across multiple projects
- Significant architectural learning
- Prevention of repeated mistakes

### playbooks/
**Purpose**: End-to-end complex workflows

**Why separate**: Different from runbooks (incident response)

**Playbooks vs Runbooks**:
- **Playbooks**: "How to accomplish complex task from start to finish"
- **Runbooks**: "How to respond to specific incident/failure"

**Examples**:
- ML-TRAINING-PLAYBOOK.md (comprehensive training workflow)
- BACKFILL-PLAYBOOK.md (when and how to create backfills)
- NEW-PROCESSOR-PLAYBOOK.md (adding new data processor)

### validation-framework/
**Purpose**: Validation system documentation

**Why separate**: Documents a system component, not operations

**What goes here**:
- Framework architecture
- Validation patterns
- Implementation guides

---

## Naming Conventions

### Files

**Descriptive, kebab-case**:
```
✅ backfill-master-guide.md
✅ pipeline-dependencies.md
✅ ml-training-procedures.md

❌ guide.md (too generic)
❌ BackfillGuide.md (wrong case)
❌ backfill_guide.md (underscores, not hyphens)
```

**Dated files** (handoffs, reports):
```
{YYYY}-{MM}-{DD}-{description}.md

✅ 2026-01-06-MORNING-HANDOFF.md
✅ 2026-01-05-BACKFILL-COMPLETE.md

❌ jan-6-handoff.md (wrong date format)
❌ 01-06-2026-handoff.md (wrong date order)
```

### Directories

**Lowercase, hyphenated**:
```
✅ backfill-system-analysis/
✅ ml-model-development/
✅ pipeline-reliability-improvements/

❌ BackfillSystem/ (wrong case)
❌ backfill_system/ (underscores)
```

**Project directories**: Descriptive, not generic
```
✅ complete-pipeline-backfill-2026-01/
✅ prediction-coverage-fix/
✅ website-ui/

❌ project-1/ (too generic)
❌ temp/ (not descriptive)
```

---

## Cross-Referencing

### From Numbered Docs to Projects

```markdown
# In 02-operations/backfill/master-guide.md

## Historical Execution Examples

For detailed execution logs and lessons learned:

- **[Jan 2026: Complete Pipeline Backfill](../../08-projects/completed/2026-01/complete-pipeline-backfill/)**
  - First full backfill with parallelization
  - 200+ hours saved through optimization
  - MERGE bug discovery and fix

- **[Dec 2025: Four-Season Backfill](../../08-projects/completed/2025-12/four-season-backfill/)**
  - Phase 5 predictions only
  - Sequential execution pattern
```

### From Projects to Numbered Docs

```markdown
# In 08-projects/completed/2026-01/complete-pipeline-backfill/README.md

## Current Backfill Procedure

⚠️ **This document describes a historical execution (Jan 5-7, 2026).**

For the current, up-to-date backfill procedure, see:
→ **[Backfill Master Guide](../../../../02-operations/backfill/master-guide.md)**

## Related Documentation

- [Troubleshooting Guide](../../../../02-operations/backfill/troubleshooting.md)
- [Pipeline Dependencies](../../../../01-architecture/pipeline-dependencies.md)
- [Validation Framework](../../../../validation-framework/README.md)
```

### Link Format

**Relative links** (preferred):
```markdown
[Link Text](../../path/to/file.md)
```

**Absolute from repo root** (when clearer):
```markdown
[Link Text](/docs/02-operations/backfill/master-guide.md)
```

**Section links**:
```markdown
[Link to Section](./file.md#section-heading)
```

---

## When to Create New Documentation

### Decision Tree

```
Is this information...

├─ Procedural (how to do X)?
│  └─ YES → Create/update in numbered docs (00-10)
│
├─ Project work (tracking active tasks)?
│  └─ YES → Create in 08-projects/current/
│
├─ Historical (what happened)?
│  └─ YES → Document in project, then move to completed/
│
├─ Session state (what's next)?
│  └─ YES → Create handoff in 09-handoff/
│
├─ Lesson learned (cross-project insight)?
│  └─ YES → Create in lessons-learned/
│
├─ Complex workflow (end-to-end process)?
│  └─ YES → Create in playbooks/
│
└─ External API documentation?
   └─ YES → Create in api/
```

### Red Flags (Don't Create)

❌ **Duplicate existing guide** → Update existing or add cross-reference
❌ **Session logs in numbered docs** → Goes in handoff or project
❌ **Outdated procedures** → Update existing or archive, don't keep both versions
❌ **Project-specific procedure** → Goes in project, link to numbered docs for general procedure

---

## Maintenance Schedule

### Weekly (Monday, 10 minutes)
```bash
# Archive old handoffs
cd docs/09-handoff
find . -maxdepth 1 -name "202*.md" -mtime +7 \
  -exec mv {} archive/$(date -d "last week" +%Y-%m)/ \;

# Clean up root (keep only 2-3 session guides)
cd /home/naji/code/nba-stats-scraper
ls -lt *.md | grep -E "START|SESSION|MORNING" | tail -n +4 | awk '{print $9}' | xargs rm -f
```

### Monthly (1st week, 30 minutes)
- Review `08-projects/current/` for completed projects
- Move completed projects to `08-projects/completed/{year-month}/`
- Extract lessons learned from completed projects
- Update master guides with new patterns

### Quarterly (2 hours)
- Review completed projects for knowledge extraction
- Update architecture docs if patterns changed
- Archive very old handoffs (> 6 months) to deep archive
- Review and update 00-start-here/ navigation

---

## For New AI Assistants

When starting a new chat session:

### 1. Check Current State
```bash
# What's the current status?
cat docs/00-start-here/SYSTEM_STATUS.md

# What's the latest handoff?
ls -t docs/09-handoff/202*.md | head -1 | xargs cat

# What projects are active?
ls docs/08-projects/current/
```

### 2. Understand Structure
- Read this guide (you're reading it!)
- Review docs/00-start-here/README.md
- Check docs/09-handoff/maintenance-playbook.md

### 3. Add New Documentation
- Use decision tree above to determine location
- Follow naming conventions
- Add cross-references
- Update relevant indexes

### 4. Never Delete
- Archive, don't delete (unless truly obsolete)
- Git tracks everything anyway
- Historical context valuable for debugging

### 5. When in Doubt
- Procedural content → Numbered docs
- Project work → 08-projects/
- Historical narrative → Keep in completed projects
- Cross-reference liberally

---

## Common Scenarios

### Scenario 1: Running a Backfill

**AI should**:
1. Read `02-operations/backfill/master-guide.md` for procedure
2. Follow current best practices
3. Log execution in active project or handoff
4. Update guide if improvements discovered

**AI should NOT**:
- Create new backfill guide (update existing)
- Follow old project docs as procedure (use numbered docs)

### Scenario 2: Investigating a Bug

**AI should**:
1. Create investigation doc in relevant project
2. Log findings in project or handoff
3. If significant bug, create postmortem in `02-operations/postmortems/`
4. Update troubleshooting guide with solution

**AI should NOT**:
- Create standalone investigation doc in root
- Skip documenting the fix

### Scenario 3: Major Project Completion

**AI should**:
1. Update project README with completion status
2. Extract procedure improvements to numbered docs
3. Create lessons-learned doc if significant insights
4. Add cross-references
5. Move project to completed/

**AI should NOT**:
- Delete project after extracting knowledge
- Leave project in current/ indefinitely

### Scenario 4: Session Handoff

**AI should**:
1. Create dated handoff in `09-handoff/`
2. Link to active projects and relevant docs
3. List next actions clearly
4. Update system status if changed

**AI should NOT**:
- Create handoff in root directory
- Create overly detailed handoff (link to project for details)

---

## Summary

### Remember
1. **Numbered docs** = Current procedures (maintained)
2. **Projects** = Historical narratives (preserved)
3. **Handoffs** = Short-term memory (archived weekly)
4. **Lessons-learned** = Organizational wisdom (accumulated)

### Always
- Cross-reference between tracks
- Follow naming conventions
- Archive, don't delete
- Update indexes when adding content

### Never
- Create duplicate authoritative procedures
- Delete historical context
- Leave completed projects in current/
- Skip cross-referencing

---

**Questions?** See docs/09-handoff/maintenance-playbook.md for operational details.

**Last Updated**: January 6, 2026
