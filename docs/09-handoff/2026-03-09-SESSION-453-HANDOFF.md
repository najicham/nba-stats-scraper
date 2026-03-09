# Session 453 Handoff — Claude API Pick Review System Exploration

**Date:** 2026-03-09
**Focus:** Explored Claude API as post-pipeline pick reviewer; slate observations killed by data
**Algorithm:** `v452_mar8_game_cap_ft_rsc` (unchanged)

## What Was Done

### 1. Claude API Pick Reviewer — Full Exploration

Built and tested a Claude API pick review system across 3 days of real data. The system reviews best bet picks using Claude Haiku 4.5 for situational context.

**v1 (per-pick review):** Asked Claude to review each pick with confidence 1-5, agree/disagree, risk flags. Result: Claude echoed our signals back to us. On Yabusele (scored 4), Claude said "6.3 edge with 95%+ signal confidence is compelling" — just parroting model internals. Agrees/disagrees split was 2-8 (20% HR) / 1-3 (25% HR) — indistinguishable.

**v2 (adversarial slate review):** Removed all model internals (no edge, no predicted_points, no signals). Added enriched stats (season PPG, last 3 games, line movement, O/U streaks). Asked Claude to identify 3 most vulnerable picks. Results:

| Date | Record | Bottom 3 | Others | Gap |
|------|--------|----------|--------|-----|
| Mar 4 (43%) | 3-4 | 0-3 (0%) | 3-1 (75%) | +75pp |
| Mar 5 (73%) | 8-3 | 3-0 (100%) | 5-3 (62%) | -38pp |
| Mar 8 (21%) | 3-11 | 0-3 (0%) | 3-8 (27%) | +27pp |
| **Aggregate** | **14-18** | **3-6 (33%)** | **11-12 (48%)** | **+15pp** |

### 2. Key Finding: Claude Is a $3.65/year Trend Detector

- 8 of 9 vulnerability flags = `trend_direction_conflict` or `cold_streak_continuation`
- Our pipeline already has 5+ signals detecting the same pattern (mean_reversion_under, over_streak_reversion_under, downtrend_under, etc.)
- On good days (Mar 5), Claude flags the model's smartest contrarian bets as "vulnerable" — net harmful
- Claude can't distinguish "model is smartly contrarian" from "model is stupidly contrarian"
- The +15pp aggregate gap at N=9 has p=0.52 — statistically indistinguishable from random

### 3. Slate Observations — Built Then Killed by Data

Initially implemented 3 Python-native slate observation rules in `pipeline_merger.py`. Then ran historical validation against 47 days of real data — **all 3 observations were useless or harmful:**

| Observation | Historical Finding | Verdict |
|-------------|-------------------|---------|
| `slate_heavy_over_lean` (>80% OVER, N>=5) | Heavy OVER days = **68.8% HR** vs balanced 56.9% | **HARMFUL** — flags best days |
| `slate_same_game_same_dir` (2+ same game, same dir) | 64.7% HR vs mixed 63.2% (1.5pp gap) | **No signal** |
| `slate_game_concentration` (3+ from one game) | 3-pick games = 71.9% HR (best bucket) | **No signal** — cap already handles |

Additional findings from the Plan agent review:
- `slate_observation_tags` were never persisted to BQ — would have been dead code even if useful
- Heavy OVER lean was bimodal (3 days at 80-100% HR, 3 days at 40-60%) — not a reliable indicator
- The existing `MAX_PICKS_PER_GAME=3` cap (Session 452) already handles concentration risk
- Same-game same-direction is inherently limited by team cap (max 2/team)

**All slate observations reverted from `pipeline_merger.py`.** Algorithm version unchanged.

### 4. Claude Reviewer Module (Preserved for Future)

`ml/signals/claude_pick_reviewer.py` — fully functional but NOT deployed. Key design decisions for future work:
- Adversarial framing (identify weakest picks, not review each one)
- No model internals in prompt (independent assessment)
- Numbered picks for reliable matching
- Closed vocabulary risk flags
- Haiku 4.5 ($0.01/day, 15s latency)

### 5. Tests

6 pipeline merger tests pass (slate obs tests removed with the revert).

## Key Files

| File | Status |
|------|--------|
| `ml/signals/pipeline_merger.py` | **Unchanged** — slate obs reverted |
| `ml/signals/claude_pick_reviewer.py` | NEW — Claude API reviewer module (exploration, not deployed) |
| `scripts/test_claude_review.py` | NEW — Test script for Claude reviewer (single day) |
| `scripts/test_claude_review_multiday.py` | NEW — Multi-day test runner with BQ data |

## Uncommitted Changes

- `ml/signals/claude_pick_reviewer.py` (new exploration code)
- `scripts/test_claude_review.py`, `scripts/test_claude_review_multiday.py` (test scripts)
- `docs/09-handoff/2026-03-09-SESSION-453-HANDOFF.md` (this doc)

Pre-existing uncommitted MLB changes from prior sessions also remain.

## Pending / Future Work

### Claude Prompt v3 — Trend-Banned Prompt (Low Priority)

The Plan agent pointed out that the v2 prompt explicitly told Claude "Focus on what the STATS TELL YOU" — directing it to be a trend detector. A v3 prompt that bans trend-based reasoning and restricts to genuinely orthogonal factors (game-script from spread, B2B scheduling, lineup/rotation changes) might produce different signal. Cost: $0.04 to test. But mechanism critique (Claude duplicates existing signals) still applies.

### Late-Breaking News Detection (Future Project, Replaces Option D)

The Plan agent correctly noted that Claude + web search is infeasible in a Cloud Function — Claude API doesn't include web search. The practical alternative:

**4:45 PM ET injury re-check scraper** — compare current injury data to what was used at pick generation time (~4 PM ET). If a player on the slate was scratched after picks locked, trigger a mini re-export. Covers 80% of the "news sentinel" value for 5% of the complexity.

### Other Pending Items (Carried from Session 451-452)
- Observation promotion check: ~March 24 (under_low_rsc, ft_variance, player_under_suppression)
- 2 BLOCKED models: auto-disable should have fired at 16:00 UTC today
- Ultra tier validation: needs 50+ picks to assess

## Key Learnings

1. **Claude API as a pick reviewer is a dead end for per-pick signals** — it detects trends our model already knows about, and can't tell when contrarianism is smart vs stupid.
2. **Slate-level observations looked promising but data says no** — heavy OVER lean days are our BEST days (68.8% HR), same-game same-direction has no HR impact (1.5pp), and game concentration at 3 picks = 71.9% HR.
3. **Always validate with historical data before shipping** — the slate observations "made sense" intuitively but were harmful or useless empirically. The Plan agent caught that they also wouldn't have been persisted to BQ (dead code).
4. **Cost is irrelevant** ($3.65/year) but statistical power is the bottleneck — need 60+ days at 3 vulnerable picks/day to validate any Claude signal.
5. **Adversarial framing >> review framing** for LLMs — forcing Claude to pick "worst 3" produces sharper output than "review each one."
6. **Don't show the model's reasoning to the reviewer** — Claude parrots back whatever signals/edge it sees instead of forming independent opinions.
7. **Prompt design drives capability** — v2's instruction to "focus on stats" made Claude a trend detector. Orthogonal prompting might produce orthogonal signal, but hasn't been tested.
