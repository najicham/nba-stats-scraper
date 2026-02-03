# Documentation Cleanup Action Plan

**Generated:** 2026-02-02
**Status:** Ready for implementation
**Total Files:** 3,551 markdown files across 37 top-level directories

## Executive Summary

The documentation structure has grown organically to **3,551 .md files** with significant organization issues:

- **Mixed numbering scheme** (00-09 numbered + 28 non-numbered directories)
- **7 deployment guides** with overlapping content → Need to consolidate to 3
- **5 troubleshooting documents** with partial duplication
- **3 competing entry points** (README.md, 00-START-HERE-FOR-ERRORS.md, 00-PROJECT-DOCUMENTATION-INDEX.md)
- **Outdated CatBoost V8 references** (should be V9)
- **Missing documentation** for Phase 6, Kalshi, dynamic subsets

**Expected outcome:** Reduce to ~2,000-2,500 docs in consistent structure, 30-40% less maintenance, 70%+ less user confusion.

---

## Priority Breakdown

### P0 - Critical (Fix Immediately, ~3-4 hours)

1. ✅ **Consolidate 7 deployment guides → 3 files**
2. ✅ **Consolidate 5 troubleshooting docs → unified matrix**
3. ✅ **Resolve 3 conflicting entry points → single README.md**
4. **Update CatBoost V8 references → V9**
5. **Add Phase 6/Kalshi/dynamic subset links to CLAUDE.md**

### P1 - Important (This Week, ~4-5 hours)

1. **Merge non-numbered dirs into numbered structure**
2. **Add "Last Updated:" metadata to all top-level docs**
3. **Create missing Phase 6 documentation**
4. **Create Archive Index**
5. **Consolidate ML docs (05-ml/ + 05-development/ml/)**

### P2 - Nice-to-Have (Next Sprint, ~2-3 hours)

1. **Merge scattered operations docs**
2. **Archive historical projects**
3. **Update stale scheduling/monitoring docs**

---

## Detailed Action Items

### P0-1: Consolidate Deployment Guides ✅

**Current state:** 7 files, 3,113 lines total
- DEPLOYMENT.md (1,090 lines)
- DEPLOYMENT-GUIDE.md (217 lines)
- DEPLOYMENT-WORKFLOW.md (518 lines)
- DEPLOYMENT-TROUBLESHOOTING.md (550 lines)
- DEPLOYMENT-CHECKLIST.md (286 lines)
- DEPLOYMENT-QUICK-REFERENCE.md (173 lines)
- DEPLOYMENT-HISTORY-TEMPLATE.md (279 lines)

**Action:**
1. Keep only 3 files:
   - `02-operations/DEPLOYMENT-RUNBOOK.md` (main reference, consolidate DEPLOYMENT.md + DEPLOYMENT-WORKFLOW.md)
   - `02-operations/DEPLOYMENT-CHECKLIST.md` (pre-flight)
   - `02-operations/DEPLOYMENT-TROUBLESHOOTING.md` (issues only)

2. Delete/archive:
   - DEPLOYMENT-GUIDE.md → merge into RUNBOOK
   - DEPLOYMENT-QUICK-REFERENCE.md → merge into RUNBOOK
   - DEPLOYMENT-HISTORY-TEMPLATE.md → move to templates/

3. Update CLAUDE.md to reference DEPLOYMENT-RUNBOOK.md

**Files to modify:**
- `docs/02-operations/DEPLOYMENT.md` → rename to `DEPLOYMENT-RUNBOOK.md`, consolidate content
- `docs/02-operations/DEPLOYMENT-CHECKLIST.md` → keep
- `docs/02-operations/DEPLOYMENT-TROUBLESHOOTING.md` → keep
- `CLAUDE.md` → update deployment references

