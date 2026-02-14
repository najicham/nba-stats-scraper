# Session 227 Handoff — V2 Model Architecture Plan Complete

**Date:** 2026-02-13
**Focus:** Critical evaluation of 3 expert reviews, V2 architecture plan, V12 feature specification
**Next Session:** Implement V12 features + run diagnostics + start experiments

---

## What Was Done This Session

### 1. Read & Critically Evaluated 3 Independent Expert Reviews

All three Opus web chats (docs 13-15) plus the master plan (doc 16) were read and evaluated. Key agreements and disagreements documented in doc 17.

### 2. Created Final Execution Plan (doc 17)

`docs/08-projects/current/model-improvement-analysis/17-FINAL-EXECUTION-PLAN.md`

**Architecture decision:** 2-model system adopted:
- **Model 1:** Vegas-free CatBoost points predictor (MAE loss, ~25-28 features, ZERO Vegas)
- **Model 2:** Edge classifier (binary, logistic regression → CatBoost)

**Additions beyond the 3 reviews:**
- Added diagnostic Query 0 (actual OVER/UNDER outcome rates by month) — none of the 3 reviews asked this
- Flagged that Feb 2025's 79.5% may be an anomaly, not achievable steady-state
- Required N>150 for go/no-go decisions (most Feb 2026 experiments had N=16-170)
- Added hard decision gate for game_total_line (already failed as V11 feature, needs proof)
- Noted Vegas-free model may benefit from longer training windows (basketball patterns more stable than Vegas calibration)

### 3. Created Testing Plan (doc 18)

`docs/08-projects/current/model-improvement-analysis/18-TESTING-PLAN.md`

**4 evaluation windows** for ALL experiments:
- Feb 2025 (known-good benchmark, DK lines)
- Dec 2025 (early season baseline)
- Jan 2026 (pre-decay validation)
- Feb 2026 (problem period, production lines)

Exact CLI commands for every experiment, decision gates at each phase, results tracking table.

### 4. Created V12 Feature Specification (doc 19)

`docs/08-projects/current/model-improvement-analysis/19-V12-FEATURE-ADDITIONS-IMPLEMENTATION.md`

**15 new features** fully specified (indices 39-53):
- 6 LOW complexity: `days_rest`, `minutes_load_last_7d`, `spread_magnitude`, `implied_team_total`, `prop_over_streak`, `prop_under_streak`
- 6 MEDIUM: `points_avg_last_3`, `scoring_trend_slope`, `deviation_from_avg_last3`, `consecutive_games_below_avg`, `usage_rate_last_5`, `multi_book_line_std`
- 3 HIGH: `teammate_usage_available`, `games_since_structural_change`, `line_vs_season_avg`

Each feature has: SQL query, source table, default value, extraction code, quality classification.

**Two-phase implementation:** Training-time augmentation first (fast, for experiments), feature store backfill later (for production).

### 5. Committed Date Bug Fix

`be2933b3` — Fixed `get_dates()` in quick_retrain.py that silently ignored `--train-start`/`--train-end` without eval dates. Also added V11 feature set support and player_lookup in eval queries.

### 6. Started Diagnostics (Incomplete)

Ran diagnostic queries Q0, Q1, Q3, Q4 against BigQuery. Q0 timed out, Q1 failed on column name (`sportsbook` should be `bookmaker` in odds_api_player_points_props). Q3 and Q4 had sibling errors. **Diagnostics need to be re-run.**

---

## What to Do Next Session

### YOUR FIRST TASK: Generate Chat Prompts

This session's work identified 3 parallelizable workstreams. **Generate prompts for separate Claude Code chats to execute in parallel:**

1. **Chat A: V12 Feature Implementation** — Implement the V12 contract, `augment_v12_features()` in quick_retrain.py, and the `--feature-set v12` flag. Use doc 19 as the spec. This is BLOCKING for all model experiments.

2. **Chat B: Phase 0 Diagnostics** — Run the 6 diagnostic BQ queries from doc 18. Fix the column name issues (use `bookmaker` not `sportsbook` for odds_api tables). Document findings. This is BLOCKING for understanding Feb 2026 failure.

3. **Chat C: Phase 1A Baseline Experiments** — After Chat A completes, run the quick Vegas-free baseline experiments (4 eval windows + training window comparison + loss function comparison). Use exact commands from doc 18.

**Generate specific, copy-pasteable prompts for each chat** with all necessary context so the new chat can execute independently.

### Execution Order

