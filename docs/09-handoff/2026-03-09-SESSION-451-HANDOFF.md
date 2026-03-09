# Session 451 Handoff — Mar 8 Autopsy Filters + Claude Review Concept

**Date:** 2026-03-09
**Focus:** Implement Mar 8 autopsy action items, design Claude API pick review system
**Algorithm:** `v451_session451_filters`

## What Was Done

### 1. Mar 8 Autopsy Filters Implemented

Reviewed all 8 action items from the Mar 8 autopsy (3-11, 21.4% HR — worst day of season). Decided to implement 5, skip 3. Committed to `main` (not yet pushed).

| # | Action | Decision | Status |
|---|--------|----------|--------|
| 1 | Line anomaly detector | **Active filter** | DONE |
| 2 | Player UNDER suppression | **Observation** | DONE |
| 3 | UNDER real_sc floor >= 2 | **Observation** | DONE |
| 4 | FT variance UNDER | **Observation** | DONE |
| 5 | Mean reversion guard | **SHADOW + over-rate guard** | DONE |
| 6 | Model unanimity signal | Skip (wait for per-model data) | — |
| 7 | B2B UNDER override | Skip (single case) | — |
| 8 | Blowout direction fix | Skip (already neutralized) | — |

### 2. Implementation Details

**Line anomaly extreme drop (ACTIVE FILTER)**
- `aggregator.py`: Blocks OVER when line drops >= 40% OR >= 6pts from previous game
- Uses existing `prop_line_delta` (current - prev). Derives prev_line, computes drop %.
- Mar 8 counterfactual: Would have blocked Derrick White ULTRA (line 16.5→8.5, 48.5% drop)
- Expected fire rate: 1-2/month. Safety net for manufactured edge from info asymmetry.

**Player UNDER suppression (OBSERVATION)**
- New function `compute_player_under_suppression()` in `player_blacklist.py`
- Queries `prediction_accuracy` for UNDER HR < 35% at N >= 20 across enabled models
- Wired into `SharedContext` and aggregator via `player_under_suppression` param
- Mar 8 counterfactual: Nobody flagged — enabled models too new (Mar 2-4 start)
- All-model data shows: Herro 22.5% (N=40), Duren 13% (N=23), GG Jackson 19% (N=21)
- Will activate as fleet accumulates history (~late March)

**UNDER low real_sc (OBSERVATION)**
- `aggregator.py`: Tags UNDER with real_sc < 2 at edge < 7
- Mar 8: 6/7 UNDER losses had rsc 1-2, but also catches 1 win (Zion rsc=1)
- Risk if promoted: blocks valid UNDER picks too. Needs N >= 30 assessment.

**FT variance UNDER (OBSERVATION)**
- New `fta_variance` CTE in `supplemental_data.py`: rolling 10-game FTA avg/std/CV
- `aggregator.py`: Tags UNDER when fta_avg >= 5 AND fta_cv >= 0.5
- Discovery: 47.8% UNDER HR vs 70.6% stable (22.8pp gap)
- Mar 8: Flags Booker (fta=5.8, cv=0.634) — ULTRA UNDER loss

