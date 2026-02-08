# Session Prompts — Post Session 164

## Prompt 1: Continue Session 164 (same chat, /clear)

**When:** If you clear context in the current chat
**Agent:** Opus

```
Continuing Session 164 after context clear.

Read the handoff: docs/09-handoff/2026-02-08-SESSION-164-HANDOFF.md

Session 164 accomplished:
- Fixed coordinator /reset bug (current_tracker = None)
- Fixed 42+ unprotected next() calls (committed: f4fcb6a3)
- Deployed 2 stale services (grading, scrapers) — both confirmed
- Fixed BQ model_registry wrong training_end_date (Jan 31 → Jan 8)
- Hardened model governance docs (SKILL.md, CLAUDE.md)
- Confirmed zero training date overlap in predictions/subsets
- All commits pushed to main, all Cloud Build deploys succeeded

Still unresolved:
1. Backfill Pub/Sub stalling — workers don't pick up messages after /start. Batch stays at 0/N. Push subscription config looks correct, no error logs. Needs deeper investigation.
2. Subset backfill for Feb 1-8 not yet run (depends on predictions being complete)
3. Dynamic model_version not yet verified (no new predictions since deploy)

Pick up where we left off. Priority is fixing the backfill stalling issue.
```

---

## Prompt 2: Model Governance Sync (NEW session)

**When:** Anytime (independent, no blockers)
**Agent:** Sonnet

```
Session: Model Governance Sync

Read the handoff: docs/09-handoff/2026-02-08-SESSION-164-HANDOFF.md
Read the project docs: docs/08-projects/current/model-governance/00-PROJECT-OVERVIEW.md
Read the current model registry script: bin/model-registry.sh
Read the GCS manifest: gsutil cat gs://nba-props-platform-models/catboost/v9/manifest.json

## Problem

We have 4 places that describe model metadata and they drift apart:
1. GCS manifest.json (source of truth — has correct training dates)
2. BQ model_registry table (had WRONG training_end_date, fixed in Session 164)
3. CLAUDE.md (manually maintained, can go stale)
4. Model filenames (use creation timestamp, not training dates)

Session 163 discovered a retrained model crashed hit rate from 71.2% to 51.2%. Future sessions could accidentally retrain the same model or deploy without proper checks.

## Tasks (implement all of these)

1. **Registry sync command**: Add `./bin/model-registry.sh sync` that reads the GCS manifest.json and upserts into BQ model_registry. This ensures BQ always matches GCS.

2. **Pre-training duplicate check**: In `ml/experiments/quick_retrain.py`, before training begins, query BQ model_registry to check if a model with the same training_start_date + training_end_date already exists. If it does, warn and require --force flag to proceed.

3. **Model naming convention**: Update `ml/experiments/quick_retrain.py` to save models with filename format: `catboost_v9_33f_train{start}-{end}_{timestamp}.cbm` (e.g., `catboost_v9_33f_train20251102-20260108_20260201T011018.cbm`). This makes training range visible in the filename.

4. **Registry validation in deploy**: Add to `bin/check-deployment-drift.sh` a check that compares the CATBOOST_V9_MODEL_PATH env var against the GCS manifest production_model field. Alert if they don't match.

5. **Auto-generate CLAUDE.md model section**: Add `./bin/model-registry.sh claude-md` that outputs a formatted snippet for CLAUDE.md's MODEL section, pulling from the BQ registry. Include: model file, training dates, hit rate, status, SHA256.

## Report back with:
- What was implemented
- Any issues encountered
- Updated model registry output (`./bin/model-registry.sh list`)
- The auto-generated CLAUDE.md snippet
- Whether any existing tests needed updating
```

---

## Prompt 3: Backfill Pub/Sub Investigation (NEW session)

**When:** After checking if the Feb 9 morning run worked (if it did, issue is manual-backfill-specific)
**Agent:** Opus

```
Session: Fix Backfill Pub/Sub Stalling

Read the handoff: docs/09-handoff/2026-02-08-SESSION-164-HANDOFF.md

## Problem

Manual prediction backfills via the coordinator /start endpoint create batches, but workers NEVER process them. The batch stays at 0/N completed for minutes then stalls.

Key facts:
- Coordinator publishes to `prediction-request-prod` Pub/Sub topic
- Push subscription pushes to `https://prediction-worker-f7p3g7f6ya-wl.a.run.app/predict`
- Worker passes /health and /health/deep checks
- No error logs in coordinator or worker during stall
- Earlier in Session 164, backfills DID work (Feb 1 got 143/181 predictions)
- The stalling began after Cloud Build redeployed all services mid-session

## Investigation steps

1. First check if the morning Feb 9 prediction run worked (it uses the same pipeline but is triggered by the scheduler, not manual /start). If it worked, the issue is specific to manual backfills after deploy.
   ```sql
   SELECT game_date, model_version, COUNT(*) as n, COUNTIF(is_active) as active
   FROM nba_predictions.player_prop_predictions
   WHERE system_id = 'catboost_v9' AND game_date >= '2026-02-08'
   GROUP BY 1, 2 ORDER BY 1
   ```

2. Check Pub/Sub delivery metrics:
   - gcloud monitoring (Pub/Sub subscription num_undelivered_messages)
   - Check dead letter queue: prediction-request-dlq topic

3. Check if coordinator actually publishes messages after batch creation:
   - Read predictions/coordinator/coordinator.py, trace /start → publish_prediction_requests()
   - Check if the batch state is being set before publish happens

4. Test worker /predict endpoint directly with a crafted Pub/Sub-style POST

5. Check Cloud Run min-instances setting — if 0, Pub/Sub push may 503 on cold start and back off

6. If push delivery is broken, consider: min-instances=1, or pull-based subscription

## Also while investigating:
- Run subset backfill for Feb 1-8 using SubsetMaterializer
- Verify Feb 9 predictions show dynamic model_version (v9_20260201_011018 not v9_current_season)

## Report back with:
- Root cause of the stalling
- Fix implemented (or proposed if needs approval)
- Whether the morning scheduler run works vs manual /start
- Feb 1-9 prediction and subset status
```

---

## Prompt 4: Morning Check (NEW quick session)

**When:** Feb 9 morning (after ~8 AM ET), before starting other sessions
**Agent:** Sonnet (quick check)

```
Quick morning check for Feb 9.

1. Did today's prediction run complete?
   ```sql
   SELECT game_date, model_version, COUNT(*) as n, COUNTIF(is_active) as active
   FROM nba_predictions.player_prop_predictions
   WHERE system_id = 'catboost_v9' AND game_date = '2026-02-09'
   GROUP BY 1, 2
   ```

2. Does model_version show the new dynamic format (v9_20260201_011018)?
   If it still shows v9_current_season, the deploy didn't take effect.

3. Run /validate-daily

4. Check subset picks exist for today:
   ```sql
   SELECT subset_name, COUNT(*) as n
   FROM nba_predictions.current_subset_picks
   WHERE game_date = '2026-02-09'
   GROUP BY 1
   ```

Report: prediction count, model_version, validation status, subset status.
```

---

## Recommended order:
1. **Morning Check** (Sonnet, 5 min) — determines if backfill investigation is urgent
2. **Model Governance Sync** (Sonnet, ~30 min) — independent, no blockers
3. **Backfill Investigation** (Opus, ~30 min) — only if morning run also failed
