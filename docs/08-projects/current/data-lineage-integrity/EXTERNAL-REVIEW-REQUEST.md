# External Review Request: Data Validation Architecture

**Date**: 2026-01-26
**Prepared By**: Claude Opus (Implementation Agent)
**Prepared For**: External Reviewer (Claude Web Chat)
**Purpose**: Seek fresh perspectives on data validation strategy

---

## Executive Summary

We operate an NBA player props prediction platform with a multi-phase data pipeline. We've discovered that **81% of this season's game data was backfilled late**, potentially contaminating downstream computed values (rolling averages, ML features, predictions).

We've built a validation system with three skills:
- `/validate-daily` - Daily pipeline health
- `/validate-historical` - Historical data completeness
- `/validate-lineage` - Data correctness (new)

**We're seeking fresh ideas on**:
1. Are we missing any validation approaches?
2. How should we structure ongoing data quality monitoring?
3. What prevention mechanisms would catch issues earlier?
4. Are there better ways to detect cascade contamination?

---

## System Architecture

### Data Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           NBA PROPS PLATFORM                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: Scraping (External APIs → Raw Storage)                            │
│  ─────────────────────────────────────────────────                          │
│  Sources: NBA.com, BallDontLie API, BettingPros, OddsAPI                    │
│  Frequency: Every 15 min during games, hourly otherwise                     │
│  Output: Raw JSON → BigQuery staging tables                                 │
│                                                                              │
│       │                                                                      │
│       ▼                                                                      │
│                                                                              │
│  PHASE 2: Raw Processing (Staging → Normalized Tables)                      │
│  ─────────────────────────────────────────────────────                      │
│  - Deduplicate records                                                       │
│  - Normalize player/team identifiers                                        │
│  - Apply data quality checks                                                │
│  - Output: nba_raw.bdl_player_boxscores, nba_raw.bdl_games, etc.           │
│                                                                              │
│       │                                                                      │
│       ▼                                                                      │
│                                                                              │
│  PHASE 3: Analytics (Raw → Game-Level Summaries)                            │
│  ───────────────────────────────────────────────                            │
│  - Player game summaries (per-game stats)                                   │
│  - Team offense/defense summaries                                           │
│  - Source tracking (which raw records used)                                 │
│  - Output: nba_analytics.player_game_summary, team_*_game_summary           │
│                                                                              │
│       │                                                                      │
│       ▼                                                                      │
│                                                                              │
│  PHASE 4: Precompute (Analytics → Derived Metrics)                          │
│  ─────────────────────────────────────────────────                          │
│  - Rolling averages (last 5, 10, 15, 20 games)                              │
│  - Composite factors (normalized, weighted metrics)                         │
│  - Matchup analysis (player vs opponent defense)                            │
│  - Shot zone analysis                                                        │
│  - Output: nba_precompute.player_composite_factors, etc.                    │
│                                                                              │
│       │                                                                      │
│       ▼                                                                      │
│                                                                              │
│  PHASE 5: Predictions (Precompute → ML Model → Props)                       │
│  ─────────────────────────────────────────────────────                      │
│  - Load features from precompute                                            │
│  - Run ML model inference                                                    │
│  - Generate player prop predictions                                         │
│  - Output: nba_predictions.player_prop_predictions                          │
│                                                                              │
│       │                                                                      │
│       ▼                                                                      │
│                                                                              │
│  PHASE 6: Grading (Predictions + Actuals → Accuracy)                        │
│  ────────────────────────────────────────────────────                       │
│  - Compare predictions to actual results                                    │
│  - Calculate accuracy metrics                                               │
│  - Feed back to model training                                              │
│  - Output: nba_grading.prediction_grades                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Daily Orchestration

The pipeline runs on a schedule via Google Cloud Scheduler + Pub/Sub:

```
┌──────────────────────────────────────────────────────────────────────┐
│                     DAILY ORCHESTRATION                               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  6:00 AM PT │ Phase 1: Scrapers run (get yesterday's final data)     │
│             │                                                         │
│  6:30 AM PT │ Phase 2: Raw processors (normalize yesterday's data)   │
│             │                                                         │
│  7:00 AM PT │ Phase 3: Analytics (compute game summaries)            │
│             │   └── Pub/Sub → triggers Phase 4 when complete         │
│             │                                                         │
│  7:30 AM PT │ Phase 4: Precompute (rolling averages, composites)     │
│             │   └── Pub/Sub → triggers Phase 5 when complete         │
│             │                                                         │
│  8:00 AM PT │ Phase 5: Predictions (for today's games)               │
│             │                                                         │
│  Next Day   │ Phase 6: Grading (compare predictions to actuals)      │
│             │                                                         │
└──────────────────────────────────────────────────────────────────────┘
```

### Key Tables and Their Relationships

```
nba_raw.bdl_player_boxscores (source of truth)
    │
    │ game_date, player_id, game_id
    ▼
nba_analytics.player_game_summary (per-game aggregation)
    │
    │ player_id, game_date, points, rebounds, assists, etc.
    ▼
nba_precompute.player_composite_factors (rolling calculations)
    │
    │ player_id, game_date, points_last_10_avg, composite_score, etc.
    ▼
nba_predictions.player_prop_predictions (model output)
    │
    │ player_id, game_date, prop_type, predicted_value, confidence
    ▼
nba_grading.prediction_grades (accuracy tracking)
```

### Processing Metadata

Every table includes processing metadata:

| Column | Purpose |
|--------|---------|
| `processed_at` | When this record was computed |
| `run_id` | Which processor run created it |
| `source_tables` | What upstream data was used |
| `data_version` | Schema/logic version |

This metadata enables lineage tracking.

---

## The Problem: Cascade Contamination

### What Happened

During the 2025-26 season, many games' data was loaded late:

| Delay Category | Game Dates | % of Season |
|----------------|------------|-------------|
| SEVERE (>7 days late) | 78 | 81% |
| MODERATE (3-7 days) | 8 | 8% |
| MINOR (2-3 days) | 3 | 3% |
| Normal (<2 days) | 7 | 7% |

### The Cascade Effect

When Game A's data is missing:

```
Day 1: Game A played
Day 2: Game A data MISSING (scraper failed)
Day 3: Phase 4 computes "last 10 games avg" for Player X
        └── Uses games 2-11 instead of 1-10 (Game A missing)
        └── Rolling average is WRONG
Day 4: Phase 5 generates prediction using wrong rolling avg
        └── Prediction is WRONG
Day 5: Game A data finally arrives (backfilled)
Day 6: Phase 4 reprocesses... but does it fix the cascade?
```

### The Challenge

1. **Detection**: How do we know which records were computed with missing data?
2. **Scope**: How widespread is the contamination?
3. **Remediation**: What needs to be reprocessed?
4. **Prevention**: How do we stop this from happening again?

---

## Current Validation System

### Skill 1: `/validate-daily`

**Purpose**: Check if today's pipeline ran successfully

**What it checks**:
- Did all phases complete?
- Are there any failed processors?
- Is data fresh (updated recently)?
- Are there any gaps in today's data?

**When to use**: Every morning after pipeline runs

**Sample output**:
```
=== Daily Pipeline Validation ===
Date: 2026-01-26

Phase Status:
  Phase 2 (Raw):       ✅ Complete (14 processors)
  Phase 3 (Analytics): ✅ Complete (8 processors)
  Phase 4 (Precompute): ✅ Complete (6 processors)
  Phase 5 (Predictions): ✅ Complete (247 predictions)

Data Freshness:
  player_game_summary: 2 hours ago ✅
  player_composite_factors: 2 hours ago ✅
  player_prop_predictions: 1 hour ago ✅

Issues Found: 0
```

**Limitations**:
- Only checks if data EXISTS, not if it's CORRECT
- Doesn't detect contamination from past gaps
- Point-in-time view, no historical context

### Skill 2: `/validate-historical`

**Purpose**: Check data completeness over a date range

**What it checks**:
- Are all expected dates present?
- Are all expected players present per date?
- Are there gaps in coverage?
- What's the record count trend?

**Modes**:
- `quick` - Just check date coverage
- `deep-check` - Verify record counts and freshness
- `player <id>` - Check specific player's history
- `game <id>` - Check specific game's data

**When to use**: After backfills, investigating issues