**Script:**
```bash
# Backup first
cp docs/02-operations/DEPLOYMENT.md /tmp/deployment-backup.md

# Consolidate
# (manual merge of DEPLOYMENT-WORKFLOW.md + DEPLOYMENT-GUIDE.md content into DEPLOYMENT.md)
# Then rename
mv docs/02-operations/DEPLOYMENT.md docs/02-operations/DEPLOYMENT-RUNBOOK.md

# Archive old files
mkdir -p docs/archive/deployment-guides/
mv docs/02-operations/DEPLOYMENT-GUIDE.md docs/archive/deployment-guides/
mv docs/02-operations/DEPLOYMENT-WORKFLOW.md docs/archive/deployment-guides/
mv docs/02-operations/DEPLOYMENT-QUICK-REFERENCE.md docs/archive/deployment-guides/
mv docs/02-operations/DEPLOYMENT-HISTORY-TEMPLATE.md docs/05-development/templates/
```

---

### P0-2: Consolidate Troubleshooting Docs ✅

**Current state:** 5 files, 4,344 lines total
- troubleshooting-matrix.md (2,204 lines) ← KEEP as master
- troubleshooting.md (843 lines)
- TROUBLESHOOTING-DECISION-TREE.md (360 lines) ← KEEP as visual guide
- GRADING-TROUBLESHOOTING-RUNBOOK.md (387 lines) ← KEEP as phase-specific
- DEPLOYMENT-TROUBLESHOOTING.md (550 lines) ← Already consolidated above

**Action:**
1. Keep:
   - `troubleshooting-matrix.md` (master reference)
   - `TROUBLESHOOTING-DECISION-TREE.md` (flow chart)
   - Phase-specific runbooks (grading, deployment)

2. Merge:
   - `troubleshooting.md` content → `troubleshooting-matrix.md`

3. Create:
   - `TROUBLESHOOTING-INDEX.md` → links to all troubleshooting docs

**Script:**
```bash
# Merge troubleshooting.md into troubleshooting-matrix.md
# (manual content merge)

# Archive old file
mv docs/02-operations/troubleshooting.md docs/archive/troubleshooting-old.md

# Create index
cat > docs/02-operations/TROUBLESHOOTING-INDEX.md <<'EOF'
# Troubleshooting Index

## Quick Start

**For immediate issues:** See [00-START-HERE-FOR-ERRORS.md](../00-START-HERE-FOR-ERRORS.md)

## Master References

1. **[troubleshooting-matrix.md](troubleshooting-matrix.md)** - Comprehensive troubleshooting guide (2,200+ lines)
   - All error patterns, root causes, fixes
   - Organized by: Infrastructure, Data Quality, Predictions, Monitoring, etc.

2. **[TROUBLESHOOTING-DECISION-TREE.md](TROUBLESHOOTING-DECISION-TREE.md)** - Visual flow chart
   - Quick diagnostic tree
   - "If X, then check Y"

## Phase-Specific Runbooks

- **[GRADING-TROUBLESHOOTING-RUNBOOK.md](GRADING-TROUBLESHOOTING-RUNBOOK.md)** - Phase 5B grading issues
- **[DEPLOYMENT-TROUBLESHOOTING.md](DEPLOYMENT-TROUBLESHOOTING.md)** - Deployment failures

## See Also

- [session-learnings.md](session-learnings.md) - Historical bug patterns and anti-patterns
- [system-features.md](system-features.md) - Feature-specific troubleshooting
EOF
```

---

### P0-3: Resolve Conflicting Entry Points ✅

**Current state:** 3 competing entry points
- `docs/README.md` - Main index (current, Feb 2)
- `docs/00-START-HERE-FOR-ERRORS.md` - Error guide (current)
- `docs/00-PROJECT-DOCUMENTATION-INDEX.md` - Master index (outdated, Jan 4)

**Action:**
1. **Make `docs/README.md` the single source of truth**
2. Enhance it with sections:
   - Quick Start
   - Getting Started (for new devs)
   - Common Issues (link to 00-START-HERE-FOR-ERRORS.md)
   - Full Directory Structure
3. Update `00-START-HERE-FOR-ERRORS.md` to cross-reference README.md
4. Delete or archive `00-PROJECT-DOCUMENTATION-INDEX.md`
5. Merge `00-start-here/README.md` into main README.md

