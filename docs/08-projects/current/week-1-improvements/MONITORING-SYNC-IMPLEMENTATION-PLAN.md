# Monitoring Config Sync System - Implementation Plan

**Created:** January 21, 2026
**Owner:** Data Platform Team
**Timeline:** 3 phases over 3 weeks
**Status:** Ready for Execution

---

## Executive Summary

This document outlines a phased approach to implementing the Monitoring Config Sync System, addressing the br_roster configuration mismatch discovered on Jan 21, 2026, and preventing future config drift issues.

**Problem:** Configurations got out of sync with infrastructure reality (br_roster vs br_rosters_current in 10 files)

**Solution:** Single Source of Truth (SSOT) with automated config generation and validation

**Timeline:** 3 weeks
- Phase 1 (Week 1): Fix immediate issue + Create SSOT for Phase 2
- Phase 2 (Week 2): Expand to all phases + Automation
- Phase 3 (Week 3): CI/CD integration + Documentation

---

## Phase 1: Immediate Fixes & Foundation (Week 1)

**Goal:** Fix br_roster issue and establish SSOT for Phase 2 processors

**Duration:** 5 days (Jan 22-26, 2026)

### Day 1-2: Fix br_roster Issue

#### Task 1.1: Update Orchestration Configs (2 hours)

**Files to Update (10 total):**
1. `/shared/config/orchestration_config.py:32`
2. `/predictions/coordinator/shared/config/orchestration_config.py:32`
3. `/predictions/worker/shared/config/orchestration_config.py:32`
4. `/orchestration/cloud_functions/phase2_to_phase3/shared/config/orchestration_config.py:32`
5. `/orchestration/cloud_functions/phase3_to_phase4/shared/config/orchestration_config.py:32`
6. `/orchestration/cloud_functions/phase4_to_phase5/shared/config/orchestration_config.py:32`
7. `/orchestration/cloud_functions/phase5_to_phase6/shared/config/orchestration_config.py:32`
8. `/orchestration/cloud_functions/self_heal/shared/config/orchestration_config.py:32`
9. `/orchestration/cloud_functions/daily_health_summary/shared/config/orchestration_config.py:32`
10. `/orchestration/cloud_functions/phase2_to_phase3/main.py:87`

**Change Required:**
```python
# FROM:
'br_roster',                  # Basketball-ref rosters

# TO:
'br_rosters_current',         # Basketball-ref rosters
```

**Steps:**
1. Create branch: `fix/br-roster-config-mismatch`
2. Use search-replace across all 10 files
3. Test locally with pytest
4. Create PR with detailed description
5. Deploy to staging
6. Verify Firestore tracking works
7. Deploy to production

**Success Criteria:**
- ✅ All 10 files updated
- ✅ Tests passing
- ✅ Firestore shows `br_rosters_current` in completed_processors
- ✅ No monitoring alerts

#### Task 1.2: Fix Monitoring Query Comments (30 min)

**File:** `bin/operations/monitoring_queries.sql:322`

**Change:**
```sql
-- FROM:
-- Track which games are using fallback data sources (nbac_gamebook instead of bdl_player_boxscores)

-- TO:
-- Track which games are using fallback data sources (nbac_gamebook_player_stats instead of bdl_player_boxscores)
```

### Day 3-4: Create SSOT for Phase 2

#### Task 1.3: Create SSOT Directory Structure (1 hour)

```bash
mkdir -p schemas/processors
mkdir -p schemas/infrastructure
```

#### Task 1.4: Create Phase 2 Processors SSOT (3 hours)

**File:** `schemas/processors/phase2_raw_processors.yaml`

**Content:** Complete YAML with all 6 critical processors

