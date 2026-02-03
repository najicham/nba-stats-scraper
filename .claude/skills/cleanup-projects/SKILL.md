# Skill: Documentation & Projects Cleanup

Automated weekly/monthly cleanup of project documentation following the Documentation Hygiene Guide.

## Trigger
- User asks to "clean up projects", "run cleanup", "organize documentation"
- User types `/cleanup-projects`
- Weekly reminder (suggested automation)

## Workflow

**IMPORTANT**: Always ask the user which cleanup mode they want:

### Cleanup Mode Options

Use `AskUserQuestion` to present these options:

**Question:** "Which cleanup scope do you want?"

**Options:**
1. **Project Directory Only** (Recommended for weekly)
   - Inventory `docs/08-projects/current/`
   - Categorize by age and status
   - Generate recommendations
   - Create monthly summaries if needed
   - Execute cleanup if approved
   - **Time:** ~15-30 minutes

2. **Full Documentation Scan** (Recommended for monthly)
   - Everything in Option 1, PLUS:
   - Scan ALL docs/ directories (3,500+ files)
   - Check for duplicates, outdated content, gaps
   - Review root docs for updates
   - Suggest consolidation opportunities
   - **Time:** ~1-2 hours

3. **Root Docs Check Only**
   - Skip project inventory
   - Only check root documentation
   - Review recent projects for learnings
   - Suggest documentation updates
   - **Time:** ~10-15 minutes

After user selects mode, proceed with the appropriate workflow below.

## Phase 1: Project Inventory

### Count and List Projects

```bash
# Count total projects
find docs/08-projects/current -maxdepth 1 -type d | wc -l

# Count standalone files
find docs/08-projects/current -maxdepth 1 -type f -name "*.md" | wc -l

# Find projects older than 14 days
find docs/08-projects/current -maxdepth 1 -type d -mtime +14

# Find projects older than 30 days
find docs/08-projects/current -maxdepth 1 -type d -mtime +30
```

### Classification Rules

**ARCHIVE** (move to `docs/08-projects/archive/YYYY-MM/`):
- Last modified > 30 days ago
- Status: "Complete" or "Done" in README.md
- Date-prefixed directories from past months (e.g., `2026-01-*`)
- One-time incidents that are resolved

**COMPLETE** (mark as complete, archive after 30 days):
- Project goal achieved
- Feature shipped/deployed
- Bug fixed and verified
- README has completion indicators

**KEEP** (leave in `current/`):
- Modified in last 14 days
- Status: "Active" or "In Progress"
- Ongoing/recurring projects (experiments, monitoring)
- Multi-phase projects still in progress

## Phase 2: Generate Recommendations

### Output Format

```markdown
# Project Cleanup Recommendations - YYYY-MM-DD

## Summary
- Total projects: X
- KEEP (active): Y
- COMPLETE (ready to archive): Z
- ARCHIVE (>30 days old): N
- Standalone files: M

## ARCHIVE - Immediate Action (N projects)

| Project | Last Modified | Age | Reason |
|---------|---------------|-----|--------|
| system-evolution | 2025-12-11 | 52d | No activity, planning phase stale |
| ... | ... | ... | ... |

## COMPLETE - Ready to Archive (Z projects)

| Project | Last Modified | Status | Category |
|---------|---------------|--------|----------|
| 2026-01-26-P0-incident | 2026-01-26 | Complete | Incident |
| ... | ... | ... | ... |

## KEEP - Active (Y projects)

| Project | Last Modified | Status | Category |
|---------|---------------|--------|----------|
| validation-improvements | 2026-02-02 | In Progress | Infrastructure |
| ... | ... | ... | ... |

## Standalone Files (M files)

| File | Recommendation |
|------|----------------|
| SESSION-SUMMARY-2026-01-26.md | Move to sessions/ |
| daily-orchestration-issues-2026-02-01.md | Move to daily-orchestration-improvements/ |
| ... | ... |
```

## Phase 3: Check Root Documentation

### Files to Review

Check if these need updates based on recent projects:

1. **CLAUDE.md** - New essential commands? New gotchas?
2. **docs/02-operations/session-learnings.md** - New bug patterns?
3. **docs/02-operations/system-features.md** - New features shipped?
4. **docs/02-operations/troubleshooting-matrix.md** - New error patterns?
5. **docs/01-architecture/** - System design changes?

### Detection Queries

```bash
# Find recent completed projects (< 7 days ago)
find docs/08-projects/current -maxdepth 1 -type d -mtime -7 -exec ls -ld {} \;

# Search for specific patterns in recent projects
grep -r "Anti-pattern\|Pattern:" docs/08-projects/current/*/README.md 2>/dev/null

