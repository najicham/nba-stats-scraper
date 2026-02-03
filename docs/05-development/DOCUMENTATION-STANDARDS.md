# Documentation Standards

Standards for creating and maintaining documentation in the NBA Props Platform.

## Document Metadata Format

**All documentation files should include this header:**

```markdown
# Document Title

**File:** `docs/category/document-name.md`
**Created:** YYYY-MM-DD
**Last Updated:** YYYY-MM-DD
**Status:** Current|Draft|Superseded|Archive
```

## Documentation Directory Structure

```
docs/
├── 00-start-here/     # Navigation, status, getting started
├── 01-architecture/   # System design & decisions
├── 02-operations/     # Daily ops, backfills, troubleshooting
├── 03-phases/         # Phase-specific documentation
├── 04-deployment/     # Deployment status & guides
├── 05-development/    # Guides, patterns, testing
├── 06-reference/      # Quick lookups, processor cards
├── 07-monitoring/     # Grafana, alerts, observability
├── 08-projects/       # Active work tracking
├── 09-handoff/        # Session handoffs
└── archive/           # Historical documentation
```

## Where to Put New Documentation

| You're creating... | Put it in... |
|--------------------|--------------|
| Active project/task tracking | `08-projects/current/{project-name}/` |
| Session handoff notes | `09-handoff/` |
| Operational procedures | `02-operations/` |
| Troubleshooting guides | `02-operations/` |
| Phase-specific docs | `03-phases/phase{N}/` |
| How-to guides | `05-development/guides/` |
| Quick reference/lookups | `06-reference/` |
| Monitoring/alerting | `07-monitoring/` |

## Project Documentation

### Starting New Work

When beginning any non-trivial task:
1. Create project directory: `docs/08-projects/current/{topic}/`
2. Create `README.md` with: Goal, Status, Quick Context
3. Create `PROGRESS.md` with: Task checklist, Last Updated date

### Required Files

- `README.md` - Goal, status, quick context for someone new
- `PROGRESS.md` - Task checklist with checkboxes

### Project Lifecycle

**When complete:**
1. Mark all tasks done in `PROGRESS.md`
2. Update `README.md` status to "Complete"
3. Move to `docs/08-projects/completed/`

**Stale projects** (14+ days without update):
- Review and either update, mark as paused, or archive

## Session Handoffs

**Location:** `docs/09-handoff/`

**Naming:** `YYYY-MM-DD-SESSION-N-HANDOFF.md`

**Required content:**
- Summary of work completed
- Current system status
- Clear next steps
- Reference to project directory (if applicable)

**Lifecycle:** Archive after 5 days to `docs/09-handoff/archive/`

## Documentation Types

**Evergreen (update in place):**
- Operations guides
- How-to documentation
- System architecture
- Monitoring guides

**Point-in-Time (archive when superseded):**
- Status reports
- Gap analyses
- Session handoffs
- Implementation plans

## Key Entry Points

| Purpose | Location |
|---------|----------|
| Navigation hub | `docs/00-start-here/README.md` |
| System status | `docs/00-start-here/SYSTEM_STATUS.md` |
| Troubleshooting | `docs/02-operations/troubleshooting-matrix.md` |
| Session learnings | `docs/02-operations/session-learnings.md` |
