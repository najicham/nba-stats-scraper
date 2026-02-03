# Opus Review Prompt: Phase 6 Enhancement Implementation Review

Copy the prompt below and paste it into a new Opus chat session for comprehensive review.

---

## PROMPT FOR OPUS

I need you to review an implementation plan for enhancing our NBA stats system's Phase 6 (data publishing) layer. Your task is to use multiple agents to thoroughly study the system and provide a comprehensive implementation review.

### Context

We have a production NBA prediction system with 6 phases:
- **Phase 1**: Scrapers (NBA.com, odds APIs, etc.)
- **Phase 2**: Raw data processors
- **Phase 3**: Analytics processors
- **Phase 4**: Precompute processors
- **Phase 5**: Prediction generation
- **Phase 6**: Publishing & exports (JSON API for website)

**Current Situation:**
- We have two major features built in backend that are NOT exposed to the website:
  1. **Dynamic Subsets** (Sessions 70-71): Signal-aware pick filtering, 9 active subsets, 82% hit rate on GREEN signal days
  2. **Model Attribution** (Session 84): Model training metadata, provenance tracking (fields exist in DB but not exported)

**Recent Research (Session 86):**
- Created implementation plan for exposing these features through Phase 6
- Proposes 5 new endpoints + modifications to 3 existing endpoints
- Full documentation in `docs/08-projects/current/phase6-subset-model-enhancements/`

### Your Task

**Use multiple Task agents in parallel to:**

1. **Review the Implementation Plan** (`IMPLEMENTATION_PLAN.md`)
   - Assess technical feasibility
   - Identify potential risks or gaps
   - Verify database queries are correct
   - Check if orchestration changes are complete

2. **Study the Existing Phase 6 System** (use agents to explore)
   - Understand current exporter architecture (`data_processors/publishing/`)
   - Study orchestration flow (`orchestration/cloud_functions/phase6_export/`)
   - Review existing JSON output structure
   - Identify patterns and conventions to follow

3. **Validate Data Availability** (use agents to verify)
   - Confirm all required tables exist (`dynamic_subset_definitions`, `daily_prediction_signals`, etc.)
   - Verify Session 84 model attribution fields exist in `player_prop_predictions` table
   - Check if views referenced in plan exist (`v_dynamic_subset_performance`)
   - Test query patterns from implementation plan

4. **Review Subset System Implementation** (use agents to explore)
   - Study subset architecture in `docs/08-projects/current/subset-pick-system/`
   - Review pre-game signals in `docs/08-projects/current/pre-game-signals-strategy/`
   - Check subset skills: `/.claude/skills/subset-picks/`, `/.claude/skills/subset-performance/`
   - Understand signal calculation logic

5. **Review Model Attribution System** (use agents to explore)
   - Find where model metadata is stored (code and database)
   - Check Session 84 implementation (`docs/08-projects/current/model-attribution-tracking/`)
   - Verify TRAINING_INFO dicts in `predictions/worker/prediction_systems/*.py`
   - Confirm model tracking fields are populated

6. **Analyze JSON Structure** (review `JSON_EXAMPLES.md`)
   - Validate JSON examples match database schema
   - Check consistency with existing Phase 6 patterns
   - Verify all necessary fields are included
   - Assess frontend usability

### Specific Questions to Answer

1. **Implementation Plan Quality:**
   - Is the plan complete? What's missing?
   - Are the database queries correct and efficient?
   - Are there any schema mismatches?
   - Is the orchestration integration clear?

2. **Risk Assessment:**
   - What could go wrong during implementation?
   - Are there backward compatibility concerns?
   - What's the rollback strategy if issues arise?
   - Are there performance implications (BigQuery quota, GCS write volume)?

3. **Data Validation:**
   - Do all referenced tables and views exist?
   - Are Session 84 fields actually populated with data?
   - Do the 9 subsets exist and have performance data?
   - Is daily signal calculation working?

4. **Architecture Review:**
   - Does this fit Phase 6 patterns?
   - Should any exporters be combined or split?
   - Are there redundant queries or computations?
   - Is caching strategy appropriate?

5. **Frontend Integration:**
   - Are JSON examples realistic and complete?
   - Is the API structure intuitive?
   - Are there missing fields frontend might need?
   - Should any endpoints be paginated?

6. **Alternative Approaches:**
   - Should we consider GraphQL instead of JSON files?
   - Should subset filtering happen in Phase 6 or backend?
   - Is there a simpler way to expose model metadata?
   - Should we create aggregated endpoints to reduce API calls?

### Key Files to Study

**Implementation Docs (Session 86):**
- `docs/08-projects/current/phase6-subset-model-enhancements/IMPLEMENTATION_PLAN.md`
- `docs/08-projects/current/phase6-subset-model-enhancements/FINDINGS_SUMMARY.md`
- `docs/08-projects/current/phase6-subset-model-enhancements/JSON_EXAMPLES.md`