**Mean reversion under → SHADOW + guard**
- Added to `SHADOW_SIGNALS` in `aggregator.py` (stops real_sc inflation)
- Added `MAX_OVER_RATE = 0.60` in `mean_reversion_under.py` (don't fire on structural high-scorers)
- Mar 8: Thompson rsc 1→0 → blocked by signal_density. Wemby/Herro rsc reduced.
- Signal HR decayed to 53% (below 54.3% baseline). This completes its demotion arc.

### 3. Mar 8 Counterfactual Results

**Confirmed blocks with new filters:** 3-11 → **3-9 (25.0%)**. Saves 2 units.
- Derrick White OVER: line anomaly blocks (48.5% drop)
- Amen Thompson UNDER: mean_reversion stops firing (over_rate=1.0) → rsc→0 → signal_density blocks

**Observations that would fire (data accumulation):**
- Booker: ft_variance flagged
- KAT/Castle/Thompson: under_low_rsc flagged
- Herro/Wemby/Thompson: hot_streak_under already fires

### 4. Tests

125 aggregator tests pass (14 new). 201 total signal tests pass.

### 5. Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Algorithm v451, 4 new filter counters + logic, player_under_suppression param |
| `ml/signals/mean_reversion_under.py` | MAX_OVER_RATE = 0.60 guard |
| `ml/signals/player_blacklist.py` | `compute_player_under_suppression()` |
| `ml/signals/supplemental_data.py` | `fta_variance` CTE + SELECT + pred dict mapping |
| `ml/signals/per_model_pipeline.py` | SharedContext field + build_shared_context + aggregator wiring |
| `ml/signals/pipeline_merger.py` | Algorithm version bump |
| `tests/unit/signals/test_aggregator.py` | 14 new tests |
| `CLAUDE.md` | Algorithm version + signal counts |
| `docs/.../SIGNAL-INVENTORY.md` | Updated filters/observations |
| `docs/.../session-451-mar8-filters/00-OVERVIEW.md` | Full project doc with validation queries |

## Uncommitted Changes

Session 451 is committed but **not yet pushed**. Push will auto-deploy.

There are also pre-existing uncommitted MLB changes (`main_mlb_grading_service.py`, `mlb/best_bets_exporter.py`) from prior sessions — not part of this commit.

## Pending / Waiting

### Observation Promotion — Check March 24

Three new observations need 2+ weeks of data before promotion decisions:

```sql
SELECT filter_name, game_date, cf_hr, n_picks
FROM nba_predictions.filter_counterfactual_daily
WHERE filter_name IN ('player_under_suppression_obs', 'under_low_rsc_obs', 'ft_variance_under_obs')
ORDER BY filter_name, game_date DESC;
```

**Promotion criteria:** CF HR >= 55% at N >= 20 for 7 consecutive days. The auto-demote system (`filter-counterfactual-evaluator` CF, daily 11:30 AM ET) will also detect this automatically.

Also check Sessions 439-442 observations that have been accumulating since Mar 3:
- `depleted_stars_over_obs`, `hot_shooting_reversion_obs`
- `over_low_rsc_obs`, `mae_gap_obs`, `thin_slate_obs`, `hot_streak_under_obs`

### 2 BLOCKED Models

`lgbm_v12_noveg_vw015` and `xgb_v12_noveg_s42` — decay-detection auto-disables at 16:00 UTC Mar 9. LGBM sourced 4/5 OVER losses on Mar 8.

---

## Next Session: Claude API Pick Review System

### The Idea

Use Claude API as a post-pipeline enrichment layer that reviews each best bet pick before publication. Not as a gate (agree/disagree that blocks picks), but as a **confidence annotator** that adds context we can correlate with outcomes over time.

### Why It Could Be Valuable

1. **Synthesize context that's hard to encode in rules** — "player just got traded", "team clinched playoff spot and may rest starters", "revenge game narrative"
2. **Catch contradictory signal combinations** — "line dropped 40% but we're picking OVER" (now caught by filter, but there are subtler versions)
3. **Richer pick angles** — narrative reasoning beyond template strings
4. **Flag common-sense red flags** our statistical filters miss
5. **Discover new filter candidates** — if Claude consistently flags a pattern that correlates with losses, that becomes a new observation

### Concerns to Address

1. **Latency:** 15 picks × 3-5s = 45-75s. Phase 6 Cloud Function has timeout constraints. Solution: run as post-export async step, not in the critical path.
2. **Cost:** ~$0.03-0.10/pick × 15/day × 365 = $165-550/year. Acceptable for the value if it works.
3. **Reliability:** Must be fail-open. If API call fails, pick still publishes. Zero impact on existing pipeline.
4. **Signal vs noise:** Claude doesn't have access to model feature weights or historical HR data. It opinionates on general basketball knowledge, not our specific edge. Our system already beats general knowledge.
5. **Measurability:** Need to log Claude's confidence rating + tags to BQ, then correlate with `prediction_correct` after grading.

### Proposed Architecture

```
Phase 6 Export (existing)
    ↓ picks written to signal_best_bets_picks
    ↓
Claude Review Step (NEW, async post-export)
    ↓ For each pick:
    ↓   1. Build context prompt (player stats, signals, line movement, injury context)
    ↓   2. Call Claude API (Haiku for cost, or Sonnet for quality)
    ↓   3. Parse structured response (confidence 1-5, tags[], reasoning)
    ↓
    ↓ Write to BQ: claude_pick_reviews table
    ↓
    ↓ Optional: Add to admin JSON export (internal only)
```

### What to Include in the Prompt

For each pick, provide:
- Player name, team, opponent, home/away
- Line value, predicted points, edge, recommendation (OVER/UNDER)
- Signal tags that fired and their meaning
- Recent player stats (last 3-5 games: points, FG%, minutes, FTA)
- Line movement (previous line, current line, DraftKings opening vs closing)
- Injury report (who's out on both teams)
- Team pace, spread, implied total
- Any filter observations that fired but didn't block

Ask Claude to return structured JSON:
```json
{
  "confidence": 3,           // 1-5 scale
  "agrees_with_pick": true,  // boolean
  "risk_flags": ["revenge_game", "back_to_back_fatigue"],
  "supporting_factors": ["hot_streak", "favorable_matchup"],
  "reasoning": "Short narrative explanation",
  "suggested_tags": ["situational_risk_medium"]
}
```

### Research Tasks for Next Session

1. **Design the prompt template** — what data to include, how to frame the question, what structured output to request. Test with a few Mar 8 picks manually.
2. **Choose the model** — Haiku (cheapest, fastest, ~$0.03/pick) vs Sonnet (better reasoning, ~$0.10/pick). Test both on same picks, see if Sonnet catches things Haiku misses.
3. **Design the BQ schema** — `claude_pick_reviews` table with pick_id, confidence, tags, reasoning, model used, latency_ms, etc.
4. **Build the integration point** — where in the pipeline does this run? Options:
   - Post-export Cloud Function triggered by Phase 6 completion
   - Separate scheduled function 5 min after Phase 6
   - Inline in exporter with timeout/fail-open
5. **Define the validation plan** — how long to run before acting on Claude's opinions. Minimum 30 days, N >= 100 graded picks with Claude confidence ratings.
6. **Cost projection** — estimate actual token usage per pick based on prompt size.

### Key Principle

**Start as pure observation.** Log everything, block nothing. Same pattern we use for new filters — accumulate data, measure correlation, promote if validated. Claude's opinion is just another signal source, treated the same as any other.

### Reference Files

- Pipeline entry: `ml/signals/best_bets_exporter.py` → `signal_best_bets_exporter.py`
- Phase 6 trigger: `orchestration/cloud_functions/phase6_export/main.py`
- Pick schema: `signal_best_bets_picks` BQ table
- Example of post-export step: `post-grading-export` Cloud Function
- Claude API docs: `@anthropic-ai/sdk` or `anthropic` Python SDK
- Skill for Claude API patterns: `/claude-api`

## Key Context for Next Session

- **Algorithm version:** `v451_session451_filters`
- **9 enabled models**, 2 BLOCKED pending auto-disable today
- **Push is pending** — `git push origin main` will auto-deploy all changes
- **Observation check date: March 24** — documented in `docs/08-projects/current/session-451-mar8-filters/00-OVERVIEW.md`
- **Claude review system** is the main new workstream — start with prompt design and manual testing
