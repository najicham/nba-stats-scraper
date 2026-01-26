# `/validate-daily` Claude Code Skill - COMPLETE ✅

**Date**: 2026-01-26
**Task**: Create Claude Code skill for daily orchestration validation
**Status**: ✅ Complete (ready for testing in next session)

---

## What Was Created

### 1. The Skill Itself

**Location**: `.claude/skills/validate-daily/SKILL.md`

**What it does**:
- Runs comprehensive daily validation of the NBA pipeline
- Checks all phases (2-5), data quality, spot checks, phase completion
- Intelligently investigates issues (not just a rigid script)
- Produces structured reports with severity classification (P1-P5)
- Adapts based on findings and provides actionable recommendations

**How to use**:
```bash
# In Claude Code, simply run:
/validate-daily
```

### 2. Comprehensive Creation Guide

**Location**: `docs/02-operations/VALIDATE-DAILY-SKILL-CREATION-GUIDE.md`

**Contains**:
- Complete research process (how the skill was designed)
- Design decisions and rationale
- Implementation details and architecture
- Testing results (manual validation on 2026-01-26)
- Usage guide with examples
- Known limitations
- Future enhancement ideas
- Appendices with references

**Purpose**: For future sessions to understand, maintain, and extend the skill.

### 3. Updated Operations Runbook

**Location**: `docs/02-operations/daily-operations-runbook.md`

**Changes**:
- Added prominent section recommending `/validate-daily` skill
- Quick start guide for using the skill
- Example output format
- When to use (pre-game vs post-game)
- Link to creation guide for deeper details

---

## Research Conducted

### Explore Agent Deep Dive

Used Task tool with `subagent_type=Explore` to thoroughly analyze:

1. **Validation Scripts**:
   - `scripts/validate_tonight_data.py` - Main validator (10 checks)
   - `scripts/spot_check_data_accuracy.py` - Data accuracy (6 check types)
   - `bin/monitoring/daily_health_check.sh` - Health checks

2. **Documentation**:
   - `docs/06-testing/SPOT-CHECK-SYSTEM.md` - Spot check architecture
   - `docs/02-operations/` - Operations runbooks
   - `docs/09-handoff/2026-01-26-SESSION-33-*.md` - Recent findings

3. **Key Insights**:
   - Validation thresholds and what "good" looks like
   - Common failure patterns and investigation workflows
   - Timing awareness (pre-game vs post-game expectations)
   - Known issues and how to distinguish from new problems
   - Severity classification system

**Result**: Comprehensive understanding encoded into the skill.

---

## Design Highlights

### Intelligent, Not Rigid

The skill provides **guidance**, not **commands**:
- Starting point: Standard validation workflow
- Knowledge base: Thresholds, patterns, known issues
- Investigation guidance: How to dig deeper
- BUT Claude still uses judgment to adapt

### Context-Aware

The skill understands:
- **Timing**: Pre-game vs post-game expectations differ
- **Known issues**: Pattern matching (e.g., "stale dependency false positive")
- **Severity**: P1-P5 classification based on actual impact
- **Root causes**: Traces issues backward through pipeline

### Actionable Output

Every validation produces:
- Summary table (quick status overview)
- Issues with severity classification
- Specific remediation commands
- Unusual observations
- Prioritized action items

---

## Testing Results

### Manual Validation (2026-01-26 14:07 PST)

**✅ Successfully Detected**:
1. 🔴 **P1 Critical**: BigQuery quota exceeded blocking Phase 3
2. 🔴 **P1 Critical**: Data quality - usage_rate 35.3% (threshold: 90%)
3. 🔴 **P1 Critical**: Spot check failures - 50% accuracy (threshold: 95%)
4. 🟡 **P2 High**: Stale dependencies (multiple processors)
5. 🟠 **P3 Medium**: API export stale (expected pre-game)

**✅ Demonstrated**:
- Context awareness (pre-game timing correctly noted)
- Root cause analysis (quota → processor failures → data quality)
- Log investigation (Cloud Run logs analyzed)
- Severity classification (P1-P5 applied correctly)
- Actionable recommendations (specific commands provided)

**See**: Full validation report in session transcript (search "Daily Orchestration Validation - 2026-01-26")

---

## Known Limitations

### 1. Session Restart Required

**Issue**: Skill not auto-discovered until Claude Code session restart

**Why**: Skills loaded at session initialization, not dynamically

**Workaround**:
- Close and reopen Claude Code
- Skill will be available in next session

### 2. Current Session Can't Test Invocation

**Issue**: Couldn't test `/validate-daily` command directly (discovery issue)

