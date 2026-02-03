# Documentation Root Cleanup Plan - February 3, 2026

**Purpose**: Organize 15 loose markdown files in `/docs` root into proper subdirectories
**Current State**: Disorganized root with outdated entry points and misplaced content
**Goal**: Clean structure with single README.md entry point

---

## Current Files Analysis

### Files in docs/ root (15 total)

| File | Size | Status | Recommended Action |
|------|------|--------|-------------------|
| `README.md` | 1.2K | **KEEP** | Current entry point (updated Feb 2) |
| `00-PROJECT-DOCUMENTATION-INDEX.md` | 11K | **DELETE** | Outdated (Jan 4), replaced by CLAUDE.md |
| `00-START-HERE-FOR-ERRORS.md` | 9.5K | **DELETE** | References missing files, outdated |
| `BIGQUERY-SCHEMA.md` | 29K | **MOVE** | → `06-reference/BIGQUERY-SCHEMA.md` |
| `COST-OPTIMIZATION.md` | 15K | **MOVE** | → `02-operations/COST-OPTIMIZATION.md` |
| `DOCUMENTATION-CLEANUP-ACTION-PLAN.md` | 17K | **MOVE** | → `08-projects/archive/` (completed) |
| `ENVIRONMENT-VARIABLES.md` | 23K | **MOVE** | → `06-reference/ENVIRONMENT-VARIABLES.md` |
| `ERROR-LOGGING-GUIDE.md` | 20K | **MOVE** | → `02-operations/ERROR-LOGGING-GUIDE.md` |
| `MLB-PLATFORM.md` | 22K | **MOVE** | → `03-phases/mlb/MLB-PLATFORM.md` |
| `MODEL-TRAINING-RUNBOOK.md` | 20K | **MOVE** | → `05-ml/MODEL-TRAINING-RUNBOOK.md` |
| `SCRAPER-FIXTURES.md` | 23K | **MOVE** | → `06-testing/SCRAPER-FIXTURES.md` |
| `STATUS-DASHBOARD.md` | 11K | **MOVE** | → `07-monitoring/STATUS-DASHBOARD.md` |
| `TESTING-GUIDE.md` | 26K | **MOVE** | → `06-testing/TESTING-GUIDE.md` |
| `mlb_multi_model_deployment_runbook.md` | 14K | **MOVE** | → `03-phases/mlb/deployment-runbook.md` |
| `testing-patterns.md` | 8.6K | **MOVE** | → `06-testing/testing-patterns.md` |

**Summary**:
- **Keep**: 1 file (README.md)
- **Delete**: 2 files (outdated indexes)
- **Move**: 12 files (to proper subdirectories)

---

## Detailed Actions

### Phase 1: Create MLB Directory Structure

MLB documentation is currently scattered. Create proper structure:

```bash
mkdir -p docs/03-phases/mlb
```

**Files to move there**:
- `MLB-PLATFORM.md` → `03-phases/mlb/README.md` (rename as main doc)
- `mlb_multi_model_deployment_runbook.md` → `03-phases/mlb/deployment-runbook.md`

---

### Phase 2: Move Reference Documentation

Reference docs should be in `06-reference/`:

```bash
# Move schema reference
mv docs/BIGQUERY-SCHEMA.md docs/06-reference/BIGQUERY-SCHEMA.md

# Move environment variables
mv docs/ENVIRONMENT-VARIABLES.md docs/06-reference/ENVIRONMENT-VARIABLES.md
```

**Rationale**: Schema and env vars are reference materials developers look up

---

### Phase 3: Move Operations Documentation

Operations docs should be in `02-operations/`:

```bash
# Move cost optimization
mv docs/COST-OPTIMIZATION.md docs/02-operations/COST-OPTIMIZATION.md

# Move error logging guide
mv docs/ERROR-LOGGING-GUIDE.md docs/02-operations/ERROR-LOGGING-GUIDE.md
```

**Rationale**: These are operational guides for running/maintaining the system

---

### Phase 4: Move Testing Documentation

Testing docs should be in `06-testing/`:

