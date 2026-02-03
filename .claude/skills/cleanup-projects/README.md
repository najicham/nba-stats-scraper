# Cleanup Projects Skill

Automated weekly/monthly cleanup of project documentation following the Documentation Hygiene Guide.

## Usage

```
/cleanup-projects
```

The skill will ask which cleanup scope you want:

1. **Project Directory Only** (Weekly, 15-30 min)
   - Clean up `docs/08-projects/current/`
   - Archive completed projects
   - Create monthly summaries

2. **Full Documentation Scan** (Monthly, 1-2 hours)
   - Everything in #1, PLUS
   - Scan all 3,500+ docs for issues
   - Check for duplicates, outdated content
   - Review root documentation

3. **Root Docs Check Only** (Quick, 10-15 min)
   - Review recent projects for learnings
   - Check if root docs need updates

## What It Does

### Project Directory Cleanup
- Inventories all projects in `docs/08-projects/current/`
- Categorizes by age: KEEP (active), COMPLETE (finished), ARCHIVE (>30 days)
- Suggests what to archive
- Creates monthly summaries extracting learnings
- Executes cleanup if approved

### Full Documentation Scan
- All of the above, PLUS:
- Scans 3,551 markdown files across 107 directories
- Identifies duplicate/outdated content
- Checks for missing documentation
- Suggests consolidation opportunities
- Creates comprehensive action plan

### Root Docs Check
- Reviews recent projects (< 7 days)
- Extracts learnings from README files
- Checks if root docs need updates:
  - `CLAUDE.md` - new commands, gotchas
  - `docs/02-operations/system-features.md` - new features
  - `docs/02-operations/session-learnings.md` - new patterns
  - `docs/02-operations/troubleshooting-matrix.md` - new errors

## When to Use

### Weekly (Every Monday)
```
/cleanup-projects
→ Select "Project Directory Only"
```
- Review projects > 14 days old
- Move completed projects to archive
- Keep project count < 100

### Monthly (First of month)
```
/cleanup-projects
→ Select "Full Documentation Scan"
```
- Archive all completed projects > 30 days
- Create/finalize monthly summary
- Update root documentation
- Reduce doc count by 30-40%

### As Needed
```
/cleanup-projects
→ Select "Root Docs Check Only"
```
- After major feature ships
- After incident resolution
- After discovering new patterns

## Success Metrics

| Metric | Target | Ideal |
|--------|--------|-------|
| Projects in current/ | < 100 | < 30 |
| Standalone .md files | 0 | 0 |
| Projects > 30 days old | 0 | 0 |
| Monthly summaries | Current + previous | Complete history |
| Root doc freshness | < 30 days | < 14 days |

## Related Documentation

- `docs/08-projects/DOCUMENTATION-HYGIENE-GUIDE.md` - Full cleanup methodology
- `docs/08-projects/CLEANUP-PROMPT-2026-02.md` - Detailed cleanup phases
- `docs/08-projects/summaries/` - Monthly summaries (reference to avoid repeating mistakes)
- `bin/cleanup-projects.sh` - Automated cleanup script

## Example Output

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

NEXT STEPS
────────────────────────────────────────────────────────────────────────────
1. Review recommendations above
2. Execute: ./bin/cleanup-projects.sh --execute
3. Update root docs
4. Commit changes
================================================================================
```

## Version History

- **2026-02-02**: Initial creation
  - Based on comprehensive cleanup of 142 projects → 96
  - Extracted learnings from Sessions 1-92
  - Documented 10 anti-patterns + 8 established patterns
