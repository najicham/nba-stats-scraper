# Session 200 Opus Review — Plan Reviews & Frontend Data Quality Investigation

**Date:** February 11, 2026
**Session:** 200 (Opus review chat)
**Status:** Active — 3 Sonnet chats spawned for implementation

---

## What This Session Did

### 1. Reviewed 3 Plans From Other Chats

**Orchestrator Resilience Plan (3 rounds of review):**
- Round 1: Identified factual errors (5 processors not 6, orchestrator is monitoring-only, SIGALRM won't work in Cloud Functions, dual-write already exists). Recommended simplifying from 3 layers to 2.
- Round 2: Approved revised 2-layer plan but flagged contradiction -- if orchestrator is monitoring-only, why did `_triggered=False` cause 3-day gap? Recommended investigating actual Phase 3 trigger mechanism.
- Round 3: Approved final plan after other chat confirmed Phase 3 is triggered by direct Pub/Sub subscription. Canary correctly changed to monitor Phase 3 output tables instead of orchestrator flag. Noted existing Phase 3 canary already checks `player_game_summary` -- should investigate why it didn't catch the gap before adding a duplicate.

**Game ID Mismatch Investigation:**
- Rejected as root cause. The game_id format mismatch (NBA official vs date-based) is a known, handled architectural pattern with 3 layers of defense (CTE normalization, game_id_reversed, GameIdConverter utility). NOT a systemic bug.
- The 7-11 hour migration plan was unnecessary.

**Phase 3 Missing Players Investigation:**
- Identified actual root cause: the **multi-window completeness check** in `upcoming_player_game_context_processor.py:1083-1117` filters players where any of 5 completeness windows has `is_production_ready=False`. 12/17 ORL players fail this check. Not a bug in the SQL or write layer.

### 2. Investigated Frontend Data Quality Issues

Received 5 issues from frontend team. Investigated all in parallel and found root causes:

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| **No Feb 11 predictions in API** | `phase6-export` Cloud Function broken -- missing `google-cloud-firestore` dependency after auto-deploy at 06:03 UTC | Add to requirements.txt, redeploy |
| **last_10_results all dashes** | `over_under_result` NULL for all 2,710 Feb records -- game_id format mismatch in `player_game_summary` prop line JOIN | Fix JOIN to use `game_date` instead of `game_id` |
| **home_score/away_score null** | Tonight exporter simply doesn't query scores | Add scores JOIN to `_query_games()` |
| **Player profiles 62 days stale** | Same firestore dependency break blocks profile generation | Will work after dependency fix + manual trigger |
| **Feb 10: 25% hit rate** | Real: 2/8 correct (9 ungraded). Model in documented decay. Not a data bug | Monitor quantile shadow models |

**Secondary finding:** 2 of 3 Phase 6 scheduler jobs send malformed Pub/Sub messages (`export_type` singular vs `export_types` plural), causing silent fallthrough to exporting yesterday's data instead of today's picks. Only the 1 PM ET scheduler works correctly.

### 3. Spawned 3 Sonnet Implementation Chats

| Chat | Task | Priority | Status |
|------|------|----------|--------|
| **Chat A** | Fix Phase 6 dependency + scheduler messages + player profiles | P0 | Spawned |
| **Chat B** | Fix player_game_summary prop line JOIN (over_under_result) | P1 | Spawned |
| **Chat C** | Add game scores to tonight exporter | P2 | Spawned |

---

## Key Discoveries

### Phase 6 Export Broken -- Full Timeline

```
Feb 10 21:36 -- Commit f68dbc56: Fix game_id mismatch in tonight exporter
Feb 10 22:03 -- Commit 8803f556: Fix duplicate exc_info in phase6_export
Feb 11 06:03 -- Cloud Build deploy-phase6-export fires, deploys with latest shared/
Feb 11 06:03 -- shared/ code now transitively imports google.cloud.firestore
Feb 11 06:03 -- google-cloud-firestore NOT in requirements.txt
Feb 11 13:02 -- First export attempt: ALL types fail with firestore import error
Feb 11 16:02 -- Morning scheduler trigger: same failure
Feb 11 17:02 -- Two more failures
Result: No tonight/picks JSON files generated for Feb 11
```

### Scheduler Message Format Mismatch

| Scheduler | Fires | Message | Works? |
|-----------|-------|---------|--------|
| `phase6-tonight-picks-morning` | 11 AM ET | `{"export_type": "tonight-picks", "date": "TODAY"}` | NO -- wrong keys |
| `phase6-tonight-picks` | 1 PM ET | `{"export_types": ["tonight", "tonight-players"], "target_date": "today"}` | YES |
| `phase6-tonight-picks-pregame` | 5 PM ET | `{"export_type": "tonight-picks", "date": "TODAY"}` | NO -- wrong keys |

Function checks `message_data.get('export_types')` (plural) at line 353. Singular `export_type` falls through to else clause at line 439, silently exporting yesterday's results.

### over_under_result NULL -- Prop Line Join Failure

`player_game_summary_processor.py` ~line 1097 JOINs on `c.game_id = p.game_id` where:
- `c` (player stats) has date-based: `20260210_IND_NYK`
- `p` (odds props) has NBA official: `0022500774`

LEFT JOIN produces NULL for all prop fields -> `PropCalculator` returns None -> `over_under_result` always NULL -> frontend shows dashes.

---

## Files Changed This Session

None -- this was a review/investigation session. All implementation delegated to Sonnet chats.

---

## What Needs Monitoring

### After Chat A Deploys
- [ ] Verify `picks/2026-02-11.json` appears in GCS
- [ ] Verify `tonight/all-players.json` shows Feb 11 data
- [ ] Verify no firestore import errors in `phase6-export` function logs
- [ ] Verify player profiles regenerate after manual trigger
- [ ] Check that morning/pregame schedulers now produce correct exports

### After Chat B Deploys
- [ ] Verify `over_under_result` is non-NULL for players with prop lines
- [ ] Verify `last_10_results` shows O/U in API after backfill
- [ ] Check no regressions in other player_game_summary fields

### After Chat C Deploys
- [ ] Verify `home_score`/`away_score` populated for final games
- [ ] Verify scores are null for scheduled games

---

## Open Items NOT Addressed This Session

1. **Orchestrator resilience implementation** -- Plan approved (02-FINAL-CORRECTED-PLAN.md), not yet implemented. 85 min effort.
2. **Phase 3 completeness check filtering** -- 12/17 ORL players filtered by multi-window completeness. May be too aggressive for daily mode. Needs separate investigation. (Note: Session 200 other chat found root cause was BDL table reference in completeness_checker_helper.py -- see SESSION-200-HANDOFF.md)
3. **7 chronically missing players** (nicolasclaxton, carltoncarrington, etc.) -- Likely related to completeness filtering. Not investigated.
4. **franzwagner/kylekuzma mystery** -- Had perfect quality but no predictions. Not resolved.
5. **Confidence scale normalization** (0-100 vs 0-1) -- Minor, not pursued. Would be a breaking change for existing frontend code.
6. **GCS 409 conflict errors** -- Feb 10 had repeated 409 PATCH errors on individual player files. Non-blocking (exports complete with errors) but should be fixed with retry logic.

---

## Quick Start for Next Session

```bash
# 1. Check if Chat A fixed Phase 6
gsutil ls gs://nba-props-platform-api/v1/picks/2026-02-11.json
gcloud logging read 'resource.labels.function_name="phase6-export" AND severity>=ERROR' \
  --project=nba-props-platform --limit=5 --freshness=2h

# 2. Check if Chat B fixed over_under_result
bq query --use_legacy_sql=false "
SELECT over_under_result, COUNT(*)
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-02-10'
GROUP BY 1"

# 3. Check prediction volume
bq query --use_legacy_sql=false "
SELECT system_id, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY 1 ORDER BY 1"

# 4. Run daily validation
/validate-daily
```
