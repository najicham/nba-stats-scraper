# MLB Pitcher-Ks Improvement Plan

**Date:** 2026-05-11 (afternoon session)
**Investigation:** 23 agents (15 original + 8 reviewers + cleanup) + 1 fresh reviewer
**Status:** Approved for execution, sequencing per reviewer corrections

---

## Headline finding

**The MLB system is operationally underbuilt, not algorithmically deficient.** Seven of fifteen agents independently surfaced fully-built-but-never-deployed plumbing. The biggest single multiplier isn't new ML — it's turning on what already exists.

## Convergent reviewer verdict

All 8 reviewers agree on this split:
- **Plumbing items: SHIP NOW** — zero in-sample threshold mining, just restore intended model behavior
- **New threshold-tuned filters/signals: HOLD AS SHADOW** — every quantitative claim derived from 40-day in-sample window failed out-of-sample validation
- **Missing entirely: edge-based auto-halt** — must ship BEFORE new pick-volume-increasing signals

## Critical reviewer-found errors in original 3-agent plan

| Original claim | Correction |
|----------------|-----------|
| "Wire 11 dead features (~1 day, highest ROI)" | **5 of 11 are abandoned-by-design** (retired BDL sources). 6 are 30min-4h fixes ranging from table-rename to missing scheduler. |
| "Add `book_disagree_over_pitcher` signal (NBA pattern, 93% HR)" | **Direction REVERSED in MLB.** OVER gets worse with disagreement (45.7% HR at std≥0.75). UNDER gets better (71.4%). Right signal is `book_disagree_under`. |
| "Promote LightGBM to unlock cross-model signals" | **Cross-model unlock was a myth.** `combo_3way` + `book_disagreement` are single-model. MLB has zero cross-model infra. |
| "True bottom-up K from `bp_batter_props`" | **Dead end.** `batter_strikeouts` market extinct from Odds API since Sep 2024. Drop. |
| "Day-of-week / calendar filter set" | **No pattern survives Bonferroni** at current N. Defer to 2027+. |
| Tier 1 #1 mid-archetype filter "N=7, 14.3% HR" | **Numbers unreproducible.** `f05_season_k_per_9` is 100% NULL in production. OOS shows ~3-5pp effect not 36pp. |
| Tier 1 #2 f28 umpire "30 min table-rename" | **Misleading.** SELECT references columns (`career_k_adjustment` etc.) that don't exist on target table. Real fix is column-redesign + UmpScorecards backfill, ~1 day. |
| Book disagreement HR numbers | **Drift 10pp when re-queried** (plan 71.4% N=35 → actual 61.8% N=76). Direction correct, magnitudes unreliable. |

---

## Revised Tier 1 — Highest ROI, Low Effort

**Reviewer-corrected priorities (independent EV/cost re-ranking by Reviewer 3):**

