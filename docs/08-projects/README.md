# Active Projects & Implementation Work

**Purpose:** Track active implementation work and preserve completed project artifacts

---

## Directory Structure

```
08-projects/
├── current/              # Active work
│   ├── scraper-audit/    # GCS data verification project
│   ├── implementation-plan.md
│   └── pattern-rollout.md
│
└── completed/            # Finished projects (for reference)
    ├── completeness/     # Completeness checking implementation
    ├── smart-idempotency/  # Smart idempotency pattern
    └── dependency-checking/ # Dependency checking pattern
```

---

## Using This Directory

### For Active Work

When working on a multi-session project:

1. Create a subdirectory in `current/`
2. Add key files:
   - `overview.md` - What is this project?
   - `checklist.md` - Tasks to complete
   - `changelog.md` - What changed (by session)

### When a Project Completes

1. Move the project folder to `completed/`
2. Update the handoff docs in `09-handoff/`

---

## Current Active Projects

| Project | Status | Last Updated |
|---------|--------|--------------|
| Scraper Audit | In Progress | 2025-11-25 |
| Pattern Rollout | In Progress | 2025-11-25 |

---

## Completed Projects

| Project | Completed | Description |
|---------|-----------|-------------|
| Completeness Checking | 2025-11-23 | 100% coverage across all phases |
| Smart Idempotency | 2025-11-21 | Hash-based change detection |
| Dependency Checking | 2025-11-20 | Upstream dependency validation |

