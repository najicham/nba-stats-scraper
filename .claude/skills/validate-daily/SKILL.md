---
name: validate-daily
description: Validate daily orchestration pipeline health
---

# Daily Orchestration Validation

You are performing a comprehensive daily validation of the NBA stats scraper pipeline. This is NOT a rigid script - you should investigate issues intelligently and adapt based on what you find.

## Your Mission

Validate that the daily orchestration pipeline is healthy and ready for predictions. Check all phases (2-5), run data quality spot checks, investigate any issues found, and provide a clear, actionable summary.

## Current Context & Timing Awareness

**First**: Determine current time and game schedule context
- What time is it now? (Pre-game ~5 PM ET vs Post-game ~6 AM ET next day)
- Are there games today? Check the schedule
- What data should exist by now? (Timing affects expectations)

**Key Timing Rules**:
- **Pre-game (5 PM ET)**: Betting data, game context, ML features should exist. Predictions may not exist yet (games haven't happened).
- **Post-game (6 AM ET)**: Everything including predictions should exist for yesterday's games.
- **Off-day**: No games scheduled is normal, not an error.

## Standard Validation Workflow

### Phase 1: Run Baseline Health Check

```bash
./bin/monitoring/daily_health_check.sh
```

Parse the output intelligently:
- What phases completed successfully?
- What phases failed or are incomplete?
- Are there any errors in recent logs?
- Is this a timing issue (too early) or a real failure?

### Phase 2: Run Main Validation Script

```bash
python scripts/validate_tonight_data.py
```

**Exit Code Interpretation**:
- `0` = All checks passed (no ISSUES)
- `1` = At least one ISSUE found (investigate)

**Classification System**:
- **ISSUES**: Hard failures (ERROR/CRITICAL severity) - block deployment
- **WARNINGS**: Non-blocking concerns - investigate but don't block
- **STATS**: Metrics for monitoring - just note

### Phase 3: Run Data Quality Spot Checks

```bash
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate
```

**Accuracy Threshold**: ≥95% expected
- **100%**: Excellent, data quality is perfect
- **95-99%**: Good, minor issues but acceptable
- **90-94%**: WARNING - investigate specific failures
- **<90%**: CRITICAL - data quality issues need immediate attention

**Common Failure Patterns**:
- Rolling avg failures: Usually cache date filter bugs (`<=` vs `<`)
- Usage rate failures: Missing team stats or join issues
- Specific players failing: Check if known issues (Mo Bamba, Josh Giddey historically)

### Phase 4: Check Phase Completion Status

**Phase 3 Analytics (Firestore)**:
```bash
python3 << 'EOF'
from google.cloud import firestore
from datetime import datetime
db = firestore.Client()
today = datetime.now().strftime('%Y-%m-%d')
doc = db.collection('phase3_completion').document(today).get()
if doc.exists:
    data = doc.to_dict()
    print(f"Phase 3 Status: {data}")
else:
    print(f"No Phase 3 completion record for {today}")
EOF
```

**Phase 4 ML Features (BigQuery)**:
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as features, COUNT(DISTINCT game_id) as games
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()"
```

**Phase 5 Predictions (BigQuery)**:
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions, COUNT(DISTINCT game_id) as games
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"
```

### Phase 5: Investigate Any Issues Found

**If validation script reports ISSUES**:
1. Read the specific error messages
2. Classify by type (missing data, quality issue, timing issue, source blocked)
3. Determine root cause (which phase failed?)
4. Check recent logs for that phase
5. Consult known issues list below
6. Provide specific remediation steps

**If spot checks fail**:
1. Which specific check failed? (rolling_avg vs usage_rate)
2. What players failed? (Check if known issue)
3. Run manual BigQuery validation on one failing sample
4. Determine if cache issue, calculation bug, or data corruption
5. Recommend regeneration or code fix

**If phase completion incomplete**:
1. Which processor(s) didn't complete?
2. Check Cloud Run logs for that processor
3. Look for errors (ModuleNotFoundError, timeout, quota exceeded)
4. Determine if can retry or needs code fix

## Investigation Tools

**Cloud Run Logs** (if needed):
```bash
# Phase 3 logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50

# Phase 4 logs
gcloud run services logs read nba-phase4-precompute-processors \
  --region=us-west2 --limit=50
```

**Manual BigQuery Validation** (if spot checks fail):
```bash
bq query --use_legacy_sql=false "
-- Example: Validate rolling average for specific player
SELECT
  game_date,
  player_name,
  points,
  points_avg_last_5
FROM nba_analytics.player_game_summary
WHERE player_name = 'lebron_james'
  AND game_date >= '2026-01-01'
ORDER BY game_date DESC
LIMIT 10"
```

## Known Issues & Context

### Known Data Quality Issues

1. **Phase 4 SQLAlchemy Missing**
   - Symptom: `ModuleNotFoundError: No module named 'sqlalchemy'`
   - Impact: ML feature generation fails
   - Fix: Deploy updated requirements.txt

2. **Phase 3 Stale Dependency False Positives**
   - Symptom: "Stale dependencies" error but data looks fresh
   - Impact: False failures in processor completion
   - Fix: Review dependency threshold logic (may be too strict)

3. **Low Prediction Coverage**
   - Symptom: Expected ~90%, seeing 32-48%
   - Context: If early season OR source-blocked games, this is normal
   - Fix: Only flag if mid-season AND no source blocks

4. **Rolling Average Cache Bug**
   - Symptom: Spot checks failing for rolling averages
   - Known players: Mo Bamba, Josh Giddey, Justin Champagnie
   - Root cause: Fixed 2026-01-26 (cache date filter bug)
   - Action: If failures still occurring, regenerate cache

5. **Betting Workflow Timing**
   - Symptom: No betting data at 5 PM ET
   - Expected: Workflow starts at 8 AM ET (not 1 PM)
   - Fix: Check workflow schedule in orchestrator

### Expected Behaviors (Not Errors)

1. **Source-Blocked Games**: NBA.com not publishing data for some games
   - Don't count as failures
   - Note in output for transparency

2. **No Predictions Pre-Game**: Normal if games haven't happened yet
   - Only error if checking yesterday's games

3. **Early Season Lower Quality**: First 2-3 weeks of season
   - 50-70% PASS predictions expected
   - 60-80% early_season_flag expected

4. **Off-Day Validation**: No games scheduled
   - Not an error, just informational

## Data Quality Thresholds

| Metric | Good | Warning | Critical |
|--------|------|---------|----------|
| **Spot Check Accuracy** | ≥95% | 90-94% | <90% |
| **Minutes Played Coverage** | ≥90% | 80-89% | <80% |
| **Usage Rate Coverage** | ≥90% | 80-89% | <80% |
| **Prediction Coverage** | ≥90% | 70-89% | <70% |
| **Game Context Coverage** | 100% | 95-99% | <95% |

## Severity Classification

**🔴 P1 CRITICAL** (Immediate Action):
- All predictions missing for entire day
- Data corruption detected (spot checks <90%)
- Pipeline completely stuck (no phases completing)
- Minutes/usage coverage <80%

**🟡 P2 HIGH** (Within 1 Hour):
- Data quality issue 70-89% coverage
- Single phase failing completely
- Spot check accuracy 90-94%
- Significant prediction quality drop

**🟠 P3 MEDIUM** (Within 4 Hours):
- Spot check accuracy 95-99%
- Single processor failing (others working)
- Timing delays (late completion)
- Non-critical data gaps

**🟢 P4 LOW** (Next Business Day):
- Non-critical data missing (prop lines, old roster)
- Performance degradation
- Documentation issues

**ℹ️  P5 INFO** (No Action):
- Source-blocked games noted
- Off-day (no games scheduled)
- Pre-game checks on data not yet expected

## Output Format

Provide a clear, concise summary structured like this:

```
## Daily Orchestration Validation - [DATE]

### Summary: [STATUS]
[One-line overall health status with emoji]

| Phase | Status | Details |
|-------|--------|---------|
| Phase 2 (Betting) | ✅/⚠️/❌ | [metrics] |
| Phase 3 (Analytics) | ✅/⚠️/❌ | [completion %] |
| Phase 4 (Precompute) | ✅/⚠️/❌ | [feature count] |
| Phase 5 (Predictions) | ✅/⚠️/❌ | [prediction count] |
| Spot Checks | ✅/⚠️/❌ | [accuracy %] |

### Issues Found
[List issues with severity emoji]
- 🔴/🟡/🟠/🟢 [Severity]: [Issue description]
  - Impact: [what's affected]
  - Root cause: [if known]
  - Recommendation: [specific action]

### Unusual Observations
[Anything notable but not critical]

### Recommended Actions
[Numbered list of specific next steps]
1. [Action with command if applicable]
2. [Action with reference to runbook if complex]
```

## Important Guidelines

1. **Be Concise**: Don't dump raw output - summarize and interpret
2. **Be Specific**: "Phase 3 incomplete" is less useful than "Phase 3: upcoming_player_game_context failed due to stale dependencies"
3. **Provide Context**: Is this a known issue? Expected behavior? New problem?
4. **Be Actionable**: Every issue should have a recommended action
5. **Classify Severity**: Use P1-P5 system, don't treat everything as critical
6. **Distinguish Failures from Expectations**: Source-blocked games, off-days, timing issues
7. **Investigate Don't Just Report**: If something fails, dig into why
8. **Reference Knowledge**: Use the known issues list and thresholds above

## Reference Documentation

For deeper investigation, consult:
- `docs/02-operations/daily-operations-runbook.md` - Standard procedures
- `docs/02-operations/troubleshooting-matrix.md` - Decision trees for failures
- `docs/06-testing/SPOT-CHECK-SYSTEM.md` - Spot check details
- `docs/09-handoff/` - Recent session findings and fixes

## Key Commands Reference

```bash
# Health check
./bin/monitoring/daily_health_check.sh

# Full validation
python scripts/validate_tonight_data.py

# Spot checks (5 samples, fast checks)
python scripts/spot_check_data_accuracy.py --samples 5 --checks rolling_avg,usage_rate

# Comprehensive spot checks (slower)
python scripts/spot_check_data_accuracy.py --samples 10

# Manual triggers (if needed)
gcloud scheduler jobs run same-day-phase3
gcloud scheduler jobs run same-day-phase4
gcloud scheduler jobs run same-day-phase5

# Check specific date
python scripts/validate_tonight_data.py --date 2026-01-26
```

---

**Remember**: You are not a rigid script. Use your judgment, investigate intelligently, and adapt based on what you find. The goal is actionable insights, not just command execution.
