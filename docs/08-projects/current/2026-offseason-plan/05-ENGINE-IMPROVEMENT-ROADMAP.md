# Prediction Engine Improvement Roadmap — 2026-05-19

**Created:** 2026-05-19
**Source:** 20-agent parallel review of the prediction engine (one agent per subsystem),
synthesized and code-verified.
**Relationship to other docs:** Extends [`01-VALIDATION-AND-IMPROVEMENT-PLAN.md`](01-VALIDATION-AND-IMPROVEMENT-PLAN.md)
(the Session-545 4-agent April audit, 32 bug/gap items, "Draft — awaiting sign-off").
That plan is **bug/gap-focused and mostly unexecuted**; this doc re-confirms its
load-bearing findings, adds **forward-looking experiments** the April audit did not
cover, lists **new bugs** it missed, and gives one unified priority order.

---

## Executive summary

- **The headline finding is real and verified: model training has temporal leakage.**
  Three review agents found it independently, and the April audit (T2-1/2/3) found it
  before that. The leak means the foundational lore — "V12_NOVEG is best, adding
  features hurts, 56-day window, 7-day retrain" — was concluded from contaminated
  experiments and **cannot be trusted until the leak is fixed and experiments re-run.**
- **Recurring meta-pattern:** *compute X → store X → never use X.* Dozens of features,
  signals, and filters are calculated and written to BigQuery but never affect a pick
  (`edge_zscore`, V18 features 60-63, referee data, position-specific DvP, several
  graduated-but-dead signals).
- **Most of the April plan is unexecuted.** As of its 2026-04-26 revision only T1-1/2/3
  (3 of 32) are marked fixed. The leakage trifecta was verified **still present in the
  code on 2026-05-19**.

---

## Part 1 — Verification log

Every load-bearing claim below was checked against the actual code on 2026-05-19.

| Claim | Location | Status |
|---|---|---|
| Random train/val split (leakage) | `ml/experiments/quick_retrain.py:3846-3850` — `train_test_split(..., random_state=args.random_seed)` | **CONFIRMED** |
| weekly_retrain split is non-temporal | `weekly_retrain/main.py` — `load_training_data` query (L327-343) has **no `ORDER BY`**; `.iloc[:85%]` split at L722-726. Comment "85/15 date-based split" is false | **CONFIRMED** |
| V12 `season_stats` augmentation joins eval data | `quick_retrain.py:~1090-1188` (April audit T2-3) | CONFIRMED (April audit, independent) |
| Governance N too small | `quick_retrain.py:4339` `MIN_BETS_RELIABLE=25`; `weekly_retrain/main.py:102` `min_n_graded=15` (`10` season-restart) | **CONFIRMED** |
| `recent_trend` feature 11 inverted | `feature_calculator.py:138-150` — `last_10_games` is newest-first; `[0:3]` mislabeled "first_3" | **CONFIRMED** |
| `rest_advantage_2d` dead weight | `aggregator.py:198` weight `2.0`; `registry.py:172` `register()` commented out | **CONFIRMED** |
| `edge_zscore` computed, never used in ranking | `aggregator.py:1305` compute, `:1503` store, no other refs | **CONFIRMED** |
| MLB `xfip_elite_over` silently dead | `predictions/mlb/pitcher_loader.py` — `xfip` absent from FanGraphs SELECT (0 occurrences) | **CONFIRMED** |
| MLB `il_return_skip`/`pitch_count_cap_skip` dead | `signals.py:565,583` read `sup.get('is_il_return'/'pitch_count_limit')`; `supplemental_loader.py` never sets them | **CONFIRMED** |
| Referee data has zero ML consumers | `covers_referee_stats` / referee assignments: no refs in `ml/`, `data_processors/precompute/`, `data_processors/analytics/` | **CONFIRMED** |
| Coordinator hardcodes points market | `predictions/coordinator/player_loader.py` — 8 × `market_type/prop_type = 'points'` + 1 in `data_freshness_validator.py` | **CONFIRMED (9)** |
| `archetype_analyzer.py` / `expanded_scanner.py` missing | `scripts/nba/training/discovery/` has only `combo_tester, data_loader, feature_scanner, stats_utils` | **CONFIRMED** |
| Ultra backtest window frozen | `ml/signals/ultra_bets.py:28-29` `BACKTEST_END='2026-02-21'` | **CONFIRMED** |

Not independently re-verified (trusted from agent file:line cites — re-check before scheduling):
Brier `edge/15` normalization (`model_performance.py:318`), auto-halt querying raw
predictions (`regime_context.py:196-204`), dead features 41/42/47/50, `bench_under`
signal/filter contradiction, merger rescue-cap priority gap, `SEASON_CALENDARS` missing
2026-27.

