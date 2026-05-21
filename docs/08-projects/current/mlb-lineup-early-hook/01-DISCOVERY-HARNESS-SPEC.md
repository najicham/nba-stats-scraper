# MLB Strikeout Discovery Harness — Spec

**Created:** 2026-05-20
**Status:** Designed + reviewed (25-agent design + 25-agent review, 2026-05-20).
**APPROVED** — MVH to be built **after Stage 1**. Round-4 revisions below override the
body where they conflict.
**Companion to:** `00-PROJECT-SPEC.md` (the MLB strikeout model spec). The harness is the
tooling for that spec's **Stage 2 feature discovery** — built **after Stage 1**, reusing
its validation framework, not as a separate project.

---

## 0. Round-4 review revisions (2026-05-20) — these override the body

- **CUT the similarity/archetype engine (§9).** Empirically, MLB K-rate is ~99.5%
  multiplicatively separable (batter K% × pitcher K%); the archetype-matchup grid yields
  ~0.2 K of signal and cannot clear its own gate. Replaced by a single dispersion
  feature (count of opposing batters with K% > threshold) + empirical-Bayes cold-start
  shrinkage applied directly to model spec feature A. Embeddings stay parked.
- **The MVH is one ~300–400-line script** (`bin/mlb/discover.py`) — *not* 8 BQ-backed
  modules. The dataset is ~20K starts; it fits in memory. Keep one cached SQL view
  (`pitch_pa_facts`); everything else is pandas + a results CSV. The 8-module
  architecture (§3) is the eventual shape only if the script proves itself.
- **Tier-2 evaluation needs fixing (§6).** CatBoost seed variance ≈ candidate effect
  size — run multi-seed paired with/without (same K seeds both arms), pin seed + split,
  add a residual-prediction co-gate, and report the minimum detectable effect per
  verdict (`UNDERPOWERED` ≠ `DEAD`).
- **Leak audit (§7) is partly un-buildable as written.** Gates 2 & 3 cannot AST-scan
  arbitrary Python `compute` lambdas — leakage lives in the upstream feature builders.
  Recast gate 2 as a column-provenance runtime check, gate 3 as a SQL lint of the
  builders. Gate 4 (point-in-time determinism) needs frozen table snapshots that don't
  exist — apply it only to snapshot-versioned sources (odds) until snapshot infra is built.
- **Residual-scoring (§2.1) is demoted** from a kill-gate to a cheap ordering heuristic
  for the Tier-2 queue (circularity: the residual depends on a possibly-misspecified
  model). Marginal-MAE-on-retrain is the sole primary screen.
- **Pre-seed the dead-ends ledger** from `mlb-2026-season-strategy/05-DEAD-ENDS.md`.
- **Add a harness self-test suite** as MVH item 0 — plant known-null, known-leaky, and
  known-real candidates and a target-shuffle negative control; no result is trusted
  until they classify correctly.
- **Build MLB-first**, lifting only `stats_utils` to `shared/discovery/`. Do not build a
  unified NBA+MLB harness. The NBA discovery framework's track record is mixed — port
  the *discipline* (FDR, bootstrap, cross-season), treat its scanner as a confirmatory
  sweep only.

---

## 1. Purpose

A system to rapidly test predictive "angles" (candidate features/signals) for MLB
pitcher strikeouts: describe an idea → the harness backfills it leak-free across past
seasons → replays it through the model → reports whether it adds real, durable value →
records it in a permanent ledger. Goal: turn "try everything and see what sticks" into a
disciplined, fast, reproducible loop instead of ad-hoc one-off experiments.

---

## 2. Core principles

1. **Score against the model *residual*, not raw strikeouts.** A candidate matters only
   if it explains what the current model still gets wrong (`K_actual − λ_predicted`). A
   feature that predicts K but is already captured scores ~zero.
