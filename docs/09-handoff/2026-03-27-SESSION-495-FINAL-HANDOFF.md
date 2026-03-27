# Session 495 Final Handoff — 2026-03-27

**Date:** 2026-03-27 (~11:30 AM ET)
**Session arc:** Sessions 494-495 across 2 days
**All commits pushed:** `1b5cbf8a` → `9d3e081c` → `2da15d31` → `a176e89a` → `cabd04d1` → `b291e91b`

---

## State of the World Right Now

### NBA — 0 Picks on a 10-Game Friday Slate

Phase 6 ran and found 0 qualifying picks. The pipeline is working correctly; the filter stack is too aggressive.

**Filter breakdown (68 candidates, all blocked):**

| Filter | Blocked | Notes |
|--------|---------|-------|
| `med_usage_under` | 18 | UNDER — blocks moderate-usage players |
| `friday_over_block` | 14 | OVER — Friday OVER 37.5% HR historically |
| `over_edge_floor` | 14 | OVER — below edge 5.0 floor |
| `signal_density` (real_sc=0) | 9 | mixed — no real signals at all |
| `under_low_rsc` (real_sc=1) | 4 | UNDER — has home_under but needs 2nd signal |
| other | 9 | — |

**Root cause chain:**
1. `home_over_obs` was promoted to **active block** in Session 494 (blocks ALL home OVER picks, N=4,278, 49.7% CF HR). Today is Friday + home OVER blocked = essentially zero OVER.
2. `under_low_rsc≥2` requires two real signals. `home_under` restoration (Session 495) gives real_sc=1, but needs a second signal.
3. 69% of candidates had real_sc=0 — signal system not generating real signals for most picks.

**Phase 6 re-runs at 1 PM ET and 5 PM ET.** Picks may appear as lines fill in (only 75% loaded at 10 AM ET).

**Key decision needed:** Should `home_over_obs` be reverted from active → observation? It blocks all home OVER picks. The 49.7% CF HR was measured on raw predictions, not BB-level picks.

---

### MLB — Infrastructure Fixed, Predictions Blocked (Phase 3/4 Not Run)

**What was fixed today:**
- Expired Odds API key on `mlb-phase1-scrapers` updated
- `mlb-events-morning` + `mlb-events-pregame` schedulers created in GCP
- `mlb_pitcher_props` scheduler body fixed (`date` → `game_date`)
- All 11 MLB scheduler URIs updated to correct `756957797294` URL
- Auto-event-discovery deployed to `mlb-phase1-scrapers` Docker image
- 486 Odds API prop rows in `mlb_raw.oddsa_pitcher_props` for today

**Why 0 predictions:** Phase 3 (analytics) and Phase 4 (precompute/feature store) haven't run for 2026 season. Prediction worker returns "No pitchers found" — needs historical feature data that Phase 3/4 compute. **MLB predictions will not work until Phase 3/4 are bootstrapped.**

**No MLB Phase 2 automation:** GCS → BQ doesn't happen automatically (no Pub/Sub subscription). Manual Phase 2 run handled today's data. Need to create `mlb-phase2-raw-sub` or equivalent.

---

## Everything Done in Sessions 494-495

### Signal Drought Fix (commit `1b5cbf8a`)
- `home_under` restored from BASE_SIGNALS → UNDER_SIGNAL_WEIGHTS (weight 1.0, NOT rescue)
  - Was primary `real_sc=1` source for ~50% of UNDER picks (home + line≥15)
  - HOT at 66.7% 7d HR ✅
- `usage_surge_over` graduated from SHADOW (68.8% HR, N=32)
- 9 signals added to `signal_health.py:ACTIVE_SIGNALS` (monitoring gap — hot_3pt_under etc.)
- `combo_3way`/`combo_he_ms` removed from UNDER rescue_tags (dead code — OVER-only signals)
- Algorithm version bumped to `v495_restore_home_under`

### New Models Enabled (manual registration last night)
Both enabled, generating predictions:
- `lgbm_v12_noveg_train0121_0318`: 59.05% HR (N=105), trained Jan 21→Mar 18
- `catboost_v12_noveg_train0121_0318`: 58.82% HR (N=51), trained Jan 21→Mar 18
- GCS: `gs://nba-props-platform-models/catboost/v12/monthly/lgbm_v12_50f_noveg_train20260121-20260318_20260326_172558.txt`
- GCS: `gs://nba-props-platform-models/catboost/v12/monthly/catboost_v12_50f_noveg_train20260121-20260318_20260326_172646.cbm`
- Not yet in `model_performance_daily` — will appear after today's grading

