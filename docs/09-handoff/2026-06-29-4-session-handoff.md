# Session Handoff — 2026-06-29 (Session 4)

**Branch:** main
**State:** Off-season — halt active, no live picks until ~Oct 2026
**Session commits:** `bc9a44ec` → `eb4dfd10` (6 commits, all pushed to origin)
**Picking up from:** `docs/09-handoff/2026-06-29-3-session-handoff.md`

---

## Context for the next session

This was a build/cleanup session, not research. We worked through a prioritized off-season todo list derived from the last three sessions of research. 5 of 6 items are complete. The one remaining item (narrative forward-collection scraper) is low urgency — season doesn't open until October.

The system is now in a clean pre-season state. Everything staged is in SHADOW (zero pick impact). The only live change is a new active block filter (`clv_diverge_under_block`) which will suppress UNDER picks where the DK line dropped ≥ 0.5 intraday. This is appropriate behavior.

**Do not re-litigate settled research.** The major off-season research questions are resolved. See MEMORY.md and `docs/09-handoff/2026-06-23-*` / `2026-06-27-*` for the full findings. The summary: UNDER-only edge is durable, OVER layer was 2025-26 anomaly, features are done (R²≈0 from error decomposition), CLV is the next live lever.

---

## What was built this session

### 1. `line_converging_under` CLV live gate

**The highest-value build of the off-season.** Commit `bc9a44ec`.

**Background:** CLV Phase 2 research (Session 3, `docs/09-handoff/2026-06-29-3-session-handoff.md`) validated that at T-3h, UNDER picks where the DK line moved WITH the pick (rose ≥ 0.5) hit at 62.4% vs 46.6% when the line moved against (dropped ≥ 0.5). p=5e-26, N=1,155 from 2025-26 true-close snapshots. The confirmed live rule: "drop a pick if by tip the close moved ≥ 0.5 against it."

**What was built — two wires:**

**Wire 1 — positive shadow signal** (`ml/signals/line_converging_under.py`):
- Fires: UNDER + `prediction.get('dk_line_move_direction') >= 0.5`
- Returns: `qualifies=True, confidence=0.65`
- Status: in `SHADOW_SIGNALS` (aggregator.py line ~175) → zero pick impact, tracks to `pick_signal_tags`
- Smoke test: `line_converging_under.evaluate({'recommendation': 'UNDER', 'dk_line_move_direction': 0.5})` → qualifies=True ✅

**Wire 2 — active block filter** (`clv_diverge_under_block` inline in `ml/signals/aggregator.py`):
- Fires: UNDER + `float(pred.get('dk_line_move_direction', 0)) <= -0.5`
- Effect: `continue` (blocks the pick from best bets)
- Records to `best_bets_filtered_picks` via `_record_filtered()` for CF HR tracking
- Has `_runtime_demoted` guard — can be demoted to observation at runtime without code deploy
- Location: after the `line_dropped_under` filter block, around line 909 in aggregator.py

**What `dk_line_move_direction` is:** Computed in `ml/signals/supplemental_data.py` as the `dk_line_movement` CTE: `closing_line - opening_line` from DK bookmaker snapshots where `minutes_before_tipoff >= 0`. Positive = line rose. Negative = line dropped. Already on every prediction dict at signal evaluation time — no new scraper needed.

**Prior art to be aware of:** `ml/signals/closing_line_value.py` contains `PositiveCLVUnderSignal` — exact same concept, removed Session 514 for 41.4% BB HR. Why this is different: that signal used generic full-day CLV across all seasons (thin intraday snapshot coverage pre-2025-26). This one is specifically validated at T-3h on the 2025-26 season which had sufficient intraday snapshot density. Don't conflate them.

**The one remaining infrastructure gap — T-3h scheduler:** The Phase 6 best-bets export currently runs at 1 PM ET (~T-6h for a 7:30 PM tip). For the CLV gate to use the T-3h snapshot as "closing line," the export needs to re-run at ~4:30 PM ET. To add this: create a Cloud Scheduler job at `30 16 * * *` (4:30 PM ET = UTC 20:30) that publishes `{"export_types": ["signal-best-bets"], "target_date": "today"}` to the Phase 6 Pub/Sub trigger. No code change to the exporter — it already re-queries on each invocation and the `dk_line_movement` CTE picks up the latest available snapshot as "closing." Without this, the gate still works (uses the ~noon snapshot) but is less precise.

