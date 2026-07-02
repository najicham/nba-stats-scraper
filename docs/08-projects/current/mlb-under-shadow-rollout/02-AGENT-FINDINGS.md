# Agent findings — MLB UNDER investigation

**Investigation date:** 2026-05-12
**Method:** 6 parallel general-purpose agents, each briefed self-contained on a distinct lane. Each capped at 400 words and instructed to be opinionated. Reports synthesized into `01-PLAN.md`.

This file preserves the auditable trail of what each agent claimed and what evidence backed it.

---

## Agent 1 — UNDER historical performance reality check

**Critical finding:** Walk-forward 2024/2025 UNDER claims in memory (52.4% / 48.1% HR) **cannot be reproduced from BigQuery**. They live only in `scripts/mlb/training/walk_forward_simulation.py` JSON output, never written to a BQ table. The only auditable UNDER history is 2026 live data.

**Verified 2026 live UNDER (from `mlb_predictions.prediction_accuracy`):**

| Window | N | HR |
|---|---|---|
| 2026 UNDER overall | 204 | 53.4% |
| 2026 OVER overall | 348 | 53.7% |
| April 2026 | 138 | 59.4% |
| **May 2026** | **66** | **40.9%** |
| Week of May 4 | 40 | 40.0% |
| Week of May 11 | 3 | **0.0% (0/3)** |

**The collapse is regime-wide, not slice-specific.** Every breakdown holds:
- Edge 0.5-1.0 (96% of volume): April 56.9% → May 40.9%
- Predicted-K mid/low: April ~60% → May ~45%
- Home and away both collapsed
- Only winning subset is edge >= 1.0 (N=8, 8-0, 100%) — too small, all April, variance

**Filter subset analysis:** No subset with N >= 100 clears 56% HR. Best qualifying: line 5.0-6.5 UNDER (N=53, 56.6%) — below the N=100 floor. Edge-0.5-1.0 UNDERs combined: N=196, 51.5%.

**Verdict:** Stay disabled. Live UNDER is currently coin-flip-trending-loser. Shadow it for >=30 days at >=56% HR before considering live flip. Reproduce walk-forward claims into BQ first so future decisions are auditable.

**What this rules out:** Option (c) ship-live-with-filters. There is no high-HR subset to filter down to.

---

## Agent 2 — Shadow UNDER design

**Recommended approach:** New dedicated BQ table `mlb_predictions.shadow_under_picks` (later overruled — see Agent 6).

**Code diff sketch — `ml/signals/mlb/best_bets_exporter.py`:**
- Add `UNDER_SHADOW_ENABLED` env var distinct from `UNDER_ENABLED`
- Always evaluate UNDER when shadow is on; route to shadow table when publish is off
- ~80 LOC patch touching lines 287, 306-329, 642-647, plus new write method
- Zero changes needed to `data_processors/publishing/mlb/mlb_best_bets_exporter.py` — it only reads `signal_best_bets_picks`

**Critical pre-flip code work uncovered:**
- `ml/analysis/mlb_model_performance.py:85-98` hardcodes `recommendation='OVER'` in all 3 windows. Without un-hardcoding, shadow UNDER perf won't appear in `model_performance_daily`.
- `ml/analysis/mlb_league_macro.py:324` has the same issue for `pct_over`.

**Graduation gate (proposed):**
- N >= 60 graded picks (45-day window, 3-5 picks/day × 60% slate density × void rate)
- HR >= 56.0%
- No monthly bucket below 50% (min N=10/month)
- Vig-adjusted ROI >= +3.0%

**Why 45 days not 30:** MLB cadence is weekday-heavy; 30 days can miss full slate variety. 45 × ~3 picks/day ≈ 90 candidates, expect 60+ graded after voids.

---

## Agent 3 — Why is OVER bias structural

**Bias magnitude (BQ 2026, N=552 graded predictions):**
- Average predicted 5.12 K, average actual 5.16 K → **raw bias -0.04 K** (model well-calibrated absolutely)
- Predicted OVER 60.0% / Actual OVER 51.1% → **8.9pp directional gap**
- **Conditional bias (picked subset):**
  - OVER picks: +0.19 K bias (pred 5.20, actual 5.00)
  - UNDER picks: **-0.45 K bias** (pred 4.99, actual 5.44)
- Edge asymmetry: avg OVER edge 0.53 K vs avg UNDER edge 0.38 K. **Lines sit ~0.1-0.2 K below model expectation**, so even a near-unbiased regressor leans OVER.

**Top 5 features driving OVER tilt (from deployed model metadata):**
1. `f32_line_level` (33.7%) — model anchors heavily to line; low lines → mechanical OVER lean
2. `f72_fip` (11.7%) — embeds 2024-25 strikeout-era levels
3. `f19b_season_csw_pct` (8.3%) — survivorship bias (only games started)
4. `f15_opponent_team_k_rate` (3.85%) — embeds historical high-K pace
5. `f44_over_implied_prob` (3.65%) — market itself prices OVER as slightly likelier (vig pulls toward OVER)