2. **Validate on all ~5,000 pitcher-starts (MAE), not the ~500 graded picks (HR).** At
   ~500 picks/season the minimum detectable HR effect is ~+9pp — HR is a directional
   sanity check, never a gate (consistent with `00-PROJECT-SPEC.md` §7.4).
3. **Leakage is made structurally hard** — a 5-gate audit every candidate must pass
   before its result counts (§7).
4. **Cross-season replication is mandatory** — a one-season effect is auto-rejected.
5. **Every dead end is remembered** — a ledger so noise is never re-discovered.
6. **MVH first.** Build the minimum viable harness; defer the similarity engine and
   book-pattern mining until the MVH produces one validated, bet-moving winner (§16).

---

## 3. Architecture — 8 modules

~70% ports from the existing NBA discovery framework (`scripts/nba/training/discovery/`).
Lift `stats_utils.py` to a shared core; build MLB discovery as a sibling under
`scripts/mlb/training/discovery/`.

```
      hypotheses (YAML / decorator-registered / LLM-proposed)
                          │
        ┌─────────────────▼─────────────────┐
        │ 1. HypothesisRegistry             │ parse · validate · dedup · status
        └─────────────────┬─────────────────┘
        ┌─────────────────▼─────────────────┐
        │ 2. FeatureBuilders                │ rolling · similarity · split · crossbook
        └─────────────────┬─────────────────┘   point-in-time (< game_date)
        ┌─────────────────▼─────────────────┐
        │ 3. CandidateFeatureStore (BQ)     │ wide, partitioned, cached
        └─────────────────┬─────────────────┘
        ┌─────────────────▼─────────────────┐
        │ 4. LeakAuditor                    │ 5 gates — BLOCKS on fail (§7)
        └─────────────────┬─────────────────┘
        ┌─────────────────▼─────────────────┐
        │ 5. WalkForwardEvaluator           │ wraps season_replay.py; 2-tier funnel
        └─────────────────┬─────────────────┘
        ┌─────────────────▼─────────────────┐
        │ 6. StatGate                       │ BH-FDR · paired-bootstrap MAE · x-season
        └─────────────────┬─────────────────┘
        ┌─────────────────▼─────────────────┐
        │ 7. ResultsLedger                  │ leaderboard + dead-ends (§12)
        └─────────────────┬─────────────────┘
          8. Orchestrator — CLI driver, parallel, checkpointed/resumable
```

| Module | Reuse |
|--------|-------|
| `stats_utils` (binomial, BH-FDR, block bootstrap, x-season) | **Port verbatim** to `shared/discovery/`, parameterize NBA constants |
| `feature_scanner` engine (generate × percentile × checkpoint loop) | Port; rebuild the MLB hypothesis generators |
| `combo_tester` (interaction search) | Port engine; rewrite signal conditions |
| `data_loader` | **Rebuild** — pitcher-start grain, OVER-only, BQ-backed |

Effort to a working MLB `feature_scanner` equivalent: **~2–3 days.**

---

## 4. The candidate API

A candidate is a small frozen dataclass carrying metadata + a pure compute function.
Registered via decorator — adding an angle is **one file, one function, zero engine
edits**. Pandas, not SQL templates (pitcher-start data is ~5K rows/season — small).

```python
@dataclass(frozen=True)
class KCandidate:
    name: str                       # "opp_lineup_k_pct_vs_hand"
    description: str
    inputs: list[str]               # source columns — CI checks they exist
    compute: Callable[[pd.DataFrame], pd.Series]
    leakage_class: Leakage          # PREGAME_SAFE | SAME_DAY | NEEDS_AUDIT | BANNED
    expected_sign: Sign             # POSITIVE | NEGATIVE | UNKNOWN  (vs strikeouts)
    recency: str | None = None      # "last_3" | "last_10" | "season"
    family: str = "misc"
    min_n: int = 150
```

`leakage_class` is load-bearing — the harness refuses to score `SAME_DAY`/`BANNED` and
runs the determinism test on every `PREGAME_SAFE` one. `expected_sign` auto-flags sign
flips (usually leakage or noise).