**Existing Phase 6 Code:**
- `data_processors/publishing/` (all exporters)
- `data_processors/publishing/base_exporter.py` (base class)
- `orchestration/cloud_functions/phase6_export/main.py` (orchestrator)

**Subset System:**
- `docs/08-projects/current/subset-pick-system/`
- `docs/08-projects/current/pre-game-signals-strategy/`
- `/.claude/skills/subset-picks/SKILL.md`
- `/.claude/skills/subset-performance/SKILL.md`

**Model Attribution:**
- `docs/08-projects/current/model-attribution-tracking/`
- `predictions/worker/prediction_systems/catboost_v9.py` (TRAINING_INFO)

**BigQuery Schemas:**
- `schemas/bigquery/predictions/04_pick_subset_definitions.sql`
- `schemas/bigquery/predictions/01_player_prop_predictions.sql` (check for Session 84 fields)

**Reference (CRITICAL):**
- `CLAUDE.md` (project conventions, hit rate definitions, known issues)

### Expected Deliverables

Provide a comprehensive review document with:

1. **Executive Summary**
   - Overall assessment (Ready/Needs Work/Major Issues)
   - Top 3 risks
   - Recommended next steps

2. **Technical Review**
   - Implementation plan completeness
   - Code architecture assessment
   - Database schema validation
   - Query correctness verification

3. **Risk Analysis**
   - Potential issues and mitigation strategies
   - Performance considerations
   - Backward compatibility concerns
   - Rollback procedures

4. **Data Validation Report**
   - Which tables/views exist
   - Which fields are populated
   - Sample data verification
   - Any data quality issues found

5. **Alternative Approaches**
   - Different architectural options
   - Pros/cons of each approach
   - Recommendation with rationale

6. **Implementation Recommendations**
   - Priority order (what to build first)
   - Quick wins vs long-term improvements
   - Testing strategy
   - Deployment sequence

### Important Context from CLAUDE.md

**Hit Rate Standards:**
- Premium picks: `confidence >= 0.92 AND edge >= 3` (target: 50-58% HR)
- High-edge picks: `edge >= 5` (target: 70-78% HR)

**Current Production Model:**
- System: `catboost_v9`
- Model file: `catboost_v9_feb_02_retrain.cbm`
- Training: Nov 2, 2025 - Jan 31, 2026
- Expected MAE: 4.12
- Expected high-edge HR: 74.6%

**Grading Table (CRITICAL):**
- Use `prediction_accuracy` table (419K+ records)
- NOT `prediction_grades` (deprecated, Jan 2026 only)

**Known Issues to Watch:**
- BigQuery partition filter requirements (some tables require `game_date >= ...`)
- Schema mismatches (Session 58 issue)
- Deployment drift (fix not deployed until next day)
- Silent BigQuery write failures (Session 59)

### How to Use Agents Effectively

**Recommended approach:**

1. **Launch 5-6 agents in PARALLEL** (single message with multiple Task calls):
   ```
   Task 1: "Review implementation plan in docs/08-projects/current/phase6-subset-model-enhancements/"
   Task 2: "Study existing Phase 6 exporters in data_processors/publishing/"
   Task 3: "Verify subset system tables and data in BigQuery schemas"
   Task 4: "Check model attribution implementation from Session 84"
   Task 5: "Explore orchestration flow for Phase 6 exports"
   Task 6: "Validate JSON examples against actual data structures"
   ```

2. **Use subagent_type appropriately:**
   - `Explore`: For researching code, finding patterns, understanding architecture
   - `general-purpose`: For running queries, testing code, verification tasks

3. **Give detailed prompts:**
   - Include file paths when known
   - Reference specific line numbers from implementation plan
   - Ask agents to verify specific claims (e.g., "Does table X have field Y?")

4. **Synthesize findings:**
   - Wait for all agents to complete
   - Combine insights into comprehensive review
   - Identify contradictions or gaps between agent findings

### Key Questions About Subset System (for agents to verify)

1. **Do these tables exist with data?**
   - `nba_predictions.dynamic_subset_definitions` (expect 9 rows)
   - `nba_predictions.daily_prediction_signals` (expect daily rows since Dec 17, 2025)
   - `nba_predictions.v_dynamic_subset_performance` (view)

2. **Subset definitions - are all 9 active?**
   - v9_high_edge_top1
   - v9_high_edge_top3
   - v9_high_edge_top5
   - v9_high_edge_top10
   - v9_high_edge_balanced (GREEN only)
   - v9_high_edge_any (no signal filter)
   - v9_high_edge_warning (RED only)
   - v9_premium_safe (GREEN_OR_YELLOW)
   - v9_high_edge_top5_balanced (top 5 + GREEN)

3. **Signal calculation:**
   - How is `pct_over` calculated?
   - What are the thresholds (GREEN: 25-40%, RED: <25% or >40%)?
   - Where does signal get computed? (Which processor/job)

