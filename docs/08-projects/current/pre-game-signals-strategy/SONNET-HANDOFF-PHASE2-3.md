# Sonnet Handoff: Pre-Game Signals Phase 2 + 3

**Copy everything below this line into a new Sonnet chat:**

---

## Task: Implement Dynamic Subsets and /subset-picks Skill

You are implementing Phases 2 and 3 of the dynamic subset system. Phase 1 (signal infrastructure) is already complete - the `daily_prediction_signals` table exists and is populated.

### Context

The signal infrastructure is live:
- `daily_prediction_signals` table has 165 records (Jan 9 - Feb 1)
- Today's V9 signal: RED (10.6% pct_over, UNDER_HEAVY)
- Historical performance: RED days = 54% HR, GREEN days = 82% HR

Now we need to:
1. Define the dynamic subsets (table + initial data)
2. Create a skill to query picks from these subsets

### Read These Documents First

```bash
cat docs/08-projects/current/pre-game-signals-strategy/DYNAMIC-SUBSET-DESIGN.md
cat docs/08-projects/current/pre-game-signals-strategy/SESSION-70-DESIGN-REVIEW.md
```

### Your Tasks

---

#### Task 1: Create the dynamic_subset_definitions Table

```sql
CREATE TABLE IF NOT EXISTS `nba-props-platform.nba_predictions.dynamic_subset_definitions` (
  -- Identity
  subset_id STRING NOT NULL,
  subset_name STRING NOT NULL,
  subset_description STRING,

  -- Filters
  system_id STRING,
  min_edge FLOAT64,
  min_confidence FLOAT64,

  -- Signal conditions
  signal_condition STRING,  -- 'GREEN', 'GREEN_OR_YELLOW', 'RED', 'ANY'
  pct_over_min FLOAT64,
  pct_over_max FLOAT64,

  -- Ranking
  use_ranking BOOL DEFAULT FALSE,
  top_n INT64,

  -- Metadata
  is_active BOOL DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP(),
  notes STRING
)
OPTIONS (
  description = 'Dynamic subset definitions for pick filtering. Created Session 70.'
);
```

Run via bq query.

---

#### Task 2: Insert Initial Subset Definitions

Insert these 9 subsets:

```sql
INSERT INTO `nba-props-platform.nba_predictions.dynamic_subset_definitions`
(subset_id, subset_name, subset_description, system_id, min_edge, min_confidence, signal_condition, pct_over_min, pct_over_max, use_ranking, top_n, is_active, notes)
VALUES
-- Unranked subsets (signal-based)
('v9_high_edge_balanced', 'V9 High Edge Balanced', 'High-edge picks on balanced signal days', 'catboost_v9', 5.0, NULL, 'GREEN', 25.0, 40.0, FALSE, NULL, TRUE, 'Historical 82% HR'),

('v9_high_edge_any', 'V9 High Edge Any', 'All high-edge picks regardless of signal (control)', 'catboost_v9', 5.0, NULL, 'ANY', NULL, NULL, FALSE, NULL, TRUE, 'Baseline for comparison'),

('v9_high_edge_warning', 'V9 High Edge Warning', 'High-edge picks on RED signal days (shadow tracking)', 'catboost_v9', 5.0, NULL, 'RED', NULL, 25.0, FALSE, NULL, TRUE, 'Historical 54% HR - track only'),

('v9_premium_safe', 'V9 Premium Safe', 'Premium picks on non-RED days', 'catboost_v9', 3.0, 0.92, 'GREEN_OR_YELLOW', NULL, NULL, FALSE, NULL, TRUE, 'High conf + edge, avoid RED'),

-- Ranked subsets (top N by composite score)
('v9_high_edge_top1', 'V9 Best Pick', 'Single best high-edge pick by composite score', 'catboost_v9', 5.0, NULL, 'ANY', NULL, NULL, TRUE, 1, TRUE, 'Lock of the day'),

('v9_high_edge_top3', 'V9 Top 3', 'Top 3 high-edge picks by composite score', 'catboost_v9', 5.0, NULL, 'ANY', NULL, NULL, TRUE, 3, TRUE, 'Ultra-selective'),

('v9_high_edge_top5', 'V9 Top 5', 'Top 5 high-edge picks by composite score', 'catboost_v9', 5.0, NULL, 'ANY', NULL, NULL, TRUE, 5, TRUE, 'Recommended default'),

('v9_high_edge_top10', 'V9 Top 10', 'Top 10 high-edge picks by composite score', 'catboost_v9', 5.0, NULL, 'ANY', NULL, NULL, TRUE, 10, TRUE, 'More volume'),

-- Combined (ranking + signal)
('v9_high_edge_top5_balanced', 'V9 Top 5 Balanced', 'Top 5 picks but only on GREEN signal days', 'catboost_v9', 5.0, NULL, 'GREEN', 25.0, 40.0, TRUE, 5, TRUE, 'Best of both worlds');
```