### Infrastructure Fixes (commit `a176e89a`)
- **Streaming buffer resilience** (`batch_staging_writer.py`): `_check_for_active_duplicates()` prevents false-positive consolidation failures when streaming buffer causes transient duplicates
- **Filtered picks partition bug** (`signal_best_bets_exporter.py`): Removed invalid `$YYYYMMDD` partition decorator from non-partitioned `best_bets_filtered_picks` table
- **MLB auto-event-discovery** (`scrapers/routes/scraper.py`): `mlb_pitcher_props` auto-discovers events when called without `event_id`
- **MLB schedulers** (`setup_mlb_schedulers.sh`): Added events schedulers, fixed URIs

### MLB Schedulers (commit `a176e89a`)
6 monitoring/validation schedulers updated to `3-10` (March-October) in YAML + deployed to GCP.

### Other Session 494-495 Changes
- retrain.sh: eval date bug fixed, display bug fixed
- SIGNAL-INVENTORY.md: 5 stale PRODUCTION entries corrected (28→25 active)
- CLAUDE.md: retrain LOOSE gate marked FIXED (Session 486)
- shared/ sync clean (0 differences, 225 files)
- 10 observation filters promoted/removed (Session 494)
- DELETE failure gate added to signal_best_bets_exporter.py (Session 494)
- Row-level fallback in best_bets_all_exporter.py (Session 494)
- 2 new canaries: GCS duplicate picks + fleet diversity (Session 494)

---

## Current Fleet State

| Model | State | HR 7d | Notes |
|-------|-------|-------|-------|
| `lgbm_v12_noveg_train0103_0227` | WATCH | 55.4% | Primary workhorse |
| `lgbm_v12_noveg_train0121_0318` | No data yet | — | NEW. 158 predictions/day. |
| `catboost_v12_noveg_train0121_0318` | No data yet | — | NEW. 158 predictions/day. |
| `catboost_v12_noveg_train0118_0315` | BLOCKED | 50.0% | Pending auto-disable |
| `lgbm_v12_noveg_train0103_0228` | BLOCKED | 50.0% | Pending auto-disable |
| `lgbm_v12_noveg_train1215_0214` | BLOCKED | 41.0% | Pending auto-disable |

Decay-detection CF fires daily at 11 AM ET. Safety floor: 3 models must remain enabled. BLOCKED models will be disabled once new models accumulate grading data.

---

## Key Technical Facts for Next Chat

### real_sc Signal Drought — Why It Persists
- `home_under` (restored) = real_sc+1 for home UNDER picks
- Still need real_sc≥2 to pass `under_low_rsc` gate
- Available second signals: `volatile_starter_under` (line 18-25, high variance), `hot_3pt_under` (3PT hot streak), `line_drifted_down_under` (BP line movement), `bench_under` (bench players), `extended_rest_under` (4+ rest days)
- Most picks don't hit these niche conditions → real_sc stays at 1 → blocked

### home_over_obs Active Block — The Debate
- **For keeping it:** 49.7% CF HR at N=4,278 is massive evidence. Every home OVER pick loses money.
- **Against:** That N is raw predictions, not BB-level. The BB pipeline normally filters to 60%+ picks. Applying a 49.7% raw-prediction filter to BB-qualified picks might be too broad.
- **Evidence today:** 0 picks on a 10-game slate. If home_over was removed AND other filters relaxed, there might still be 0 OVER picks because OVER needs signals too.

### Corrections to Common Misunderstandings
- `combo_3way`/`book_disagreement` do NOT need cross-model diversity (confirmed by reading signal code)
- BLOCKED models contribute ZERO candidates (excluded at BQ query level: `status IN ('blocked','disabled')`)
- Weekly-retrain LOOSE gate is FIXED (Session 486 — `cap_to_last_loose_market_date()`)
- `flat_trend_under_obs` removal had zero pick impact (was observation-only)
- The 10-day pick drought (March 14-25) was caused by `home_under` demotion, not fleet issues

