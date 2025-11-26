# Documentation Reorganization - Migration Guide

**Date:** 2025-11-15
**Purpose:** Record of major documentation reorganization from single orchestration/ directory to 5 focused directories
**Status:** Complete
**Impact:** All operational documentation reorganized for better discoverability

---

## Summary

Reorganized NBA Stats Scraper documentation from a mixed `orchestration/` directory into 5 focused directories with clear purposes:

**Before:** `orchestration/` contained Phase 1, Phase 2, Pub/Sub, and monitoring docs (9 files mixed together)

**After:**
- `orchestration/` - Phase 1 scheduler only (4 files)
- `infrastructure/` - Pub/Sub cross-phase (2 files)
- `processors/` - Phase 2+ operations (1 file, room for growth)
- `monitoring/` - Grafana observability (2 files)
- `data-flow/` - Data mappings placeholder

---

## Motivation

### Problems with Old Structure

1. **Confusing scope** - "Orchestration" directory contained:
   - Phase 1 scheduler docs ✅
   - Phase 2 processor docs ❌ (not orchestration)
   - Pub/Sub infrastructure ❌ (cross-phase, not Phase 1)
   - Monitoring docs ❌ (cross-phase)

2. **Poor scalability** - Where would Phase 3, 4, 5 docs go?

3. **Unclear discovery** - Engineers couldn't easily find docs

### Solution

Clear separation by **purpose**:
- `orchestration/` = Phase 1 time-based scheduling
- `infrastructure/` = Cross-phase shared services
- `processors/` = All processor operations (Phase 2-5)
- `monitoring/` = Cross-phase observability
- `data-flow/` = Data transformation mappings

---

## File Migrations

### From orchestration/ → processors/

| Old Path | New Path | Reason |
|----------|----------|--------|
| `orchestration/03-phase2-operations-guide.md` | `processors/01-phase2-operations-guide.md` | Phase 2 processor operations |

### From orchestration/ → infrastructure/

| Old Path | New Path | Reason |
|----------|----------|--------|
| `orchestration/06-pubsub-integration-verification-guide.md` | `infrastructure/01-pubsub-integration-verification.md` | Cross-phase Pub/Sub |
| `orchestration/07-pubsub-schema-management.md` | `infrastructure/02-pubsub-schema-management.md` | Cross-phase schemas |

### From orchestration/ → monitoring/

| Old Path | New Path | Reason |
|----------|----------|--------|
| `orchestration/04-grafana-monitoring-guide.md` | `monitoring/01-grafana-monitoring-guide.md` | Cross-phase monitoring |
| `orchestration/05-grafana-daily-health-check-guide.md` | `monitoring/02-grafana-daily-health-check.md` | Cross-phase health checks |

### Renumbered in orchestration/

| Old Path | New Path | Reason |
|----------|----------|--------|
| `orchestration/08-phase1-bigquery-schemas.md` | `orchestration/03-bigquery-schemas.md` | Fill gap after moves |
| `orchestration/09-phase1-troubleshooting.md` | `orchestration/04-troubleshooting.md` | Fill gap after moves |

### Stayed in orchestration/

| Path | Reason |
|------|--------|
| `orchestration/01-how-it-works.md` | Phase 1 overview |
| `orchestration/02-phase1-overview.md` | Phase 1 architecture |

---

## New Directory Structure