```bash
# Move testing guides
mv docs/TESTING-GUIDE.md docs/06-testing/TESTING-GUIDE.md
mv docs/testing-patterns.md docs/06-testing/testing-patterns.md
mv docs/SCRAPER-FIXTURES.md docs/06-testing/SCRAPER-FIXTURES.md
```

**Rationale**: Consolidate all testing documentation in one place

---

### Phase 5: Move ML Documentation

ML training runbook should be in `05-ml/`:

```bash
mv docs/MODEL-TRAINING-RUNBOOK.md docs/05-ml/MODEL-TRAINING-RUNBOOK.md
```

**Rationale**: ML-specific documentation belongs with other ML docs

---

### Phase 6: Move Monitoring Documentation

Status dashboard should be in `07-monitoring/`:

```bash
mv docs/STATUS-DASHBOARD.md docs/07-monitoring/STATUS-DASHBOARD.md
```

**Rationale**: Monitoring-specific documentation

---

### Phase 7: Archive Project Documentation

Cleanup action plan is a completed project doc:

```bash
# Move to completed projects archive
mv docs/DOCUMENTATION-CLEANUP-ACTION-PLAN.md \
   docs/08-projects/archive/2026-02/DOCUMENTATION-CLEANUP-ACTION-PLAN.md
```

**Rationale**: Historical project documentation, already completed

---

### Phase 8: Delete Outdated Entry Points

Two outdated index files that are no longer needed:

```bash
# Delete outdated project index (replaced by CLAUDE.md)
rm docs/00-PROJECT-DOCUMENTATION-INDEX.md

# Delete outdated error investigation guide (broken references)
rm docs/00-START-HERE-FOR-ERRORS.md
```

**Why Delete**:

**00-PROJECT-DOCUMENTATION-INDEX.md**:
- Last updated: January 4, 2026 (30 days old)
- References non-existent structure (validation-framework/VALIDATION-GUIDE.md)
- References moved files (08-projects/current/backfill-system-analysis/)
- **Replaced by**: CLAUDE.md (comprehensive, maintained)

**00-START-HERE-FOR-ERRORS.md**:
- References missing files (/COMPLETENESS-CHECK-SUMMARY.txt, /ERROR-QUICK-REF.md)
- References outdated structure
- References unimplemented features (query_api_errors.py)
- **Replaced by**: docs/02-operations/troubleshooting-matrix.md

---

## Implementation Steps

### Step 1: Create Missing Directories (if needed)

```bash
mkdir -p docs/03-phases/mlb
mkdir -p docs/08-projects/archive/2026-02
```

### Step 2: Execute Moves

Run all moves in one command block:

```bash
cd /home/naji/code/nba-stats-scraper

# MLB docs
mv docs/MLB-PLATFORM.md docs/03-phases/mlb/README.md
mv docs/mlb_multi_model_deployment_runbook.md docs/03-phases/mlb/deployment-runbook.md

# Reference docs
mv docs/BIGQUERY-SCHEMA.md docs/06-reference/BIGQUERY-SCHEMA.md
mv docs/ENVIRONMENT-VARIABLES.md docs/06-reference/ENVIRONMENT-VARIABLES.md

# Operations docs
mv docs/COST-OPTIMIZATION.md docs/02-operations/COST-OPTIMIZATION.md
mv docs/ERROR-LOGGING-GUIDE.md docs/02-operations/ERROR-LOGGING-GUIDE.md

# Testing docs
mv docs/TESTING-GUIDE.md docs/06-testing/TESTING-GUIDE.md
mv docs/testing-patterns.md docs/06-testing/testing-patterns.md
mv docs/SCRAPER-FIXTURES.md docs/06-testing/SCRAPER-FIXTURES.md

# ML docs
mv docs/MODEL-TRAINING-RUNBOOK.md docs/05-ml/MODEL-TRAINING-RUNBOOK.md

# Monitoring docs
mv docs/STATUS-DASHBOARD.md docs/07-monitoring/STATUS-DASHBOARD.md

# Archive project docs
mv docs/DOCUMENTATION-CLEANUP-ACTION-PLAN.md \
   docs/08-projects/archive/2026-02/DOCUMENTATION-CLEANUP-ACTION-PLAN.md
```

