Read docs/09-handoff/2026-02-10-SESSION-185-HANDOFF.md for full context. Session 185 deployed 3 bug fixes, cleaned up postponed games, and assessed model promotion.

**P0 (Immediate):**

1. **Verify Phase 2→3 trigger fired overnight.** Session 184 fixed name mapping typos — deployed in Session 185. Check if `_triggered: True` for last night's games:
   ```bash
   python3 -c "
   from google.cloud import firestore; import datetime
   db = firestore.Client(project='nba-props-platform')
   yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
   doc = db.collection('phase2_completion').document(yesterday).get()
   print(f'Phase 2 {yesterday}: _triggered={doc.to_dict().get(\"_triggered\", False)}' if doc.exists else 'No record')
   "
   ```

2. **Check grading is caught up.** Session 185 deployed grading service (was 4 commits behind) and triggered backfill for Feb 8-9:
   ```bash
   bq query --use_legacy_sql=false "
   SELECT game_date, COUNT(*) as n FROM nba_predictions.prediction_accuracy
   WHERE game_date >= '2026-02-08' AND system_id = 'catboost_v9' GROUP BY 1 ORDER BY 1 DESC"
   ```

3. **Run /validate-daily** for pipeline health.

**P1 (Model Promotion — target ~Feb 17-20):**

Champion is at 43.7% weekly HR and decaying fast (was 59.1% three weeks prior). Jan 31 challengers have 53-54% HR All but only ~3 edge 3+ picks/week (retrain paradox). Jan 8 clean has 70.8% edge 3+ HR but only ~12/week.

**NOT READY yet.** Wait for Jan 31 models to age and naturally diverge from Vegas. Reassess:
```bash
PYTHONPATH=. python bin/compare-model-performance.py catboost_v9_train1102_0131_tuned --days 14
```

Look for: Jan 31 tuned generating 10+ edge 3+ picks/week with HR >= 55%.

**P2 (Extended Experiments — when 2+ weeks eval data available):**

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C1_CHAOS_EXT2" \
  --rsm 0.3 --random-strength 10 --subsample 0.5 --bootstrap Bernoulli \
  --train-start 2025-11-02 --train-end 2026-01-31 \
  --eval-start 2026-02-01 --eval-end 2026-02-15 --walkforward --force
```

**P3 (Other Follow-ups):**
- Fix breakout classifier feature mismatch (shadow mode, not blocking)
- Optional: Delay overnight Phase 3/4 schedulers from 6→8 AM ET (reduces log noise)

**Key context from Sessions 179-185:**
- 63+ experiments, none beat controlled staleness for betting performance
- Retrain paradox: fresher models = fewer edge picks = less profit
- Champion at 43.7% this week — below breakeven after vig
- Postponed games cleaned up (Jan 8, 24, 25) — 420 predictions deactivated, schedule updated to game_status=9
- Phase 2→3 trigger was completely broken due to name typo — now fixed and deployed
- Grading service was 4 commits behind — now deployed with Session 170/175 fixes

Use agents in parallel where possible.