**Loss function:** `RMSE` at `scripts/mlb/training/train_regressor_v2.py:83`. Quadratically punishes K blowups (10-K outliers) → model defends against upside tail by anchoring slightly above the median.

**Verdict:** Re-calibrate the regressor, don't train separate UNDER model.
- 552 graded picks / 204 UNDER samples too thin for a credible classifier
- A simple "subtract 0.4 K" shift would **make OVER picks worse without helping UNDER**, because the bias is direction-conditional and opposite-sign
- Concrete fix: change `train_regressor_v2.py:83` from `'RMSE'` to `'Quantile:alpha=0.5'` (MAE-equivalent). Walk-forward expectation: OVER-prediction rate drops 60% → 53-55%, UNDER edge >= 0.75 picks become statistically available

**Deferred to Phase 3** — model swap has its own governance gates; do it after shadow has 30d data so we can A/B.

---

## Agent 4 — Signal coverage for UNDER

**Critical finding:** UNDER signal pipeline is hollow. `UNDER_MIN_SIGNALS=3` is **structurally unreachable** today.

**Current UNDER signal inventory:**

| Signal | Status | In `UNDER_SIGNAL_WEIGHTS`? | Reality |
|---|---|---|---|
| `velocity_drop_under` | ACTIVE | YES (2.0) | **Dead** — `velocity_change` never populated in supplemental |
| `short_rest_under` | ACTIVE | YES (1.5) | Works |
| `high_variance_under` | ACTIVE | YES (1.5) | Works |
| `weather_cold_under` | SHADOW | YES (1.0) ← BUG | Won't fire (shadow) |
| `pitch_count_limit_under` | SHADOW | YES (2.0) ← BUG | Field never populated. Dead. |
| `short_starter_under` | SHADOW | no | Ready to promote |
| `k_rate_reversion_under` | SHADOW | no | Ready to promote — NBA analogue 62.5% HR |
| `cumulative_arm_stress_under` | SHADOW | no | Ready to promote |
| `rematch_familiarity_under` | SHADOW | no | Lower priority |
| `catcher_framing_poor_under` | SHADOW | no | Sup feed exists, low expected lift |
| `rest_workload_stress_under` | SHADOW | no | Subsumed by `cumulative_arm_stress_under` |
| `contact_specialist_under` | SHADOW | no | f71 z_contact_pct exists |

**Effective active UNDER signals = 2** (`short_rest_under`, `high_variance_under`). `UNDER_MIN_SIGNALS=3` cannot be reached.

**NBA vs MLB gap matrix (selected):**

| NBA signal | MLB equivalent? |
|---|---|
| `sharp_line_drop_under` (weight 2.5) | NO — `opening_line` never set in `supplemental_loader.py:120-162` |
| `book_disagreement` (1.0) | NO — `oa_std` not wired into MLB supplemental |
| `volatile_starter_under` (2.0) | EQUIVALENT — `high_variance_under` |
| `hot_3pt_under` (2.5) | EQUIVALENT in spirit — `k_rate_reversion_under` (shadow today) |
| `line_drifted_down_under` (2.0) | NO — same `opening_line` gap |

**Top 5 NEW signals to add (ranked):**

| Rank | Signal | Trigger | Cost |
|---|---|---|---|
| 1 | `k_rate_reversion_under` (promote) | Hot streak reversion | TRIVIAL — flip `is_shadow=False`, add to weights at 2.5 |
| 2 | `velocity_drop_under` (fix feed) | Wire `velocity_change` from `pitcher_rolling_statcast` | MEDIUM — 1-2h supplemental wiring |
| 3 | `book_disagree_under` (new) | `oa_std >= 0.65` (PLAN.md proposal) | MEDIUM — 2 days, needs `oa_std` plumbing |
| 4 | `short_starter_under` (promote) | `ip_avg_last_5 < 5.0` | TRIVIAL |
| 5 | `cumulative_arm_stress_under` (promote) | `pitch_count_avg >= 100 AND games_30d >= 6` | TRIVIAL |

**Demote/remove:**
- `pitch_count_limit_under` — REMOVE from weights (field never populated)
- `weather_cold_under` — REMOVE or promote (currently shadow + weighted = inconsistent)

**Pipeline implication:** Shadow rollout today produces zero useful data because every UNDER pick fails the signal gate silently. Phase 0 Step 1 must ship first.

---

## Agent 5 — Filter coverage for UNDER

**Filter inventory verified** (from `ml/signals/mlb/signals.py:528-709`):

| Filter | Direction blocked |
|---|---|
| `bullpen_game_skip` | BOTH |
| `il_return_skip` | BOTH |
| `pitch_count_cap_skip` | **OVER only** |
| `insufficient_data_skip` | BOTH |
| `pitcher_blacklist` | **OVER only** |
| `whole_line_over` | **OVER only** |

Memory's "all 6 OVER-targeted" was wrong — 3 bidirectional + 3 OVER-only. **Zero UNDER-targeted filters exist.**

**Worst 2025 UNDER archetypes** (edge >= 0.75, joined to `pitcher_game_summary`):