| Rank | # | Item | Effort | Verdict |
|------|---|------|--------|---------|
| 1 | T1.3 | **Anchor training window to `last_april_1`** at `train_regressor_v2.py:141`. 1-line edit (~5 min) + retrain run. Eliminates +0.60 K April bias (cost in old model: 45.8% HR on Apr 1-14 OVER) | 2h | **SHIP** (structural, low overfit risk) |
| 2 | T1.6 | **Demote `high_csw_over` to shadow.** Note: `chase_rate_over` is **ALREADY shadow** (Reviewer 2 caught plan error) | 30 min | **SHIP** |
| 3 | NEW | **Build MLB edge-based auto-halt FIRST.** Port `regime_context.py` to MLB. Without this, every pick-volume-increasing signal is uncovered risk. NBA paid for this lesson with 25.6% of season profit in March | 1 day | **SHIP** (Reviewer 4's critical addition) |
| — | T1.7 | **DROP** — `ballpark_k_factor` already in 36-feature vector at `catboost_v2_regressor_predictor.py:34` (Reviewer 2 verified) | — | **REMOVE** |
| 4 | T1.4 | Wire f11/f13 splits — IF `bdl_pitcher_splits` actually has data (stub docstring says BDL retired Session 430; verify first) | 1-4h | **SHIP if verified** |
| 5 | T1.5 | Schedule existing `MlbLineupKAnalysisProcessor` | 1-2h | **SHIP** |
| 6 | T1.1 | `high_k_mid_archetype_over_block` filter — **SHADOW ONLY, N≥150 graded blocks before promote.** OOS effect is 3-5pp not 36pp; in-sample numbers unreproducible | 2-4h | **SHADOW** (not active) |
| 7 | T1.2 | f28 umpire fix — **NOT 30 min.** Real fix needs `mlb_umpire_assignments` table-rename + `mlb_umpire_stats` UmpScorecards backfill + weekly scheduler. ~1 day total | 1 day | **SHIP** (downgrade priority — Reviewer 3 demoted from #2 to T2) |

---

## Revised Tier 2 — Medium effort, validated lift

| # | Item | Effort | Notes |
|---|------|--------|-------|
| T2.10 | **Fix Statcast aggregation pipeline.** `mlb_raw.statcast_pitcher_game_stats` 7-month stale (last Oct 1, 2025). `mlb_precompute.pitcher_arsenal_summary` empty. Backfill unblocks f50-f53 (silently NaN in trained model — CatBoost NaN-tolerant). Reviewer 2 caveat: features are NaN not zero; populating them is a silent inference change | 1-2 days | **SHIP plumbing; verify HR delta before declaring win** |
| T2.11 | **Weather pipeline activation.** Scraper exists at `scrapers/mlb/external/mlb_weather.py`, never scheduled. 2-4h to add Cloud Scheduler | 2-4h | **SHIP plumbing** |
| T2.13 | **MLB weekly-retrain CF** with TWO training caps (TIGHT-market + late-season) ported from NBA. Reviewer 4: don't ship retrain CF without both caps | 1 day | **SHIP** (pair with T1.3 in same PR) |
| T2.9 | MLB line-drop signals — fix `opening_line` field in `supplemental_loader.py:120-162` (never assigned). 2 viable signals at 57%/62% HR (N=21/13) | 1.5-2 days | **SHADOW ONLY, N≥200 each direction** |
| T2.8 | `book_disagree_under` signal — fixed direction (UNDER not OVER), oa_std≥0.65, `oddsa_pitcher_props` data. **Add `_get_min_std(book_count, market_id)` scaffolding from day 1** (Reviewer 4 — avoid NBA Session 515 trap) | 2 days | **SHADOW ONLY, N≥200** |
| T2.12 | Wire f18/f19 (game total / implied runs) — `oddsa_game_lines` empty all-time, investigate scraper | 2-4h | **SHIP plumbing** |

---

## Revised Tier 3 — Conditional

| # | Item | Effort | Notes |
|---|------|--------|-------|
| T3.14 | LightGBM v1 shadow — **shadow only.** Reviewer 7: reject if r>0.85 with catboost_v2. Don't enable until per-pitcher dedup in `mlb_best_bets_exporter.py` | 2-3 days | Don't justify on cross-model signals — that was a myth |
| T3.15 | `team_quick_hook_over_shadow` — N=40, 72.5% HR. Team-quality confound (CWS/COL/OAK have bad pitching AND quick hooks) unaddressed | 2h | **N≥150 OOS before promote** |
| — | Real cross-model infrastructure | 2-3 weeks | **Don't build until 3+ models genuinely useful** |

---

## Explicit REJECTs (evidence-backed)

- **Bottom-up K from batter props** — Odds API `batter_strikeouts` extinct since Sep 2024; r=0.28 vs Vegas-line r=0.40 even when alive
- **Calendar / DOW filters** — Best raw signal (Thursday 41.5% HR) fails uncorrected p<0.05. Only 1 partial season in BQ
- **Catcher framing signals** — Source table empty (0 rows ever). Savant URL broken (`year` param ignored, verified)
- **New recent-form signals** — Residual correlation = -0.003. Model already captures form
- **New net-new Statcast derived features** (FTTO K-rate, pitch-mix shift) — Correlations 0.02-0.16, collinear with rolling K averages

---

## Critical missing items (per reviewers)

| Item | Source | Priority |
|------|--------|----------|
| **MLB edge-based auto-halt** — port `regime_context.py` to MLB. Without this, every new pick-volume signal is uncovered risk | Reviewer 4 (NBA pattern skeptic) | **MUST SHIP BEFORE any new signal/filter** |
| **`model_raw_predictions` table** — write every prediction with full feature snapshot + signal/filter evaluations, regardless of BB eligibility. The measurement substrate every future analysis needs | Reviewer 5 (devil's advocate) | High — single highest-leverage move not in original plan |
| **Walk-forward replay backfill of 2024-2025** — extend `walk_forward_simulation.py` to emit pick-level records to BQ. 5,000-10,000 historical BB-equivalent picks vs current 543 | Reviewers 7 + 8 | High — would make all Tier 1 #1 / Tier 2 #8 claims OOS-validatable |
| **`MLB_UNDER_ENABLED=false` is still prod default** | Reviewer 5 | Tier 2 #8 lands ZERO picks until env var flipped |
| **`mlb_best_bets_exporter.py:227` silent bug** — returns `'home': bool(row.get('is_home'))` but SELECT never projects `is_home`. Every pick shows home=False | Reviewer 5 | Trivial fix, ship in Tier 1 |

---

## Statistical reality check (Reviewer 1 — Wilson 95% CIs)

| # | Item | N | Point HR | Wilson 95% CI | Verdict |
|---|------|---|----------|---------------|---------|
| T1.1 | mid-archetype OVER block | 7 | 14.3% | **[2.6%, 51.3%]** | WAIT |
| T2.8a | book_disagree_under @ std≥0.65 | 67 | 61.2% | [49.3%, 71.7%] | SHADOW |
| T2.8b | book_disagree_under @ std≥0.75 | 35 | 71.4% | **[54.7%, 83.8%]** | SHADOW |
| T2.9a | line_drop_over | 21 | 57.1% | [36.1%, 76.2%] | WAIT |
| T2.9b | line_drop_under | 13 | 61.5% | [35.5%, 82.3%] | WAIT |
| T3.15 | team_quick_hook_over | 40 | 72.5% | [57.2%, 83.4%] | SHADOW |

**Family-wise error rate from 15 parallel hypothesis families at α=0.05: ~54%.** At least one Tier 2/3 finding is statistically expected to be a false positive.

**Hard rule (Reviewer 1):** "No new MLB filter ships at N<100. No new MLB signal graduates from shadow at Wilson lower bound <55%."

---

## Recommended PR sequence (Reviewer 2 corrected)

| PR | Items | Constraint |
|----|-------|-----------|
| **PR 1 (1 day) — Plumbing + safety net** | T1.3 anchor + T1.6 demote + T2.13 weekly-retrain CF (with caps) + NEW: MLB edge-based auto-halt + `is_home` exporter fix | **#1 filter + retrain MUST NOT ship together** (attribution-killer) |
| **PR 2 (1 day) — Feature contract audit** | T1.4 splits + T1.5 lineup + T2.12 f18/f19 — gated on verifying upstream data exists | If `bdl_pitcher_splits` is dead, drop T1.4 |
| **PR 3 (1 day) — Signal additions** | T2.8 book_disagree_under (SHADOW) + T2.9 line_drop_* (SHADOW, opening_line loader) + T3.15 team_quick_hook (SHADOW) | All shadow-only with explicit graduation gates |
| **PR 4 (1-2 days, separate week) — Statcast** | T2.10 backfill `statcast_pitcher_game_stats` + `pitcher_arsenal_summary`. **Verify HR delta on N≥20 graded picks before retrain** | Once stable, retrain to take advantage |
| **PR 5 (separate week, ≥14 days after PR 1)** | T1.1 mid-archetype filter (SHADOW) + T1.2 umpire (real version) | Wait ≥14 days so PR 1's filter has graded N≥30 for attribution |
| **PR 6 (conditional, weeks later)** | T3.14a per-pitcher dedup in `mlb_best_bets_exporter.py` (ship + verify) → T3.14b LightGBM v1 shadow enable | Reject if r>0.85 with catboost_v2 |

---

## Open validation questions

1. **Did Session 524 retrain actually fix the mid-archetype high-K bias?** Direction flipped (signed_err +0.82 → -1.4) but N=2 post-retrain. Re-check at N≥30. T1.1 filter is reversible safety net regardless.
2. **`ballpark_k_factor` model membership** — **CONFIRMED in 36-feature contract** at `catboost_v2_regressor_predictor.py:34` (Reviewer 2 verified). Original "verify" item dropped.
3. **Whether T1.2 umpire and T2.10 Statcast plumbing fixes actually move HR** — measurable within 4-6 weeks after deploy.

---

## References

### Agent investigations (this session, 2026-05-11)
- 15 original investigation agents (dead features re-validation, archetype bias, edge curve, book disagreement, bottom-up K, training window, multi-model fleet, calendar effects, weather/park, umpire, statcast, recent form, catcher framing, opener/hook, line movement)
- 8 reviewer agents (statistical rigor, engineering risk, effort/impact, NBA pattern skeptic, devil's advocate, claim verification, OOS overfit, strategic)
- 1 fresh reviewer integrated above

### Key files

**Training:** `scripts/mlb/training/train_regressor_v2.py:141` (anchor fix), `scripts/mlb/training/walk_forward_simulation.py` (replay infra)

**Predictions:** `predictions/mlb/prediction_systems/catboost_v2_regressor_predictor.py:29-48` (canonical 36-feature contract), `predictions/mlb/supplemental_loader.py:120-162` (opening_line gap, weather load)

**Precompute:** `data_processors/precompute/mlb/pitcher_features_processor.py:303` (`_get_pitcher_splits` stub), `:406` (umpire table-name fix), `:615-618` (ballpark_k_factor — confirmed wired)

**Publishing:** `data_processors/publishing/mlb/mlb_best_bets_exporter.py:227` (silent is_home bug), `mlb_pitcher_exporter.py:98-110` (history sidecar)

**Signals:** `ml/signals/mlb/signals.py:288` (LineMovementOverSignal reads `opening_line` that's never set), `:377` and `:1277` (catcher framing shadow signals — source dead)

**Regime/halt:** NBA template `ml/regime_context.py` (port to MLB), `regime_context.py` edge-halt logic (port to `mlb_regime_context.py`)