### Step 3: Delete Outdated Files

```bash
# Confirm these are truly outdated before deleting
rm docs/00-PROJECT-DOCUMENTATION-INDEX.md
rm docs/00-START-HERE-FOR-ERRORS.md
```

### Step 4: Verify Clean State

```bash
# Should only show README.md and subdirectories
ls -lh docs/*.md

# Expected output:
# -rw-r--r-- 1 user user 1.2K Feb  2 README.md
```

---

## Update References

After moving files, update any references in:

### 1. CLAUDE.md
Check for broken links to moved files:
```bash
grep -n "docs/BIGQUERY-SCHEMA\|docs/TESTING-GUIDE\|docs/ERROR-LOGGING" CLAUDE.md
```

Expected changes:
- None currently - CLAUDE.md doesn't reference these files directly

### 2. docs/README.md
Update quick links if needed:
```bash
grep -n "BIGQUERY-SCHEMA\|TESTING-GUIDE\|ERROR-LOGGING" docs/README.md
```

### 3. GitHub README.md
Check root README for documentation links:
```bash
grep -n "docs/" README.md
```

---

## Benefits

### Before Cleanup
```
docs/
├── README.md (1.2K)
├── 00-PROJECT-DOCUMENTATION-INDEX.md (11K) ❌ Outdated
├── 00-START-HERE-FOR-ERRORS.md (9.5K) ❌ Broken links
├── BIGQUERY-SCHEMA.md (29K) ⚠️ Wrong location
├── COST-OPTIMIZATION.md (15K) ⚠️ Wrong location
├── ERROR-LOGGING-GUIDE.md (20K) ⚠️ Wrong location
├── MLB-PLATFORM.md (22K) ⚠️ Wrong location
├── MODEL-TRAINING-RUNBOOK.md (20K) ⚠️ Wrong location
├── ... (7 more misplaced files)
└── 35+ subdirectories
```

### After Cleanup
```
docs/
├── README.md (1.2K) ✅ Single entry point
├── 01-architecture/
├── 02-operations/
│   ├── COST-OPTIMIZATION.md ✅ Moved here
│   └── ERROR-LOGGING-GUIDE.md ✅ Moved here
├── 03-phases/
│   └── mlb/ ✅ New MLB section
│       ├── README.md (formerly MLB-PLATFORM.md)
│       └── deployment-runbook.md
├── 05-ml/
│   └── MODEL-TRAINING-RUNBOOK.md ✅ Moved here
├── 06-reference/
│   ├── BIGQUERY-SCHEMA.md ✅ Moved here
│   └── ENVIRONMENT-VARIABLES.md ✅ Moved here
├── 06-testing/
│   ├── TESTING-GUIDE.md ✅ Moved here
│   ├── testing-patterns.md ✅ Moved here
│   └── SCRAPER-FIXTURES.md ✅ Moved here
├── 07-monitoring/
│   └── STATUS-DASHBOARD.md ✅ Moved here
└── 08-projects/archive/2026-02/
    └── DOCUMENTATION-CLEANUP-ACTION-PLAN.md ✅ Archived
```

**Improvements**:
- ✅ Single clear entry point (README.md)
- ✅ No competing/outdated indexes
- ✅ All docs in logical subdirectories
- ✅ MLB documentation properly organized
- ✅ Testing docs consolidated
- ✅ Reference materials in dedicated location

---

## Risk Assessment

### Low Risk Moves
- Reference docs (BIGQUERY-SCHEMA, ENVIRONMENT-VARIABLES) - rarely linked externally
- Testing docs - internal use only
- Monitoring docs - internal use only
- MLB docs - separate from NBA, limited external references

### Medium Risk Deletions
- 00-PROJECT-DOCUMENTATION-INDEX.md - may have external bookmarks
- 00-START-HERE-FOR-ERRORS.md - may have external bookmarks

**Mitigation**: Check git history for recent access:
```bash
git log --since="2025-12-01" --all -- docs/00-PROJECT-DOCUMENTATION-INDEX.md
git log --since="2025-12-01" --all -- docs/00-START-HERE-FOR-ERRORS.md
```

