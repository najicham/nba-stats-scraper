# Documentation Maintenance Playbook

**Created:** 2025-11-23
**Purpose:** Guide for future documentation cleanup and maintenance sessions
**Status:** Living document - update after each major cleanup

---

## Quick Reference

**Last Cleanup:** 2025-11-23
**Next Scheduled:** Monthly (first week of month)
**Time Required:** 1-2 hours
**Success Criteria:** <220 active docs, >90% README coverage, no files >30 days old

---

## Table of Contents

1. [Cleanup Methodology](#cleanup-methodology)
2. [Decision Framework](#decision-framework)
3. [Techniques Used](#techniques-used)
4. [Common Patterns](#common-patterns)
5. [Tools & Commands](#tools--commands)
6. [Lessons Learned](#lessons-learned)
7. [Next Session Plan](#next-session-plan)

---

## Cleanup Methodology

### Phase 1: Assess (15 minutes)

**Goal:** Understand current state before making changes

```bash
# 1. Count files
find docs -type f -name "*.md" -not -path "*/archive/*" | wc -l

# 2. Check README coverage
for dir in docs/*/; do
  if [ -f "$dir/README.md" ]; then echo "✅ $dir";
  else echo "❌ $dir"; fi
done

# 3. Find old files (>30 days)
find docs -type f -name "*.md" -not -path "*/archive/*" -mtime +30

# 4. Find large files (>100KB)
find docs -type f -name "*.md" -not -path "*/archive/*" -size +100k

# 5. Check for empty files
find docs -type f -name "*.md" -not -path "*/archive/*" -size 0
```

**Output:** Create initial health report with metrics

### Phase 2: Identify Issues (15 minutes)

**Goal:** Categorize files into keep/archive/consolidate/delete

**Decision Tree:**

```
For each file, ask:

1. Is it temporal (dated, status update)?
   YES → Archive to dated folder (archive/YYYY-MM/)
   NO → Continue

2. Does it have ongoing reference value?
   YES → Keep or move to reference/
   NO → Continue

3. Is it a meta-document about changes?
   YES → Consolidate into summary
   NO → Continue

4. Is it completed work with no future value?
   YES → Archive
   NO → Keep active

5. Is it duplicated elsewhere?
   YES → Delete, keep canonical version
   NO → Keep
```

**Categories:**
- **Keep Active:** Implementation guides, operational runbooks, references
- **Archive (dated):** Status updates, handoffs, completed rollouts
- **Archive (reference):** Completed strategies with ongoing value
- **Consolidate:** Multiple meta-docs → single summary
- **Delete:** Duplicates, truly obsolete content

### Phase 3: Execute (30-45 minutes)

**Goal:** Implement changes systematically

**Order of Operations:**

1. **Archive temporal docs first**
   - Create archive/YYYY-MM/ directories
   - Move dated handoffs, status updates
   - Preserve file history

2. **Consolidate meta-documentation**
   - Read through related meta-docs
   - Extract key insights
   - Create consolidated summary
   - Delete originals after verification

3. **Organize reference material**
   - Create topic-based subdirectories
   - Move strategy docs to reference/
   - Separate from pure status updates

4. **Create missing READMEs**
   - One README per directory minimum
   - Explain purpose and contents
   - Link to key documents

5. **Update existing READMEs**
   - Reflect new structure
   - Update file counts
   - Add new sections as needed

### Phase 4: Verify (15 minutes)

**Goal:** Ensure nothing was lost or broken

```bash
# 1. Verify file counts
find docs -type f -name "*.md" | wc -l  # Should be reasonable

# 2. Check for broken moves
find docs -type f -name "*.md" -size 0  # Should be empty

# 3. Verify README coverage
# Should be >90%

# 4. Spot check important docs still exist
cat docs/README.md | head -20
cat docs/SYSTEM_STATUS.md | head -20

# 5. Check archive organization
ls -la docs/*/archive/2025-*/
```

### Phase 5: Document (15 minutes)

**Goal:** Record what was done for future reference

Create cleanup summary documenting:
- What was archived (file counts, categories)
- What was consolidated (which docs, key insights)
- What was created (new READMEs, summaries)
- Final metrics (file counts, coverage %)
- Remaining issues identified

---

## Decision Framework

### Should I Archive This File?

**Archive if ANY of these are true:**

✅ **Temporal marker in filename** - HANDOFF-YYYY-MM-DD, SESSION_YYYY-MM-DD
✅ **Status update** - "COMPLETE", "PROGRESS", "ROLLOUT", "WEEK1_DONE"
✅ **Older than 2 weeks AND superseded** - Content now in main docs
✅ **Meta-documentation** - Documents what changed in other docs
✅ **Deployment/rollout record** - Historical record of deployment

**Keep active if:**

🟢 **Ongoing reference value** - Implementation strategies, patterns
🟢 **Operational runbook** - Daily/weekly procedures
🟢 **Architecture/design** - System design decisions
🟢 **Referenced frequently** - Other docs link to it

### Should I Consolidate These Files?

**Consolidate if:**

✅ **Multiple meta-docs on same topic** - 5 enhancement docs → 1 summary
✅ **Overlapping content** - Same information in multiple places
✅ **Chronological sequence completed** - 01, 02, 03... all done
✅ **Total >1000 lines** - Too much meta-documentation

**Keep separate if:**

🟢 **Different audiences** - Dev guide vs ops guide
🟢 **Different purposes** - Strategy vs implementation vs status
🟢 **Active work in progress** - Still being updated
🟢 **Referenced independently** - Other docs link to specific file

### Where Should This File Live?

**Decision Matrix:**

| Content Type | Location | Example |
|--------------|----------|---------|
| Temporal status update | archive/YYYY-MM/ | WEEK1_COMPLETE.md |
| Completed strategy (valuable) | implementation/reference/ | smart-idempotency-strategy.md |
| Active implementation guide | implementation/ | pattern-rollout-plan.md |
| Dated handoff | handoff/archive/YYYY-MM/ | HANDOFF-2025-11-15.md |
| Operational runbook | operations/ or processors/ | phase3-operations-guide.md |
| Architecture decision | architecture/ | event-driven-pipeline.md |
| Code example | examples/ | smart_reprocessing.py |
| Template | templates/ | processor-card-template.md |
| Pattern reference | patterns/ | smart-idempotency-reference.md |

---

## Techniques Used

### 1. Consolidation Pattern

**Problem:** 5 related meta-documentation files (1,698 lines total)

**Solution:**
1. Read all files to understand content
2. Identify key insights and decisions
3. Create single consolidated summary with:
   - What was changed and why
   - Key concepts introduced
   - Impact metrics
   - Status (completed/deployed)
4. Delete individual files
5. Keep consolidated summary in archive

**Result:** 1,698 lines → 312 lines, insights preserved

**Example:** dependency-checks enhancement docs → single evolution summary

### 2. Reference Extraction Pattern

**Problem:** Valuable strategy docs buried in archive with status updates

**Solution:**
1. Create reference/ subdirectory
2. Identify files with ongoing value (implementation strategies)
3. Separate from pure status updates
4. Organize by topic (smart-idempotency/, dependency-checking/, etc.)
5. Create comprehensive README indexing all reference docs
6. Keep only status updates in archive/

**Result:** Easy to find "how we implemented X" without digging through archives

**Example:** implementation/reference/ with 4 topic areas

### 3. Handoff Consolidation Pattern

**Problem:** 37 dated handoff files making directory hard to navigate

**Solution:**
1. Create comprehensive consolidated summary
2. Timeline format with dates and summaries
3. Extract key accomplishments from each handoff
4. Delete individual dated handoffs
5. Keep consolidated summary + active files only

**Result:** 37 files → 5 files (4 active + 1 consolidated summary)

**Example:** handoff/ directory cleanup

### 4. Progressive README Creation

**Problem:** Missing READMEs reduce discoverability

**Solution:**
1. Identify directories without README/00-overview
2. Read directory contents to understand purpose
3. Create README with:
   - Purpose statement
   - What's in this directory
   - How to use the content
   - Links to related docs
4. Add navigation and organization

**Result:** Went from 65% → 95.5% README coverage

**Example:** examples/, templates/, patterns/ READMEs

### 5. Archive Organization Strategy

**Problem:** Ad-hoc archiving making old docs hard to find

**Solution:**
1. Create consistent archive structure: archive/YYYY-MM/
2. Group by date for temporal docs
3. Keep reference/ separate for ongoing value
4. Archive README explains what's archived and why
5. Link to consolidated summaries

**Result:** Clear separation of temporal (archive) vs reference (ongoing value)

**Example:** handoff/archive/2025-11/, implementation/archive/2025-11/

---

## Common Patterns

### Pattern: Too Many Dated Handoffs

**Symptoms:**
- 30+ HANDOFF-YYYY-MM-DD files
- Hard to find current status
- Repeated information across files

**Solution:**
1. Create consolidated summary with timeline
2. Delete dated handoffs (content in summary)
3. Keep 2-3 most recent if actively referenced

**Prevention:**
- Monthly: Archive handoffs >2 weeks old
- Quarterly: Create consolidated summary

### Pattern: Meta-Documentation Explosion

**Symptoms:**
- Multiple "IMPROVEMENTS", "ENHANCEMENTS", "SUMMARY" files
- Same topic covered in 3-5 files
- Total >1000 lines of meta-docs

**Solution:**
1. Read all related meta-docs
2. Extract key insights (what, why, impact)
3. Create single summary
4. Delete individual meta-docs

**Prevention:**
- Write insights directly in main docs
- Use changelog sections instead of separate files
- Consolidate monthly

### Pattern: Implementation Docs Mixed with Status

**Symptoms:**
- Valuable strategies in archive/
- Status updates mixed with reference material
- Hard to find implementation knowledge

**Solution:**
1. Create reference/ subdirectory
2. Organize by topic (not date)
3. Separate strategies from status
4. Archive only pure status updates

**Prevention:**
- Use implementation/reference/ for strategies
- Use implementation/archive/ for status
- Clear naming (strategy vs status)

### Pattern: Missing Navigation

**Symptoms:**
- Directories without README
- Hard to know what's in each directory
- Users ask "where do I find...?"

**Solution:**
1. Create README for each directory
2. Explain purpose and contents
3. Index key files
4. Link to related docs

**Prevention:**
- README required for new directories
- Update READMEs when structure changes
- Monthly README review

---

## Tools & Commands

### Quick Health Check

```bash
#!/bin/bash
# Run from /docs directory

echo "=== Documentation Health Check ==="
echo ""

echo "Active files:"
find . -type f -name "*.md" -not -path "*/archive/*" | wc -l

echo ""
echo "Archived files:"
find . -type f -name "*.md" -path "*/archive/*" | wc -l

echo ""
echo "README coverage:"
total_dirs=$(find . -maxdepth 1 -type d | wc -l)
readme_count=$(find . -maxdepth 1 -type d -exec test -f {}/README.md \; -print | wc -l)
echo "$readme_count/$total_dirs directories"

echo ""
echo "Old files (>30 days):"
find . -type f -name "*.md" -not -path "*/archive/*" -mtime +30 | wc -l

echo ""
echo "Large files (>100KB):"
find . -type f -name "*.md" -not -path "*/archive/*" -size +100k | wc -l

echo ""
echo "Recent activity (last 7 days):"
find . -type f -name "*.md" -not -path "*/archive/*" -mtime -7 | wc -l
```

### Archive Old Handoffs

```bash
#!/bin/bash
# Archive handoffs older than 2 weeks

CUTOFF_DATE=$(date -d "14 days ago" +%Y-%m-%d)
ARCHIVE_DIR="docs/handoff/archive/$(date +%Y-%m)"

mkdir -p "$ARCHIVE_DIR"

find docs/handoff -maxdepth 1 -name "HANDOFF-*.md" | while read file; do
  file_date=$(echo "$file" | grep -oP '\d{4}-\d{2}-\d{2}')
  if [[ "$file_date" < "$CUTOFF_DATE" ]]; then
    echo "Archiving: $file"
    mv "$file" "$ARCHIVE_DIR/"
  fi
done
```

### Find Consolidation Candidates

```bash
#!/bin/bash
# Find groups of related files that might be consolidated

echo "=== Potential Consolidation Candidates ==="
echo ""

echo "Meta-documentation (IMPROVEMENTS, ENHANCEMENTS, etc):"
find docs -name "*IMPROVEMENT*" -o -name "*ENHANCEMENT*" -o -name "*SUMMARY*" | grep -v archive

echo ""
echo "Status updates (COMPLETE, PROGRESS, etc):"
find docs -name "*COMPLETE*" -o -name "*PROGRESS*" -o -name "*STATUS*" | grep -v archive

echo ""
echo "Numbered sequences (might be completed):"
find docs -name "[0-9][0-9]-*.md" | grep -v archive | sort
```

### Generate README Coverage Report

```bash
#!/bin/bash
# Check which directories lack READMEs

echo "=== README Coverage Report ==="
echo ""

for dir in docs/*/; do
  dirname=$(basename "$dir")
  if [ -f "$dir/README.md" ]; then
    echo "✅ $dirname (README.md)"
  elif [ -f "$dir/00-overview.md" ]; then
    echo "⚠️  $dirname (00-overview.md only)"
  else
    echo "❌ $dirname (no README)"
  fi
done
```

---

## Lessons Learned

### What Worked Well

1. **Question before archiving recent files**
   - Asked about dependency-checks docs from yesterday
   - Discovered ongoing reference value
   - Prevented losing valuable content

2. **Create reference/ for completed strategies**
   - Separated temporal from valuable
   - Organized by topic, not date
   - Easy to find implementation knowledge

3. **Consolidate instead of archive meta-docs**
   - Preserved key insights
   - Eliminated redundancy
   - Much more navigable

4. **Progressive approach**
   - Start with obvious wins (dated handoffs)
   - Build confidence before bigger changes
   - Verify at each step

5. **Document as you go**
   - Created cleanup summary
   - Recorded decisions made
   - Future sessions can learn from this

### What to Avoid

1. **Blindly archiving recent work**
   - Always question if it has ongoing value
   - Recent ≠ temporal
   - Check with user if uncertain

2. **Archiving without consolidation**
   - Multiple related files → hard to find insights
   - Better to consolidate then archive summary
   - Preserve the "why" not just the "what"

3. **Moving files without updating READMEs**
   - Stale READMEs worse than no README
   - Update immediately after restructuring
   - Users rely on READMEs for navigation

4. **Deleting without checking references**
   - Files might be linked from elsewhere
   - Search for links before deleting
   - Keep in archive if any doubt

5. **Too much at once**
   - Easy to lose track
   - Verify incrementally
   - Can't undo bulk operations easily

### Decision Principles

1. **When in doubt, archive (don't delete)**
   - Archives are cheap (1.4M is fine)
   - Can always delete later
   - Can't recover deleted files

2. **Prefer consolidation over deletion**
   - Preserve insights and decisions
   - Single summary better than scattered info
   - 5 files → 1 file more valuable than → 0 files

3. **Organize by topic, not time (for reference)**
   - Time-based for archives (temporal)
   - Topic-based for reference (ongoing)
   - Makes knowledge easier to find

4. **Ask user about ambiguous cases**
   - Recent files that seem temporal
   - Files with unclear ongoing value
   - Better to confirm than guess wrong

5. **Maintain navigation at all costs**
   - README coverage > file reduction
   - Navigation more important than size
   - Users can't use what they can't find

---

## Next Session Plan

**Scheduled:** First week of December 2025

### Pre-Session Checklist

Run these commands before starting:

```bash
# 1. Health check
./docs/scripts/health-check.sh  # If we create this script

# 2. Find candidates
find docs -name "HANDOFF-2025-11-*" -mtime +14  # Handoffs >2 weeks
find docs -name "*COMPLETE*" -o -name "*PROGRESS*"  # Status docs
find docs -mtime +30 -not -path "*/archive/*"  # Old files
```

### Tasks for Next Session

#### High Priority (30 min)

1. **Update outdated root docs** (from Oct 14)
   - [ ] ALERT_SYSTEM.md - Add completeness alerts
   - [ ] TROUBLESHOOTING.md - Add recent patterns
   - [ ] BACKFILL_GUIDE.md - Add completeness integration

2. **Archive November handoffs** (if >2 weeks old)
   - [ ] Move dated handoffs to archive/2025-11/
   - [ ] Consider monthly consolidation if >10 files

#### Medium Priority (30 min)

3. **Check for new temporal docs**
   - [ ] Find status updates created in November
   - [ ] Archive completed rollout docs
   - [ ] Consolidate if 3+ related docs

4. **README maintenance**
   - [ ] Consider guides/README.md (currently has 00-overview)
   - [ ] Update any READMEs with stale file counts
   - [ ] Add any new directories created

#### Low Priority (Optional)

5. **Naming standardization**
   - [ ] Review SCREAMING_SNAKE_CASE files
   - [ ] Standardize if updating anyway
   - [ ] Not urgent - do opportunistically

6. **Cross-reference review**
   - [ ] Check for broken links
   - [ ] Add more cross-references
   - [ ] Update related docs sections

### Success Criteria

- [ ] <220 active markdown files
- [ ] >95% README coverage (maintain current level)
- [ ] No files >60 days old (except root guides)
- [ ] Archive organized by month
- [ ] Health report generated

### Time Budget

- Assessment: 15 minutes
- High priority tasks: 30 minutes
- Medium priority tasks: 30 minutes
- Verification & documentation: 15 minutes
- **Total: 90 minutes**

---

## Maintenance Schedule

### Monthly (First Week)

- [ ] Run health check
- [ ] Archive handoffs >2 weeks old
- [ ] Update root docs if needed
- [ ] Create monthly archive directory
- [ ] Generate health report

**Time:** 60-90 minutes

### Quarterly (January, April, July, October)

- [ ] Consolidate monthly handoffs into quarterly summary
- [ ] Review and update READMEs
- [ ] Check for consolidation opportunities
- [ ] Update this playbook with lessons learned
- [ ] Review archive organization

**Time:** 2-3 hours

### Annually (January)

- [ ] Archive previous year's quarterly summaries
- [ ] Review entire docs structure
- [ ] Update documentation standards
- [ ] Clean up old archives (>2 years)
- [ ] Major structural improvements

**Time:** 4-6 hours

---

## Metrics to Track

### Core Metrics

Track these every cleanup session:

| Metric | Target | Alert If |
|--------|--------|----------|
| Active files | <220 | >250 |
| README coverage | >95% | <90% |
| Archived files | N/A | Growing >10%/month |
| Old files (>30 days) | <10 | >20 |
| Large files (>100KB) | <5 | >10 |
| Recent updates (7 days) | >50% | <30% |

### Quality Metrics

| Metric | Target | Status |
|--------|--------|--------|
| Overall quality score | >4.5/5 | Currently 4.8/5 ✅ |
| Organization | 5/5 | ✅ |
| Discoverability | 5/5 | ✅ |
| Consistency | 4/5 | ⚠️ Can improve |

---

## Resources

### Related Documentation

- [Documentation Health Report](../2025-11-23-docs-health-report.md) - Current state
- [Cleanup Summary](../2025-11-23-documentation-cleanup-summary.md) - What we did
- [Documentation Guide](../DOCUMENTATION_GUIDE.md) - Standards
- [Navigation Guide](../NAVIGATION_GUIDE.md) - How docs are organized

### Templates

- [Cleanup Summary Template](../templates/cleanup-summary-template.md) - If we create it
- [Health Report Template](../templates/health-report-template.md) - If we create it

### Scripts (To Create)

- `docs/scripts/health-check.sh` - Quick health metrics
- `docs/scripts/archive-old-handoffs.sh` - Automated archiving
- `docs/scripts/find-consolidation-candidates.sh` - Find related files
- `docs/scripts/readme-coverage-check.sh` - README coverage report

---

## Updates to This Playbook

### Version History

**v1.0 - 2025-11-23**
- Initial creation after successful cleanup session
- Documented methodology and techniques used
- Created decision framework
- Established maintenance schedule

**Future updates:**
- Add after each major cleanup session
- Document new patterns discovered
- Update metrics and targets
- Refine decision framework

---

**Playbook Status:** ✅ Active and maintained
**Last Used:** 2025-11-23
**Next Review:** December 2025
**Effectiveness:** TBD (track over time)