**Promotion gates:**
- Positive signal (`line_converging_under`): promote to `UNDER_SIGNAL_WEIGHTS` at weight ~1.5 after live N≥30 at HR≥60% in 2026-27
- Block filter (`clv_diverge_under_block`): monitor CF HR — if CF HR climbs above 55% (meaning we're blocking winners), add the filter name to `self._runtime_demoted` in the aggregator instance or demote via the standard CF HR mechanism

---

### 2. Scraper audit — three dead data sources

**Commit:** `679241db`

Three scrapers were active in the pipeline, running daily, but producing empty/null/zero data.

#### `covers_referee_stats` — code bug (wrong URL)

**File:** `scrapers/external/covers_referee_stats.py`

**Root cause:** `set_url()` was building `https://www.covers.com/sport/basketball/nba/referees/statistics/{season}` — this path does not exist. The correct URL (in the scraper inventory) is `https://www.covers.com/sport/basketball/nba/referee-stats` (no season in path, covers.com shows current season automatically).

**Fix:** Changed `set_url()` to hardcode the correct path. Season derivation logic in `set_additional_opts()` was left in place (still used for logging and data tagging), just not inserted into the URL.

**Why data was NULL:** The scraper was hitting the wrong URL, probably getting a 404 or a redirect to a page with different HTML structure. The table parser found no matching tables, so `referees` list was empty and the processor wrote rows with all numeric fields as NULL.

**Still needs live verification:** We can't verify the fix is correct without hitting covers.com — Cloud IPs may be blocked or the page structure may have changed again since March. Test at season open: run `python scrapers/external/covers_referee_stats.py --date <today> --debug` and check that referee rows with O/U stats are returned.

---

#### `nba_tracking_stats` — code bug (wrong endpoint)

**File:** `scrapers/external/nba_tracking_stats.py`

**Root cause:** The scraper called `leaguedashplayerstats?MeasureType=Usage`, which returns usage percentage breakdowns (USG_PCT, PCT_FGA_2PT, PCT_FGA_3PT, etc.). It does NOT return `TOUCHES`, `DRIVES`, `CATCH_SHOOT_FGA`, or `PAINT_TOUCHES`. Those come from a completely different endpoint family: `leaguedashptstats?PtMeasureType=...`. Because the column names (`TOUCHES`, `DRIVES`, etc.) didn't exist in the response, `_get("TOUCHES", 0)` returned the default `0` for every player. The scraper appeared to succeed (no exceptions, 546 players written) but silently wrote zeros for all tracking columns.

**Fix:** Significant refactor. The scraper now:
1. Calls `leaguedashptstats` four times with different `PtMeasureType` values: `Possessions`, `Drives`, `CatchShoot`, `PaintTouch`
2. Also calls `leaguedashplayerstats?MeasureType=Usage` for `USG_PCT`, `PACE`, base player identity
3. Stores all responses in `self.decoded_data` as a dict keyed by measure type
4. `validate_download_data()` now validates each key in the dict
5. `transform_data()` parses each result set into `{player_id: {col: val}}` dicts, then merges all on PLAYER_ID before building player records
6. Old `_extract_player_record(row, col_idx)` replaced by `_extract_player_record_from_dict(d)` which reads from the merged dict

Both the nba_api path (`_fetch_all_via_nba_api`) and HTTP fallback path (`_fetch_all_via_http`) were updated. The nba_api path tries to import `LeagueDashPtStats` — if it's not available in the installed nba_api version, it falls back to HTTP for the pt_stats calls.

**Column mapping after fix:**
- `touches`, `front_ct_touches`, `time_of_poss`, `avg_drib_per_touch` ← PtMeasureType=Possessions
- `drives`, `drive_pts`, `drive_fga`, `drive_fg_pct` ← PtMeasureType=Drives
- `catch_shoot_fga`, `catch_shoot_fg_pct` ← PtMeasureType=CatchShoot
- `paint_touches`, `paint_touch_fga`, `paint_touch_fg_pct` ← PtMeasureType=PaintTouch
- `usage_pct`, `pace`, `poss` ← MeasureType=Usage (leaguedashplayerstats)

**Still needs live verification:** stats.nba.com blocks Cloud IPs — the scraper uses proxy infrastructure from ScraperBase. It may still timeout/block. If it does, the `nba_api` library path with proxy kwarg is the preferred approach. Test at season open.

---

#### `vsin_betting_splits` — operational gap (code is correct)

**File:** `scrapers/external/vsin_betting_splits.py`

**Root cause:** NOT a code bug. The Session 406 parser fix (adding `recursive=False` to the freezetable div search) is present and correct. Data simply stopped after 2026-03-28 — either the Cloud Run scheduler job stopped firing, or VSiN updated their HTML class names after March.

**Fix:** Added a diagnostic checklist comment in the file docstring. No code change.

**At 2026-27 season open — checklist:**
1. Check the Cloud Run scheduler for this scraper is enabled and has fired recently
2. Run manually: `python scrapers/external/vsin_betting_splits.py --date <today> --debug`
3. If 0 games parsed: run with `--group capture` to dump raw HTML to `/tmp/raw_vsin_betting_splits_<date>.html`
4. Inspect HTML: look for `txt-color-vsinred` links (team names) — if that CSS class changed, update `_parse_game_row()` line ~220 in the scraper

---

### 3. Regime-conditional promotion gate for `downtrend_under` / `mean_reversion_under`

**Commit:** `46458a49`

**Why this matters:** Both signals were part of the March 2026 collapse (Cause 2 in the root cause analysis). `downtrend_under` went 2/18 (11.1% HR) and `mean_reversion_under` went 0/8 (0.0%) — both during the TIGHT market of early March 2026. They are correctly in `SHADOW_SIGNALS` now. But the code had no guard preventing someone from reading "63.3% 5-season HR!" in the signal file and promoting it mid-season, including during a TIGHT market.

**Fix applied in two places:**

`shared/registry/signals.yaml` — added `promotion_gate` field to each entry:
```yaml
- tag: downtrend_under
  promotion_gate: "LOOSE market only (vegas_mae_7d >= 4.5). DO NOT PROMOTE in TIGHT market
    — went 11.1% HR (2/18) in March 2026 TIGHT conditions. Requires N>=30 at HR>=58%
    AND market_regime=LOOSE before adding to UNDER_SIGNAL_WEIGHTS."
```

`ml/signals/aggregator.py` — added `⚠️ REGIME-GATED` comment block immediately after each signal's entry in `SHADOW_SIGNALS`:
```python
'mean_reversion_under',
# ⚠️  REGIME-GATED (2026-06-29): DO NOT PROMOTE without LOOSE market (vegas_mae_7d >= 4.5).
# Went 0.0% HR (0-8) in March 2026 TIGHT conditions. See signals.yaml promotion_gate field.
```

**The rule:** Both signals may be profitable in LOOSE markets (vegas_mae_7d ≥ 4.5) where lines are moving freely and UNDER value is real. In TIGHT markets (vegas_mae_7d < 4.5), these signals fire on picks that are already underwater and make things catastrophically worse. They MUST NOT be promoted until there is a full season of live data under LOOSE conditions showing sustained HR ≥ 58% (downtrend) or ≥ 55% (mean_reversion).

---

### 4. `high_line_under` shadow signal

**Commit:** `7db333c9`

**Discovery background:** Passed formal discovery gate (pre-registered, BH-FDR corrected): line ≥ 25, UNDER: 59.9% HR, above breakeven 5/5 seasons, p=0.0007.

**Overlap finding (investigated before wiring):** `star_line_under` in `ml/signals/star_line_under.py` has NO "star player" criterion despite its name. The actual code: UNDER + `line >= 25.0` + `edge >= 3.0 AND edge < 7.0`. That's it. No usage rate, no minutes, no player tier. So `high_line_under` (UNDER + `line >= 25`, no edge gate) is a **strict superset** of `star_line_under`.

**Implication:** The two signals measure the same underlying phenomenon. `star_line_under` is the edge-band-constrained version (which also performs worse because the edge band artificially excluded the full signal). `high_line_under` is the intended replacement. They should NOT both be active — if `high_line_under` graduates, retire `star_line_under`.

**Critical 2025-26 warning:** `star_line_under` is running 35.3% HR this season (N=17). The `line >= 25 UNDER` thesis is stressed in 2025-26 — the season where OVER was anomalously dominant may also be the season where star lines were NOT overpriced. Watch `high_line_under` live HR extremely carefully in 2026-27 before considering graduation. If it tracks similarly to `star_line_under`'s 35.3%, the entire `line >= 25 UNDER` thesis may be regime-dependent.

**Files changed:**
- `ml/signals/high_line_under.py` — new file, `line >= 25.0` gate, `confidence=0.65`
- `ml/signals/aggregator.py` — added to `SHADOW_SIGNALS`
- `ml/signals/registry.py` — registered `HighLineUnderSignal`
- `shared/registry/signals.yaml` — added entry with `promotion_gate` and DO NOT co-promote note
- `ml/signals/star_line_under.py` — updated docstring with 2025-26 decay warning and overlap documentation

**Promotion gate:** N≥30 at HR≥58% live 2026-27. Stratify by edge band before graduating — the 59.9% aggregate may not hold at all edge levels. If it graduates, edit `star_line_under`'s `status` in signals.yaml to `removed` and remove it from `SHADOW_SIGNALS`.

---

### 5. `over_decay_watch.py` confirmed and documented

**Commit:** `f849ed02`

Script is at `bin/monitoring/over_decay_watch.py`. Read-only (prints report, writes nothing). Syntax clean, smoke-tested Session 3. Watches 5 demoted OVER signals: `fast_pace_over`, `cold_3pt_over`, `line_rising_over`, `book_disagree_over`, `b2b_boost_over`.

Logic: queries `pick_signal_tags` ⋈ `prediction_accuracy` for live 2026-27 OVER picks carrying each watched tag. Wilson CI verdict: KEEP if HR ≥ 58% at N ≥ 30 (CI lo > 53.5%), DEMOTE if HR < 52.4% or CI hi < 58%, WATCH if marginal. Each signal is **presumed fragile** — must EARN a keep verdict.

Added to `CLAUDE.md` monitoring section under `## Monitoring`.

**Run from ~Dec 2026** once enough live picks have accrued (N≥30 per signal):
```bash
PYTHONPATH=. python bin/monitoring/over_decay_watch.py
# Or with explicit window:
PYTHONPATH=. python bin/monitoring/over_decay_watch.py --season-start 2026-10-20 --min-n 30 --keep-threshold 58
```

---

## Complete current shadow signal inventory

All signals in `SHADOW_SIGNALS` as of this session. Zero pick impact — fire, record to `pick_signal_tags`, excluded from `real_sc`.

### Signals likely to graduate 2026-27 (strong backtests, just need live N)

| Signal | 5-season HR | Promotion gate | Key risk |
|--------|------------|---------------|---------|
| `b2b_fatigue_under` | 63.2% (5/5) | N≥30, HR≥58% | `is_b2b` feature only populated in 2025-26; pre-2025 data gap may mean N accrues slowly |
| `ft_anomaly_under` | 63.3% (N=278) | N≥30, HR≥60% | FTA CV ≥ 0.5 gate may fire rarely |
| `whole_line_precision` | +10-20pp vs half-lines (all 5 seasons) | UNDER: N≥30 HR≥62%. OVER: N≥50 HR≥70% | OVER BB evidence weak (+2pp, not sig); UNDER is the real finding |
| `line_converging_under` | 62.4% vs 46.6% disagree (2025-26) | N≥30, HR≥60% | Single-season; T-3h precision needs scheduler job |

### Signals needing careful live watch (mixed signals or recency concerns)

| Signal | Status | Concern |
|--------|--------|---------|
| `national_tv_under` | 54.7% (5/5), post-hoc directional flip | Flip from OVER → UNDER was post-hoc; check overlap with `star_line_under` at season open |
| `slow_pace_under` | 56.6% (N=777, 5-season) | Opponent pace data may lag; fire rate check |
| `star_line_under` | 57.6% (5-season) BUT **35.3% live 2025-26 (N=17)** | DO NOT GRADUATE. Same thesis as `high_line_under`. Decaying. |
| `high_line_under` | 59.9% (5/5) | Same thesis as `star_line_under` — which is decaying this season |
| `sharp_consensus_under` | 69.3% (5-season) BUT 0-14 BB in 2025-26 (12+ books) | Threshold calibrated for 4-5 book regime; completely different in 12+ book regime |
| `book_disagree_under` | Direction-specific, accumulating | In UNDER_SIGNAL_WEIGHTS (weight 1.5) but excluded from real_sc via SHADOW_SIGNALS |

### Regime-gated (LOOSE market only — DO NOT promote in TIGHT)

| Signal | March 2026 HR | Promotion gate |
|--------|--------------|---------------|
| `downtrend_under` | **11.1% (2/18)** in TIGHT market | LOOSE (vegas_mae_7d ≥ 4.5) + N≥30 + HR≥58% |
| `mean_reversion_under` | **0.0% (0/8)** in TIGHT market | LOOSE + N≥30 + HR≥55% |

### Demoted OVER layer (must earn back via over_decay_watch.py)

| Signal | Prior 4-season HR | 2025-26 HR | Fragility verdict |
|--------|------------------|-----------|------------------|
| `cold_3pt_over` | 45.0% (sub-BE 4/4) | 74.1% | STRONGEST demote candidate |
| `book_disagree_over` | 50.0% (no edge) | Unknown | N=18 total cross-season — unproven |
| `b2b_boost_over` | 51.0% (2/5 > BE) | 70%+ | b2b pair was backwards; UNDER is the durable side |
| `fast_pace_over` | 53.0% (58/47/49/59) | 71.5% | Consistent with OVER anomaly |
| `line_rising_over` | 52.0% (breakeven) | 81.8% | 2025-26 anomaly only (p<0.001) |

### Other shadows (miscellaneous)

`projection_consensus_under`, `usage_surge_over`, `career_matchup_over`, `consistent_scorer_over`, `over_trend_over`, `minutes_load_over`, `sharp_money_under`, `dvp_favorable_over`, `day_of_week_under`, `over_streak_reversion_under`, `star_favorite_under`, `starter_away_overtrend_under`, `sharp_book_lean_over`, `extended_rest_under`, `quantile_floor_over`

---

## Active UNDER signal weights (production)

From `UNDER_SIGNAL_WEIGHTS` in aggregator.py — these count toward `real_sc` and composite score ranking:

```
sharp_line_drop_under:    2.5  # 87.5% HR (N=8)
volatile_starter_under:   2.0  # Cross-season +11.1pp lift (best structural UNDER signal)
hot_3pt_under:            2.5  # 62.5% HR (N=670) — strongest overall
line_drifted_down_under:  2.0  # 59.8% HR (N=336)
bench_under:              2.0  # 76.9% HR
book_disagree_under:      1.5  # Direction-specific; in shadow so no real_sc contribution
home_under:               1.0  # 63.9% backtest HR, restored Session 495
book_disagreement:        1.0  # Reduced 2.5→1.0 (47.4% 7d HR)
```

Quantile ceiling UNDER is in UNDER_SIGNAL_WEIGHTS but excluded from real_sc via SHADOW_SIGNALS (N=10 first test, MultiQuantile models only).

---

## Active negative filters (production — can block picks)

From inline filter blocks in `aggregator.py`:

| Filter | Condition | CF HR target | Notes |
|--------|-----------|-------------|-------|
| `line_jumped_under_obs` | UNDER + `prop_line_delta >= 2.0` | CF HR 41.4% (N=58) — confirmed blocks losers | BettingPros delta (current vs prev game line), not intraday |
| `line_dropped_under` | UNDER + `prop_line_delta <= -2.0` | CF HR 37.5% (N=8) — blocks losers | Same source |
| `clv_diverge_under_block` | UNDER + `dk_line_move_direction <= -0.5` | NEW — monitor CF HR | DK intraday (closing - opening); blocks if line dropped ≥ 0.5 on game day |
| `line_anomaly_extreme_drop` | OVER + line dropped ≥ 40% OR ≥ 6 pts vs prev game | Safety net | Catches injury/restriction information asymmetry |
| `opponent_under_block` | UNDER + opponent in UNDER_TOXIC_OPPONENTS | CF HR 52.4% (N=21) — DEMOTED to observation | Session 488 demotion |
| `cold_fg_under` | UNDER + FG% cold | Active block | Promoted Session 462 |
| `cold_3pt_under` | UNDER + 3PT cold | Active block | Promoted Session 462 |
| `over_line_rose_heavy` | OVER + line rose ≥ 1.0 | Active block | Promoted Session 469 |
| `high_spread_over_would_block` | Various | OBSERVATION ONLY | N too small for active block |

---

## Open items for next session

### Immediate (before October)

**1. Narrative forward-collection scraper (Task 6 — not started)**

Build before Oct 2026. Two entry points:
- `nbainjuries` Python package — injury-report snapshots at game-day resolution. Simple: `pip install nbainjuries`, scrape daily, write to GCS and BigQuery as `nba_raw.nba_injury_snapshots`
- ESPN hidden API — probe `https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news` for game-day news blurbs. Forward-collect only — no signal yet.

The signal payoff is deferred to 2027+ (need 1 season of forward-collected data to backtest). The point is to start the clock now.

**2. T-3h Cloud Scheduler job for `line_converging_under` precision**

Add a Cloud Scheduler job that fires at 4:30 PM ET on NBA game days to re-trigger the Phase 6 best-bets export. This gives `line_converging_under` and `clv_diverge_under_block` T-3h precision instead of ~T-6h (noon) precision.

```
Schedule: 30 20 * * *  (UTC = 4:30 PM ET)
Target:   Pub/Sub topic nba-phase6-export-trigger (or equivalent)
Message:  {"export_types": ["signal-best-bets"], "target_date": "today"}
```

No code change to the exporter — it already re-queries on each invocation. The `dk_line_movement` CTE uses `MIN(rn_desc=1)` which picks the latest available snapshot at query time.

### At season open (October 2026)

3. **Verify scraper fixes work live:** covers_referee_stats URL, nba_tracking_stats endpoint, vsin_betting_splits scheduler
4. **Check whole-number line presence** at DraftKings/FanDuel in October — if they use whole-number lines, `whole_line_precision` is a major practical edge
5. **Watch `b2b_fatigue_under` and `national_tv_under` fire rates** — check that `is_b2b` is populated and that national TV games appear correctly
6. **First week HR check** — look at `high_line_under` vs `star_line_under` early to see if the `line >= 25 UNDER` thesis is recovering or still stressed

### From December 2026

7. **Run `over_decay_watch.py`** once each demoted OVER signal has N≥30 live picks
8. **CLV live gate confirm** — once `line_converging_under` has N≥30, evaluate agree vs disagree split in 2026-27 to confirm the T-3h effect cross-season

---

## Key decisions NOT to re-litigate

These were resolved with multi-agent research and should not be re-opened without a full season of contradicting live data:

- **OVER layer is 2025-26-overfit** — fast_pace_over / cold_3pt_over / line_rising_over / book_disagree_over / b2b_boost_over are in shadow. Do not re-promote based on recency or gut feel. Use over_decay_watch.py.
- **Features are done** — error decomposition showed R²≈0 for new features. Edge is in selection/signals, not accuracy. No new model features.
- **downtrend_under and mean_reversion_under are REGIME-GATED** — don't promote without LOOSE market.
- **high_line_under replaces star_line_under** — don't graduate both.
- **CLV is not the old positive_clv_under** — the ancestor was removed for 41.4% HR. The new gate is validated differently (T-3h, direction-agreement filter, 2025-26 true-close snapshots).
- **March 2026 collapse is fully diagnosed** — three causes documented (TIGHT market, bad signals active, algorithm churn). All major fixes are in place. Don't confuse this with model staleness or feature drift.

---

## Commits this session

```
eb4dfd10  docs: session 4 handoff
f849ed02  docs: add over_decay_watch.py to monitoring section + season-open checklist
7db333c9  feat: high_line_under shadow signal — edge-ungated replacement for star_line_under
46458a49  docs: regime-conditional promotion gate for downtrend_under / mean_reversion_under
679241db  fix: scraper audit — covers URL, tracking stats endpoint, vsin diagnostic
bc9a44ec  feat: line_converging_under CLV live gate — shadow signal + active block filter
```

All on main, pushed to origin. Auto-deploy will run for changed services.