---

## Part 2 — Prioritized roadmap

Effort: XS <1h · S 1-4h · M half-to-full day · L multi-day. Tag `[APR …]` = also in the
April plan; `[NEW]` = surfaced by this review.

### P0 — Foundation (do first; gates every model experiment)

Nothing about features, windows, or cadence can be trusted until these land. They
compound — fix together, then retrain the fleet once on clean data.

| ID | Item | Effort | Notes |
|---|---|---|---|
| P0-1 | Fix random train/val split → temporal cutoff | S | `[APR T2-1]` `quick_retrain.py:3846`: sort by `game_date`, take last 15%. `weekly_retrain`: add `ORDER BY mf.game_date` to the `load_training_data` query (L327) — then the existing `.iloc` split becomes correct for free. |
| P0-2 | Fix V12 `season_stats` augmentation leakage | M | `[APR T2-3]` Training rows must use a window capped at `train_end`; eval rows per-row `< game_date`. Add the regression test from T2-3. |
| P0-3 | Governance: separate holdout from val, raise N, add bootstrap CIs | M | `[APR T2-2]` Train `[start, end-14]` / val `[end-13, end-7]` / strict holdout `[end-6, end]`; `min_n>=40`; print 95% CI on every gate (at N=25 a 53% gate has a ±20pp CI). |
| P0-4 | Re-run the foundational experiments on clean data | M | `[NEW]` After P0-1/2/3: re-test V13–V19 feature sets, **42-day window**, and **14/21-day cadence**. The only post-leakage replay evidence already points to 21-day cadence and 42-day window beating the current 7d/56d. Expected recovery: 1–3pp HR. |

### P1 — High-EV experiments (new; April audit did not cover these)

| ID | Item | Effort | Notes |
|---|---|---|---|
| P1-1 | Referee-crew OVER signal | S | `[NEW]` `covers_referee_stats` + referee assignments are scraped daily with **zero consumers** — the scraper docstring already specs `ref_crew_over_tendency`. Verify the table is per-date vs season-aggregate first. |
| P1-2 | Bias-corrected edge for the OVER floor | S | `[NEW]` Apply the OVER edge floor to `edge − pred_bias_7d` (already in `model_performance_daily`). A model with +2K bias overstates every OVER edge. |
| P1-3 | Fix auto-halt input | S | `[NEW]` `regime_context.py` computes the edge auto-halt over **all ~180 raw predictions/day**, not the 5–15 BB-eligible picks. The hardest gate uses the wrong population. |
| P1-4 | Implement the low-line + low-variance UNDER archetype | S | `[NEW]` 5-season discovery found 62% HR, N=819, 4/4 seasons consistent — the single most stable pattern found, and **no signal/filter captures it.** |
| P1-5 | Graduate validated-but-shadow signals | S | `[NEW]` `ft_anomaly_under` (63.3%, N=278), `downtrend_under` (63.9%, N=1654) — check BB-level N, promote into `UNDER_SIGNAL_WEIGHTS`. |
| P1-6 | Volatility-normalized edge (`edge_zscore`) | M | `[NEW]` Already computed and stored (`aggregator.py:1305`), never used. A 6pt edge on a volatile 28-PPG star ≠ on a steady 14-PPG role player. Backtest as a secondary OVER gate. |

### P2 — Quick-win bug fixes (low effort, currently bleeding value)

| ID | Item | Effort | Notes |
|---|---|---|---|
| P2-1 | Remove dead `rest_advantage_2d` weight | XS | `[NEW]` Weight `2.0` in `OVER_SIGNAL_WEIGHTS` but signal unregistered → never fires; harmless-but-misleading dead code. |
| P2-2 | Fix MLB `xfip_elite_over` (silently dead) | S | `[NEW]` A *promoted* 67.5%-HR signal that produces nothing — `fg.xfip` is not in the `pitcher_loader` SELECT. Also `low_era_high_k_combo_over` (wrong key `season_era`). |
| P2-3 | Fix MLB `il_return_skip` / `pitch_count_cap_skip` | S | `[NEW]` Filters read `sup` keys the supplemental loader never sets → they pass every pitcher. Either populate the keys or remove the filters. |
| P2-4 | Fix `recent_trend` (feature 11) inversion | S+retrain | `[NEW]` Confirmed inverted. Low model impact (CatBoost learns the sign), but fix on the next retrain and audit any signal that reads it expecting "positive = improving." |
| P2-5 | Drop dead constant features 41/42/47/50 | S | `[NEW]` Always-default constants wasting CatBoost split budget. Fold into the P0-4 clean re-run. |
| P2-6 | Filter / signal registry drift | S | `[APR T3-1/T3-2]` ~18 active blocking filters missing from `filters.yaml`; `ACTIVE_SIGNALS` and `ELIGIBLE_FOR_AUTO_DEMOTE` stale. `bench_under` is both a +2.0 signal and a "would-block" filter — resolve the contradiction. |
| P2-7 | Remaining April Tier-1 gaps | S–M | `[APR T1-4/5/6]` Phase 4→5 coverage gate; quality scorer blind to features 54-59; published-JSON-vs-BQ reconciliation canary. |

