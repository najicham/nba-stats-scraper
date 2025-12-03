# Documentation Organization Guide

**Version:** 1.1
**File:** `docs/05-development/documentation-standards.md`
**Created:** 2025-11-15
**Last Updated:** 2025-12-02
**Purpose:** Standard approach for organizing documentation across all directories
**Status:** Current
**Audience:** Future AI assistants and engineers organizing documentation

---

## Overview

This guide defines the **standard pattern** for organizing documentation directories across the NBA Stats Scraper project. Use this approach consistently in all doc directories for predictable, maintainable documentation structure.

**Proven in:** `docs/01-architecture/` (reorganized 2025-11-15, updated 2025-11-29)

---

## Core Principles

### 1. Chronological Numbering (Context-Free)
- ✅ Number files in creation order (01, 02, 03...)
- ✅ New docs just increment the highest number
- ✅ Never rename existing files
- ✅ Use 2 digits (01-99) for clarity

### 2. README Provides Reading Order (Pedagogical)
- ✅ README lists docs in logical reading order
- ✅ Filename order ≠ reading order
- ✅ "Start here" guidance for new readers
- ✅ Document categories and purpose

### 3. Archive Completed/Superseded Docs
- ✅ Keep main directory clean (~20-30 active docs)
- ✅ Move session artifacts to `archive/YYYY-MM-DD/`
- ✅ Move superseded docs to `archive/old/`
- ✅ Preserve history, reduce clutter

### 4. Consistent Metadata
- ✅ All docs have Created/Last Updated timestamps
- ✅ Use PST/PDT timezone explicitly
- ✅ Include purpose and status fields
- ✅ Update file path in metadata when renaming

---

## Directory Structure Template

```
docs/{category}/
├── README.md                          ← Index with reading order
├── 01-first-created-doc.md           ← Chronological order
├── 02-second-created-doc.md
├── 03-third-created-doc.md
├── 04-most-important-doc.md          ← May be "START HERE" in README
├── 05-current-status.md
├── ... (future docs use 06, 07, 08...)
│
└── archive/
    ├── YYYY-MM-DD/                    ← Session artifacts by date
    │   └── session-handoff.md
    └── old/                           ← Superseded documentation
        └── old-approach.md
```

---

## File Naming Convention

### Active Documents

**Format:** `{NN}-{descriptive-name}.md`

**Rules:**
- `{NN}` = Two-digit number (01-99)
- Number reflects creation order (chronological)
- Use descriptive kebab-case names
- No dates in filename (use metadata instead)

**Examples:**
```
01-phase1-to-phase5-integration-plan.md
02-granular-updates-optimization.md
03-monitoring-and-error-handling.md
04-event-driven-pipeline-architecture.md
```

**Why chronological, not pedagogical?**
- New docs just increment highest number (no context needed)
- Never requires renaming existing files
- README provides logical reading order
- Shows historical development

### Archived Documents

**Format:** Preserve original filename OR use date prefix for clarity

**Location:**
```
archive/
├── 2025-11-15/                    ← Date-based for session artifacts
│   ├── session-handoff.md
│   └── completed-task-doc.md
└── old/                           ← For superseded versions
    └── old-architecture-v1.md
```

---

## Document Metadata Template

**Every document should start with:**

```markdown
# Document Title

**File:** `docs/{category}/{NN}-filename.md`
**Created:** YYYY-MM-DD HH:MM PST
**Last Updated:** YYYY-MM-DD HH:MM PST
**Purpose:** Brief description of document purpose
**Status:** Current|Draft|Superseded|Archive
```

**Timezone:** Always use PST/PDT (Pacific Time) explicitly

---

## Status Legend (Standard Markers)

Use these consistently across all documentation:

### Deployment/Component Status

| Marker | Text | Meaning |
|--------|------|---------|
| ✅ | `Deployed` / `Production` / `Complete` | Fully operational |
| ⚠️ | `Partial` / `In Progress` | Partially complete or needs attention |
| ❌ | `Missing` / `Not Started` / `Failed` | Not available or broken |
| 🔄 | `Pending` / `Backfill Needed` | Waiting for action |