**Sample output**:
```
=== Historical Validation: 2025-10-01 to 2026-01-26 ===

Date Coverage:
  Expected dates: 96
  Present dates: 96
  Missing dates: 0

Record Counts:
  Total player_game_summary records: 28,450
  Average per game date: 296
  Min: 42 (2025-11-06)
  Max: 632 (2025-11-10)

Gaps Detected:
  None

Freshness:
  All records processed within expected window ✅
```

**Limitations**:
- Checks PRESENCE, not CORRECTNESS
- Doesn't know if rolling averages used complete windows
- Can't detect if a record was computed before its dependencies existed

### Skill 3: `/validate-lineage` (NEW)

**Purpose**: Validate that computed data used complete, correct upstream data

**What it checks**:
- Was this record computed AFTER all its dependencies were available?
- Does the stored value match what we'd compute today from current upstream?
- Are there systematic patterns in contamination?

**Approach**: Tiered validation

```
Tier 1: Aggregate Validation
─────────────────────────────
For each date, compare:
  - Stored: AVG(composite_score) for all players
  - Recomputed: AVG(recompute_composite()) for all players
If difference > 1%, flag date for Tier 2

Tier 2: Sample Validation
─────────────────────────
For flagged dates:
  - Pick 50 random player records
  - Recompute each individually
  - Compare to stored value
If >5% differ significantly, flag for reprocessing

Tier 3: Spot Check
──────────────────
For "normal" dates:
  - Pick 100 random records across all dates
  - Verify no systemic issues
```

**When to use**: After backfills, quarterly audits, investigating accuracy issues

**Limitations**:
- Computationally expensive for full validation
- Requires knowing the computation logic to recompute
- May not catch all edge cases

---

## What We're Trying to Achieve

### Immediate Goals

1. **Quantify contamination**: How many records are wrong?
2. **Remediate**: Reprocess affected date ranges
3. **Validate fixes**: Confirm reprocessing worked

### Long-Term Goals

1. **Prevent future contamination**: Catch gaps before downstream processing
2. **Continuous validation**: Ongoing data quality monitoring
3. **Fast detection**: Know within hours if something is wrong
4. **Self-healing**: Automatic reprocessing when issues detected

---

## Open Questions for Review

### 1. Validation Approach

- Are we missing any validation dimensions?
- Is the tiered approach (aggregate → sample → spot) sound?
- What statistical methods would be more rigorous?

### 2. Prevention Mechanisms

Current prevention ideas:
- Pre-processing dependency check (verify upstream complete before computing)
- Processing timestamp audit (flag if processed_at < dependency.loaded_at)
- Window completeness check (for rolling averages, verify all N games existed)

Questions:
- What other prevention mechanisms exist?
- How do data platforms (Airflow, dbt, etc.) handle this?
- Is there a "data contract" pattern we should adopt?

### 3. Detection Timing

Currently we detect contamination retroactively. Ideas for earlier detection:
- Real-time dependency graph validation
- Processing-time assertions
- Anomaly detection on computed values

Questions:
- What's the right balance between detection speed and compute cost?
- Should we validate inline (during processing) or async (batch job)?

### 4. Remediation Strategy

When contamination is found:
- Reprocess from earliest contaminated date forward
- Cascade triggers downstream reprocessing

Questions:
- Is there a smarter remediation strategy?
- How do we handle records that were used for model training?
- Should we version data (keep old and new) for comparison?

### 5. Monitoring and Alerting

What metrics should we track?
- % of records validated per day
- Contamination rate over time
- Time from issue to detection

Questions:
- What dashboards/alerts would be most valuable?
- How do we distinguish "expected" differences from "contamination"?

---

## Specific Scenarios We Want to Handle

### Scenario 1: Late Game Data

```
Timeline:
  Jan 15: Game played
  Jan 15: Scraper fails (API timeout)
  Jan 16: Rolling averages computed (missing Jan 15 game)
  Jan 17: Predictions generated (using wrong rolling avg)
  Jan 18: Jan 15 game data scraped successfully
  Jan 19: ??? What happens now?
```

**Current behavior**: Manual detection, manual reprocessing
**Desired behavior**: Auto-detect, auto-reprocess, alert

### Scenario 2: Partial Game Data