```
Chat A (V12 features) ──────────── BLOCKING
  │
  ├── Chat B (diagnostics) ─────── Can run in PARALLEL with Chat A
  │
  ├── MERGE Chat A results ─────── Commit V12 code changes
  │
  └── Chat C (experiments) ─────── AFTER Chat A completes
       ├── Phase 1A baseline (no-vegas, MAE, V9 features)
       ├── Phase 1A with V12 features
       ├── Training window comparison
       └── Loss function comparison
```

### Key Documents to Read

```bash
# The implementation spec (most important for Chat A)
cat docs/08-projects/current/model-improvement-analysis/19-V12-FEATURE-ADDITIONS-IMPLEMENTATION.md

# The execution plan (architecture decisions)
cat docs/08-projects/current/model-improvement-analysis/17-FINAL-EXECUTION-PLAN.md

# The testing plan (exact experiments to run)
cat docs/08-projects/current/model-improvement-analysis/18-TESTING-PLAN.md

# Previous session's experiment results
cat docs/09-handoff/2026-02-12-SESSION-226B-HANDOFF.md
```

---

## Important Context

### Modified Files (NOT Committed — from previous sessions)

These are staged/modified changes from sessions 225-226B that are unrelated to the V2 model work:

```
M  backfill_jobs/publishing/daily_export.py
M  data_processors/precompute/ml_feature_store/feature_extractor.py
M  data_processors/precompute/ml_feature_store/ml_feature_store_processor.py
M  data_processors/precompute/ml_feature_store/quality_scorer.py
M  data_processors/publishing/tonight_player_exporter.py
M  shared/ml/feature_contract.py
```

**Be careful:** `shared/ml/feature_contract.py` has uncommitted changes from a previous session (V10 feature set additions). The V12 contract additions should be applied ON TOP of these existing changes, not conflict with them.

### New Untracked Files (This Session)

```
docs/08-projects/current/model-improvement-analysis/17-FINAL-EXECUTION-PLAN.md
docs/08-projects/current/model-improvement-analysis/18-TESTING-PLAN.md
docs/08-projects/current/model-improvement-analysis/19-V12-FEATURE-ADDITIONS-IMPLEMENTATION.md
docs/09-handoff/2026-02-13-SESSION-227-HANDOFF.md
```

### BQ Column Names (Gotcha)

- `nba_raw.odds_api_player_points_props` uses `bookmaker` (NOT `sportsbook`)
- `nba_raw.odds_api_game_lines` uses `bookmaker_key` and `bookmaker_title`
- Game spread convention in UPCG: **verify** whether `game_spread` is from home team perspective before implementing `implied_team_total`

### Existing Capabilities (No Code Changes Needed for Phase 1A)

`quick_retrain.py` already supports:
- `--no-vegas` — drops features 25-28
- `--loss-function MAE` — trains with MAE loss (no quantile)
- `--walkforward` — per-week evaluation
- `--exclude-features "name1,name2"` — drop specific features
- `--feature-set v11` — uses 39-feature contract (with augmentation)

**Phase 1A experiments can run NOW** using `--no-vegas --loss-function MAE` with V9 features. V12 features (Chat A) are needed for Phase 1B+.

### Dead Ends (Do NOT Revisit)

Monotonic constraints, multi-quantile ensemble, alpha fine-tuning, residual mode (single model), two-stage sequential pipeline, 3+ season training with Vegas features, neural networks, micro-retraining alone, V10/V11 features as-is.

---

## Quick Reference

| Resource | Path |
|----------|------|
| V12 feature spec | `docs/08-projects/current/model-improvement-analysis/19-V12-FEATURE-ADDITIONS-IMPLEMENTATION.md` |
| Final execution plan | `docs/08-projects/current/model-improvement-analysis/17-FINAL-EXECUTION-PLAN.md` |
| Testing plan | `docs/08-projects/current/model-improvement-analysis/18-TESTING-PLAN.md` |
| Expert review 1 | `docs/08-projects/current/model-improvement-analysis/13-OPUS-CHAT-1-ANALYSIS.md` |
| Expert review 2 | `docs/08-projects/current/model-improvement-analysis/14-OPUS-CHAT-2-ARCHITECTURE.md` |
| Expert review 3 | `docs/08-projects/current/model-improvement-analysis/15-OPUS-CHAT-3-STRATEGY.md` |
| Master plan (synthesized) | `docs/08-projects/current/model-improvement-analysis/16-MASTER-IMPLEMENTATION-PLAN.md` |
| Session 226B handoff | `docs/09-handoff/2026-02-12-SESSION-226B-HANDOFF.md` |
| Feature contract | `shared/ml/feature_contract.py` |
| Training script | `ml/experiments/quick_retrain.py` |
| Feature extractor | `data_processors/precompute/ml_feature_store/feature_extractor.py` |
