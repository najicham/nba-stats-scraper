# Session 268: Daily Steering Skill + Backfill

**Context:** Session 267 built the model-steering-playbook, two new GCS exporters (signal-health, model-health), and a comprehensive forward plan. What's missing is a **daily workflow that tells the user what they need to know and what decisions to make**, ideally as a Claude skill.

---

## Part 1: Build a `/daily-steering` Skill

The user wants a single command they can run each morning that tells them:

### What It Should Show

1. **Model health state** — Query `model_performance_daily` for the latest date. Show each model's state (HEALTHY/WATCH/DEGRADING/BLOCKED), rolling 7d HR, and days since training. Highlight the best bets model.

2. **Signal health summary** — Query `signal_health_daily` for the latest date. Count HOT/NORMAL/COLD signals. Flag any COLD model-dependent signals (these are effectively zeroed out).

3. **Best bets performance** — Query `prediction_accuracy` for the best bets subset (subset_id='best_bets') recent results. Show last 7 days W-L record if data exists.

4. **Decision recommendations** — Based on the data, recommend one of:
   - "All clear — model healthy, no action needed"
   - "WATCH — model dipping, monitor for 2-3 more days"
   - "SWITCH — champion degrading, challenger X is viable (Y% HR, N=Z)"
   - "BLOCKED — all picks auto-blocked, consider retrain"
   - "RETRAIN — model N+ days stale, retrain recommended"

5. **Upcoming risk factors** — Check if we're within 5 days of trade deadline or All-Star break (calendar awareness from `nba_reference.nba_schedule`).

### Implementation Notes

- The skill file goes in `.claude/skills/daily-steering/SKILL.md`
- It should use BigQuery queries (not GCS files) for freshest data
- Reference the playbook at `docs/02-operations/runbooks/model-steering-playbook.md` for the decision logic
- The skill should be read-only (research, no writes)
- Show the actual `gcloud run services update` command if a switch is recommended (but don't run it)
- Include the `/replay --compare` command if the user wants to validate a decision

### Existing Skills to Reference

- `/validate-daily` (`.claude/skills/validate-daily/SKILL.md`) — extensive pipeline health check, similar pattern
- `/reconcile-yesterday` — another diagnostic skill
- `/subset-performance` — subset W-L tracking

### Example Output

```
=== Daily Steering Report ===

MODEL HEALTH (as of 2026-02-19):
  catboost_v9:  BLOCKED  39.9% HR 7d (N=85, 42 days stale) ⛔
  catboost_v12: HEALTHY  56.0% HR 7d (N=50, 15 days stale) ✅
  Best Bets Model: catboost_v9

RECOMMENDATION: ⚠️ SWITCH to catboost_v12
  Champion is BLOCKED. Challenger catboost_v12 is HEALTHY with 56.0% HR.
  To switch:
    gcloud run services update prediction-worker --region=us-west2 \
      --update-env-vars="BEST_BETS_MODEL_ID=catboost_v12"
  To validate first:
    /replay --compare (last 30 days)

SIGNAL HEALTH:
  6 signals tracked: 2 HOT, 3 NORMAL, 1 COLD
  COLD: edge_spread_optimal (model-dependent, zeroed at 0.0x)
  HOT: minutes_surge (1.2x), cold_snap (1.2x)

BEST BETS TRACK RECORD (last 7 days):
  No data yet (Best Bets subset needs backfill — see Part 2)

RISK FACTORS:
  None detected. Next trade deadline: ~Dec 2026.
  Games resume Feb 19 after All-Star break.

NEXT STEPS:
  1. Switch BEST_BETS_MODEL_ID (see command above)
  2. Run /validate-daily for full pipeline check
  3. Monitor first game day results (Feb 19)
```

---

## Part 2: Backfill Best Bets + Signal Data

The best bets subset (id=26) was only created on ~Feb 14. We need historical data for:
- Website track record display
- Grading history for the "Best Bets Track Record" section of the steering skill
- Performance comparison vs other subsets

### Backfill Commands

```bash
# Backfill subset-picks (includes signal annotation + best bets bridge) for Jan 9 - Feb 14
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --backfill-range 2026-01-09 2026-02-14 --only subset-picks

# Backfill signal-best-bets JSON to GCS for website
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --backfill-range 2026-01-09 2026-02-14 --only signal-best-bets

# Backfill the two new exports (signal-health, model-health)
# These are "latest only" files, so just running once populates them:
PYTHONPATH=. python backfill_jobs/publishing/daily_export.py \
  --date 2026-02-14 --only signal-health,model-health
```

**Note:** Check if `--backfill-range` is a supported flag. If not, the script supports `--backfill-all` or individual `--date` runs. Read `daily_export.py` argument parser to confirm.

### Verification After Backfill

```sql
-- Check best_bets subset has historical data
SELECT game_date, COUNT(*) as picks
FROM nba_predictions.current_subset_picks
WHERE subset_id = 'best_bets'
GROUP BY 1 ORDER BY 1 DESC
LIMIT 10;

-- Check signal-best-bets GCS files exist
-- gsutil ls gs://nba-props-platform-api/v1/signal-best-bets/ | tail -10
```

---

## Part 3: Update START-NEXT-SESSION-HERE

After completing the skill and backfill, update `docs/09-handoff/START-NEXT-SESSION-HERE.md`:
- Add `/daily-steering` to Quick Start section
- Mark "Backfill best bets subset" as DONE
- Mark "Build signal health export" and "Build model health export" as DONE (Session 267)
- Add reference to the steering playbook

---

## Key Files to Read

| File | Purpose |
|------|---------|
| `docs/02-operations/runbooks/model-steering-playbook.md` | Decision logic for all 7 scenarios |
| `docs/08-projects/current/signal-discovery-framework/SESSION-267-FORWARD-PLAN.md` | Full system architecture review |
| `.claude/skills/validate-daily/SKILL.md` | Pattern to follow for skill design |
| `shared/config/model_selection.py` | BEST_BETS_MODEL_ID config |
| `ml/analysis/model_performance.py` | Model performance computation |
| `ml/signals/signal_health.py` | Signal health computation |
| `data_processors/publishing/signal_health_exporter.py` | New signal health export (Session 267) |
| `data_processors/publishing/model_health_exporter.py` | New model health export (Session 267) |
| `backfill_jobs/publishing/daily_export.py` | Phase 6 export orchestration |

---

## Success Criteria

1. `/daily-steering` skill exists and produces clear, actionable output
2. Best bets subset backfilled Jan 9 - Feb 14 with picks in `current_subset_picks`
3. Signal-best-bets JSON files backfilled to GCS
4. Signal-health and model-health exports produce valid JSON
5. START-NEXT-SESSION-HERE updated
6. All changes committed and pushed
