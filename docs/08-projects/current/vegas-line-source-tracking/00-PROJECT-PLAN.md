# Vegas Line Source Tracking & Pipeline Validation

**Session:** 152
**Status:** Planning (reviewed by Opus agent)
**Priority:** P1 — Revenue-critical (betting lines drive edge calculations)

## Problem Statement

We have zero tolerance for missing ML features (Session 141) but made an intentional exception for vegas features 25-27 (Session 145) — players without sportsbook lines still get predictions with `has_vegas_line=0`.

**What we can't distinguish today:**
- "Sportsbook doesn't offer a line for this player" (legitimate — bench players)
- "Our scraper failed and we missed lines that DO exist" (pipeline bug — lost edge)

**What we don't track today:**
- Which source (Odds API vs BettingPros) provided each player's line
- Per-run aggregate: how many games/players had lines from each source
- Whether predictions were made with stale or missing line data that later became available

**Impact:** If Odds API is down for a day and BettingPros covers 80% of players, the 20% gap gets `has_vegas_line=0` silently. We lose edge on those predictions without knowing it was a fixable pipeline issue.

## Design

### Layer 1: Per-Player Source Attribution

Track which source(s) provided each player's vegas line at the point of feature extraction.

**Where:** `ml_feature_store_v2.vegas_line_source` (new STRING column, metadata NOT a feature)
**Values:** Defined as constants in code (see Constants section below)
- `'odds_api'` — Line came from Odds API only
- `'bettingpros'` — Line came from BettingPros only
- `'both'` — Both sources had a line (Odds API used via COALESCE priority)
- `'none'` — No line from either source

**Relationship to existing `has_vegas_line`:** The existing `has_vegas_line BOOL` column in `ml_feature_store_v2` tracks "did any source provide a line" (true/false). The new `vegas_line_source` answers "WHICH source." The BOOL column is kept for backward compatibility; downstream consumers can derive it from `vegas_line_source != 'none'`.

**Change:** `feature_extractor.py` `_batch_extract_vegas_lines`

The SQL already does a `FULL OUTER JOIN` between odds_api and bettingpros CTEs. Add source tracking to the `combined` CTE:

```sql
-- In the combined CTE, add:
CASE
    WHEN oa.player_lookup IS NOT NULL AND bp.player_lookup IS NOT NULL THEN 'both'
    WHEN oa.player_lookup IS NOT NULL THEN 'odds_api'
    WHEN bp.player_lookup IS NOT NULL THEN 'bettingpros'
    ELSE 'none'
END as vegas_line_source
```

Store `vegas_line_source` in `_vegas_lines_lookup` dict alongside existing fields.

**CRITICAL implementation detail:** The SQL query ends with `WHERE vegas_points_line IS NOT NULL`, so players with NO line from either source never appear in the query results. The `'none'` value must be set in **Python** in the ML Feature Store Processor (`ml_feature_store_processor.py`) when it finds no entry in `_vegas_lines_lookup` for a player. Specifically around line 1620 where the record dict is assembled — default to `'none'` when `feature_extractor.get_vegas_lines(player_lookup)` returns an empty dict.

### Layer 2: Propagate to Predictions

**Where:** `player_prop_predictions.vegas_line_source` (new STRING column)

**Change:** `worker.py` — the inline dict construction around line 2258-2276 (the quality/provenance fields section) already copies `is_quality_ready`, `quality_alert_level`, etc. Add `vegas_line_source` in the same pattern:

```python
'vegas_line_source': features.get('vegas_line_source'),
```

This gives us per-prediction queryability:
```sql
-- How many predictions today were made without any line?
SELECT vegas_line_source, COUNT(*)
FROM player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE
GROUP BY 1
```

### Layer 3: Per-Run Source Coverage (VIEW first, table later if needed)

**Reviewer recommendation:** Start with a VIEW over `ml_feature_store_v2` rather than a new materialized table. This gives 80% of the value with zero new infrastructure.

**Phase 2a — VIEW (start here):**
```sql
CREATE OR REPLACE VIEW nba_predictions.v_vegas_source_coverage AS
SELECT
    game_date,
    COUNT(*) as total_players,
    COUNTIF(vegas_line_source = 'odds_api') as odds_api_only,
    COUNTIF(vegas_line_source = 'bettingpros') as bettingpros_only,
    COUNTIF(vegas_line_source = 'both') as both_sources,
    COUNTIF(vegas_line_source = 'none') as no_source,
    ROUND(COUNTIF(vegas_line_source != 'none') * 100.0 / COUNT(*), 1) as coverage_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= CURRENT_DATE() - 30
GROUP BY 1
ORDER BY 1 DESC;
```

**Phase 2b — Materialized table (only if per-batch snapshots are needed):**