---

#### Task 3: Verify Subset Definitions

```sql
SELECT subset_id, subset_name, min_edge, signal_condition, use_ranking, top_n
FROM nba_predictions.dynamic_subset_definitions
WHERE is_active = TRUE
ORDER BY subset_id;
```

Expected: 9 active subsets.

---

#### Task 4: Create /subset-picks Skill

Create the skill directory and files:

```bash
mkdir -p .claude/skills/subset-picks
```

Create `.claude/skills/subset-picks/SKILL.md`:

```markdown
# /subset-picks - Query Picks from Dynamic Subsets

## Purpose

Query and display picks from any defined dynamic subset, with signal context and performance history.

## Usage

```
/subset-picks                              # List available subsets
/subset-picks <subset_id>                  # Today's picks from subset
/subset-picks <subset_id> --history 7      # Last 7 days performance
```

## Available Subsets

Query to list subsets:
```sql
SELECT subset_id, subset_name,
  CASE WHEN use_ranking THEN CONCAT('Top ', top_n) ELSE 'All' END as selection,
  signal_condition,
  notes
FROM nba_predictions.dynamic_subset_definitions
WHERE is_active = TRUE
ORDER BY subset_id;
```

## Query: Get Subset Picks for Today

For **unranked** subsets (signal-based filtering):

```sql
WITH daily_signal AS (
  SELECT * FROM nba_predictions.daily_prediction_signals
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
),
subset_def AS (
  SELECT * FROM nba_predictions.dynamic_subset_definitions
  WHERE subset_id = '{SUBSET_ID}'  -- Replace with actual subset_id
)
SELECT
  p.player_lookup,
  ROUND(p.predicted_points, 1) as predicted,
  p.current_points_line as line,
  ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
  p.recommendation,
  ROUND(p.confidence_score, 2) as confidence,
  s.pct_over,
  s.daily_signal,
  CASE
    WHEN d.signal_condition = 'ANY' THEN '✅ INCLUDED'
    WHEN d.signal_condition = 'GREEN' AND s.daily_signal = 'GREEN' THEN '✅ INCLUDED'
    WHEN d.signal_condition = 'GREEN_OR_YELLOW' AND s.daily_signal IN ('GREEN', 'YELLOW') THEN '✅ INCLUDED'
    WHEN d.signal_condition = 'RED' AND s.daily_signal = 'RED' THEN '✅ INCLUDED'
    ELSE '❌ EXCLUDED (signal mismatch)'
  END as status
FROM nba_predictions.player_prop_predictions p
CROSS JOIN daily_signal s
CROSS JOIN subset_def d
WHERE p.game_date = CURRENT_DATE()
  AND p.system_id = d.system_id
  AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
  AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
  AND p.current_points_line IS NOT NULL
