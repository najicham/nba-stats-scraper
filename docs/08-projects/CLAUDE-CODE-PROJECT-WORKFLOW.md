# Claude Code Project Documentation Workflow

> **READ THIS FIRST** - This file explains how to document work in this repository.

---

## Quick Start for New Sessions

1. **Check for existing project**: Look in `current/` for a related subdirectory
2. **If project exists**: Add your docs there, update PROGRESS.md
3. **If new work**: Create a subdirectory in `current/` with format `{topic}-{YYYY-MM}`

---

## Common Commands

| User Says | What To Do |
|-----------|------------|
| "Keep project docs updated" | Update PROGRESS.md and README.md in relevant `current/{project}/` |
| "Update the project summary" | Create new file in `project-summaries/YYYY-MM-DD-PROJECT-SUMMARY.md` |
| "Archive old handoffs" | Move files >5 days old from `09-handoff/` to `09-handoff/archive/` |
| "What are we working on?" | Check `project-summaries/` for latest summary, or scan `current/` |

---

## Directory Structure

```
docs/08-projects/
├── CLAUDE-CODE-PROJECT-WORKFLOW.md  # THIS FILE - read first
├── README.md                         # Overview and navigation
├── current/                          # Active projects (ADD WORK HERE)
│   ├── {project-name}/              # Multi-session project folders
│   └── {single-doc}.md              # One-off session docs
├── completed/                        # Finished projects
├── archive/                          # Old/deprecated projects
└── backlog/                          # Future work ideas
```

---

## When to Create a Project Subdirectory

**Create a subdirectory when:**
- Work spans multiple sessions
- Multiple related documents needed
- Feature/initiative with distinct scope
- Bug investigation requiring tracking

**Use a single file when:**
- Quick session-specific status
- One-off investigation
- Simple task completion notes

---

## Project Subdirectory Structure

For multi-session work, create in `current/`:

```
current/{topic}-{YYYY-MM}/
├── README.md          # REQUIRED: Project overview, goals, quick nav
├── PROGRESS.md        # REQUIRED: Status tracking, what's done/pending
├── CHANGELOG.md       # Optional: Session-by-session changes
└── {topic-docs}.md    # Technical documentation as needed
```

### Required Files

**README.md** - Must include:
```markdown
# {Project Name}

## Goal
{1-2 sentences on what this project achieves}

## Status
{Current state: Planning | In Progress | Testing | Complete}

## Key Files
- `PROGRESS.md` - Current progress
- `{other-key-files}` - Brief description

## Quick Context
{2-3 bullet points for someone new picking this up}
```

**PROGRESS.md** - Must include:
```markdown
# Progress Tracker

## Status: {In Progress | Blocked | Complete}

## Completed
- [x] Task 1
- [x] Task 2

## In Progress
- [ ] Current task

## Pending
- [ ] Future task

## Last Updated: {YYYY-MM-DD}
```

---

## Naming Conventions

### Project Directories
Format: `{descriptive-name}-{YYYY-MM}` or `{descriptive-name}`

Good examples:
- `code-quality-2026-01`
- `architecture-refactoring-2026-01`
- `pipeline-reliability-improvements`
- `historical-backfill-audit`

Avoid:
- `session-123-work` (use descriptive names)
- `misc-fixes` (too vague)
- `january-stuff` (not descriptive)

### File Names
- Use UPPERCASE-KEBAB-CASE for markdown: `PROGRESS.md`, `IMPLEMENTATION-PLAN.md`
- Date prefix for session docs: `2026-01-24-SESSION-SUMMARY.md`
- Be specific: `RATE-LIMITING-IMPLEMENTATION.md` not `feature.md`

---

## Workflow Examples

### Starting New Feature Work
```bash
# 1. Create project directory
mkdir -p docs/08-projects/current/new-feature-2026-01

# 2. Create README.md with goals and context
# 3. Create PROGRESS.md with task checklist
# 4. Begin work, update PROGRESS.md each session
```

### Continuing Existing Project
```bash
# 1. Find relevant project in current/
ls docs/08-projects/current/

# 2. Read README.md for context
# 3. Read PROGRESS.md for current state
# 4. Update PROGRESS.md as you work
```

### Completing a Project
```bash
# 1. Mark all tasks complete in PROGRESS.md
# 2. Update README.md status to "Complete"
# 3. Move to completed/:
mv docs/08-projects/current/{project} docs/08-projects/completed/
# 4. Update docs/08-projects/completed/README.md index
```

---

---

## End-of-Session Checklist

Before ending a session:

- [ ] **Update PROGRESS.md** - Mark completed tasks, add new tasks discovered
- [ ] **Update README.md** - Change status if needed (Planning → In Progress → Complete)
- [ ] **Update "Last Updated" date** in both files
- [ ] **Create handoff** in `docs/09-handoff/` if significant work was done

---

## Project Lifecycle

### Active → Complete

When a project finishes:

```bash
# 1. Update project docs
# Mark all tasks complete in PROGRESS.md
# Set status to "Complete" in README.md

# 2. Move to completed
mv docs/08-projects/current/{project} docs/08-projects/completed/

# 3. Update completed index
# Add entry to docs/08-projects/completed/README.md
```

### Stale Projects

Projects not updated in 14+ days should be reviewed:
- **Still active?** → Update PROGRESS.md with current status
- **Paused?** → Add note to README.md explaining why
- **Abandoned?** → Move to `archive/`

---

## Weekly Summary

Create a new project summary every 1-2 weeks in `project-summaries/`:
- File: `YYYY-MM-DD-PROJECT-SUMMARY.md`
- Include: Active projects, timelines, key metrics, focus areas

---

## Related Documentation

- **Handoff docs**: `/docs/09-handoff/` - Session continuity, archived after 5 days
- **Project summaries**: `/docs/08-projects/project-summaries/` - Periodic status snapshots
- **Operational docs**: `/docs/02-operations/` - Procedures and runbooks
- **Architecture docs**: `/docs/01-architecture/` - System design decisions

---

**Last Updated:** 2026-01-24
