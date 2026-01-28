# Data Quality Root Cause Investigation - Session Prompt

**Use this prompt to start the next Claude Code session**

---

## Session Objective

**PRIMARY GOAL**: Understand WHY data quality issues occur, not just patch symptoms.

We've been fixing bugs (20.0 placeholders, import errors, IAM permissions) but haven't investigated the ROOT CAUSES of systemic data issues:
- Why does December have a 15-day analytics gap?
- Why did November have duplicates?
- Why is usage_rate only 60% coverage?
- Why are some usage_rate values >100% (impossible)?
- Why didn't Phase 4 auto-trigger after Phase 3 for Jan 27?

**APPROACH**: Investigation-first, then systematic fixes. Stop the band-aid cycle.

---

## Context (Read This First)

### What We Know
1. **Repository**: `/home/naji/code/nba-stats-scraper`
2. **Project**: nba-props-platform (GCP, us-west2)
3. **Pipeline**: 5 phases (Raw → Enrichment → Analytics → Precompute → Predictions)
4. **Previous Work**:
   - Fixed 4 code bugs (import path, syntax, IAM, 20.0 placeholder)
   - Deployed fixes, all working
   - Validated full season (Oct 2025 - Jan 2026)
   - Found 3 critical data quality issues

### Critical Data Quality Issues Found

**ISSUE #1: December Analytics Gap** (P1 CRITICAL)
- **What**: 15 days (Dec 16-31) have incomplete analytics
- **Severity**: 51-82% completion (should be >90%)
- **Impact**: ~2,000 missing records, corrupts rolling averages for 3+ weeks
- **Root Cause**: UNKNOWN (this is what we need to investigate)

**ISSUE #2: November Duplicates** (P2 HIGH)
- **What**: 123 duplicate player-game records on Nov 10 and Nov 13
- **Severity**: ALL duplicates in November, none before/after
- **Impact**: Corrupted averaging calculations
- **Root Cause**: UNKNOWN

**ISSUE #3: usage_rate Coverage 60%** (P3 MEDIUM)
- **What**: Only 60% of active players have usage_rate in January
- **History**: 0% in Oct-Nov, jumped to 60% around Dec 29
- **Impact**: 40% of players missing usage_rate, features incomplete
- **Root Cause**: UNKNOWN (is this expected or a bug?)

**ISSUE #4: usage_rate Anomalies** (P3 MEDIUM)
- **What**: 27 players have usage_rate >50%, some >100%
- **Example**: deandreayton at 264.9% (physically impossible)
- **Impact**: Feature corruption for affected players
- **Root Cause**: UNKNOWN (calculation bug or data corruption?)