**What was tested**: Ran skill logic manually to validate behavior

**Next session**: Will be able to invoke `/validate-daily` directly

### 3. Future Enhancements Identified

See "Future Enhancements" section in creation guide for ideas like:
- Multi-file skill structure
- Trend analysis (historical validation results)
- Auto-fix safe issues
- Alert integration (Slack/email)
- Dashboard integration

---

## Next Session Action Items

### Immediate (First Thing)

1. **Test Skill Invocation**
   ```bash
   /validate-daily
   ```
   - Verify skill is auto-discovered
   - Confirm it runs the full validation workflow
   - Check output format matches expectations

2. **Run on Different Scenarios**
   - Pre-game validation (afternoon)
   - Post-game validation (next morning)
   - During an actual issue
   - On an off-day (no games scheduled)

3. **Refine Based on Usage**
   - Is output too verbose/too terse?
   - Are investigations deep enough?
   - Are recommendations actionable?
   - Any missing validations?

### Near-Term Improvements

1. **Add BigQuery Schema Reference**
   - Manual queries sometimes failed on schema assumptions
   - Add common table schemas to skill or reference doc

2. **Consider Multi-File Structure**
   - If skill gets too large (>15KB), split into:
     - `SKILL.md` - Main orchestration
     - `runbooks/investigation.md` - Deep investigation procedures
     - `reference/schemas.md` - BigQuery schemas

3. **Create Additional Skills**
   - `/validate-phase3` - Focused Phase 3 investigation
   - `/investigate-spot-checks` - Deep dive on spot check failures
   - `/check-quotas` - BigQuery quota monitoring

### Long-Term Enhancements

1. **Trend Analysis**: Store validation results, detect degradation patterns
2. **Auto-Fix Mode**: Permission-based auto-remediation of safe issues
3. **Alert Integration**: Slack/email for P1 issues
4. **Dashboard**: Grafana visualization of validation metrics over time

---

## File Summary

### Created Files

1. `.claude/skills/validate-daily/SKILL.md` (10,624 bytes)
   - Main skill definition
   - Frontmatter, validation workflow, investigation guidance, known issues

2. `docs/02-operations/VALIDATE-DAILY-SKILL-CREATION-GUIDE.md` (26,752 bytes)
   - Comprehensive creation documentation
   - Research, design, implementation, testing
   - Usage guide, limitations, future enhancements
   - For review and maintenance

3. `docs/09-handoff/2026-01-26-VALIDATE-DAILY-SKILL-COMPLETE.md` (this file)
   - Summary for next session
   - What was created and why
   - Testing results and next steps

### Modified Files

1. `docs/02-operations/daily-operations-runbook.md`
   - Added `/validate-daily` skill section at top
   - Recommended over manual validation
   - Quick start guide and example output

---

## Questions for Review

When reviewing this work, consider:

1. **Skill Effectiveness**: Does the skill provide value over manual validation?
2. **Investigation Depth**: Is guidance sufficient for novel issues?
3. **Output Clarity**: Is the report format actionable?
4. **Knowledge Completeness**: Are there validation aspects missing?
5. **Documentation Quality**: Is the creation guide useful for maintenance?
6. **Severity System**: Is P1-P5 classification appropriate?
7. **Future Direction**: Which enhancements should be prioritized?

---

## Success Metrics

**✅ Skill Created**: Correctly formatted in `.claude/skills/validate-daily/`

**✅ Comprehensive Research**: Explore agent deep dive completed

**✅ Knowledge Encoded**: Thresholds, patterns, workflows documented

**✅ Tested Manually**: Validation logic verified with real pipeline state

**✅ Documentation Complete**: Creation guide and usage docs written

**✅ Operations Updated**: Daily runbook references new skill

**⏳ Pending Testing**: Skill invocation in next session (after discovery)

---

## Conclusion

The `/validate-daily` Claude Code skill is **complete and ready for use**.

**What makes this skill valuable**:
1. **Encapsulates expertise**: Deep validation system knowledge in reusable form
2. **Intelligent investigation**: Adapts to findings, not rigid execution
3. **Context-aware**: Understands timing, known issues, severity
4. **Actionable**: Every issue has specific remediation steps
5. **Consistent**: Structured reports, priority classification
6. **Documented**: Comprehensive creation guide for maintenance

**Next session**: Test skill invocation and refine based on real-world usage.

---

**Session Complete**: 2026-01-26
**Ready for Handoff**: Yes
**Documentation**: Complete
**Next Action**: `/validate-daily` in new Claude Code session
