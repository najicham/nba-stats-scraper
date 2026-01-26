# Task: Create `/validate-daily` Claude Skill

**Model**: Sonnet (sufficient for this task)
**Estimated Time**: 30-45 minutes
**Type**: Skill creation (writing task)

---

## Objective

Create a Claude Code skill (`/validate-daily`) that validates daily orchestration with flexibility to investigate new issues.

## What is a Claude Skill?

A skill is a markdown file in `.claude/skills/` that provides a starting prompt when invoked. It's NOT a rigid script - Claude still uses judgment and adapts based on what it finds.

## Skill Requirements

### File Location
```
.claude/skills/validate-daily.md
```

### Skill Behavior

**Fixed Starting Point:**
1. Run `./bin/monitoring/daily_health_check.sh`
2. Check Phase 2/3/4/5 completion in Firestore/BigQuery
3. Verify predictions exist for today's games
4. Run spot checks (5 samples using `scripts/spot_check_data_accuracy.py`)

**Flexible Investigation:**
- If issues found, investigate root cause
- If new error patterns, analyze them
- Compare to recent days if helpful
- Check logs if needed
- Adapt based on findings

**Output:**
- Health status summary
- Issues found (with severity)
- Recommended actions
- Anything unusual (even if not critical)

### Key Commands/Scripts to Reference

```bash
# Health check
./bin/monitoring/daily_health_check.sh

# Spot check
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate

# Validation
python scripts/validate_tonight_data.py --date 2026-01-26

# Phase 3 status (Firestore)
python3 << 'EOF'
from google.cloud import firestore
db = firestore.Client()
doc = db.collection('phase3_completion').document('2026-01-26').get()
print(doc.to_dict() if doc.exists else "No document")
EOF

# Predictions count
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT game_id) as games
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"

# ML features count
bq query --use_legacy_sql=false "
SELECT COUNT(*) as features
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()"

# Recent errors
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=20

gcloud run services logs read nba-phase4-precompute-processors \
  --region=us-west2 --limit=20
```

### Reference Documentation

The skill should know about these docs for context:

```
docs/02-operations/daily-operations-runbook.md
docs/02-operations/daily-validation-checklist.md
docs/06-testing/SPOT-CHECK-SYSTEM.md
docs/09-handoff/ (recent session findings)
```

### Known Issues to Check For

The skill should be aware of recent/common issues:

1. **Phase 4 SQLAlchemy** - `ModuleNotFoundError: No module named 'sqlalchemy'`
2. **Phase 3 stale dependencies** - False positive freshness errors
3. **Betting timing** - Workflow should start at 8 AM, not 1 PM
4. **Low prediction coverage** - Expected ~90%, often see 32-48%
5. **Scraper IP bans** - cdn.nba.com returns 403

### Skill Tone

- Be concise in reporting
- Flag issues by severity (Critical, High, Medium, Low)
- Provide actionable recommendations
- Note unusual patterns even if not errors
- Don't just dump raw output - summarize and interpret

---

## Example Skill Output (What We Want)

When someone runs `/validate-daily`, the output should look something like:

```
## Daily Orchestration Validation - 2026-01-26

### Summary: ⚠️ NEEDS ATTENTION

| Phase | Status | Details |
|-------|--------|---------|
| Phase 2 (Betting) | ✅ OK | 147 props, 28 lines |
| Phase 3 (Analytics) | ⚠️ 80% | 4/5 processors complete |
| Phase 4 (Precompute) | ✅ OK | 1,247 ML features |
| Phase 5 (Predictions) | ✅ OK | 89 predictions, 7 games |
| Spot Checks | ✅ OK | 5/5 passed (100%) |

### Issues Found

**🟡 Medium: Phase 3 incomplete**
- `upcoming_player_game_context` not complete
- Error: "Stale dependencies" (but data looks fresh)
- This matches the known stale dependency false positive issue
- Recommendation: Review dependency threshold logic

### Unusual Observations
- Prediction coverage at 44% (below expected 90%)
- Same pattern as last 7 days - may be systemic

### Recommended Actions
1. Investigate Phase 3 stale dependency error
2. If predictions needed urgently: `gcloud scheduler jobs run same-day-phase3`
```