4. **Performance data:**
   - Does `v_dynamic_subset_performance` have 47+ days of data?
   - Are hit rates realistic (70-85% range)?
   - Do signal breakdowns exist (GREEN vs RED performance)?

### Key Questions About Model Attribution (for agents to verify)

1. **Do Session 84 fields exist in `player_prop_predictions` table?**
   - `model_file_name`
   - `model_training_start_date`
   - `model_training_end_date`
   - `model_expected_mae`
   - `model_expected_hit_rate`
   - `model_trained_at`

2. **Are these fields actually populated with data?**
   - Query recent predictions (last 7 days)
   - Check if fields are NULL or have values
   - Verify values match expected (e.g., "catboost_v9_feb_02_retrain.cbm")

3. **Where is model metadata stored in code?**
   - Check `predictions/worker/prediction_systems/catboost_v9.py`
   - Look for `TRAINING_INFO` dictionary
   - Verify it has training dates, MAE, hit rate targets

4. **How are these fields populated?**
   - Which code writes these fields during prediction generation?
   - Is it in prediction worker or coordinator?

### Success Criteria for Your Review

Your review should:
- ✅ Be backed by agent findings (not speculation)
- ✅ Include specific file paths, line numbers, query results
- ✅ Identify concrete gaps or issues (not vague concerns)
- ✅ Propose actionable alternatives if plan has issues
- ✅ Validate implementation plan against actual system state
- ✅ Check for consistency with project conventions (CLAUDE.md)

### Output Format

Structure your response as:

```markdown
# Phase 6 Enhancement Implementation Review

## Executive Summary
[3-5 paragraphs with overall assessment]

## Agent Research Findings

### Agent 1: Implementation Plan Review
[What agent found, key insights]

### Agent 2: Phase 6 System Study
[Current architecture analysis]

### Agent 3: Data Validation
[Tables verified, fields checked, sample data]

### Agent 4: Subset System Verification
[Subset data validation results]

### Agent 5: Model Attribution Check
[Session 84 field verification]

### Agent 6: JSON Structure Review
[Frontend integration assessment]

## Technical Assessment

### Implementation Plan Quality
[Detailed analysis]

### Architecture Review
[Fit with existing patterns]

### Database Validation
[Schema correctness, query validation]

## Risk Analysis

### Critical Risks
[High priority issues]

### Performance Concerns
[BigQuery quota, GCS volume, caching]

### Backward Compatibility
[Breaking changes, migration needed]

## Alternative Approaches

### Option 1: [Approach Name]
**Description:** ...
**Pros:** ...
**Cons:** ...
**Effort:** ...

### Option 2: [Approach Name]
**Description:** ...
**Pros:** ...
**Cons:** ...
**Effort:** ...

### Recommended Approach
[Which option and why]

## Implementation Recommendations

### Phase 1: [What to build first]
**Priority:** HIGH/MEDIUM/LOW
**Effort:** X days
**Risk:** LOW/MEDIUM/HIGH
**Deliverables:** ...

### Phase 2: [Next step]
...

### Testing Strategy
[How to validate each phase]

### Deployment Sequence
[Order of deployments, dependencies]

## Action Items

### Before Implementation
- [ ] [Specific task with owner]
- [ ] [Specific task with owner]

### During Implementation
- [ ] [Specific task]
- [ ] [Specific task]

### Post-Implementation
- [ ] [Specific task]
- [ ] [Specific task]

## Questions for Clarification
[Unanswered questions that need product/business input]

## Conclusion
[Final recommendation: Go/No-Go/Needs Work]
```

### Important Notes

1. **Use agents liberally** - Spawn 5-6 agents in parallel for comprehensive research
2. **Verify everything** - Don't trust implementation plan without checking actual system
3. **Check Session 84** - This is critical - if model attribution fields don't exist, plan won't work
4. **Test queries** - Run sample queries from implementation plan against actual BigQuery
5. **Follow conventions** - Reference CLAUDE.md for standards (hit rate filters, table names, etc.)
6. **Be specific** - Don't say "looks good" - provide concrete evidence or specific issues
7. **Consider alternatives** - If plan has issues, propose better approaches

### Context about the System

**Production Environment:**
- GCP Project: `nba-props-platform`
- Region: `us-west2`
- BigQuery datasets: `nba_predictions`, `nba_analytics`, `nba_raw`, `nba_reference`
- GCS bucket: `gs://nba-props-platform-api/v1/`
- Cloud Run services: Multiple (prediction-worker, prediction-coordinator, etc.)

**Current Phase 6:**
- 21 exporters creating JSON files
- Exports triggered by Phase 5 completion (Pub/Sub)
- GCS used as static JSON API
- No database backend for website - pure JSON files

**Development History:**
- Session 70-71: Built dynamic subset system
- Session 84: Added model attribution fields
- Session 86: Researched what to expose to website (created docs you're reviewing)

Begin your review by launching multiple agents to research the system in parallel. Then synthesize findings into the comprehensive review format above.
