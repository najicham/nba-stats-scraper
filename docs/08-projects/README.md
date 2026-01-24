# Active Projects & Implementation Work

**Last Updated:** 2026-01-24
**Purpose:** Track active implementation work and preserve completed project artifacts

---

## Start Here

| Document | Purpose |
|----------|---------|
| **[CLAUDE-CODE-PROJECT-WORKFLOW.md](./CLAUDE-CODE-PROJECT-WORKFLOW.md)** | How to document work (READ FIRST) |
| **[project-summaries/](./project-summaries/)** | Periodic status snapshots |

---

## Quick Navigation

| What | Where |
|------|-------|
| **Current work** | [current/](./current/) |
| **Project summaries** | [project-summaries/](./project-summaries/) |
| **Completed projects** | [completed/](./completed/) |
| **Completed index** | [completed/README.md](./completed/README.md) |

---

## Directory Structure

```
08-projects/
├── README.md                        # This file
├── CLAUDE-CODE-PROJECT-WORKFLOW.md  # How to document work
├── project-summaries/               # Periodic status snapshots
│   └── YYYY-MM-DD-PROJECT-SUMMARY.md
├── current/                         # Active work (65+ projects)
│   ├── architecture-refactoring-2026-01/
│   ├── code-quality-2026-01/
│   ├── pipeline-reliability-improvements/
│   └── ... (see current/ for full list)
├── completed/                       # Finished projects (20 projects)
│   ├── README.md
│   └── ... (indexed projects)
├── archive/                         # Old/deprecated projects
└── backlog/                         # Future work ideas
```

---

## Current Active Projects

See **[project-summaries/](./project-summaries/)** for detailed status snapshots.

**Key Active Projects (January 2026):**

| Project | Focus | Status |
|---------|-------|--------|
| **architecture-refactoring-2026-01** | Code duplication, large file cleanup | Planning |
| **code-quality-2026-01** | Testing, security, tech debt | In Progress |
| **pipeline-reliability-improvements** | Data pipeline robustness | Stable |
| **live-data-reliability** | Live game data freshness | Phase 1 Complete |
| **email-alerting** | AWS SES, Slack integration | Phases 1-3 Complete |
| **website-ui** | Frontend UI implementation | Ready for Impl |
| **challenge-system-backend** | API fixes for web feature | In Progress |
| **system-evolution** | Post-backfill analysis | Planning |

---

## Summary

| Category | Count |
|----------|-------|
| Active projects | 65+ directories |
| Completed projects | 20 |
| Project summaries | 1+ snapshots |
| Total documentation | 600+ files |

---

## Using This Directory

### For Active Work

When working on a multi-session project:

1. Create a subdirectory in `current/`
2. Add key files:
   - `overview.md` or `README.md` - What is this project?
   - `checklist.md` - Tasks to complete
   - `changelog.md` - What changed (by session)

### When a Project Completes

1. Move the project folder to `completed/`
2. Update `completed/README.md` index
3. Add handoff doc in `09-handoff/` if significant

### Session-Specific Docs

For single-session work or status tracking:
- Add files directly to `current/` (e.g., `SESSION-173-STATUS.md`)
- These don't need full project structure

---

## Related Documentation

- [System Status](../00-start-here/SYSTEM_STATUS.md) - Current operational state
- [Active Handoffs](../09-handoff/) - Session continuity docs
- [Backfill Guide](../02-operations/backfill/) - Data backfill procedures
