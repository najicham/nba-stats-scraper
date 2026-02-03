# Session 90 Handoff - Opus Review & Documentation Cleanup

**Date:** 2026-02-03
**Model:** Claude Opus 4.5
**Duration:** ~2 hours

---

## Session Summary

This session focused on two major areas:
1. **Technical review** of Phase 6 subset exporters implementation
2. **Documentation cleanup** - trimming CLAUDE.md and creating hygiene system

---

## Part 1: Phase 6 Subset Exporters Review

### Critical Bug Found

**ROI Calculation is mathematically incorrect** in two files:
- `data_processors/publishing/all_subsets_picks_exporter.py` (lines 307-318)
- `data_processors/publishing/subset_performance_exporter.py` (lines 196-209)

**Impact:** Reported ROI is inflated by 30-50 percentage points

| Subset | Correct ROI | Buggy ROI | Error |
|--------|-------------|-----------|-------|
| v9_high_edge_any | +1.1% | +48.1% | +47 pts |
| v9_high_edge_warning | -4.5% | +45.5% | +50 pts |

**Fix:** Replace `CASE WHEN wins > 0 THEN wins * 0.909 ELSE -(graded_picks - wins) END` with `wins * 0.909 - (graded_picks - wins)`

### Other Issues Found

| Priority | Issue | File |
|----------|-------|------|
| MAJOR | NULL team/opponent in output | `all_subsets_picks_exporter.py` |
| MAJOR | Security fallback exposes internal IDs | `subset_public_names.py` |
| MAJOR | N+1 query pattern (9 queries) | `all_subsets_picks_exporter.py` |
| MINOR | Non-sequential public IDs | `subset_public_names.py` |

### Review Documents Created

| Document | Purpose |
|----------|---------|
| `docs/08-projects/current/phase6-subset-model-enhancements/SESSION_90_OPUS_REVIEW_FOR_SONNET.md` | Detailed fix instructions for Sonnet |

### Next Steps for Phase 6

1. **Sonnet chat** should apply the ROI fix (critical)
2. Apply other fixes (security fallback, NULL handling)
3. Run tests and verify
4. Deploy to production

---

## Part 2: CLAUDE.md Refactoring

### Changes Made

| Before | After | Reduction |
|--------|-------|-----------|
| CLAUDE.md: 1,200 lines | CLAUDE.md: 291 lines | **76%** |
| claude_project_instructions.md: 503 lines | Archived | 100% |

### New Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `docs/02-operations/session-learnings.md` | 323 | Historical bug fixes & patterns |
| `docs/02-operations/system-features.md` | 237 | Feature documentation |
| `docs/05-development/DOCUMENTATION-STANDARDS.md` | 107 | Documentation conventions |

### Archived

- `.claude/archive/claude_project_instructions_2026-02-03.md`

---

## Part 3: Documentation Hygiene System

### Problem Identified

- `docs/08-projects/current/` has **125 directories**
- 64 directories are > 7 days old
- 17 standalone .md files
- Oldest projects from December 2024
- No lifecycle management

### Solution Created

| Document | Purpose |
|----------|---------|
| `docs/08-projects/DOCUMENTATION-HYGIENE-GUIDE.md` | Complete rules & workflow |
| `docs/08-projects/CLEANUP-PROMPT-2026-02.md` | Detailed cleanup instructions |
| `docs/08-projects/SONNET-CLEANUP-PROMPT.txt` | Quick prompt for new chat |
| `docs/08-projects/summaries/` | Directory for monthly summaries |

### Key Decisions

- **Monthly summaries** (not per-project) - prevents bloat, better temporal context
- **Archive by month** - `archive/2026-01/`, `archive/2026-02/`
- **Summarize before archiving** - extract learnings first
- **Sync root docs** - update CLAUDE.md, troubleshooting, etc. with patterns

---

## Pending Tasks for Next Sessions

### Task 1: Fix Phase 6 ROI Bug (Sonnet - HIGH PRIORITY)

```
Read: docs/08-projects/current/phase6-subset-model-enhancements/SESSION_90_OPUS_REVIEW_FOR_SONNET.md

Apply the ROI calculation fix to both files, then run tests and deploy.
```

### Task 2: Documentation Cleanup (Sonnet - MEDIUM PRIORITY)

```
Read: docs/08-projects/DOCUMENTATION-HYGIENE-GUIDE.md
Read: docs/08-projects/CLEANUP-PROMPT-2026-02.md

Follow the phases to clean up the 125 projects in current/.
```

### Task 3: Create /cleanup-projects Skill (Future)

After initial cleanup, consider creating a skill for ongoing hygiene.

---

## Files Changed This Session

### Created
- `docs/02-operations/session-learnings.md`
- `docs/02-operations/system-features.md`
- `docs/05-development/DOCUMENTATION-STANDARDS.md`
- `docs/08-projects/DOCUMENTATION-HYGIENE-GUIDE.md`
- `docs/08-projects/CLEANUP-PROMPT-2026-02.md`
- `docs/08-projects/SONNET-CLEANUP-PROMPT.txt`
- `docs/08-projects/summaries/` (directory)
- `docs/08-projects/current/phase6-subset-model-enhancements/SESSION_90_OPUS_REVIEW_FOR_SONNET.md`

### Modified
- `CLAUDE.md` (trimmed from 1200 to 291 lines)

### Archived
- `.claude/archive/claude_project_instructions_2026-02-03.md`

---

## Key Learnings

1. **CLAUDE.md was 40% troubleshooting notes** - moved to session-learnings.md
2. **ROI formula bugs are subtle** - always verify with actual data
3. **125 projects in "current" is a smell** - need lifecycle management
4. **Monthly summaries > per-project summaries** - better for long-term retrieval

---

## Quick Start for Next Session

```bash
# Check Phase 6 review document
cat docs/08-projects/current/phase6-subset-model-enhancements/SESSION_90_OPUS_REVIEW_FOR_SONNET.md

# Check documentation cleanup prompt
cat docs/08-projects/SONNET-CLEANUP-PROMPT.txt

# Verify CLAUDE.md is trimmed
wc -l CLAUDE.md  # Should be ~291 lines
```