**Composition** via a `cross()` combinator — base feature × situational split × recency
window — auto-named (`pitcher_k_rate__two_strike__last_10`), strictest `leakage_class`
propagated.

---

## 5. Backfill engine

- **One cached PA intermediate** — `mlb_discovery.pitch_pa_facts`: a single pass over
  `mlb_game_feed_pitches` (~246 MB, 920K rows) collapses to one row per (pitcher, game)
  with PA-level aggregates (2-strike counts, CSW, velo splits, TTO buckets). The
  expensive pitch scan happens **once**; all PA-derived candidates build from this.
- **One wide candidate store** — `mlb_discovery.candidate_feature_store`, keyed
  `(pitcher_lookup, game_date)`, partitioned by `game_date`, clustered by
  `(pitcher_lookup, season_year)`. Grow it with `ADD COLUMN` per candidate; cache by SQL
  hash — never recompute an unchanged candidate.
- **Incremental** — every backfill is partition-scoped (`MERGE` on a date range).
- **Cost is a non-issue** — full pitch scan ≈ $0.0015; a 500-candidate run < $1.
  Optimize wall-clock, not dollars. A `--dry_run` byte estimate gates any runaway query.
- **Horizon-aware** — each candidate declares its earliest valid season; the engine
  refuses earlier rows rather than emitting silent NULLs (see §15).

---

## 6. Evaluation engine — two-tier funnel

**Tier 0 — build the residual frame once.** Walk-forward the current model over the
backtest seasons, persist `game_date, pitcher, actual_K, line, pred_K, residual,
edge, went_over`. Every candidate is then an in-memory join — no retrain.

**Tier 1 — univariate quick-screen (seconds/candidate).** Against the residual frame:
Spearman ρ(candidate, **residual**) — the incremental-value test; decile-residual
monotonicity; cross-season sign stability. Kills ~80% of candidates instantly.