```yaml
version: "1.0"
phase: 2
phase_name: "raw_data_ingestion"
dataset: "nba_raw"

critical_processors:
  - name: bdl_player_boxscores
    class: BdlPlayerBoxScoresProcessor
    target_table: bdl_player_boxscores
    schedule: post_game
    required: true
    description: "Daily box scores from Ball Don't Lie API"

  - name: bigdataball_play_by_play
    class: BigDataBallPbpProcessor
    target_table: bigdataball_play_by_play
    schedule: post_game
    required: true
    description: "Per-game play-by-play data"

  - name: odds_api_game_lines
    class: OddsGameLinesProcessor
    target_table: odds_api_game_lines
    schedule: pre_game
    required: true
    description: "Pre-game odds and betting lines"

  - name: nbac_schedule
    class: NbacScheduleProcessor
    target_table: nbac_schedule
    schedule: daily_morning
    required: true
    description: "NBA schedule from NBA.com"

  - name: nbac_gamebook_player_stats
    class: NbacGamebookProcessor
    target_table: nbac_gamebook_player_stats
    schedule: post_game
    required: true
    description: "Official gamebook player stats"

  - name: br_rosters_current
    class: BasketballRefRosterProcessor
    target_table: br_rosters_current
    schedule: daily_6am_et
    required: false
    description: "Current NBA rosters from Basketball Reference"
    notes: "May not publish daily if no roster changes"

orchestration:
  expected_count: 6
  trigger_mode: all_complete
  timeout_minutes: 30
  enable_deadline_monitoring: true
```

**Steps:**
1. Create YAML file
2. Validate YAML syntax
3. Document in README
4. Commit to git

#### Task 1.5: Create Basic Validation Script (4 hours)

**File:** `bin/validate_config_sync.sh`

**Features:**
- Check BigQuery tables exist for all processors
- Verify processor count matches SSOT
- Basic health checks

**Steps:**
1. Create script following MONITORING-CONFIG-SYNC-SYSTEM.md design
2. Test with Phase 2 processors
3. Document usage
4. Add to pre-deployment checklist

### Day 5: Testing & Documentation

#### Task 1.6: Create Validation Tests (3 hours)

**File:** `tests/config_validation/test_orchestration_consistency.py`

**Tests:**
- `test_processor_names_match_ssot` - Config matches SSOT
- `test_all_tables_exist` - Tables exist in BigQuery
- `test_expected_processor_count` - Count matches SSOT

**Steps:**
1. Create test file
2. Run locally
3. Verify all pass
4. Document test coverage

#### Task 1.7: Update Documentation (2 hours)

**Documents to Create/Update:**
1. `MONITORING-CONFIG-SYNC-SYSTEM.md` - Full system design ✅ (Created)
2. `MONITORING-SYNC-QUICK-REF.md` - Quick reference ✅ (Created)
3. `MONITORING-SYNC-IMPLEMENTATION-PLAN.md` - This document
4. `README.md` in `schemas/` - SSOT documentation

### Phase 1 Deliverables

- ✅ br_roster issue fixed in 10 files
- ✅ Phase 2 SSOT YAML created
- ✅ Basic validation script working
- ✅ Test suite for Phase 2
- ✅ Documentation complete

**Time Investment:** 20 hours (4 hours/day for 5 days)

---

## Phase 2: Expansion & Automation (Week 2)

**Goal:** Expand SSOT to all phases and create automation tools

**Duration:** 5 days (Jan 29 - Feb 2, 2026)

### Day 1-2: Expand SSOT to All Phases

#### Task 2.1: Create Phase 3 SSOT (3 hours)

**File:** `schemas/processors/phase3_analytics_processors.yaml`

**Content:** 5 critical analytics processors

```yaml
version: "1.0"
phase: 3
phase_name: "analytics_generation"
dataset: "nba_analytics"

critical_processors:
  - name: player_game_summary
    class: PlayerGameSummaryProcessor
    target_table: player_game_summary

  - name: team_defense_game_summary
    class: TeamDefenseGameSummaryProcessor
    target_table: team_defense_game_summary

  - name: team_offense_game_summary
    class: TeamOffenseGameSummaryProcessor
    target_table: team_offense_game_summary

  - name: upcoming_player_game_context
    class: UpcomingPlayerGameContextProcessor
    target_table: upcoming_player_game_context

  - name: upcoming_team_game_context
    class: UpcomingTeamGameContextProcessor
    target_table: upcoming_team_game_context
```

#### Task 2.2: Create Phase 4 SSOT (2 hours)