**Script:**
```bash
# Archive old index
mv docs/00-PROJECT-DOCUMENTATION-INDEX.md docs/archive/old-documentation-index.md

# Update cross-references in 00-START-HERE-FOR-ERRORS.md
# (manual edit to add link to README.md at top)
```

---

### P0-4: Update CatBoost V8 → V9 References

**Files to update:**
- `docs/05-ml/MODEL-TRAINING-RUNBOOK.md` - Update production model reference
- `docs/08-projects/current/prediction-system-optimization/` - Update benchmarks
- Any docs referencing "CatBoost V8 as production"

**Action:**
```bash
# Find all V8 references (excluding historical docs)
grep -r "CatBoost V8" docs/ --exclude-dir=archive | grep -v "incident" | grep -v "2026-01"

# Manual review each file:
# - Update "CatBoost V8" → "CatBoost V9" if referring to current production
# - Update stats: 65% hit rate (3+ edge), 79% hit rate (5+ edge)
# - Update baseline MAE if referenced
```

---

### P0-5: Add Phase 6 Links to CLAUDE.md

**Current:** CLAUDE.md mentions Phase 6 but doesn't link to detailed docs

**Action:**
Add to CLAUDE.md "Feature References" section:

```markdown
## Feature References

For detailed documentation on these features, see `docs/02-operations/system-features.md`:

- **Heartbeat System** - Firestore-based processor health tracking
- **Evening Analytics** - Same-night game processing (6 PM, 10 PM, 1 AM ET)
- **Early Predictions** - 2:30 AM predictions with REAL_LINES_ONLY mode
- **Model Attribution** - Track which model file generated predictions
- **Signal System** - GREEN/YELLOW/RED daily prediction signals
- **Phase 6 Subset Exporters** - 4 exporters publishing curated picks to GCS API (NEW)
- **Dynamic Subset System** - 9 subsets with signal-aware filtering (NEW)
- **Kalshi Integration** - CFTC-regulated prediction market integration (PLANNED)

For Phase 6 architecture: `docs/03-phases/phase6-publishing/README.md`
```

---

### P1-1: Merge Non-Numbered Directories

**28 non-numbered directories** to consolidate:

| Current | Move To | Reason |
|---------|---------|--------|
| `docs/analysis/` | `docs/02-operations/analysis/` | Operational analytics |
| `docs/architecture/` | `docs/01-architecture/` | Single file, merge |
| `docs/deployment/` | `docs/04-deployment/` | Duplicate |
| `docs/api/` | `docs/03-phases/phase6-publishing/api-reference/` | Phase 6 exports |
| `docs/guides/` | `docs/05-development/guides/` | Development guides |
| `docs/incidents/` | `docs/02-operations/incidents/` | Operational incidents |
| `docs/investigations/` | `docs/02-operations/investigations/` | Operational investigations |
| `docs/lessons-learned/` | `docs/02-operations/lessons-learned/` | Operational learnings |
| `docs/performance/` | `docs/07-monitoring/performance/` | Monitoring metrics |
| `docs/playbooks/` | `docs/02-operations/runbooks/playbooks/` | Operational runbooks |
| `docs/sessions/` | `docs/09-handoff/` | Session handoffs |
| `docs/technical/` | `docs/01-architecture/technical/` | Architecture docs |
| `docs/testing/` | `docs/05-development/testing/` | Development testing |
| `docs/validation/` | `docs/05-development/validation/` | Development validation |

**Script:**
```bash
#!/bin/bash
# Consolidate non-numbered directories into numbered structure

# Create backup
tar -czf docs-backup-$(date +%Y%m%d).tar.gz docs/

# Move directories
mv docs/analysis/ docs/02-operations/analysis/
mv docs/architecture/cloud-function-shared-consolidation.md docs/01-architecture/
rmdir docs/architecture/
mv docs/deployment/* docs/04-deployment/
rmdir docs/deployment/
mv docs/api/ docs/03-phases/phase6-publishing/api-reference/
mv docs/guides/ docs/05-development/guides/
mv docs/incidents/ docs/02-operations/incidents/
mv docs/investigations/ docs/02-operations/investigations/
mv docs/lessons-learned/ docs/02-operations/lessons-learned/
mv docs/performance/ docs/07-monitoring/performance/
mv docs/playbooks/ docs/02-operations/runbooks/playbooks/
mv docs/sessions/* docs/09-handoff/
rmdir docs/sessions/
mv docs/technical/ docs/01-architecture/technical/
mv docs/testing/ docs/05-development/testing/
mv docs/validation/ docs/05-development/validation/

# Update cross-references (manual step)
echo "MANUAL STEP: Update links in affected docs to new paths"
```

