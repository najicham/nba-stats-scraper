# Documentation Hygiene Guide

A systematic approach to keeping project documentation organized, summarized, and in sync with the codebase.

## Overview

This guide defines the workflow for:
1. Managing project lifecycle (current → completed → archive)
2. Creating and maintaining project summaries
3. Keeping root documentation up to date
4. Ensuring docs match code reality

---

## Directory Structure

```
docs/08-projects/
├── current/              # Active projects (< 14 days old or actively worked)
├── completed/            # Finished projects (keep 30 days, then archive)
├── archive/              # Historical projects (compressed or summarized)
├── summaries/            # Monthly summaries of completed work
│   ├── 2026-01.md       # January 2026 summary
│   ├── 2026-02.md       # February 2026 summary
│   └── ...
├── DOCUMENTATION-HYGIENE-GUIDE.md  # This file
└── README.md             # Index of projects
```

---

## Project Lifecycle

### Stage 1: Current (`current/`)

**Criteria:**
- Actively being worked on
- Modified in last 14 days
- Ongoing/recurring work (experiments, monitoring)

**Required files:**
- `README.md` - Goal, status, context
- `PROGRESS.md` - Task checklist (optional but recommended)

### Stage 2: Completed (`completed/`)

**When to move:**
- Project goal achieved
- Feature shipped/deployed
- Bug fixed and verified

**Before moving:**
1. Update README.md with final status
2. Extract key learnings to monthly summary
3. Note any follow-up work needed

**Retention:** 30 days, then move to archive

### Stage 3: Archive (`archive/`)

**When to move:**
- 30+ days in completed/
- Historical reference only
- One-time incidents/fixes

**Organization:**
```
archive/
├── 2026-01/           # Group by month
│   ├── catboost-v8-incident/
│   ├── betting-timing-fix/
│   └── ...
├── 2026-02/
└── ...
```

---

## Monthly Summaries

### Purpose

Capture key learnings before projects are archived so knowledge isn't lost.

### Location

`docs/08-projects/summaries/{YYYY-MM}.md`

### Template

```markdown
# {Month Year} Project Summary

## Overview
- Projects completed: X
- Projects archived: Y
- Key themes: [list major areas of work]

## Major Accomplishments

### Bug Fixes
| Issue | Root Cause | Fix | Impact |
|-------|------------|-----|--------|
| ... | ... | ... | ... |

### Features Shipped
| Feature | Description | Files Changed |
|---------|-------------|---------------|
| ... | ... | ... |

### Performance Improvements
| Area | Before | After | How |
|------|--------|-------|-----|
| ... | ... | ... | ... |

## Patterns & Practices Established

### New Patterns
- [Pattern name]: [Description and when to use]

### Anti-Patterns Discovered
- [Anti-pattern]: [Why it's bad and what to do instead]

## Documentation Updates Made

| Doc | Update | Reason |
|-----|--------|--------|
| CLAUDE.md | Added X section | Session Y learning |
| ... | ... | ... |

## Metrics

| Metric | Value |
|--------|-------|
| Sessions this month | X |
| Bugs fixed | Y |
| Features shipped | Z |
| Lines of code changed | ~N |

## Carry-Forward Items

Items that need continued attention:
- [ ] Item 1
- [ ] Item 2

## Projects Archived This Month

| Project | Summary | Key Files |
|---------|---------|-----------|
| project-name | One-line summary | key-file.py |
| ... | ... | ... |
```

---

## Root Documentation Sync

### Documents to Keep Updated

These documents should be reviewed and updated based on project learnings:

| Document | Update Frequency | Sync From |
|----------|------------------|-----------|
| `CLAUDE.md` | After major learnings | Session learnings, bug patterns |
| `docs/02-operations/troubleshooting-matrix.md` | After bug fixes | Project incident reports |
| `docs/02-operations/session-learnings.md` | After bug fixes | Project findings |
| `docs/02-operations/system-features.md` | After features ship | Feature projects |
| `docs/01-architecture/` | After architecture changes | Architecture projects |

### Sync Checklist

When completing a project, check if any of these need updates:

- [ ] **CLAUDE.md** - New essential commands? New gotchas?
- [ ] **troubleshooting-matrix.md** - New error patterns? New fixes?
- [ ] **session-learnings.md** - New bug patterns worth preserving?
- [ ] **system-features.md** - New feature documentation needed?
- [ ] **Architecture docs** - System design changed?
- [ ] **Runbooks** - New operational procedures?

### Validation Against Code

Periodically verify documentation matches code:

1. **Schema docs** - Match BigQuery schemas
2. **API docs** - Match actual endpoints
3. **Configuration docs** - Match actual config files
4. **Command examples** - Actually work when run

---

## Cleanup Workflow

### Weekly (15 min)

1. Review `current/` for projects > 14 days old
2. Move completed projects to `completed/`
3. Check if any summaries need updating

### Monthly (1 hour)

1. Create/update monthly summary
2. Move `completed/` items > 30 days to `archive/`
3. Review and update root documentation
4. Validate key docs against code

### Quarterly (2 hours)

1. Review all root documentation for accuracy
2. Archive old monthly summaries (> 6 months)
3. Clean up duplicate/outdated docs
4. Update documentation index

---

## Classification Rules

### Move to ARCHIVE

- Last modified > 30 days ago AND in completed/
- One-time incidents/fixes that are resolved
- Date-prefixed directories from past months
- Projects with "COMPLETE" or "DONE" in README status

### Move to COMPLETED

- Project goal was achieved
- Feature was shipped/deployed
- Bug was fixed and verified
- Has completion indicators in README

### Keep in CURRENT

- Modified in last 14 days
- Ongoing/recurring projects (experiments, monitoring)
- Multi-phase projects still in progress
- Active investigation or development

### Standalone .md Files

- If related to a project → move into project directory
- If operational doc → move to `docs/02-operations/`
- If architecture doc → move to `docs/01-architecture/`
- If obsolete → archive with note

---

## Anti-Patterns to Avoid

1. **Project graveyards** - Don't let 100+ projects accumulate in current/
2. **Lost knowledge** - Always summarize before archiving
3. **Stale docs** - Update root docs when patterns change
4. **Orphan files** - Don't leave standalone .md files scattered
5. **No lifecycle** - Every project should eventually complete or be explicitly paused

---

## Automation Opportunities

Consider creating these tools:

1. **`/cleanup-projects` skill** - Weekly project hygiene
2. **Project age report** - List projects by age
3. **Doc freshness check** - Flag docs not updated in 30+ days
4. **Code-doc sync validator** - Check if docs match code

---

## Quick Reference

### Commands

```bash
# List projects by age
ls -lt docs/08-projects/current/ | head -20

# Find projects older than 14 days
find docs/08-projects/current -maxdepth 1 -type d -mtime +14

# Count standalone files
find docs/08-projects/current -maxdepth 1 -type f -name "*.md" | wc -l

# Move project to completed
mv docs/08-projects/current/project-name docs/08-projects/completed/

# Move to monthly archive
mkdir -p docs/08-projects/archive/2026-02
mv docs/08-projects/completed/project-name docs/08-projects/archive/2026-02/
```

### Status Indicators

Use these in README.md Status field:
- `Active` - Currently being worked on
- `On Hold` - Paused, will resume
- `Complete` - Finished, ready to archive
- `Abandoned` - Not continuing, archive immediately
