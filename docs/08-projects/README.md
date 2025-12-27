# Active Projects & Implementation Work

**Last Updated:** 2025-12-27
**Purpose:** Track active implementation work and preserve completed project artifacts

---

## Quick Navigation

| What | Where |
|------|-------|
| **Current work** | [current/](./current/) |
| **Completed projects** | [completed/](./completed/) |
| **Completed index** | [completed/README.md](./completed/README.md) |

---

## Directory Structure

```
08-projects/
├── README.md           # This file
├── current/            # Active work (8 projects)
│   ├── 2025-26-season-backfill/
│   ├── challenge-system-backend/
│   ├── email-alerting/
│   ├── four-season-backfill/
│   ├── observability/
│   ├── processor-optimization/
│   ├── system-evolution/
│   └── website-ui/
│
└── completed/          # Finished projects (20 projects)
    ├── README.md       # Full index with descriptions
    ├── phase4-phase5-integration/
    ├── phase-6-publishing/
    ├── frontend-api-backend/
    ├── ai-name-resolution/
    └── ... (16 more)
```

---

## Current Active Projects

| Project | Description | Status | Last Updated |
|---------|-------------|--------|--------------|
| **challenge-system-backend** | Challenge/contest system API design | Design Phase | 2025-12-27 |
| **website-ui** | Frontend UI implementation | In Progress | 2025-12-12 |
| **2025-26-season-backfill** | Current season data completeness | In Progress | 2025-12-17 |
| **four-season-backfill** | Historical seasons (2021-2024) | In Progress | 2025-12-14 |
| **processor-optimization** | Performance improvements | In Progress | 2025-12-09 |
| **system-evolution** | Architecture improvements | In Progress | 2025-12-11 |
| **observability** | Monitoring enhancements | In Progress | 2025-12-06 |
| **email-alerting** | Alert system implementation | In Progress | 2025-11-30 |

---

## Summary

| Category | Count |
|----------|-------|
| Active projects | 8 |
| Completed projects | 20 |
| Total documentation | 110+ files |

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