**File:** `schemas/processors/phase4_precompute_processors.yaml`

**Content:** 5 precompute processors

```yaml
version: "1.0"
phase: 4
phase_name: "precompute_features"
dataset: "nba_precompute"

critical_processors:
  - name: player_composite_factors
  - name: player_shot_zone_analysis
  - name: team_defense_zone_analysis
  - name: player_daily_cache
  - name: ml_feature_store
```

#### Task 2.3: Create Infrastructure SSOT (3 hours)

**File:** `schemas/infrastructure/bigquery_tables.yaml`
**File:** `schemas/infrastructure/cloud_run_services.yaml`
**File:** `schemas/infrastructure/pubsub_topics.yaml`

**Content:** Complete inventory of all infrastructure

### Day 3-4: Create Config Generation Tool

#### Task 2.4: Create Config Generator (6 hours)

**File:** `bin/generate_configs.py`

**Features:**
- Validate SSOT YAML files
- Generate orchestration configs from SSOT
- Verify configs match infrastructure
- Support --validate, --generate, --verify, --all modes

**Implementation:**
- Follow design in MONITORING-CONFIG-SYNC-SYSTEM.md
- Support Phase 2, 3, 4 processors
- Generate comments with SSOT metadata
- Auto-update all config file locations

**Steps:**
1. Implement ConfigGenerator class
2. Add validation logic
3. Add generation logic
4. Add verification logic
5. Test with all phases
6. Document usage

#### Task 2.5: Create Monitoring Query Sync Tool (3 hours)

**File:** `bin/sync_monitoring_queries.py`

**Features:**
- Read processor definitions from SSOT
- Generate table verification queries
- Update monitoring_queries.sql
- Validate queries actually work

**Steps:**
1. Implement query generation
2. Test with Phase 2 processors
3. Expand to Phase 3, 4
4. Document usage

### Day 5: Config Drift Detection

#### Task 2.6: Create Drift Auditor (4 hours)

**File:** `bin/audit_config_drift.py`

**Features:**
- Compare SSOT to deployed configs
- Flag mismatches
- Suggest fixes
- Report on drift severity

**Steps:**
1. Implement ConfigDriftAuditor class
2. Add comparison logic
3. Add reporting
4. Test with current configs
5. Document usage

### Phase 2 Deliverables

- ✅ SSOT for Phase 3 and 4 created
- ✅ Infrastructure SSOT created
- ✅ Config generation tool working
- ✅ Monitoring query sync tool working
- ✅ Config drift detection working

**Time Investment:** 21 hours (4-5 hours/day for 5 days)

---

## Phase 3: CI/CD Integration & Completion (Week 3)

**Goal:** Integrate into CI/CD pipeline and complete documentation

**Duration:** 5 days (Feb 5-9, 2026)

### Day 1-2: CI/CD Integration

#### Task 3.1: Create GitHub Actions Workflow (3 hours)

**File:** `.github/workflows/config-validation.yml`

**Content:**
```yaml
name: Config Validation

on: [push, pull_request]

jobs:
  validate-configs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
      - name: Install dependencies
        run: pip install pytest pyyaml google-cloud-bigquery
      - name: Validate SSOT
        run: python bin/generate_configs.py --validate
      - name: Run consistency tests
        run: pytest tests/config_validation/
```

**Steps:**
1. Create workflow file
2. Test in feature branch
3. Verify runs on PR
4. Document in README

#### Task 3.2: Add Pre-Commit Hooks (2 hours)

**File:** `.pre-commit-config.yaml`

**Hooks:**
- Validate SSOT YAML syntax
- Check for manual edits to generated files
- Run quick validation tests

**Steps:**
1. Create pre-commit config
2. Test locally
3. Document setup in README

### Day 3: Enhanced Testing

#### Task 3.3: Expand Test Coverage (4 hours)

**New Tests:**
- `test_no_hardcoded_table_names` - No hardcoded refs
- `test_service_urls_reachable` - Services deployed
- `test_pubsub_topics_exist` - Topics exist
- `test_config_generation_idempotent` - Regenerating produces same output

