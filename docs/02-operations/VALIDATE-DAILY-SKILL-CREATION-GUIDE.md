# `/validate-daily` Claude Code Skill - Creation Guide

**Created**: 2026-01-26
**Session**: Task - Create Claude Code skill for daily orchestration validation
**Status**: ✅ Complete (pending session restart for discovery)

---

## Table of Contents

1. [Overview](#overview)
2. [Research Phase](#research-phase)
3. [Design Decisions](#design-decisions)
4. [Implementation](#implementation)
5. [Skill Architecture](#skill-architecture)
6. [Testing & Validation](#testing--validation)
7. [Usage Guide](#usage-guide)
8. [Known Limitations](#known-limitations)
9. [Future Enhancements](#future-enhancements)

---

## Overview

### What is `/validate-daily`?

A Claude Code skill that performs comprehensive daily validation of the NBA stats scraper orchestration pipeline. Unlike a rigid script, this skill provides intelligent guidance to Claude for investigating issues adaptively.

### Why Create This Skill?

**Problem**: Daily validation involves:
- Running multiple validation scripts
- Checking phase completion across different systems (Firestore, BigQuery)
- Interpreting complex error patterns
- Classifying severity
- Investigating root causes
- Providing actionable recommendations

**Solution**: Encapsulate deep domain knowledge into a reusable skill that:
- Runs standard checks systematically
- Adapts investigation based on findings
- Applies context awareness (timing, known issues)
- Produces consistent, actionable reports

### Key Design Philosophy

**"Intelligent Orchestrator, Not Rigid Script"**

The skill provides:
- **Starting point**: Standard validation workflow
- **Knowledge base**: Known issues, thresholds, failure patterns
- **Investigation guidance**: How to dig deeper when issues found
- **Output structure**: Consistent reporting format

But Claude still uses judgment to:
- Adapt based on what's discovered
- Investigate new error patterns
- Distinguish expected vs unexpected behavior
- Prioritize issues by impact

---

## Research Phase

### Step 1: Explore Agent Investigation

Before writing the skill, I used the **Explore agent** (Task tool with `subagent_type=Explore`) to deeply understand the validation system.

**Files Analyzed**:
1. `scripts/validate_tonight_data.py` - Main validation orchestrator
2. `scripts/spot_check_data_accuracy.py` - Data accuracy verification
3. `bin/monitoring/daily_health_check.sh` - Health check script
4. `docs/06-testing/SPOT-CHECK-SYSTEM.md` - Spot check architecture
5. `docs/02-operations/` - Operations runbooks
6. `docs/09-handoff/2026-01-26-SESSION-33-*.md` - Recent findings

**Key Insights Discovered**:

#### Validation Exit Codes
- `0` = All checks passed (no ISSUES)
- `1` = At least one ISSUE found (CRITICAL/ERROR severity)
- ISSUES vs WARNINGS distinction critical

#### Data Quality Thresholds
| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| Spot Check Accuracy | ≥95% | 90-94% | <90% |
| Minutes Played Coverage | ≥90% | 80-89% | <80% |
| Usage Rate Coverage | ≥90% | 80-89% | <80% |
| Prediction Coverage | ≥90% | 70-89% | <70% |

#### Timing Awareness Critical
- **Pre-game (5 PM ET)**: Betting data should exist, predictions won't
- **Post-game (6 AM ET)**: Everything including predictions should exist
- Missing data has different meanings at different times

#### Common Failure Patterns
1. **Source-blocked games**: Not failures, expected behavior
2. **Stale dependency false positives**: Known issue #2
3. **Quota exceeded**: Blocks entire pipeline
4. **Rolling average cache bugs**: Fixed 2026-01-26, watch for regression
5. **Usage rate missing**: Team stats join issue

#### Spot Check System
- 6 distinct checks (A-F)
- Random sampling from last 7 days
- 2% tolerance for floating point
- Specific known failures: Mo Bamba, Josh Giddey (fixed)

### Step 2: Knowledge Synthesis

From the research, I identified what the skill must encapsulate:

**1. Execution Knowledge**
- Which scripts to run in which order
- Required parameters and flags
- How to interpret outputs

**2. Domain Knowledge**
- What metrics indicate health
- What thresholds define failure
- What behaviors are expected vs unexpected

**3. Investigation Knowledge**
- How to trace issues backward through pipeline
- What logs to check for which failures
- How to distinguish transient from permanent issues

**4. Context Knowledge**
- Known historical issues
- Recent fixes to watch for regression
- Seasonal patterns (early season vs mid-season)

**5. Action Knowledge**
- What remediation steps exist
- When to auto-fix vs escalate
- Which runbooks apply to which scenarios

---

## Design Decisions

### Decision 1: Skill Structure

**Chosen**: Single comprehensive SKILL.md file with all guidance

**Alternatives Considered**:
- Split into multiple files (runbooks/, reference/, etc.)
- Minimal prompt relying on Claude reading docs

**Rationale**:
- Single file easier to maintain initially
- All context in one place for Claude
- Can refactor to multi-file later if too large
- Current size (10KB) manageable

### Decision 2: Automation Level

**Chosen**: Guided investigation, not full automation

**Alternatives Considered**:
- Fully automated script (no Claude judgment)
- Minimal guidance (just run commands, Claude figures out rest)

**Rationale**:
- Validation requires contextual judgment
- New issues need human-like investigation
- Rigid automation fragile to changes
- Claude's reasoning valuable for root cause analysis

### Decision 3: Output Format

**Chosen**: Structured markdown report with severity classification

**Example**:
```markdown
## Daily Orchestration Validation - [DATE]

### Summary: [STATUS]

| Phase | Status | Details |
|-------|--------|---------|

### Issues Found
🔴/🟡/🟠/🟢 [Severity]: [Description]
  - Impact: ...
  - Root cause: ...
  - Recommendation: ...

### Recommended Actions
1. [Specific action with command]
```

**Rationale**:
- Consistent format aids rapid scanning
- Severity emojis provide visual priority
- Actionable recommendations reduce decision latency
- Commands copy-pasteable for quick remediation

### Decision 4: Severity Classification

**Chosen**: P1-P5 system aligned with SLA impact

- **P1 Critical**: Production down, immediate action
- **P2 High**: Data quality degraded, 1 hour response
- **P3 Medium**: Non-blocking issues, 4 hour response
- **P4 Low**: Minor issues, next business day
- **P5 Info**: Informational, no action needed

**Rationale**:
- Prevents "everything is critical" alert fatigue
- Aligns with actual impact (predictions blocked vs delayed)
- Guides prioritization of remediation

### Decision 5: Known Issues Integration

**Chosen**: Embed known issues directly in skill with context

**Example from skill**:
```markdown
### Known Data Quality Issues

1. **Phase 4 SQLAlchemy Missing**
   - Symptom: `ModuleNotFoundError: No module named 'sqlalchemy'`
   - Impact: ML feature generation fails
   - Fix: Deploy updated requirements.txt
```

**Rationale**:
- Faster pattern matching (no doc searching)
- Context aids diagnosis (symptom → fix mapping)
- Reduces false alarms (distinguish known from new issues)

---

## Implementation

### File Structure

Following Claude Code skill requirements:

```
.claude/skills/validate-daily/
└── SKILL.md              # Main skill file
```

**Why directory structure?**
- Claude Code auto-discovers skills in `.claude/skills/`
- Each skill must be a **directory** with `SKILL.md` inside
- NOT a standalone `.md` file (this was initial mistake)

### SKILL.md Frontmatter

```yaml
---
name: validate-daily
description: Validate daily orchestration pipeline health
---
```

**Fields**:
- `name`: Becomes the `/validate-daily` slash command
- `description`: Helps Claude decide when to auto-invoke (optional)

**Optional fields not used**:
- `disable-model-invocation: true` - Allows auto-invocation
- `allowed-tools` - No tool restrictions needed
- `context: fork` - Runs in main context (not isolated)

### Skill Content Organization

**Section 1: Mission & Context** (Lines 1-25)
- Clear objective statement
- Timing awareness (pre-game vs post-game)
- Expected behavior by time of day

**Section 2: Standard Validation Workflow** (Lines 26-150)
- Phase 1: Health check script
- Phase 2: Main validation script
- Phase 3: Spot checks
- Phase 4: Phase completion status
- Phase 5: Investigation guidance

**Section 3: Investigation Tools** (Lines 151-180)
- Cloud Run log commands
- BigQuery validation queries
- Manual verification approaches

**Section 4: Known Issues & Context** (Lines 181-240)
- Known data quality issues (5 items)
- Expected behaviors (4 items)
- Data quality thresholds table

**Section 5: Severity Classification** (Lines 241-265)
- P1-P5 definitions with examples
- Clear escalation criteria

**Section 6: Output Format** (Lines 266-290)
- Template for validation report
- Examples of each section
- Formatting guidelines

**Section 7: Important Guidelines** (Lines 291-310)
- Be concise, specific, actionable
- Classify severity appropriately
- Distinguish failures from expectations
- Investigate, don't just report

**Section 8: Reference Documentation** (Lines 311-320)
- Links to deeper docs
- Runbooks for complex investigations

**Section 9: Key Commands Reference** (Lines 321-340)
- Quick reference for all validation commands
- Manual trigger commands
- Date-specific validation

### Key Implementation Patterns

#### Pattern 1: Context-Aware Expectations

```markdown
**Key Timing Rules**:
- **Pre-game (5 PM ET)**: Betting data should exist. Predictions may not.
- **Post-game (6 AM ET)**: Everything should exist.
```

This prevents false alarms when data isn't expected yet.

#### Pattern 2: Investigation Branching Logic

```markdown
**If validation script reports ISSUES**:
1. Read the specific error messages
2. Classify by type (missing data, quality issue, timing issue, source blocked)
3. Determine root cause (which phase failed?)
4. Check recent logs for that phase
5. Consult known issues list
6. Provide specific remediation steps
```

This guides Claude through systematic root cause analysis.

#### Pattern 3: Failure Classification

```markdown
**If spot checks fail**:
1. Which specific check failed? (rolling_avg vs usage_rate)
2. What players failed? (Check if known issue)
3. Run manual BigQuery validation on one failing sample
...
```

Progressively deeper investigation based on findings.

#### Pattern 4: Known Issue Pattern Matching

```markdown
1. **Phase 4 SQLAlchemy Missing**
   - Symptom: `ModuleNotFoundError: No module named 'sqlalchemy'`
   - Impact: ML feature generation fails
   - Fix: Deploy updated requirements.txt
```

Symptom → Impact → Fix mapping for rapid diagnosis.

---

## Skill Architecture

### Information Flow

```
User invokes `/validate-daily`
  ↓
Claude receives SKILL.md as system prompt
  ↓
1. Determine current time & game schedule (context)
  ↓
2. Run baseline health check
  ↓
3. Run main validation script
  ↓
4. Run spot checks
  ↓
5. Check phase completion status
  ↓
6. IF issues found → Investigate
     - Read error messages
     - Check logs
     - Classify severity
     - Determine root cause
     - Consult known issues
  ↓
7. Generate structured report
     - Summary table
     - Issues with severity
     - Unusual observations
     - Recommended actions
```

### Decision Points

**At each phase, Claude decides**:
1. **Did this check pass?** (exit code, metrics, thresholds)
2. **Is failure expected?** (timing, source blocks, known issues)
3. **What's the impact?** (P1-P5 severity)
4. **What's the root cause?** (trace backward through pipeline)
5. **What's the remediation?** (auto-fix, manual intervention, escalate)

### Knowledge Integration

The skill acts as a **knowledge compiler**, integrating:

1. **Procedural Knowledge**: How to run validations (scripts, commands)
2. **Declarative Knowledge**: What thresholds define health (metrics, ranges)
3. **Heuristic Knowledge**: How to investigate (patterns, workflows)
4. **Historical Knowledge**: What issues have occurred (known bugs, fixes)
5. **Contextual Knowledge**: When behaviors are expected (timing, seasonality)

---

## Testing & Validation

### Test Execution (2026-01-26 14:07 PST)

**Ran skill logic manually** (skill not auto-discovered until session restart):

#### Test Results

**✅ Successfully Detected**:
1. **P1 Critical: BigQuery Quota Exceeded**
   - Traced from health check errors to Cloud Run logs
   - Identified impact: Phase 3 → Phase 4 → Phase 5 cascade failure
   - Root cause: Partition modification quota limit

2. **P1 Critical: Data Quality - Usage Rate 35.3%**
   - Threshold: 90%, Actual: 35.3%
   - Linked to quota exceeded (processor can't write results)

3. **P1 Critical: Spot Check Failures (50% accuracy)**
   - jusufnurkic: 27-32% error (severe)
   - jamalmurray: 3-5% error (moderate)
   - Potential cache date filter regression

4. **P2 High: Stale Dependencies**
   - Multiple processors reporting 99h-573h old data
   - Mix of true stale data and false positives

5. **P3 Medium: API Export Stale**
   - Expected for pre-game check (context-aware)

**✅ Context Awareness Demonstrated**:
- Correctly identified pre-game timing (5:07 PM ET)
- Noted predictions missing is expected pre-game
- Distinguished source-blocked games from failures
- Applied P1-P5 severity classification appropriately

**✅ Investigation Depth**:
- Checked Cloud Run logs when processors failed
- Attempted BigQuery validation for spot check failures
- Traced quota issue through multiple error sources
- Provided specific remediation commands

**✅ Output Quality**:
- Structured report with summary table
- Issues categorized by severity with emojis
- Actionable recommendations with commands
- Unusual observations section
- Context references to known issues

### What Worked Well

1. **Comprehensive Research**: Explore agent provided deep understanding
2. **Knowledge Encoding**: Thresholds, patterns, and workflows clearly documented
3. **Adaptive Investigation**: Skill guided investigation without being rigid
4. **Severity Classification**: P1-P5 system prevented alert fatigue
5. **Actionable Output**: Every issue had specific next steps

### Issues Encountered

1. **Skill Discovery**:
   - Initial error: Created as `.claude/skills/validate-daily.md` (file)
   - Required: `.claude/skills/validate-daily/SKILL.md` (directory)
   - Fix: Restructured to directory format
   - Still not discovered: Requires session restart for auto-discovery

2. **BigQuery Schema Unknown**:
   - Attempted to query `player_name` field
   - Field doesn't exist in `player_daily_cache`
   - Solution: Check schema first, adapt query
   - **Improvement**: Add schema reference to skill

3. **Manual Testing Only**:
   - Couldn't invoke `/validate-daily` directly (discovery issue)
   - Had to run skill logic manually
   - Next session will test actual invocation

---

## Usage Guide

### How to Invoke

**Command**: `/validate-daily`

**When to Run**:
- **Pre-game (5 PM ET)**: Verify data ready before games
- **Post-game (6 AM ET next day)**: Verify complete pipeline ran
- **Ad-hoc**: After making fixes to verify resolution

**Expected Duration**: 2-5 minutes depending on investigation depth

### Interpreting Output

#### Summary Line
```
### Summary: 🔴 CRITICAL ISSUES DETECTED
```

- ✅ **OK**: All checks passed, no action needed
- ⚠️ **NEEDS ATTENTION**: Warnings but predictions can proceed
- 🔴 **CRITICAL ISSUES**: Predictions blocked, immediate action required

#### Phase Status Table
```
| Phase | Status | Details |
|-------|--------|---------|
| Phase 3 (Analytics) | 🔴 CRITICAL | Quota exceeded blocking processors |
```

- ✅ = Healthy
- ⚠️ = Degraded but functional
- ❌ = Failed
- 🔴 = Critical failure blocking downstream
- ℹ️ = Not applicable (e.g., predictions pre-game)

#### Issues Section
```
🔴 P1 CRITICAL: BigQuery Quota Exceeded
- Impact: Phase 3 processors cannot write results
- Root cause: Pipeline logger partition modifications
- Recommendation: [specific commands]
```

**Severity Emojis**:
- 🔴 P1 = Drop everything, fix now
- 🟡 P2 = Fix within 1 hour
- 🟠 P3 = Fix within 4 hours
- 🟢 P4 = Next business day
- ℹ️ P5 = Informational only

#### Recommended Actions
```
1. IMMEDIATE: Investigate BigQuery quota exceeded issue
   [specific commands to run]

2. HIGH (within 1 hour): Review stale dependency thresholds
   [what to check]
```

Actions are **priority-ordered** and include:
- Timeframe for completion
- Specific commands to run
- Expected outcomes

### Following Up on Issues

**For P1 Critical Issues**:
1. Run recommended commands immediately
2. Verify fix with another `/validate-daily` run
3. Document root cause in handoff if novel issue

**For P2-P3 Issues**:
1. Create TODO or ticket
2. Schedule remediation within SLA
3. Monitor if degradation worsens

**For P4-P5 Issues**:
1. Note in session log
2. Address during next maintenance window
3. Consider if pattern emerges

### Re-running After Fixes

```bash
# After fixing an issue, re-validate
/validate-daily

# Or run specific validation only
python scripts/validate_tonight_data.py
python scripts/spot_check_data_accuracy.py --samples 10
```

Expect improved metrics and reduced issue count.

---

## Known Limitations

### 1. Session Restart Required for Discovery

**Issue**: Skill not auto-discovered until Claude Code session restart

**Workaround**:
- Close and reopen Claude Code
- Skill will be available in next session

**Why**: Skills are loaded at session initialization, not dynamically

### 2. No Historical Trending

**Limitation**: Each validation is point-in-time, no trend analysis

**Example**: Can't automatically detect "usage_rate has been declining for 3 days"

**Workaround**:
- Manual: Compare to previous validation outputs
- Future: Build trend tracking into health check script

### 3. Limited Auto-Remediation

**Limitation**: Skill recommends actions but doesn't auto-fix

**Example**: Won't automatically trigger Phase 3 retry if failed

**Rationale**: Safety - human approval for production actions

**Future Enhancement**: Add "auto-fix safe issues" mode with approval

### 4. BigQuery Schema Assumptions

**Limitation**: Skill includes sample queries assuming schema hasn't changed

**Risk**: If columns renamed/removed, queries will fail

**Mitigation**: Skill instructs Claude to adapt if queries fail

### 5. No Alert Integration

**Limitation**: Validation results only shown in terminal, no alerting

**Future Enhancement**:
- Slack/email integration for P1 issues
- Dashboard integration for historical tracking

---

## Future Enhancements

### Phase 1: Usability Improvements

1. **Multi-file Skill Structure**
   ```
   .claude/skills/validate-daily/
   ├── SKILL.md              # Main orchestration
   ├── runbooks/
   │   ├── investigation.md  # Deep investigation procedures
   │   └── remediation.md    # Fix procedures
   └── reference/
       ├── thresholds.md     # Data quality thresholds
       └── schemas.md        # BigQuery schema reference
   ```

2. **Interactive Mode**
   - Ask user which phases to validate (skip some if focused investigation)
   - Offer "quick check" vs "comprehensive" modes

3. **Validation History**
   - Store validation results in `.claude/validation-history/`
   - Automatic trend detection ("usage_rate declining")

### Phase 2: Intelligence Improvements

1. **Root Cause Inference**
   - Build decision tree for common failures
   - Automatic correlation (quota exceeded → processor failures → data quality)

2. **Predictive Alerts**
   - "Usage_rate at 91%, trending toward threshold in 2 days"
   - "Spot check accuracy degrading, investigate before critical"

3. **Auto-Fix Safe Issues**
   - Stale schedule games → auto-update
   - Missing predictions pre-game → note as expected, don't alarm

### Phase 3: Integration Improvements

1. **Dashboard Integration**
   - Export validation results to BigQuery
   - Grafana dashboard showing health over time

2. **Alert Routing**
   - P1 Critical → Slack + email immediately
   - P2-P3 → Slack only
   - P4-P5 → Log only

3. **Incident Tracking**
   - Auto-create issue in tracking system for P1-P2
   - Link to validation output
   - Track resolution time

### Phase 4: Additional Validations

1. **Performance Validation**
   - Phase execution time trends
   - Resource usage patterns
   - Cost tracking

2. **Model Quality Validation**
   - Prediction accuracy trends
   - Calibration metrics
   - Feature importance drift

3. **Business Logic Validation**
   - Prop line coverage by bookmaker
   - Player coverage by team
   - Games coverage by date range

---

## Appendix A: Skill Creation Checklist

For creating similar skills in the future:

### Research Phase
- [ ] Identify core scripts/tools to orchestrate
- [ ] Use Explore agent to deeply understand system
- [ ] Document thresholds, metrics, and "good" state
- [ ] Catalog common failure patterns
- [ ] Map investigation workflows
- [ ] Identify context dependencies (timing, seasonality)

### Design Phase
- [ ] Define skill objective and scope
- [ ] Choose automation level (guided vs rigid)
- [ ] Design output format (structure, severity)
- [ ] Identify decision points for Claude judgment
- [ ] Map knowledge to encode (procedural, declarative, heuristic)

### Implementation Phase
- [ ] Create `.claude/skills/[name]/` directory
- [ ] Write `SKILL.md` with frontmatter
- [ ] Organize content into clear sections
- [ ] Include examples and templates
- [ ] Add known issues and patterns
- [ ] Provide investigation guidance
- [ ] Reference deeper documentation

### Testing Phase
- [ ] Test skill logic manually first
- [ ] Verify context awareness works
- [ ] Check investigation adapts to findings
- [ ] Validate output format and clarity
- [ ] Test with different scenarios (success, failure, partial)

### Documentation Phase
- [ ] Document skill creation process (this doc)
- [ ] Update operations runbooks to reference skill
- [ ] Add to daily validation checklist
- [ ] Create usage examples
- [ ] Note limitations and future enhancements

---

## Appendix B: Key Files Reference

### Skill Files
- **Skill definition**: `.claude/skills/validate-daily/SKILL.md`
- **This guide**: `docs/02-operations/VALIDATE-DAILY-SKILL-CREATION-GUIDE.md`

### Validation System Files
- **Main validator**: `scripts/validate_tonight_data.py`
- **Spot checker**: `scripts/spot_check_data_accuracy.py`
- **Health check**: `bin/monitoring/daily_health_check.sh`

### Documentation
- **Spot check system**: `docs/06-testing/SPOT-CHECK-SYSTEM.md`
- **Daily operations**: `docs/02-operations/daily-operations-runbook.md`
- **Troubleshooting**: `docs/02-operations/troubleshooting-matrix.md`
- **Recent findings**: `docs/09-handoff/2026-01-26-SESSION-33-*.md`

### Configuration
- **Claude settings**: `.claude/settings.local.json`
- **Project instructions**: `.claude/claude_project_instructions.md`

---

## Appendix C: Research Agent Output Summary

The Explore agent provided comprehensive analysis including:

1. **Validation Architecture**: 5-phase pipeline validation flow
2. **Check Details**: 10 distinct validation checks with logic
3. **Spot Check System**: 6 check types (A-F) with formulas and tolerances
4. **Failure Patterns**: 6 common patterns with investigation workflows
5. **Timing & Scheduling**: When to run validations, what to expect when
6. **Severity Classification**: P1-P5 system with examples
7. **Historical Context**: Known issues and recent fixes
8. **Commands Reference**: All validation and investigation commands

**Full output**: Available in session transcript (search for "COMPREHENSIVE VALIDATION & MONITORING SYSTEM ANALYSIS")

---

## Appendix D: Sample Validation Output

See session transcript (2026-01-26 14:07 PST) for full example of validation report generated during testing.

**Highlights**:
- Detected 3 P1 critical issues (quota, data quality, spot checks)
- Detected 1 P2 high issue (stale dependencies)
- Detected 2 P3 medium issues (API export, prediction coverage)
- Provided 5 prioritized remediation actions
- Included unusual observations section
- Referenced known issues appropriately

---

## Questions for Review

For the next session reviewing this work:

1. **Skill Structure**: Is the single-file approach adequate or should it be split?
2. **Knowledge Completeness**: Are there validation aspects missing?
3. **Investigation Depth**: Is guidance sufficient for novel issues?
4. **Output Format**: Is the report structure clear and actionable?
5. **Severity Classification**: Is P1-P5 system appropriate?
6. **Auto-Remediation**: Should skill have permission to auto-fix safe issues?
7. **Documentation**: Is this guide sufficient for maintaining/extending the skill?

---

## Conclusion

The `/validate-daily` skill successfully encapsulates deep validation system knowledge into a reusable Claude Code skill. It demonstrates:

- **Comprehensive research** → Deep system understanding
- **Thoughtful design** → Guided investigation, not rigid automation
- **Knowledge encoding** → Thresholds, patterns, workflows documented
- **Adaptive execution** → Claude uses judgment within structured framework
- **Actionable output** → Consistent severity classification and recommendations

**Next Steps**:
1. Test skill invocation in new session (after discovery)
2. Refine based on real-world usage
3. Consider enhancements (trending, auto-fix, alerting)
4. Create additional skills for other workflows

**Success Criteria**: ✅ Met
- Skill created and tested
- Produces actionable validation reports
- Adapts investigation to findings
- Classifies severity appropriately
- Documented for future maintenance

---

**Document Status**: Complete
**Ready for Review**: Yes
**Next Action**: Test `/validate-daily` in fresh session
