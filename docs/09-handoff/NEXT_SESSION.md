# Next Session Plan - Documentation Maintenance

**Created:** 2025-11-23
**For Session:** December 2025 (first week)
**Estimated Time:** 90 minutes
**Priority:** Medium (monthly maintenance)

---

## Quick Start

**Before you begin:** Read [Documentation Maintenance Playbook](documentation-maintenance-playbook.md) for full methodology.

**Context:** Last cleanup was 2025-11-23. Reduced 268 → 221 files, achieved 95.5% README coverage.

---

## Pre-Session Check (5 min)

Run these commands to assess current state:

```bash
cd /home/naji/code/nba-stats-scraper/docs

# 1. Count active files (target: <220)
find . -type f -name "*.md" -not -path "*/archive/*" | wc -l

# 2. Find files older than 30 days (target: <10)
find . -type f -name "*.md" -not -path "*/archive/*" -mtime +30 | wc -l

# 3. Find recent handoffs to archive (>14 days old)
find handoff/ -maxdepth 1 -name "HANDOFF-2025-11-*" -mtime +14

# 4. Check README coverage (target: >95%)
for dir in */; do
  if [ -f "$dir/README.md" ] || [ -f "$dir/00-overview.md" ]; then
    echo "✅ $dir"
  else
    echo "❌ $dir"
  fi
done | grep "❌" | wc -l  # Should be 0-1
```

---

## Tasks

### 🔴 High Priority (30 min)

#### 1. Update Outdated Root Docs (from Oct 14)

**Why:** Missing 6+ weeks of improvements (smart idempotency, completeness, etc.)

```bash
# Check last modified dates
ls -lh ALERT_SYSTEM.md TROUBLESHOOTING.md BACKFILL_GUIDE.md
```

**Action for each file:**
- [ ] **ALERT_SYSTEM.md** - Add completeness checking alerts
  - Read: `completeness/02-operational-runbook.md` for alert guidance
  - Add: Circuit breaker alerts, <90% completeness thresholds
  - Time: 15 min

- [ ] **TROUBLESHOOTING.md** - Add recent patterns and issues
  - Read: `operations/cross-phase-troubleshooting-matrix.md`
  - Add: Smart idempotency troubleshooting, completeness issues
  - Time: 10 min

- [ ] **BACKFILL_GUIDE.md** - Add completeness integration
  - Read: `completeness/01-quick-start.md`
  - Add: How completeness affects backfills, verification steps
  - Time: 10 min

**Verification:** Check that references are up-to-date with November work

#### 2. Archive November Handoffs (if applicable)

**Check if any handoffs are >2 weeks old:**

```bash
find handoff/ -maxdepth 1 -name "*.md" -mtime +14
```

**If found:**
```bash
mkdir -p handoff/archive/2025-11
# Review each file before moving
# Move to archive if pure status update
# Keep if actively referenced
```

