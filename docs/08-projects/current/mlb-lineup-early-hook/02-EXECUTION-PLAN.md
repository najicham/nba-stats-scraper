# MLB Strikeout Project — Execution Plan

**Created:** 2026-05-20
**Status:** Approved — build in progress.
**The single ordered checklist.** Detail lives in `00-PROJECT-SPEC.md` (model) and
`01-DISCOVERY-HARNESS-SPEC.md` (discovery harness). This doc is "what to do next."

---

## Where we are (2026-05-21)

- **Phase 0 — DONE + VERIFIED.** MLB lineup capture was broken all of 2026 (night-game
  coverage ~0%, vs 100% in 2024/25). Fixed: two new scraper schedulers
  (`mlb-lineups-afternoon` 4pm ET, `mlb-lineups-overnight` 3am ET) + a dedup-guard fix
  (`SKIP_DEDUPLICATION` on `MlbLineupsProcessor`, commit `eb056db4`). Verified end-to-end.
- **Plan — DONE.** Two specs, four review rounds (8 + 15 + 25 + 25 agents). Core
  conclusion: the model already matches the market (MAE 1.83 vs 1.85); the **betting
  machinery** leaks the value (fake constant-sigmoid probability, selection layer buys
  losers at ranks 4–5, CLV unmeasurable). Fix the machinery first, add features second.
- **Build — IN PROGRESS.** `mlb_lineups` registered in `expected_outputs_planner`
  (`b03b228d`); `mlb_reference.pitcher_handedness` table built. **Stage 1.1 built +
  committed.** **Stage 1.4 framework built + RUN 1 done (2026-05-21)** — a 15-agent
  review caught a critical FanGraphs look-ahead leak (fixed: prior-season join across
  9 files + a `pitcher_game_summary` backfill) and that the replay harness still
  measured the pre-Stage-1.1 system; harness rewired leak-free. First 2025 backtest:
  the Poisson `p_over` is a *wash* vs the old sigmoid, and the model-market blend is
  not worth activating — a 20-run confirmation sweep (2 seasons × 5 seeds)
  verified both, seed variance near-zero. 7 commits, **none pushed**.

---

## The build sequence

Legend: `[x]` done · `[~]` in progress · `[ ]` todo.

### Wave 0 — no-regret prerequisites (no decision needed; build now)

| | Item | Effort | Notes |
|--|------|--------|-------|
| `[x]` | Register `mlb_lineups` in `expected_outputs_planner` | — | `b03b228d` (pushed) |
| `[x]` | Build `mlb_reference.pitcher_handedness` | — | 1,113 pitchers, L/R/S |
| `[ ]` | Deploy `mlb_freshness_checker` (daily scheduler; extend thresholds to `mlb_game_feed_pitches`, `statcast_pitcher_daily`) | Low | exists, never scheduled |
| `[ ]` | D1 — repoint code refs `mlb_game_feed` → `mlb_game_feed_pitches` | Low | `mlb_game_feed` is empty |
| `[ ]` | Rename project folder → `mlb-strikeout-model` | Trivial | cosmetic; leave a stub |

### Procurement — decide early (unblocks Stage 1.2 + harness book features)

| | Item | Cost | Notes |
|--|------|------|-------|
| `[ ]` | **Buy an odds feed** — SportsGameOdds or The Odds API (real closing lines, finer snapshots) | ~$99–200/mo | Replaces the closing-line-capture build; unblocks CLV. Needs an owner purchase decision. |
| `[ ]` | Confirm free sources: FanGraphs Stuff+ via `pybaseball`; Open-Meteo historical weather | $0 | Kills the Stuff+-proxy build (Stage 2-I) |

### Stage 1 — fix the betting machinery (THE CORE WORK)