### Data Status

| Marker | Text | Meaning |
|--------|------|---------|
| `complete` | Full data coverage | All expected data present |
| `partial` | Partial coverage | Some data missing |
| `missing` | No data | No data for this period |
| `timeout` | Query timeout | Check didn't complete |
| `bootstrap_skip` | Bootstrap period | Expected empty (first 14 days) |

### Document Status

| Status | Meaning |
|--------|---------|
| `Current` | Active, up-to-date documentation |
| `Draft` | Work in progress |
| `Superseded` | Replaced by newer version |
| `Archive` | Historical reference only |

### Priority/Severity

| Level | Use For |
|-------|---------|
| `HIGH` / `Critical` | Blocking issues, immediate action |
| `MEDIUM` / `Warning` | Should be addressed soon |
| `LOW` / `Info` | Nice to have, future work |

**When to update "Last Updated":**
- Significant content changes
- Not for typo fixes or minor corrections
- Update timezone if DST changed (PST ↔ PDT)

---

## README.md Template

```markdown
# {Category} Documentation

**Last Updated:** YYYY-MM-DD
**Purpose:** Brief description
**Audience:** Target readers

---

## 📖 Reading Order (Start Here!)

**New to the system? Read these in order:**

### 1. **{NN}-most-important-doc.md** ⭐ START HERE
   - **Created:** YYYY-MM-DD HH:MM PST
   - **Brief description**
   - **Why read this:** Foundational understanding

### 2. **{NN}-second-most-important.md**
   - **Created:** YYYY-MM-DD HH:MM PST
   - **Brief description**
   - **Why read this:** Current status/practical application

### 3. **{NN}-detail-doc.md**
   - **Created:** YYYY-MM-DD HH:MM PST
   - **Brief description**
   - **Why read this:** Deep dive on specific topic

---

## 🗂️ Document Organization

### File Naming Convention
- Files numbered in creation order (01-99)
- Prefix is **chronological**, not pedagogical
- Reading order defined in this README
- Archive old docs when superseded

### Directory Structure
```
{category}/
├── README.md
├── 01-*.md (created first)
├── 02-*.md (created second)
├── ...
└── archive/
```

---

## 📝 Adding New Documents

```bash
# Find highest number
ls docs/{category}/*.md | grep -oE '^[0-9]+' | sort -n | tail -1

# Create new doc with next number
# Example: 06-new-document-name.md

# Use standard metadata header

# Update this README
```

---

## 🗄️ Archive Policy

**Move to archive/ when:**
- Session artifacts completed
- Status reports superseded
- Old approach replaced
- Historical reference only

**Archive structure:**
```
archive/
├── YYYY-MM-DD/     (session artifacts)
└── old/            (superseded docs)
```

---

## 🔗 Related Documentation

**For this category:**
- List related docs

**Other categories:**
- Link to related doc directories

---
```

---

## Adding New Documents (Step-by-Step)

### Step 1: Find Next Number

```bash
# Navigate to category directory
cd docs/{category}/

# Find highest number
ls *.md | grep -E '^[0-9]{2}-' | tail -1
# Example output: 05-current-doc.md

# Next number: 06
```

### Step 2: Create Document with Standard Header

```markdown
# Your Document Title

**File:** `docs/{category}/06-your-document-name.md`
**Created:** 2025-11-15 14:30 PST
**Last Updated:** 2025-11-15 14:30 PST
**Purpose:** What this document covers
**Status:** Draft

---

## Your Content Here
```

### Step 3: Update README

Add entry to "Reading Order" section if foundational, or to appropriate category section.

**Update "Last Updated" in README:**
```markdown
**Last Updated:** 2025-11-15
```

### Step 4: Verify

```bash
# Check file exists
ls docs/{category}/06-*.md

# Verify metadata format
head -10 docs/{category}/06-*.md
```

---

## Archiving Documents (Step-by-Step)

### When to Archive

**Session artifacts:**
- Handoff documents after session complete
- Planning docs after implementation
- Status reports after milestone

**Superseded docs:**
- Old architecture replaced by new
- Outdated approaches no longer used
- Deprecated guides

### How to Archive

```bash
# Create archive directory (if needed)
mkdir -p docs/{category}/archive/$(date +%Y-%m-%d)/

# Move doc to archive
mv docs/{category}/old-doc.md docs/{category}/archive/$(date +%Y-%m-%d)/

# Or move to old/ for superseded versions
mkdir -p docs/{category}/archive/old/
mv docs/{category}/old-version.md docs/{category}/archive/old/

# Update README to reference archive
# (Usually just brief mention, not detailed list)
```

---

## Timestamp Format Standards

### Format
```
YYYY-MM-DD HH:MM PST
```

**Examples:**
- `2025-11-15 14:30 PST` (Pacific Standard Time)
- `2025-06-15 14:30 PDT` (Pacific Daylight Time)

**Why this format:**
- ✅ Human-readable
- ✅ Sortable
- ✅ Hour-level precision for multi-doc sessions
- ✅ Explicit timezone (PST/PDT)

**Alternatives considered:**
- Date only: Too coarse for tracking session work
- ISO 8601: Less readable (`2025-11-15T14:30:00-08:00`)
- UTC: Less intuitive for local team

---

## Categories of Documents

### Evergreen Documents
**Keep updated, never archive:**
- Operations guides
- How-to documentation
- System architecture (current)
- Monitoring guides

**Maintenance:**
- Update in place
- Keep "Last Updated" current
- Version in header if needed

### Point-in-Time Documents
**Archive when superseded:**
- Status reports
- Gap analyses
- Session handoffs
- Implementation plans (after complete)

**Maintenance:**
- Archive after milestone
- Move to `archive/YYYY-MM-DD/`
- Create new version if needed

---

## Directory-Specific Applications

### docs/01-architecture/
**Focus:** System design, architecture decisions, v1.0 orchestration
**Example docs:** Pipeline design, orchestrators, Pub/Sub topics
**Status:** ✅ Organized (2025-11-29)
**Subdirs:** `orchestration/`, `change-detection/`, `decisions/`, `diagrams/`

### docs/02-operations/
**Focus:** Operational guides, monitoring, orchestrator troubleshooting
**Example docs:** Orchestrator monitoring, Pub/Sub operations, backfill guide
**Status:** ✅ Organized (2025-11-29)
**Next:** Apply same pattern as architecture/

### docs/specifications/
**Focus:** Technical specs, message formats, API contracts
**Example docs:** Pub/Sub message formats, BigQuery schemas
**Status:** To be organized
**Next:** Apply pattern when multiple specs exist

### docs/sessions/
**Focus:** Detailed implementation session logs
**Example docs:** Session summaries, implementation details
**Status:** Chronological by nature
**Note:** May not need numbering, already date-prefixed

---

## Why This Pattern Works

### Benefits

**For new AI assistants:**
- ✅ No context needed to add docs (just increment)
- ✅ Clear instructions in README
- ✅ Consistent pattern across all directories
- ✅ Can organize new directories independently

**For engineers:**
- ✅ Clear "start here" guidance
- ✅ Predictable structure across project
- ✅ Easy to find information (README index)
- ✅ Historical docs preserved but not cluttered

**For maintenance:**
- ✅ Low overhead (just increment, no renaming)
- ✅ README provides organization
- ✅ Archive keeps directories clean
- ✅ Scales to 99 docs per directory

### Limitations

**When this pattern may not work:**
- Very large doc sets (>99 docs) → Consider subdirectories
- Rapidly changing docs → Use versioning instead
- Tutorial series → Pedagogical numbering may be better
- API documentation → Tool-generated structure preferred

**Solutions:**
- Create subdirectories by topic
- Use version numbers in filenames
- Create separate tutorial directory
- Keep tool-generated docs separate

---

## Examples from Real Reorganizations

### Architecture Directory Reorganization (2025-11-15)

**Before:**
- 11 files, no clear structure
- Unclear reading order
- Mix of current and old docs

**After:**
- 5 active docs (01-05)
- 6 archived docs
- Comprehensive README
- Clear "start with 04" guidance

**Result:**
- New chat can add doc 06 without context
- Engineers know where to start
- History preserved in archive
- Clean, maintainable structure

**Full details:** `docs/architecture/archive/2025-11-15/architecture-reorganization-handoff.md`

---

## Decision Tree: When to Use This Pattern

```
Do you have 3+ documentation files?
├─ NO → Just use descriptive names, add README when you hit 3
└─ YES → Continue

Are docs created over time (not all at once)?
├─ NO → Consider pedagogical numbering or subdirectories
└─ YES → Continue

Do new docs get added regularly?
├─ NO → Pedagogical numbering may be fine
└─ YES → Use chronological pattern ✅

Will different people/sessions add docs?
├─ NO → Flexibility in approach
└─ YES → Use chronological pattern ✅ (context-free)

Is reading order different from creation order?
├─ NO → Simple numbering may suffice
└─ YES → Use README for reading order ✅
```

**Recommendation: Use this pattern for most doc directories**

---

## Quick Reference

### Adding a Doc
```bash
# 1. Find next number
ls docs/{category}/*.md | tail -1  # Shows: 05-something.md
# 2. Create: 06-new-doc.md
# 3. Use standard metadata header
# 4. Update README
```

### Archiving a Doc
```bash
# 1. Create archive dir
mkdir -p docs/{category}/archive/$(date +%Y-%m-%d)
# 2. Move doc
mv docs/{category}/old-doc.md docs/{category}/archive/$(date +%Y-%m-%d)/
# 3. Update README reference
```

### Creating New Category
```bash
# 1. Create directory
mkdir -p docs/new-category
# 2. Copy README template (this doc)
# 3. Create first doc as 01-*.md
# 4. Customize README for category
```

---

## Checklist for New Directory Organization

**Before starting:**
- [ ] Read this guide completely
- [ ] Review `docs/01-architecture/` as example
- [ ] Check if category needs organization (3+ docs)

**During organization:**
- [ ] Create archive/ subdirectories
- [ ] Rename files with chronological numbers (01-99)
- [ ] Update all metadata headers (Created/Last Updated)
- [ ] Fix internal cross-references if filenames changed
- [ ] Move completed/superseded docs to archive
- [ ] Create comprehensive README

**After organization:**
- [ ] Verify file structure matches template
- [ ] Test that cross-references work
- [ ] Create handoff doc in archive/YYYY-MM-DD/
- [ ] Update this guide if lessons learned

---

## Version History

### v1.0 (2025-11-15)
- Initial version based on architecture/ reorganization
- Established chronological numbering pattern
- Defined README template
- Created metadata standards
- Documented archiving approach

**Next version:** After applying pattern to orchestration/ or specifications/

---

## Questions & Answers

**Q: What if I need to insert a doc between two numbers?**
A: You don't! Just use the next available number. README provides reading order, not filenames.

**Q: What if I hit 99 documents?**
A: Archive more aggressively, or create subdirectories by topic. 99 is a signal to reorganize.

**Q: Should I use this for session notes?**
A: Maybe not. Session notes are often date-prefixed already (2025-11-15-session.md). Use if >99 sessions.

**Q: Can I use pedagogical numbering instead?**
A: For tutorial series or very stable doc sets, yes. But chronological is better for evolving documentation.

**Q: What about generated documentation?**
A: Keep tool-generated docs separate (e.g., `docs/api/` for auto-generated API docs). This pattern is for hand-written docs.

**Q: How do I handle version 2 of a document?**
A: Archive v1 to `archive/old/`, create new doc with next number. Or use version in filename: `06-architecture-v2.md`

---

## See Also

- **Architecture example:** `docs/01-architecture/README.md`
- **Operations example:** `docs/02-operations/README.md`
- **Phases example:** `docs/03-phases/README.md`

---

**Guide Status:** Active
**Maintained By:** Project documentation standards
**Next Review:** After organizing 2nd directory

---

*This guide should be referenced whenever organizing a documentation directory. Keep it updated with lessons learned.*