**Decision:** Use [Decision Framework](documentation-maintenance-playbook.md#decision-framework)

---

### 🟡 Medium Priority (30 min)

#### 3. Check for New Temporal Docs

**Find status updates created since last cleanup:**

```bash
# Find files with status markers
find . -name "*COMPLETE*" -o -name "*PROGRESS*" -o -name "*STATUS*" | \
  grep -v archive | \
  xargs ls -lt | \
  head -20
```

**Action:**
- Review each file
- Archive if completed work
- Consolidate if 3+ related files on same topic

#### 4. README Maintenance

**Check for stale content:**

```bash
# Find READMEs that haven't been updated in 30+ days
find . -name "README.md" -not -path "*/archive/*" -mtime +30
```

**Action:**
- Update file counts if changed
- Add any new sections
- Fix broken links
- Update "last updated" dates

**Consider:** guides/README.md (currently has 00-overview.md instead)
- Option A: Rename 00-overview.md → README.md
- Option B: Create README.md pointing to 00-overview.md
- Option C: Leave as-is (functional but inconsistent)

---

### 🟢 Low Priority (Optional)

#### 5. Naming Standardization

**Only if updating files anyway:**

```bash
# Find SCREAMING_SNAKE_CASE files
find . -name "*.md" | grep -E "[A-Z_]{3,}" | grep -v README
```

**Action:**
- Standardize to lowercase-with-dashes when editing
- Not urgent - do opportunistically
- Update links if renaming

#### 6. Archive Organization Review

**Check archive sizes:**

```bash
du -sh */archive/ 2>/dev/null
```

**If any archive >500KB:**
- Consider consolidating into quarterly summary
- Compress old archives (>6 months)

---

## Success Criteria

After session, verify:

- [ ] Active files still <220
- [ ] No files >60 days old (except intentional root docs)
- [ ] README coverage maintained at >95%
- [ ] All November handoffs reviewed (archived or kept with reason)
- [ ] 3 root docs updated with November learnings
- [ ] Cleanup summary created documenting what was done

---

## Time Budget

| Task | Planned | Actual |
|------|---------|--------|
| Pre-session check | 5 min | _____ |
| Update root docs | 30 min | _____ |
| Archive handoffs | 10 min | _____ |
| Check temporal docs | 15 min | _____ |
| README maintenance | 15 min | _____ |
| Verification | 10 min | _____ |
| Documentation | 15 min | _____ |
| **Total** | **90 min** | **_____** |

---

## Post-Session

### 1. Create Cleanup Summary

```bash
# Copy template (or create new)
cat > docs/2025-12-XX-documentation-cleanup-summary.md << 'EOF'
# Documentation Cleanup Summary

**Date:** 2025-12-XX
**Time Spent:** ___ minutes

## What Was Done

### Archived
- X handoff files to handoff/archive/2025-11/
- X status docs to implementation/archive/

### Updated
- ALERT_SYSTEM.md - Added completeness alerts
- TROUBLESHOOTING.md - Added recent patterns
- BACKFILL_GUIDE.md - Added completeness integration

### Created
- [List any new docs]

## Metrics

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Active files | ___ | ___ | ___ |
| Archived files | ___ | ___ | ___ |
| README coverage | 95.5% | ___% | ___ |

## Issues Identified

- [List any issues found for future sessions]

## Next Session

- [Recommendations for next month]
EOF
```

### 2. Update Playbook

If you learned anything new:
- Add to [Lessons Learned](documentation-maintenance-playbook.md#lessons-learned)
- Update [Common Patterns](documentation-maintenance-playbook.md#common-patterns)
- Refine [Decision Framework](documentation-maintenance-playbook.md#decision-framework)

### 3. Update This Plan

Set up for next session (January 2026):
- Review quarterly tasks (Q1)
- Update dates
- Adjust tasks based on what was found

---

## Quick Reference Links

### Methodology
- [Documentation Maintenance Playbook](documentation-maintenance-playbook.md) - Full guide
- [Decision Framework](documentation-maintenance-playbook.md#decision-framework) - Archive/keep/consolidate
- [Common Patterns](documentation-maintenance-playbook.md#common-patterns) - Typical issues

### Current State
- [Health Report (2025-11-23)](../2025-11-23-docs-health-report.md) - Baseline metrics
- [Cleanup Summary (2025-11-23)](../2025-11-23-documentation-cleanup-summary.md) - What was done

### Standards
- [Documentation Guide](../DOCUMENTATION_GUIDE.md) - Writing standards
- [Navigation Guide](../NAVIGATION_GUIDE.md) - Organization principles

---

## Emergency: If Running Out of Time

**Minimum viable cleanup (30 min):**

1. Archive obvious dated handoffs (10 min)
```bash
mkdir -p handoff/archive/2025-11
mv handoff/HANDOFF-2025-11-* handoff/archive/2025-11/  # Review first!
```

2. Update one root doc (15 min)
- Pick TROUBLESHOOTING.md (most frequently used)
- Add recent patterns section
- Link to new docs

3. Quick verification (5 min)
```bash
# Verify file counts reasonable
find docs -name "*.md" -not -path "*/archive/*" | wc -l
```

**Done.** Schedule remaining tasks for next week.

---

## Notes Section

Use this space during the session to track decisions:

**Files Reviewed:**
-

**Archived:**
-

**Kept Active (with reason):**
-

**Issues Found:**
-

**Questions for User:**
-

---

**Plan Status:** ✅ Ready for December 2025
**Created:** 2025-11-23
**Last Updated:** 2025-11-23
**Next Review:** After December cleanup session