ORDER BY ABS(p.predicted_points - p.current_points_line) DESC;
```

For **ranked** subsets (top N by composite score):

```sql
WITH daily_signal AS (
  SELECT * FROM nba_predictions.daily_prediction_signals
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
),
subset_def AS (
  SELECT * FROM nba_predictions.dynamic_subset_definitions
  WHERE subset_id = '{SUBSET_ID}'  -- Replace with actual subset_id
),
ranked_picks AS (
  SELECT
    p.player_lookup,
    ROUND(p.predicted_points, 1) as predicted,
    p.current_points_line as line,
    ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
    p.recommendation,
    ROUND(p.confidence_score, 2) as confidence,
    -- Composite score: edge * 10 + confidence * 0.5
    ROUND((ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5), 1) as composite_score,
    ROW_NUMBER() OVER (
      ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
    ) as pick_rank
  FROM nba_predictions.player_prop_predictions p
  CROSS JOIN subset_def d
  WHERE p.game_date = CURRENT_DATE()
    AND p.system_id = d.system_id
    AND ABS(p.predicted_points - p.current_points_line) >= COALESCE(d.min_edge, 0)
    AND (d.min_confidence IS NULL OR p.confidence_score >= d.min_confidence)
    AND p.current_points_line IS NOT NULL
)
SELECT
  r.*,
  s.pct_over,
  s.daily_signal,
  CASE
    WHEN d.signal_condition = 'ANY' THEN '✅'
    WHEN d.signal_condition = 'GREEN' AND s.daily_signal = 'GREEN' THEN '✅'
    ELSE '⚠️ Signal mismatch'
  END as signal_ok
FROM ranked_picks r
CROSS JOIN daily_signal s
CROSS JOIN subset_def d
WHERE r.pick_rank <= COALESCE(d.top_n, 999)
ORDER BY r.pick_rank;
```

## Query: Subset Historical Performance

```sql
WITH picks_with_results AS (
  SELECT
    p.game_date,
    p.player_lookup,
    ABS(p.predicted_points - p.current_points_line) as edge,
    p.confidence_score,
    p.recommendation,
    (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) as composite_score,
    ROW_NUMBER() OVER (
      PARTITION BY p.game_date
      ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
    ) as daily_rank,
    pgs.points as actual_points,
    p.current_points_line,
    CASE
      WHEN pgs.points = p.current_points_line THEN NULL  -- Push
      WHEN (pgs.points > p.current_points_line AND p.recommendation = 'OVER') OR
           (pgs.points < p.current_points_line AND p.recommendation = 'UNDER')
      THEN 1 ELSE 0
    END as is_correct,
    s.daily_signal
  FROM nba_predictions.player_prop_predictions p
  JOIN nba_analytics.player_game_summary pgs
    ON p.player_lookup = pgs.player_lookup AND p.game_date = pgs.game_date
  LEFT JOIN nba_predictions.daily_prediction_signals s
    ON p.game_date = s.game_date AND p.system_id = s.system_id
  WHERE p.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {DAYS} DAY)  -- Replace {DAYS}
    AND p.game_date < CURRENT_DATE()  -- Exclude today (no results yet)
    AND p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5
    AND p.current_points_line IS NOT NULL
)
SELECT
  '{SUBSET_ID}' as subset,
  COUNT(*) as picks,
  SUM(is_correct) as wins,
  ROUND(100.0 * SUM(is_correct) / NULLIF(COUNT(*), 0), 1) as hit_rate
FROM picks_with_results
WHERE daily_rank <= {TOP_N}  -- For ranked subsets, or remove for unranked
  AND ('{SIGNAL_CONDITION}' = 'ANY' OR daily_signal = '{SIGNAL_CONDITION}');
```

## Output Format

### When listing subsets:

```
## Available Subsets

| Subset ID | Name | Selection | Signal | Notes |
|-----------|------|-----------|--------|-------|
| v9_high_edge_top5 | V9 Top 5 | Top 5 | ANY | Recommended default |
| v9_high_edge_balanced | V9 High Edge Balanced | All | GREEN | Historical 82% HR |
...
```

### When showing picks:

```
## {Subset Name} - {Date}

### Signal Status
| Metric | Value | Status |
|--------|-------|--------|
| pct_over | X% | {GREEN/YELLOW/RED} |
| Signal Match | ✅/❌ | {Included/Excluded reason} |

{If RED signal and subset requires GREEN, show warning:}
⚠️ TODAY'S SIGNAL IS RED
This subset filters for GREEN signal days.
No picks recommended today based on historical 54% HR on RED days.

### Picks (Rank by Composite Score)
| Rank | Player | Line | Predicted | Edge | Direction | Confidence | Score |
|------|--------|------|-----------|------|-----------|------------|-------|
| 1 | Player A | 22.5 | 28.1 | +5.6 | OVER | 0.89 | 100.5 |
...
```

### When showing history:

```
## {Subset Name} - Last {N} Days Performance

