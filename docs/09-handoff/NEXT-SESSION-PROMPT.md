# Session 141 Prompt - Finish Deployment + Commit + Verify Quality Gate

Copy and paste this to start the next session:

---

## Context

Sessions 139-140 implemented and deployed a **Quality Gate Overhaul**. The prediction system no longer forces garbage predictions at LAST_CALL. A hard floor blocks red alerts and low matchup quality, a self-healer re-triggers Phase 4 processors, and a BACKFILL mode allows next-day record-keeping. 50 new tests pass. The schema migration is done.

**Session 140 deployed** prediction-coordinator, prediction-worker, and nba-grading-service. It also updated 5 Claude skills with quality fields, fixed 3 bugs in `/validate-source-alignment`, and ran the first source alignment validation (found 17 real vegas default bugs out of 120 reported).

**What's left:**
1. **~30 files with uncommitted changes** from Sessions 139-140
2. **All 5 services deployed** (coordinator, worker, grading, phase3, phase4 - all confirmed)
3. **Monitor prediction_made_before_game** field (was NULL on Feb 6 - generated before deploy)
4. **Test BACKFILL mode** once a game day passes with the new quality gate
5. **Investigate 17 vegas default bugs** (game_total exists in source but feature store defaulted)

## Priority 1: Commit All Changes (CRITICAL)

~30 files across Sessions 139-140 are uncommitted. Run `git status` and commit:

```bash
git status

# Suggested: Two commits
# 1. Session 139 core (quality gate overhaul)
git add predictions/ schemas/ validation/ tests/ bin/monitoring/ docs/ CLAUDE.md ml/
git commit -m "feat: Quality gate hard floor, self-healer, BACKFILL mode, 50 tests (Session 139)"

# 2. Session 140 skills + source alignment
git add .claude/skills/
git commit -m "feat: Update skills with quality fields + fix source alignment bugs (Session 140)"
```

## Priority 3: Verify New Quality Fields Are Working

```sql
-- Check if prediction_made_before_game is now populated (should be TRUE for new predictions)
SELECT prediction_made_before_game, prediction_run_mode, COUNT(*)
FROM nba_predictions.player_prop_predictions
WHERE game_date >= '2026-02-07'
  AND system_id = 'catboost_v9'
  AND is_active = TRUE
GROUP BY 1, 2;
```

If still NULL, the next prediction run should populate it.

## Priority 4: Run /validate-source-alignment

Session 140 fixed 3 schema bugs in the skill. Re-run to verify clean results:
```
/validate-source-alignment quick
```

## Priority 5: Test BACKFILL Mode

```bash
curl -X POST https://prediction-coordinator-<hash>.us-west2.run.app/start \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{"game_date":"2026-02-07","prediction_run_mode":"BACKFILL","skip_completeness_check":true}'
```

Verify: `prediction_made_before_game = FALSE` for backfill predictions.

## Priority 6: Investigate 17 Vegas Default Bugs

17 players have `game_total` in `upcoming_player_game_context` but feature store defaulted features 25-28. Investigate the feature store builder to find the data flow bug.

## Key Findings from Session 140

- **Feature quality (Feb 6):** 175 green, 26 yellow, 0 red. Avg quality 89.7, matchup 100%
- **Quality gate working:** No red-alert predictions exist
- **Yellow alerts:** Players with quality 65-85, NOT blocked (correct - above hard floor)
- **Prop line coverage:** 73.8% (16 players with lines but no prediction - timing, not quality gate)
- **Phase 3/4 deploy issue:** Both lack `requirements-lock.txt`, causing pip timeout failures

## Key Files

```
docs/09-handoff/2026-02-06-SESSION-140-HANDOFF.md   # Full Session 140 details
docs/09-handoff/2026-02-06-SESSION-139-HANDOFF.md   # Session 139 details
predictions/coordinator/quality_gate.py              # Hard floor + BACKFILL
predictions/coordinator/quality_healer.py            # Self-healing (NEW)
predictions/coordinator/quality_alerts.py            # PREDICTIONS_SKIPPED alert
.claude/skills/validate-source-alignment/SKILL.md    # Fixed skill
```
