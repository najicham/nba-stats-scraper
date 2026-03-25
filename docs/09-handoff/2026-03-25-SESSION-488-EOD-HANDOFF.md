# Session 488 EOD Handoff — 2026-03-25

**Latest commits:** `17c46fa0` — feat: BettingPros fallback for feature 50 (book_disagreement signal)
**Branch:** main (auto-deployed)

---

## System State: RECOVERING (filters corrected, picks purged)

The morning part of this session made 5 filter demotions based on a misreading of CF HR. A 10-agent review panel caught the error: CF HR is the hit rate of *blocked* picks. A filter blocking winners would have CF HR ≥ 55%. Filters at 37–52% CF HR are doing their jobs. 4 of the 5 demotions were reverted. Today's 7 bad picks were removed via Phase 6 re-export.

---

## What Was Done This Session (488)

### Part 1: Morning Sweep (commit `f56dd6e2` — PARTIALLY WRONG)

10 agents ran in parallel investigating the pick drought. Most findings were correct. One was wrong:

**Correct findings:**
- `combo_3way` and `book_disagreement` are NOT cross-model signals — fire from single-model data
- Session 487's "fleet diversity collapse" narrative was incorrect about signal gating
- `odds_api` API changed Mar 16, breaking Feature 50 (`book_disagreement_score`)
- `lgbm_v12_noveg_train1215_0214` expected to auto-disable Mar 26 via decay CF

**Wrong finding — the filter demotions:**

The agent reported CF HR = hit rate of *winner* picks blocked. It's actually the *inverse*: CF HR = hit rate of the blocked picks themselves. A filter correctly blocking losers has a LOW CF HR (the blocked picks lose at high rate). A filter incorrectly blocking winners has a HIGH CF HR ≥ 55%.

Session 488 morning demoted 5 filters with CF HR 37–52%, which is correctly working filters.

### Part 2: Corrective Action (commits `8708b228`, `17c46fa0`)

#### 2a. Revert 4 incorrect filter demotions (`8708b228`)

**File:** `ml/signals/aggregator.py`

| Filter | CF HR | Correct Status | Notes |
|--------|-------|----------------|-------|
| `signal_density` | 40% (N=35) | **ACTIVE (restored)** | 60% of blocked picks lose — doing its job |
| `med_usage_under` | 45.9% (N=37) | **ACTIVE (restored)** | 54% of blocked picks lose — doing its job |
| `line_dropped_under` | 37.5% (N=8) | **ACTIVE (restored)** | 62% of blocked picks lose — very effective |
| `under_after_streak` | 45.5% (N=11) | **ACTIVE (restored)** | Session 418 N=515 finding (44.7%) validates direction |

**Kept demoted (observation-only):**
- `opponent_under_block`: CF HR 52.4% — above 50%, borderline. Stays observation per the plan.

All 4 reverted filters now use `if 'filter_name' not in self._runtime_demoted: continue` pattern, so auto-demote system can still override if needed.

Added missing `line_dropped_under` log message (it had no logger.info call before).

#### 2b. Phase 6 re-export to remove today's 7 bad picks

After the filter revert commit deployed (`deploy-phase6-export` triggered by `8708b228`):

```bash
gcloud pubsub topics publish nba-phase6-export-trigger \
  --project=nba-props-platform \
  --message='{"export_types": ["signal-best-bets"], "target_date": "2026-03-25"}'
```

The aggregator re-evaluated all candidates with the corrected filters. The scoped DELETE removed the 7 previously-published picks (KD, Shai, Reaves + others — all edge 3–5 no-signal UNDER picks).

**Result:** GCS JSON updated to 0 picks (confirmed by degradation alert at 22:15: "picks_dropped_to_zero (was 7)"). BQ `signal_best_bets_picks` still has 7 rows — the scoped DELETE only removes players in the current output; with 0 aggregator picks, scope was empty. Frontend is correct. The 7 rows will grade as data points; they are effectively "shadow" records now.