---

## Implementation Steps

### Step 0: Research First (Use Agents)

Before writing the skill, use the Explore agent to thoroughly understand the existing validation system:

```
Use the Task tool with subagent_type=Explore to study:

1. The validation system architecture:
   - scripts/validate_tonight_data.py (main validation script)
   - bin/monitoring/daily_health_check.sh (health check script)
   - How they work, what they check, what they output

2. The spot check system:
   - scripts/spot_check_data_accuracy.py
   - docs/06-testing/SPOT-CHECK-SYSTEM.md
   - What checks exist (A-E), how they work

3. Operations documentation:
   - docs/02-operations/daily-operations-runbook.md
   - docs/02-operations/daily-validation-checklist.md
   - docs/02-operations/orchestrator-monitoring.md

4. Recent incident findings:
   - docs/09-handoff/2026-01-26-SESSION-33-ORCHESTRATION-VALIDATION-CRITICAL-FINDINGS.md
   - docs/sessions/2026-01-26-COMPREHENSIVE-ACTION-PLAN.md
   - Common issues and patterns

5. Pipeline architecture:
   - How Phase 2/3/4/5 work
   - What Firestore collections track completion
   - What BigQuery tables to check
```

**This research is critical** - the skill needs to encapsulate deep knowledge of the validation system, not just run commands.

### Step 1: Create the skill file

1. **Create the skill file**: `.claude/skills/validate-daily.md`

2. **Structure the skill with**:
   - Clear objective statement
   - Starting checks to run
   - Guidance on investigation approach
   - Reference to key commands
   - Expected output format
   - Context about known issues

3. **Test the skill** by running `/validate-daily` and verifying it:
   - Runs the standard checks
   - Adapts when it finds issues
   - Produces clear, actionable output

4. **Document** any setup needed in the skill itself

---

## Skill Template Structure

```markdown
---
name: validate-daily
description: Validate daily orchestration pipeline health
---

# Daily Orchestration Validation

[Objective and context]

## Standard Checks

[List of checks to run]

## Investigation Guidance

[How to dig deeper when issues found]

## Known Issues

[Common problems to watch for]

## Output Format

[Expected structure of report]

## Reference

[Key commands and docs]
```

---

## Success Criteria

- [ ] Skill file created at `.claude/skills/validate-daily.md`
- [ ] Skill runs standard health checks
- [ ] Skill adapts and investigates when issues found
- [ ] Output is clear, concise, and actionable
- [ ] Known issues are flagged appropriately
- [ ] Skill tested with at least one invocation
- [ ] Documentation updated (see below)

---

## Documentation Requirements

After creating the skill, update the documentation:

### 1. Update Operations Runbook

Add a section about the skill to `docs/02-operations/daily-operations-runbook.md`:
- How to invoke the skill (`/validate-daily`)
- What it checks
- How to interpret output
- When to use it vs manual investigation

### 2. Create Skill Reference (Optional)

If there will be multiple skills, consider creating:
```
docs/02-operations/CLAUDE-SKILLS-REFERENCE.md
```

With:
- List of available skills
- What each skill does
- Usage examples
- How to create new skills

### 3. Update Daily Validation Checklist

Add the skill to `docs/02-operations/daily-validation-checklist.md` as the recommended first step for morning validation.

### Why docs/02-operations/?

Skills are operational tools for daily workflows, so they belong with other operations documentation - not in projects (which is for temporary work).

---

## Notes

- Keep the skill prompt concise - Claude doesn't need excessive detail
- Focus on WHAT to check and HOW to report, not rigid step-by-step
- The skill should feel like guidance from an experienced operator
- Allow flexibility for Claude to use judgment

---

**Document Created**: 2026-01-26
**For**: New chat session to create the skill
**Model Recommendation**: Sonnet
