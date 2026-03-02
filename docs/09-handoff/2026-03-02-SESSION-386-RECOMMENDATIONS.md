# Session 386 Recommendations — March 2, 2026

For the next session to review. Prioritized by impact.

---

## Priority 1: Deployment Drift

**`nba-grading-service` is stale.** Deployed commit `bedc7b45`, current is `d553578e`. Missing the per-model performance profiling system (Session 384, commit `d90d09b1`).

**Action:**
```bash
./bin/deploy-service.sh nba-grading-service
```

Also: Session 386's two commits (`5eccddbe` feat + `d553578e` docs) auto-deployed publishing services but the grading service predates these and was already stale. Verify after deploy:
```bash
./bin/check-deployment-drift.sh --verbose
```

---

## Priority 2: Model Fleet Triage — Fresh Models Underperforming

**Current fleet health (7-day, edge 3+):**

| Model | HR% | N | Notes |
|-------|-----|---|-------|
| `v12_noveg_60d_vw025_train1222_0219` | 75.0% | 8 | Best HR, tiny sample |
| `v16_noveg_rec14_train1201_0215` | 64.3% | 14 | Strong, 15 days stale |
| `v12_noveg_train0110_0220` | 63.6% | 11 | Current best bets source |
| `v16_noveg_train1201_0215` | 63.6% | 11 | Matches v12_noveg |
| `ensemble_v1` | 62.5% | 16 | Ensemble performing well |
| `lgbm_v12_noveg_train1102_0209` | 57.1% | 21 | LightGBM — 21 days stale, disable candidate |
| `v12_noveg_q43_train1102_0125` | 40.7% | 27 | **Catastrophic** — disable candidate |
| `v12_noveg_q45_train1102_0125` | 40.9% | 22 | **Catastrophic** — disable candidate |
| `v8` (production champion) | 48.9% | 92 | Below breakeven |
| `v12` | 51.7% | 60 | Below breakeven |

**Freshest models** (trained through Feb 27, 3 days stale):
- `catboost_v12_noveg_train0103_0227` — no HR data yet (too new)
- `lgbm_v12_noveg_train0103_0227` — no HR data yet (too new)

**Recommendations:**
1. **Disable the two Q43/Q45 models** from Nov training (`v12_noveg_q43_train1102_0125` and `v12_noveg_q45_train1102_0125`). Both at ~40% HR on 20+ graded picks. Use:
   ```bash
   python bin/deactivate_model.py catboost_v12_noveg_q43_train1102_0125 --dry-run
   python bin/deactivate_model.py catboost_v12_noveg_q45_train1102_0125 --dry-run
   ```
2. **Evaluate the 21-day-stale LightGBM** (`lgbm_v12_noveg_train1102_0209`). At 57.1% HR it's above breakeven but the Nov training window is ancient. The fresh `lgbm_v12_noveg_train0103_0227` (3 days stale) should replace it once it has graded data.
3. **Monitor the Feb 27 models** — they're the freshest but have zero graded picks yet. Check back after 2-3 game days.

---

## Priority 3: Best Bets Performance — Low Volume, Mixed Results

**Last 7 days:**

| Date | Picks | W-L | HR |
|------|-------|-----|-----|
| Mar 1 | 2 | 2-0 | 100% |
| Feb 28 | 6 | 3-3 | 50% |
| Feb 27 | 1 | 0-1 | 0% |
| Feb 26 | 5 | 2-2 (+1 pending) | 50% |
| Feb 24 | 2 | 1-1 | 50% |

**7-day total: 8W-7L (53.3%).** Below breakeven. Volume is very low (1-6 picks/day).

**Possible causes:**
- All-Star break and schedule gaps reduced game volume
- The poisoned XGBoost incident (Session 378c → 383B → 386) may have leaked bad picks into Feb 28 results before cleanup
- V8 production champion at 48.9% is dragging — but filter stack should handle this

**Recommendations:**
1. **Don't panic** — 15 total graded picks in 7 days is too small for conclusions. Variance is massive at this sample.
2. **Check if any Feb 28 picks came from XGBoost** — cross-reference signal_best_bets_picks for Feb 28 against XGBoost model. If any leaked through before the Session 383B deactivation, those losses aren't representative.
3. **Wait for volume** — March schedule picks up. The system needs 30+ graded picks for meaningful HR assessment.

---

## Priority 4: Retrain Cadence

**Training staleness across enabled models:**
- 2 models at 3 days stale (Feb 27 training end) — good
- 3 models at 8 days stale (Feb 22) — acceptable
- 1 model at 10 days (Feb 20) — approaching threshold
- 4 models at 15-16 days — overdue for retrain or disable
- 1 model at 21 days — should be replaced by fresh equivalent

The 7-day cadence target means anything >10 days is technically overdue. The Feb 27 models are the freshest and should naturally take over selection as they accumulate data.

**Recommendation:** No urgent retrain needed since we have 2 models at 3 days stale. But the 15-16 day models (`v16_noveg_train1201_0215`, `v12_train0104_0215`, etc.) should be watched. If the Feb 27 models prove viable, consider disabling the >15d models to simplify the fleet.

---

## Priority 5: Session 386 Verification Items

The Session 386 prevention system is deployed but hasn't been exercised in production yet (no game day has run with the new code through the full pipeline).

**Verify on the next game day:**

1. **system_id populated in published picks:**
   ```sql
   SELECT game_date, COUNTIF(system_id IS NOT NULL) as has_id, COUNT(*) as total
   FROM nba_predictions.best_bets_published_picks
   WHERE game_date >= CURRENT_DATE()
   GROUP BY 1
   ```
   Expected: 100% of picks have system_id.

2. **Pick events logged for any drops:**
   ```sql
   SELECT * FROM nba_predictions.best_bets_pick_events
   WHERE game_date >= CURRENT_DATE()
   ORDER BY created_at DESC
   ```
   Expected: Events logged for any pick that was in signal but later dropped (common during hourly re-exports as games start).

3. **Disabled model filter working:**
   Check Cloud Run logs for `signal_best_bets_exporter` — look for "Filtered N picks from disabled models" log line. Should appear if any disabled model's predictions are still in `player_prop_predictions` (possible for models disabled without running `deactivate_model.py`).

4. **Published-only grading working:**
   If any picks get dropped from signal mid-day (e.g., game starts, re-export runs), they should still show `actual` and `result` in the JSON once games finish and grading runs.

---

## Priority 6: Pipeline Health Gaps

**No Phase 5 completions recorded in last 3 days.** This might be:
- Normal (no games on some days around All-Star break)
- Or the `phase_completions` table isn't being written to

**Action:** Check if there were NBA games on Feb 28 / Mar 1:
```sql
SELECT game_date, COUNT(*) as games, COUNTIF(game_status = 3) as final
FROM nba_reference.nba_schedule
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1 ORDER BY 1
```

If there were games but no Phase 5 completions, investigate the orchestrator chain.

---

## Quick Summary for Next Session

| Item | Action | Urgency |
|------|--------|---------|
| Deploy grading service | `./bin/deploy-service.sh nba-grading-service` | Do first |
| Disable 2 catastrophic Q43/Q45 models | `bin/deactivate_model.py` (dry-run first) | High |
| Verify Session 386 prevention system | Check on next game day | Medium |
| Monitor Feb 27 fresh models | Wait for 10+ graded picks | Low |
| Check Phase 5 completions gap | Investigate if games happened | Low |
| LightGBM 21d stale model | Disable once fresh LGBM has data | Low |
