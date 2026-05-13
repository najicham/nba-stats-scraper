# A5 — Closing Line Value (CLV) Tracking — Design Draft

**Status:** DESIGN ONLY (Session 2). Build deferred to Session 3.
**Scope:** New `mlb_raw.pitcher_props_closing` table, dense pre-game scheduler, materializer processor, schema extension on `mlb_predictions.prediction_accuracy`.
**Goal:** Capture true closing line per pitcher × bookmaker so CLV can be computed daily — earlier-warning signal than HR (Lane 18: would have caught May UNDER collapse 10 days early).

## Why this design

Today `oddsa_pitcher_props` has 24 snapshots/day but stops ~5h+ before first pitch (Lane 18 audit, 2026-05-11 sample). `bp_pitcher_props` is upsert-latest only, no history. We have no row that represents "line right before puck-drop." That's the row CLV needs.

Two pieces required:

1. **Capture** — additional scheduler fires that pull `mlb_pitcher_props` at higher cadence in the 90→0 min pre-game window. Existing scraper writes to `oddsa_pitcher_props` time-series, so no new scraper code.
2. **Materialize** — post-game processor copies the last `oddsa_pitcher_props` snapshot per (game_pk, player_lookup, bookmaker) that's within the closing window into a flat `pitcher_props_closing` table. Indexed for join into `prediction_accuracy`.

## Layer A — `mlb_raw.pitcher_props_closing`

```sql
CREATE TABLE `nba-props-platform.mlb_raw.pitcher_props_closing` (
  game_date              DATE      NOT NULL,
  game_pk                INT64     NOT NULL,
  game_start_time        TIMESTAMP NOT NULL,
  player_lookup          STRING    NOT NULL,
  player_name            STRING    NOT NULL,
  team_abbr              STRING,
  opponent_team_abbr     STRING,
  bookmaker              STRING    NOT NULL,
  market_key             STRING    NOT NULL,    -- 'pitcher_strikeouts'
  closing_line           FLOAT64   NOT NULL,
  closing_over_price     INT64,
  closing_under_price    INT64,
  closing_over_implied   FLOAT64,
  closing_under_implied  FLOAT64,
  closing_snapshot_time  TIMESTAMP NOT NULL,
  minutes_before_first_pitch INT64 NOT NULL,    -- <= 30 for "true" closing; tag higher if no fresh snapshot
  is_synthetic           BOOLEAN   NOT NULL,    -- TRUE when we fell back to last available > 30 min pre-game
  source_snapshot_id     STRING,                -- ref back to oddsa_pitcher_props row
  materialized_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY game_date
CLUSTER BY player_lookup, bookmaker;
```

**Why these columns:**
- Partition by `game_date` matches every other raw MLB table. Cluster by `player_lookup, bookmaker` matches the join key used in any signal that compares pick-time vs closing line per book.
- `minutes_before_first_pitch` keeps the freshness audit visible. Lane 18's red flag was "closest snapshot to first pitch = 340 min before" — that's a synthetic closer, not real. The `is_synthetic` flag lets queries filter to truly-closing rows.
- `source_snapshot_id` is forensic: lets us trace which raw row got promoted, useful when book lines spike right before game.

**Grants / IAM:** match `mlb_raw.oddsa_pitcher_props` exactly. Materializer writes via the existing `mlb-phase2-raw-processors` SA. Read access for `mlb-prediction-worker` SA.

## Layer B — `prediction_accuracy` schema extension

Add these columns to `nba-props-platform.mlb_predictions.prediction_accuracy`:

```sql
ALTER TABLE `nba-props-platform.mlb_predictions.prediction_accuracy`
  ADD COLUMN IF NOT EXISTS pick_time_line       NUMERIC,
  ADD COLUMN IF NOT EXISTS closing_line         NUMERIC,
  ADD COLUMN IF NOT EXISTS closing_bookmaker    STRING,
  ADD COLUMN IF NOT EXISTS closing_snapshot_time TIMESTAMP,
  ADD COLUMN IF NOT EXISTS clv_raw              NUMERIC,  -- closing - pick_time (line direction, +/- K)
  ADD COLUMN IF NOT EXISTS clv_directional      NUMERIC,  -- signed by recommendation:
                                                          --   OVER  picks: +CLV when line dropped (good buy)
                                                          --   UNDER picks: +CLV when line rose (good buy)
  ADD COLUMN IF NOT EXISTS clv_quality_flag     STRING;   -- 'true_closing' | 'stale_closing' | 'no_closing'
```

