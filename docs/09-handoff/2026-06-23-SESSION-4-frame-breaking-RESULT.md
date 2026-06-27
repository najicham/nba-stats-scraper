# Session 4 (2026-06-23) — frame-breaking exploration: error-structure, price, CLV

Follows SESSION-3. The 34-agent review concluded "research has converged" — but only
*within* the frame we'd always used (per-pick, HR-graded, hypothesis-driven, single-line).
This session relaxed three of those assumptions to test whether the convergence is real or
just a blind spot of the method. Scripts:
`scripts/nba/training/discovery/{error_decomposition,structural_selection_signals}.py`.

## 1. Discovery method: hypothesis-test → ERROR-DECOMPOSITION → "features are DONE"

Instead of testing hand-built features, let the model's own errors name the gaps.
residual = actual − predicted on 47K walk-forward V12_NOVEG predictions; ask what pre-game
feature predicts the residual.

- **Held-out (leave-one-season-out) LightGBM R² predicting residual:** ALL features **+0.012**;
  **player/context-only +0.004** (≈0); market-feature positive control +0.003 (confirms the
  method — "vegas helps" appears, as it must, but explains <0.3%).
- Every per-feature Spearman |ρ| < 0.05 — FDR-significant on 47K rows but practically nil.
- Model is unbiased every season (mean residual −0.07…+0.07), MAE ~4.9 — near the irreducible
  floor of game-to-game NBA scoring variance.

**VERDICT: the model is well-specified; adding features cannot help.** This is the principled,
leak-free version of the old "adding features hurts" rule — and it is now the **3rd independent
lens** to reach it (leak-clean feature-set experiments → GBDT-are-clones diversity → error
structure). Three orthogonal methods agreeing ⇒ trustworthy. **The edge is in SELECTION and
SIGNALS, not the model or its features.**

## 2. Ground-truth/price axis: two new structural SELECTION signals — both negative

Tested as selection signals (not model features), with Wilson CI + per-season + binomial p:

- **No-vig / over-price juice (`over_odds_median`) → DEAD END.** "Fade the juiced over"
  REFUTED: UNDER picks when over is juiced (≤−130) = 50.0% (N=52), *worse* than normal (58.0%).
  Price-implied prob does not discriminate OVER outcomes (54.6% high vs 54.6% low). The price
  carries no usable signal beyond the line.
- **CLV proxy (`line_movement`) → not actionable as built, one real hint.** Movement *toward*
  the pick (58.9%) and *against* it (57.6%) hit identically — direction does not discriminate.
  But **"line did NOT move" = 51.7% (sub-breakeven)** vs ~58% for any movement. The signal isn't
  CLV-direction; it's "static-line picks underperform" — confounded (low-profile games) and the
  in-cache proxy is too crude to settle.

## 3. DROPPED / DEFERRED

- **Line-vs-game-total mispricing → CANNOT TEST.** `implied_team_total`/`game_total_line` are
  **0% populated 2021-25, 88% only 2025-26** — the 3rd single-season-coverage artifact in the
  cache (after `is_b2b` and `star_teammates_out`). **META-FINDING: the research cache's pre-2025
  enrichment is thin; many "richer feature" ideas can't be cross-season tested. Future feature
  research needs a cache rebuild with backfilled enrichment, or production BQ.**
- **True CLV → feasible BUILD, deferred (the one genuinely-unexplored high-value angle).**
  Production has NO closing-line column/table, BUT `nba_raw.odds_api_player_points_props` has
  `snapshot_timestamp` + `game_start_time`, so the closing line is reconstructable (last snapshot
  before tip). Snapshot tags are time-based (`snap-1431`), not semantic, and the raw data looks
  sparse/irregular → this is a scoped data-engineering build with data-quality risk, not a quick
  query. **RECOMMENDED NEXT INVESTMENT:** CLV is the lower-variance validator that would settle
  "real edge vs 2025-26 noise" with far less data than HR — and the "static-line underperforms"
  hint suggests there is market-information structure there to mine. Approach: reconstruct closing
  line per (game,player) from the latest pre-`game_start_time` snapshot, join to picks at their
  pick-time line, compute CLV by direction, validate cross-season.

## Bottom line
Breaking the frame CONFIRMED the convergence rather than overturning it: the model is
well-specified (features done, triple-confirmed), and two new structural selection angles are
dead/blocked. The only remaining genuinely-unexplored high-value lever is **true CLV** — a
bounded build, not more mining. Net new actionable items: **zero** (all three relaxed-assumption
angles came back negative or build-gated), which is itself the decisive answer to "are there more
features/angles": not in the cache — the next real step is the CLV reconstruction.