### Monday March 30 — Weekly Retrain CF
- Fires at 5 AM ET
- 60% governance gate — probability ~35-45% of passing (model HR ~59%)
- If fails: same manual enable process (models on disk, commands in Session 494 handoff)
- `training_end_date = 2026-03-18` for new models (12 days before March 30) — CF won't skip them

---

## Immediate Action Items for New Chat

### 1. Check 1 PM ET picks (HIGH PRIORITY)
```sql
SELECT recommendation, COUNT(*) as picks, ROUND(AVG(edge),2) as avg_edge
FROM nba_predictions.signal_best_bets_picks
WHERE game_date = '2026-03-27'
GROUP BY 1
```
If still 0 after 1 PM ET, consider:
- Reverting `home_over_obs` to observation
- Or accepting 0 picks today and investigating tomorrow

### 2. home_over_obs decision
Check whether to revert:
```bash
grep -n "home_over_obs" ml/signals/aggregator.py | head -5
```
If reverting: change `continue` → `pass` on the `home_over_obs` block (make it observation-only).

### 3. MLB Phase 3/4 bootstrap (MEDIUM PRIORITY)
For MLB to work, need to trigger Phase 3 analytics:
```bash
# Check if mlb-phase3-analytics-processors service exists and what triggers it
gcloud run services list --project=nba-props-platform | grep mlb
```
For now, MLB is a future-day problem (data accumulates over the season).

### 4. MLB Phase 2 automation
Create Pub/Sub subscription to automate GCS→BQ for MLB:
```bash
# Check if mlb-phase2-raw-processors service exists
gcloud run services describe mlb-phase2-raw-processors --region=us-west2 --project=nba-props-platform
```

### 5. Monday retrain verification
After 5 AM ET Monday: check Slack `#nba-alerts` for retrain results. If CF fails 60% gate, manually enable disk models or force-register.

---

## Observation Filters — Remaining Work

Still pending BQ verification before promoting/removing:

```sql
SELECT filter_name, AVG(cf_hr) AS avg_cf_hr, SUM(n_blocked) AS total_n
FROM nba_predictions.filter_counterfactual_daily
WHERE game_date >= '2025-11-01'
  AND filter_name IN (
    'neg_pm_streak_obs','line_dropped_over_obs',
    'ft_variance_under_obs','familiar_matchup_obs','b2b_under_block_obs',
    'player_under_suppression_obs'
  )
GROUP BY 1 ORDER BY avg_cf_hr DESC
```

From Session 461 simulation (5-season validated, pending current-season verification):
- Remove: `neg_pm_streak_obs` (64.5% CF HR, N=758), `line_dropped_over_obs` (60.0%, N=477), `ft_variance_under_obs`, `familiar_matchup_obs`, `b2b_under_block_obs`

---

## Full Commit Log (Sessions 494-495)

| Commit | Description |
|--------|-------------|
| `0652741a` | retrain.sh eval date bug fix |
| `7b2901c9` | retrain.sh python → .venv/bin/python3 |
| `98b59ecc` | promote hot_shooting_reversion + remove flat_trend_under |
| `79f6a0f8` | promote/remove 7 observation filters |
| `68c5eb1e` | shared/ sync to 6 CF directories |
| `0ad2bd66` | Layer 6 fixes: DELETE gate, row-level fallback, canaries, drift script |
| `ff7b8922` | Session 494 original handoff |
| `1b5cbf8a` | **Session 495: signal drought fix + home_under restore** |
| `9d3e081c` | Session 495 handoff docs |
| `2da15d31` | Session 495 morning handoff (initial) |
| `a176e89a` | Streaming buffer fix + MLB auto-event-discovery + filtered picks bug |
| `cabd04d1` | Updated morning handoff with root cause analysis |
| `b291e91b` | Signal drought diagnosis queries |

---

## Reference Docs

- Signal drought root cause: `docs/09-handoff/2026-03-26-SESSION-495-SIGNAL-DROUGHT-FIX.md`
- Detailed handoff (Session 494): `docs/09-handoff/2026-03-26-SESSION-494-LAYER6-FIXES.md`
- Morning handoff (updated): `docs/09-handoff/2026-03-27-SESSION-495-MORNING-HANDOFF.md`
- Diagnostic queries: `docs/02-operations/queries/signal-drought-diagnosis-2026-03-26.sql`
- MLB launch runbook: `docs/08-projects/current/mlb-2026-season-strategy/07-LAUNCH-RUNBOOK.md`