```
docs/
├── architecture/          # Design, planning, future vision
│   ├── README.md
│   ├── 00-quick-reference.md
│   ├── 01-phase1-to-phase5-integration-plan.md
│   ├── 04-event-driven-pipeline-architecture.md
│   └── 05-implementation-status-and-roadmap.md
│
├── orchestration/         # Phase 1: Scheduler & daily workflows
│   ├── README.md         # ✅ Updated
│   ├── 01-how-it-works.md
│   ├── 02-phase1-overview.md
│   ├── 03-bigquery-schemas.md         # Renumbered from 08
│   └── 04-troubleshooting.md          # Renumbered from 09
│
├── infrastructure/        # 🆕 Cross-phase: Pub/Sub, shared services
│   ├── README.md         # ✅ Created
│   ├── 01-pubsub-integration-verification.md
│   └── 02-pubsub-schema-management.md
│
├── processors/            # 🆕 Phase 2+: Data processor operations
│   ├── README.md         # ✅ Created
│   └── 01-phase2-operations-guide.md
│
├── monitoring/            # 🆕 Cross-phase: Grafana, observability
│   ├── README.md         # ✅ Created
│   ├── 01-grafana-monitoring-guide.md
│   └── 02-grafana-daily-health-check.md
│
└── data-flow/            # 🆕 Phase-to-phase data mappings
    └── README.md         # ✅ Created (placeholder)
```

---

## Changes Made

### 1. Directory Creation
```bash
mkdir -p docs/infrastructure/archive
mkdir -p docs/processors/archive
mkdir -p docs/monitoring/archive
mkdir -p docs/data-flow/archive
```

### 2. File Moves
```bash
mv orchestration/03-phase2-operations-guide.md processors/01-phase2-operations-guide.md
mv orchestration/06-pubsub-integration-verification-guide.md infrastructure/01-pubsub-integration-verification.md
mv orchestration/07-pubsub-schema-management.md infrastructure/02-pubsub-schema-management.md
mv orchestration/04-grafana-monitoring-guide.md monitoring/01-grafana-monitoring-guide.md
mv orchestration/05-grafana-daily-health-check-guide.md monitoring/02-grafana-daily-health-check.md
```

### 3. File Renumbering
```bash
mv orchestration/08-phase1-bigquery-schemas.md orchestration/03-bigquery-schemas.md
mv orchestration/09-phase1-troubleshooting.md orchestration/04-troubleshooting.md
```

### 4. Metadata Updates

Updated file metadata headers in all moved/renumbered files:
- Updated `**File:**` path to new location
- Updated `**Last Updated:**` to 2025-11-15
- Added note about move/renumber

### 5. README Creation

Created comprehensive README.md for each new directory:
- `infrastructure/README.md` - Pub/Sub and shared services guide
- `processors/README.md` - Phase 2+ processor operations guide
- `monitoring/README.md` - Observability and health checks guide
- `data-flow/README.md` - Data mapping placeholder

Updated existing README:
- `orchestration/README.md` - Focused on Phase 1 only, added cross-references

### 6. Cross-Reference Updates

Updated references in:
- `docs/architecture/00-quick-reference.md`
- `docs/architecture/01-phase1-to-phase5-integration-plan.md`
- `docs/architecture/03-pipeline-monitoring-and-error-handling.md`
- `.claude/claude_project_instructions.md` - Major update to Documentation References section

### 7. Documentation Guide Creation

Created `docs/DOCS_DIRECTORY_STRUCTURE.md`:
- Comprehensive guide for directory organization
- Decision tree for "where does X go?"
- Complements existing `DOCUMENTATION_GUIDE.md` (file organization within directories)

---

## Breaking Changes

### ⚠️ Path Changes

**Old paths no longer work:**
```
docs/orchestration/03-phase2-operations-guide.md
docs/orchestration/04-grafana-monitoring-guide.md
docs/orchestration/05-grafana-daily-health-check-guide.md
docs/orchestration/06-pubsub-integration-verification-guide.md
docs/orchestration/07-pubsub-schema-management.md
docs/orchestration/08-phase1-bigquery-schemas.md
docs/orchestration/09-phase1-troubleshooting.md
```

**New paths:**
```
docs/processors/01-phase2-operations-guide.md
docs/monitoring/01-grafana-monitoring-guide.md
docs/monitoring/02-grafana-daily-health-check.md
docs/infrastructure/01-pubsub-integration-verification.md
docs/infrastructure/02-pubsub-schema-management.md
docs/orchestration/03-bigquery-schemas.md
docs/orchestration/04-troubleshooting.md
```

### 🔧 Mitigation

