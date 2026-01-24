# Documentation Cleanup Implementation Plan

Based on research completed 2026-01-24.

---

## Quick Reference

| Task | Effort | Impact | Priority |
|------|--------|--------|----------|
| Merge validation directories | Medium | High | 1 |
| Merge 03-architecture → 01-architecture | Low | Medium | 2 |
| Delete 03-configuration | Low | Low | 3 |
| Document 07-* purpose differences | Low | Medium | 4 |

---

## Task 1: Merge Validation Directories

**Current State:**
- `docs/validation-framework/` - 10 files, 200KB (framework design)
- `docs/validation/` - 10 files, 156KB (operational reports)

**Target Structure:**
```
docs/validation/
├── README.md                    # Unified index
├── framework/                   # Architecture & design
│   ├── VALIDATION-FRAMEWORK-DESIGN.md
│   ├── IMPLEMENTATION-PLAN.md
│   ├── EXECUTIVE-SUMMARY.md
│   └── ...
├── operational/                 # Daily operations
│   ├── NBA_PRIORITIES_TODO_LIST.md
│   ├── NBA_VALIDATION_TODO_LIST.md
│   └── ...
├── reports/                     # Historical reports
│   ├── JAN_8_15_PREDICTION_PERFORMANCE_REPORT.md
│   └── ...
└── guides/                      # User guides
    ├── VALIDATION-GUIDE.md
    ├── PRACTICAL-USAGE-GUIDE.md
    └── ...
```

**Commands:**
```bash
# Create subdirectories
mkdir -p docs/validation/{framework,operational,reports,guides}

# Move framework files
mv docs/validation-framework/VALIDATION-FRAMEWORK-DESIGN.md docs/validation/framework/
mv docs/validation-framework/IMPLEMENTATION-PLAN.md docs/validation/framework/
mv docs/validation-framework/EXECUTIVE-SUMMARY.md docs/validation/framework/
mv docs/validation-framework/PHASE3-COMPLETION-CHECKLIST.md docs/validation/framework/
mv docs/validation-framework/ULTRATHINK-RECOMMENDATIONS.md docs/validation/framework/

# Move guide files
mv docs/validation-framework/VALIDATION-GUIDE.md docs/validation/guides/
mv docs/validation-framework/PRACTICAL-USAGE-GUIDE.md docs/validation/guides/
mv docs/validation-framework/COMPREHENSIVE-VALIDATION-SCRIPTS-GUIDE.md docs/validation/guides/
mv docs/validation-framework/VALIDATION-COMMANDS-REFERENCE.md docs/validation/guides/

# Move operational files to operational/
mv docs/validation/NBA_PRIORITIES_TODO_LIST.md docs/validation/operational/
mv docs/validation/NBA_VALIDATION_TODO_LIST.md docs/validation/operational/
mv docs/validation/VALIDATION_OPPORTUNITIES.md docs/validation/operational/
mv docs/validation/2026-01-16-OPERATIONAL-FINDINGS.md docs/validation/operational/

# Move reports
mv docs/validation/FINAL_V16_VALIDATION_FINDINGS.md docs/validation/reports/
mv docs/validation/JAN_8_15_PREDICTION_PERFORMANCE_REPORT.md docs/validation/reports/
mv docs/validation/JAN_10_15_COMPREHENSIVE_VALIDATION.md docs/validation/reports/
mv docs/validation/JAN_16_EVENING_VALIDATION_REPORT.md docs/validation/reports/
mv docs/validation/PHASE1_VALIDATION_REPORT.md docs/validation/reports/
mv docs/validation/jan15_data_report.md docs/validation/reports/

# Delete old framework directory
rm -rf docs/validation-framework/

# Create unified README
# (create new README.md with index)
```

---

## Task 2: Merge 03-architecture into 01-architecture

**Current State:**
- `docs/03-architecture/ORCHESTRATION-PATHS.md` - Single file explaining orchestration decision logic

**Action:**
```bash
# Move file
mv docs/03-architecture/ORCHESTRATION-PATHS.md docs/01-architecture/orchestration/decision-paths.md

# Remove empty directory
rm -rf docs/03-architecture/
```

**Post-move:** Update any references (mostly in archived docs, low impact)

---

## Task 3: Delete 03-configuration

**Current State:**
- `docs/03-configuration/notification-rate-limiting.md` - Archived config doc from Dec 2024
- Only referenced in archived handoff docs

**Action:**
```bash
# Archive to archive directory (preserve history)
mv docs/03-configuration/notification-rate-limiting.md docs/archive/2024-12/

# Remove empty directory
rm -rf docs/03-configuration/
```

---

## Task 4: Document 07-* Purpose Differences

**Finding:** The three 07-* directories serve different purposes and audiences. This is intentional, not a conflict.

| Directory | Audience | Content Type |
|-----------|----------|--------------|
| 07-monitoring | Engineers, ops | Dashboards, health checks, queries |
| 07-admin-dashboard | UI users, ops | Web app API reference |
| 07-security | Security team | Audits, compliance, IAM |

**Action:** Add clarifying note to docs README (no file moves needed)

```markdown
### Note on 07-* Directories

The three 07-* directories serve different audiences:
- `07-monitoring/` - System observability (dashboards, health checks)
- `07-admin-dashboard/` - Pipeline UI documentation
- `07-security/` - Security governance and compliance
```

---

## Execution Order

1. **Validation merge** - Biggest impact, consolidates scattered docs
2. **03-architecture merge** - Quick win, 1 file
3. **03-configuration delete** - Quick win, archived content
4. **07-* documentation** - Just add clarifying note

---

## Not Changing

- `03-phases/` - Active, well-organized, 40 files
- `07-monitoring/` - Primary monitoring hub
- `07-admin-dashboard/` - Different purpose, keep separate
- `07-security/` - Different purpose, keep separate

---

**Created:** 2026-01-24