#### 2c. Artifact Registry keepCount 3 → 5

Updated `keep-minimum-versions` policy via `gcloud artifacts repositories set-cleanup-policies`:
- `nba-props`: 3 → 5
- `cloud-run-source-deploy`: 3 → 5
- `gcf-artifacts`: 3 → 5

3 was too tight (~5-6 hours of rollback window). 5 gives ~1 day. Note: net change from start of session is 10→5 (session 488 morning reduced from 10 to 3, this corrective step raised to 5).

#### 2d. BettingPros fallback for Feature 50 (`17c46fa0`)

**Files:** `data_processors/precompute/ml_feature_store/feature_extractor.py`, `ml_feature_store_processor.py`, `quality_scorer.py`

`book_disagreement` signal has been near-zero since Mar 16 when the odds_api changed format. Feature 50 (`multi_book_line_std`) drives this signal.

Fallback logic: when odds_api produces 0 players OR MAX(line_std) < 0.3, query `nba_raw.bettingpros_player_points_props` instead. Excludes DFS platforms (PrizePicks, PropSwap, Fliff, Underdog, Sleeper) that don't set sharp lines.

**Shadow mode:** Source tagged as `'bettingpros'` in `feature_50_source`. Running in observation for 2-3 weeks. Threshold of 1.5 may need lowering to ~1.2 for BettingPros data — validate before changing.

Expected recovery: ~30% restoration of `book_disagreement` signal instances.

Quality scorer updated:
- `SOURCE_WEIGHTS['bettingpros'] = 100` (same quality as vegas)
- `SOURCE_TYPE_CANONICAL['bettingpros'] = 'bettingpros'` (distinct for shadow tracking)

#### 2e. Cloud Build trigger filtering — already in place

Verified all 31 triggers have `includedFiles` patterns. The Session 388 risk (docs commit deploys all services) is already mitigated. No changes needed.

---

## Morning Findings (Session 488) — Still Valid

### combo_3way and book_disagreement are NOT cross-model signals

Session 487 documented the pick drought as "fleet diversity collapse — cross-model signals cannot fire." This was wrong.

- `combo_3way`: fires when model recommends OVER AND pace is fast AND usage surge. All single-model data.
- `book_disagreement`: fires when opening vs closing line moves significantly AND sharp book (Pinnacle/BetCNX) disagrees with market. All single-model data.

Neither signal requires 2+ models to agree. Fleet diversity does not gate them.

**CLAUDE.md correction needed:** The "fleet diversity collapse" entry in pick drought causes is misleading. Real cause of the Mar 18-24 drought: 5 UNDER filters over-blocked UNDER candidates. With OVER floor at 5.0, almost all picks come from UNDER — blocking UNDER = blocking everything.

### book_disagreement signal improvement underway

Feature 50 (`book_disagreement_score`) collapsed Mar 16 due to odds_api format change. BettingPros fallback is now deployed (shadow). If it works, `book_disagreement` should recover ~30% of signal instances within a few days.

Monitor:
```sql
SELECT game_date, COUNT(DISTINCT feature_50_source) as sources,
       COUNTIF(feature_50_source = 'bettingpros') as bp_players,
       AVG(feature_50_value) as avg_std
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC
```

---

## NBA Fleet (4 enabled models)

| Model | Framework | Train Window | State | Notes |
|-------|-----------|-------------|-------|-------|
| `lgbm_v12_noveg_train0103_0227` | LGBM | Jan 3 – Feb 27 | HEALTHY | Anchor model |
| `lgbm_v12_noveg_train0103_0228` | LGBM | Jan 3 – Feb 28 | BLOCKED 50.0% | 1 day BLOCKED as of Mar 24 |
| `lgbm_v12_noveg_train1215_0214` | LGBM | Dec 15 – Feb 14 | BLOCKED 45.7% | **Auto-disable fires Mar 26 (tomorrow)** |
| `catboost_v12_noveg_train0118_0315` | CatBoost | Jan 18 – Mar 15 | active (re-enabled) | Framework diversity; rarely produces edge 5+ independently |

