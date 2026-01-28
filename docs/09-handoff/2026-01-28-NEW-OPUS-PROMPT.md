# New Opus Chat Prompt - 2026-01-28

Copy everything below the line into a new Opus chat:

---

## Context

Continue from the 2026-01-28 Opus session. I've started 3 Sonnet chats working in parallel:

1. **Sonnet 1**: Creating NBA odds schedulers and triggering for Jan 28 (URGENT - games tonight)
2. **Sonnet 2**: Pushing commits and deploying Phase 3 processor with fixes
3. **Sonnet 3**: Auditing NBA vs MLB scheduler coverage for other gaps

## Read First

```
docs/09-handoff/2026-01-28-OPUS-SESSION-HANDOFF.md
```

This contains:
- All accomplishments from previous session (8 commits ready to push)
- Critical discovery: No NBA odds schedulers exist
- MLB vs NBA scheduler gap analysis
- Commands cheat sheet
- Remaining tasks

## Your Mission

1. **Coordinate and verify** the 3 Sonnet chats' work as they complete
2. **Continue improving** the system based on findings
3. **Run validation** once fixes are deployed to measure improvement

## Current System Status (as of ~4:30 PM PT)

| Component | Status |
|-----------|--------|
| Orchestrators | ✅ Fixed and deployed |
| Phase 3 backfill Jan 25-27 | ✅ Completed |
| Phase 4 backfill | ⚠️ Partial (dependency issues) |
| Prediction coordinator | ✅ Ready (no_active_batch) |
| Jan 28 betting lines | ❌ Not scraped (no scheduler) |
| Jan 28 predictions | ❌ Blocked by betting lines |
| Usage rate coverage | ⚠️ 60% (target 90%, fix committed not deployed) |

## Key Metrics to Track

After Sonnet chats complete their work, verify:

```bash
# Check if betting lines were scraped
bq query "SELECT COUNT(DISTINCT player_lookup) FROM nba_raw.odds_api_player_points_props WHERE game_date='2026-01-28'"

# Check has_prop_line status
bq query "SELECT game_date, COUNTIF(has_prop_line=TRUE) as with_lines, COUNT(*) as total FROM nba_analytics.upcoming_player_game_context WHERE game_date='2026-01-28' GROUP BY 1"

# Check predictions generated
bq query "SELECT COUNT(*) FROM nba_predictions.player_prop_predictions WHERE game_date='2026-01-28' AND is_active=TRUE"

# Check usage_rate coverage after reprocess
bq query "SELECT game_date, ROUND(100.0*COUNTIF(usage_rate IS NOT NULL)/COUNT(*),1) as usage_pct FROM nba_analytics.player_game_summary WHERE game_date>='2026-01-25' GROUP BY 1 ORDER BY 1"
```

## Priority Tasks for This Session

### If Sonnet chats succeeded:
1. Verify Jan 28 predictions exist
2. Run `/validate-daily 2026-01-28` to check system health
3. Verify usage_rate improved to 90%+
4. Check if other scheduler gaps were found and addressed

### If Sonnet chats had issues:
1. Debug and complete their tasks
2. Focus on getting Jan 28 predictions working (games tonight)

### Ongoing improvements:
1. Fix Phase 3 timing race condition (Task #7 from previous session)
2. Improve prediction coordinator reliability (Task #8)
3. Add any missing schedulers identified by Sonnet 3

## Git Status

8 commits should be pushed by Sonnet 2:
- Orchestrator symlink fixes
- Import validation improvements
- Pre-commit hooks
- CI pipeline updates
- Post-deployment health check
- Team stats deduplication
- Handoff documentation

## Files Modified in Previous Session

```
orchestration/cloud_functions/phase3_to_phase4/shared/utils/*.py
orchestration/cloud_functions/phase4_to_phase5/shared/utils/*.py
bin/validation/validate_cloud_function_imports.py
bin/validation/post_deployment_health_check.py
.pre-commit-config.yaml
.github/workflows/deployment-validation.yml
data_processors/analytics/team_offense_game_summary/team_offense_game_summary_processor.py
data_processors/analytics/team_defense_game_summary/team_defense_game_summary_processor.py
docs/09-handoff/2026-01-28-OPUS-SESSION-HANDOFF.md
```

## Philosophy

Every error we find → ask "what else might have this same problem?" → systematic audit → prevention framework

Example: Missing odds scheduler → audit all MLB vs NBA schedulers → found multiple gaps → create prevention checklist
