# Claude Code Skills - Handoff for Next Session

**Date**: 2026-01-26
**Session**: Validation Skills Development - Complete
**Status**: ✅ Ready for Testing & Enhancement
**Next Session Goal**: Test skills, gather feedback, implement enhancements

---

## Quick Start for New Session

### What You're Working On

Two Claude Code skills for NBA stats scraper data quality assurance:
1. **`/validate-daily`** - Daily pipeline health check (today's data)
2. **`/validate-historical`** - Historical data integrity audit (date ranges)

### First Actions

```bash
# 1. Test the skills exist
ls -la .claude/skills/validate-daily/SKILL.md
ls -la .claude/skills/validate-historical/SKILL.md

# 2. Try invoking them (interactive mode)
/validate-daily
/validate-historical

# 3. Read the documentation
docs/02-operations/VALIDATE-DAILY-SKILL-CREATION-GUIDE.md
docs/09-handoff/2026-01-26-VALIDATE-HISTORICAL-SKILL-COMPLETE.md
```

---

## Executive Summary

### What Was Accomplished This Session

**Created**: 2 comprehensive validation skills
- `/validate-daily` (~12KB) - 5 validation phases, quota monitoring, known issues
- `/validate-historical` (~23KB) - 9 validation modes, cascade impact assessment

**Fixed**: 1 critical production bug
- PlayerGameSummaryProcessor registry attribute error (Phase 3)

**Enhanced**: Both skills with interactive mode
- Ask multiple-choice questions when no parameters provided
- Discover features without reading docs

**Documented**: 7 comprehensive guides
- Creation guides, testing results, fixes applied, interactive mode

### Current State

**Both skills are**:
- ✅ Fully implemented with comprehensive validation logic
- ✅ Interactive mode enabled (ask questions if no parameters)
- ✅ Documented with creation guides and usage examples
- ✅ Include BigQuery schema references
- ✅ Provide remediation commands in correct dependency order
- ⏳ **Not yet tested in actual usage** (need new session for skill discovery)

---

## Skills Overview

### `/validate-daily` - Daily Pipeline Health

**Purpose**: Validate today's orchestration pipeline is ready for predictions

**When to Use**:
- Pre-game (5 PM ET): Check data ready before games
- Post-game (6 AM ET next day): Verify yesterday's games processed

**Key Features**:
- Phase 0: Proactive BigQuery quota check (NEW)
- Phase 1-5: Full pipeline validation (health check → predictions)
- Spot checks: Data accuracy verification (95% threshold)
- Known issues: 7 documented patterns (quota, stale deps, registry bug)
- Interactive mode: Ask what to validate if no params

**Location**: `.claude/skills/validate-daily/SKILL.md`

**Invocation**:
```bash
/validate-daily                    # Interactive mode (asks questions)
/validate-daily yesterday          # Post-game check
/validate-daily today              # Pre-game check
/validate-daily 2026-01-26         # Specific date
```

---

### `/validate-historical` - Historical Data Integrity

**Purpose**: Audit historical data over date ranges, find gaps, assess cascade impacts

**When to Use**:
- Weekly health check (last 7-14 days)
- After pipeline failures (identify and backfill gaps)
- Before/after backfills (verify fixes)
- Investigating prediction quality issues

**Key Features**:
- **9 Validation Modes**:
  1. Standard - Gap detection with quality trends
  2. Deep check - Recalculate rolling averages, verify accuracy
  3. Player-specific - Single player data deep dive
  4. Game-specific - Single game all-players validation
  5. Verify backfill - Confirm gap filled, cascade resolved
  6. Coverage only - Quick completeness scan
  7. Anomalies - Statistical outlier detection
  8. Compare sources - Cross-source reconciliation
  9. Export - Save results to JSON

- **Cascade Impact Assessment**: Understands L5 (5 days), L10 (10 days), up to 21 days forward
- **Remediation Plans**: Phase 3 → Phase 4 → Verify (correct dependency order)
- **Interactive Mode**: Ask date range + mode if no params

**Location**: `.claude/skills/validate-historical/SKILL.md`

**Invocation**:
```bash
/validate-historical               # Interactive (asks date range + mode)
/validate-historical 7             # Last 7 days, standard mode
/validate-historical --deep-check 2026-01-18
/validate-historical --player "LeBron James"
/validate-historical --game "LAL vs GSW 2026-01-25"
/validate-historical --verify-backfill 2026-01-18
```

---

## File Locations

### Skills
```
.claude/skills/
├── validate-daily/
│   └── SKILL.md              (12KB - 5 phases, interactive mode)
└── validate-historical/
    └── SKILL.md              (23KB - 9 modes, cascade assessment)
```

### Documentation
```
docs/02-operations/
├── VALIDATE-DAILY-SKILL-CREATION-GUIDE.md     (27KB - comprehensive)
└── daily-operations-runbook.md                (updated with skill refs)

docs/09-handoff/
├── 2026-01-26-VALIDATE-DAILY-SKILL-COMPLETE.md
├── 2026-01-26-VALIDATE-DAILY-REVIEW.md
├── 2026-01-26-VALIDATE-DAILY-ENHANCEMENTS.md
├── 2026-01-26-VALIDATE-HISTORICAL-SKILL-COMPLETE.md
├── 2026-01-26-SKILLS-INTERACTIVE-MODE.md
├── 2026-01-26-SKILLS-FIXES-APPLIED.md
└── 2026-01-26-SKILLS-NEXT-SESSION-HANDOFF.md  (this file)
```

### Production Code
```
data_processors/analytics/player_game_summary/
└── player_game_summary_processor.py           (registry bug FIXED)
```

---

## Testing Status

### What Was Tested

**Manual Validation** (this session):
- ✅ `/validate-daily` logic tested manually (found 3 P1 bugs!)
- ✅ Production bug fixed (PlayerGameSummaryProcessor)
- ✅ BigQuery queries validated
- ✅ Remediation scripts verified to exist

**What Detected** (real production issues):
1. 🔴 P1: BigQuery quota exceeded (partition modifications)
2. 🔴 P1: PlayerGameSummaryProcessor registry attribute bug
3. 🔴 P1: Usage rate coverage 35% (caused by above two)

### What Needs Testing

**Skill Invocation** (requires new session):
- ⏳ `/validate-daily` command discovery (skill not loaded in current session)
- ⏳ `/validate-historical` command discovery
- ⏳ Interactive mode questions appear correctly
- ⏳ All 9 modes of validate-historical work

**Real-World Usage**:
- ⏳ Run on actual data gaps
- ⏳ Test deep-check mode accuracy
- ⏳ Verify backfill mode after actual backfill
- ⏳ Export mode produces valid JSON
- ⏳ Game-specific mode on real game

---

## Known Issues & Limitations

### Skill Discovery Caching

**Issue**: Skills created this session won't be discovered until Claude Code restart

**Workaround**:
1. Exit Claude Code
2. Restart Claude Code
3. Skills will auto-discover from `.claude/skills/`

**Verification**:
```bash
# In new session, just type:
/validate-daily
# Should invoke skill, not show "Unknown skill"
```

### Interactive Mode Behavior

**Expected**: If user provides parameters, questions are skipped

**Example**:
```bash
/validate-historical --deep-check 2026-01-18
# Should NOT ask questions, proceed directly with deep check
```

**If questions asked anyway**: Skill detection logic needs adjustment

### BigQuery Query Performance

**Limitation**: Some queries (especially for 30+ days) may be slow

**Mitigation**: Skill warns user for large ranges, suggests `--coverage-only`

### Manual Command Execution

**Limitation**: Skills recommend commands but don't execute them (by design)

**User must**:
1. Read remediation commands
2. Copy and paste to terminal
3. Run manually

**Future Enhancement**: Auto-execute with approval (see Future Work section)

---

## Important Context & Knowledge

### The Data Cascade Problem

**Critical concept** for validate-historical:

```
Missing data on 2026-01-18:
  ↓
Affects rolling averages:
  - L5 averages: 5 days forward (2026-01-19 → 01-23)
  - L10 averages: 10 days forward (2026-01-19 → 01-28)
  - Longer features: up to 21 days forward
  ↓
Predictions degraded for affected dates
```

**Why it matters**: A single day's gap can corrupt 5-21 days of downstream predictions

### Cache Date Semantics

**CRITICAL**: `cache_date = game_date - 1`

**Meaning**: Cache for game on 2026-01-26 has `cache_date = 2026-01-25`

**Query filter**: `WHERE game_date < '2026-01-25'` (NOT `<=`)

**This trips up**: Deep check validation queries

### Severity Classification (P1-P5)

Both skills use consistent severity:
- **P1 Critical**: Production down, predictions blocked (immediate)
- **P2 High**: Data quality degraded (1 hour)
- **P3 Medium**: Non-blocking issues (4 hours)
- **P4 Low**: Minor issues (next day)
- **P5 Info**: Informational only

### Remediation Dependency Order

**ALWAYS**: Phase 3 → Phase 4 → Verify

```bash
# CORRECT order:
python scripts/backfill_player_game_summary.py --date 2026-01-18        # Phase 3
python scripts/regenerate_player_daily_cache.py --start-date 2026-01-18 # Phase 4
python scripts/spot_check_data_accuracy.py --date 2026-01-19            # Verify

# WRONG order (Phase 4 before Phase 3):
python scripts/regenerate_player_daily_cache.py --start-date 2026-01-18 # ❌ Won't work
python scripts/backfill_player_game_summary.py --date 2026-01-18
```

**Why**: Phase 4 depends on Phase 3 data existing

---

## Next Steps & Priorities

### High Priority (This Week)

#### 1. Test Skills in New Session

**Tasks**:
- [ ] Restart Claude Code to discover skills
- [ ] Test `/validate-daily` invocation
- [ ] Test `/validate-historical` invocation
- [ ] Verify interactive mode works (asks questions)
- [ ] Test at least 3 modes of validate-historical

**Success Criteria**:
- Skills are discovered (no "Unknown skill" error)
- Interactive mode asks appropriate questions
- Validation runs without errors
- Output format matches expectations

#### 2. Real-World Validation Run

**Tasks**:
- [ ] Run `/validate-daily` on actual pipeline
- [ ] Run `/validate-historical 7` for last week
- [ ] Document any issues found
- [ ] Verify remediation commands work

**Success Criteria**:
- Skills detect real issues (if any exist)
- Recommended commands execute successfully
- Output is clear and actionable

#### 3. Gather User Feedback

**Questions to Answer**:
- Is interactive mode helpful or annoying?
- Are validation modes correctly named?
- Is output too verbose or too terse?
- Are remediation commands correct?
- What features are missing?

### Medium Priority (Next Week)

#### 4. Enhance Based on Feedback

**Potential Improvements**:
- Add more known issues to validate-daily
- Refine sample size recommendations
- Add shortcuts for common workflows
- Improve error messages

#### 5. Create Additional Skills

**Candidates**:
- `/investigate-gap <date>` - Focused gap investigation
- `/check-quotas` - BigQuery quota monitoring only
- `/validate-phase3` - Deep dive into Phase 3 analytics
- `/compare-dates <date1> <date2>` - Side-by-side comparison

#### 6. Integration & Automation

**Ideas**:
- CI/CD integration (run validation in GitHub Actions)
- Slack alerts for P1/P2 issues
- Weekly automated validation email
- Dashboard integration (Grafana)

### Low Priority (Future)

#### 7. Advanced Features

- Trend analysis (store validation history)
- ML-based anomaly detection
- Auto-fix mode (with approval)
- Multi-file skill structure (if >15KB)

#### 8. Documentation Improvements

- Video walkthrough of skills
- Troubleshooting FAQ
- Common workflows quick reference
- Skills reference guide (all skills in one doc)

---

## Testing Guide for Next Session

### Test Plan: Validate-Daily

#### Test 1: Basic Invocation
```bash
/validate-daily
```
**Expected**:
- Questions appear (What to validate? How thorough?)
- User can select options
- Validation runs based on selections

#### Test 2: Direct Invocation
```bash
/validate-daily yesterday
```
**Expected**:
- No questions (parameters provided)
- Runs post-game validation for yesterday
- Shows Phase 0-5 results

#### Test 3: Specific Date
```bash
/validate-daily 2026-01-25
```
**Expected**:
- Validates specific date
- Appropriate timing expectations (pre-game vs post-game)

#### Test 4: Error Handling
```bash
/validate-daily invalid-date
```
**Expected**:
- Claude asks for clarification or parses as best possible
- Graceful handling, not crash

---

### Test Plan: Validate-Historical

#### Test 5: Interactive Mode
```bash
/validate-historical
```
**Expected**:
- Q1: What date range? (7 options)
- Q2: What type of validation? (7 options)
- Q3: (conditional) Additional questions based on mode

#### Test 6: Standard Validation
```bash
/validate-historical 7
```
**Expected**:
- Checks last 7 days
- Shows completeness table
- Identifies gaps (if any)
- Calculates cascade impact
- Provides remediation

#### Test 7: Deep Check Mode
```bash
/validate-historical --deep-check 2026-01-25
```
**Expected**:
- Recalculates rolling averages from raw data
- Compares to cached values
- Reports mismatches
- Recommends 10-15 samples (1-3 day range)

#### Test 8: Player-Specific Mode
```bash
/validate-historical --player "LeBron James"
```
**Expected**:
- Shows LeBron's game-by-game data
- Pipeline stage completion for each game
- Rolling average integrity check

#### Test 9: Game-Specific Mode (NEW)
```bash
/validate-historical --game "LAL vs GSW 2026-01-25"
```
**Expected**:
- Identifies game
- Shows all players with completeness
- Verifies team totals
- Reports issues

#### Test 10: Verify Backfill Mode
```bash
# After running a backfill:
python scripts/backfill_player_game_summary.py --date 2026-01-18

# Then verify:
/validate-historical --verify-backfill 2026-01-18
```
**Expected**:
- Confirms 2026-01-18 data complete
- Checks downstream dates (5-21 days)
- Verifies cascade resolved
- Spot check accuracy back to >95%

---

## How to Extend the Skills

### Adding a New Validation Check

**To `/validate-daily`**:

1. Add check to appropriate Phase section:
   ```markdown
   ### Phase X: New Check Name

   ```bash
   # Command to run
   ```

   **What to look for**:
   - Threshold: X
   - Good: Y
   - Critical: Z
   ```

2. Update Known Issues if relevant:
   ```markdown
   8. **New Issue Pattern**
      - Symptom: ...
      - Impact: ...
      - Fix: ...
   ```

3. Test the new check manually

**To `/validate-historical`**:

1. Add new mode section:
   ```markdown
   ## Mode X: New Mode Name (`--flag`)

   **When**: ...
   **Purpose**: ...

   ### Workflow
   [Steps and queries]
   ```

2. Update interactive mode Question 2 to include new mode

3. Update mode summary table

### Adding Known Issues

**Pattern**:
```markdown
N. **Issue Name** [✅ FIXED / ⚠️ WATCH / 🔴 ACTIVE]
   - Symptom: What error message appears
   - Impact: What breaks
   - Root cause: Technical explanation
   - Fix: Remediation steps or status
   - Status: When fixed, who fixed it
```

**Add to**: Known Data Quality Issues section

### Adding BigQuery Queries

**Best Practices**:
1. Include full query (copy-pasteable)
2. Use project placeholder: `nba-props-platform`
3. Add comments explaining key parts
4. Show expected output format
5. Note performance (fast vs slow)

---

## Common Issues & Solutions

### Issue: "Unknown skill: validate-daily"

**Cause**: Skills not loaded in current session

**Fix**:
```bash
# Exit and restart Claude Code
# OR verify skill file exists:
ls .claude/skills/validate-daily/SKILL.md
```

### Issue: Interactive mode doesn't ask questions

**Cause**: User provided parameters, questions skipped (by design)

**Fix**: Invoke without parameters:
```bash
/validate-daily           # Not: /validate-daily yesterday
```

### Issue: BigQuery queries fail

**Cause**: Schema assumptions or missing tables

**Fix**:
1. Check schema reference in skill
2. Verify table exists:
   ```bash
   bq show nba-props-platform:nba_analytics.player_game_summary
   ```
3. Update query if schema changed

### Issue: Remediation commands don't work

**Cause**: Script paths wrong or scripts don't exist

**Fix**:
1. Verify scripts exist:
   ```bash
   ls scripts/backfill_player_game_summary.py
   ls scripts/regenerate_player_daily_cache.py
   ```
2. If missing, use processor directly:
   ```bash
   python -m data_processors.analytics.player_game_summary --date 2026-01-18
   ```

---

## Key Decisions & Rationale

### Why Interactive Mode?

**Problem**: Users forget flags, modes, options

**Solution**: Ask multiple-choice questions when no parameters

**Trade-off**: Extra clicks for new users vs memorization for power users

**Result**: Both paths supported (interactive or direct invocation)

### Why Two Separate Skills?

**Alternative**: One mega-skill `/validate` with all modes

**Chosen**: Separate skills because:
- Different use cases (daily vs historical)
- Different timing (routine vs ad-hoc)
- Different complexity (moderate vs high)
- Easier to discover

### Why P1-P5 Severity?

**Alternative**: Just "Error" vs "Warning"

**Chosen**: 5 levels because:
- Aligns with SLA response times
- Prevents "everything is critical" fatigue
- Guides prioritization
- Industry standard (incident management)

### Why No Auto-Execution?

**Alternative**: Skills could run backfill commands automatically

**Chosen**: Recommend but don't execute because:
- Safety (no accidental production changes)
- Transparency (user sees what will run)
- Approval flow (user decides when)
- Trust building (not too aggressive)

**Future**: Could add with explicit approval prompts

---

## Success Metrics

### Skills Are Successful When:

**Adoption**:
- [ ] Used in weekly operations routine
- [ ] Mentioned in runbooks as standard procedure
- [ ] Other team members learn and use them

**Effectiveness**:
- [ ] Detect issues before they impact predictions
- [ ] Reduce time to identify gaps (minutes vs hours)
- [ ] Remediation commands work first time

**Quality**:
- [ ] Output is clear and actionable
- [ ] Fewer "what does this mean?" questions
- [ ] Users trust the severity classifications

**Maintenance**:
- [ ] Easy to add new validation checks
- [ ] Known issues stay updated
- [ ] Documentation kept current

---

## Resources & References

### Essential Reading

1. **Skill Creation Guide**:
   - `docs/02-operations/VALIDATE-DAILY-SKILL-CREATION-GUIDE.md`
   - Comprehensive - read first for deep understanding

2. **Testing Results**:
   - `docs/09-handoff/2026-01-26-VALIDATE-DAILY-REVIEW.md`
   - Real-world validation that found 3 P1 bugs

3. **Interactive Mode**:
   - `docs/09-handoff/2026-01-26-SKILLS-INTERACTIVE-MODE.md`
   - How questions work, UX design decisions

4. **Fixes Applied**:
   - `docs/09-handoff/2026-01-26-SKILLS-FIXES-APPLIED.md`
   - 6 improvements from review feedback

### Related Systems

**Validation Scripts**:
- `scripts/validate_tonight_data.py` - Main validation logic
- `scripts/spot_check_data_accuracy.py` - Data accuracy verification
- `bin/monitoring/daily_health_check.sh` - Health check script

**Backfill Scripts**:
- `scripts/backfill_player_game_summary.py` - Phase 3 regeneration
- `scripts/regenerate_player_daily_cache.py` - Phase 4 regeneration

**Processors**:
- `data_processors/analytics/player_game_summary/` - Phase 3
- `data_processors/precompute/player_daily_cache/` - Phase 4

### Claude Code Docs

**Skill Documentation**:
- [Claude Code Guide] - Search for skill creation when available
- Frontmatter format: `name`, `description`, optional `disable-model-invocation`
- Directory structure: `.claude/skills/<name>/SKILL.md`

**AskUserQuestion Tool**:
- Multiple-choice questions
- "Other" option always available
- Up to 4 questions
- Multi-select supported (not used in these skills)

---

## FAQ for New Session

### Q: Where should I start?

**A**:
1. Read this handoff (you are here)
2. Test skill invocation: `/validate-daily` and `/validate-historical`
3. Run real validation: `/validate-historical 7`
4. Document findings and improvement ideas

### Q: What if skills don't work?

**A**:
1. Verify files exist: `ls .claude/skills/*/SKILL.md`
2. Check file format (frontmatter correct?)
3. Restart Claude Code for skill discovery
4. Try manual invocation with Skill tool

### Q: Should I add more features or fix bugs?

**A**:
- **First**: Test existing features, gather feedback
- **Then**: Fix critical bugs (P1/P2)
- **Finally**: Add enhancements based on real needs

### Q: How do I know if cascade impact is correct?

**A**: Check these queries work:
```sql
-- Should show games used in rolling average
SELECT game_date FROM nba_analytics.player_game_summary
WHERE player_lookup = 'lebronjames'
  AND game_date < '2026-01-25'
ORDER BY game_date DESC LIMIT 5;

-- Should show features affected by gap
SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2
WHERE DATE('2026-01-18') IN UNNEST(historical_completeness.contributing_game_dates);
```

### Q: Can I change skill structure?

**A**: Yes, but:
- Keep backward compatibility (old invocations still work)
- Update documentation when changing
- Test interactive mode after structure changes
- Consider splitting to multi-file if >15KB

### Q: What should I NOT do?

**A**: Don't:
- Remove validation checks without good reason
- Change severity classification (P1-P5 is standard)
- Auto-execute commands without approval
- Skip testing before deploying to docs

---

## Session Handoff Checklist

### For Reviewer (Next Session)

**Before Starting**:
- [ ] Read this handoff document
- [ ] Read validate-daily creation guide
- [ ] Understand cascade problem concept
- [ ] Review P1-P5 severity system

**Initial Testing**:
- [ ] Verify skills exist and load
- [ ] Test interactive mode (both skills)
- [ ] Run one real validation
- [ ] Check output format

**Gather Feedback**:
- [ ] Is output clear?
- [ ] Are modes well-named?
- [ ] Are remediation commands correct?
- [ ] What's missing?

**Document Findings**:
- [ ] Create testing results doc
- [ ] List bugs found
- [ ] Suggest improvements
- [ ] Prioritize next steps

### For Future Sessions

**Maintenance**:
- [ ] Keep known issues updated
- [ ] Add new validation checks as needed
- [ ] Update BigQuery schemas if changed
- [ ] Refresh examples with current dates

**Enhancement**:
- [ ] Implement high-priority improvements
- [ ] Create additional skills if valuable
- [ ] Integrate with automation (CI/CD, Slack)
- [ ] Build trend tracking

**Documentation**:
- [ ] Update runbooks with skill usage
- [ ] Create troubleshooting guide
- [ ] Record common workflows
- [ ] Maintain handoff docs

---

## Conclusion

Two comprehensive validation skills are ready for testing:

**`/validate-daily`**: Daily health checks, quota monitoring, known issues
**`/validate-historical`**: Gap detection, cascade assessment, 9 validation modes

**Both have**: Interactive mode, BigQuery schemas, remediation commands

**Next step**: Test in new session, gather feedback, enhance based on real usage

**Success looks like**: Skills become standard part of daily operations, catch issues before they impact predictions, save time in investigations

---

**Session Complete**: 2026-01-26
**Skills Created**: 2 (validate-daily, validate-historical)
**Bugs Fixed**: 1 (PlayerGameSummaryProcessor)
**Documentation**: 7 comprehensive guides
**Status**: ✅ Ready for Testing
**Next Session**: Test, gather feedback, iterate

---

**Good luck! The skills are comprehensive and well-documented. Focus on real-world testing first, then enhance based on actual usage patterns.** 🚀