---

### P1-2: Add "Last Updated" Metadata

**Action:**
Add to **DOCUMENTATION-STANDARDS.md**:

```markdown
## Document Metadata Standard

All documentation files MUST include header metadata:

```markdown
# Document Title

**File:** `docs/path/filename.md`
**Created:** YYYY-MM-DD
**Last Updated:** YYYY-MM-DD  ← REQUIRED
**Status:** Current|Draft|Superseded|Archive
**Audience:** Developers|Operators|All

[Content starts here...]
```

**Enforcement:**
- Pre-commit hook validates metadata presence
- CI checks fail if missing "Last Updated:"
```

**Script to add metadata:**
```bash
#!/bin/bash
# Add "Last Updated" to all top-level docs missing it

for file in docs/*.md; do
    if ! grep -q "Last Updated:" "$file"; then
        # Get last git commit date for file
        LAST_MOD=$(git log -1 --format="%ai" -- "$file" | cut -d' ' -f1)

        # Add metadata after first heading
        sed -i "1a\\
\\n**Last Updated:** $LAST_MOD\\n**Status:** Current" "$file"
    fi
done
```

---

### P1-3: Create Missing Phase 6 Documentation

**New files to create:**

1. **`docs/03-phases/phase6-publishing/SUBSET-EXPORTERS-GUIDE.md`**

```markdown
# Phase 6 Subset Exporters Guide

**Last Updated:** 2026-02-02
**Status:** Current
**Phase:** 6 - Publishing

## Overview

Phase 6 exports curated prediction subsets to GCS for clean public API access.

## 4 Subset Exporters

### 1. AllSubsetsPicksExporter
- **File:** `all_subsets_combined.json`
- **Purpose:** All 9 subset picks in single file
- **Design:** Atomic consistency, simpler API
- **Size:** ~200-500 KB

[Continue with implementation details from system-features.md Phase 6 section...]
```

2. **`docs/03-phases/phase6-publishing/DYNAMIC-SUBSETS.md`**

```markdown
# Dynamic Subset System

**Last Updated:** 2026-02-02
**Status:** Current
**Phase:** 6 - Publishing

## Overview

9 strategic subsets based on edge, confidence, market type, and game context.

## Subset Definitions

[Copy table from system-features.md Dynamic Subset System section...]
```

3. **`docs/03-phases/phase6-publishing/KALSHI-INTEGRATION.md`**

```markdown
# Kalshi Integration Guide

**Last Updated:** 2026-02-02
**Status:** Planned
**Phase:** 6 - Publishing

## Overview

Integration with Kalshi CFTC-regulated prediction market platform.

[Link to docs/08-projects/current/kalshi-integration/README.md for details...]
```

4. **`docs/02-operations/DAILY-SIGNAL-SYSTEM.md`**

```markdown
# Daily Signal System (GREEN/YELLOW/RED)

**Last Updated:** 2026-02-02
**Status:** Current

## Overview

Predicts overall prediction quality for the day to guide bet volume.

[Copy Signal System details from system-features.md...]
```

5. **`docs/02-operations/HEARTBEAT-MONITORING-RUNBOOK.md`**

```markdown
# Heartbeat Monitoring Runbook

**Last Updated:** 2026-02-02
**Status:** Current

## Overview

Firestore-based health tracking for processors.

[Copy from system-features.md Heartbeat System section...]
```

6. **`docs/03-phases/phase5-predictions/ml-training/04-monthly-retraining-guide.md`**

```markdown
# Monthly Retraining Guide

**Last Updated:** 2026-02-02
**Status:** Current

## Overview

Retrain CatBoost V9 monthly with trailing 90-day window.

[Copy from session-learnings.md Monthly Model Retraining pattern...]
```

