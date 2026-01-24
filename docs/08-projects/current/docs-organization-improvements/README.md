# Documentation Organization Improvements

**Status:** Proposed
**Created:** 2026-01-24
**Priority:** Low (cleanup, not blocking)

---

## Goal

Clean up structural inconsistencies in the `/docs` directory to make documentation easier to navigate.

---

## Issues Identified

### 1. Duplicate Numbered Directories

Multiple directories share the same number prefix, creating confusion:

| Prefix | Conflicting Directories |
|--------|------------------------|
| `03-*` | `03-architecture/`, `03-configuration/`, `03-phases/` |
| `06-*` | `06-grading/`, `06-operations/`, `06-reference/` |
| `07-*` | `07-admin-dashboard/`, `07-monitoring/`, `07-operations/`, `07-security/` |

**Impact:** Unclear which is the "official" directory for each number.

### 2. Non-Prefixed Directories

11 directories don't follow the numbered prefix convention:

```
archive/
api/
deployment/
handoffs/
incidents/
lessons-learned/
playbooks/
runbooks/
validation/
validation-framework/
```

**Impact:** Breaks the established hierarchy pattern.

### 3. Scattered Runbooks

Runbooks exist in multiple locations:
- `/docs/runbooks/`
- `/docs/02-operations/runbooks/`

**Impact:** Confusion about authoritative location.

### 4. Duplicate Validation Docs

- `/docs/validation/` (152KB)
- `/docs/validation-framework/` (196KB)

**Impact:** Likely overlapping content.

### 5. Orphaned Directories

Some directories have minimal content or unclear purpose:
- `03-configuration/` - Purpose unclear
- `06-operations/` - Only contains `mlb/` subdirectory
- `07-operations/` - Single file (SCHEDULING-GUIDELINES.md)
- `07-admin-dashboard/` - Disconnected from broader docs

---

## Proposed Fixes

### Quick Wins (Low Risk)

| Action | Description |
|--------|-------------|
| Merge `06-operations/` | Move contents into `02-operations/` |
| Merge `07-operations/` | Move SCHEDULING-GUIDELINES.md to `02-operations/` |
| Consolidate runbooks | Move `/docs/runbooks/` into `02-operations/runbooks/` |
| Merge validation dirs | Combine into single `validation/` or `05-development/validation/` |
| Delete `handoffs/` | Only 1 file, redirect to `09-handoff/` |

### Medium Effort (Some Restructuring)

| Action | Description |
|--------|-------------|
| Rename `03-architecture/` | Already exists as `01-architecture/` - delete if empty |
| Rename `03-configuration/` | Move to `01-architecture/configuration/` or delete |
| Clarify `06-grading/` | Move to `07-monitoring/grading/` |
| Consolidate `07-*` dirs | Keep `07-monitoring/` as primary, nest others |

### Larger Refactor (Optional)

| Action | Description |
|--------|-------------|
| Add `99-misc/` | Home for non-prefixed directories |
| Create directory map | Single source of truth for directory purposes |
| Establish governance | Document when to create vs reuse directories |

---

## Recommended Priority

1. **Do Now:** Merge scattered runbooks and delete empty `handoffs/`
2. **Next Session:** Merge `06-operations/` and `07-operations/` into `02-operations/`
3. **Later:** Address validation directories and orphaned 03-* directories

---

## Files

- `README.md` - This file
- `PROGRESS.md` - Task tracking (when work begins)

---

**Next Step:** Review this proposal and decide which fixes to implement.