If we need to track coverage per prediction batch (not just per date), add a lean table:

```sql
CREATE TABLE nba_predictions.prediction_run_source_coverage (
  game_date DATE NOT NULL,
  batch_id STRING NOT NULL,
  prediction_run_mode STRING NOT NULL,
  recorded_at TIMESTAMP NOT NULL,

  -- Game-level
  scheduled_games INT64,
  odds_api_games INT64,
  bettingpros_games INT64,

  -- Player-level (from feature store at run time)
  total_players INT64,
  players_with_odds_api INT64,
  players_with_bettingpros INT64,
  players_with_both_sources INT64,
  players_with_no_line INT64
)
PARTITION BY game_date;
```

Derived fields (`source_status`, `either_source_games`, `missing_all_sources_games`) computed in queries, not stored.

**Who writes this:** The ML Feature Store Processor (Phase 4), NOT the coordinator. Rationale from review: Phase 4 already queries raw betting tables during `_batch_extract_vegas_lines`. The coordinator (Phase 5) has no knowledge of raw scraper tables today and adding that dependency is unnecessary. The coordinator can query the feature store or the VIEW to check coverage before starting predictions.

### Layer 4: Late-Line Detection & Re-Prediction

**The scenario:**
1. ML Feature Store runs at ~midnight, predictions at 2:30 AM — `vegas_line_source='none'` for some players
2. Betting scrapers run at 8 AM, 10 AM, etc. — new lines arrive in raw tables
3. Detection: "Player X has a prediction without vegas data, but raw lines now exist"
4. Re-prediction: refresh feature store, then re-run predictions for the date

**Scraper timing context:**
- Betting line scrapers run every 2 hours, starting 12h before first game (clamped to 8 AM ET)
- For a 7 PM ET game: 8 AM, 10 AM, 12 PM, 2 PM, 4 PM, 6 PM ET
- ML Feature Store runs at ~midnight (uses whatever lines were scraped by then)
- Lines scraped AFTER midnight won't be in the feature store until a refresh

**Detection query:**
```sql
-- Players predicted without lines who NOW have raw lines
SELECT p.player_lookup, p.prediction_id, p.vegas_line_source,
       rl.points_line as now_available_line, rl.source
FROM nba_predictions.player_prop_predictions p
JOIN (
    SELECT DISTINCT player_lookup, 'odds_api' as source,
           FIRST_VALUE(points_line) OVER (PARTITION BY player_lookup ORDER BY snapshot_timestamp DESC) as points_line
    FROM nba_raw.odds_api_player_points_props
    WHERE game_date = @game_date AND points_line > 0
    UNION ALL
    SELECT DISTINCT player_lookup, 'bettingpros' as source,
           FIRST_VALUE(points_line) OVER (PARTITION BY player_lookup ORDER BY created_at DESC) as points_line
    FROM nba_raw.bettingpros_player_points_props
    WHERE game_date = @game_date AND market_type = 'points' AND points_line > 0
) rl ON p.player_lookup = rl.player_lookup
WHERE p.game_date = @game_date
  AND p.is_active = TRUE
  AND p.vegas_line_source = 'none'
```

**Re-prediction flow:**
1. Detection finds players with `vegas_line_source='none'` but lines now in raw tables
2. Trigger ML Feature Store refresh for game_date (Phase 4 reprocess)
3. Then trigger prediction re-run via existing `/start` endpoint

**Re-prediction is date-wide.** The existing `/regenerate-with-supersede` endpoint supersedes ALL predictions for a date and regenerates ALL of them. This is acceptable because:
- Total processing time is ~2 minutes for a full date
- With ~4 potential re-runs per day, that's ~8 minutes of compute — negligible
- Targeted per-player regeneration would require significant coordinator changes for minimal savings

**Timing constraint:** Re-prediction only makes sense BEFORE game time. After tip-off, no point regenerating. Detection should check `game_start_time > CURRENT_TIMESTAMP()`.

**Trigger mechanism:** Start with **Option C (manual)** — validation skill detects and recommends, human triggers. Graduate to **Option B (scraper-triggered)** via Pub/Sub when we're confident in the flow.

## Constants

Define in `shared/ml/feature_contract.py` or a new `shared/constants/vegas_sources.py`:

```python
# Vegas line source values (stored in ml_feature_store_v2 and player_prop_predictions)
VEGAS_SOURCE_ODDS_API = 'odds_api'
VEGAS_SOURCE_BETTINGPROS = 'bettingpros'
VEGAS_SOURCE_BOTH = 'both'
VEGAS_SOURCE_NONE = 'none'
```

## Implementation Phases

### Phase 1: Source Tracking (Next session)

Add `vegas_line_source` to the feature store and predictions.

**Files to modify:**