**Steps:**
1. Add tests to test_orchestration_consistency.py
2. Run full test suite
3. Verify 100% pass rate
4. Document test coverage

#### Task 3.4: Add Integration Tests (3 hours)

**Tests:**
- End-to-end config generation
- Full validation workflow
- Drift detection

**Steps:**
1. Create integration test suite
2. Test in staging environment
3. Document test scenarios

### Day 4: Documentation Completion

#### Task 3.5: Create Pre-Deployment Checklist (2 hours)

**File:** `docs/deployment/PRE-DEPLOYMENT-CHECKLIST.md`

**Content:**
- Before every deployment steps
- Phase-specific checklists
- Emergency rollback plan
- Sign-off template

**Steps:**
1. Create comprehensive checklist
2. Review with operations team
3. Integrate into deployment process

#### Task 3.6: Create Change Management Procedures (2 hours)

**File:** `docs/operations/CHANGE-MANAGEMENT-PROCEDURES.md`

**Content:**
- Adding new processor procedure
- Renaming table procedure
- Changing processor count procedure
- Emergency sync procedure

**Steps:**
1. Document all procedures
2. Add examples
3. Review with team

#### Task 3.7: Create Monthly Review Template (1 hour)

**File:** `docs/operations/MONTHLY-CONFIG-REVIEW-TEMPLATE.md`

**Content:**
- Checklist for monthly audit
- Config drift review
- SSOT updates needed
- Infrastructure changes
- Lessons learned

### Day 5: Training & Rollout

#### Task 3.8: Team Training (3 hours)

**Activities:**
- Present system design
- Demo tools and workflows
- Hands-on practice
- Q&A session

**Materials:**
- Presentation slides
- Demo script
- Practice exercises

#### Task 3.9: Final Validation (2 hours)

**Activities:**
- Run complete validation
- Test all tools
- Verify documentation
- Check CI/CD pipeline

**Checklist:**
- [ ] All SSOT files created
- [ ] All tools working
- [ ] All tests passing
- [ ] CI/CD integrated
- [ ] Documentation complete
- [ ] Team trained

### Phase 3 Deliverables

- ✅ CI/CD integration complete
- ✅ Pre-commit hooks active
- ✅ Full test coverage achieved
- ✅ Documentation complete
- ✅ Team trained

**Time Investment:** 22 hours (4-5 hours/day for 5 days)

---

## Timeline Summary

| Phase | Duration | Time Investment | Key Deliverables |
|-------|----------|-----------------|------------------|
| Phase 1 | Week 1 (5 days) | 20 hours | br_roster fix, Phase 2 SSOT, basic validation |
| Phase 2 | Week 2 (5 days) | 21 hours | All phase SSOT, automation tools |
| Phase 3 | Week 3 (5 days) | 22 hours | CI/CD, testing, documentation |
| **Total** | **3 weeks** | **63 hours** | **Complete system** |

---

## Resource Allocation

### Team Requirements

**Core Team (Required):**
- 1 Senior Engineer (full-time, 3 weeks) - System design & implementation
- 1 Data Engineer (part-time, 2 weeks) - SSOT creation, validation
- 1 DevOps Engineer (part-time, 1 week) - CI/CD integration

**Supporting Team (As Needed):**
- Tech Lead - Design review, final approval
- QA Engineer - Testing support
- Technical Writer - Documentation review

### Skills Required

**Must Have:**
- Python development
- YAML configuration
- BigQuery
- Google Cloud Platform
- Git/GitHub

**Nice to Have:**
- pytest experience
- GitHub Actions
- Shell scripting
- Technical writing

---

## Success Criteria

### Phase 1 Success
- ✅ br_roster issue resolved in production
- ✅ Phase 2 SSOT created and validated
- ✅ Basic validation working
- ✅ Zero production incidents

### Phase 2 Success
- ✅ All phases have SSOT
- ✅ Config generation working
- ✅ Monitoring queries auto-updated
- ✅ Drift detection working

### Phase 3 Success
- ✅ CI/CD running on all PRs
- ✅ 100% test pass rate
- ✅ Documentation complete
- ✅ Team trained and confident