| | Item | Effort | Gating |
|--|------|--------|--------|
| `[~]` | **1.1 — Poisson `P(over)` + model-market blend** | Med | **Built + committed; Stage-1.4-evaluated 2026-05-21.** Predictor emits `p_over = 1 − PoissonCDF(floor(line), λ)` and blends `λ` with the market line (`w` fit by `fit_blend_weight()`). **RUN-1 verdict:** the Poisson `p_over` is a *wash* vs the old sigmoid — keep it (principled), but it is **not** the "pure improvement" first claimed; re-examine the exporter `probability_cap` (tuned to the sigmoid). The **blend is not worth activating as fit-to-MAE** (0.6% MAE gain, hurts calibration, no betting win) — keep `w=1.0`, or refit `w` to ROI and require a betting win. The earlier "Poisson-loss retrain that activates the blend" plan is **superseded** — confirmed by a 20-run sweep (seed variance near-zero). Note: de-leaked, the model has **no real edge over the market** (2024 model MAE 1.787 > line 1.763) — betting value is the selection layer, not the model. |
| `[~]` | 1.4 — validation framework — calibration harness + leak-free replay built; RUN 1 + 20-run confirmation sweep done | Low–Med | gates everything after |
| `[ ]` | 1.3 — selection/staking fix (replace fixed top-5 with a quality gate; ranks 4–5 lose money today) | Low–Med | after 1.4 |
| `[ ]` | 1.2 — CLV measurement (populate `clv_*` from the bought feed) | Med | after the feed lands; **not on the critical path** |
| `[ ]` | 1.5 — monitoring (feature-coverage alerts; MLB Brier emitter) | Low–Med | with the above |

**First shippable result ≈ 1 week** (Wave 0 + Stage 1.1). Stage 1 complete ≈ 3–3.5 weeks.

### Stage 2 — strikeout features (only after Stage 1; each wave validated independently)

| | Wave | Features | Effort |
|--|------|----------|--------|
| `[ ]` | Wave 1 | A (opponent K% vs handedness — dispersion variant), C (velocity drop ×2), D (line movement) | Med |
| `[ ]` | Wave 2 | B (2-strike putaway), E (times-through-order), H (CSW%) — shared PA pipeline (`pitch_pa_facts`) | Med–High |
| `[ ]` | Wave 3 | F (umpire zone — needs D5 morning scrape), I (Stuff+ — *sourced free*, not built) | Med |
| `[ ]` | Any | G (opener flag + OVER suppression), J (park/weather), K (game script — needs D7) | Low–Med |

Each feature must beat the prior MLB dead-ends baseline (`mlb-2026-season-strategy/05-DEAD-ENDS.md`).

### Discovery harness — MVH (after Stage 1 produces a calibrated model)

| | Item | Effort |
|--|------|--------|
| `[ ]` | MVH = one script `bin/mlb/discover.py` — candidate registry + leak-safe backfill + multi-seed replay scorer + self-test | ~1–1.5 wk |
| `[ ]` | `pitch_pa_facts` cached SQL view (also feeds Stage 2 Wave 2) | Low–Med |

Deferred until the MVH yields one validated winner: `/mlb-discover` skill, book-pattern
mining, LLM-auto-hypothesis, combo discovery. **Similarity engine — cut entirely**
(K-rate is ~99.5% multiplicatively separable).

### Stage 3 — per-batter lineup model — effectively RETIRED

The similarity-engine cut removed its mechanistic rationale. Revisit only on contrary
evidence from Stage 2's dispersion feature.

---

## Critical path & risks

- **Critical path:** Wave 0 → Stage 1.1 → Stage 1.4 → Stage 1.3 → (Stage 2 / MVH).
- **First ship is small and stops bleeding:** Stage 1.1 fixes the non-monotonic
  edge→hit-rate bug; Stage 1.3 stops the system buying sub-coin-flip picks.
- **Biggest risk:** treating planning as progress. The plan is well-vetted across 4
  rounds — further review has hit diminishing returns. Build.
- **Deploy discipline:** Stage 2 retrains are a feature-contract change — upload +
  register + shadow the new model artifact in GCS *first*, then merge the worker
  `FEATURE_COLS` change (the MLB worker auto-deploys).

---

## Adjacent opportunities (parked — revisit after Stage 1 ships)

- **Pitcher props beyond strikeouts** — the `outs`/innings market is nearly free (deepest
  books, gradable today) and ~triples bettable edges/day. Reframe to "pitcher props."
- **Batter props** — 5–8× more events/day, likely softer; needs the batter-prop scrapers
  re-enabled for 2026 (stopped 2025-09-28).
- **Live / in-game betting** — softer markets; major new build. Cheap step now: schedule
  the dormant `mlb_live_box_scores` scraper to start the data clock.
- **Pre-2025 pitch-level backfill** (`pybaseball`) — unblocks cross-season validation of
  the entire pitch-level feature catalog. High leverage for the harness.