| File | Change |
|------|--------|
| `shared/ml/feature_contract.py` | Add `VEGAS_SOURCE_*` constants |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Add `vegas_line_source` to SQL combined CTE and `_vegas_lines_lookup` dict |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Thread `vegas_line_source` into BigQuery record (~line 1620); default `'none'` when vegas data empty |
| `schemas/bigquery/predictions/ml_feature_store_v2.sql` | Add `vegas_line_source STRING` column (schema doc) |
| `predictions/worker/worker.py` | Copy `vegas_line_source` from features dict (~line 2258-2276) |
| `schemas/bigquery/predictions/01_player_prop_predictions.sql` | Add `vegas_line_source STRING` column (schema doc) |

**Schema migration (run once):**
```sql
ALTER TABLE nba_predictions.ml_feature_store_v2
ADD COLUMN IF NOT EXISTS vegas_line_source STRING;

ALTER TABLE nba_predictions.player_prop_predictions
ADD COLUMN IF NOT EXISTS vegas_line_source STRING;
```

**Deployment order:** Phase 4 service (`nba-phase4-precompute-processors`) first, then `prediction-worker`. If worker deploys first and reads a feature store record without `vegas_line_source`, it gets `None` and writes NULL — backward compatible, not harmful.

**Validation:**
```sql
SELECT vegas_line_source, COUNT(*)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
GROUP BY 1
```

### Phase 2: Coverage VIEW + Validation Integration

Create the VIEW and update validation skills.

**Files to create/modify:**

| File | Change |
|------|--------|
| `schemas/bigquery/predictions/vegas_source_coverage_view.sql` | New VIEW definition |
| `.claude/skills/validate-daily/SKILL.md` | Add vegas source coverage check using VIEW |
| `.claude/skills/reconcile-yesterday/SKILL.md` | Add vegas reconciliation check |
| `bin/monitoring/check_betting_line_sources.py` | Add `--check-predictions` flag to also check prediction coverage |

### Phase 3: Late-Line Detection & Re-Prediction

Detect and re-predict when lines arrive after initial predictions.

**Files to create/modify:**

| File | Change |
|------|--------|
| `bin/monitoring/check_late_vegas_lines.py` | New detection script |
| `.claude/skills/validate-daily/SKILL.md` | Add late-line detection check (pre-game mode) |
| `.claude/skills/reconcile-yesterday/SKILL.md` | Add "were late-arriving lines handled?" check |

**Future (Phase 3b):** Automate via scraper-completion Pub/Sub trigger.

### Phase 4: Per-Batch Materialized Table (if needed)

Only build `prediction_run_source_coverage` table if the VIEW proves insufficient for per-batch tracking.

## Risks & Edge Cases

1. **`'none'` set in Python, not SQL** — The SQL's `WHERE vegas_points_line IS NOT NULL` filters out no-line players. The processor must default to `'none'` for players not found in `_vegas_lines_lookup`. This is the most important implementation detail.

2. **Team abbreviation mismatches** — Odds API uses `home_team_abbr`, schedule uses `home_team_tricode`, BettingPros uses `player_team`. These match (3-letter codes), validated in Session 152's `check_betting_line_sources.py`.

3. **Odds API snapshot timing** — Multiple snapshots per day. Feature extractor uses latest snapshot (`ORDER BY snapshot_timestamp DESC`). Source tracking reflects what was available at feature extraction time, not what's available later.

4. **Re-prediction race condition** — Feature store refresh while predictions running → some workers get old features. Mitigated by sequential: refresh feature store THEN start predictions.

5. **Date-wide re-prediction cost** — ~2 minutes per full date regeneration. With ~4 runs/day, ~8 minutes total. Acceptable.

6. **Feature 28 (`has_vegas_line`) and `vegas_line_source` consistency** — Both set from the same SQL query at the same time, so they'll always agree within a feature store snapshot.

## Success Criteria

- [ ] Every new prediction has `vegas_line_source` populated (not NULL)
- [ ] VIEW gives per-date source coverage breakdown
- [ ] Validation skills answer: "Were any predictions made without lines that should have had them?"
- [ ] When lines arrive late (before game time), detection flags them for re-prediction
- [ ] No regression in prediction latency

## Review Notes (Opus Agent — Session 152)

Plan was reviewed by an Opus agent with full codebase access. Key changes from review:
- Moved coverage checker from coordinator (Phase 5) to Phase 4 — Phase 4 already queries raw tables
- Replaced materialized table with VIEW as default approach
- Added critical note about `'none'` being set in Python, not SQL
- Documented deployment order (Phase 4 service first, then worker)
- Simplified coverage table schema (deferred to Phase 4 if needed)
- Added constants requirement for source values
- Fixed incorrect `build_prediction_record` function name reference
