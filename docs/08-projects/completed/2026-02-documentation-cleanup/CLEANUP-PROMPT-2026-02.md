# Documentation Cleanup Task - February 2026

## Your Mission

Clean up and organize the documentation in this repository, focusing on:
1. Project directory hygiene (`docs/08-projects/current/`)
2. Creating/updating monthly summaries
3. Syncing root documentation with project learnings
4. Validating docs against actual code

**Reference:** Read `docs/08-projects/DOCUMENTATION-HYGIENE-GUIDE.md` for full details on the workflow.

---

## Phase 1: Assess Current State

### Step 1.1: Inventory Projects

```bash
# Count and list all projects
ls -la docs/08-projects/current/ | head -50
find docs/08-projects/current -maxdepth 1 -type d | wc -l

# Find old projects (> 14 days)
find docs/08-projects/current -maxdepth 1 -type d -mtime +14 | wc -l

# Find standalone .md files
find docs/08-projects/current -maxdepth 1 -type f -name "*.md"
```

### Step 1.2: Categorize Each Project

For each project directory in `current/`, determine:
- **Age**: When was it last modified?
- **Status**: Check README.md for status (Active/Complete/Abandoned)
- **Category**: Bug fix, feature, incident, ML experiment, etc.
- **Disposition**: Keep, Complete, or Archive

Create a table like:
| Project | Last Modified | Status | Category | Disposition | Reason |
|---------|---------------|--------|----------|-------------|--------|

### Step 1.3: Identify Key Learnings

For projects being archived, note:
- What was the problem/goal?
- What was the solution?
- What patterns or practices emerged?
- Should any root docs be updated?

---

## Phase 2: Create Monthly Summary

### Step 2.1: Create February Summary Structure

Create `docs/08-projects/summaries/2026-02.md` using the template from the hygiene guide.

### Step 2.2: Extract Learnings from January Projects

Review projects from January that are being archived. Extract:
- Major bugs fixed (with root causes)
- Features shipped
- Patterns established
- Anti-patterns discovered

Add to `docs/08-projects/summaries/2026-01.md` (create if doesn't exist).

---

## Phase 3: Execute Moves

### Step 3.1: Move Completed Projects

```bash
# Example moves
mv docs/08-projects/current/completed-project docs/08-projects/completed/
```

### Step 3.2: Archive Old Projects

```bash
# Create monthly archive directory
mkdir -p docs/08-projects/archive/2026-01
mkdir -p docs/08-projects/archive/2025-12

# Move old projects
mv docs/08-projects/completed/old-project docs/08-projects/archive/2026-01/
```

### Step 3.3: Handle Standalone Files

For each standalone .md file in `current/`:
- If related to a project → move into that project
- If operational → move to `docs/02-operations/`
- If obsolete → move to archive with date prefix

---

## Phase 4: Sync Root Documentation

### Step 4.1: Review These Documents

Check if these need updates based on project learnings:

1. **`CLAUDE.md`** (~290 lines)
   - New essential commands?
   - New gotchas or common issues?
   - Model info still current?

2. **`docs/02-operations/session-learnings.md`**
   - New bug patterns from recent sessions?
   - New troubleshooting steps?

3. **`docs/02-operations/system-features.md`**
   - New features documented?
   - Existing features changed?

4. **`docs/02-operations/troubleshooting-matrix.md`**
   - New error patterns?
   - New solutions?

### Step 4.2: Validate Against Code

Spot-check that documentation matches reality:

```bash
# Check if referenced files exist
grep -r "shared/utils/" CLAUDE.md | head -5
# Verify those paths exist

# Check if commands work
# (Don't actually run destructive commands, just verify syntax)
```

### Step 4.3: Make Updates

For each doc that needs updating:
1. Note what's changing and why
2. Make the edit
3. Update "Last Updated" if the doc has one

---

## Phase 5: Create Cleanup Report

Create `docs/08-projects/CLEANUP-REPORT-2026-02-XX.md` with:

```markdown
# Documentation Cleanup Report - 2026-02-XX

## Summary
- Projects reviewed: X
- Moved to completed: Y
- Moved to archive: Z
- Standalone files handled: N

## Projects Archived

| Project | Summary | Key Learning |
|---------|---------|--------------|
| ... | ... | ... |

## Root Docs Updated

| Document | Change | Reason |
|----------|--------|--------|
| ... | ... | ... |

## Issues Found

- [List any problems discovered]

## Recommendations

- [Any process improvements suggested]
```

---

## Important Rules

1. **Don't delete anything** - Only move files
2. **Summarize before archiving** - Extract learnings first
3. **When in doubt, keep** - Better to keep than lose info
4. **Check README status** - Projects may have status indicators
5. **Group related items** - Archive related projects together
6. **Update, don't duplicate** - Update existing docs rather than creating new ones

---

## Expected Outcomes

After this cleanup:
- `current/` should have < 30 active projects
- Monthly summaries exist for recent months
- Root docs are updated with recent learnings
- No standalone .md files in `current/`
- Clear archive organization by month

---

## Time Estimate

- Phase 1 (Assess): 30-45 minutes
- Phase 2 (Summaries): 30 minutes
- Phase 3 (Moves): 15-20 minutes
- Phase 4 (Sync docs): 30-45 minutes
- Phase 5 (Report): 15 minutes

**Total: ~2-3 hours**

Consider breaking into multiple sessions if needed.