`grading_service` already writes one row per (system_id, pitcher_lookup, recommendation, line_value, game_date). Extend the UPSERT to:

1. Lookup the matching `pitcher_props_closing` row by (game_date, pitcher_lookup) — pick the row whose `bookmaker` matches the pick's `line_bookmaker` if available, else fall back to median across all books.
2. Compute `clv_raw = closing_line - pick_time_line`.
3. Compute `clv_directional = clv_raw * (-1 if recommendation='OVER' else +1)` — because a dropping line is good for OVER buyers (they got a higher number than the market closed at).
4. Tag `clv_quality_flag` based on `pitcher_props_closing.is_synthetic` and `minutes_before_first_pitch`.

## Layer C — Scheduler additions

Existing capture (DO NOT REMOVE):
- `mlb-oddsa-pitcher-props-morning` — fires daily 10:30 UTC (cron `30 10 * * *`). One snapshot. Stays.
- `mlb-props-morning` — BettingPros props. Stays.

New schedulers (proposed — pre-game burst):

```yaml
# deployment/scheduler/mlb/clv-capture-schedulers.yaml (NEW file)
schedulers:
  - name: mlb-oddsa-pitcher-props-burst-afternoon
    schedule: "0,30 17-23 * 3-10 *"   # ET 1:00 PM – 7:30 PM, every 30 min, Mar–Oct
    time_zone: America/New_York
    description: "Pre-game burst capture for CLV — afternoon/early-evening MLB starts"
    target_uri: https://mlb-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape
    body: '{"scraper": "mlb_pitcher_props", "game_date": "TODAY"}'

  - name: mlb-oddsa-pitcher-props-burst-evening
    schedule: "0,30 0-3 * 3-10 *"     # ET 8:00 PM – 11:30 PM (UTC next-day 0–3), every 30 min
    time_zone: UTC
    description: "Pre-game burst capture for CLV — late-evening MLB starts (West Coast)"
    target_uri: https://mlb-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape
    body: '{"scraper": "mlb_pitcher_props", "game_date": "TODAY"}'
```

**Cost note:** 24 fires/day × scraper run cost. Odds API has a quota; verify before enabling that 12+ books × ~30 pitchers per call stays under quota. The existing single fire returns ~360 rows/day; bursting to 24 fires would yield ~8.6K rows/day. Partition pruning + clustering keep query cost flat.

**Alternative (cheaper):** trigger the burst only when at least one MLB game starts in next 90 min, computed from `mlb_reference.mlb_schedule`. Skip burst on off-days. Implementation: one Cloud Scheduler at 5-min cadence that POSTs to a small CF that conditionally invokes the scraper. Defer to Session 3.

## Layer D — Materializer (closing-line picker)

New processor: `data_processors/raw/mlb/pitcher_props_closing_materializer.py`

Trigger: Cloud Scheduler at 09:00 UTC daily (after all games final). Job name: `mlb-pitcher-props-closing-materialize`.

Logic (pseudocode):
```python
# 1. Get yesterday's games
games = bq("SELECT game_pk, game_start_time FROM mlb_reference.mlb_schedule "
           "WHERE game_date = @yesterday")

# 2. For each game, pick best snapshot per (player_lookup, bookmaker)
for game in games:
    # Window: 30 min before first pitch is "true closing"; 31–180 min is "stale"
    rows = bq("""
        WITH ranked AS (
          SELECT *,
            ROW_NUMBER() OVER (
              PARTITION BY player_lookup, bookmaker
              ORDER BY snapshot_time DESC
            ) AS rn
          FROM mlb_raw.oddsa_pitcher_props
          WHERE game_date = @yesterday
            AND market_key = 'pitcher_strikeouts'
            AND snapshot_time <= @game_start_time
            AND snapshot_time >= TIMESTAMP_SUB(@game_start_time, INTERVAL 180 MINUTE)
        )
        SELECT *,
               TIMESTAMP_DIFF(@game_start_time, snapshot_time, MINUTE) AS minutes_before_first_pitch
        FROM ranked WHERE rn = 1
    """, params={...})

    # 3. Insert into pitcher_props_closing
    for row in rows:
        row['is_synthetic'] = row['minutes_before_first_pitch'] > 30
        write_row(row)
```