### Overall Success
- ✅ No config drift for 30 days post-implementation
- ✅ Zero deployment incidents due to config issues
- ✅ 100% adoption by team
- ✅ Tool usage in 100% of deployments
- ✅ Positive team feedback

---

## Risks & Mitigation

### Risk 1: Breaking Existing Workflows
**Likelihood:** Medium
**Impact:** High

**Mitigation:**
- Deploy Phase 1 fix without SSOT dependency
- Introduce SSOT alongside existing configs
- Gradual migration, not big bang
- Extensive testing in staging

### Risk 2: Team Resistance to New Process
**Likelihood:** Low
**Impact:** Medium

**Mitigation:**
- Demonstrate value early (br_roster fix)
- Make tools easy to use
- Comprehensive documentation
- Hands-on training
- Quick wins and success stories

### Risk 3: Tool Bugs Causing Deployment Issues
**Likelihood:** Medium
**Impact:** High

**Mitigation:**
- Extensive testing before rollout
- Manual verification checklist
- Gradual rollout
- Easy rollback procedures
- Monitoring for issues

### Risk 4: Incomplete SSOT Coverage
**Likelihood:** Low
**Impact:** Medium

**Mitigation:**
- Comprehensive inventory upfront
- Validation tests catch gaps
- Iterative improvement
- Regular audits

### Risk 5: CI/CD Pipeline Delays
**Likelihood:** Medium
**Impact:** Low

**Mitigation:**
- Optimize test execution time
- Parallel test execution
- Cache dependencies
- Optional full validation (manual trigger)

---

## Maintenance Plan

### Daily
- Automated CI/CD validation on every PR
- Pre-commit hooks validate local changes

### Weekly
- Review config validation test results
- Address any failures immediately

### Monthly
- Run full config drift audit
- Review and update SSOT as needed
- Check for infrastructure changes
- Update documentation

### Quarterly
- Team retrospective on tool usage
- Identify improvements
- Update training materials
- Review success metrics

---

## Next Steps (Immediate)

### This Week (Jan 22-26)
1. **Monday:** Create branch, fix br_roster in 10 files
2. **Tuesday:** Test fix, deploy to staging
3. **Wednesday:** Deploy to production, create SSOT directory
4. **Thursday:** Create Phase 2 SSOT YAML
5. **Friday:** Create basic validation script, test

### Next Week (Jan 29 - Feb 2)
1. Expand SSOT to Phase 3, 4, infrastructure
2. Create config generation tool
3. Create monitoring query sync tool
4. Create config drift auditor

### Week After (Feb 5-9)
1. CI/CD integration
2. Complete testing
3. Finalize documentation
4. Team training
5. Launch

---

## Appendix: Tool Usage Examples

### Example 1: Adding New Processor

```bash
# 1. Update SSOT
vi schemas/processors/phase2_raw_processors.yaml
# Add new processor definition

# 2. Create table
bq mk --table nba-props-platform:nba_raw.new_table schema.json

# 3. Validate SSOT
python bin/generate_configs.py --validate

# 4. Generate configs
python bin/generate_configs.py --generate

# 5. Review changes
git diff

# 6. Test
pytest tests/config_validation/

# 7. Commit
git add schemas/ shared/ orchestration/
git commit -m "Add new processor: new_processor_name"

# 8. Deploy
gcloud run deploy ...
```

### Example 2: Monthly Audit

```bash
# 1. Check for drift
python bin/audit_config_drift.py

# 2. Validate current state
python bin/validate_config_sync.sh

# 3. Run full test suite
pytest tests/config_validation/

# 4. Review monitoring queries
# Run queries in bin/operations/monitoring_queries.sql

# 5. Update SSOT if needed
vi schemas/processors/*.yaml

# 6. Regenerate if updated
python bin/generate_configs.py --all

# 7. Document findings
# Add to monthly review report
```

---

**Implementation Plan Version:** 1.0
**Created:** January 21, 2026
**Owner:** Data Platform Team
**Status:** Ready for Execution
**Next Review:** End of Phase 1 (Jan 26, 2026)