### P3 — New markets / products

| ID | Item | Effort | Notes |
|---|---|---|---|
| P3-1 | 3-pointers-made market | S–M | `[NEW]` Fastest new market: scraper supports market ID 162, 3PT signals already exist, 4 seasons of actuals in `player_game_summary`. Needs a dedicated model + grading mapping. |
| P3-2 | Make the pipeline prop-type agnostic | M | `[NEW]` **Blocker for assists/rebounds:** coordinator hardcodes `market_type='points'` in 9 places; grading hardcodes `actual_points`. Must be parameterized before any non-points market can run. |
| P3-3 | Assists / rebounds models | L | `[NEW]` After P3-2. Data clock started 2026-04-06; `hashtagbasketball_dvp` already has `assists_allowed`/`rebounds_allowed` (currently orphaned). Won't have enough graded data until ~Nov 2026. |
| P3-4 | MLB strikeout UNDER | S | `[NEW]` Currently OVER-only by config. Low-risk walk-forward test to see if UNDER has edge. |
| P3-5 | Ultra-bets cross-season validation + staking | S–M | `[NEW]` Ultra criteria were never walk-forward validated (100% HR on N=26, single 44-day window). Validate across 3 seasons before adding an NBA staking multiplier (MLB already has one). |

### P4 — Deeper research bets (lower confidence, higher ceiling)

- **Player modeling:** player identity as a CatBoost categorical; 2-state HMM hot/cold
  signal (no HMM approach tried yet — not a dead end).
- **Market microstructure:** line-move *velocity* (not just magnitude); `vig_skew`
  (feature 61, computed, unused); sharp-book-only disagreement std.
- **MLB model:** batter-level lineup K-rate, umpire K-rate as a regressor feature,
  Poisson loss A/B (flag already wired in `train_regressor_v2.py`).
- **Phase 3/4 features:** position-specific DvP (data exists, only `position='ALL'`
  used), Q4/clutch scoring from play-by-play, NBA tracking touch/drive rates.
- **Calibration:** replace the bogus `edge/15` Brier normalization with proper Platt
  scaling for honest cross-model calibration comparison.

---

## Part 3 — Relationship to the April plan

- **Re-confirmed and still open:** the leakage trifecta (T2-1/2/3 → P0), quality-scorer
  feature gap (T1-5 → P2-7), cross-model diversity gate (T2-8), registry drift
  (T3-1/2 → P2-6), `book_count` never populated (T3-4), MultiQuantile dead code (T3-10).
- **Net-new from this review:** every P1 experiment, the P2 bugs (`rest_advantage_2d`,
  MLB `xfip`/`il`/`pitch` filters, `recent_trend` inversion, dead features), all P3
  new markets, all P4 research bets. The April audit was a *reliability* audit; it did
  not look for growth experiments or for these specific dead-code paths.
- **Action:** the April plan's Tier-1 reliability items (T1-4/5/6) and Tier-2
  infra-hardening (T2-4..10) remain valid and should be scheduled in parallel with the
  model work here — they are independent workstreams.

---

## Part 4 — Recommended execution order

1. **Week 1 — P0-1 + P0-3** (the two cheap leakage/governance fixes). Land them, then
   nothing downstream is built on sand.
2. **Week 1–2 — P2 quick wins** in parallel (independent, low-risk, stop active bleeding).
3. **Week 2 — P0-2** (augmentation leakage) then **P0-4** (the clean re-run). This is the
   payoff: it tells you whether "adding features hurts" was ever true.
4. **Weeks 3+ — P1 experiments**, highest-EV first (P1-1 referee signal, P1-3 auto-halt
   fix, P1-4 archetype). Each is independently shippable and shadow-testable.
5. **P3-1 (3PT)** can start any time — it doesn't depend on the model work.
6. **P3-2 (prop-type plumbing)** before committing to assists/rebounds.
7. **P4** as research capacity allows.

**One-line recommendation:** start at P0-1. It is a few lines of code, and it is the
gate on trusting every experiment that follows.