**Backfill:** one-time SQL job replays the same logic over `oddsa_pitcher_props` for `game_date BETWEEN '2026-03-01' AND CURRENT_DATE() - 1`. Most early rows will land as `is_synthetic=TRUE` because pre-game capture wasn't running — that's expected; flag distinguishes the post-A5 high-quality rows from the pre-A5 stale ones.

## Layer E — Daily summary view (optional, ship in Session 4)

```sql
CREATE OR REPLACE VIEW `nba-props-platform.mlb_predictions.bb_clv_daily` AS
SELECT
  bb.game_date,
  bb.algorithm_version,
  bb.recommendation,
  COUNT(*)                          AS n_picks,
  COUNTIF(pa.clv_quality_flag = 'true_closing') AS n_true_closing,
  AVG(pa.clv_directional)           AS avg_clv,
  STDDEV(pa.clv_directional)        AS clv_stddev,
  -- 14d rolling for auto-demote
  AVG(pa.clv_directional) OVER (
    PARTITION BY bb.algorithm_version, bb.recommendation
    ORDER BY bb.game_date
    ROWS BETWEEN 13 PRECEDING AND CURRENT ROW
  ) AS clv_14d_avg
FROM `nba-props-platform.mlb_predictions.signal_best_bets_picks` bb
LEFT JOIN `nba-props-platform.mlb_predictions.prediction_accuracy` pa
  USING (pitcher_lookup, game_date, system_id, recommendation, line_value)
WHERE bb.game_date >= '2026-03-01'
GROUP BY 1, 2, 3;
```

## Open questions for Session 3 build

1. **Which bookmaker is "the" closing line?** Options: (a) line_bookmaker from the pick row, (b) median across all books, (c) sharp-book preference (Pinnacle/Circa, neither in current feed). Lane 11 (regime-mismatch flags) warns against pretending we have sharp books. **Default decision:** pick's line_bookmaker if present, else median of `bp_pitcher_props` books.
2. **Backfill quality cutoff.** Backfill rows where the closest snapshot is 5h+ pre-game are noise. Either flag-and-keep or drop. **Default:** keep with `is_synthetic=TRUE`, exclude from `clv_14d_avg` via the daily view's filter.
3. **Auto-demote integration.** Lane 18's killer use-case is signals auto-demoting on 14d CLV < -0.15K. That's a SEPARATE project (Session 5+). Don't wire into `mlb_filter_counterfactual_evaluator` yet — let CLV data accumulate 14+ days first.
4. **Odds API quota math.** 24 fires/day × N events × ~12 books. Need a quota check before enabling the burst scheduler. **Default:** Session 3 first task is a 1-day burst on a low-game day to measure cost, then enable full cadence.

## Validation plan (Session 3, post-build)

- **Day 0 (build day):** Schema migration applied. Materializer dry-runs on 2026-05-12 oddsa data. Closing row count > 0 per game.
- **Day 1:** First live burst capture + materialize. Verify `is_synthetic=FALSE` count > 50% of pitchers per day. Spot-check 5 random rows against bookmaker website.
- **Day 14:** `clv_14d_avg` for `book_disagreement` signal should be > 0 (signal claims to identify mis-priced lines). If avg CLV is 0 or negative, signal isn't actually finding closing-line edges — flag for Session 6 Phase C decision.

## Files touched (when built — Session 3)

- New: `schemas/mlb_raw/pitcher_props_closing.json`
- New: `data_processors/raw/mlb/pitcher_props_closing_materializer.py`
- Modified: `schemas/mlb_predictions/prediction_accuracy.json` (4 new columns)
- Modified: `mlb_grading_service/main.py` (CLV computation in UPSERT)
- New: `deployment/scheduler/mlb/clv-capture-schedulers.yaml`
- Modified: `bin/schedulers/setup_mlb_schedulers.sh` (add new scheduler entries)

No model changes. No governance gates. Auto-deploy via Cloud Build push to `main` once landed.