All known cross-references have been updated in:
- Architecture docs
- Claude project instructions
- README files

External bookmarks/links need manual update.

---

## Verification Checklist

**Completed:**
- [x] Create new directories with archive/ subdirectories
- [x] Move files to new locations
- [x] Renumber remaining orchestration files
- [x] Update file metadata headers
- [x] Create README.md for each new directory
- [x] Update orchestration/README.md
- [x] Update cross-references in architecture docs
- [x] Update Claude project instructions
- [x] Create DOCS_DIRECTORY_STRUCTURE.md guide
- [x] Create this migration document

**To verify:**
- [ ] All docs findable via directory READMEs
- [ ] No broken links in documentation
- [ ] Claude project instructions accurate

---

## How to Find Documents Now

### Quick Reference

**"Where is the Phase 2 operations guide?"**
→ `docs/processors/01-phase2-operations-guide.md`

**"Where is the Grafana monitoring guide?"**
→ `docs/monitoring/01-grafana-monitoring-guide.md`

**"Where is the Pub/Sub verification guide?"**
→ `docs/infrastructure/01-pubsub-integration-verification.md`

**"Where is the Phase 1 troubleshooting guide?"**
→ `docs/orchestration/04-troubleshooting.md`

### Decision Tree

Use `docs/DOCS_DIRECTORY_STRUCTURE.md` decision tree:

```
I have documentation to add/find. What is it about?

├─ System Design & Future Plans → architecture/
├─ Phase 1 Scheduler & Workflows → orchestration/
├─ Cross-Phase Infrastructure → infrastructure/
├─ Phase 2+ Processor Operations → processors/
├─ Monitoring & Observability → monitoring/
└─ Data Transformations & Mappings → data-flow/
```

---

## Future Additions

### Processors Directory (Ready for Growth)

When Phase 3, 4, 5 are deployed, add here:
- `02-phase3-analytics-guide.md`
- `03-phase4-precompute-guide.md`
- `04-phase5-predictions-guide.md`

### Data Flow Directory (Awaiting Content)

When data mapping docs are ready:
- `01-phase1-to-phase2-mapping.md` - Scraper JSON → Raw tables
- `02-phase2-to-phase3-mapping.md` - Raw → Analytics
- `03-phase3-to-phase4-mapping.md` - Analytics → Precompute
- `04-phase4-to-phase5-mapping.md` - Precompute → Predictions
- `05-phase5-to-phase6-mapping.md` - Predictions → API
- `99-end-to-end-example.md` - Full trace through pipeline

---

## Lessons Learned

### What Worked Well

1. **Clear purpose per directory** - No ambiguity about where docs go
2. **Chronological numbering** - Easy to add new docs without renaming
3. **Comprehensive READMEs** - Each directory self-documents its purpose
4. **Archive pattern** - Clean directories, preserved history

### What to Watch

1. **Cross-references** - Need to maintain as docs move
2. **External links** - Can't control bookmarks, but documented clearly
3. **Numbering gaps** - Acceptable (README provides reading order)

### Recommendations

1. **Always update READMEs** when adding docs
2. **Use DOCS_DIRECTORY_STRUCTURE.md** to decide placement
3. **Reference this migration doc** for historical context
4. **Archive old docs** rather than deleting

---

## Related Documentation

- **Directory Organization:** `docs/DOCS_DIRECTORY_STRUCTURE.md`
- **File Organization:** `docs/DOCUMENTATION_GUIDE.md`
- **Project Instructions:** `.claude/claude_project_instructions.md`

---

## Contact & Questions

For questions about this reorganization or where to place new docs:
1. Check `docs/DOCS_DIRECTORY_STRUCTURE.md` decision tree
2. Look at similar existing docs for examples
3. When in doubt, ask in project discussions

---

**Migration Status:** ✅ Complete
**Date Completed:** 2025-11-15
**Files Moved:** 5
**Files Renumbered:** 2
**New Directories:** 4
**READMEs Created:** 5
**Impact:** Improved documentation discoverability and scalability