1. High line >= 7.0 + normal-form pitcher (k_avg_last_10 < 6.5): 47-53% HR (N=34)
2. Elite K/9 >= 9.5 in summer (Jul-Aug): 49-55% HR (N=83)
3. High line >= 7.0 + AWAY: 58.5% HR (N=41)
4. **Elite K/9 + line >= 7.0:** 65.2% HR 2025 vs **96.9%** HR 2024 — biggest cross-season collapse (-31.7pp)
5. Whole-line UNDER: N/A (current data has only half-line UNDERs at edge >= 0.75)

**Proposed UNDER filters (priority order):**

| Name | Trigger | Expected effect |
|---|---|---|
| `high_line_under_block` | UNDER + line >= 7.0 + edge < 1.5 | Blocks ~80/yr at ~62% HR |
| `elite_k9_under_block` | UNDER + season_k_per_9 >= 9.5 + line >= 6.5 | Blocks 100-150/yr at ~65% HR — strongest cross-season signal |
| `summer_elite_under_block` | UNDER + Jul-Aug + k_per_9 >= 9.5 | Calendar-fragile — make observation-only first |
| `away_high_line_under_block` | UNDER + away + line >= 7.0 | Blocks ~40/yr at 58% — most surgical |
| `pitcher_blacklist_under` | Symmetric to OVER blacklist for >70% OVER-hit pitchers | Future work |

**NBA filters worth porting:** `high_book_std_under_block` (needs `oa_std` plumbing — Phase 3+).

**Recommendation in plan:** Ship filters 1+2 as ACTIVE in Phase 0 Step 2. Skip 3 (calendar-fragile), defer 4+5.

---

## Agent 6 — Operations

**Shadow table verdict:** **Reuse `mlb_predictions.blacklist_shadow_picks`** (contradicts Agent 2's new-table proposal).
- Schema already fits (recommendation, edge, signal_tags, real_signal_count, would_be_selected, ultra_tier, prediction_correct, is_voided)
- Same DELETE-by-date dedup pattern already used in `_write_shadow_picks` (lines 1010-1035)
- Add a `shadow_reason` discriminator column rather than build new infrastructure

**Do NOT use** `shadow_mode_predictions` — that's for model-version comparison (v1.4 vs v1.6), wrong shape entirely.

**Alert pattern:**
- New CF: `bin/monitoring/mlb_under_shadow_monitor.py` (+ `cloud_functions/mlb_under_shadow_monitor/`)
- Scheduler: cron `30 14 * 3-10 *` (9:30 AM ET, March-October, post-grading)
- Triggers: 7d HR < 50% (N >= 14) OR no shadow UNDER picks 5+ consecutive days
- Slack: `#nba-alerts` via existing `mlb-alert-forwarder` CF
- Dedup: `shared/alerts/rate_limiter.py` + per-context GCS pattern `v1/admin/alerts/mlb-under-shadow-{trigger}.json` (24h dedup)

**Cost impact:**
- BQ rows: ~3 UNDER/day × 180 game days = ~540 rows/season. Negligible cost.
- CF runtime: zero delta. Regressor already predicts both directions; today they're filtered at `best_bets_exporter.py:317`. Signal eval already loops every signal regardless of direction (line 524). ~50ms extra ranking sort at most.
- Frontend volume: zero. `MAX_PICKS_PER_DAY=5` is shared between directions; UNDER competes with OVER for slots when live.

**Backfill viable:** `prediction_accuracy` has 204 graded MLB UNDER predictions since 2024-04-01. Fields are sufficient. Sketch: replay historical predictions, call `MLBBestBetsExporter._evaluate_shadow_picks()` with `UNDER_ENABLED=true` injected. ~3 minutes for full 2024-2025 history. Bootstraps shadow with N≈200 day-1 instead of waiting 60 days.

---

## Synthesis notes — where agents disagreed

| Question | Agent 2 | Agent 6 | Resolution in plan |
|---|---|---|---|
| Shadow table | New `shadow_under_picks` | Reuse `blacklist_shadow_picks` | **Agent 6** — less surface, schema fits, simpler grading |
| Graduation N | 60 | not specified | **Agent 2's 60** |

The disagreement is operational, not strategic. Both agreed on env-var separation, monitor cadence, and frontend impact.

---

## Risk factors surfaced

- **Agent 1's live regime collapse (40.9% HR in May)** is the strongest argument against shipping anything live in the next 30 days. Even after Phase 0 fixes ship, shadow data will be collected during this regime — the graduation gate should evaluate whether the fixes change the regime or just track it.
- **Agent 4's hollow pipeline** means without Phase 0 Step 1, shadow data is garbage in / garbage out.
- **Agent 3's RMSE loss function** is the root cause of the OVER bias. Until Phase 3 retrains with Quantile loss, UNDER picks will continue to be selection-biased toward pitchers who out-perform the line.
- **Walk-forward unreproducibility (Agent 1):** the 48.1% / -6.8% ROI figures that triggered the original disable cannot be audited. Future decisions should require walk-forward output to be written to BQ.