**Tier 2 — marginal retrain-replay (minutes/survivor only).** Add the candidate to
`FEATURE_COLS`, re-run the walk-forward. Metrics, **pre-registered before running**:
- **Primary gate:** paired-bootstrap MAE lift, 95% CI lower bound > 0, all ~5K starts.
- Brier-score delta (calibration must not regress).
- CatBoost importance + SHAP-vs-residual (confirms the model uses it, isn't double-counting).
- HR / CLV — directional sanity only, never a gate.

Interactions (§10) tested in `combo_tester` only after both parents clear Tier 2.

---

## 7. Leakage prevention — the 5-gate audit

A candidate earns a result row only after passing all five, in order:

1. **Source manifest + availability timestamps.** Each source has a registered landing
   time; the harness rejects a feature that reads data landing after the 12:55 pm ET
   prediction cutoff. Catches closing-line-as-same-day, next-day Statcast.
2. **Column allowlist** for post-game tables — only `*_last_N`, `season_*`,
   `days_since_last_game`, `games_last_*` from `batter/pitcher_game_summary`; banned:
   target-game actuals, post-game `batting_order`, `vs_pitcher_*` (BvP), `_latest`
   arsenal. AST-checked.
3. **Strict `< game_date` window audit** — AST scan rejects `CURRENT ROW`, `<=`,
   `BETWEEN ... game_date`. The `bench_under` failure mode made un-writable.
4. **Point-in-time determinism replay** — recompute the feature as-of D vs from a D+30
   snapshot; require byte-identical. The backstop for restatement / late-landing leakage.
5. **Suspicious-correlation flag** — any candidate correlating with realized K above an
   empirical ceiling is routed to a mandatory 3× re-audit.

Output per candidate: a **leakage audit card** stored beside the result.

---

## 8. Statistical rigor

"Try everything" is a noise machine without these — all enforced automatically:

- **BH-FDR over the entire batch** of candidates in a run (feature × threshold × split),
  not per-family. The total candidate count `m` is logged and pre-registered.
- **Cross-season replication is a hard pass/fail** — same sign, CI excludes null, in
  every season that clears the N floor. One-season effects auto-rejected.
- **Sealed holdout** — the most recent ~½ season is never read until a candidate is
  final. No re-tuning against it.
- **Deflated effect sizes** — the displayed effect is shrunk for selection (haircut ∝
  `log(m)`).
- **Garden-of-forking-paths control** — an append-only registry of every candidate ever
  scored; cumulative tests count toward the FDR denominator across sessions; pre-register
  each hypothesis before viewing results.
- **Economic-durability gate** — beyond significance: stable across the threshold grid
  (no knife-edge optimum), a stated mechanism, no calibration regression, CLV ≥ 0
  (once `00-PROJECT-SPEC.md` §7.2 lands).

---

## 9. Similarity & connections engine — CUT (see §0)

**Removed by the round-4 review.** A separability test on 232K plate appearances found
MLB K-rate is ~99.5% multiplicatively separable: `K_rate ≈ batter_K% × pitcher_K% /
league_K%` predicts cell rates at r = 0.995. The archetype-matchup grid's entire upside
is the residual interaction — ~0.0055 K/PA per cell, ≈0.2 K over a full start — below
the model's 1.83 MAE and far below the §6 paired-bootstrap CI. It would not clear its
own gate, and the spec's own shrinkage-toward-product-of-margins design guarantees a
no-interaction cell just returns `batter_K% × pitcher_K%`, which the model already has.

**What survives:** the *cold-start EB shrinkage* idea — apply it directly to model spec
feature A (opponent-lineup K%), shrinking thin batters toward a coarse 2–3-bucket K-tier
mean. And the **dispersion** variant of feature A (count of opposing batters with K% >
threshold) — a single rolling column, not an interaction grid. No pitcher/batter kNN, no
25-dim vectors, no archetype grid, no embeddings.

This also removes Stage 3's mechanistic rationale: with no non-separable matchup
interaction, a per-batter early-hook model has no composition signal beyond dispersion,
which the scalar feature already delivers. Treat Stage 3 as effectively retired pending
contrary evidence.

---

## 10. Candidate angle catalog

The initial families the harness ships with (each angle = a `KCandidate`):

| Family | Examples | Data | Notes |
|--------|----------|------|-------|
| **Pitch-level** | CSW%, SwStr%, 2-strike putaway rate, chase%, whiff% by pitch type, first-pitch-strike%, zone%, pitch-mix entropy | `mlb_game_feed_pitches` | 2025+ only |
| **Sequencing** | TTO K% decay, within-start velo fade, putaway-stability across TTO, whiff-generating pitch sequences, pitch economy | `mlb_game_feed_pitches` | 2025+ only |
| **Stuff+ proxy** | lightweight pitch-quality model (velo + spin + extension → expected whiff) | pitch-level | Wave 3 |
| **Form / recency** | recent-K z-score, velocity trend, CSW trend, workload-fatigue — **recency-weighting scheme itself is a scanned hyperparameter** (fixed windows vs exp-decay half-life vs EB blend); placebo-tested (shuffle game order) | summaries + statcast | 4 seasons |
| **Situational** | count-leverage, home/away, day/night, rest buckets | summaries | base-state ("runner on first") **blocked** — data absent |
| **Lineup construction** | PA-weighted lineup K%, whiff-rate dispersion, easy-out count, top-vs-bottom split, platoon-disadvantage count | `mlb_lineup_batters` + batter stats | dispersion variant gates Stage 3 |
| **Book / market** | cross-book consensus, disagreement (std), line drift, outlier book, lopsided vig; ported NBA OVER signals (`line_rising_over`, `sharp_book_lean_over`, `book_disagree_over` — **thresholds recalibrated** for the 12-book regime) | `oddsa_pitcher_props` | movement = 2026 only; no steam (2h cadence) |
| **Context** | umpire strike-zone tendency, ballpark K-factor, elevation/dome, weather (temp/air-density), travel/getaway-day | umpire/park/weather | umpire needs the D5 morning scrape; weather needs a backfill |
| **Interactions** | pitcher K% × lineup K%, putaway × opponent chase, velo-drop × TTO penalty | derived | §8 combo discovery |

---

## 11. Search strategy

- **LLM-proposed hypotheses are the primary generator.** At MLB's thin sample, the
  scarce resource is *test budget* — spend it on mechanism-backed angles. An agent with
  the domain spec proposes ranked batches of 15–30, each with a stated causal mechanism,
  pre-registered direction/threshold, and a leak-class note.
- **Brute-force scan = a confirmatory safety sweep** — a `feature_scanner`-style grid
  flags missed univariate effects; anything it surfaces goes back to the LLM for a
  mechanism before counting as a real candidate.
- **Iterative mutation = polish only** — mutate only angles that already cleared the
  gate, ≤3 mutations each, counted toward the FDR ledger.

---

## 12. Results store & dead-ends ledger

Two BigQuery tables; **`definition_hash`** (SHA-256 of the normalized candidate JSON) is
the primary key of knowledge.

- **`mlb_discovery.hypothesis_results`** — append-only, one row per (candidate × run):
  definition JSON, stage/wave, `mae_delta` + `ci_low/high`, `brier_delta`, `clv_mean/n`,
  `hr_delta/n`, `season_breakdown` JSON, `max_corr_existing`, `verdict`, `verdict_reason`.
- **`mlb_discovery.dead_ends_ledger`** — one row per terminal `definition_hash`. The
  harness **queries this first** and skips known dead-ends (`SKIPPED_KNOWN_DEAD`),
  incrementing `times_rediscovered` (a noise-frequency signal). `verdict_reason` enum:
  `NOISE_CI_SPANS_ZERO`, `LEAKAGE_PIT_NONDETERMINISM`, `REDUNDANT_HIGH_CORR`,
  `NO_ECONOMIC_EDGE`, `INCONSISTENT_SEASONS`, `COVERAGE_TOO_LOW`. `revisit_allowed_after`
  auto-expires a verdict once a new season of data exists.

A `leaderboard` view ranks `PROMISING` candidates by `ci_low` DESC, tie-broken by
worst-season delta. Extends the existing `docs/06-reference/model-dead-ends.md` into a
queryable, hash-versioned system.

---

## 13. Graduation pipeline (discovered angle → production)

- **D0 — classify.** Model FEATURE (predicts the K count → `pitcher_game_summary` +
  `FEATURE_COLS`) vs betting SIGNAL/FILTER (predicts bet quality → `ml/signals/mlb/`).
  Tie-breaker: line/book-derived → signal; pure baseball → feature.
- **D1 — discovered.** Pre-registered hypothesis card; passes the §7 leak audit.
- **D2 — shadow.** Feature: trained into a `_shadow` model, not the production
  `FEATURE_COLS`. Signal: `is_shadow=True`. ≥1 season walk-forward observation.
- **D3 — validated.** All `00-PROJECT-SPEC.md` §7.4 gates + cross-season consistency +
  feature-coverage check.
- **D4 — live.** Feature: **artifact-first deploy** — upload + register + shadow the new
  model in GCS, *then* merge the worker `FEATURE_COLS` change (never the reverse).
  Signal: flip `is_shadow=False` + update `shared/registry/signals.yaml` in one commit.
  Reversible — a degrading feature returns to shadow.

---

## 14. Owner interface

A Claude Code skill **`/mlb-discover`** backed by a thin CLI (`bin/mlb/discover.py`):
the owner states a hypothesis in plain English → Claude translates it to a concrete
`KCandidate` (surfaced for confirmation) → the CLI runs the leak-safe backtest → Claude
narrates a **per-season breakdown** (never one blended number) + a mechanical verdict
(`STRONG` / `PROMISING` / `NOISE` / `DEAD`). `/mlb-discover history` browses the ledger
(including `--losers`) so nothing is re-tested. Target loop time: < 60 s.

```
> /mlb-discover pitchers coming off a fastball velo drop strike out fewer guys
CANDIDATE  velo_drop_under   rule: fb_velo_z_last_start < -1.0
  2022 N=288 56.6% | 2023 N=301 54.8% | 2024 N=277 58.1% | 2025 N=119 55.5%
  VERDICT: PROMISING — 4/4 seasons, paired-bootstrap 95% CI low +1.8pp
```

---

## 15. Data constraints — what we can vs cannot test

| | |
|---|---|
| **Testable, 4 seasons (2022–2025)** | rolling K/velocity/CSW form, line-movement (static cross-book), opponent team K-rate, rest/schedule, ballpark, day/night |
| **Testable, 2025 only** (no cross-season validation yet) | CSW%, 2-strike putaway, times-through-order, within-start velo decline, plate discipline, umpire zone tendency, lineup composition |
| **Blocked** | base-state / "runner on first" (data absent — needs a re-scrape), batted-ball quality (no exit-velo), real CLV (closing lines 98% synthetic), pre-2025 umpire, weather (needs an Open-Meteo historical backfill), steam/sharp-money (2-hour snapshot cadence too coarse; no sharp anchor book) |

---

## 16. Scope — MVH (revised per §0)

**Minimum Viable Harness = one script**, `bin/mlb/discover.py` (~300–400 lines), built
*after* Stage 1 ships. Contents:
0. **Harness self-test** — planted known-null / known-leaky / known-real candidates +
   a target-shuffle negative control. Nothing is trusted until these pass.
1. **Candidate registry** (§4) — `KCandidate` dataclass + decorator.
2. **Point-in-time backfill** (§5) — leak-safe `< game_date` columns; one cached SQL
   view `pitch_pa_facts`; everything else pandas (~20K starts fits in memory).
3. **Replay scorer** (§6) — multi-seed paired-bootstrap MAE (per §0), per-season
   breakdown, results appended to a CSV. Reuses Stage 1's validation framework.

~1–1.5 weeks once Stage 1's validation framework exists. **Cut from the MVH:** the
BQ-backed candidate store, the standalone 8 modules, the dead-ends BQ tables (a CSV
column suffices), the `/mlb-discover` skill.

**Deferred (gated on the MVH producing one validated, bet-moving winner):** the
`/mlb-discover` skill, book-pattern mining, LLM-auto-hypothesis search, combo discovery,
the productionized 8-module architecture. The similarity engine (§9) is **cut entirely**,
not deferred.

---

## 17. Open decisions & sequencing

1. **Timing vs Stage 1.** The MVH shares Stage 1.4's validation framework — recommend
   building them together; do **not** build the harness before Stage 1.1–1.3
   (calibration/selection fixes), or candidates get scored against a broken model.
2. **`/mlb-discover` skill** — build as part of the MVH, or after?
3. **LLM-auto-hypothesis** — in scope eventually, or kept as a manual owner-driven loop?
4. Folder/naming — this harness + the strikeout model both live under
   `mlb-lineup-early-hook/`; consider renaming the project folder.

| Step | Effort | Gating |
|------|--------|--------|
| Port `stats_utils` → `shared/discovery/` | Low | — |
| MVH: candidate registry + backfill + replay scorer | ~2 wk | after Stage 1.4 |
| `/mlb-discover` skill + CLI + ledger | Low–Med | with MVH |
| Similarity/archetype engine (§9) | Med–High | after MVH winner |
| Book-pattern mining (§10) | Med | after MVH winner |
| LLM-auto-hypothesis + combo discovery | Med | after MVH winner |

**No code is written until this spec is approved.**