**ISSUE #5: Manual Phase Triggers** (P2 HIGH)
- **What**: Phase 4 didn't auto-run after Phase 3 completed for Jan 27
- **Impact**: Predictions blocked, requires manual intervention
- **Root Cause**: UNKNOWN (what's the expected trigger mechanism?)

### Documentation Available

**Handoff Doc**: `docs/08-projects/current/2026-01-27-data-quality-investigation/HANDOFF-2026-01-28.md`
- Complete session history
- All validation reports
- Investigation questions and queries
- Service URLs and tools

**Other Docs**:
- `ROOT-CAUSE-ANALYSIS.md` - Deep dive into original 6 root causes
- `VALIDATION-REPORT.md` - Session 1 validation findings
- `ARCHITECTURE-IMPROVEMENTS.md` - Phase 3 sub-phases design

---

## Your Mission

### Phase 1: Understand the Data Pipeline (TOP PRIORITY)

**Goal**: Create a complete map of how data flows through the system

**Tasks**:
1. **Find all Cloud Run services** for phases 1-5:
   ```bash
   gcloud run services list --platform=managed --region=us-west2
   ```
   Document which service handles which phase.

2. **Find all Cloud Scheduler jobs**:
   ```bash
   gcloud scheduler jobs list --location=us-west2
   ```
   Document what triggers what and when.

3. **Find all Pub/Sub topics**:
   ```bash
   gcloud pubsub topics list
   gcloud pubsub subscriptions list
   ```
   Document phase transition mechanism (does Phase 3 completion trigger Phase 4?).

4. **Create architecture diagram**:
   ```
   Phase 1 (Raw) → [Scheduler/Pub/Sub?] → Phase 2 (Enrichment) → [?] → Phase 3 (Analytics) → [?] → Phase 4 (Precompute) → [?] → Phase 5 (Predictions)
   ```

5. **Document expected SLAs**:
   - How long should each phase take?
   - When should each phase run?
   - What are the dependencies?

**Expected Output**: Architecture documentation showing complete data flow with triggers

---

### Phase 2: Investigate December Analytics Gap

**Goal**: Understand WHY 15 days are incomplete

**Investigation Steps**:

1. **Check processor execution history**:
   ```sql
   SELECT processor_name, data_date, status, skip_reason,
     errors, warnings, records_processed
   FROM `nba-props-platform.nba_reference.processor_run_history`
   WHERE data_date BETWEEN '2025-12-16' AND '2025-12-31'
     AND processor_name LIKE '%player_game%'
   ORDER BY data_date, started_at
   ```

   **Questions**:
   - Did Phase 3 run for these dates?
   - Did it complete successfully?
   - Were there errors or warnings?
   - How many records did it process vs expect?

2. **Compare raw source vs analytics output**:
   ```sql
   SELECT
     r.game_date,
     COUNT(DISTINCT r.player_lookup) as raw_players,
     COUNT(DISTINCT a.player_lookup) as analytics_players,
     ROUND(100.0 * COUNT(DISTINCT a.player_lookup) /
       NULLIF(COUNT(DISTINCT r.player_lookup), 0), 1) as pct_coverage,
     ARRAY_AGG(DISTINCT r.player_lookup ORDER BY r.player_lookup LIMIT 5) as sample_raw,
     ARRAY_AGG(DISTINCT a.player_lookup ORDER BY a.player_lookup LIMIT 5) as sample_analytics
   FROM `nba-props-platform.nba_raw.nbac_gamebook` r
   LEFT JOIN `nba-props-platform.nba_analytics.player_game_summary` a
     ON r.player_lookup = a.player_lookup AND r.game_date = a.game_date
   WHERE r.game_date BETWEEN '2025-12-16' AND '2025-12-31'
   GROUP BY r.game_date
   ORDER BY pct_coverage
   ```

   **Questions**:
   - Which specific players are missing from analytics?
   - Is there a pattern (specific teams, games, positions)?
   - Are the missing players DNPs or active players?

3. **Check game status during December**:
   ```sql
   SELECT game_date, game_id, game_status, game_status_text
   FROM `nba-props-platform.nba_raw.nbac_schedule`
   WHERE game_date BETWEEN '2025-12-16' AND '2025-12-31'
   ORDER BY game_date
   ```

   **Questions**:
   - Were games marked as "Final"?
   - Could wrong status have blocked processing?

4. **Check for code deployments**:
   ```bash
   # Check git log for December deployments
   git log --since="2025-12-15" --until="2026-01-01" \
     --oneline --all -- data_processors/analytics/player_game_summary/
   ```

   **Questions**:
   - Was there a bug introduced in December?
   - Was there a code change that filtered out records?

**Expected Output**: Root cause document explaining WHY the gap occurred + prevention strategy

---

### Phase 3: Investigate November Duplicates

**Goal**: Understand WHY only Nov 10/13 have duplicates

**Investigation Steps**:

1. **Examine the duplicate records**:
   ```sql
   SELECT game_date, game_id, player_lookup,
     COUNT(*) as duplicate_count,
     ARRAY_AGG(STRUCT(processed_at, data_source_primary,
       points, minutes_played) ORDER BY processed_at) as versions
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE game_date IN ('2025-11-10', '2025-11-13')
   GROUP BY game_date, game_id, player_lookup
   HAVING COUNT(*) > 1
   ORDER BY duplicate_count DESC
   LIMIT 20
   ```

   **Questions**:
   - Are the duplicate records identical or different?
   - What are the timestamps (how far apart)?
   - Do they have different data sources?

2. **Check processor run history for double-processing**:
   ```sql
   SELECT data_date, processor_name, run_id,
     started_at, processed_at, status,
     trigger_source, records_created
   FROM `nba-props-platform.nba_reference.processor_run_history`
   WHERE data_date IN ('2025-11-10', '2025-11-13')
     AND processor_name LIKE '%player_game%'
   ORDER BY data_date, started_at
   ```

   **Questions**:
   - Did the processor run twice for these dates?
   - What triggered each run (manual, scheduler, pubsub)?
   - Were they overlapping or sequential?

3. **Check for analytics processor code issues**:
   ```bash
   # Look for idempotency checks in processor code
   grep -r "INSERT\|MERGE\|duplicate" \
     data_processors/analytics/player_game_summary/
   ```

   **Questions**:
   - Does the processor use INSERT (allows duplicates) or MERGE (prevents duplicates)?
   - Is there idempotency protection?
   - Could a retry have caused double-insert?

**Expected Output**: Root cause + code fix to prevent future duplicates

---

### Phase 4: Investigate usage_rate Coverage

**Goal**: Determine if 60% is expected or a data quality issue

**Investigation Steps**:

1. **Correlate with team stats availability**:
   ```sql
   SELECT
     p.game_date,
     COUNT(DISTINCT p.player_lookup) as total_players,
     COUNT(DISTINCT CASE WHEN p.minutes_played > 0
       THEN p.player_lookup END) as active_players,
     COUNT(DISTINCT CASE WHEN p.usage_rate IS NOT NULL
       THEN p.player_lookup END) as players_with_usage,
     COUNT(DISTINCT t.game_id) as games_with_team_stats,
     ROUND(100.0 * COUNT(DISTINCT CASE WHEN p.usage_rate IS NOT NULL
       THEN p.player_lookup END) /
       NULLIF(COUNT(DISTINCT CASE WHEN p.minutes_played > 0
         THEN p.player_lookup END), 0), 1) as usage_pct
   FROM `nba-props-platform.nba_analytics.player_game_summary` p
   LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
     ON p.game_id = t.game_id
   WHERE p.game_date >= '2025-12-01'
   GROUP BY p.game_date
   ORDER BY p.game_date
   ```

   **Questions**:
   - Is usage_rate coverage correlated with team stats availability?
   - What changed on Dec 29 (0% → 60% jump)?
   - Are team stats missing for the 40% without usage_rate?

2. **Analyze players missing usage_rate**:
   ```sql
   SELECT
     player_lookup,
     game_date,
     minutes_played,
     points,
     field_goal_attempts,
     free_throw_attempts,
     turnovers,
     game_id
   FROM `nba-props-platform.nba_analytics.player_game_summary`
   WHERE game_date >= '2026-01-20'
     AND minutes_played > 0
     AND usage_rate IS NULL
   ORDER BY minutes_played DESC
   LIMIT 50
   ```

   **Questions**:
   - Are missing usage_rate players low-minute players (expected)?
   - Are they DNPs (expected NULL)?
   - Or are they high-minute players (unexpected, indicates bug)?

3. **Check usage_rate calculation code**:
   ```bash
   # Find where usage_rate is calculated
   grep -r "usage_rate" data_processors/analytics/ --include="*.py"
   ```

   **Questions**:
   - What's the calculation formula?
   - What happens if team stats are NULL?
   - Is there error handling for edge cases?

**Expected Output**: Expected vs actual coverage analysis + fix if needed

---

### Phase 5: Investigate usage_rate Anomalies

**Goal**: Find calculation bug or data corruption

**Investigation Steps**:

1. **Get source data for anomalous cases**:
   ```sql
   SELECT
     p.player_lookup,
     p.game_date,
     p.game_id,
     p.usage_rate,
     p.field_goal_attempts as player_fga,
     p.free_throw_attempts as player_fta,
     p.turnovers as player_tov,
     p.minutes_played as player_mp,
     t.field_goal_attempts as team_fga,
     t.free_throw_attempts as team_fta,
     t.turnovers as team_tov,
     t.minutes_played as team_mp,
     -- Manual calculation
     ROUND(100.0 *
       ((p.field_goal_attempts + 0.44 * p.free_throw_attempts + p.turnovers) *
        (t.minutes_played / 5)) /
       (p.minutes_played *
        (t.field_goal_attempts + 0.44 * t.free_throw_attempts + t.turnovers)), 1
     ) as manual_usage_rate
   FROM `nba-props-platform.nba_analytics.player_game_summary` p
   LEFT JOIN `nba-props-platform.nba_analytics.team_offense_game_summary` t
     ON p.game_id = t.game_id
   WHERE p.usage_rate > 50
   ORDER BY p.usage_rate DESC
   LIMIT 20
   ```

   **Questions**:
   - Does manual calculation match stored usage_rate?
   - Are team stats corrupted (zero values causing division errors)?
   - Is there a data type issue (overflow, truncation)?

2. **Check for NULL/zero handling bugs**:
   Look at the usage_rate calculation code for:
   - Division by zero protection
   - NULL handling
   - Data type casting (float vs int)

**Expected Output**: Bug fix or data correction

---

## Success Criteria

At the end of this session, you should have:

1. **Architecture Documentation**:
   - Complete pipeline diagram (Phases 1-5)
   - Documented trigger mechanisms
   - Identified gaps in automation

2. **Root Cause Analysis for Each Issue**:
   - December gap: WHY it happened + prevention
   - November duplicates: WHY only those dates + fix
   - usage_rate coverage: Expected vs actual + action plan
   - usage_rate anomalies: Bug identified + fix
   - Phase transitions: Why manual intervention needed

3. **Systematic Improvement Plan**:
   - NOT just backfill commands
   - Code fixes to prevent recurrence
   - Monitoring to detect issues early
   - Validation framework for ongoing health checks

4. **Priority-Ordered Fixes**:
   - Fix root causes FIRST
   - Then backfill/cleanup as needed
   - Then validate fixes worked

---

## Tools and Resources

### Key Commands

```bash
# BigQuery queries
bq query --use_legacy_sql=false --location=us-west2 "SQL HERE"

# Cloud Run services
gcloud run services list --platform=managed --region=us-west2
gcloud run services describe SERVICE_NAME --region=us-west2

# Cloud Scheduler
gcloud scheduler jobs list --location=us-west2
gcloud scheduler jobs describe JOB_NAME --location=us-west2

# Pub/Sub
gcloud pubsub topics list
gcloud pubsub subscriptions list

# Logs
gcloud logging read 'FILTER' --limit=100 --format=json

# Git history
git log --oneline --since="2025-12-01" -- path/to/file
```

### Key Tables

- **Raw Data**: `nba-props-platform.nba_raw.nbac_gamebook`
- **Analytics**: `nba-props-platform.nba_analytics.player_game_summary`
- **Team Stats**: `nba-props-platform.nba_analytics.team_offense_game_summary`
- **Features**: `nba-props-platform.nba_precompute.ml_feature_store_v2`
- **Predictions**: `nba-props-platform.nba_predictions.player_prop_predictions`
- **Execution Log**: `nba-props-platform.nba_reference.processor_run_history`

### Documentation

- **Handoff Doc**: `docs/08-projects/current/2026-01-27-data-quality-investigation/HANDOFF-2026-01-28.md`
- **Scripts**: `scripts/backfill_*.py`, `bin/predictions/fix_stuck_coordinator.py`

---

## Important Reminders

1. **INVESTIGATE FIRST**: Don't backfill until you know WHY data is missing
2. **FIX ROOT CAUSES**: Don't patch symptoms, fix the underlying issues
3. **VALIDATE FIXES**: After fixing, verify the issue doesn't recur
4. **DOCUMENT**: Write clear root cause analysis for each issue
5. **THINK SYSTEMICALLY**: Look for patterns, not one-off fixes

---

## Example Starting Response

When you start the session, begin like this:

"I'm going to investigate the root causes of the data quality issues found in the previous session.

First, I'll map the complete data pipeline architecture to understand how data flows from Phase 1 (Raw) through Phase 5 (Predictions).

Then I'll systematically investigate each critical issue:
1. December analytics gap (WHY 15 days incomplete?)
2. November duplicates (WHY only Nov 10/13?)
3. usage_rate coverage (WHY only 60%?)
4. usage_rate anomalies (WHY values >100%?)
5. Manual phase triggers (WHY Phase 4 didn't auto-run?)

Let me start by mapping the pipeline architecture..."

---

**Good luck! Remember: Understand WHY, then fix systematically. Stop the band-aid cycle.**