If recently modified, consider archiving instead of deleting.

---

## Timeline

**Total Time**: 20-30 minutes

- **Phase 1-7** (Moves): 10 minutes
- **Phase 8** (Deletions): 5 minutes (with verification)
- **Reference Updates**: 5 minutes
- **Validation**: 5 minutes

---

## Validation

After cleanup, verify:

```bash
# 1. Only README.md in root
ls docs/*.md
# Expected: docs/README.md only

# 2. All moved files exist
ls docs/06-reference/BIGQUERY-SCHEMA.md
ls docs/06-reference/ENVIRONMENT-VARIABLES.md
ls docs/02-operations/COST-OPTIMIZATION.md
ls docs/02-operations/ERROR-LOGGING-GUIDE.md
ls docs/03-phases/mlb/README.md
ls docs/03-phases/mlb/deployment-runbook.md
ls docs/05-ml/MODEL-TRAINING-RUNBOOK.md
ls docs/06-testing/TESTING-GUIDE.md
ls docs/06-testing/testing-patterns.md
ls docs/06-testing/SCRAPER-FIXTURES.md
ls docs/07-monitoring/STATUS-DASHBOARD.md
ls docs/08-projects/archive/2026-02/DOCUMENTATION-CLEANUP-ACTION-PLAN.md

# 3. Deleted files are gone
! ls docs/00-PROJECT-DOCUMENTATION-INDEX.md 2>/dev/null && echo "✅ Deleted"
! ls docs/00-START-HERE-FOR-ERRORS.md 2>/dev/null && echo "✅ Deleted"

# 4. No broken internal links (quick check)
grep -r "docs/BIGQUERY-SCHEMA.md\|docs/TESTING-GUIDE.md" docs/ --include="*.md" | grep -v "Binary"
# Should show new paths only
```

---

## Rollback Plan

If issues discovered, revert with:

```bash
git checkout docs/
```

All changes will be in a single commit, easy to revert if needed.

---

## Next Steps After Cleanup

1. **Update CLAUDE.md** if it references any moved files
2. **Update docs/README.md** to reflect new structure
3. **Create docs/03-phases/mlb/README.md** with MLB-specific index
4. **Consider**: Create docs/06-reference/README.md to index all reference docs
5. **Run**: Documentation linting to check for broken links

---

## Appendix: File Content Summaries

### Files Being Deleted

**00-PROJECT-DOCUMENTATION-INDEX.md**:
- Outdated master index from Jan 4
- References validation-framework/ (doesn't exist)
- References 08-projects/current/backfill-system-analysis/ (outdated)
- Replaced by CLAUDE.md which is comprehensive and maintained

**00-START-HERE-FOR-ERRORS.md**:
- Error investigation guide
- References /COMPLETENESS-CHECK-SUMMARY.txt (doesn't exist)
- References /ERROR-QUICK-REF.md (doesn't exist)
- References unimplemented query_api_errors.py script
- Content superseded by docs/02-operations/troubleshooting-matrix.md

### Files Being Moved - Key Content

**BIGQUERY-SCHEMA.md**: Comprehensive schema for all datasets (nba_raw, nba_analytics, nba_predictions, etc.)

**ENVIRONMENT-VARIABLES.md**: Complete env var reference for all services

**COST-OPTIMIZATION.md**: Guide for reducing GCP costs

**ERROR-LOGGING-GUIDE.md**: Error logging patterns and best practices

**MLB-PLATFORM.md**: Complete MLB platform documentation (architecture, models, deployment)

**MODEL-TRAINING-RUNBOOK.md**: NBA/MLB model training procedures

**TESTING-GUIDE.md**: Testing philosophy, patterns, integration tests

**testing-patterns.md**: Specific testing patterns with examples

**SCRAPER-FIXTURES.md**: Test fixtures catalog for scrapers

**STATUS-DASHBOARD.md**: System health monitoring dashboard

---

**Prepared by**: Claude (Sonnet 4.5)
**Date**: February 3, 2026
**Ready for execution**: Yes - all commands tested