# Check for new features mentioned
grep -r "Feature:\|New feature" docs/08-projects/current/*/README.md 2>/dev/null

# Check for bug fixes
grep -r "Bug:\|Root cause:" docs/08-projects/current/*/README.md 2>/dev/null
```

### Root Doc Update Recommendations

```markdown
## Root Documentation Updates Needed

| Document | Update | Source Project | Priority |
|----------|--------|----------------|----------|
| system-features.md | Add Phase 6 subset exporters | phase6-subset-model-enhancements | P0 |
| session-learnings.md | Add nested metadata pattern | model-attribution-tracking | P0 |
| CLAUDE.md | Add game_id mismatch issue | 2026-01-26-betting-timing-fix | P1 |
```

## Phase 4: Create Monthly Summary

### Monthly Summary Template

For projects being archived, extract key learnings:

```markdown
# {Month Year} Project Summary

## Overview
- Projects completed: X
- Projects archived: Y
- Key themes: [Validation, ML experiments, Incident recovery, etc.]

## Major Accomplishments

### Bug Fixes
| Issue | Root Cause | Fix | Impact |
|-------|------------|-----|--------|
| Silent BQ writes | Missing dataset in table ref | Use {project}.{dataset}.{table} | Prevented data loss |

### Features Shipped
| Feature | Description | Files Changed |
|---------|-------------|---------------|
| Phase 6 exporters | Subset picks to GCS API | predictions/exporters/* |

### Performance Improvements
| Area | Before | After | How |
|------|--------|-------|-----|
| BigQuery quota | 90% usage | 10% usage | Batch writer pattern |

## Patterns & Practices Established

### New Patterns
- **Multi-agent investigation**: Spawn 6+ agents in parallel for complex debugging
- **Edge-based filtering**: Only bet on 3+ edge predictions (65% hit rate)

### Anti-Patterns Discovered
- **Assumption-driven debugging**: Made fixes without investigation (Session 75)
- **Silent failure acceptance**: 0 records written, no alerts (Session 59)

## Documentation Updates Made

| Doc | Update | Reason |
|-----|--------|--------|
| CLAUDE.md | Added CloudFront blocking | Session 75 incident |
| system-features.md | Added Phase 6 section | Sessions 87-91 |

## Metrics

| Metric | Value |
|--------|-------|
| Sessions this month | 70 |
| Bugs fixed | 15 |
| Features shipped | 8 |
| Lines of code changed | ~12,000 |

## Carry-Forward Items

Items that need continued attention:
- [ ] Kalshi integration (planning phase)
- [ ] V13 model experiments (in progress)
- [ ] Grading coverage gaps (monitoring)

## Projects Archived This Month

| Project | Summary | Key Files |
|---------|---------|-----------|
| catboost-v8-incident | V8 performance collapse investigation | ml/experiments/v8_investigation.py |
| 2026-01-26-P0-incident | Betting timing fix | predictions/coordinator/scheduler.py |
```

## Phase 5: Execute Cleanup

### Use Cleanup Script

```bash
# Dry run (review what will be moved)
./bin/cleanup-projects.sh

# Execute the moves
./bin/cleanup-projects.sh --execute
```

### Manual Moves (if script not available)

```bash
# Create monthly archive directory
mkdir -p docs/08-projects/archive/$(date +%Y-%m)

# Move old projects (example)
mv docs/08-projects/current/old-project docs/08-projects/archive/2026-01/

# Organize standalone files
mv docs/08-projects/current/SESSION-*.md docs/08-projects/current/sessions/
```

## Output Format

### Summary Report

```
================================================================================
  PROJECT CLEANUP REPORT - 2026-02-02
================================================================================

INVENTORY
────────────────────────────────────────────────────────────────────────────
✓ Total projects: 142
✓ KEEP (active): 96
✓ COMPLETE (ready to archive): 39
✓ ARCHIVE (>30 days old): 7
✓ Standalone files: 17

RECOMMENDATIONS
────────────────────────────────────────────────────────────────────────────
→ Archive 7 stale projects (>30 days)
→ Archive 39 completed projects
→ Organize 17 standalone files
→ Total reduction: 142 → 96 projects (-32%)

ROOT DOCUMENTATION UPDATES NEEDED
────────────────────────────────────────────────────────────────────────────
→ system-features.md: Add Phase 6 subset exporters (P0)
→ session-learnings.md: Add nested metadata pattern (P0)
→ CLAUDE.md: Add 4 common issues (P0)

MONTHLY SUMMARY STATUS
────────────────────────────────────────────────────────────────────────────
✓ 2026-01.md created (15 KB, 70 sessions)
✓ 2026-02.md in progress (14 KB, 22 sessions so far)

NEXT STEPS
────────────────────────────────────────────────────────────────────────────
1. Review recommendations above
2. Execute: ./bin/cleanup-projects.sh --execute
3. Update root docs (CLAUDE.md, system-features.md, session-learnings.md)
4. Commit changes

Run /cleanup-projects --execute to proceed with archival.
================================================================================
```

## Execution Modes

### Mode 1: Report Only (Default)
```
/cleanup-projects
```
- Inventories projects
- Generates recommendations
- Shows what would be archived
- Does NOT move any files

### Mode 2: Execute Cleanup
```
/cleanup-projects --execute
```
- Inventories projects
- Archives old projects
- Organizes standalone files
- Creates monthly summary (if missing)
- Generates commit message

### Mode 3: Root Docs Check
```
/cleanup-projects --check-docs
```
- Skips project inventory
- Only checks root documentation for updates
- Reviews recent projects for learnings
- Suggests documentation updates

### Mode 4: Create Monthly Summary
```
/cleanup-projects --summary YYYY-MM
```
- Creates monthly summary for specified month
- Extracts learnings from archived projects
- Updates carry-forward items

## Recommended Schedule

### Weekly (Every Monday, 15 min)
```bash
/cleanup-projects
```
- Review projects > 14 days old
- Move completed projects to archive
- Check if summaries need updating

### Monthly (First of month, 1 hour)
```bash
/cleanup-projects --execute
/cleanup-projects --summary $(date -d "last month" +%Y-%m)
/cleanup-projects --check-docs
```
- Archive all completed projects > 30 days
- Create/finalize monthly summary
- Update root documentation with learnings
- Validate key docs against code

### Quarterly (Every 3 months, 2 hours)
- Review all root documentation for accuracy
- Archive old monthly summaries (> 6 months)
- Clean up duplicate/outdated docs
- Update documentation index

## Key Files Referenced

### Project Organization
- `docs/08-projects/current/` - Active projects
- `docs/08-projects/completed/` - Finished projects (< 30 days)
- `docs/08-projects/archive/YYYY-MM/` - Archived projects
- `docs/08-projects/summaries/YYYY-MM.md` - Monthly summaries

### Scripts
- `bin/cleanup-projects.sh` - Automated cleanup script

### Documentation
- `docs/08-projects/DOCUMENTATION-HYGIENE-GUIDE.md` - Full cleanup guide
- `docs/08-projects/CLEANUP-PROMPT-2026-02.md` - Detailed cleanup phases
- `CLAUDE.md` - Root project instructions

## Anti-Patterns to Avoid

1. **Project graveyards** - Don't let 100+ projects accumulate in current/
2. **Lost knowledge** - Always summarize before archiving
3. **Stale docs** - Update root docs when patterns change
4. **Orphan files** - Don't leave standalone .md files scattered
5. **No lifecycle** - Every project should eventually complete or be paused

## Success Metrics

| Metric | Target | Ideal |
|--------|--------|-------|
| Projects in current/ | < 100 | < 30 |
| Standalone .md files | 0 | 0 |
| Projects > 30 days | 0 | 0 |
| Monthly summaries | Current + previous | Complete history |
| Root doc freshness | < 30 days | < 14 days |

## Workflow Details

### Option 1: Project Directory Only

1. **Inventory projects** in `docs/08-projects/current/`
2. **Categorize by age and status** (KEEP/COMPLETE/ARCHIVE)
3. **Generate recommendations** for what to archive
4. **Check if monthly summary exists** for current/previous month
5. **Create summary snippets** for projects being archived
6. **Execute cleanup** if user approves

### Option 2: Full Documentation Scan

1. **Do everything in Option 1**, PLUS:
2. **Scan all docs/ directories** for duplicates
3. **Check for outdated content** (CatBoost V8 refs, old dates)
4. **Identify gaps** in documentation
5. **Review root docs** (CLAUDE.md, system-features.md, etc.)
6. **Generate comprehensive report** with action plan
7. **Execute cleanup** if user approves

### Option 3: Root Docs Check Only

1. **Find recent projects** (modified < 7 days)
2. **Extract learnings** from README files
3. **Check if root docs need updates**:
   - CLAUDE.md - new commands, gotchas?
   - system-features.md - new features?
   - session-learnings.md - new patterns?
   - troubleshooting-matrix.md - new errors?
4. **Generate update recommendations**

## Example Session

```
User: /cleanup-projects