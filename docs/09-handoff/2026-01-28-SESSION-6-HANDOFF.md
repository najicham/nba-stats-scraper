# Session 6 Handoff - January 28, 2026

## Quick Start for Next Session

```bash
# 1. Read this document first
# 2. Run daily validation
/validate-daily

# 3. Check deployment drift
./bin/check-deployment-drift.sh --verbose

# 4. Use agents liberally for investigation and fixes
```

---

## Session Summary

This session performed comprehensive investigation and fixes using 6 parallel agents to tackle multiple issues simultaneously. We identified several root causes and deployed fixes to critical services.

### Issues Investigated (6 Parallel Agents)

| Issue | Finding | Status |
|-------|---------|--------|
| Jan 26-27 predictions missing | Feature version mismatch (v2_34 vs v2_33) | Root cause identified |
| Phase 2 trigger not working | Processor name normalization bug (missing p2_ prefix) | Fixed |
| Phase 3 errors | Missing boxscores for 2 games | Expected behavior |
| Low prediction coverage | Phase 3 timing + quality filters | Understood |
| Deployment drift | 3 services needed redeployment | Fixed |
| Data quality issues | game_id format inconsistency causing duplicates | In progress |

### Commits Made

| Commit | Description |
|--------|-------------|
| Phase 2 processor name mapping | Added CLASS_TO_CONFIG_MAP for explicit mapping |
| `ac1d4c47` | fix: Revert to v2_33features, fix Phase 2 trigger, add upgrade guide |
| `968323e6` | fix: Replace hardcoded path with relative path in batch_state_manager |

### Services Deployed

| Service | Old Revision | New Revision | Status |
|---------|--------------|--------------|--------|
| nba-phase3-analytics-processors | 00130 | 00131 | Current |
| nba-phase4-precompute-processors | 00062 | 00063 | Current |
| prediction-coordinator | 00093 | 00094 | Current |

---

## Final Results

### Features Regenerated
- **Date Range**: Jan 25-27, 2026
- **Feature Version**: v2_33features (reverted from v2_34)
- **Status**: Successfully regenerated with correct feature count

### Predictions Generated
| Game Date | Predictions | Status |
|-----------|-------------|--------|
| Jan 25, 2026 | 1,354 | Complete |
| Jan 26, 2026 | 723 | Complete |
| Jan 27, 2026 | 697 | Complete |
| Jan 28, 2026 | 2,629 | Complete |

### Services Redeployed (Final)
| Service | Old Revision | New Revision |
|---------|--------------|--------------|
| nba-phase4-precompute-processors | 00062 | 00063 |

---

## Fixes Applied

| Fix | Commit/Change | Files |
|-----|---------------|-------|
| Phase 2 processor name mapping | Added CLASS_TO_CONFIG_MAP | `orchestration/cloud_functions/phase2_to_phase3/main.py` |
| Redeployed Phase 3 | 00130 to 00131 | nba-phase3-analytics-processors |
| Redeployed Phase 4 | 00061 to 00062 | nba-phase4-precompute-processors |
| Redeployed Coordinator | 00093 to 00094 | prediction-coordinator |

---

## Root Causes Identified

### 1. Phase 2 Trigger Bug
**Problem**: Phase 2 processors publish class names (e.g., `PlayerBoxScoresProcessor`) but config expects `p2_`-prefixed names (e.g., `p2_player_box_scores`).

**Cause**: Previous regex-based normalization was fragile and failed to handle all cases.

**Fix**: Added explicit `CLASS_TO_CONFIG_MAP` dictionary for deterministic mapping.

**Prevention**: Use explicit mappings instead of regex for processor name normalization.

### 2. Feature Version Mismatch
**Problem**: Jan 26-27 predictions failing due to feature count mismatch.

**Cause**: Code evolved from v2_33 to v2_34 features (new field: `has_shot_zone_data`). Feature store had v2_33 data, but prediction worker expected v2_34.

**Impact**: Predictions cannot generate until feature stores are regenerated with v2_34 schema.

**Prevention**: Feature version changes need coordinated deployment of processor + worker.

### 3. game_id Duplicates
**Problem**: Duplicate team_offense records appearing in analytics tables.

**Cause**: Two source paths using different game_id formats:
- Path A: `AWAY_HOME` format (e.g., `BOS_NYK`)
- Path B: `HOME_AWAY` format (e.g., `NYK_BOS`)

**Prevention**: Standardize game_id format at processing time.

### 4. NULL usage_rate Values
**Problem**: Some players showing NULL usage_rate.

**Cause**: NOT related to game_id mismatch - actually caused by players with 0 minutes or 0 FGA (usage rate calculation divides by minutes/possessions).

**Status**: Expected behavior for inactive players.

### 5. Missing Boxscores
**Problem**: Phase 3 showing errors for certain games.

**Games Affected**:
- MIA@CHI (Jan 8, 2026) - postponed/cancelled
- LAC@UTA (Jan 27, 2026) - data not yet available

**Status**: Expected behavior - these are legitimate missing games.

---

## Feature Version Revert (v2_34 → v2_33)

**Issue**: Feature #34 (`has_shot_zone_data`) was added without training a challenger model. This broke predictions for Jan 26-27 because:
- Feature processor generated v2_34 features
- CatBoost V8 model expects v2_33 features
- Prediction worker rejected mismatched versions

**Resolution**: Reverted feature processor back to v2_33 features. The 34th feature will be added properly when a challenger model is trained.

**Documentation Added**: `docs/05-development/ML-FEATURE-VERSION-UPGRADE-GUIDE.md` - Comprehensive guide for future feature version changes.

---

## Known Issues Still to Address

### HIGH Priority