7. **`docs/ARCHIVE-INDEX.md`**

```markdown
# Archive Index

**Last Updated:** 2026-02-02
**Status:** Current

## Purpose

Guide to historical documentation in `docs/archive/`.

## By Topic

### Incidents
- **CatBoost V8 Performance Collapse** - `archive/2026-01-incidents/v8-performance-collapse/`
- **P0 Incident (Jan 26)** - `archive/2026-01/2026-01-26-P0-incident/`

[Continue organizing by topic...]
```

8. **`docs/08-projects/PROJECT-SUMMARIES-INDEX.md`**

```markdown
# Project Summaries Index

**Last Updated:** 2026-02-02
**Status:** Current

## Monthly Summaries

- **[2026-02 (In Progress)](summaries/2026-02.md)** - Sessions 71-92, Phase 6 subset exporters
- **[2026-01](summaries/2026-01.md)** - Sessions 1-70, V8 incident → V9 deployment

## How to Use

These summaries extract key learnings before projects are archived, preserving knowledge.
```

---

### P1-4: Consolidate ML Documentation

**Issue:** ML docs split across:
- `docs/05-ml/` (2 files)
- `docs/05-development/ml/` (multiple subdirs)
- `docs/03-phases/phase5-predictions/` (operational)

**Action:**
- **Development guides** → `docs/05-development/ml/`
- **Training operations** → `docs/03-phases/phase5-predictions/ml-training/`
- **Delete** `docs/05-ml/`, move contents

**Script:**
```bash
# Move 05-ml/ contents
mv docs/05-ml/* docs/05-development/ml/
rmdir docs/05-ml/

# Update cross-references
grep -r "05-ml/" docs/ --files-with-matches | xargs sed -i 's|05-ml/|05-development/ml/|g'
```

---

## Implementation Timeline

### Week 1 (Feb 3-9): P0 Critical Fixes
- **Day 1:** Consolidate deployment guides (P0-1)
- **Day 2:** Consolidate troubleshooting docs (P0-2)
- **Day 3:** Fix entry points (P0-3)
- **Day 4:** Update V8→V9 references (P0-4)
- **Day 5:** Add Phase 6 links to CLAUDE.md (P0-5)

### Week 2 (Feb 10-16): P1 Important Updates
- **Day 1-2:** Merge non-numbered directories (P1-1)
- **Day 3:** Add "Last Updated" metadata (P1-2)
- **Day 4-5:** Create missing Phase 6 docs (P1-3)
- **Weekend:** Consolidate ML docs (P1-4)

### Week 3 (Feb 17-23): P2 Nice-to-Haves
- Merge scattered operations docs
- Archive historical projects
- Update stale scheduling docs

---

## Success Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Total .md files | 3,551 | ~2,000-2,500 | -30-45% |
| Top-level directories | 37 | 9-12 | -68-73% |
| Deployment guides | 7 | 3 | -57% |
| Troubleshooting docs | 5 | 3 + index | Consolidated |
| Entry points | 3 competing | 1 (README.md) | Clear |
| Non-numbered dirs | 28 | 0 | All organized |
| Outdated V8 refs | Multiple | 0 (except historical) | Fixed |
| Phase 6 docs | Missing | Complete | Added |

---

## Rollback Plan

If issues arise:

```bash
# Restore from backup
tar -xzf docs-backup-YYYYMMDD.tar.gz

# Revert git changes
git checkout docs/

# Restore specific file
git restore docs/path/to/file.md
```

---

## Next Steps

1. **Review this plan** with team
2. **Create feature branch:** `git checkout -b docs-cleanup-feb-2026`
3. **Start with P0-1:** Consolidate deployment guides
4. **Test after each step:** Verify links still work
5. **Commit incrementally:** Don't do all at once
6. **Update this plan:** Mark completed items with ✅

---

**Plan Owner:** Claude Sonnet 4.5
**Review Date:** 2026-02-09 (after Week 1)
**Completion Target:** 2026-02-23 (3 weeks)