---

## Pending Items

- [ ] **Mar 26 (tomorrow), 11 AM ET** — Decay CF fires. `lgbm_v12_noveg_train1215_0214` hits 3-day BLOCKED gate → auto-disable expected. Fleet drops to 3 models (above 3-model safety floor). Verify after 11 AM ET.
- [ ] **Mar 26** — Monitor today's corrected picks. Expected: 0 picks published for Mar 25 after Phase 6 re-export (verify below).
- [ ] **Mar 27** — MLB Opening Day. Run Session 486 verification queries.
- [ ] **Mar 28** — MLB `mlb_league_macro.py` backfill after first games grade.
- [ ] **Mar 30, 5 AM ET** — Weekly retrain CF fires. Expected IDs: `lgbm_v12_noveg_train0110_0307`, `catboost_v12_noveg_train0110_0307`. Window: Jan 10 – Mar 7 (cap fires). Watch avg_abs_diff — if still ≤1.5, pick drought is structural TIGHT market effect.
- [ ] **Post-retrain** — Enable new models, clean up BLOCKED models.
- [ ] **BettingPros shadow validation** — After 2-3 weeks, query `feature_50_source = 'bettingpros'` picks and check `book_disagreement` signal HR. If signal HR recovers to >60%, lower threshold from 1.5 to 1.2 and graduate.
- [ ] **Backtest needed:** `fast_pace_over` threshold 0.75 → 0.55. Run 5-season validation before changing.
- [ ] **Backtest needed:** `combo_3way` MIN_SURGE 3.0 → 2.0. Run 5-season validation before changing.
- [ ] **CLAUDE.md correction** — "Fleet diversity collapse" in pick drought causes needs reframing. Not about signal gating — about UNDER filter over-blocking.
- [ ] **Observation filter debt (ongoing)** — `thin_slate_obs`, `neg_pm_streak_obs` showed 60-62% CF HR in holistic agent (full season). Dedicated investigation needed with full-season data.
- [ ] **Apr 14** — Playoffs shadow mode activation.

---

## Morning Verification for Session 489

### 1. Confirm GCS JSON has 0 picks for Mar 25

The BQ `signal_best_bets_picks` table still has 7 rows (scoped DELETE was empty since re-export produced 0 picks). They will grade. The frontend JSON is clean.

Check how they graded:
```sql
SELECT sbp.player_lookup, sbp.recommendation, sbp.pick_edge,
       pa.prediction_correct, pa.actual_points, sbp.line_value
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks` sbp
JOIN `nba-props-platform.nba_predictions.prediction_accuracy` pa
  ON pa.player_lookup = sbp.player_lookup AND pa.game_date = sbp.game_date
WHERE sbp.game_date = '2026-03-25'
  AND pa.has_prop_line = TRUE
  AND pa.prediction_correct IS NOT NULL
-- Expected: 7 graded. If HR < 50%, the re-activated filters were protecting winners.
-- If HR > 50%, the re-activated filters may have been too aggressive.
```

### 2. Fleet count after decay CF (runs 11 AM ET Mar 26)

```sql
SELECT model_id, enabled, status
FROM `nba-props-platform.nba_predictions.model_registry`
WHERE enabled = TRUE
ORDER BY model_id
-- Expected: 3 models after lgbm_train1215_0214 auto-disabled
```

### 3. Mar 26 picks flowing with corrected filters

```sql
SELECT game_date, recommendation, COUNT(*) as n,
       ROUND(AVG(pick_edge), 2) as avg_edge