```
Timeline:
  Jan 15: Game played, but only roster data available (no stats)
  Jan 15: player_game_summary created with zeros
  Jan 16: Rolling averages include the zeros (wrong!)
  Jan 17: Full stats become available
  Jan 18: player_game_summary updated with real stats
  Jan 19: Rolling averages still have the zeros baked in
```

**Challenge**: The record EXISTS, but was INCOMPLETE when downstream computed

### Scenario 3: Retroactive Correction

```
Timeline:
  Jan 15: Game played, stats recorded
  Jan 16: Pipeline processes normally
  Jan 20: NBA issues stat correction (player actually had 25 pts, not 23)
  Jan 21: Raw data updated
  Jan 22: ??? Downstream still has old values
```

**Challenge**: Source of truth changed, but downstream doesn't know

### Scenario 4: Schema/Logic Change

```
Timeline:
  Jan 1-15: Composite score computed with formula V1
  Jan 16: We deploy formula V2 (bug fix)
  Jan 17: New records use V2, old records still V1
```

**Challenge**: Mixed versions in the same table

---

## Technical Context

### Infrastructure

- **Cloud**: Google Cloud Platform
- **Compute**: Cloud Run (serverless containers)
- **Orchestration**: Cloud Scheduler + Pub/Sub
- **Storage**: BigQuery (data warehouse)
- **Monitoring**: Cloud Logging, custom dashboards

### Data Volumes

| Table | Records/Day | Total Records |
|-------|-------------|---------------|
| bdl_player_boxscores | ~300 | ~30,000 |
| player_game_summary | ~300 | ~30,000 |
| player_composite_factors | ~300 | ~30,000 |
| player_prop_predictions | ~250 | ~25,000 |

### Processing Times

| Phase | Duration | Frequency |
|-------|----------|-----------|
| Phase 2 | 5-10 min | Daily |
| Phase 3 | 10-15 min | Daily |
| Phase 4 | 15-20 min | Daily |
| Phase 5 | 5 min | Daily |

---

## What We've Built So Far

### Validation Skills

1. **`/validate-daily`**: Pipeline health checks
2. **`/validate-historical`**: Data completeness checks
3. **`/validate-lineage`**: Data correctness checks (new)

### Detection Queries

```sql
-- Find late-loaded data
SELECT game_date,
       TIMESTAMP_DIFF(MIN(processed_at), TIMESTAMP(game_date), HOUR) as hours_late
FROM nba_raw.bdl_player_boxscores
GROUP BY game_date
HAVING hours_late > 48;

-- Find records computed before dependencies
SELECT pf.game_date, pf.player_id, pf.processed_at as computed_at,
       MAX(pgs.processed_at) as dependency_loaded_at
FROM nba_precompute.player_composite_factors pf
JOIN nba_analytics.player_game_summary pgs
  ON pf.player_id = pgs.player_id AND pgs.game_date < pf.game_date
GROUP BY 1, 2, 3
HAVING computed_at < dependency_loaded_at;
```

### Initial Findings

- 78 of 96 game dates (81%) were backfilled >7 days late
- Two major backfill waves: Dec 20, 2025 and Jan 23, 2026
- Unknown how much downstream data is contaminated

---

## Request for Review

We're looking for:

1. **Fresh perspectives**: What are we missing?
2. **Best practices**: How do mature data platforms handle this?
3. **Novel approaches**: Any creative solutions we haven't considered?
4. **Prioritization**: What should we tackle first?
5. **Tool recommendations**: Are there tools/frameworks for this?

Specifically interested in:
- Data observability patterns
- Data contracts / schema enforcement
- Lineage tracking systems
- Anomaly detection for data quality
- Self-healing data pipelines

---

## Appendix: Key Files

| Purpose | Location |
|---------|----------|
| Validate-daily skill | `.claude/skills/validate-daily.md` |
| Validate-historical skill | `.claude/skills/validate-historical.md` |
| Validate-lineage skill | `.claude/skills/validate-lineage.md` |
| Data lineage project | `docs/08-projects/current/data-lineage-integrity/` |
| Pipeline architecture | `docs/03-phases/` |
| Processing code | `data_processors/` |

---

**End of Review Request**

Please provide your analysis, recommendations, and any questions you have about the system.