| Metric | Value |
|--------|-------|
| Days | X |
| Total Picks | Y |
| Wins | Z |
| Hit Rate | W% |

### Daily Breakdown
| Date | Signal | Picks | Wins | Hit Rate |
|------|--------|-------|------|----------|
...
```

## Important Notes

1. **Composite Score Formula**: `(edge * 10) + (confidence * 0.5)`
   - Edge dominates (1 point edge = 10 score points)
   - Confidence is tiebreaker (20% diff = 10 score points)

2. **Signal Conditions**:
   - `ANY`: Include picks regardless of daily signal
   - `GREEN`: Only on balanced days (pct_over 25-40%)
   - `GREEN_OR_YELLOW`: Exclude RED days only
   - `RED`: Only on warning days (for shadow tracking)

3. **Ranked vs Unranked**:
   - Ranked subsets use `top_n` to limit picks
   - Unranked subsets include all matching picks
```

---

#### Task 5: Create Skill Manifest

Create `.claude/skills/subset-picks/manifest.json`:

```json
{
  "name": "subset-picks",
  "description": "Query picks from dynamic subsets with signal context",
  "version": "1.0.0",
  "created": "2026-02-01",
  "author": "Session 70"
}
```

---

#### Task 6: Test the Skill Queries

Run a test query to verify everything works:

```sql
-- Test: Get v9_high_edge_top5 for today
WITH daily_signal AS (
  SELECT * FROM nba_predictions.daily_prediction_signals
  WHERE game_date = CURRENT_DATE() AND system_id = 'catboost_v9'
),
ranked_picks AS (
  SELECT
    p.player_lookup,
    ROUND(p.predicted_points, 1) as predicted,
    p.current_points_line as line,
    ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
    p.recommendation,
    ROUND(p.confidence_score, 2) as confidence,
    ROUND((ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5), 1) as composite_score,
    ROW_NUMBER() OVER (
      ORDER BY (ABS(p.predicted_points - p.current_points_line) * 10) + (p.confidence_score * 0.5) DESC
    ) as pick_rank
  FROM nba_predictions.player_prop_predictions p
  WHERE p.game_date = CURRENT_DATE()
    AND p.system_id = 'catboost_v9'
    AND ABS(p.predicted_points - p.current_points_line) >= 5
    AND p.current_points_line IS NOT NULL
)
SELECT r.*, s.pct_over, s.daily_signal
FROM ranked_picks r
CROSS JOIN daily_signal s
WHERE r.pick_rank <= 5
ORDER BY r.pick_rank;
```

Should return today's top 5 high-edge V9 picks with signal context.

---

#### Task 7: Commit Changes

```bash
git add .claude/skills/subset-picks/
git status

git commit -m "$(cat <<'EOF'
feat: Add dynamic subset system (Phase 2 + 3)

Phase 2: Dynamic subset definitions
- Created dynamic_subset_definitions table
- Added 9 initial subsets (ranked + signal-based)

Phase 3: /subset-picks skill
- Query picks from any defined subset
- Signal context and warnings
- Historical performance tracking
- Composite score ranking

Subsets include:
- v9_high_edge_top1/3/5/10 (ranked by composite score)
- v9_high_edge_balanced (GREEN signal days only)
- v9_high_edge_any (control group)
- v9_premium_safe (high conf + non-RED days)

Co-Authored-By: Claude Sonnet <noreply@anthropic.com>
EOF
)"
```

---

### Success Criteria

Before finishing, verify:

1. [ ] `dynamic_subset_definitions` table exists with 9 rows
2. [ ] Test query returns today's top 5 picks with signal
3. [ ] `/subset-picks` skill files created (SKILL.md + manifest.json)
4. [ ] Changes committed

---

### Do NOT Do These Things

- Do NOT modify the prediction worker
- Do NOT create Cloud Functions
- Do NOT modify the daily_prediction_signals table (already done)
- Do NOT implement `/subset-performance` skill yet (future phase)

Focus on subset definitions and the /subset-picks skill.

---

**End of Sonnet Handoff Prompt**