FROM `nba-props-platform.nba_predictions.signal_best_bets_picks`
WHERE game_date = '2026-03-26'
GROUP BY 1, 2
-- Expected: UNDER picks flowing again (5 filters were blocking the pool)
```

### 4. BettingPros fallback working

```sql
SELECT game_date,
       COUNTIF(feature_50_source = 'bettingpros') as bp_players,
       COUNTIF(feature_50_source = 'phase4') as odds_api_players,
       ROUND(AVG(CASE WHEN feature_50_source = 'bettingpros' THEN feature_50_value END), 3) as bp_avg_std
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date >= CURRENT_DATE() - 2
GROUP BY 1 ORDER BY 1 DESC
-- Expected: bp_players > 0 when odds_api is dead
```

### 5. Filter audit — verify no unexpected blocks

```sql
SELECT filter_reason, recommendation, COUNT(*) as blocked
FROM `nba-props-platform.nba_analytics.best_bets_filtered_picks`
WHERE game_date = '2026-03-26'
GROUP BY 1, 2
ORDER BY 3 DESC
LIMIT 20
```

---

## Key Active Constraints (Do Not Change Without Review)

- **OVER edge floor: 5.0** — do not lower, 5-season finding holds
- **`high_spread_over_would_block`: KEEP ACTIVE** — all-time CF HR 50% (7-7, N=14). No demote until N≥30
- **`opponent_under_block`: STAYS OBSERVATION** — CF HR 52.4%, borderline, no re-activate until N≥30 at CF HR ≥55%
- **`projection_consensus_over`: DO NOT GRADUATE** — BB HR 1-8 (12.5%), catastrophic at BB level
- **`usage_surge_over`: DO NOT GRADUATE** — BB-level HR 40% (N=5), not the signal_health_daily 68%
- **4 reverted filters: ACTIVE** — signal_density, med_usage_under, line_dropped_under, under_after_streak. CF HR < 50% = doing their jobs.
- **CF HR interpretation:** CF HR is the hit rate of BLOCKED picks. Low CF HR (37-46%) = filter correctly blocking losers. Auto-demote threshold is CF HR ≥ 55% (blocking winners). Do NOT demote below 55%.
- **BettingPros fallback: SHADOW ONLY** — threshold 1.5 stays, evaluate over 2-3 weeks before any changes
- **`fast_pace_over` threshold: DO NOT CHANGE** without 5-season backtest
- **`combo_3way` MIN_SURGE: DO NOT CHANGE** without 5-season backtest
- **Fleet minimum: 3 enabled models** — currently 4, drops to 3 Mar 26 after decay CF

---

## Session 488 Commits (5 total)

```
17c46fa0 feat: BettingPros fallback for feature 50 (book_disagreement signal)
8708b228 fix: revert 4 incorrect filter demotions from Session 488
c8c43a9a fix: make LOG_LEVEL env var effective in worker, coordinator, scrapers, monitors
02847a85 fix: reduce BQ cost from bigdataball-puller SA (~2 TB/day → ~50 GB/day)
f56dd6e2 fix: demote 5 UNDER filters to observation — CF HR 37-52%, blocking winners
```

Note: `f56dd6e2` demoted 5 filters; `8708b228` reverted 4 of those demotions (opponent_under_block stays observation).

### Infrastructure changes (no commits — gcloud/BQ only):

Morning:
- 5 stale Cloud Scheduler jobs deleted
- 4 scheduler job URLs updated to current Cloud Run revisions
- Artifact Registry keepCount 10→3 on 3 repos (then corrected to 5 below)
- 13 stale BQ tables deleted (including `bdl_live_boxscores` 2.13 GB)
- 45 monitoring services: `LOG_LEVEL=WARNING` set

Corrective (this sub-session):
- Artifact Registry keepCount 3→5 on 3 repos (`nba-props`, `cloud-run-source-deploy`, `gcf-artifacts`)
- Phase 6 re-triggered for 2026-03-25 (removes 7 bad picks)
- Verified all 31 Cloud Build triggers have `includedFiles` filtering (no changes needed)
