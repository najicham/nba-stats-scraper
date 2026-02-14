# Session 228 Start Prompt

Paste this into a new Claude Code session:

---

## Context

We're rebuilding our NBA player props prediction model. The current champion (CatBoost V9, 33 features) decayed from 71.2% to ~40% hit rate. Last session (227) we:

1. Critically evaluated 3 independent expert reviews
2. Created a final execution plan (V2 architecture: Vegas-free Model 1 + edge classifier Model 2)
3. Specified 15 new features (V12 contract, indices 39-53) with SQL queries, defaults, and extraction code
4. Created a detailed testing plan with exact CLI commands and 4 evaluation windows
5. Committed the `quick_retrain.py` date bug fix

## Your Task

1. **Read the handoff doc:**

```bash
cat docs/09-handoff/2026-02-13-SESSION-227-HANDOFF.md
```

2. **Read the 3 key planning docs (skim — they're thorough):**

```bash
cat docs/08-projects/current/model-improvement-analysis/17-FINAL-EXECUTION-PLAN.md
cat docs/08-projects/current/model-improvement-analysis/18-TESTING-PLAN.md
cat docs/08-projects/current/model-improvement-analysis/19-V12-FEATURE-ADDITIONS-IMPLEMENTATION.md
```

3. **Generate 3 copy-pasteable chat prompts** for me to open in parallel Claude Code sessions:

   **Chat A — V12 Feature Implementation:** Implement the V12 feature contract and `augment_v12_features()` in quick_retrain.py. Doc 19 is the complete spec. The chat should:
   - Add V12 contract to `shared/ml/feature_contract.py` (features 39-53, defaults, source map)
   - Add `augment_v12_features()` to `ml/experiments/quick_retrain.py` (training-time BQ augmentation)
   - Add `--feature-set v12` support
   - Test that `--feature-set v12 --no-vegas --loss-function MAE` runs without errors
   - Include enough context from doc 19 that the chat doesn't need to re-read it

   **Chat B — Phase 0 Diagnostics:** Run the 6 diagnostic BQ queries from doc 18 (Queries 0-5). The chat should:
   - Fix known issues: use `bookmaker` not `sportsbook` for odds_api tables
   - Run all 6 queries and document results
   - Apply the decision gates from doc 17 to the findings
   - Save results to `docs/08-projects/current/model-improvement-analysis/20-DIAGNOSTIC-RESULTS.md`

   **Chat C — Phase 1A Baseline Experiments:** Run the initial Vegas-free baseline experiments. This can start immediately since Phase 1A uses existing V9 features (no V12 needed). The chat should:
   - Run `VF_BASE` on all 4 eval windows (Feb 2025, Dec 2025, Jan 2026, Feb 2026)
   - Run `VF_BASE_180D` and `VF_BASE_STD` training window comparisons on Feb 2026
   - Run `VF_HUBER` loss function comparison on Feb 2026
   - Run dead feature ablation (`VF_NO_DEAD`, `VF_LEAN`)
   - Document all results in a comparison table
   - Save to `docs/08-projects/current/model-improvement-analysis/21-PHASE1A-RESULTS.md`
   - All exact CLI commands are in doc 18

4. **Make each prompt self-contained** — include all necessary context, file paths, exact commands, and expected outputs so each chat can execute independently without reading other docs.

5. **After generating prompts**, also identify which experiments from Phase 1A can run in parallel vs which must be sequential. Chats B and C can run simultaneously. Chat A must complete before any V12-based experiments.

## Key Facts

- `quick_retrain.py` already supports `--no-vegas --loss-function MAE` — no code changes needed for Phase 1A
- Feature contract is at `shared/ml/feature_contract.py` — has uncommitted V10/V11 changes from previous session
- The `bookmaker` column (not `sportsbook`) is used in `nba_raw.odds_api_player_points_props`
- Game spread in UPCG needs sign convention verified before implementing `implied_team_total`
- Training takes ~2-5 minutes per experiment
- All experiments should use `--walkforward --force --skip-register`

## Important

- Do NOT deploy anything — this is all experimentation
- Do NOT run experiments yourself — just generate the 3 chat prompts for me
- Use `doc` procedure for any new documents
- Read CLAUDE.md for project conventions