1. **game_id Format Standardization**
   - In progress but needs completion
   - Affects: team_offense, potentially other analytics tables
   - Goal: Single canonical format across all pipelines

2. **Clean Up Duplicate Team Stats**
   - 16+ duplicate records exist from format inconsistency
   ```sql
   -- Identify duplicates
   SELECT game_id, team_abbr, COUNT(*)
   FROM nba_analytics.team_offense_game_summary
   WHERE game_date >= '2026-01-24'
   GROUP BY 1, 2
   HAVING COUNT(*) > 1
   ```

### MEDIUM Priority

3. **Feature Version Coordination Process**
   - Document process for feature schema changes
   - Consider feature versioning in table (not just code)

4. **Missing Boxscores Monitoring**
   - Add alerting for expected games that don't receive data
   - Current missing: MIA@CHI (Jan 8), LAC@UTA (Jan 27)

5. **Prediction Parallelism vs Batch Insert Investigation** (Ongoing)
   - Need to investigate whether prediction generation parallelism conflicts with batch insert operations
   - May be causing intermittent issues with prediction counts
   - Consider: rate limiting, batch size tuning, or serialization

### LOW Priority

6. **Phase 2 Trigger Audit**
   - Verify all processors are in CLASS_TO_CONFIG_MAP
   - Add validation to fail loudly on unmapped processors

---

## Next Session Checklist

Priority order for next session:

- [x] **P0**: ~~Resolve feature version mismatch (v2_33 vs v2_34)~~ - DONE (reverted to v2_33)
- [x] **P0**: ~~Regenerate Jan 25-27 predictions~~ - DONE (Jan 25: 1,354, Jan 26: 723, Jan 27: 697)
- [ ] **P1**: Complete game_id format standardization
- [ ] **P1**: Clean up duplicate team stats records
- [ ] **P1**: Investigate prediction parallelism vs batch insert issues
- [ ] **P2**: Add feature version to feature store metadata
- [ ] **P2**: Audit Phase 2 processor mappings
- [ ] **P3**: Document feature schema change process
- [ ] **P3**: Review and update troubleshooting runbooks based on session learnings

---

## Key Learnings

### 1. Explicit Mappings Over Regex
**Before**: Regex-based normalization `PlayerBoxScoresProcessor` to `p2_player_box_scores`
**After**: Explicit dictionary `CLASS_TO_CONFIG_MAP`
**Why**: Regex is fragile, fails silently, hard to debug. Dictionaries are explicit and fail loudly.

### 2. Feature Version Coordination
**Learning**: Feature schema changes (adding/removing fields) require:
1. Update feature store generation code
2. Regenerate feature store data
3. Deploy prediction worker with new schema
4. All three must be coordinated - partial deployment causes failures

### 3. Raw Data Format Inconsistency
**Learning**: Different data sources have different conventions for the same concept (game_id).
**Solution**: Standardize at processing time, not at query time. Pick one canonical format and enforce it.

### 4. Parallel Agent Investigation
**Learning**: Using 6 parallel agents dramatically accelerated investigation.
**Pattern**: Spawn agents for each independent issue, then synthesize findings.

### 5. Feature Version Changes Require Challenger Model Training
**Learning**: Feature version changes (adding new features) require training a challenger model first.
**Why**: Production model expects a specific feature count. Adding features without retraining causes version mismatch rejections.
**Process**: See `docs/05-development/ML-FEATURE-VERSION-UPGRADE-GUIDE.md` for the proper workflow.

### 6. Never Modify Production Feature Set Without A/B Testing
**Learning**: The production feature set is tightly coupled to the trained model.
**Risk**: Modifying features without A/B testing can break predictions entirely (as happened with v2_34).
**Solution**: Always train challenger model, validate offline, then promote through proper model deployment process.

---

## Validation Commands

### Daily Validation
```bash
/validate-daily
```

### Check Predictions
```bash
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(*) as predictions, COUNT(DISTINCT player_lookup) as players
FROM \`nba-props-platform.nba_predictions.player_prop_predictions\`
WHERE game_date >= '2026-01-26' AND is_active = TRUE
GROUP BY game_date ORDER BY game_date"
```

### Check Feature Store Version
```bash
bq query --use_legacy_sql=false "
SELECT game_date, feature_version, COUNT(*)
FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\`
WHERE game_date >= '2026-01-25'
GROUP BY 1, 2 ORDER BY 1"
```

### Deployment Drift
```bash
./bin/check-deployment-drift.sh --verbose
```

---

## Files Modified This Session

### Code Changes
- `orchestration/cloud_functions/phase2_to_phase3/main.py` - Added CLASS_TO_CONFIG_MAP

### Deployments
- nba-phase3-analytics-processors (00130 to 00131)
- nba-phase4-precompute-processors (00061 to 00062)
- prediction-coordinator (00093 to 00094)

---

## Session Philosophy (Carry Forward)

1. **Understand root causes, not just symptoms** - Every error should trigger investigation into WHY
2. **Prevent recurrence** - Add validation, tests, automation
3. **Use agents liberally** - Spawn multiple agents for parallel work (this session: 6 parallel agents)
4. **Keep documentation updated** - Update handoff docs, runbooks
5. **Fix the system, not just the code** - Schema issues need validation, drift needs automation

---

## Contact & Escalation

For issues outside Claude's scope:
- Check `docs/02-operations/troubleshooting-matrix.md`
- Review recent handoff documents in `docs/09-handoff/`
- Check GitHub issues for known problems

---

*Session ended: 2026-01-28*
*Total services redeployed: 4 (Phase 3, Phase 4 x2, Coordinator)*
*Parallel agents used: 6*
*Root causes identified: 5*
*Predictions regenerated: 5,403 total (Jan 25-28)*
